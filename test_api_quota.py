"""
test_api_quota.py -- per-person limits and the anonymous trial's caps (api/quota.py; website design WEBSITE_DESIGN.md section 6 and the owner's D4, step A3.3). Free and offline: a throwaway PostgreSQL (SKIPPED and exit 0 where none exists).
Proves: limits come from the plan's entitlements (the highest version wins) and are counted in India Standard Time days and months (the day turns over at 18:30 UTC); reserve-run-settle gives the last answer to exactly ONE of many simultaneous
requests; a refused or failed question is given back; a plan without the feature has none of it; no limit means no cap; the anonymous trial is capped per device and, separately, per scrambled address, atomically, and NOTHING is kept when
either cap is reached; the trial's own daily budget stops it; a release never goes below zero.
Run: python -X utf8 test_api_quota.py
"""
import concurrent.futures
import datetime
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "ANON_DAILY_BUDGET_INR", "ANON_IP_DAILY_LIMIT"):
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
    from sqlalchemy import func, select, text

    from api import config
    from api import quota as Q
    from api.db import migrate as MIG
    from api.db import models as M
    from api.db import session as DBS

    UTC = datetime.timezone.utc

    def at(y, mo, d, h, mi=0):
        return datetime.datetime(y, mo, d, h, mi, tzinfo=UTC)

    # ------------------------------------------------------------ windows (no database)
    s, r = Q.window("day", at(2026, 10, 21, 18, 29))
    check(s == at(2026, 10, 20, 18, 30) and r == at(2026, 10, 21, 18, 30), "23:59 IST on 21 Oct is still the 21 Oct day (it began 20 Oct 18:30 UTC)")
    s, r = Q.window("day", at(2026, 10, 21, 18, 31))
    check(s == at(2026, 10, 21, 18, 30) and r == at(2026, 10, 22, 18, 30), "00:01 IST on 22 Oct starts a new day")
    s, r = Q.window("month", at(2026, 12, 15, 5))
    check(s == at(2026, 11, 30, 18, 30) and r == at(2026, 12, 31, 18, 30), "the IST month of December begins on 30 Nov 18:30 UTC and ends on 31 Dec 18:30 UTC")
    s, r = Q.window("month", at(2026, 12, 31, 18, 31))
    check(s == at(2026, 12, 31, 18, 30) and r == at(2027, 1, 31, 18, 30), "...and the year turns over correctly (January starts 31 Dec 18:30 UTC)")
    check(Q.window("none") == (None, None), "'none' has no window")

    pg.create_db("quota")
    os.environ["DATABASE_URL"] = pg.url("quota")
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())
    eng = DBS.get_engine()

    def new_user(plan_code="free", email=None):
        with DBS.session() as db:
            plan = db.execute(select(M.Plan).where(M.Plan.code == plan_code)).scalar_one()
            u = M.User(email=email or f"{uuid.uuid4().hex[:8]}@example.com", plan_id=plan.id)
            db.add(u)
            db.commit()
            return u.id

    def reserve(uid, feature="answer_layman", now=None):
        with DBS.session() as db:
            u = db.get(M.User, uid)
            ok, ev, info = Q.reserve(db, u, feature, now)
            db.commit()
            return ok, ev, info

    # ------------------------------------------------------------ basic reserve (free plan: 10 layman, 3 lawyer a day)
    NOW = at(2026, 10, 21, 6)
    u1 = new_user()
    got = [reserve(u1, now=NOW)[0] for _ in range(12)]
    check(got == [True] * 10 + [False] * 2, f"free plan: the first 10 layman answers of the day are allowed, the 11th and 12th are not ({got.count(True)} allowed)")
    ok, ev, info = reserve(u1, now=NOW)
    check(ok is False and info["reason"] == "limit_reached" and info["limit"] == 10 and info["used"] == 10 and info["period"] == "day" and info["resets_at"].startswith("2026-10-21T18:30"), f"a refusal says the limit, the use, and when it resets ({info})")
    check(reserve(u1, "answer_lawyer", now=NOW)[0] is True, "the lawyer allowance is separate from the layman allowance")
    ok, _, _ = reserve(u1, now=at(2026, 10, 21, 18, 31))
    check(ok is True, "after IST midnight the day's allowance is fresh")
    # settle and release
    with DBS.session() as db:
        u = db.get(M.User, new_user())
        ok, ev, _ = Q.reserve(db, u, "answer_layman", NOW)
        Q.settle(db, ev, cost_inr=2.22)
        db.commit()
        row = db.get(M.UsageEvent, ev)
        check(float(row.cost_inr) == 2.22 and row.counted is True and row.message_id is None, "settle records the real cost and keeps the unit")
        Q.release(db, ev)
        db.commit()
        check(db.get(M.UsageEvent, ev).counted is False, "release gives the unit back")
    u2 = new_user()
    evs = [reserve(u2, now=NOW)[1] for _ in range(10)]
    check(reserve(u2, now=NOW)[0] is False, "10 reserved: the 11th is refused")
    with DBS.session() as db:
        Q.release(db, evs[0])
        db.commit()
    check(reserve(u2, now=NOW)[0] is True and reserve(u2, now=NOW)[0] is False, "releasing one (a refused question) frees exactly one")

    # ------------------------------------------------------------ plans, versions, missing rows
    with DBS.session() as db:
        free = db.execute(select(M.Plan).where(M.Plan.code == "free")).scalar_one()
        db.add(M.Entitlement(plan_id=free.id, feature="answer_layman", period="day", limit_count=2, version=2))
        db.commit()
    u3 = new_user()
    got = [reserve(u3, now=NOW)[0] for _ in range(4)]
    check(got == [True, True, False, False], "a newer entitlement version (limit 2) replaces the older one (limit 10)")
    with DBS.session() as db:
        free = db.execute(select(M.Plan).where(M.Plan.code == "free")).scalar_one()
        db.add(M.Entitlement(plan_id=free.id, feature="answer_layman", period="day", limit_count=None, version=3))
        db.commit()
    u4 = new_user()
    check(all(reserve(u4, now=NOW)[0] for _ in range(30)), "no limit (NULL): never refused")
    with DBS.session() as db:
        db.add(M.Plan(code="empty", name="Empty"))
        db.commit()
    u5 = new_user("empty")
    ok, ev, info = reserve(u5, now=NOW)
    check(ok is False and info["reason"] == "no_entitlement" and ev is None, "a plan that does not list the feature has none of it (fails closed)")
    with DBS.session() as db:
        db.add(M.Entitlement(plan_id=db.execute(select(M.Plan.id).where(M.Plan.code == "empty")).scalar_one(), feature="answer_layman", period="day", limit_count=0, version=1))
        db.commit()
    check(reserve(u5, now=NOW)[0] is False, "a limit of 0 refuses everything")
    with DBS.session() as db:
        db.add(M.Entitlement(plan_id=db.execute(select(M.Plan.id).where(M.Plan.code == "empty")).scalar_one(), feature="answer_lawyer", period="month", limit_count=2, version=1))
        db.commit()
    got = [reserve(u5, "answer_lawyer", now=at(2026, 10, 21, 6))[0] for _ in range(3)]
    check(got == [True, True, False], "a monthly limit counts across days")
    check(reserve(u5, "answer_lawyer", now=at(2026, 10, 30, 6))[0] is False and reserve(u5, "answer_lawyer", now=at(2026, 10, 31, 18, 31))[0] is True, "...and renews at the start of the next IST month")
    u6 = new_user(email="nopan@example.com")
    with DBS.session() as db:
        db.execute(text("update users set plan_id = null where email = 'nopan@example.com'"))
        db.commit()
    check(reserve(u6, now=NOW)[0] is False, "a person with no plan has no allowance")

    # ------------------------------------------------------------ the race: many requests at once, one person
    with DBS.session() as db:
        db.execute(text("delete from entitlements where plan_id = (select id from plans where code='free') and version > 1"))
        db.commit()
    u7 = new_user()
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        res = list(pool.map(lambda _: reserve(u7, now=NOW)[0], range(48)))
    with DBS.session() as db:
        counted = db.execute(select(func.count()).select_from(M.UsageEvent).where(M.UsageEvent.user_id == u7, M.UsageEvent.counted.is_(True))).scalar()
    check(res.count(True) == 10 and counted == 10, f"48 simultaneous requests, limit 10: exactly 10 are allowed and 10 are counted ({res.count(True)} allowed, {counted} counted)")
    u8, u9 = new_user(), new_user()
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        r8 = list(pool.map(lambda i: reserve(u8 if i % 2 else u9, now=NOW)[0], range(40)))
    check(r8[1::2].count(True) == 10 and r8[0::2].count(True) == 10, "two people's requests mixed together: each gets their own 10")

    # ------------------------------------------------------------ usage view
    with DBS.session() as db:
        v = Q.usage_view(db, db.get(M.User, u1), NOW)
    check(v["answer_layman"]["used"] == 10 and v["answer_layman"]["limit"] == 10 and v["answer_lawyer"]["used"] == 1 and v["answer_lawyer"]["limit"] == 3 and v["answer_layman"]["resets_at"].startswith("2026-10-21T18:30"), f"the usage view shows used, limit and reset ({v['answer_layman']})")
    check(v["notes_max"] == {"limit": 100, "period": "none"} and v["chat_history_days"]["limit"] is None, "...and the non-counted limits (notes, history) without a count")

    # ------------------------------------------------------------ the anonymous trial
    os.environ["ANON_DAILY_BUDGET_INR"] = "50"

    def anon(device, ip, now=NOW, release=False):
        with DBS.session() as db:
            ok, info = Q.anon_reserve(db, device, ip, now)
            if ok:
                db.commit()
            return ok, info

    got = [anon("dev-1", "ip-A")[0] for _ in range(5)]
    check(got == [True, True, True, False, False], f"the trial: three questions a day per device ({got})")
    ok, info = anon("dev-1", "ip-A")
    check(ok is False and info["reason"] == "device_limit" and info["limit"] == 3, f"a refusal names the device cap ({info})")
    check(anon("dev-2", "ip-A")[0] is True, "another device on the same address still has its own three (an address is shared by many people)")
    check(anon("dev-1", "ip-A", now=at(2026, 10, 21, 18, 31))[0] is True, "the next IST day: the device is fresh")
    with DBS.session() as db:
        dc = db.execute(select(M.AnonCounter.count).where(M.AnonCounter.kind == "device", M.AnonCounter.key == "dev-1", M.AnonCounter.day == datetime.date(2026, 10, 21))).scalar()
        ic = db.execute(select(M.AnonCounter.count).where(M.AnonCounter.kind == "ip", M.AnonCounter.key == "ip-A", M.AnonCounter.day == datetime.date(2026, 10, 21))).scalar()
    check(dc == 3 and ic == 4, f"the counters are exactly what was allowed (device 3, address 4: {dc}, {ic})")
    # the address cap: low limit, nothing kept when it is hit
    os.environ["ANON_IP_DAILY_LIMIT"] = "2"
    check([anon(f"dev-ip{i}", "ip-B")[0] for i in range(4)] == [True, True, False, False], "the address flood guard: only the configured number per address per day")
    with DBS.session() as db:
        d3 = db.execute(select(M.AnonCounter.count).where(M.AnonCounter.kind == "device", M.AnonCounter.key == "dev-ip2")).scalar()
    check(d3 is None, "when the address cap refuses, the device's counter was NOT incremented (nothing is kept)")
    os.environ.pop("ANON_IP_DAILY_LIMIT")
    # release
    check(anon("dev-r", "ip-R")[0] is True, "(reserve for the release test)")
    with DBS.session() as db:
        Q.anon_release(db, "dev-r", "ip-R", NOW)
        Q.anon_release(db, "dev-r", "ip-R", NOW)
        db.commit()
        rc = db.execute(select(M.AnonCounter.count).where(M.AnonCounter.key == "dev-r")).scalar()
    check(rc == 0, "releasing gives the unit back and never goes below zero")
    check([anon("dev-r", "ip-R")[0] for _ in range(4)] == [True, True, True, False], "...and the device has its three again")
    # concurrency
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        rr = list(pool.map(lambda _: anon("dev-race", "ip-race")[0], range(40)))
    with DBS.session() as db:
        rc = db.execute(select(M.AnonCounter.count).where(M.AnonCounter.key == "dev-race")).scalar()
        ric = db.execute(select(M.AnonCounter.count).where(M.AnonCounter.key == "ip-race")).scalar()
    check(rr.count(True) == 3 and rc == 3 and ric == 3, f"40 simultaneous anonymous requests from one device: exactly 3 allowed, counters 3 and 3 ({rr.count(True)}, {rc}, {ric})")
    # budget
    with DBS.session() as db:
        db.add(M.AnonQuestion(device_id="d", question="q", cost_inr=49.9, expires_at=NOW + datetime.timedelta(days=90), created_at=NOW))
        db.commit()
    check(anon("dev-b1", "ip-b1")[0] is True, "just under the trial's daily budget (Rs 49.90 of 50): still open")
    with DBS.session() as db:
        db.add(M.AnonQuestion(device_id="d", question="q2", cost_inr=0.2, expires_at=NOW + datetime.timedelta(days=90), created_at=NOW))
        db.commit()
    ok, info = anon("dev-b2", "ip-b2")
    check(ok is False and info["reason"] == "trial_budget_spent", f"at or over the budget the trial stops for the day ({info})")
    check(anon("dev-b3", "ip-b3", now=at(2026, 10, 21, 18, 31))[0] is True, "...and reopens on the next IST day")
    del os.environ["ANON_DAILY_BUDGET_INR"]
    ok, info = anon("dev-c", "ip-c")
    check(ok is False and info["reason"] == "trial_closed", "no budget set: the trial is closed (fails closed)")
    os.environ["ANON_DAILY_BUDGET_INR"] = "banana"
    check(anon("dev-c", "ip-c")[0] is False, "a budget that is not a number counts as none")
    os.environ["ANON_DAILY_BUDGET_INR"] = "50"
    # ---- refusals are free of the allowance but not unlimited
    os.environ["REFUSAL_DAILY_LIMIT"] = "3"
    ur = new_user()
    def refuse(uid_, cost=0.43, now=None):
        with DBS.session() as db:
            u = db.get(M.User, uid_)
            ok, ev, info = Q.reserve(db, u, "answer_layman", now or NOW)
            if ok:
                Q.settle(db, ev, cost, None)
                Q.release(db, ev)
            db.commit()
            return ok, info
    res = [refuse(ur)[0] for _ in range(5)]
    ok, info = refuse(ur)
    check(res == [True, True, True, False, False] and ok is False and info["reason"] == "too_many_refusals" and info["refusal_limit"] == 3 and info["refusals"] == 3, f"a person's refused questions stop at the daily refusal limit ({res}, {info.get('reason')})")
    with DBS.session() as db:
        check(Q.refusals_today(db, ur, NOW) == 3 and Q.used_in_window(db, ur, "answer_layman", *Q.window("day", NOW)) == 0, "...they cost no allowance (0 answers used), only 3 refusals counted")
    check(refuse(ur, now=at(2026, 10, 21, 18, 31))[0] is True, "...and the next IST day starts fresh")
    uf = new_user()
    for _ in range(4):
        with DBS.session() as db:
            u = db.get(M.User, uf)
            ok, ev, info = Q.reserve(db, u, "answer_layman", NOW)
            Q.release(db, ev)                      # an engine failure: released with no cost recorded
            db.commit()
    check(refuse(uf)[0] is True, "failures of ours (no cost recorded) are not counted against the person")
    other = new_user()
    check(refuse(other)[0] is True, "another person is not affected")
    uc = new_user()
    for _ in range(3):
        refuse(uc)
    with DBS.session() as db:
        ch = M.Chat(user_id=uc)
        db.add(ch)
        db.flush()
        db.execute(text("delete from chats where user_id = :u"), {"u": uc})
        db.commit()
    check(refuse(uc)[0] is False, "deleting chats does not reset the refusal count")
    os.environ.pop("REFUSAL_DAILY_LIMIT")
    check(config.refusal_daily_limit() == 20 and config.anon_refusal_daily_limit() == 10, "defaults: 20 a day for a person, 10 for a trial device")
    os.environ["ANON_REFUSAL_DAILY_LIMIT"] = "2"
    os.environ["ANON_DAILY_BUDGET_INR"] = "5000"                 # the budget is spent for this day by the earlier tests; these tests are about the refusal limit
    def anon_try(dev, state, now=None):
        with DBS.session() as db:
            ok, info = Q.anon_start(db, dev, "ip-" + dev, "q", now=now or NOW)
            if ok:
                Q.anon_finish(db, info["id"], dev, "ip-" + dev, 0.4, state, state in Q.ANSWER_STATES, now or NOW)
            db.commit()
            return ok, info
    seq = [anon_try("dev-ref", "adjacent_uncovered")[0], anon_try("dev-ref", "no_match")[0]]
    ok, info = anon_try("dev-ref", "adjacent_uncovered")
    check(seq == [True, True] and ok is False and info["reason"] == "refusal_limit" and info["limit"] == 2, f"a trial device's refused questions stop at the refusal limit ({seq}, {info.get('reason')})")
    check(anon_try("dev-ref", "adjacent_uncovered", now=at(2026, 10, 21, 18, 31))[0] is True and anon_try("dev-fail", "failed")[0] is True and anon_try("dev-fail", "failed")[0] is True and anon_try("dev-fail", "failed")[0] is True,
          "...the next IST day starts fresh; failures ('failed') are not refusals")
    os.environ.pop("ANON_REFUSAL_DAILY_LIMIT")
    os.environ["ANON_DAILY_BUDGET_INR"] = "50"
    with DBS.session() as db:
        anon_plan = db.execute(select(M.Plan.id).where(M.Plan.code == "anonymous")).scalar_one()
        db.add(M.Entitlement(plan_id=anon_plan, feature="answer_layman", period="day", limit_count=0, version=2))
        db.commit()
    ok, info = anon("dev-z", "ip-z")
    check(ok is False and info["reason"] == "trial_closed", "an anonymous allowance of 0 closes the trial")
finally:
    pg.stop()

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
