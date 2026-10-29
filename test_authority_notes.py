"""
test_authority_notes.py -- authority_notes.py and its use in sci_search_tier.feed_block (2026-10-29: the search service says which judgments the retrieved judgments name).
Offline and free: the search service is replaced by a function that returns fixed results; no model, no network. Run: python -X utf8 test_authority_notes.py
"""
import contextlib
import hashlib
import io
import json
import os
import sys

os.environ["SCI_SEARCH_MODE"] = "feed"
os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
os.environ.pop("PASSAGE_NOTES", None)

import answer_view
import authority_notes as AN
import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 1. facts(): only well-formed facts count
GOOD = {"named_by_collection": 446, "named_by_retrieved": 22, "retrieved": 59, "pointer": True, "raw_score": 0.8}
f = AN.facts({"authority": GOOD})
check(f == {"collection": 446, "retrieved_by": 22, "retrieved": 59, "pointer": True}, f"well-formed facts are read ({f})")
check(AN.facts({}) is None and AN.facts(None) is None and AN.facts("x") is None and AN.facts({"authority": None}) is None and AN.facts({"authority": "446"}) is None, "no field, or a field that is not an object: nothing")
bad = [dict(GOOD, named_by_collection="446"), dict(GOOD, named_by_retrieved=-1), dict(GOOD, named_by_retrieved=True), dict(GOOD, retrieved=0), dict(GOOD, named_by_retrieved=60), dict(GOOD, named_by_retrieved=None),
       {k: v for k, v in GOOD.items() if k != "retrieved"}, dict(GOOD, named_by_collection=4.5)]
check(all(AN.facts({"authority": b}) is None for b in bad), "text, negative, boolean, missing, fractional numbers and more judgments naming it than were retrieved are all refused")
check(AN.facts({"authority": dict(GOOD, pointer="yes")})["pointer"] is False and AN.facts({"authority": {k: v for k, v in GOOD.items() if k != "pointer"}})["pointer"] is False, "'pointer' must be literally true: a string or a missing field is not a pointer")
check(AN.facts({"authority": dict(GOOD, named_by_collection=3)})["collection"] == 22, "the collection count is never shown as smaller than the retrieved count")
check(AN.is_pointer(f) and not AN.is_pointer(dict(f, pointer=False)) and not AN.is_pointer(dict(f, retrieved_by=1)) and not AN.is_pointer(None), "only a result the service marks as a pointer, named by at least two retrieved judgments, is one")

# ---------------------------------------------------------------- 2. the words
line, note = AN.prompt_line(f), AN.page_note(f)
check("22 of the 59 judgments" in line and "about 446 judgments" in line and "NOT a statement that the case is good law" in line and line.startswith("\n[Named by other judgments"), f"the prompt line gives the counts and says it is not a statement that the case is good law ({line[:160]!r})")
check("22 of the 59 judgments" in note and "about 446 in the whole collection" in note and "does not say that the case is still good law" in note and "automatic count" in note and note.startswith("Named by other judgments:"), "the page sentence gives the counts, calls them an automatic count, and says it does not say the case is good law")
check(len(note) < 330, f"the page sentence is short enough for a row of the table of authorities ({len(note)} characters)")
check(AN.prompt_line(dict(f, pointer=False)) == "" and AN.page_note(None) == "" and "about 1,234 in the whole collection" in AN.page_note(dict(f, collection=1234)), "a result that is not a pointer gets nothing; thousands are separated")
check("never repeat its numbers" in AN.INSTRUCTION and "never call the case settled or good law" in AN.INSTRUCTION and "describe only what the passage itself says" in AN.INSTRUCTION, "the instruction forbids repeating the numbers and calling the case settled, and keeps the model to what the passage says")
check(AN.PASSAGE_CHARS > T.FEED_PASSAGE_CHARS, "a pointer passage is shown longer than an ordinary one")
words = " ".join([line, note, AN.INSTRUCTION]).lower()
check(words.count("good law") == 3 and all(("not a statement that the case is good law" in w or "does not say that the case is still good law" in w or "or good law" in w) for w in [line.lower(), note.lower(), AN.INSTRUCTION.lower()]),
      "'good law' appears only to deny it")

# ---------------------------------------------------------------- 3. nothing changes while the service sends no authority facts (the block and the page list are what they were before)
LONG = ("The prosecution must establish each circumstance by cogent and reliable evidence; the circumstances must be of a conclusive nature and tendency and must exclude every hypothesis but the one proposed to be proved. " * 9)
BASE = [
    {"rank": 1, "doc": 11, "case_name": "Alpha Kumar v. State of Bihar", "date": "2015-05-03", "paragraph": "12", "link": "https://x/11.pdf", "link_kind": "open_bucket_pdf", "text": LONG, "name_to_review": False, "citations": {}, "score": 0.9, "passage_type": "reasoning"},
    {"rank": 2, "doc": 12, "case_name": "Beta Singh v. State of Punjab", "date": "2018-07-02", "paragraph": "9", "link": "https://x/12.pdf", "link_kind": "open_bucket_pdf", "text": "Short passage about circumstantial evidence.", "name_to_review": False, "citations": {}, "score": 0.8, "passage_type": "reasoning"},
    {"rank": 3, "doc": 13, "case_name": "Gamma Devi v. State of Kerala", "date": "2020-01-10", "paragraph": "4", "link": "https://x/13.pdf", "link_kind": "open_bucket_pdf", "text": LONG[:700], "name_to_review": False, "citations": {}, "score": 0.7, "passage_type": "facts"},
    {"rank": 4, "doc": 11, "case_name": "Alpha Kumar v. State of Bihar", "date": "2015-05-03", "paragraph": "14", "link": "https://x/11.pdf", "link_kind": "open_bucket_pdf", "text": "again", "name_to_review": False, "citations": {}, "score": 0.6, "passage_type": "reasoning"},
]
# the two hashes were taken from the code as it was BEFORE authority_notes existed (2026-10-29), for exactly this scenario
BLOCK_SHA, CASES_SHA = "1fc213652d1bd600033c6ef6b624ae84cbd012e8de2a9dffd89966b54ec4ce47", "ee722b7b2a79d2846c7fcb6e865c1be986d90f2916817cf7830d9caf8e39798e"
STATE = {"res": BASE}


def fake_search(question, timeout=None, k=10, label="x"):
    return {"ok": True, "results": json.loads(json.dumps(STATE["res"])), "as_of": "2026-07-13", "index_commit": "abc"}


T.search = fake_search
Q = "Can a person be convicted on circumstantial evidence alone? What must the prosecution prove?"


def block_for(results, question=Q):
    STATE["res"] = results
    T.reset()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        b = T.feed_block(question)
    return b, [dict(c) for c in T._LOCAL.cases], buf.getvalue()


b0, c0, log0 = block_for(BASE)
check(sha(b0) == BLOCK_SHA and sha(json.dumps(c0, sort_keys=True)) == CASES_SHA, "no authority facts: the block and the page list are byte for byte what the code produced before this change")
check("SCI_FEED_AUTHORITY" not in log0 and "Named by other judgments" not in b0 and AN.INSTRUCTION not in b0, "no authority facts: no log line, no authority line and no instruction")
with_junk = [dict(r, authority=a) for r, a in zip(BASE, ["446", {"named_by_collection": "x"}, {"named_by_collection": 5, "named_by_retrieved": 9, "retrieved": 3, "pointer": True}, [1, 2]])]
b1, c1, log1 = block_for(with_junk)
check(b1 == b0 and json.dumps(c1, sort_keys=True) == json.dumps(c0, sort_keys=True), "malformed authority fields are ignored: the same block, the same list")
not_ptr = [dict(r, authority={"named_by_collection": 900, "named_by_retrieved": 0, "retrieved": 59, "pointer": False, "raw_score": 0.9}) for r in BASE]
b2, c2, _ = block_for(not_ptr)
check(b2 == b0 and json.dumps(c2, sort_keys=True) == json.dumps(c0, sort_keys=True), "facts on results that are not pointers (even a judgment named by 900 others) change nothing: the line and the longer cut are for the court's own pointers only")

# ---------------------------------------------------------------- 4. a pointer passage
SARDA_TXT = ("It is well settled that the prosecution must stand or fall on its own legs and it cannot derive any strength from the weakness of the defence. " * 8).strip() + " END-OF-SARDA-PASSAGE."
HANU_TXT = ("In cases where the evidence is of a circumstantial nature, the circumstances from which the conclusion of guilt is to be drawn should in the first instance be fully established. " * 5).strip()
ptr = lambda n, m, c: {"named_by_collection": c, "named_by_retrieved": n, "retrieved": m, "pointer": True, "raw_score": 0.8}
SARDA = {"rank": 1, "doc": 9517, "case_name": "Sharad Birdhi Chand Sarda v. State of Maharashtra", "date": "1984-07-17", "paragraph": None, "link": "https://x/9517.pdf", "link_kind": "court_archive_pdf",
         "text": SARDA_TXT, "name_to_review": False, "citations": {}, "authority": ptr(22, 59, 446)}
SARDA2 = dict(SARDA, rank=2, text="a second passage of the same judgment " * 5)
HANU = {"rank": 3, "doc": 1154, "case_name": "Hanumant v. The State of Madhya Pradesh", "date": "1952-01-23", "paragraph": "10", "link": "https://x/1154.pdf", "link_kind": "court_archive_pdf",
        "text": HANU_TXT, "name_to_review": False, "citations": {}, "authority": ptr(7, 59, 82)}
OTHER = [dict(r, rank=4 + i, authority={"named_by_collection": 0, "named_by_retrieved": 0, "retrieved": 59, "pointer": False, "raw_score": 0.9}) for i, r in enumerate(BASE[:3])]
assert len(SARDA_TXT) > 1000 and len(SARDA_TXT) < AN.PASSAGE_CHARS - 20
b3, c3, log3 = block_for([SARDA, SARDA2, HANU] + OTHER)
check(len(c3) == 5 and [c["case_name"] for c in c3][:2] == ["Sharad Birdhi Chand Sarda v. State of Maharashtra", "Hanumant v. The State of Madhya Pradesh"], f"the page list holds the pointer cases first, one passage each ({[c['case_name'][:20] for c in c3]})")
check("END-OF-SARDA-PASSAGE" in b3, "a pointer passage of about 1,200 characters reaches the model whole (an ordinary passage is cut at about 900)")
alpha = b3[b3.index("Alpha Kumar"):]
check(("circumstances must be of a conclusive nature" in alpha) and alpha.count("...") >= 1 and len(alpha.split("[WIDER SEARCH")[0]) < 1400, "an ordinary passage is still cut at the old length")
check(b3.count("[Named by other judgments") == 2 and "22 of the 59 judgments" in b3 and "7 of the 59 judgments" in b3 and "about 446 judgments" in b3 and "about 82 judgments" in b3, "each pointer passage carries its own line with its own counts, and no other passage does")
check(b3.count(AN.INSTRUCTION) == 1 and b3.index(AN.INSTRUCTION) < b3.index("[WIDER SEARCH"), "the instruction on how to use the line appears once, before the passages")
check(b3.startswith(T.FEED_INSTRUCTION), "the feed instruction itself is untouched")
sarda_part = b3[b3.index("Sharad Birdhi Chand Sarda"):b3.index("Hanumant")]
check(sarda_part.index("END-OF-SARDA-PASSAGE") < sarda_part.index("[Named by other judgments"), "the line sits under the passage")
check("a second passage of the same judgment" not in b3, "still one passage per case")
sc = c3[0]
check("Named by other judgments" in sc["passage_note"] and "22 of the 59 judgments" in sc["passage_note"] and sc["authority"] == {"named_by_retrieved": 22, "retrieved": 59, "named_by_collection": 446}, "the page list carries the sentence and the counts for a pointer case")
check(all(not c.get("passage_note") and "authority" not in c for c in c3[2:]), "the other cases have no note and no authority field")
check("SCI_FEED_AUTHORITY" in log3 and json.loads(log3.split("SCI_FEED_AUTHORITY ", 1)[1].splitlines()[0])["pointers"][0] == {"case": "Sharad Birdhi Chand Sarda v. State of Maharashtra", "named_by_retrieved": 22, "retrieved": 59, "named_by_collection": 446},
      "the log line names the pointer passages that reached the prompt and their counts")
# the numbers are for the page; the label rule of the wider search is untouched
check(b3.count(T.LABEL) >= 1 and "NOT INDEPENDENTLY VERIFIED: Sharad Birdhi Chand Sarda" in b3, "the wider-search heading is still on a pointer passage")

# ---------------------------------------------------------------- 5. the register scan reads exactly what the model is shown
FILL = "The court considered the circumstances proved by the prosecution and the chain of evidence. " * 10          # about 900 characters
NAMING = FILL + "Reference was made to Raj Deo Sharma (II) v. State of Bihar, (1999) 7 SCC 604, where this Court laid down outer time limits for completing criminal trials."
assert 900 < len(FILL) < 1000
plain_case = {"rank": 1, "doc": 31, "case_name": "Delta Rao v. State of Goa", "date": "2012-03-01", "paragraph": "6", "link": "https://x/31.pdf", "link_kind": "open_bucket_pdf", "text": NAMING, "name_to_review": False, "citations": {}}
bp, cp, _ = block_for([plain_case])
check("REGISTER FACT: Raj Deo Sharma" not in bp and "Raj Deo Sharma" not in bp.split("[WIDER SEARCH")[1], "an ordinary passage that names a register case only after the cut: not shown, so no line is attached (as before)")
bq, cq, _ = block_for([dict(plain_case, authority=ptr(5, 40, 60))])
check("Raj Deo Sharma" in bq and "REGISTER FACT: Raj Deo Sharma v. The State of Bihar (1999) was overruled by P. Ramachandra Rao" in bq, "a pointer passage shows the longer text AND the register line for a case named in it: the scan reads what the model is shown")
check(cq[0]["names_register_note"] and "overruled by P. Ramachandra Rao" in cq[0]["names_register_note"], "the page list says that this pointer passage names a register case")

# ---------------------------------------------------------------- 5b. a case on the Overruled Register is never presented as "read this first"
RDS = {"rank": 1, "doc": 41, "case_name": "Raj Deo Sharma v. The State of Bihar", "date": "1999-05-03", "paragraph": "5", "link": "https://x/41.pdf", "link_kind": "court_archive_pdf", "name_to_review": False,
       "citations": {"air": ["1999 AIR 2000"], "scr": ["1999 SCR (3) 1"]}, "text": ("Time limits for the completion of criminal trials were laid down. " * 10).strip() + " END-OF-RDS-PASSAGE.", "authority": ptr(30, 59, 300)}
br, cr, lr = block_for([RDS])
check("REGISTER FACT: Raj Deo Sharma v. The State of Bihar (1999) was overruled by P. Ramachandra Rao" in br, "the register still attaches its fact to a case that the service marks as a pointer")
check("[Named by other judgments" not in br and AN.INSTRUCTION not in br and "SCI_FEED_AUTHORITY" not in lr and "END-OF-RDS-PASSAGE" in br, "...but no 'read this passage first' line, no instruction and no log line for it (its passage is not lengthened either: the text is short enough to appear whole here)")
check("authority" not in cr[0] and not cr[0].get("passage_note"), "...and the page list carries no authority sentence for it")
long_rds = dict(RDS, text=("Time limits for the completion of criminal trials were laid down. " * 30).strip() + " END-OF-RDS-PASSAGE.")
bl, cl, _ = block_for([long_rds])
check("END-OF-RDS-PASSAGE" not in bl, "a register-listed pointer passage is cut at the ordinary length, not the longer one")
bm, cm, lm = block_for([RDS, SARDA])
check(bm.count("[Named by other judgments") == 1 and bm.count(AN.INSTRUCTION) == 1 and bm.index("NOT INDEPENDENTLY VERIFIED: Sharad") < bm.index("NOT INDEPENDENTLY VERIFIED: Raj Deo Sharma"), "with a register case and an unflagged pointer in the same feed, only the unflagged one gets the line, and the instruction appears once")
check([c["case_name"] for c in cm][-1].startswith("Raj Deo Sharma") and "authority" in cm[0], "the register case still goes last in the list")

# ---------------------------------------------------------------- 6. a pointer passage in someone's own voice keeps its voice note, and the authority sentence is added to it
os.environ["PASSAGE_NOTES"] = "on"
ONE = dict(SARDA, text="I am of the opinion that the circumstances must be fully established before a conviction can rest on them. " * 4)
b6, c6, _ = block_for([ONE])
check("Note by code" in b6 and "[Named by other judgments" in b6 and "ONE judge" in b6, "with PASSAGE_NOTES=on a pointer passage carries both the voice note and the authority line")
check(c6[0]["passage_note"].startswith("This passage is one judge's own opinion") and c6[0]["passage_note"].endswith("so this does not say that the case is still good law).") and "Named by other judgments" in c6[0]["passage_note"], f"the page sentence for the voice comes first, then the authority sentence ({c6[0]['passage_note'][:80]!r})")
os.environ.pop("PASSAGE_NOTES", None)

# ---------------------------------------------------------------- 7. the note reaches the page and the exports
block_for([SARDA, HANU] + OTHER)
result = {"state": "single_match", "response_text": "The Supreme Court in Sharad Birdhi Chand Sarda v. State of Maharashtra said the prosecution must stand or fall on its own legs.", "matches": []}
with contextlib.redirect_stdout(io.StringIO()):
    out = T.attach(Q, result, background=False)
check(out.get("sci_related_judgments") and out["sci_related_judgments"][0]["passage_note"] and "Named by other judgments" in out["sci_related_judgments"][0]["passage_note"], "attach() hands the note to the answer result")
view = answer_view.build(out)
items = ((view or {}).get("sci_related") or {}).get("items") or []
check(items and "Named by other judgments" in (items[0].get("passage_note") or "") and not items[-1].get("passage_note"), "the view the page and the Next.js front end draw carries the note for the pointer case only")
import authorities_table
tab = authorities_table.build([], [], [], out["sci_related_judgments"], lambda name, year, cit: {"source": "none", "note": None})
wider = {r["case"]: r for r in tab["wider"]}
check("Reading note: Named by other judgments: 22 of the 59" in (wider["Sharad Birdhi Chand Sarda v. State of Maharashtra"]["status"] or "") and "Reading note" not in (wider["Alpha Kumar v. State of Bihar"]["status"] or ""), "the table of authorities carries the note after 'Reading note:' for the pointer row only")
import answer_export
exp_text = json.dumps(answer_view.build(out), default=str)
check(exp_text.count("Named by other judgments") >= 2, "the note is part of the view that the PDF and Word export are built from")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
