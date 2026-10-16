"""The cards overlay: what the site may say about a case that is NOT on the Overruled Register, and the fixed "not checked by us" wording for a case that is on neither list.

Order of lookup on the site (see REGISTER_SITE_PATCH.md): the register first (register.py: firm for verified rows, "reported ... not yet confirmed" for candidates), then this overlay (the checker's cards,
computed ahead of time), then the fixed sentence NOT_CHECKED. Nothing here ever says a case "is good law": a quiet card is silence in the judgments we hold, not a finding about the law, and the
wording says so. A person's decision (the register, or a reviewed card) always outranks the checker's reading.

    overlay = Overlay.load(path)                    # overlay_slim.json made by build_overlay()
    overlay.lookup(name, year, citation)            # an entry or None
    audit_answer(reg, overlay, answer_text)         # {'register_notes', 'card_notes', 'not_checked'} for a finished answer

Cases are found by reported citation (cites.py) or by both party names plus a year within one (register.party_sigs / indexable), never by a bare name. A case described without its name is invisible.
Source label on every entry: pattern-rule reading of Supreme Court texts; not lawyer-validated.
"""
import json
import os
import re

from . import cites as C
from . import register as R

SCHEMA = "goodlaw-overlay-1"
LABEL = "pattern-rule reading of Supreme Court texts; not lawyer-validated"
NOT_CHECKED = "Not checked by us: we have not checked whether this decision is still good law. Please ask a lawyer before relying on it."
NOT_CHECKED_LIST = "Cases named in this answer that we have not checked: {names}. Please ask a lawyer before relying on any of them."
QUIET = "Our automatic check found no later Supreme Court judgment, among those we hold (up to {as_of}), that goes against this case. That is not a finding that it is still good law."
ADVERSE_KINDS = ("ADVERSE_SIGNAL", "QUESTIONED")
_QUOTE_MAX = 260


def note_for_card(card, as_of):
    """(kind, text) for one card: kind is 'warning', 'caution', 'quiet' or 'not_checked'. Only the checker's own plain note is used for warnings and cautions."""
    st = card.get("status")
    if st == "ADVERSE_SIGNAL" and card.get("user_facing_note"):
        return "warning", card["user_facing_note"]
    if st == "QUESTIONED" and card.get("user_facing_note"):
        return "caution", card["user_facing_note"]
    if st == "NO_ADVERSE_FOUND":
        return "quiet", QUIET.format(as_of=as_of or "the date of the last check")
    return "not_checked", NOT_CHECKED


def _quote(card):
    for e in card.get("evidence") or []:
        q = (e.get("quote") or "").strip()
        if q and e.get("quote_verified", True):
            q = re.sub(r"\s+", " ", q)
            return {"quote": q[:_QUOTE_MAX] + ("..." if len(q) > _QUOTE_MAX else ""), "title": e.get("title"), "year": e.get("year"), "date": e.get("date")}
    return None


def build_overlay(cards_doc, today=None):
    """The slim overlay from a cards file (cards/currency_cards.json): one entry per card, wording fixed here, no auditor trail."""
    cards = cards_doc["cards"]
    as_of = ((cards_doc.get("cards") or [{}])[0].get("provenance") or {}).get("corpus", {}).get("latest_judgment_date")
    entries = []
    for c in cards:
        kind, note = note_for_card(c, as_of)
        case = c.get("case") or {}
        keys = sorted(set(case.get("citation_keys") or []) | set(C.cite_keys(case.get("citation") or "")))
        e = {"name": case.get("name"), "citation": case.get("citation"), "year": case.get("year"), "keys": keys, "status": c.get("status"), "kind": kind, "note": note}
        if kind in ("warning", "caution"):
            q = _quote(c)
            if q:
                e["evidence"] = q
        if c.get("statute_flag") and c.get("statute_note"):
            e["statute_note"] = c["statute_note"]
        entries.append(e)
    return {"schema": SCHEMA, "label": LABEL, "generated": R.today_str(today), "as_of": as_of, "not_checked": NOT_CHECKED, "counts": _counts(entries), "entries": entries}


def _counts(entries):
    out = {}
    for e in entries:
        out[e["kind"]] = out.get(e["kind"], 0) + 1
    return out


class Overlay:
    def __init__(self, doc):
        self.doc = doc
        self.entries = doc["entries"]
        self.by_key = {}
        for i, e in enumerate(self.entries):
            for k in e.get("keys") or []:
                for v in C.key_variants(k):
                    self.by_key.setdefault(v, []).append(i)
        self.sigs = [R.party_sigs(e.get("name") or "") for e in self.entries]

    @classmethod
    def load(cls, path=None):
        path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlay_slim.json")
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def lookup(self, name=None, year=None, citation=None):
        """The overlay entry for one named case, or None. By citation first; then by both party names and a year within one (a name pair that is only common words is not matched by name)."""
        text = " ".join(x for x in (citation, name) if x)
        for k in C.cite_keys(text):
            for v in C.key_variants(k):
                for i in self.by_key.get(v, ()):
                    return self.entries[i]
        s1, s2 = R.party_sigs(name or "")
        if not (s1 and s2 and R.indexable(s1, s2)) or not year:
            return None
        for i, (e1, e2) in enumerate(self.sigs):
            ey = self.entries[i].get("year")
            if e1 == s1 and e2 == s2 and ey and abs(int(ey) - int(year)) <= 1:
                return self.entries[i]
        return None


# ----- finding every case an answer names ------------------------------------------------------------------------------------------------------------------------------

_WORD = r"(?:[A-Z][\w.'’&-]*\.?|of|the|and|&|\([A-Za-z.]{1,8}\)|@)"
_PAREN = r"\s+\([A-Z][A-Za-z.]*(?:\s+[A-Za-z.]+){0,6}\)"            # a closing parenthetical of the second party: 'State (Narcotic Branch of Delhi)'
_NAME = re.compile(r"(?P<p1>[A-Z][\w.'’&-]*\.?(?:\s+" + _WORD + r"){0,6}?)\s+(?:v\.?|vs\.?|versus)\s+(?P<p2>[A-Z][\w.'’&-]*\.?(?:\s+" + _WORD + r"){0,6}(?:" + _PAREN + r")?)"
                   r"(?P<tail>\s*,?\s*\(?(?P<year>(?:19|20)\d\d)\)?)?")
_LEAD_STOP = {"the", "in", "see", "also", "as", "of", "and", "that", "this", "but", "under", "per", "held", "case", "cases", "court", "supreme", "high"}
# a capitalised word that ends the PREVIOUS sentence ("... into the Code. In Ram Prasad v. State of Bihar ...") must not become the start of the case name: cut after a full stop when what follows is a
# word that opens a sentence, or when the word before the full stop is one of the legal nouns that end sentences (Code, Act, Constitution ...); names with abbreviations (Dr. K. Mohan Rao, Mohd. Khan) are kept whole
_SENTENCE_OPENERS = {"in", "the", "see", "also", "as", "this", "that", "these", "those", "thus", "similarly", "likewise", "hence", "however", "but", "further", "moreover", "again", "here", "there", "it",
                     "so", "now", "then", "for", "on", "when", "where", "while", "although", "since", "because", "after", "before", "earlier", "later", "recently", "finally"}
_SENTENCE_ENDERS = {"code", "act", "acts", "constitution", "rules", "rule", "section", "sections", "article", "articles", "order", "judgment", "court", "law", "bail", "trial", "appeal", "petition",
                    "evidence", "investigation", "proceedings", "provision", "provisions", "clause", "schedule", "bench", "decision", "sanhita", "chargesheet"}


def case_mentions(text):
    """[{'name', 'year', 'start', 'end'}] for every 'X v. Y' (with an optional year) in the text. Bare names ('the Mohan Lal case') are not found, by design."""
    out = []
    for m in _NAME.finditer(text or ""):
        p1 = m.group("p1").strip()
        words = p1.split()
        for i in range(len(words) - 2, -1, -1):                                # the last sentence break inside the first party's words
            if words[i].endswith(".") and len(words[i]) > 2 and (words[i + 1].lower() in _SENTENCE_OPENERS or words[i].rstrip(".").lower() in _SENTENCE_ENDERS):
                words = words[i + 1:]
                break
        while words and (words[0].lower().strip(",.") in _LEAD_STOP or words[0].lower() in _SENTENCE_OPENERS) and len(words) > 1:
            words = words[1:]
        p1 = " ".join(words)
        if not p1 or not p1[0].isupper() and p1[0] != "(":
            continue
        name = f"{p1} v. {m.group('p2').strip()}"
        out.append({"name": name, "year": int(m.group("year")) if m.group("year") else None, "start": m.start(), "end": m.end()})
    return out


def audit_answer(reg, overlay, text, exclude_names=(), question=None):
    """What the site adds to a finished answer. register_notes: the register guard's sentences (firm or 'reported ... not yet confirmed'); card_notes: one per case the answer names that has a warning or
    caution card and is not already a register case; not_checked: the cases the answer names that are on neither list (the fixed sentence is built from these names). A case is left out of not_checked
    when it is the overruling case of a register note on this answer, or one of `exclude_names` (the judgments the site itself lists as the answer's sources): a note or a verified source already speaks for it.
    `question` (2026-10-16): the person's own words; register cases they name (with a year, by both full names, or by a first party) add register_notes (level 1) and `possible` sentences (levels 2 and 3), see register_guard.extra_notes. Never raises."""
    from . import register_guard as G
    res = {"register_notes": [], "card_notes": [], "quiet": [], "not_checked": [], "review": [], "possible": []}
    skip = {R.party_sigs(n) for n in (exclude_names or ()) if n}
    try:
        g = G.guard_answer(reg, text or "")
        res["register_notes"], res["review"] = g["notes"], g["review"]
        try:                                                      # 2026-10-16: the question is read too, and a name without a year is no longer silent (register_guard.extra_notes)
            ex = G.extra_notes(reg, question, text or "", g)
            res["register_notes"] = list(g["notes"]) + ex["notes"]
            res["possible"] = ex["possible"]
        except Exception:
            pass
        covered = [(f["mention"] or "").lower() for f in g["findings"]]
        for f in g["findings"]:
            row = reg.by_id.get(f.get("row_id")) if reg is not None else None
            if row:
                skip.add(R.party_sigs(row["overruling"]["name"]))
                for x in reg.same_decision_rows(row):
                    skip.add(R.party_sigs(x["overruling"]["name"]))
    except Exception:
        covered = []
    seen = set()
    cites_in = C.find_cites(text or "")
    for m in case_mentions(text or ""):
        if m["name"].lower() in seen:
            continue
        seen.add(m["name"].lower())
        cit = next((k for k, s, e in cites_in if s >= m["end"] - 1 and s - m["end"] < 40), None)
        if reg is not None and reg.lookup_case(m["name"], m["year"], None if cit is None else _key_text(cit)):
            continue
        if any(m["name"].lower()[:25] in c for c in covered):
            continue
        entry = overlay.lookup(m["name"], m["year"], None if cit is None else _key_text(cit)) if overlay else None
        if entry is None:
            if R.party_sigs(m["name"]) in skip:
                continue
            res["not_checked"].append(m["name"][:90])
        elif entry["kind"] in ("warning", "caution"):
            res["card_notes"].append({"case": entry["name"], "kind": entry["kind"], "note": entry["note"], "evidence": entry.get("evidence")})
        elif entry["kind"] == "quiet":
            res["quiet"].append({"case": entry["name"], "note": entry["note"]})
        elif R.party_sigs(m["name"]) not in skip:
            res["not_checked"].append(m["name"][:90])
    res["not_checked_sentence"] = NOT_CHECKED_LIST.format(names="; ".join(res["not_checked"])) if res["not_checked"] else None
    return res


def _key_text(key):
    """A citation string that cites.find_cites reads back as this key (for a lookup by key)."""
    kind, year, series, page = C.parse_key(key)
    if kind == "scc":
        return f"({year}) {series} SCC {page}"
    if kind == "air":
        return f"AIR {year} SC {page}"
    if kind == "insc":
        return f"{year} INSC {page}"
    return ""
