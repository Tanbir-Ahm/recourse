"""
test_sci_search_tier.py -- the wider-pool search tier on the website side (sci_search_tier.py + its call in chat_assistant.answer_question + the page box).
Fully offline and free: a local stand-in for the sci-search service, no model, no network beyond localhost. Run: python -X utf8 test_sci_search_tier.py
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


SEEN = {"calls": 0, "token": None, "body": None}
MODE = {"kind": "ok"}
RES = [
    {"rank": 1, "doc": 1, "case_name": "Raj Deo Sharma v. The State of Bihar", "date": "1999-05-03", "paragraph": "5", "link": "https://api.sci.gov.in/jonew/judis/1.pdf", "link_kind": "court_archive_pdf", "text": "Time limit held X.", "name_to_review": False, "citations": {}},
    {"rank": 2, "doc": 2, "case_name": "Arnesh Kumar v. State of Bihar", "date": "2014-07-02", "paragraph": "9", "link": "https://x/2.pdf", "link_kind": "open_bucket_pdf", "text": "Arrest guidelines.", "name_to_review": False, "citations": {}},
    {"rank": 3, "doc": 3, "case_name": None, "date": None, "paragraph": "1", "link": "https://api.sci.gov.in/jonew/judis/3.pdf", "link_kind": "court_archive_pdf", "text": "unnamed", "name_to_review": True, "citations": {}},
    {"rank": 4, "doc": 1, "case_name": "Raj Deo Sharma v. The State of Bihar", "date": "1999-05-03", "paragraph": "7", "link": "https://api.sci.gov.in/jonew/judis/1.pdf", "link_kind": "court_archive_pdf", "text": "again", "name_to_review": False, "citations": {}},
]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        SEEN["calls"] += 1
        SEEN["token"] = self.headers.get("X-Search-Token")
        SEEN["body"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if MODE["kind"] == "slow":
            time.sleep(3)
        code, body = (503, {"ok": False}) if MODE["kind"] == "down" else (200, {"ok": True, "tier": "x", "index_commit": "abc", "as_of": "2026-07-13", "seconds": 1.0, "results": RES})
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["SCI_SEARCH_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ["SCI_SEARCH_TOKEN"] = "sekrit"
ANS = {"state": "single_match", "response_text": "An answer."}

# off (the default): nothing happens, nothing is called
os.environ.pop("SCI_SEARCH_MODE", None)
r = T.attach("q", dict(ANS))
check(r == ANS and SEEN["calls"] == 0, "off is the default: the answer is untouched and the service is not called")
os.environ["SCI_SEARCH_MODE"] = "banana"
check(T.mode() == "off", "an unknown mode means off")

# shadow: the answer is untouched, the call happens in the background, the log holds a hash and not the question
os.environ["SCI_SEARCH_MODE"] = "shadow"
logfile = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"shadow_{os.getpid()}.jsonl")
os.environ["SCI_SHADOW_LOG_FILE"] = logfile
MODE["kind"] = "slow"
t0 = time.time()
r = T.attach("Can police arrest me for cheating?", dict(ANS))
check(r == ANS and time.time() - t0 < 1.0, "shadow does not change the answer and does not make the user wait for a slow service")
time.sleep(4.5)
check(SEEN["calls"] == 1 and SEEN["token"] == "sekrit" and SEEN["body"]["question"] == "Can police arrest me for cheating?", "the service was called with the token and the question")
rec = json.loads(open(logfile, encoding="utf-8").readline())
check("question" not in rec and len(rec["q_hash"]) == 16, "the shadow log has a hash of the question, not the text, by default")
check(len(rec["results"]) == 4 and rec["results"][0]["flag"] == "register" and "overruled" in (rec["results"][0]["note"] or "").lower(), f"and a register flag on Raj Deo Sharma (overruled): {rec['results'][0]['flag']}")
check(rec["flagged"] >= 1 and rec["results"][2]["flag"] == "none", "unnamed judgments are not looked up")
os.environ["SCI_SHADOW_LOG_QUESTIONS"] = "1"
MODE["kind"] = "ok"
T.attach("second?", dict(ANS), background=False)
rec2 = [json.loads(l) for l in open(logfile, encoding="utf-8")][-1]
check(rec2.get("question") == "second?", "with SCI_SHADOW_LOG_QUESTIONS=1 the text is logged")
os.environ.pop("SCI_SHADOW_LOG_QUESTIONS")

# show: passages attached, unnamed and repeated judgments left out, register note carried
os.environ["SCI_SEARCH_MODE"] = "show"
r = T.attach("q", dict(ANS))
sh = r.get("sci_related_judgments") or []
check([j["case_name"] for j in sh] == ["Raj Deo Sharma v. The State of Bihar", "Arnesh Kumar v. State of Bihar"], "show: named judgments only, each once")
check(sh and sh[0]["register_note"] and sh[1]["register_note"] is None and sh[0]["link"].startswith("https://api.sci.gov.in/"), "the register note sits beside the overruled case, links are kept")
check(r["sci_as_of"] == "2026-07-13" and r["response_text"] == "An answer.", "the as-of date is attached and the answer text is untouched")
check("sci_related_judgments" not in T.attach("q", {"state": "no_match"}), "a non-answer state gets nothing")

# fail-open
MODE["kind"] = "down"
check(T.attach("q", dict(ANS)) == ANS, "a service that answers 503 leaves the answer as it was")
MODE["kind"] = "slow"
os.environ["SCI_SEARCH_TIMEOUT"] = "1"
t0 = time.time()
check(T.attach("q", dict(ANS)) == ANS and time.time() - t0 < 2.5, "show mode gives up after the timeout and the answer goes out")
os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:1"
check(T.attach("q", dict(ANS)) == ANS, "a service that cannot be reached leaves the answer as it was")
os.environ.pop("SCI_SEARCH_URL")
check(T.attach("q", dict(ANS)) == ANS, "no address set: nothing happens")
check(T.attach("q", "not a dict") == "not a dict", "bad input does not raise")

# the call in answer_question
import chat_assistant as CA
os.environ["SCI_SEARCH_MODE"] = "show"
os.environ["SCI_SEARCH_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
MODE["kind"] = "ok"
os.environ["SCI_SEARCH_TIMEOUT"] = "6"
CA._answer_question_core = lambda q, inline_domains=frozenset(): {"state": "single_match", "response_text": "Core answer."}
out = CA.answer_question("a question")
check(out.get("sci_related_judgments") and out["response_text"] == "Core answer.", "answer_question carries the tier in show mode")
os.environ["SCI_SEARCH_MODE"] = "off"
check("sci_related_judgments" not in CA.answer_question("a question"), "and nothing with the mode off")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
