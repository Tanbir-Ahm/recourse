"""
web_e2e_stack.py -- the back half of the new front end's browser tests (the repository recourse-web, folder e2e/): a throwaway PostgreSQL and the real API with a stub engine and a stand-in for Google's signing keys. Not a test itself (the suite does not run it).
    python web_e2e_stack.py --web-origin http://127.0.0.1:3100 --dir /tmp/some/folder
Prints ONE line of JSON, {"api": "<url>", "key_pem": "<path>", "client_id": "...", "proxy_secret": "..."}, when the API answers, then waits until its parent process ends or it is terminated, and cleans up.
Settings it gives the API: the search page's settings (no meaning search, so no outside call; the Act shelf on; a stand-in for the wider search), accounts open on placeholder legal text (staging-style), the front end's origin in CORS_ALLOW_ORIGINS (so the API's Origin check on cookie calls is exercised), FRONTEND_PROXY_SECRET (the visitor's address is vouched for by the front end's server).
"""
import argparse
import http.server
import json
import os
import signal
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import api_harness
import pg_harness

CLIENT_ID = "e2e-client.apps.googleusercontent.com"
PROXY_SECRET = "p" * 40


# A stand-in for the sci-search service (the search page's "Search wider"): the same /search call, a fixed reply. One passage whose case the Overruled Register knows, one it does not (with a link that is not a web link),
# one that is held back for review (the page must not show it).
SCI_REPLY = {"ok": True, "as_of": "2026-08-12", "index_commit": "stand-in", "seconds": 0.01, "results": [
    {"rank": 1, "doc": "d1", "case_name": "Mohan Lal v. State of Punjab", "date": "2018-07-24", "paragraph": 12, "link": "https://example.org/mohan-lal", "link_kind": "pdf", "text": "The standing-in passage about search and seizure under the NDPS Act.",
     "citations": {"scr": "[2018] 8 S.C.R. 1"}},
    {"rank": 2, "doc": "d2", "case_name": "Some Other Case v. State", "date": "2020-01-01", "paragraph": "4", "link": "javascript:alert(1)", "link_kind": "pdf", "text": "A second stand-in passage."},
    {"rank": 3, "doc": "d3", "case_name": "Held Back Case v. State", "name_to_review": True, "date": "2021-01-01", "text": "This passage must not be shown."},
]}


# The same stand-in as the wide index of 2026-10-24 answers: a High Court passage beside a Supreme Court one, with the date of each court. Sent when the question holds the word "gauhati".
SCI_REPLY_MIXED = {"ok": True, "as_of": "2026-10-16", "as_of_by_court": {"Gauhati High Court": "2026-10-14", "Supreme Court of India": "2026-10-16"}, "index_commit": "stand-in", "seconds": 0.01, "results": [
    {"rank": 1, "doc": 11, "case_name": "Sample Supreme Court Case v. State", "date": "2024-03-05", "paragraph": "7", "link": "https://example.org/sc-case", "link_kind": "court_site_pdf", "court": "Supreme Court of India",
     "text": "The standing-in passage of a Supreme Court judgment about bail conditions."},
    {"rank": 2, "doc": 2000000001, "case_name": "Dinathso Chaitom v. The State of AP", "date": "2020-12-17", "paragraph": "4", "link": "https://example.org/hc-case", "link_kind": "high_court_bucket_pdf", "court": "Gauhati High Court",
     "text": "The standing-in passage of a Gauhati High Court judgment about bail conditions."},
]}


class _SciStub(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        try:
            asked = json.loads(self.rfile.read(n).decode("utf-8")).get("question") or ""
        except Exception:  # noqa: BLE001
            asked = ""
        data = json.dumps(SCI_REPLY_MIXED if "gauhati" in asked.lower() else SCI_REPLY).encode("utf-8")
        self.send_response(200 if self.path == "/search" else 404)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def start_sci_stub():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SciStub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


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
    sci = start_sci_stub()
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    parent = os.getppid()
    try:
        pg.create_db("webe2e")
        srv = api_harness.start({"DATABASE_URL": pg.url("webe2e"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "GOOGLE_CLIENT_ID": CLIENT_ID, "API_COOKIE_SECURE": "off",
                                 "CORS_ALLOW_ORIGINS": a.web_origin, "FRONTEND_PROXY_SECRET": PROXY_SECRET, "API_RATE_LIMIT_PER_MINUTE": "0", "API_AUTH_RATE_PER_MINUTE": "0",
                                 "HARNESS_FAKE_GOOGLE_DIR": a.dir, "API_PURGE": "off", "ANON_TRIAL": "on", "IP_HASH_SECRET": "h" * 40, "ANON_DAILY_BUDGET_INR": "1000", "API_ANON_RATE_PER_MINUTE": "0",
                                 "SEARCH_MEANING": "off", "ACT_SHELF": "on", "SCI_SEARCH_URL": f"http://127.0.0.1:{sci.server_address[1]}", "API_SEARCH_RATE_PER_MINUTE": "0"})
        print(json.dumps({"api": srv.url, "key_pem": os.path.join(a.dir, "private.pem"), "client_id": CLIENT_ID, "proxy_secret": PROXY_SECRET}), flush=True)
        while not stop["now"] and os.getppid() == parent:
            time.sleep(0.5)
    finally:
        if srv:
            srv.stop()
        sci.shutdown()
        pg.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
