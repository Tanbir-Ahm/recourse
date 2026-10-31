"""
test_relevance_gate.py -- relevance_gate.py (RELEVANCE_GATE=off|log|on) and its wiring. Offline and free: a stand-in re-ranker, stand-in searches. Run: python -X utf8 test_relevance_gate.py
"""
import contextlib
import io
import os
import sys

import relevance_gate as G
import semantic_retrieval as sr

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


for k in ("RELEVANCE_GATE", "RELEVANCE_FLOOR_STATUTE", "RELEVANCE_FLOOR_JUDGMENT"):
    os.environ.pop(k, None)

S = lambda sec, score=0.43, act="BNSS": {"type": "statute", "act": act, "section_number": sec, "text": f"{sec}. Text of section {sec}.", "score": score}
J = lambda name, score=0.45: {"type": "judgment", "case_name": name, "text": f"Passage of {name}.", "score": score}
SCORES = {"249": 0.407, "303": 0.484, "35": 0.715, "230": 0.289, "Arnesh Kumar": 0.633, "Satishchandra": 0.345}


def fake_rerank(q, docs):
    out = []
    for i, d in enumerate(docs):
        s = next((v for k, v in SCORES.items() if k in d), 0.5)
        out.append({"index": i, "score": s, "document": d})
    return sorted(out, key=lambda x: -x["score"])


def run(statutes, judgments, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = G.apply("a question", statutes, judgments, rerank_fn=kw.pop("rerank_fn", fake_rerank), **kw)
    return r, buf.getvalue()


# ---- off (the default): nothing happens, no call
calls = []
(r, log) = run([S("249")], [J("Arnesh Kumar")], rerank_fn=lambda q, d: calls.append(1) or fake_rerank(q, d))
check(G.mode() == "off" and r == ([S("249")], [J("Arnesh Kumar")]) and not calls and "RELEVANCE_GATE" not in log, "off by default: the lists come back as they were, no re-ranker call, no log line")
os.environ["RELEVANCE_GATE"] = "banana"
check(G.mode() == "off", "an unknown value is off")

# ---- log: scores and writes, keeps everything
os.environ["RELEVANCE_GATE"] = ' "LOG" '
(r, log) = run([S("249"), S("35")], [J("Arnesh Kumar"), J("Satishchandra")])
check(G.mode() == "log" and len(r[0]) == 2 and len(r[1]) == 2 and log.count("RELEVANCE_GATE") == 1 and '"kept": false' in log and '"rerank": 0.407' in log, "log: everything is kept, the line says what 'on' would drop")

# ---- on
os.environ["RELEVANCE_GATE"] = "on"
G.reset()
(r, log) = run([S("249"), S("35"), S("230", 0.435, "BNS")], [J("Arnesh Kumar"), J("Satishchandra")])
check([x["section_number"] for x in r[0]] == ["35"] and [x["case_name"] for x in r[1]] == ["Arnesh Kumar"], f"on: sections below 0.45 and judgments below 0.40 are dropped, the rest kept ({[x['section_number'] for x in r[0]]}, {[x['case_name'] for x in r[1]]})")
check(not G.emptied(), "on: something was kept, so the question is not 'emptied'")
G.reset()
(r, log) = run([S("249"), S("230", 0.435, "BNS")], [J("Satishchandra")])
check(r == ([], []) and G.emptied(), "on: when everything is below the floors the lists are empty and the question is marked emptied (it is then answered from the wider search, not refused)")
G.reset()
check(not G.emptied(), "reset clears the mark")
(r, _) = run([], [])
check(r == ([], []) and not G.emptied(), "nothing to gate: nothing marked")
(r, log) = run([S("249")], [J("Arnesh Kumar")], statutes_trusted=True)
check([x["section_number"] for x in r[0]] == ["249"] and "249" not in log.split('"items"')[1] and [x["case_name"] for x in r[1]] == ["Arnesh Kumar"], "a section the person NAMED is trusted: never scored, never dropped")
(r, _) = run([S("303")], [], rerank_fn=lambda q, d: None)
check(len(r[0]) == 1 and not G.emptied(), "no re-ranker (None): nothing is removed")
(r, _) = run([S("303")], [], rerank_fn=lambda q, d: (_ for _ in ()).throw(RuntimeError("down")))
check(len(r[0]) == 1, "a failure inside leaves the lists as they were")
(r, _) = run([dict(S("303"), text="")], [])
check(len(r[0]) == 1, "a match with no text cannot be scored and is kept")
b = {"index": 0, "score": 0.45}
(r, _) = run([S("1")], [], rerank_fn=lambda q, d: [b])
check(len(r[0]) == 1, "a score exactly at the floor is kept")

# ---- floors from the environment
os.environ["RELEVANCE_FLOOR_STATUTE"] = '"0.6"'
os.environ["RELEVANCE_FLOOR_JUDGMENT"] = "5"
check(G.floors() == (0.6, 0.9), f"floors are read, quotes are harmless, and clamped to 0.9 ({G.floors()})")
os.environ["RELEVANCE_FLOOR_STATUTE"] = "x"
check(G.floors()[0] == G.DEFAULT_STATUTE_FLOOR, "a non-number falls back to the default")
os.environ.pop("RELEVANCE_FLOOR_STATUTE"); os.environ.pop("RELEVANCE_FLOOR_JUDGMENT")

# ---- wired into find_relevant_sections (stand-in searches, stand-in re-ranker)
REC = lambda i, **kw: dict({"type": "statute", "act": "BNSS", "section_number": i, "text": f"{i}. section {i}", "score": 0.43, "key": i, "section": i}, **kw)
orig = (sr.semantic_search, sr.lexical_search, sr.rerank)
try:
    sr.semantic_search = lambda q, top_k=50, _raise_errors=False: [REC("249"), REC("35", score=0.5)]
    sr.lexical_search = lambda q, top_k=50: []
    sr.rerank = lambda q, docs, top_k=None, _raise_errors=False: fake_rerank(q, docs)
    os.environ["RELEVANCE_GATE"] = "off"
    with contextlib.redirect_stdout(io.StringIO()):
        base = sr.find_relevant_sections("what must the prosecution prove")
    os.environ["RELEVANCE_GATE"] = "on"
    G.reset()
    with contextlib.redirect_stdout(io.StringIO()):
        gated = sr.find_relevant_sections("what must the prosecution prove")
    b_secs = sorted(m["section_number"] for m in base.get("matches", []))
    g_secs = sorted(m["section_number"] for m in gated.get("matches", []))
    check(b_secs == ["249", "35"] and g_secs == ["35"], f"find_relevant_sections: off keeps 249 and 35; on keeps only 35 ({b_secs} / {g_secs})")
    sr.semantic_search = lambda q, top_k=50, _raise_errors=False: [REC("249")]
    G.reset()
    with contextlib.redirect_stdout(io.StringIO()):
        none_left = sr.find_relevant_sections("what must the prosecution prove")
    check(none_left.get("state") == "no_match" and G.emptied(), "when the gate removes the only match the state is no_match AND the question is marked emptied")
finally:
    sr.semantic_search, sr.lexical_search, sr.rerank = orig
    os.environ.pop("RELEVANCE_GATE", None)

# ---- the wider-search-only answer is allowed after the gate emptied a question (not otherwise)
import chat_assistant as CA
src = open(CA.__file__, encoding="utf-8").read()
check("relevance_gate.emptied()" in src and "RELEVANCE_GATE_WIDER_ONLY" in src and "relevance_gate.reset()" in src, "chat_assistant resets the mark per question and lets the wider-search-only answer run after the gate emptied one")

# ---- the prompts carry the rule
check("cite a section only if it answers the question" in CA._V3_SHAPE.lower() and "Cite a section only if it answers the question" in CA._V3_LAWYER_INCLUDE and "how a trial opens" in CA._V3_LAWYER_INCLUDE, "both v3 prompts say: a section is not relevant because it was supplied")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
