"""
test_case_events.py -- the CASE-command usage log (case_lookup.log_event / event_summary,
wired into whatsapp_bot). Written BEFORE the code (methodology: tests first).

Contract being tested: every CASE interaction leaves EXACTLY ONE row saying what happened;
logging can never break or slow the person's real answer (fail-open); the report never
shows phone numbers. Temp databases + mocked network only.
Run: python -X utf8 test_case_events.py
"""
import os
import sys
import tempfile

import case_lookup
import whatsapp_bot
import whatsapp_store

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


_TMP = tempfile.mkdtemp()
_N = [0]
whatsapp_store.DB_PATH = os.path.join(_TMP, "wa_conversations.db")  # never touch the real conversation log


def fresh_db():
    _N[0] += 1
    case_lookup.INDEX_PATH = os.path.join(_TMP, f"index{_N[0]}.db")
    case_lookup.STATE_PATH = os.path.join(_TMP, f"state{_N[0]}.db")
    case_lookup.SEARCH_DAILY_LIMIT = 40
    case_lookup.FETCH_DAILY_LIMIT = 15


def seed(cases):
    conn = case_lookup._index_conn()
    with conn:
        for cid, title, n in cases:
            conn.execute("INSERT INTO cases (case_id, title, court, decision_date, citation, source_url, n_chunks) "
                         "VALUES (?,?,?,?,?,?,?)", (cid, title, "Supreme Court of India", "2014-07-02", "[2014] 8 S.C.R. 128", None, n))
            conn.execute("INSERT INTO cases_fts (case_id, title) VALUES (?, ?)", (cid, title))
    conn.close()


class FakeCon:
    def __init__(self, rows=None, exc=None):
        self.rows, self.exc, self.calls = rows, exc, 0
    def execute(self, *a, **k):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self
    def fetchall(self):
        return self.rows


GOOD = [(i, f"part {i} " * 60, "body", 2) for i in range(2)]
sent, docs = [], []
whatsapp_bot.send_whatsapp_message = lambda ph, t: sent.append(t)
whatsapp_bot.send_whatsapp_document = lambda ph, url, fn, caption=None: (docs.append((url, fn)) or True)
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://example.test"
# These suites test the TEXT pipeline in isolation; the original-PDF path (a plain PDF request tries the
# original first) is covered, with a fake network, by test_case_original.py.
whatsapp_bot._try_original_pdf = lambda *a, **k: None


def events_of(phone=None):
    """[(event, case_id, detail, cached)] for the test phone, oldest first -- read raw, not via the report."""
    conn = case_lookup._state_conn()
    try:
        q = "SELECT event, case_id, detail, cached FROM case_events"
        args = ()
        if phone:
            q += " WHERE phone_number = ?"
            args = (phone,)
        return conn.execute(q + " ORDER BY id", args).fetchall()
    finally:
        conn.close()


def names(phone=None):
    return [e[0] for e in events_of(phone)]


def say(phone, text):
    sent.clear(); docs.clear()
    return whatsapp_bot.handle_incoming_message(phone, text)


# ---------------------------------------------------------------- the logger itself
fresh_db()
check(hasattr(case_lookup, "log_event") and hasattr(case_lookup, "event_summary"),
      "case_lookup exposes log_event() and event_summary()")
case_lookup.log_event("111", "doc_delivered", case_id="c1", query="x" * 500, detail="pdf", elapsed_ms=1234, cached=False)
row = events_of("111")[0]
check(row[0] == "doc_delivered" and row[1] == "c1" and row[2] == "pdf" and row[3] == 0, "a logged event stores its event name, case, detail and cached flag")
conn = case_lookup._state_conn()
qlen = conn.execute("SELECT length(query) FROM case_events").fetchone()[0]
conn.close()
check(qlen <= 80, "the typed query is truncated to 80 characters (privacy: a long message can't be stored whole)")

orig = case_lookup._state_conn
def broken(*a, **k): raise RuntimeError("disk full")
case_lookup._state_conn = broken
try:
    case_lookup.log_event("111", "doc_delivered")
    check(True, "FAIL-OPEN: log_event swallows a database failure instead of raising")
except Exception as exc:
    check(False, f"FAIL-OPEN: log_event raised {exc!r}")
case_lookup._state_conn = orig

# ---------------------------------------------------------------- every path through the bot: exactly one right row
fresh_db()
seed([("c1", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", 40), ("c3", "STATE OF BIHAR versus RAMESH", 12),
      ("c5", "LATA SINGH versus STATE OF U.P. AND ANR.", 12), ("c7", "SINGH versus STATE ONE", 5),
      ("c8", "SINGH versus STATE TWO", 6)])
case_lookup._duckdb = lambda: FakeCon(GOOD)

say("A", "CASE:")
check(names("A") == ["usage_help"], f"bare 'CASE:' logs exactly one usage_help -- got {names('A')}")

say("B", "CASE: Zzzz Qqqq Wwww")
check(names("B") == ["search_no_match"], f"an unmatched name logs exactly one search_no_match -- got {names('B')}")

say("C", "CASE: Arnesh Kumar v State of Bihar")
check(names("C") == ["exact_auto_send", "doc_delivered"], f"a single exact match logs exact_auto_send then doc_delivered -- got {names('C')}")
ev = events_of("C")
check(ev[1][1] == "c1" and ev[1][2] == "pdf" and ev[1][3] == 0, "the delivery row carries the case id, format 'pdf' and cached=False (first, live fetch)")

say("D", "CASE: Arnesh Kumar v State of Bihar")
check(names("D") == ["exact_auto_send", "doc_delivered"] and events_of("D")[1][3] == 1,
      "the same case again is logged as delivered from CACHE (cached=True)")

say("E", "CASE: Arnesh Kumar v State of Bihar word")
check(events_of("E")[-1][0] == "doc_delivered" and events_of("E")[-1][2] == "docx", "a Word request logs format 'docx'")

say("F", "CASE: Singh")
check(names("F") == ["menu_exact"], f"several exact matches log one menu_exact -- got {names('F')}")
say("F", "2")
check(names("F") == ["menu_exact", "pick_ok", "doc_delivered"], f"picking a number logs pick_ok then doc_delivered -- got {names('F')}")

say("G", "CASE: Lata Singh v State of Bihar")
check(names("G") == ["menu_fuzzy"], f"a fuzzy match logs menu_fuzzy (never an auto-send) -- got {names('G')}")
say("G", "9")
check(names("G") == ["menu_fuzzy", "pick_invalid"], f"an out-of-range pick logs pick_invalid -- got {names('G')}")

# rate limits
fresh_db()
seed([("c1", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", 40)])
case_lookup._duckdb = lambda: FakeCon(GOOD)
case_lookup.SEARCH_DAILY_LIMIT = 1
say("H", "CASE: Arnesh Kumar"); say("H", "CASE: Arnesh Kumar")
check(names("H")[-1] == "search_rate_limited", f"a search over the daily cap logs search_rate_limited -- got {names('H')}")
case_lookup.SEARCH_DAILY_LIMIT = 40
case_lookup.FETCH_DAILY_LIMIT = 0
say("I", "CASE: Arnesh Kumar")
check(names("I") == ["exact_auto_send", "fetch_rate_limited"], f"a download over the cap logs fetch_rate_limited -- got {names('I')}")
case_lookup.FETCH_DAILY_LIMIT = 15

# failures -- each on a CLEAN database, so an earlier cached copy of the case can't mask the failure
def clean_case_db():
    fresh_db()
    seed([("c1", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", 40)])

clean_case_db()
case_lookup._duckdb = lambda: FakeCon(exc=RuntimeError("network down"))
say("J", "CASE: Arnesh Kumar")
check(names("J") == ["exact_auto_send", "fetch_unavailable"], f"an unreachable source logs fetch_unavailable -- got {names('J')}")
clean_case_db()
case_lookup._duckdb = lambda: FakeCon([])
say("K", "CASE: Arnesh Kumar")
check(names("K") == ["exact_auto_send", "fetch_not_found"], f"a case with no text logs fetch_not_found -- got {names('K')}")
clean_case_db()
case_lookup._duckdb = lambda: FakeCon([(0, "tiny", "body", 1)])
say("L", "CASE: Arnesh Kumar")
check(names("L") == ["exact_auto_send", "doc_too_short"], f"a near-empty record logs doc_too_short -- got {names('L')}")

clean_case_db()
case_lookup._duckdb = lambda: FakeCon(GOOD)
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = None
say("M", "CASE: Arnesh Kumar")
check(names("M") == ["exact_auto_send", "doc_text_fallback"], f"a file that can't be delivered logs doc_text_fallback -- got {names('M')}")
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://example.test"

# ---------------------------------------------------------------- the "did you mean CASE:?" hint
before = len(events_of())
out = say("N", "CASE Gayatri Balasamy v ISG Novasoft Technologies")
check(names("N") == ["case_hint"] and out and "CASE: Gayatri Balasamy v ISG Novasoft Technologies" in out[0],
      "'CASE <name> v <name>' with no colon gets a gentle 'did you mean CASE: ...' reply and logs case_hint")
ai_calls = []
whatsapp_bot.chat_assistant.answer_question = lambda *a, **k: (ai_calls.append(1) or {"state": "no_match", "response_text": "ok"})
for q in ["case of bail after 14 days arrest?", "case law on arrest v police powers?", "in this case what should I do"]:
    say("O", q)
check(not any(e == "case_hint" for e in names("O")), "ordinary questions that merely contain the word 'case' do NOT trigger the hint")

# ---------------------------------------------------------------- fail-open through the real bot
fresh_db()
seed([("c1", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", 40)])
case_lookup._duckdb = lambda: FakeCon(GOOD)
real_log = case_lookup._state_conn
# break ONLY the events table writes: make log_event's own connection fail
def boom(*a, **k): raise RuntimeError("logger down")
_orig_log = case_lookup.log_event
case_lookup.log_event = boom
try:
    say("P", "CASE: Arnesh Kumar v State of Bihar")
    check(len(docs) == 1, "FAIL-OPEN through the bot: even if the logger itself blows up, the person still gets their judgment")
except Exception as exc:
    check(False, f"FAIL-OPEN through the bot: the logger crashed the request: {exc!r}")
case_lookup.log_event = _orig_log

# ---------------------------------------------------------------- the report
fresh_db()
seed([("c1", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", 40)])
case_lookup._duckdb = lambda: FakeCon(GOOD)
say("+919999900001", "CASE: Arnesh Kumar v State of Bihar")
say("+919999900002", "CASE: Arnesh Kumar v State of Bihar")
say("+919999900002", "CASE: Zzzz Qqqq Wwww")
s = case_lookup.event_summary(days=7)
check(s["total"] == 5 and s["users"] == 2, f"summary counts total events and DISTINCT users -- got total={s.get('total')} users={s.get('users')}")
check(s["by_event"].get("doc_delivered") == 2 and s["by_event"].get("search_no_match") == 1, "summary counts each outcome")
check(s["deliveries"] == 2 and s["cache_hits"] == 1, f"summary counts deliveries and how many came from cache -- got {s.get('deliveries')}/{s.get('cache_hits')}")
check("+919999900001" not in repr(s) and "9999900002" not in repr(s), "PRIVACY: the summary never contains a phone number")
check(case_lookup.event_summary(days=0)["total"] == 0, "a window that excludes everything reports zero, not an error")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
