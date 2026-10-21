"""
api/db/session.py -- the connection to the database (step A2). Fails closed: without DATABASE_URL nothing here connects and the rest of the service works as before (the ask route needs no database yet).
Railway's Postgres hands out DATABASE_URL as postgresql://...; the driver here is psycopg 3, so the scheme is rewritten to postgresql+psycopg://. The database is imported lazily: /api/health never loads SQLAlchemy
unless a database is configured.
"""
import os
import threading
import time

_ENGINE = {"e": None, "url": None}
_LOCK = threading.Lock()


def _env(name):
    return (os.environ.get(name) or "").strip().strip("\"'")


def database_url():
    """DATABASE_URL normalised for psycopg 3, or '' when none is set."""
    url = _env("DATABASE_URL")
    if not url:
        return ""
    for old in ("postgres://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old):]
    return url


def configured():
    return bool(database_url())


def get_engine():
    """One engine per process (a small pool; connections are checked before use). Raises RuntimeError when no database is configured."""
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    with _LOCK:
        if _ENGINE["e"] is None or _ENGINE["url"] != url:
            from sqlalchemy import create_engine
            if _ENGINE["e"] is not None:
                _ENGINE["e"].dispose()
            _ENGINE["e"] = create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=1800, connect_args={"connect_timeout": 3} if url.startswith("postgresql") else {})
            _ENGINE["url"] = url
        return _ENGINE["e"]


def reset_engine():
    """For tests and for a changed DATABASE_URL."""
    _STATUS["at"], _STATUS["v"] = 0.0, None
    with _LOCK:
        if _ENGINE["e"] is not None:
            _ENGINE["e"].dispose()
        _ENGINE["e"], _ENGINE["url"] = None, None


_STATUS = {"at": 0.0, "v": None}
STATUS_CACHE_SECONDS = 5.0


def status():
    """'not_configured' | 'ok' | 'down' for /api/health. Never raises, never returns the error text (it could carry the address). The answer is remembered for 5 seconds so a flood of health checks is one query."""
    if not configured():
        return "not_configured"
    now = time.monotonic()
    if _STATUS["v"] is not None and now - _STATUS["at"] < STATUS_CACHE_SECONDS:
        return _STATUS["v"]
    try:
        from sqlalchemy import text
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        v = "ok"
    except Exception:  # noqa: BLE001
        v = "down"
    _STATUS["at"], _STATUS["v"] = now, v
    return v


def session():
    """A SQLAlchemy session bound to the engine (use as a context manager; commit explicitly)."""
    from sqlalchemy.orm import Session
    return Session(get_engine(), expire_on_commit=False)
