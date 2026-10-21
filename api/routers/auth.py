"""
api/routers/auth.py -- sign in and out for the browser path (step A3). POST /api/auth/google takes a Google ID token the front end got from Google, verifies it (api/auth/google.py), finds or creates the person, and sets two cookies:
rc_session (HttpOnly: the script cannot read it) and rc_csrf (readable: the page echoes it in X-CSRF-Token on every call that changes something). Closed (503) until ACCOUNTS_OPEN=on.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import config, netutil
from ..auth import sessions, users
from ..auth.errors import AuthError
from ..deps import Principal, current_user, get_db, require_accounts_open, verify_google

router = APIRouter()


class GoogleBody(BaseModel):
    id_token: str = Field(min_length=10, max_length=8192)


def _cookie_args():
    return {"httponly": True, "secure": config.cookie_secure(), "samesite": "lax", "path": "/", "max_age": config.session_days() * 86400}


def set_session_cookies(response, token):
    response.set_cookie(sessions.COOKIE, token, **_cookie_args())
    response.set_cookie(sessions.CSRF_COOKIE, sessions.csrf_for(token), **{**_cookie_args(), "httponly": False})


def clear_session_cookies(response):
    response.delete_cookie(sessions.COOKIE, path="/")
    response.delete_cookie(sessions.CSRF_COOKIE, path="/")


@router.post("/api/auth/google", summary="Sign in with a Google ID token")
def sign_in_google(body: GoogleBody, request: Request, response: Response, db=Depends(get_db)):
    require_accounts_open()
    claims = verify_google(body.id_token)
    try:
        user = users.find_or_create(db, "google", claims["sub"], claims["email"], claims["email_verified"], claims.get("name"))
        token = sessions.create(db, user, config.session_days(), user_agent=request.headers.get("user-agent"), ip_hash=netutil.ip_hash(netutil.client_ip(request)))
        db.commit()
    except AuthError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.code) from None
    set_session_cookies(response, token)
    return {"user": {"id": str(user.id), "email": user.email, "display_name": user.display_name, "role": user.role}, "csrf": sessions.csrf_for(token)}


@router.post("/api/auth/logout", summary="Sign out")
def sign_out(response: Response, principal: Principal = Depends(current_user), db=Depends(get_db)):
    if principal.session_token:
        sessions.destroy(db, principal.session_token)
        db.commit()
    clear_session_cookies(response)
    return {"ok": True}
