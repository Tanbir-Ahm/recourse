"""
test_api_search.py -- POST /api/search (api/routers/search.py, search_service.py): the search page's route. Free and offline: a throwaway PostgreSQL (the test exits 0 where none exists), the Streamlit service's signed token as the
way to be somebody, no model, no Voyage call (SEARCH_MEANING=off), no sci-search service (a stand-in replaces its client).
Proves: only a signed-in person who accepted the documents and declared being 18+ can search; the body is checked; a search returns the engine's result and the usage line; each search counts one unit of the plan's daily
`search` allowance, a wider search of `search_wider`, and the allowance holds under simultaneous requests; a wider search that cannot be served gives its unit back; a failure inside gives the unit back and says nothing
about the query; the answer features' refusal cap does not apply to searching; the per-person rate limit and the cap on searches running at once refuse without spending a unit; the query is stored nowhere and logged nowhere;
a plan with no `search` entitlement has none (fails closed); /api/me shows the usage; the start-up warm-up can be switched off.
Run: python -X utf8 test_api_search.py
"""
import json
import logging
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "API_ACCESS_TOKEN", "ACCOUNTS_OPEN", "GOOGLE_CLIENT_ID", "STREAMLIT_API_SECRET", "IP_HASH_SECRET", "CORS_ALLOW_ORIGINS", "TRUSTED_PROXY_HOPS", "API_COOKIE_SECURE", "API_RUN_MIGRATIONS",
           "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL", "ANON_TRIAL", "ANON_DAILY_BUDGET_INR", "CHAT_MODE", "API_SEARCH_RATE_PER_MINUTE", "API_SEARCH_PARALLEL", "API_RATE_LIMIT_PER_MINUTE", "REFUSAL_DAILY_LIMIT", "SCI_SEARCH_URL",
           "ACT_SHELF", "API_SEARCH_WARM", "API_PURGE"):
    os.environ.pop(_v, None)
os.environ["SEARCH_MEANING"] = "off"                   # no Voyage call from this file, whatever keys the machine holds

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
    from sqlalchemy import select, text, update
    from sqlalchemy.orm import Session

    import search_service
    import sci_search_tier
    from api import ratelimit
    from api.auth import streamlit_token as ST
    from api.db import migrate as MIG
    from api.db import models as M
    from api.db import session as DBS
    from api.main import app

    SECRET = "s" * 40
    pg.create_db("search")
    os.environ.update({"DATABASE_URL": pg.url("search"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "GOOGLE_CLIENT_ID": "client.example", "API_COOKIE_SECURE": "off",
                       "API_RATE_LIMIT_PER_MINUTE": "0", "API_SEARCH_RATE_PER_MINUTE": "0", "API_SEARCH_PARALLEL": "32"})
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())
    ratelimit.reset()
    c = TestClient(app)

    def H(sub, email):
        return lambda: {"Authorization": "Bearer " + ST.mint(SECRET, sub, email)}

    A, B, N, Z = H("a-sub", "alice@example.com"), H("b-sub", "bob@example.com"), H("n-sub", "newbie@example.com"), H("z-sub", "zero@example.com")

    def make_ready(h):
        for doc in ("privacy", "terms"):
            v = c.get(f"/api/legal/{doc}").json()["version"]
            assert c.post("/api/me/consent", json={"document": doc, "version": v}, headers=h()).status_code == 200
        assert c.post("/api/me/age", json={"confirmed": True}, headers=h()).status_code == 200

    [c.get("/api/me", headers=x()) for x in (A, B, N, Z)]
    make_ready(A)
    make_ready(B)
    make_ready(Z)

    versions = {"search": 1, "search_wider": 1}

    def set_limit(feature, limit):
        """A new entitlement version for the free plan (the highest version is in force), as a change in plans.json would make."""
        with Session(DBS.get_engine()) as s_:
            free_id = s_.execute(select(M.Plan.id).where(M.Plan.code == "free")).scalar_one()
            versions[feature] += 1
            s_.add(M.Entitlement(plan_id=free_id, feature=feature, period="day", limit_count=limit, version=versions[feature]))
            s_.commit()

    def post(h, q, mode="library", **kw):
        return c.post("/api/search", json={"q": q, "mode": mode}, headers=h(), **kw)

    def usage(h, feature):
        return c.get("/api/me", headers=h()).json()["usage"].get(feature)

    def events(kind=None):
        with Session(DBS.get_engine()) as s:
            q = select(M.UsageEvent)
            if kind:
                q = q.where(M.UsageEvent.kind == kind)
            return [(e.kind, e.counted) for e in s.execute(q.order_by(M.UsageEvent.at)).scalars()]

    # ------------------------------------------------------------ who may search
    r = c.post("/api/search", json={"q": "BNSS 187"})
    check(r.status_code == 401, f"without signing in: 401 ({r.status_code})")
    r = post(N, "BNSS 187")
    check(r.status_code == 403 and r.json()["detail"] == "consent_required", f"signed in but the documents not accepted: 403 consent_required ({r.status_code} {r.text[:80]})")
    os.environ["ACCOUNTS_OPEN"] = "off"
    check(post(A, "BNSS 187").status_code == 503, "accounts closed: 503")
    os.environ["ACCOUNTS_OPEN"] = "on"
    check(c.get("/api/search", headers=A()).status_code == 405, "GET is not allowed: the query is in the body, never in a URL that a server log keeps")

    # ------------------------------------------------------------ the body
    check(c.post("/api/search", json={}, headers=A()).status_code == 422, "no query: 422")
    check(post(A, "").status_code == 422, "an empty query: 422")
    r = post(A, "   \n\t ")
    check(r.status_code == 422 and r.json()["detail"] == "empty_query", f"a blank query: 422 empty_query ({r.status_code} {r.text[:60]})")
    check(post(A, "x" * 1001).status_code == 422, "a query over 1000 characters: 422")
    check(post(A, "bail", mode="everything").status_code == 422, "an unknown mode: 422")
    check(c.post("/api/search", content="not json", headers={**A(), "content-type": "application/json"}).status_code == 422, "a body that is not JSON: 422")
    check(usage(A, "search")["used"] == 0 and events() == [], "none of those used a unit")

    # ------------------------------------------------------------ a library search
    r = post(A, "BNSS 187")
    j = r.json()
    check(r.status_code == 200 and set(j) == {"result", "usage"}, f"a search: 200 with the result and the usage ({r.status_code})")
    direct = search_service.search("BNSS 187", "library")
    check(j["result"] == json.loads(json.dumps(direct)), "the route returns the engine's result unchanged")
    check(j["result"]["intent"] == "section" and [p["section"] for p in j["result"]["provisions"]] == ["187"] and j["result"]["mode"] == "library", "BNSS 187: the section, intent 'section'")
    u = j["usage"]
    check(u["feature"] == "search" and u["limit"] == 100 and u["used"] == 1 and u["period"] == "day" and u["resets_at"], f"the usage line: search, 100 a day, 1 used, when it resets ({u})")
    check(usage(A, "search")["used"] == 1 and usage(A, "search")["limit"] == 100 and usage(A, "search_wider") == {"used": 0, "limit": 10, "period": "day", "resets_at": usage(A, "search_wider")["resets_at"]},
          "/api/me shows the search usage and the wider-search allowance")
    check(usage(B, "search")["used"] == 0, "another person's count is separate")
    check(events("search") == [("search", True)], f"one counted event of kind 'search' ({events()})")
    r = post(A, "IPC 420")
    check(r.status_code == 200 and r.json()["usage"]["used"] == 2 and r.json()["result"]["provisions"][0]["section"] == "318", "the second search: used 2, IPC 420 -> BNS 318")
    r = post(A, "(2014) 8 SCC 273")
    check(r.status_code == 200 and r.json()["result"]["cases"][0]["title"] == "Arnesh Kumar v State of Bihar", "a citation search through the route")
    r = post(A, "dowry death")
    check(r.status_code == 200 and r.json()["result"]["provisions"][0]["section"] == "80", "a words search through the route")
    r = post(A, "section")
    check(r.status_code == 200 and r.json()["result"]["intent"] == "nothing" and r.json()["result"]["hint"], "a query with nothing to search is answered with a hint (and counts: it was a request)")

    # ------------------------------------------------------------ nothing of the query is kept
    SECRET_Q = "zqxjkwunique bail"
    before = len(events())
    post(A, SECRET_Q)
    with DBS.get_engine().connect() as conn:
        dump = []
        for (t,) in conn.execute(text("select tablename from pg_tables where schemaname = 'public'")).all():
            dump += [str(row) for row in conn.execute(text(f'select * from "{t}"')).all()]
    check(len(events()) == before + 1 and not any("zqxjkwunique" in d for d in dump), "the query text is in no table of the database (only a counted event)")
    records = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    g = Grab()
    logging.getLogger().addHandler(g)
    old = logging.getLogger().level
    logging.getLogger().setLevel(logging.DEBUG)
    post(A, "zqxjkwunique bail")
    post(A, "zqxjkwunique", mode="wider")
    logging.getLogger().removeHandler(g)
    logging.getLogger().setLevel(old)
    check(records and not any("zqxjkwunique" in m for m in records), f"no log line carries the query ({len(records)} lines)")

    # ------------------------------------------------------------ the allowance holds
    set_limit("search", 0)
    r = post(B, "BNSS 187")
    check(r.status_code == 429 and r.json()["detail"] == "limit_reached" and r.json()["usage"]["limit"] == 0, f"a limit of 0: 429 limit_reached with the usage ({r.status_code} {r.text[:100]})")
    check(usage(B, "search")["used"] == 0, "a refused search spends nothing")
    set_limit("search", 3)
    codes = [post(B, "BNSS 187").status_code for _ in range(5)]
    check(codes == [200, 200, 200, 429, 429], f"a limit of 3: the first three searches pass, the rest are refused ({codes})")
    r = post(B, "BNSS 187")
    check(r.json()["usage"] == {"feature": "search", "limit": 3, "used": 3, "period": "day", "resets_at": r.json()["usage"]["resets_at"], "reason": "limit_reached"}, f"the refusal says how many were used ({r.json()['usage']})")
    check(usage(B, "search")["used"] == 3, "/api/me agrees: 3 of 3")
    # simultaneous requests cannot take more than the allowance
    set_limit("search", 5)
    out = []

    def go():
        out.append(post(Z, "BNSS 187").status_code)

    ts = [threading.Thread(target=go) for _ in range(20)]
    [t.start() for t in ts]
    [t.join(120) for t in ts]
    check(sorted(out) == [200] * 5 + [429] * 15, f"20 simultaneous searches with 5 left: exactly 5 are served ({sorted(out).count(200)} served, {sorted(out).count(429)} refused)")
    check(usage(Z, "search")["used"] == 5, "...and the count is exactly 5")
    set_limit("search", 100)

    # the refusal cap of the answer features does not apply to searching
    os.environ["REFUSAL_DAILY_LIMIT"] = "1"
    with Session(DBS.get_engine()) as s:
        a_user = s.execute(select(M.User).where(M.User.email == "alice@example.com")).scalar_one()
        for _ in range(3):
            s.add(M.UsageEvent(user_id=a_user.id, kind="answer_layman", counted=False, cost_inr=0.4))
        s.commit()
    check(post(A, "BNSS 187").status_code == 200, "a person who has used up the daily refusals can still search")
    os.environ.pop("REFUSAL_DAILY_LIMIT")

    # ------------------------------------------------------------ the wider search
    w_before = len(events("search_wider"))
    r = post(A, "search and seizure", mode="wider")
    j = r.json()
    check(r.status_code == 200 and j["result"]["mode"] == "wider" and j["result"]["wider"]["available"] is False and j["result"]["wider"]["note"] == search_service.WIDER_UNAVAILABLE, "wider with no service configured: 200 and a note")
    check(j["usage"]["feature"] == "search_wider" and j["usage"]["used"] == 0 and usage(A, "search_wider")["used"] == 0, "...and no unit is used: the search could not be served")
    check(events("search_wider")[w_before:] == [("search_wider", False)], f"the event is there, not counted ({events('search_wider')[w_before:]})")
    FAKE = {"ok": True, "as_of": "2026-08-12", "results": [{"rank": 1, "doc": "d1", "case_name": "Mohan Lal v. State of Punjab", "date": "2018-07-24", "paragraph": 12, "link": "https://example.org/1", "text": "a passage"},
                                                         {"rank": 2, "doc": "d2", "case_name": "Some Case v. State", "date": "2020-01-01", "paragraph": "4", "link": "javascript:alert(1)", "text": "another"}]}
    os.environ["SCI_SEARCH_URL"] = "http://stand-in.invalid"
    real_search = sci_search_tier.search
    seen_q = []
    sci_search_tier.search = lambda text_, **kw: (seen_q.append(text_) or FAKE)
    r = post(A, "search and seizure", mode="wider")
    j = r.json()
    w = j["result"]["wider"]
    check(r.status_code == 200 and w["available"] and [i["title"] for i in w["items"]] == ["Mohan Lal v. State of Punjab", "Some Case v. State"] and seen_q == ["search and seizure"], "wider with a service: its passages")
    check(w["items"][0]["status"]["source"] == "register" and w["items"][1]["link"] is None and w["label"].startswith("(from a wider search"), "wider: the register's sentence, only web links, the label")
    check(j["usage"]["feature"] == "search_wider" and j["usage"]["used"] == 1 and usage(A, "search_wider")["used"] == 1, "a wider search that was served counts one unit of its own allowance")
    check(usage(A, "search")["used"] >= 5, "...and none of the library allowance")
    sci_search_tier.search = lambda text_, **kw: None
    r = post(A, "search and seizure", mode="wider")
    check(r.status_code == 200 and not r.json()["result"]["wider"]["available"] and usage(A, "search_wider")["used"] == 1, "the service answers nothing: a note, the unit is given back")
    sci_search_tier.search = lambda text_, **kw: FAKE
    set_limit("search_wider", 2)
    codes = [post(A, "search and seizure", mode="wider").status_code for _ in range(3)]
    check(codes == [200, 429, 429], f"a wider allowance of 2 with one used: one more, then refused ({codes})")
    sci_search_tier.search = real_search
    os.environ.pop("SCI_SEARCH_URL")

    # ------------------------------------------------------------ a failure inside
    real = search_service.search
    search_service.search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("zqxjkwunique boom"))
    used_before = usage(B, "search")["used"]
    ok_before = len([e for e in events("search") if e[1]])
    records.clear()
    logging.getLogger().addHandler(g)
    r = post(Z, "BNSS 187")
    logging.getLogger().removeHandler(g)
    search_service.search = real
    check(r.status_code == 500 and r.json()["detail"] == "search_failed", f"a failure inside: 500 search_failed ({r.status_code})")
    check(len([e for e in events("search") if e[1]]) == ok_before, "...and the unit is given back")
    check(not any("zqxjkwunique" in m for m in records) and any("RuntimeError" in m for m in records), "...the log names the kind of failure, not the words of the failure or the query")

    # ------------------------------------------------------------ the guards that spend nothing
    os.environ["API_SEARCH_RATE_PER_MINUTE"] = "3"
    ratelimit.reset()
    n_before = len(events())
    codes = [post(B, "BNSS 187").status_code for _ in range(5)]
    check(codes == [200, 200, 200, 429, 429], f"a flood guard per person per minute: the first 3 pass, the next are refused ({codes})")
    r = post(B, "BNSS 187")
    check(r.status_code == 429 and r.json()["detail"] == "rate_limited" and r.headers.get("retry-after") == "30", "the refusal says rate_limited and when to try again")
    check(len(events()) - n_before == codes.count(200), "a rate-limited search leaves no event: it spent nothing")
    check(post(A, "BNSS 187").status_code == 200, "the limit is per person: another person has their own minute")
    os.environ["API_SEARCH_RATE_PER_MINUTE"] = "0"
    ratelimit.reset()
    # searches running at once
    os.environ["API_SEARCH_PARALLEL"] = "1"
    gate, started = threading.Event(), threading.Event()

    def slow(q, mode="library", **k):
        started.set()
        gate.wait(30)
        return real(q, mode)

    search_service.search = slow
    first = []
    t1 = threading.Thread(target=lambda: first.append(post(A, "BNSS 187").status_code))
    t1.start()
    started.wait(30)
    n_before = len(events("search"))
    r2 = post(B, "BNSS 187")
    check(r2.status_code == 429 and r2.json()["detail"] == "busy" and r2.headers.get("retry-after") == "2", f"a second search while the only slot is taken: 429 busy ({r2.status_code})")
    check(len(events("search")) == n_before, "...it spent nothing")
    gate.set()
    t1.join(30)
    search_service.search = real
    check(first == [200], "the first one finishes normally")
    check(post(B, "BNSS 187").status_code == 200, "after it the slot is free again")
    os.environ["API_SEARCH_PARALLEL"] = "32"

    # ------------------------------------------------------------ a plan with no search entitlement has none
    with Session(DBS.get_engine()) as s:
        s.execute(update(M.User).where(M.User.email == "zero@example.com").values(plan_id=None))
        s.commit()
    r = post(Z, "BNSS 187")
    check(r.status_code == 429 and r.json()["detail"] == "no_entitlement", f"a person whose plan has no search entitlement: refused ({r.status_code} {r.text[:80]})")

    # ------------------------------------------------------------ start-up
    os.environ["API_PURGE"] = "off"
    warmed = []
    real_warm = search_service.warm
    search_service.warm = lambda: warmed.append(1)
    os.environ["API_SEARCH_WARM"] = "off"
    with TestClient(app) as c2:
        c2.get("/api/health")
    check(warmed == [], "API_SEARCH_WARM=off: nothing is loaded at start")
    os.environ.pop("API_SEARCH_WARM")
    with TestClient(app) as c2:
        c2.get("/api/health")
        import time
        for _ in range(50):
            if warmed:
                break
            time.sleep(0.1)
    check(warmed == [1], "by default the search is warmed up in the background at start")
    search_service.warm = real_warm
finally:
    pg.stop()

print()
print(f"{len(FAILURES)} FAILED" if FAILURES else "ALL PASSED")
sys.exit(1 if FAILURES else 0)
