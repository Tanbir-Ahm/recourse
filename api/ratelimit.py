"""
api/ratelimit.py -- a flood guard per caller address (step A3.5). Plain ASGI. Counts requests per scrambled address in a sliding minute, in memory only (nothing is stored; the service runs as ONE replica, WEBSITE_DESIGN 9): API_RATE_LIMIT_PER_MINUTE
(default 120; 0 turns it off) for every /api route except /api/health, and API_AUTH_RATE_PER_MINUTE (default 20) for sign-in. A request that carries a Bearer token is NOT counted here: the Streamlit service makes every visitor's call from its own
address, and a made-up token fails its signature check anyway; the per-person allowance (quota.py) is what limits signed-in people. Over the limit: 429 with Retry-After.
This is a blunt guard against floods and password-guessing style hammering, not a fairness mechanism: many people can share one mobile address.
"""
import json
import time
from collections import deque

from starlette.requests import Request

from . import config, netutil

WINDOW = 60.0
MAX_KEYS = 50000
_HITS = {}


def reset():
    _HITS.clear()


def _limit_for(path):
    if path == "/api/health" or not path.startswith("/api"):
        return None
    if path.startswith("/api/auth/"):
        return "auth", config.auth_rate_per_minute()
    return "all", config.rate_limit_per_minute()


def hit(key, limit, now=None):
    """True if allowed (and counted), else False."""
    now = time.monotonic() if now is None else now
    if len(_HITS) > MAX_KEYS:
        for k in [k for k, d in _HITS.items() if not d or now - d[-1] > WINDOW]:
            _HITS.pop(k, None)
        if len(_HITS) > MAX_KEYS:
            _HITS.clear()                # under an enormous spread of addresses, forget rather than grow
    d = _HITS.setdefault(key, deque())
    while d and now - d[0] > WINDOW:
        d.popleft()
    if len(d) >= limit:
        return False
    d.append(now)
    return True


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        rule = _limit_for(scope["path"])
        if rule is None or rule[1] <= 0:
            return await self.app(scope, receive, send)
        req = Request(scope)
        if (req.headers.get("authorization") or "").lower().startswith("bearer "):
            return await self.app(scope, receive, send)
        who = netutil.ip_hash(netutil.client_ip(req)) or netutil.client_ip(req)
        if not hit((rule[0], who), rule[1]):
            body = json.dumps({"detail": "rate_limited"}).encode()
            await send({"type": "http.response.start", "status": 429, "headers": [(b"content-type", b"application/json"), (b"retry-after", b"30"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
