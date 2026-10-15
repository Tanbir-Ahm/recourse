"""test_cost_switches.py -- ANSWER_EFFORT, SCOPE_MODEL, PROMPT_CACHE and DAILY_BUDGET_INR. Every one defaults to today's behaviour. Offline and free. Run: python -X utf8 test_cost_switches.py"""
import contextlib
import io
import json
import os
import sys
import tempfile
import types

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
for k in ("ANSWER_EFFORT", "SCOPE_MODEL", "PROMPT_CACHE", "DAILY_BUDGET_INR", "DAILY_BUDGET_SOFT_PCT", "COST_STATE_FILE", "RESPONSE_STYLE", "GROUNDING_CHECKS", "USD_INR"):
    os.environ.pop(k, None)
import chat_assistant as CA
import cost_log as C

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


KW = []
BEHAVE = {"reject_effort": False, "scope_reply": "text", "scope_raises": False}


class _Msgs:
    def create(self, **kw):
        KW.append(kw)
        if kw.get("output_config", {}).get("effort") and BEHAVE["reject_effort"] and kw["model"] != CA.HAIKU_MODEL:
            err = Exception("effort not supported"); err.status_code = 400
            raise err
        if kw["model"] != CA.HAIKU_MODEL and kw["max_tokens"] == 1500:       # a scope-check call on the configured model
            if BEHAVE["scope_raises"]:
                raise RuntimeError("model unavailable")
            blocks = [types.SimpleNamespace(type="text", text='{"category":"in_scope"}')] if BEHAVE["scope_reply"] == "text" else [types.SimpleNamespace(type="thinking", thinking="...")]
            return types.SimpleNamespace(content=blocks, stop_reason="end_turn", usage=types.SimpleNamespace(input_tokens=100, output_tokens=20))
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="An answer.")], stop_reason="end_turn",
                                     usage=types.SimpleNamespace(input_tokens=1000, output_tokens=500, cache_creation_input_tokens=0, cache_read_input_tokens=0))


CA.client = types.SimpleNamespace(messages=_Msgs())


def quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


# ================= ANSWER_EFFORT =================
CA._SWITCH_BROKEN["effort"] = False
KW.clear(); quiet(lambda: CA._create_answer("claude-sonnet-5", "prompt"))
check("output_config" not in KW[0] and KW[0]["messages"] == [{"role": "user", "content": "prompt"}] and KW[0]["max_tokens"] == 4000, "default: no effort setting, the prompt as one plain string, 4000 tokens (today's call)")
for v, want in (("medium", "medium"), (' "LOW" ', "low"), ("xhigh", "xhigh"), ("banana", None), ("", None)):
    os.environ["ANSWER_EFFORT"] = v
    CA._SWITCH_BROKEN["effort"] = False
    check(CA._answer_effort() == want, f"ANSWER_EFFORT={v!r} is read as {want}")
os.environ["ANSWER_EFFORT"] = "medium"
KW.clear(); quiet(lambda: CA._create_answer("claude-sonnet-5", "prompt"))
check(KW[0].get("output_config") == {"effort": "medium"}, "ANSWER_EFFORT=medium reaches the answer call as output_config")
BEHAVE["reject_effort"] = True
KW.clear(); out = quiet(lambda: CA._create_answer("claude-sonnet-5", "prompt"))
check(out == "An answer." and len(KW) == 2 and "output_config" not in KW[1] and CA._SWITCH_BROKEN["effort"], "if the API rejects the effort setting, the call is repeated without it and the setting is dropped for good")
KW.clear(); quiet(lambda: CA._create_answer("claude-sonnet-5", "prompt"))
check(len(KW) == 1 and "output_config" not in KW[0], "afterwards no further failed calls are made")
BEHAVE["reject_effort"] = False
CA._SWITCH_BROKEN["effort"] = False
os.environ.pop("ANSWER_EFFORT")

# ================= SCOPE_MODEL =================
KW.clear(); resp, used = CA._scope_call("scope prompt")
check(used == CA.HAIKU_MODEL and KW[0]["model"] == CA.HAIKU_MODEL and KW[0]["max_tokens"] == 1500 and "thinking" not in KW[0], "default: the Haiku 4.5 call exactly as before")
os.environ["SCOPE_MODEL"] = "claude-haiku-5-5"
KW.clear(); resp, used = CA._scope_call("scope prompt")
check(used == "claude-haiku-5-5" and KW[0]["thinking"] == {"type": "disabled"} and KW[0]["output_config"] == {"effort": "low"} and len(KW) == 1, "SCOPE_MODEL=claude-haiku-5-5 is used, told not to think and to use low effort")
os.environ["SCOPE_MODEL"] = "claude-sonnet-5"
KW.clear(); resp, used = CA._scope_call("scope prompt")
check(used == "claude-sonnet-5" and "thinking" not in KW[0], "another model is used as given, with no extra settings")
BEHAVE["scope_raises"] = True
KW.clear(); resp, used = CA._scope_call("scope prompt")
check(used == CA.HAIKU_MODEL and [k["model"] for k in KW] == ["claude-sonnet-5", CA.HAIKU_MODEL], "if the configured model fails, Haiku 4.5 answers instead")
BEHAVE["scope_raises"] = False
BEHAVE["scope_reply"] = "thinking_only"
KW.clear(); resp, used = CA._scope_call("scope prompt")
check(used == CA.HAIKU_MODEL, "a reply with no text falls back to Haiku 4.5 too")
BEHAVE["scope_reply"] = "text"
os.environ.pop("SCOPE_MODEL")
check(CA._scope_model() == CA.HAIKU_MODEL, "unset: Haiku 4.5")

# ================= PROMPT_CACHE =================
PREFIX = "RULES. " * 50
PROMPT = PREFIX + "QUESTION: delay? MATERIAL: text"
check(CA._messages_for(PROMPT, PREFIX) == [{"role": "user", "content": PROMPT}], "default: no cache, the whole prompt as one string")
for v, want in (("on", "5m"), ("1h", "1h"), (' "true" ', "5m"), ("off", None), ("", None), ("banana", None)):
    os.environ["PROMPT_CACHE"] = v
    check(CA._prompt_cache_mode() == want, f"PROMPT_CACHE={v!r} is read as {want}")
os.environ["PROMPT_CACHE"] = "on"
m = CA._messages_for(PROMPT, PREFIX)
blocks = m[0]["content"]
check(len(blocks) == 2 and blocks[0]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in blocks[1] and blocks[0]["text"] + blocks[1]["text"] == PROMPT, "on: two blocks, the fixed rules marked for caching, and the two together are exactly the prompt")
os.environ["PROMPT_CACHE"] = "1h"
check(CA._messages_for(PROMPT, PREFIX)[0]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}, "1h: the one-hour cache")
check(CA._messages_for("other prompt", PREFIX) == [{"role": "user", "content": "other prompt"}] and CA._messages_for(PREFIX, PREFIX) == [{"role": "user", "content": PREFIX}], "a prompt that does not start with the prefix (or has nothing after it) is sent plain")
os.environ["PROMPT_CACHE"] = "on"
KW.clear(); quiet(lambda: CA.generate_grounded_response("My trial has gone on nine years", "[BNSS Section 346]\ntext", matches=[]))
c0 = KW[0]["messages"][0]["content"]
tpl = CA._response_prompt_template()
check(isinstance(c0, list) and c0[0]["text"] == tpl.split("{conflict_instruction}", 1)[0] and "Hard rules" in c0[0]["text"] and "My trial has gone on nine years" in c0[1]["text"], "generate_grounded_response caches the template's fixed part and keeps the question and material outside it")
check(len(c0[0]["text"]) > 4000, "the cached part is large enough to be cacheable (well over 1,024 tokens)")
os.environ.pop("PROMPT_CACHE")
# cost with cache tokens
C.begin("q")
rec = None
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    C.note_anthropic("answer", "claude-sonnet-5", types.SimpleNamespace(input_tokens=2000, output_tokens=1000, cache_creation_input_tokens=3000, cache_read_input_tokens=0))
    os.environ["PROMPT_CACHE"] = "1h"
    C.note_anthropic("answer", "claude-sonnet-5", types.SimpleNamespace(input_tokens=2000, output_tokens=1000, cache_creation_input_tokens=3000, cache_read_input_tokens=0))
    os.environ.pop("PROMPT_CACHE")
    C.note_anthropic("answer", "claude-sonnet-5", types.SimpleNamespace(input_tokens=2000, output_tokens=1000, cache_creation_input_tokens=0, cache_read_input_tokens=3000))
    C.finish()
calls = [json.loads(l[10:]) for l in buf.getvalue().splitlines() if l.startswith("COST_CALL ")]
exp_write = (2000 * 2 + 3000 * 2 * 1.25 + 1000 * 10) / 1e6
exp_write_1h = (2000 * 2 + 3000 * 2 * 2.0 + 1000 * 10) / 1e6
exp_read = (2000 * 2 + 3000 * 2 * 0.1 + 1000 * 10) / 1e6
check(abs(calls[0]["usd"] - exp_write) < 1e-8 and abs(calls[1]["usd"] - exp_write_1h) < 1e-8 and abs(calls[2]["usd"] - exp_read) < 1e-8, f"cost_log prices cache writes at 1.25x (2x for 1h) and reads at 0.1x ({[c['usd'] for c in calls]})")
check(calls[0]["cache_write"] == 3000 and calls[2]["cache_read"] == 3000, "the cache token counts are in the log line")

# ================= DAILY_BUDGET_INR =================
C._reset_day_for_tests()
check(C.budget_cap_inr() is None and C.budget_state() == "ok", "unset: no limit")
os.environ["DAILY_BUDGET_INR"] = "100"
C._reset_day_for_tests()
check(C.budget_cap_inr() == 100.0 and C.budget_state() == "ok", "a limit of Rs 100 and nothing spent: ok")
C.add_spend_inr(79.9)
check(C.budget_state() == "ok", "Rs 79.9 of 100: still ok")
C.add_spend_inr(0.2)
check(C.budget_state() == "soft" and abs(C.spent_today_inr() - 80.1) < 1e-9, "from 80 per cent: soft")
os.environ["DAILY_BUDGET_SOFT_PCT"] = "50"
check(C.budget_state() == "soft", "DAILY_BUDGET_SOFT_PCT moves the soft line")
os.environ.pop("DAILY_BUDGET_SOFT_PCT")
os.environ["ANSWER_EFFORT"] = "high"
CA._SWITCH_BROKEN["effort"] = False
check(CA._answer_effort() == "low", "at the soft line the answer runs at low effort, whatever ANSWER_EFFORT says")
os.environ.pop("ANSWER_EFFORT")
C.add_spend_inr(25)
check(C.budget_state() == "hard", "at the limit: hard")
CA.client = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(AssertionError("a model was called after the budget was spent"))))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = CA.answer_question("My trial has gone on nine years")
check(r == {"state": "budget_paused"} and "BUDGET_PAUSED" in buf.getvalue(), "at the hard limit answer_question returns 'budget_paused' without calling any model")
# the cost line shows the switches as they were when the question STARTED (2026-10-15): a question that itself pushes the day over the limit still reads 'ok', then 'budget_after: hard'
C._reset_day_for_tests()
os.environ["DAILY_BUDGET_INR"] = "8"
os.environ["ANSWER_EFFORT"] = "medium"
CA._SWITCH_BROKEN["effort"] = False
_orig_inner = CA._answer_question_inner
def _spends(question, inline_domains=frozenset()):
    C.add_spend_inr(9.0)
    return {"state": "out_of_scope"}
CA._answer_question_inner = _spends
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    CA.answer_question("a question")
CA._answer_question_inner = _orig_inner
cq = [json.loads(l[len("COST_QUESTION "):]) for l in buf.getvalue().splitlines() if l.startswith("COST_QUESTION ")]
check(cq and cq[-1]["switches"]["budget"] == "ok" and cq[-1]["switches"]["effort"] == "medium" and cq[-1]["switches"]["budget_after"] == "hard", f"switches are the state at the start; the end state is budget_after ({cq[-1]['switches'] if cq else None})")
os.environ.pop("ANSWER_EFFORT")
os.environ.pop("DAILY_BUDGET_INR")
C._reset_day_for_tests()
# the day rolls over
C._DAY["date"] = "2000-01-01"
check(C.budget_state() == "ok" and C.spent_today_inr() == 0.0, "a new (Indian) day starts again from zero")
# persistence across a restart
d = tempfile.mkdtemp()
os.environ["COST_STATE_FILE"] = os.path.join(d, "cost_state.json")
C._reset_day_for_tests()
C.add_spend_inr(42.5)
C._reset_day_for_tests()
check(abs(C.spent_today_inr() - 42.5) < 1e-9, "COST_STATE_FILE keeps today's total across a restart")
os.environ.pop("COST_STATE_FILE")
os.environ["DAILY_BUDGET_INR"] = "banana"
check(C.budget_cap_inr() is None and C.budget_state() == "ok", "a bad limit means no limit")
os.environ.pop("DAILY_BUDGET_INR")
# every spend logged by a call counts
C._reset_day_for_tests()
os.environ["USD_INR"] = "100"
with contextlib.redirect_stdout(io.StringIO()):
    C.note_anthropic("a", "claude-sonnet-5", types.SimpleNamespace(input_tokens=1_000_000, output_tokens=0))
check(abs(C.spent_today_inr() - 200.0) < 1e-6, "a logged call adds its rupee cost to the day's total ($2 at Rs 100 = Rs 200)")
os.environ.pop("USD_INR")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
