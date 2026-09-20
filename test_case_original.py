"""
test_case_original.py -- delivering the ORIGINAL Supreme Court Reports page-image PDF (from the open
'Indian Supreme Court Judgments' S3 bucket) instead of our re-typed text. Written BEFORE the code.

What must hold: the right file is found from the printed citation; it is VERIFIED against the case
name before it is sent (a wrong-case file is the worst failure); every failure falls back to the text
PDF instead of leaving the person with nothing; the source is credited; memory stays bounded.
Temp DBs, fake network, tiny in-memory PDFs. Run: python -X utf8 test_case_original.py
"""
import os
import sys
import tempfile

import fitz

import case_lookup
import whatsapp_bot
import whatsapp_store

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


_TMP = tempfile.mkdtemp()
whatsapp_store.DB_PATH = os.path.join(_TMP, "wa.db")
_N = [0]


def fresh_db():
    _N[0] += 1
    case_lookup.INDEX_PATH = os.path.join(_TMP, f"index{_N[0]}.db")
    case_lookup.STATE_PATH = os.path.join(_TMP, f"state{_N[0]}.db")
    case_lookup.SEARCH_DAILY_LIMIT = 40
    case_lookup.FETCH_DAILY_LIMIT = 15


def seed(cases):
    conn = case_lookup._index_conn()
    with conn:
        for cid, title, citation in cases:
            conn.execute("INSERT INTO cases (case_id, title, court, decision_date, citation, source_url, n_chunks) "
                         "VALUES (?,?,?,?,?,?,?)", (cid, title, "Supreme Court of India", "2017-08-16", citation, None, 46))
            conn.execute("INSERT INTO cases_fts (case_id, title) VALUES (?, ?)", (cid, title))
    conn.close()


def make_pdf(first_page_text, pages=3, pad=0):
    d = fitz.open()
    for i in range(pages):
        p = d.new_page()
        p.insert_text((72, 100), first_page_text if i == 0 else f"page {i + 1} of the report", fontsize=11)
    b = d.tobytes()
    return b + (b"\0" * pad)


try:
    import case_original as co
except ImportError:
    co = None
check(co is not None, "case_original module exists")
if co is None:
    print("\nFAILED (module missing)")
    sys.exit(1)

# ---------------------------------------------------------------- 1. citation -> (year, volume, start page)
check(co.parse_scr_citation("[2017] 8 S.C.R. 785") == (2017, 8, 785), "standard SCR citation parsed")
check(co.parse_scr_citation("[2006] SUPP. 8 S.C.R. 1021") == (2006, 8, 1021), "'SUPP.' volume citation parsed")
check(co.parse_scr_citation("[1996] Suppl. 1 SCR 163") == (1996, 1, 163), "loosely-written citation parsed")
check(co.parse_scr_citation("AIR 1978 SC 597") is None and co.parse_scr_citation("") is None and co.parse_scr_citation(None) is None,
      "a non-SCR / empty / None citation gives None, never a crash")

# ---------------------------------------------------------------- 2. the per-year file list
KEYS_2017 = ["data/pdf/year=2017/english/2017_8_785_851_EN.pdf", "data/pdf/year=2017/english/2017_8_1_20_EN.pdf",
             "data/pdf/year=2017/english/2017_9_785_790_EN.pdf", "data/pdf/year=2017/english/notes.txt"]
calls = []


def fake_list(prefix, token=None):
    calls.append((prefix, token))
    if token is None:
        return KEYS_2017[:2], "TOKEN2"          # page 1 of a paginated listing
    return KEYS_2017[2:], None                  # page 2


co._list_page = fake_list
co._YEAR_CACHE.clear()
cands = co.candidate_keys("[2017] 8 S.C.R. 785")
check(cands and cands[0].endswith("2017_8_785_851_EN.pdf"), f"the file with the matching volume + start page comes first -- got {cands}")
check(any(k.endswith("2017_9_785_790_EN.pdf") for k in cands) and len(cands) == 2,
      "a same-start-page file in ANOTHER volume is offered second (for Supp. volumes) and non-PDF keys are ignored")
n1 = len(calls)
co.candidate_keys("[2017] 8 S.C.R. 1")
check(len(calls) == n1 and n1 == 2, f"the year's listing (paginated, {n1} requests) is fetched once, then cached -- {len(calls)} total after a 2nd lookup")
check(co.candidate_keys("[2017] 8 S.C.R. 99999") == [], "a start page with no file gives no candidates")

# ---------------------------------------------------------------- 3. verifying the file is the right case
good = make_pdf("[2017] 8 S.C.R. 785\nRAKESH KUMAR PAUL\nv.\nSTATE OF ASSAM\n(Special Leave to Appeal (Cr!.) No. 2009 of 2017)")
check(co.verify_matches_case(good, "RAKESH KUMAR PAUL versus STATE OF ASSAM"), "the right file passes verification")
check(not co.verify_matches_case(good, "MANEKA GANDHI versus UNION OF INDIA"), "a DIFFERENT case's file fails verification")
noisy = make_pdf("RAKESH KUMAR PAUL\nv.\nSTATE OF ASSAM")
check(co.verify_matches_case(noisy, "RAKESH KUMAR PAULL versus STATE OF ASAM"), "a title with a small scan-style typo still verifies")
check(not co.verify_matches_case(good, "STATE versus UNION"), "a title with no distinctive words can never pass (refuse rather than guess)")
check(not co.verify_matches_case(b"not a pdf at all", "RAKESH KUMAR PAUL versus STATE OF ASSAM"), "a corrupt file fails verification, no crash")

# ---------------------------------------------------------------- 4. get_original: every outcome, never raises
CASE = {"case_id": "2017_INSC_754", "title": "RAKESH KUMAR PAUL versus STATE OF ASSAM", "citation": "[2017] 8 S.C.R. 785"}
co._YEAR_CACHE.clear()
co._list_page = lambda prefix, token=None: (KEYS_2017[:3], None)
co._download = lambda key, max_bytes: good
r = co.get_original(CASE)
check(r["status"] == "ok" and r["bytes"] == good and r["key"].endswith("2017_8_785_851_EN.pdf"), f"ok: right file found, verified, returned -- {r['status']}")

co._download = lambda key, max_bytes: make_pdf("MANEKA GANDHI\nv.\nUNION OF INDIA")
check(co.get_original(CASE)["status"] == "mismatch", "a file that is a different case is reported as mismatch (never returned)")

def too_big(key, max_bytes): raise co.TooLarge(key)
co._download = too_big
check(co.get_original(CASE)["status"] == "too_large", "a file over the size cap is reported too_large")

def boom(key, max_bytes): raise RuntimeError("s3 down")
co._download = boom
check(co.get_original(CASE)["status"] == "unreachable", "a network failure is reported unreachable, not raised")

co._download = lambda key, max_bytes: good
check(co.get_original({**CASE, "citation": "AIR 1978 SC 597"})["status"] == "not_found", "no usable SCR citation -> not_found")
co._YEAR_CACHE.clear()
co._list_page = lambda prefix, token=None: ([], None)
check(co.get_original(CASE)["status"] == "not_found", "no file for that page in the bucket -> not_found")
def list_boom(prefix, token=None): raise RuntimeError("list failed")
co._YEAR_CACHE.clear()
co._list_page = list_boom
check(co.get_original(CASE)["status"] == "unreachable", "a failing bucket listing -> unreachable, not raised")

# ---------------------------------------------------------------- 5. through the WhatsApp bot
sent, docs = [], []
whatsapp_bot.send_whatsapp_message = lambda ph, t: sent.append(t)
whatsapp_bot.send_whatsapp_document = lambda ph, url, fn, caption=None: (docs.append((url, fn)) or True)
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://example.test"


class FakeCon:
    def __init__(self, rows): self.rows, self.calls = rows, 0
    def execute(self, *a, **k): self.calls += 1; return self
    def fetchall(self): return self.rows


TEXT_ROWS = [(0, "Judgment text part. " * 80, "body", 1)]


def events(phone):
    c = case_lookup._state_conn()
    try:
        return c.execute("SELECT event, detail FROM case_events WHERE phone_number=? ORDER BY id", (phone,)).fetchall()
    finally:
        c.close()


def say(phone, text):
    sent.clear(); docs.clear()
    return whatsapp_bot.handle_incoming_message(phone, text)


fresh_db()
seed([("2017_INSC_754", "RAKESH KUMAR PAUL versus STATE OF ASSAM", "[2017] 8 S.C.R. 785")])
fc = FakeCon(TEXT_ROWS)
case_lookup._duckdb = lambda: fc
co._YEAR_CACHE.clear()
co._list_page = lambda prefix, token=None: (KEYS_2017[:1], None)
co._download = lambda key, max_bytes: good
before_pdfs = len(whatsapp_bot._PENDING_PDFS)
say("O1", "CASE: Rakesh Kumar Paul v State of Assam")
check(len(docs) == 1 and docs[0][1].lower().endswith(".pdf") and len(whatsapp_bot._PENDING_PDFS) == before_pdfs + 1,
      "a default PDF request delivers the ORIGINAL pdf")
served = max(whatsapp_bot._PENDING_PDFS.values(), key=lambda e: e[1])[0]
check(served == good, "the bytes handed to WhatsApp are exactly the original file's bytes (not re-typed, not altered)")
check(fc.calls == 0, "the slow text fetch is skipped entirely when the original is found")
check(events("O1") == [("exact_auto_send", "pdf"), ("doc_delivered", "pdf_original")], f"logged as an original delivery -- got {events('O1')}")
check("CC-BY" in " ".join(sent) and "Dattam Labs" in " ".join(sent), "the message credits the source and licence (CC-BY-4.0, Dattam Labs)")
check("not been checked" in " ".join(sent).lower() or "not independently verified" in " ".join(sent).lower(), "the message still says it is unverified")

say("O2", "CASE: Rakesh Kumar Paul v State of Assam word")
check(len(docs) == 1 and docs[0][1].lower().endswith(".docx") and fc.calls == 1, "a Word request still builds our text Word file (original PDFs can't be edited)")

def newest_pdf():
    return max(whatsapp_bot._PENDING_PDFS.values(), key=lambda e: e[1])[0]


say("O3", "CASE: Rakesh Kumar Paul v State of Assam text")
check(len(docs) == 1 and docs[0][1].lower().endswith(".pdf") and events("O3")[-1][1] == "pdf"
      and newest_pdf()[:4] == b"%PDF" and newest_pdf() != good,
      "a 'text' request builds OUR re-typed text PDF instead (not the original file)")

wrong = make_pdf("MANEKA GANDHI\nv.\nUNION OF INDIA")
co._download = lambda key, max_bytes: wrong
say("O4", "CASE: Rakesh Kumar Paul v State of Assam")
ev = [e[0] for e in events("O4")]
check(len(docs) == 1 and newest_pdf() != wrong and newest_pdf() != good and "original_unavailable" in ev and ev[-1] == "doc_delivered",
      f"a wrong-case original is refused and the person still gets the text PDF; the reason is logged -- got {events('O4')}")
check(dict(events("O4")).get("original_unavailable") == "mismatch", "the logged reason is 'mismatch'")

co._download = boom
say("O5", "CASE: Rakesh Kumar Paul v State of Assam")
check(len(docs) == 1 and newest_pdf() != good and dict(events("O5")).get("original_unavailable") == "unreachable",
      "if the bucket is unreachable the person still gets the text PDF, and the reason is logged")

# ---------------------------------------------------------------- 6. bounded memory for big files
whatsapp_bot._PENDING_PDFS.clear()
big = b"x" * (40 * 1024 * 1024)
for i in range(6):
    whatsapp_bot._store_pending_pdf(big)
total = sum(len(v[0]) for v in whatsapp_bot._PENDING_PDFS.values())
check(total <= whatsapp_bot._PENDING_MAX_TOTAL_BYTES + len(big) and len(whatsapp_bot._PENDING_PDFS) < 6,
      f"the temporary file store also caps TOTAL bytes (kept {len(whatsapp_bot._PENDING_PDFS)} of 6 big files)")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
