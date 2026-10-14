"""test_cost_log.py -- per-question cost from the tokens each call really used. Offline and free. Run: python -X utf8 test_cost_log.py"""
import contextlib
import io
import json
import os
import sys
import types

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.pop("USD_INR", None)
os.environ.pop("PRICES_JSON", None)
import cost_log as C
import chat_assistant as CA
import answer_style as AS

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn()
    lines = [l for l in buf.getvalue().splitlines()]
    return out, lines


def parse(lines, tag):
    return [json.loads(l[len(tag) + 1:]) for l in lines if l.startswith(tag + " ")]


U = lambda i, o: types.SimpleNamespace(input_tokens=i, output_tokens=o)

# ---- arithmetic ----
C.begin("a question")
_, lines = capture(lambda: C.note_anthropic("answer", "claude-sonnet-5", U(10000, 1500)))
c = parse(lines, "COST_CALL")[0]
check(abs(c["usd"] - 0.035) < 1e-9 and abs(c["inr"] - 0.035 * 96.5) < 1e-3 and c["in"] == 10000 and c["out"] == 1500, f"Sonnet 5: 10,000 in + 1,500 out = $0.035 ({c['usd']}), rupees at the default rate ({c['inr']})")
_, lines = capture(lambda: C.note_anthropic("scope_check", "claude-haiku-4-5-20251001", U(4200, 150)))
c = parse(lines, "COST_CALL")[0]
check(abs(c["usd"] - (4200 * 1.0 + 150 * 5.0) / 1e6) < 1e-9 and c["priced"], "Haiku 4.5 is priced at $1 in / $5 out per million")
_, lines = capture(lambda: C.note_search_usage("sci_search", {"embed_model": "voyage-law-2", "embed_tokens": 170, "rerank_model": "rerank-3-lite", "rerank_tokens": 21700}))
cs = parse(lines, "COST_CALL")
check(len(cs) == 2 and abs(cs[1]["usd"] - 21700 * 0.02 / 1e6) < 1e-9 and abs(cs[0]["usd"] - 170 * 0.12 / 1e6) < 1e-9, "a wider search: 21,700 re-rank tokens at $0.02/M and 170 embedding tokens at $0.12/M")
_, lines = capture(lambda: C.note_anthropic("x", "some-new-model", U(1000, 1000)))
check(parse(lines, "COST_CALL")[0]["priced"] is False and parse(lines, "COST_CALL")[0]["usd"] == 0, "a model with no price is flagged unpriced, never guessed")
rec, lines = capture(lambda: C.finish(style="v3", audience="lawyer"))
q = parse(lines, "COST_QUESTION")[0]
check(len(q["calls"]) == 5 and abs(q["usd"] - sum(x["usd"] for x in q["calls"])) < 1e-5 and q["unpriced"] == ["some-new-model"] and q["style"] == "v3" and q["audience"] == "lawyer", "COST_QUESTION lists every call, the total, the style, the audience and the unpriced models")
check("a question" not in "\n".join(lines) and len(q["q"]) == 12, "the question text is never logged, only a 12-character hash")
rec2, lines2 = capture(lambda: C.finish())
check(rec2 is None and not lines2, "finishing twice prints nothing")

# ---- settings ----
os.environ["USD_INR"] = ' "90" '
check(C.usd_inr() == 90.0, "USD_INR tolerates quotation marks and spaces")
os.environ["USD_INR"] = "banana"
check(C.usd_inr() == 96.5, "a bad USD_INR falls back to the default")
os.environ["USD_INR"] = "100"
os.environ["PRICES_JSON"] = json.dumps({"claude-sonnet-5": [3, 15], "rerank-3-lite": 0.05})
C.begin("q")
_, lines = capture(lambda: (C.note_anthropic("a", "claude-sonnet-5", U(1_000_000, 1_000_000)), C.note_voyage("v", "rerank-3-lite", 1_000_000)))
cs = parse(lines, "COST_CALL")
check(abs(cs[0]["usd"] - 18.0) < 1e-6 and cs[0]["inr"] == 1800.0 and abs(cs[1]["usd"] - 0.05) < 1e-9, "PRICES_JSON and USD_INR override the built-in prices and rate")
C.finish()
os.environ.pop("PRICES_JSON"); os.environ.pop("USD_INR")
check(C.note_anthropic("a", "claude-sonnet-5", None) is None and C.note_voyage("v", "voyage-law-2", None) is None, "missing usage does not raise")

# ---- wired into the answer path ----
CALLS = []
class _Msgs:
    def create(self, **kw):
        CALLS.append(kw["max_tokens"])
        stop = "max_tokens" if len(CALLS) == 1 else "end_turn"
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="An answer.")], stop_reason=stop, usage=U(6000, 2500))
CA.client = types.SimpleNamespace(messages=_Msgs())
os.environ["RESPONSE_STYLE"] = "v3"


def core(q, inline_domains=frozenset()):
    CA._create_answer("claude-sonnet-5", "prompt")
    return {"state": "no_match"}


CA._answer_question_core = core
_, lines = capture(lambda: CA.answer_question("My trial has gone on nine years", audience="lawyer"))
q = parse(lines, "COST_QUESTION")
check(len(q) == 1 and [c["label"] for c in q[0]["calls"]] == ["answer", "answer_after_cutoff"] and q[0]["audience"] == "lawyer" and q[0]["style"] == "v3", "answer_question prints one COST_QUESTION: the answer call and the second call after a cut-off, style v3, audience lawyer")
check(abs(q[0]["usd"] - 2 * (6000 * 2 + 2500 * 10) / 1e6) < 1e-9, f"the two calls cost 2 x $0.037 = ${q[0]['usd']}")
os.environ["RESPONSE_STYLE"] = "v1"
CALLS.clear()
_, lines = capture(lambda: CA.answer_question("another"))
check(len(parse(lines, "COST_QUESTION")) == 1 and parse(lines, "COST_QUESTION")[0]["audience"] == "layman", "under v1 the line is printed too (audience layman)")

# ---- the wider search reports its usage ----
import sci_search_tier as T
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        data = json.dumps({"ok": True, "results": [], "usage": {"embed_model": "voyage-law-2", "embed_tokens": 170, "rerank_model": "rerank-3-lite", "rerank_tokens": 21700}}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["SCI_SEARCH_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
C.begin("q")
body, lines = capture(lambda: T.search("question", label="sci_search_second"))
cs = parse(lines, "COST_CALL")
check(body and [c["label"] for c in cs] == ["sci_search_second_embed", "sci_search_second_rerank"], "the tier logs the search service's usage under the label of the search (here the second search for a correcting case)")
C.finish()
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
