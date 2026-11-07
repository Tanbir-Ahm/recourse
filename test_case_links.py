"""
test_case_links.py -- build_case_links.py (how a title-index row is tied to a PDF) and case_links.py (the runtime lookup), added 2026-11-07 (FOLLOW_UPS 2ds in the research repository).
Offline and free: the matching runs on invented rows; the shipped table is only read. Run: python -X utf8 test_case_links.py
"""
import gzip
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
import build_case_links as B
import case_links as CL

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---- normalisers
check(B.norm_title("THE STATE OF  BOMBAY & ANR.") == B.norm_title("the state of bombay anr"), "norm_title keeps letters and digits only")
check(B.norm_name("Sarjoo Prasad v. The State of Uttar Pradesh") == B.norm_name("SARJOO PRASAD versus THE STATE OF UTTAR PRADESH") == B.norm_name("Sarjoo Prasad vs The State of Uttar Pradesh"), "versus, v. and vs read alike in a case name")
check(B.norm_name("Vijay v. Vishal") != B.norm_name("Vishal v. Vijay"), "the order of the parties still matters")
check(B.iso_date("04-12-1950") == "1950-12-04" and B.iso_date("1950-12-04") == "1950-12-04" and B.iso_date("junk") is None, "dates: dd-mm-yyyy and ISO")
check(B.case_id_of("2014 INSC 463") == "2014_INSC_463", "a case id with spaces becomes the title index's form")

# ---- the bucket match
keys = ["data/pdf/year=1951/english/1951_1_603_620_EN.pdf",
        "data/pdf/year=1951/english/1952_1_127_134_EN.pdf", "data/pdf/year=1952/english/1952_1_127_134_EN.pdf",          # one path under two year folders
        "data/pdf/year=1992/english/S_1992_3_544_555_EN.pdf",                                                          # a supplement file name
        "data/pdf/year=2015/english/2015_14_269_281_EN.pdf",
        "data/pdf/year=2020/english/2020_1_1_9_EN.pdf", "data/pdf/year=2020/english/2020_1_10_19_EN.pdf"]
meta = [{"case_id": "1951 INSC 34", "path": "1951_1_603_620", "decision_date": "07-05-1951", "citation": "[1951] 1 S.C.R. 603", "title": "BHAGWATI PRASAD SAH versus DULHIN RAMESHWARI KUER"},
        {"case_id": "1951 INSC 34", "path": "1951_1_603_620", "decision_date": "07-05-1951", "citation": "[1951] 1 S.C.R. 603", "title": "BHAGWATI PRASAD SAH versus DULHIN RAMESHWARI KUER"},      # an exact duplicate row
        {"case_id": "1951 INSC 7", "path": "1952_1_127_134", "decision_date": "10-12-1951", "citation": "[1952] 1 S.C.R. 127", "title": "JOYLAL AGARWALA versus THE STATE"},
        {"case_id": "1992 INSC 5", "path": "S_1992_3_544_555", "decision_date": "01-01-1992", "citation": "[1992] 3 S.C.R. 544", "title": "A versus B"},
        {"case_id": "2015 INSC 9", "path": "2015_14_269_281", "decision_date": "19-08-2015", "citation": "[2015] 14 S.C.R. 269", "title": "SAKHARAM versus STATE OF MADHYA PRADESH"},
        {"case_id": "2020 INSC 1", "path": "2020_1_1_9", "decision_date": "02-01-2020", "citation": "[2020] 1 S.C.R. 1", "title": "P versus Q"},
        {"case_id": "2020 INSC 1", "path": "2020_1_10_19", "decision_date": "02-01-2020", "citation": "[2020] 1 S.C.R. 10", "title": "P versus Q"},                       # one id, two paths
        {"case_id": "2020 INSC 2", "path": "2020_1_9999_9999", "decision_date": "03-01-2020", "citation": "[2020] 1 S.C.R. 9999", "title": "NOKEY versus STATE"},
        {"case_id": "2020 INSC 3", "path": "2020_1_1_9", "decision_date": "05-05-2020", "citation": "[2020] 1 S.C.R. 1", "title": "OTHER versus CASE"}]
rows = [("1951_INSC_34", "BHAGWATI PRASAD SAH versus DULHIN RAMESHWARI KUER", "1951-05-07", "[1951] 1 S.C.R. 603"),
        ("1951_INSC_7", "JOYLAL AGARWALA versus THE STATE", "1951-12-10", "[1952] 1 S.C.R. 127"),
        ("1992_INSC_5", "A versus B", "1992-01-01", "[1992] 3 S.C.R. 544"),
        ("2015_SCR_14_269", "SAKHARAM versus STATE OF MADHYA PRADESH", "2015-08-19", "[2015] 14 S.C.R. 269"),
        ("2020_INSC_1", "P versus Q", "2020-01-02", "[2020] 1 S.C.R. 1"),
        ("2020_INSC_2", "NOKEY versus STATE", "2020-01-03", "[2020] 1 S.C.R. 9999"),
        ("2020_INSC_3", "A DIFFERENT TITLE versus ENTIRELY", "2020-05-05", "[2020] 1 S.C.R. 1"),
        ("2020_INSC_4", "OTHER versus CASE", "2020-06-06", "[2020] 1 S.C.R. 1"),
        ("1999_INSC_99", "NOT IN THE BUCKET versus AT ALL", "1999-09-09", "[1999] 9 S.C.R. 9")]
links, why = B.match_bucket(rows, meta, keys)
check(links.get("1951_INSC_34") == "data/pdf/year=1951/english/1951_1_603_620_EN.pdf", "a row with the same id, title and date is tied to its key (a duplicate metadata row does no harm)")
check(links.get("1951_INSC_7") == "data/pdf/year=1951/english/1952_1_127_134_EN.pdf", "a path listed under two year folders: the folder of the decision year is taken")
check(links.get("1992_INSC_5") == "data/pdf/year=1992/english/S_1992_3_544_555_EN.pdf", "a supplement file (S_ prefix) is found")
check(links.get("2015_SCR_14_269") == "data/pdf/year=2015/english/2015_14_269_281_EN.pdf", "an id that is not an INSC number is tied through the citation, with the same title and date")
check("2020_INSC_1" not in links and why["more than one path"] == 1, "an id that names two paths gets no link (never a guess)")
check("2020_INSC_2" not in links and why["no key in the bucket's listing"] == 1, "a path with no key in the bucket's listing gets no link")
check("2020_INSC_3" not in links and why["a row with that id or citation, but another title or date"] >= 1, "the same id with another title is refused")
check("2020_INSC_4" not in links, "a row with the same title but another date and another id is refused")
check("1999_INSC_99" not in links and why["no row in the bucket's metadata"] == 1, "a case the bucket does not list gets no link")
check(B.pick_key(["data/pdf/year=1952/english/x_EN.pdf", "data/pdf/year=1950/english/x_EN.pdf"], "1951", "1952") == "data/pdf/year=1952/english/x_EN.pdf", "no key in the decision year: the citation year's, then the first by name")

# ---- the court's own addresses
names = [{"name": "Sarjoo Prasad v. The State of Uttar Pradesh", "date": "1960-12-16", "court": "Supreme Court of India", "link_kind": "court_archive_pdf", "link": "https://api.sci.gov.in/jonew/judis/3.pdf"},
         {"name": "Twin v. State", "date": "2001-01-01", "court": "Supreme Court of India", "link_kind": "court_archive_pdf", "link": "https://api.sci.gov.in/jonew/judis/10.pdf"},
         {"name": "Twin v. State", "date": "2001-01-01", "court": "Supreme Court of India", "link_kind": "court_archive_pdf", "link": "https://api.sci.gov.in/jonew/judis/11.pdf"},
         {"name": "Bucket v. State", "date": "2002-02-02", "court": "Supreme Court of India", "link_kind": "open_bucket_pdf", "link": "https://x/y.pdf"},
         {"name": "Hc v. State", "date": "2003-03-03", "court": "Gauhati High Court", "link_kind": "court_archive_pdf", "link": "https://api.sci.gov.in/jonew/judis/12.pdf"}]
trows = [("1960_INSC_1", "SARJOO PRASAD versus THE STATE OF UTTAR PRADESH", "1960-12-16", ""), ("2001_INSC_1", "TWIN versus STATE", "2001-01-01", ""), ("2002_INSC_1", "BUCKET versus STATE", "2002-02-02", ""),
         ("2003_INSC_1", "HC versus STATE", "2003-03-03", ""), ("1960_INSC_2", "SARJOO PRASAD versus THE STATE OF UTTAR PRADESH", "1961-01-01", "")]
off = B.match_official(trows, names)
check(off == {"1960_INSC_1": "https://api.sci.gov.in/jonew/judis/3.pdf"}, f"the court's own address is taken only for the same name and date, one address, a court-site link of a Supreme Court row ({off})")

# ---- the runtime lookup
tmp = tempfile.mkdtemp()
good = os.path.join(tmp, "links.json.gz")
doc = {"schema": "case-pdf-links-1", "built": "2026-11-07", "bucket_base": B.BUCKET, "links": {"2001_INSC_5": "data/pdf/year=2001/english/2001_1_1_9_EN.pdf", "2001_INSC_6": "data/pdf/year=2001/english/b_EN.pdf"},
       "official": {"2001_INSC_6": "https://api.sci.gov.in/jonew/judis/77.pdf", "2001_INSC_7": "http://api.sci.gov.in/jonew/judis/78.pdf", "2001_INSC_8": "https://evil.example.com/x.pdf"}}
json.dump(doc, gzip.open(good, "wt", encoding="utf-8"))
os.environ["CASE_LINKS_PATH"] = good
os.environ.pop("CASE_LINKS", None)
a = CL.link_for("2001_INSC_5")
check(a and a["kind"] == "open_bucket_pdf" and a["url"] == B.BUCKET + "data/pdf/year=2001/english/2001_1_1_9_EN.pdf" and a["label"] == CL.MIRROR_LABEL, "a bucket link is the bucket address plus the key")
b = CL.link_for("2001_INSC_6")
check(b and b["kind"] == "court_site_pdf" and b["url"] == "https://api.sci.gov.in/jonew/judis/77.pdf" and b["label"] == CL.OFFICIAL_LABEL, "the court's own address wins over the bucket's")
check(CL.link_for("2001_INSC_7") is None and CL.link_for("2001_INSC_8") is None, "an address that is not https, or not on a known host, is never returned")
check(CL.link_for("2001 INSC 5") == a and CL.link_for("") is None and CL.link_for(None) is None and CL.link_for("1900_INSC_1") is None, "a case id with spaces is read like the underscore form; unknown or empty ids give None")
os.environ["CASE_LINKS"] = "off"
check(CL.link_for("2001_INSC_5") is None, "CASE_LINKS=off gives no link")
os.environ.pop("CASE_LINKS")
for name, content in (("wrong schema", {"schema": "other", "bucket_base": B.BUCKET, "links": {"x": "y"}}), ("foreign bucket", {"schema": "case-pdf-links-1", "bucket_base": "https://evil.example.com/", "links": {"2001_INSC_5": "k"}})):
    p = os.path.join(tmp, name.replace(" ", "_") + ".json.gz")
    json.dump(content, gzip.open(p, "wt", encoding="utf-8"))
    os.environ["CASE_LINKS_PATH"] = p
    check(CL.link_for("2001_INSC_5") is None, f"a file with a {name} gives no link")
bad = os.path.join(tmp, "garbage.json.gz")
open(bad, "wb").write(b"not gzip")
os.environ["CASE_LINKS_PATH"] = bad
check(CL.link_for("2001_INSC_5") is None, "an unreadable file gives no link and no error")
os.environ["CASE_LINKS_PATH"] = os.path.join(tmp, "missing.json.gz")
check(CL.link_for("2001_INSC_5") is None, "a missing file gives no link and no error")
os.environ.pop("CASE_LINKS_PATH")

# ---- the table that ships
real = json.load(gzip.open(os.path.join(HERE, "case_pdf_links.json.gz"), "rt", encoding="utf-8"))
import sqlite3
ids = {r[0] for r in sqlite3.connect("file:case_lookup_index.db?mode=ro", uri=True).execute("select case_id from cases")}
check(real["schema"] == "case-pdf-links-1" and real["title_rows"] == len(ids) and set(real["links"]) <= ids and set(real["official"]) <= ids, "the shipped table is for this title index: every id in it is a row of case_lookup_index.db")
check(len(real["links"]) / len(ids) > 0.99 and len(real["official"]) > 3500, f"it ties {len(real['links'])} of {len(ids)} judgments to a PDF and {len(real['official'])} to the court's own address")
check(all(k.startswith("data/pdf/year=") and k.endswith("_EN.pdf") for k in real["links"].values()) and all(u.startswith("https://api.sci.gov.in/") for u in real["official"].values()), "every key is a bucket PDF path and every official address is on api.sci.gov.in")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
