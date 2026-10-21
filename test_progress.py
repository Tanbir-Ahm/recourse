"""
test_progress.py -- live steps (progress.py and the emit points in chat_assistant.py; website design WEBSITE_DESIGN.md section 3, step A1.0). Free and offline: the model and the embedding call are stubs.
Proves: (1) the module: no listener = nothing happens, one listener per thread, details are cleaned so no text can slip into a step, a failing listener never raises; (2) the engine: with a listener the steps come
in the order the engine passes them, carry counts and Act names and never the question; with NO listener the result is byte for byte the result with one (the steps change nothing), and no extra work is done.
Run: python -X utf8 test_progress.py
"""
import contextlib
import io
import json
import os
import sys
import threading
import types

import numpy as np

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("ACT_SHELF", "ACT_DIRECTORY", "ACT_DETECT", "CHAT_MODE", "SECTION_RULE", "SECTION_XREF", "REGISTER_HOOKS", "RESPONSE_STYLE", "SCOPE_GATE", "SCI_SEARCH_MODE", "ANCHORS", "GROUNDING_CHECKS", "PASSAGE_NOTES"):
    os.environ.pop(_v, None)

import act_shelf as S
import chat_assistant as CA
import progress as P

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---------------------------------------------------------------- the module
got = []
check(P.active() is False, "no listener: active() is False")
P.emit("scope", category="in_scope")
check(got == [], "no listener: emit() does nothing")
P.set_listener(lambda step, d: got.append((step, d)))
check(P.active() is True, "listener set: active() is True")
P.emit("acts", names=["Prevention of Corruption Act, 1988", None, {"x": 1}, ["nested"]], n=3, flag=True, text="x" * 500, obj={"passage": "secret"}, miss=None)
step, d = got[-1]
check(step == "acts" and d["names"] == ["Prevention of Corruption Act, 1988", None], f"a list keeps only plain items ({d['names']})")
check(d["n"] == 3 and d["flag"] is True and d["miss"] is None, "numbers, booleans and None pass through")
check(len(d["text"]) == 80, "a long string is cut to 80 characters")
check(d["obj"] is None, "a dict (a passage, a result) is dropped to None: no text can ride along")
P.emit("many", items=list(range(50)))
check(len(got[-1][1]["items"]) == 10, "a long list is cut to 10 items")


def bad(step, d):
    raise RuntimeError("listener failed")


P.set_listener(bad)
try:
    P.emit("scope")
    ok = True
except Exception:  # noqa: BLE001
    ok = False
check(ok, "a failing listener never raises")
P.clear()
check(P.active() is False, "clear() removes the listener")

# one listener per thread
seen = {"a": [], "b": []}


def worker(name):
    P.set_listener(lambda step, d, n=name: seen[n].append(step))
    for _ in range(50):
        P.emit(name)
    P.clear()


ts = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b")]
[t.start() for t in ts]
[t.join() for t in ts]
check(seen["a"] == ["a"] * 50 and seen["b"] == ["b"] * 50, "two threads, two listeners: each hears only its own steps")
check(P.active() is False, "the main thread was not affected by the others' listeners")

# ---------------------------------------------------------------- the engine, with a stub model
def boom(text):
    raise AssertionError("the test reached the real Voyage call")


S._embed_query = boom
EMB = json.load(open(os.path.join(S.SHELF_DIR, "shelf_embeddings.json"), encoding="utf-8"))
VEC = {r["chunk_id"]: np.array(r["embedding"], dtype=float) for r in EMB["records"]}
sent = {}
REPLY = {"text": "Section 17 of the Prevention of Corruption Act, 1988 needs approval before an investigation. Please speak to a lawyer."}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=REPLY["text"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
CA.classify_scope = lambda q: ("in_scope", "corruption", None)
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "no_match"}
CA._fetch_pilot_related_judgments = lambda *a, **k: []
import answer_cache
answer_cache.get_cached = lambda m: None
answer_cache.record_candidate = lambda *a, **k: None
CANARY = "my brother Zebulon Quillfeather was held in Hoskote"
Q = f"Can a disproportionate assets case under PC act be filed without section 17 approval? {CANARY}"


def run(question, listener):
    S._embed_query = lambda text: VEC["act:PCACT:17"]
    if listener:
        P.set_listener(listener)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return CA.answer_question(question)
    finally:
        S._embed_query = boom
        P.clear()


os.environ["ACT_SHELF"] = "on"
steps = []
r_on = run(Q, lambda step, d: steps.append((step, d)))
ids = [s for s, _ in steps]
check(r_on.get("state") == "single_match", f"the run produced an answer ({r_on.get('state')})")
check(ids[0] == "scope" and steps[0][1] == {"category": "in_scope"}, f"first step is the scope check ({steps[0]})")
check("acts" in ids and "sections" in ids and "library" in ids and "write" in ids and "register" in ids and "checks" in ids, f"the steps the engine passed are all there ({ids})")
order = [ids.index(x) for x in ("scope", "acts", "sections", "library", "write", "register", "checks")]
check(order == sorted(order), f"...in the order the engine passes them ({ids})")
acts = dict(steps)["acts"]
check(acts["names"] == ["Prevention of Corruption Act, 1988"], f"'acts' names the Act the Directory found ({acts})")
sec = dict(steps)["sections"]
check(any(i.endswith("s.17") for i in sec["items"]), f"'sections' lists the shelf section that reached the material ({sec})")
blob = json.dumps(steps)
check(CANARY not in blob and "Zebulon" not in blob and "Hoskote" not in blob, "no step carries any word of the question's own facts")
check(REPLY["text"][:40] not in blob and "needs approval before an investigation" not in blob, "no step carries any answer text")
check(all(isinstance(v, (bool, int, float, str, list, type(None))) for _, d in steps for v in d.values()), "every detail is a plain value")

# with no listener: the same result, and the emit helpers do no work
calls = {"acts": 0}
_orig = CA._acts_named
CA._acts_named = lambda q: (calls.__setitem__("acts", calls["acts"] + 1) or _orig(q))
r_off = run(Q, None)
n_off = calls["acts"]
steps2 = []
calls["acts"] = 0
r_on2 = run(Q, lambda step, d: steps2.append(step))
n_on = calls["acts"]
CA._acts_named = _orig
check(json.dumps(r_off, sort_keys=True, default=str) == json.dumps(r_on2, sort_keys=True, default=str), "the result is byte for byte the same with and without a listener (the steps change nothing)")
check(n_on == n_off + 1, f"without a listener the 'acts' step does no extra work ({n_off} lookups) and with one it adds a single lookup ({n_on})")

# a refusal reports its scope and the register look-up (the engine runs that for every result), but has no 'write', 'library' or 'checks' step
CA.classify_scope = lambda q: ("unrelated", "x", None)
steps3 = []
r3 = run("What is the capital of France?", lambda step, d: steps3.append((step, d)))
check(r3.get("state") == "unrelated" and [s for s, _ in steps3] == ["scope", "register"] and steps3[0][1] == {"category": "unrelated"}, f"an unrelated question: 'scope' then the register look-up, nothing else ({steps3})")
CA.classify_scope = lambda q: (None, "", None)
steps4 = []
r4 = run("anything", lambda step, d: steps4.append((step, d)))
check(r4.get("state") == "classifier_unavailable" and steps4[0] == ("scope", {"category": "unavailable"}) and [s for s, _ in steps4] == ["scope", "register"], f"the classifier down: 'scope' says unavailable ({steps4})")

# a listener that fails changes nothing about the answer
CA.classify_scope = lambda q: ("in_scope", "corruption", None)
r_bad = run(Q, bad)
check(json.dumps(r_bad, sort_keys=True, default=str) == json.dumps(r_off, sort_keys=True, default=str), "a listener that raises on every step: the answer is the same")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
