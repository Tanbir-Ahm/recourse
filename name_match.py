"""
name_match.py -- do two case names point to the same case? (added 2026-10-28, FOLLOW_UPS 2cp; used by checker_list.py for the invented-case check)

The check asks "is there a judgment with these parties in the lists we hold?". The titles in those lists are typed by the court, scanned and read by a program, so the same case appears as
"STATE OF U.P." and "State of Uttar Pradesh", "ST ATE OF HYDERABAD", "Sri Rajendra Agrawalla" and "RA.IENDRA AGRAWALLA", "Girja Prasad (Dead) by Lrs" and "Girija Prasad", and a model writes
"Kalika Tiwari v. State of Bihar" for a title that lists three appellants. The older match (grounding_checks.sc_list_has) wanted the same words in the same form and missed those.

THE RULE (all of it is code, nothing is guessed by a model):
  * A name is "first party v. second party". Each party is cleaned: honorifics (Shri, Smt, Dr, M/s), "& Ors", "(Dead) by LRs", "through/represented by ...", "with connected appeals" are dropped;
    Uttar Pradesh/U.P., Government/Govt., Limited/Ltd. and a few more are written one way; a bracket may be read both with and without its content ("State (NCT of Delhi)").
  * A party with several names (commas, "and", "@") is read as a list: one name of the list matching is enough ("Kalika Tiwari" for "Kalika Tiwari, Uma Shankar Rai and others").
  * Two names of a party are the same when their letters (spacing and punctuation ignored) are equal, or differ by the few slips a scanner makes: an extra or missing letter, a letter confused with a
    look-alike (I/L/J, O/0, C/E, U/V), two letters swapped. The allowance grows with the length of the name (none under 14 letters; one up to 23; two up to 33; three beyond), and a substitution
    of an unrelated letter costs two, so "Rakesh" is not "Ramesh" and "Rajesh Kumar Singh" is not "Rakesh Kumar Singh".
  * Initials must agree when both names have them ("K. Kumar" is not "S. Kumar"); a name without initials matches a name with them only when it is long enough to stand alone (10 letters).
  * The first parties must match; the second parties must match too, or share at least half of their words, or one of them must have no words at all. The parties may also be given the other way round.
This is a "same parties" test, not a test that the case is the one meant: two different cases between "Rajesh Kumar" and "State of Bihar" are the same name. Nothing here says a case is good law.
Everything is pure (no files, no network) and never raises on odd input: a name it cannot read matches nothing.
"""
import re

_VS_ANY = re.compile(r"\s+(v\.?|vs\.?|versus)\s+", re.I)

# ---- cleaning
_MS = re.compile(r"\bm\s*/\s*s\.?(?=\s|$)", re.I)
_PAREN = re.compile(r"\(([^()]*)\)")
_PAREN_NOISE = re.compile(r"\b(?:dead|deceased|legal|lrs?|l\.?rs?|connected|through|thru|rep|represented|late|died)\b|^\s*[a-z]?\s*$", re.I)
_CUT = re.compile(r"\b(?:(?:with|and)\s+)?connected\s+(?:appeals?|matters?|cases?|petitions?)\b.*$|\b(?:thru|through|represented|rep|by\s+lrs?|by\s+legal|lrs?)\b.*$|\b(?:dead|deceased)\b.*$")
_CUT_BY = re.compile(r"^(.+?)\s+by\s+\w+.*$")
_PHRASES = [
    ("uttar pradesh", "up"), ("u p", "up"), ("madhya pradesh", "mp"), ("m p", "mp"), ("andhra pradesh", "ap"), ("a p", "ap"), ("himachal pradesh", "hp"), ("h p", "hp"),
    ("arunachal pradesh", "arp"), ("tamil nadu", "tn"), ("t n", "tn"), ("west bengal", "wb"), ("w b", "wb"), ("jammu and kashmir", "jk"), ("j k", "jk"),
    ("government", "govt"), ("department", "dept"), ("company", "co"), ("limited", "ltd"), ("private", "pvt"), ("corporation", "corp"), ("association", "assn"),
    ("commissioner", "commr"), ("district", "dist"), ("superintendent", "supdt"), ("orissa", "odisha"), ("bombay", "mumbai"), ("madras", "chennai"), ("calcutta", "kolkata"),
    ("bangalore", "bengaluru"), ("banglore", "bengaluru"), ("pondicherry", "puducherry"),
]
_DROP = frozenset("""vs versus the of and ors anr another others etc respondent respondents appellant appellants petitioner petitioners
    shri sri smt shrimati srimati dr mr mrs ms hon late alias connected""".split())
_NOISE_WORDS = frozenset("dead deceased lr lrs".split())


def _squash(s):
    return re.sub(r"\s+", " ", s).strip()


def _plain(s):
    s = (s or "").lower().replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    s = _MS.sub(" ", s)
    s = s.replace("&", " and ").replace("@", " @ ")
    s = re.sub(r"[‐-―]", " ", s)
    s = re.sub(r"[^a-z0-9@,\s]", " ", s)                       # full stops, brackets, apostrophes become spaces, so "U.P." is "u p" and "D.K." is "d k"
    return _squash(s)


def _variants(raw):
    """Texts of one party: with every bracket removed, and (only when a bracket holds a real name) with the bracket kept."""
    raw = raw if isinstance(raw, str) else ""
    a = _PAREN.sub(" ", raw)
    out = [a]
    kept = []
    changed = False

    def keep(m):
        nonlocal changed
        inner = m.group(1)
        if len(re.findall(r"[A-Za-z]{2,}", inner)) >= 1 and len(inner.strip()) >= 3 and not _PAREN_NOISE.search(inner):
            changed = True
            return " " + inner + " "
        return " "
    b = _PAREN.sub(keep, raw)
    if changed:
        out.append(b)
    return out


def _canon(text):
    s = " " + text + " "
    for a, b in _PHRASES:
        s = s.replace(f" {a} ", f" {b} ")
    return _squash(s)


def _segments(variant):
    """[(initials, words, concat, from_split)] for one variant of a party: the whole party first, then (if the party lists several names) each name."""
    low = variant.lower()
    low = _CUT.sub(" ", _plain(low))
    low = _CUT_BY.sub(r"\1", low)
    whole = _canon(_squash(low.replace(",", " ").replace("@", " ")))
    parts = []
    pieces = [p for p in re.split(r"\s*(?:,|@|\band\b)\s*", low) if p.strip()]
    if len(pieces) > 1:
        parts = [_canon(_squash(p)) for p in pieces]
    out = []
    for text, split in [(whole, False)] + [(p, True) for p in parts]:
        toks = [t for t in text.split() if t not in _DROP and t not in _NOISE_WORDS]
        initials = tuple(t for t in toks if len(t) == 1 and t.isalpha())
        words = tuple(t for t in toks if not (len(t) == 1 and t.isalpha()))
        if not words and len(initials) >= 3:                      # M.C.D., C.B.I., N.I.A.: a body known by its letters
            words, initials = ("".join(initials),), ()
        concat = "".join(words)
        if concat:
            out.append((initials, words, concat, split))
    return out


def parse_party(raw):
    seen, out = set(), []
    for v in _variants(raw):
        for seg in _segments(v):
            if seg[:3] not in seen:
                seen.add(seg[:3])
                out.append(seg)
    return out


def split_versus(name):
    """[first party, second party] (or [name] when there is no 'v.'). The marker is v / v. / vs / versus; a capital 'V' or 'V.' counts only when the word after it is not an initial
    ('Dr. V. K. Saxena v. State of U.P.' has its marker at the lowercase v.; 'ARNESH KUMAR versus STATE OF BIHAR' at the versus)."""
    name = name if isinstance(name, str) else ""
    marks = list(_VS_ANY.finditer(name))
    pick = next((m for m in marks if m.group(1) not in ("V", "V.")), None)
    if pick is None:
        pick = next((m for m in marks if not re.match(r"[A-Za-z]\.?(\s|$)", name[m.end():m.end() + 3])), None)
    if pick is None:
        return [name]
    return [name[:pick.start()], name[pick.end():]]


_GENERIC = frozenset("""state union india govt dept central commr inspector police station dist sho officer secretary home ministry rep represented by through thru""".split())


def _bag(raw):
    """(distinct words, generic words) of one party read whole (nothing cut off, the longest reading of a bracket): the words that tell one body or person from another, and 'state', 'union', 'police' ... ."""
    best = set()
    for v in _variants(raw):
        text = _canon(_plain(v).replace(",", " ").replace("@", " "))
        words = {t for t in text.split() if t not in _DROP and t not in _NOISE_WORDS and not (len(t) == 1 and t.isalpha())}
        if len(words) > len(best):
            best = words
    return (frozenset(w for w in best if w not in _GENERIC), frozenset(w for w in best if w in _GENERIC))


def parse_name(name):
    """(first party segments, second party segments, second party bag); the second is [] and the bag empty for a name that is only one party."""
    parts = split_versus(name)
    if len(parts) == 2:
        return parse_party(parts[0]), parse_party(parts[1]), _bag(parts[1])
    return parse_party(parts[0]), [], (frozenset(), frozenset())


# ---- edit distance with the allowance described at the top
_LOOK = {frozenset(p) for p in ("il", "ij", "lj", "1l", "1i", "o0", "ce", "uv", "nh", "ao")}


def _sub_cost(a, b):
    return 0 if a == b else (1 if frozenset((a, b)) in _LOOK else 2)


def wdist(a, b, limit):
    """Weighted edit distance of a and b (insert/delete 1, swap of neighbours 1, look-alike letter 1, other substitution 2), or limit + 1 when it is more than limit."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2 = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j in range(1, len(b) + 1):
            c = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + _sub_cost(a[i - 1], b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                c = min(c, prev2[j - 2] + 1)
            cur[j] = c
            if c < best:
                best = c
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1] if prev[-1] <= limit else limit + 1


def allowance(n):
    """Slips allowed in a name of n letters (the shorter of the two)."""
    return 0 if n < 14 else 1 if n < 24 else 2 if n < 34 else 3


def tok_eq(a, b):
    """Two single words are the same word: equal, or (words of 8+ letters) one slip apart."""
    if a == b:
        return True
    return min(len(a), len(b)) >= 8 and wdist(a, b, 1) <= 1


def seg_match(x, y):
    """Do two segments (see _segments) name the same person or body?"""
    ia, wa, ca, sa = x
    ib, wb, cb, sb = y
    if not ca or not cb:
        return False
    if (sa and not (len(wa) >= 2 or len(ca) >= 6)) or (sb and not (len(wb) >= 2 or len(cb) >= 6)):
        return False                                           # one name taken out of a list must be able to stand alone
    if ia and ib and ia != ib:
        return False
    if (ia and not ib) or (ib and not ia):
        if min(len(ca), len(cb)) < 10:
            return False
    if ca == cb:
        return True
    n = min(len(ca), len(cb))
    return wdist(ca, cb, allowance(n)) <= allowance(n)


def party_match(pa, pb):
    return any(seg_match(x, y) for x in pa for y in pb)


def _first_words(p):
    return min((len(x[2]) for x in p if not x[3]), default=0)


_PARTICLES = frozenset("""mohd mohammad mohammed muhammad md mohamed mohmed singh kumar kumari devi lal ram rani kaur khan begum bai prasad chand chandra nath das dass sharma rao reddy naidu nair pillai ali ahmed ahmad
    hussain shah bibi lakshmi kumar kr lall sahu sah yadav mandal""".split())


def _shared(x, y):
    """Number of words of x that have a counterpart in y (equal, or one slip apart in a long word)."""
    return sum(1 for t in x if any(tok_eq(t, u) for u in y))


def second_ok(pa, pb, ba, bb, strict=False):
    """The second parties may be taken as the same:
      * one of them has no words (nothing to contradict; not allowed when `strict`);
      * both have words that tell people or bodies apart: they share at least one such word that is not a common name-particle (Singh, Kumar, Mohd ...) and at least half of the smaller set, and where both
        carry particles they are the same ones ('Ajay Singh' is not 'Ajay Kumar'; 'State of Bihar' is not 'State of Punjab'; 'State (Delhi Admn.)' is 'State (NCT of Delhi)');
      * one side has only particles: the two sets must be equal;
      * neither has such words ('State', 'Union of India', 'State rep. by the Inspector of Police'): they share a generic word, and not when `strict`.
    strict is for a first party that is a short single word such as 'Kumar' or 'Sanjay', which names thousands of people: the second party must be shown to be the same, not merely not contradicted."""
    da, ga = ba
    db, gb = bb
    if not pa or not pb or not (da or ga) or not (db or gb):
        return not strict
    if da and db:
        na, nb = frozenset(w for w in da if w not in _PARTICLES), frozenset(w for w in db if w not in _PARTICLES)
        if na and nb:
            shared = _shared(na, nb)
            if shared < 1 or shared / min(len(na), len(nb)) < 0.5:
                return False
            qa, qb = da - na, db - nb
            return not (qa and qb and qa != qb)
        return da == db
    if strict:
        return not da and not db and bool(ga & gb)
    return bool(ga & gb)


def names_match(q, c):
    """q and c are parse_name results. True when they read as the same parties."""
    q1, q2, qb = q
    c1, c2, cb = c
    if not q1 or not c1:
        return False
    if party_match(q1, c1) and second_ok(q2, c2, qb, cb, strict=_first_words(q1) < 12):
        return True
    return bool(q2 and c2 and party_match(q1, c2) and party_match(q2, c1))
