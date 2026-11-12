"""test_case_court_age_fixes.py -- three fixes after the owner's staging test of the Muslim Women Act (2026-11-12): (1) the case-name reader no longer takes a section reference such as 7(c) as the first word of a
case name; (2) a reviewed-library judgment's Court cell comes from its own record (a Karnataka High Court judgment was printed as 'Supreme Court of India'); (3) a person's age ('31-year-old') next to 'case' is not a trial
that has run for years (the trial-delay excerpts were handed over to a compounding question). Offline and free. Run: python -X utf8 test_case_court_age_fixes.py"""
import json
import os
import sys

import authorities_table as AT
import excerpt_anchors as E
import grounding_checks as G

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---- 1. the case-name reader ----
check(G._mentions("under Section 7(c) (Rahna Jalal v. State of Kerala).") == ["Rahna Jalal v. State of Kerala"], "'Section 7(c) (Rahna Jalal v. State of Kerala)': the name starts at Rahna")
check(G._mentions("on a point (Section 7(c); Rahna Jalal v. State of Kerala).") == ["Rahna Jalal v. State of Kerala"], "'(Section 7(c); Rahna Jalal ...)': same")
check(G._mentions("section 35(3) (Satender Kumar Antil v Central Bureau of Investigation; Arnesh Kumar v State of Bihar).") == ["Satender Kumar Antil v. Central Bureau of Investigation", "Arnesh Kumar v. State of Bihar"], "two names in one bracket, each clean")
check(G._mentions("(Prabir Purkayastha v State (NCT of Delhi); Vihaan Kumar v State of Haryana).") == ["Prabir Purkayastha v. State (NCT of Delhi)", "Vihaan Kumar v. State of Haryana"], "a name with its own bracket does not swallow the next name")
check(G._mentions("In Hussainara Khatoon (I) v. Home Secretary the Court held") == ["Hussainara Khatoon I v. Home Secretary"], "a closed bracket inside the name stays (its words, as before): (I)")
check(G._mentions("In State (NCT of Delhi) v. Mahavir Singh the Court held") == ["State NCT of Delhi v. Mahavir Singh"], "a closed bracket inside the first party stays (its words, as before): State (NCT of Delhi)")
check(G._mentions("In Rahna Jalal v. State of Kerala (Supreme Court, 2020, from the wider search) the Court held") == ["Rahna Jalal v. State of Kerala"], "a court / year bracket after a name is not part of the name")
check(G._mentions("In Sushila Aggarwal v. State (NCT of Delhi), (2020) 5 SCC 1 the Court held") == ["Sushila Aggarwal v. State (NCT of Delhi)"], "a citation after the name is not part of it")
check(G._mentions("In Rahna Jalal v State of Kerala (2020) the Court held that") == ["Rahna Jalal v. State of Kerala"], "a plain mention is unchanged")
out = G.check_cases("Bail may be sought (Section 7(c); Rahna Jalal v. State of Kerala).", "Rahna Jalal v. State of Kerala and Another. 11. The statutory text indicates")
check(out == [], f"the Muslim Women Q1 sentence with the case in the material: no 'not found' notice ({out})")

# ---- 2. the Court cell of a library judgment ----
check(AT.library_court("Sri Manjunath M P v State of Karnataka", "2026:KHC:2726") == "High Court of Karnataka at Bengaluru", "Sri Manjunath: High Court of Karnataka at Bengaluru")
check(AT.library_court("Vihaan Kumar v State of Haryana", "2025 INSC 162") == "Supreme Court of India", "Vihaan Kumar: Supreme Court of India")
check(AT.library_court("Sakharam v State of Madhya Pradesh", "[1992] 1 S.C.R. 638") == "Supreme Court of India", "a pilot record sourced from api.sci.gov.in: Supreme Court of India")
check(AT.library_court("No Such Case v. Nobody", None) is None, "an unknown case: None")
rows = AT.build([{"type": "judgment", "case_name": "Sri Manjunath M P v State of Karnataka", "citation": "2026:KHC:2726", "year": 2026, "paragraph_number": "23"},
                 {"type": "judgment", "case_name": "Vihaan Kumar v State of Haryana", "citation": "2025 INSC 162", "year": 2025, "paragraph_number": "26"}],
                {"Sri Manjunath M P v State of Karnataka", "Vihaan Kumar v State of Haryana"}, [], [], lambda n, y, c: {})
check(rows["has_court"] is True and [r["court"] for r in rows["library"]] == ["High Court of Karnataka at Bengaluru", "Supreme Court of India"], "a High Court library row turns the Court column on and carries its court")
md = dict(AT.render_markdown(rows))["Authorities (reviewed library)"]
check("| Court |" in md and "High Court of Karnataka at Bengaluru" in md and "Supreme Court of India" in md, "the page table shows the library rows' courts")
rows2 = AT.build([{"type": "judgment", "case_name": "Vihaan Kumar v State of Haryana", "citation": "2025 INSC 162", "year": 2025, "paragraph_number": "26"}], {"Vihaan Kumar v State of Haryana"}, [], [], lambda n, y, c: {})
check("has_court" not in rows2 and "| Court |" not in dict(AT.render_markdown(rows2))["Authorities (reviewed library)"], "only Supreme Court rows: no Court column (the table is as it was)")
rows3 = AT.build([{"type": "judgment", "case_name": "Mathai Verghese v State of Kerala", "citation": None, "year": 2020, "paragraph_number": "5"},
                  {"type": "judgment", "case_name": "Sri Manjunath M P v State of Karnataka", "citation": "2026:KHC:2726", "year": 2026, "paragraph_number": "23"}],
                 {"Mathai Verghese v State of Kerala", "Sri Manjunath M P v State of Karnataka"}, [], [], lambda n, y, c: {})
check("not recorded" in dict(AT.render_markdown(rows3))["Authorities (reviewed library)"], "a library judgment with no court on record says 'not recorded', not Supreme Court")
src = open(os.path.join(HERE, "answer_export.py"), encoding="utf-8").read()
check('x["court"] or "Supreme Court of India"' not in src and 'x["court"] or "not recorded"' in src, "the Word / PDF export no longer defaults an empty Court cell to the Supreme Court")

# ---- 3. an age is not the length of a trial ----
POS = ["My 45-year-old client's trial has been going on for 9 years and the prosecution keeps asking for time. Can the case be closed because of the delay?",
       "The accused, aged 60, has been in custody for 5 years and the trial has not started. What can I do?",
       "He is now 66 years old and the trial that began 15 years ago is still not over. Can the court discharge him?",
       "My trial has been going on for 9 years and the prosecution keeps asking for time. Can the case be closed because of the delay?"]
NEG = ["Can the case against the 31-year-old shopkeeper be compounded under Section 7(b) now that the wife wants to settle, and does that change bail?",
       "My client is a 62-year-old man facing proceedings under the Dowry Prohibition Act. Is the offence bailable?",
       "The accused, aged 45 years, was tried in a case of theft. What is the punishment under the BNS?",
       "The complainant is a 70 years old widow and the case is about a forged will. Which sections apply?",
       "My client is 19 years of age and the proceedings were started on a neighbour's complaint. Can the FIR be quashed?",
       "In a case where the accused is at the age of 55, does the police need permission before arrest?"]
for q in POS:
    check(E._trial_delay(q) is True, f"still a delay question: {q[:70]!r}")
for q in NEG:
    check(E._trial_delay(q) is False, f"an age, not a delay: {q[:70]!r}")
data = json.load(open(os.path.join(HERE, "..", "recourse-sci-pool", "review_results", "2026-11-12_anchor_age", "questions.json"))) if os.path.exists(os.path.join(HERE, "..", "recourse-sci-pool", "review_results", "2026-11-12_anchor_age", "questions.json")) else None
if data:
    check(sum(E._trial_delay(q) for q in data["neg"]) == 0 and all(E._trial_delay(q) for q in data["pos"]), "the frozen 24 + 10 age questions: 0 false fires, 10 of 10 kept")

print()
print(f"{len(FAILURES)} failed" if FAILURES else "all passed")
sys.exit(1 if FAILURES else 0)
