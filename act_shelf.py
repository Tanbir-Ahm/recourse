"""
act_shelf.py -- the Act shelf at answer time.  Added 2026-10-16 (STATUTE_COVERAGE_PLAN.md step 2, research repository).

WHAT IT IS.  A few Acts whose full text Recourse does not hold in its BNS/BNSS library are loaded from India Code (build_act_chunks.py: checked against India Code's own PDF), embedded with voyage-law-2
(embed_act_shelf.py) and kept in act_shelf/ next to this file.  When the Act Directory (act_directory.py) spots one of them in a question, this module hands the answer model the sections of that Act
that bear on the question, labelled with the Act's name, so that it need not (and, by the Hard rules, must not) answer from memory.

WHAT TRIGGERS IT, AND WHAT DOES NOT.  Only ACT_SHELF=on (default: off, and then NOTHING in the site changes) and only an Act the Directory found in the question, by name or by one of its listed phrases.
A question that never names the Act gets no shelf text, as before.  (Searching the shelf for every question was tried and does not work: act_shelf/EVAL_NOTES.md.)

HOW SECTIONS ARE CHOSEN (all by code; the numbers behind each choice are in act_shelf/EVAL_NOTES.md):
  1. sections the question names ("section 45 of the PMLA", "PMLA s.45", "sections 3 and 4 of POCSO"): only when the Act's name stands next to the number (a "section 438 CrPC" is not ours), at most 3;
  2. pointers (act_shelf/manifest.json, per Act): everyday phrases that the statute never uses but means ("anticipatory bail" = "section 438 of the Code not to apply"), at most 2;
  3. the sections whose meaning is closest to the question: voyage-law-2 cosine, ranked within the Act, 5 sections for one Act (3 each for two), none scoring under FLOOR, and no more characters in all than
     MAX_CHARS (named and pointed sections always come; the very first section of an Act is exempt from the cap; a section is never cut).
  A very short Act (the manifest says "whole_act": true, and the code checks that the Act is under WHOLE_ACT_MAX_CHARS characters: the Muslim Women (Protection of Rights on Marriage) Act, 2019 has 8 sections
  and about 3,300 characters, the Prevention of Damage to Public Property Act, 1984 has 7 and about 3,800) is handed over WHOLE, in the Act's own order, whatever the question: for such an Act the question
  "which section?" is not worth asking, and the sections a search by meaning dropped for a 24-question test (2026-10-17) were the ones that fix the Act's reach: the date it came into force and the saving clause.
  Nothing is handed over on a stale embedding (the sha256 of the section text is checked), a missing file, or an Act whose text did not pass its PDF check: that Act is then simply "not held".

WHAT THE TEXT IS.  India Code's text of the Act, "machine_checked": its sections equal the PDF's arrangement of sections and every word occurs in the PDF; a person has not read it.  The page and the notice say so.
It is India Code's database text, which can differ from the printed Act in punctuation (see the manifest's corrections).

Never raises into an answer: every public function returns an empty result on bad input, a missing file or any failure.

Public: mode(), enabled(), available(act_id), loaded_on(act_id), loaded_label(act_id), display_names(), name_patterns(), search(question, acts, current_message=None, embed_fn=None), held_state(matches, acts),
        shelf_ids(matches), load(), named_sections(text, act_ids), other_numbers(text, act_ids), implied_sections(text, act_ids), section_numbers_in(text), xref_enabled(), cited_sections(st, num).
"""
import datetime
import hashlib
import json
import os
import re
import threading

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SHELF_DIR = os.path.join(HERE, "act_shelf")
MODEL = "voyage-law-2"             # the model the sections were embedded with; the question is embedded with the same one (semantic_retrieval.MODEL)
TOP_K_ONE = 5                      # sections by meaning for a question that draws one shelf Act ...
TOP_K_TWO = 3                      # ... and for each of two
FLOOR = 0.22                       # cosine under which a section is not handed over (act_shelf/EVAL_NOTES.md: scores are compressed inside one Act, so no high threshold)
MAX_CHARS = 14000                  # characters of statute text handed over for one question (shared by the Acts; named and pointed sections always come); the first section of an Act is exempt. 18,000 and 14,000 handed the marked section over equally often on the test questions (28 of 29), 12,000 did not (27)
MAX_NAMED = 3
MAX_POINTED = 2
MAX_CITED = 2                      # sections handed over because a section the person asked about cites them (SECTION_XREF), at most this many for one Act
CITED_MAX_CHARS = 4000             # a cited section longer than this is not added (a section is never cut): the cited sections of the nine Acts are mostly short, 1,107 characters for section 13 of the PC Act
MAX_FANOUT = 2                     # a section that cites MORE than this many other sections of its Act (a rule-making power, a list of offences, section 19 of the PC Act with its four) is not followed at all: all or none, so the page never shows two of four as if they were all
WHOLE_ACT_MAX_CHARS = 6000         # a manifest entry may say "whole_act": true only for an Act this short (sections that are not omitted, in all); a longer Act with that flag is NOT held, so a slip in the manifest cannot hand over a long Act in full
MIN_MEANING = 2                    # a question that names sections still gets this many by meaning, when any clears the floor
WINDOW = 45                        # characters either side of a section number in which the Act's name must START (after the number) or END (before it): 'section 45 of the PMLA', 'PMLA section 45'
NAME_ROOM = 110                    # how far past WINDOW a name may run: the longest name of an Act, the SC/ST Act's full title with its short name, is under 100 characters (until 2026-10-17 the whole name had to fit inside WINDOW, which no official title of a long-named Act does)
GOOD_STATUS = ("machine_checked", "reviewed")
# Housekeeping sections: they amend ANOTHER enactment or only repeal/save. Never ranked by meaning (staging 2026-10-17: PC Act s.29, "Amendment of the Ordinance 38 of 1944", ranked 2nd for a bribery question,
# ahead of s.7, the offence), but still handed over when a question NAMES them by number. 'Amendment of Schedule' (UAPA s.35, a live power over the list of terrorist organisations) is NOT in this class.
_HOUSEKEEPING = re.compile(r"^\s*(?:amendments?\s+of\s+(?:the\s+)?(?:[A-Z][\w()'.,-]*\s+)*?(?:Ordinance|Act|Code|Acts|Sanhita)\b.*|repeals?(?:\s+and\s+savings?)?|savings?|repealed|repeal\s+and\s+savings?)\W*$", re.I)
_STATE = {}


def _housekeeping(c):
    """True for a section that only amends another enactment or repeals/saves (see _HOUSEKEEPING)."""
    return bool(_HOUSEKEEPING.match(str(c.get("title") or "")))
_LOCK = threading.Lock()


def mode():
    """'on' or 'off' (default), from ACT_SHELF.  Quotation marks around the value are ignored."""
    v = (os.environ.get("ACT_SHELF") or "").strip().strip("\"'").strip().lower()
    return "on" if v == "on" else "off"


def enabled():
    return mode() == "on"


def text_sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _norm(text):
    t = (text or "").lower().replace("’", "'")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _flex(phrase):
    """A regex for a phrase: its words, in order, joined by anything that is not a letter or a digit, whole words only ('money laundering' matches 'Money-laundering')."""
    words = _norm(phrase).split()
    if not words:
        return None
    return re.compile(r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(re.escape(w) for w in words) + r"(?![a-z0-9])", re.IGNORECASE)


# ----- loading ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def manifest(path=None):
    """The manifest's Acts, cached ({key: entry}); {} on any failure.  Small: names and pointers can be read without the embeddings."""
    base = os.path.abspath(path or SHELF_DIR)
    st = _STATE.get(("manifest", base))
    if st is not None:
        return st
    try:
        data = _read_json(os.path.join(base, "manifest.json"))
        out = {e["key"]: e for e in data.get("acts", []) if isinstance(e, dict) and e.get("key") and e.get("code")}
    except Exception:  # noqa: BLE001
        out = {}
    _STATE[("manifest", base)] = out
    return out


def _alias_patterns(entry):
    """The names a question or an answer may use for the Act: the Act Directory's aliases and short name (one source of truth), the manifest's display name, short name, full name and answer_names."""
    names = [entry.get("display"), entry.get("short"), entry.get("name")] + list(entry.get("answer_names") or [])      # answer_names: other ways lawyers write the Act's name ("UA(P) Act"); they do not make the Directory detect anything
    try:
        import act_directory
        d = act_directory.load()["by_id"].get(entry["key"]) or {}
        names += list(d.get("aliases") or []) + [d.get("short"), d.get("name")]
    except Exception:  # noqa: BLE001
        pass
    seen, out = set(), []
    for n in names:
        key = _norm(n)
        if key and key not in seen:
            seen.add(key)
            out.append(_flex(n))
    return [p for p in out if p is not None]


def _load_act(entry, embeddings, base):
    key = entry["key"]
    st = {"key": key, "code": entry["code"], "name": entry.get("name"), "short": entry.get("short"), "display": entry.get("display") or entry.get("short") or entry.get("name"), "citation": entry.get("citation"),
          "loaded_on": entry.get("loaded_on"), "pdf_as_on": entry.get("pdf_as_on"), "text_status": entry.get("text_status"), "pointers": [], "ok": False, "problems": [],
          "by_num": {}, "ranked": [], "matrix": None, "whole": False}
    if entry.get("text_status") not in GOOD_STATUS:
        st["problems"].append(f"text_status is {entry.get('text_status')!r}: the Act's text did not pass its PDF check")
        return st
    if not entry.get("loaded_on"):
        st["problems"].append("no loaded_on date")
        return st
    try:
        chunks = _read_json(os.path.join(base, f"{key}.json"))
    except Exception as exc:  # noqa: BLE001
        st["problems"].append(f"the section file cannot be read: {type(exc).__name__}")
        return st
    if not isinstance(chunks, list) or len(chunks) != entry.get("sections_loaded"):
        st["problems"].append(f"the section file holds {len(chunks) if isinstance(chunks, list) else '?'} sections, the manifest says {entry.get('sections_loaded')}")
        return st
    by_num, ranked, vectors, stale = {}, [], [], []
    for c in chunks:
        if not isinstance(c, dict) or not c.get("section_number") or not isinstance(c.get("text"), str) or c.get("act") != entry["code"]:
            st["problems"].append("a section record is malformed")
            return st
        by_num[str(c["section_number"]).upper()] = c
        if c.get("omitted"):
            continue
        rec = embeddings.get(f"act:{c['act']}:{c['section_number']}")
        if rec is None or rec.get("text_sha") != text_sha(c["text"]) or not isinstance(rec.get("embedding"), list):
            stale.append(c["section_number"])
            continue
        ranked.append(c)
        vectors.append(rec["embedding"])
    if stale:
        st["problems"].append(f"no fresh embedding for section(s) {', '.join(stale[:6])}{' ...' if len(stale) > 6 else ''}: run embed_act_shelf.py")
        return st
    if not ranked:
        st["problems"].append("no section to search")
        return st
    if entry.get("whole_act"):
        total = sum(len(c["text"]) for c in ranked)
        if total > WHOLE_ACT_MAX_CHARS:
            st["problems"].append(f"the manifest says whole_act, but the Act is {total:,} characters long (the limit is {WHOLE_ACT_MAX_CHARS:,}): it is not held")
            return st
        st["whole"] = True
    for p in entry.get("pointers") or []:
        rxs = [r for r in (_flex(x) for x in p.get("phrases") or []) if r is not None]
        try:                                                  # 'patterns' (added 2026-10-17): regular expressions, for a cue that is not one fixed phrase ("took Rs 10,000 from us"); case-insensitive
            rxs += [re.compile(x, re.IGNORECASE | re.DOTALL) for x in p.get("patterns") or []]
        except (re.error, TypeError):
            rxs = []
        secs = [str(s).upper() for s in p.get("sections") or []]
        if not rxs or not secs or any(s not in by_num for s in secs):
            st["problems"].append(f"a pointer is malformed or points to a section that is not in the Act: {p.get('phrases') or p.get('patterns')}")
            return st
        st["pointers"].append({"rx": rxs, "sections": secs, "phrases": list(p.get("phrases") or []) + list(p.get("patterns") or []), "tag": p.get("tag")})
    st.update(ok=True, by_num=by_num, ranked=ranked, matrix=np.array(vectors, dtype=float), aliases=_alias_patterns(entry))
    return st


def load(path=None, refresh=False):
    """The shelf: {'acts': {key: state}, 'problems': [...]}; an Act that fails any check has ok=False and says why in 'problems'.  Never raises.  Cached per directory."""
    base = os.path.abspath(path or SHELF_DIR)
    with _LOCK:
        st = _STATE.get(("shelf", base))
        if st is not None and not refresh:
            return st
        if refresh:
            _STATE.pop(("manifest", base), None)
        out = {"acts": {}, "problems": []}
        try:
            entries = manifest(base)
            emb = _read_json(os.path.join(base, "shelf_embeddings.json"))
            if emb.get("model") != MODEL:
                out["problems"].append(f"the embeddings were made with {emb.get('model')!r}, not {MODEL!r}")
                records = {}
            else:
                records = {r["chunk_id"]: r for r in emb.get("records", []) if isinstance(r, dict) and r.get("chunk_id")}
            for key, entry in entries.items():
                out["acts"][key] = _load_act(entry, records, base) if records else {"key": key, "code": entry["code"], "ok": False, "problems": ["no usable embeddings"]}
        except Exception as exc:  # noqa: BLE001 -- fail-open: no shelf
            out["problems"].append(f"the shelf cannot be loaded: {type(exc).__name__}: {exc}")
        _STATE[("shelf", base)] = out
        return out


def _state(act_id):
    try:
        st = load()["acts"].get(act_id)
        return st if st and st.get("ok") else None
    except Exception:  # noqa: BLE001
        return None


def available(act_id):
    """True when ACT_SHELF=on and this Directory id has a shelf whose every check passed."""
    return enabled() and _state(act_id) is not None


def loaded_on(act_id):
    st = _state(act_id)
    return st["loaded_on"] if st else None


def loaded_label(iso):
    """'2026-10-16' -> '16 October 2026' ('' when it is not a date)."""
    try:
        d = datetime.date.fromisoformat(str(iso))
        return f"{d.day} {d.strftime('%B %Y')}"
    except Exception:  # noqa: BLE001
        return ""


def display_names():
    """{act code: display name} for every Act of the manifest (a small read; works whether or not the shelf is on)."""
    try:
        return {e["code"]: (e.get("display") or e.get("short") or e.get("name")) for e in manifest().values()}
    except Exception:  # noqa: BLE001
        return {}


def name_patterns():
    """{act code: compiled regex} of the names an answer may use for the Act (for chat_assistant's missing-Act check)."""
    try:
        with _LOCK:
            cached = _STATE.get("name_patterns")
        if cached is not None:
            return cached
        out = {}
        for e in manifest().values():
            pats = _alias_patterns(e)
            if pats:
                out[e["code"]] = re.compile("|".join(p.pattern for p in pats), re.IGNORECASE)
        with _LOCK:
            _STATE["name_patterns"] = out
        return out
    except Exception:  # noqa: BLE001
        return {}


# ----- sections named in the question -----------------------------------------------------------------------------------------------------------------------------------------------------

_SECREF = re.compile(
    r"(?<![a-z0-9])(?:u\s*/\s*ss?|ss?\.|sections?|secs?\.?)\s*"
    r"(\d{1,3}[a-z]{0,2}(?:\s*\(\s*[0-9a-z]{1,4}\s*\))*"
    r"(?:\s*(?:,|and|&|/|or)\s*\d{1,3}[a-z]{0,2}(?:\s*\(\s*[0-9a-z]{1,4}\s*\))*)*)", re.IGNORECASE)
_OTHER_CODES = [p for p in (_flex(x) for x in (
    "bnss", "bns", "crpc", "cr p c", "ipc", "i p c", "code of criminal procedure", "indian penal code", "bharatiya nyaya sanhita", "bharatiya nagarik suraksha sanhita", "bharatiya sakshya adhiniyam",
    "bsa", "evidence act", "it act", "information technology act", "ni act", "negotiable instruments act", "constitution")) if p is not None]


def _other_patterns(exclude):
    """The names of everything that is not one of the shelf Acts being looked for: BNS, CrPC and the like, and every other Act of the Directory (so that 'section 15 of the Juvenile Justice Act' is not taken for POCSO's)."""
    key = ("others", tuple(sorted(exclude)))
    with _LOCK:
        cached = _STATE.get(key)
    if cached is not None:
        return cached
    out = list(_OTHER_CODES)
    try:
        import act_directory
        for e in act_directory.load()["acts"]:
            if e["id"] in exclude:
                continue
            for n in list(e.get("aliases") or []) + [e.get("short"), e.get("name")]:
                p = _flex(n)
                if p is not None:
                    out.append(p)
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        _STATE[key] = out
    return out


def _names_between(text, lo, hi, alias_map, others):
    """Every Act name inside text[lo:hi] as (start, end, kind, key): a shelf Act's alias (kind 'act', key = its id) or another code or Act (kind 'other')."""
    out = []
    seg = text[lo:hi]
    for kind, key, pats in [("act", k, v) for k, v in alias_map.items()] + [("other", None, others)]:
        for p in pats:
            for m in p.finditer(seg):
                out.append((lo + m.start(), lo + m.end(), kind, key))
    return out


def _attributions(text, act_ids, with_bare=False):
    """[(number, kind, act id)] for every section number in the text, with the name that stands next to it: kind 'act' (a shelf Act among act_ids; the third item is its id), 'other' (BNS, CrPC, another Act of the
    Directory; the third item is None).  A number with no name next to it is left out (with_bare=True: it is reported as (number, None, None), see implied_sections).  A name stands next to a number when it follows it ('section 45 of the PMLA': it STARTS within WINDOW characters of the
    number and lies before the next section number) or, failing that, precedes it ('PMLA section 45': it ENDS within WINDOW characters before the number; a name an earlier number has already taken does not
    count).  A long official name ('section 5 of the Prevention of Damage to Public Property Act, 1984') therefore counts; it did not before 2026-10-17."""
    out = []
    text = (text or "").lower()
    alias_map = {}
    for aid in act_ids:
        st = _state(aid)
        if st:
            alias_map[aid] = st["aliases"]
    if not alias_map:
        return out
    others = _other_patterns(set(alias_map))
    refs = list(_SECREF.finditer(text))
    taken = set()                                                    # names an earlier number has already claimed
    for i, m in enumerate(refs):
        prev_end = refs[i - 1].end() if i else 0
        next_start = refs[i + 1].start() if i + 1 < len(refs) else len(text)
        after = sorted(n for n in _names_between(text, m.end(), min(m.end() + WINDOW + NAME_ROOM, next_start), alias_map, others) if n[0] - m.end() <= WINDOW)             # starts within WINDOW after the number
        before = sorted((n for n in _names_between(text, max(m.start() - WINDOW - NAME_ROOM, prev_end), m.start(), alias_map, others) if m.start() - n[1] <= WINDOW and n[:2] not in taken),
                        key=lambda n: -n[1])                                                                                                                                   # ends within WINDOW before it
        pick = after[0] if after else (before[0] if before else None)
        nums = re.findall(r"\d{1,3}[a-z]{0,2}", re.sub(r"\([^)]*\)", " ", m.group(1)))
        if pick is None:
            if with_bare:
                out.extend((n.upper(), None, None) for n in nums)
            continue
        taken.add(pick[:2])
        for n in nums:
            out.append((n.upper(), pick[2], pick[3]))
    return out


def named_sections(text, act_ids):
    """{act id: [section numbers]} the question names for the given shelf Acts, in the order named ('section 45 of the PMLA', 'PMLA s.45', 'sections 3 and 4 of POCSO').  If the name next to the number is another
    code's ('section 438 CrPC', 'section 3 of the BNS', 'section 15 of the Juvenile Justice Act') the number is not ours.  The Act must have such a section (an omitted or repealed one too: the person is told so)."""
    out = {}
    try:
        for n, kind, aid in _attributions(text, act_ids):
            if kind == "act" and n in (_state(aid) or {}).get("by_num", {}):
                bucket = out.setdefault(aid, [])
                if n not in bucket:
                    bucket.append(n)
    except Exception:  # noqa: BLE001
        return {}
    return out


def other_numbers(text, act_ids):
    """The section numbers in the text that stand next to the name of something that is not one of the shelf Acts in act_ids ('section 3 of the BNS'): the numbers the shelf does NOT claim."""
    try:
        return {n for n, kind, _ in _attributions(text, act_ids) if kind == "other"}
    except Exception:  # noqa: BLE001
        return set()


def section_numbers_in(text):
    """The section numbers (upper case, '17', '17A') that a text puts after the word 'section' / 's.' / 'ss.' / 'u/s', whatever Act it means: the numbers an ANSWER uses. A set; empty on any problem.
    '17-A' (no spaces) and '17 A' (a capital letter) are read as 17A here, so that an answer which writes 17A that way is not taken for one that names section 17; the question side (named_sections) still reads '17 A' as 17."""
    try:
        out = set()
        t = re.sub(r"(?<=\d)[-\u2013](?=[A-Za-z](?![A-Za-z]))", "", text or "")
        t = re.sub(r"(?<=\d) (?=[A-Z](?![A-Za-z]))", "", t)
        for m in _SECREF.finditer(t.lower()):
            out.update(n.upper() for n in re.findall(r"\d{1,3}[a-z]{0,2}", re.sub(r"\([^)]*\)", " ", m.group(1))))
        return out
    except Exception:  # noqa: BLE001
        return set()


def implied_sections(text, act_ids):
    """{act id: [section numbers]}: the numbers of the text that have NO Act or code named next to them ('No section 17 order exists ...', said in a conversation about the Prevention of Corruption Act), taken
    for the shelf Act of the question that has a section of that number.  named_sections leaves such a number out, so before 2026-10-19 it was tied to no Act: the Act's own section was found only by meaning, and
    chat_assistant read the bare number as a BNS section and put BNS section 17 into the material (owner's staging test, turns 2 to 4 of the section 17 conversation).
    Taken only when exactly ONE of the shelf Acts in act_ids has a section of that number (section 17 exists in the PMLA as well: with both Acts drawn it is not guessed), and not when the text also puts the same
    number next to some name ('section 17 of the BNS and ... section 17': which is meant is not known).  {} when SECTION_RULE is off or on any problem."""
    out = {}
    try:
        import section_rule
        if not section_rule.enabled():
            return out
        ids = [a for a in act_ids if _state(a)]
        if not ids:
            return out
        attrs = _attributions(text, ids, with_bare=True)
        elsewhere = {n for n, kind, _ in attrs if kind is not None}
        for n, kind, _ in attrs:
            if kind is not None or n in elsewhere:
                continue
            owners = [a for a in ids if n in (_state(a) or {}).get("by_num", {})]
            if len(owners) == 1:
                bucket = out.setdefault(owners[0], [])
                if n not in bucket:
                    bucket.append(n)
    except Exception:  # noqa: BLE001
        return {}
    return out


# ----- sections that a named section cites (SECTION_XREF) ------------------------------------------------------------------------------------------------------------------------------------

def xref_enabled():
    """SECTION_XREF=on|off, default OFF (added 2026-10-20). On: a section the person asked about, and that cites another section of its own Act by number, brings that section too (cited_sections, _add_cited)."""
    return (os.environ.get("SECTION_XREF") or "").strip().strip("\"'").strip().lower() == "on"


# An enactment named in the words right after a reference: 'section 8 of the Code of Criminal Procedure, 1973', 'section 617 of the Companies Act, 1956', 'section 42 of that Code', 'section 195 and [Chapter XXVI] of the [Code]',
# 'section 15 of the Act' (which Act is not known): the number is then NOT this Act's.  The words must follow the number at once ('of', 'in', 'under' + a capitalised name that runs on to Act, Code, ...): an Act named
# later in the same sentence ('sections 7, 11, 13 and 15 ... save as otherwise provided in the Lokpal and Lokayuktas Act, 2013') does not make the reference another Act's.  'this Act' (lower-case 'this') and the Act's
# own name are the exceptions.  Case-sensitive on purpose.
_AFTER_REF = re.compile(r"^[\s,\]\)]*(?:(?:and|or)\s+)?(?:to\s+\d{1,3}[A-Za-z]{0,2}\s*(?:\([^)]*\)\s*)*)?(?:\[?(?:Chapter|sub-section|clause)\b[^,;]{0,30}?\s+)?(?:of|in|under|to)\s+(?:(?:the|that|said)\s+)*(?P<name>\[?[A-Z].{0,200})", re.S)
_ENACTMENT_WORDS = {"Act", "Code", "Sanhita", "Adhiniyam", "Ordinance", "Constitution", "Rules", "Regulations"}
_NAME_CONNECTORS = {"of", "and", "the", "for", "on", "to", "in", "&"}
_ENACTMENT_ABBR = re.compile(r"^[\s,\]\)]*(?:(?:and|or)\s+)?(?:of|in|under|to)\s+(?:(?:the|that|said)\s+)*(?:Cr\.?\s?P\.?\s?C\.?|I\.?P\.?C\.?|BNSS?|BSA|NDPS|POCSO|PMLA|UAPA)(?![A-Za-z])")
_NOTE_START = re.compile(r"\[\s*Note\s*:", re.I)
_REF_WORD = re.compile(r"^sections?\b", re.I)
_AMENDING = re.compile(r"\(\s*\d+\s+of\s+\d{4}\s*\)\s*,?\s*$|\b(?:Subs|Ins|Rep)\.\s*(?:by|w\.e\.f)", re.I)


def _tied_elsewhere(tail, aid):
    """True when the words right after a section reference (`tail`) name some OTHER enactment than the Act `aid`: the reference is then not to a section of this Act (see _AFTER_REF).  The name may contain small
    words ('Persons with Disabilities (Equal Opportunities ...) Act, 1995'): the capitalised start is followed to the first Act/Code/... within 30 words, stopping at ';' or ':'."""
    if _ENACTMENT_ABBR.match(tail) or re.match(r"\s*\(\s*\d+\s+of\s+\d{4}\s*\)", tail):         # 'section 153A (45 of 1860)': an enactment's number and year follow
        return True
    m = _AFTER_REF.match(tail)
    if not m:
        return False
    name = m.group("name")
    if any(p.match(name) for p in ((_state(aid) or {}).get("aliases") or [])):
        return False                                                  # the Act's own name
    prev = ""
    for tok in name.split()[:30]:
        w = tok.strip("[](),.;:")
        if w in _ENACTMENT_WORDS and prev != "this":
            return True
        if tok.endswith((";", ":")) or w.lower() in ("section", "sections", "sub-section", "sub-sections"):
            return False                                              # the name ended without naming an enactment ('of Police;'), or the next reference began
        prev = w.lower()
    return False


_ENUM = re.compile(r"^\s*,?\s*(?:or|and)\b", re.I)


def cited_sections(st, num):
    """(cited, info): the numbers of the sections of the same Act that section `num` of the Act `st` cites by number in its own text ('... of section 13 shall not be investigated ...'), in order of first mention, and a
    dict of what was left out and why.  A reference is left out when: it is not written 'section N' / 'sections N, M' (an amendment note's 's. 5'); it stands in India Code's own '[Note: ...]' paragraph or in an amending
    Act's note ('... (3 of 2013), s. 5'); the words right after it name another enactment ('section 8 of the Code of Criminal Procedure, 1973'); it points at the section itself; the Act has no such section or it is omitted.
    A section that cites more than MAX_FANOUT other sections is followed for none of them (info['fanout']).  ([], {}) on any problem."""
    info = {}
    try:
        c = st["by_num"].get(str(num).upper())
        text = (c or {}).get("text") or ""
        if not text:
            return [], info
        note_at = _NOTE_START.search(text)
        limit = note_at.start() if note_at else len(text)
        out = []
        refs = [m for m in _SECREF.finditer(text[:limit]) if _REF_WORD.match(m.group(0))]       # 's. 5', 'u/s 5' (an amendment note) are not read
        other = [None] * len(refs)
        for i in range(len(refs) - 1, -1, -1):
            m = refs[i]
            tail = text[m.end():m.end() + 160]
            if _ENUM.match(tail) and i + 1 < len(refs) and refs[i + 1].start() - m.end() <= 200:
                other[i] = other[i + 1]                                 # 'section 3, or ... section 17 of the Commissions ... Act': one name for the list
            else:
                other[i] = _tied_elsewhere(tail, st["key"])
        for i, m in enumerate(refs):
            word = _REF_WORD.match(m.group(0))
            head = text[max(0, m.start() - 120):m.start()]
            if _AMENDING.search(head) or re.match(r"\s*\(\s*w\.e\.f", text[m.end():m.end() + 40], re.I) or other[i]:
                continue
            g = m.group(1)
            nums = re.findall(r"\d{1,3}[a-z]{0,2}", re.sub(r"\([^)]*\)", " ", g))
            if word.group(0).lower() == "section":
                nums = nums[:1]                                       # 'section 3 or 5 years' is one section; 'sections 7, 13 and 17' is three
            for n in (x.upper() for x in nums):
                t = st["by_num"].get(n)
                if n == str(num).upper() or not t or t.get("omitted") or n in out:
                    continue
                out.append(n)
        if len(out) > MAX_FANOUT:
            info["fanout"] = len(out)
            return [], info
        return out, info
    except Exception:  # noqa: BLE001
        return [], {}


def _add_cited(st, mine, rec):
    """SECTION_XREF: after the sections the person asked about are chosen (rec['named'], rec['implied']), adds the sections they cite (cited_sections) to `mine` as retrieval 'cited' with 'cited_by' = the citing
    section, at most MAX_CITED new ones, none longer than CITED_MAX_CHARS.  Every asked section's own match gets 'cites' = the cited numbers that are in the material (added now, or already there by meaning).
    rec['cited'] lists what was added, rec['cite_skipped'] what was left out and why (for the ACT_SHELF log line).  Never raises."""
    try:
        have = {str(m["section_number"]).upper(): m for m in mine}
        added = 0
        for n in list(rec["named"]) + list(rec.get("implied") or []):
            holder = have.get(n)
            cites, info = cited_sections(st, n)
            if info.get("fanout"):
                rec.setdefault("cite_skipped", []).append({"by": n, "why": f"cites {info['fanout']} sections"})
            shown = []
            for cn in cites:
                m = have.get(cn)
                if m is None:
                    c = st["by_num"][cn]
                    if added >= MAX_CITED:
                        rec.setdefault("cite_skipped", []).append({"s": cn, "by": n, "why": "cap"})
                        continue
                    if len(c.get("text") or "") > CITED_MAX_CHARS:
                        rec.setdefault("cite_skipped", []).append({"s": cn, "by": n, "why": "too long"})
                        continue
                    m = _match(st, c, "cited", None)
                    m["cited_by"] = n
                    mine.append(m)
                    have[cn] = m
                    added += 1
                    rec.setdefault("cited", []).append({"s": cn, "by": n})
                shown.append(cn)
            if holder is not None and shown:
                holder["cites"] = shown
    except Exception:  # noqa: BLE001 -- the cited sections are an addition: without them the material is what it was
        pass


# ----- the search -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _embed_query(text):
    """The question as a voyage-law-2 query vector (what semantic_retrieval does for the library); the cost is logged like the library's query embedding."""
    import voyageai
    from semantic_retrieval import _resolve_voyage_api_key
    resp = voyageai.Client(api_key=_resolve_voyage_api_key(), max_retries=1, timeout=20).embed([text], model=MODEL, input_type="query")      # a hang here must not hold up the answer: after 20 seconds the sections the question names still go
    try:
        import cost_log
        cost_log.note_voyage("act_shelf_query_embed", MODEL, getattr(resp, "total_tokens", 0))
    except Exception:  # noqa: BLE001
        pass
    return resp.embeddings[0]


def _match(st, c, how, score):
    return {"type": "statute", "act": st["code"], "act_key": st["key"], "act_display": st["display"], "section_number": str(c["section_number"]), "title": c.get("title"), "text": c["text"],
            "score": round(float(score), 4) if score is not None else None, "source": "act_shelf", "retrieval": how, "chunk_id": f"act:{c['act']}:{c['section_number']}", "all_variants": {},
            "shelf": {"loaded_on": st["loaded_on"], "pdf_as_on": st["pdf_as_on"], "text_status": st["text_status"], "source_url": c.get("source_url"), "footnotes": c.get("footnotes") or "",
                      "omitted": bool(c.get("omitted"))}}


def search(question, acts, current_message=None, embed_fn=None):
    """The shelf's answer for a question that the Directory tied to `acts` ([{'id',...}]):  {'matches': [...match dicts, statute text with source='act_shelf'...], 'info': {...for the log...}}.
    Empty matches when ACT_SHELF is off, when no named Act has a shelf, or on any failure."""
    info = {"acts": [], "embed": "skipped", "per_act": {}, "chars": 0}
    empty = {"matches": [], "info": info}
    try:
        if not enabled():
            return empty
        shelf = load()["acts"]
        ids = []
        for a in acts or []:
            aid = a.get("id") if isinstance(a, dict) else a
            if aid in shelf and shelf[aid].get("ok") and aid not in ids:
                ids.append(aid)
        if not ids:
            return empty
        info["acts"] = ids
        text = (current_message or question or "").strip()
        named = named_sections(text, ids)
        implied = implied_sections(text, ids)
        lowered = text.lower()
        qvec = None
        if all(shelf[a].get("whole") for a in ids):
            info["embed"] = "not needed"                              # every Act drawn is handed over whole: no question vector, no Voyage call
        else:
            try:
                qvec = np.array((embed_fn or _embed_query)(text), dtype=float)
                info["embed"] = "ok"
            except Exception as exc:  # noqa: BLE001 -- the named sections and pointers still go
                info["embed"] = f"failed: {type(exc).__name__}"
        k_meaning = TOP_K_ONE if len(ids) == 1 else TOP_K_TWO
        budget = MAX_CHARS // len(ids)
        matches = []
        for aid in ids:
            st = shelf[aid]
            seen, mine, rec = set(), [], {"named": [], "pointed": [], "meaning": [], "below_floor": 0, "dropped_by_cap": []}
            for n in named.get(aid, [])[:MAX_NAMED]:
                if n not in seen:
                    seen.add(n)
                    mine.append(_match(st, st["by_num"][n], "named", None))
                    rec["named"].append(n)
            for n in implied.get(aid, []):                           # a bare number taken for this Act (implied_sections); the named ones come first and the two together stay within MAX_NAMED
                if n not in seen and len(rec["named"]) + len(rec.setdefault("implied", [])) < MAX_NAMED:
                    seen.add(n)
                    mine.append(_match(st, st["by_num"][n], "implied", None))
                    rec["implied"].append(n)
            pointed, tags = [], {}
            for p in st["pointers"]:
                if any(rx.search(lowered) for rx in p["rx"]):
                    for s_ in p["sections"]:
                        if s_ not in pointed:
                            pointed.append(s_)
                            if p.get("tag"):
                                tags[s_] = p["tag"]
            for n in pointed[:MAX_POINTED]:
                if n not in seen:
                    seen.add(n)
                    mm = _match(st, st["by_num"][n], "pointer", None)
                    if tags.get(n):
                        mm["pointer_tag"] = tags[n]                    # e.g. 'payer': why this pointer fired (chat_assistant adds an instruction to the prompt for it)
                    mine.append(mm)
                    rec["pointed"].append(n)
            if st.get("whole"):                                       # a very short Act: every section, in the Act's own order (named and pointed ones are already first)
                rec["whole"] = True
                for c in st["ranked"]:
                    n = str(c["section_number"]).upper()
                    if n not in seen:
                        seen.add(n)
                        mine.append(_match(st, c, "whole", None))
                info["per_act"][aid] = rec
                matches += mine
                continue
            want = max(MIN_MEANING, k_meaning - len(mine))
            if qvec is not None:
                scores = st["matrix"] @ qvec
                order = np.argsort(-scores, kind="stable")
                rec["below_floor"] = int((scores < FLOOR).sum())
                used, got = sum(len(m["text"]) for m in mine), 0
                for i in order:
                    sc = float(scores[i])
                    if sc < FLOOR:
                        break
                    c = st["ranked"][int(i)]
                    if str(c["section_number"]).upper() in seen or _housekeeping(c):
                        continue
                    if got >= want:
                        break
                    if mine and used + len(c["text"]) > budget:       # named and pointed sections always come; a meaning-ranked one must fit what is left (the very first section of an Act is exempt)
                        rec["dropped_by_cap"].append(str(c["section_number"]))
                        continue
                    seen.add(str(c["section_number"]).upper())
                    mine.append(_match(st, c, "meaning", sc))
                    rec["meaning"].append({"s": str(c["section_number"]), "score": round(sc, 3)})
                    used += len(c["text"])
                    got += 1
            if xref_enabled():
                _add_cited(st, mine, rec)                              # SECTION_XREF: the sections that the named section cites
            info["per_act"][aid] = rec
            matches += mine
        info["chars"] = sum(len(m["text"]) for m in matches)
        return {"matches": matches, "info": info}
    except Exception as exc:  # noqa: BLE001 -- fail-open: no shelf text
        info["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return {"matches": [], "info": info}


def shelf_ids(matches):
    """The Directory ids of the Acts whose shelf text is among `matches`."""
    out = []
    for m in matches or []:
        if isinstance(m, dict) and m.get("source") == "act_shelf" and m.get("act_key") and m["act_key"] not in out:
            out.append(m["act_key"])
    return out


def _act_year(m):
    """The year in an Act's name ('... Act, 2002' gives 2002) from the match's display name or citation; None when there is none."""
    for t in (m.get("act_display"), (_state(m.get("act_key") or "") or {}).get("name"), (_state(m.get("act_key") or "") or {}).get("citation")):
        y = re.search(r"\b(1[89]\d\d|20\d\d)\b", t or "")
        if y:
            return int(y.group(1))
    return None


def statute_context(matches):
    """For the wider search (sci_search_tier.set_statute_context): [{'act': display name, 'aliases': compiled regex of the Act's names or None, 'sections': {number: title + text}}] for the shelf sections the
    question NAMED (retrieval 'named', or 'implied': a bare number taken for the one shelf Act of the conversation). A section found by meaning or by a pointer is not one the person asked about, so it is
    left out. [] when there is none."""
    out = {}
    try:
        patterns = name_patterns()
        for m in matches or []:
            if not (isinstance(m, dict) and m.get("source") == "act_shelf" and m.get("retrieval") in ("named", "implied") and m.get("text") and m.get("act")):
                continue
            item = out.setdefault(m["act"], {"act": m.get("act_display") or m["act"], "aliases": patterns.get(m["act"]), "year": _act_year(m), "sections": {}})
            item["sections"][str(m.get("section_number")).upper()] = ((m.get("title") or "") + " " + m["text"]).strip()
    except Exception:  # noqa: BLE001
        return []
    return list(out.values())


def held_state(matches, acts):
    """For the notice and the prompt: {act id: {'state': 'used'|'unused', 'loaded_on': iso date}} for every Act of `acts` that has a working shelf.  'used' = text of that Act reached the answer;
    'unused' = the shelf holds the Act but nothing from it did (nothing close enough, or the question was not searched).  'whole': True is added for an Act that is handed over in full.  An Act with no working shelf is not in the result."""
    out = {}
    try:
        if not enabled():
            return out
        used = set(shelf_ids(matches))
        import section_rule
        asked = {}                                                     # the sections the person named (or bare-named in a conversation about the Act): the prompt tells the model to stay on them
        for m in (matches or []) if section_rule.enabled() else []:
            if isinstance(m, dict) and m.get("source") == "act_shelf" and m.get("retrieval") in ("named", "implied") and m.get("act_key") and m.get("section_number"):
                bucket = asked.setdefault(m["act_key"], [])
                if str(m["section_number"]).upper() not in bucket:
                    bucket.append(str(m["section_number"]).upper())
        cited = {}
        for m in (matches or []) if section_rule.enabled() else []:
            if isinstance(m, dict) and m.get("source") == "act_shelf" and m.get("retrieval") == "cited" and m.get("act_key") and m.get("section_number") and m.get("cited_by"):
                cited.setdefault(m["act_key"], []).append({"by": str(m["cited_by"]).upper(), "section": str(m["section_number"]).upper()})
        for a in acts or []:
            aid = a.get("id") if isinstance(a, dict) else a
            st = _state(aid)
            if st:
                out[aid] = {"state": "used" if aid in used else "unused", "loaded_on": st["loaded_on"]}
                if st.get("whole"):
                    out[aid]["whole"] = True                           # the Act is handed over in full (a very short Act): the notice and the prompt say so instead of "the sections our search found"
                if asked.get(aid):
                    out[aid]["named"] = asked[aid]
                if cited.get(aid):
                    out[aid]["cited"] = cited[aid]                      # SECTION_XREF: [{'by': '17', 'section': '13'}]: the prompt tells the model that the asked section refers to these
    except Exception:  # noqa: BLE001
        return {}
    return out
