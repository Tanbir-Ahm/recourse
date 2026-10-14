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


def search(question, timeout=None, k=10, label="sci_search"):
    """The service's answer dict, or None on any failure (never raises). The service's per-search token usage goes to the cost log under `label`."""
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
        if isinstance(body, dict) and body.get("ok") and isinstance(body.get("results"), list):
            try:
                import cost_log
                cost_log.note_search_usage(label, body.get("usage"))
            except Exception:  # noqa: BLE001
                pass
            return body
        return None
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
        found = search(question, timeout=30, label="sci_search_shadow")
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
    "A REGISTER FACT line placed under a passage that only NAMES another case is about that other case: if you rely on that passage, do not present the named case's rule as current law, and say how it was treated. "
    "Credit a principle to the case whose own words state it: if a passage quotes or restates an earlier decision, say it was an earlier decision's holding, never the named case's. "
    "Use a passage only for the question it actually decides: a passage about delay in starting a prosecution does not answer a question about delay in a trial that is already running, and a passage about one kind of bail condition says nothing about another. "
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


_NUMBER_MARK = re.compile(r"\s*\((?:I{1,3}|IV|V|[1-9])\)\s*$")


def _party_core(p):
    return _NUMBER_MARK.sub("", _TRAIL_PARTY.sub("", (p or "").strip())).strip(" .,;")      # 'Hussainara Khatoon (I)' is written 'Hussainara Khatoon' as often as not


def _parties(name):
    parts = re.split(r"\s+(?:v\.?|vs\.?|versus)\s+", name or "", maxsplit=1, flags=re.I)
    return (_party_core(parts[0]), _party_core(parts[1])) if len(parts) == 2 else (_party_core(name), "")


def _same_case(a, b):
    try:
        from overruled_register import register as R
        return R.party_sigs(a) == R.party_sigs(b) and bool(R.party_sigs(a)[0])
    except Exception:  # noqa: BLE001
        return (a or "").lower().strip(" .") == (b or "").lower().strip(" .")


def _same_case_loose(a, b):
    """The same case allowing a shortened or lengthened party name ('P. Ramachandra Rao, etc. Etc.Appellants v. State of Karnataka Respondent'): the first three words of the first party and the first
    two of the second agree (the register's own rule for two spellings of one name)."""
    try:
        from overruled_register import register as R
        return bool(R.Register._names_agree(a, b))                          # noqa: SLF001
    except Exception:  # noqa: BLE001
        return _same_case(a, b)


def _anchor_case_names(question):
    """Cases whose verbatim excerpts (excerpt_anchors.py, ANCHORS=on) go into the prompt for this question: the wider search does not hand the same case over a second time."""
    try:
        import excerpt_anchors
        return [a["case_name"] for a in excerpt_anchors.selected(question)]
    except Exception:  # noqa: BLE001
        return []


_GENERIC_FIRST = re.compile(r"^(?:the\s+)?(?:state|union|commissioner|collector|central|govt|government)\b", re.I)


def _fuzzy_span(text, phrase, threshold=0.86):
    """(start, end) of the stretch of `text` that looks like `phrase` (same number of words, allowing a typo), or None."""
    import difflib
    words = list(re.finditer(r"\S+", text))
    n = len(phrase.split())
    if n == 0 or len(words) < n:
        return None
    for i in range(len(words) - n + 1):
        cand = text[words[i].start():words[i + n - 1].end()].strip(" ,.;:()")
        if difflib.SequenceMatcher(None, cand.lower(), phrase.lower()).ratio() >= threshold:
            return words[i].start(), words[i + n - 1].end()
    return None


def _fuzzy_end(text, phrase, threshold=0.86):
    """End position of the stretch of `text` that looks like `phrase`, or None."""
    sp = _fuzzy_span(text, phrase, threshold)
    return sp[1] if sp else None


_V = r"\s+(?:v\.?|vs\.?|versus)\s+"
_MARK = r"(?:\s*\((?:I{1,3}|IV|V|[1-9])\))?"                          # '(I)' after a first party: Hussainara Khatoon (I) v. Home Secretary
_EXTRA = r"(?:\s*(?:,|&|and)\s*(?:anr|ors|another|others|etc)\b\.?)?"
_LABEL_NOTE = re.compile(r"\(\s*(?:[\w ]{0,12}from a |[\w ]{0,12})?wider search,?\s*not independently verified|\([^()]{0,90}not independently verified", re.I)
_LABEL_SPAN = re.compile(r"\([^()]{0,160}not independently verified[^()]{0,200}(?:\([^()]{0,80}\)[^()]{0,40})?\)", re.I)


def _labelled_here(text, pos, note_re=None):
    """True when a bracketed 'not independently verified' note comes right at `pos` (the model's own wording is tolerated, and a longer note such as '..., not independently verified; overruled by X' counts). Only the very next bracket counts: a label after a LATER case must not hide this one."""
    return bool((note_re or _LABEL_NOTE).match(text[pos:].lstrip(" \t")))


def _inside_label(text, pos, span_re=None):
    """True when `pos` falls inside a label that is already in the text (inserting there would nest one label in another)."""
    return any(m.start() < pos < m.end() for m in (span_re or _LABEL_SPAN).finditer(text))


def _words_re(p):
    return r"\s+".join(re.escape(t) for t in p.split())


_NAME_TOKEN = re.compile(r"\s+(?:[A-Z][\w'\u2019-]*(?:\.(?=[A-Z]))*|of|and|the|for|&)(?=[\s,;:)*_.]|$)")


def _extend_second_party(text, end):
    """When only the first party was found: take the ' v. <second party>' that follows it, as a run of capitalised name words (stops at a bracket, a digit, a full stop or a lower-case word)."""
    m = re.match(_MARK + _V + r"(?:the\s+)?", text[end:], re.I)
    if not m:
        return end
    pos, n = end + m.end(), 0
    first = re.match(r"[A-Z][\w'\u2019-]*(?:\.(?=[A-Z]))*", text[pos:])
    if not first:
        return end
    pos += first.end()
    while n < 7:
        t = _NAME_TOKEN.match(text, pos)
        if not t:
            break
        pos, n = t.end(), n + 1
    return end + len(re.sub(r"(?:\s+(?:of|and|the|for|&))+$", "", text[end:pos], flags=re.I))   # never end on a connecting word


def _tidy_labels(text):
    """Collapses labels the model and the code both put in: one inside another, or two in a row."""
    lab = re.escape(LABEL)
    for _ in range(3):
        text = re.sub(r"\(from\s+" + lab + r"\s+a wider search, not independently verified\)", LABEL, text)
        text = re.sub(r"(" + lab + r")(?:[ \t]*([.,;]?)[ \t]*" + lab + r")+", r"\1\2", text)
    return text


def _locate(text, case_name):
    """(start, end) of the first mention in `text` of a wider-search case: found by its full name, else by a distinctive party name (allowing a typo, and a dropped 'Dr.'), taking the ' v. second party'
    and a trailing '& Another' with it. The end is the end of the name, before italics marks and brackets. None when the case is not mentioned."""
    p1, p2 = _parties(case_name)
    span = None
    if p1 and p2:
        m = re.search(r"\b(?:the\s+)?" + _words_re(p1) + _MARK + _V + r"(?:the\s+)?" + _words_re(p2) + _EXTRA, text, re.I)
        span = (m.start(), m.end()) if m else None
    if span is None:
        p1 = re.sub(r"^(?:dr|mr|mrs|ms|shri|smt)\.?\s+", "", p1, flags=re.I)             # the answer may drop 'Dr.' from the name
    if span is None and p1 and len(p1) >= 8 and not _GENERIC_FIRST.match(p1):
        m = re.search(r"\b" + _words_re(p1) + r"\b", text, re.I)
        sp = (m.start(), m.end()) if m else _fuzzy_span(text, p1)
        if sp is not None:
            end = sp[1]
            tail_v = re.search(r"\s+(?:v\.?|vs\.?|versus)$", text[sp[0]:sp[1]], re.I)           # the fuzzy window may have taken the 'v.' too: back off before it
            if tail_v:
                end = sp[0] + tail_v.start()
            if p2:
                end = _extend_second_party(text, end)
                m = re.match(_EXTRA, text[end:], re.I)
                end += m.end() if m else 0
            span = (sp[0], end)
    if span is None and p2 and len(p2) >= 8:
        span = _fuzzy_span(text, p2)
    if span is None and p1 and p2:
        span = _fuzzy_span(text, p1 + " v. " + p2, 0.9)
    if span is not None and text[span[1]:span[1] + 1] == "." and re.search(r"(?:\b[A-Za-z]\.){1,}[A-Za-z]$", text[:span[1]]):
        span = (span[0], span[1] + 1)                                    # 'State of M.P.': the closing full stop of the initials belongs to the name (the party names are stored without it)
    return span


def _name_end(out, end, note_re):
    """Where a label belongs for a name that ends at `end`: after the italics mark, then after a short year or citation in brackets, or a report citation ', (2002) 4 SCC 578', that follows the name."""
    m0 = re.match(r"[*_]{1,2}", out[end:])                        # the name is in italics (answer style v3): put the label after the closing mark, not inside it
    if m0:
        end += m0.end()
    for _ in range(3):
        if _labelled_here(out, end, note_re):
            break
        m2 = re.match(r"\s*[\(\[][^)\]]{0,40}[\)\]]", out[end:]) or _REPORT_CITE.match(out[end:])
        if not m2 or note_re.match(out[end:].lstrip()):
            break
        end += m2.end()
    return end


def only_at_first_mentions(text, cases, label, note_re):
    """The text with `label` kept only where it follows the first mention of one of `cases` (the model sometimes also writes it after 'a seven-judge Bench' or a later mention): any other copy is removed."""
    try:
        out = text or ""
        keep = set()
        for c in cases or []:
            span = _locate(out, c["case_name"])
            if span is None:
                continue
            end = _name_end(out, span[1], note_re)
            m = re.compile(r"\s*" + re.escape(label)).match(out[end:])
            if m:
                keep.add(end + m.end() - len(label))
        for m in sorted(re.finditer(re.escape(label), out), key=lambda m: -m.start()):
            if m.start() not in keep:
                a = m.start()
                while a > 0 and out[a - 1] == " ":
                    a -= 1
                out = out[:a] + out[m.end():]
        return out
    except Exception:  # noqa: BLE001
        return text


_REPORT_CITE = re.compile(r"\s*,?\s*(?:\(?(?:19|20)\d\d\)?\s+(?:\d{1,2}\s+)?(?:SCC|S\.C\.C\.|SCR|S\.C\.R\.|INSC)\b(?:\s*\([A-Za-z0-9.\-]+\))?\s*\d+"
                          r"|(?:\d{1,2}\s+)?(?:SCC|S\.C\.C\.|SCR|S\.C\.R\.)\b(?:\s*\([A-Za-z0-9.\-]+\))?\s*\d+"
                          r"|AIR\s+(?:19|20)\d\d\s+(?:SC|[A-Za-z]{2,5})\s+\d+)")


def label_cases(text, cases, label, note_re, span_re, tidy=None):
    """Puts `label` right after the first mention of each case in a finished answer, unless the answer already says so there (`note_re` recognises the model's own wording of the label, `span_re` a label
    that is already in the text). The case is found by its full name, else by a distinctive party name, allowing a typo. The label goes after the whole name (including '& Another', italics marks and a
    year in brackets), never inside a name or inside another label. Returns the text unchanged on any problem."""
    try:
        out = text or ""
        seen = set()
        for c in cases or []:
            key = re.sub(r"\W+", " ", (c.get("case_name") or "").lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            span = _locate(out, c["case_name"])
            if span is None:
                continue
            end = _name_end(out, span[1], note_re)
            if _labelled_here(out, end, note_re) or _inside_label(out, end, span_re):
                continue
            out = out[:end] + " " + label + out[end:]
        return tidy(out) if tidy else out
    except Exception:  # noqa: BLE001
        return text


def label_fed_cases(text, cases):
    """The wider-search label (LABEL) after the first mention of each wider-search case in a finished answer."""
    return label_cases(text, cases, LABEL, _LABEL_NOTE, _LABEL_SPAN, _tidy_labels)


def fed_case_names():
    """The names of the wider-search cases handed to the model for THIS question (feed mode); [] otherwise."""
    try:
        return [c["case_name"] for c in getattr(_LOCAL, "cases", None) or [] if c.get("case_name")]
    except Exception:  # noqa: BLE001
        return []


def fed_names_in(text, extra=None):
    """The wider-search cases of THIS question that a finished answer mentions (plus `extra`: more case dicts, the site's pilot cases in feed mode): the name as the search service has it, the stretch of
    the answer that located it, and every 'X v. Y' the answer's case-name finder (the one behind the 'not checked' sentence) reads at that place. Used so that the sentence does not list them: they
    carry the wider-search label instead. [] outside feed mode and on any problem."""
    try:
        text = text or ""
        out, mentions = [], None
        for c in list(getattr(_LOCAL, "cases", None) or []) + [e for e in (extra or []) if isinstance(e, dict)]:
            if not c.get("case_name"):
                continue
            out.append(c["case_name"])
            span = _locate(text, c["case_name"])
            if not span:
                continue
            out.append(text[span[0]:span[1]])
            if mentions is None:
                try:
                    from overruled_register.overlay import case_mentions
                    mentions = case_mentions(text)
                except Exception:  # noqa: BLE001
                    mentions = []
            out.extend(m["name"] for m in mentions if m["start"] < span[1] and m["end"] > span[0])
        return out
    except Exception:  # noqa: BLE001
        return []


def _fetch_case(name, question):
    """A passage of one named case (the case that corrected a flagged one), by a second search: its name plus the question. (result, flag) or None."""
    found = search((name + " " + question)[:400], timeout=15.0, label="sci_search_second")
    if not found:
        return None
    for r in found["results"]:
        if r.get("case_name") and not r.get("name_to_review") and _same_case(r["case_name"], name):
            return r, _flags([r])[0]
    return None


MAX_NAMED_FETCHES = 2        # second searches per question for a controlling case that a passage points to (a flagged case's own corrector is fetched without this cap)
NAMED_NOTE = "\n[Overruled Register -- not optional: this passage names a case on our register; if you mention that case at all, state this fact in the same sentence]\n"


def _named_register(text):
    """The register cases a fed passage names (register_hooks.text_mentions): {'lines', 'clauses', 'overruling'}; empty when none or on any problem."""
    try:
        from register_hooks import text_mentions
        return text_mentions(text)
    except Exception:  # noqa: BLE001
        return {"lines": [], "clauses": [], "overruling": []}


def feed_block(question):
    """The prompt section for feed mode ('' in every other mode, and on any failure). One passage per case, up to FEED_MAX_CASES cases; a case the register flags goes last and the case that overruled it
    is added (taken from the results, or fetched by a second search), so the model can name the controlling case. The same is done for a case the register lists that a passage merely NAMES (a later
    judgment that quotes or discusses it): the passage carries the REGISTER FACT line and the case that corrected it is added. The search runs once per question and is reused by the retry loop.
    Never raises."""
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
        anchor_names = _anchor_case_names(question)
        by_doc = {}
        for r, f in zip(res, flags):
            if any(_same_case_loose(r["case_name"], n) for n in anchor_names):
                continue                                              # its verbatim excerpt is already in the prompt
            by_doc.setdefault(r["doc"], (r, f))                       # the best-ranked passage of each judgment
        pairs = list(by_doc.values())
        flagged = [p for p in pairs if p[1]["source"] == "register"]
        correcting = []

        def _known(name):
            return (any(_same_case(c[0]["case_name"], name) for c in correcting) or any(_same_case(p[0]["case_name"], name) for p in pairs)
                    or any(_same_case_loose(n, name) for n in anchor_names))

        def _controlling(name):
            """The passage of the case that corrected another one: already chosen, else among the results, else by a second search. Added to `correcting` once. A case whose verbatim excerpt is
            in the prompt (an anchor) needs none."""
            if any(_same_case_loose(n, name) for n in anchor_names):
                return None
            hit = next((c for c in correcting if _same_case(c[0]["case_name"], name)), None)
            if hit:
                return hit
            hit = next((p for p in pairs if _same_case(p[0]["case_name"], name)), None) or _fetch_case(name, question)
            if hit and all(hit[0]["doc"] != c[0]["doc"] for c in correcting) and all(hit[0]["doc"] != p[0]["doc"] for p in flagged):
                correcting.append(hit)
            return hit

        for r, f in flagged:
            if f.get("overruling"):
                _controlling(f["overruling"])

        def _split():
            special = {p[0]["doc"] for p in flagged} | {p[0]["doc"] for p in correcting}
            return [p for p in pairs if p[0]["doc"] not in special], max(FEED_MAX_CASES - len(flagged) - len(correcting), 2)

        plain, room = _split()
        named, n_fetch, tried = {}, 0, set()                          # doc -> the register cases its passage names; names already looked up by a second search
        for r, f in plain[:room]:
            men = _named_register(_cut(r.get("text") or "", FEED_PASSAGE_CHARS))
            if not men["lines"]:
                continue
            named[r["doc"]] = men
            for name, _yr in men["overruling"]:
                if not _known(name):                                  # a second search is needed: at most MAX_NAMED_FETCHES of them per question, and never twice for the same name
                    key = re.sub(r"\W+", " ", name.lower()).strip()
                    if n_fetch >= MAX_NAMED_FETCHES or key in tried:
                        continue
                    tried.add(key)
                    n_fetch += 1
                _controlling(name)
        plain, room = _split()
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
            men = named.get(r["doc"]) if f["source"] != "register" else None
            if men:                                                    # the passage names a case on the register: the fact rides with the passage
                facts += NAMED_NOTE + "\n".join(men["lines"])
            blocks.append(head + "\n" + body + facts)
            cases.append({"case_name": r["case_name"], "date": r.get("date"), "paragraph": r.get("paragraph"), "link": r.get("link"), "link_kind": r.get("link_kind"),
                          "excerpt": _cut(r.get("text") or "", EXCERPT), "register_note": f["note"] if f["source"] in ("register", "card") else None,
                          "names_register_note": (" ".join(men["clauses"]) if men else None)})
        if not blocks:
            print("SCI_FEED no passages: nothing usable came back", flush=True)
            return ""
        print("SCI_FEED fed %d case(s): %s" % (len(cases), "; ".join(c["case_name"] for c in cases)), flush=True)
        if named:
            print("SCI_FEED passages naming register cases: %s" % "; ".join(c["case_name"] for c, (r, _f) in zip(cases, chosen) if r["doc"] in named), flush=True)
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
            pilot = [{"case_name": j["case_name"]} for j in (result.get("unverified_related_judgments") or []) if isinstance(j, dict) and j.get("case_name")]       # the site's pilot cases are cited like the rest
            if cases:
                result["sci_related_judgments"] = cases
                result["sci_fed"] = True
            if cases or pilot:
                result["response_text"] = label_fed_cases(result.get("response_text") or "", list(cases) + pilot)      # every wider-search or pilot case named in the answer is tagged as unverified, whatever the model wrote
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
