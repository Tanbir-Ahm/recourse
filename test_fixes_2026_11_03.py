"""
test_fixes_2026_11_03.py -- owner's "Build A, B, C and E; run D first" (2026-11-03). Offline and free; no model. Run: python -X utf8 test_fixes_2026_11_03.py
  A  the box of sections shows the sub-section the answer cites when the plain excerpt stops before it (BNSS 483(3))
  B  a passage that is a law reporter's headnote (page markers such as [419 C-E]) is said to be one, to the model and on the page
  C  the merged table of authorities has no Source column when every row has the same source (the label is in the heading)
  E  one second search per name per question (four flagged cases pointing at one corrector ran the same search four times)
"""
import contextlib
import io
import json
import os
import sys

os.environ["SCI_SEARCH_MODE"] = "feed"
os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
os.environ.pop("PASSAGE_NOTES", None)
os.environ.pop("HEADNOTE_NOTE", None)

import answer_export as X
import answer_view as V
V.LIBRARY_FULL_CHARS = 900          # since 2026-11-09 a library section is shown whole up to 8,000 characters; the cut logic below is unchanged and still serves a longer one, so these short test sections lower the limit to keep exercising it (test_statute_full.py tests the new limit)
import chat_assistant as CA
import passage_notes as PN
import sci_search_tier as T
from retrieval import get_statute_section

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---------------------------------------------------------------- A
d = get_statute_section("BNSS", "483")
m483 = {"type": "statute", "act": "BNSS", "section_number": "483", "text": d["text"], "source": "semantic"}
plain = V.statute_excerpt(m483)
check(len(plain) <= 900 and "(3) A High Court" not in plain, "the plain excerpt of BNSS 483 stops before sub-section 3 (the gap the owner saw)")
check(V.cited_subsections("Section 483(3) of the BNSS and s. 483(1)(a) apply; section 4830(2) does not.", "483") == ["3", "1"] and V.cited_subsections("Section 483 of the BNSS", "483") == [] and V.cited_subsections("Section 482(2)", "483") == [], "cited_subsections: only the section asked about, only a bracketed sub-section")
ex = V.statute_excerpt(m483, "Section 483(3) of the BNSS allows the court to direct arrest.")
check(ex.startswith("483. (1) A High Court or Court of Session may direct") and "\n[...]\n" in ex and "(3) A High Court or Court of Session may direct that any person who has been\nreleased on bail under this Chapter be arrested" in ex and "(2)" not in ex.split("[...]")[1], "an answer that cites 483(3): the first line, a marked gap, and sub-section 3 itself")
check(V.statute_excerpt(m483, "Section 483 of the BNSS lets a court grant bail.") == plain and V.statute_excerpt(m483, "") == plain and V.statute_excerpt(m483) == plain, "an answer that cites no sub-section: the excerpt it always was")
short = {"act": "BNSS", "section_number": "9", "text": "9. (1) First.\n(2) Second.\n(3) Third."}
check(V.statute_excerpt(short, "Section 9(3) says so.") == V.clean_excerpt(short["text"]), "a section shorter than the cut is shown whole")
inside = {"act": "BNSS", "section_number": "9", "text": "9. (1) First part.\n(2) Second part.\n(3) " + "x " * 600}
check(V.statute_excerpt(inside, "Section 9(2) says so.") == V.clean_excerpt(inside["text"])[:900], "a cited sub-section already inside the plain excerpt: nothing added")
check(V.statute_excerpt(m483, "Section 483(9) says so.") == plain, "a cited sub-section the section does not have: the plain excerpt, no error")
view = V.build({"state": "single_match", "response_text": "Section 483(3) of the BNSS allows arrest of a person on bail.", "matches": [m483], "audience": "lawyer"})
check(len(view["statutes"]) == 1 and "(3) A High Court or Court of Session may direct" in view["statutes"][0]["text"], "the view's sections box carries sub-section 3")
doc = X.build_document([{"question": "q", "view": view, "answer_id": "a1", "created_at": None, "audience": "lawyer"}])
check("released on bail under this Chapter be arrested and commit him to custody" in " ".join(X.all_text(doc).split()), "the download prints it")

# ---------------------------------------------------------------- B
SIBBIA = ("5. An order of bail can be passed under section 438(1) of the Code without notice to the Public Prosecutor. [419 E-F] 6. Equally the operation of an order passed under section 438(1) need not "
          "necessarily be limited in point of time. The Court may, if there are reasons for doing so, limit the operation of the order to a short period. [419 F-G]")
check(PN.is_headnote(SIBBIA) and PN.is_headnote("x [420 A] y") and not PN.is_headnote("The Court said at para [12] that item [1] applies, (AIR pp. 345-46, para 10).") and not PN.is_headnote("") and not PN.is_headnote(None), "is_headnote: reporter page markers, nothing else")
os.environ["HEADNOTE_NOTE"] = "off"
check(not PN.is_headnote(SIBBIA), "HEADNOTE_NOTE=off: no note")
os.environ.pop("HEADNOTE_NOTE")


def fake_search(question, timeout=None, k=10, label="x"):
    return {"ok": True, "results": json.loads(json.dumps(RES["v"])), "as_of": "2026-07-13", "index_commit": "abc"}


RES = {"v": [{"rank": 1, "doc": 21, "case_name": "Gurbaksh Singh Sibbia v. State of Punjab", "date": "1980-04-09", "paragraph": "5", "link": "https://x/21.pdf", "link_kind": "court_archive_pdf", "text": SIBBIA + " " + "more words " * 20,
                      "name_to_review": False, "citations": {}, "score": 0.9},
                     {"rank": 2, "doc": 22, "case_name": "Beta Singh v. State of Punjab", "date": "2018-07-02", "paragraph": "9", "link": "https://x/22.pdf", "link_kind": "court_archive_pdf",
                      "text": "The accused is entitled to the benefit of doubt where two views are possible on the evidence, and the court must prefer the view favouring the accused. " * 3, "name_to_review": False, "citations": {}, "score": 0.8}]}
T.search = fake_search
T.reset()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    block = T.feed_block("Can an anticipatory bail order be limited in time?")
cases = {c["case_name"]: c for c in T._LOCAL.cases}
sib, beta = block.split("Gurbaksh Singh Sibbia v. State of Punjab", 1)[1].split("Beta Singh", 1)[0], block.split("Beta Singh v. State of Punjab", 1)[1]
check("the reporter's HEADNOTE" in sib and "not the Court's own words" in sib and "reporter's HEADNOTE" not in beta, "feed block: the headnote passage carries the note for the model, the ordinary one does not")
check(PN.HEADNOTE_PAGE in (cases["Gurbaksh Singh Sibbia v. State of Punjab"]["passage_note"] or "") and not cases["Beta Singh v. State of Punjab"]["passage_note"], "...and the page's list says it, for that case only")
pool = [{"case_name": "Gurbaksh Singh Sibbia v. State of Punjab", "citation": None, "text": SIBBIA, "ik_search_url": "https://e.org/s"}, {"case_name": "Z v. W", "citation": None, "text": "An ordinary passage.", "ik_search_url": None}]
blk = CA._format_pilot_context_as_wider_search(pool, T)
check(blk.count("reporter's HEADNOTE") == 1 and blk.index("reporter's HEADNOTE") < blk.index("Z v. W"), "the pool block (feed mode): the note under the headnote passage only")
os.environ["SCI_SEARCH_MODE"] = "shadow"
blk2 = CA._format_pilot_context_for_prompt(pool)
check(blk2.count("reporter's HEADNOTE") == 1, "the pool block (other modes): the same")
os.environ["SCI_SEARCH_MODE"] = "feed"
res = {"state": "single_match", "response_text": "In Gurbaksh Singh Sibbia v. State of Punjab (1980) the Court said so. Z v. W is also relevant.", "matches": [], "unverified_related_judgments": [dict(p, paragraph_number=None) for p in pool]}
v = V.build(res)
u = {j["case_name"]: j for j in v["unverified"]}
check(u["Gurbaksh Singh Sibbia v. State of Punjab"]["note"] == PN.HEADNOTE_PAGE and u["Z v. W"]["note"] is None, "the view: a note on the headnote passage only")
dd = X.build_document([{"question": "q", "view": v, "answer_id": "a1", "created_at": None, "audience": "lawyer"}])
check(X.all_text(dd).count(PN.HEADNOTE_PAGE) == 1, "the download prints it once, under the passage")

# ---------------------------------------------------------------- C
def table(sources):
    rows = ""
    for i, (heading, n) in enumerate(sources):
        rows += ""
    tables = []
    for heading, name in sources:
        tables.append({"heading": heading, "markdown": "| Case | Citation | Paragraph | Where it stands on our lists | Link |\n|---|---|---|---|---|\n| " + name + " | not held | 4 | Not checked by us. | [open](https://e.org/x) |\n"})
    return tables


one = X.merged_authorities(table([("Further reading from a wider search (not independently verified)", "A v. B (2020)"), ("Further reading from a wider search (not independently verified)", "C v. D (2019)")]))
check(one["head"][0] == "Case" and "Source" not in one["head"] and one["single_source"] == "Wider search (not independently verified)" and len(one["rows"]) == 2 and all(len(r) == len(one["head"]) for r in one["rows"]), f"one source: no Source column ({one['head']})")
two = X.merged_authorities(table([("Verbatim excerpts the answer read", "A v. B (2020)"), ("Further reading from a wider search (not independently verified)", "C v. D (2019)")]))
check(two["head"][:2] == ["Case", "Source"] and two["single_source"] is None and all(len(r) == len(two["head"]) for r in two["rows"]), "two sources: the column stays")
vw = {"kind": "answer", "answer_markdown": "Short.", "authorities": {"tables": table([("Further reading from a wider search (not independently verified)", "A v. B (2020)")]), "note": None}}
dc = X.build_document([{"question": "q", "view": vw, "answer_id": "a1", "created_at": None, "audience": "lawyer"}])
heads = [b["text"] for b in dc["blocks"] if b["t"] in ("h3", "p") and b.get("text", "").startswith("Authorities and where each stands")] or [X.plain(b["runs"]) for b in dc["blocks"] if b["t"] == "p" and X.plain(b["runs"]).startswith("Authorities and where each stands")]
check(heads == ["Authorities and where each stands on our lists — wider search (not independently verified)"], f"the heading carries the label ({heads})")
txt = X.all_text(dc)
check(txt.count("not independently verified") <= 3, "the file no longer repeats the label per row")
lib = X.merged_authorities(table([("Authorities (reviewed library)", "A v. B (2020)")]))
check(lib["single_source"] == "Library", "a table that is only library cases: label 'Library' (no heading suffix)")

# ---------------------------------------------------------------- E
CALLS = []


def counting_search(question, timeout=None, k=10, label="x"):
    CALLS.append(label)
    if label == "sci_search_second":
        return {"ok": True, "results": [], "as_of": "2026-07-13", "index_commit": "abc"}
    return {"ok": True, "results": json.loads(json.dumps(RES["v"])), "as_of": "2026-07-13", "index_commit": "abc"}


def flags(results):
    return [{"source": "register", "note": "reported overruled", "overruling": "Sushila Aggarwal v. State (NCT of Delhi)", "overruling_year": "2020"} if r["doc"] in (21, 22) else {"source": "none", "note": None} for r in results]


RES["v"] = [dict(RES["v"][0], doc=21), dict(RES["v"][1], doc=22, case_name="Nirmal Jeet Kaur v. State of M.P."),
            dict(RES["v"][1], doc=23, case_name="Adri Dharan Das v. State of West Bengal"), dict(RES["v"][1], doc=24, case_name="Salauddin Abdulsamad Shaikh v. State of Maharashtra")]
T.search = counting_search
T._flags = lambda results: [{"source": "register", "note": "reported overruled", "overruling": "Sushila Aggarwal v. State (NCT of Delhi)", "overruling_year": "2020"} if r["doc"] in (21, 22, 23) else {"source": "none", "note": None} for r in results]
T.reset()
CALLS.clear()
with contextlib.redirect_stdout(io.StringIO()):
    T.feed_block("Can an anticipatory bail order be limited in time?")
check(CALLS.count("sci_search_second") == 1, f"three flagged cases that point at one corrector: ONE second search ({CALLS.count('sci_search_second')}; the first search is {CALLS.count('x') + sum(1 for c in CALLS if c != 'sci_search_second')})")

print()
if FAILURES:
    print(len(FAILURES), "FAILED:", FAILURES)
    sys.exit(1)
print("ALL PASSED")
