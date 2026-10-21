"""
api/auth/users.py -- who is this person (step A3). find_or_create() maps a verified (provider, subject, email) to ONE users row: by identity first; else by verified email (so the same person who signs in by another route is the same user); else a new user on the free plan.
A suspended or deleted account never signs in. Emails are stored lower-case (the table checks it).
"""
import datetime

from sqlalchemy import select

from ..db import models as M
from .errors import AuthError


def free_plan_id(db):
    return db.execute(select(M.Plan.id).where(M.Plan.code == "free")).scalar_one_or_none()


def find_or_create(db, provider, subject, email, email_verified, name=None, now=None):
    """-> User. The caller commits."""
    if not email_verified:
        raise AuthError("email_not_verified", 403)
    email = email.strip().lower()
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ident = db.execute(select(M.Identity).where(M.Identity.provider == provider, M.Identity.subject == subject)).scalar_one_or_none()
    if ident is not None:
        user = db.get(M.User, ident.user_id)
    else:
        user = db.execute(select(M.User).where(M.User.email == email)).scalar_one_or_none()
        if user is None:
            user = M.User(email=email, email_verified=True, display_name=name, plan_id=free_plan_id(db))
            db.add(user)
            db.flush()
        db.add(M.Identity(user_id=user.id, provider=provider, subject=subject))
        db.flush()
    if user.status != "active":
        raise AuthError("account_unavailable", 403)
    user.last_seen_at = now
    if name and not user.display_name:
        user.display_name = name
    if not user.email_verified:
        user.email_verified = True
    return user
