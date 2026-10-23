"""
test_site_client.py -- the Streamlit page's client of the API (site_client.py, step A5) over REAL HTTP: a throwaway PostgreSQL and a real API server with a stub engine (api_harness.py; SKIPPED where no PostgreSQL exists). Free and offline.
Proves: switches fail closed (USE_API off by default; configured() needs an address and a 32-character secret); the signed token the client mints is accepted by the API and works ONCE; sign-in, consent, age, chat, a streamed question (steps one by one, then
the answer), usage, feedback, export and delete work through the client; each API refusal arrives as an ApiError with the API's own code (consent required, daily limit, conversation full, wrong secret, service unreachable, engine failure) and never leaks the
exception text; a refusal (topic bar) carries the shared notice.
Run: python -X utf8 test_site_client.py
"""
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("USE_API", "SITE_API_URL", "STREAMLIT_API_SECRET", "SITE_API_TIMEOUT", "DATABASE_URL", "ACCOUNTS_OPEN", "REFUSAL_DAILY_LIMIT"):
    os.environ.pop(_v, None)

import site_client as SC

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ------------------------------------------------------------ switches
check(SC.enabled() is False and SC.configured() is False and SC.api_url() == "" and SC.secret() == "", "everything is off with nothing set (USE_API off by default)")
os.environ["USE_API"] = "on"
check(SC.enabled() is True and SC.configured() is False, "USE_API alone is not enough: an address and a secret are needed")
os.environ["SITE_API_URL"] = "https://api.example.test/"
os.environ["STREAMLIT_API_SECRET"] = "short"
check(SC.api_url() == "https://api.example.test" and SC.secret() == "" and SC.configured() is False, "a trailing slash is dropped; a secret under 32 characters counts as unset")
os.environ["STREAMLIT_API_SECRET"] = "s" * 40
check(SC.configured() is True, "address + 40-character secret: configured")
for v in ("off", "0", "", "banana"):
    os.environ["USE_API"] = v
    check(SC.enabled() is False, f"USE_API={v!r} is off")
os.environ["USE_API"] = "ON"
check(SC.enabled() is True, "USE_API=ON is on (case is ignored)")
os.environ["SITE_API_TIMEOUT"] = "5"
check(SC.timeout_seconds() == 10, "the timeout has a floor of 10 seconds")
os.environ.pop("SITE_API_TIMEOUT")
check(SC.timeout_seconds() == 150, "default timeout 150 seconds")

# unreachable service
os.environ["SITE_API_URL"] = "http://127.0.0.1:1"
P = {"sub": "client-test-sub", "email": "client@example.com", "email_verified": True, "name": "Client Test"}
try:
    SC.me(P)
    check(False, "an unreachable service raises")
except SC.ApiError as e:
    check(e.status == 0 and e.code == "unreachable" and "127.0.0.1" not in str(e), f"an unreachable service: ApiError(0, 'unreachable'), no address in the message ({e})")

import api_harness
import pg_harness
pg = pg_harness.start()
if pg is None:
    print("SKIPPED: no PostgreSQL here, the part over real HTTP was not run")
    print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1 if FAILURES else 0)
srv = None
try:
    from sqlalchemy import func, select

    from api.db import models as M
    from api.db import session as DBS
    SECRET = "s" * 40
    pg.create_db("siteclient")
    srv = api_harness.start({"DATABASE_URL": pg.url("siteclient"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "API_COOKIE_SECURE": "off", "API_RATE_LIMIT_PER_MINUTE": "0"})
    os.environ["DATABASE_URL"] = pg.url("siteclient")
    DBS.reset_engine()
    os.environ["SITE_API_URL"] = srv.url
    os.environ["STREAMLIT_API_SECRET"] = SECRET

    # ---- sign-in is by the minted token
    me = SC.me(P)
    check(me["user"]["email"] == "client@example.com" and me["user"]["plan"] == "free" and me["via"] == "streamlit" and [d["document"] for d in me["consent"]["missing"]] == ["privacy", "terms"] and me["usage"]["answer_layman"]["limit"] == 10,
          "me: the person is created on first use, on the free plan, with the documents to accept and today's limits")
    tok = SC.mint(P)
    import urllib.request
    def raw_me(t):
        r = urllib.request.Request(srv.url + "/api/me", headers={"Authorization": "Bearer " + t})
        try:
            return urllib.request.urlopen(r, timeout=20).status
        except urllib.error.HTTPError as e:
            return e.code
    check(raw_me(tok) == 200 and raw_me(tok) == 401, "a minted token works ONCE (the second use is refused)")
    os.environ["STREAMLIT_API_SECRET"] = "x" * 40
    try:
        SC.me(P)
        check(False, "a wrong secret is refused")
    except SC.ApiError as e:
        check(e.status == 401 and e.code == "bad_token", f"a wrong secret: 401 bad_token ({e})")
    os.environ["STREAMLIT_API_SECRET"] = SECRET
    long_name = dict(P, name="N" * 500)
    check(SC.me(long_name)["user"]["email"] == "client@example.com", "a very long display name does not break sign-in")

    # ---- consent and the first question
    try:
        SC.new_chat(P, "layman")
        check(False, "a chat needs consent first")
    except SC.ApiError as e:
        check(e.status == 403 and e.code == "consent_required", f"before accepting: 403 consent_required ({e})")
    docs = SC.me(P)["consent"]["missing"]
    for d in docs:
        t = SC.legal(d["document"])
        check(t["placeholder"] is True and t["version"] == d["version"], f"{d['document']}: the public text and its version")
        SC.accept(P, d["document"], t["version"])
    try:
        SC.new_chat(P, "layman")
        check(False, "a chat needs the age declaration too")
    except SC.ApiError as e:
        check(e.code == "consent_required", "documents accepted but not the age declaration: still 403")
    SC.confirm_age(P)
    me = SC.me(P)
    check(me["consent"]["ready"] is True, "after the documents and the age declaration: ready")
    chat = SC.new_chat(P, "layman")["id"]
    steps = []
    stamps = []
    def on_step(label):
        steps.append(label)
        stamps.append(time.time())
    t0 = time.time()
    r = SC.ask(P, chat, "What happens at a remand hearing before a magistrate?", on_step=on_step)
    check(r["result"]["state"] == "single_match" and r["text"].startswith("Stub answer to:") and r["saved"] is True and r["message_id"] and r["usage"]["used"] == 1 and r["usage"]["limit"] == 10 and r["notice"] is None,
          "ask: the engine's result, the saved message id, the usage 1 of 10, no notice for an answer")
    check(len(steps) == 2 and steps[0].startswith("Checked the topic") and steps[1] == "Writing the answer" and stamps[0] - t0 < stamps[1] - t0 and stamps[1] - stamps[0] > 0.05, f"the steps arrived one at a time, before the end ({steps})")
    r2 = SC.ask(P, chat, "And what if I am not given a lawyer there?")
    check(r2["usage"]["used"] == 2 and r2["turn"] == 2, "a follow-up in the same chat: usage 2, turn 2")
    check(SC.ask(P, chat, "What happens at a remand hearing before a magistrate?", key="fixed-key-0000000001")["usage"]["used"] == 3 and SC.ask(P, chat, "What happens at a remand hearing before a magistrate?", key="fixed-key-0000000001").get("replayed") is True,
          "the same Idempotency-Key again returns the stored answer (replayed)")
    r = SC.ask(P, SC.new_chat(P, "layman")["id"], "REFUSE: can my employer fire me without notice?")
    check(r["result"]["state"] == "adjacent_uncovered" and r["text"] is None and r["notice"]["title"] == "Recourse can't help with this one" and r["usage"]["used"] == 3, f"a topic-bar refusal: no text, the shared notice, no use counted ({r['usage']['used']})")

    # ---- the refusals
    try:
        SC.ask(P, SC.new_chat(P, "layman")["id"], "BOOM please")
        check(False, "an engine failure raises")
    except SC.ApiError as e:
        check(e.status == 500 and e.code == "engine_error" and "secret" not in str(e) and "secret" not in str(e.payload), f"an engine failure: ApiError 500 engine_error, no internal text ({e})")
    try:
        SC.ask(P, "00000000-0000-0000-0000-000000000000", "hello there friend")
        check(False, "a chat that does not exist raises")
    except SC.ApiError as e:
        check(e.status == 404 and e.code == "not_found", "a chat that is not yours or not there: 404 not_found")
    full = SC.new_chat(P, "layman")["id"]
    with DBS.session() as s:
        import uuid
        uid = s.execute(select(M.User.id).where(M.User.email == "client@example.com")).scalar_one()
        for i in range(8):
            s.add(M.Message(chat_id=uuid.UUID(full), role="user", seq=2 * i + 1, content=f"q{i}"))
            s.add(M.Message(chat_id=uuid.UUID(full), role="assistant", seq=2 * i + 2, content="a", result={"state": "single_match"}))
        s.commit()
    try:
        SC.ask(P, full, "a ninth question")
        check(False, "a full conversation raises")
    except SC.ApiError as e:
        check(e.status == 409 and e.code == "turn_limit", "the ninth question in a chat: 409 turn_limit")
    with DBS.session() as s:
        for _ in range(8):
            s.add(M.UsageEvent(user_id=uid, kind="answer_layman", counted=True))
        s.commit()
    try:
        SC.ask(P, SC.new_chat(P, "layman")["id"], "one more please")
        check(False, "the daily limit raises")
    except SC.ApiError as e:
        check(e.status == 429 and e.code == "limit_reached" and e.payload["usage"]["limit"] == 10 and e.payload["usage"]["resets_at"], f"over the daily allowance: 429 limit_reached with the limit and the reset time ({e})")

    # ---- feedback, export, delete
    try:
        SC.feedback(P, r2["message_id"], "nonsense")
        check(False, "an unknown kind raises")
    except SC.ApiError as e:
        check(e.status == 422, "feedback with an unknown kind: 422")
    check(SC.feedback(P, r2["message_id"], "wrong_case", "Case does not fit.")["status"] == "new", "feedback on my own answer is saved")
    exp = SC.export_my_data(P)
    check(exp["account"]["email"] == "client@example.com" and len(exp["chats"]) >= 3 and len(exp["feedback"]) == 1, "export: my chats and my report")
    check(SC.delete_account(P)["deleted"] is True, "delete: done")
    with DBS.session() as s:
        check(s.execute(select(func.count()).select_from(M.User).where(M.User.email == "client@example.com")).scalar() == 0, "...and the person is gone from the database")
finally:
    if srv:
        srv.stop()
    pg.stop()

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
