"""
test_refusal_notes.py -- the Overruled Register's note on a question that cannot be answered here (2026-10-16, after situation exam run 3: 5 of the 12 questions that named an overruled case were
turned away with not a word about it). chat_assistant._attach_question_register_notes, the call in _answer_question_inner, the page (recourse_app.render_answer) and WhatsApp
(whatsapp_formatter.format_answer_for_whatsapp). Real register bundle (overruled_register/), the model replaced by a stub, no network, no cost. Run: python -X utf8 test_refusal_notes.py
"""
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ.pop("REGISTER_HOOKS", None)
os.environ.pop("RESPONSE_STYLE", None)
from streamlit.testing.v1 import AppTest

import chat_assistant as CA
import register_hooks as RH
import whatsapp_formatter as WF

FAILURES = []
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


RH._STATE.clear()

Q_NAMED = ("My brother was convicted of sedition by a TADA Designated Court and given life imprisonment. His lawyer is relying on Bilal Ahmed Kaloo v. State of Andhra Pradesh (1997) for the "
           "appeal. How does that help him?")
Q_NOYEAR = "Our lawyer cites Naresh Kumar Yadav v. Ravindra Kumar to ask that the bail be cancelled. Is that a good ground?"
Q_FIRST = "My lawyer cites Mohan Lal v. State for the appeal. Does it help?"
Q_PLAIN = "My corruption case has been in the trial court for 9 years. Is there a fixed time limit after which the trial must be dropped?"

# ---- the function ----
for st_ in CA._REFUSAL_NOTE_STATES:
    res = CA._attach_question_register_notes({"state": st_}, question=Q_NAMED)
    check(len(res.get("register_notes", [])) == 1 and res["register_notes"][0].startswith("Bilal Ahmed Kaloo v. State of Andhra Pradesh (1997) was overruled by")
          and "register_possible" not in res and "register_not_checked" not in res, f"{st_}: the note for the case the question names is attached (and no 'not checked' sentence)")
check(CA._REFUSAL_NOTE_STATES == ("adjacent_uncovered", "covered_elsewhere_in_tool", "no_match", "classifier_unavailable", "retrieval_unavailable"), "the five non-answer states that get the note")

res = CA._attach_question_register_notes({"state": "adjacent_uncovered"}, question=Q_NOYEAR)
check("register_notes" not in res and len(res.get("register_possible", [])) == 1 and res["register_possible"][0].startswith("Possible match"), "level 2 (both names, no year) on a refusal: a 'Possible match' note")
res = CA._attach_question_register_notes({"state": "no_match"}, question=Q_FIRST)
check(len(res.get("register_possible", [])) == 1 and "Mohan Lal" in res["register_possible"][0], "level 3 (first party only) on a refusal: the list of the register's decisions")
res = CA._attach_question_register_notes({"state": "adjacent_uncovered"}, question=Q_PLAIN)
check("register_notes" not in res and "register_possible" not in res, "a refused question that names no register case gets nothing")

for st_ in ("unrelated", "budget_paused", "single_match", "conflicting_matches", "error"):
    res = CA._attach_question_register_notes({"state": st_}, question=Q_NAMED)
    check("register_notes" not in res and "register_possible" not in res, f"{st_}: left alone")
check(CA._attach_question_register_notes("not a dict", question=Q_NAMED) == "not a dict", "bad input does not raise")
check("register_notes" not in CA._attach_question_register_notes({"state": "adjacent_uncovered"}), "without a question nothing is added")
check("register_notes" not in CA._attach_question_register_notes({"state": "adjacent_uncovered"}, question=""), "an empty question adds nothing")
os.environ["REGISTER_HOOKS"] = "off"
check("register_notes" not in CA._attach_question_register_notes({"state": "adjacent_uncovered"}, question=Q_NAMED), "REGISTER_HOOKS=off: nothing is added")
os.environ.pop("REGISTER_HOOKS", None)

# ---- through the public path (the classifier and retrieval replaced by a stub) ----
_core = CA._answer_question_core
try:
    CA._answer_question_core = lambda question, inline_domains=frozenset(): {"state": "adjacent_uncovered", "reasoning": "A TADA appeal."}
    out = CA._answer_question_inner(Q_NAMED)
    check(out["state"] == "adjacent_uncovered" and len(out.get("register_notes", [])) == 1, "_answer_question_inner: the refusal carries the note")
    CA._answer_question_core = lambda question, inline_domains=frozenset(): {"state": "unrelated"}
    out = CA._answer_question_inner(Q_NAMED)
    check("register_notes" not in out, "_answer_question_inner: 'unrelated' carries none")
    CA._answer_question_core = lambda question, inline_domains=frozenset(): {"state": "no_match"}
    out = CA._answer_question_inner(Q_PLAIN)
    check({k: v for k, v in out.items() if k != "act_notice"} == {"state": "no_match"}, "_answer_question_inner: a refusal about a question that names no register case is unchanged (the Act Directory's notice, 2026-10-17, is separate: Q_PLAIN says 'corruption case')")
finally:
    CA._answer_question_core = _core

# ---- WhatsApp ----
NOTE = "Bilal Ahmed Kaloo v. State of Andhra Pradesh (1997) was overruled by State through Superintendent of Police, CBI/SIT v. Nalini and Others (1999)."
msgs = WF.format_answer_for_whatsapp({"state": "adjacent_uncovered", "reasoning": "A TADA appeal.", "register_notes": [NOTE]})
check(len(msgs) == 3 and msgs[0].startswith("This looks like it's related to law") and msgs[1].startswith("*Currency notes*") and NOTE in msgs[1] and msgs[2] == WF._CONSULT_LINE,
      "WhatsApp: the note comes before the closing 'consult a lawyer' line")
msgs = WF.format_answer_for_whatsapp({"state": "no_match", "register_possible": ["Possible match: X"]})
check(len(msgs) == 3 and "Possible match: X" in msgs[1] and msgs[2] == WF._CONSULT_LINE, "WhatsApp: no_match carries a possible-match note too")
msgs = WF.format_answer_for_whatsapp({"state": "classifier_unavailable", "register_notes": [NOTE]})
check(len(msgs) == 2 and NOTE in msgs[1], "WhatsApp: a technical-failure message with no closing line gets the note at the end")
check(WF.format_answer_for_whatsapp({"state": "adjacent_uncovered", "reasoning": "x"}) == ["This looks like it's related to law, but it's outside what I can confidently answer right now.\n\nx", WF._CONSULT_LINE],
      "WhatsApp: a refusal without notes is exactly as before")
check(WF.format_answer_for_whatsapp({"state": "unrelated", "register_notes": [NOTE]}) == WF.format_answer_for_whatsapp({"state": "unrelated"}), "WhatsApp: 'unrelated' never shows a note")
ans = WF.format_answer_for_whatsapp({"state": "single_match", "response_text": "Short answer.\n\nMore.", "register_notes": [NOTE]})
check(sum(1 for m in ans if NOTE in m) == 1, "WhatsApp: an answer still shows its note once (the answer path is unchanged)")

# ---- the page ----
SEEN = {}


def stub(question, inline_domains=frozenset(), audience=None, channel=None):
    mode = os.environ.get("TEST_MODE")
    if mode == "refused_with_note":
        return {"state": "adjacent_uncovered", "reasoning": "A TADA appeal.", "register_notes": [NOTE]}
    if mode == "no_match_possible":
        return {"state": "no_match", "register_possible": ["Possible match: the case you named may be Naresh Kumar Yadav v. Ravindra Kumar (2008), which is reported as overruled."]}
    if mode == "refused_plain":
        return {"state": "adjacent_uncovered", "reasoning": "A civil suit."}
    if mode == "covered_elsewhere":
        return {"state": "covered_elsewhere_in_tool", "redirect_domain": "ndps", "register_notes": [NOTE]}
    return {"state": "single_match", "response_text": "Short answer.", "matches": [], "situation_detected": False}


CA.answer_question = stub


def md_values(at):
    return [m.value for m in at.markdown]


def ask(mode):
    os.environ["TEST_MODE"] = mode
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.text_area(key="text").set_value("My brother was convicted under TADA").run()
    [b for b in at.button if "Check my situation" in b.label][0].click().run()
    return at


at = ask("refused_with_note")
vals = md_values(at)
check(not at.exception and any("Recourse can't help with this one" in v for v in vals), "page: the refusal is still shown")
check(any("Currency notes (checked by code, not by the model)" in v for v in vals) and any(NOTE in v for v in vals), f"page: the register note is shown under the refusal (exception={at.exception})")
at = ask("no_match_possible")
vals = md_values(at)
check(not at.exception and any("Not enough to go on yet" in v for v in vals) and any("Possible match: the case you named" in v for v in vals), "page: no_match shows the possible-match note")
at = ask("covered_elsewhere")
vals = md_values(at)
check(not at.exception and any("That's a different kind of matter" in v for v in vals) and any(NOTE in v for v in vals), "page: the 'different kind of matter' redirect also shows the note")
at = ask("refused_plain")
vals = md_values(at)
check(not at.exception and any("Recourse can't help with this one" in v for v in vals) and not any("Currency notes" in v for v in vals), "page: a refusal without notes shows no currency box")
at = ask("answered")
vals = md_values(at)
check(not at.exception and not any("Currency notes" in v for v in vals), "page: an answer without notes is unchanged")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
