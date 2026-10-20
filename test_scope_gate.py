"""
test_scope_gate.py -- SCOPE_GATE (2026-10-16, owner's instruction: "the site should accept all topics now"). Default 'on' = today's behaviour; 'open' lifts the topic bar: a question the classifier calls
'adjacent_uncovered' goes through the in_scope pipeline, with a scope note in the prompt, a fixed notice with the answer, a wider-search-only answer when the library has nothing and SCI_SEARCH_MODE=feed,
and one SCOPE_OPEN log line. 'unrelated' (not a legal question) and the inline domains are untouched. The classifier, retrieval and the model are replaced by stubs: offline, free.
Run: python -X utf8 test_scope_gate.py
"""
import contextlib
import io
import json
import os
import sys
import types

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ.pop("SCOPE_GATE", None)
os.environ.pop("REGISTER_HOOKS", None)
os.environ.pop("SCI_SEARCH_MODE", None)
from streamlit.testing.v1 import AppTest

import chat_assistant as CA
import sci_search_tier as ST
import whatsapp_formatter as WF

FAILURES = []
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recourse_app.py")


def _sans_act(res):
    """The Act Directory's notice (act_directory.py, 2026-10-16) is additive and independent of SCOPE_GATE: a question that names TADA carries it on every state. These checks are about the gate alone."""
    return {k: v for k, v in res.items() if k != "act_notice"}



def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


Q_TADA = "My brother was sentenced by a TADA Designated Court. What can he argue in his appeal?"
Q_PLAIN = "Can the police arrest me without telling me why?"
CATEGORY = {"v": ("adjacent_uncovered", "A TADA appeal is outside BNS/BNSS.", None)}
RETRIEVAL = {"v": {"state": "no_match"}}
CALLS = {"single": 0, "gen": []}
FEED = {"mode": "off", "block": ""}


def fake_classify(question):
    return CATEGORY["v"]


def fake_retrieval(current_message, full_question, **kw):
    return RETRIEVAL["v"]


def fake_single(question, matches):
    CALLS["single"] += 1
    ST._LOCAL.cases = [{"case_name": n} for n in FEED.get("cases", ())]       # what feed_block leaves behind for fed_case_names()
    return {"state": "single_match", "matches": matches, "response_text": "Library answer.", "situation_detected": False, "from_cache": False, "unverified_related_judgments": []}


def fake_generate(question, retrieved_text, **kw):
    CALLS["gen"].append((question, retrieved_text, kw))
    return "Wider answer."


CA.classify_scope = fake_classify
CA._find_relevant_sections_for_turn = fake_retrieval
CA._answer_single_match = fake_single
CA.generate_grounded_response = fake_generate
ST.mode = lambda: FEED["mode"]
ST.feed_block = lambda q: FEED["block"]


def run(question=Q_TADA, category=("adjacent_uncovered", "A TADA appeal is outside BNS/BNSS.", None), retrieval=None, gate=None, feed=("off", ""), fed_cases=()):
    CATEGORY["v"] = category
    RETRIEVAL["v"] = retrieval or {"state": "no_match"}
    FEED["mode"], FEED["block"], FEED["cases"] = feed[0], feed[1], tuple(fed_cases)
    CALLS["single"], CALLS["gen"] = 0, []
    if gate is None:
        os.environ.pop("SCOPE_GATE", None)
    else:
        os.environ["SCOPE_GATE"] = gate
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = CA._answer_question_inner(question)
    lines = [l for l in buf.getvalue().splitlines() if l.startswith("SCOPE_OPEN ")]
    return res, [json.loads(l[len("SCOPE_OPEN "):]) for l in lines]


# ---- the setting ----
for v, want in (("open", True), (' "OPEN" ', True), ("on", False), ("", False), ("banana", False), (None, False)):
    if v is None:
        os.environ.pop("SCOPE_GATE", None)
    else:
        os.environ["SCOPE_GATE"] = v
    check(CA._scope_gate_open() is want, f"SCOPE_GATE={v!r}: {'open' if want else 'the bar stays'}")

# ---- default (unset, or 'on'): exactly today's behaviour ----
res, log = run()
check(_sans_act(res) == {"state": "adjacent_uncovered", "reasoning": "A TADA appeal is outside BNS/BNSS."} and log == [] and CALLS["single"] == 0, "default: an adjacent_uncovered question is turned away exactly as before, no log line")
res, log = run(gate="on")
check(res["state"] == "adjacent_uncovered" and log == [], "SCOPE_GATE=on: the same")
res, log = run(category=("unrelated", "not legal", None), gate="open")
check(res == {"state": "unrelated"} and log == [], "open: a question that is not a legal question is still turned away")
res, log = run(category=("covered_elsewhere_in_tool", "NDPS", "ndps"), gate="open")
check(res["state"] == "covered_elsewhere_in_tool" and res["redirect_domain"] == "ndps" and log == [], "open: the inline-domain route is untouched")
res, log = run(question=Q_PLAIN, category=("in_scope", "arrest", None), retrieval={"state": "no_match"}, gate="open", feed=("feed", "FEED"))
check(res == {"state": "no_match"} and log == [] and CALLS["gen"] == [], "open: an ordinary in_scope question with no match is still 'no_match' (no wider-search answer, no log line)")

# ---- open: the library has a match ----
res, log = run(retrieval={"state": "single_match", "matches": [{"section_number": "482", "act": "BNSS", "text": "x"}], "judgment_matches": []}, gate="open")
check(res["state"] == "single_match" and res["response_text"] == "Library answer." and CALLS["single"] == 1, "open: the question goes through the in_scope pipeline (library answer)")
check(res.get("outside_scope_note") == CA.OUTSIDE_SCOPE_NOTE and "has not checked in depth" in res["outside_scope_note"], "open: the answer carries the fixed notice")
check(len(log) == 1 and log[0]["state"] == "single_match" and log[0]["wider_only"] is False and "TADA" in log[0]["reasoning"] and len(log[0]["q"]) == 12 and Q_TADA not in json.dumps(log), "open: one SCOPE_OPEN line, with a hash of the question and not the question itself")
check(log[0]["act"] == ["tada_1987"] and res["act_notice"]["kind"] == "opened" and res["act_notice"]["acts"] == ["tada_1987"], "open: the SCOPE_OPEN line names the Act directory entry the question names (ids only), and the answer carries the Act notice of kind 'opened'")

# the log line also says what the library and the wider search each supplied (names and scores only), so that an irrelevant library hit can be seen in the log
NALSA_NAME = "National Legal Services Authority v Union of India"
LIB = {"state": "single_match", "matches": [{"section_number": "482", "act": "BNSS", "text": "x"}, {"section_number": "482", "act": "BNSS", "text": "again"}, {"section_number": "35", "act": "BNSS", "text": "y"}],
       "judgment_matches": [{"type": "judgment", "case_name": NALSA_NAME, "score": 0.4123}, {"type": "judgment", "case_name": "Arnesh Kumar v State of Bihar", "score": 0.4551, "retrieval": "lexical"},
                            {"type": "judgment", "case_name": NALSA_NAME, "score": 0.401}]}
res, log = run(retrieval=LIB, gate="open", fed_cases=["State of Tamil Nadu Through Superintendent of Police,Cbi/Sit v. Nalini and 25 Others"])
lib = log[0]["library"]
check(lib["judgments"] == [{"case": "Arnesh Kumar v State of Bihar", "score": 0.455, "via": "lexical"}, {"case": NALSA_NAME, "score": 0.412}] and lib["sections"] == ["BNSS 482", "BNSS 35"],
      f"SCOPE_OPEN names the library's judgments (best score first, one entry per case, how a keyword hit was found) and its sections ({lib})")
check(log[0]["wider"] == ["State of Tamil Nadu Through Superintendent of Police,Cbi/Sit v. Nalini and 25 Others"], "...and the wider-search cases the model was handed")
check(Q_TADA not in json.dumps(log) and "text" not in json.dumps(lib), "...without the question and without any passage text")
res, log = run(retrieval={"state": "single_match", "matches": [], "judgment_matches": []}, gate="open")
check(log[0]["library"] == {"judgments": [], "sections": []} and log[0]["wider"] == [], "an opened question with nothing from the library or the search logs empty lists")
many = {"state": "single_match", "matches": [], "judgment_matches": [{"type": "judgment", "case_name": f"Case {i} v State", "score": 0.5 - i / 100} for i in range(12)]}
res, log = run(retrieval=many, gate="open")
check(len(log[0]["library"]["judgments"]) == 8 and log[0]["library"]["judgments"][0]["case"] == "Case 0 v State", "at most eight judgments are named")
res, log = run(question=Q_PLAIN, category=("adjacent_uncovered", "A special law.", None), retrieval={"state": "single_match", "matches": [], "judgment_matches": []}, gate="open")
check(log[0]["act"] == [] and "act_notice" not in res, "open: a question that names no Act of the directory logs act: [] and gets no Act notice")
check(CA._library_summary(None) == {"judgments": [], "sections": []} and CA._library_summary("not a list") == {"judgments": [], "sections": []} and CA._library_summary([None, 3, {"type": "judgment"}]) == {"judgments": [], "sections": []},
      "_library_summary never raises on odd input")

# ---- open: nothing in the library ----
res, log = run(gate="open")
check(_sans_act(res) == {"state": "no_match"} and len(log) == 1 and log[0]["state"] == "no_match" and "outside_scope_note" not in res, "open, search off: nothing in the library ends as 'no_match' (the same as an in_scope question), and is logged")
res, log = run(gate="open", feed=("shadow", ""))
check(res["state"] == "no_match", "open, SCI_SEARCH_MODE=shadow: still 'no_match' (the passages are not given to the model)")
res, log = run(gate="open", feed=("feed", ""))
check(res["state"] == "no_match" and CALLS["gen"] == [], "open, feed mode but the search found nothing: 'no_match', and the model is not called")
res, log = run(gate="open", feed=("feed", "WIDER PASSAGES"))
check(res["state"] == "single_match" and res["response_text"] == "Wider answer." and res["matches"] == [] and res["situation_detected"] is False
      and res.get("outside_scope_note") == CA.OUTSIDE_SCOPE_NOTE and len(CALLS["gen"]) == 1 and CALLS["gen"][0][1] == "", "open, feed mode with passages: the answer is written from the wider search alone, with the notice")
check(len(log) == 1 and log[0]["wider_only"] is True and log[0]["state"] == "single_match", "...and the log line says so")
CA.generate_grounded_response = lambda q, rt, **kw: None
res, log = run(gate="open", feed=("feed", "WIDER PASSAGES"))
check(_sans_act(res) == {"state": "no_match"}, "open, feed mode, but the answer is withheld by a check: 'no_match', as before")
CA.generate_grounded_response = fake_generate
res, log = run(gate="on", feed=("feed", "WIDER PASSAGES"))
check(res["state"] == "adjacent_uncovered" and CALLS["gen"] == [], "SCOPE_GATE=on with feed on: the bar stays")

# ---- a curated override still answers even when nothing else matched ----
res, log = run(retrieval={"state": "no_match"}, gate="open", question="What does Section 66A of the IT Act say?")
check(res["state"] in ("single_match", "no_match"), "an override-only question under open does not fail")

# ---- the prompt ----
sent = {}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Short answer.")], stop_reason="end_turn", usage=None)


real_generate = None
import importlib
CA2 = importlib.reload(CA)             # the real generate_grounded_response again (the stubs above are gone)
CA2.client = types.SimpleNamespace(messages=_Msgs())
os.environ["SCOPE_GATE"] = "open"
CA2._open_topic_reset()
txt = CA2.generate_grounded_response(Q_TADA, "[BNSS Section 482]\nText.", matches=[])
check(txt and "Scope note -- this question is outside the criminal-procedure library" not in sent["prompt"], "open, but the bar was not opened for this question: no scope note")
CA2._open_topic_start(Q_TADA, "x")
sent.clear()
txt = CA2.generate_grounded_response(Q_TADA, "[BNSS Section 482]\nText.", matches=[])
check(txt and "Scope note -- this question is outside the criminal-procedure library" in sent["prompt"] and sent["prompt"].index("Text.") < sent["prompt"].index("Scope note"), "open, bar opened for this question: the scope note follows the material")
check("never adding a section number, case holding, punishment or Act name that is not in the material" in sent["prompt"], "the scope note keeps the Hard rules in force")
check("do not present a BNS or BNSS section as the governing provision" in sent["prompt"] and "route of appeal" in sent["prompt"] and "for example a general appeal provision" in sent["prompt"]
      and "the governing statute is not in the material" in sent["prompt"], "the scope note says not to stretch a BNS or BNSS section over a matter under another Act (production 2026-10-16: 'appeal under Section 420 of the BNSS' for a TADA conviction)")
check("## Hard rules (never break)" in sent["prompt"] and "Use ONLY the legal information given below" in sent["prompt"], "the Hard rules block is still in the prompt, unchanged")
os.environ.pop("SCOPE_GATE")
sent.clear()
txt = CA2.generate_grounded_response(Q_TADA, "[BNSS Section 482]\nText.", matches=[])
check(txt and "Scope note" not in sent["prompt"], "SCOPE_GATE off again: no scope note, even with the marker set")
CA2._open_topic_start(Q_TADA, "x")
os.environ["SCOPE_GATE"] = "open"
sent.clear()
CA2.generate_grounded_response("A different question", "[BNSS Section 35]\nText.", matches=[])
check("Scope note" not in sent["prompt"], "the marker belongs to its own question: another question gets no scope note")
CA2._open_topic_reset()
os.environ.pop("SCOPE_GATE", None)

# ---- the templates are untouched (test_answer_style_v3.py asserts the Hard rules block is identical in every style) ----
check("Never add a section number, case holding, punishment, or the NAME of any act/law from your own knowledge" in CA2.RESPONSE_GENERATION_PROMPT, "the base template's Hard rules are in place")

# ---- the page and WhatsApp ----
CA.answer_question = lambda question, inline_domains=frozenset(), audience=None, channel=None: {
    "state": "single_match", "response_text": "Short answer.", "matches": [], "situation_detected": False, "outside_scope_note": CA2.OUTSIDE_SCOPE_NOTE}
at = AppTest.from_file(APP, default_timeout=90).run()
at.text_area(key="text").set_value("My brother was sentenced under TADA").run()
[b for b in at.button if "Check my situation" in b.label][0].click().run()
vals = [m.value for m in at.markdown]
check(not at.exception and any(CA2.OUTSIDE_SCOPE_NOTE in v for v in vals), f"page: the fixed notice is shown with the answer (exception={at.exception})")
i_note = next((i for i, v in enumerate(vals) if CA2.OUTSIDE_SCOPE_NOTE in v), -1)
i_ans = next((i for i, v in enumerate(vals) if "Short answer." in v), -1)
check(0 <= i_note < i_ans, "page: the notice comes before the answer")
msgs = WF.format_answer_for_whatsapp({"state": "single_match", "response_text": "Short answer.\n\nMore.", "outside_scope_note": CA2.OUTSIDE_SCOPE_NOTE})
check(msgs[0] == CA2.OUTSIDE_SCOPE_NOTE and "Short answer." in msgs[1], "WhatsApp: the notice is the first message")
check(CA2.OUTSIDE_SCOPE_NOTE not in "".join(WF.format_answer_for_whatsapp({"state": "single_match", "response_text": "Short answer."})), "WhatsApp: no notice on an ordinary answer")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
