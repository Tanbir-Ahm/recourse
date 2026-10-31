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
import functools
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
    "A passage can be a QUOTATION from another, earlier decision that the judgment it is listed under reproduces, and it may start in the middle of the extract without naming that decision. Treat a passage as a probable "
    "quotation when the facts, dates, names or places it describes cannot be those of the case it is listed under (for example a 1968 arrest described in a judgment of 2011, or a petitioner who is plainly another person), "
    "or when it is in quotation marks or introduced by words such as \"observed as under\". Then: (1) never say that the listed case decided, held or recorded it, and never use it as that case's authority; "
    "(2) never give its paragraph number, which belongs to the quoted decision and not to the listed case; (3) build no ground and no For/Against point on it; (4) do not mention it in your answer, and do not mention that it is a "
    "quotation: leave it out as if you had not seen it, and never write a sentence about where it sits, which earlier decision it may reproduce, or that it needs checking (the reader's page carries that caution; such a sentence only breaks the flow of the argument). "
    "If another passage of the same case states the point in the court's own words, you may use that one. A quoted section of a statute is not a problem; this rule is about quoted decisions. "
    "Use a passage only for the question it actually decides: a passage about delay in starting a prosecution does not answer a question about delay in a trial that is already running, and a passage about one kind of bail condition says nothing about another. "
    "Put words in quotation marks ONLY when you copy them exactly, letter for letter, from a passage. If you shorten, join, reorder or reword anything (for example turning \"neither X nor Y would be justified\" into \"would not be justified\"), write it in your own words WITHOUT quotation marks. "
    "A passage that ends in \"...\" is cut off: do not complete it from memory. "
    "If no passage clearly bears on the person's situation, ignore them all. Do not say that a case is good law.\n"
)

# ---- which court decided a wider-search passage (the wide index holds Gauhati High Court judgments beside the Supreme Court's since the index of 2026-10-24) ----
# Everything below leaves the text above and every string of an all-Supreme-Court result exactly as it was: a service that sends no `court` (the one on production) is read as the Supreme Court, which is all it holds.
SC_COURT = "Supreme Court of India"
COURT_RULE = ("The heading of each passage names the court that decided that case. Name that court exactly as the heading gives it. NEVER call a High Court's decision a decision of the Supreme Court, and never present it "
              "as the law everywhere in India: a High Court's decision does not bind courts outside its own territory, so say which High Court decided it. ")


def court_of(r):
    """The court that decided a wider-search result: the service's `court` field; the Supreme Court when the service sends none."""
    c = r.get("court") if isinstance(r, dict) else None
    c = re.sub(r"\s+", " ", str(c)).strip() if c else ""
    return c or SC_COURT


def courts_of(items):
    return [court_of(r) for r in items or [] if isinstance(r, dict)]


def mixed(items):
    """True when at least one of the items was decided by a court other than the Supreme Court (only then does anything on a page or in the prompt name a court)."""
    return any(c != SC_COURT for c in courts_of(items))


def scope_phrase(courts):
    """'Supreme Court' when all are Supreme Court; else 'Supreme Court and High Court' / 'High Court' (every other court a High Court) or the plainer 'Supreme Court and other court' / 'court'."""
    others = {c for c in courts if c != SC_COURT}
    if not others:
        return "Supreme Court"
    kind = "High Court" if all("High Court" in c for c in others) else "other court"
    if SC_COURT in courts:
        return "Supreme Court and " + kind
    return kind if kind == "High Court" else "court"


def short_court(court):
    """'Supreme Court' for the Supreme Court of India; every other court as it is recorded."""
    return "Supreme Court" if (court or SC_COURT) == SC_COURT else court


OPEN_BUCKET_CREDIT = "copy from the open Supreme Court judgments bucket (CC-BY-4.0, Dattam Labs)"
CREDITS = {"open_bucket_pdf": OPEN_BUCKET_CREDIT,
           "high_court_bucket_pdf": "copy from the open High Court judgments bucket (Dattam Labs; licence terms to be confirmed)",
           "high_court_site_pdf": "copy from the High Court's own website"}
COURT_FOOT = (" A passage marked with a High Court is that court's decision, not the Supreme Court's, and it does not bind courts outside that High Court's territory.")


def credit_for(link_kind):
    """The words that credit the place a wider-search PDF link points to ('' when it is the court's own archive)."""
    return CREDITS.get(link_kind or "", "")


def _upper_first(s):
    return s[:1].upper() + s[1:]


def box_title(items, fed, scope=None):
    """The heading of the box of wider-search passages (for the list `items`, or for a `scope` phrase already worked out). For an all-Supreme-Court list it is the heading that was there before the High Court judgments came."""
    scope = scope or scope_phrase(courts_of(items))
    return (_upper_first(scope) + " passages from a wider search that this answer also read (not independently verified)" if fed
            else "More " + scope + " judgments that may be relevant (a wider search; not independently verified)")


def asof_sentence(as_of, by_court=None):
    """' The collection ends 2026-07-13.' (nothing when no date). With a date for each of several courts: ' The collection ends 2026-10-16 for the Supreme Court and 2026-10-14 for the Gauhati High Court.'"""
    if isinstance(by_court, dict) and len(by_court) > 1:
        order = sorted(by_court.items(), key=lambda kv: (kv[0] != SC_COURT, kv[0]))
        return " The collection ends " + " and ".join("%s for the %s" % (d, short_court(c)) for c, d in order if d) + "."
    return (" The collection ends " + str(as_of) + ".") if as_of else ""


def feed_instruction(courts):
    """The prompt block's opening for the courts of the passages fed: FEED_INSTRUCTION itself when all are Supreme Court (nothing changes), else the same text with the court named, plus COURT_RULE."""
    if not any(c != SC_COURT for c in courts):
        return FEED_INSTRUCTION
    scope = scope_phrase(courts)
    other = short_court(next((c for c in courts if c != SC_COURT), "court"))
    example = '("the Supreme Court in X said ..." or "the %s in X said ...")' % other if SC_COURT in courts else '("the %s in X said ...")' % other
    text = FEED_INSTRUCTION
    for old, new in _feed_swaps(scope, example):
        text = text.replace(old, new, 1)
    return text


def _feed_swaps(scope, example):
    """(old, new) pairs applied to FEED_INSTRUCTION for a feed that has a passage of another court; test_sci_search_tier checks that every `old` is in the text exactly once."""
    return (("## Supreme Court passages from", "## " + scope[0].upper() + scope[1:] + " passages from"),
            ("a much larger collection of Supreme Court judgments", "a much larger collection of " + scope + " judgments"),
            ('attributed to the court ("the Supreme Court in X said ...")', "attributed to the court that decided it " + example),
            (" right after its name. ", " right after its name. " + COURT_RULE))


_TRAIL_PARTY = re.compile(r"(?:[,.\s]+(?:&|and)\s+(?:anr|ors|another|others)\b\.?|[,.\s]+(?:anr|ors|another|others|etc)\b\.?)+\s*$", re.I)


def reset():
    """Forget what was fed to the model for the previous question (called at the start of answer_question)."""
    _LOCAL.question, _LOCAL.skips, _LOCAL.block, _LOCAL.cases = None, (), "", []
    _LOCAL.statute_ctx = []


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


_SERVICE_NO = re.compile(r"^[^,]{0,25}\d[^,]{0,25},\s*(\S+(?:\s+\S+)+)$")          # 'I C 62912 F, Major Sowmithri S': the High Court's title starts with the officer's service number; the answer writes the name without it


def _parties(name):
    parts = re.split(r"\s+(?:v\.?|vs\.?|versus)\s+", name or "", maxsplit=1, flags=re.I)
    if len(parts) == 2:
        m = _SERVICE_NO.match(parts[0].strip())
        return (_party_core(m.group(1) if m else parts[0]), _party_core(parts[1]))
    return (_party_core(name), "")


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
    """Cases whose verbatim excerpts (excerpt_anchors.py, ANCHORS=on or LANDMARKS=on) go into the prompt for this question: the wider search does not hand the same case over a second time."""
    try:
        import excerpt_anchors
        return [a["case_name"] for a in excerpt_anchors.selected(question)]
    except Exception:  # noqa: BLE001
        return []


def _anchor_doc_ids(question):
    """The court-archive ids (the number in https://api.sci.gov.in/jonew/judis/<id>.pdf) of those same cases, which the search service also reports as "doc". Added 2026-10-29 with the landmark anchors: the index
    spells "Sharad Birdhi Chand Sarda" and "Hanumant v. The State of Madhya Pradesh.Raojibhaithe State of Madhya Pra", and a name comparison would not know them for the anchors' own names, so the same
    judgment would reach the model twice, the second time as an unverified "wider search" case."""
    try:
        import excerpt_anchors
        out = set()
        for a in excerpt_anchors.selected(question):
            m = re.search(r"/judis/(\d+)\.pdf", a.get("link") or "")
            if m:
                out.add(int(m.group(1)))
        return out
    except Exception:  # noqa: BLE001
        return set()


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


_GENERIC_PARTY = re.compile(r"^(?:the\s+)?(?:state|union|central|govt|government|commissioner|collector|director|directorate|superintendent|inspector|bureau|enforcement|national|registrar|station|public|police|"
                            r"cbi|home|ministry|secretary|chief|district|sessions|magistrate|bank|municipal|corporation|board|authority|committee|commission|tribunal|university|institute|company|assistant|"
                            r"deputy|additional|joint|senior|principal|high\s+court|supreme\s+court)\b", re.I)         # a party that many cases share ('State of Karnataka', 'Union of India', 'CBI'): it cannot identify a case on its own
_AFTER_V = re.compile(r"(?:\bv\.?|\bvs\.?|\bversus)\s*(?:the\s+)?$", re.I)                                        # the text just before a span ends with 'v.': the span stands as a SECOND party


@functools.lru_cache(maxsize=512)
def _locate_strong(text, case_name):
    """(start, end) of the first mention of a case by its FULL name, else by a distinctive FIRST party (allowing a typo, and a dropped 'Dr.'), taking the ' v. second party' and a trailing '& Another' with it.
    These two ways name the case itself; the weaker ways (a second party alone) are in _locate. None when neither finds it."""
    p1, p2 = _parties(case_name)
    span = None
    if p1 and p2:
        m = re.search(r"\b(?:the\s+)?" + _words_re(p1) + _EXTRA + _MARK + _V + r"(?:the\s+)?" + _words_re(p2) + _EXTRA, text, re.I)      # '& Ors' / '& Anr' may stand between the first party and 'v.' ('Rajeswar Tiwari & Ors v. Nanda Kishore Roy')
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
                m_x = re.match(_EXTRA, text[end:], re.I)                                  # '& Ors' between the first party and 'v.': step over it, then take the second party (was: the label landed inside the name)
                if m_x and m_x.end() and re.match(_MARK + _V, text[end + m_x.end():], re.I):
                    end += m_x.end()
                end = _extend_second_party(text, end)
                m = re.match(_EXTRA, text[end:], re.I)
                end += m.end() if m else 0
            span = (sp[0], end)
    return span


_FIRST_PARTY_STOP = frozenset("the and ors anr another others dr mr mrs ms shri smt sri etc versus".split())


def _first_party_agrees(text, a, p1):
    """True when the words standing before the 'v.' that precedes position `a` of `text` could be the case's first party `p1` (they share a word of three letters or more, or spell it alike): 'Pankaj Bansal v. Union of
    India' is not 'Vijay Madanlal Choudhary v. Union of India'. Found with real data on 2026-10-26: a generic second party alone ('Union of India' after 'v.') used to be enough, so the label of one wider-search case
    landed on another case that has the same respondent. True when `p1` is unknown."""
    try:
        if not p1:
            return True
        before = re.sub(r"[*_\[\]()]", " ", text[max(0, a - 120):a])
        before = re.sub(r"\s+(?:v\.?|vs\.?|versus)\s*$", "", before.rstrip(), flags=re.I)
        words = re.findall(r"[A-Za-z][A-Za-z.'\u2019-]*", before)[-6:]
        have = {w.strip(".'\u2019-").lower() for w in words} - _FIRST_PARTY_STOP
        want = {w.strip(".'\u2019-").lower() for w in re.findall(r"[A-Za-z][A-Za-z.'\u2019-]*", p1)} - _FIRST_PARTY_STOP
        if any(len(w) >= 3 and w in have for w in want):
            return True
        import difflib
        return any(len(h) >= 4 and len(w) >= 4 and difflib.SequenceMatcher(None, h, w).ratio() >= 0.8 for h in have for w in want)
    except Exception:  # noqa: BLE001
        return True


def _second_party_span(text, p2, avoid=(), p1=None):
    """(start, end) of the second party of a case standing ALONE in `text` (the first party was not found: it is misspelt, or the answer shortened it). Owner's staging test 2026-10-19: 'Yunus Zia v. State of
    Karnataka' (fed in the same turn) was found at the start of 'State of Karnataka v. T.N. Sudhakar Reddy', and 'State of Andhra Pradesh' passed for 'State of Madhya Pradesh' by the typo tolerance, so the label
    landed inside another case's name. Now: (1) a stretch that overlaps the name of another case (`avoid`) never counts; (2) a party that many cases share ('State of ...', 'Union of India', 'CBI') counts only
    when it is spelt exactly and stands after 'v.' (as a second party); (3) a distinctive party may still be found with a typo."""
    generic = bool(_GENERIC_PARTY.match(p2))
    cands = [(m.start(), m.end()) for m in re.finditer(r"\b" + _words_re(p2) + r"\b", text, re.I)]
    if not cands and not generic:
        sp = _fuzzy_span(text, p2)
        if sp:
            cands.append(sp)
    for a, b in cands:
        if any(a < y and x < b for x, y in avoid):
            continue
        if generic and not _AFTER_V.search(text[max(0, a - 14):a]):
            continue
        if generic and not _first_party_agrees(text, a, p1):
            continue
        return a, b
    return None


def _locate(text, case_name, others=None):
    """(start, end) of the first mention in `text` of a wider-search case: found by its full name, else by a distinctive party name (allowing a typo, and a dropped 'Dr.'), taking the ' v. second party'
    and a trailing '& Another' with it, else by its second party alone (see _second_party_span) or by a close spelling of the whole name. The end is the end of the name, before italics marks and brackets.
    `others`: the names of the other cases that are looked for in the same text; a weak match is never taken from inside one of them. None when the case is not mentioned."""
    p1, p2 = _parties(case_name)
    span = _locate_strong(text, case_name)
    if span is None and p2 and len(p2) >= 8:
        avoid = [sp for sp in (_locate_strong(text, o) for o in (others or []) if o and o != case_name) if sp]
        span = _second_party_span(text, p2, avoid, p1)
    if span is None and p1 and p2:
        span = _fuzzy_span(text, re.sub(r"^(?:dr|mr|mrs|ms|shri|smt)\.?\s+", "", p1, flags=re.I) + " v. " + p2, 0.9)
    if span is not None and text[span[1]:span[1] + 1] == "." and re.search(r"(?:\b[A-Za-z]\.){1,}[A-Za-z]$", text[:span[1]]):
        span = (span[0], span[1] + 1)                                    # 'State of M.P.': the closing full stop of the initials belongs to the name (the party names are stored without it)
    return span


def _others(cases, c):
    """The names of the cases in `cases` other than `c` (for _locate's `others`)."""
    return [x.get("case_name") for x in cases or [] if isinstance(x, dict) and x is not c and x.get("case_name")]


def _name_end(out, end, note_re):
    """Where a label belongs for a name that ends at `end`: after the italics mark, then after a short year or citation in brackets, or a report citation ', (2002) 4 SCC 578', that follows the name."""
    m0 = re.match(r"[*_]{1,2}", out[end:])                        # the name is in italics (answer style v3): put the label after the closing mark, not inside it
    if m0:
        end += m0.end()
    for _ in range(3):
        if _labelled_here(out, end, note_re):
            break
        mlong = re.match(r"\s*\([^()]{41,140}\)", out[end:])          # a longer note about the case ('(Supreme Court, 1968 facts recorded in a 2011 order)') that the model itself follows with the label: the label is already there, after it
        if mlong and note_re.match(out[end + mlong.end():].lstrip(" \t")):
            end += mlong.end()
            continue
        m2 = re.match(r"\s*[\(\[][^)\]]{0,40}[\)\]]", out[end:]) or _REPORT_CITE.match(out[end:])
        if not m2 or note_re.match(out[end:].lstrip()):
            break
        end += m2.end()
        m3 = re.match(r"[*_]{1,2}", out[end:])                    # '*Sumit Mehta v State (NCT of Delhi)*': the bracket is part of the italic name, so the closing mark follows it
        if m3:
            end += m3.end()
    return end


def only_at_first_mentions(text, cases, label, note_re):
    """The text with `label` kept only where it follows the first mention of one of `cases` (the model sometimes also writes it after 'a seven-judge Bench' or a later mention): any other copy is removed."""
    try:
        out = text or ""
        keep = set()
        for c in cases or []:
            span = _locate(out, c["case_name"], _others(cases, c))
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


_NEVER = re.compile(r"(?!)")


def _drop_midname_labels(text, cases, label):
    """Removes a copy of `label` that stands INSIDE a case name (the model wrote 'Union of India (from a wider search ...) v. Kanhaiya Prasad (2025)' or '... v. Assistant Director (label), Directorate of
    Enforcement (2015)'; the code then added a second one after the whole name: nine labels in one paragraph, staging 2026-10-17). The case is located with every copy of the label taken out; a copy that starts
    before the last character of the name (with its italics marks and bracket) is inside it and is dropped. A copy after the name, or one that belongs to no case we can find, is left alone."""
    try:
        rx = re.compile(r"[ \t]*" + re.escape(label))
        copies = [(m.start(), m.end()) for m in rx.finditer(text)]
        if not copies:
            return text
        keep, pos = [], 0
        for a, b in copies:
            keep.extend(range(pos, a))
            pos = b
        keep.extend(range(pos, len(text)))
        stripped = "".join(text[i] for i in keep)
        drop = set()
        for c in cases or []:
            span = _locate(stripped, c.get("case_name") or "", _others(cases, c))
            if span is None:
                continue
            end = _name_end(stripped, span[1], _NEVER)
            if end < 1 or end > len(keep):
                continue
            last, first = keep[end - 1], keep[span[0]]
            for a, b in copies:
                if first <= a < last:
                    drop.add((a, b))
        if not drop:
            return text
        out, pos = [], 0
        for a, b in sorted(copies):
            if (a, b) in drop:
                out.append(text[pos:a])
                pos = b
        out.append(text[pos:])
        return "".join(out)
    except Exception:  # noqa: BLE001
        return text


def label_cases(text, cases, label, note_re, span_re, tidy=None):
    """Puts `label` right after the first mention of each case in a finished answer, unless the answer already says so there (`note_re` recognises the model's own wording of the label, `span_re` a label
    that is already in the text). The case is found by its full name, else by a distinctive party name, allowing a typo. The label goes after the whole name (including '& Another', italics marks and a
    year in brackets), never inside a name or inside another label. Returns the text unchanged on any problem."""
    try:
        out = _drop_midname_labels(text or "", cases, label)
        seen = set()
        for c in cases or []:
            key = re.sub(r"\W+", " ", (c.get("case_name") or "").lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            span = _locate(out, c["case_name"], _others(cases, c))
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
        every = list(getattr(_LOCAL, "cases", None) or []) + [e for e in (extra or []) if isinstance(e, dict)]
        for c in every:
            if not c.get("case_name"):
                continue
            out.append(c["case_name"])
            span = _locate(text, c["case_name"], _others(every, c))
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


# ---- the statute filter (owner's staging test 2026-10-19) ---------------------------------------------------------------------------------------------------------------------------------------------
# The question was about section 17 of the Prevention of Corruption Act. The wider search ranks a passage that holds the section NUMBER higher, so "Sri Radhy Shyam v. State of U.P." (section 17 of the
# land-acquisition law: urgency) was fed and listed under the answer. When the Act shelf found an Act AND the question names a section of it (chat_assistant publishes that with set_statute_context), a passage
# that cites the SAME number is left out when it is plainly about another statute: (A) every reference to the number is tied, in so many words, to some other Act or Code; or (B) it never names the Act and has
# almost nothing of the section's own words (the section's own text is the yardstick). A passage that names the Act, one that does not cite the number, and one too short or too ambiguous to judge are kept. The
# filter fails open. FEED_STATUTE_FILTER=off switches it off; with no statute context it does nothing at all.
FILTER_MIN_PASSAGE = 150          # characters: a shorter passage is judged only by (A)
FILTER_MIN_SECTION_WORDS = 12     # a section with fewer content words of its own cannot be used as the yardstick
FILTER_ANAPHORA = 2000            # characters: a bare 'Section 19' this soon after the last mention of 'Section 19 of the X Act' is the X Act's
_FILTER_STOP = frozenset("""about above after against also among another because been before being between both could does done during each either else even ever every from further have having here herein hereby however
into itself just made make makes many more most much must neither never none only other otherwise over same shall should since some such than that their them then there thereof these they this those through under
until upon very were what when where whether which while will with within without would your section sections subsection clause provided notwithstanding anything contained thereto thereby therein act acts code person
persons court courts order orders state states government case cases""".split())
_ACRONYMS = r"(?:Cr\.?\s?P\.?\s?C\.?|I\.?\s?P\.?\s?C\.?|C\.?\s?P\.?\s?C\.?|BNSS|BNS|BSA|NDPS(?:\s+Act)?|PMLA|UAPA|POCSO|IT\s+Act|NI\s+Act|PC\s+Act|P\.C\.\s+Act)"
_NAME_WORD = r"\(?[A-Z][\w.&'’()-]*"                                       # a capitalised word of a statute's name ('Land', 'Narcotic', '(Prevention', 'Atrocities)')
_NAME_LINK = r"(?:(?:of|and|the|for|from|with|to|on|in)\s+)*"                # the small words inside a name ('Prevention of Money Laundering', 'Narcotic Drugs and Psychotropic Substances'); a name never ENDS in one, so 'Chapter IV of the Act' is not a statute
_NAMED_AFTER = re.compile(r"\s*,?\s*(?:(?:of|under|in)\s+(?:the\s+)?)?(?P<a>" + _ACRONYMS + r")(?!\w)(?!\.\w)"                          # an acronym needs no 'of': 'Section 482 Cr.P.C.', 'Section 19(1) PMLA.' (a full stop after it ends the sentence)
                          r"|\s*,?\s*(?:of|under|in)\s+(?:the\s+)?(?:"
                          r"(?P<c>Code\s+of\s+(?:Criminal|Civil)\s+Procedure(?:\s*,?\s*(?:18|19|20)\d\d)?|Indian\s+Penal\s+Code|Penal\s+Code|Constitution(?:\s+of\s+India)?)"
                          r"|(?P<n>" + _NAME_WORD + r"(?:\s+" + _NAME_LINK + _NAME_WORD + r"){0,8}?\s+(?:Act|Sanhita|Adhiniyam|Ordinance|Rules|Regulations)\b(?:\s*,?\s*(?:18|19|20)\d\d)?)"
                          r"|(?P<y>Act\s+of\s+(?:18|19|20)\d\d\b|(?:18|19|20)\d\d\s+Act\b))")
_CHAIN = re.compile(r"\s*,?\s*(?:read\s+with|r/w|r\.w\.|along\s*with|together\s+with|and|or|&)\s+", re.I)       # 'Section 45 read with Section 40 of the X Act': both numbers are the X Act's


def _year_alias(year):
    """The ways a judgment shortens an Act's name to its year: 'the Act of 2002', 'Act, 2002', 'the 2002 Act'."""
    y = re.escape(str(year))
    return re.compile(r"\bAct\s*(?:of\s+|,\s*)" + y + r"\b|\b" + y + r"\s+Act\b", re.I)


def _filter_on():
    return _env("FEED_STATUTE_FILTER", "on").strip().lower() not in ("off", "0", "false", "no")


def _stems(text):
    """The content words of a text, each cut to its first six letters (so that 'investigate', 'investigation' and 'investigating' agree), without the common words of every statute."""
    return {w[:6] for w in re.findall(r"[a-z]{4,}", (text or "").lower()) if w not in _FILTER_STOP}


def make_statute_context(items):
    """The statute context in the form the filter uses: [{'act', 'aliases' (a compiled regex of the Act's names, or None), 'sections': {number: text}, 'words': {number: content words}}] from
    act_shelf.statute_context's items. [] for nothing usable."""
    out = []
    for it in items or []:
        try:
            secs = {str(n).upper(): t for n, t in (it.get("sections") or {}).items() if t}
            if secs:
                out.append({"act": it.get("act") or "", "aliases": it.get("aliases"), "year": it.get("year"), "sections": secs, "words": {n: _stems(t) for n, t in secs.items()}})
        except Exception:  # noqa: BLE001
            continue
    return out


def set_statute_context(items):
    """Called by chat_assistant once the Act shelf has handed over a section the question named: the filter for THIS question's wider search. reset() forgets it."""
    try:
        _LOCAL.statute_ctx = make_statute_context(items)
    except Exception:  # noqa: BLE001
        _LOCAL.statute_ctx = []


def _section_refs(text):
    """[(number, start, end)] for every section number a text cites ('section 17', 'Sections 13 and 17(1)', 's. 45', 'Section 5-A' is 5A); end is where the reference stops, where the statute's name would follow."""
    try:
        from act_shelf import _SECREF
    except Exception:  # noqa: BLE001
        return []
    out = []
    for m in _SECREF.finditer(text or ""):
        nums = re.findall(r"\d{1,3}[A-Za-z]{0,2}", re.sub(r"\([^)]*\)", " ", m.group(1)))
        tail = re.match(r"\s*-\s*([A-Za-z])\b", text[m.end():])
        for i, n in enumerate(nums):
            if tail and i == len(nums) - 1 and not re.search(r"[A-Za-z]$", n):
                n += tail.group(1)
            out.append((n.upper(), m.start(), m.end() + (tail.end() if tail else 0)))
    return out


_THEREOF = re.compile(r"\s*(?:thereof|therein|thereunder|of\s+(?:that|the\s+said|the\s+same)\s+(?:Act|Code))\b", re.I)
_NAME_ANYWHERE = re.compile(r"(?P<n>" + _NAME_WORD + r"(?:\s+" + _NAME_LINK + _NAME_WORD + r"){0,8}?\s+(?:Act|Sanhita|Adhiniyam|Ordinance|Rules|Regulations)\b(?:\s*,?\s*(?:18|19|20)\d\d)?)|(?P<y>\bAct\s+of\s+(?:18|19|20)\d\d\b|\b(?:18|19|20)\d\d\s+Act\b)")


def _statute_named_before(text, start, aliases=None, year=None):
    """The statute named in the 200 characters before a section reference that ends 'thereof' ('... the Prevention of Money Laundering Act, 2002 under Section 19 thereof'): its last name there, or None (none
    named, or it is the Act's own: `aliases`, or the bare short form of its `year`)."""
    last = None
    for m in _NAME_ANYWHERE.finditer(text[max(0, start - 200):start]):
        last = m
    if not last:
        return None
    name = re.sub(r"\s+", " ", last.group(0)).strip(" ,")
    if aliases is not None and aliases.search(name):
        return None
    if year and last.group("y") and _year_alias(year).search(name):
        return None
    return name


def _statute_named_after(text, end, aliases, year=None, start=None):
    """The statute a section reference ending at `end` is tied to in so many words ('of the Land Acquisition Act, 1894', 'under the Code of Criminal Procedure', 'of the NDPS Act', 'of the Prevention of Money
    Laundering Act, 2002', 'of the Act of 1894'), or None when none is named, when only 'the Act' / 'the Code' is written, or when the name is one of the Act's own (`aliases`; `year`: the Act's year, so that
    'the Act of 1988' is the Prevention of Corruption Act's own).  Following section references joined by 'read with' / 'and' ('Section 45 read with Section 40 of the RPwD Act') are skipped: they share the name."""
    text = text or ""
    pos = end
    try:
        from act_shelf import _SECREF
        for _ in range(3):
            c = _CHAIN.match(text, pos)
            r = _SECREF.match(text, c.end()) if c else None
            if not r:
                break
            tail = re.match(r"\s*-\s*([A-Za-z])\b", text[r.end():])
            pos = r.end() + (tail.end() if tail else 0)
    except Exception:  # noqa: BLE001
        pos = end
    m = _NAMED_AFTER.match(text, pos)
    if not m:
        if start is not None and _THEREOF.match(text, pos):                # 'under Section 19 thereof': the Act named just before
            return _statute_named_before(text, start, aliases, year)
        return None
    name = re.sub(r"\s+", " ", m.group(0)).strip(" ,")
    name = re.sub(r"^(?:of|under|in)\s+(?:the\s+)?", "", name, flags=re.I)
    if aliases is not None and aliases.search(name):
        return None
    if year and m.group("y") and _year_alias(year).search(name):         # only the bare short form ('the Act of 1988'): a full name of the same year ('Motor Vehicles Act, 1988') is another statute
        return None
    return name


def _off_statute(text, ctx):
    """None to keep a wider-search passage; else a short reason why it is about another statute. See the comment above. `ctx` is make_statute_context's form. Never raises."""
    try:
        if not text or not ctx:
            return None
        refs = _section_refs(text)
        cited = []
        for item in ctx:
            for num, words in item["words"].items():
                spans = [(s, e) for n, s, e in refs if n == num]
                if spans:
                    cited.append((item, num, words, spans))
        if not cited:
            return None
        if any(it["aliases"] is not None and it["aliases"].search(text) for it, _n, _w, _s in cited):
            return None                                                    # the passage names the Act itself
        tied = []
        for it, num, _w, spans in cited:
            last = None                                                    # the last statute this number was tied to: 'Section 19 of the PMLA ... Section 19 reads thus' (a bare repeat within FILTER_ANAPHORA characters of the last mention)
            for s_, e in sorted(spans):
                name = _statute_named_after(text, e, it["aliases"], it.get("year"), start=s_)
                if not name and last and s_ - last[1] <= FILTER_ANAPHORA:
                    name = last[0]
                if name:
                    last = (name, e)                                       # the window slides: a bare repeat that inherited the tie carries it on
                tied.append((it, num, name))
        if tied and all(t[2] for t in tied):                               # (A) every reference to the number is tied to some other statute
            return "cites section %s of %s" % (tied[0][1], tied[0][2][:70])
        if any(_year_alias(it.get("year")).search(text) for it, _n, _w, _s in cited if it.get("year")):
            return None                                                    # 'the Act of 2002', 'the 2002 Act': a judgment's usual short name for the Act (it may also be another Act of that year: kept, not judged)
        if len(text) < FILTER_MIN_PASSAGE:
            return None
        mine = _stems(text)
        judged = []
        for it, num, words, _spans in cited:                               # (B) the section's own words are the yardstick
            if len(words) < FILTER_MIN_SECTION_WORDS:
                return None
            need = 3 if len(words) >= 25 else 2
            shared = len(mine & words)
            if shared >= need:
                return None
            judged.append((it, num, shared))
        it, num, shared = judged[0]
        return "cites section %s without naming %s and shares only %d word(s) with it" % (num, it["act"] or "the Act", shared)
    except Exception:  # noqa: BLE001 -- fail open
        return None


def _statute_filter(results):
    """(kept, dropped): `results` without the passages that are plainly about another statute; dropped is [(result, reason)]. Nothing is dropped without a statute context or with FEED_STATUTE_FILTER=off."""
    ctx = getattr(_LOCAL, "statute_ctx", None) or []
    if not ctx or not _filter_on():
        return list(results), []
    kept, dropped = [], []
    for r in results:
        why = _off_statute((r.get("text") or "") if isinstance(r, dict) else "", ctx)
        (dropped.append((r, why)) if why else kept.append(r))
    return kept, dropped


MAX_NAMED_FETCHES = 2        # second searches per question for a controlling case that a passage points to (a flagged case's own corrector is fetched without this cap)
NAMED_NOTE = "\n[Overruled Register -- not optional: this passage names a case on our register; if you mention that case at all, state this fact in the same sentence]\n"


def _named_register(text):
    """The register cases a fed passage names (register_hooks.text_mentions): {'lines', 'clauses', 'overruling'}; empty when none or on any problem."""
    try:
        from register_hooks import text_mentions
        return text_mentions(text)
    except Exception:  # noqa: BLE001
        return {"lines": [], "clauses": [], "overruling": []}


def _library_skips(exclude):
    """`exclude`: case names (str) or (name, year) pairs of the reviewed-library judgments that already reach this answer, as a tuple that can be a cache key; names that are empty are dropped."""
    out = []
    for e in exclude or []:
        name, year = (e if isinstance(e, (tuple, list)) and len(e) == 2 else (e, None))
        if isinstance(name, str) and name.strip():
            out.append((name.strip(), str(year)[:4] if year else None))
    return tuple(sorted(set(out), key=lambda t: (t[0], t[1] or "")))


def library_keys(matches):
    """(case name, year or None) for each judgment among an answer's reviewed-library `matches` (the year from the match's own year field, else the first year in its citation: '2023 INSC 866', '(2014) 8 SCC 273', 'AIR 1978 SC 597')."""
    out = []
    try:
        for m in matches or []:
            if isinstance(m, dict) and m.get("case_name"):
                found = re.search(r"\b(?:18|19|20)\d{2}\b", str(m.get("year") or "") + " " + str(m.get("citation") or ""))
                out.append((m["case_name"], found.group(0) if found else None))
    except Exception:  # noqa: BLE001
        pass
    return out


def is_library_case(case_name, date, skips):
    """True when a wider-search result is a judgment the answer already has from the reviewed library: the same case by the register's own name rule (_same_case_loose), and, where both sides give a year, the
    same year (two decisions of the same parties in different years are two cases). Never raises."""
    try:
        year = (date or "")[:4]
        for name, y in skips or ():
            if _same_case_loose(case_name, name) and (not y or not year or y == year):
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def feed_block(question, exclude_names=None):
    """The prompt section for feed mode ('' in every other mode, and on any failure). One passage per case, up to FEED_MAX_CASES cases; a case the register flags goes last and the case that overruled it
    is added (taken from the results, or fetched by a second search), so the model can name the controlling case. The same is done for a case the register lists that a passage merely NAMES (a later
    judgment that quotes or discusses it): the passage carries the REGISTER FACT line and the case that corrected it is added. The search runs once per question and is reused by the retry loop.
    Never raises."""
    try:
        import quote_notes
        if mode() != "feed" or not question:
            return ""
        skips = _library_skips(exclude_names)                         # judgments the answer already has from the reviewed library: not handed over again, never labelled "wider search" (FOLLOW_UPS 2cm)
        if getattr(_LOCAL, "question", None) == question and getattr(_LOCAL, "skips", ()) == skips:
            return _LOCAL.block
        found = search(question, timeout=max(float(_env("SCI_SEARCH_TIMEOUT", "6")), 15.0))
        try:
            import evidence_companions                                   # EVIDENCE_COMPANIONS (default off): more questions put to the wider search for a circumstantial-evidence question
            found = evidence_companions.merge(found, question, lambda q: search(q, timeout=max(float(_env("SCI_SEARCH_TIMEOUT", "6")), 15.0), label="sci_search_companion"))
        except Exception:  # noqa: BLE001
            pass
        _LOCAL.question, _LOCAL.skips, _LOCAL.block, _LOCAL.cases = question, skips, "", []
        if not found:
            print("SCI_FEED no passages: the search service gave no answer (down, slow, wrong address or token)", flush=True)
            return ""
        res = [r for r in found["results"] if r.get("case_name") and not r.get("name_to_review")]
        in_library = [r for r in res if is_library_case(r["case_name"], r.get("date"), skips)]
        if in_library:
            gone = {id(r) for r in in_library}
            res = [r for r in res if id(r) not in gone]
            print("SCI_FEED_LIBRARY " + json.dumps({"left_out": sorted({r["case_name"][:100] for r in in_library})}), flush=True)
        flagged_q = [r for r in res if quote_notes.clean(r.get("quote"))]
        if flagged_q:                                                  # SCI_QUOTES=on at the service: the passage's number is not the judgment's own (a quoted decision, an order, a statute section, a list, a wrapped citation): it is not handed to the model
            gone_q = {id(r) for r in flagged_q}                        # (FOLLOW_UPS 2cn: told to mention it, the model wrote sentences about where it sits and what it may quote). Another passage of the same case may take its place.
            res = [r for r in res if id(r) not in gone_q]
            print("SCI_FEED_QUOTED " + json.dumps({"left_out": [{"case": (r.get("case_name") or "")[:100], "para": r.get("paragraph"), "within": r["quote"].get("within") if isinstance(r.get("quote"), dict) else None} for r in flagged_q]}), flush=True)
        res, left_out = _statute_filter(res)                              # a passage that cites the section the person named, of ANOTHER statute (owner's staging test 2026-10-19)
        if left_out:
            print("SCI_FEED_FILTER " + json.dumps({"dropped": [{"case": (r.get("case_name") or "")[:100], "para": r.get("paragraph"), "why": why[:160]} for r, why in left_out]}), flush=True)
        flags = _flags(res)
        anchor_names = _anchor_case_names(question)
        anchor_docs = _anchor_doc_ids(question)
        by_doc = {}
        for r, f in zip(res, flags):
            if r.get("doc") in anchor_docs or any(_same_case_loose(r["case_name"], n) for n in anchor_names):
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
            if hit and is_library_case(hit[0]["case_name"], hit[0].get("date"), skips):
                return None                                            # the reviewed library already hands this case over
            if hit and all(hit[0]["doc"] != c[0]["doc"] for c in correcting) and all(hit[0]["doc"] != p[0]["doc"] for p in flagged):
                correcting.append(hit)
            return hit

        for r, f in flagged:
            if f.get("overruling"):
                _controlling(f["overruling"])

        def _pointer(r, f):
            """The authority facts of a result the search service marks as one of the court's own pointers (authority_notes.py), else None. A case that the Overruled Register or a warning card has a word on is never
            presented as 'read this first': it is shown as the register wants it (last, with its fact and the case that corrected it)."""
            try:
                import authority_notes
                if f.get("source") in ("register", "card"):
                    return None
                x = authority_notes.facts(r)
                return x if authority_notes.is_pointer(x) else None
            except Exception:  # noqa: BLE001
                return None

        def _limit(r, f):
            """How many characters of a passage the answer model sees (and that the register scan reads): FEED_PASSAGE_CHARS, or longer for a pointer passage."""
            try:
                import authority_notes
                return max(FEED_PASSAGE_CHARS, authority_notes.PASSAGE_CHARS) if _pointer(r, f) else FEED_PASSAGE_CHARS
            except Exception:  # noqa: BLE001
                return FEED_PASSAGE_CHARS

        def _split():
            special = {p[0]["doc"] for p in flagged} | {p[0]["doc"] for p in correcting}
            return [p for p in pairs if p[0]["doc"] not in special], max(FEED_MAX_CASES - len(flagged) - len(correcting), 2)

        plain, room = _split()
        named, n_fetch, tried = {}, 0, set()                          # doc -> the register cases its passage names; names already looked up by a second search
        for r, f in plain[:room]:
            men = _named_register(_cut(r.get("text") or "", _limit(r, f)))
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
        blocks, cases, pointers = [], [], []
        chosen_courts = courts_of([r for r, _f in chosen])
        any_other = any(c != SC_COURT for c in chosen_courts)           # only then does a heading name its court; an all-Supreme-Court feed is worded exactly as before
        for r, f in chosen:
            year = r["date"][:4] if r.get("date") else None
            court = court_of(r)
            head = (f"[WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: {r['case_name']}" + (f" ({r['date']})" if r.get("date") else "") + (f", {court}" if any_other else "")
                    + (f", paragraph {r['paragraph']}" if r.get("paragraph") else "") + "]")
            body = _cut(r.get("text") or "", _limit(r, f))
            fx = _pointer(r, f)                                       # the service's authority facts (SCI_AUTHORITY=on there): only a pointer passage gets a line, a longer cut and a page note
            if fx:
                import authority_notes
            voices = []
            try:                                                      # PASSAGE_NOTES=on: whose voice the visible words are in (a lower court's view, one judge's opinion, a party's submission): passage_notes.py
                import passage_notes
                if passage_notes.enabled():
                    voices = passage_notes.kinds(body, r.get("passage_type"))
                    body += passage_notes.prompt_note(voices)
            except Exception:  # noqa: BLE001
                voices = []
            if fx:
                body += authority_notes.prompt_line(fx)
            facts = ""
            try:
                if court != SC_COURT:                                 # the register is about Supreme Court decisions (see register_hooks.result_flags)
                    raise LookupError
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
            case = {"case_name": r["case_name"], "date": r.get("date"), "paragraph": r.get("paragraph"), "link": r.get("link"), "link_kind": r.get("link_kind"), "court": court,
                    "excerpt": _cut(r.get("text") or "", EXCERPT), "register_note": f["note"] if f["source"] in ("register", "card") else None,
                    "names_register_note": (" ".join(men["clauses"]) if men else None), "passage_kinds": voices, "passage_note": (passage_notes.page_note(voices, court) if voices else None)}
            if fx:                                                     # a pointer passage: the page says why it is here, beside any note on whose voice it is in
                case["passage_note"] = ((case["passage_note"] + " ") if case["passage_note"] else "") + authority_notes.page_note(fx)
                case["authority"] = {"named_by_retrieved": fx["retrieved_by"], "retrieved": fx["retrieved"], "named_by_collection": fx["collection"]}
                pointers.append(authority_notes.log_item(r["case_name"], fx))
            cases.append(case)
        if not blocks:
            print("SCI_FEED no passages: nothing usable came back", flush=True)
            return ""
        print("SCI_FEED fed %d case(s): %s" % (len(cases), "; ".join(c["case_name"] for c in cases)), flush=True)
        if named:
            print("SCI_FEED passages naming register cases: %s" % "; ".join(c["case_name"] for c, (r, _f) in zip(cases, chosen) if r["doc"] in named), flush=True)
        extra = ""
        try:
            import passage_notes
            extra = passage_notes.INSTRUCTION if passage_notes.enabled() else ""
        except Exception:  # noqa: BLE001
            extra = ""
        if pointers:                                                   # at least one passage is from a judgment that the retrieved judgments themselves name: say how to use that line
            import authority_notes
            extra += authority_notes.INSTRUCTION
            print("SCI_FEED_AUTHORITY " + json.dumps({"pointers": pointers}), flush=True)
        _LOCAL.block = feed_instruction(chosen_courts) + extra + "\n\n".join(blocks) + "\n"
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
            skips = _library_skips(library_keys(result.get("matches")))
            if cases and skips:                                       # a case the reviewed library supplied for this answer is never shown or labelled as a wider-search case, whatever reached the prompt
                cases = [c for c in cases if not is_library_case(c.get("case_name"), c.get("date"), skips)]
            pilot = [{"case_name": j["case_name"]} for j in (result.get("unverified_related_judgments") or []) if isinstance(j, dict) and j.get("case_name")]       # the site's pilot cases are cited like the rest
            if cases:
                result["sci_related_judgments"] = cases
                result["sci_fed"] = True
            try:                                                      # a sentence that names a wider-search case and talks about where a passage sits or what it may quote is taken out (quote_notes.py, FOLLOW_UPS 2cn)
                import quote_notes
                names = [c["case_name"] for c in cases if c.get("case_name")]
                if names and result.get("response_text"):
                    text2, n_talk = quote_notes.drop_provenance_sentences(result["response_text"], names, lambda t, nm: _locate(t, nm, []))
                    if n_talk:
                        result["response_text"] = text2
                        print("QUOTE_TALK_DROPPED " + json.dumps({"sentences": n_talk}), flush=True)
            except Exception:  # noqa: BLE001
                pass
            if cases or pilot:
                result["response_text"] = label_fed_cases(result.get("response_text") or "", list(cases) + pilot)      # every wider-search or pilot case named in the answer is tagged as unverified, whatever the model wrote
            try:                                                      # a High Court passage that the answer's own sentence calls a Supreme Court one: a notice and a log line (no switch: it can only fire when a passage of another court was fed)
                import passage_notes
                if cases and mixed(cases):
                    wrong = passage_notes.court_notes(result.get("response_text") or "", cases, lambda t, n: _locate(t, n, [c.get("case_name") for c in cases if c.get("case_name") != n]))
                    if wrong:
                        print("COURT_LABEL_FLAG " + json.dumps({"cases": [w.split(":", 1)[0][:100] for w in wrong]}), flush=True)
                        import grounding_checks
                        grounding_checks.add_notes(wrong)
            except Exception:  # noqa: BLE001
                pass
            try:                                                      # PASSAGE_NOTES=on: the answer calls a flagged passage "the Supreme Court" in so many words: a notice (shown with GROUNDING_CHECKS=warn or enforce), and a log line
                import passage_notes
                if passage_notes.enabled() and cases:
                    flags = passage_notes.answer_notes(result.get("response_text") or "", cases, lambda t, n: _locate(t, n, [c.get("case_name") for c in cases if c.get("case_name") != n]))
                    if flags:
                        print("PASSAGE_NOTE_FLAG " + json.dumps({"cases": [f.split(":", 1)[0][:100] for f in flags]}), flush=True)
                        import grounding_checks
                        grounding_checks.add_notes(flags)
            except Exception:  # noqa: BLE001
                pass
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
            shown.append({"case_name": r["case_name"], "date": r.get("date"), "paragraph": r.get("paragraph"), "link": r.get("link"), "link_kind": r.get("link_kind"), "court": court_of(r),
                          "excerpt": txt, "register_note": f["note"] if f["source"] in ("register", "card") else None})
            if len(shown) >= MAX_SHOWN:
                break
        if shown:
            result["sci_related_judgments"] = shown
            result["sci_as_of"] = found.get("as_of")
            if isinstance(found.get("as_of_by_court"), dict) and len(found["as_of_by_court"]) > 1:
                result["sci_as_of_by_court"] = {str(k): str(v) for k, v in found["as_of_by_court"].items() if v}
    except Exception as exc:  # noqa: BLE001 -- fail-open
        logger.warning("sci tier attach failed: %s", type(exc).__name__)
    return result
