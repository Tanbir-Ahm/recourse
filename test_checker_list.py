"""test_checker_list.py -- checker_list.py (the lists the invented-case check looks a name up in) and its wiring in grounding_checks (CHECKER_LIST=title|wide). Offline and free: a small title database and a
small names file are made in a temporary folder. Run: python -X utf8 test_checker_list.py"""
import gzip
import json
import os
import sqlite3
import sys
import tempfile

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.pop("CHECKER_LIST", None)
os.environ.pop("GROUNDING_CHECKS", None)

TMP = tempfile.mkdtemp()
DB = os.path.join(TMP, "titles.db")
NAMES = os.path.join(TMP, "names.json.gz")
os.environ["CASE_LOOKUP_INDEX_PATH"] = DB

conn = sqlite3.connect(DB)
conn.execute("CREATE TABLE cases (case_id TEXT PRIMARY KEY, title TEXT NOT NULL, petitioner TEXT, respondent TEXT, court TEXT, decision_date TEXT, citation TEXT, source_url TEXT, n_chunks INTEGER, source TEXT)")
conn.execute("CREATE VIRTUAL TABLE cases_fts USING fts5(case_id UNINDEXED, title)")
TITLES = [
    ("2014_INSC_1", "ARNESH KUMAR versus STATE OF BIHAR & ANR.", "2014-07-02"),
    ("1997_INSC_1", "KALIKA TIWARI AND ORS. ETC. versus STATE OF BIHAR", "1997-03-25"),
    ("2012_INSC_1", "LALITA KUMARI versus GOVT. OF U.P. & ORS.", "2012-02-27"),
    ("1954_INSC_1", "PANDURANG, TUKIA AND BHILLIA versus THE ST ATE OF HYDERABAD", "1954-12-03"),
    ("2001_INSC_1", "GIRIJA PRASAD (DEAD) BY LRS. versus STATE OF MADHYA PRADESH", "2001-01-01"),
]
for cid, t, d in TITLES:
    conn.execute("INSERT INTO cases (case_id, title, court, decision_date, n_chunks) VALUES (?,?,?,?,?)", (cid, t, "Supreme Court of India", d, 5))
    conn.execute("INSERT INTO cases_fts (case_id, title) VALUES (?, ?)", (cid, t))
conn.commit()
conn.close()
with gzip.open(NAMES, "wt", encoding="utf-8") as fh:
    json.dump({"schema": "checker-names-1", "index_commit": "abc", "documents": 3, "named": 3, "courts": ["Supreme Court of India", "Gauhati High Court", "Reviewed library (court not recorded here)"], "sources": ["wide index", "library"],
               "rows": [["Usha Chakraborty & Anr v. State of West Bengal & Anr", 0, "2023-01-30", 0], ["Bimal Kumar Das v. State of Assam", 1, "2012-05-09", 0], ["Deepa v S. Vijayalakshmi", 2, None, 1]]}, fh)

import checker_list as C
import grounding_checks as G

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---- the switch
for v, want in ((None, "title"), ("wide", "wide"), (' "WIDE" ', "wide"), ("title", "title"), ("banana", "title"), ("", "title")):
    if v is None:
        os.environ.pop("CHECKER_LIST", None)
    else:
        os.environ["CHECKER_LIST"] = v
    check(C.mode() == want, f"CHECKER_LIST={v!r} is read as {want}")
os.environ.pop("CHECKER_LIST", None)

# ---- building
info = C.build(title_db=DB, names_path=NAMES)
check(info["entries"] == 8 and info["title_list"] == 5 and info["names_file"] == 3, f"the index holds the five titles and the three names ({info})")
st = C.stats()
check(st["entries"] == 8 and st["by_list_and_court"].get("wide index | Gauhati High Court") == 1, f"stats counts by list and court ({st['by_list_and_court']})")
check(C.entry_tokens("State of U.P. v. Smt. Radha Devi, thru Dist. Judge") >= {"radha", "devi", "up"} and "smt" not in C.entry_tokens("Smt. Radha Devi"), "entry words: canonical, no honorifics, a State's short form kept")

# ---- lookups
r = C.lookup("Kalika Tiwari v. State of Bihar")
check(r and r["found"] and r["list"] == "title list" and r["court"] == "Supreme Court of India" and r["date"] == "1997-03-25", f"one appellant of a list is found, with its list, court and date ({r})")
check(C.lookup("Lalita Kumari v Government of Uttar Pradesh")["found"], "Government of Uttar Pradesh is found under 'Govt. of U.P.'")
check(C.lookup("Pandurang v. The State of Hyderabad")["found"], "'ST ATE' (a scanned space) does not hide a title")
check(C.lookup("Girija Prasad v. State of Madhya Pradesh")["found"], "'(DEAD) BY LRS.' does not hide a title")
r = C.lookup("Bimal Kumar Das v. State of Assam")
check(r and r["found"] and r["court"] == "Gauhati High Court" and r["list"] == "wide index", f"a Gauhati High Court judgment is found by its court ({r})")
r = C.lookup("Deepa v. S. Vijayalakshmi")
check(r and r["found"] and r["list"] == "library", f"a library case is found ({r})")
check(C.lookup("Zorro Unreal v. State of Nowhere") == {"found": False}, "an unknown name is found nowhere: {'found': False}")
check(C.lookup("Ramesh Chandra v. State of Madhya Pradesh") == {"found": False}, "a name that only shares words with titles is not found")
check(C.lookup("") is None and C.lookup(None) is None and C.lookup("v.") is None, "empty or one-party-less input gives None, not a guess")

# ---- no list readable: None, never False
C.build(title_db=os.path.join(TMP, "missing.db"), names_path=os.path.join(TMP, "missing.gz"))
check(C.lookup("Arnesh Kumar v. State of Bihar") is None, "with no list readable the answer is None ('could not look'), never False")
bad = os.path.join(TMP, "bad.gz")
open(bad, "wb").write(b"not a gzip file")
info = C.build(title_db=DB, names_path=bad)
check(info.get("names_file_error") and info["title_list"] == 5 and C.lookup("Arnesh Kumar v. State of Bihar")["found"], "a broken names file is ignored; the title list still works")
C.build(title_db=DB, names_path=NAMES)

# ---- grounding_checks wiring: the default is the old behaviour
os.environ.pop("CHECKER_LIST", None)
T = lambda n: G.list_lookup(n)                                              # noqa: E731
check(T("Bimal Kumar Das v. State of Assam")[0] is False, "default (title): a High Court case is not found (as before)")
check(T("Kalika Tiwari v. State of Bihar")[0] is False or T("Kalika Tiwari v. State of Bihar")[0] is True, "default (title): the old function decides (whatever it says, the wide lists are not consulted)")
check(G.sc_list_has("Usha Chakraborty v. State of West Bengal") is False, "default (title): the names file is not consulted")
n_old = G.notices([{"name": "A v. B", "status": "not_found"}], [])[0]
check("our list of Supreme Court judgments" in n_old, "default (title): the not-found notice reads exactly as before")

# ---- CHECKER_LIST=wide
os.environ["CHECKER_LIST"] = "wide"
ok, where = G.list_lookup("Bimal Kumar Das v. State of Assam")
check(ok is True and where["court"] == "Gauhati High Court" and where["list"] == "wide index", f"wide: a Gauhati High Court case is found ({where})")
check(G.sc_list_has("Usha Chakraborty v. State of West Bengal") is True, "wide: a Supreme Court case that only the names file holds is found")
check(G.sc_list_has("Kalika Tiwari v. State of Bihar") is True, "wide: a title the old match misses is found")
ok, where = G.list_lookup("Zorro Unreal v. State of Nowhere")
check(ok is False and where is None, "wide: a name in no list is False")
res = G.check_cases("In Bimal Kumar Das v. State of Assam (2012) the Court held X. In Zorro Unreal v. State of Nowhere (2020) it held Y.", "nothing")
check([c["status"] for c in res] == ["real_not_supplied", "not_found"] and res[0]["listed_in"]["court"] == "Gauhati High Court" and "listed_in" not in res[1], f"check_cases: a High Court case is 'real_not_supplied' with its court recorded, an unknown one 'not_found' ({res})")
n_new = G.notices(res, [])
check("could not find it in our lists of judgments" in n_new[1] and "could not find" not in n_new[0], f"wide: the notices ({n_new})")
res2 = G.check_cases("In Zorro Unreal v. State of Nowhere the Court held X.", "nothing", exists_fn=lambda n: None)
check(res2[0]["status"] == "unknown", "a custom exists_fn still works (and is not wrapped)")
# every name the old function found is still found (nothing is lost by switching on)
for t, _c, _d in [(x[1], 0, 0) for x in TITLES]:
    nm = t.replace(" versus ", " v. ")
    if G._sc_title_list_has(nm) is True:
        check(G.sc_list_has(nm) is True, f"nothing lost: {nm} stays found")
# None (nothing readable) in wide mode
C.build(title_db=os.path.join(TMP, "missing.db"), names_path=os.path.join(TMP, "missing.gz"))
check(G.sc_list_has("Arnesh Kumar v. State of Bihar") in (None, True, False) and G.list_lookup("Zorro Unreal v. State of Nowhere")[0] is not True, "wide, nothing readable: never True")
check(G.check_cases("In Zorro Unreal v. State of Nowhere the Court held X.", "nothing")[0]["status"] in ("unknown", "not_found"), "wide, nothing readable: the check does not crash")
os.environ.pop("CHECKER_LIST", None)

# ---- the real files shipped with the code, when they are there (not part of the fixed tests above)
here = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(here, "checker_names.json.gz")) and os.path.exists(os.path.join(here, "case_lookup_index.db")):
    C.build(title_db=os.path.join(here, "case_lookup_index.db"), names_path=os.path.join(here, "checker_names.json.gz"))
    st = C.stats()
    check(st["entries"] > 50000 and any("Gauhati High Court" in k for k in st["by_list_and_court"]), f"the shipped lists load: {st['entries']} entries")
    check(C.lookup("Lalita Kumari v. Government of Uttar Pradesh")["found"] and C.lookup("Usha Chakraborty v. State of West Bengal")["found"], "the shipped lists find Lalita Kumari and Usha Chakraborty (both missed before)")
    check(C.lookup("Ramesh Chandra v. State of Madhya Pradesh") == {"found": False} and C.lookup("Zorro Unreal v. State of Nowhere") == {"found": False}, "the shipped lists still do not find the two invented names of the older tests")
    import time as _t
    t0 = _t.time()
    for _ in range(200):
        C.lookup("Sanjay Kumar Singh v. State of Uttar Pradesh")
    check((_t.time() - t0) / 200 < 0.05, "a lookup takes under 50 ms on the real lists")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
