"""
api/netutil.py -- the caller's address, scrambled (step A3). The service sits behind Railway's proxy, so the address is in X-Forwarded-For; only the entry added by OUR proxy can be trusted, i.e. the one `trusted_proxy_hops` places from the RIGHT
(a caller may add anything to the left). Addresses are never stored or counted as they are: ip_hash() is an HMAC with IP_HASH_SECRET, so a copy of the database cannot be turned back into addresses. Without the secret there is no hash (None) and the
things that need one (the anonymous trial) refuse.
"""
import hashlib
import hmac

from . import config


def client_ip(request):
    hops = config.trusted_proxy_hops()
    xff = request.headers.get("x-forwarded-for") or ""
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if hops and len(parts) >= hops:
        return parts[-hops]
    if hops and parts:
        return parts[0]
    c = getattr(request, "client", None)
    return (c.host if c else None) or "unknown"


def ip_hash(ip):
    secret = config.ip_hash_secret()
    if not secret or not ip:
        return None
    return hmac.new(secret.encode("utf-8"), ("ip:" + ip).encode("utf-8"), hashlib.sha256).hexdigest()[:48]
