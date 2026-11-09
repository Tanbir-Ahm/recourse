"""
statute_aliases.py -- STATUTE_ALIASES=off|on (default off; written 2026-11-03 on the owner's "Yes, measure the misses and fix the common ones"; research repository FOLLOW_UPS item 2de).

THE MISS IT CLOSES (a small one, on purpose). Some sections are never close to the words people use for them. The Sanhita calls BNSS 528 "Saving of inherent powers of the High Court" and its text never says "quash" or "FIR";
a question "How can a High Court quash an FIR?" ranked it 83rd and "Can the High Court cancel an FIR that is false and malicious?" 119th of the library's sections. BNSS 359 (compounding of offences) ranked 38th for "Can the
parties settle a case and have it ended?" (0.19). Widening the pool (statute_widen.py) cannot help: they are nowhere near it. Both were missed in BOTH development question sets.

WHAT IT DOES. A short list of word groups; when every word of one group is in the question, the section is handed to the answer model as an ordinary library passage (its own official text from the library, no commentary, no
curated note), marked retrieval 'alias'. Nothing is said about the law beyond what the section itself says. A section the person named by number is not touched, and a section the library search found anyway is not added twice.

WHAT IT IS NOT. It is NOT measured on unseen questions: the two entries were written BECAUSE of those misses, so the development sets can only show that they fire; the 48 frozen questions contain no question about quashing or
compounding. They are tested by hand-written cases (test_statute_aliases.py). The word groups are Claude's, not a lawyer's, and nobody has checked that every question that fires one of them is about that section. A new entry needs
a miss that was MEASURED, its word groups written before the question set is looked at, a negative list, and a test. Do not grow this into a general dictionary without a held-out measurement.

HARBOURING (2026-11-09): BNS 249, 253 and 254, version 1 and 2 of the word groups, measured on pre-registered question sets (research repository review_results/2026-11-09_harbouring_alias/). The library search already brought the section
when a question used a word such as harbour, hide or shelter (20 of 24 on set 1); the entries are for the phrasings without such a word (lift, drove, took, staying at my house, rented a room).
Known limits, left as written: his/her/their before the person, 'the wanted man', 'the absconding accused', 'dropped him at'; and three declared false fires (the police taking an absconder to the station; accompanying a wanted relative to surrender).

BAIL (2026-11-09): BNSS 478, 480 and 483 for a person who says someone has been arrested or is in custody, or that bail was refused (research repository review_results/2026-11-09_bail_alias/). Known false fires, left as written:
'the police took my phone' reads as an arrest, and a general question that says 'kept in custody' fires. A question that merely mentions an arrest gets the two sections (about 6,000 characters) even when it is not about release.

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

# ---- harbouring (added 2026-11-09, FOLLOW_UPS 2dw; word groups written before the question set was run: review_results/2026-11-09_harbouring_alias/PREREGISTRATION.md). Version 1, unchanged since.
# The library search already finds BNS 249/253/254 when the question uses a word such as harbour, hide or shelter (20 of 24, 8 of 8 and 4 of 4 on the pre-registered set); the alias is for the other phrasings.
NOUN = (r"(?:him|her|them|someone|somebody|the (?:accused|offender|man|boy|woman|person|fugitive|culprit|absconder)|"
        r"my (?:brother|son|friend|husband|cousin|relative|nephew|uncle|neighbou?r|employee|worker|father|driver)|"
        r"a (?:friend|relative|man|person|stranger|colleague|fugitive|accused|offender)|an (?:accused|offender|absconder|acquaintance))")
HIDE = r"\b(?:hid|hide|hiding|hidden|conceal\w*|shelter\w*|harbou?r\w*)\s+" + NOUN + r"\b"
GIVE = r"\b(?:gave|give|giving|given|offered|offering|provided|providing)\b[^.?!]{0,40}?\b(?:lift|ride|shelter|refuge|hiding place|place to stay|accommodation|food and (?:money|shelter)|money and (?:food|shelter))\b"
LET = r"\b(?:let|allowed|letting|allowing)\s+" + NOUN + r"\s+(?:stay|sleep|live|hide)\b"
HELPFLEE = r"\bhelp\w*\s+" + NOUN + r"\s+(?:to\s+)?(?:hide|flee|abscond|run away|go into hiding|stay hidden|evade)\b"
WANTED = (r"(?:abscond\w*|fugitive|on the run|running (?:away )?from (?:the )?police|wanted (?:by|for|in)\b|wanted (?:man|person)|proclaimed offender|"
          r"\bpolice (?:was|were|are|is) (?:looking|searching|hunting|after)\b|sought by (?:the )?police|evading (?:arrest|the police)|prime accused|main accused|principal accused|"
          r"\b(?:fled|escaped|flee|fleeing)\b|jumped bail)")
ESCAPED_OR_ORDERED = (r"(?:escap\w+\s+(?:from\s+)?(?:lawful\s+|police\s+|judicial\s+)?(?:custody|jail|prison|lock-?up)|jail\s?break|prison\s?break|"
                      r"(?:warrant|order)\w*\b[^.?!]{0,40}\b(?:arrest|apprehen\w+)|(?:arrest|apprehension)\b[^.?!]{0,40}\b(?:ordered|warrant)|ordered\s+(?:his|her|their|the)\s+arrest|police\s+ordered)")
ROBBERS = r"\b(?:robber\w*|dacoit\w*|decoit\w*|robbed)\b"

HARBOUR_ENTRIES = [
    {"id": "bns_249_harbour", "act": "BNS", "section": "249", "groups": [
        [r"\bharbou?r\w*", r"\b(?:offenders?|accused|criminals?|fugitives?|absconders?|culprits?)\b"],
        [HIDE, WANTED],
        [GIVE, WANTED],
        [LET, WANTED],
        [HELPFLEE],
        [r"\bscreen\w*\s+(?:an?\s+|the\s+)?(?:offender|accused|person|him|her)\s+from\s+(?:legal\s+)?(?:punishment|arrest|the police)"],
        [r"\baccessory after the fact\b"],
    ]},
    {"id": "bns_253_harbour_escaped_or_ordered", "act": "BNS", "section": "253", "groups": [
        [HIDE, ESCAPED_OR_ORDERED], [GIVE, ESCAPED_OR_ORDERED], [LET, ESCAPED_OR_ORDERED], [HELPFLEE, ESCAPED_OR_ORDERED],
        [r"\b(?:harbou?r\w*|conceal\w*)", ESCAPED_OR_ORDERED],
    ]},
    {"id": "bns_254_harbour_robbers", "act": "BNS", "section": "254", "groups": [
        [HIDE, ROBBERS], [GIVE, ROBBERS], [LET, ROBBERS], [HELPFLEE, ROBBERS],
        [r"\bharbou?r\w*", ROBBERS],
    ]},
]
ENTRIES = ENTRIES + HARBOUR_ENTRIES

# ---- harbouring, version 2 (added 2026-11-09 after version 1 was measured; word groups written before the new question set was run: review_results/2026-11-09_harbouring_alias/PREREGISTRATION_V2.md)
# three groups for the phrasings with no word of harbouring: taking an accused somewhere, an accused staying at my premises, renting a room to a wanted man. Added to the 249 entry only.
NOUN_ACC = (r"(?:him|her|them|the (?:prime |main |principal )?(?:accused|offender|man|fugitive|absconder|culprit)|(?:an? )?(?:absconding|wanted) \w+|"
            r"my (?:brother|son|friend|husband|cousin|relative|nephew|uncle|neighbou?r|employee|worker|father)|a (?:friend|relative|man|person|stranger|colleague|fugitive|accused|offender))")
TRANSPORT = r"\b(?:drove|driven|driving|took|taken|taking|dropped|dropping|carried|carrying|transported|ferried|escorted|accompanied)\s+" + NOUN_ACC + r"\b[^.?!]{0,30}?\b(?:to|away|across|out of|from)\b"
STAY = r"\b(?:staying|stayed|stays|lodged|lodging|living|lived|residing|resided|sleeping|slept|put up|putting up)\s+(?:at|in|with|inside)\s+(?:my|our|his|her)\s+(?:house|home|guest ?house|farm\w*|shop|room|flat|hotel|lodge|property|place|godown|office)\b"
RENT = r"\b(?:rented|let out|leased|gave on rent|sublet)\s+(?:a|my|the|one)\s+(?:room|flat|house|shop|godown|portion)\s+to\s+"
V2_GROUPS_249 = [[TRANSPORT, WANTED], [STAY, WANTED], [RENT, WANTED]]
HARBOUR_ENTRIES[0]["groups"] = HARBOUR_ENTRIES[0]["groups"] + V2_GROUPS_249

# ---- bail for a person who has been arrested (added 2026-11-09, FOLLOW_UPS 2dx; word groups written before the question set was run: review_results/2026-11-09_bail_alias/PREREGISTRATION.md).
# BNSS 478 (bail in a bailable offence), 480 (non-bailable), 483 (High Court / Sessions Court) for a person who says someone has been arrested or is in custody, or that bail was refused. Baseline: both 478 and 480 reached the prompt for only 4 of 30 such questions.
ARRESTED = (r"(?:\b(?:i|we|he|she|they)\s+(?:was|were|got|am|is|are|have been|has been|had been)\s+(?:arrested|detained|taken into custody|taken to (?:the )?(?:police station|lock-?up))\b|"
            r"\b(?:was|were|got|been|get)\s+(?:arrested|detained)\b|"
            r"\barrested\s+(?:me|my \w+|him|her|them|us)\b|"
            r"\bpolice\s+(?:arrested|detained|picked up|took|have taken|has taken|have arrested|has arrested)\s+(?:me|my \w+|him|her|them|us)\b|"
            r"\b(?:is|am|was|are|were|been|remains?|kept|held|lying)\s+(?:\w+\s+)?(?:in|into)\s+(?:police\s+|judicial\s+)?custody\b|"
            r"\b(?:is|am|was|are|were|been|remains?|kept|held|lying)\s+(?:\w+\s+)?(?:in|inside)\s+(?:the\s+)?(?:jail|lock-?up|prison)\b|"
            r"\bremanded\b)")
BAIL_REFUSED = (r"(?:\bbail\b[^.?!]{0,50}\b(?:refused|rejected|denied|dismissed|declined)\b|\b(?:refused|rejected|denied|dismissed|declined)\b[^.?!]{0,30}\bbail\b)")
HIGHER = r"\b(?:high court|sessions court|session court|sessions judge)\b"

BAIL_ENTRIES = [
    {"id": "bnss_478_bail_bailable", "act": "BNSS", "section": "478", "groups": [[ARRESTED]]},
    {"id": "bnss_480_bail_nonbailable", "act": "BNSS", "section": "480", "groups": [[ARRESTED]]},
    {"id": "bnss_483_bail_higher_court", "act": "BNSS", "section": "483", "groups": [[BAIL_REFUSED], [r"\bbail\b", HIGHER]]},
]
ENTRIES = ENTRIES + BAIL_ENTRIES
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
