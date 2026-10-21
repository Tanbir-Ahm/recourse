"""
api/auth/streamlit_token.py -- the short-lived signed token the Streamlit service sends for the person it has signed in (WEBSITE_DESIGN 1.3; A0 spike 1 showed Streamlit never refreshes Google's own token, so it sends this one).
HS256, shared secret STREAMLIT_API_SECRET; claims iss=streamlit, aud=recourse-api, sub (Google subject), email, email_verified, iat, exp (at most 10 minutes after iat), jti (a token is accepted ONCE, so a copy captured
in transit is worthless; the memory of used jti values is in this process, which is why the service runs as one copy). mint() is what the Streamlit side will call (step A5) and what the tests use.
"""
import threading
import time
import uuid

import jwt

from .errors import AuthError

ISSUER = "streamlit"
AUDIENCE = "recourse-api"
MAX_LIFETIME = 600
SKEW = 30


class ReplayCache:
    def __init__(self, limit=100_000):
        self._seen = {}
        self._lock = threading.Lock()
        self._limit = limit
        self._last_purge = 0.0

    def add(self, jti, exp, now=None):
        """True when the jti is new (and remembered until exp), False when it was used before."""
        now = now if now is not None else time.time()
        with self._lock:
            if len(self._seen) >= self._limit or now - self._last_purge > 60:
                for k in [k for k, v in self._seen.items() if v < now]:
                    del self._seen[k]
                self._last_purge = now
            if len(self._seen) >= self._limit:
                return False        # full of unexpired tokens: refuse rather than forget one
            if jti in self._seen and self._seen[jti] >= now:
                return False
            self._seen[jti] = exp
            return True


REPLAY = ReplayCache()


def mint(secret, sub, email, email_verified=True, name=None, ttl=300, now=None):
    now = int(now if now is not None else time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": str(sub), "email": email, "email_verified": bool(email_verified), "iat": now, "exp": now + int(ttl), "jti": uuid.uuid4().hex}
    if name:
        claims["name"] = name
    return jwt.encode(claims, secret, algorithm="HS256")


def verify(token, secret, replay=None, now=None):
    """-> {'sub', 'email', 'email_verified': True, 'name'}; raises AuthError (a fixed code) for anything wrong, including a token that was already used."""
    if not secret:
        raise AuthError("streamlit_sign_in_off", 503)
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise AuthError("bad_token")
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER, options={"require": ["exp", "iat", "sub", "jti", "aud", "iss"]}, leeway=SKEW)
    except jwt.ExpiredSignatureError:
        raise AuthError("token_expired") from None
    except jwt.PyJWTError:
        raise AuthError("bad_token") from None
    t = now if now is not None else time.time()
    iat, exp = claims.get("iat"), claims.get("exp")
    if not isinstance(iat, (int, float)) or not isinstance(exp, (int, float)) or exp - iat > MAX_LIFETIME or iat > t + SKEW:
        raise AuthError("bad_token")
    if claims.get("email_verified") is not True:
        raise AuthError("email_not_verified", 403)
    email = (claims.get("email") or "").strip()
    sub = str(claims.get("sub") or "").strip()
    jti = str(claims.get("jti") or "")
    if not email or "@" not in email or not sub or len(sub) > 255 or len(email) > 320 or not jti or len(jti) > 64:
        raise AuthError("bad_token")
    if not (replay or REPLAY).add(jti, exp, now=t):
        raise AuthError("token_reused")
    return {"sub": sub, "email": email, "email_verified": True, "name": (claims.get("name") or "")[:200] or None}
