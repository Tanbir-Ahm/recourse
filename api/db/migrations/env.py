"""Alembic environment (step A2). Uses the engine handed in by api.db.migrate (cfg.attributes['engine']) or, for the alembic command line, DATABASE_URL."""
from alembic import context
from sqlalchemy import create_engine

from api.db.models import Base
from api.db.session import database_url

target_metadata = Base.metadata


def _engine():
    eng = context.config.attributes.get("engine")
    if eng is not None:
        return eng
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(url)


def run_migrations_online():
    with _engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run_migrations_online()
