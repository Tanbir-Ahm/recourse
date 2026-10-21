"""
api/purge.py -- the retention promises, kept by code (step A3.5). Run hourly by the service (API_PURGE=off stops it; API_PURGE_INTERVAL_SECONDS, default 3600) and by hand:  python -m api.purge
Deletes: trial questions past their 90 days (owner's D4), sign-in sessions past their expiry, trial counters older than two days, and chats older than a plan's chat_history_days (a plan with no such limit keeps chats until the person deletes them, D3).
Takes a Postgres lock first, so two copies of the service never purge at once. Writes ONE audit row with the counts when anything was removed; it never holds or logs text.
"""
import datetime
import logging
import sys

from sqlalchemy import delete, select, text

from . import quota
from .db import models as M

logger = logging.getLogger("recourse.api")
LOCK_NAME = "recourse-purge"


def purge_once(db, now=None):
    """-> {'anon_questions', 'sessions', 'anon_counters', 'chats'} counts, or None when another purge holds the lock. The caller commits."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not db.execute(text("select pg_try_advisory_xact_lock(hashtext(:n))"), {"n": LOCK_NAME}).scalar():
        return None
    out = {}
    out["anon_questions"] = db.execute(delete(M.AnonQuestion).where(M.AnonQuestion.expires_at < now)).rowcount
    out["sessions"] = db.execute(delete(M.Session).where(M.Session.expires_at < now)).rowcount
    keep_from = now.astimezone(quota.IST).date() - datetime.timedelta(days=2)
    out["anon_counters"] = db.execute(delete(M.AnonCounter).where(M.AnonCounter.day < keep_from)).rowcount
    chats = 0
    for plan_id in db.execute(select(M.Plan.id)).scalars().all():
        ent = quota.entitlement(db, plan_id, "chat_history_days")
        if ent is None or ent[1] is None:
            continue
        cutoff = now - datetime.timedelta(days=ent[1])
        users = select(M.User.id).where(M.User.plan_id == plan_id)
        chats += db.execute(delete(M.Chat).where(M.Chat.user_id.in_(users), M.Chat.updated_at < cutoff)).rowcount
    out["chats"] = chats
    if any(out.values()):
        db.add(M.AuditLog(actor_user_id=None, action="purge", target_type="retention", detail=dict(out)))
    return out


def run():
    from .db import session as dbs
    with dbs.session() as db:
        out = purge_once(db)
        db.commit()
    if out and any(out.values()):
        logger.info("purge: %s", out)
    return out


def main():
    from .db import session as dbs
    if not dbs.configured():
        print("purge: DATABASE_URL is not set, nothing to do")
        return 0
    try:
        out = run()
    except Exception as exc:  # noqa: BLE001
        print(f"purge: FAILED ({type(exc).__name__})")
        return 1
    print("purge: another copy is running" if out is None else f"purge: removed {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
