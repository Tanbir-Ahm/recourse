"""
search_service.py -- the engine of the website's SEARCH PAGE (built 2026-10-23; owner's go: "I want a PDF / word export and the search page"; the lawyers' module's first piece).

WHAT IT IS. A search of the texts and judgments Recourse HOLDS, for a person who types a section, a case name, a citation or a few words. It writes no answer and calls no language model: every line it returns is text Recourse
already holds (the Acts' sections word for word, the library judgments' paragraphs, the Supreme Court case-title index) or a fixed sentence. The result is plain data for the front end to draw.

THE QUERY IS READ FIRST (parse_query) and only the parts that fit it run; the first version ran everything and showed BNS section 273 for the citation "(2014) 8 SCC 273":
  citation   "(2014) 8 SCC 273", "[2014] 8 S.C.R. 128", "2014 INSC 463", "AIR 2014 SC 1863"   -> cases by that citation only (no sections, no passages)
  number     "17"                                                                          -> that section of every Act held
  section    "IPC 420", "BNSS 187", "sections 103 and 105 of the BNS", "section 17 PC Act"  -> the named sections only (an old IPC / CrPC number is mapped to its BNS / BNSS section through the table of
             corresponding sections and says so); any words left over in the query are searched below them
  act        "POCSO", "Prevention of Corruption Act"                                         -> the Act card (held or not held) and, for a very short Act, its sections
  words      "bail conditions", "arnesh kumar", "dowry death"                               -> sections (BM25 over the words and, when on, meaning), the case-title index and the library cases whose
             name holds the words, and the library judgments' paragraphs that hold them

WHAT IT SEARCHES (each part fails open: a missing file or service is a note, never an error):
  PROVISIONS   BNS, BNSS, the IT Act (10 sections) and the NI Act (19) from the chunk files; the Acts on the Act shelf (only while ACT_SHELF is on, as everywhere else). An Act the Directory names that Recourse does
               not hold gets its own card with the official link, never a lookalike section of another Act.
  CASES        the judgments of the reviewed library (68 distinct cases) and the Supreme Court title index (case_lookup_index.db, about 38,000 judgments: by title words, by Supreme Court Reports citation, by neutral
               citation). Every case carries the Overruled Register / checker verdict (register_hooks.case_status) or the fixed sentence "Not checked by us."
  MENTIONS     paragraphs of the library judgments that hold the words (BM25, and when it is on a query vector from voyage-law-2: the retrieval the answers use, thresholds included).
  WIDER        (mode "wider" only, a separate request) the sci-search service's Supreme Court passages (sci_search_tier.search), each with its register verdict and the label "not independently verified".

WHAT IT DOES NOT SAY. Nothing here says a case is good law. A missing result is not a finding that nothing exists. Library statute text carries no heading (the chunk files hold none). The BNS / BNSS copy is Recourse's
own; a word-for-word comparison with India Code on 2026-10-17 (acts/crosscheck_bns_bnss_report.json in the research repository) found it about 99% identical and listed the losses, which KNOWN_GAPS repeats beside the
sections they affect until the copy is repaired (deferred by the owner, 2026-10-17). The shelf's text is India Code's, machine-checked, not read by a person, and says so beside every section.

Public: search(query, mode="library", *, meaning=None, embed_fn=None, sci_fn=None) -> dict (never raises). parse_query(query). scope(). warm().
"""
import logging
import math
import os
import re
import threading
import urllib.parse

import numpy as np

logger = logging.getLogger("search_service")

MAX_QUERY_CHARS = 300
MAX_PROVISIONS = 10
MAX_NAMED_SECTIONS = 4           # sections named in one query ("sections 103, 105, 109 and 111 of the BNS")
MAX_EXTRA_WITH_SECTION = 5       # words-matched sections shown below the named ones
MAX_CASES = 12
MAX_MENTIONS = 6
MAX_PASSAGES_PER_CASE = 2
MAX_WIDER = 8
TEXT_CAP_ASKED = 16000           # a section the person asked for by number (the page's own cap, answer_view.SHELF_EXCERPT_CHARS)
TEXT_CAP_FOUND = 6000            # a section found by words or meaning
EXCERPT_CAP = 700
MODES = ("library", "wider")
INTENTS = ("empty", "nothing", "citation", "number", "section", "act", "words")

SCOPE_NOTE = ("This searches the sections and judgments Recourse holds, not everything that exists. Finding nothing here is not a finding that nothing exists. "
              "It does not say whether a decision is still good law; where a case is on our Overruled Register or has a warning from our automatic check, that is shown beside it.")
LIBRARY_CAPTION = "Recourse's stored copy of the text; check the official text before you rely on it"
BNS_COMPARED_NOTE = ("The BNS and BNSS text is Recourse's own copy. A word-for-word comparison with India Code on 17 October 2026 found about 99% of the words identical; "
                     "the losses in Recourse's copy that it found are noted beside the sections they affect.")
TABLE_NOTE = "The table of corresponding sections is a pointer, not a legal verdict; read the new section itself."
NOT_CHECKED = "Not checked by us."
CLOSE_NOTE = "These titles are close to what you typed but not exact. Check the name before you rely on one."
WIDER_UNAVAILABLE = "The wider search is not available right now."
WIDER_NEEDS_WORDS = "The wider search needs a few words that describe what you are looking for."
TIER_LIBRARY_LABEL = "Reviewed library"
TIER_INDEX_LABEL = "Supreme Court index (title and citation only)"
TIER_WIDER_LABEL = "Wider search (not independently verified)"
WIDER_LABEL = "(from a wider search, not independently verified)"

# What Recourse's own copy of the BNSS lost, found by the comparison with India Code of 2026-10-17 (research repository, acts/crosscheck_bns_bnss_report.json, "verdicts" whose "who" is RECOURSE).
# (code, section): (note shown beside the section, test that the defect is still in the stored text or None for "always"). A note is shown only while its test finds the defect, so a repaired section
# stops carrying it by itself; the entry can then be deleted.
KNOWN_GAPS = {
    ("BNSS", "183"): ("Recourse's copy lost the last line of the confession certificate, \"(Signed) A. B. Magistrate.\"", lambda t: "(Signed) A. B. Magistrate" not in t),
    ("BNSS", "401"): ("Recourse's copy lost the last sub-section, (10) (\"Nothing in this section shall affect the provisions of the Probation of Offenders Act, 1958 ...\"); here the section ends at (9).",
                      lambda t: not re.search(r"\n\(10\)", t)),
    ("BNSS", "480"): ("In Recourse's copy a letter was lost: \"on the execution by him of a bond\" reads \"o the execution\".", lambda t: bool(re.search(r"\bo\s+the execution by him of a bond", t))),
    ("BNSS", "359"): ("In Recourse's copy the table of offences that may be compounded is flattened cell by cell and wrapped cells run together; read the table in the official text.", None),
}


def known_gap(code, base, text):
    """The note for a section of Recourse's own copy that is known to have lost something, while the loss is still in `text`; else None."""
    entry = KNOWN_GAPS.get((code, base))
    if not entry:
        return None
    note, still = entry
    try:
        return note if still is None or still(text) else None
    except Exception:  # noqa: BLE001
        return note


_STOP = frozenset("a an the of and or in on at to for by with from is are was were be been this that these those it its as under any all what which who whom how when where why can may shall not no".split())
# words that carry no search value in legal text (every section has them): they never count towards a match
_GENERIC = frozenset("section sections sec secs act acts code law laws rule rules india indian court courts case cases provision provisions article articles ss "
                     "scc scr air insc online ors anr supp".split())             # the last row: words of reporters' citations, which nearly every judgment holds
_CASE_STOP = frozenset({"v", "vs", "versus", "the", "of", "and", "anr", "ors", "another", "others", "in", "re", "etc"})
_TOK = re.compile(r"[a-z0-9]+")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_LOCK = threading.RLock()
_CACHE = {}


def _tok(text):
    return _TOK.findall((text or "").lower())


def _content_terms(tokens):
    """The words of a query that can match something: no stop words, no words every legal text has, no single letters (single digits stay), each once, in order."""
    return [t for t in dict.fromkeys(tokens) if t not in _STOP and t not in _GENERIC and (len(t) > 1 or t.isdigit())]


def _need(n):
    """How many of n query words a section or paragraph must hold: all of one or two, otherwise 60% (at least two)."""
    return n if n <= 2 else max(2, math.ceil(0.6 * n))


def _variants(term):
    """The word and its usual inflections (plural, -ed, -ing, a dropped final e), so that 'conditions' finds 'condition' and 'bribe' finds 'bribed' and 'bribing' (the BM25 index matches whole words only)."""
    out = {term}
    if term.isdigit() or len(term) < 4:
        return out
    derived = set()
    if term.endswith("ies") or term.endswith("ied"):
        derived.add(term[:-3] + "y")
    if term.endswith("es"):
        derived.add(term[:-2])
    if term.endswith("s") and not term.endswith("ss"):
        derived.add(term[:-1])
    if term.endswith("ed"):
        derived.update((term[:-2], term[:-1]))
    if term.endswith("ing") and len(term) > 5:
        derived.update((term[:-3], term[:-3] + "e"))
    for st in [x for x in (derived or {term}) if len(x) >= 3]:
        out.update((st, st + "s"))
        if st.endswith(("s", "x", "z", "ch", "sh")):
            out.add(st + "es")
        if st.endswith("e"):
            out.update((st + "d", st[:-1] + "ing"))
        elif st.endswith("y"):
            out.update((st[:-1] + "ies", st[:-1] + "ied"))
        else:
            out.update((st + "ed", st + "ing"))
    return out


def _covered(term_sets, token_set):
    """How many of the query words (each a set of spellings) the text holds."""
    return sum(1 for vs in term_sets if vs & token_set)


def _s(v):
    return None if v is None else str(v)


# ======================================================================================================================
# 1. reading the query
# ======================================================================================================================
_NUM_ONLY = re.compile(r"^\s*(?:sections?|secs?\.?|s\.?|u/s)?\s*(\d{1,3}[A-Za-z]{0,2})\s*$", re.I)
_CIT_SCC = re.compile(r"(?<![A-Za-z0-9])\(?((?:19|20)\d\d)\)?\s*(\d{1,2})\s*S\.?\s?C\.?\s?C\.?\s*(\d{1,4})(?![A-Za-z0-9])", re.I)
_CIT_SCR = re.compile(r"(?<![A-Za-z0-9])\[?((?:19|20)\d\d)\]?\s*(?:Suppl?\.?\s*)?(\d{1,3})\s*(?:Suppl?\.?\s*)?S\.?\s?C\.?\s?R\.?\s*(\d{1,4})(?![A-Za-z0-9])", re.I)
_CIT_INSC = re.compile(r"(?<![A-Za-z0-9])((?:19|20)\d\d)\s*[_ ]?\s*INSC\s*[_ ]?\s*(\d{1,5})(?![A-Za-z0-9])", re.I)
_CIT_AIR = re.compile(r"(?<![A-Za-z0-9])AIR\s*((?:19|20)\d\d)\s*SC\s*(\d{1,5})(?![A-Za-z0-9])", re.I)
_CIT_AIR_OLD = re.compile(r"(?<![A-Za-z0-9])((?:19|20)\d\d)\s*AIR\s*(\d{1,5})(?![A-Za-z0-9])", re.I)
_CIT_ONLINE = re.compile(r"(?<![A-Za-z0-9])((?:19|20)\d\d)\s*SCC\s*Online\s*([A-Za-z]{2,6})\s*(\d{1,5})(?![A-Za-z0-9])", re.I)
# a section reference with no Act next to it: "section 17", "ss. 3 and 4", "u/s 420"
_SECREF_ANY = re.compile(r"(?<![a-z0-9])(?:u\s*/\s*ss?|ss?\.|sections?|secs?\.?)\s*\d{1,4}[a-z]{0,2}(?:\s*\(\s*[0-9a-z]{1,4}\s*\))*"
                         r"(?:\s*(?:,|and|&|/|or)\s*\d{1,4}[a-z]{0,2}(?:\s*\(\s*[0-9a-z]{1,4}\s*\))*)*", re.I)


def citation_keys(text):
    """The citations a text holds, in comparable form: {('scc', year, volume, page), ('scr', year, volume, page), ('insc', year, number), ('air', year, page), ('online', year, court, number)}.
    A library judgment's citation field may hold several ('AIR 2016 SC 4774, (2016) 10 SCC 165'); a typed citation matches when its key is among them."""
    t = str(text or "")
    keys = set()
    for m in _CIT_SCC.finditer(t):
        keys.add(("scc", int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _CIT_SCR.finditer(t):
        keys.add(("scr", int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _CIT_INSC.finditer(t):
        keys.add(("insc", int(m.group(1)), int(m.group(2))))
    for rx in (_CIT_AIR, _CIT_AIR_OLD):
        for m in rx.finditer(t):
            keys.add(("air", int(m.group(1)), int(m.group(2))))
    for m in _CIT_ONLINE.finditer(t):
        keys.add(("online", int(m.group(1)), m.group(2).upper(), int(m.group(3))))
    return keys


def _typed_citation(q):
    """The first citation in the query as {'kind', 'key', 'year', 'text'} (kinds in the order they are tried: insc, scr, scc, air, online), else None."""
    for kind, rx in (("insc", _CIT_INSC), ("scr", _CIT_SCR), ("scc", _CIT_SCC), ("air", _CIT_AIR), ("air", _CIT_AIR_OLD), ("online", _CIT_ONLINE)):
        m = rx.search(q)
        if m:
            keys = citation_keys(m.group(0))
            if keys:
                key = sorted(keys)[0]
                return {"kind": kind, "key": key, "year": int(m.group(1)), "text": m.group(0).strip()}
    return None


def _section_regexes():
    """(number-then-Act, Act-then-number, {alias: code}, old codes), built from semantic_retrieval's own table of names so that the page reads "IPC 420" exactly as the answers do; adds lists ("sections 103 and 105 of the BNS")."""
    with _LOCK:
        hit = _CACHE.get("rx")
        if hit is not None:
            return hit
        import semantic_retrieval as SR
        acts = "|".join(re.escape(a) for a in sorted(SR._SECTION_ACT_ALIASES, key=len, reverse=True))
        num = SR._SECTION_NUM_PATTERN
        lst = rf"{num}(?:\s*(?:,|and|&|/|or)\s*{num})*"
        pre = r"(?:under\s+)?(?:sections?|secs?\.?|ss\.?|s\.|u\s*/\s*ss?)?\s*"
        after = re.compile(rf"(?<![A-Za-z0-9])(?:{pre})(?P<list>{lst})\s*(?:of\s+(?:the\s+)?)?(?P<act>{acts})(?![A-Za-z0-9])", re.I)
        before = re.compile(rf"(?<![A-Za-z0-9])(?P<act>{acts})\s*(?:{pre})(?P<list>{lst})(?![A-Za-z0-9])", re.I)
        built = (after, before, dict(SR._SECTION_ACT_ALIASES), frozenset(SR._OLD_CODE_ACTS))
        _CACHE["rx"] = built
        return built


def _detect_sections(q):
    """-> ([{'act': 'IPC'|'CrPC'|'BNS'|'BNSS'|'ITACT'|'NIACT', 'number': '420', 'ref': '420' | '318(4)'}...] in the order typed, at most MAX_NAMED_SECTIONS, [spans of the references in q])."""
    try:
        after, before, aliases, _old = _section_regexes()
    except Exception as exc:  # noqa: BLE001
        logger.warning("section patterns unavailable: %s", type(exc).__name__)
        return [], []
    found, spans, seen = [], [], set()
    for m in sorted([*after.finditer(q), *before.finditer(q)], key=lambda m: m.start()):
        act = aliases.get(m.group("act").lower())
        if not act:
            continue
        spans.append(m.span())
        for ref in re.findall(r"\d{1,4}[A-Za-z]{0,2}(?:\(\d+\))?", m.group("list")):
            number = re.sub(r"\(.*", "", ref).upper()
            if (act, number) in seen:
                continue
            seen.add((act, number))
            found.append({"act": act, "number": number, "ref": ref.upper()})
    return found[:MAX_NAMED_SECTIONS], spans


def _alias_sequences(act_ids):
    """Token sequences of the names the Act Directory knows the given Acts by ('prevention of corruption act', 'pc act', ...), longest first."""
    seqs = []
    try:
        import act_directory
        by_id = act_directory.load()["by_id"]
        for aid in act_ids:
            e = by_id.get(aid) or {}
            for n in list(e.get("aliases") or []) + [e.get("short"), e.get("name")]:
                s = act_directory._norm(n).split()
                if s:
                    seqs.append(s)
    except Exception:  # noqa: BLE001
        pass
    return sorted(seqs, key=len, reverse=True)


def _drop_sequences(tokens, seqs):
    """The tokens without the Acts' names; a year right after a name ('PMLA 2002', 'Prevention of Corruption Act, 1988') belongs to the name and goes with it."""
    out, i = [], 0
    while i < len(tokens):
        for s in seqs:
            if tokens[i:i + len(s)] == s:
                i += len(s)
                if i < len(tokens) and re.fullmatch(r"(?:18|19|20)\d\d", tokens[i]):
                    i += 1
                break
        else:
            out.append(tokens[i])
            i += 1
    return out


def _section_word_added(q, act_ids):
    """The query with the word 'section' put before a number that stands right next to the name of an Act the Directory found ('POCSO 19' -> 'POCSO section 19', '45 PMLA' -> 'section 45 PMLA'), so that the shelf
    reads it as that Act's section. A number that already follows the word 'section' (or 's.', 'u/s') is left alone, and so is a year ('PMLA 2002': only one to three digits are a section)."""
    seqs = _alias_sequences(act_ids)
    toks = [(m.group(0).lower(), m.start()) for m in re.finditer(r"[A-Za-z0-9]+", q)]
    low = [t for t, _ in toks]
    at, i = set(), 0
    while i < len(low):
        for seq in seqs:
            if low[i:i + len(seq)] == seq:
                j, k = i + len(seq), i - 1
                if j < len(low) and re.fullmatch(r"\d{1,3}[a-z]{0,2}", low[j]):
                    at.add(toks[j][1])
                if k >= 0 and re.fullmatch(r"\d{1,3}[a-z]{0,2}", low[k]) and not re.search(r"(?:sections?|secs?\.?|ss?\.?|u\s*/\s*ss?)\s*$", q[:toks[k][1]], re.I):
                    at.add(toks[k][1])
                i += len(seq) - 1
                break
        i += 1
    for pos in sorted(at, reverse=True):
        if not re.search(r"(?:sections?|secs?\.?|ss?\.?|u\s*/\s*ss?)\s*$", q[:pos], re.I):
            q = q[:pos] + "section " + q[pos:]
    return q


def parse_query(query):
    """What the query is. {'q': cleaned text, 'q_shelf': the text the Act shelf reads (a bare number next to an Act's name gets the word 'section'), 'tokens', 'terms': content words, 'has_words': a content word with a letter in it, 'rest_terms': content words left once
    the section references and the Acts' names are taken out (the words to search for), 'intent': one of INTENTS, 'number_only': '17' | None, 'sections': [{'act','number','ref'}], 'has_secref': bool,
    'citation': {'kind','key','year','text'} | None, 'acts': Act Directory entries NAMED in the query [{'id','short','how'}]}."""
    q = _CONTROL.sub(" ", str(query or ""))
    q = " ".join(q.split())[:MAX_QUERY_CHARS]
    out = {"q": q, "q_shelf": q, "tokens": _tok(q), "terms": [], "has_words": False, "rest_terms": [], "intent": "empty", "number_only": None, "sections": [], "has_secref": False, "citation": None, "acts": []}
    if not q:
        return out
    m = _NUM_ONLY.match(q)
    if m:
        out["number_only"] = m.group(1).upper()
    out["citation"] = _typed_citation(q)
    try:
        import act_directory
        out["acts"] = [a for a in act_directory.detect(q) if a.get("how") == "named"]
    except Exception:  # noqa: BLE001
        out["acts"] = []
    if out["acts"] and not out["citation"]:
        out["q_shelf"] = _section_word_added(q, [a["id"] for a in out["acts"]])
    qs = out["q_shelf"]
    out["sections"], spans = _detect_sections(qs)
    out["has_secref"] = bool(_SECREF_ANY.search(qs))
    out["terms"] = _content_terms(out["tokens"])
    out["has_words"] = any(not t.isdigit() for t in out["terms"])
    # the words that are left once the references and the Acts' names are taken out
    rest = qs.lower()
    for a, b in sorted([*spans, *(m.span() for m in _SECREF_ANY.finditer(rest))], reverse=True):
        rest = rest[:a] + " " + rest[b:]
    rest_tokens = _drop_sequences(_tok(rest), _alias_sequences([a["id"] for a in out["acts"]]))
    out["rest_terms"] = _content_terms(rest_tokens)
    if out["citation"]:
        out["intent"] = "citation"
    elif out["number_only"]:
        out["intent"] = "number"
    elif out["sections"] or (out["acts"] and out["has_secref"]):
        out["intent"] = "section"
    elif out["acts"] and not out["rest_terms"]:
        out["intent"] = "act"
    elif not out["has_words"]:
        out["intent"] = "nothing"                     # no word that can match anything: only generic words, single letters, bare numbers ("section", "u/s", "[2014] 8 S.C.R.")
    else:
        out["intent"] = "words"
    return out


# ======================================================================================================================
# 2. provisions
# ======================================================================================================================
_ACT_LABELS = {"BNS": "Bharatiya Nyaya Sanhita, 2023", "BNSS": "Bharatiya Nagarik Suraksha Sanhita, 2023", "ITACT": "Information Technology Act, 2000", "NIACT": "Negotiable Instruments Act, 1881",
               "IPC": "Indian Penal Code, 1860", "CrPC": "Code of Criminal Procedure, 1973"}
_SHORTS = {"BNS": "BNS", "BNSS": "BNSS", "ITACT": "IT Act", "NIACT": "NI Act", "IPC": "IPC", "CrPC": "CrPC"}
_NEXT_CHAPTER = re.compile(r"\n\s*(CHAPTER\s+[IVXLC]+)\s*\n\s*([A-Z][A-Z ,.'’&()\-]{3,200}?)\s*$")
_SCHEDULES = re.compile(r"\n\s*THE\s+FIRST\s+SCHEDULE\s*\n")
_GAZETTE_TAIL = re.compile(r"\n\s*DIWAKAR\s+SINGH\s*,\s*\n\s*Joint\s+Secretary.*$", re.S)


def _act_label(code):
    return _ACT_LABELS.get(code, code)


def _short(code):
    return _SHORTS.get(code, code)


def _tidy_library_text(text):
    """-> (text, next_chapter | None, trimmed | None): Recourse's chunk of a BNS / BNSS section sometimes carries more than the section, which is cut off and said so: the heading of the NEXT chapter that follows it ('CHAPTER III
    GENERAL EXCEPTIONS'), the Act's Schedules that BNSS section 531 is run together with, the Gazette's signature block and printer's line. Nothing inside the section is touched."""
    chapter, trimmed = None, []
    m = _SCHEDULES.search(text)
    if m:
        text = text[:m.start()]
        trimmed.append("the Act's Schedules and the printer's footer, which Recourse's copy runs together with this section (read the Schedules in the official text)")
    m = _GAZETTE_TAIL.search(text)
    if m:
        text = text[:m.start()]
        trimmed.append("the Gazette's signature block and printer's line")
    m = _NEXT_CHAPTER.search(text)
    if m:
        chapter = " ".join(f"{m.group(1)} {m.group(2)}".split())
        text = text[:m.start()]
    return text.rstrip(), chapter, ("; ".join(trimmed) if trimmed else None)


def _corresponds(code, base):
    """The old numbers the table of corresponding sections gives for a BNS / BNSS section: [{'act': 'IPC', 'section': '420', 'change': bool}]."""
    if code not in ("BNS", "BNSS"):
        return []
    try:
        import statute_concordance as C
        return [{"act": r["act"], "section": str(r["section"]), "change": bool(r.get("change"))} for r in (C.to_old(code, base) or [])]
    except Exception:  # noqa: BLE001
        return []


def _library_statute(code, number, how, score=None, cap=TEXT_CAP_ASKED, ref=None, mapped_from=None):
    """A provision card from Recourse's stored copy of BNS / BNSS / the IT Act / the NI Act, or None when that section is not held."""
    import retrieval
    chunks = retrieval._load_statute_chunks(code)
    if not chunks:
        return None
    base = str(number).split("(")[0].strip().upper()
    c = chunks.get(base)
    if c is None or not base[:1].isdigit() or not isinstance(c.get("text"), str):
        return None
    text, chapter, trimmed = _tidy_library_text(c["text"])
    url = c.get("source_url") if str(c.get("source_url") or "").startswith("http") else None
    cit = str(c.get("citation") or "").strip()
    return {"act": code, "act_name": _act_label(code), "short": _short(code), "section": base, "section_ref": ref if ref and ref != base else None, "title": str(c.get("title") or "").strip(), "text": text[:cap],
            "cut": len(text) > cap, "held": "library", "how": how, "caption": LIBRARY_CAPTION + (f" ({cit})" if cit else ""), "url": url, "omitted": False,
            "warning": known_gap(code, base, c["text"]), "next_chapter": chapter, "trimmed": trimmed, "mapped_from": mapped_from, "corresponds_to": _corresponds(code, base),
            "score": score}


def _shelf_provision(m, how=None, cap=TEXT_CAP_FOUND):
    """A provision card from an Act-shelf match (act_shelf.search's match dict)."""
    sh = m.get("shelf") or {}
    try:
        import answer_view
        cap_line = answer_view.shelf_caption(m) or {}
    except Exception:  # noqa: BLE001
        cap_line = {}
    text = m.get("text") or ""
    return {"act": m.get("act"), "act_name": m.get("act_display"), "short": m.get("act_display"), "section": str(m.get("section_number")), "section_ref": None, "title": (m.get("title") or "").strip(),
            "text": text[:cap], "cut": len(text) > cap, "held": "shelf", "how": how or m.get("retrieval") or "words",
            "caption": cap_line.get("text") or "Official text from India Code; not yet read by our reviewer", "url": cap_line.get("url") or sh.get("source_url"), "omitted": bool(sh.get("omitted")),
            "warning": None, "next_chapter": None, "trimmed": None, "mapped_from": None, "corresponds_to": [],
            "score": m.get("score")}


def _shelf_state():
    try:
        import act_shelf
        if not act_shelf.enabled():
            return {}
        return {k: v for k, v in act_shelf.load()["acts"].items() if v.get("ok")}
    except Exception:  # noqa: BLE001
        return {}


def _bm25(docs_tokens):
    n = len(docs_tokens)
    df, postings = {}, {}
    for i, toks in enumerate(docs_tokens):
        counts = {}
        for t in toks:
            counts[t] = counts.get(t, 0) + 1
        for t, f in counts.items():
            postings.setdefault(t, []).append((i, f))
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1.0 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    lens = np.array([len(t) for t in docs_tokens], dtype=float)
    return {"postings": postings, "idf": idf, "len": lens, "avg": float(lens.mean()) if n else 1.0, "sets": [set(t) for t in docs_tokens]}


def _bm25_rank(ix, term_sets, need, k=10):
    """[(doc index, score)] best first: documents that hold at least `need` of the query words (each a set of spellings)."""
    scores = {}
    for vs in term_sets:
        for t in vs:
            for i, f in ix["postings"].get(t, ()):
                denom = f + 1.5 * (1 - 0.75 + 0.75 * ix["len"][i] / (ix["avg"] or 1))
                scores[i] = scores.get(i, 0.0) + ix["idf"][t] * f * 2.5 / denom
    out = []
    for i, s in sorted(scores.items(), key=lambda kv: -kv[1]):
        if _covered(term_sets, ix["sets"][i]) >= need:
            out.append((i, s))
        if len(out) >= k:
            break
    return out


def _shelf_index(shelf):
    """BM25 over the shelf's sections (title and text), cached until the shelf is reloaded."""
    key = id(shelf)
    with _LOCK:
        hit = _CACHE.get("shelf_ix")
        if hit and hit[0] == key:
            return hit[1]
        docs, refs = [], []
        for aid, st in shelf.items():
            for c in st["ranked"]:
                docs.append(_tok((c.get("title") or "") + " " + (c.get("text") or "")))
                refs.append((aid, c))
        built = {"ix": _bm25(docs), "refs": refs} if docs else None
        _CACHE["shelf_ix"] = (key, built)
        return built


def _match_dict(st, c, how="words", score=None):
    try:
        import act_shelf
        return act_shelf._match(st, c, how, score)
    except Exception:  # noqa: BLE001
        return None


def _housekeeping(c):
    try:
        import act_shelf
        return act_shelf._housekeeping(c)
    except Exception:  # noqa: BLE001
        return False


def _statute_threshold():
    try:
        import semantic_retrieval as SR
        return SR.STATUTE_SIMILARITY_THRESHOLD
    except Exception:  # noqa: BLE001
        return 0.34


def _judgment_threshold():
    try:
        import semantic_retrieval as SR
        return SR.JUDGMENT_SIMILARITY_THRESHOLD
    except Exception:  # noqa: BLE001
        return 0.40


def _is_section_record(r):
    return r.get("type") == "statute" and str(r.get("section_number") or "")[:1].isdigit() and r.get("act") in ("BNS", "BNSS", "ITACT", "NIACT")


def _mapped_card(sec, new, ref, change):
    """The BNS / BNSS card for an old IPC / CrPC number, with what the table says."""
    note = f"{sec['act']} {sec['number']} corresponds to {new} {ref} in the official table of corresponding sections."
    if change:
        note += " The new provision was substantively changed; do not assume it reads the same."
    note += " " + TABLE_NOTE
    return {"act": sec["act"], "section": sec["number"], "new_act": new, "new_ref": ref, "change": bool(change), "note": note}


def named_provisions(parsed, shelf, notes, embed_fn=None):
    """The sections the query names: library sections (an old IPC / CrPC number through the table) and sections of the shelf Acts the Directory found in it. -> [cards]"""
    out, seen = [], set()

    def add(card):
        if card is not None and (card["act"], card["section"].upper()) not in seen:
            seen.add((card["act"], card["section"].upper()))
            out.append(card)

    try:
        import statute_concordance as C
        import retrieval
    except Exception as exc:  # noqa: BLE001
        logger.warning("named sections unavailable: %s", type(exc).__name__)
        return out
    for sec in parsed["sections"]:
        act, number = sec["act"], sec["number"]
        try:
            if act in ("IPC", "CrPC"):
                mapped = C.to_new(act, number)
                if mapped is None:
                    notes.append(f"{act} {number} is not in Recourse's table of corresponding sections. Check the number.")
                elif not mapped:
                    notes.append(f"Recourse's table of corresponding sections shows no section of the {'BNS' if act == 'IPC' else 'BNSS'} for {act} {number}: the old section has no successor in the table. "
                                 "Recourse does not hold the text of the old code.")
                for r in (mapped or [])[:3]:
                    new_act, new_ref = r["act"], str(r["section"])
                    card = _library_statute(new_act, new_ref, "named", 1.0, ref=new_ref, mapped_from=_mapped_card(sec, new_act, new_ref, r.get("change")))
                    if card is None:
                        notes.append(f"{act} {number} corresponds to {new_act} {new_ref}, which is not among the sections of the {_short(new_act)} that Recourse holds.")
                    add(card)
            else:
                card = _library_statute(act, number, "named", 1.0, ref=sec["ref"])
                if card is None:
                    held = retrieval._load_statute_chunks(act) or {}
                    n_held = len([k for k in held if str(k)[:1].isdigit()])
                    if act in ("ITACT", "NIACT"):
                        notes.append(f"Section {number} of the {_act_label(act)} is not one of the {n_held} sections of that Act that Recourse holds.")
                    else:
                        notes.append(f"The {_short(act)} has no section {number} in the text Recourse holds. Check the number.")
                add(card)
        except Exception as exc:  # noqa: BLE001
            logger.warning("named section lookup failed: %s", type(exc).__name__)
    ids = [a["id"] for a in parsed["acts"] if a["id"] in shelf]
    if ids:
        try:
            import act_shelf
            res = act_shelf.search(parsed["q_shelf"], [{"id": i} for i in ids], embed_fn=embed_fn or _no_embed)
            for m in res.get("matches") or []:
                if m.get("retrieval") in ("named", "implied", "cited"):
                    add(_shelf_provision(m, m.get("retrieval"), TEXT_CAP_ASKED))
            for aid, n in _missing_numbers(parsed["q_shelf"], ids, shelf):
                notes.append(f"The {shelf[aid].get('display') or aid} has no section {n} in the text Recourse holds. Check the number.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("shelf search failed: %s", type(exc).__name__)
    return out


def _missing_numbers(q, ids, shelf):
    """[(Act id, number)] for section numbers the query ties to a shelf Act that the Act does not have."""
    try:
        import act_shelf
        return [(aid, n) for n, kind, aid in act_shelf._attributions(q, ids) if kind == "act" and n not in shelf[aid]["by_num"]]
    except Exception:  # noqa: BLE001
        return []


def number_provisions(parsed, shelf):
    """A bare number ('17'): that section of every Act held."""
    out, num = [], parsed["number_only"]
    for code in ("BNS", "BNSS", "ITACT", "NIACT"):
        try:
            card = _library_statute(code, num, "number")
            if card is not None:
                out.append(card)
        except Exception:  # noqa: BLE001
            pass
    for aid, st in shelf.items():
        c = st["by_num"].get(num)
        if c is not None:
            m = _match_dict(st, c, "number")
            if m:
                out.append(_shelf_provision(m, "number", TEXT_CAP_ASKED))
    return out


def act_provisions(parsed, shelf, embed_fn, notes):
    """An Act named with no section: the shelf's own search for it (a very short Act gives every section)."""
    out = []
    ids = [a["id"] for a in parsed["acts"] if a["id"] in shelf]
    if not ids:
        return out
    try:
        import act_shelf
        res = act_shelf.search(parsed["q_shelf"], [{"id": i} for i in ids], embed_fn=embed_fn or _no_embed)
        for m in res.get("matches") or []:
            out.append(_shelf_provision(m, m.get("retrieval"), TEXT_CAP_FOUND))
    except Exception as exc:  # noqa: BLE001
        logger.warning("shelf search failed: %s", type(exc).__name__)
    return out[:MAX_PROVISIONS]


def word_provisions(terms, lex, sem, shelf, limit, only_acts=None):
    """Sections that hold the query's words (BM25; at least _need(n) of the n words, each spelled any usual way) and sections close in meaning (cosine over the statute threshold), fused by rank. Library and shelf
    results alternate so that neither crowds out the other. only_acts (Directory ids): the person named these Acts, so only their sections are searched (never the BNS or BNSS). -> [cards]"""
    if not terms or limit <= 0:
        return []
    term_sets = [_variants(t) for t in terms]
    need = _need(len(terms))
    lib = []
    lexical = [r for r in (lex or []) if _is_section_record(r) and _covered(term_sets, set(_tok(r.get("text")))) >= need]
    semantic = [r for r in (sem or []) if _is_section_record(r) and (r.get("score") or 0) >= _statute_threshold()]
    if only_acts:
        lexical, semantic = [], []
    fused, rec = {}, {}
    for rank, r in enumerate(lexical):
        fused[r["chunk_id"]] = fused.get(r["chunk_id"], 0.0) + 1.0 / (60 + rank + 1)
        rec[r["chunk_id"]] = [r, True, False]
    for rank, r in enumerate(semantic):
        fused[r["chunk_id"]] = fused.get(r["chunk_id"], 0.0) + 1.0 / (60 + rank + 1)
        e = rec.setdefault(r["chunk_id"], [r, False, False])
        e[2] = True
    for cid, _ in sorted(fused.items(), key=lambda kv: -kv[1]):
        r, by_words, by_meaning = rec[cid]
        card = _library_statute(r["act"], r["section_number"], "both" if by_words and by_meaning else "words" if by_words else "meaning", round(fused[cid], 5), cap=TEXT_CAP_FOUND)
        if card is not None:
            lib.append(card)
        if len(lib) >= limit:
            break
    sh = []
    ix = _shelf_index(shelf) if shelf else None
    if ix:
        for i, s in _bm25_rank(ix["ix"], term_sets, need, k=len(ix["refs"]) if only_acts else limit + 4):
            aid, c = ix["refs"][i]
            if _housekeeping(c) or (only_acts and aid not in only_acts):
                continue
            m = _match_dict(shelf[aid], c, "words", None)
            if m:
                sh.append(_shelf_provision(m, "words", TEXT_CAP_FOUND))
            if len(sh) >= limit:
                break
    out = []
    for pair in zip(*(lib, sh)) if lib and sh else ():
        out.extend(pair)
    n = min(len(lib), len(sh))
    out.extend(lib[n:] + sh[n:])
    return out[:limit]


def _no_embed(text):
    raise RuntimeError("meaning search is off")


# ======================================================================================================================
# 3. cases
# ======================================================================================================================
def _year_of(*texts):
    for t in texts:
        m = re.search(r"\b((?:18|19|20)\d\d)\b", str(t or ""))
        if m:
            return int(m.group(1))
    return None


_CIT_YEAR = re.compile(r"^\W*(?:AIR(?:ONLINE)?\s+)?((?:19|20)\d\d)\b|[(\[]\s*((?:19|20)\d\d)\s*[)\]]")


def _year_of_citation(cit):
    """The year a citation shows ('(2014) 8 SCC 273', '[1992] 1 S.C.R. 638', '2025 INSC 162', 'AIR 2014 SC 1863', '2025:CHC-AS:1826'); None for a case number ('Criminal Appeal No. 511 of 2022') or no citation."""
    t = str(cit or "").strip()
    if not t or re.match(r"(?i)^(?:civil|criminal|crl|r/|writ|w\.p|special leave)", t):
        return None
    m = _CIT_YEAR.search(t)
    return int(m.group(1) or m.group(2)) if m else None


def _court_of(cit):
    """'Supreme Court' or 'High Court' when the citation itself says so; None otherwise (never a guess)."""
    t = str(cit or "")
    if re.search(r"INSC|\bSCC\b(?!\s*OnLine)|S\.?C\.?R\b|AIR(?:ONLINE)?\s+\d{4}\s+SC\b|\bAIR\s+SC\b|SCC\s*OnLine\s+SC\b|LiveLaw\s*\(SC\)", t, re.I):
        return "Supreme Court"
    if re.search(r"\b\d{4}:[A-Z]{2,5}[:\-]|\bHC\b|High Court", t):
        return "High Court"
    return None


def _ik_search(title):
    return "https://indiankanoon.org/search/?formInput=" + urllib.parse.quote(re.sub(r"\s+", " ", str(title or "")).strip())


def library_cases():
    """The judgments of the reviewed library: [{'key','name','citation','url','year','court','cites'}], one per case name (cached)."""
    with _LOCK:
        if "library" in _CACHE:
            return _CACHE["library"]
        out, seen = [], set()
        try:
            import retrieval
            for key in list(retrieval._JUDGMENT_CHUNK_FILES):
                chunks = retrieval._load_judgment_chunks(key)
                if not chunks or not isinstance(chunks[0], dict):
                    continue
                c = chunks[0]
                name = str(c.get("case_name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                url = c.get("source_url") if str(c.get("source_url") or "").startswith("http") else None
                cit = str(c.get("citation") or "").strip() or None
                out.append({"key": key, "name": name, "citation": cit, "url": url, "year": _year_of_citation(cit), "court": _court_of(cit), "cites": citation_keys(cit)})
        except Exception as exc:  # noqa: BLE001
            logger.warning("library cases unavailable: %s", type(exc).__name__)
            return out                                    # a failed read is not remembered: the next search tries again
        _CACHE["library"] = out
        return out


_YEAR_TOKEN = re.compile(r"(?:18|19|20)\d\d")


def _name_tokens(text):
    """The words of a case name that tell cases apart: the title index's own canonical form (Govt = Government, U.P. = Uttar Pradesh, no 'v', 'of', 'Ors'), without a year ('... (2026)')."""
    try:
        import case_lookup
        toks = case_lookup._canon_tokens(text)
    except Exception:  # noqa: BLE001
        toks = [t for t in _tok(text) if t not in _CASE_STOP]
    return [t for t in toks if not _YEAR_TOKEN.fullmatch(t)]


def _neutral(case_id):
    m = re.match(r"^(\d{4})_INSC_(\d+)$", str(case_id or ""))
    return f"{m.group(1)} INSC {m.group(2)}" if m else None


def _clean_passage(text):
    try:
        import answer_view
        t = answer_view.clean_excerpt(text or "")
    except Exception:  # noqa: BLE001
        t = (text or "").strip()
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= EXCERPT_CAP else t[:EXCERPT_CAP].rstrip() + " ..."


def _para_label(pn):
    head = str(pn or "").split("_")[0]
    return head if head.isdigit() else None


def _case_card(title, year, citation, held, how, links, **extra):
    d = {"title": title, "year": year, "citation": citation, "held": held, "tier": TIER_LIBRARY_LABEL if held == "library" else TIER_INDEX_LABEL, "how": how, "links": links,
         "court": None, "scr_citation": None, "neutral": None, "date": None, "passages": [], "status": None}
    d.update(extra)
    return d


def _library_card(c, how):
    links = [{"label": "Read the judgment", "url": c["url"]}] if c.get("url") else [{"label": "Search for it on Indian Kanoon", "url": _ik_search(c["name"])}]
    return _case_card(c["name"], c.get("year"), c.get("citation"), "library", how, links, court=c.get("court"))


def _index_rows_by_scr(cit):
    """Index rows whose Supreme Court Reports citation equals the typed one ('[2014] 8 S.C.R. 128'). SQL narrows by the two ends; the exact comparison is done on the parsed citation, because LIKE '8 S.C.R. 128%'
    would also take '18 S.C.R. 1280'."""
    import case_lookup
    _kind, year, vol, page = cit["key"]
    conn = case_lookup._index_conn()
    try:
        rows = conn.execute("SELECT case_id, title, court, decision_date, citation, source_url, n_chunks, source FROM cases WHERE citation LIKE ? AND citation LIKE ?",
                            (f"%{year}%", f"%S.C.R.%{page}%")).fetchall()
    finally:
        conn.close()
    return [case_lookup._row_to_case(r) for r in rows if cit["key"] in citation_keys(r[4])]


def _status(cards):
    """The Overruled Register / checker verdict for each case card, in place: card['status'] = {'source', 'text', 'detail'} (the same function and the same short sentences as the lawyers' table of authorities)."""
    try:
        from register_hooks import case_status
    except Exception:  # noqa: BLE001
        case_status = None
    try:
        from authorities_table import SHORT_STATUS as short
    except Exception:  # noqa: BLE001
        short = {"not_checked": NOT_CHECKED}
    for c in cards:
        st = {"source": "not_checked", "note": None}
        if case_status is not None:
            try:
                st = case_status(c["title"], c.get("year"), c.get("scr_citation") or c.get("citation")) or st
            except Exception:  # noqa: BLE001
                pass
        src = st.get("source") or "not_checked"
        note = st.get("note")
        if src in ("register", "card") and note:
            c["status"] = {"source": src, "text": note, "detail": None}
        elif src == "off":
            c["status"] = {"source": "off", "text": note or "Register checks are switched off on this site.", "detail": None}
        else:
            c["status"] = {"source": src if src in ("card_quiet", "not_checked") else "not_checked", "text": short.get(src) or short.get("not_checked") or NOT_CHECKED, "detail": note if src == "card_quiet" else None}


def _merge_index_row(card, row):
    card["neutral"] = card.get("neutral") or _neutral(row["case_id"])
    card["scr_citation"] = card.get("scr_citation") or (row.get("citation") or None)
    card["date"] = card.get("date") or row.get("decision_date")


def case_cards(parsed, lex=None, sem=None, notes=None):
    """-> (cases, mentions): cases found by their citation or their name (library first), and library judgments whose paragraphs hold the words (not by name)."""
    notes = notes if notes is not None else []
    q, cit = parsed["q"], parsed["citation"]
    lib = library_cases()
    cases, by_name = [], {}

    def lib_card(c, how):
        card = by_name.get(c["name"])
        if card is None:
            card = _library_card(c, how)
            by_name[c["name"]] = card
            cases.append(card)
        return card

    def twin(title, year):
        """The library case an index row is: the same party names and the same year (a year apart is allowed: a citation's year is the year of the report, which may follow the decision)."""
        ntok = frozenset(_name_tokens(title))
        for c in lib:
            if frozenset(_name_tokens(c["name"])) == ntok and c.get("year") is not None and year is not None and abs(c["year"] - year) <= 1:
                return c
        return None

    # 1. the library, by citation or by every word of the name
    if cit:
        for c in lib:
            if cit["key"] in c["cites"]:
                lib_card(c, "citation")
    elif not parsed["acts"]:
        qn = _name_tokens(q)
        if qn and not parsed["number_only"]:
            for c in lib:
                if all(t in set(_name_tokens(c["name"])) for t in qn):
                    lib_card(c, "name")
    # 2. the Supreme Court title index
    try:
        import case_lookup
        found, exact = [], True
        if cit and cit["kind"] == "insc":
            row = case_lookup.get_case(f"{cit['year']}_INSC_{cit['key'][2]}")
            found = [row] if row else []
        elif cit and cit["kind"] == "scr":
            found = _index_rows_by_scr(cit)
        elif not cit and not parsed["acts"] and 1 <= len(_name_tokens(q)) <= 8 and not parsed["number_only"]:
            r = case_lookup.search_cases_detailed(q, limit=10)
            found, exact = r["cases"], r["exact"]
        added_close = False
        for row in found:
            title = case_lookup.clean_title(row["title"])
            year = _year_of(row.get("decision_date"))
            c = twin(title, year)
            if c is not None:
                _merge_index_row(lib_card(c, "citation" if cit else "name"), row)
                continue
            card = next((x for x in cases if x["held"] == "index" and x["year"] == year and frozenset(_name_tokens(x["title"])) == frozenset(_name_tokens(title))), None)
            if card is not None:
                continue
            cases.append(_case_card(title, year, row.get("citation") or None, "index", "close" if not exact else ("citation" if cit else "name"),
                                    [{"label": "Search for it on Indian Kanoon", "url": _ik_search(title)}], court=row.get("court"), neutral=_neutral(row["case_id"]), date=row.get("decision_date")))
            added_close = added_close or not exact
        if added_close:
            notes.append(CLOSE_NOTE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("case title index unavailable: %s", type(exc).__name__)
        notes.append("The Supreme Court title index is not available right now.")
    for card in cases:
        if card["held"] == "index" and card.get("scr_citation") is None and card.get("citation"):
            card["scr_citation"] = card["citation"]
    # 3. paragraphs of the library judgments that hold the words
    mentions = []
    if parsed["intent"] == "words" and parsed["rest_terms"]:
        term_sets = [_variants(t) for t in parsed["rest_terms"]]
        need = _need(len(parsed["rest_terms"]))
        sem_ok = [r for r in (sem or []) if r.get("type") == "judgment" and (r.get("score") or 0) >= _judgment_threshold()]
        hits = {}
        rec = {}
        for rank, r in enumerate(r for r in (lex or []) if r.get("type") == "judgment" and _covered(term_sets, set(_tok(r.get("text")))) >= need):
            hits[r["chunk_id"]] = hits.get(r["chunk_id"], 0.0) + 1.0 / (60 + rank + 1)
            rec[r["chunk_id"]] = r
        for rank, r in enumerate(sem_ok):
            hits[r["chunk_id"]] = hits.get(r["chunk_id"], 0.0) + 1.0 / (60 + rank + 1)
            rec.setdefault(r["chunk_id"], r)
        by_lib = {c["name"]: c for c in lib}
        for cid, _ in sorted(hits.items(), key=lambda kv: -kv[1]):
            r = rec[cid]
            name = r.get("case_name")
            card = by_name.get(name) or next((m for m in mentions if m["title"] == name), None)
            if card is None:
                c = by_lib.get(name)
                if c is None or len(mentions) >= MAX_MENTIONS:
                    continue
                card = _library_card(c, "passage")
                mentions.append(card)
            if len(card["passages"]) < MAX_PASSAGES_PER_CASE:
                card["passages"].append({"paragraph": _para_label(r.get("paragraph_number")), "text": _clean_passage(r.get("text"))})
    cases, mentions = cases[:MAX_CASES], mentions[:MAX_MENTIONS]
    _status(cases + mentions)
    return cases, mentions


# ======================================================================================================================
# 4. the wider search
# ======================================================================================================================
def wider(parsed, sci_fn=None):
    """{'available': bool, 'items': [...], 'as_of': ..., 'note': str|None, 'label': ..., 'tier': ...}: the sci-search service's passages, each with its register verdict; never raises."""
    q = parsed["q"]
    out = {"available": False, "items": [], "as_of": None, "note": None, "label": WIDER_LABEL, "tier": TIER_WIDER_LABEL}
    if parsed["intent"] in ("citation", "number") or not parsed["terms"]:
        out["note"] = WIDER_NEEDS_WORDS
        return out
    try:
        import sci_search_tier as T
        fn = sci_fn or (lambda text: T.search(text, timeout=float(os.environ.get("SEARCH_WIDER_TIMEOUT", "10") or 10), k=12, label="search_page"))
        if not sci_fn and not T._env("SCI_SEARCH_URL"):
            out["note"] = WIDER_UNAVAILABLE
            return out
        found = fn(q)
        if not found or not isinstance(found.get("results"), list):
            out["note"] = WIDER_UNAVAILABLE
            return out
        res = found["results"]
        flags = T._flags(res)
        try:
            from authorities_table import SHORT_STATUS as short
        except Exception:  # noqa: BLE001
            short = {"not_checked": NOT_CHECKED, "card_quiet": "No adverse later judgment found by our automatic check (silence, not a finding)."}
        items, seen = [], set()
        for r, f in zip(res, flags):
            if r.get("name_to_review") or not r.get("case_name") or r.get("doc") in seen:
                continue
            seen.add(r.get("doc"))
            src, note = f.get("source") or "none", f.get("note")
            if src in ("register", "card") and note:
                status = {"source": src, "text": note}
            elif src == "card_quiet":
                status = {"source": src, "text": short.get("card_quiet") or NOT_CHECKED}
            else:
                status = {"source": "not_checked", "text": short.get("not_checked") or NOT_CHECKED}
            link = r.get("link") if str(r.get("link") or "").startswith(("http://", "https://")) else None
            items.append({"title": r["case_name"], "date": r.get("date"), "year": _year_of(r.get("date")), "paragraph": _s(r.get("paragraph")), "link": link, "link_kind": _s(r.get("link_kind")) if link else None,
                          "excerpt": _clean_passage(r.get("text")), "status": status})
            if len(items) >= MAX_WIDER:
                break
        out.update(available=True, items=items, as_of=found.get("as_of"))
        if not items:
            out["note"] = "The wider search found no passage for these words."
    except Exception as exc:  # noqa: BLE001
        logger.warning("wider search failed: %s", type(exc).__name__)
        out["note"] = WIDER_UNAVAILABLE
    return out


# ======================================================================================================================
# 5. the Acts the query names
# ======================================================================================================================
def act_cards(parsed, shelf):
    """One card for each Act the Directory found in the query: whether Recourse holds its text, how many sections, and where the official text is. [{'id','name','short','held','sections','loaded','url','url_verified','lines'}]"""
    out = []
    try:
        import act_directory
        d = act_directory.load()
        for a in parsed["acts"]:
            e = d["by_id"].get(a["id"]) or {}
            url, verified = act_directory.link_for(e, d["fallback_url"])
            st = shelf.get(a["id"])
            loaded = None
            if st:
                try:
                    import act_shelf
                    loaded = act_shelf.loaded_label(st.get("loaded_on")) or None
                except Exception:  # noqa: BLE001
                    loaded = None
            lines = [t for t in (act_directory._reviewed_text(e, "status"), act_directory._reviewed_text(e, "appeal")) if t]
            out.append({"id": a["id"], "name": e.get("name") or a["short"], "short": a["short"], "held": bool(st), "sections": len(st["ranked"]) if st else None, "loaded": loaded,
                        "whole": bool(st and st.get("whole")), "url": url, "url_verified": bool(verified), "lines": lines})
    except Exception as exc:  # noqa: BLE001
        logger.warning("act cards failed: %s", type(exc).__name__)
    return out


# ======================================================================================================================
# 6. the search
# ======================================================================================================================
def scope():
    """What a library search covers, counted from the files (for the page's one-line description)."""
    out = {"statutes": [], "shelf": [], "library_cases": len(library_cases()), "indexed_cases": None}
    try:
        import retrieval
        for code in ("BNS", "BNSS", "ITACT", "NIACT"):
            ch = retrieval._load_statute_chunks(code)
            if ch:
                out["statutes"].append({"act": code, "name": _act_label(code), "sections": len([k for k in ch if str(k)[:1].isdigit()])})
    except Exception:  # noqa: BLE001
        pass
    for aid, st in _shelf_state().items():
        out["shelf"].append({"act": st.get("display") or aid, "sections": len(st.get("ranked") or [])})
    try:
        import case_lookup
        out["indexed_cases"] = case_lookup.index_size()
    except Exception:  # noqa: BLE001
        pass
    return out


def warm():
    """Load what the first search would otherwise load (the corpus, its word index, the shelf, the library list). Never raises; safe to run on a background thread."""
    try:
        import semantic_retrieval as SR
        SR._load_corpus_embeddings()
        SR.lexical_search("warm", top_k=1)
    except Exception:  # noqa: BLE001
        pass
    try:
        _section_regexes()
        library_cases()
        shelf = _shelf_state()
        if shelf:
            _shelf_index(shelf)
    except Exception:  # noqa: BLE001
        pass


def _meaning_on(meaning):
    if meaning is not None:
        return bool(meaning)
    return (os.environ.get("SEARCH_MEANING") or "on").strip().strip("\"'").lower() not in ("off", "0", "false", "no")


def _embed_query(text):
    """The query as a voyage-law-2 vector (the model the corpus and the Act shelf were embedded with); the cost is logged under its own label."""
    import voyageai
    import semantic_retrieval as SR
    resp = voyageai.Client(api_key=SR._resolve_voyage_api_key(), max_retries=1, timeout=15).embed([text], model=SR.MODEL, input_type="query")
    try:
        import cost_log
        cost_log.note_voyage("search_page_query_embed", SR.MODEL, getattr(resp, "total_tokens", 0))
    except Exception:  # noqa: BLE001
        pass
    return resp.embeddings[0]


def _corpus_meaning(qv, top_k=60):
    """Corpus records (statutes and judgment paragraphs) by cosine to the query vector, best first, each with 'score'."""
    import semantic_retrieval as SR
    corpus = SR._load_corpus_embeddings()
    if corpus is None:
        return None
    scores = corpus["matrix"] @ qv
    out = []
    for i in np.argsort(scores)[::-1][:top_k]:
        r = dict(corpus["records"][int(i)])
        r.pop("embedding", None)
        r["score"] = float(scores[int(i)])
        out.append(r)
    return out


def _empty_result(parsed, mode):
    return {"q": parsed["q"], "mode": mode if mode in MODES else "library", "intent": parsed["intent"], "acts": [], "provisions": [], "cases": [], "mentions": [], "wider": None, "suggestions": [], "elsewhere": [],
            "notes": [], "meaning_used": False, "scope_note": SCOPE_NOTE, "hint": None}


def number_suggestions(parsed):
    """A bare number is also a section of the old codes: [{'label','query'}] for 'IPC 302' / 'CrPC 438' when the table of corresponding sections has that number, so that the person can ask for the old section."""
    import statute_concordance as C
    out, n = [], parsed["number_only"]
    for code, name in (("IPC", "Indian Penal Code, 1860"), ("CrPC", "Code of Criminal Procedure, 1973")):
        if C.to_new(code, n) is not None:                 # None: not in the table; [] (a section with no successor) is in it
            out.append({"label": f"{code} {n} ({name})", "query": f"{code} {n}"})
    return out


def _elsewhere(parsed):
    if not parsed["q"] or parsed["intent"] == "empty":
        return []
    return [{"label": "Search these words on Indian Kanoon", "url": _ik_search(parsed["q"])}]


def _guard(sink, message, fn, *args, default=None, **kw):
    """Run one part of a search; if it fails, log the kind of failure (never the query), add `message` to the list `sink` and give `default`, so that the other parts still answer."""
    try:
        return fn(*args, **kw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s failed: %s", getattr(fn, "__name__", "part"), type(exc).__name__)
        if message:
            sink.append(message)
        return default


PART_DOWN = "Part of the search could not be completed just now."


def search(query, mode="library", *, meaning=None, embed_fn=None, sci_fn=None):
    """The whole result for one search: {'q','mode','intent','acts','provisions','cases','mentions','wider','suggestions','elsewhere','notes','meaning_used','scope_note','hint'}. Never raises: a failing part is left out with a note.
    embed_fn(text) -> vector and sci_fn(text) -> sci-search reply replace the Voyage call and the wider-search service (tests)."""
    parsed = parse_query(query)
    res = _empty_result(parsed, mode)
    if not parsed["q"]:
        res["hint"] = "Type a section (for example \"section 17 PC Act\" or \"IPC 420\"), a case name, a citation or a few words."
        return res
    res["elsewhere"] = _elsewhere(parsed)
    if res["mode"] == "wider":
        res["wider"] = wider(parsed, sci_fn)
        return res
    if parsed["intent"] == "nothing":
        res["hint"] = _nothing_hint(parsed)
        return res
    try:
        shelf = _guard(res["notes"], None, _shelf_state, default={})
        intent, notes = parsed["intent"], res["notes"]
        res["acts"] = _guard(notes, None, act_cards, parsed, shelf, default=[])
        scoped = [a["id"] for a in parsed["acts"]]
        terms = parsed["rest_terms"]
        # the words stage (sections that hold the words, passages that hold them) and, when it is on, the query's meaning vector, once, for the corpus and for the shelf
        qv, sem, lex = None, None, []
        if intent == "words" or (intent in ("section", "act") and terms):
            def lexical():
                import semantic_retrieval as SR
                return SR.lexical_search(" ".join(sorted({v for t in terms for v in _variants(t)})), top_k=400) or []
            lex = _guard(notes, "Part of the library could not be searched just now.", lexical, default=[])
            if _meaning_on(meaning):
                def vector():
                    v = np.array((embed_fn or _embed_query)(parsed["q"]), dtype=float)
                    return v, _corpus_meaning(v)
                qv, sem = _guard(notes, None, vector, default=(None, None))
                if sem is None:
                    qv = None
                    notes.append("Meaning search was not available just now; these are matches on the words you typed.")
                else:
                    res["meaning_used"] = True
        shelf_embed = (lambda _t: qv) if qv is not None else _no_embed
        if intent == "citation":
            res["cases"], res["mentions"] = _guard(notes, PART_DOWN, case_cards, parsed, notes=notes, default=([], []))
        elif intent == "number":
            res["provisions"] = _guard(notes, PART_DOWN, number_provisions, parsed, shelf, default=[])
            res["suggestions"] = _guard(notes, None, number_suggestions, parsed, default=[])
        elif intent == "section":
            res["provisions"] = _guard(notes, PART_DOWN, named_provisions, parsed, shelf, notes, shelf_embed, default=[])
            if terms:
                have = {(p["act"], p["section"].upper()) for p in res["provisions"]}
                more = _guard(notes, PART_DOWN, word_provisions, terms, lex, sem, shelf, MAX_EXTRA_WITH_SECTION + len(have), only_acts=scoped or None, default=[])
                res["provisions"] += [p for p in more if (p["act"], p["section"].upper()) not in have][:MAX_EXTRA_WITH_SECTION]
        elif intent == "act":
            res["provisions"] = _guard(notes, PART_DOWN, act_provisions, parsed, shelf, shelf_embed, notes, default=[])
        else:
            if scoped:                                      # the person named an Act: its own sections (the shelf's search by meaning and pointers first, then its sections that hold the words), never the BNS or BNSS
                found = _guard(notes, PART_DOWN, act_provisions, parsed, shelf, shelf_embed, notes, default=[]) + _guard(notes, PART_DOWN, word_provisions, terms, lex, sem, shelf, MAX_PROVISIONS, only_acts=scoped, default=[])
                seen = set()
                for p in found:
                    if (p["act"], p["section"].upper()) not in seen:
                        seen.add((p["act"], p["section"].upper()))
                        res["provisions"].append(p)
            else:
                res["provisions"] = _guard(notes, PART_DOWN, word_provisions, terms, lex, sem, shelf, MAX_PROVISIONS, default=[])
            res["cases"], res["mentions"] = _guard(notes, "The case list could not be searched just now.", case_cards, parsed, lex=lex, sem=sem, notes=notes, default=([], []))
        res["provisions"] = res["provisions"][:MAX_PROVISIONS]
        if any(p["act"] in ("BNS", "BNSS") for p in res["provisions"]):
            notes.append(BNS_COMPARED_NOTE)
        if any(p.get("mapped_from") or p.get("corresponds_to") for p in res["provisions"]):
            notes.append(TABLE_NOTE)
        for a in res["acts"]:
            if not a["held"]:
                notes.append(f"Recourse does not hold the text of the {a['short']}, so no section of it is shown. The official text is linked below.")
        if not (res["provisions"] or res["cases"] or res["mentions"] or res["acts"] or res["suggestions"]):
            res["hint"] = _nothing_hint(parsed)
        elif intent == "act" and res["acts"] and not res["provisions"] and res["acts"][0]["held"]:
            res["hint"] = "Add a section number or a few words to look inside this Act, for example \"section 3\" or a word from the section you want."
    except Exception as exc:  # noqa: BLE001
        logger.warning("search failed: %s", type(exc).__name__)
        res["notes"].append("The search could not be completed just now.")
    return res


def _nothing_hint(parsed):
    intent = parsed["intent"]
    if not parsed["tokens"]:
        return "The search reads English words and numbers. Try the section number with the Act's name (\"BNSS 187\"), a case name or a citation."
    if intent == "nothing":
        return "Type a few more words: a section with the Act's name (\"section 17 PC Act\"), a case name, a citation or the subject you are looking for."
    if intent == "citation":
        return ("Recourse finds a judgment by its SCC or AIR citation only when it is in the reviewed library. The Supreme Court index is searched by neutral citation (2014 INSC 463) or by Supreme Court Reports "
                "citation ([2014] 8 S.C.R. 128). Try the case name.")
    if intent in ("section", "number"):
        return "Check the section number and the name of the Act, for example \"BNSS 187\", \"IPC 420\" or \"section 17 PC Act\"."
    if len(parsed["terms"]) > 3:
        return "Nothing matched. Try fewer words, the section number with the Act's name (\"section 17 PC Act\"), both party names of a case, or a citation such as (2014) 8 SCC 273."
    return "Nothing matched in what Recourse holds. Try the Act's name with the section number, both party names of a case, or different words."
