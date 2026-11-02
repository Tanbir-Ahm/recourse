"""
test_no_inline_disclaimers.py -- 2026-11-02, owner's instruction: no "(from a wider search, not independently verified)" after a wider-search case in the answer, and no source-credit tags ("(open bucket, CC-BY-4.0, Dattam
Labs)", "(Dattam Labs; licence terms to be confirmed)") after a link. WIDER_LABEL and SOURCE_TAGS are off by default; the data credit is given once in the page footer.  Also the NI Act / IT Act shelf copies are not handed
over twice (chat_assistant._drop_full_act_duplicates).  Offline and free.  Run: python -X utf8 test_no_inline_disclaimers.py
"""
import os
import sys

for k in ("WIDER_LABEL", "SOURCE_TAGS"):
    os.environ.pop(k, None)

import authorities_table as AT  # noqa: E402
import chat_assistant as CA  # noqa: E402
import sci_search_tier as T  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


txt = "In *Arnesh Kumar v. State of Bihar* the Supreme Court directed that arrest is not automatic. See also *Ram Singh v. State of Punjab*."
cases = [{"case_name": "Ram Singh v. State of Punjab"}]
check(not T.label_on() and T.label_fed_cases(txt, cases) == txt, "off by default: the answer text gets no wider-search label")
check("EVERY TIME you name one of these cases" not in T.feed_instruction([T.SC_COURT]), "off: the feed instruction no longer asks the model for the label")
check("EVERY TIME you name one of these cases" not in T.feed_instruction([T.SC_COURT, "Gauhati High Court"]), "off: the same for a feed with a High Court passage")
check("nobody at recourse has read" in T.feed_instruction([T.SC_COURT]).lower() or "NOT independently verified" in T.feed_instruction([T.SC_COURT]), "the model is still told that the passages are not independently verified (an instruction to it, not a tag in the answer)")
check(T.credit_for("open_bucket_pdf") == "" and T.credit_for("high_court_bucket_pdf") == "" and T.credit_for("high_court_site_pdf") == "", "off by default: no credit tag after a link")
rows = [{"case": "A v. B", "year": "2020", "citation": "", "paragraphs": ["4"], "link": "https://x/y.pdf", "link_kind": "open_bucket_pdf", "court": "Supreme Court of India"},
        {"case": "C v. D", "year": "2021", "citation": "", "paragraphs": ["5"], "link": "https://x/z.pdf", "link_kind": "high_court_bucket_pdf", "court": "Gauhati High Court"}]
tab = AT._table(rows, False, True)
check("Dattam" not in tab and "CC-BY" not in tab and "licence terms" not in tab and "[open](https://x/y.pdf)" in tab, "the table of authorities links the judgment with no credit tag")
check("Dattam Labs" in T.PAGE_CREDIT and "CC-BY-4.0" in T.PAGE_CREDIT, "the credit exists once, as PAGE_CREDIT (the page footer)")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "recourse_app.py"), encoding="utf-8").read()
check("PAGE_CREDIT" in src, "the Streamlit page footer prints PAGE_CREDIT")
pilot = CA._format_pilot_context_as_wider_search([{"case_name": "X v. Y", "text": "passage"}], T)
check("EVERY TIME you name one of these cases" not in pilot and "NOT independently verified" in pilot, "the pilot-case instruction does not ask for the label either")
check("followed each time by the words" not in CA.RESPONSE_GENERATION_PROMPT_V3_LAWYER, "the Research Note prompt no longer says a wider-search case is followed by the label")

os.environ["WIDER_LABEL"] = "on"
os.environ["SOURCE_TAGS"] = "on"
check(T.label_fed_cases(txt, cases).count(T.LABEL) == 1 and "EVERY TIME you name one of these cases" in T.feed_instruction([T.SC_COURT]), "WIDER_LABEL=on brings the old behaviour back (label in the text, sentence in the prompt)")
check("CC-BY-4.0" in T.credit_for("open_bucket_pdf"), "SOURCE_TAGS=on brings the credit tag back")
for k in ("WIDER_LABEL", "SOURCE_TAGS"):
    os.environ.pop(k, None)

ov = [{"act": "NIACTFULL", "section_number": "138"}, {"act": "NIACTFULL", "section_number": "9"}, {"act": "ITACTFULL", "section_number": "66C"}, {"act": "PCACT", "section_number": "17"}]
out = CA._drop_full_act_duplicates(ov, [{"act": "NIACT", "section_number": "138"}, {"act": "ITACT", "section_number": "66C"}])
check([(m["act"], m["section_number"]) for m in out] == [("NIACTFULL", "9"), ("PCACT", "17")], "NI / IT shelf copies of a section the library already supplies are dropped; other sections and Acts stay")
check(CA._drop_full_act_duplicates(ov, []) == ov and CA._drop_full_act_duplicates(ov, None) == ov, "with nothing from the library nothing is dropped")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")
