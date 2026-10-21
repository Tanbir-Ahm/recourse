"""
test_api_db.py -- the API's database layer (api/db/: models, migration 0001, session, seed, migrate; website design WEBSITE_DESIGN.md section 4, step A2), run against a REAL throwaway PostgreSQL 16 that this test starts
and removes itself (no network, no cost). When no Postgres server is installed the test says SKIPPED and exits 0, so the free suite still passes on a machine without one; on this repository's development sandbox it runs.
Proves: the migration builds exactly the tables the models describe (no drift) and can go down and up again; plans and quotas load, are safe to load twice, and a changed number becomes a new version; the constraints refuse
bad data; "delete my data" is one delete of the users row and removes everything a person owns while the billing and audit rows stay, with no person attached; four services starting at once migrate once; a broken or
missing database never lets the migrate command pretend; /api/health reports the database without ever failing because of it.
Run: python -X utf8 test_api_db.py
"""
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "API_ACCESS_TOKEN"):
    os.environ.pop(_v, None)

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def find_bin():
    for d in sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True):
        if all(os.path.exists(os.path.join(d, n)) for n in ("initdb", "pg_ctl", "postgres")):
            return d
    w = shutil.which("initdb")
    return os.path.dirname(w) if w and shutil.which("pg_ctl") and shutil.which("postgres") else None


BIN = find_bin()
try:
    import sqlalchemy  # noqa: F401
    import alembic  # noqa: F401
    import psycopg  # noqa: F401
except ImportError as exc:
    print(f"SKIPPED: {exc} (the database packages are in requirements.txt)")
    sys.exit(0)
if not BIN:
    print("SKIPPED: no PostgreSQL server found on this machine")
    sys.exit(0)

ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False
DATA = tempfile.mkdtemp(prefix="pgtest_")
SOCK = tempfile.mkdtemp(prefix="pgsock_")
for d in (DATA, SOCK):
    os.chmod(d, 0o700)
    if ROOT:
        shutil.chown(d, "postgres", "postgres")
PRE = ["runuser", "-u", "postgres", "--"] if ROOT else []
s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()


def run(*cmd, **kw):
    return subprocess.run(PRE + list(cmd), capture_output=True, text=True, timeout=120, **kw)


r = run(os.path.join(BIN, "initdb"), "-D", DATA, "-A", "trust", "-U", "postgres", "-E", "UTF8", "--locale=C.UTF-8")
if r.returncode != 0:
    print("SKIPPED: initdb failed:", (r.stderr or r.stdout)[-200:])
    shutil.rmtree(DATA, ignore_errors=True)
    shutil.rmtree(SOCK, ignore_errors=True)
    sys.exit(0)
r = run(os.path.join(BIN, "pg_ctl"), "-D", DATA, "-o", f"-p {PORT} -k {SOCK} -c listen_addresses=127.0.0.1", "-l", os.path.join(DATA, "log.txt"), "-w", "start")
if r.returncode != 0:
    print("SKIPPED: the throwaway server did not start:", (r.stderr or r.stdout)[-200:])
    shutil.rmtree(DATA, ignore_errors=True)
    shutil.rmtree(SOCK, ignore_errors=True)
    sys.exit(0)


def url(db):
    return f"postgresql://postgres@127.0.0.1:{PORT}/{db}"


def create_db(name):
    r = subprocess.run([os.path.join(BIN, "psql"), "-h", "127.0.0.1", "-p", str(PORT), "-U", "postgres", "-c", f"create database {name}"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


try:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, func, inspect, select, text
    from sqlalchemy.exc import DBAPIError, IntegrityError
    from sqlalchemy.orm import Session

    from api.db import migrate as M
    from api.db import models as D
    from api.db import seed as SEED
    from api.db import session as S

    # ------------------------------------------------------------ settings and the connection string
    for raw, want in (("", ""), ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"), ("postgresql://u@h/d", "postgresql+psycopg://u@h/d"), (' "postgres://u@h/d" ', "postgresql+psycopg://u@h/d"), ("postgresql+psycopg://u@h/d", "postgresql+psycopg://u@h/d")):
        os.environ["DATABASE_URL"] = raw
        check(S.database_url() == want, f"DATABASE_URL {raw!r} -> {want!r}")
    os.environ.pop("DATABASE_URL")
    check(S.configured() is False and S.status() == "not_configured", "no DATABASE_URL: not configured, status 'not_configured'")
    try:
        S.get_engine()
        ok = False
    except RuntimeError:
        ok = True
    check(ok, "no DATABASE_URL: get_engine() refuses (fails closed)")
    bad = "postgresql://postgres:secretpw@127.0.0.1:1/nope"
    os.environ["DATABASE_URL"] = bad
    S.reset_engine()
    check(S.status() == "down", "a database that cannot be reached: status 'down'")
    check("secretpw" not in S.status(), "...and the status carries no address or password")

    # ------------------------------------------------------------ migrate: fresh database
    create_db("t1")
    os.environ["DATABASE_URL"] = url("t1")
    S.reset_engine()
    check(S.status() == "ok", "a reachable database: status 'ok'")
    eng = S.get_engine()
    res = M.upgrade(eng)
    names = set(inspect(eng).get_table_names())
    want = set(D.Base.metadata.tables) | {"alembic_version"}
    check(names == want, f"the migration builds exactly the 15 model tables plus alembic_version ({sorted(names ^ want)})")
    with eng.connect() as c:
        rev = c.execute(text("select version_num from alembic_version")).scalar()
        drift = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), D.Base.metadata)
    check(rev == "0001", f"the schema is at revision 0001 ({rev})")
    check(drift == [], f"the migrated schema and the models do not differ ({drift[:2]})")
    check(res == {"plans_added": 2, "entitlements_added": 6}, f"the seed added the two plans and their six limits ({res})")
    with Session(eng) as ss:
        plans = {p.code: p for p in ss.execute(select(D.Plan)).scalars()}
        ents = {(e.plan.code, e.feature): (e.period, e.limit_count, e.version) for e in ss.execute(select(D.Entitlement)).scalars()}
    check(set(plans) == {"anonymous", "free"}, "the plans are 'anonymous' (the no-sign-in trial) and 'free'")
    check(ents[("anonymous", "answer_layman")] == ("day", 3, 1) and ents[("anonymous", "answer_lawyer")] == ("day", 0, 1), "the anonymous trial: 3 layman answers a day, no lawyer mode (D4)")
    check(ents[("free", "chat_history_days")] == ("none", None, 1), "an unlimited limit is stored as NULL")
    res2 = M.upgrade(eng)
    check(res2 == {"plans_added": 0, "entitlements_added": 0}, "running the migration and the seed again changes nothing")

    # ------------------------------------------------------------ seed: versions and validation
    cfg = SEED.load_config()
    cfg2 = json.loads(json.dumps(cfg))
    for p in cfg2["plans"]:
        if p["code"] == "free":
            for e in p["entitlements"]:
                if e["feature"] == "answer_layman":
                    e["limit"] = 12
    with Session(eng) as ss:
        a = SEED.seed(ss, cfg2)
        ss.commit()
        vers = [(e.version, e.limit_count) for e in ss.execute(select(D.Entitlement).join(D.Plan).where(D.Plan.code == "free", D.Entitlement.feature == "answer_layman").order_by(D.Entitlement.version)).scalars()]
    check(a == {"plans_added": 0, "entitlements_added": 1} and vers == [(1, 10), (2, 12)], f"a changed number is a NEW version; the old one stays as history ({vers})")
    with Session(eng) as ss:
        a = SEED.seed(ss, cfg)
        ss.commit()
        vers = [(e.version, e.limit_count) for e in ss.execute(select(D.Entitlement).join(D.Plan).where(D.Plan.code == "free", D.Entitlement.feature == "answer_layman").order_by(D.Entitlement.version)).scalars()]
    check(vers == [(1, 10), (2, 12), (3, 10)], f"changing it back is version 3, nothing is rewritten ({vers})")
    for label, mut in (("a duplicate plan code", lambda c: c["plans"].append(dict(c["plans"][0]))), ("a bad period", lambda c: c["plans"][1]["entitlements"][0].update(period="week")),
                       ("a negative limit", lambda c: c["plans"][1]["entitlements"][0].update(limit=-1)), ("a true/false limit", lambda c: c["plans"][1]["entitlements"][0].update(limit=True)),
                       ("a duplicate feature", lambda c: c["plans"][1]["entitlements"].append(dict(c["plans"][1]["entitlements"][0])))):
        bad_cfg = json.loads(json.dumps(cfg))
        mut(bad_cfg)
        tmp = os.path.join(DATA, "bad_plans.json")
        json.dump(bad_cfg, open(tmp, "w"))
        try:
            SEED.load_config(tmp)
            ok = False
        except ValueError:
            ok = True
        check(ok, f"plans.json with {label} is refused")

    # ------------------------------------------------------------ constraints
    def attempt(fn):
        with Session(eng) as ss:
            try:
                fn(ss)
                ss.commit()
                return None
            except (IntegrityError, DBAPIError) as exc:
                ss.rollback()
                return type(exc).__name__

    free = plans["free"].id
    check(attempt(lambda s_: s_.add(D.User(email="Upper@Example.com"))) is not None, "an email with capital letters is refused (emails are stored lower-case)")
    check(attempt(lambda s_: s_.add(D.User(email="a@example.com", role="owner"))) is not None, "an unknown role is refused")
    check(attempt(lambda s_: s_.add(D.User(email="a@example.com", status="gone"))) is not None, "an unknown status is refused")
    check(attempt(lambda s_: s_.add(D.User(email="dup@example.com", plan_id=free))) is None, "a normal user is accepted")
    check(attempt(lambda s_: s_.add(D.User(email="dup@example.com"))) is not None, "the same email twice is refused")
    with Session(eng) as ss:
        uid = ss.execute(select(D.User.id).where(D.User.email == "dup@example.com")).scalar_one()
        u = ss.get(D.User, uid)
        check(u.role == "user" and u.status == "active" and u.email_verified is False and u.created_at is not None, "defaults: role user, status active, email not verified, created_at set by the database")
    check(attempt(lambda s_: s_.add(D.Identity(user_id=uid, provider="google", subject="s1"))) is None, "an identity is accepted")
    check(attempt(lambda s_: s_.add(D.Identity(user_id=uid, provider="google", subject="s1"))) is not None, "the same provider and subject twice is refused")
    check(attempt(lambda s_: s_.add(D.Consent(user_id=uid, document="cookies", version="1", text_hash="x"))) is not None, "a consent for an unknown document is refused")
    check(attempt(lambda s_: s_.add(D.Entitlement(plan_id=free, feature="x", period="week", limit_count=1))) is not None, "an entitlement with a bad period is refused")
    check(attempt(lambda s_: s_.add(D.Entitlement(plan_id=free, feature="x", period="day", limit_count=-5))) is not None, "an entitlement with a negative limit is refused")
    check(attempt(lambda s_: s_.add(D.AnonCounter(kind="phone", key="k", day=time.gmtime() and __import__("datetime").date.today(), count=1))) is not None, "an anonymous counter of an unknown kind is refused")
    check(attempt(lambda s_: s_.add(D.AnonQuestion(device_id="d", question="q", audience="judge", expires_at=func.now()))) is not None, "an anonymous question with an unknown audience is refused")
    check(attempt(lambda s_: s_.add(D.UsageEvent(kind="mystery"))) is not None, "a usage event of an unknown kind is refused")

    # ------------------------------------------------------------ "delete my data"
    now_expr = func.now()
    with Session(eng) as ss:
        person = D.User(email="person@example.com", plan_id=free, email_verified=True)
        ss.add(person)
        ss.flush()
        ss.add_all([D.Identity(user_id=person.id, provider="google", subject="gp"), D.Session(id="h" * 64, user_id=person.id, expires_at=now_expr), D.Consent(user_id=person.id, document="privacy", version="v1", text_hash="t"),
                    D.Note(user_id=person.id, body="private note")])
        chat = D.Chat(user_id=person.id, title="my case", audience="layman")
        chat.messages = [D.Message(role="user", seq=1, content="what happens at a remand hearing?"), D.Message(role="assistant", seq=2, content="answer", result={"state": "single_match", "matches": [{"a": [1, 2, {"b": None}]}]}, cost_inr=2.22)]
        ss.add(chat)
        ss.flush()
        mid = chat.messages[1].id
        ss.add_all([D.Feedback(user_id=person.id, message_id=mid, kind="wrong_law", comment="the second point is wrong"), D.UsageEvent(user_id=person.id, message_id=mid, kind="answer_layman", cost_inr=2.22, plan_id_at_time=free),
                    D.AuditLog(actor_user_id=person.id, action="login", detail={"provider": "google"}), D.DeletionRequest(user_id=person.id)])
        ss.commit()
        pid = person.id
    with Session(eng) as ss:
        got = ss.execute(select(D.Message).where(D.Message.role == "assistant")).scalar_one()
        check(got.result == {"state": "single_match", "matches": [{"a": [1, 2, {"b": None}]}]} and float(got.cost_inr) == 2.22, "an assistant message keeps the engine's whole structured result (JSON) and its cost")
        jq = ss.execute(text("select count(*) from messages where result->>'state' = 'single_match'")).scalar()
        check(jq == 1, "the result is real JSONB: it can be queried by field")
    with Session(eng) as ss:
        ss.execute(text("delete from users where id = :i"), {"i": pid})
        ss.commit()
    counts = {}
    with eng.connect() as c:
        for t in ("identities", "sessions", "consents", "chats", "messages", "notes", "feedback"):
            counts[t] = c.execute(text(f"select count(*) from {t} where user_id = :i" if t not in ("messages",) else "select count(*) from messages"), {"i": pid} if t != "messages" else {}).scalar()
        ue = c.execute(text("select user_id, message_id, kind, cost_inr from usage_events")).all()
        al = c.execute(text("select actor_user_id, action from audit_log")).all()
        dr = c.execute(text("select user_id, requested_at from deletion_requests")).all()
        still = c.execute(text("select count(*) from plans")).scalar()
    check(all(v == 0 for v in counts.values()), f"deleting the person removes their identities, sessions, consents, chats, messages, notes and feedback ({counts})")
    check(len(ue) == 1 and ue[0][0] is None and ue[0][1] is None and ue[0][2] == "answer_layman" and float(ue[0][3]) == 2.22, f"the usage row stays for billing, with no person and no message attached ({ue})")
    check(al == [(None, "login")] and len(dr) == 1 and dr[0][0] is None, "the audit row and the deletion request stay, with no person attached")
    check(still == 2, "deleting a person does not touch the plans")
    with Session(eng) as ss:
        u2 = D.User(email="two@example.com", plan_id=free)
        ss.add(u2)
        ss.flush()
        ch = D.Chat(user_id=u2.id)
        ch.messages = [D.Message(role="assistant", seq=1, content="a")]
        ss.add(ch)
        ss.flush()
        ss.add(D.Note(user_id=u2.id, message_id=ch.messages[0].id, body="kept note"))
        ss.commit()
        ss.delete(ch)
        ss.commit()
        n = ss.execute(select(D.Note)).scalar_one()
        check(n.message_id is None, "deleting one chat keeps the person's note (its link to the message is cleared)")
    check(attempt(lambda s_: s_.execute(text("delete from plans where code = 'free'"))) is not None, "a plan that users hold cannot be deleted (RESTRICT)")

    # ------------------------------------------------------------ down and up again
    from alembic import command
    cfgA = M.alembic_config()
    cfgA.attributes["engine"] = eng
    command.downgrade(cfgA, "base")
    left = set(inspect(eng).get_table_names())
    check(left == {"alembic_version"}, f"downgrading to base removes every table ({sorted(left)})")
    res3 = M.upgrade(eng)
    check(res3["plans_added"] == 2 and set(inspect(eng).get_table_names()) == want, "upgrading again from nothing works and re-seeds")

    # ------------------------------------------------------------ four services starting at once
    create_db("race")
    os.environ["DATABASE_URL"] = url("race")
    S.reset_engine()
    out, errs = [], []

    def go():
        e = create_engine(S.database_url())
        try:
            out.append(M.upgrade(e))
        except Exception as exc:  # noqa: BLE001
            errs.append(type(exc).__name__)
        finally:
            e.dispose()

    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join(120) for t in ts]
    e2 = create_engine(S.database_url())
    with e2.connect() as c:
        npl = c.execute(text("select count(*) from plans")).scalar()
        nen = c.execute(text("select count(*) from entitlements")).scalar()
    e2.dispose()
    check(not errs and len(out) == 4 and npl == 2 and nen == 6, f"four migrations at once: no error, one set of plans and limits ({errs}, plans {npl}, entitlements {nen})")
    check(sum(r["plans_added"] for r in out) == 2, "...and exactly one of them did the seeding")

    # ------------------------------------------------------------ the migrate command
    import io
    import contextlib
    os.environ.pop("DATABASE_URL")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main()
    check(rc == 0 and "DATABASE_URL is not set" in buf.getvalue(), "migrate with no database: says so and exits 0 (the service can still start)")
    os.environ["DATABASE_URL"] = "postgresql://postgres:secretpw@127.0.0.1:1/nope"
    S.reset_engine()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main()
    check(rc == 1 and "FAILED" in buf.getvalue() and "secretpw" not in buf.getvalue() and "127.0.0.1" not in buf.getvalue(), "migrate with an unreachable database: exits 1, says FAILED, prints no address or password")
    create_db("t2")
    os.environ["DATABASE_URL"] = url("t2")
    S.reset_engine()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = M.main()
    check(rc == 0 and "schema at head; plans added 2, entitlements added 6" in buf.getvalue(), f"migrate on a fresh database: exits 0 ({buf.getvalue().strip()})")
    r = subprocess.run([sys.executable, "-m", "api.db.migrate"], cwd=HERE, env={**os.environ}, capture_output=True, text=True, timeout=120)
    check(r.returncode == 0 and "plans added 0, entitlements added 0" in r.stdout, f"`python -m api.db.migrate` as the start command would run it: exits 0 on an up-to-date database ({r.stdout.strip()})")

    # ------------------------------------------------------------ /api/health
    from fastapi.testclient import TestClient
    from api.main import app
    S.reset_engine()
    h = TestClient(app).get("/api/health")
    check(h.status_code == 200 and h.json()["db"] == "ok", f"/api/health with a working database: db 'ok' ({h.json()})")
    os.environ["DATABASE_URL"] = "postgresql://postgres:secretpw@127.0.0.1:1/nope"
    S.reset_engine()
    h = TestClient(app).get("/api/health")
    check(h.status_code == 200 and h.json()["db"] == "down" and "secretpw" not in h.text, "/api/health with a dead database: still 200, db 'down', no address in the reply")
    os.environ.pop("DATABASE_URL")
    S.reset_engine()
    check(TestClient(app).get("/api/health").json()["db"] == "not_configured", "/api/health with no database configured: db 'not_configured'")

    # ------------------------------------------------------------ migration at startup (API_RUN_MIGRATIONS)
    create_db("boot")
    os.environ["DATABASE_URL"] = url("boot")
    S.reset_engine()
    with TestClient(app) as c:      # entering the client runs the app's startup
        c.get("/api/health")
    e3 = create_engine(S.database_url())
    check(set(inspect(e3).get_table_names()) == set(), "API_RUN_MIGRATIONS unset: starting the service creates nothing")
    os.environ["API_RUN_MIGRATIONS"] = "on"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with TestClient(app) as c:
            hb = c.get("/api/health").json()
    names_boot = set(inspect(e3).get_table_names())
    check(names_boot == want and "database schema is up to date" in buf.getvalue() and hb["db"] == "ok", f"API_RUN_MIGRATIONS=on: starting the service builds the schema and loads the plans ({buf.getvalue().strip()})")
    with e3.connect() as c2:
        check(c2.execute(text("select count(*) from plans")).scalar() == 2, "...and the plans are there")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with TestClient(app):
            pass
    check("up to date" in buf.getvalue(), "starting again on an up-to-date database is fine")
    e3.dispose()
    os.environ["DATABASE_URL"] = "postgresql://postgres:secretpw@127.0.0.1:1/nope"
    S.reset_engine()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            with TestClient(app):
                pass
        refused = False
    except RuntimeError as exc:
        refused = "secretpw" not in str(exc) and "127.0.0.1" not in str(exc)
    check(refused and "FAILED" in buf.getvalue() and "secretpw" not in buf.getvalue() and "127.0.0.1" not in buf.getvalue(), "API_RUN_MIGRATIONS=on with an unreachable database: the service refuses to start, and says nothing about the address")
    os.environ.pop("DATABASE_URL")
    S.reset_engine()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with TestClient(app) as c:
            ok_nodb = c.get("/api/health").status_code == 200
    check(ok_nodb and "DATABASE_URL is not set; skipping" in buf.getvalue(), "API_RUN_MIGRATIONS=on with no DATABASE_URL: starts anyway and says it skipped")
    os.environ.pop("API_RUN_MIGRATIONS")
finally:
    subprocess.run(PRE + [os.path.join(BIN, "pg_ctl"), "-D", DATA, "-m", "immediate", "stop"], capture_output=True, timeout=60)
    shutil.rmtree(DATA, ignore_errors=True)
    shutil.rmtree(SOCK, ignore_errors=True)

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
