"""
test_site_account.py -- the page with USE_API on (site_account.py wired into recourse_app.py, step A5), driven by Streamlit's AppTest with the API client replaced by a recorder (no network, no model, no cost). The real client over real HTTP is test_site_client.py.
Proves: with USE_API off the page shows none of it; with it on and not set up the page says so and stops; not signed in: only the sign-in card (no question box); signed in but not accepted: the documents, the two tick boxes, nothing saved until both are ticked;
ready: the bar (who, usage left, sign out, my data), the question goes to the API in a saved chat, the real steps are drawn, the answer is drawn by the page's own renderer, today's usage line and the report-a-problem box appear; a follow-up stays in the
same chat and a new question or a change of voice starts another; each limit (daily, conversation full, refusals, busy) shows its own plain notice and never the technical-trouble text; a refusal is worded by the shared module; feedback and delete reach the client.
Run: python -X utf8 test_site_account.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("USE_API", "SITE_API_URL", "STREAMLIT_API_SECRET", "RESPONSE_STYLE", "CHAT_MODE", "REGISTER_HOOKS", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "STREAMLIT_COOKIE_SECRET", "SITE_URL"):
    os.environ.pop(_v, None)

from streamlit.testing.v1 import AppTest

import chat_assistant as CA
import site_account as SA
import site_client as SC

FAILURES = []
APP = os.path.join(HERE, "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CALLS = []
STATE = {"person": {"sub": "sub-1", "email": "reader@example.com", "email_verified": True, "name": "Reader"}, "ready": True, "age": True, "missing": [], "next_error": None, "next_result": None, "n": 0,
         "usage": {"answer_layman": {"used": 0, "limit": 10, "period": "day", "resets_at": "2026-10-24T18:30:00+00:00"}, "answer_lawyer": {"used": 0, "limit": 3, "period": "day", "resets_at": "x"}}}
DOCS = {"privacy": {"document": "privacy", "version": "PRIVACY-T1", "placeholder": True, "text": "TEST privacy text."}, "terms": {"document": "terms", "version": "TERMS-T1", "placeholder": True, "text": "TEST terms text."}}


def reset(**kw):
    CALLS.clear()
    STATE.update({"person": {"sub": "sub-1", "email": "reader@example.com", "email_verified": True, "name": "Reader"}, "ready": True, "age": True, "missing": [], "next_error": None, "next_result": None, "n": 0})
    STATE["usage"]["answer_layman"]["used"] = 0
    STATE.update(kw)


def fake_me(person):
    CALLS.append(("me",))
    return {"user": {"email": person["email"], "plan": "free"}, "via": "streamlit",
            "consent": {"missing": [{"document": d, "version": DOCS[d]["version"], "placeholder": True} for d in STATE["missing"]], "age_confirmed": STATE["age"], "ready": not STATE["missing"] and STATE["age"], "legal_text_is_placeholder": True},
            "usage": STATE["usage"]}


def fake_ask(person, chat_id, question, on_step=None, key=None):
    CALLS.append(("ask", chat_id, question))
    if on_step:
        on_step("Checked the topic of the question: it is within what Recourse covers")
        on_step("Writing the answer")
    if STATE["next_error"]:
        raise STATE["next_error"]
    STATE["n"] += 1
    STATE["usage"]["answer_layman"]["used"] += 1
    u = dict(STATE["usage"]["answer_layman"], feature="answer_layman")
    res = STATE["next_result"] or {"state": "single_match", "response_text": f"**Answer {STATE['n']}**\n\nThe stub answer to: {question[-50:]}", "matches": [], "situation_detected": False}
    return {"result": res, "text": res.get("response_text"), "notice": None, "usage": u, "chat_id": chat_id, "message_id": f"msg-{STATE['n']}", "saved": True, "turn": STATE["n"]}


def fake_new_chat(person, audience="layman"):
    CALLS.append(("new_chat", audience))
    return {"id": f"chat-{sum(1 for c in CALLS if c[0] == 'new_chat')}"}


SC.me = fake_me
SC.legal = lambda d: DOCS[d]
SC.accept = lambda person, d, v: CALLS.append(("accept", d, v)) or STATE["missing"].remove(d) or {}
SC.confirm_age = lambda person: CALLS.append(("age",)) or STATE.update(age=True) or {}
SC.new_chat = fake_new_chat
SC.ask = fake_ask
SC.feedback = lambda person, mid, kind, comment=None: CALLS.append(("feedback", mid, kind, comment)) or {"status": "new"}
SC.export_my_data = lambda person: {"account": {"email": person["email"]}}
SC.delete_account = lambda person: CALLS.append(("delete",)) or {"deleted": True}
SA.current_user = lambda: STATE["person"]
SA.ensure_login_config = lambda: True


def page(**env):
    for k in ("USE_API", "SITE_API_URL", "STREAMLIT_API_SECRET", "RESPONSE_STYLE"):
        os.environ.pop(k, None)
    os.environ.update(env)
    return AppTest.from_file(APP, default_timeout=90).run()


def md(at):
    return [m.value for m in at.markdown]


def has(at, text):
    return any(text in v for v in md(at))


def ask(at, q, form_key="text", label="Check my situation"):
    at.text_area(key=form_key).set_value(q).run()
    [b for b in at.button if label in b.label][0].click().run()
    return at


ON = dict(USE_API="on", SITE_API_URL="https://api.example.test", STREAMLIT_API_SECRET="s" * 40)

# ------------------------------------------------------------ off, and on but not set up
reset()
at = page()
check(not at.exception and not has(at, "Sign in to ask") and not has(at, "Signed in as") and at.text_area(key="text"), "USE_API off: the page is as before (no sign-in card, no account bar, the question box is there)")
at = page(USE_API="on")
check(not at.exception and has(at, "Accounts are not connected") and not [t for t in at.text_area if getattr(t, "key", "") == "text"], "USE_API on but no address or secret: 'Accounts are not connected' and the page stops (no question box)")
SA.ensure_login_config = lambda: False
at = page(**ON)
check(has(at, "Sign-in is not set up") and not [t for t in at.text_area if getattr(t, "key", "") == "text"], "sign-in not configured: the page says so and stops")
SA.ensure_login_config = lambda: True

# ------------------------------------------------------------ not signed in
STATE["person"] = None
at = page(**ON)
check(has(at, "Sign in to ask") and [b for b in at.button if "Sign in with Google" in b.label] and not [t for t in at.text_area if getattr(t, "key", "") == "text"], "signed out: the sign-in card with the Google button, and no question box")
check(not CALLS, "...and no call was made to the API")

# ------------------------------------------------------------ consent
reset(missing=["privacy", "terms"], age=False)
at = page(**ON)
check(has(at, "Before you start") and len(at.expander) >= 2 and len(at.checkbox) == 2 and not [t for t in at.text_area if getattr(t, "key", "") == "text"], "signed in, nothing accepted: the documents, two tick boxes, no question box")
check(any("TEST text" in w.value for w in at.warning), "the placeholder text is called TEST text, not the final notice")
[b for b in at.button if "Accept and continue" in b.label][0].click().run()
check(any("Please tick" in e.value for e in at.error) and not [c for c in CALLS if c[0] in ("accept", "age")], "pressing accept with nothing ticked: a plain message, nothing saved")
at.checkbox(key="consent_docs").check()
[b for b in at.button if "Accept and continue" in b.label][0].click().run()
check(any("Please tick" in e.value for e in at.error) and not [c for c in CALLS if c[0] in ("accept", "age")], "only the documents ticked (not 18+): nothing saved")
at.checkbox(key="consent_age").check()
[b for b in at.button if "Accept and continue" in b.label][0].click().run()
check([c for c in CALLS if c[0] in ("accept", "age")] == [("accept", "privacy", "PRIVACY-T1"), ("accept", "terms", "TERMS-T1"), ("age",)] and at.text_area(key="text"), "both ticked: each document is accepted at its own version, the age is confirmed, and the page opens")

# ------------------------------------------------------------ ready: the bar, a question, the answer
reset()
at = page(**ON)
check(has(at, "Signed in as reader@example.com") and has(at, "10 of 10 answers left today") and [b for b in at.button if "Sign out" in b.label] and at.text_area(key="text"), "ready: who is signed in, 10 of 10 left today, sign out, the question box")
ask(at, "My brother was arrested yesterday and has not been told why.")
check(not at.exception and has(at, "The stub answer to:") and ("new_chat", "layman") in CALLS and [c for c in CALLS if c[0] == "ask"] == [("ask", "chat-1", "My brother was arrested yesterday and has not been told why.")], f"the question goes to the API in a new chat and the answer is drawn by the page ({at.exception})")
check(has(at, "9 of 10 answers left today"), "today's usage line under the answer: 9 of 10 left")
check(len([e for e in at.expander if "Report a problem" in e.label]) == 1, "the report-a-problem box is there")
at.radio(key="fb_kind").set_value("wrong_case")
at.text_area(key="fb_comment").set_value("The case is about bail, not remand.")
[b for b in at.button if b.key == "fb_send"][0].click().run()
check(("feedback", "msg-1", "wrong_case", "The case is about bail, not remand.") in CALLS and has(at, "Thank you. Your report goes"), "report a problem: sent for this answer's message, with the kind and the comment; thanks shown")
# follow-up
at.text_area(key="followup_text").set_value("And what if he is not given a lawyer?").run()
[b for b in at.button if "Ask a follow-up" in b.label][0].click().run()
asks = [c for c in CALLS if c[0] == "ask"]
check(not at.exception and len(asks) == 2 and asks[1][1] == "chat-1" and asks[1][2] == "And what if he is not given a lawyer?" and sum(1 for c in CALLS if c[0] == "new_chat") == 1, "a follow-up goes into the SAME chat (no second chat) with only the new words (the server folds the earlier ones)")
check(has(at, "8 of 10 answers left today") and has(at, "Your conversation is saved to your account"), "usage now 8 of 10; the follow-up note says the conversation is saved to the account")
# new question
at.text_area(key="text").set_value("A completely different matter about a cheque.").run()
[b for b in at.button if "Check my situation" in b.label][0].click().run()
check(sum(1 for c in CALLS if c[0] == "new_chat") == 2 and [c for c in CALLS if c[0] == "ask"][-1][1] == "chat-2", "a new question from the box starts a new chat")

# ------------------------------------------------------------ voices
reset()
at = page(RESPONSE_STYLE="v3", **ON)
ask(at, "Question in the layman voice about bail.")
at.radio(key="audience_choice").set_value("Lawyer").run()
at.text_area(key="followup_text").set_value("A follow-up now in the lawyer voice about bail?").run()
[b for b in at.button if "Ask a follow-up" in b.label][0].click().run()
check([c for c in CALLS if c[0] == "new_chat"] == [("new_chat", "layman"), ("new_chat", "lawyer")], "changing the voice in the middle starts a chat in the other voice (lawyer answers have their own allowance)")

# ------------------------------------------------------------ limits and refusals
def limited(err, expect, absent="Something isn't working right now"):
    reset(next_error=err)
    a = page(**ON)
    ask(a, "A question that will be refused by the limit.")
    check(not a.exception and has(a, expect) and not has(a, absent), f"{err.code}: the page says '{expect}' and not the technical-trouble text")
limited(SC.ApiError(429, "limit_reached", {"usage": {"limit": 10, "used": 10}}), "You have used today's answers")
limited(SC.ApiError(429, "too_many_refusals", {}), "Too many questions Recourse could not take up")
limited(SC.ApiError(409, "turn_limit", {}), "This conversation is full")
limited(SC.ApiError(409, "in_progress", {}), "Your last question is still being answered")
limited(SC.ApiError(429, "busy, try again shortly", {}), "Recourse is busy right now")
limited(SC.ApiError(429, "rate_limited", {}), "Please slow down a little")
limited(SC.ApiError(0, "unreachable", {}), "Something isn't working right now", absent="You have used today's answers")
limited(SC.ApiError(500, "engine_error", {}), "Something isn't working right now", absent="You have used today's answers")
reset(next_result={"state": "adjacent_uncovered", "reasoning": "An employment dispute."})
at = page(**ON)
ask(at, "Can my employer fire me without notice?")
check(has(at, "Recourse can't help with this one") and has(at, "An employment dispute.") and has(at, "speak with a lawyer who handles that area of law"), "a refusal is worded by the shared module, exactly as the direct path words it")

# ------------------------------------------------------------ my data
reset()
at = page(**ON)
at.text_input(key="acct_delete_word").set_value("delete").run()
check([b for b in at.button if b.key == "acct_delete"][0].disabled, "delete stays disabled until DELETE is typed (exactly)")
at.text_input(key="acct_delete_word").set_value("DELETE").run()
[b for b in at.button if b.key == "acct_delete"][0].click().run()
check(("delete",) in CALLS, "typing DELETE and pressing the button deletes the account through the client")

# ------------------------------------------------------------ the login configuration
SA2 = __import__("importlib").reload(SA)
for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "STREAMLIT_COOKIE_SECRET", "SITE_URL", "SITE_OIDC_METADATA_URL"):
    os.environ.pop(k, None)
check(SA2.login_config() is None, "no login settings: no configuration")
os.environ.update({"GOOGLE_CLIENT_ID": "cid.apps.googleusercontent.com", "GOOGLE_CLIENT_SECRET": 'sec"ret', "STREAMLIT_COOKIE_SECRET": "c" * 40, "SITE_URL": "https://staging.example.test/"})
cfg = SA2.login_config()["auth"]
check(cfg["redirect_uri"] == "https://staging.example.test/oauth2callback" and cfg["client_id"] == "cid.apps.googleusercontent.com" and cfg["client_secret"] == 'sec"ret' and cfg["cookie_secret"] == "c" * 40 and cfg["server_metadata_url"] == "https://accounts.google.com/.well-known/openid-configuration",
      "the login configuration holds the redirect address, the client, the cookie secret and Google's discovery address")
os.environ["STREAMLIT_COOKIE_SECRET"] = "short"
check(SA2.login_config() is None, "a cookie secret under 32 characters: no configuration (fails closed)")
os.environ["STREAMLIT_COOKIE_SECRET"] = "c" * 40
os.environ["SITE_URL"] = "staging.example.test"
check(SA2.login_config() is None, "a SITE_URL without http: no configuration")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
