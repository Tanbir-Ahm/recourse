"""grounding_checks.py -- two checks on a finished answer, run by code, not by the model.

  1. Citation check: every case the answer names ("X v. Y") must be in the material the model was given (the question, the retrieved passages, the wider-search passages, the related-judgment list).
     A case that is not there came from the model's memory, which the prompt forbids. Each one is also looked up in the site's list of Supreme Court judgments (case_lookup) so the notice can say
     "real but not among our sources" or "not found in our list". The model may mention a case that a passage itself names (a passage that quotes Ramachandra Rao makes Ramachandra Rao part of the material).
  2. Quote check: words in quotation marks (five words or more) must appear in the material, apart from small differences of spacing, punctuation and case. "..." and [bracketed] insertions split a quotation
     into pieces and each piece is checked.

GROUNDING_CHECKS = off | log | warn | enforce.  log (the default) only prints a GROUNDING_CHECK line to the application log: nothing the user sees changes. warn adds a plain notice under the answer.
enforce also asks the model once more with the problem named, and withholds the answer when a case that cannot be found anywhere is still in it. Nothing here ever says a case is good law; a notice only withdraws trust.
Every function swallows its own errors (a failure of a check never breaks an answer).
"""
import difflib
import json
import os
import re
import threading

MODES = ("off", "log", "warn", "enforce")
QUOTE_MIN_WORDS = 5
_LOCAL = threading.local()

_GENERIC = re.compile(r"^(?:the\s+)?(?:state|union|commissioner|collector|central|govt|government|cbi|police|inspector|director|chief|secretary|ministry|bureau|board|authority|corporation|bank|company|ltd|"
                      r"national|nia|enforcement|customs|income|revenue|public|prosecution|home|district|superintendent|officer|station|house|sho)\b", re.I)
_TRAIL = re.compile(r"(?:[,.\s]+(?:&|and)\s+(?:anr|ors|another|others)\b\.?|[,.\s]+(?:anr|ors|another|others|etc|dead|by lrs?)\b\.?)+\s*$", re.I)
_STOP = {"v", "vs", "versus", "the", "of", "and", "anr", "ors", "another", "others", "etc", "state", "u", "p"}


def mode():
    v = (os.environ.get("GROUNDING_CHECKS") or "log").strip().strip("\"'").strip().lower()
    return v if v in MODES else "log"


# ---- notices travel from the generation step to answer_question in a thread-local ----
def reset_notes():
    _LOCAL.notes = []


def add_notes(notes):
    if not hasattr(_LOCAL, "notes") or _LOCAL.notes is None:
        _LOCAL.notes = []
    for n in notes:
        if n not in _LOCAL.notes:
            _LOCAL.notes.append(n)


def pop_notes():
    n = getattr(_LOCAL, "notes", None) or []
    _LOCAL.notes = []
    return n


# ---- text normalising ----
def norm(s):
    s = (s or "").lower()
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[‐-―\-]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _nospace(s):
    return norm(s).replace(" ", "")


# ---- case names ----
_VS = {"v", "v.", "vs", "vs.", "versus"}
_CONNECT = {"of", "the", "and", "for", "in", "on", "&", "by", "de", "la", "at", "through", "thru"}
_ABBREV = {"ltd", "pvt", "anr", "ors", "etc", "govt", "dept", "corp", "co", "inc", "bros", "assn", "ors.", "anr."}
_COURT_WORDS = {"court", "supreme", "high", "bench", "apex", "magistrate", "tribunal", "judge", "judges"}
_STARTERS = {"in", "see", "also", "under", "section", "court", "held", "and", "but", "while", "however", "as", "on", "for", "by", "at", "after", "before", "since", "because", "whether", "that", "this",
             "these", "those", "then", "there", "it", "its", "a", "an", "if", "when", "where", "which", "who", "with", "from", "to", "so", "thus", "hence", "per", "cf", "compare", "like", "unlike", "unless",
             "although", "though", "even", "yet", "now", "here", "both", "each", "every", "any", "some", "all", "no", "not", "only", "just", "likewise", "similarly", "moreover", "furthermore", "finally"}


def _is_name_token(tok, first_party):
    core = tok.strip(",;:()\"'\u201c\u201d")
    if not core:
        return False
    low = core.lower().rstrip(".")
    if first_party and low in _STARTERS:
        return False
    return core[0].isupper() or low in _CONNECT or low in _ABBREV or core == "&" or core[0].isdigit()


def _mentions(text):
    """Case names written 'X v. Y' (also vs., versus). The first party is read backwards from the 'v.', the second forwards, each stopping at a sentence start, a lowercase word that is not a name
    connector (of, the, and ...), the end of a sentence, or 'the Court'. A short parenthesis after the second party stays with it."""
    names = []
    toks = re.findall(r"\S+", text or "")
    for i, t in enumerate(toks):
        if t.strip(",;:()\"'\u201c\u201d").lower() not in _VS:
            continue
        back = []
        j = i - 1
        while j >= 0 and len(back) < 6:
            tk = toks[j]
            core = tk.strip(",;:()\"'\u201c\u201d")
            if not _is_name_token(tk, True):
                break
            if tk.endswith((",", ";", ":")) and back:
                break
            if tk.endswith(".") and len(core.rstrip(".")) > 3 and core.rstrip(".").lower() not in _ABBREV and back:
                break                                   # the end of the previous sentence
            back.append(core)
            j -= 1
        back.reverse()
        while back and back[0].lower().rstrip(".") in _CONNECT and back[0].lower() != "the":
            back.pop(0)
        fwd = []
        k = i + 1
        while k < len(toks) and len(fwd) < 7:
            tk = toks[k]
            core = tk.strip(",;:()\"'\u201c\u201d")
            if tk.startswith("(") and fwd:
                grp = [tk]
                m = k
                while not toks[m].endswith(")") and m + 1 < len(toks) and m - k < 8:
                    m += 1
                    grp.append(toks[m])
                if toks[m].rstrip(".,;:").endswith(")"):
                    gtxt = " ".join(grp).rstrip(".,;:")
                    if re.search(r"[A-Za-z]{4,}", gtxt) and not re.search(r"\b(?:SCC|AIR|SCR|SCALE|INSC|JT)\b", gtxt):     # a name's own parenthesis, not a year or a citation
                        fwd.append(gtxt)
                    k = m + 1
                    break
                break
            if not _is_name_token(tk, False):
                break
            if core.lower() == "the" and k + 1 < len(toks) and toks[k + 1].strip(",;:()\"'").lower() in _COURT_WORDS:
                break
            fwd.append(core)
            k += 1
            if tk.endswith((",", ";", ":")):
                break
            if tk.endswith(".") and len(core.rstrip(".")) > 3 and core.rstrip(".").lower() not in _ABBREV:
                break
        while fwd and fwd[-1].lower() in _CONNECT:
            fwd.pop()
        if back and fwd:
            names.append(" ".join(back).rstrip(".") + " v. " + " ".join(fwd).rstrip("."))
    return names


def _parties(name):
    parts = re.split(r"\s+(?:v\.?|vs\.?|versus)\s+", name or "", maxsplit=1, flags=re.I)
    clean = lambda p: _TRAIL.sub("", re.sub(r"\([^)]*\)", " ", (p or ""))).strip(" .,;")
    return (clean(parts[0]), clean(parts[1])) if len(parts) == 2 else (clean(name), "")


def _distinctive(name):
    p1, p2 = _parties(name)
    for p in (p1, p2):
        if p and not _GENERIC.match(p.strip()) and len(_nospace(p)) >= 5:
            return p
    return None


def supported_in_material(name, material_nospace):
    """True when the case's distinctive party name appears in the material (spacing and punctuation ignored; a leading initial such as the 'P.' of 'P. Ramachandra Rao' is optional)."""
    d = _distinctive(name)
    if d is None:
        return True                      # nothing distinctive to look for: never a basis for a notice
    words = d.split()
    forms = [d]
    while words and len(norm(words[0]).replace(" ", "")) <= 1:
        words = words[1:]
        if words:
            forms.append(" ".join(words))
    return any(len(_nospace(f)) >= 5 and _nospace(f) in material_nospace for f in forms)


def _tokens(party):
    return {t for t in norm(party).split() if t not in _STOP}


def sc_list_has(name):
    """True / False / None (could not look). True only when a title in the Supreme Court list has the same first party and a similar second party; lookalikes are not enough."""
    try:
        import case_lookup
        p1, p2 = _parties(name)
        a1, a2 = _tokens(p1), _tokens(p2)
        if not a1:
            return None
        res = case_lookup.search_cases_detailed(name, 8)
        for c in res.get("cases") or []:
            q1, q2 = _parties(c.get("title") or "")
            b1, b2 = _tokens(q1), _tokens(q2)
            if a1 == b1 and (not a2 or not b2 or len(a2 & b2) / max(1, len(a2 | b2)) >= 0.5):
                return True
        return False
    except Exception:  # noqa: BLE001
        return None


def check_cases(answer, material, exists_fn=sc_list_has):
    """[{'name', 'status'}] for each case named in the answer that is not in the material. status: 'real_not_supplied' (in the Supreme Court list), 'not_found' (not in it), 'unknown' (could not look)."""
    out, seen = [], set()
    try:
        mat = _nospace(material)
        for name in _mentions(answer):
            key = _nospace(name)
            if key in seen:
                continue
            seen.add(key)
            if supported_in_material(name, mat):
                continue
            ex = exists_fn(name) if exists_fn else None
            out.append({"name": name, "status": "real_not_supplied" if ex is True else ("not_found" if ex is False else "unknown")})
    except Exception:  # noqa: BLE001
        return []
    return out


# ---- quotations ----
_QUOTE = re.compile(r"“([^”\n]{20,600}?)”|\"([^\"\n]{20,600}?)\"")
_SPLIT = re.compile(r"\.\s?\.\s?\.|…|\[[^\]]*\]")


def _fragments(quote):
    return [f.strip(" ,.;:") for f in _SPLIT.split(quote) if len(norm(f).split()) >= QUOTE_MIN_WORDS]


def _fuzzy_in(frag_norm, material_norm, threshold=0.95):
    words, mw = frag_norm.split(), material_norm.split()
    n = len(words)
    if n == 0 or len(mw) < n:
        return False
    first = words[0]
    for i, w in enumerate(mw[: len(mw) - n + 1]):
        if w != first and difflib.SequenceMatcher(None, w, first).ratio() < 0.8:
            continue
        if difflib.SequenceMatcher(None, " ".join(mw[i:i + n]), frag_norm).ratio() >= threshold:
            return True
    return False


def check_quotes(answer, material):
    """The quotations (five words or more) whose words cannot be found in the material. Returns the original quotation texts."""
    bad = []
    try:
        mat = norm(material)
        for m in _QUOTE.finditer(answer or ""):
            q = m.group(1) or m.group(2)
            for frag in _fragments(q):
                fn = norm(frag)
                if fn and fn not in mat and not _fuzzy_in(fn, mat):
                    bad.append(q.strip())
                    break
    except Exception:  # noqa: BLE001
        return []
    return bad


# ---- wording ----
def notices(cases, quotes):
    out = []
    for c in cases:
        if c["status"] == "not_found":
            out.append(f"The case “{c['name']}” is named in this answer, but it is not among the sources we read for it and we could not find it in our list of Supreme Court judgments. Please do not rely on it.")
        else:
            out.append(f"The case “{c['name']}” is named in this answer, but it is not among the sources we read for it. Please do not rely on it unless you have read the judgment yourself.")
    for q in quotes:
        shown = q if len(q) <= 160 else q[:157].rstrip() + "..."
        out.append(f"The words “{shown}” are in quotation marks in this answer, but we could not find them in the sources we read. Treat them as unverified.")
    return out


RETRY_CASES = ("\n\nCORRECTION NEEDED: your answer names these cases, which are not among the passages given above: {names}. Rewrite the answer without naming any case that has no passage above "
               "(describe the point generally if you need to). Everything else stays as it was.\n")
RETRY_QUOTES = ("\n\nCORRECTION NEEDED: these words are in quotation marks in your answer but do not appear in the passages given above: {quotes}. Either quote the passage exactly, or remove the quotation "
                "marks and say it in your own words. Everything else stays as it was.\n")


def log_line(question_hash, found_cases, found_quotes, note=""):
    print("GROUNDING_CHECK " + json.dumps({"q": question_hash, "mode": mode(), "cases": found_cases, "quotes": [q[:120] for q in found_quotes], "note": note}), flush=True)
