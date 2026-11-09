"""
test_sci_unused.py -- wider-search passages the answer does not name go into a collapsed list (2026-11-09; staging: a lawyer's note named none of 8 passages it had been handed, six of them about other subjects, and all 8 sat open under the answer).

Proves: answer_view.sci_named() says whether the answer names a wider-search case (by its distinctive party words, whatever the stored form "Samar Chiring v. The State of Assam" or the answer's form "Samar Chiring"); a generic party (State of ..., Union of India) never counts alone;
the view's sci_related items carry `used`; nothing is removed from the view (the authorities table and the export still list every case); the Word/PDF export prints the unused ones as names only.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import answer_view as AV

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


reply = ("Samar Chiring (Gauhati High Court 2025) is a case about a recorded clip. The Supreme Court in Satender Kumar Antil v CBI held that notice is the rule. "
         "In Gurmit Singh the Court said a complainant's testimony may be relied on. The State of Punjab was the appellant there. Ranjit Hazarika is also relevant.").lower()
check(AV.sci_named("Samar Chiring v. The State of Assam", reply), "a case the answer names by its first party is named")
check(AV.sci_named("The State of Punjab v. Gurmit Singh & Ors", reply), "a case named by its second party, the first being the State, is named")
check(AV.sci_named("Sri Ranjit Hazarika v. State of Assam and Anr", reply), "an honorific and 'and Anr' do not hide a case")
check(not AV.sci_named("Ashok Dhankad v. State of NCT of Delhi and Anr", reply), "a case the answer does not name is not named")
check(not AV.sci_named("The State of Maharashtra P. C. Singhi v. Dr. Praful B. Desai Dr. Praful B. Desai and another", reply), "the video-conferencing case is not named")
check(not AV.sci_named("Vijayakumar v. State of Tamil Nadu, Represented by the Inspector of Police", "the state of tamil nadu was a party in another matter."), "a generic party alone never counts")
check(not AV.sci_named("", reply) and not AV.sci_named(None, reply) and not AV.sci_named("A v. B", reply), "no name, or a name too short to be distinctive: not named")
check(AV.sci_named("Just Rights for Children Alliance & Anr v. S. Harish & Ors", "just rights for children alliance decided section 67b."), "a long first party is matched as a whole")

items = [{"case_name": "Samar Chiring v. The State of Assam", "link": "u1", "date": "2025-02-20", "paragraph": "5-6", "link_kind": None, "register_note": None, "passage_note": None, "names_register_note": None, "excerpt": "x"},
         {"case_name": "Ashok Dhankad v. State of NCT of Delhi and Anr", "link": "u2", "date": "2025-08-13", "paragraph": "9", "link_kind": None, "register_note": None, "passage_note": None, "names_register_note": None, "excerpt": "y"}]
res = {"state": "single_match", "audience": "lawyer", "response_text": "Samar Chiring (2025) concerns a recorded clip.", "matches": [], "sci_related_judgments": items, "sci_fed": True}
v = AV.build(res)
got = [(i["case_name"], i["used"]) for i in v["sci_related"]["items"]]
check(got == [("Samar Chiring v. The State of Assam", True), ("Ashok Dhankad v. State of NCT of Delhi and Anr", False)], f"the view marks each wider-search item used or not ({got})")
check(len(v["sci_related"]["items"]) == 2, "nothing is removed from the view")

import answer_export as AE
blocks = AE._answer_blocks(v, True)
txt = " ".join(" ".join(r.get("text", "") for r in b.get("runs", [])) + " " + str(b.get("text", "")) for b in blocks)
check("Also read, but not named in the answer" in txt and "Ashok Dhankad" in txt, "the export lists the case the answer does not name, under its own line")
monos = [b.get("text") for b in blocks if b.get("t") == "mono"]
check("Samar Chiring" in txt and "x" in monos, f"the export keeps the named case with its passage ({monos})")
check("y" not in monos, "the export does not reproduce the unnamed case's passage")
order = [txt.index("Samar Chiring"), txt.index("Ashok Dhankad")]
check(order == sorted(order), "the named case comes first")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
