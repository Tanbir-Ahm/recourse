"""
checker_list.py -- the lists the invented-case check looks a case name up in (added 2026-10-28, FOLLOW_UPS 2cp)

The check (grounding_checks.check_cases) lets a case named in an answer pass when the material the model was given contains it. A case that is not in the material is looked up here, only so that the
notice can say "real, but not among the sources we read" or "we could not find it". Before this module the only list was the Supreme Court title list (case_lookup_index.db: 38,026 titles to 12 December 2025,
no text), looked up word for word, which left out every High Court judgment, every Supreme Court judgment after 12 December 2025, about 2,400 Supreme Court judgments the wide search index holds that the title
list lacks, and every title spelt differently (see review_results/2026-10-28_register_and_checker_lists/).

CHECKER_LIST = title | wide.  title (the default) is the old behaviour byte for byte (grounding_checks.sc_list_has alone). wide also looks in:
  * checker_names.json.gz, beside this file: the name, court and date of every judgment the wide search index holds (Supreme Court and Gauhati High Court) and of every judgment of the reviewed library
    (written by sci_checker_names.py in the research repository; it must be rebuilt when the index changes; no judgment text),
  * the Supreme Court title list again, with the tolerant matching of name_match.py (spelling variants, abbreviations, several appellants, parties the other way round).
A name found in any of them counts as "real". The answer is True when found, False when looked everywhere and not found, None when no list could be read (the notice then says nothing about the list).

NOT a verification: a hit says that a judgment with those parties exists in a list we hold. It does not say it is the case meant, that it decides what the answer says, or that it is good law; and a miss says only that
the name is in no list we hold (the other twenty-odd High Courts are in none, nor is a Supreme Court judgment that is in neither list).
Everything here swallows its own errors (a failure leaves the older behaviour in place) and the index is built once per process, on first use (about two seconds; warm() builds it at start-up).
"""
import gzip
import json
import os
import re
import sqlite3
import threading
import time

import name_match as NM

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES_PATH = os.environ.get("CHECKER_NAMES_PATH") or os.path.join(HERE, "checker_names.json.gz")
MODES = ("title", "wide")
MAX_CANDIDATES = 300
_COMMON_DF = 2500                          # a word in more entries than this (state, india, kumar ...) does not select candidates when a rarer word is there

_LOCK = threading.Lock()
_STATE = {"built": False, "error": None}


def mode():
    v = (os.environ.get("CHECKER_LIST") or "title").strip().strip("\"'").strip().lower()
    return v if v in MODES else "title"


_TOKEN_DROP = NM._DROP | NM._NOISE_WORDS
_STATE_ABBR = frozenset("up mp ap hp tn wb jk".split())            # the canonical short forms of the big States (name_match._PHRASES): two letters, but they tell cases apart


def entry_tokens(name):
    """The words of a case name that select candidate entries: letters and digits, canonical spelling, no honorifics or filler, three letters or more (or a State's short form)."""
    s = NM._canon(NM._plain(re.sub(r"[()]", " ", name or "")).replace(",", " ").replace("@", " "))
    return {t for t in s.split() if (len(t) >= 3 or t in _STATE_ABBR) and t not in _TOKEN_DROP}


def _read_title_list(path):
    conn = sqlite3.connect("file:" + path + "?mode=ro", uri=True, timeout=5.0)
    try:
        return [(t, c, d) for t, c, d in conn.execute("SELECT title, court, decision_date FROM cases WHERE title IS NOT NULL")]
    finally:
        conn.close()


def _read_names(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    courts, srcs = data.get("courts") or [], data.get("sources") or []
    out = []
    for name, ci, date, si in data.get("rows") or []:
        out.append((name, courts[ci] if ci is not None and 0 <= ci < len(courts) else None, date, srcs[si] if si is not None and 0 <= si < len(srcs) else "names file"))
    return out, {k: data.get(k) for k in ("schema", "built", "index_commit", "documents", "named")}


def build(title_db=None, names_path=None):
    """Read the lists and build the index (idempotent). Returns the info dict; raises nothing."""
    with _LOCK:
        _STATE.update(built=False, error=None)
        t0 = time.time()
        entries, info = [], {"title_list": 0, "names_file": 0, "names_file_info": None}
        try:
            import case_lookup
            path = title_db or case_lookup.INDEX_PATH
            if os.path.exists(path):
                for t, c, d in _read_title_list(path):
                    entries.append((t, c, d, "title list"))
                info["title_list"] = len(entries)
        except Exception as e:  # noqa: BLE001
            info["title_list_error"] = type(e).__name__
        try:
            p = names_path or NAMES_PATH
            if os.path.exists(p):
                rows, ninfo = _read_names(p)
                entries.extend(rows)
                info["names_file"], info["names_file_info"] = len(rows), ninfo
        except Exception as e:  # noqa: BLE001
            info["names_file_error"] = type(e).__name__
        inv = {}
        for i, (name, _c, _d, _s) in enumerate(entries):
            for t in entry_tokens(name):
                inv.setdefault(t, []).append(i)
        p3, s3 = {}, {}
        for t in inv:
            if len(t) >= 7:
                p3.setdefault(t[:3], []).append(t)
                s3.setdefault(t[-3:], []).append(t)
        _STATE.update(entries=entries, inv=inv, p3=p3, s3=s3, cache={}, sets={}, info=info)
        _STATE["built"] = bool(entries)
        _STATE["error"] = None if entries else "no list could be read"
        info["entries"], info["seconds"] = len(entries), round(time.time() - t0, 2)
        return info


def warm():
    if not _STATE["built"]:
        build()
    return dict(_STATE.get("info") or {})


def _ready():
    if not _STATE["built"] and not _STATE["error"]:
        info = build()
        try:
            print("CHECKER_LIST_READY " + json.dumps({"entries": info.get("entries"), "title_list": info.get("title_list"), "names_file": info.get("names_file"), "index_commit": str(((info.get("names_file_info") or {}).get("index_commit")) or "")[:7],
                                                      "seconds": info.get("seconds"), "error": _STATE["error"]}), flush=True)
        except Exception:  # noqa: BLE001
            pass
    return _STATE["built"]


def _parsed(i):
    cache = _STATE["cache"]
    p = cache.get(i)
    if p is None:
        if len(cache) > 20000:
            cache.clear()
        p = cache[i] = NM.parse_name(_STATE["entries"][i][0])
    return p


def _posting_set(t):
    sets = _STATE["sets"]
    st = sets.get(t)
    if st is None:
        st = sets[t] = frozenset(_STATE["inv"].get(t, ()))
    return st


def _candidates(name):
    """Entries that share words with the name, best first. Entries holding one of the name's rarer words (or a word one slip from it) are all considered; the common words (State, Union, Singh ...) only
    order them, so a very common surname does not push the real entry out of the first MAX_CANDIDATES."""
    inv, p3, s3 = _STATE["inv"], _STATE["p3"], _STATE["s3"]
    toks = entry_tokens(name)
    near_of = {}
    for t in toks:
        near = []
        if t in inv:
            near.append(t)
        if len(t) >= 7:
            for u in set(p3.get(t[:3], ())) | set(s3.get(t[-3:], ())):
                if u != t and NM.tok_eq(t, u):
                    near.append(u)
        if near:
            near_of[t] = near
    rare_t = [t for t, near in near_of.items() if all(len(inv[u]) <= _COMMON_DF for u in near)]
    if not near_of:
        return []
    use = rare_t or list(near_of)
    score = {}
    for t in use:
        for u in near_of[t]:
            ids = inv[u]
            w = 1.0 / (1 + len(ids) / 50.0) + 0.05
            for i in ids:
                score[i] = score.get(i, 0.0) + w
    for t in near_of:
        if t in use:
            continue
        for u in near_of[t]:
            ps = _posting_set(u)
            bonus = 0.05
            for i in score:
                if i in ps:
                    score[i] += bonus
    return sorted(score, key=lambda i: -score[i])[:MAX_CANDIDATES]


def lookup(name):
    """{'found': True, 'title', 'court', 'date', 'list'} for the first entry that reads as the same parties; {'found': False}; or None when no list could be read or the name has no first party."""
    try:
        if not _ready():
            return None
        q = NM.parse_name(name)
        if not q[0]:
            return None
        for i in _candidates(name):
            if NM.names_match(q, _parsed(i)):
                t, c, d, s = _STATE["entries"][i]
                return {"found": True, "title": t, "court": c, "date": d, "list": s}
        return {"found": False}
    except Exception:  # noqa: BLE001
        return None


def stats():
    _ready()
    ents = _STATE.get("entries") or []
    by = {}
    for _t, c, _d, s in ents:
        by[(s, c)] = by.get((s, c), 0) + 1
    return {"entries": len(ents), "by_list_and_court": {f"{s} | {c}": n for (s, c), n in sorted(by.items(), key=lambda kv: -kv[1])}, "info": _STATE.get("info")}
