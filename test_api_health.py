"""
test_api_health.py -- the API service skeleton (api/main.py, api/railway.api.json). Free and offline.
Guards the trap named in WEBSITE_DESIGN.md 1.2: the repository root's railway.json and Procfile start Streamlit; the API service must start uvicorn from its own file and its healthcheck must be a route only the API has.
Run: python -X utf8 test_api_health.py
"""
import json
import os
import sys

from fastapi.testclient import TestClient

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


from api.main import app, ROLE

c = TestClient(app)
r = c.get("/api/health")
check(r.status_code == 200 and r.json().get("role") == "api" == ROLE, f"/api/health answers 200 with role 'api' ({r.status_code} {r.json()})")
check(set(r.json()) == {"role", "commit", "db"}, "the health body carries exactly role, commit, db (no secrets, no engine data)")
os.environ["RAILWAY_GIT_COMMIT_SHA"] = "0123456789abcdef0123"
check(c.get("/api/health").json()["commit"] == "0123456789ab", "commit is Railway's build sha cut to 12 characters")
check(c.get("/").status_code == 404, "no route outside /api (nothing else is exposed yet)")
check(c.post("/api/health").status_code == 405, "health is GET only")

cfg = json.load(open(os.path.join(HERE, "api", "railway.api.json"), encoding="utf-8"))["deploy"]
check("uvicorn api.main:app" in cfg["startCommand"] and "streamlit" not in cfg["startCommand"].lower(), "the API config starts uvicorn api.main:app and never Streamlit")
check("$PORT" in cfg["startCommand"], "it listens on Railway's $PORT")
check(cfg["healthcheckPath"] == "/api/health" and any(getattr(rt, "path", None) == cfg["healthcheckPath"] for rt in app.routes), "its healthcheck path is a route the app really has")
check(cfg.get("numReplicas") == 1, "one replica (the daily-budget file has an in-process lock only)")

root = json.load(open(os.path.join(HERE, "railway.json"), encoding="utf-8"))["deploy"]
check("streamlit run recourse_app.py" in root["startCommand"] and root["healthcheckPath"] == "/_stcore/health", "the root railway.json is still the website's (this work must not change it)")
check("streamlit run recourse_app.py" in open(os.path.join(HERE, "Procfile"), encoding="utf-8").read(), "the Procfile is still the website's")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
