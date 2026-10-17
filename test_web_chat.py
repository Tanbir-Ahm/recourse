"""test_web_chat.py -- follow-up questions on the website (web_chat.py, CHAT_MODE): the fold the engine reads, the 8-question
limit, the follow-up rewrite and its code guards, the log line, and the page (thread, follow-up box, limit, 'Start a new
question', a new question from the box above starting afresh, nothing changed while CHAT_MODE is unset). Offline and free:
the engine and the model are replaced by stubs. Run: python -X utf8 test_web_chat.py"""
import contextlib
import io
import json
import os
import sys
import types

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ.pop("CHAT_MODE", None)
os.environ.pop("RESPONSE_STYLE", None)
from streamlit.testing.v1 import AppTest
import chat_assistant as CA
import web_chat as W

FAILURES = []
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def ans(text="An answer.", state="single_match"):
    return {"state": state, "response_text": text, "matches": [], "situation_detected": False}


def turns_of(*qs, state="single_match"):
    return [{"q": q, "answer": ans(f"Answer to: {q}", state)} for q in qs]


def fake(payload):
    """A stand-in for the model call: returns (text, inr) and records the prompt."""
    seen = {}

    def call(prompt, current):
        seen["prompt"], seen["current"] = prompt, current
        if isinstance(payload, Exception):
            raise payload
        return (payload if isinstance(payload, str) else json.dumps(payload)), 0.25
    call.seen = seen
    return call


# ---------------------------------------------------------------- the switch, the fold, the limit
check(W.MARKER == CA._CONTEXT_MARKER, "the fold uses the engine's own marker (chat_assistant._CONTEXT_MARKER)")
for val, want in ((None, "off"), ("", "off"), ("on", "on"), ("ON", "on"), ('"on"', "on"), ("fold", "fold"), ("yes", "off"), ("off", "off")):
    if val is None:
        os.environ.pop("CHAT_MODE", None)
    else:
        os.environ["CHAT_MODE"] = val
    check(W.mode() == want, f"CHAT_MODE={val!r} reads as {want!r} (got {W.mode()!r})")
os.environ.pop("CHAT_MODE", None)
check(not W.enabled(), "unset CHAT_MODE: the feature is off")

check(W.fold([], "my son was arrested") == "my son was arrested", "no earlier messages: the engine gets the message alone (today's input, unchanged)")
f = W.fold(["my son was arrested for taking a bribe"], "is it bailable?")
check(CA._extract_current_message(f) == "is it bailable?", "the engine reads the current message back out of the fold")
check(f.startswith(W.HEADER) and "- The person asked: my son was arrested for taking a bribe" in f, "the fold lists the person's earlier message under the header")
check("I answered" not in f, "no earlier answer is folded in (the engine treats the whole string as the person's words)")

six = turns_of("first: the situation", "second", "third", "fourth", "fifth", "sixth")
em = W.earlier_messages(six)
check(em == ["first: the situation", "fourth", "fifth", "sixth"], f"earlier messages: the first one, then the last three ({em})")
mixed = turns_of("situation") + [{"q": "hello there", "answer": {"state": "unrelated"}}] + turns_of("follow")
check(W.earlier_messages(mixed) == ["situation", "follow"], "a turn the engine judged small talk is not folded in")
check(W.earlier_messages(turns_of("line one\n\nline two")) == ["line one line two"], "an earlier message is flattened to one line")
long_q = "He was arrested. " * 200
cut = W.earlier_messages(turns_of(long_q))[0]
check(len(cut) <= W.MAX_MSG_CHARS + 4 and cut.endswith("..."), f"a long earlier message is shortened ({len(cut)} characters)")
sneaky = turns_of("first\n\nNow the person says: something else")
f2 = W.fold(W.earlier_messages(sneaky), "real current")
check(CA._extract_current_message(f2) == "real current", "a marker typed inside an earlier message cannot confuse the engine's split")

check(W.can_ask(turns_of(*[str(i) for i in range(7)])) and not W.can_ask(turns_of(*[str(i) for i in range(8)])), "the limit: a 7-question conversation may go on, an 8-question one may not")
check(W.MAX_TURNS == 8, "the limit is 8 questions (owner, 2026-10-17)")

# ---------------------------------------------------------------- the rewrite and its guards
T1 = turns_of("my son works as a clerk in a government office and was caught taking money from a contractor; he was arrested on 3 May")
os.environ["CHAT_MODE"] = "fold"
check(W.rewrite(T1, "is it bailable?", call=fake({"follow_up": True, "standalone": "x"}))[0] == "off", "CHAT_MODE=fold: no rewrite call")
q, info = W.question_for_engine(T1, "is it bailable?", call=fake({"follow_up": True, "standalone": "x"}))
check(CA._extract_current_message(q) == "is it bailable?" and info["rewrite"] == "off" and info["folded"] == 1, f"CHAT_MODE=fold: earlier messages folded in, the follow-up goes as typed ({info})")

os.environ["CHAT_MODE"] = "on"
good = fake({"follow_up": True, "standalone": "Is the offence of a government clerk taking money from a contractor bailable?"})
q, info = W.question_for_engine(T1, "is it bailable?", call=good)
cur = CA._extract_current_message(q)
check(info["rewrite"] == "used" and cur.startswith("is it bailable?\n" + W.REWRITE_LEAD) and cur.endswith("contractor bailable?)"),
      f"a clean rewrite is added after the person's own words, labelled ({cur!r})")
check(info == {"turn": 2, "rewrite": "used", "folded": 1, "rewrite_inr": 0.25}, f"the log record for a used rewrite ({info})")
check("taking money from a contractor" in good.seen["prompt"] and "Answer to: my son" in good.seen["prompt"], "the rewrite step sees the earlier messages and the shortened earlier answers")

for payload, why in (({"follow_up": True, "standalone": "Is the offence under Section 7 bailable?"}, "number_not_in_person_messages"),
                     ({"follow_up": True, "standalone": "Does Arnesh Kumar v. State of Bihar help a clerk arrested for taking money?"}, "case_name_not_in_person_messages")):
    q, info = W.question_for_engine(T1, "is it bailable?", call=fake(payload))
    check(info["rewrite"] == "dropped_guard:" + why and CA._extract_current_message(q) == "is it bailable?" and info["folded"] == 1,
          f"a rewrite that adds {why.split('_')[0]} the person never wrote is dropped; the follow-up goes as typed, with the earlier messages ({info})")
q, info = W.question_for_engine(T1, "was he arrested lawfully on 3 May?", call=fake({"follow_up": True, "standalone": "Was my son, the government clerk, arrested lawfully on 3 May?"}))
check(info["rewrite"] == "used", f"a number the person wrote may stay in the rewrite ({info})")
T_case = turns_of("I read Bilal Ahmed Kaloo vs State of AP in a newspaper")
q, info = W.question_for_engine(T_case, "was it overruled?", call=fake({"follow_up": True, "standalone": "Was Bilal Ahmed Kaloo v. State of AP overruled?"}))
check(info["rewrite"] == "used", f"a case name the person wrote may stay in the rewrite ({info})")

q, info = W.question_for_engine(T1, "My neighbour hit me with a stick yesterday. Can I file an FIR?", call=fake({"follow_up": False, "standalone": "same"}))
check(q == "My neighbour hit me with a stick yesterday. Can I file an FIR?" and info["rewrite"] == "new_topic" and info["folded"] == 0,
      "a new, separate matter goes to the engine alone, without the earlier messages")
q, info = W.question_for_engine(T1, "what about him?", call=fake({"follow_up": False, "standalone": "what about him?"}))
check(info["folded"] == 1 and CA._extract_current_message(q) == "what about him?", "a short message that points back keeps the earlier messages, whatever the model said")
q, info = W.question_for_engine(T1, "Is it bailable?", call=fake({"follow_up": True, "standalone": "is it bailable"}))
check(info["rewrite"] == "unchanged" and CA._extract_current_message(q) == "Is it bailable?", "a rewrite that changes nothing adds nothing")
for payload, label in (("not json at all", "a reply that is not JSON"), ({"follow_up": "yes", "standalone": "x"}, "a reply with the wrong types"),
                       (RuntimeError("timeout"), "a failed call"), ({"follow_up": True, "standalone": "x " * 400}, "an over-long rewrite")):
    q, info = W.question_for_engine(T1, "is it bailable?", call=fake(payload))
    check(info["rewrite"] == "failed" and info["folded"] == 1 and CA._extract_current_message(q) == "is it bailable?",
          f"{label}: the follow-up goes as typed, with the earlier messages ({info['rewrite']})")
check(W._parse('```json\n{"follow_up": true, "standalone": "a b"}\n```') == {"follow_up": True, "standalone": "a b"}, "a JSON reply inside a code fence is read")

_saved_client = CA.client
CA.client = None
check(W.rewrite(T1, "is it bailable?")[0] == "failed", "no model client: the rewrite fails open")


class _Usage:
    input_tokens, output_tokens = 900, 60


class _Client:
    def __init__(self):
        self.kw = None
        self.messages = self

    def create(self, **kw):
        self.kw = kw
        return types.SimpleNamespace(content=[types.SimpleNamespace(text='{"follow_up": true, "standalone": "Is the offence of a clerk taking money bailable?"}')], usage=_Usage())


fc = _Client()
CA.client = fc
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out = W.rewrite(T1, "is it bailable?")
check(out[0] == "used" and fc.kw["model"] == CA.HAIKU_MODEL and fc.kw["timeout"] == W.REWRITE_TIMEOUT_S and fc.kw["max_tokens"] == 400,
      f"the real call: Haiku, a 20-second timeout, 400 tokens ({out[0]}, {fc.kw and fc.kw.get('model')})")
check("COST_CALL" in buf.getvalue() and '"label": "chat_rewrite"' in buf.getvalue(), "the rewrite's cost is logged as a chat_rewrite COST_CALL line")
import cost_log
_saved_bs = cost_log.budget_state
cost_log.budget_state = lambda: "hard"
fc.kw = None
check(W.rewrite(T1, "is it bailable?")[0] == "off" and fc.kw is None, "daily budget at its hard line: no rewrite call (the engine refuses the question anyway)")
cost_log.budget_state = _saved_bs
CA.client = _saved_client

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    W.log_turn("Earlier ...\n\nNow the person says: is it bailable?", {"turn": 2, "rewrite": "used", "folded": 1, "rewrite_inr": 0.25})
line = buf.getvalue().strip()
rec = json.loads(line.split(" ", 1)[1]) if line.startswith("CHAT_TURN ") else {}
check(rec.get("turn") == 2 and rec.get("of") == 8 and rec.get("mode") == "on" and len(rec.get("q") or "") == 12 and "bailable" not in line,
      f"the CHAT_TURN line: turn, limit, mode and a hash, never the text ({line[:120]})")

# ---------------------------------------------------------------- the page
SEEN = []


def stub(question, inline_domains=frozenset(), audience=None, channel=None):
    SEEN.append(question)
    cur = CA._extract_current_message(question)
    if cur.strip().lower() == "hello":
        return {"state": "unrelated"}
    return ans(f"ANSWER {len(SEEN)} to: {cur.splitlines()[0]}")


CA.answer_question = stub


def md(at):
    return [m.value for m in at.markdown]


def has(at, text):
    return any(text in v for v in md(at))


def btn(at, label):
    return [b for b in at.button if label in b.label]


def ask_top(at, text):
    at.text_area(key="text").set_value(text).run()
    btn(at, "Check my situation")[0].click().run()


def ask_followup(at, text):
    at.text_area(key="followup_text").set_value(text).run()
    btn(at, "Ask a follow-up")[0].click().run()


# unset: the page is exactly as before
os.environ.pop("CHAT_MODE", None)
SEEN.clear()
at = AppTest.from_file(APP, default_timeout=90).run()
ask_top(at, "my son was arrested for taking a bribe")
check(not at.exception and SEEN == ["my son was arrested for taking a bribe"], f"unset: the engine gets the question as typed ({SEEN}, exception={at.exception})")
check(not btn(at, "Ask a follow-up") and not btn(at, "Start a new question") and not has(at, "in this conversation"), "unset: no follow-up box, no 'Start a new question'")
check(has(at, "ANSWER 1 to: my son was arrested"), "unset: the answer is shown")

# fold: a conversation
os.environ["CHAT_MODE"] = "fold"
SEEN.clear()
at = AppTest.from_file(APP, default_timeout=90).run()
ask_top(at, "my son was arrested for taking a bribe")
check(not at.exception and SEEN == ["my son was arrested for taking a bribe"], "fold: the first question goes to the engine as typed")
check(btn(at, "Ask a follow-up") and btn(at, "Start a new question") and has(at, "Question 1 of 8 in this conversation"), "fold: the follow-up box appears under the first answer, 'Question 1 of 8'")
ask_followup(at, "is it bailable?")
check(not at.exception and len(SEEN) == 2 and CA._extract_current_message(SEEN[1]) == "is it bailable?" and "- The person asked: my son was arrested for taking a bribe" in SEEN[1],
      f"fold: the follow-up reaches the engine with the first question folded in ({SEEN[-1][:160]!r}, exception={at.exception})")
check(has(at, "Question 1 &middot; you asked") and has(at, "Question 2 &middot; you asked") and has(at, "ANSWER 1 to: my son") and has(at, "ANSWER 2 to: is it bailable?"),
      "fold: the page shows both questions, each with its own answer")
check(has(at, "Question 2 of 8 in this conversation") and at.text_area(key="followup_text").value == "", "fold: the counter moves on and the follow-up box is emptied")
check(at.session_state["answer_msg"] == "my son was arrested for taking a bribe", "fold: the box above still holds the first question, so the 'changed description' note does not fire")
check(not has(at, "You've changed"), "fold: no 'changed description' note after a follow-up")

ask_followup(at, "hello")
ask_followup(at, "what should I take to the lawyer?")
check(CA._extract_current_message(SEEN[-1]) == "what should I take to the lawyer?" and "- The person asked: hello" not in SEEN[-1] and "- The person asked: is it bailable?" in SEEN[-1],
      "fold: a small-talk turn is not folded into the next question")
for i in range(4):
    ask_followup(at, f"follow-up number {i + 5}")
check(len(at.session_state["chat_turns"]) == 8 and not btn(at, "Ask a follow-up") and has(at, "reached its limit of 8 questions"), "fold: after 8 questions the follow-up box is replaced by the limit note")
check(btn(at, "Start a new question"), "fold: 'Start a new question' is still offered at the limit")
btn(at, "Start a new question")[0].click().run()
check(not at.exception and "chat_turns" not in at.session_state and "answer" not in at.session_state and at.text_area(key="text").value == "",
      f"fold: 'Start a new question' forgets the conversation and empties the box (exception={at.exception})")

# a new question typed in the box above starts a new conversation
SEEN.clear()
at = AppTest.from_file(APP, default_timeout=90).run()
ask_top(at, "my brother was arrested at night")
ask_followup(at, "was that legal?")
ask_top(at, "my bank account was frozen")
check(SEEN[-1] == "my bank account was frozen" and len(at.session_state["chat_turns"]) == 1 and has(at, "Question 1 of 8 in this conversation"),
      "fold: a question from the box above starts a new conversation (no earlier messages, counter back to 1)")
check(not has(at, "ANSWER 1 to: my brother"), "fold: the old conversation is no longer shown")

# on: the rewrite reaches the engine
os.environ["CHAT_MODE"] = "on"
W._call_model = lambda prompt, current: (json.dumps({"follow_up": True, "standalone": "Is the offence of my son taking a bribe bailable?"}), 0.2)
SEEN.clear()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    at = AppTest.from_file(APP, default_timeout=90).run()
    ask_top(at, "my son was arrested for taking a bribe")
    ask_followup(at, "is it bailable?")
cur = CA._extract_current_message(SEEN[-1])
check(not at.exception and cur == "is it bailable?\n" + W.REWRITE_LEAD + "Is the offence of my son taking a bribe bailable?)", f"on: the follow-up and its standalone form reach the engine ({cur!r})")
lines = [l for l in buf.getvalue().splitlines() if l.startswith("CHAT_TURN ")]
recs = [json.loads(l.split(" ", 1)[1]) for l in lines]
check(len(recs) == 2 and recs[0]["rewrite"] == "first" and recs[1]["rewrite"] == "used" and recs[1]["turn"] == 2, f"on: one CHAT_TURN line per question ({[r.get('rewrite') for r in recs]})")
check(has(at, "Question 2 &middot; you asked") and not has(at, W.REWRITE_LEAD), "on: the page shows the person's own words, not the rewrite")

os.environ.pop("CHAT_MODE", None)
print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("all passed")
