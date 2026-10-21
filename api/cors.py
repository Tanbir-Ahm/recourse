"""
api/cors.py -- cross-origin access for the new front end (step A3.5). Plain ASGI (not Starlette's BaseHTTPMiddleware, which can hold back a server-sent-events stream). Only origins listed in CORS_ALLOW_ORIGINS get any CORS header, so with the variable
unset the browser blocks every cross-site page; the list is read at each request. Credentials (the session cookie) are allowed for a listed origin; the CSRF header is what protects a signed-in call.
"""
from . import config

ALLOW_METHODS = "GET, POST, PATCH, DELETE, OPTIONS"
ALLOW_HEADERS = "Content-Type, X-CSRF-Token, Idempotency-Key, Accept"
EXPOSE = "X-Request-Id"


class CORSMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        origin = (headers.get("origin") or "").rstrip("/")
        allowed = bool(origin) and origin in config.cors_origins()
        if allowed and scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
            await send({"type": "http.response.start", "status": 204, "headers": [
                (b"access-control-allow-origin", origin.encode()), (b"access-control-allow-credentials", b"true"), (b"access-control-allow-methods", ALLOW_METHODS.encode()),
                (b"access-control-allow-headers", ALLOW_HEADERS.encode()), (b"access-control-max-age", b"600"), (b"vary", b"Origin")]})
            await send({"type": "http.response.body", "body": b""})
            return
        if not allowed:
            return await self.app(scope, receive, send)

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                h = list(message.get("headers", []))
                h += [(b"access-control-allow-origin", origin.encode()), (b"access-control-allow-credentials", b"true"), (b"access-control-expose-headers", EXPOSE.encode()), (b"vary", b"Origin")]
                message = {**message, "headers": h}
            await send(message)
        await self.app(scope, receive, send_with_cors)
