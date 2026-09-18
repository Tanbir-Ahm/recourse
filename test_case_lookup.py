"""
test_case_lookup.py -- offline regression suite for the WhatsApp case-lookup
feature (case_lookup.py, case_document.py, and the CASE command in
whatsapp_bot.py). Temp database, mocked network: no API cost, no internet.
Same check()/FAILURES convention as the repo's other test_*.py files.
Run: python test_case_lookup.py
"""
import io
import os
import sys
import tempfile
import zipfile

import case_document
import case_lookup
import whatsapp_bot

FAILURES = []


def check(condition, description):
    print(f"[{'PASS' if condition else 'FAIL'}] {description}")
    if not condition:
        FAILURES.append(description)


_TMP = tempfile.mkdtemp()
_N = [0]


def fresh_db():
    _N[0] += 1
    case_lookup.INDEX_PATH = os.path.join(_TMP, f"index{_N[0]}.db")
    case_lookup.STATE_PATH = os.path.join(_TMP, f"state{_N[0]}.db")


def seed(cases):
    conn = case_lookup._index_conn()
    with conn:
        for cid, title, n in cases:
            conn.execute(
                "INSERT INTO cases (case_id, title, court, decision_date, citation, source_url, n_chunks) "
                "VALUES (?,?,?,?,?,?,?)",
                (cid, title, "Supreme Court of India", "2014-07-02", "[2014] 8 S.C.R. 128", None, n),
            )
            conn.execute("INSERT INTO cases_fts (case_id, title) VALUES (?, ?)", (cid, title))
    conn.close()


# ---- tokenizing: no user text can reach FTS5 as syntax ----
check(case_lookup._tokens('Arnesh Kumar v. State of Bihar') == ["arnesh", "kumar", "state", "bihar"],
      "tokens drop 'v.', 'of' and punctuation, keep the real party-name words")
check(case_lookup._tokens('"*" -- ( ) : , NOT') == ["not"] or case_lookup._tokens('"*" -- ( ) : , NOT') == [],
      "FTS5 operator characters vanish before reaching a MATCH string")
check(case_lookup._tokens("D.K. Basu") == ["d", "k", "basu"], "initials are kept, so 'D.K. Basu' is searchable by them")
check(case_lookup._tokens("") == [] and case_lookup._tokens(None) == [], "empty/None query -> no tokens, never raises")

# ---- search ----
fresh_db()
try:
    case_lookup.search_cases("anything")
    check(False, "an empty index raises IndexNotBuilt")
except case_lookup.IndexNotBuilt:
    check(True, "an empty index raises IndexNotBuilt (the bot turns this into an honest 'not available yet')")

seed([
    ("c1", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", 40),
    ("c2", "KARNESH KUMAR SINGH versus STATE OF UTTAR PRADESH", 24),
    ("c3", "STATE OF BIHAR versus RAMESH", 12),
    ("c4", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", 2),
])
r = case_lookup.search_cases("Arnesh Kumar v State of Bihar")
check([c["case_id"] for c in r] == ["c1", "c4"], f"all-words search finds only the matching titles, longer record first -- got {[c['case_id'] for c in r]}")
check(case_lookup.search_cases("kumar bihar zzzzznope")[0]["case_id"] in ("c1", "c4"),
      "when ALL words don't match, it falls back to ANY word, best match first")
check(case_lookup.search_cases("xyzzy plugh") == [], "a query matching nothing returns an honest empty list")
check(case_lookup.search_cases("") == [], "an empty query returns [] instead of matching everything")
try:
    case_lookup.search_cases("Arnesh's \"Kumar\" AND OR NOT * : ( ) , ;")
    check(True, "FTS5-hostile punctuation in the query never raises")
except Exception as exc:
    check(False, f"FTS5-hostile punctuation raised {exc!r}")

# ---- exact vs fuzzy: a lookalike must never look like the case that was asked for ----
seed([("c5", "LATA SINGH versus STATE OF U.P. AND ANR.", 12), ("c6", "KUSUM LATA SHARMA versus ARVIND SINGH", 9)])
det = case_lookup.search_cases_detailed("Arnesh Kumar")
check(det["exact"] and [c["case_id"] for c in det["cases"]] == ["c1", "c4"], "a match on every word is flagged exact=True")
det = case_lookup.search_cases_detailed("Lata Singh v State of Uttar Pradesh")
check(det["exact"] and [c["case_id"] for c in det["cases"]] == ["c5"],
      "'Uttar Pradesh' typed in full still EXACT-matches the title's 'U.P.' (abbreviation aliases), and a title sharing only a name is not dragged in")
det = case_lookup.search_cases_detailed("Lata Singh v State of Bihar")
check(not det["exact"] and [c["case_id"] for c in det["cases"]] == ["c5"],
      "a genuinely fuzzy query ('Bihar' isn't in the title) finds the close case, flagged exact=False; a name-only lookalike is excluded")
check(case_lookup._canon_tokens("State of Uttar Pradesh") == case_lookup._canon_tokens("STATE OF U.P."), "alias spellings collapse to one form when scoring")
check(case_lookup.search_cases_detailed("Zzzz Qqqq Singh")["cases"] == [],
      "a query where no title matches 60% of the words returns nothing rather than lookalikes")
check(case_lookup.search_cases_detailed("Lata Pradesh")["cases"] == [] or True, "(two-word partial match handled without error)")
check(case_lookup.search_cases_detailed("Xylophone")["cases"] == [], "a single unmatched word has no fuzzy fallback at all")
check("exact match" in case_lookup.format_choices([{"case_id": "a", "title": "X v Y", "n_chunks": 9}], exact=False),
      "a fuzzy menu says plainly that it is NOT an exact match")

# ---- reassembling a fetched judgment ----
rows = [(2, "third part " * 40, "conclusion", 3), (0, "first part " * 40, "body", 3), (1, "second part " * 40, "ratio_decidendi", 3)]
doc = case_lookup.assemble_case("c1", rows)
check(doc["complete"] and doc["text"].index("first") < doc["text"].index("second") < doc["text"].index("third"),
      "chunks arriving out of order are reassembled in chunk_index order")
doc = case_lookup.assemble_case("c1", rows[:2])
check(not doc["complete"] and any("of 3" in w for w in doc["warnings"]),
      "a record missing a chunk is flagged INCOMPLETE with a plain warning -- never silently 'fixed'")
doc = case_lookup.assemble_case("c1", [(0, "tiny", "body", 1)])
check(not doc["complete"], "a near-empty record is flagged incomplete")

# ---- fetch: remote mocked, cache behaviour, honest failures ----
class _FakeCon:
    def __init__(self, rows=None, exc=None):
        self.rows, self.exc, self.calls, self.sql = rows, exc, 0, ''
    def execute(self, *a, **k):
        self.calls += 1
        self.sql = a[0] if a else ''
        if self.exc:
            raise self.exc
        return self
    def fetchall(self):
        return self.rows

fresh_db()
good = [(i, f"part {i} " * 60, "body", 2) for i in range(2)]
fake = _FakeCon(good)
case_lookup._duckdb = lambda: fake
d1 = case_lookup.fetch_case_text("cX")
d2 = case_lookup.fetch_case_text("cX")
check(d1["complete"] and not d1["from_cache"] and d2["from_cache"] and fake.calls == 1,
      "a complete judgment is fetched remotely once, then served from the local cache (repeat requests are instant, no second remote query)")
fake_bad = _FakeCon(good[:1])
case_lookup._duckdb = lambda: fake_bad
case_lookup.fetch_case_text("cY")
case_lookup.fetch_case_text("cY")
check(fake_bad.calls == 2, "an INCOMPLETE record is never cached -- a retry gets a fresh chance at the whole thing")
case_lookup._duckdb = lambda: _FakeCon([])
try:
    case_lookup.fetch_case_text("cZ")
    check(False, "an unknown case_id raises CaseNotFound")
except case_lookup.CaseNotFound:
    check(True, "an unknown case_id raises CaseNotFound")
case_lookup._duckdb = lambda: _FakeCon(exc=OSError("network down"))
try:
    case_lookup.fetch_case_text("cW")
    check(False, "a network failure raises CaseLookupUnavailable")
except case_lookup.CaseLookupUnavailable:
    check(True, "a network failure raises CaseLookupUnavailable, never a raw crash")

# ---- English-only fetch, cleaning, and the pre-warmed bundle ----
fresh_db()
fake_sql = _FakeCon(good)
case_lookup._duckdb = lambda: fake_sql
case_lookup.fetch_case_text("cLang")
check("language_code = 'en'" in fake_sql.sql,
      "the remote fetch asks for ENGLISH chunks only (every case is stored once per language -- mixing them produced interleaved garbage)")

raw = ("Case: ARNESH KUMAR versus STATE OF BIHAR & ANR. [[2014] 8 S.C.R. 128] (2014)\nSection: BODY\n\n"
       "[TITLE] # ARNESH KUMAR\n\nA\n\nB\n\n[SECTION] ## CODE OF CRIMINAL PROCEDURE, 1973:\n\nx\n\n"
       "The appellant was arrested.\n\nI\n")
cleaned = case_lookup.clean_chunk_text(raw)
check("Case:" not in cleaned and "Section: BODY" not in cleaned and "[TITLE]" not in cleaned and "[SECTION]" not in cleaned,
      "dataset markup (per-chunk header, [TITLE] #, [SECTION] ##) is stripped")
check("ARNESH KUMAR" in cleaned and "CODE OF CRIMINAL PROCEDURE, 1973:" in cleaned and "The appellant was arrested." in cleaned,
      "the judgment's own words -- including heading text after a stripped marker -- are untouched")
check(not any(len(l.strip()) == 1 and l.strip() in "ABx" for l in cleaned.split("\n")), "stray one-letter margin/OCR lines are removed")
check(cleaned.strip().endswith("I"), "a lone roman numeral 'I' is kept (it can be a real heading)")

fresh_db()
fake_pw = _FakeCon([("okCase", 0, "para one " * 60, "body", 2), ("okCase", 1, "para two " * 60, "body", 2),
                    ("brokenCase", 0, "only part " * 60, "body", 3)])
case_lookup._duckdb = lambda: fake_pw
rep = {r["case_id"]: r for r in case_lookup.prewarm(["okCase", "brokenCase", "missingCase"], write=False)}
check(rep["okCase"]["stored"] is False and "chars" in rep["okCase"], "prewarm(write=False) only REPORTS -- a person reviews before anything is stored")
check(fake_pw.calls == 1, "many cases are fetched in ONE remote pass, not one scan each")
conn = case_lookup._index_conn(); n0 = conn.execute("select count(*) from doc_bundle").fetchone()[0]; conn.close()
check(n0 == 0, "write=False stored nothing")
rep = {r["case_id"]: r for r in case_lookup.prewarm(["okCase", "brokenCase", "missingCase"], write=True)}
check(rep["okCase"]["stored"] and not rep["brokenCase"]["stored"] and rep["missingCase"]["reason"] == "not found",
      "only COMPLETE judgments are bundled; an incomplete or unknown id is reported, not stored")
case_lookup._duckdb = lambda: _FakeCon(exc=OSError("must not be called"))
hit = case_lookup.fetch_case_text("okCase")
check(hit["from_cache"] and hit["complete"], "a pre-warmed case is served instantly with NO remote call (the network is unreachable in this check)")

# ---- per-phone state: choices and daily limits ----
fresh_db()
case_lookup.save_choices("911", [{"case_id": "a"}, {"case_id": "b"}], "docx")
check(case_lookup.get_choices("911") == (["a", "b"], "docx"), "a saved numbered menu (and its file format) is read back")
check(case_lookup.get_choices("922") is None, "a different phone number has no pending menu")
check(case_lookup.get_choices("911", ttl=-1) is None, "an expired menu is treated as gone")
case_lookup.clear_choices("911")
check(case_lookup.get_choices("911") is None, "clearing removes the pending menu")

case_lookup.FETCH_DAILY_LIMIT = 2
check([case_lookup.check_and_record("911", "fetch") for _ in range(3)] == [True, True, False],
      "the daily fetch cap blocks the 3rd request")
check(case_lookup.check_and_record("922", "fetch"), "the cap is per phone number, not global")
check(case_lookup.check_and_record("911", "search"), "search and fetch are counted separately")
case_lookup.FETCH_DAILY_LIMIT = 15

# ---- presentation ----
menu = case_lookup.format_choices([
    {"case_id": "a", "title": "ARNESH KUMAR versus STATE OF BIHAR", "court": "Supreme Court of India",
     "decision_date": "2014-07-02", "citation": "[2014] 8 S.C.R. 128", "n_chunks": 40},
    {"case_id": "b", "title": "X versus Y", "court": "Supreme Court of India", "decision_date": "1999-01-01",
     "citation": None, "n_chunks": 1},
])
check("1. ARNESH KUMAR v STATE OF BIHAR (Supreme Court, 2014) [2014] 8 S.C.R. 128" in menu, "menu line shows title, court, year and citation")
check("very short record" in menu, "a tiny record is flagged in the menu (possibly just an order)")

# ---- documents ----
case = {"title": "ARNESH KUMAR versus STATE OF BIHAR", "court": "Supreme Court of India",
        "decision_date": "2014-07-02", "citation": None, "source_url": None}
docd = {"text": "1. Arrest brings “humiliation” — costs Rs. ₹5,000.\nwrapped line\n\n2. Second para & <b>.",
        "complete": False, "warnings": ["only 1 of 3 parts of this record were available"], "is_procedural": True}
pdf = case_document.build_pdf(case, docd)
check(pdf[:5] == b"%PDF-", "build_pdf produces a real PDF")
try:
    import fitz
    text = "".join(p.get_text() for p in fitz.open(stream=pdf, filetype="pdf"))
    text_flat = " ".join(text.split())
    check("NOT been independently verified" in text_flat, "the disclaimer is printed INSIDE the PDF itself")
    check("Citation: not available in this record" in text_flat, "a missing citation is printed as 'not available', never invented")
    check("interim or procedural order" in text_flat and "may be incomplete" in text_flat, "procedural-order and incomplete warnings appear in the file")
    check("humiliation" in text_flat and "Second para & <b>." in text_flat, "curly quotes are mapped and special characters are escaped, not crashing or dropped")
except ImportError:
    check(True, "(pymupdf not installed -- PDF text checks skipped)")
docx_bytes = case_document.build_docx(case, docd)
check(zipfile.is_zipfile(io.BytesIO(docx_bytes)), "build_docx produces a real .docx (zip) file")
from docx import Document
dtext = " ".join(p.text for p in Document(io.BytesIO(docx_bytes)).paragraphs)
check("NOT been independently verified" in dtext and "not available in this record" in dtext, "the Word file carries the same disclaimer and honest gaps")
check(case_document.suggested_filename(case, "pdf") == "arnesh_kumar_v_state_of_bihar.pdf", "filenames are safe slugs")

# ---- the CASE command through whatsapp_bot ----
p = whatsapp_bot._parse_case_command
check(p("CASE: Arnesh Kumar v State of Bihar") == ("Arnesh Kumar v State of Bihar", "pdf"), "CASE: <name> parses")
check(p("find case Arnesh Kumar word") == ("Arnesh Kumar", "docx"), "'find case <name> word' asks for a Word file")
check(p("case: kumar PDF") == ("kumar", "pdf"), "a trailing PDF is accepted and stripped from the name")
check(p("CASE:") == ("", "pdf") and p("find case") == ("", "pdf"), "a bare command parses to an empty query (-> usage help)")
check(p("Case of theft against my brother, what do I do") is None,
      "REGRESSION GUARD: ordinary text that merely starts with 'case' is NOT hijacked as a lookup command")
check(p("find casement details") is None, "'find casement...' is not the 'find case' command")
check(p("my brother was arrested") is None, "ordinary questions are never treated as commands")

sent, docs = [], []
whatsapp_bot.send_whatsapp_message = lambda ph, t: sent.append(t)
whatsapp_bot.send_whatsapp_document = lambda ph, url, fn, caption=None: (docs.append((url, fn)) or True)
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://example.test"

fresh_db()
seed([("c1", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", 40), ("c4", "ARNESH KUMAR versus STATE OF BIHAR (ORDER)", 2)])
case_lookup._duckdb = lambda: _FakeCon([(i, f"part {i} " * 60, "body", 2) for i in range(2)])

check(case_lookup.get_choices("911") is None, "(no menu pending before the first search)")
sent.clear(); docs.clear()
out = whatsapp_bot.handle_incoming_message("911", "CASE: Arnesh Kumar")
check(len(out) == 1 and "reply with a number" in out[0] and not docs, "two matches -> a numbered menu, no document sent yet")
out = whatsapp_bot.handle_incoming_message("911", "1")
check(len(docs) == 1 and docs[0][0].endswith(".pdf") and docs[0][1].endswith(".pdf"), "replying 1 fetches, builds and sends the PDF")
check(any("NOT been checked against the official law reporter" in m for m in out), "the caption repeats the not-verified warning")
check(case_lookup.get_choices("911") is None, "the menu is cleared after a choice is made")

docs.clear(); sent.clear()
whatsapp_bot.handle_incoming_message("911", "CASE: Arnesh Kumar word")
whatsapp_bot.handle_incoming_message("911", "2")
check(len(docs) == 1 and docs[0][0].endswith(".docx"), "'... word' delivers a .docx via its own store/route")
token = docs[0][0].rsplit("/", 1)[1][:-5]
check(token in whatsapp_bot._PENDING_DOCX and token not in whatsapp_bot._PENDING_PDFS, "the Word file sits in the Word store, never the PDF one")

sent.clear(); docs.clear()
out = whatsapp_bot.handle_incoming_message("911", "CASE: Nonexistent Person v Nobody")
check(len(out) == 1 and "couldn't find" in out[0] and "just send it without" in out[0], "no match -> honest message that also protects a mis-typed real question")

sent.clear(); docs.clear()
out = whatsapp_bot.handle_incoming_message("911", "CASE:")
check(out == [whatsapp_bot._CASE_USAGE], "a bare CASE: shows usage help")

case_lookup._duckdb = lambda: _FakeCon(exc=OSError("down"))
sent.clear(); docs.clear()
seed([("c9", "UNIQUE PARTYNAME versus STATE", 30)])
out = whatsapp_bot.handle_incoming_message("933", "CASE: Unique Partyname")
check(not docs and any("isn't reachable" in m for m in out), "Vaquill unreachable -> honest 'try again shortly', no crash, no file")

case_lookup._duckdb = lambda: _FakeCon([(0, "tiny", "body", 1)])
sent.clear(); docs.clear()
out = whatsapp_bot.handle_incoming_message("934", "CASE: Unique Partyname")
check(not docs and any("broken or almost empty" in m for m in out), "a garbled/near-empty record is never sent as a file")

case_lookup._duckdb = lambda: _FakeCon([(i, f"part {i} " * 60, "body", 2) for i in range(2)])
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = None
sent.clear(); docs.clear()
out = whatsapp_bot.handle_incoming_message("935", "CASE: Unique Partyname")
check(not docs and any("start of the text" in m for m in out), "if the file can't be delivered, the person still gets the text instead of nothing")
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://example.test"

case_lookup.SEARCH_DAILY_LIMIT = 40
seed([("c5", "LATA SINGH versus STATE OF U.P. AND ANR.", 12)])
case_lookup._duckdb = lambda: _FakeCon([(i, f"part {i} " * 60, "body", 2) for i in range(2)])
sent.clear(); docs.clear()
out = whatsapp_bot.handle_incoming_message("955", "CASE: Lata Singh v State of Bihar")
check(not docs and len(out) == 1 and "exact match" in out[0] and "ONLY if one is the case you meant" in out[0],
      "REGRESSION GUARD: a single FUZZY match is shown as a labelled menu, NEVER auto-sent as though it were the case asked for")
out = whatsapp_bot.handle_incoming_message("955", "1")
check(len(docs) == 1, "...and is delivered only after the person picks it")
sent.clear(); docs.clear()
out = whatsapp_bot.handle_incoming_message("956", "CASE: Nonexistent Person v Nobody")
check("does not contain every judgment" in out[0], "the no-match message admits the collection is incomplete (not finding a case is not proof it doesn't exist)")
case_lookup.SEARCH_DAILY_LIMIT = 1
sent.clear()
whatsapp_bot.handle_incoming_message("944", "CASE: Unique Partyname")
out = whatsapp_bot.handle_incoming_message("944", "CASE: Unique Partyname")
check(any("today's limit" in m for m in out), "the daily search cap is enforced with a plain message")
case_lookup.SEARCH_DAILY_LIMIT = 40

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("All checks passed.")
