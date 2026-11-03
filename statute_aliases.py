"""
statute_aliases.py -- STATUTE_ALIASES=off|on (default off; written 2026-11-03 on the owner's "Yes, measure the misses and fix the common ones"; research repository FOLLOW_UPS item 2dg).

THE MISS IT CLOSES (a small one, on purpose). Some sections are never close to the words people use for them. The Sanhita calls BNSS 528 "Saving of inherent powers of the High Court" and its text never says "quash" or "FIR";
a question "How can a High Court quash an FIR?" ranked it 83rd and "Can the High Court cancel an FIR that is false and malicious?" 119th of the library's sections. BNSS 359 (compounding of offences) ranked 38th for "Can the
parties settle a case and have it ended?" (0.19). Widening the pool (statute_widen.py) cannot help: they are nowhere near it. Both were missed in BOTH development question sets.

WHAT IT DOES. A short list of word groups; when every word of one group is in the question, the section is handed to the answer model as an ordinary library passage (its own official text from the library, no commentary, no
curated note), marked retrieval 'alias'. Nothing is said about the law beyond what the section itself says. A section the person named by number is not touched, and a section the library search found anyway is not added twice.

WHAT IT IS NOT. It is NOT measured on unseen questions: the two entries were written BECAUSE of those misses, so the development sets can only show that they fire; the 48 frozen questions contain no question about quashing or
compounding. They are tested by hand-written cases (test_statute_aliases.py). The word groups are Claude's, not a lawyer's, and nobody has checked that every question that fires one of them is about that section. A new entry needs
a miss that was MEASURED, its word groups written before the question set is looked at, a negative list, and a test. Do not grow this into a general dictionary without a held-out measurement.

SWITCH: STATUTE_ALIASES = off (default; nothing changes) | on. One log line (STATUTE_ALIAS) when an entry fires.
"""
import hashlib
import json
import os
import re

# each entry: the section, and word groups (a group fires when EVERY regular expression in it is found in the lower-cased question)
ENTRIES = [
    {
        "id": "bnss_528_quash",
        "act": "BNSS", "section": "528",
        "groups": [
            [r"\bquash\w*"],
            [r"\binherent\b", r"\bpowers?\b"],
            [r"\babuse\b", r"\bprocess\b"],
            [r"\b(?:cancel\w*|set aside|get rid of|scrap\w*|annul\w*|dismiss\w*)\b", r"\bfirs?\b|\bfirst information report\b", r"\bhigh court\b"],
            [r"\b(?:cancel\w*|set aside|get rid of|scrap\w*|annul\w*|dismiss\w*)\b", r"\bcriminal (?:case|proceedings?|complaint)\b", r"\bhigh court\b"],
        ],
    },
    {
        "id": "bnss_359_compound",
        "act": "BNSS", "section": "359",
        "groups": [
            [r"\bcompoundable\b"],
            [r"\bcompounded\b"],
            [r"\bcompounding\b"],
            [r"\bcompound\s+(?:of\s+)?(?:an?\s+|the\s+)?(?:offences?|cases?)\b"],
            [r"\b(?:compromis\w+|settle\w*|patch\w* up)\b", r"\b(?:case|complaint|fir|offence|criminal)\b", r"\b(?:complainant|victim|parties|both sides|other side)\b"],
        ],
    },
]
_COMPILED = [dict(e, groups=[[re.compile(p) for p in g] for g in e["groups"]]) for e in ENTRIES]


def _env(name, default=""):
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().strip("\"'").strip()
    return v if v else default


def mode():
    return "on" if _env("STATUTE_ALIASES", "off").lower() in ("on", "true", "1", "yes") else "off"


def fired(question):
    """The entries (dicts with id, act, section) whose word groups the question satisfies. [] for anything else."""
    q = (question or "").lower()
    if not q.strip():
        return []
    return [e for e in _COMPILED if any(all(p.search(q) for p in g) for g in e["groups"])]


def matches(question, already=frozenset()):
    """Statute matches (the library's own text of each section) for the entries the question fires; [] when the switch is off or on any failure. `already`: {(ACT, SECTION)} to leave out."""
    try:
        if mode() == "off":
            return []
        hits = fired(question)
        if not hits:
            return []
        from retrieval import get_statute_section
        out, ids = [], []
        for e in hits:
            if (e["act"].upper(), str(e["section"]).upper()) in {(a.upper(), str(s).upper()) for a, s in already}:
                continue
            data = get_statute_section(e["act"], e["section"])
            if not data or not (data.get("text") or "").strip():
                continue
            out.append({"type": "statute", "act": data["act"], "section_number": data["section_number"], "text": data["text"], "score": None,
                        "source": "statute_alias", "retrieval": "alias", "alias_id": e["id"], "chunk_id": f"statute:{data['act']}:{data['section_number']}"})
            ids.append(e["id"])
        if ids:
            print("STATUTE_ALIAS " + json.dumps({"q": hashlib.sha1((question or "").encode("utf-8", "ignore")).hexdigest()[:12], "entries": ids}), flush=True)
        return out
    except Exception:  # noqa: BLE001 -- never lets a failure here touch an answer
        return []
