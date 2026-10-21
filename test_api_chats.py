"""
test_api_chats.py -- saved conversations, the free trial, notes and feedback (api/routers/chats.py, anon.py, notes.py, api/chat_service.py; WEBSITE_DESIGN.md sections 5 and 6, step A3.4). Free and offline: a throwaway PostgreSQL (SKIPPED
and exit 0 where none exists), a stand-in engine, the Streamlit service's signed token as the way to be somebody.
Proves: a chat is its owner's alone (anyone else gets 404); a question needs consent and an Idempotency-Key; the question and the answer are saved by the worker thread (so a caller who leaves loses nothing); a repeated key returns the stored answer
and charges nothing, the same key with other words is refused, the same key while the first still runs is refused; follow-ups send the engine the person's earlier QUESTIONS and never an earlier answer; an answered question counts one use,
a refusal and a failure count none; the daily limit stops with the reset time; the turn limit stops at 8; deleting a chat deletes its messages; notes are limited by the plan, even under simultaneous adds; feedback only on one's own answers;
the free trial is closed unless switched on, keeps the question under a random device id and no address for 90 days, stops at three a day per device, at the address flood guard, and at the trial's budget even when many questions arrive at once.
Run: python -X utf8 test_api_chats.py
"""
import datetime
import os
import sys
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "API_ACCESS_TOKEN", "ACCOUNTS_OPEN", "GOOGLE_CLIENT_ID", "STREAMLIT_API_SECRET", "IP_HASH_SECRET", "CORS_ALLOW_ORIGINS", "TRUSTED_PROXY_HOPS", "API_COOKIE_SECURE", "API_RUN_MIGRATIONS",
           "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL", "ANON_TRIAL", "ANON_DAILY_BUDGET_INR", "ANON_IP_DAILY_LIMIT", "ANON_EST_COST_INR", "CHAT_MODE"):
    os.environ.pop(_v, None)

import pg_harness

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


pg = pg_harness.start()
if pg is None:
    sys.exit(0)
try:
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select, text

    from api import chat_service, engine_adapter
    from api import quota as Q
    from api.auth import streamlit_token as ST
    from api.db import migrate as MIG
    from api.db import models as M
    from api.db import session as DBS
    from api.main import app

    SECRET = "s" * 40
    pg.create_db("chats")
    os.environ.update({"DATABASE_URL": pg.url("chats"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "GOOGLE_CLIENT_ID": "client.example", "API_COOKIE_SECURE": "off"})
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())

    class FakeEngine:
        mode = "ok"
        gate = threading.Event()
        questions = []
        n = 0

        def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None):
            import cost_log
            import progress
            self.questions.append(question)
            FakeEngine.n += 1
            cost_log.begin(question)
            try:
                progress.emit("scope", category="in_scope")
                progress.emit("write")
                if self.mode == "boom":
                    raise RuntimeError("secret failure")
                if self.mode == "slow":
                    self.gate.wait(10)
                if self.mode == "refuse":
                    return {"state": "no_match", "response_text": "Not enough to go on yet."}
                return {"state": "single_match", "response_text": f"ANSWER-{FakeEngine.n}: the law says something about {question[-30:]}", "matches": []}
            finally:
                cost_log.finish(style="v1", audience=audience or "")

    ENG = FakeEngine()
    engine_adapter.set_engine(ENG)
    engine_adapter.reset_runner(engine_adapter.Runner(4, 8))
    c = TestClient(app)

    def H(sub, email):
        return lambda: {"Authorization": "Bearer " + ST.mint(SECRET, sub, email)}        # a signed token is good for ONE request: every call mints its own

    A, B = H("a-sub", "alice@example.com"), H("b-sub", "bob@example.com")
    N = H("n-sub", "newbie@example.com")

    def make_ready(h):
        for doc in ("privacy", "terms"):
            v = c.get(f"/api/legal/{doc}").json()["version"]
            assert c.post("/api/me/consent", json={"document": doc, "version": v}, headers=h()).status_code == 200
        assert c.post("/api/me/age", json={"confirmed": True}, headers=h()).status_code == 200

    [c.get("/api/me", headers=x()) for x in (A, B, N)]
    make_ready(A)
    make_ready(B)

    def uid(email):
        with DBS.session() as s:
            return s.execute(select(M.User.id).where(M.User.email == email)).scalar_one()

    def counted(email, kind="answer_layman"):
        with DBS.session() as s:
            return s.execute(select(func.count()).select_from(M.UsageEvent).where(M.UsageEvent.user_id == uid(email), M.UsageEvent.kind == kind, M.UsageEvent.counted.is_(True))).scalar()

    def n_messages(chat_id):
        with DBS.session() as s:
            return s.execute(select(func.count()).select_from(M.Message).where(M.Message.chat_id == uuid.UUID(chat_id))).scalar()

    def ask(h, chat, q, key=None, accept=None):
        hh = dict(h(), **{"Idempotency-Key": key or uuid.uuid4().hex[:20]})
        if accept:
            hh["Accept"] = accept
        return c.post(f"/api/chats/{chat}/ask", json={"question": q}, headers=hh)

    # ------------------------------------------------------------ consent and ownership
    r = c.post("/api/chats", json={}, headers=N())
    check(r.status_code == 403 and r.json()["detail"] == "consent_required", "a person who has not accepted the documents cannot start a chat (403 consent_required)")
    check(c.get("/api/chats").status_code == 401, "without signing in: 401")
    r = c.post("/api/chats", json={"audience": "layman"}, headers=A())
    chat = r.json()["id"]
    check(r.status_code == 201 and r.json()["audience"] == "layman" and r.json()["title"] == "", "a chat is created (201), empty and untitled")
    check(c.post("/api/chats", json={"audience": "judge"}, headers=A()).status_code == 422, "an unknown audience is refused (422)")
    check(c.get(f"/api/chats/{chat}", headers=B()).status_code == 404 and c.patch(f"/api/chats/{chat}", json={"title": "x"}, headers=B()).status_code == 404
          and c.delete(f"/api/chats/{chat}", headers=B()).status_code == 404 and ask(B, chat, "hello there").status_code == 404, "another person gets 404 on read, rename, delete and ask (existence is not told)")
    check(c.get("/api/chats/not-a-uuid", headers=A()).status_code == 422, "a malformed id is 422")

    # ------------------------------------------------------------ ask: validation
    check(c.post(f"/api/chats/{chat}/ask", json={"question": "hello"}, headers=A()).status_code == 400, "no Idempotency-Key: 400")
    check(c.post(f"/api/chats/{chat}/ask", json={"question": "hello"}, headers=dict(A(), **{"Idempotency-Key": "short"})).status_code == 400, "a too-short key: 400")
    check(c.post(f"/api/chats/{chat}/ask", json={"question": "hello"}, headers=dict(A(), **{"Idempotency-Key": "bad key with spaces!!"})).status_code == 400, "a key with odd characters: 400")
    check(ask(A, chat, "   ").status_code == 422, "an empty question: 422")
    check(ask(A, chat, "x" * 7000).status_code == 413, "a too-long question: 413")
    check(FakeEngine.n == 0 and counted("alice@example.com") == 0, "none of those reached the engine or the allowance")

    # ------------------------------------------------------------ ask: the first answer is saved
    Q1 = "My landlord is refusing to return my deposit of 50000 rupees after I vacated."
    r = ask(A, chat, Q1, key="key-first-0001")
    j = r.json()
    check(r.status_code == 200 and j["saved"] is True and j["chat_id"] == chat and j["message_id"] and j["text"].startswith("ANSWER-1"), f"JSON reply: the answer, its message id, saved=true ({r.status_code})")
    check(j["usage"]["used"] == 1 and j["usage"]["limit"] == 10 and j["usage"]["period"] == "day", f"the reply says how much of today's allowance is used ({j['usage']})")
    g = c.get(f"/api/chats/{chat}", headers=A()).json()
    check([m["role"] for m in g["messages"]] == ["user", "assistant"] and [m["seq"] for m in g["messages"]] == [1, 2] and g["messages"][0]["content"] == Q1 and g["messages"][1]["result"]["state"] == "single_match", "the question and the answer are stored in order, with the engine's whole result")
    check(g["title"].startswith("My landlord is refusing") and len(g["title"]) <= 70 and g["turn_limit"] == 8, f"the chat takes its title from the first question ({g['title']!r})")
    check(counted("alice@example.com") == 1, "one use counted")
    with DBS.session() as s:
        ev = s.execute(select(M.UsageEvent).where(M.UsageEvent.user_id == uid("alice@example.com"))).scalars().one()
        check(str(ev.message_id) == j["message_id"], "the use is linked to the answer's message")

    # ------------------------------------------------------------ idempotency
    before = FakeEngine.n
    r = ask(A, chat, Q1, key="key-first-0001")
    check(r.status_code == 200 and r.json().get("replayed") is True and r.json()["text"] == j["text"] and FakeEngine.n == before, "the same key and question again: the stored answer, replayed=true, the engine is NOT asked again")
    check(counted("alice@example.com") == 1 and n_messages(chat) == 2, "...nothing is charged and nothing is stored twice")
    check(ask(A, chat, "A different question altogether.", key="key-first-0001").status_code == 409, "the same key with other words: 409")
    r = ask(A, chat, Q1, key="key-first-0001", accept="text/event-stream")
    check("event: result" in r.text and '"replayed": true' in r.text and "event: done" in r.text, "a replay over server-sent events ends in a result and done")

    # ------------------------------------------------------------ follow-up
    Q2 = "Can I also claim interest on that deposit?"
    r = ask(A, chat, Q2)
    sent = ENG.questions[-1]
    check(r.status_code == 200 and Q1 in sent and sent.endswith("Now the person says: " + Q2), "a follow-up reaches the engine with the person's EARLIER question folded in, in the engine's own format")
    check("ANSWER-1" not in sent and "the law says" not in sent, "...and with none of OUR earlier answer")
    check(n_messages(chat) == 4 and counted("alice@example.com") == 2, "four messages, two uses")

    # ------------------------------------------------------------ SSE, refusals, failures
    r = ask(A, chat, "And what about stamp duty on the agreement?", accept="text/event-stream")
    check(r.status_code == 200 and "event: start" in r.text and "event: step" in r.text and "event: result" in r.text and "message_id" in r.text and r.text.rstrip().endswith("data: {}"), "server-sent events: start, steps, a result carrying the message id, done")
    ENG.mode = "refuse"
    used = counted("alice@example.com")
    r = ask(A, chat, "Tell me about the weather today in Delhi.")
    check(r.status_code == 200 and r.json()["saved"] is True and r.json()["result"]["state"] == "no_match", "a refusal is shown and saved")
    check(counted("alice@example.com") == used and r.json()["usage"]["used"] == used, f"...and costs nothing ({r.json()['usage']['used']} of the day used, was {used})")
    ENG.mode = "boom"
    nmsg = n_messages(chat)
    r = ask(A, chat, "A question that makes the engine fail.", key="key-boom-00001")
    check(r.status_code == 500 and r.json()["error"]["code"] == "engine_error" and "secret" not in r.text, "an engine failure: a fixed sentence, no internal text")
    check(counted("alice@example.com") == used and n_messages(chat) == nmsg, "...nothing saved, no use counted")
    ENG.mode = "ok"
    r = ask(A, chat, "A question that makes the engine fail.", key="key-boom-00001")
    check(r.status_code == 200 and r.json()["saved"] is True, "the same key works again after a failure (the key was released)")

    # ------------------------------------------------------------ a caller who leaves loses nothing
    cc = c.post("/api/chats", json={}, headers=A()).json()["id"]
    with DBS.session() as s:
        u = s.get(M.User, uid("alice@example.com"))
        ok, ev, info = Q.reserve(s, u, "answer_layman")
        s.commit()
    t = chat_service.Turn(user_id=uid("alice@example.com"), chat_id=uuid.UUID(cc), audience="layman", question="Saved by the worker alone.", request_id="key-worker-001", event_id=ev, usage=info)
    chat_service.claim(t.chat_id, t.request_id)
    out = chat_service.run_turn(lambda *a: None, t)
    check(out["saved"] is True and n_messages(cc) == 2, "run_turn alone (nobody listening) saves the question and the answer")

    # ------------------------------------------------------------ the limits
    with DBS.session() as s:
        for _ in range(12):
            s.add(M.UsageEvent(user_id=uid("bob@example.com"), kind="answer_layman", counted=True))
        s.commit()
    bc = c.post("/api/chats", json={}, headers=B()).json()["id"]
    n0 = FakeEngine.n
    r = ask(B, bc, "Can I still ask today?")
    check(r.status_code == 429 and r.json()["detail"] == "limit_reached" and r.json()["usage"]["limit"] == 10 and r.json()["usage"]["resets_at"], f"over the daily allowance: 429 with the limit and the reset time ({r.json()})")
    check(FakeEngine.n == n0 and n_messages(bc) == 0, "...the engine was not asked and nothing was saved")
    lc = c.post("/api/chats", json={"audience": "lawyer"}, headers=A()).json()["id"]
    check(ask(A, lc, "Research note on the maintainability of a Section 138 complaint.").status_code == 200 and counted("alice@example.com", "answer_lawyer") == 1, "a lawyer-voice chat uses the lawyer allowance, not the layman one")
    tc = c.post("/api/chats", json={}, headers=A()).json()["id"]
    with DBS.session() as s:
        for i in range(8):
            s.add(M.Message(chat_id=uuid.UUID(tc), role="user", seq=2 * i + 1, content=f"q{i}"))
            s.add(M.Message(chat_id=uuid.UUID(tc), role="assistant", seq=2 * i + 2, content="a", result={"state": "single_match"}))
        s.commit()
    used = counted("alice@example.com")
    r = ask(A, tc, "A ninth question?")
    check(r.status_code == 409 and r.json()["detail"] == "turn_limit" and counted("alice@example.com") == used, "the ninth question in a chat: 409 turn_limit, nothing charged")

    # ------------------------------------------------------------ the same key while the first is running
    ENG.mode, ENG.gate = "slow", threading.Event()
    sc = c.post("/api/chats", json={}, headers=A()).json()["id"]
    res = {}

    def first():
        res["first"] = ask(A, sc, "A slow question about bail.", key="key-slow-00001")
    th = threading.Thread(target=first)
    th.start()
    for _ in range(100):
        if ("%s" % uuid.UUID(sc), "key-slow-00001") in {(str(a), b) for a, b in chat_service._INFLIGHT}:
            break
        time.sleep(0.05)
    r = ask(A, sc, "A slow question about bail.", key="key-slow-00001")
    check(r.status_code == 409 and r.json()["detail"] == "in_progress", "the same key while the first is still running: 409 in_progress")
    ENG.gate.set()
    th.join(30)
    ENG.mode = "ok"
    check(res["first"].status_code == 200 and res["first"].json()["saved"] is True and n_messages(sc) == 2, "...and the first one completes and is saved once")

    # ------------------------------------------------------------ list, search, rename, archive, delete
    names = [x["title"] for x in c.get("/api/chats", headers=A()).json()["chats"]]
    check(len(names) >= 4, f"the list shows my chats ({len(names)})")
    c.patch(f"/api/chats/{sc}", json={"title": "100% bail_matter"}, headers=A())
    check([x["id"] for x in c.get("/api/chats?q=100%25 bail_", headers=A()).json()["chats"]] == [sc], "search by title treats % and _ as plain characters")
    check([x["id"] for x in c.get("/api/chats?q=%25", headers=A()).json()["chats"]] == [sc], "a lone % matches only the title that contains a percent sign (not everything)")
    c.patch(f"/api/chats/{sc}", json={"archived": True}, headers=A())
    check(sc not in [x["id"] for x in c.get("/api/chats", headers=A()).json()["chats"]] and sc in [x["id"] for x in c.get("/api/chats?archived=true", headers=A()).json()["chats"]], "an archived chat leaves the list and shows under archived")
    check(c.get("/api/chats", headers=B()).json()["chats"][0]["id"] == bc and len(c.get("/api/chats", headers=B()).json()["chats"]) == 1, "another person's list holds only their own")

    # ------------------------------------------------------------ notes
    mid = c.get(f"/api/chats/{chat}", headers=A()).json()["messages"][1]["id"]
    with DBS.session() as s:
        pid = s.execute(select(M.Plan.id).where(M.Plan.code == "free")).scalar_one()
        s.add(M.Entitlement(plan_id=pid, feature="notes_max", period="none", limit_count=3, version=2))
        s.commit()
    r = c.post("/api/notes", json={"body": "Call the landlord on Monday.", "message_id": mid}, headers=A())
    nid = r.json()["id"]
    check(r.status_code == 201 and r.json()["message_id"] == mid, "a note linked to my own answer is saved")
    check(c.post("/api/notes", json={"body": "x", "message_id": mid}, headers=B()).status_code == 404, "a note cannot be tied to somebody else's message (404)")
    check(c.patch(f"/api/notes/{nid}", json={"body": "Call on Tuesday."}, headers=A()).json()["body"] == "Call on Tuesday." and c.patch(f"/api/notes/{nid}", json={"body": "x"}, headers=B()).status_code == 404, "I can change my note; nobody else can")
    outs = []
    ths = [threading.Thread(target=lambda i=i: outs.append(c.post("/api/notes", json={"body": f"n{i}"}, headers=A()).status_code)) for i in range(6)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    with DBS.session() as s:
        total = s.execute(select(func.count()).select_from(M.Note).where(M.Note.user_id == uid("alice@example.com"))).scalar()
    check(total == 3 and outs.count(201) == 2 and outs.count(403) == 4, f"6 simultaneous adds with 2 places left: exactly 2 are saved, the limit of 3 holds ({outs.count(201)} saved, {total} in all)")
    check(c.get("/api/notes", headers=A()).json()["limit"] == 3 and len(c.get("/api/notes", headers=B()).json()["notes"]) == 0, "the list shows the limit and only my notes")
    c.delete(f"/api/chats/{chat}", headers=A())
    with DBS.session() as s:
        n = s.get(M.Note, uuid.UUID(nid))
        check(n is not None and n.message_id is None, "deleting a chat deletes its messages but keeps my note (its link is cleared)")
        check(s.execute(select(func.count()).select_from(M.Message).where(M.Message.chat_id == uuid.UUID(chat))).scalar() == 0, "...the messages are gone")
        check(s.execute(select(func.count()).select_from(M.UsageEvent).where(M.UsageEvent.user_id == uid("alice@example.com"))).scalar() >= 3, "...the usage rows stay (they hold no text)")
    check(c.delete(f"/api/notes/{nid}", headers=B()).status_code == 404 and c.delete(f"/api/notes/{nid}", headers=A()).status_code == 200, "only I can delete my note")

    # ------------------------------------------------------------ feedback
    fid = c.get(f"/api/chats/{sc}", headers=A()).json()["messages"]
    am, um = fid[1]["id"], fid[0]["id"]
    check(c.post("/api/feedback", json={"message_id": am, "kind": "wrong_case", "comment": "Case is not about deposits."}, headers=A()).status_code == 201, "feedback on my own answer is saved")
    check(c.post("/api/feedback", json={"message_id": am, "kind": "nonsense"}, headers=A()).status_code == 422, "an unknown kind: 422")
    check(c.post("/api/feedback", json={"message_id": um, "kind": "other"}, headers=A()).status_code == 422, "feedback on my own question (not an answer): 422")
    check(c.post("/api/feedback", json={"message_id": am, "kind": "helpful"}, headers=B()).status_code == 404, "feedback on somebody else's answer: 404")
    with DBS.session() as s:
        for _ in range(60):
            s.add(M.Feedback(user_id=uid("alice@example.com"), message_id=uuid.UUID(am), kind="other"))
        s.commit()
    check(c.post("/api/feedback", json={"message_id": am, "kind": "other"}, headers=A()).status_code == 429, "more than 50 reports a day: 429")

    # ------------------------------------------------------------ the cookie path needs the CSRF header
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from api.auth import google as G
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Jw:
        def get_signing_key_from_jwt(self, t):
            import types
            return types.SimpleNamespace(key=rsa_key.public_key())
    G._CLIENT["c"] = Jw()
    now = int(time.time())
    gt = jwt.encode({"iss": "https://accounts.google.com", "aud": "client.example", "sub": "cookie-sub", "email": "dan@example.com", "email_verified": True, "iat": now, "exp": now + 600}, rsa_key, algorithm="RS256")
    dc = TestClient(app)
    csrf = dc.post("/api/auth/google", json={"id_token": gt}).json()["csrf"]
    from api.auth import sessions as SS
    for doc in ("privacy", "terms"):
        v = dc.get(f"/api/legal/{doc}").json()["version"]
        dc.post("/api/me/consent", json={"document": doc, "version": v}, headers={"X-CSRF-Token": csrf})
    dc.post("/api/me/age", json={"confirmed": True}, headers={"X-CSRF-Token": csrf})
    check(dc.post("/api/chats", json={}).status_code == 403 and dc.post("/api/chats", json={}, headers={"X-CSRF-Token": csrf}).status_code == 201, "through the browser cookie, creating a chat needs the CSRF header")
    check(dc.post(f"/api/chats/{dc.get('/api/chats').json()['chats'][0]['id']}/ask", json={"question": "hello there friend"}, headers={"Idempotency-Key": "key-cookie-001"}).status_code == 403, "...and so does asking")

    # ------------------------------------------------------------ the free trial
    ENG.mode = "ok"
    ac = TestClient(app)
    check(ac.post("/api/anon/ask", json={"question": "Can my employer fire me without notice?"}).status_code == 503, "the trial is closed unless switched on")
    os.environ.update({"ANON_TRIAL": "on", "ANON_DAILY_BUDGET_INR": "50"})
    check(ac.post("/api/anon/ask", json={"question": "Can my employer fire me without notice?"}).status_code == 503, "...and closed without IP_HASH_SECRET")
    os.environ["IP_HASH_SECRET"] = "i" * 40
    os.environ["ANON_IP_DAILY_LIMIT"] = "6"

    def anon(client, q="Can my employer fire me without notice?", ip="203.0.113.7", **kw):
        return client.post("/api/anon/ask", json={"question": q}, headers={"X-Forwarded-For": ip, **kw})

    r = anon(ac)
    dev = ac.cookies.get("rc_device")
    check(r.status_code == 200 and r.json()["trial"] == {"used": 1, "limit": 3} and dev and len(dev) == 32 and "httponly" in r.headers["set-cookie"].lower(), f"a trial question is answered, the device cookie is set (HttpOnly), 1 of 3 used ({r.json().get('trial')})")
    with DBS.session() as s:
        row = s.execute(select(M.AnonQuestion)).scalars().one()
        check(row.question == "Can my employer fire me without notice?" and row.device_id == dev and row.result_state == "single_match" and row.audience == "layman", "the question is stored under the device id")
        span = (row.expires_at - row.created_at).days
        check(span == 90, f"...kept for 90 days ({span})")
        everything = " ".join(str(v) for t in (M.AnonQuestion.__table__, M.AnonCounter.__table__) for rr in s.execute(select(t)).all() for v in rr)
        check("203.0.113.7" not in everything, "...and no IP address appears in the stored rows")
    check(anon(ac).json()["trial"]["used"] == 2 and anon(ac).json()["trial"]["used"] == 3, "second and third questions count 2 and 3")
    r = anon(ac)
    check(r.status_code == 429 and r.json()["detail"] == "device_limit" and r.json()["limit"] == 3, "the fourth question from the same device: 429 device_limit")
    ac2 = TestClient(app)
    check(anon(ac2).status_code == 200, "a new device on the same address still gets its own three (an address is shared by many people)")
    ac3 = TestClient(app)
    r = [anon(ac3).status_code for _ in range(3)]
    ac4 = TestClient(app)
    r4 = anon(ac4)
    check(r4.status_code == 429 and r4.json()["detail"] == "ip_limit", f"the address flood guard (6 a day here) stops a seventh ({r}, then {r4.status_code})")
    check(anon(TestClient(app), ip="198.51.100.9").status_code == 200, "...another address is unaffected")
    import re as _re
    r = anon(TestClient(app), ip="198.51.100.10", Cookie="rc_device=../../etc/passwd")
    m = _re.search(r"rc_device=([^;]+)", r.headers.get("set-cookie", ""))
    check(r.status_code == 200 and m and _re.fullmatch(r"[0-9a-f]{32}", m.group(1)), "a malformed device cookie is replaced, not trusted")
    ENG.mode = "refuse"
    d5 = TestClient(app)
    r = anon(d5, ip="198.51.100.11")
    check(r.status_code == 200 and r.json()["trial"]["used"] == 0, "a refusal does not use up one of the three")
    ENG.mode = "boom"
    r = anon(d5, ip="198.51.100.11")
    check(r.status_code == 500, "an engine failure is a fixed 500")
    ENG.mode = "ok"
    check([anon(d5, ip="198.51.100.11").json()["trial"]["used"] for _ in range(3)] == [1, 2, 3], "...and used none either: all three are still available")
    os.environ["CORS_ALLOW_ORIGINS"] = "https://app.recourse.test"
    r = ac2.post("/api/anon/ask", json={"question": "Can my employer fire me?"}, headers={"X-Forwarded-For": "198.51.100.12", "Origin": "https://evil.example"})
    check(r.status_code == 403 and r.json()["detail"] == "origin", "a browser page from another origin cannot use someone's device allowance (403)")
    check(ac2.post("/api/anon/ask", json={"question": "Can my employer fire me?"}, headers={"X-Forwarded-For": "198.51.100.12", "Origin": "https://app.recourse.test"}).status_code == 200, "...the allowed origin can")
    os.environ.pop("CORS_ALLOW_ORIGINS")

    # budget: running questions count at the estimate, so a burst cannot all pass the check
    os.environ["ANON_DAILY_BUDGET_INR"] = "40"
    os.environ["ANON_EST_COST_INR"] = "10"
    os.environ["ANON_IP_DAILY_LIMIT"] = "100"
    with DBS.session() as s:
        s.execute(text("delete from anon_questions"))
        s.execute(text("delete from anon_counters"))
        s.commit()
    engine_adapter.reset_runner(engine_adapter.Runner(8, 8))
    ENG.mode, ENG.gate = "slow", threading.Event()
    codes = []
    lock = threading.Lock()

    def burst(i):
        r = anon(TestClient(app), ip=f"192.0.2.{i + 1}")
        with lock:
            codes.append((r.status_code, r.json().get("detail") if r.status_code != 200 else "ok"))
    ths = [threading.Thread(target=burst, args=(i,)) for i in range(12)]
    [t.start() for t in ths]
    for _ in range(200):
        with lock:
            if sum(1 for k in codes if k[0] == 429) >= 8:
                break
        time.sleep(0.05)
    ENG.gate.set()
    [t.join(60) for t in ths]
    ENG.mode = "ok"
    ok_n = sum(1 for k in codes if k[0] == 200)
    check(ok_n == 4 and sum(1 for k in codes if k == (429, "trial_budget_spent")) == 8, f"12 simultaneous trial questions with a budget of Rs 40 at an estimate of Rs 10 each: exactly 4 are admitted, 8 are turned away ({ok_n} admitted, {len(codes) - ok_n} refused)")
    with DBS.session() as s:
        check(s.execute(select(func.count()).select_from(M.AnonQuestion).where(M.AnonQuestion.cost_inr.is_(None))).scalar() == 0, "...and every admitted question's cost was recorded when it finished")
    os.environ["ANON_DAILY_BUDGET_INR"] = "0"
    check(anon(TestClient(app), ip="192.0.2.99").json()["detail"] == "trial_closed", "a budget of 0 closes the trial again")
finally:
    pg.stop()

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
