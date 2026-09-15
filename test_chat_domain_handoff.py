
"""
test_chat_domain_handoff.py

Regression suite for the chat-to-domain-flow handoff, 2026-09-01.

BACKGROUND: the "I just want to ask something in my own words" chat
feature used to dead-end on bank-freeze/cheque-bounce questions with a
generic "go upload a document" message -- even though a BETTER, no-
document-needed option (the dedicated free-text interview flows in
freeze_interview_flow.py / cheque_bounce_interview_flow.py, which give
a real Compliant/Non-Compliant verdict, not just an explanation) was
already sitting in the same mode-selector menu. This suite covers the
one-click handoff that now carries the user's already-typed question
straight into the right flow instead.

REAL BUG CAUGHT WHILE BUILDING THIS (kept here as the regression it
is): calling the handoff logic directly from the normal script body
raises StreamlitAPIException ("st.session_state.mode cannot be
modified after the widget with key 'mode' is instantiated"), since the
mode radio (key="mode") has already rendered earlier in the same
script pass. Must be an on_click callback. A SECOND bug caught the
same way: the callback originally re-appended the chat reply into
chat_history, which run_chat_flow() had already appended on the same
pass that rendered the button -- producing a duplicate identical
assistant turn every time the button was clicked.

ADDED 2026-09-01 (chat-quality plan Phase 3/4): a third handoff domain,
"arrest". Unlike freeze/cheque, an arrest question stays classified
in_scope and STILL gets a full chat answer -- the handoff button is
offered ALONGSIDE it, driven by answer_question()'s new
situation_detected flag (True when the answer opens with the "Right
now" block the prompt uses for questions describing something that
already happened). interview_flow.py's process_turn has a richer state
machine than freeze/cheque's, so _handoff_to_domain_flow special-cases
this domain via the shared _arrest_turn_reply() helper -- this suite's
arrest case is the regression guard for that path and for the
_handoff_to_domain_flow refactor that introduced the branch.

COST NOTE: unlike this project's other test_*.py suites, the AppTest
cases below make REAL LLM calls (classify_scope, process_turn's
extraction, and -- for the arrest case -- the full chat answer +
offence identification) -- there is no way to test the actual handoff
wiring without exercising the real chat pipeline. Kept deliberately
small (3 end-to-end cases) to bound cost. The classify_scope unit
checks below also cost real API calls, one per question.

Run with: python test_chat_domain_handoff.py
"""

import sys

from chat_assistant import classify_scope, answer_question
from streamlit.testing.v1 import AppTest

APP_PATH = r"C:\Users\reeti\OneDrive\Documents\My Project\app.py"

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- classify_scope: redirect_domain is populated correctly ----

category, reasoning, redirect_domain = classify_scope(
    "my bank account got frozen by the police and nobody told me why"
)
check(category == "covered_elsewhere_in_tool", "freeze question classified as covered_elsewhere_in_tool")
check(redirect_domain == "freeze", "freeze question's redirect_domain is 'freeze'")

category, reasoning, redirect_domain = classify_scope(
    "I got a legal notice saying my cheque bounced, what happens now"
)
check(category == "covered_elsewhere_in_tool", "cheque-bounce question classified as covered_elsewhere_in_tool")
check(redirect_domain == "cheque_bounce", "cheque-bounce question's redirect_domain is 'cheque_bounce'")

category, reasoning, redirect_domain = classify_scope(
    "police came to my house and arrested me directly saying that i stole a goat"
)
check(category == "in_scope", "an in-scope arrest question is still classified as in_scope")
check(redirect_domain is None, "redirect_domain is None for an in_scope question, never guessed")

# REGRESSION TEST (2026-09-05, caught via live user testing after Phase
# 3b): SCOPE_CLASSIFIER_PROMPT's new IT-Act paragraph ended with "...stays
# adjacent_uncovered UNLESS the question is PURELY about arrest/detention/
# remand PROCEDURE" -- a real LOC/transit-remand detention question that
# also mentions an unlisted cyber-offence (a deleted Twitter post) as
# BACKGROUND, not as its own question, got misclassified adjacent_uncovered
# some real fraction of the time, contradicting the already-proven
# detention/production/remand paragraph one above it (which says this
# exact fact pattern IS in_scope regardless of the underlying offence).
# Fixed by rewording that closing sentence to explicitly defer to the
# backstory/procedure rule instead of re-litigating it with a stricter
# "purely about" phrasing. Confirmed via a real 20/20 sample after the
# fix (was intermittently failing before, at roughly 1-in-12 in one
# sample) -- a single call here still carries some inherent LLM
# non-determinism, same caveat as every other classify_scope check in
# this file, but should now pass reliably.
category, reasoning, redirect_domain = classify_scope(
    "\U0001F6A8 URGENT LEGAL HELP NEEDED \U0001F6A8\n"
    "I have been detained by Immigration at Delhi IGI Airport due to a Look Out Circular (LOC) "
    "issued by the Chennai Cyber Crime / Tamil Nadu Police regarding a X Twitter Post in June, "
    "which is already deleted.\n"
    "We need a criminal defense lawyer in Delhi/NCR who can immediately reach the IGI Airport "
    "Police Station or Patiala House Court to handle the situation and contest the upcoming "
    "transit remand.\n"
    "Please amplify and tag any available criminal lawyers or legal aid networks."
)
check(category == "in_scope",
      f"LOC/transit-remand detention question (Twitter post mentioned only as background) is "
      f"in_scope, not adjacent_uncovered -- got {category!r} ({reasoning!r})")

# REGRESSION TEST (2026-09-15, caught via live end-to-end testing of the
# domestic_violence domain): a question describing EXACTLY the S. Vanitha
# v Deputy Commissioner fact pattern -- in-laws using the Senior Citizens
# Act to evict a daughter-in-law -- was classified adjacent_uncovered
# ("a civil property/residence dispute involving the Senior Citizens Act")
# instead of covered_elsewhere_in_tool/domestic_violence, even though this
# is precisely the scenario the 6th PWDVA judgment anchor exists for.
# SCOPE_CLASSIFIER_PROMPT's PWDVA paragraph only listed "hit, threatened,
# thrown out, denied money" as trigger fact patterns and never mentioned
# the Senior Citizens Act angle, so the classifier reasoned from the
# Act named in the question rather than the underlying PWDVA remedy.
# Fixed by explicitly naming this fact pattern in that paragraph.
category, reasoning, redirect_domain = classify_scope(
    "My husband's parents are trying to evict me from the house using the senior citizens act, "
    "is that allowed?"
)
check(category == "covered_elsewhere_in_tool",
      f"Senior-Citizens-Act eviction question (S. Vanitha fact pattern) is covered_elsewhere_in_tool, "
      f"not adjacent_uncovered -- got {category!r} ({reasoning!r})")
check(redirect_domain == "domestic_violence",
      f"Senior-Citizens-Act eviction question's redirect_domain is 'domestic_violence' -- got {redirect_domain!r}")

# ---- answer_question: redirect_domain propagates into the returned dict ----

result = answer_question("my bank account got frozen by the police and nobody told me why")
check(result["state"] == "covered_elsewhere_in_tool", "answer_question returns covered_elsewhere_in_tool for a freeze question")
check(result.get("redirect_domain") == "freeze", "answer_question propagates redirect_domain='freeze'")

# ---- answer_question: situation_detected drives the arrest handoff ----

result = answer_question("the police took me to the station this morning without telling me what i had done")
check(result["state"] in ("single_match", "conflicting_matches"),
      "an arrest-situation question is answered in-scope (not routed away)")
check(result.get("situation_detected") is True,
      "answer_question flags situation_detected=True when the answer leads with a 'Right now' block")

result = answer_question("what is section 318 of BNS")
check(result.get("situation_detected") is not True,
      "a general 'what is section X' question is NOT flagged as a situation")


# ---- End-to-end AppTest: the actual button click switches mode and seeds the flow ----

def run_handoff_case(question, history_key):
    at = AppTest.from_file(APP_PATH)
    at.session_state["route"] = "chat"
    at.run(timeout=90)
    at.chat_input[0].set_value(question).run(timeout=90)
    if at.exception:
        return None, [str(e) for e in at.exception]

    # The arrest answer (single_match) now also renders an opt-in
    # "Show related court judgments" button (Lane B); the freeze/cheque
    # redirects do not. Target the handoff button by its key rather than
    # assuming it's the only one.
    handoff = [b for b in at.button if getattr(b, "key", None) == "chat_domain_handoff"]
    if len(handoff) != 1:
        return None, [f"expected exactly 1 handoff button, found {len(handoff)} "
                      f"(total buttons on page: {len(at.button)})"]

    handoff[0].click().run(timeout=90)
    if at.exception:
        return None, [str(e) for e in at.exception]

    return {
        "route": at.session_state["route"],
        "domain_history": at.session_state[history_key],
        "chat_history": at.session_state["chat_history"],
    }, []


result, errors = run_handoff_case(
    "my bank account got frozen by the police and nobody told me why",
    "freeze_chat_history",
)
check(not errors, f"freeze handoff runs with no exceptions ({errors})")
if result:
    check(result["route"] == "freeze_assess", "freeze handoff routes to the freeze assessment flow")
    check(len(result["domain_history"]) == 2, "freeze flow history has exactly 2 turns (seeded question + real follow-up)")
    check(
        result["domain_history"][0]["content"] == "my bank account got frozen by the police and nobody told me why",
        "freeze flow's first turn is the user's original, verbatim question",
    )
    check(len(result["chat_history"]) == 2, "chat_history has exactly 2 turns, NOT duplicated by the handoff callback")

result, errors = run_handoff_case(
    "I got a legal notice saying my cheque bounced, what happens now",
    "cheque_chat_history",
)
check(not errors, f"cheque-bounce handoff runs with no exceptions ({errors})")
if result:
    check(result["route"] == "cheque_assess", "cheque-bounce handoff routes to the cheque assessment flow")
    check(len(result["domain_history"]) == 2, "cheque flow history has exactly 2 turns (seeded question + real follow-up)")
    check(
        result["domain_history"][0]["content"] == "I got a legal notice saying my cheque bounced, what happens now",
        "cheque flow's first turn is the user's original, verbatim question",
    )
    check(len(result["chat_history"]) == 2, "chat_history has exactly 2 turns, NOT duplicated by the handoff callback")

_arrest_q = "the police took me to the station this morning without telling me what i had done"
result, errors = run_handoff_case(_arrest_q, "interview_chat_history")
check(not errors, f"arrest handoff runs with no exceptions ({errors})")
if result:
    check(result["route"] == "arrest_assess",
          "arrest handoff routes to the free-text arrest assessment flow")
    check(len(result["domain_history"]) == 2,
          "arrest flow history has 2 turns (seeded question + the flow's own first question)")
    check(result["domain_history"][0]["content"] == _arrest_q,
          "arrest flow's first turn is the user's original, verbatim question")
    check(result["domain_history"][1]["role"] == "assistant" and result["domain_history"][1]["content"].strip(),
          "arrest flow's second turn is a non-empty assistant question (process_turn ran on the seed)")
    check(len(result["chat_history"]) == 2,
          "chat_history has exactly 2 turns -- arrest answer NOT duplicated by the handoff callback")


print("\n" + "=" * 70)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("RESULT: ALL TESTS PASSED")
    sys.exit(0)
