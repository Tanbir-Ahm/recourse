"""
api/auth/sessions.py -- the browser path's login (step A3). The cookie holds a random 256-bit value; the database holds only its SHA-256 (a copy of the table cannot be used to log in). Expired sessions are refused and removed.
The CSRF token is an HMAC of the cookie value (bound to THIS session, readable by the page's own script, echoed back in X-CSRF-Token on every call that changes something).
"""
import datetime
import hashlib
import hmac
import secrets

from sqlalchemy import delete, select

from ..db import models as M

COOKIE = "rc_session"
CSRF_COOKIE = "rc_csrf"
CSRF_HEADER = "X-CSRF-Token"


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_for(token):
    return hmac.new(token.encode("utf-8"), b"recourse-csrf-v1", hashlib.sha256).hexdigest()


def create(db, user, days, user_agent=None, ip_hash=None, now=None):
    """-> the cookie value. The caller commits."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    token = secrets.token_urlsafe(32)
    db.add(M.Session(id=_hash(token), user_id=user.id, expires_at=now + datetime.timedelta(days=days),
                     user_agent_hash=_hash(user_agent)[:32] if user_agent else None, ip_hash=ip_hash))
    db.flush()
    return token


def lookup(db, token, now=None):
    """-> (Session, User) or None. An expired session is deleted; a session whose user is not active is refused."""
    if not token or len(token) > 200:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    row = db.get(M.Session, _hash(token))
    if row is None:
        return None
    if row.expires_at <= now:
        db.delete(row)
        db.flush()
        return None
    user = db.get(M.User, row.user_id)
    if user is None or user.status != "active":
        return None
    return row, user


def destroy(db, token):
    if token:
        db.execute(delete(M.Session).where(M.Session.id == _hash(token)))
        db.flush()


def destroy_all(db, user_id):
    db.execute(delete(M.Session).where(M.Session.user_id == user_id))
    db.flush()
