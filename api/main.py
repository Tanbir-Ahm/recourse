"""
api/main.py -- the Recourse API service (website design WEBSITE_DESIGN.md, step A0: a SKELETON).
The health route and, from A1, POST /api/ask (api/ask.py). The health route answers with the service's role so a deploy that started the wrong program (for example Streamlit, because the repository root's railway.json
and Procfile belong to the website) fails its healthcheck instead of going live. The engine is imported only when the first question arrives, never by the health route.
Run: uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from . import ask as _ask
from . import config
from .cors import CORSMiddleware
from .ratelimit import RateLimitMiddleware
from .routers import anon as _anon_router
from .routers import auth as _auth_router
from .routers import chats as _chats_router
from .routers import me as _me_router
from .routers import notes as _notes_router

ROLE = "api"

def _flag(name):
    return (os.environ.get(name) or "").strip().strip("\"'").lower() in ("1", "on", "true", "yes")


async def _purge_loop():
    """Keeps the retention promises (api/purge.py): once at the start, then every API_PURGE_INTERVAL_SECONDS. Does nothing without a database; a failure is logged by type only and tried again next time."""
    from .db import session
    while True:
        if session.configured():
            try:
                from . import purge
                await asyncio.to_thread(purge.run)
            except Exception as exc:  # noqa: BLE001
                print(f"api: purge failed ({type(exc).__name__})")
        await asyncio.sleep(config.purge_interval_seconds())


@asynccontextmanager
async def lifespan(_app):
    """With API_RUN_MIGRATIONS=on and a DATABASE_URL, bring the schema up to date (and load the plans) before the first request, under a Postgres lock so several services starting together take turns.
    A failure stops the start: a deploy on a broken schema must not go live. The reason is never printed (it could carry the database address)."""
    if _flag("API_RUN_MIGRATIONS"):
        from .db import migrate, session
        if session.configured():
            try:
                await asyncio.to_thread(migrate.upgrade)
            except Exception as exc:  # noqa: BLE001
                print(f"api: database migration FAILED ({type(exc).__name__}); not starting")
                raise RuntimeError("database migration failed") from None
            print("api: database schema is up to date")
        else:
            print("api: API_RUN_MIGRATIONS is on but DATABASE_URL is not set; skipping")
    task = asyncio.create_task(_purge_loop()) if config.purge_on() else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()


app = FastAPI(title="Recourse API", version="0.1.0", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(CORSMiddleware)           # added last = outermost: a refused request still carries the CORS headers a browser needs to read it

app.include_router(_ask.router)
app.include_router(_auth_router.router)
app.include_router(_me_router.router)
app.include_router(_chats_router.router)
app.include_router(_anon_router.router)
app.include_router(_notes_router.router)


@app.get("/api/debug/headers", include_in_schema=False)
def debug_headers(request: Request):
    """STAGING DIAGNOSTIC for the client-address question (FOLLOW_UPS 2bz): with API_DEBUG_HEADERS=on it shows which address headers the platform's proxy passed on, so TRUSTED_PROXY_HOPS can be set from evidence. It returns only the caller's OWN
    request's address headers and never an Authorization header or a cookie. Off (404) unless the variable is on; never set it on production."""
    if not _flag("API_DEBUG_HEADERS"):
        raise HTTPException(status_code=404, detail="not found")
    from . import netutil
    h = request.headers
    return {"x_forwarded_for": h.get("x-forwarded-for"), "x_real_ip": h.get("x-real-ip"), "forwarded": h.get("forwarded"), "cf_connecting_ip": h.get("cf-connecting-ip"), "peer": getattr(request.client, "host", None),
            "trusted_proxy_hops": config.trusted_proxy_hops(), "client_ip_header": config.client_ip_header() or "(default: hops rule)", "address_the_service_would_use": netutil.client_ip(request)}


@app.get("/api/health")
def health():
    """Liveness and identity. No authentication. 'role' must be 'api'; 'commit' is Railway's build commit when present; 'db' is 'not_configured' without DATABASE_URL, else 'ok' or 'down' (a down database does not fail the health check: the service still answers; the value is for the monitor)."""
    from .db import session as _db
    return {"role": ROLE, "commit": (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:12], "db": _db.status()}
