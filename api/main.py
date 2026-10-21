"""
api/main.py -- the Recourse API service (website design WEBSITE_DESIGN.md, step A0: a SKELETON).
The health route and, from A1, POST /api/ask (api/ask.py). The health route answers with the service's role so a deploy that started the wrong program (for example Streamlit, because the repository root's railway.json
and Procfile belong to the website) fails its healthcheck instead of going live. The engine is imported only when the first question arrives, never by the health route.
Run: uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import ask as _ask
from .routers import auth as _auth_router
from .routers import me as _me_router

ROLE = "api"

def _flag(name):
    return (os.environ.get(name) or "").strip().strip("\"'").lower() in ("1", "on", "true", "yes")


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
    yield


app = FastAPI(title="Recourse API", version="0.1.0", lifespan=lifespan)

app.include_router(_ask.router)
app.include_router(_auth_router.router)
app.include_router(_me_router.router)


@app.get("/api/health")
def health():
    """Liveness and identity. No authentication. 'role' must be 'api'; 'commit' is Railway's build commit when present; 'db' is 'not_configured' without DATABASE_URL, else 'ok' or 'down' (a down database does not fail the health check: the service still answers; the value is for the monitor)."""
    from .db import session as _db
    return {"role": ROLE, "commit": (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:12], "db": _db.status()}
