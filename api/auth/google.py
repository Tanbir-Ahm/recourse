"""
api/auth/google.py -- verifies a Google ID token (the browser path; WEBSITE_DESIGN 1.3). Checks the signature against Google's published keys, the issuer, that the token was issued for OUR client id, that it has not
expired, and that Google says the email is verified. Anything else raises AuthError with a fixed code; nothing from the token is put in an error.
The key fetcher is a parameter so tests can use a stand-in for Google; in production it is PyJWT's PyJWKClient with Google's key set (cached).
"""
import jwt

from .errors import AuthError

JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("accounts.google.com", "https://accounts.google.com")
_CLIENT = {"c": None}


def default_jwks_client():
    if _CLIENT["c"] is None:
        _CLIENT["c"] = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600, timeout=5)
    return _CLIENT["c"]


def verify_id_token(token, client_id, jwks_client=None):
    """-> {'sub', 'email', 'email_verified': True, 'name'} for a valid token; raises AuthError otherwise."""
    if not client_id:
        raise AuthError("google_sign_in_off", 503)
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise AuthError("bad_token")
    try:
        key = (jwks_client or default_jwks_client()).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id, options={"require": ["exp", "iat", "sub", "aud", "iss"]}, leeway=30)
    except jwt.ExpiredSignatureError:
        raise AuthError("token_expired") from None
    except jwt.PyJWTError:
        raise AuthError("bad_token") from None
    except Exception:  # noqa: BLE001 -- a failure to fetch Google's keys is not the caller's fault, and says nothing about the token
        raise AuthError("keys_unavailable", 503) from None
    if claims.get("iss") not in ISSUERS:
        raise AuthError("bad_token")
    ev = claims.get("email_verified")
    if ev is not True and str(ev).lower() != "true":
        raise AuthError("email_not_verified", 403)
    email = (claims.get("email") or "").strip()
    sub = str(claims.get("sub") or "").strip()
    if not email or "@" not in email or not sub or len(sub) > 255 or len(email) > 320:
        raise AuthError("bad_token")
    return {"sub": sub, "email": email, "email_verified": True, "name": (claims.get("name") or "")[:200] or None}
