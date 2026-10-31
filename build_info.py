"""
build_info.py -- which code is running (added 2026-10-31, after an answer from staging showed a defect that a fix pushed two days earlier should have removed, and nobody could say which commit the service ran).

Railway sets RAILWAY_GIT_COMMIT_SHA for a service deployed from GitHub. A service deployed with the Railway CLI has none; then the commit is "unknown" and the stamp says so.
The stamp is shown in four places, so that "which code made this answer" can be read from the answer's own surroundings: the start-up line BUILD_INFO in the log, the field `commit` on every COST_QUESTION line,
a small line at the foot of the Streamlit page, and (already there before this change) the `commit` of the API's /api/health.
It is not a secret and not a version promise: twelve characters of a public-to-the-owner commit hash.
"""
import os

SHORT = 12


def commit():
    """The first 12 characters of the deployed commit, or 'unknown'."""
    v = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("SOURCE_COMMIT") or "").strip().lower()
    return v[:SHORT] if v and all(c in "0123456789abcdef" for c in v) else "unknown"


def branch():
    return (os.environ.get("RAILWAY_GIT_BRANCH") or "").strip()[:60] or None


def footer_text():
    """The quiet line for the foot of a page: 'Build 56e0cf1f9f9c (branch register-hooks-and-overlay)'."""
    b = branch()
    return "Build " + commit() + (f" (branch {b})" if b else "")


_ANNOUNCED = []


def announce(service=""):
    """Print one BUILD_INFO line per process (the deploy log then shows which commit started)."""
    if _ANNOUNCED:
        return
    _ANNOUNCED.append(1)
    print("BUILD_INFO commit=%s branch=%s service=%s" % (commit(), branch() or "-", service or os.environ.get("RAILWAY_SERVICE_NAME") or "-"), flush=True)
