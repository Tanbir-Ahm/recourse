"""
test_evidence_companions.py -- evidence_companions.py (EVIDENCE_COMPANIONS=off|on) and its two hooks.  Offline and free: stand-in searches.  Run: python -X utf8 test_evidence_companions.py
"""
import contextlib
import io
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


for k in ("EVIDENCE_COMPANIONS", "ACT_SHELF"):
    os.environ.pop(k, None)

import evidence_companions as C  # noqa: E402

Q = "Can a person be convicted on circumstantial evidence alone? What must the prosecution prove?"
Q2 = "What is the punishment for theft?"
Q3 = "My landlord is not returning the deposit of my flat after a divorce settlement on circumstantial evidence of cruelty"

check(C.mode() == "off" and C.topic(Q) is None, "off by default: no topic for a circumstantial-evidence question")
check(C.shelf_matches(Q) == [] and C.extra_queries(Q) == [], "off by default: no shelf sections, no extra queries")
found = {"results": [{"doc": "a", "case_name": "A v B"}]}
check(C.merge(found, Q, lambda q: (_ for _ in ()).throw(AssertionError("must not search"))) is found, "off by default: merge returns the same answer without searching")

os.environ["EVIDENCE_COMPANIONS"] = "on"
check(C.mode() == "on" and C.topic(Q) == "circumstantial", "on: a circumstantial-evidence question has the topic")
check(C.topic(Q2) is None, "on: a question on another subject has none")
check([t for t, _ in C.extra_queries(Q)] == ["last_seen_together", "false_explanation", "recovery"], "on: three extra queries (last seen together; false explanation; recovery)")
check(C.shelf_matches(Q) == [], "on, ACT_SHELF off: no shelf sections")

os.environ["ACT_SHELF"] = "on"
import act_shelf  # noqa: E402

ms = C.shelf_matches(Q)
check([f"{m['act']}{m['section_number']}" for m in ms] == ["IEA106", "BSA109", "IEA27", "BSA23", "IEA8", "BSA6"], "on, shelf on: sections EA 106, 27, 8 and BSA 109, 23, 6, in that order")
check(all(m["source"] == "act_shelf" and m["retrieval"] == "companion" and m.get("text") for m in ms), "each is an Act-shelf statute match with retrieval 'companion' and its text")
check("section 109" in (ms[0].get("context_note") or "") and "Evidence Act" in (ms[1].get("context_note") or ""), "each carries the counterpart note (EA 106 -> BSA 109; BSA 109 -> the Evidence Act)")
check(C.shelf_matches(Q, already={"act:IEA:106"})[0]["section_number"] == "109", "a section the question already has is not handed over twice")

# all or none: a missing Act gives nothing
real_load = act_shelf.load
act_shelf.load = lambda *a, **k: {"acts": {"evidence_act_1872": real_load()["acts"]["evidence_act_1872"]}, "problems": []}
check(C.shelf_matches(Q) == [], "all or none: with one Act of the pair missing nothing is handed over")
act_shelf.load = real_load

# merge with a stand-in search
calls = []


def fake(q):
    calls.append(q)
    return {"results": [{"doc": "x" + str(len(calls)), "case_name": f"Case {len(calls)} v. State", "paragraph": "5"}, {"doc": "y" + str(len(calls)), "case_name": f"Other {len(calls)} v. State"}]}


base = {"results": [{"doc": f"d{i}", "case_name": f"Main {i} v. State"} for i in range(6)]}
with contextlib.redirect_stdout(io.StringIO()) as buf:
    out = C.merge(base, Q, fake)
docs = [r["doc"] for r in out["results"]]
check(len(calls) == 3 and docs[:3] == ["d0", "d1", "d2"] and docs[3:6] == ["x1", "x2", "x3"] and docs[6:] == ["d3", "d4", "d5"], "merge: one new result from each of the three queries goes after the first three results")
check(all(r.get("companion") for r in out["results"][3:6]) and "EVIDENCE_COMPANIONS_SEARCH" in buf.getvalue(), "merge: the added results are tagged and one log line is written")
check(len(base["results"]) == 6, "merge: the original answer is not changed")
dup = {"results": [{"doc": "x1", "case_name": "Main v. State"}, {"doc": "x2", "case_name": "Main2"}, {"doc": "x3", "case_name": "Main3"}]}
calls.clear()
out2 = C.merge(dup, Q, fake)
check(sum(1 for r in out2["results"] if r["doc"] == "x1") == 1, "merge: a judgment already among the results is not added again")
check(C.merge(base, Q, lambda q: None) is base, "merge: a failing search leaves the answer as it was")
check(C.merge(None, Q, fake) is None and C.merge({"results": 5}, Q, fake) == {"results": 5}, "merge: a missing or malformed answer is returned unchanged")
check(C.merge(base, Q2, fake) is base, "merge: another subject adds nothing")

# the hook in chat_assistant
import chat_assistant as CA  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    got = CA._act_shelf_matches(Q, Q)
check(len(got) == 6 and all(m["retrieval"] == "companion" for m in got), "chat_assistant: a circumstantial-evidence question that names no Act gets the six companion sections")
os.environ["EVIDENCE_COMPANIONS"] = "off"
check(CA._act_shelf_matches(Q, Q) == [], "chat_assistant: switch off -> nothing, as before")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sci_search_tier.py"), encoding="utf-8").read()
check("evidence_companions.merge(found, question" in src, "sci_search_tier.feed_block calls the merge after the main search")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")
