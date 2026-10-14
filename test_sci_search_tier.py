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
    {"rank": 1, "doc": 1, "case_name": "Raj Deo Sharma v. The State of Bihar", "date": "1999-05-03", "paragraph": "5", "link": "https://api.sci.gov.in/jonew/judis/1.pdf", "link_kind": "court_archive_pdf", "text": "Time limit held X.", "name_to_review": False, "citations": {"air": ["1999 AIR 2000"], "scr": ["1999 SCR (3) 1"]}},
    {"rank": 2, "doc": 2, "case_name": "Arnesh Kumar v. State of Bihar", "date": "2014-07-02", "paragraph": "9", "link": "https://x/2.pdf", "link_kind": "open_bucket_pdf", "text": "Arrest guidelines.", "name_to_review": False, "citations": {}},
    {"rank": 3, "doc": 3, "case_name": None, "date": None, "paragraph": "1", "link": "https://api.sci.gov.in/jonew/judis/3.pdf", "link_kind": "court_archive_pdf", "text": "unnamed", "name_to_review": True, "citations": {}},
    {"rank": 4, "doc": 1, "case_name": "Raj Deo Sharma v. The State of Bihar", "date": "1999-05-03", "paragraph": "7", "link": "https://api.sci.gov.in/jonew/judis/1.pdf", "link_kind": "court_archive_pdf", "text": "again", "name_to_review": False, "citations": {}},
]
RC = [{"rank": 1, "doc": 9, "case_name": "P. Ramachandra Rao v. State of Karnataka", "date": "2002-04-16", "paragraph": "29", "link": "https://x/9.pdf", "link_kind": "open_bucket_pdf",
       "text": "We hold that the criminal courts are not empowered to prescribe periods of limitation. The bar of limitation is not to be read into the Code. " * 12, "name_to_review": False, "citations": {}}]
WITH_RC = {"on": False}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        SEEN["calls"] += 1
        SEEN["token"] = self.headers.get("X-Search-Token")
        SEEN["body"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if MODE["kind"] == "slow":
            time.sleep(3)
        code, body = (503, {"ok": False}) if MODE["kind"] == "down" else (200, {"ok": True, "tier": "x", "index_commit": "abc", "as_of": "2026-07-13", "seconds": 1.0, "results": RC if SEEN["body"]["question"].startswith("P. Ramachandra") else (RES + RC[:1] if WITH_RC["on"] else RES)})
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
# the shadow line goes to stdout (what Railway's log shows), and a list-valued citation (crawl judgments) does not break the flags
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    T.attach("third question", dict(ANS), background=False)
out_lines = [l for l in buf.getvalue().splitlines() if l.startswith("SCI_SHADOW ")]
check(len(out_lines) == 1 and json.loads(out_lines[0][len("SCI_SHADOW "):])["results"][0]["flag"] == "register", "the shadow record is printed to stdout as one 'SCI_SHADOW {...}' line, with the register flag even when the citation is a list")
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

# values typed with quotation marks or spaces in a dashboard still work
os.environ["SCI_SEARCH_MODE"] = ' "FEED" '
check(T.mode() == "feed", "the mode ' \"FEED\" ' (quotes, spaces, capitals) is read as feed")
os.environ["SCI_SEARCH_MODE"] = "'shadow'"
check(T.mode() == "shadow", "the mode 'shadow' in single quotes is read as shadow")
os.environ["SCI_SEARCH_MODE"] = "off"

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

# feed mode (experiment): the passages go into the prompt, the register fact rides with an overruled case, the page lists what was read
import types
os.environ["SCI_SEARCH_MODE"] = "feed"
os.environ["SCI_SEARCH_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
MODE["kind"] = "ok"
T.reset()
fb = T.feed_block("a trial question")
check("REGISTER FACT" in fb and "Raj Deo Sharma" in fb and "NOT INDEPENDENTLY VERIFIED" in fb and "Arnesh Kumar" in fb, "feed: the block holds the passages, labelled, with a REGISTER FACT line for the overruled case")
check("unnamed" not in fb and fb.index("Arnesh Kumar") < fb.index("Raj Deo Sharma"), "feed: an unnamed judgment is left out and the flagged case comes after the others")
calls = SEEN["calls"]
T.feed_block("a trial question")
check(SEEN["calls"] == calls, "feed: the search runs once per question (the retry loop reuses it)")
os.environ["SCI_SEARCH_MODE"] = "show"
T.reset()
check(T.feed_block("another") == "", "feed_block is empty in every other mode")
os.environ["SCI_SEARCH_MODE"] = "feed"
sent = {}
class _Msgs:
    def create(self, **kw):
        sent["prompt"] = kw["messages"][0]["content"]
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Short answer. In Raj Deo Sharma v. The State of Bihar (1999) the Supreme Court said a time limit applied, but that case was overruled by P. Ramachandra Rao v. State of Karnataka (2002).")])
CA.client = types.SimpleNamespace(messages=_Msgs())
T.reset()
txt = CA.generate_grounded_response("My trial has been going on for 9 years", "[BNSS Section 346]\nTrial text.", matches=[])
check(txt and "WIDER SEARCH" in sent["prompt"] and "REGISTER FACT" in sent["prompt"] and "[BNSS Section 346]" in sent["prompt"], "feed: generate_grounded_response puts the wider passages into the prompt after the library text")
res_f = T.attach("My trial has been going on for 9 years", {"state": "single_match", "response_text": txt})
check(res_f.get("sci_fed") and [j["case_name"] for j in res_f["sci_related_judgments"]][:1] == ["Arnesh Kumar v. State of Bihar"] and any(j["register_note"] for j in res_f["sci_related_judgments"]), "feed: the result lists the passages the answer read, with the register note beside the overruled case")
check(any("Raj Deo Sharma" in n for n in CA._attach_register_notes(dict({"state": "single_match", "response_text": "The Supreme Court in Raj Deo Sharma v. The State of Bihar (1999) fixed time limits."})).get("register_notes", [])), "feed: if the answer still cites the overruled case flatly, the post-answer lock adds the note")

# changes 1-3: the correcting case, one passage per case, sentence-boundary cuts, inline labels
os.environ["SCI_SEARCH_MODE"] = "feed"
MODE["kind"] = "ok"
T.reset()
calls = SEEN["calls"]
fb = T.feed_block("a trial question")
check(SEEN["calls"] == calls + 2 and "P. Ramachandra Rao v. State of Karnataka" in fb, "feed: the case that overruled a flagged case is fetched by a second search when it is not in the results")
check(fb.count("[WIDER SEARCH") == 3 and fb.index("Arnesh Kumar") < fb.index("Ramachandra") < fb.index("Raj Deo Sharma v."), "feed: one passage per case (Raj Deo Sharma's second passage is dropped); flagged case last")
check(fb.count("again") == 0 and "Time limit held X." in fb, "feed: the best-ranked passage of the flagged case is the one kept")
rc_part = fb[fb.index("[WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: P. Ramachandra"):fb.index("[WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: Raj Deo")]
check(rc_part.rstrip().endswith("...") and "limitation. ..." in rc_part.replace("\n", " ") or rc_part.rstrip().endswith("."), "feed: a long passage is cut at the end of a sentence")
check("name the case that corrected it" not in fb and "name that case too" in fb and T.LABEL in fb, "feed: the instruction asks for the correcting case and for the label after every case name")
check(len(T._LOCAL.cases) == 3 and [c["case_name"] for c in T._LOCAL.cases][-1].startswith("Raj Deo Sharma"), "feed: the page list holds the same three cases")
WITH_RC["on"] = True
T.reset()
calls = SEEN["calls"]
T.feed_block("a trial question")
check(SEEN["calls"] == calls + 1 and sum(1 for c in T._LOCAL.cases if c["case_name"].startswith("P. Ramachandra")) == 1, "feed: when the correcting case is already among the results no second search is made")
WITH_RC["on"] = False
check(T._cut("One sentence here. Another sentence follows, and it is long.", 30) == "One sentence here. ..." and T._cut("short", 30) == "short", "_cut ends at a sentence boundary and leaves a short text alone")
cases3 = [{"case_name": "P. Ramachandra Rao v. State of Karnataka"}, {"case_name": "Raj Deo Sharma v. The State of Bihar"}, {"case_name": "Hemendra Rai v. State of Bihar"}]
txt3 = "In P. Ramachandra Rao v. State of Karnataka (2002) the Court said X. Raj Deo Sharma v. The State of Bihar (1999) was overruled. Hemendhra Rai v. State of Bihar was also said to apply. Raj Deo Sharma v. The State of Bihar again."
lab = T.label_fed_cases(txt3, cases3)
check(lab.count(T.LABEL) == 3, f"every fed case named in the answer gets the label once ({lab.count(T.LABEL)})")
check("(2002) " + T.LABEL in lab and "Karnataka (2002) (from" in lab, "the label goes after the year in brackets")
check("Hemendhra Rai v. State of Bihar " + T.LABEL in lab, "a typo in a party name (Hemendhra) is still found")
check(T.label_fed_cases(lab, cases3) == lab, "labelling twice adds nothing")
check(T.label_fed_cases("The Court did not name anyone.", cases3) == "The Court did not name anyone." and T.label_fed_cases(None, cases3) == "", "an answer that names none of them is left alone; None does not fail")
check(T.label_fed_cases("Under Raj Deo Sharma, time ran.", [{"case_name": "Raj Deo Sharma v. The State of Bihar"}]).count(T.LABEL) == 1, "a distinctive first party alone is enough")
check(T.label_fed_cases("The State v. Kumar held X.", [{"case_name": "State of Bihar v. Kumar"}]) == "The State v. Kumar held X.", "a generic first party alone is not enough (no wrong labels)")
it = T.label_fed_cases("In *Raj Deo Sharma v. The State of Bihar* (1999) the Court said X, and *P. Ramachandra Rao v. State of Karnataka* later corrected it.", cases3)
check("*Raj Deo Sharma v. The State of Bihar* (1999) " + T.LABEL in it and "*P. Ramachandra Rao v. State of Karnataka* " + T.LABEL in it and T.label_fed_cases(it, cases3) == it, "a case name in italics (answer style v3) gets the label after the closing mark and the year, once")
T.reset()
T.feed_block("a trial question")
res_l = T.attach("a trial question", {"state": "single_match", "response_text": "The Supreme Court in Raj Deo Sharma v. The State of Bihar (1999) fixed time limits; P. Ramachandra Rao v. State of Karnataka corrected it."})
check(res_l["response_text"].count(T.LABEL) == 2, "attach (feed) tags the wider-search cases in the finished answer text")
os.environ["SCI_SEARCH_MODE"] = "off"
T.reset()
check(T.feed_block("x") == "" and "sci_related_judgments" not in T.attach("x", {"state": "single_match"}), "with the mode off feed does nothing")

# --- staging 2026-10-14: label bugs found in the seven saved answers
LB = T.LABEL
def _one(txt, *names):
    return T.label_fed_cases(txt, [{"case_name": n} for n in names])
o = _one("In State Through Central Bureau of Investigation v. Hemendhra Reddy & Another (2023), the Court said X.", "State Through Central Bureau Of Investigation v. Hemendhra Reddy And Another")
check(o.count(LB) == 1 and "Another (2023) " + LB in o, f"the label goes after '& Another (2023)', not inside the name ({o!r})")
o = _one("per Dr. Subhash Kashinath Mahajan v. State of Maharashtra (2018) " + LB + ".", "Dr. Subhash Kashinath Mahajan v. The State Of Maharashtra And Anr.")
check(o.count(LB) == 1 and o.endswith(LB + "."), f"a label the model already wrote is not doubled, even when the name has 'The' ({o!r})")
o = _one("in Shaurya Sunil Kumar Singh v. CBI " + LB + " both say.", "Shaurya Sunil Kumar Singh v. Central Bureau Of Investigation")
check(o.count(LB) == 1 and "(from (from" not in o, f"no label inside another label ({o!r})")
o = _one("in Shaurya Sunil Kumar Singh v. CBI both say.", "Shaurya Sunil Kumar Singh v. Central Bureau Of Investigation")
check(o == "in Shaurya Sunil Kumar Singh v. CBI " + LB + " both say.", f"first party found, the second party (an abbreviation) taken with it ({o!r})")
o = _one("overruling Raj Deo Sharma v. State of Bihar (1999) (from a wider search, not independently verified; overruled by P. Ramachandra Rao v. State of Karnataka (2002)). Next.", "Raj Deo Sharma v. State Of Bihar", "Raj Deo Sharma v. State Of Bihar")
check(o.count("not independently verified") == 1, f"the model's own longer label ('...; overruled by ...') counts as the label ({o!r})")
o = _one("Sumit Mehta v State (NCT of Delhi) said x.", "Sumit Mehta v. State (Nct Of Delhi)")
check(o == "Sumit Mehta v State (NCT of Delhi) " + LB + " said x.", f"a bracket inside the name is part of the name ({o!r})")
o = _one("Rini Johar held it. Rini Johar again.", "Dr. Rini Johar And Another v. State Of M.P. And Ors.")
check(o.count(LB) == 1, "the answer may drop 'Dr.' from the name; only the first mention is labelled")
check(T._tidy_labels("A (from (from a wider search, not independently verified) a wider search, not independently verified) B " + LB + ". " + LB) == "A " + LB + " B " + LB + ".", "nested and doubled labels collapse")
check("Credit a principle to the case whose own words state it" in T.FEED_INSTRUCTION and "already running" in T.FEED_INSTRUCTION, "the feed instruction says: credit the case whose words state it; use a passage only for the question it decides")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
