"""The wider-pool search tier on the website side: asks the private sci-search service (recourse-sci-pool, sci_search_service.py) for Supreme Court passages and either logs them (shadow) or hands them
to the page (show). Fail-open: any problem, a slow service, a missing setting -- the answer goes out exactly as it does without this module.

    SCI_SEARCH_MODE   off (default) | shadow | show | feed
    SCI_SEARCH_URL    base address of the service, for example http://sci-search.railway.internal:8080
    SCI_SEARCH_TOKEN  the shared secret (header X-Search-Token)
    SCI_SEARCH_TIMEOUT  seconds to wait in show mode (default 6)
    SCI_SHADOW_LOG_QUESTIONS  1 to write the question text into the shadow log (default: only a hash; legal questions are private)
    SCI_SHADOW_LOG_FILE  optional path (a volume) to append the shadow records to; they always go to the application log as lines starting SCI_SHADOW

shadow: the search runs in a background thread AFTER the answer is built; the user sees nothing and waits for nothing. show: the search runs before the answer is returned (up to the timeout) and
result['sci_related_judgments'] holds the passages, each with the register/card note beside it; the website shows them in their own box, labelled not independently verified.
feed (EXPERIMENT, staging only): the passages are also given to the language model, inside the prompt, so that its answer may rely on and name these cases (generate_grounded_response calls feed_block).
Cases on the Overruled Register carry a REGISTER FACT line the model must repeat; the page lists the passages the answer drew on, labelled not independently verified; the three register locks still run on the finished
answer. This goes further than the site's own pilot tier, which only lets a wider-pool case be mentioned descriptively. Use it to see what such answers look like, not as a way to publish them.
Nothing here says a case is good law.
"""
import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)
MODES = ("off", "shadow", "show", "feed")
MAX_SHOWN = 5
EXCERPT = 600


def mode():
    m = (os.environ.get("SCI_SEARCH_MODE") or "off").strip().lower()
    return m if m in MODES else "off"


def search(question, timeout=None, k=10):
    """The service's answer dict, or None on any failure (never raises)."""
    base = (os.environ.get("SCI_SEARCH_URL") or "").rstrip("/")
    if not base or not question:
        return None
    try:
        timeout = float(timeout if timeout is not None else os.environ.get("SCI_SEARCH_TIMEOUT") or 6)
        headers = {"Content-Type": "application/json"}
        if os.environ.get("SCI_SEARCH_TOKEN"):
            headers["X-Search-Token"] = os.environ["SCI_SEARCH_TOKEN"]
        req = urllib.request.Request(base + "/search", data=json.dumps({"question": question, "k": k}).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
        return body if isinstance(body, dict) and body.get("ok") and isinstance(body.get("results"), list) else None
    except urllib.error.HTTPError as exc:
        logger.warning("sci-search answered %s", exc.code)
    except Exception as exc:  # noqa: BLE001 -- fail-open
        logger.warning("sci-search failed: %s", type(exc).__name__)
    return None


def _flags(results):
    try:
        from register_hooks import result_flags
        return result_flags(results)
    except Exception:  # noqa: BLE001
        return [{"source": "none", "note": None} for _ in results]


def shadow_record(question, found, answer_result=None):
    """What the shadow log holds for one question: the passages, the register/card verdict on each, and how many cases in the answer's own sources overlap."""
    results = found["results"]
    flags = _flags(results)
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "q_hash": hashlib.sha256(question.encode("utf-8")).hexdigest()[:16],
           "index_commit": found.get("index_commit"), "seconds": found.get("seconds"),
           "state": (answer_result or {}).get("state"),
           "results": [{"rank": r.get("rank"), "doc": r.get("doc"), "case": r.get("case_name"), "date": r.get("date"), "para": r.get("paragraph"), "name_to_review": r.get("name_to_review"),
                        "flag": f["source"], "note": f["note"]} for r, f in zip(results, flags)]}
    rec["flagged"] = sum(1 for f in flags if f["source"] in ("register", "card"))
    if os.environ.get("SCI_SHADOW_LOG_QUESTIONS") == "1":
        rec["question"] = question
    return rec


def _write_shadow(question, answer_result):
    try:
        found = search(question, timeout=30)
        if not found:
            return
        rec = shadow_record(question, found, answer_result)
        line = json.dumps(rec, ensure_ascii=False)
        print("SCI_SHADOW " + line, flush=True)             # stdout: the application's logger is at WARNING level on Railway, so logger.info would never show
        path = os.environ.get("SCI_SHADOW_LOG_FILE")
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("sci shadow logging failed: %s", type(exc).__name__)


_LOCAL = threading.local()
FEED_MAX_PASSAGES = 6
FEED_PASSAGE_CHARS = 900
FEED_INSTRUCTION = (
    "\n\n## Supreme Court passages from a wider, automatic search -- NOT independently verified\n"
    "The passages below came from an automatic search of a much larger collection of Supreme Court judgments. Nobody at Recourse has read and confirmed them. You may name one of these cases when "
    "it clearly bears on the person's situation, and describe ONLY what its own passage literally says, attributed to the court (\"the Supreme Court in X said ...\"); never state more than the passage "
    "shows, and do not call a passage the whole holding of the case. If a line starting REGISTER FACT is attached to a case, whenever you mention that case say how it was treated in the same sentence, "
    "and never present its holding as the current law. If no passage clearly bears on the person's situation, ignore them all. Do not say that a case is good law.\n"
)


def reset():
    """Forget what was fed to the model for the previous question (called at the start of answer_question)."""
    _LOCAL.question, _LOCAL.block, _LOCAL.cases = None, "", []


def feed_block(question):
    """The prompt section for feed mode ('' in every other mode, and on any failure). The search runs once per question and is reused by the retry loop of generate_grounded_response. Never raises."""
    try:
        if mode() != "feed" or not question:
            return ""
        if getattr(_LOCAL, "question", None) == question:
            return _LOCAL.block
        found = search(question)
        _LOCAL.question, _LOCAL.block, _LOCAL.cases = question, "", []
        if not found:
            return ""
        res = [r for r in found["results"] if r.get("case_name") and not r.get("name_to_review")]
        flags = _flags(res)
        paired = list(zip(res, flags))
        paired = [p for p in paired if p[1]["source"] not in ("register",)] + [p for p in paired if p[1]["source"] == "register"]     # a case the register flags goes last
        chosen = paired[:FEED_MAX_PASSAGES]
        blocks, cases = [], []
        for r, f in chosen:
            year = r["date"][:4] if r.get("date") else None
            head = f"[WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: {r['case_name']}" + (f" ({r['date']})" if r.get("date") else "") + (f", paragraph {r['paragraph']}" if r.get("paragraph") else "") + "]"
            body = (r.get("text") or "")[:FEED_PASSAGE_CHARS]
            facts = ""
            try:
                from register_hooks import prompt_lines_for_match
                cits = r.get("citations") or {}
                one = lambda v: v[0] if isinstance(v, (list, tuple)) and v else (v if isinstance(v, str) else None)
                lines = prompt_lines_for_match({"case_name": r["case_name"], "year": year, "citation": one(cits.get("scr")) or one(cits.get("insc")) or one(cits.get("air"))})
                if lines:
                    facts = "\n[Overruled Register -- not optional: if you mention this case at all, state this fact in the same sentence]\n" + "\n".join(lines)
            except Exception:  # noqa: BLE001
                facts = ""
            blocks.append(head + "\n" + body + facts)
            cases.append({"case_name": r["case_name"], "date": r.get("date"), "paragraph": r.get("paragraph"), "link": r.get("link"), "link_kind": r.get("link_kind"),
                          "excerpt": (r.get("text") or "")[:EXCERPT], "register_note": f["note"] if f["source"] in ("register", "card") else None})
        if not blocks:
            return ""
        _LOCAL.block = FEED_INSTRUCTION + "\n\n".join(blocks) + "\n"
        _LOCAL.cases = cases
        return _LOCAL.block
    except Exception as exc:  # noqa: BLE001
        logger.warning("sci feed block failed: %s", type(exc).__name__)
        return ""


def attach(question, result, background=True):
    """Called at the end of chat_assistant.answer_question. Returns `result` (changed only in show mode, and only by adding 'sci_related_judgments'). Never raises."""
    try:
        m = mode()
        if m == "off" or not isinstance(result, dict) or result.get("state") not in ("single_match", "conflicting_matches"):
            return result
        if m == "shadow":
            t = threading.Thread(target=_write_shadow, args=(question, dict(result)), daemon=True)
            t.start()
            if not background:
                t.join()
            return result
        if m == "feed":
            cases = getattr(_LOCAL, "cases", None) or []
            if cases:
                result["sci_related_judgments"] = cases
                result["sci_fed"] = True
            return result
        found = search(question)
        if not found:
            return result
        res = found["results"][:MAX_SHOWN * 2]
        flags = _flags(res)
        shown, seen = [], set()
        for r, f in zip(res, flags):
            if r.get("name_to_review") or not r.get("case_name") or r["doc"] in seen:
                continue                                        # a judgment with no readable name is not shown to a person
            seen.add(r["doc"])
            txt = (r.get("text") or "")[:EXCERPT]
            shown.append({"case_name": r["case_name"], "date": r.get("date"), "paragraph": r.get("paragraph"), "link": r.get("link"), "link_kind": r.get("link_kind"),
                          "excerpt": txt, "register_note": f["note"] if f["source"] in ("register", "card") else None})
            if len(shown) >= MAX_SHOWN:
                break
        if shown:
            result["sci_related_judgments"] = shown
            result["sci_as_of"] = found.get("as_of")
    except Exception as exc:  # noqa: BLE001 -- fail-open
        logger.warning("sci tier attach failed: %s", type(exc).__name__)
    return result
