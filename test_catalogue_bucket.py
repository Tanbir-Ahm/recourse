"""
test_catalogue_bucket.py -- extending the search catalogue with cases from the open bucket's own case list
(extend_index_from_bucket.py), and the bot behaviour for those bucket-only cases. Written BEFORE the code.

Contract: only genuinely NEW cases are added (never a duplicate of one we already have, matched by id OR by
title+date); the run is repeatable (2nd run adds nothing); existing rows are untouched; new cases are searchable;
a bucket-only case (no re-typed text available) still gets its ORIGINAL pdf, and asking for WORD/TEXT says plainly
that the editable version isn't available and sends the original instead. Temp DBs + fake network.
Run: python -X utf8 test_catalogue_bucket.py
"""
import os
import sys
import tempfile

import case_lookup
import case_original
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


try:
    import extend_index_from_bucket as ext
except ImportError:
    ext = None
check(ext is not None, "extend_index_from_bucket module exists")
if ext is None:
    print("\nFAILED (module missing)")
    sys.exit(1)

# ---------------------------------------------------------------- 1. turning a bucket row into a catalogue row
row = {"case_id": "2025 INSC 605", "title": "GAYATRI BALASAMY versus M/S ISG NOVASOFT TECHNOLOGIES LIMITED",
       "decision_date": "30-04-2025", "citation": "[2025] 4 S.C.R. 2080", "court": "Supreme Court of India"}
c = ext.bucket_row_to_case(row)
check(c["case_id"] == "2025_INSC_605", f"the bucket id '2025 INSC 605' becomes our id scheme '2025_INSC_605' -- got {c['case_id']}")
check(c["decision_date"] == "2025-04-30", "the date DD-MM-YYYY becomes ISO YYYY-MM-DD like the rest of the catalogue")
check(c["source"] == "bucket" and c["citation"] == "[2025] 4 S.C.R. 2080" and c["court"] == "Supreme Court of India",
      "the row is marked source='bucket' and keeps the citation")
c2 = ext.bucket_row_to_case({**row, "case_id": "", "citation": "[2017] 11 S.C.R. 251"})
check(c2 and c2["case_id"] == "2017_SCR_11_251", f"a row with NO id gets a stable id built from its citation -- got {c2 and c2['case_id']}")
check(ext.bucket_row_to_case({**row, "case_id": "", "citation": ""}) is None, "no id and no citation -> skipped (nothing stable to key it on)")
check(ext.bucket_row_to_case({**row, "title": ""}) is None and ext.bucket_row_to_case({**row, "title": None}) is None, "a row with no title is skipped")
check(ext.bucket_row_to_case({**row, "decision_date": "garbage"})["decision_date"] is None, "an unreadable date becomes None, not a crash")

# ---------------------------------------------------------------- 2. merging into the catalogue
fresh_db()
conn = case_lookup._index_conn()
with conn:
    conn.execute("INSERT INTO cases (case_id, title, court, decision_date, citation, source_url, n_chunks) VALUES (?,?,?,?,?,?,?)",
                 ("2017_INSC_754", "RAKESH KUMAR PAUL versus STATE OF ASSAM", "Supreme Court of India", "2017-08-16", "[2017] 8 S.C.R. 785", None, 46))
    conn.execute("INSERT INTO cases_fts (case_id, title) VALUES (?, ?)", ("2017_INSC_754", "RAKESH KUMAR PAUL versus STATE OF ASSAM"))

incoming = [
    ext.bucket_row_to_case(row),                                                                   # genuinely new
    ext.bucket_row_to_case({**row, "case_id": "2017 INSC 754", "title": "RAKESH KUMAR PAUL versus STATE OF ASSAM",
                            "decision_date": "16-08-2017", "citation": "[2017] 8 S.C.R. 785"}),      # same id as ours
    ext.bucket_row_to_case({**row, "case_id": "2017 INSC 9999", "title": "Rakesh  Kumar Paul versus State of Assam",
                            "decision_date": "16-08-2017", "citation": "[2017] 8 S.C.R. 785"}),      # different id, same title+date
    ext.bucket_row_to_case(row),                                                                   # repeated in the same batch
]
r1 = ext.merge_new_cases(conn, [x for x in incoming if x])
check(r1["added"] == 1 and r1["skipped_same_id"] >= 1 and r1["skipped_same_title_date"] == 1,
      f"only the genuinely new case is added; same-id and same-title+date lookalikes are not -- {r1}")
r2 = ext.merge_new_cases(conn, [x for x in incoming if x])
check(r2["added"] == 0, "running the merge again adds nothing (repeatable)")
old = conn.execute("SELECT n_chunks, source FROM cases WHERE case_id='2017_INSC_754'").fetchone()
check(old == (46, None), f"an existing row is left exactly as it was -- {old}")
conn.close()

# ---------------------------------------------------------------- 3. searchable + shown honestly
res = case_lookup.search_cases_detailed("Gayatri Balasamy v ISG Novasoft Technologies")
check(res["exact"] and [x["case_id"] for x in res["cases"]] == ["2025_INSC_605"], f"the new case is found by name -- {[x['case_id'] for x in res['cases']]}")
check(res["cases"][0]["source"] == "bucket" and res["cases"][0]["n_chunks"] is None, "search results carry source='bucket' and n_chunks=None")
check("very short record" not in case_lookup.format_choices(res["cases"]), "an unknown chunk count is NOT mislabelled 'very short record'")
check(case_lookup.get_case("2025_INSC_605")["source"] == "bucket" and case_lookup.get_case("2017_INSC_754")["source"] is None,
      "get_case reports the source (bucket vs the original catalogue)")

# ---------------------------------------------------------------- 4. an old-format catalogue file gains the column safely
import sqlite3
old_path = os.path.join(_TMP, "oldformat.db")
oc = sqlite3.connect(old_path)
oc.execute("CREATE TABLE cases (case_id TEXT PRIMARY KEY, title TEXT NOT NULL, petitioner TEXT, respondent TEXT, court TEXT, "
           "decision_date TEXT, citation TEXT, source_url TEXT, n_chunks INTEGER)")
oc.execute("INSERT INTO cases (case_id, title, decision_date, n_chunks) VALUES ('x1','A versus B','2000-01-01',5)")
oc.commit(); oc.close()
case_lookup.INDEX_PATH = old_path
check(case_lookup.get_case("x1")["source"] is None, "a catalogue file built before this change still works (column added on open)")

# ---------------------------------------------------------------- 5. the bot with a bucket-only case
fresh_db()
conn = case_lookup._index_conn()
ext.merge_new_cases(conn, [ext.bucket_row_to_case(row)])
conn.close()
sent, docs = [], []
whatsapp_bot.send_whatsapp_message = lambda ph, t: sent.append(t)
whatsapp_bot.send_whatsapp_document = lambda ph, url, fn, caption=None: (docs.append((url, fn)) or True)
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://example.test"


class FakeCon:
    def __init__(self): self.calls = 0
    def execute(self, *a, **k): self.calls += 1; return self
    def fetchall(self): return []          # Vaquill has no text for a bucket-only case


fc = FakeCon()
case_lookup._duckdb = lambda: fc
import fitz
d = fitz.open(); pg = d.new_page(); pg.insert_text((72, 100), "GAYATRI BALASAMY\nv.\nM/S ISG NOVASOFT TECHNOLOGIES LIMITED", fontsize=11)
good = d.tobytes()
KEY = "data/pdf/year=2025/english/2025_4_2080_2110_EN.pdf"
case_original._YEAR_CACHE.clear()
case_original._list_page = lambda prefix, token=None: ([KEY], None)
case_original._download = lambda key, max_bytes: good


def events(phone):
    cc = case_lookup._state_conn()
    try:
        return cc.execute("SELECT event, detail FROM case_events WHERE phone_number=? ORDER BY id", (phone,)).fetchall()
    finally:
        cc.close()


def say(phone, text):
    sent.clear(); docs.clear()
    return whatsapp_bot.handle_incoming_message(phone, text)


say("B1", "CASE: Gayatri Balasamy v ISG Novasoft Technologies")
check(len(docs) == 1 and dict(events("B1")).get("doc_delivered") == "pdf_original" and fc.calls == 0,
      f"a plain request for a bucket-only case delivers its ORIGINAL pdf without touching the (empty) text source -- {events('B1')}")

for suffix, who in (("word", "B2"), ("text", "B3")):
    say(who, f"CASE: Gayatri Balasamy v ISG Novasoft Technologies {suffix}")
    ev = dict(events(who))
    said = " ".join(sent).lower()
    check(len(docs) == 1 and docs[0][1].endswith(".pdf") and ev.get("doc_delivered") == "pdf_original" and ev.get("text_unavailable") == suffix
          and "editable" in said and fc.calls == 0,
          f"'{suffix}' on a bucket-only case says the editable/text version isn't available and sends the original instead -- {events(who)}")

case_original._download = lambda key, max_bytes: (_ for _ in ()).throw(RuntimeError("bucket down"))
say("B4", "CASE: Gayatri Balasamy v ISG Novasoft Technologies word")
check(not docs and "couldn't" in " ".join(sent).lower() and dict(events("B4")).get("text_unavailable") == "word",
      "if the original can't be fetched either, the person gets a plain 'couldn't retrieve' message, never a crash or silence")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
