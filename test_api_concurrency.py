"""
test_api_concurrency.py -- the REAL answer engine behind the API, many questions at once (website design WEBSITE_DESIGN.md section 5.2, step A1). Free and offline: the model and the embedding call are stubs
(slowed by random pauses so the questions really overlap); everything else is the engine as it runs on the site.
The engine keeps per-question state in threading.local (cost log, audience, grounding notes, Act cache, search tier, open-topic note). The API is safe only if (1) a question that runs alone in a fresh thread, (2) the
same questions one after another on ONE reused worker thread, and (3) the same questions in parallel on many threads (through the adapter and through HTTP) all give the SAME result, the same cost and the same live steps.
Questions alternate between "names the Prevention of Corruption Act, section 17" and a plain one, and between layman and lawyer, so any leak of Act, audience, notice, cost or steps would show.
Run: python -X utf8 test_api_concurrency.py
"""
import concurrent.futures
import contextlib
import io
import json
import os
import random
import re
import sys
import threading
import time
import types

import numpy as np

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("ACT_SHELF", "ACT_DIRECTORY", "ACT_DETECT", "CHAT_MODE", "SECTION_RULE", "SECTION_XREF", "REGISTER_HOOKS", "RESPONSE_STYLE", "SCOPE_GATE", "SCI_SEARCH_MODE", "ANCHORS", "GROUNDING_CHECKS",
           "PASSAGE_NOTES", "COST_STATE_FILE", "DAILY_BUDGET_INR", "API_ACCESS_TOKEN"):
    os.environ.pop(_v, None)
os.environ["RESPONSE_STYLE"] = "v3"
os.environ["ACT_SHELF"] = "on"
os.environ["GROUNDING_CHECKS"] = "warn"

from fastapi.testclient import TestClient

import act_shelf as S
import chat_assistant as CA
from api import engine_adapter
from api.main import app

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


EMB = json.load(open(os.path.join(S.SHELF_DIR, "shelf_embeddings.json"), encoding="utf-8"))
VEC = {r["chunk_id"]: np.array(r["embedding"], dtype=float) for r in EMB["records"]}
S._embed_query = lambda text: VEC["act:PCACT:17"]
random.seed(7)


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        p = c if isinstance(c, str) else json.dumps(c)
        marks = re.findall(r"ZQ(\d+)Z", p)
        n = int(marks[0]) if marks else 0
        time.sleep(random.uniform(0.0, 0.04))
        voice = "NOTE" if "## Voice and shape (the Research Note)" in p else "ADVISER"
        text = f"Answer for ZQ{n}Z in the {voice} voice. The court may adjourn only for recorded reasons."
        if voice == "NOTE":
            text = "**Bottom line**\n\n" + text
        time.sleep(random.uniform(0.0, 0.04))
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                                     usage=types.SimpleNamespace(input_tokens=1000 * (n + 1), output_tokens=100 * (n + 1)))


CA.client = types.SimpleNamespace(messages=_Msgs())
CA.classify_scope = lambda q: ("in_scope", "x", None)
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "single_match", "matches": [
    {"type": "statute", "act": "BNSS", "section_number": "346", "text": "346. Postponement and adjournment of proceedings.", "source": "semantic"}]}
CA._inject_definitional_companions = lambda m: m
CA._fetch_pilot_related_judgments = lambda *a, **k: []
import answer_cache
answer_cache.get_cached = lambda m: None
answer_cache.record_candidate = lambda *a, **k: None

N = 16


def question(i):
    if i % 2:
        return f"Can a disproportionate assets case under PC act be filed without section 17 approval? ZQ{i}Z"
    return f"What happens at a remand hearing before a magistrate? ZQ{i}Z"


def audience(i):
    return "lawyer" if i % 4 in (2, 3) else "layman"


def run_one(i, on_step=None):
    """The adapter's work(), in the calling thread. Returns (result, cost, steps)."""
    got = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf) if threading.current_thread() is threading.main_thread() else contextlib.nullcontext():
        out = engine_adapter.work(question(i), audience(i), lambda s, d: got.append((s, d)))
    return out["result"], out["cost_inr"], got


def norm(x):
    return json.dumps(x, sort_keys=True, default=str)


# (1) each question alone, in a fresh thread
BASE = {}
for i in range(N):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as one:
        BASE[i] = one.submit(run_one, i).result()
r5, r6 = BASE[5][0], BASE[6][0]
check(all(BASE[i][0].get("state") == "single_match" for i in range(N)), "baseline: every question produced an answer")
check(all(f"ZQ{i}Z" in BASE[i][0]["response_text"] for i in range(N)), "baseline: each answer is the one made for its own question")
check(r5.get("act_notice") and not BASE[4][0].get("act_notice"), "baseline: the Act question carries the Act notice, the plain one does not")
check(r6.get("audience") == "lawyer" and BASE[0][0].get("audience") == "layman" and "NOTE" in r6["response_text"] and "ADVISER" in BASE[0][0]["response_text"], "baseline: lawyer and layman get their own voices")
check(BASE[9][1] is not None and len({BASE[i][1] for i in range(N)}) > 1 or all(BASE[i][1] == 0 for i in range(N)), f"baseline: cost is recorded per question ({[BASE[i][1] for i in range(4)]})")
steps_ids = {i: [s for s, _ in BASE[i][2]] for i in range(N)}
check("acts" in steps_ids[1] and "sections" in steps_ids[1] and "sections" not in steps_ids[0], f"baseline: the 'sections' step appears only for a question that names the Act ({steps_ids[1]} / {steps_ids[0]})")

# (2) the same questions on ONE reused worker thread, in an order that alternates Act / plain / layman / lawyer
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as one:
    reused = {i: one.submit(run_one, i).result() for i in range(N)}
bad = [i for i in range(N) if norm(reused[i][0]) != norm(BASE[i][0]) or reused[i][1] != BASE[i][1] or norm(reused[i][2]) != norm(BASE[i][2])]
check(not bad, f"one reused worker thread: every result, cost and step list equals the fresh-thread one (differences at {bad})")

# (3) in parallel through the adapter's runner
runner = engine_adapter.Runner(8, 16)
futs = {}
for i in random.sample(range(N), N):
    futs[i] = runner.submit(run_one, i)
par = {i: f.result(timeout=120) for i, f in futs.items()}
bad = [i for i in range(N) if norm(par[i][0]) != norm(BASE[i][0])]
check(not bad, f"{N} questions in parallel on 8 threads: every result equals its fresh-thread result (differences at {bad})")
bad = [i for i in range(N) if par[i][1] != BASE[i][1]]
check(not bad, f"...and every cost equals its own (a leak of cost between questions would show here; differences at {bad})")
bad = [i for i in range(N) if norm(par[i][2]) != norm(BASE[i][2])]
check(not bad, f"...and every live step list equals its own (differences at {bad})")
check(all(f"ZQ{i}Z" in par[i][0]["response_text"] for i in range(N)), "...and each answer is the one for its own question")
check(runner.inflight == 0, "no question is left counted as running")
check(S._embed_query is not None and not threading.current_thread().name.startswith("engine"), "the main thread's own engine state was not disturbed")

# (4) through HTTP: 8 threads, each with its own client, streaming
os.environ["API_ACCESS_TOKEN"] = "k"
engine_adapter.reset_runner(engine_adapter.Runner(8, 16))


def http_one(i):
    c = TestClient(app)
    r = c.post("/api/ask", json={"question": question(i), "audience": audience(i)}, headers={"X-API-Key": "k", "Accept": "text/event-stream"})
    events, cur = [], None
    for line in r.text.split("\n"):
        if line.startswith("event: "):
            cur = line[7:]
        elif line.startswith("data: ") and cur:
            events.append((cur, json.loads(line[6:])))
            cur = None
    return r.status_code, events


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    http = dict(zip(range(N), pool.map(http_one, range(N))))
check(all(http[i][0] == 200 for i in range(N)), "HTTP: all 16 streamed requests answered 200")
bad = [i for i in range(N) if norm([e for e in http[i][1] if e[0] == "result"][0][1]["result"]) != norm(BASE[i][0])]
check(not bad, f"HTTP: every streamed result equals its fresh-thread result (differences at {bad})")
bad = [i for i in range(N) if [e[1]["id"] for e in http[i][1] if e[0] == "step"] != steps_ids[i]]
check(not bad, f"HTTP: every request's streamed steps are its own (differences at {bad})")
bad = [i for i in range(N) if [e[0] for e in http[i][1]][0] != "start" or [e[0] for e in http[i][1]][-1] != "done"]
check(not bad, "HTTP: every stream starts with 'start' and ends with 'done'")

# (5) a caller who leaves: the question still finishes, the thread is clean for the next one
runner2 = engine_adapter.Runner(1, 4)
engine_adapter.reset_runner(runner2)
import asyncio


async def abandon():
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()
    from api import ask as A
    A._start(question(7), "layman", loop, q)       # started, then nobody reads the queue
    await asyncio.sleep(0)


asyncio.run(abandon())          # the event loop is closed straight away, as when a caller disconnects
for _ in range(300):
    if runner2.inflight == 0:
        break
    time.sleep(0.02)
check(runner2.inflight == 0, "a caller who left: the worker still finished and was released")
after = runner2.submit(run_one, 4).result(timeout=60)
check(norm(after[0]) == norm(BASE[4][0]) and norm(after[2]) == norm(BASE[4][2]), "the next question on that same worker thread is unaffected by the abandoned one")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
