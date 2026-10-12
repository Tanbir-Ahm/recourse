"""The Overruled Register: decisions that a later court has overruled, reversed or disapproved, kept as facts with their evidence and their trust level.

What it is for. An answer must never state an overruled decision's holding as current law. The checker (goodlaw/report.py) reads judgments and can only warn; this register holds what a
person has confirmed, or what an outside list says, and answers "has the Supreme Court said this decision is overruled?" for a case named in a question, a retrieved passage or a finished
answer. Nothing here is a verdict of the code: the code only looks up and words what a row says.

Rows and trust. Each row says: decision A (the overruled one), decision B (the overruling one), the treatment in the court's words, the evidence, who verified it and when, and a history.
    verified             the owner's lawyer-verified 2015 list (list 1), as recorded on 2026-10-07; wording is firm
    reviewer_confirmed   a row the reviewer confirmed one by one (a candidate promoted, or a checker flag confirmed); wording is firm
    candidate            checked against the judgment's own text by Claude, not by a lawyer (list 2, the post-2015 list, and sibling decisions found in the same judgments); wording says
                         "reported ... not yet confirmed by our reviewer"
    unchecked            named by an outside list but not found in our text; never worded, only queued for review
    rejected             a candidate or unchecked row the reviewer rejected; kept (nothing is deleted), never worded
Treatments are the court's words, not one flag: overruled | overruled_in_part | not_good_law | per_incuriam | not_binding | not_approved | reversed_on_appeal | disputed_listing.

Matching (never a bare name). A decision is recognised by (1) a reported citation that is on the row, or (2) BOTH party names in the row's order followed by a year within one of the row's years
(reporter year and decision year differ by one). Both names without a year is a weak match: reported for a person, never worded as a fact. A first party alone ("Mohan Lal") is ignored.

Chains. If B is itself the overruled decision of another row, a note is added ("B was itself later ...; check the current position"). A row is never silently carried forward.
"""
import datetime
import functools
import json
import os
import re

from . import cites as C

SCHEMA = "goodlaw-register-1"
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "register", "register.json")

TRUST_FIRM = ("verified", "reviewer_confirmed")
TRUSTS = ("verified", "reviewer_confirmed", "candidate", "unchecked", "rejected")
NO_WORDING = ("unchecked", "rejected")
TREATMENTS = ("overruled", "overruled_in_part", "not_good_law", "per_incuriam", "not_binding", "not_approved", "reversed_on_appeal", "disputed_listing")

_PHRASE = {
    "overruled": "overruled by {b}",
    "overruled_in_part": "overruled in part by {b}",
    "not_good_law": "held not to be good law in {b}",
    "per_incuriam": "held to have been decided per incuriam in {b}",
    "not_binding": "held not to be a binding precedent in {b}",
    "not_approved": "not approved in {b}",
    "reversed_on_appeal": "reversed on appeal by the Supreme Court in {b}",
    "disputed_listing": "listed in our reference list as overruled by {b}, but the list is inconsistent on this entry",
}

# ----- names ------------------------------------------------------------------------------------------------------------------------------------------------------------------

_TOK = re.compile(r"[A-Za-z0-9]+")
_STOP = {"v", "vs", "versus", "the", "of", "and", "an", "a", "in", "re", "m", "s", "ors", "anr", "anrs", "others", "another", "etc", "through", "by", "its", "lrs", "lr", "dead", "late",
         "pvt", "ltd", "limited", "private", "co", "company", "inc", "mr", "mrs", "ms", "dr", "shri", "sri", "smt", "kumari", "for", "to", "on", "at", "no", "ex", "rep"}
_VS = {"v", "vs", "versus"}
_STATE_PAIRS = {("u", "p"): "uttar_pradesh", ("m", "p"): "madhya_pradesh", ("a", "p"): "andhra_pradesh", ("h", "p"): "himachal_pradesh", ("t", "n"): "tamil_nadu",
                ("w", "b"): "west_bengal", ("j", "k"): "jammu_kashmir"}
_STATE_ABBR = {"up": "uttar_pradesh", "mp": "madhya_pradesh", "ap": "andhra_pradesh", "hp": "himachal_pradesh", "tn": "tamil_nadu", "wb": "west_bengal"}
_STATE_WORDS = {("uttar", "pradesh"): "uttar_pradesh", ("madhya", "pradesh"): "madhya_pradesh", ("andhra", "pradesh"): "andhra_pradesh", ("himachal", "pradesh"): "himachal_pradesh",
                ("tamil", "nadu"): "tamil_nadu", ("west", "bengal"): "west_bengal"}
_GENERIC = {"state", "union", "india", "government", "commissioner", "collector", "king", "emperor", "crown", "corporation", "board", "authority", "officer", "income", "tax", "central", "excise",
            "customs", "bank", "municipal", "district", "magistrate", "secretary", "registrar", "director", "manager", "chairman", "committee", "society", "university", "college", "court",
            "judge", "public", "service", "commission", "department", "ministry", "uttar_pradesh", "madhya_pradesh", "andhra_pradesh", "tamil_nadu", "west_bengal", "punjab", "bihar",
            "maharashtra", "gujarat", "kerala", "karnataka", "orissa", "rajasthan", "delhi", "madras", "bombay", "bengal"}
_SKIP = 10               # tokens that may sit between the first party's leading words and the 'v' (a long name, a town)
_N1, _N2 = 3, 2          # party tokens that must agree: the first three of party 1 and the first two of party 2 (names are often shortened or lose a trailing town)
_YEAR = re.compile(r"\b(1[89]\d\d|20[0-3]\d)\b")


def tokenize(text):
    """[(token, start, end)] lower-cased letters-and-digits runs. Dotted initials are one token ('K.L.' and 'KL' both -> 'kl'; 'A.D.M.' and 'ADM' -> 'adm'); 'U.P.', 'UP' after 'State of'
    and 'Uttar Pradesh' are one token."""
    raw = [(m.group(0).lower(), m.start(), m.end()) for m in _TOK.finditer(text)]
    merged, i = [], 0
    while i < len(raw):
        j = i
        while (j + 1 < len(raw) and len(raw[j][0]) == 1 and len(raw[j + 1][0]) == 1 and raw[j][0].isalpha() and raw[j + 1][0].isalpha() and raw[j][0] != "v" and raw[j + 1][0] != "v"
               and re.fullmatch(r"\.\s?", text[raw[j][2]:raw[j + 1][1]] or "")):
            j += 1
        if j > i:
            merged.append(("".join(t for t, _, _ in raw[i:j + 1]), raw[i][1], raw[j][2]))
            i = j + 1
        else:
            merged.append(raw[i])
            i += 1
    out, i = [], 0
    while i < len(merged):
        t = merged[i][0]
        if t in _STATE_ABBR and out and out[-1][0] in ("state", "of"):
            out.append((_STATE_ABBR[t], merged[i][1], merged[i][2]))
            i += 1
            continue
        if i + 1 < len(merged):
            pair = (t, merged[i + 1][0])
            if pair in _STATE_WORDS:
                out.append((_STATE_WORDS[pair], merged[i][1], merged[i + 1][2]))
                i += 2
                continue
            if pair in _STATE_PAIRS and out and out[-1][0] in ("state", "of"):
                out.append((_STATE_PAIRS[pair], merged[i][1], merged[i + 1][2]))
                i += 2
                continue
        out.append(merged[i])
        i += 1
    return out


def split_parties(name):
    """('Kharak Singh', 'State of U.P.') from 'Kharak Singh v. State of U.P.'; (name, '') when there is no 'v'."""
    parts = re.split(r"\s+(?:v\.?|vs\.?|versus)\s+", name or "", maxsplit=1, flags=re.I)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ((name or "").strip(), "")


def significant(party, limit=5):
    return [t for t, _, _ in tokenize(party) if t not in _STOP][:limit]


def indexable(s1, s2):
    """A name pair may be matched by name (with a year) only if the two names together hold at least two different words that are not common (state, union, commissioner, a state's name ...):
    'Mohan Lal v. State of Punjab' qualifies, 'Srinivasulu v. State of Andhra Pradesh' and 'Sekar v. State' do not (they are found by citation only)."""
    if not s1 or not s2:
        return False
    return len({t for t in list(s1) + list(s2) if t not in _GENERIC}) >= 2


@functools.lru_cache(maxsize=None)
def party_sigs(name):
    """(significant tokens of party 1, of party 2), at most four each."""
    p1, p2 = split_parties(re.sub(r"\([^)]*\)", " ", name or ""))
    return tuple(significant(p1, 4)), tuple(significant(p2, 4))


def years_in(text):
    return [int(y) for y in _YEAR.findall(text or "")]


# ----- sentences ----------------------------------------------------------------------------------------------------------------------------------------------------------

_ABBR = {"v", "vs", "no", "nos", "dr", "mr", "mrs", "ms", "smt", "shri", "sri", "co", "ltd", "pvt", "anr", "ors", "etc", "re", "st", "sec", "secs", "art", "arts", "cl", "para", "paras", "vol", "ed",
         "viz", "ie", "eg", "cf", "hon", "justice", "j", "jj", "cj", "cji", "addl", "asst", "dist", "govt", "dept", "corp", "assn", "regd", "retd", "p", "w", "m"}
_BOUND = re.compile(r"[.!?]+(?=\s+[A-Z\"(\[“])")


def sentences(text):
    """[(start, end, sentence)]. A full stop after a legal abbreviation ('v.', 'Co.', 'U.P.', 'Dr.', an initial) is not a sentence end."""
    out, last = [], 0
    for m in _BOUND.finditer(text):
        w = re.search(r"([A-Za-z][A-Za-z.]*)$", text[max(0, m.start() - 24):m.start()])
        word = w.group(1) if w else ""
        if m.group(0) == "." and (word.lower() in _ABBR or len(word) == 1 or re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]", word)):
            continue
        out.append((last, m.end(), text[last:m.end()]))
        last = m.end()
        while last < len(text) and text[last].isspace():
            last += 1
    if last < len(text):
        out.append((last, len(text), text[last:]))
    return out


# ----- citations --------------------------------------------------------------------------------------------------------------------------------------------------------------

_HC_AIR = re.compile(r"\bAIR\s*\(?\s*((?:18|19|20)\d\d)\s*\)?\s+([A-Za-z&]{2,8})\s*(?:\(\d\)\s*)?(\d{1,4})\b")


def hc_keys(text):
    """[(key, start, end)] for AIR citations of courts other than the Supreme Court ('AIR 1965 All 586' -> airx:1965:all:586)."""
    out = []
    for m in _HC_AIR.finditer(text):
        court = m.group(2).lower()
        if court == "sc":
            continue
        out.append((f"airx:{m.group(1)}:{court}:{m.group(3)}", m.start(), m.end()))
    return out


def all_cite_keys(text):
    """[(key, start, end)] Supreme Court reporter keys (goodlaw.cites) plus High Court AIR keys."""
    return sorted(C.find_cites(text) + hc_keys(text), key=lambda x: x[1])


def key_set(text):
    """Distinct keys of every citation in a string, exactly as printed (no volume-less variants: those would make two different volumes' page 332 look alike)."""
    out = []
    for k, _, _ in all_cite_keys(text):
        if k not in out:
            out.append(k)
    return out


def keys_agree(a, b):
    """Equal keys, or the same SCR page where one side prints no volume (or only 'Supp')."""
    if a == b:
        return True
    if a.startswith(("airx:", "air:")) or b.startswith(("airx:", "air:")):
        return False
    try:
        return C.keys_match(a, b)
    except (ValueError, IndexError):
        return False


# ----- the register -----------------------------------------------------------------------------------------------------------------------------------------------------------

class Match(dict):
    """A hit: row, how ('citation' | 'name_year' | 'name_only'), strength ('strong' | 'weak'), start, end (positions in the scanned text)."""
    def __getattr__(self, k):
        return self[k]


def _first_name(party_sig):
    return party_sig[0] if party_sig else None


class Register:
    def __init__(self, rows, meta=None):
        self.meta = meta or {}
        self.rows = rows
        self.by_id = {r["id"]: r for r in rows}
        self._by_key = {}
        self._scr_page = {}
        self._by_first = {}
        self._variants = {}
        for r in rows:
            o = r["overruled"]
            for k in o.get("keys", []):
                self._by_key.setdefault(k, []).append(r)
                if k.startswith("scr:"):
                    _, y, ser, pg = k.split(":")
                    self._scr_page.setdefault((y, pg), []).append((r, ser))
            self._variants[r["id"]] = []
            for nm in [o["name"]] + list(o.get("alt_names", [])):
                s1, s2 = (list(x) for x in party_sigs(nm))
                if indexable(s1, s2):
                    self._variants[r["id"]].append((s1, s2))
                    if r not in self._by_first.setdefault(s1[0], []):
                        self._by_first[s1[0]].append(r)
        self._chain = {}
        for r in rows:
            b = r["overruling"]
            cands = {}
            for k in b.get("keys", []):
                for s in self.rows_for_key(k):
                    cands[s["id"]] = s
            b1, b2 = party_sigs(b.get("name", ""))
            if indexable(b1, b2):
                for s in self._by_first.get(b1[0], ()):
                    cands[s["id"]] = s
            self._chain[r["id"]] = [i for i, s in cands.items() if s is not r and self._same_decision(b, s["overruled"])]
        self._same = {}
        for r in rows:
            a = r["overruled"]
            cands = {}
            for k in a.get("keys", []):
                for s in self.rows_for_key(k):
                    cands[s["id"]] = s
            for s1, s2 in self._variants[r["id"]]:
                for s in self._by_first.get(s1[0], ()):
                    cands[s["id"]] = s
            self._same[r["id"]] = [i for i, s in cands.items() if s is not r and self._same_decision(a, s["overruled"])]

    # --- loading
    @classmethod
    def load(cls, path=None):
        d = json.load(open(path or DEFAULT_PATH, encoding="utf-8"))
        if d.get("schema") != SCHEMA:
            raise ValueError(f"unexpected register schema {d.get('schema')!r}")
        return cls(d["rows"], {k: v for k, v in d.items() if k != "rows"})

    # --- matching
    def rows_for_key(self, key):
        """Rows whose overruled decision carries this citation key: the same key, or the same SCR page where one side prints no volume."""
        out = {r["id"]: r for r in self._by_key.get(key, ())}
        if key.startswith("scr:"):
            _, y, ser, pg = key.split(":")
            for r, ser2 in self._scr_page.get((y, pg), ()):
                if ser == ser2 or ser in ("", "s") or ser2 in ("", "s"):
                    out[r["id"]] = r
        return list(out.values())

    def _same_decision(self, a, b):
        """Two decision records (name, cites, year) denote one decision: a shared citation key, or both parties in order and years within one."""
        if any(keys_agree(x, y) for x in a.get("keys", []) for y in b.get("keys", [])):
            return True
        if not any(self._names_agree(x, y) for x in [a.get("name", "")] + list(a.get("alt_names", [])) for y in [b.get("name", "")] + list(b.get("alt_names", []))):
            return False
        ya = set(a.get("years") or ([a["year"]] if a.get("year") else []))
        yb = set(b.get("years") or ([b["year"]] if b.get("year") else []))
        return any(abs(x - y) <= 1 for x in ya for y in yb)

    @staticmethod
    def _names_agree(na, nb):
        sa, sb = party_sigs(na), party_sigs(nb)
        if not (indexable(sa[0], sa[1]) and indexable(sb[0], sb[1])):
            return False
        n1, n2 = min(len(sa[0]), len(sb[0]), _N1), min(len(sa[1]), len(sb[1]), _N2)
        return sa[0][:n1] == sb[0][:n1] and sa[1][:n2] == sb[1][:n2]

    def _name_hits(self, text):
        toks = tokenize(text)
        out = []
        for i, (t, s0, e0) in enumerate(toks):
            for r in self._by_first.get(t, ()):
                for s1, s2 in self._variants[r["id"]]:
                    if s1[0] != t:
                        continue
                    j = self._seq(toks, i, s1, min(len(s1), _N1))
                    if j is None:
                        continue
                    # up to two further tokens (a town, an abbreviation), then the 'v'
                    k = j
                    while k < len(toks) and toks[k][0] not in _VS and k - j <= _SKIP:
                        k += 1
                    if k >= len(toks) or toks[k][0] not in _VS:
                        continue
                    j2 = self._seq(toks, k + 1, s2, min(len(s2), _N2), lead=True)
                    if j2 is None:
                        continue
                    out.append((r, s0, toks[j2 - 1][2]))
                    break
        return out

    @staticmethod
    def _seq(toks, i, want, need, lead=False):
        """Index after the tokens `want[:need]` found in order starting at toks[i] (filler tokens allowed between and, if `lead`, before); None if not found."""
        pos = i
        for n, w in enumerate(want[:need]):
            gaps = 0
            while pos < len(toks) and toks[pos][0] != w:
                if not (toks[pos][0] in _STOP or len(toks[pos][0]) == 1) or gaps >= 5 or (n == 0 and not lead):
                    return None
                pos += 1
                gaps += 1
            if pos >= len(toks):
                return None
            pos += 1
        return pos

    def scan(self, text):
        """Every recognised register decision in text. A list of Match, strongest first per row; the same row is reported once per position."""
        hits = []
        seen = set()
        for key, s, e in all_cite_keys(text):
            for r in self.rows_for_key(key):
                if (r["id"], "citation", s) not in seen:
                    seen.add((r["id"], "citation", s))
                    hits.append(Match(row=r, how="citation", strength="strong", start=s, end=e))
        for r, s, e in self._name_hits(text):
            window = text[max(0, s - 12): e + 170]
            ys = set(years_in(window))
            ys |= {int(k.split(":")[1]) for k, _, _ in all_cite_keys(window)}
            rows_years = set(r["overruled"].get("years") or ([r["overruled"]["year"]] if r["overruled"].get("year") else []))
            ok = any(abs(y - ry) <= 1 for y in ys for ry in rows_years)
            how, strength = ("name_year", "strong") if ok else ("name_only", "weak")
            if (r["id"], how, s) not in seen:
                seen.add((r["id"], how, s))
                hits.append(Match(row=r, how=how, strength=strength, start=s, end=e))
        # a citation hit and a name hit on the same row are one finding: keep the citation one
        by_row = {}
        for h in sorted(hits, key=lambda h: (h["row"]["id"], 0 if h["how"] == "citation" else 1 if h["how"] == "name_year" else 2, h["start"])):
            by_row.setdefault(h["row"]["id"], []).append(h)
        out = []
        for rid, hs in by_row.items():
            if any(h["strength"] == "strong" for h in hs):
                hs = [h for h in hs if h["strength"] == "strong"]
            first = {}
            for h in hs:
                first.setdefault(h["start"] // 400, h)
            out.extend(first.values())
        return sorted(out, key=lambda h: h["start"])

    def lookup_case(self, name=None, year=None, citation=None):
        """The register rows for one named case (a library case, a retrieved passage's case): same rules as scan, on a short synthetic text."""
        text = " ".join(x for x in (name, f"({year})" if year else None, citation) if x)
        return self.scan(text)

    # --- chains and wording
    def chain(self, row):
        """Rows whose overruled decision is this row's overruling decision (B was itself later overruled / disapproved)."""
        return [self.by_id[i] for i in self._chain.get(row["id"], ())]

    @staticmethod
    def _bname(row):
        b = row["overruling"]
        y = (b.get("date") or "")[:4] or b.get("year")
        return f"{b['name']} ({y})" if y else b["name"]

    def phrase(self, row):
        t = row["treatment"]
        text = _PHRASE.get(t, "{b}").format(b=self._bname(row))
        if row.get("scope") and t in ("overruled_in_part", "not_binding", "not_approved"):
            text += f" ({row['scope']})"
        return text

    def clause(self, row, with_chain=True):
        """The sentence an answer may carry for this row, or None for an unchecked row. Firm for verified and reviewer-confirmed rows, hedged for candidates."""
        if row["trust"] in NO_WORDING:
            return None
        a = row["overruled"]
        label = a["name"] + (f" ({a['year']})" if a.get("year") else "")
        ph = self.phrase(row)
        if row["trust"] in TRUST_FIRM:
            s = f"{label} was {ph}." if row["treatment"] not in ("disputed_listing",) else f"{label} is {ph}."
        else:
            s = f"{label} is reported as {ph} (not yet confirmed by our reviewer)."
        if with_chain:
            for nxt in self.chain(row):
                s += f" Note: {row['overruling']['name']} was itself later {self.phrase(nxt)}; the current position should be checked."
        return s

    def same_decision_rows(self, row):
        """The other rows whose overruled decision is this row's (the same decision overruled by different later cases, or listed twice)."""
        return [self.by_id[i] for i in self._same.get(row["id"], ())]

    def clause_group(self, rows):
        """One sentence for rows that concern the same overruled decision: the firmest row first, the others as 'also reported'."""
        rows = sorted((r for r in rows if r["trust"] not in NO_WORDING), key=lambda r: (TRUSTS.index(r["trust"]), r["id"]))
        if not rows:
            return None
        lead, rest = rows[0], rows[1:]
        s = self.clause(lead)
        for r in rest:
            if self._same_decision(r["overruling"], lead["overruling"]):
                continue
            if r["trust"] in TRUST_FIRM:
                s += f" It was also {self.phrase(r)}."
            else:
                s += f" It is also reported as {self.phrase(r)} (not yet confirmed by our reviewer)."
        return s

    def match_class(self, row):
        """How a row can be recognised: 'name_year' (strong by its own name and year), 'citation' (only by a reported citation), 'weak' (its name alone), 'none'."""
        o = row["overruled"]
        nm = re.sub(r"\s+Vs\.?\s+", " v. ", o["name"], flags=re.I)
        if self._scan_row(nm + (f" ({o['year']})" if o.get("year") else ""), row, strong=True):
            return "name_year"
        if o.get("cites") and self._scan_row(" ; ".join(o["cites"]), row, strong=True):
            return "citation"
        if self._scan_row(nm, row, strong=False):
            return "weak"
        return "none"

    def _scan_row(self, text, row, strong):
        hits = [h for h in self.scan(text) if h["row"]["id"] == row["id"]]
        return any(h["strength"] == "strong" for h in hits) if strong else bool(hits)

    # --- review state
    def counts(self):
        out = {}
        for r in self.rows:
            k = (r["source"], r["trust"])
            out[k] = out.get(k, 0) + 1
        return out


def slim(rows):
    """What a site needs to recognise and word a row (no history, no evidence text): the bundle written by `register-export-site`."""
    out = []
    for r in rows:
        if r["trust"] in ("rejected",):
            continue
        a, b = r["overruled"], r["overruling"]
        out.append({"id": r["id"], "source": r["source"], "trust": r["trust"], "treatment": r["treatment"], "scope": r.get("scope"),
                    "overruled": {"name": a["name"], "alt_names": a.get("alt_names", []), "keys": a.get("keys", []), "year": a.get("year"), "years": a.get("years", [])},
                    "overruling": {"name": b.get("name", ""), "keys": b.get("keys", []), "year": b.get("year"), "date": b.get("date"), "alt_names": b.get("alt_names", []), "years": b.get("years", [])}})
    return out


def today_str(today=None):
    return today or datetime.date.today().isoformat()


def add_event(row, event, by, on=None, note=None):
    """Append-only history: events are only ever added."""
    row.setdefault("history", []).append({"on": today_str(on), "by": by, "event": event, **({"note": note} if note else {})})
    return row


def save(rows, meta, path=None):
    d = {"schema": SCHEMA, **meta, "rows": rows}
    p = path or DEFAULT_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return p
