"""
api/db/migrate.py -- brings the database up to the latest schema and loads the plans (step A2).  Run:   python -m api.db.migrate
Meant to run before the service starts (Railway start command: `python -m api.db.migrate && uvicorn api.main:app ...`). With no DATABASE_URL it says so and exits 0 (the service still starts without a database);
with a database it exits 1 on any failure, so a deploy with a broken schema does not go live. A Postgres advisory lock makes two services starting together take turns instead of racing.
"""
import os
import sys

LOCK_KEY = 74_201_021      # arbitrary, fixed: the same number in every process that migrates this database


def alembic_config():
    from alembic.config import Config
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(here, "migrations"))
    return cfg


def upgrade(engine=None):
    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from . import session as S
    from .seed import seed
    engine = engine or S.get_engine()
    with engine.connect() as lock:
        if engine.dialect.name == "postgresql":
            lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
            lock.commit()
        try:
            cfg = alembic_config()
            cfg.attributes["engine"] = engine
            command.upgrade(cfg, "head")
            with Session(engine, expire_on_commit=False) as s:
                result = seed(s)
                s.commit()
            return result
        finally:
            if engine.dialect.name == "postgresql":
                lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                lock.commit()


def main():
    from . import session as S
    if not S.configured():
        print("migrate: DATABASE_URL is not set, nothing to do")
        return 0
    try:
        r = upgrade()
    except Exception as exc:  # noqa: BLE001
        print(f"migrate: FAILED ({type(exc).__name__}); the service must not start on this database")
        return 1
    print(f"migrate: schema at head; plans added {r['plans_added']}, entitlements added {r['entitlements_added']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
