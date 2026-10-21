"""
test_api_ask.py -- POST /api/ask (api/ask.py, api/engine_adapter.py, api/steps.py, api/config.py; website design WEBSITE_DESIGN.md sections 5.1 and 5.2, step A1). Free and offline: the engine is a fake object here
(test_api_concurrency.py runs the REAL engine with a stubbed model). Proves: it fails closed (no token = 503, wrong key = 401), validates input, streams start/step/result/done in order, gives the same result as
one JSON reply, hands the engine's result on whole, never leaks the question or an exception's text, says "busy" (429) when full, times out cleanly, and that /api/health never imports the engine.
Run: python -X utf8 test_api_ask.py
"""
import json
import os
import subprocess
import sys
import threading
import time

import numpy as np
from fastapi.testclient import TestClient

for _v in ("API_ACCESS_TOKEN", "API_ENGINE_WORKERS", "API_ASK_TIMEOUT_SECONDS", "API_MAX_QUESTION_CHARS"):
    os.environ.pop(_v, None)

from api import config, engine_adapter, steps
from api.main import app

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CANARY = "Zebulon Quillfeather of Hoskote"
KEY = "test-key-123"
RESULT = {"state": "single_match", "response_text": "The court may adjourn only for recorded reasons.", "matches": [{"type": "statute", "act": "BNSS", "section_number": "346", "score": np.float64(0.91)}],
          "audience": "layman", "act_notice": {"kind": "answer", "acts": ["x"], "html": "<b>n</b>"}, "section_note": [{"act": "PCACT", "section": "17", "texts": ["t"], "cut": False}],
          "tags": {"a", "b"}, "pair": (1, 2), "nan": float("nan")}


class FakeEngine:
    """Stands in for chat_assistant: reports steps through progress like the real one, returns RESULT."""
    mode = "ok"
    gate = threading.Event()

    seen_domains = []

    def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None):
        import cost_log
        import progress
        self.seen_domains.append(frozenset(inline_domains))
        cost_log.begin(question)
        try:
            progress.emit("scope", category="in_scope")
            progress.emit("acts", names=["Prevention of Corruption Act, 1988"])
            progress.emit("library", statutes=3, judgments=1)
            progress.emit("unknown_step_id", x=1)
            progress.emit("write")
            if self.mode == "boom":
                raise RuntimeError("secret internal failure about " + CANARY)
            if self.mode == "slow":
                self.gate.wait(5)
            progress.emit("checks", notes=0)
            return dict(RESULT, audience=audience or "layman")
        finally:
            cost_log.finish(style="v1", audience=audience or "")


ENG = FakeEngine()
engine_adapter.set_engine(ENG)


def new_runner(workers=4, waiting=None):
    engine_adapter.reset_runner(engine_adapter.Runner(workers, waiting))


def sse(resp):
    events, cur = [], None
    for line in resp.text.split("\n"):
        if line.startswith("event: "):
            cur = line[7:]
        elif line.startswith("data: ") and cur:
            events.append((cur, json.loads(line[6:])))
            cur = None
    return events


H = {"X-API-Key": KEY}
SSE = {"X-API-Key": KEY, "Accept": "text/event-stream"}
new_runner()
c = TestClient(app)

# ---------------------------------------------------------------- fails closed
r = c.post("/api/ask", json={"question": "q"}, headers=H)
check(r.status_code == 503, f"no API_ACCESS_TOKEN set: 503, the ask route is off ({r.status_code})")
os.environ["API_ACCESS_TOKEN"] = KEY
check(c.post("/api/ask", json={"question": "q"}).status_code == 401, "no key: 401")
check(c.post("/api/ask", json={"question": "q"}, headers={"X-API-Key": "wrong"}).status_code == 401, "wrong key: 401")
check(c.post("/api/ask", json={"question": "q"}, headers={"X-API-Key": KEY[:-1]}).status_code == 401, "a key that is a prefix of the right one: 401")
os.environ["API_ACCESS_TOKEN"] = ' "' + KEY + '" '
check(c.post("/api/ask", json={"question": "q"}, headers=H).status_code == 200, "quote marks and spaces around the variable's value are stripped (as the engine's own variables are)")
os.environ["API_ACCESS_TOKEN"] = KEY

# ---------------------------------------------------------------- validation
check(c.post("/api/ask", json={"question": "q", "audience": "judge"}, headers=H).status_code == 422, "an unknown audience: 422")
check(c.post("/api/ask", json={"question": ""}, headers=H).status_code == 422, "an empty question: 422")
check(c.post("/api/ask", json={"question": "   "}, headers=H).status_code == 422, "a question of blanks: 422")
check(c.post("/api/ask", json={}, headers=H).status_code == 422, "no question: 422")
check(c.post("/api/ask", data="not json", headers={**H, "Content-Type": "application/json"}).status_code == 422, "a body that is not JSON: 422")
os.environ["API_MAX_QUESTION_CHARS"] = "200"
check(c.post("/api/ask", json={"question": "x" * 201}, headers=H).status_code == 413, "a question over the limit: 413")
check(c.post("/api/ask", json={"question": "x" * 200}, headers=H).status_code == 200, "a question at the limit: accepted")
os.environ.pop("API_MAX_QUESTION_CHARS")
check(c.get("/api/ask", headers=H).status_code == 405, "GET /api/ask: 405")

# ---------------------------------------------------------------- one JSON reply
r = c.post("/api/ask", json={"question": "Can the court adjourn? " + CANARY, "audience": "lawyer"}, headers=H)
j = r.json()
check(r.status_code == 200 and r.headers.get("X-Request-Id") == j["request_id"], "JSON mode: 200, the request id is in the header and the body")
res = j["result"]
check(res["state"] == "single_match" and res["response_text"] == RESULT["response_text"] and j["text"] == RESULT["response_text"], "the answer text arrives, also as 'text'")
check(res["audience"] == "lawyer", "the audience the caller asked for reached the engine")
check(res["matches"][0]["score"] == 0.91 and res["tags"] in (["a", "b"], ["b", "a"]) and res["pair"] == [1, 2] and res["nan"] is None, "numpy numbers, sets, tuples and NaN come out as plain JSON")
check(set(RESULT) <= set(res), "every key the engine returned is in the reply: nothing dropped or renamed")
check(res["act_notice"] == RESULT["act_notice"] and res["section_note"] == RESULT["section_note"], "the notices and the official-text boxes arrive unchanged")
check("elapsed_ms" in j and "cost_inr" in j, "elapsed time and cost fields are present")

# ---------------------------------------------------------------- the same four inline topics as the page and the bot
import re as _re
page_src = open(os.path.join(HERE, "recourse_app.py"), encoding="utf-8").read()
bot_src = open(os.path.join(HERE, "whatsapp_bot.py"), encoding="utf-8").read()
page_set = eval(_re.search(r"inline_domains=(\{[^}]*\})", page_src).group(1))
bot_set = eval(_re.search(r"inline_domains=(\{[^}]*\})", bot_src).group(1))
check(engine_adapter.INLINE_DOMAINS == frozenset(page_set) == frozenset(bot_set), f"the API passes the same inline topics as the page and the WhatsApp bot ({sorted(engine_adapter.INLINE_DOMAINS)})")
check(ENG.seen_domains and all(d == engine_adapter.INLINE_DOMAINS for d in ENG.seen_domains), "every question the engine received carried those topics (cheque bounce, bank freeze, domestic violence and NDPS are answered, not redirected)")

# ---------------------------------------------------------------- the event stream
r = c.post("/api/ask", json={"question": "Can the court adjourn? " + CANARY}, headers=SSE)
ev = sse(r)
names = [n for n, _ in ev]
check(r.headers["content-type"].startswith("text/event-stream") and r.headers.get("X-Accel-Buffering") == "no" and r.headers.get("Cache-Control") == "no-cache", "SSE: right content type and buffering switched off")
check(names[0] == "start" and names[-2:] == ["result", "done"], f"SSE: start first, then result and done last ({names})")
st = [d for n, d in ev if n == "step"]
check([s["id"] for s in st] == ["scope", "acts", "library", "write", "checks"], f"the steps arrive in the order the engine reported them, unknown ids left out ({[s['id'] for s in st]})")
check(st[1]["label"] == "Found an Act named or described in the question: Prevention of Corruption Act, 1988" and st[1]["status"] == "done", f"the label is built from the step's own details ({st[1]['label']})")
check(st[3]["status"] == "running" and st[3]["label"] == "Writing the answer", "'write' is shown as running")
check("Searched the library: 3 law passages and 1 judgment passage found" == st[2]["label"], f"counts are worded with the right plural ({st[2]['label']})")
resv = [d for n, d in ev if n == "result"][0]
check(resv["result"] == res or resv["result"]["response_text"] == RESULT["response_text"], "the streamed result carries the same answer as the JSON reply")
check(resv["request_id"] == ev[0][1]["request_id"], "the request id is the same on 'start' and 'result'")
check(CANARY not in r.text, "no event carries any word of the question")

# ---------------------------------------------------------------- an engine failure
ENG.mode = "boom"
r = c.post("/api/ask", json={"question": "q " + CANARY}, headers=SSE)
ev = sse(r)
err = [d for n, d in ev if n == "error"]
check(len(err) == 1 and err[0]["code"] == "engine_error" and err[0]["message"] == "The answer could not be produced. Please try again.", f"a failing engine: one 'error' event with a fixed sentence ({err})")
check("secret internal failure" not in r.text and CANARY not in r.text and "RuntimeError" not in r.text, "the exception's text, its type and the question are not in the stream")
check([n for n, _ in ev][-1] == "done" and "result" not in [n for n, _ in ev], "the stream still ends with 'done', and has no result")
r = c.post("/api/ask", json={"question": "q " + CANARY}, headers=H)
check(r.status_code == 500 and r.json()["error"]["code"] == "engine_error" and "secret internal" not in r.text and CANARY not in r.text, "JSON mode: 500 with the same fixed sentence and nothing else")
ENG.mode = "ok"
check(engine_adapter.get_runner().inflight == 0, "after the failure no question is left counted as running")

# ---------------------------------------------------------------- busy
ENG.mode = "slow"
ENG.gate.clear()
new_runner(workers=1, waiting=0)
box = {}


def first():
    box["r"] = TestClient(app).post("/api/ask", json={"question": "first"}, headers=H)


t = threading.Thread(target=first)
t.start()
for _ in range(100):
    if engine_adapter.get_runner().inflight == 1:
        break
    time.sleep(0.02)
r2 = c.post("/api/ask", json={"question": "second"}, headers=H)
check(r2.status_code == 429 and r2.headers.get("Retry-After") == "5", f"one worker, no waiting room, one question running: the second gets 429 with Retry-After ({r2.status_code})")
ENG.gate.set()
t.join(10)
check(box["r"].status_code == 200, "the first question still finishes normally")
check(engine_adapter.get_runner().inflight == 0, "both are accounted for afterwards")
ENG.mode = "ok"

# ---------------------------------------------------------------- timeout
new_runner()
ENG.mode = "slow"
ENG.gate.clear()
_orig = config.ask_timeout_seconds
config.ask_timeout_seconds = lambda: 0.3
r = c.post("/api/ask", json={"question": "slow one"}, headers=SSE)
ev = sse(r)
check([n for n, _ in ev][-2:] == ["error", "done"] and [d for n, d in ev if n == "error"][0]["code"] == "timeout", "SSE: a slow question ends with a 'timeout' error and 'done'")
r = c.post("/api/ask", json={"question": "slow one"}, headers=H)
check(r.status_code == 504, f"JSON mode: 504 on timeout ({r.status_code})")
config.ask_timeout_seconds = _orig
ENG.gate.set()
time.sleep(0.3)
ENG.mode = "ok"

# ---------------------------------------------------------------- settings
for v, want in ((None, 4), ("2", 2), ("0", 1), ("99", 16), ("x", 4), (' "3" ', 3)):
    if v is None:
        os.environ.pop("API_ENGINE_WORKERS", None)
    else:
        os.environ["API_ENGINE_WORKERS"] = v
    check(config.engine_workers() == want, f"API_ENGINE_WORKERS={v!r}: {want}")
os.environ.pop("API_ENGINE_WORKERS", None)
check(config.ask_timeout_seconds() == 120 and config.max_question_chars() == 6000, "defaults: 120 seconds, 6000 characters")

# ---------------------------------------------------------------- the step lines
check(steps.describe("nope", {}) is None and steps.describe("sections", {"items": []}) is None, "an unknown step, or a 'sections' step with no sections, produces no line")
check(steps.describe("sections", {"items": ["PCACT s.17", "PCACT s.13"], "cited": 1})["label"] == "Brought in the official text of: PCACT s.17, PCACT s.13 (including 1 section cited by the section asked about)", "the 'sections' line says how many were cited by the section asked about")
check(steps.describe("register", {"notes": 0})["label"] == "Checked the Overruled Register: nothing flagged" and steps.describe("register", {"notes": 2})["label"] == "Checked the Overruled Register: 2 cases flagged", "register lines")
check(steps.describe("scope", {"category": "banana"})["label"] == "Checked the topic of the question", "an unexpected scope category gets the neutral line")
check(steps.describe("library", {"statutes": "x", "judgments": True}) ["detail"] == {"statutes": 0, "judgments": 0}, "junk counts become 0")

# ---------------------------------------------------------------- health never imports the engine
code = "import sys; import api.main as m; from fastapi.testclient import TestClient; r = TestClient(m.app).get('/api/health'); print(r.json()['role'], 'chat_assistant' in sys.modules, 'streamlit' in sys.modules, 'sqlalchemy' in sys.modules)"
out = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=120).stdout.strip()
check(out == "api False False False", f"/api/health answers without importing the engine, Streamlit or the database library ({out!r})")


# ---------------------------------------------------------------- the command-line helper, against a real server process
import socket
srv_code = (
    "import os, sys, uvicorn\n"
    "from api import engine_adapter\n"
    "class E:\n"
    "    def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None):\n"
    "        import progress\n"
    "        progress.emit('scope', category='in_scope'); progress.emit('write')\n"
    "        return {'state': 'single_match', 'response_text': 'Server answer for ' + (audience or 'none'), 'matches': []}\n"
    "engine_adapter.set_engine(E())\n"
    "import api.main\n"
    "uvicorn.run(api.main.app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')\n"
)
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
sock.close()
env = {**os.environ, "API_ACCESS_TOKEN": KEY, "PYTHONPATH": HERE}
srv = subprocess.Popen([sys.executable, "-c", srv_code, str(port)], cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
try:
    import urllib.request
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    ok = subprocess.run([sys.executable, os.path.join(HERE, "api", "try_ask.py"), "--url", f"http://127.0.0.1:{port}", "--audience", "lawyer", "A question"], env=env, capture_output=True, text=True, timeout=60)
    check(ok.returncode == 0 and "[done] Checked the topic of the question: it is within what Recourse covers" in ok.stdout and "[running] Writing the answer" in ok.stdout and "Server answer for lawyer" in ok.stdout and "state: single_match" in ok.stdout,
          f"try_ask.py against a real server prints the steps, then the answer and its state ({ok.stdout.strip()[:300]!r})")
    check(KEY not in ok.stdout and KEY not in ok.stderr, "...and prints no key")
    bad = subprocess.run([sys.executable, os.path.join(HERE, "api", "try_ask.py"), "--url", f"http://127.0.0.1:{port}", "A question"], env={**env, "API_ACCESS_TOKEN": "wrong"}, capture_output=True, text=True, timeout=60)
    check(bad.returncode == 1 and "the key was refused (401)" in bad.stdout, f"a wrong key: a plain message and exit code 1 ({bad.stdout.strip()!r})")
    nokey = subprocess.run([sys.executable, os.path.join(HERE, "api", "try_ask.py"), "--url", f"http://127.0.0.1:{port}", "A question"], env={k: v for k, v in env.items() if k != "API_ACCESS_TOKEN"}, capture_output=True, text=True, timeout=60)
    check(nokey.returncode == 1 and "Set the environment variable API_ACCESS_TOKEN" in nokey.stdout, "no key in the environment: tells the person what to set, exit code 1")
    down = subprocess.run([sys.executable, os.path.join(HERE, "api", "try_ask.py"), "--url", "http://127.0.0.1:1", "A question"], env=env, capture_output=True, text=True, timeout=60)
    check(down.returncode == 1 and "Could not reach the service" in down.stdout, "an unreachable service: a plain message and exit code 1")
finally:
    srv.terminate()
    try:
        srv.wait(10)
    except Exception:  # noqa: BLE001
        srv.kill()

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
