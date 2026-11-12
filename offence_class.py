"""
offence_class.py -- the classification of an offence (cognizable or not, bailable or not, the court that tries it) from the First Schedule of the BNSS (schedules/bnss_schedule_I.json, built by build_bnss_schedule1.py; owner's go 2026-11-09, FOLLOW_UPS 2ef).

Every lawyers' note had to say "the material does not show whether Section 77 is bailable or cognizable" because the library lacked the Schedule's rows. With the rows, a section's classification is handed to the answer model as material, word for word from the Schedule, and
the other-charges panel shows it beside each section.

Rules: the cells are shown as the Schedule has them, in the Schedule's order (a section with several entries, for example a first and a second conviction, keeps them in that order in every column); nothing is summed up by code except where every entry of a column says the same; the Schedule's own
note says its entries are 'not intended as the definition of, and the punishment prescribed for, the offence' but 'merely as indication of the substance of the section', so the section's text stays the authority. The file is `machine_extracted` from one source (the Gazette PDF); nobody has read it.
Offences under other laws (the IT Act, POCSO ...) are not in Part I: Part II of the Schedule classifies them by their punishment unless the Act classifies them itself (the IT Act's own section 77B does); this module returns None for them and never guesses.
Switch OFFENCE_CLASS (default off) controls only the prompt block (`prompt_block`); the lookup functions are always available.
"""
import json
import os
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "schedules", "bnss_schedule_I.json")
_CACHE = {}


def enabled():
    return (os.environ.get("OFFENCE_CLASS") or "").strip().strip("\"'").strip().lower() in ("on", "true", "1", "yes")


def load():
    if "d" not in _CACHE:
        try:
            _CACHE["d"] = json.load(open(PATH, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _CACHE["d"] = {"rows": []}
    return _CACHE["d"]


def _base(sec):
    return re.sub(r"\(.*$", "", str(sec or "").strip()).upper()


def rows_for(section):
    """Every row of Schedule I whose section is `section` or one of its sub-sections ('77' -> '77'; '70' -> '70(1)', '70(2)'; '70(1)' -> '70(1)'). [] when the section has none (not an offence of the BNS, or not in the file)."""
    q = str(section or "").strip().upper()
    if not q:
        return []
    rows = load().get("rows") or []
    exact = [r for r in rows if r["section"].upper() == q]
    return exact or [r for r in rows if _base(r["section"]) == _base(q)]


def line(row, act="BNS"):
    """One row as the prompt and the panel show it: section, offence, punishment, cognizable, bailable, court (the Schedule's own words)."""
    return (f"{act} {row['section']}: {row['offence']} | Punishment: {row['punishment']} | Cognizable or non-cognizable: {row['cognizable']} | Bailable or non-bailable: {row['bailable']} | By what court triable: {row['court']}")


def summary(row):
    """'cognizable, non-bailable' style words ONLY when every entry of the row agrees; else ''."""
    c, b = row.get("cognizable_summary") or "", row.get("bailable_summary") or ""
    parts = [x for x in (c if c in ("cognizable", "non-cognizable") else "", b if b in ("bailable", "non-bailable") else "") if x]
    return ", ".join(parts)


def part2_note():
    return ("Offences under other laws are classified by Part II of the same Schedule: punishable with death, imprisonment for life or more than 7 years: cognizable, non-bailable, Court of Session; 3 years and upwards but not more than 7 years: cognizable, non-bailable, Magistrate of the first class; "
            "less than 3 years or fine only: non-cognizable, bailable, any Magistrate. An Act that classifies its own offences (the Information Technology Act, section 77B) is governed by that Act.")


# ----------------------------------------------------------------------------- offences under OTHER laws (Part II of the Schedule), OTHER_LAW_CLASS (default ON, 2026-11-12)
# Why: a staging answer about drink driving under the Motor Vehicles Act said the material did not show whether the offence is bailable, although Part II of the Schedule (already extracted here) classifies an offence under another
# law by its punishment. The rule was built on 2026-11-09 and never handed to the answer. It is now handed over, for every section of another law that reaches the answer and names a punishment, together with the
# terms the section's own text names, found by code, so that the model applies the rule to words it can see and not to a number it remembers.
_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "sixty": 60, "ninety": 90}
_TERM = re.compile(r"(?:extend|up)\s+to\s+(?:a\s+(?:period|term)\s+of\s+)?((?:\w+[- ])?\w+)\s+(years?|months?|days?)\b", re.I)
_OFFENCE_WORDS = re.compile(r"\b(?:imprisonment|punishable|punished|punishment)\b", re.I)
_OWN_CLASS = re.compile(r"\b(?:cognizable|non-cognizable|bailable|non-bailable)\b", re.I)

# 2026-11-12 (owner's staging test of the Dowry Prohibition Act): Part II is the DEFAULT for an offence under another law, and an Act's own provisions govern where they speak. Section 4 of the Dowry Prohibition Act
# named a term of two years, the default said "Non-cognizable. Bailable.", and the answer built its first ground for bail on it, while section 8(2) of the Act says every offence under it is non-bailable (section 8 never reached
# the model). So for an Act that classifies its own offences in a section of its own, the default is NOT offered; the line says which section governs, and shelf_companions hands that section over.
# This is the whole list: each entry was found by searching the shelf's section texts for the words cognizable / bailable (test_own_classifiers.py repeats the search and fails when a new section turns up that is neither here nor in
# NOT_CLASSIFIERS). The Information Technology Act (section 77B) is excluded from Part II by act code in other_law_block. Nothing here says what the section provides: the model reads the section.
OWN_CLASSIFIERS = {
    "dowry_prohibition_act_1961": ["8"],      # offences cognizable only for investigation (not arrest without warrant), non-bailable, non-compoundable
    "jj_act_2015": ["86"],                    # its own bands by punishment, and the Children's Court
    "muslim_women_act_2019": ["7"],           # cognizable only on information from the woman or her blood / marriage relatives, compoundable, bail only after the Magistrate hears her
    "pmla_2002": ["45"],                      # cognizable and non-bailable, with its twin conditions for bail
    "uapa_1967": ["43D"],                     # offences deemed cognizable, modified sections 167 and 437, and its bail restriction
}
# shelf sections whose text uses the words but that do NOT classify the Act's offences (read 2026-11-12): checked by the test that repeats the search
NOT_CLASSIFIERS = {
    ("it_act_2000", "69"), ("it_act_2000", "69A"), ("it_act_2000", "77B"),   # 77B classifies its own offences: the Act is excluded from Part II by code
    ("jj_act_2015", "12"),               # bail for a child alleged to be in conflict with the law
    ("mv_act_1988", "19"),               # a licensing authority's power to disqualify; "cognizable" names an offence the licence holder used a vehicle in
    ("ni_act_1881", "147"),              # "every offence punishable under this Act shall be compoundable": compounding only, nothing on bail or arrest
    ("pc_act_1988", "9"),                # a commercial organisation's offence
    ("uapa_1967", "14"),                 # "an offence punishable under this Act shall be cognizable": one line, repeated in 43D(1), which is the section handed over
}


def classifier_sections(act_key):
    return list(OWN_CLASSIFIERS.get(str(act_key or ""), []))


def other_law_enabled():
    return (os.environ.get("OTHER_LAW_CLASS") or "on").strip().strip("\"'").strip().lower() not in ("off", "0", "false", "no")


def _num(word):
    w = re.sub(r"[-\s]+", " ", word.strip().lower())
    if w.isdigit():
        return int(w)
    if w in _NUMS:
        return _NUMS[w]
    parts = w.split(" ")
    if len(parts) == 2 and parts[0] in _NUMS and parts[1] in _NUMS and _NUMS[parts[0]] >= 20 and _NUMS[parts[1]] < 10:
        return _NUMS[parts[0]] + _NUMS[parts[1]]
    if len(parts) == 2 and parts[1] == "hundred" and parts[0] in _NUMS:
        return _NUMS[parts[0]] * 100
    return None


def terms_in(text):
    """The imprisonment terms a section's text names: ([(text, years)], life_or_death). 'may extend to six months' -> ('6 months', 0.5). Only maxima ('extend to'); a minimum is not a term of the band."""
    out, life = [], False
    t = re.sub(r"[\[\]*]", "", text or "")                       # India Code marks amended words in square brackets and omitted ones with asterisks
    for m in _TERM.finditer(t):
        n = _num(m.group(1))
        if n is None:
            continue
        unit = m.group(2).lower().rstrip("s")
        years = n if unit == "year" else (n / 12.0 if unit == "month" else n / 365.0)
        out.append((f"{n} {unit}{'s' if n != 1 else ''}", years))
    if re.search(r"imprisonment\s+for\s+life|\bdeath\b", t, re.I):
        life = True
    return out, life


def band_for(terms, life, fine_only=False):
    """The Part II row (as a dict of the Schedule's own columns) for the highest term named; None when there is no term, no life or death and no fine-only wording."""
    rows = {r.get("if", ""): r for r in load().get("part_II_rows") or []}
    ordered = list(rows.values())
    if len(ordered) < 3:
        return None
    top = max([y for _, y in terms], default=None)
    if life or (top is not None and top > 7):
        return ordered[0]
    if top is not None and top >= 3:
        return ordered[1]
    if top is not None or fine_only:
        return ordered[2]
    return None


def other_law_block(matches, limit=5):
    """For each statute section of a LAW OTHER THAN the BNS, BNSS and BSA that reaches the answer and names a punishment: the terms its text names and the Part II row they fall in, with the instruction to state the
    classification only so, as the Schedule's DEFAULT for an offence under another law (an Act's own provisions on arrest, bail, cognizability or the court govern where they speak). For an Act that classifies its own
    offences in a section of its own (OWN_CLASSIFIERS) NO default is offered: the line names the governing section, and says so plainly when that section's text is not in the material. '' when switched off, when no
    section qualifies, or on any failure."""
    try:
        if not other_law_enabled() or not load().get("part_II_rows"):
            return ""
        have = {(str(m.get("act_key") or ""), str(m.get("section_number") or "").upper()) for m in matches or [] if isinstance(m, dict) and not m.get("case_name")}
        seen, lines, own_lines, own_acts = set(), [], [], {}
        for m in matches or []:
            if not isinstance(m, dict) or m.get("case_name") or m.get("type") not in (None, "statute"):
                continue
            act = str(m.get("act") or "").upper()
            if not act or act in ("BNS", "BNSS", "BSA", "ITACT", "ITACTFULL"):           # the Information Technology Act classifies its own offences (section 77B): no default is offered for them
                continue
            text = m.get("text") or ""
            if not text or not _OFFENCE_WORDS.search(text):
                continue
            key = (act, str(m.get("section_number")))
            if key in seen:
                continue
            name = m.get("act_display") or act
            gov = classifier_sections(m.get("act_key"))
            if gov and str(m.get("section_number") or "").upper() not in [g.upper() for g in gov]:
                seen.add(key)
                own_acts.setdefault(str(m.get("act_key")), {"name": name, "gov": gov, "sections": []})["sections"].append(str(m.get("section_number")))
                if len(seen) >= limit:
                    break
                continue
            terms, life = terms_in(text)
            fine_only = not terms and not life and bool(re.search(r"\bfine\b", text, re.I)) and not re.search(r"\bimprisonment\b", text, re.I)
            row = band_for(terms, life, fine_only)
            if row is None:
                continue
            seen.add(key)
            named = ", ".join(t for t, _ in terms) + (", imprisonment for life or death" if life else "") if (terms or life) else "no imprisonment (a fine)"
            own = " The section's own text uses the words cognizable / bailable: go by it." if _OWN_CLASS.search(text) else ""
            lines.append(f"- {name} section {m.get('section_number')}: the terms its text names: {named}. Part II row: {row.get('cognizable')} {row.get('bailable')} {row.get('court')}{own}")
            if len(seen) >= limit:
                break
        for ak, info in own_acts.items():
            nums = " and ".join(f"section {g}" for g in info["gov"])
            secs = ", ".join(info["sections"])
            if all((ak, g.upper()) in have for g in info["gov"]):
                own_lines.append(f"- {info['name']}, sections {secs}: this Act classifies its own offences in {nums}, whose text is in the material above. The Part II default does NOT apply to this Act: say whether an offence under it is cognizable, bailable or compoundable, and what the Act provides on arrest, bail or the court, only from {nums} itself.")
            else:
                own_lines.append(f"- {info['name']}, sections {secs}: this Act classifies its own offences in {nums}, whose text is NOT in the material. The Part II default does NOT apply to this Act: do not state whether an offence under it is cognizable, bailable or compoundable; say that the material does not show it and that {nums} of the Act must be read.")
        if not lines and not own_lines:
            return ""
        head = "\n\n## Classification of offences under OTHER laws (BNSS, First Schedule, Part II) - the Schedule's default, applied by a program to the terms the section's own text names\n"
        out = head + "\n".join(own_lines + lines)
        if lines:
            out += ("\nPart II classifies an offence against another law by its punishment: " + part2_note().split(": ", 1)[1] + "\n"
                    "If you say whether such an offence is cognizable or bailable, or which court tries it, say it as this default from Part II of the Schedule, and say that the Act's own provisions govern where they speak (a special court, "
                    "a power of arrest without warrant, a section that makes offences cognizable or non-bailable). Where a section has different punishments for a first and a later offence, apply the rule to each. Do not say the material "
                    "does not show the classification when a line above gives it; do not state a classification for a section not listed above.\n")
        if own_lines:
            out += "\nFor an Act whose line above says it classifies its own offences, never give the Part II default, not even as a fallback; the Act's own section governs.\n"
        return out
    except Exception:  # noqa: BLE001
        return ""


def prompt_block(matches, limit=6):
    """OFFENCE_CLASS=on: for the BNS offence sections among `matches`, the Schedule's rows, as material the answer may state from. '' when off, when no match is an offence of the BNS, or on any failure."""
    try:
        if not enabled():
            return ""
        seen, lines = set(), []
        for m in matches or []:
            if not isinstance(m, dict) or str(m.get("act") or "").upper() != "BNS" or m.get("case_name"):
                continue
            num = _base(m.get("section_number"))
            if not num or num in seen:
                continue
            seen.add(num)
            for r in rows_for(num):
                lines.append(line(r))
            if len(seen) >= limit:
                break
        if not lines:
            return ""
        return ("\n\n## Classification of the offences above (BNSS, First Schedule, Part I: the Schedule's own words)\n" + "\n".join(lines) +
                "\nState whether an offence is cognizable or bailable and which court tries it ONLY from these lines, in the order of the Schedule's entries (where a section has more than one entry, for example a first and a second conviction, the entries of each column follow the same order). "
                "The Schedule says its entries are only an indication of the substance of the section; the section's own text above is the authority on the offence and its punishment. If an offence is not listed here, say the material does not show its classification.\n")
    except Exception:  # noqa: BLE001
        return ""
