"""
test_site_e2e.py -- the whole A5 path in a real browser (SKIPPED where PostgreSQL, Authlib, Playwright or Chromium is missing). Free and offline: a throwaway PostgreSQL, the real API server with a stub engine (api_harness.py), a local stand-in for Google's sign-in
(review_results/2026-10-20_a0_spikes/fake_oidc.py logic, inlined here), the REAL Streamlit page with USE_API on, and headless Chromium. It is NOT Google: only the owner's staging test with a real Google client proves that.
Proves, in a browser: the page starts with the sign-in card; Streamlit's login configuration is handed over from the environment in memory (no secrets file is written) and the sign-in round trip works; the consent card appears for a new person and nothing is
asked before it is accepted; the question goes through the API, the answer and the usage line appear; the person stays signed in after a reload; the account was created in the database with the consents recorded; sign out brings the sign-in card back.
Run: python -X utf8 test_site_e2e.py
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def skip(why):
    print("SKIPPED:", why)
    sys.exit(0)


try:
    import authlib  # noqa: F401
except ImportError:
    skip("Authlib is not installed")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    skip("Playwright is not installed")
CHROME = next((p for p in ("/opt/pw-browsers/chromium-1194/chrome-linux/chrome", "/opt/pw-browsers/chromium/chrome-linux/chrome") if os.path.exists(p)), None)
if CHROME is None:
    skip("Chromium is not installed")
import api_harness
import pg_harness
pg = pg_harness.start()
if pg is None:
    skip("PostgreSQL is not installed")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


OIDC_PORT, SITE_PORT = free_port(), free_port()
OIDC = r'''
import secrets, time, os
from authlib.jose import JsonWebKey, jwt
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
import uvicorn
PORT = int(os.environ["OIDC_PORT"]); ISS = f"http://localhost:{PORT}"
KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "k1"}); CODES = {}
async def disco(r): return JSONResponse({"issuer": ISS, "authorization_endpoint": ISS + "/authorize", "token_endpoint": ISS + "/token", "jwks_uri": ISS + "/jwks", "response_types_supported": ["code"], "subject_types_supported": ["public"], "id_token_signing_alg_values_supported": ["RS256"], "scopes_supported": ["openid", "email", "profile"]})
async def jwks(r): return JSONResponse({"keys": [KEY.as_dict(is_private=False)]})
async def authorize(r):
    q = r.query_params; code = secrets.token_urlsafe(8); CODES[code] = {"nonce": q.get("nonce"), "client_id": q.get("client_id")}
    return RedirectResponse(f"{q['redirect_uri']}?code={code}&state={q['state']}")
async def token(r):
    form = await r.form(); info = CODES.pop(form["code"]); now = int(time.time())
    claims = {"iss": ISS, "sub": "1048576000000000000777", "aud": info["client_id"], "iat": now, "exp": now + 3600, "nonce": info["nonce"], "email": "e2e.person@example.com", "email_verified": True, "name": "E2E Person"}
    return JSONResponse({"access_token": "at-" + secrets.token_urlsafe(6), "token_type": "Bearer", "expires_in": 3600, "id_token": jwt.encode({"alg": "RS256", "kid": "k1"}, claims, KEY).decode()})
app = Starlette(routes=[Route("/.well-known/openid-configuration", disco), Route("/jwks", jwks), Route("/authorize", authorize), Route("/token", token, methods=["POST"])])
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
'''
procs = []
home = tempfile.mkdtemp(prefix="e2ehome_")
api = None
try:
    from sqlalchemy import func, select

    from api.db import models as M
    from api.db import session as DBS
    pg.create_db("e2e")
    SECRET = "e" * 40
    api = api_harness.start({"DATABASE_URL": pg.url("e2e"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "API_COOKIE_SECURE": "off", "API_RATE_LIMIT_PER_MINUTE": "0"})
    os.environ["DATABASE_URL"] = pg.url("e2e")
    DBS.reset_engine()
    procs.append(subprocess.Popen([sys.executable, "-c", OIDC], env={**os.environ, "OIDC_PORT": str(OIDC_PORT)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    env = {**os.environ, "HOME": home, "USERPROFILE": home, "USE_API": "on", "SITE_API_URL": api.url, "STREAMLIT_API_SECRET": SECRET, "GOOGLE_CLIENT_ID": "e2e-client", "GOOGLE_CLIENT_SECRET": "e2e-secret",
           "STREAMLIT_COOKIE_SECRET": "k" * 40, "SITE_URL": f"http://localhost:{SITE_PORT}", "SITE_OIDC_METADATA_URL": f"http://localhost:{OIDC_PORT}/.well-known/openid-configuration", "AUTHLIB_INSECURE_TRANSPORT": "1",
           "ANTHROPIC_API_KEY": "dummy", "VOYAGE_API_KEY": "dummy"}
    for v in ("RESPONSE_STYLE", "CHAT_MODE", "REGISTER_HOOKS"):
        env.pop(v, None)
    st_log = open(os.path.join(home, "streamlit.log"), "wb")
    procs.append(subprocess.Popen([sys.executable, "-m", "streamlit", "run", "recourse_app.py", "--server.port", str(SITE_PORT), "--server.address", "127.0.0.1", "--server.headless", "true", "--server.enableCORS", "false",
                                   "--browser.gatherUsageStats", "false"], env=env, cwd=HERE, stdout=st_log, stderr=subprocess.STDOUT))
    end = time.time() + 90
    while time.time() < end:
        try:
            urllib.request.urlopen(f"http://localhost:{SITE_PORT}/_stcore/health", timeout=2).read()
            urllib.request.urlopen(f"http://localhost:{OIDC_PORT}/.well-known/openid-configuration", timeout=2).read()
            break
        except OSError:
            time.sleep(0.5)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg_ = b.new_page()
        pg_.set_default_timeout(60000)
        pg_.goto(f"http://localhost:{SITE_PORT}", wait_until="networkidle")
        try:
            pg_.wait_for_selector("text=Sign in to ask", timeout=40000)
        except Exception:                                  # show what the page did show: the failure is then readable
            print("PAGE TEXT:", pg_.inner_text("body")[:1500])
            raise
        body = pg_.inner_text("body")
        check("Sign in with Google" in body and "Describe your situation" not in body and "Check my situation" not in body, "signed out: the sign-in card, and no question box")
        check(not os.path.exists(os.path.join(home, ".streamlit", "secrets.toml")) and "auth" not in open(os.path.join(HERE, ".streamlit", "secrets.toml"), encoding="utf-8").read(), "the login settings came from the environment in memory: no secrets file was written anywhere")
        pg_.get_by_role("button", name="Sign in with Google").click()
        pg_.wait_for_selector("text=Before you start")
        body = pg_.inner_text("body")
        check("Before you start" in body and "Check my situation" not in body, "signed in through the (stand-in) provider: the consent card, and still no question box")
        pg_.get_by_text("I have read and I accept").click()
        pg_.get_by_text("I am 18 years old or older").click()
        pg_.get_by_role("button", name="Accept and continue").click()
        pg_.wait_for_selector("text=Signed in as e2e.person@example.com")
        body = pg_.inner_text("body")
        check("10 of 10 answers left today" in body and "Check my situation" in body, "after accepting: who is signed in, 10 of 10 left, the question box")
        pg_.get_by_placeholder("e.g. My brother was arrested four days ago").fill("What happens at a remand hearing before a magistrate in India today?")
        pg_.get_by_role("button", name="Check my situation").click()
        pg_.wait_for_selector("text=Stub answer to:")
        pg_.wait_for_selector("text=9 of 10 answers left today")
        check("Report a problem with this answer" in pg_.inner_text("body"), "the question went through the API: the answer, the usage line (9 of 10) and the report box")
        pg_.reload(wait_until="networkidle")
        pg_.wait_for_selector("text=Signed in as e2e.person@example.com")
        check("Check my situation" in pg_.inner_text("body") and "Before you start" not in pg_.inner_text("body"), "after a reload the person is still signed in and need not accept again")
        with DBS.session() as s:
            u = s.execute(select(M.User)).scalars().one()
            n_consent = s.execute(select(func.count()).select_from(M.Consent).where(M.Consent.user_id == u.id)).scalar()
            chats = s.execute(select(func.count()).select_from(M.Chat).where(M.Chat.user_id == u.id)).scalar()
            msgs = s.execute(select(func.count()).select_from(M.Message)).scalar()
            check(u.email == "e2e.person@example.com" and u.age_confirmed_at is not None and n_consent == 2 and chats == 1 and msgs == 2, f"in the database: the person, 2 consents, the age declaration, 1 chat, 2 messages ({n_consent}, {chats}, {msgs})")
        pg_.get_by_role("button", name="Sign out").click()
        pg_.wait_for_selector("text=Sign in to ask")
        check("Sign in with Google" in pg_.inner_text("body") and "Check my situation" not in pg_.inner_text("body"), "sign out: the sign-in card is back and the question box is gone")
        b.close()
finally:
    for pr in procs:
        pr.terminate()
    for pr in procs:
        try:
            pr.wait(10)
        except subprocess.TimeoutExpired:
            pr.kill()
    if api:
        api.stop()
    pg.stop()
    if FAILURES:
        try:
            print(open(os.path.join(home, "streamlit.log"), encoding="utf-8", errors="replace").read()[-2500:])
        except OSError:
            pass
    shutil.rmtree(home, ignore_errors=True)

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
