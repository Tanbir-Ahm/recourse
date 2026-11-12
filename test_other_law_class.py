"""test_other_law_class.py -- Part II of the BNSS First Schedule handed to the answer for offences under OTHER laws (OTHER_LAW_CLASS, default on; 2026-11-12, after a staging answer said the classification of a Motor Vehicles Act offence
was 'not shown in the material'). Offline and free. Run: python -X utf8 test_other_law_class.py"""
import json
import os
import sys
import types

import offence_class as O

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []
DISP = {"mv_act_1988": "Motor Vehicles Act, 1988", "pocso_act_2012": "POCSO Act", "pc_act_1988": "Prevention of Corruption Act, 1988", "pmla_2002": "PMLA"}


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def sec(key, num):
    for c in json.load(open(os.path.join(HERE, "act_shelf", f"{key}.json"), encoding="utf-8")):
        if str(c["section_number"]) == str(num):
            return {"type": "statute", "act": c["act"], "act_display": DISP.get(key, key), "section_number": num, "text": c["text"], "source": "act_shelf"}
    raise KeyError((key, num))


t, life = O.terms_in(sec("mv_act_1988", "185")["text"])
check([x[0] for x in t] == ["6 months", "2 years"] and not life, f"terms of MV s.185 read from the text, brackets ignored ({t})")
check(O.terms_in("imprisonment for a term which shall not be less than ten years but which may extend to imprisonment for life")[1] is True, "life imprisonment is recognised")
check(O.terms_in("shall be punishable with imprisonment for a term which may extend to two years")[0] == [("2 years", 2)] and O.terms_in("may extend to thirty days")[0][0][0] == "30 days", "number words and days")
check(O.terms_in("not less than three years")[0] == [], "a minimum is not a term of the band")

rows = O.load()["part_II_rows"]
check(O.band_for([("6 months", .5)], False) is rows[2] and O.band_for([("5 years", 5)], False) is rows[1] and O.band_for([("10 years", 10)], False) is rows[0] and O.band_for([], True) is rows[0] and O.band_for([], False, True) is rows[2] and O.band_for([], False) is None,
      "bands: under 3 years, 3 to 7, over 7 or life, fine only, nothing")

os.environ.pop("OTHER_LAW_CLASS", None)
b = O.other_law_block([sec("mv_act_1988", "185"), sec("mv_act_1988", "187"), sec("mv_act_1988", "181")])
check("Motor Vehicles Act, 1988 section 185: the terms its text names: 6 months, 2 years. Part II row: Non-cognizable. Bailable. Any Magistrate." in b and "Motor Vehicles Act, 1988 section 181" in b and "Do not say the material does not show the classification when a line above gives it" in b,
      "MV Act s.185, 187, 181: the Part II default (non-cognizable, bailable) with the terms the text names")
check("the Act's own provisions govern where they speak" in b and "Part II classifies an offence against another law by its punishment" in b, "...with the caveat that the Act's own provisions govern")
check(O.other_law_block([sec("mv_act_1988", "194"), sec("mv_act_1988", "20"), sec("mv_act_1988", "134")]) == "", "a monetary-penalty section, a disqualification section and a duty section: no line")
p = O.other_law_block([sec("pocso_act_2012", "4"), sec("pc_act_1988", "7"), sec("pmla_2002", "4")])
check("POCSO Act section 4" in p and "Cognizable. Non-bailable. Court of Session." in p.split("POCSO Act section 4")[1].split("\n")[0], "POCSO s.4 (up to life): cognizable, non-bailable, Court of Session")
check("Prevention of Corruption Act, 1988 section 7" in p and "Cognizable. Non-bailable. Magistrate of the first class." in p.split("Prevention of Corruption Act, 1988 section 7")[1].split("\n")[0], "PC Act s.7 (three to seven years): cognizable, non-bailable, Magistrate of the first class")
check(O.other_law_block([{"type": "statute", "act": "BNS", "section_number": "318", "text": "imprisonment which may extend to three years"}, {"type": "statute", "act": "BNSS", "section_number": "35", "text": "punishable with imprisonment which may extend to seven years"},
                         {"type": "statute", "act": "ITACTFULL", "section_number": "66", "text": "imprisonment for a term which may extend to three years"}, {"case_name": "A v B", "text": "punishable with imprisonment up to two years"}]) == "",
      "BNS (Part I has it), BNSS, the Information Technology Act (section 77B governs) and a case: no default offered")
check("go by it" in O.other_law_block([{"type": "statute", "act": "XACT", "section_number": "5", "text": "Whoever does this shall be punished with imprisonment which may extend to two years, and the offence shall be cognizable and bailable."}]), "a section whose own text uses cognizable / bailable is marked 'go by it'")
os.environ["OTHER_LAW_CLASS"] = "off"
check(O.other_law_block([sec("mv_act_1988", "185")]) == "", "switched off: nothing")
os.environ.pop("OTHER_LAW_CLASS", None)

import chat_assistant as CA
sent = {}


class _M:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["p"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Short.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_M())
m185 = sec("mv_act_1988", "185")
CA.generate_grounded_response("Is drunk driving bailable?", "[MVACT Section 185]\n" + m185["text"], matches=[m185])
p = sent["p"]
check("## Classification of offences under OTHER laws" in p and p.index("Driving by a drunken person") < p.index("## Classification of offences under OTHER laws") and "## Hard rules (never break)" in p, "the engine's prompt carries the block after the material, Hard rules unchanged")
check("## What the material does not show (applies to every answer)" in p, "...and the clause that absence from the material is not an argument")
os.environ["OTHER_LAW_CLASS"] = "off"; os.environ["ABSENCE_RULE"] = "off"
CA.generate_grounded_response("Is drunk driving bailable?", "[MVACT Section 185]\n" + m185["text"], matches=[m185])
check("## Classification of offences under OTHER laws" not in sent["p"] and "## What the material does not show" not in sent["p"], "both switched off: the prompt is as before")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
