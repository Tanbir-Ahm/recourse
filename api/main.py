"""
api/main.py -- the Recourse API service (website design WEBSITE_DESIGN.md, step A0: a SKELETON).
Only the health route exists. It answers with the service's role so a deploy that started the wrong program (for example Streamlit, because the repository root's railway.json
and Procfile belong to the website) fails its healthcheck instead of going live. Nothing here touches the answer engine yet.
Run: uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
import os

from fastapi import FastAPI

ROLE = "api"

app = FastAPI(title="Recourse API", version="0.0.1")


@app.get("/api/health")
def health():
    """Liveness and identity. No authentication. 'role' must be 'api'; 'commit' is Railway's build commit when present; 'db' is filled in when the database is added."""
    return {"role": ROLE, "commit": (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:12], "db": "not_configured"}
