"""
test_fixes_2026_11_02.py -- the fixes after the owner's first full-stack staging answer (circumstantial evidence, 2026-11-02; "Yes, build it, along with the other fixes"). Offline and free; no model.
Run: python -X utf8 test_fixes_2026_11_02.py
  1. an excerpt-anchor case that is on the Overruled Register (Hanumant v. The State of Madhya Pradesh, row L1-0471) carries the register's line into the prompt, with the "register does not say which point" sentence
  2. the register's scan recognises a retrieved case given as year + AIR citation (the year goes in brackets)
  3. PASSAGE_NOTES: a passage that tells the story of ANOTHER reported decision (its trial court, its High Court) is not noted as "a lower court's view"; a passage with its own lower-court sentence still is
  4. the support rule reaches comparison tables and lists, and bans labels the passage does not use
  5. an Act that is loaded but not relied on no longer gets "the answer below does not rest on it"; an Act that is not held keeps its sentence
  6. the Evidence Act / BSA pairing note says "unreviewed" once per answer
  7. the PDF / Word export carries the CC-BY credit once, only for the buckets its passages came from
"""
import json
import os
import sys

os.environ["REGISTER_HOOKS"] = "on"

import act_directory as AD
import answer_export as X
import chat_assistant as CA
import ea_bsa_map
import excerpt_anchors as E
import passage_notes as PN
import register_hooks as RH

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


data = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "excerpt_anchors.json"), encoding="utf-8"))
anchors = [a for a in data["anchors"] if a["topic"] == "circumstantial_evidence"]
byid = {a["id"]: a for a in anchors}

# 1. the anchor's own register line
h = RH.own_case_lines_for_anchor(byid["circumstantial_evidence_hanumant"])
check(len(h) == 1 and h[0].startswith("REGISTER FACT: Hanumant v. The State of Madhya Pradesh (1952) was overruled by State through CBI v. S.J. Choudhary (1996)."), "Hanumant: the register's REGISTER FACT line is produced from the anchor's own name, year and citation")
check("does not say which point of this judgment was corrected" in h[0] and "has been displaced" in h[0] and "Do not state its holding as current law" not in h[0], "Hanumant: the row has no scope, so the line says the register does not say which point, and does not contradict the excerpt")
check(RH.own_case_lines_for_anchor(byid["circumstantial_evidence_sharad_sarda"]) == [], "Sarda is not on the register: no line")
check(RH.own_case_lines_for_anchor({}) == [] and RH.own_case_lines_for_anchor(None) == [], "no anchor, no line; never raises")
sec = E._section("circumstantial_evidence", anchors)
check("[Overruled Register -- not optional: a case whose excerpt is given above is on our register" in sec and "REGISTER FACT: Hanumant" in sec, "the prompt section of the topic carries the line")
os.environ["REGISTER_HOOKS"] = "off"
check(RH.own_case_lines_for_anchor(byid["circumstantial_evidence_hanumant"]) == [] and "REGISTER FACT: Hanumant" not in E._section("circumstantial_evidence", anchors), "REGISTER_HOOKS=off: nothing")
os.environ["REGISTER_HOOKS"] = "on"

# 2. year + AIR citation
lines = RH.prompt_lines_for_match({"case_name": "Hanumant v. The State of Madhya Pradesh", "year": 1952, "citation": "AIR 1952 SC 343"})
check(len(lines) == 1 and "overruled by State through CBI v. S.J. Choudhary" in lines[0], "a retrieved case given as name + year + 'AIR 1952 SC 343' is found by the register")
lines = RH.prompt_lines_for_match({"case_name": "Raj Deo Sharma v. The State of Bihar", "year": 1999, "citation": None})
check(len(lines) == 1, "a case with no citation is still found by name and year (as before)")

# 3. passage notes
TRI = ("14. The question of burden of proof where some facts are within the personal knowledge of the accused was examined in State of West Bengal v. Mir Mohammad Omar & Ors. (2000) 8 SCC 382. "
       "In this case the assailants forcibly dragged the deceased Mahesh. The trial Court convicted the accused under Section 364 read with Section 34 IPC and sentenced them to 10 years RI. The High Court held that the prosecution failed and acquitted them.")
check(PN.kinds(TRI) == [], "a passage telling the story of a reported decision (its trial court, its High Court): no 'lower court' note")
OWN = "The trial Court convicted the accused. The High Court held that the evidence was insufficient and acquitted them."
check(PN.kinds(OWN) == ["lower_court"], "a passage with its own lower-court sentence is still noted")
REJ = "In Raju v. State (2010) 5 SCC 1 this was applied. The High Court erred in holding that the evidence was insufficient."
check(PN.kinds(REJ) == ["lower_court_rejected"], "a lower court found wrong by this Court is still noted, even after a citation")
check(PN.kinds("The High Court held that the evidence was insufficient. See Raju v. State (2010) 5 SCC 1.") == ["lower_court"], "a citation AFTER the lower-court sentence does not remove the note")

# 4. support rule
for name, prompt in (("Adviser", CA.RESPONSE_GENERATION_PROMPT_V3), ("Research Note", CA.RESPONSE_GENERATION_PROMPT_V3_LAWYER)):
    check("is left out" in prompt and "missing link" in prompt and "only DESCRIBES" in prompt and "silence may not be held against a person" in prompt, f"{name}: the support rule reaches tables and lists, bans labels the passage does not use, and covers a passage that only describes an earlier judgment")
def hard(t):
    return t[t.index("## Hard rules (never break)"):t.index("## What to include, what to leave out")]
check(hard(CA.RESPONSE_GENERATION_PROMPT) == hard(CA.RESPONSE_GENERATION_PROMPT_V3) == hard(CA.RESPONSE_GENERATION_PROMPT_V3_LAWYER), "the Hard rules block is still identical in every style")

# 5. Act notice
PM = AD.detect("Can I get bail under the Prevention of Money-laundering Act, 2002?")
n = AD.notice(PM, "answer", held={"pmla_2002": {"state": "unused", "loaded_on": "2026-10-16"}})
check(n and "does not rest on it" not in n["text"] and "Official text on India Code:" in n["text"], "an Act loaded but not relied on: subject line and link only")
PC = AD.detect("Is a bribe taken by a clerk punishable under the Prevention of Corruption Act, 1988?")
n2 = AD.notice(PC, "answer", held=None)
check(n2 and "does not hold the text of that Act, so the answer below does not rest on it." in n2["text"], "an Act that is not held keeps its sentence")

# 6. pairing note once
note_ea = ea_bsa_map.note_for("evidence_act_1872", "106")
note_bsa = ea_bsa_map.note_for("bsa_2023", "109")
check("ONCE in the whole answer" in note_ea and "ONCE in the whole answer" in note_bsa, "the Evidence Act and BSA notes ask for the 'unreviewed' remark once per answer")

# 7. export credit
def doc(kind):
    return X.build_document([{"question": "q", "view": {"kind": "answer", "answer_text": "x", "sci_related": {"items": [{"link_kind": kind, "case_name": "A v. B"}], "fed": True}}, "answer_id": "a1", "created_at": None, "audience": "lawyer"}])
t_sc, t_hc, t_none = X.all_text(doc("open_bucket_pdf")), X.all_text(doc("high_court_bucket_pdf")), X.all_text(doc("court_archive_pdf"))
check("Supreme Court judgments bucket (Dattam Labs, CC-BY-4.0)" in t_sc and t_sc.count("Dattam Labs") == 1 and "High Court judgments bucket" not in t_sc, "export: Supreme Court bucket passages -> the credit once, naming that bucket only")
check("High Court judgments bucket (Dattam Labs)" in t_hc and "CC-BY" not in t_hc, "export: High Court bucket passages -> the credit for that bucket")
check("Dattam" not in t_none, "export: only court-archive passages -> no credit line")

# 8. layout change (owner: "Build the layout change"): paragraph labels in the table of authorities; the rest is tested in test_answer_export.py
import authorities_table as AT
check(AT.paragraph_label("preamble/128") == "not numbered" and AT.paragraph_label("42") == "42" and AT.paragraph_label("152 to 154") == "152 to 154", "authorities_table.paragraph_label: numbers as written, passage ids as 'not numbered'")
tbl = AT._table([{"case": "A v. B", "year": 2020, "citation": None, "paragraphs": ["preamble/128", "9"], "status": "Not checked by us.", "link": "https://x.org/a"}], False, False) if hasattr(AT, "_table") else None
check(tbl is None or ("not numbered, 9" in tbl and "preamble" not in tbl), "the table cell shows 'not numbered', not the index's passage id")

print()
if FAILURES:
    print(len(FAILURES), "FAILED:", FAILURES)
    sys.exit(1)
print("ALL PASSED")
