"""
test_api_hardening.py -- the retention purge, cross-origin access and the flood guard (api/purge.py, api/cors.py, api/ratelimit.py; WEBSITE_DESIGN.md sections 8 and 9, step A3.5). Free and offline; the purge part needs a throwaway PostgreSQL
(that part prints SKIPPED where none exists).
Proves: expired trial questions, sessions, old trial counters and chats past a plan's history limit are deleted and nothing else (a plan with no limit keeps its chats; a chat inside its limit stays), one audit row holds only the counts, a second run
removes nothing, a second copy running at the same time does nothing; only listed origins get CORS headers (also on a refused request), a preflight is answered only for them; the flood guard counts per address in a minute, ignores a made-up
left part of X-Forwarded-For, does not count Bearer-token calls or the health check, and lets another address through.
Run: python -X utf8 test_api_hardening.py
"""
import asyncio
import datetime
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "CORS_ALLOW_ORIGINS", "TRUSTED_PROXY_HOPS", "CLIENT_IP_HEADER", "API_RATE_LIMIT_PER_MINUTE", "API_AUTH_RATE_PER_MINUTE", "IP_HASH_SECRET", "API_PURGE", "API_PURGE_INTERVAL_SECONDS", "ACCOUNTS_OPEN"):
    os.environ.pop(_v, None)

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


from fastapi.testclient import TestClient

from api import config, ratelimit
from api.main import app

c = TestClient(app)

# ------------------------------------------------------------ CORS
r = c.get("/api/health", headers={"Origin": "https://app.recourse.test"})
check("access-control-allow-origin" not in r.headers, "with CORS_ALLOW_ORIGINS unset, no origin gets a CORS header")
os.environ["CORS_ALLOW_ORIGINS"] = "https://app.recourse.test, https://staging.recourse.test/"
r = c.get("/api/health", headers={"Origin": "https://app.recourse.test"})
check(r.headers.get("access-control-allow-origin") == "https://app.recourse.test" and r.headers.get("access-control-allow-credentials") == "true" and "Origin" in r.headers.get("vary", ""), "a listed origin gets its own origin back, with credentials allowed and Vary: Origin")
check(c.get("/api/health", headers={"Origin": "https://staging.recourse.test"}).headers.get("access-control-allow-origin") == "https://staging.recourse.test", "a trailing slash in the list is ignored")
check("access-control-allow-origin" not in c.get("/api/health", headers={"Origin": "https://evil.example"}).headers, "an origin that is not listed gets nothing")
check("access-control-allow-origin" not in c.get("/api/health", headers={"Origin": "https://app.recourse.test.evil.example"}).headers, "...nor an origin that merely starts with a listed one")
p = c.options("/api/chats", headers={"Origin": "https://app.recourse.test", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-csrf-token,idempotency-key"})
check(p.status_code == 204 and "POST" in p.headers["access-control-allow-methods"] and "X-CSRF-Token" in p.headers["access-control-allow-headers"] and "Idempotency-Key" in p.headers["access-control-allow-headers"] and p.headers["access-control-allow-origin"] == "https://app.recourse.test", "a preflight from a listed origin: 204 with the methods and the headers the front end needs")
p = c.options("/api/chats", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
check("access-control-allow-origin" not in p.headers and p.status_code != 204, "a preflight from another origin is not answered")
check("authorization" not in c.options("/api/chats", headers={"Origin": "https://app.recourse.test", "Access-Control-Request-Method": "POST"}).headers["access-control-allow-headers"].lower(), "a browser page may not send an Authorization header (that path is for the Streamlit service only)")

# ------------------------------------------------------------ flood guard
ratelimit.reset()
os.environ["API_RATE_LIMIT_PER_MINUTE"] = "5"
os.environ["API_AUTH_RATE_PER_MINUTE"] = "3"


def get(ip, path="/api/legal/privacy", **h):
    return c.get(path, headers={"X-Forwarded-For": ip, **h})


codes = [get("203.0.113.1").status_code for _ in range(7)]
check(codes == [200] * 5 + [429] * 2, f"the sixth request in a minute from one address is refused ({codes})")
r = get("203.0.113.1")
check(r.status_code == 429 and r.json() == {"detail": "rate_limited"} and r.headers.get("retry-after") == "30", "...with a fixed body and Retry-After")
check(get("203.0.113.2").status_code == 200, "another address is unaffected")
check(get("198.51.100.77, 203.0.113.1").status_code == 429 and get("1.1.1.1, 203.0.113.2").status_code == 200, "a made-up left part of X-Forwarded-For changes nothing: the entry our proxy added decides")
check(all(get("203.0.113.1", "/api/health").status_code == 200 for _ in range(10)), "the health check is never limited")
check(all(get("203.0.113.1", Authorization="Bearer abc.def.ghi").status_code != 429 for _ in range(10)), "a request carrying a Bearer token is not counted (the Streamlit service shares one address)")
check(c.options("/api/chats", headers={"X-Forwarded-For": "203.0.113.1"}).status_code != 429, "OPTIONS is never limited")
r = c.get("/api/legal/privacy", headers={"X-Forwarded-For": "203.0.113.1", "Origin": "https://app.recourse.test"})
check(r.status_code == 429 and r.headers.get("access-control-allow-origin") == "https://app.recourse.test", "a refused request still carries the CORS header, so the front end can read the 429")
ac = [c.post("/api/auth/google", json={"id_token": "x"}, headers={"X-Forwarded-For": "203.0.113.50"}).status_code for _ in range(5)]
check(ac[:3].count(429) == 0 and ac[3:] == [429, 429], f"sign-in has its own, smaller limit ({ac})")
# the Railway case: the visitor is constant but the edge address at the end of X-Forwarded-For changes on every request
os.environ["CLIENT_IP_HEADER"] = "x-real-ip"
rr = [c.get("/api/legal/privacy", headers={"X-Forwarded-For": f"49.37.108.90, 152.233.15.{i}", "X-Real-IP": "49.37.108.90"}).status_code for i in range(7)]
check(rr == [200] * 5 + [429] * 2, f"with CLIENT_IP_HEADER=x-real-ip the flood guard holds even though the edge address changes on every request ({rr})")
os.environ.pop("CLIENT_IP_HEADER")
ratelimit.reset()
rr0 = [c.get("/api/legal/privacy", headers={"X-Forwarded-For": f"49.37.108.90, 152.233.15.{i}", "X-Real-IP": "49.37.108.90"}).status_code for i in range(7)]
check(rr0 == [200] * 7, "...and with the default rule the same traffic is never limited (the staging bug, kept as a test of why the setting exists)")
ratelimit.reset()
os.environ["API_ANON_RATE_PER_MINUTE"] = "3"
an = [c.post("/api/anon/ask", json={"question": "Can I be fired?"}, headers={"X-Forwarded-For": "203.0.113.60"}).status_code for _ in range(5)]
check(an[:3].count(429) == 0 and an[3:] == [429, 429], f"the free trial has its own small per-minute limit, because every trial question costs money ({an})")
os.environ.pop("API_ANON_RATE_PER_MINUTE")
check(config.anon_rate_per_minute() == 6, "default: 6 a minute for the trial")
os.environ["API_RATE_LIMIT_PER_MINUTE"] = "0"
check(all(get("203.0.113.1").status_code == 200 for _ in range(20)), "0 turns the guard off")
os.environ["API_RATE_LIMIT_PER_MINUTE"] = "5"
ratelimit.reset()
check(ratelimit.hit(("t", "k"), 2, now=100.0) and ratelimit.hit(("t", "k"), 2, now=101.0) and not ratelimit.hit(("t", "k"), 2, now=102.0) and ratelimit.hit(("t", "k"), 2, now=161.5), "the window slides: a hit older than a minute no longer counts")
ratelimit._HITS.clear()
for i in range(ratelimit.MAX_KEYS + 5):
    ratelimit._HITS[("a", str(i))] = ratelimit.deque([0.0])
ratelimit.hit(("a", "new"), 5, now=1000.0)
check(len(ratelimit._HITS) <= ratelimit.MAX_KEYS, "the table of addresses cannot grow without bound")
ratelimit.reset()
os.environ.pop("API_RATE_LIMIT_PER_MINUTE"), os.environ.pop("API_AUTH_RATE_PER_MINUTE")
check(config.rate_limit_per_minute() == 120 and config.auth_rate_per_minute() == 20 and config.purge_on() is True and config.purge_interval_seconds() == 3600, "defaults: 120 and 20 a minute, purge on, hourly")

# ------------------------------------------------------------ the staging diagnostic for the client address
check(c.get("/api/debug/headers").status_code == 404, "the address diagnostic is off (404) unless API_DEBUG_HEADERS is on")
os.environ["API_DEBUG_HEADERS"] = "on"
r = c.get("/api/debug/headers", headers={"X-Forwarded-For": "198.51.100.5, 203.0.113.9", "X-Real-IP": "203.0.113.9", "Authorization": "Bearer secret-token", "Cookie": "rc_session=abc"})
check(r.status_code == 200 and r.json()["x_forwarded_for"] == "198.51.100.5, 203.0.113.9" and r.json()["x_real_ip"] == "203.0.113.9" and r.json()["address_the_service_would_use"] == "203.0.113.9" and r.json()["trusted_proxy_hops"] == 1, f"on: it shows the address headers and the address the service would use ({r.json()})")
check("secret-token" not in r.text and "rc_session" not in r.text, "...and never an Authorization header or a cookie")
os.environ.pop("API_DEBUG_HEADERS")
check("/api/debug/headers" not in open(os.path.join(HERE, "api", "openapi.json"), encoding="utf-8").read(), "the diagnostic is not in the public contract")

# ------------------------------------------------------------ the purge loop
import api.main as main_mod
import api.purge as purge_mod
calls = []
orig_run, orig_sleep = purge_mod.run, asyncio.sleep


async def fake_sleep(n):
    calls.append(("sleep", n))
    raise asyncio.CancelledError()
os.environ["DATABASE_URL"] = "postgresql://nobody@127.0.0.1:1/none"
purge_mod.run = lambda: calls.append("run")
main_mod.asyncio.sleep = fake_sleep
try:
    asyncio.run(main_mod._purge_loop())
except asyncio.CancelledError:
    pass
main_mod.asyncio.sleep = orig_sleep
purge_mod.run = orig_run
os.environ.pop("DATABASE_URL")
check(calls == ["run", ("sleep", 3600)], f"the loop purges once at the start, then sleeps an hour ({calls})")

# ------------------------------------------------------------ the purge itself (PostgreSQL)
import pg_harness
pg = pg_harness.start()
if pg is None:
    print("SKIPPED: no PostgreSQL here, the purge itself was not tested")
else:
    try:
        from sqlalchemy import func, select, text

        from api.db import migrate as MIG
        from api.db import models as M
        from api.db import session as DBS
        pg.create_db("purge")
        os.environ["DATABASE_URL"] = pg.url("purge")
        DBS.reset_engine()
        MIG.upgrade(DBS.get_engine())
        NOW = datetime.datetime(2026, 10, 21, 12, 0, tzinfo=datetime.timezone.utc)
        D = datetime.timedelta
        with DBS.session() as s:
            free = s.execute(select(M.Plan).where(M.Plan.code == "free")).scalar_one()
            keeper = M.Plan(code="keeper", name="Keeper")
            s.add(keeper)
            s.flush()
            s.add(M.Entitlement(plan_id=free.id, feature="chat_history_days", period="none", limit_count=30, version=2))
            s.add(M.Entitlement(plan_id=keeper.id, feature="chat_history_days", period="none", limit_count=None, version=1))
            u_free, u_keep = M.User(email="f@example.com", plan_id=free.id), M.User(email="k@example.com", plan_id=keeper.id)
            s.add_all([u_free, u_keep])
            s.flush()
            s.add_all([M.AnonQuestion(device_id="d1", question="old secret question", created_at=NOW - D(100), expires_at=NOW - D(10)),
                       M.AnonQuestion(device_id="d1", question="fresh question", created_at=NOW - D(1), expires_at=NOW + D(89))])
            s.add_all([M.Session(id="s-old", user_id=u_free.id, expires_at=NOW - D(1)), M.Session(id="s-new", user_id=u_free.id, expires_at=NOW + D(5))])
            s.add_all([M.AnonCounter(kind="device", key="d1", day=datetime.date(2026, 10, 10), count=3), M.AnonCounter(kind="device", key="d1", day=datetime.date(2026, 10, 20), count=2),
                       M.AnonCounter(kind="ip", key="i1", day=datetime.date(2026, 10, 21), count=1)])
            chats = {}
            for name, user, age in (("free_old", u_free, 40), ("free_new", u_free, 10), ("keep_old", u_keep, 400)):
                ch = M.Chat(user_id=user.id, title=name, updated_at=NOW - D(age))
                s.add(ch)
                s.flush()
                s.add(M.Message(chat_id=ch.id, role="user", seq=1, content="private words"))
                chats[name] = ch.id
            s.commit()
        with DBS.session() as s:
            out = purge_mod.purge_once(s, NOW)
            s.commit()
        check(out == {"anon_questions": 1, "sessions": 1, "anon_counters": 1, "chats": 1}, f"one of each kind past its time is deleted ({out})")
        with DBS.session() as s:
            qs = [q.question for q in s.execute(select(M.AnonQuestion)).scalars()]
            check(qs == ["fresh question"], "the question inside its 90 days stays, the expired one is gone")
            check([x.id for x in s.execute(select(M.Session)).scalars()] == ["s-new"], "only the live session stays")
            check(sorted((x.key, str(x.day)) for x in s.execute(select(M.AnonCounter)).scalars()) == [("d1", "2026-10-20"), ("i1", "2026-10-21")], "counters of today and yesterday stay, an old one goes")
            left = {x.title for x in s.execute(select(M.Chat)).scalars()}
            check(left == {"free_new", "keep_old"}, f"a chat past its plan's 30 days is deleted; one inside it stays; a plan with no limit keeps everything ({left})")
            check(s.execute(select(func.count()).select_from(M.Message).where(M.Message.chat_id == chats["free_old"])).scalar() == 0, "...and its messages went with it")
            audit = s.execute(select(M.AuditLog).where(M.AuditLog.action == "purge")).scalars().all()
            check(len(audit) == 1 and audit[0].detail == out and "secret" not in str(audit[0].detail), "one audit row holds the counts and no text")
        with DBS.session() as s:
            out2 = purge_mod.purge_once(s, NOW)
            s.commit()
            check(out2 == {"anon_questions": 0, "sessions": 0, "anon_counters": 0, "chats": 0} and s.execute(select(func.count()).select_from(M.AuditLog).where(M.AuditLog.action == "purge")).scalar() == 1, "a second run removes nothing and writes no second audit row")
        a, b = DBS.session(), DBS.session()
        try:
            a.execute(text("select pg_advisory_xact_lock(hashtext('recourse-purge'))"))
            check(purge_mod.purge_once(b, NOW) is None, "while another copy holds the lock, a purge does nothing (None)")
        finally:
            a.rollback(), b.rollback(), a.close(), b.close()
        check(purge_mod.main() == 0, "python -m api.purge runs and exits 0")
    finally:
        pg.stop()

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
