"""
test_feed_dedup.py -- the same paragraph found in two judgments is handed over once (sci_search_tier._dedupe_passages, FEED_DEDUP default on; owner's 2026-11-05 test: Jayanta Kumar Ghosh and Debashish Bhattacharjee).
Offline and free: a stand-in search. Run: python -X utf8 test_feed_dedup.py
"""
import contextlib
import io
import os
import sys

os.environ["SCI_SEARCH_MODE"] = "feed"
for k in ("FEED_DEDUP", "PASSAGE_NOTES", "FEED_STATUTE_FILTER"):
    os.environ.pop(k, None)
import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


P45 = ("What is, however, extremely important to note is that the legislature, while imposing limitation by Section 437(1) on the powers of the Magistrate, has expressly excluded from the purview of this limitation, "
       "the Court of Session and the High Court. Having excluded from the embargo of the limitation, Section 439(1) confers special powers on the High Court and the Court of Session to grant bail.")


def R(doc, name, date, text, para="45", court="High Court"):
    return {"rank": doc, "doc": doc, "case_name": name, "date": date, "paragraph": para, "link": f"https://x/{doc}.pdf", "link_kind": "open_bucket_pdf", "text": text, "name_to_review": False,
            "court": "Gauhati High Court" if court == "High Court" else "Supreme Court of India"}


A = R(1, "Jayanta Kumar Ghosh v. The State of Assam and Anr", "2010-05-28", P45)
B = R(2, "Debashish Bhattacharjee @ Bappi v. The State of Assam and Anr", "2010-05-28", "45.  " + P45.upper().replace(",", " ,"))      # same words: other case, capitals, other spacing
C = R(3, "Kalyan Chandra Sarkar v. Rajesh Ranjan", "2005-01-18", "But even persons accused of non bailable offences are entitled for bail if the court concerned comes to the conclusion that the prosecution has failed to establish a prima facie case against him.", "7", "SC")
real_search = T.search


def run(results, flags=None):
    T.search = lambda q, **k: {"results": [dict(r) for r in results], "as_of": "2026-07-13", "index_commit": "abc", "tier": "x"}
    if flags is not None:
        real_flags = T._flags
        T._flags = flags
    T.reset()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            block = T.feed_block("a bail question")
    finally:
        if flags is not None:
            T._flags = real_flags
    return block, list(T._LOCAL.cases), buf.getvalue()


block, cases, out = run([A, B, C])
names = [c["case_name"] for c in cases]
check(len(cases) == 2 and "Debashish" not in " ".join(names) and "Jayanta Kumar Ghosh v. The State of Assam and Anr" in names, f"the identical paragraph is handed over once: {names}")
check("Debashish" not in block and T.SAME_PASSAGE_PROMPT.strip() in block, "the model's material has one copy and a line saying it is ONE passage")
ja = next(c for c in cases if c["case_name"].startswith("Jayanta"))
check("Debashish Bhattacharjee" in (ja.get("passage_note") or "") and "2010-05-28" in ja["passage_note"] and "one passage, not two decisions" in ja["passage_note"], "the page says where else the paragraph appears")
check(not (next(c for c in cases if c["case_name"].startswith("Kalyan")).get("passage_note") or "").count("same paragraph"), "an unrelated passage gets no such note")
check("SCI_FEED_SAME" in out and "Debashish" in out, "one SCI_FEED_SAME log line")
check("SCI_FEED fed 2 case(s)" in out, "the fed count is the merged one")

block, cases, out = run([B, A, C])
check([c["case_name"][:9] for c in cases][0] == "Debashish" and len(cases) == 2, "the better-ranked copy is the one kept")

os.environ["FEED_DEDUP"] = "off"
block, cases, out = run([A, B, C])
check(len(cases) == 3 and T.SAME_PASSAGE_PROMPT.strip() not in block and "SCI_FEED_SAME" not in out, "FEED_DEDUP=off: both are handed over as before, no note")
os.environ.pop("FEED_DEDUP")

block, cases, out = run([A, dict(A, rank=2, paragraph="46")])
check(len(cases) == 1 and "SCI_FEED_SAME" not in out, "two passages of the SAME judgment are not a merge (one passage per judgment as before)")

short = "Bail is a right."
block, cases, out = run([R(1, "Case One v. State", "2001-01-01", short), R(2, "Case Two v. State", "2002-02-02", short)])
check(len(cases) == 2, "passages too short to compare (under 120 characters) are never merged")

other = P45.replace("limitation", "restriction")
block, cases, out = run([A, R(2, "Another v. State", "2011-01-01", other)])
check(len(cases) == 2, "different words are not merged")

flag_b = lambda results: [{"source": "register" if r.get("doc") == 2 else "none", "note": None} for r in results]
block, cases, out = run([A, B, C], flags=flag_b)
check(len(cases) == 3 and "SCI_FEED_SAME" not in out, "a judgment on the Overruled Register is never merged away (its fact must reach the model)")
flag_a = lambda results: [{"source": "card" if r.get("doc") == 1 else "none", "note": None} for r in results]
block, cases, out = run([A, B, C], flags=flag_a)
check(len(cases) == 3, "nor is one with a warning card")

many = [R(i, f"Case {i} v. State", f"2000-01-{i:02d}", f"Distinct passage number {i} about bail and custody and the powers of the court. " * 4, str(i), "SC") for i in range(10, 19)]
dup = [R(30, "Copy v. State", "2010-05-28", many[0]["text"], "9", "SC")]
block, cases, out = run([many[0]] + dup + many[1:])
check(len(cases) == 8 and all(c["case_name"] != "Copy v. State" for c in cases), f"a merged copy gives its place to the next case: {len(cases)} cases fed (the cap is 8)")

kept, same = T._dedupe_passages([], [])
check(kept == [] and same == {}, "an empty list is fine")
kept, same = T._dedupe_passages([{"text": None, "doc": 1}], [{"source": "none"}])
check(len(kept) == 1, "a result with no text is kept")
T.search = real_search

print()
print("FAILURES:", len(FAILURES))
for f in FAILURES:
    print("  -", f)
sys.exit(1 if FAILURES else 0)
