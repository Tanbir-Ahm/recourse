"""
api/main.py -- the Recourse API service (website design WEBSITE_DESIGN.md, step A0: a SKELETON).
The health route and, from A1, POST /api/ask (api/ask.py). The health route answers with the service's role so a deploy that started the wrong program (for example Streamlit, because the repository root's railway.json
and Procfile belong to the website) fails its healthcheck instead of going live. The engine is imported only when the first question arrives, never by the health route.
Run: uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
import os

from fastapi import FastAPI

from . import ask as _ask

ROLE = "api"

app = FastAPI(title="Recourse API", version="0.1.0")

app.include_router(_ask.router)


@app.get("/api/health")
def health():
    """Liveness and identity. No authentication. 'role' must be 'api'; 'commit' is Railway's build commit when present; 'db' is filled in when the database is added."""
    return {"role": ROLE, "commit": (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:12], "db": "not_configured"}
