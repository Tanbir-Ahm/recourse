"""
web_e2e_stack.py -- the back half of the new front end's browser tests (the repository recourse-web, folder e2e/): a throwaway PostgreSQL and the real API with a stub engine and a stand-in for Google's signing keys. Not a test itself (the suite does not run it).
    python web_e2e_stack.py --web-origin http://127.0.0.1:3100 --dir /tmp/some/folder
Prints ONE line of JSON, {"api": "<url>", "key_pem": "<path>", "client_id": "...", "proxy_secret": "..."}, when the API answers, then waits until its parent process ends or it is terminated, and cleans up.
Settings it gives the API: accounts open on placeholder legal text (staging-style), the front end's origin in CORS_ALLOW_ORIGINS (so the API's Origin check on cookie calls is exercised), FRONTEND_PROXY_SECRET (the visitor's address is vouched for by the front end's server).
"""
import argparse
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import api_harness
import pg_harness

CLIENT_ID = "e2e-client.apps.googleusercontent.com"
PROXY_SECRET = "p" * 40


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--web-origin", required=True)
    ap.add_argument("--dir", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.dir, exist_ok=True)
    pg = pg_harness.start()
    if pg is None:
        print(json.dumps({"error": "no PostgreSQL here"}), flush=True)
        return 2
    srv = None
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    parent = os.getppid()
    try:
        pg.create_db("webe2e")
        srv = api_harness.start({"DATABASE_URL": pg.url("webe2e"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "GOOGLE_CLIENT_ID": CLIENT_ID, "API_COOKIE_SECURE": "off",
                                 "CORS_ALLOW_ORIGINS": a.web_origin, "FRONTEND_PROXY_SECRET": PROXY_SECRET, "API_RATE_LIMIT_PER_MINUTE": "0", "API_AUTH_RATE_PER_MINUTE": "0",
                                 "HARNESS_FAKE_GOOGLE_DIR": a.dir, "API_PURGE": "off"})
        print(json.dumps({"api": srv.url, "key_pem": os.path.join(a.dir, "private.pem"), "client_id": CLIENT_ID, "proxy_secret": PROXY_SECRET}), flush=True)
        while not stop["now"] and os.getppid() == parent:
            time.sleep(0.5)
    finally:
        if srv:
            srv.stop()
        pg.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
