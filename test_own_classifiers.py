"""test_own_classifiers.py -- an Act that classifies its own offences (Dowry Prohibition Act section 8, Juvenile Justice Act section 86, Muslim Women Act section 7, PMLA section 45, UAPA section 43D) gets no Part II default,
and its classifying section goes with its offence sections (2026-11-12, after the owner's staging test of the Dowry Prohibition Act: Part II said 'Bailable', section 8(2) says non-bailable, and section 8 never reached the model).
Also the section-gloss check's two fixes of the same day. Offline and free (the search by meaning is not called). Run: python -X utf8 test_own_classifiers.py"""
import glob
import json
import os
import re
import sys

import offence_class as O
import section_checks as SC
import shelf_companions

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def shelf(key):
    return json.load(open(os.path.join(HERE, "act_shelf", f"{key}.json"), encoding="utf-8"))


def m(key, num, display, text=None):
    for c in shelf(key):
        if str(c["section_number"]) == str(num):
            return {"type": "statute", "source": "act_shelf", "act": c["act"], "act_key": key, "act_display": display, "section_number": num, "text": text or c["text"]}
    raise KeyError((key, num))


# ---- 1. the registry is the whole of what the shelf holds: repeat the search that found it ----
pat = re.compile(r"\b(?:non-?\s?cognizable|cognizable|non-?\s?bailable|bailable|non-?\s?compoundable|compoundable)\b", re.I)
found = set()
for f in glob.glob(os.path.join(HERE, "act_shelf", "*.json")):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        continue
    if not isinstance(d, list) or not d or not isinstance(d[0], dict) or "section_number" not in d[0]:
        continue
    key = os.path.basename(f)[:-5]
    for c in d:
        if not c.get("omitted") and pat.search(c.get("text") or ""):
            found.add((key, str(c["section_number"])))
registered = {(k, s) for k, v in O.OWN_CLASSIFIERS.items() for s in v}
check(found - registered - O.NOT_CLASSIFIERS == set(), f"every shelf section that uses the words cognizable / bailable / compoundable is a registered classifier or on the read-and-not-needed list (unlisted: {sorted(found - registered - O.NOT_CLASSIFIERS)})")
check(registered <= found, f"every registered classifier uses those words in its own text (not found: {sorted(registered - found)})")
check(not (registered & O.NOT_CLASSIFIERS), "no section is both registered and on the not-needed list")

# ---- 2. the override line ----
DOW = "Dowry Prohibition Act, 1961"
s4, s3, s6, s8 = m("dowry_prohibition_act_1961", "4", DOW), m("dowry_prohibition_act_1961", "3", DOW), m("dowry_prohibition_act_1961", "6", DOW), m("dowry_prohibition_act_1961", "8", DOW)
os.environ.pop("OTHER_LAW_CLASS", None)
b = O.other_law_block([s4, s3, s6])
check("Part II row:" not in b and "Non-cognizable. Bailable" not in b and "Part II default does NOT apply" in b, "Dowry sections 3, 4, 6 without section 8: no Part II row is offered")
check("whose text is NOT in the material" in b and "do not state whether an offence under it is cognizable, bailable or compoundable" in b, "...and the line says section 8 is not in the material and forbids a classification")
check(b.count("- Dowry Prohibition Act, 1961, sections") == 1, "one line for the Act, however many of its sections")
b2 = O.other_law_block([s4, s3, s6, s8])
check("whose text is in the material above" in b2 and "only from section 8 itself" in b2 and "Part II row:" not in b2, "with section 8 among the sections: the line sends the model to section 8")
check("never give the Part II default, not even as a fallback" in b2, "the closing sentence forbids a fallback")
b3 = O.other_law_block([m("pc_act_1988", "7", "Prevention of Corruption Act, 1988"), s4])
check("Prevention of Corruption Act, 1988 section 7:" in b3 and "Part II row:" in b3 and "Dowry Prohibition Act, 1961, sections 4" in b3, "an Act with no own classifier keeps its Part II line next to the Dowry line")
saved = dict(O.OWN_CLASSIFIERS)
O.OWN_CLASSIFIERS.clear()
b4 = O.other_law_block([s4])
check("Non-cognizable. Bailable." in b4, "with the registry emptied the old line returns (this is the behaviour the owner saw on staging)")
O.OWN_CLASSIFIERS.update(saved)
check(O.other_law_block([s8]) == "", "the classifying section alone (no punishment words in it) gives no line")
for key, num, disp in (("jj_act_2015", "75", "Juvenile Justice Act, 2015"), ("pmla_2002", "4", "PMLA"), ("muslim_women_act_2019", "4", "Muslim Women Act"), ("uapa_1967", "16", "UAPA")):
    t = O.other_law_block([m(key, num, disp)])
    check("Part II row:" not in t and "does NOT apply" in t and f"section {O.OWN_CLASSIFIERS[key][0]}" in t, f"{disp} section {num}: no default, names section {O.OWN_CLASSIFIERS[key][0]}")

# ---- 3. the companion ----
os.environ["ACT_SHELF"] = "on"
os.environ.pop("SHELF_COMPANIONS", None)
added = shelf_companions.add("Is the offence under the Dowry Prohibition Act bailable?", [s4, s3])
check([a["section_number"] for a in added] == ["8"] and added[0].get("companion"), "sections 4 and 3 handed over: section 8 is added as a companion")
added = shelf_companions.add("What does the Act mean by dowry?", [m("dowry_prohibition_act_1961", "2", DOW)])
check(added == [], "only the definition section and a question with no bail word: nothing is added")
added = shelf_companions.add("Can the police arrest without a warrant under this Act?", [m("dowry_prohibition_act_1961", "2", DOW)])
check([a["section_number"] for a in added] == ["8"], "only the definition section but a question about arrest: section 8 is added")
check(shelf_companions.add("bail?", [s4, s8]) == [] and s8.get("companion") is True, "section 8 already there: not added twice, and it is marked")
os.environ["SHELF_COMPANIONS"] = "off"
check(shelf_companions.add("Is it bailable?", [s4]) == [], "SHELF_COMPANIONS=off: nothing is added (the line then says section 8 is not in the material)")
os.environ.pop("SHELF_COMPANIONS")
added = shelf_companions.add("Is it bailable?", [m("uapa_1967", "16", "UAPA")])
check([a["section_number"] for a in added] == ["43D"], "UAPA section 16: section 43D is added")
added = shelf_companions.add("Is it bailable?", [m("pc_act_1988", "7", "Prevention of Corruption Act, 1988")])
check(added == [], "an Act with no own classifier: nothing is added by this rule")

# ---- 4. section_checks: the two fixes ----
SECTS = [
    {"type": "statute", "act": "DOWRY", "act_display": DOW, "section_number": "4", "text": "4. Penalty for demanding dowry. If any person demands any dowry he shall be punishable with imprisonment for a term which may extend to two years."},
    {"type": "statute", "act": "BNSS", "act_display": "BNSS", "section_number": "480", "text": "480. When any person accused of any non-bailable offence which is cognizable is arrested he may be released on bail by the Magistrate; the offence is triable by the Court of Session."},
]
ans = "Section 4 of the Dowry Prohibition Act carries a term of up to two years, classified under Part II of the First Schedule as non-cognizable, bailable, triable by any Magistrate."
check(SC.section_gloss(ans, SECTS, "") == [], "a sentence that describes the Schedule's classification is not checked as a description of the section")
ans2 = "Section 4 of the Dowry Prohibition Act penalises a demand for dowry and is a non-bailable cognizable offence triable by the Court of Session."
check(len(SC.section_gloss(ans2, SECTS, "")) == 1, "a sentence that really attributes borrowed words to the section is still reported (true positive kept)")
ans3 = "Section 4 of the Dowry Prohibition Act punishes a demand; the Supreme Court in X held that the offence is cognizable and non-bailable."
check(SC.section_gloss(ans3, SECTS, "") == [], "the clause after ';' that turns to a court is not attributed to the section")
ans4 = "Section 4 of the Dowry Prohibition Act punishes a demand, the Supreme Court having held that it is cognizable and non-bailable."
check(SC.section_gloss(ans4, SECTS, "") == [], "the clause after ', the Supreme Court' is not attributed to the section")
ans5 = "Section 4 of the Dowry Prohibition Act lets the High Court treat a cognizable non-bailable offence as triable by the Court of Session."
check(len(SC.section_gloss(ans5, SECTS, "")) == 1, "'the High Court' inside the clause (no comma before it) does not cut the sentence")
cls = "\n\n## Classification of offences under OTHER laws (BNSS, First Schedule, Part II)\n- X section 4: Part II row: Non-cognizable. Bailable. Any Magistrate. Triable by the Court of Session.\n\n## Other"
check("Triable by the Court" in SC.classification_text("blah" + cls) and "Other" not in SC.classification_text("blah" + cls), "classification_text returns the classification blocks only")
ans6 = "Section 4 of the Dowry Prohibition Act provides a penalty that makes it a cognizable and non-bailable offence triable by the Court of Session."
check(SC.section_gloss(ans6, SECTS, "", SC.classification_text(cls)) == [], "words that the code-built classification block supplied are not 'borrowed'")

print()
print(f"{len(FAILURES)} failed" if FAILURES else "all passed")
sys.exit(1 if FAILURES else 0)
