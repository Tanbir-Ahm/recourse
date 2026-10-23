"""
api/quota.py -- how many answers a person may have (step A3.3; WEBSITE_DESIGN 6). Limits are DATA (plans, entitlements: the highest version of a feature is in force), counted from usage_events, in India Standard Time days and months.
Reserve, run, settle: reserve() takes a row lock on the person, counts, and records one counted event in the same transaction, so two requests arriving together cannot both take the last answer; the lock is released when the caller commits
(before the engine runs, which takes seconds). settle() records the real cost afterwards; release() gives the unit back (the engine failed, or the question was refused: refusals are free).
The anonymous trial has its own counters: one per device (the per-person cap) and one per scrambled IP (a flood guard), incremented atomically in one statement each, so a cap holds under any number of simultaneous requests.
"""
import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import config
from .db import models as M

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
FEATURE_FOR_AUDIENCE = {"layman": "answer_layman", "lawyer": "answer_lawyer"}


def _now(now):
    return now or datetime.datetime.now(datetime.timezone.utc)


def window(period, now=None):
    """(start, resets_at) in UTC for a period measured in IST: 'day' from IST midnight, 'month' from the first of the IST month; (None, None) for 'none'."""
    now = _now(now).astimezone(IST)
    if period == "day":
        s = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return s.astimezone(datetime.timezone.utc), (s + datetime.timedelta(days=1)).astimezone(datetime.timezone.utc)
    if period == "month":
        s = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = (s.replace(year=s.year + 1, month=1) if s.month == 12 else s.replace(month=s.month + 1))
        return s.astimezone(datetime.timezone.utc), nxt.astimezone(datetime.timezone.utc)
    return None, None


def entitlement(db, plan_id, feature):
    """The limit in force for a feature of a plan: (period, limit_count) from the highest version, or None when the plan has no such row."""
    if plan_id is None:
        return None
    e = db.execute(select(M.Entitlement).where(M.Entitlement.plan_id == plan_id, M.Entitlement.feature == feature).order_by(M.Entitlement.version.desc()).limit(1)).scalar_one_or_none()
    return (e.period, e.limit_count) if e is not None else None


def used_in_window(db, user_id, feature, start, end=None):
    q = select(func.count()).select_from(M.UsageEvent).where(M.UsageEvent.user_id == user_id, M.UsageEvent.kind == feature, M.UsageEvent.counted.is_(True))
    if start is not None:
        q = q.where(M.UsageEvent.at >= start)
    if end is not None:
        q = q.where(M.UsageEvent.at < end)
    return db.execute(q).scalar()


def reserve(db, user, feature, now=None):
    """-> (True, event_id, info) or (False, None, info). A plan with no such entitlement has none of the feature (fail closed). The caller must COMMIT to keep the unit and release the lock."""
    now = _now(now)
    db.execute(select(M.User.id).where(M.User.id == user.id).with_for_update()).scalar_one()      # the row lock that serialises this person's requests
    ent = entitlement(db, user.plan_id, feature)
    if ent is None:
        return False, None, {"feature": feature, "limit": 0, "used": 0, "period": None, "resets_at": None, "reason": "no_entitlement"}
    period, limit = ent
    start, resets = window(period, now)
    used = used_in_window(db, user.id, feature, start, resets)
    info = {"feature": feature, "limit": limit, "used": used, "period": period, "resets_at": resets.isoformat() if resets else None}
    if limit is not None and used >= limit:
        info["reason"] = "limit_reached"
        return False, None, info
    ev = M.UsageEvent(user_id=user.id, kind=feature, counted=True, plan_id_at_time=user.plan_id, at=now)
    db.add(ev)
    db.flush()
    info["used"] = used + 1
    return True, ev.id, info


def settle(db, event_id, cost_inr=None, message_id=None):
    db.execute(update(M.UsageEvent).where(M.UsageEvent.id == event_id).values(cost_inr=cost_inr, message_id=message_id))


def release(db, event_id):
    db.execute(update(M.UsageEvent).where(M.UsageEvent.id == event_id).values(counted=False))


def usage_view(db, user, now=None):
    """What the page shows: for each limit of the person's plan that is counted per day or month, how many are used, the limit and when it resets."""
    now = _now(now)
    out = {}
    latest = {}
    if user.plan_id is not None:
        for e in db.execute(select(M.Entitlement).where(M.Entitlement.plan_id == user.plan_id).order_by(M.Entitlement.version)).scalars():
            latest[e.feature] = e
    for feature, e in latest.items():
        if e.period in ("day", "month") and feature.startswith("answer_"):
            start, resets = window(e.period, now)
            out[feature] = {"used": used_in_window(db, user.id, feature, start, resets), "limit": e.limit_count, "period": e.period, "resets_at": resets.isoformat()}
        else:
            out[feature] = {"limit": e.limit_count, "period": e.period}
    return out


# ---------------------------------------------------------------- the anonymous trial
def _anon_limit(db):
    plan = db.execute(select(M.Plan).where(M.Plan.code == "anonymous")).scalar_one_or_none()
    ent = entitlement(db, plan.id, "answer_layman") if plan else None
    return ent[1] if ent else 0


def anon_spent_today(db, now=None):
    """Rupees the trial has spent since IST midnight. A question still running (cost not yet known) counts at ANON_EST_COST_INR, so a burst of simultaneous questions cannot all pass the budget check before any of them has been paid for."""
    start, _ = window("day", _now(now))
    est = config.anon_est_cost_inr()
    return float(db.execute(select(func.coalesce(func.sum(func.coalesce(M.AnonQuestion.cost_inr, est)), 0)).where(M.AnonQuestion.created_at >= start)).scalar() or 0)


def _bump(db, kind, key, day, limit):
    t = M.AnonCounter.__table__
    stmt = pg_insert(t).values(kind=kind, key=key, day=day, count=1).on_conflict_do_update(index_elements=[t.c.kind, t.c.key, t.c.day], set_={"count": t.c.count + 1}, where=t.c.count < limit).returning(t.c.count)
    row = db.execute(stmt).first()
    return row[0] if row is not None else None


def anon_reserve(db, device_id, ip_hash, now=None):
    """-> (True, info) or (False, info). Takes one unit from the device's counter (the per-person cap) and one from the address's counter (the flood guard), each in one atomic statement; if either cap is reached NOTHING is kept
    (the transaction is rolled back). Also refuses when the trial's own daily budget is spent or not set. The caller commits on True."""
    now = _now(now)
    day = now.astimezone(IST).date()
    limit, ip_limit, budget = _anon_limit(db), config.anon_ip_daily_limit(), config.anon_budget_inr()
    if limit <= 0 or budget <= 0:
        return False, {"reason": "trial_closed"}
    if anon_spent_today(db, now) >= budget:
        return False, {"reason": "trial_budget_spent"}
    used = _bump(db, "device", device_id, day, limit)
    if used is None:
        db.rollback()
        return False, {"reason": "device_limit", "limit": limit}
    if _bump(db, "ip", ip_hash, day, ip_limit) is None:
        db.rollback()
        return False, {"reason": "ip_limit", "limit": ip_limit}
    return True, {"limit": limit, "used": used, "day": day.isoformat()}


def anon_release(db, device_id, ip_hash, now=None):
    """Gives both units back (the question was refused or the engine failed), never below zero."""
    day = _now(now).astimezone(IST).date()
    t = M.AnonCounter.__table__
    for kind, key in (("device", device_id), ("ip", ip_hash)):
        db.execute(update(t).where(t.c.kind == kind, t.c.key == key, t.c.day == day, t.c.count > 0).values(count=t.c.count - 1))


ANON_KEEP_DAYS = 90        # owner's decision D4


def anon_start(db, device_id, ip_hash, question, audience="layman", now=None):
    """The whole beginning of a trial question in ONE transaction: a Postgres lock so that the budget check and the new row are one step (simultaneous questions queue here for a few milliseconds), the caps, and the stored question
    (cost not yet known, so it counts at the estimate). -> (True, info with 'id', 'used', 'limit') or (False, info). The caller commits on True."""
    now = _now(now)
    db.execute(text("select pg_advisory_xact_lock(hashtext('recourse-anon-budget'))"))
    ok, info = anon_reserve(db, device_id, ip_hash, now)
    if not ok:
        return False, info
    row = M.AnonQuestion(device_id=device_id, question=question, audience=audience, created_at=now, expires_at=now + datetime.timedelta(days=ANON_KEEP_DAYS))
    db.add(row)
    db.flush()
    return True, {**info, "id": row.id}


def anon_finish(db, question_id, device_id, ip_hash, cost_inr, state, counted, now=None):
    """After the engine: the real cost and the state go on the stored question; a refusal or a failure (counted=False) gives the two units back to the PERSON, but the money the model call cost stays on the row, so the trial's daily
    budget sees every rupee spent, refused questions included (found on staging 2026-10-23: a topic-bar refusal cost Rs 0.43 and had been recorded as 0)."""
    row = db.get(M.AnonQuestion, question_id)
    if row is not None:
        row.cost_inr = cost_inr or 0
        row.result_state = state
    if not counted:
        anon_release(db, device_id, ip_hash, now)
