"""test_mv_act.py -- the Motor Vehicles Act, 1988 on the Act shelf (owner's go 2026-11-10: "Motor Vehicles Act. Put it on the Act shelf, so the answer can state its sections").
What is checked: the loaded text carries the repairs the PDF as on 15 August 2026 required (Act 8 of 2026 and slips of India Code's database), the superseded sub-sections are gone, the State amendments are set aside, the key accident sections are there,
and the word pass reaches the Act for accident wording that does not name it. Offline and free. Run: python -X utf8 test_mv_act.py"""
import json
import os
import re

import act_detect
import act_shelf as S

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


C = {c["section_number"]: c for c in json.load(open(os.path.join(HERE, "act_shelf", "mv_act_1988.json"), encoding="utf-8"))}
check(len(C) == 257 and sum(1 for c in C.values() if c["omitted"]) == 7 and all(c["text_status"] == "machine_checked" for c in C.values()), "257 sections, 7 omitted stubs, every section machine_checked (nobody has read the text)")
st = S.load()["acts"]["mv_act_1988"]
check(st["ok"] and len(st["by_num"]) == 257 and len(st["ranked"]) == 250, "the shelf loads the Act: every section by number, 250 searchable by meaning")
check(all(k in C and not C[k]["omitted"] for k in ("132", "134", "134A", "159", "161", "162", "164", "164A", "164B", "166", "184", "185", "187", "194B", "194D", "196", "199A", "207")), "the accident, licence, insurance and penalty sections are all there")
# repairs the PDF required
check("within thirty days or as soon as may be" in C["55"]["text"] and "fourteen days" not in C["55"]["text"], "s.55: 'thirty days' (Act 8 of 2026, w.e.f. 15-08-2026; the database still read 'fourteen days')")
check("(4) Notwithstanding anything contained in sub-section (3), ex gratia payments" in C["164"]["text"] and "Explanation" in C["164"]["text"], "s.164: sub-section (4) and the Explanation (inserted by Act 8 of 2026) are present")
check("Each State Government shall supply" not in C["26"]["text"] and "Each State Government shall supply" not in C["63"]["text"], "ss.26 and 63: the superseded sub-sections are gone (the sections were substituted whole)")
check("[or any other person authorised in this behalf by the State Government]" in C["114"]["text"] and "unmanageable,\n* * * * *\nand he shall" in C["132"]["text"], "ss.114 and 132: the PDF's reading")
check("phycically" not in C["186"]["title"] and "physically" in C["186"]["title"] and "physically" in C["186"]["text"].split("\n", 1)[0], "s.186: the title's typing slip is corrected, in the title and in the heading line")
check(all(c["text"].count("learners licence") == 0 and "belive" not in c["text"] and "diplaying" not in c["text"] for c in C.values()), "the typing slips of the database are corrected (learners, belive, diplaying)")
check(not any(re.search(r"STATE\s+AMENDMENT", c["text"], re.I) for c in C.values()) and {k for k, c in C.items() if c.get("state_amendments")} == {"41", "65", "71", "103", "192", "207"}, "State amendments are set aside from the text (41, 65, 71, 103, 192, 207)")
check("is super-imposed on" in C["2"]["text"] and "adapted carriage" not in C["2"]["text"], "s.2: 'super-imposed' and 'adapted vehicle'")
# the strict check ran and nothing was left unexplained
m = {a["key"]: a for a in json.load(open(os.path.join(HERE, "act_shelf", "manifest.json"), encoding="utf-8"))["acts"]}["mv_act_1988"]
check(len(m["corrections"]) == 39 and all(x.get("why", "").strip() for x in m["corrections"] + m["ordered_accepted"] + m["accepted"]) and m["india_code"]["uuid"] == "2bbbcc40-38f1-4b15-ae94-646b85db4ee7", "the manifest: 39 corrections, every correction and every accepted difference says why")

# the word pass reaches the Act for accident wording
os.environ["ACT_DETECT"] = "wide"
hit = lambda q: any(h["id"] == "mv_act_1988" for h in act_detect.wide(q))
for q in ("Around 11 pm on a highway his truck hit a man who was crossing the road, and the man died. My client did not stop and drove on.",
          "I was fined Rs 1,000 for riding without a helmet. Is that legal?", "Can a Claims Tribunal award compensation to the family of a person killed by a bus?",
          "My driving licence was suspended after I was caught talking on the phone while driving."):
    check(hit(q), f"the word pass reaches the Act: {q[:60]}")
for q in ("My car was stolen from outside my house last night.", "The accused kidnapped the girl and took her in a car to another town.", "A gang robbed the truck carrying electronics on the highway at gunpoint.",
          "The shopkeeper sold me a defective helmet and refuses to return the money."):
    check(not hit(q), f"...and not for: {q[:60]}")
print()
print("FAILED:" if FAILURES else "all passed", FAILURES if FAILURES else "")
raise SystemExit(1 if FAILURES else 0)
