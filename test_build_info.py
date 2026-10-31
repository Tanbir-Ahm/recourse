"""test_build_info.py -- build_info.py: the commit stamp. Offline. Run: python -X utf8 test_build_info.py"""
import contextlib
import io
import json
import os
import sys

import build_info as B

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


for k in ("RAILWAY_GIT_COMMIT_SHA", "SOURCE_COMMIT", "RAILWAY_GIT_BRANCH", "RAILWAY_SERVICE_NAME"):
    os.environ.pop(k, None)
check(B.commit() == "unknown" and B.footer_text() == "Build unknown", "no Railway variable: the stamp says 'unknown', it does not guess")
os.environ["RAILWAY_GIT_COMMIT_SHA"] = "56e0cf1f9f9c3d8d5b0e1a2b3c4d5e6f70819293"
check(B.commit() == "56e0cf1f9f9c", "the first twelve characters of Railway's commit")
os.environ["RAILWAY_GIT_BRANCH"] = "register-hooks-and-overlay"
check(B.footer_text() == "Build 56e0cf1f9f9c (branch register-hooks-and-overlay)", B.footer_text())
os.environ["RAILWAY_GIT_COMMIT_SHA"] = "not a hash; <script>"
check(B.commit() == "unknown", "a value that is not a hex hash is never shown (nothing from the environment reaches a page unchecked)")
os.environ["RAILWAY_GIT_COMMIT_SHA"] = "56E0CF1F9F9C3D8D"
check(B.commit() == "56e0cf1f9f9c", "upper case is folded")

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    B.announce("test-service")
    B.announce("test-service")
check(buf.getvalue().count("BUILD_INFO") == 1 and "commit=56e0cf1f9f9c" in buf.getvalue() and "service=test-service" in buf.getvalue(), "one BUILD_INFO line per process")

import cost_log
cost_log.begin("a question") if hasattr(cost_log, "begin") else None
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cost_log.finish(style="v3", audience="layman")
line = [l for l in buf.getvalue().splitlines() if l.startswith("COST_QUESTION")]
check(line and json.loads(line[0].split(" ", 1)[1]).get("commit") == "56e0cf1f9f9c", "every COST_QUESTION line carries the commit")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
