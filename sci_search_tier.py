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
import re
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)
MODES = ("off", "shadow", "show", "feed")
MAX_SHOWN = 5
EXCERPT = 600


_ANNOUNCED = []


def _env(name, default=""):
    """An environment value without the quotation marks or spaces that are sometimes typed around it in a hosting dashboard ("feed", 'feed', " feed ")."""
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().strip("\"'").strip()
    return v if v else default


def mode():
    m = _env("SCI_SEARCH_MODE", "off").lower()
    m = m if m in MODES else "off"
    if not _ANNOUNCED:
        _ANNOUNCED.append(m)
        print("SCI_TIER mode=%s url_set=%s token_set=%s" % (m, bool(_env("SCI_SEARCH_URL")), bool(_env("SCI_SEARCH_TOKEN"))), flush=True)       # once per process: shows in the log what the setting really is
    return m


def search(question, timeout=None, k=10):
    """The service's answer dict, or None on any failure (never raises)."""
    base = _env("SCI_SEARCH_URL").rstrip("/")
    if not base or not question:
        return None
    try:
        timeout = float(timeout if timeout is not None else _env("SCI_SEARCH_TIMEOUT", "6"))
        headers = {"Content-Type": "application/json"}
        if _env("SCI_SEARCH_TOKEN"):
            headers["X-Search-Token"] = _env("SCI_SEARCH_TOKEN")
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
    if _env("SCI_SHADOW_LOG_QUESTIONS") == "1":
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
FEED_MAX_CASES = 8
FEED_PASSAGE_CHARS = 900
LABEL = "(from a wider search, not independently verified)"
FEED_INSTRUCTION = (
    "\n\n## Supreme Court passages from a wider, automatic search -- NOT independently verified\n"
    "The passages below came from an automatic search of a much larger collection of Supreme Court judgments. Nobody at Recourse has read and confirmed them. You may name one of these cases when "
    "it clearly bears on the person's situation, and describe ONLY what its own passage literally says, attributed to the court (\"the Supreme Court in X said ...\"). Never state more than the passage "
    "shows, do not call a passage the whole holding of the case, and if a passage is only quoting or repeating an earlier decision, credit the earlier decision when it is named in the passage. "
    "EVERY TIME you name one of these cases, put the words " + LABEL + " right after its name. "
    "If a line starting REGISTER FACT is attached to a case, whenever you mention that case say how it was treated in the same sentence, and never present its holding as the current law; "
    "the case that corrected it is among the passages when it could be found, so name that case too. "
    "If no passage clearly bears on the person's situation, ignore them all. Do not say that a case is good law.\n"
)
_TRAIL_PARTY = re.compile(r"(?:[,.\s]+(?:&|and)\s+(?:anr|ors|another|others)\b\.?|[,.\s]+(?:anr|ors|another|others|etc)\b\.?)+\s*$", re.I)


def reset():
    """Forget what was fed to the model for the previous question (called at the start of answer_question)."""
    _LOCAL.question, _LOCAL.block, _LOCAL.cases = None, "", []


def _cut(text, n):
    """text shortened to about n characters at the end of a sentence (or clause, or word), with an ellipsis; whole when it is short."""
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    if len(text) <= n:
        return text
    head = text[:n]
    for pat in (r".*[.?!][\"')\]]?\s", r".*[;:]\s", r".*\s"):
        m = re.match(pat, head, re.S)
        if m and len(m.group(0)) > n * 0.5:
            return m.group(0).rstrip() + " ..."
    return head.rstrip() + " ..."


def _party_core(p):
    return _TRAIL_PARTY.sub("", (p or "").strip()).strip(" .,;")


def _parties(name):
    parts = re.split(r"\s+(?:v\.?|vs\.?|versus)\s+", name or "", maxsplit=1, flags=re.I)
    return (_party_core(parts[0]), _party_core(parts[1])) if len(parts) == 2 else (_party_core(name), "")


def _same_case(a, b):
    try:
        from overruled_register import register as R
        return R.party_sigs(a) == R.party_sigs(b) and bool(R.party_sigs(a)[0])
    except Exception:  # noqa: BLE001
        return (a or "").lower().strip(" .") == (b or "").lower().strip(" .")


_GENERIC_FIRST = re.compile(r"^(?:the\s+)?(?:state|union|commissioner|collector|central|govt|government)\b", re.I)


def _fuzzy_end(text, phrase, threshold=0.86):
    """End position of the stretch of `text` that looks like `phrase` (same number of words, allowing a typo), or None."""
    import difflib
    words = list(re.finditer(r"\S+", text))
    n = len(phrase.split())
    if n == 0 or len(words) < n:
        return None
    for i in range(len(words) - n + 1):
        cand = text[words[i].start():words[i + n - 1].end()].strip(" ,.;:()")
        if difflib.SequenceMatcher(None, cand.lower(), phrase.lower()).ratio() >= threshold:
            return words[i + n - 1].end()
    return None


def _labelled_here(text, pos):
    """True when a bracketed 'not independently verified' note comes right at `pos` (the model's own wording is tolerated). Only the very next bracket counts: a label after a LATER case must not hide this one."""
    return bool(re.match(r"\s*\([^)]{0,90}not independently verified[^)]{0,20}\)", text[pos:], re.I))


def label_fed_cases(text, cases):
    """Puts LABEL right after the first mention of each wider-search case in a finished answer, unless the answer already says so there. The case is found by its full name, else by a distinctive
    party name, allowing a typo. Returns the text unchanged on any problem."""
    try:
        out = text or ""
        for c in cases or []:
            p1, p2 = _parties(c["case_name"])
            end = None
            if p1 and p2:
                m = re.search(re.escape(p1) + r"\s+(?:v\.?|vs\.?|versus)\s+" + re.escape(p2), out, re.I)
                end = m.end() if m else None
            if end is None and p1 and len(p1) >= 8 and not _GENERIC_FIRST.match(p1):
                m = re.search(r"\b" + re.escape(p1) + r"\b", out, re.I)
                end = m.end() if m else _fuzzy_end(out, p1)
            if end is None and p2 and len(p2) >= 8:
                end = _fuzzy_end(out, p2)
            if end is None and p1 and p2:
                end = _fuzzy_end(out, p1 + " v. " + p2, 0.9)
            if end is None:
                continue
            if p2:                                                           # a match on the first party alone: take the " v. second party" that follows it too
                m3 = re.match(r"\s+(?:v\.?|vs\.?|versus)\s+" + r"\S+\s*" * len(p2.split()), out[end:], re.I)
                if m3:
                    end += len(m3.group(0).rstrip())
            m0 = re.match(r"[*_]{1,2}", out[end:])                        # the name is in italics (answer style v3): put the label after the closing mark, not inside it
            if m0:
                end += m0.end()
            if _labelled_here(out, end):
                continue
            m2 = re.match(r"\s*[\(\[][^)\]]{0,40}[\)\]]", out[end:])        # a short year or citation in brackets right after the name
            if m2:
                end += m2.end()
                if _labelled_here(out, end):
                    continue
            out = out[:end] + " " + LABEL + out[end:]
        return out
    except Exception:  # noqa: BLE001
        return text


def _fetch_case(name, question):
    """A passage of one named case (the case that corrected a flagged one), by a second search: its name plus the question. (result, flag) or None."""
    found = search((name + " " + question)[:400], timeout=15.0)
    if not found:
        return None
    for r in found["results"]:
        if r.get("case_name") and not r.get("name_to_review") and _same_case(r["case_name"], name):
            return r, _flags([r])[0]
    return None


def feed_block(question):
    """The prompt section for feed mode ('' in every other mode, and on any failure). One passage per case, up to FEED_MAX_CASES cases; a case the register flags goes last and the case that overruled it
    is added (taken from the results, or fetched by a second search), so the model can name the controlling case. The search runs once per question and is reused by the retry loop. Never raises."""
    try:
        if mode() != "feed" or not question:
            return ""
        if getattr(_LOCAL, "question", None) == question:
            return _LOCAL.block
        found = search(question, timeout=max(float(_env("SCI_SEARCH_TIMEOUT", "6")), 15.0))
        _LOCAL.question, _LOCAL.block, _LOCAL.cases = question, "", []
        if not found:
            print("SCI_FEED no passages: the search service gave no answer (down, slow, wrong address or token)", flush=True)
            return ""
        res = [r for r in found["results"] if r.get("case_name") and not r.get("name_to_review")]
        flags = _flags(res)
        by_doc = {}
        for r, f in zip(res, flags):
            by_doc.setdefault(r["doc"], (r, f))                       # the best-ranked passage of each judgment
        pairs = list(by_doc.values())
        flagged = [p for p in pairs if p[1]["source"] == "register"]
        correcting = []
        for r, f in flagged:
            name = f.get("overruling")
            if not name:
                continue
            hit = next((p for p in pairs if _same_case(p[0]["case_name"], name)), None) or _fetch_case(name, question)
            if hit and all(hit[0]["doc"] != c[0]["doc"] for c in correcting):
                correcting.append(hit)
        special = {p[0]["doc"] for p in flagged} | {p[0]["doc"] for p in correcting}
        plain = [p for p in pairs if p[0]["doc"] not in special]
        room = max(FEED_MAX_CASES - len(flagged) - len(correcting), 2)
        chosen = plain[:room] + correcting + flagged
        blocks, cases = [], []
        for r, f in chosen:
            year = r["date"][:4] if r.get("date") else None
            head = f"[WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: {r['case_name']}" + (f" ({r['date']})" if r.get("date") else "") + (f", paragraph {r['paragraph']}" if r.get("paragraph") else "") + "]"
            body = _cut(r.get("text") or "", FEED_PASSAGE_CHARS)
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
                          "excerpt": _cut(r.get("text") or "", EXCERPT), "register_note": f["note"] if f["source"] in ("register", "card") else None})
        if not blocks:
            print("SCI_FEED no passages: nothing usable came back", flush=True)
            return ""
        print("SCI_FEED fed %d case(s): %s" % (len(cases), "; ".join(c["case_name"] for c in cases)), flush=True)
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
                result["response_text"] = label_fed_cases(result.get("response_text") or "", cases)      # every wider-search case named in the answer is tagged as unverified, whatever the model wrote
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
            txt = _cut(r.get("text") or "", EXCERPT)
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
