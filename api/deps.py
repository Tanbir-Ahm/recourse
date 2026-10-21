"""
api/deps.py -- what every signed-in route needs (step A3): a database session, and WHO is calling.
Two ways to be somebody (WEBSITE_DESIGN 1.3): (1) the Streamlit service's short-lived signed token in `Authorization: Bearer ...` (the person is created on first use), (2) the browser's session cookie, which for every call that changes
something must also carry the CSRF header bound to that session. If both are present the Bearer token wins. Everything here answers 503 while ACCOUNTS_OPEN is off (gate G1), and never puts text from a token in an error.
"""
import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request

from . import config, consent
from .auth import google, sessions, streamlit_token, users
from .auth.errors import AuthError
from .db import models as M
from .db import session as dbs

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def get_db():
    if not dbs.configured():
        raise HTTPException(status_code=503, detail="database is not configured")
    db = dbs.session()
    try:
        yield db
    finally:
        db.close()


@dataclass
class Principal:
    user: M.User
    via: str                      # 'session' | 'streamlit'
    session_token: Optional[str] = None


def _fail(exc):
    raise HTTPException(status_code=exc.status, detail=exc.code)


def require_accounts_open():
    if not config.accounts_open():
        raise HTTPException(status_code=503, detail="accounts are not open yet")
    if not consent.legal_ready() and not config.allow_placeholder_legal():
        raise HTTPException(status_code=503, detail="legal text is not final")        # gate G1: no accounts on placeholder text


def current_user(request: Request, db=Depends(get_db)) -> Principal:
    require_accounts_open()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        try:
            claims = streamlit_token.verify(auth[7:].strip(), config.streamlit_secret())
            user = users.find_or_create(db, "google", claims["sub"], claims["email"], claims["email_verified"], claims.get("name"))
            db.commit()
        except AuthError as exc:
            db.rollback()
            _fail(exc)
        return Principal(user=user, via="streamlit")
    token = request.cookies.get(sessions.COOKIE)
    found = sessions.lookup(db, token) if token else None
    if not found:
        db.commit()                # lookup may have removed an expired session
        raise HTTPException(status_code=401, detail="not_signed_in")
    _row, user = found
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(sessions.CSRF_HEADER) or ""
        if not hmac.compare_digest(sent.encode("utf-8"), sessions.csrf_for(token).encode("utf-8")):
            raise HTTPException(status_code=403, detail="csrf")
        origin = (request.headers.get("origin") or "").rstrip("/")
        allowed = config.cors_origins()
        if origin and allowed and origin not in allowed:
            raise HTTPException(status_code=403, detail="origin")
    return Principal(user=user, via="session", session_token=token)


def verify_google(id_token):
    try:
        return google.verify_id_token(id_token, config.google_client_id())
    except AuthError as exc:
        _fail(exc)
