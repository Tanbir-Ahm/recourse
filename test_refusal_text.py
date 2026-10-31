"""
test_refusal_text.py -- the words for a question the site cannot answer live in one module (refusal_text.py), used by the Streamlit page and the API (2026-10-23; FOLLOW_UPS 2bz). Free and offline, the engine replaced by a stub.
Proves: every non-answer state has a title, a plain-text body and (where the page had one) a footer; an answer has no notice; the text holds no HTML; the page's rendered text for all 12 refusal cases is IDENTICAL to a golden copy captured from the page
BEFORE it was changed to use this module (refusal_page_golden.json); the API's reply (/api/ask and a saved chat's messages) carries the same notice, so `text: null` is no longer all a front end gets.
Run: python -X utf8 test_refusal_text.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("REGISTER_HOOKS", "RESPONSE_STYLE", "CHAT_MODE", "API_ACCESS_TOKEN", "DATABASE_URL"):
    os.environ.pop(_v, None)

import refusal_text as RT

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ------------------------------------------------------------ the module
check(RT.notice({"state": "single_match"}) is None and RT.notice({"state": "conflicting_matches"}) is None and RT.notice({}) is None and RT.notice("x") is None and RT.notice(None) is None, "an answer, an empty result and non-results have no notice")
states = ["budget_paused", "covered_elsewhere_in_tool", "adjacent_uncovered", "unrelated", "no_match", "classifier_unavailable", "retrieval_unavailable", "something_new"]
for st_ in states:
    n = RT.notice({"state": st_, "redirect_domain": "freeze", "reasoning": "A civil suit."})
    check(n["state"] == st_ and n["body"] and "{" not in n["body"] and "<" not in n["body"] and "&" not in n["body"] and (n["title"] or st_ == "budget_paused"), f"{st_}: a plain-text body, no HTML, no placeholder left, a title")
check(RT.notice({"state": "budget_paused"})["label"] == "Daily limit reached" and RT.notice({"state": "no_match"})["label"] == "Out of scope", "the two labels")
n = RT.notice({"state": "covered_elsewhere_in_tool", "redirect_domain": "cheque_bounce"})
check(n["topic"] == "a bounced cheque" and n["body"].startswith("This looks like it is about a bounced cheque. ") and "{topic}" in n["body_template"], "a redirect names its topic (and the template keeps the place for it)")
check(RT.notice({"state": "covered_elsewhere_in_tool", "redirect_domain": "ndps"})["topic"] == "this" and RT.notice({"state": "covered_elsewhere_in_tool"})["topic"] == "this", "an unlisted or missing topic says 'this'")
n = RT.notice({"state": "adjacent_uncovered", "reasoning": "A TADA appeal."})
check(n["reasoning"] == "A TADA appeal." and n["footer"].startswith("For this kind of question") and RT.notice({"state": "adjacent_uncovered"})["reasoning"] is None and RT.notice({"state": "adjacent_uncovered", "reasoning": 5})["reasoning"] is None, "the engine's reason is passed on only when it is text; the footer is there")
check(RT.notice({"state": "unrelated"})["footer"] is None, "only 'adjacent_uncovered' has a footer (as the page always had)")
check("—" in RT.notice({"state": "no_match"})["body"] and "—" in RT.notice({"state": "adjacent_uncovered"})["body"], "the dashes are real dashes in the plain text")

# ------------------------------------------------------------ the page: identical to what it showed before
from streamlit.testing.v1 import AppTest

import chat_assistant as CA
APP = os.path.join(HERE, "recourse_app.py")
RES = {
    "budget_paused": {"state": "budget_paused"},
    "covered_freeze": {"state": "covered_elsewhere_in_tool", "redirect_domain": "freeze"},
    "covered_cheque": {"state": "covered_elsewhere_in_tool", "redirect_domain": "cheque_bounce"},
    "covered_dv": {"state": "covered_elsewhere_in_tool", "redirect_domain": "domestic_violence"},
    "covered_other": {"state": "covered_elsewhere_in_tool", "redirect_domain": "ndps"},
    "adjacent_reason": {"state": "adjacent_uncovered", "reasoning": "A civil suit <b>x</b>."},
    "adjacent_plain": {"state": "adjacent_uncovered"},
    "unrelated": {"state": "unrelated"},
    "no_match": {"state": "no_match"},
    "classifier_unavailable": {"state": "classifier_unavailable"},
    "retrieval_unavailable": {"state": "retrieval_unavailable"},
    "weird": {"state": "something_new"},
}
golden = json.load(open(os.path.join(HERE, "refusal_page_golden.json"), encoding="utf-8"))
check(set(golden) == set(RES), "the golden copy covers all 12 cases")
for name, res in RES.items():
    CA.answer_question = lambda q, inline_domains=frozenset(), audience=None, channel=None, _r=res: dict(_r)
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.text_area(key="text").set_value("My brother was arrested").run()
    [b for b in at.button if "Check my situation" in b.label][0].click().run()
    import build_info
    got = [m.value for m in at.markdown if build_info.footer_text() not in m.value]                  # the quiet build line at the foot of the page (build_info.py, 2026-10-31) is not a refusal text
    check(not at.exception and got == golden[name], f"page, {name}: the rendered text is identical to the golden copy" + ("" if got == golden[name] else f" (first difference: {[ (a, b) for a, b in zip(golden[name], got) if a != b][:1]})"))

# ------------------------------------------------------------ the API carries the same words
from fastapi.testclient import TestClient

from api import engine_adapter
from api.main import app
os.environ["API_ACCESS_TOKEN"] = "k" * 32


class Eng:
    res = {}

    def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None):
        return dict(self.res)


E = Eng()
engine_adapter.set_engine(E)
engine_adapter.reset_runner(engine_adapter.Runner(2, 2))
c = TestClient(app)
E.res = {"state": "adjacent_uncovered", "reasoning": "An employment dispute."}
r = c.post("/api/ask", json={"question": "Can my employer fire me without notice?"}, headers={"X-API-Key": "k" * 32}).json()
check(r["text"] is None and r["notice"] == RT.notice(E.res) and r["notice"]["title"] == "Recourse can't help with this one" and r["notice"]["reasoning"] == "An employment dispute.", "/api/ask: a refusal has no text but carries the notice, the same one the page shows")
E.res = {"state": "single_match", "response_text": "An answer."}
r = c.post("/api/ask", json={"question": "What is bail?"}, headers={"X-API-Key": "k" * 32}).json()
check(r["text"] == "An answer." and r["notice"] is None, "/api/ask: an answer has text and no notice")
from api.routers.chats import message_view
import types
mk = lambda role, result: types.SimpleNamespace(id="i", seq=1, role=role, content="c", result=result, state=None, created_at=None)
check(message_view(mk("assistant", {"state": "no_match"}))["notice"]["title"] == "Not enough to go on yet" and message_view(mk("user", None))["notice"] is None and message_view(mk("assistant", {"state": "single_match"}))["notice"] is None,
      "a saved chat's messages carry the notice for a refusal only")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
