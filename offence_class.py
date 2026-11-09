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
