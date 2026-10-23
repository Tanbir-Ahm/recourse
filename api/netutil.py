"""
api/netutil.py -- the caller's address, scrambled (step A3). The service sits behind Railway's proxy. MEASURED on staging-api 2026-10-23 (FOLLOW_UPS 2bz): Railway's edge REPLACES a caller's own X-Forwarded-For with "<visitor>, <an edge address that changes>" and sets
X-Real-IP to the visitor, so the default rule (the entry `trusted_proxy_hops` places from the RIGHT) saw a different "address" on every request; on Railway set CLIENT_IP_HEADER=x-real-ip. Elsewhere, with no setting, only the entry added by OUR proxy is trusted (a caller may add anything to the left). Addresses are never stored or counted as they are: ip_hash() is an HMAC with IP_HASH_SECRET, so a copy of the database cannot be turned back into addresses. Without the secret there is no hash (None) and the
things that need one (the anonymous trial) refuse.
"""
import hashlib
import hmac
import ipaddress

from . import config


def _valid(value):
    """The value as an address (an IPv6 address is cut to its /64: one subscriber's devices change the lower half all the time), or None when it is not an IP address."""
    v = (value or "").strip()
    if not v or len(v) > 64:
        return None
    try:
        ip = ipaddress.ip_address(v)
    except ValueError:
        return None
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address)
    return str(ip)


def client_ip(request):
    """The visitor's address (never raw to a database; see ip_hash). By CLIENT_IP_HEADER when it names a header and that header holds a valid address; otherwise the entry `trusted_proxy_hops` places from the RIGHT of X-Forwarded-For; otherwise the connection's own."""
    mode = config.client_ip_header()
    if mode == "x-real-ip":
        got = _valid(request.headers.get("x-real-ip"))
        if got:
            return got
    elif mode == "xff-first":
        parts = [p.strip() for p in (request.headers.get("x-forwarded-for") or "").split(",") if p.strip()]
        got = _valid(parts[0]) if parts else None
        if got:
            return got
    hops = config.trusted_proxy_hops()
    xff = request.headers.get("x-forwarded-for") or ""
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if hops and len(parts) >= hops:
        return _valid(parts[-hops]) or parts[-hops][:64]
    if hops and parts:
        return _valid(parts[0]) or parts[0][:64]
    c = getattr(request, "client", None)
    return (c.host if c else None) or "unknown"


def ip_hash(ip):
    secret = config.ip_hash_secret()
    if not secret or not ip:
        return None
    return hmac.new(secret.encode("utf-8"), ("ip:" + ip).encode("utf-8"), hashlib.sha256).hexdigest()[:48]
