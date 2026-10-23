"""
test_api_auth.py -- sign-in for the API (api/auth/, api/deps.py, api/routers/auth.py, api/routers/me.py, api/netutil.py; website design WEBSITE_DESIGN.md 1.3 and 9, step A3.1). Free and offline: Google is a stand-in (a fresh RSA key and a
key-fetcher that returns it), the database is a throwaway PostgreSQL (tests print SKIPPED and exit 0 where none exists; the token checks that need no database still run).
Proves: a Google ID token is accepted only if it is signed by Google's key, issued by Google, for OUR client id, unexpired and email-verified (and not by the old trick of re-signing with a shared secret); the Streamlit service's token is
accepted only if signed with the shared secret, for this API, short-lived and used ONCE; sign-in is closed (503) until ACCOUNTS_OPEN=on; a session cookie holds a random value whose hash (not the value) is stored, is HttpOnly, SameSite=Lax and Secure
by default, and every call that changes something also needs the CSRF header bound to that session; the same person is one user however they arrive; a suspended or deleted account never signs in; no error carries text from a token.
Run: python -X utf8 test_api_auth.py
"""
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "API_ACCESS_TOKEN", "ACCOUNTS_OPEN", "GOOGLE_CLIENT_ID", "STREAMLIT_API_SECRET", "IP_HASH_SECRET", "CORS_ALLOW_ORIGINS", "TRUSTED_PROXY_HOPS", "CLIENT_IP_HEADER", "FRONTEND_PROXY_SECRET", "API_COOKIE_SECURE", "API_RUN_MIGRATIONS", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL"):
    os.environ.pop(_v, None)

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


from api import netutil
from api.auth import google as G
from api.auth import streamlit_token as ST
from api.auth.errors import AuthError

CLIENT = "recourse-test-client.apps.example"
SECRET = "s" * 40
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJwks:
    def __init__(self, pub, fail=False):
        self.pub, self.fail = pub, fail

    def get_signing_key_from_jwt(self, token):
        if self.fail:
            raise OSError("network down")
        return types.SimpleNamespace(key=self.pub)


JWKS = FakeJwks(KEY.public_key())


def gtoken(sub="g-1", email="Person@Example.com", verified=True, aud=CLIENT, iss="https://accounts.google.com", exp_in=3600, key=KEY, name="A Person", drop=(), alg="RS256"):
    now = int(time.time())
    c = {"iss": iss, "aud": aud, "sub": sub, "email": email, "email_verified": verified, "iat": now, "exp": now + exp_in, "name": name}
    for d in drop:
        c.pop(d, None)
    return jwt.encode(c, key, algorithm=alg, headers={"kid": "k1"})


def expect(fn, code, status=None):
    try:
        fn()
    except AuthError as exc:
        return exc.code == code and (status is None or exc.status == status)
    return False


# ---------------------------------------------------------------- Google ID tokens (no database needed)
ok = G.verify_id_token(gtoken(), CLIENT, JWKS)
check(ok == {"sub": "g-1", "email": "Person@Example.com", "email_verified": True, "name": "A Person"}, f"a valid Google token is accepted ({ok})")
check(expect(lambda: G.verify_id_token(gtoken(), "", JWKS), "google_sign_in_off", 503), "no GOOGLE_CLIENT_ID configured: Google sign-in is off (503)")
check(expect(lambda: G.verify_id_token(gtoken(aud="someone-elses-client"), CLIENT, JWKS), "bad_token"), "a token issued for another client id is refused")
check(expect(lambda: G.verify_id_token(gtoken(iss="https://evil.example"), CLIENT, JWKS), "bad_token"), "a token from another issuer is refused")
check(G.verify_id_token(gtoken(iss="accounts.google.com"), CLIENT, JWKS)["sub"] == "g-1", "Google's other issuer spelling is accepted")
check(expect(lambda: G.verify_id_token(gtoken(exp_in=-3600), CLIENT, JWKS), "token_expired"), "an expired token is refused")
check(expect(lambda: G.verify_id_token(gtoken(verified=False), CLIENT, JWKS), "email_not_verified", 403), "an unverified email is refused (403)")
check(G.verify_id_token(gtoken(verified="true"), CLIENT, JWKS)["email_verified"] is True, "Google's string 'true' for email_verified is accepted")
check(expect(lambda: G.verify_id_token(gtoken(key=OTHER), CLIENT, JWKS), "bad_token"), "a token signed with a different key is refused")
check(expect(lambda: G.verify_id_token(gtoken(drop=("exp",)), CLIENT, JWKS), "bad_token"), "a token with no expiry is refused")
check(expect(lambda: G.verify_id_token(gtoken(drop=("sub",)), CLIENT, JWKS), "bad_token"), "a token with no subject is refused")
check(expect(lambda: G.verify_id_token(gtoken(email="not-an-email"), CLIENT, JWKS), "bad_token"), "a token whose email is not an email is refused")
hs = jwt.encode({"iss": "https://accounts.google.com", "aud": CLIENT, "sub": "x", "email": "a@b.co", "email_verified": True, "iat": int(time.time()), "exp": int(time.time()) + 600}, "any-shared-secret-value-here-123456", algorithm="HS256")
check(expect(lambda: G.verify_id_token(hs, CLIENT, JWKS), "bad_token"), "a token re-signed with a shared secret (the algorithm-confusion trick) is refused")
check(expect(lambda: G.verify_id_token('{"alg":"none"}.e30.', CLIENT, JWKS), "bad_token") and expect(lambda: G.verify_id_token("", CLIENT, JWKS), "bad_token") and expect(lambda: G.verify_id_token("x" * 9000, CLIENT, JWKS), "bad_token") and expect(lambda: G.verify_id_token(None, CLIENT, JWKS), "bad_token"), "garbage, an empty token, an oversized token and None are refused")
check(expect(lambda: G.verify_id_token(gtoken(), CLIENT, FakeJwks(None, fail=True)), "keys_unavailable", 503), "Google's keys cannot be fetched: 503, not a verdict on the token")
try:
    G.verify_id_token("bad.token.CANARYTEXT", CLIENT, JWKS)
except AuthError as exc:
    check("CANARYTEXT" not in str(exc) and "CANARYTEXT" not in exc.code, "an error carries a fixed code, never text from the token")

# ---------------------------------------------------------------- Streamlit's signed tokens (no database needed)
def smint(**kw):
    return ST.mint(kw.pop("secret", SECRET), kw.pop("sub", "g-9"), kw.pop("email", "stream@example.com"), **kw)


v = ST.verify(smint(name="Stream Person"), SECRET)
check(v == {"sub": "g-9", "email": "stream@example.com", "email_verified": True, "name": "Stream Person"}, f"a fresh Streamlit token is accepted ({v})")
t = smint()
ST.verify(t, SECRET)
check(expect(lambda: ST.verify(t, SECRET), "token_reused"), "the same token a second time is refused (used once)")
check(expect(lambda: ST.verify(smint(), "w" * 40), "bad_token"), "a token signed with another secret is refused")
check(expect(lambda: ST.verify(smint(), ""), "streamlit_sign_in_off", 503), "no STREAMLIT_API_SECRET: that path is off (503)")
check(expect(lambda: ST.verify(smint(ttl=-100), SECRET), "token_expired"), "an expired token is refused")
check(expect(lambda: ST.verify(smint(ttl=3600), SECRET), "bad_token"), "a token valid for an hour is refused (at most ten minutes)")
check(expect(lambda: ST.verify(smint(now=time.time() + 3600, ttl=300), SECRET), "bad_token"), "a token dated in the future is refused")
check(expect(lambda: ST.verify(smint(email_verified=False), SECRET), "email_not_verified", 403), "an unverified email is refused (403)")
def forge(**over):
    now = int(time.time())
    c = {"iss": ST.ISSUER, "aud": ST.AUDIENCE, "sub": "s", "email": "a@b.co", "email_verified": True, "iat": now, "exp": now + 300, "jti": "j-" + str(time.time_ns())}
    c.update(over)
    return jwt.encode({k: v_ for k, v_ in c.items() if v_ is not None}, SECRET, algorithm="HS256")


check(expect(lambda: ST.verify(forge(aud="other-api"), SECRET), "bad_token"), "a token for another audience is refused")
check(expect(lambda: ST.verify(forge(iss="not-streamlit"), SECRET), "bad_token"), "a token from another issuer is refused")
check(expect(lambda: ST.verify(forge(jti=None), SECRET), "bad_token"), "a token with no jti is refused")
check(expect(lambda: ST.verify(forge(email="nope"), SECRET), "bad_token"), "a token whose email is not an email is refused")
check(expect(lambda: ST.verify(jwt.encode({"iss": ST.ISSUER}, "", algorithm="none"), SECRET), "bad_token"), "an unsigned (alg none) token is refused")
rc = ST.ReplayCache(limit=3)
check(rc.add("a", 1000, now=10) and not rc.add("a", 1000, now=11) and rc.add("a", 2000, now=1001), "the replay memory forgets a token once it has expired")
rc = ST.ReplayCache(limit=2)
check(rc.add("a", 10**9, now=1) and rc.add("b", 10**9, now=1) and not rc.add("c", 10**9, now=1), "a full replay memory refuses rather than forgets a live token")
check(ST.REPLAY is not None and sys.getsizeof(ST.REPLAY) > 0, "the process-wide replay memory exists")

# ---------------------------------------------------------------- addresses
class Req:
    def __init__(self, xff=None, host="10.0.0.9", real=None, secret=None, visitor=None):
        self.headers = {k: v for k, v in (("x-forwarded-for", xff), ("x-real-ip", real), ("x-frontend-secret", secret), ("x-visitor-ip", visitor)) if v}
        self.client = types.SimpleNamespace(host=host)


check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2")) == "2.2.2.2", "one trusted proxy: the address is the LAST entry (the one our proxy added)")
check(netutil.client_ip(Req("9.9.9.9, 3.3.3.3")) == "3.3.3.3", "a caller who sends its own X-Forwarded-For cannot choose its address")
os.environ["TRUSTED_PROXY_HOPS"] = "2"
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2")) == "1.1.1.1", "two trusted proxies: the second from the right")
os.environ["TRUSTED_PROXY_HOPS"] = "0"
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2")) == "10.0.0.9", "no trusted proxy: the connection's own address")
os.environ.pop("TRUSTED_PROXY_HOPS")
check(netutil.client_ip(Req()) == "10.0.0.9", "no header: the connection's own address")
# what Railway's edge was measured to send on 2026-10-23 (FOLLOW_UPS 2bz): the visitor first, an edge address last, X-Real-IP = the visitor
R1, R2 = Req("49.37.108.90, 152.233.15.120", real="49.37.108.90"), Req("49.37.108.90, 152.233.15.77", real="49.37.108.90")
check(netutil.client_ip(R1) != netutil.client_ip(R2), "the default (last entry) rule sees a DIFFERENT address on each request on Railway: the bug found on staging")
os.environ["CLIENT_IP_HEADER"] = "x-real-ip"
check(netutil.client_ip(R1) == netutil.client_ip(R2) == "49.37.108.90", "CLIENT_IP_HEADER=x-real-ip: the visitor, the same on every request")
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2")) == "2.2.2.2", "...and with no X-Real-IP it falls back to the default rule")
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2", real="not-an-address")) == "2.2.2.2" and netutil.client_ip(Req("1.1.1.1, 2.2.2.2", real="9" * 100)) == "2.2.2.2", "...a header that is not an address is ignored")
check(netutil.client_ip(Req(real="2001:db8:1:2:aaaa:bbbb:cccc:dddd")) == "2001:db8:1:2::" and netutil.client_ip(Req(real="2001:db8:1:2:1:2:3:4")) == "2001:db8:1:2::", "an IPv6 visitor is grouped by its /64 (the lower half changes on one connection)")
os.environ["CLIENT_IP_HEADER"] = "xff-first"
check(netutil.client_ip(R1) == netutil.client_ip(R2) == "49.37.108.90", "CLIENT_IP_HEADER=xff-first: the first entry, the same on every request")
check(netutil.client_ip(Req("garbage, 2.2.2.2")) == "2.2.2.2", "...a first entry that is not an address is ignored")
os.environ["CLIENT_IP_HEADER"] = "banana"
check(netutil.client_ip(R1) == "152.233.15.120", "an unknown value of CLIENT_IP_HEADER means the default rule")
os.environ.pop("CLIENT_IP_HEADER")
# the new front end's server vouches for the visitor's address
FES = "f" * 40
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2", secret=FES, visitor="7.7.7.7")) == "2.2.2.2", "no FRONTEND_PROXY_SECRET set: X-Visitor-IP is ignored (anyone could send it)")
os.environ["FRONTEND_PROXY_SECRET"] = FES
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2", secret=FES, visitor="7.7.7.7")) == "7.7.7.7", "with the secret set and sent: the visitor address the front end names is used")
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2", secret="x" * 40, visitor="7.7.7.7")) == "2.2.2.2" and netutil.client_ip(Req("1.1.1.1, 2.2.2.2", visitor="7.7.7.7")) == "2.2.2.2", "a wrong or missing secret: X-Visitor-IP is ignored")
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2", secret=FES, visitor="not-an-ip")) == "2.2.2.2" and netutil.client_ip(Req("1.1.1.1, 2.2.2.2", secret=FES)) == "2.2.2.2", "the right secret but no valid visitor address: the ordinary rule")
check(netutil.client_ip(Req(secret=FES, visitor="2001:db8:1:2:aaaa:bbbb:cccc:dddd")) == "2001:db8:1:2::", "an IPv6 visitor from the front end is grouped by /64 as well")
os.environ["FRONTEND_PROXY_SECRET"] = "short"
check(netutil.client_ip(Req("1.1.1.1, 2.2.2.2", secret="short", visitor="7.7.7.7")) == "2.2.2.2", "a secret under 32 characters counts as unset")
os.environ.pop("FRONTEND_PROXY_SECRET")
check(netutil.ip_hash("1.2.3.4") is None, "no IP_HASH_SECRET: no hash (the features that need one refuse)")
os.environ["IP_HASH_SECRET"] = "k" * 40
h1, h2 = netutil.ip_hash("1.2.3.4"), netutil.ip_hash("1.2.3.5")
check(h1 and h1 != h2 and h1 == netutil.ip_hash("1.2.3.4") and "1.2.3.4" not in h1 and len(h1) == 48, "an IP is scrambled the same way each time, differently per address, and the address is not in it")
os.environ["IP_HASH_SECRET"] = "z" * 40
check(netutil.ip_hash("1.2.3.4") != h1, "a different secret gives different hashes")
os.environ.pop("IP_HASH_SECRET")

# ---------------------------------------------------------------- the database flows
import pg_harness

pg = pg_harness.start()
if pg is None:
    print("(the database flows were not run)")
    print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1 if FAILURES else 0)
try:
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select, text

    from api.auth import sessions as SES
    from api.db import migrate as MIG
    from api.db import models as M
    from api.db import session as DBS
    from api.main import app

    pg.create_db("auth")
    os.environ["DATABASE_URL"] = pg.url("auth")
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())
    G._CLIENT["c"] = JWKS

    def counts():
        with DBS.session() as s:
            return {k: s.execute(select(func.count()).select_from(t)).scalar() for k, t in (("users", M.User), ("identities", M.Identity), ("sessions", M.Session))}

    c = TestClient(app)
    # closed by default
    r = c.post("/api/auth/google", json={"id_token": gtoken()})
    check(r.status_code == 503 and r.json()["detail"] == "accounts are not open yet", f"ACCOUNTS_OPEN unset: sign-in answers 503 ({r.status_code})")
    check(c.get("/api/me").status_code == 503 and c.post("/api/auth/logout").status_code == 503, "...and so does every signed-in route")
    check(counts() == {"users": 0, "identities": 0, "sessions": 0}, "...and nothing was created")
    os.environ["ACCOUNTS_OPEN"] = "on"
    r = c.post("/api/auth/google", json={"id_token": gtoken()})
    check(r.status_code == 503 and r.json()["detail"] == "legal text is not final", f"accounts open but the privacy notice and terms are still placeholders: 503 (gate G1) ({r.json()})")
    os.environ["ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL"] = "on"
    r = c.post("/api/auth/google", json={"id_token": gtoken()})
    check(r.status_code == 503 and r.json()["detail"] == "google_sign_in_off", "accounts open but no GOOGLE_CLIENT_ID: Google sign-in is off")
    os.environ["GOOGLE_CLIENT_ID"] = CLIENT
    os.environ["STREAMLIT_API_SECRET"] = SECRET
    os.environ["IP_HASH_SECRET"] = "i" * 40

    # a secure cookie by default
    r = c.post("/api/auth/google", json={"id_token": gtoken()})
    sc = [x.lower() for x in r.headers.get_list("set-cookie")]
    sess_c = [x for x in sc if x.startswith("rc_session=")][0]
    csrf_c = [x for x in sc if x.startswith("rc_csrf=")][0]
    check(r.status_code == 200 and "httponly" in sess_c and "secure" in sess_c and "samesite=lax" in sess_c and "max-age=2592000" in sess_c, f"sign-in sets the session cookie HttpOnly, Secure, SameSite=Lax, 30 days ({sess_c[:80]})")
    check("httponly" not in csrf_c and "secure" in csrf_c, "...and a readable CSRF cookie (no HttpOnly)")
    check(r.json()["user"]["email"] == "person@example.com" and r.json()["user"]["role"] == "user", f"the email is stored lower-case, the role is 'user' ({r.json()['user']})")
    raw_cookie = sess_c.split("=", 1)[1].split(";", 1)[0]
    with DBS.session() as s:
        row = s.execute(select(M.Session)).scalars().first()
        u = s.execute(select(M.User)).scalar_one()
        plan = s.get(M.Plan, u.plan_id)
        check(row.id != raw_cookie and len(row.id) == 64 and raw_cookie not in str(row.id), "the database stores a hash of the cookie value, not the value")
        check(plan.code == "free" and u.email_verified is True and u.last_seen_at is not None, "a new person is on the free plan, email verified, last-seen set")
        check(row.ip_hash and "testclient" not in row.ip_hash and row.user_agent_hash is not None and len(row.ip_hash) == 48, "the session keeps a scrambled address and a scrambled browser id")
    check(r.json()["csrf"] == csrf_c.split("=", 1)[1].split(";", 1)[0], "the CSRF value in the reply is the one in the cookie")

    # plain-http cookies for the rest (a test client over http would not send Secure cookies back)
    os.environ["API_COOKIE_SECURE"] = "off"
    c = TestClient(app)
    r = c.post("/api/auth/google", json={"id_token": gtoken()})
    csrf = r.json()["csrf"]
    check(c.get("/api/me").json()["user"]["email"] == "person@example.com" and c.get("/api/me").json()["via"] == "session", "with the cookie, /api/me knows who it is")
    n = counts()
    check(n["users"] == 1 and n["identities"] == 1 and n["sessions"] == 2, f"the same person signing in again: still ONE user and one identity, a new session each time ({n})")
    c2 = TestClient(app)
    c2.post("/api/auth/google", json={"id_token": gtoken(sub="g-OTHER-SUBJECT")})
    n = counts()
    check(n["users"] == 1 and n["identities"] == 2, f"another Google subject with the same verified email is the same person ({n})")
    c3 = TestClient(app)
    r3 = c3.post("/api/auth/google", json={"id_token": gtoken(sub="g-3", email="Third@Example.com")})
    check(r3.status_code == 200 and counts()["users"] == 2, "a different email is a different person")

    # CSRF, origin
    check(c.post("/api/auth/logout").status_code == 403 and c.post("/api/auth/logout").json()["detail"] == "csrf", "a call that changes something without the CSRF header is refused (403)")
    check(c.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403, "...and with a wrong one")
    check(c.post("/api/auth/logout", headers={"X-CSRF-Token": SES.csrf_for("some-other-session")}).status_code == 403, "...and with the token of another session")
    os.environ["CORS_ALLOW_ORIGINS"] = "https://app.recourse.example/"
    check(c.post("/api/auth/logout", headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}).status_code == 403, "a right CSRF token from a wrong Origin is refused (403)")
    os.environ.pop("CORS_ALLOW_ORIGINS")
    # Bearer path
    sub_before = counts()
    tok = smint(sub="g-stream", email="Stream@Example.com")
    r = TestClient(app).get("/api/me", headers={"Authorization": "Bearer " + tok})
    check(r.status_code == 200 and r.json()["via"] == "streamlit" and r.json()["user"]["email"] == "stream@example.com", f"the Streamlit token signs a person in on first use ({r.status_code})")
    check(counts()["users"] == sub_before["users"] + 1 and counts()["sessions"] == sub_before["sessions"], "...creating the user and no session")
    r = TestClient(app).get("/api/me", headers={"Authorization": "Bearer " + tok})
    check(r.status_code == 401 and r.json()["detail"] == "token_reused", "the same Streamlit token twice: refused (401, token_reused)")
    r = TestClient(app).get("/api/me", headers={"Authorization": "Bearer " + smint(sub="g-stream", email="Stream@Example.com")})
    check(r.status_code == 200 and counts()["users"] == sub_before["users"] + 1, "a new token for the same person: the same user")
    r = c.get("/api/me", headers={"Authorization": "Bearer " + smint(sub="g-viaboth", email="both@example.com")})
    check(r.json()["via"] == "streamlit" and r.json()["user"]["email"] == "both@example.com", "when both a cookie and a Bearer token arrive, the Bearer token wins")
    r = TestClient(app).get("/api/me", headers={"Authorization": "Bearer " + smint(secret="q" * 40)})
    check(r.status_code == 401 and r.json()["detail"] == "bad_token", "a Bearer token signed with a wrong secret: 401")
    os.environ.pop("STREAMLIT_API_SECRET")
    r = TestClient(app).get("/api/me", headers={"Authorization": "Bearer " + tok})
    check(r.status_code == 503 and r.json()["detail"] == "streamlit_sign_in_off", "no STREAMLIT_API_SECRET: that path answers 503")
    os.environ["STREAMLIT_API_SECRET"] = SECRET
    # suspended, deleted
    with DBS.session() as s:
        s.execute(text("update users set status='suspended' where email='third@example.com'"))
        s.commit()
    r = TestClient(app).post("/api/auth/google", json={"id_token": gtoken(sub="g-3", email="Third@Example.com")})
    check(r.status_code == 403 and r.json()["detail"] == "account_unavailable", "a suspended account cannot sign in (403)")
    check(c3.get("/api/me").status_code == 401, "...and its existing session stops working")
    with DBS.session() as s:
        s.execute(text("update users set status='deleted' where email='third@example.com'"))
        s.commit()
    check(TestClient(app).post("/api/auth/google", json={"id_token": gtoken(sub="g-3", email="Third@Example.com")}).status_code == 403, "a deleted account cannot sign in")
    # expired session
    c4 = TestClient(app)
    c4.post("/api/auth/google", json={"id_token": gtoken(sub="g-4", email="four@example.com")})
    with DBS.session() as s:
        s.execute(text("update sessions set expires_at = now() - interval '1 minute' where user_id = (select id from users where email='four@example.com')"))
        s.commit()
    check(c4.get("/api/me").status_code == 401, "an expired session is refused (401)")
    with DBS.session() as s:
        left = s.execute(text("select count(*) from sessions where user_id = (select id from users where email='four@example.com')")).scalar()
    check(left == 0, "...and removed")
    check(TestClient(app).get("/api/me").status_code == 401 and TestClient(app).get("/api/me", headers={"Cookie": "rc_session=" + "x" * 300}).status_code == 401, "no cookie, or a nonsense cookie: 401")
    # logout
    r = c.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    check(r.status_code == 200 and r.json() == {"ok": True}, "logout with the CSRF header: 200")
    check(c.get("/api/me").status_code == 401, "...and the session is gone (401)")
    with DBS.session() as s:
        gone = s.get(M.Session, SES._hash(csrf)) is None
    check(gone, "(and the CSRF value is not a session id)")
    # no text from the ID token in errors
    r = TestClient(app).post("/api/auth/google", json={"id_token": "THIS.IS.CANARYTOKENTEXT"})
    check(r.status_code == 401 and "CANARYTOKENTEXT" not in r.text, "a bad ID token: 401 and its text is not echoed")
    r = TestClient(app).post("/api/auth/google", json={"id_token": "short"})
    check(r.status_code == 422, "an ID token that is too short is rejected by validation (422)")
    r = TestClient(app).post("/api/auth/google", json={"id_token": gtoken(verified=False)})
    check(r.status_code == 403 and r.json()["detail"] == "email_not_verified", "an unverified Google email cannot sign in (403)")
    G._CLIENT["c"] = FakeJwks(None, fail=True)
    r = TestClient(app).post("/api/auth/google", json={"id_token": gtoken()})
    check(r.status_code == 503 and r.json()["detail"] == "keys_unavailable", "Google's keys unreachable: 503")
    G._CLIENT["c"] = JWKS
finally:
    pg.stop()

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
