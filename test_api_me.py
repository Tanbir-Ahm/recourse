"""
test_api_me.py -- consent, the 18+ declaration, export and delete-my-data (api/consent.py, api/routers/me.py, api/legal/; website design WEBSITE_DESIGN.md sections 8 and 9, step A3.2). Free and offline: a throwaway PostgreSQL (SKIPPED
and exit 0 where none exists) and the Streamlit service's signed token as the way to be somebody.
Proves: the privacy notice and terms must be accepted at their CURRENT version and exact text (a new version or a changed text asks again), the acceptance records the version and the SHA-256 of the text shown; the age declaration is
required and idempotent; accounts cannot be opened on placeholder legal text (gate G1) unless the staging override is set; export gives a person exactly their own data and nothing else (no other person's, no session or address hashes);
delete needs a deliberate confirmation, removes the account and everything the person owns at once, leaves usage and audit rows with no person and no text, and clears the cookies; a deleted person who signs in again is a NEW account.
Run: python -X utf8 test_api_me.py
"""
import hashlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "API_ACCESS_TOKEN", "ACCOUNTS_OPEN", "GOOGLE_CLIENT_ID", "STREAMLIT_API_SECRET", "IP_HASH_SECRET", "CORS_ALLOW_ORIGINS", "TRUSTED_PROXY_HOPS", "API_COOKIE_SECURE", "API_RUN_MIGRATIONS", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL"):
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
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select, text

    from api import consent as CON
    from api.auth import google as G
    from api.auth import streamlit_token as ST
    from api.db import migrate as MIG
    from api.db import models as M
    from api.db import session as DBS
    from api.main import app

    SECRET = "s" * 40
    CLIENT = "client.example"
    pg.create_db("me")
    os.environ.update({"DATABASE_URL": pg.url("me"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "GOOGLE_CLIENT_ID": CLIENT, "API_COOKIE_SECURE": "off"})
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())
    c = TestClient(app)

    def H(sub, email):
        return {"Authorization": "Bearer " + ST.mint(SECRET, sub, email)}

    A = ("a-sub", "alice@example.com")
    B = ("b-sub", "bob@example.com")

    # ------------------------------------------------------------ the public text
    r = c.get("/api/legal/privacy")
    check(r.status_code == 200 and r.json()["placeholder"] is True and r.json()["text"].startswith("PLACEHOLDER") and r.json()["version"] == "PLACEHOLDER-0", "the privacy text is public and says it is a placeholder")
    check(c.get("/api/legal/data_use").status_code == 200 and c.get("/api/legal/cookies").status_code == 404, "the optional document is public too; an unknown one is 404")

    mu = c.get("/api/me", headers=H(*A)).json()["usage"]
    check(mu["answer_layman"]["limit"] == 10 and mu["answer_layman"]["used"] == 0 and mu["answer_lawyer"]["limit"] == 3 and mu["answer_layman"]["resets_at"], f"/api/me carries today's usage and limits ({mu['answer_layman']})")

    # ------------------------------------------------------------ consent flow
    me = c.get("/api/me", headers=H(*A)).json()
    check([m["document"] for m in me["consent"]["missing"]] == ["privacy", "terms"] and me["consent"]["age_confirmed"] is False and me["consent"]["ready"] is False and me["consent"]["legal_text_is_placeholder"] is True,
          f"a new person must accept the privacy notice and the terms and declare their age ({me['consent']})")
    check(c.post("/api/me/consent", json={"document": "privacy", "version": "OLD-1"}, headers=H(*A)).status_code == 409, "accepting a stale version is refused (409)")
    check(c.post("/api/me/consent", json={"document": "cookies", "version": "x"}, headers=H(*A)).status_code == 404, "accepting an unknown document is refused (404)")
    r = c.post("/api/me/consent", json={"document": "privacy", "version": "PLACEHOLDER-0"}, headers=H(*A))
    check(r.status_code == 200 and r.json()["document"] == "privacy", "accepting the current privacy notice: 200")
    c.post("/api/me/consent", json={"document": "privacy", "version": "PLACEHOLDER-0"}, headers=H(*A))
    with DBS.session() as s:
        rows = s.execute(select(M.Consent)).scalars().all()
        check(len(rows) == 1 and rows[0].text_hash == hashlib.sha256(CON.current("privacy")["text"].encode("utf-8")).hexdigest() and rows[0].version == "PLACEHOLDER-0", "the acceptance records the version and the SHA-256 of the text shown, once however often it is repeated")
    me = c.get("/api/me", headers=H(*A)).json()
    check([m["document"] for m in me["consent"]["missing"]] == ["terms"], "after the notice only the terms are missing")
    c.post("/api/me/consent", json={"document": "terms", "version": "PLACEHOLDER-0"}, headers=H(*A))
    me = c.get("/api/me", headers=H(*A)).json()
    check(me["consent"]["missing"] == [] and me["consent"]["ready"] is False, "both documents accepted but no age declaration: not ready")
    check(c.post("/api/me/age", json={"confirmed": False}, headers=H(*A)).status_code == 422, "age 'not confirmed' is refused (422)")
    check(c.post("/api/me/age", json={}, headers=H(*A)).status_code == 422, "no answer about age is refused (422)")
    check(c.post("/api/me/age", json={"confirmed": True}, headers=H(*A)).json() == {"age_confirmed": True}, "age confirmed")
    with DBS.session() as s:
        t1 = s.execute(select(M.User.age_confirmed_at).where(M.User.email == A[1])).scalar()
    time.sleep(0.05)
    c.post("/api/me/age", json={"confirmed": True}, headers=H(*A))
    with DBS.session() as s:
        t2 = s.execute(select(M.User.age_confirmed_at).where(M.User.email == A[1])).scalar()
    check(t1 is not None and t1 == t2, "confirming again keeps the first timestamp")
    check(c.get("/api/me", headers=H(*A)).json()["consent"]["ready"] is True, "all three done: ready")

    # a new version, or the same version with a changed text, asks again
    real = CON._config
    CON._config = lambda: {**real(), "documents": {**real()["documents"], "privacy": {"version": "V2", "file": "privacy.md", "placeholder": True}}}
    check([m["document"] for m in c.get("/api/me", headers=H(*A)).json()["consent"]["missing"]] == ["privacy"], "a new privacy version: the person is asked again")
    check(c.post("/api/me/consent", json={"document": "privacy", "version": "PLACEHOLDER-0"}, headers=H(*A)).status_code == 409, "...and the old version can no longer be accepted")
    check(c.post("/api/me/consent", json={"document": "privacy", "version": "V2"}, headers=H(*A)).status_code == 200 and c.get("/api/me", headers=H(*A)).json()["consent"]["missing"] == [], "...and accepting V2 clears it")
    CON._config = real
    orig_current = CON.current

    def changed(document):
        cur = orig_current(document)
        if document == "terms":
            cur = {**cur, "text": cur["text"] + " (edited)", "text_hash": hashlib.sha256((cur["text"] + " (edited)").encode()).hexdigest()}
        return cur
    CON.current = changed
    check([m["document"] for m in c.get("/api/me", headers=H(*A)).json()["consent"]["missing"]] == ["privacy", "terms"], "the same version with a changed text asks again (privacy is back to the first version: its V2 acceptance no longer matches)")
    CON.current = orig_current

    # ------------------------------------------------------------ gate G1
    del os.environ["ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL"]
    r = c.get("/api/me", headers=H(*A))
    check(r.status_code == 503 and r.json()["detail"] == "legal text is not final", "without the staging override, accounts stay closed while the legal text is a placeholder")
    CON._config = lambda: {"required": ["privacy", "terms"], "documents": {d: {**v, "placeholder": False} for d, v in real()["documents"].items()}}
    check(c.get("/api/me", headers=H(*A)).status_code == 200, "once both required documents are marked as the lawyer's text, accounts open")
    CON._config = real
    os.environ["ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL"] = "on"

    # ------------------------------------------------------------ export
    with DBS.session() as s:
        ua = s.execute(select(M.User).where(M.User.email == A[1])).scalar_one()
        ub_h = c.get("/api/me", headers=H(*B)).json()["user"]["id"]
        ub = s.get(M.User, __import__("uuid").UUID(ub_h))
        for u, tag in ((ua, "ALICE"), (ub, "BOB")):
            ch = M.Chat(user_id=u.id, title=f"{tag} chat")
            ch.messages = [M.Message(role="user", seq=1, content=f"{tag} question"), M.Message(role="assistant", seq=2, content=f"{tag} answer", result={"state": "single_match", "who": tag}, state="single_match", cost_inr=2.5)]
            s.add(ch)
            s.flush()
            s.add_all([M.Note(user_id=u.id, body=f"{tag} note"), M.Feedback(user_id=u.id, kind="unclear", comment=f"{tag} feedback"), M.UsageEvent(user_id=u.id, kind="answer_layman", cost_inr=2.5)])
        s.add(M.Session(id="x" * 64, user_id=ua.id, expires_at=func.now(), ip_hash="iphash123"))
        s.commit()
        aid = str(ua.id)
    r = c.post("/api/me/export", headers=H(*A))
    d = r.json()
    check(r.status_code == 200 and "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store", "export is a file download that is not cached")
    check(d["account"]["email"] == A[1] and d["account"]["id"] == aid and d["sign_in_methods"] == [{"provider": "google", "since": d["sign_in_methods"][0]["since"]}], "export has the account and the sign-in method (the provider, not the subject)")
    check(len(d["consents"]) >= 3 and d["chats"][0]["title"] == "ALICE chat" and [m["content"] for m in d["chats"][0]["messages"]] == ["ALICE question", "ALICE answer"], "export has the consents and the whole chat in order")
    check(d["chats"][0]["messages"][1]["result"] == {"state": "single_match", "who": "ALICE"} and d["chats"][0]["messages"][1]["cost_inr"] == 2.5, "...with the answer's structured result and cost")
    check(d["notes"][0]["body"] == "ALICE note" and d["feedback"][0]["comment"] == "ALICE feedback" and d["usage"][0]["kind"] == "answer_layman", "export has notes, feedback and usage")
    blob = r.text
    check("BOB" not in blob and "bob@example.com" not in blob, "export holds nothing of any other person")
    check("iphash123" not in blob and "x" * 64 not in blob and "a-sub" not in blob, "export holds no session, address hash or sign-in subject")

    # ------------------------------------------------------------ delete
    check(c.delete("/api/me", headers=H(*A)).status_code == 422 and c.delete("/api/me?confirm=yes", headers=H(*A)).status_code == 422, "delete without the exact confirmation is refused (422)")
    with DBS.session() as s:
        check(s.execute(select(func.count()).select_from(M.User).where(M.User.email == A[1])).scalar() == 1, "...and nothing was deleted")
    r = c.delete("/api/me?confirm=DELETE", headers=H(*A))
    check(r.status_code == 200 and r.json() == {"deleted": True}, "delete with the confirmation: 200")
    with DBS.session() as s:
        left = {t: s.execute(text(f"select count(*) from {t} where user_id = :i"), {"i": aid}).scalar() for t in ("identities", "sessions", "consents", "chats", "notes", "feedback")}
        check(s.execute(select(func.count()).select_from(M.User).where(M.User.email == A[1])).scalar() == 0 and all(v == 0 for v in left.values()), f"the account and everything the person owned are gone ({left})")
        check(s.execute(select(func.count()).select_from(M.Message).where(M.Message.content.like("ALICE%"))).scalar() == 0, "...including every message")
        check(s.execute(select(func.count()).select_from(M.Chat).where(M.Chat.title == "BOB chat")).scalar() == 1 and s.execute(select(func.count()).select_from(M.User).where(M.User.email == B[1])).scalar() == 1, "another person's data is untouched")
        ue = s.execute(select(M.UsageEvent.user_id, M.UsageEvent.cost_inr).order_by(M.UsageEvent.at)).all()
        check(sorted([str(x[0]) for x in ue]).count("None") == 1 and len(ue) == 2, f"the usage row stays with no person attached ({ue})")
        al = s.execute(select(M.AuditLog)).scalars().all()
        check(len(al) == 1 and al[0].action == "user_deleted" and al[0].actor_user_id is None and al[0].target_id == hashlib.sha256(aid.encode()).hexdigest()[:16] and aid not in str(al[0].target_id) and A[1] not in str(al[0].detail), "the audit row says a user was deleted, by a reference that is not the user id, with no email")
        dr = s.execute(select(M.DeletionRequest)).scalars().all()
        check(len(dr) == 1 and dr[0].user_id is None and dr[0].completed_at is not None, "the deletion request is recorded as completed, with no person attached")
    r = c.get("/api/me", headers=H(*A))
    new_id = r.json()["user"]["id"]
    check(r.status_code == 200 and new_id != aid and r.json()["consent"]["ready"] is False, "the same person signing in again is a NEW account that must accept everything again")

    # ------------------------------------------------------------ delete through a cookie session
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Jw:
        def get_signing_key_from_jwt(self, t):
            import types
            return types.SimpleNamespace(key=rsa_key.public_key())
    G._CLIENT["c"] = Jw()
    now = int(time.time())
    gt = jwt.encode({"iss": "https://accounts.google.com", "aud": CLIENT, "sub": "cookie-sub", "email": "carol@example.com", "email_verified": True, "iat": now, "exp": now + 600}, rsa_key, algorithm="RS256")
    cc = TestClient(app)
    csrf = cc.post("/api/auth/google", json={"id_token": gt}).json()["csrf"]
    r = cc.delete("/api/me?confirm=DELETE")
    check(r.status_code == 403 and r.json()["detail"] == "csrf", "delete through the cookie without the CSRF header is refused (403)")
    with DBS.session() as s:
        check(s.execute(select(func.count()).select_from(M.User).where(M.User.email == "carol@example.com")).scalar() == 1, "...and nothing was deleted")
    r = cc.delete("/api/me?confirm=DELETE", headers={"X-CSRF-Token": csrf})
    cookies_cleared = [x.lower() for x in r.headers.get_list("set-cookie")]
    check(r.status_code == 200 and any(x.startswith("rc_session=") and ("max-age=0" in x or "expires=" in x) for x in cookies_cleared), "delete through the cookie with the CSRF header: 200 and the session cookie is cleared")
    check(cc.get("/api/me").status_code == 401, "...and the old cookie no longer signs anyone in")
finally:
    pg.stop()

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
