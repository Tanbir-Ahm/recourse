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

# ---- the court's own addresses (three guarded passes)
def N(name, date, link, scr=None, kind="court_archive_pdf", court="Supreme Court of India"):
    return {"name": name, "date": date, "court": court, "link_kind": kind, "link": link, "citations": {"scr": scr or []}}


names = [N("Sarjoo Prasad v. The State of Uttar Pradesh", "1960-12-16", "https://api.sci.gov.in/jonew/judis/3.pdf"),
         N("Twin v. State", "2001-01-01", "https://api.sci.gov.in/jonew/judis/10.pdf"), N("Twin v. State", "2001-01-01", "https://api.sci.gov.in/jonew/judis/11.pdf"),
         N("Bucket v. State", "2002-02-02", "https://x/y.pdf", kind="open_bucket_pdf"), N("Hc v. State", "2003-03-03", "https://api.sci.gov.in/jonew/judis/12.pdf", court="Gauhati High Court"),
         N("Teja Singh v. State of Punjab and Others", "1997-01-24", "https://api.sci.gov.in/jonew/judis/20.pdf"),
         N("Munshi Ram and Others v. Delhi Administration", "1967-11-27", "https://api.sci.gov.in/jonew/judis/2217.pdf", scr=["1968 SCR (2) 408"]),
         N("Shyamlal Mohanlal v. State of Gujarat", "1964-12-14", "https://api.sci.gov.in/jonew/judis/30.pdf", scr=["1965 SCR (1) 99"]),
         N("Vijayan @ Vijayakumar v. State Rep.By Inspector of Police", "2000-03-22", "https://api.sci.gov.in/jonew/judis/16470.pdf"),
         N("Rajiv Kumar & Ors v. Raksha Kumari", "2003-09-17", "https://api.sci.gov.in/jonew/judis/40.pdf")]
trows = [("1960_INSC_1", "SARJOO PRASAD versus THE STATE OF UTTAR PRADESH", "1960-12-16", ""), ("2001_INSC_1", "TWIN versus STATE", "2001-01-01", ""), ("2002_INSC_1", "BUCKET versus STATE", "2002-02-02", ""),
         ("2003_INSC_1", "HC versus STATE", "2003-03-03", ""), ("1960_INSC_2", "SARJOO PRASAD versus THE STATE OF UTTAR PRADESH", "1961-01-01", ""),
         ("1997_INSC_54", "SODAGAR SINGH versus STATE OF PUNJAB AND ORS.", "1997-01-24", "[1997] 1 S.C.R. 1"),
         ("1967_INSC_272", "STATE OF GUJARAT versus JASWANTLAL NATHALAL", "1967-11-23", "[1968] 2 S.C.R. 408"),
         ("1964_INSC_285", "SHYAMLAL MOBANLAL versus STATE OF GUJARAT", "1964-12-14", "[1965] 1 S.C.R. 99"),
         ("1999_INSC_125", "VIJAYAN @ VIJAYA KUMAR versus STATE REP. BY INSPECTOR OF POLICE", "1999-03-22", "[1999] 2 S.C.R. 89"),
         ("2003_INSC_9", "A COMPLETELY OTHER CASE versus SOMEONE ELSE", "2003-09-17", "")]
off = B.match_official(trows, names)
check(off.get("1960_INSC_1") == "https://api.sci.gov.in/jonew/judis/3.pdf", "same date and the same parties: the court's address is taken")
check("1960_INSC_2" not in off, "a second title-index row with the same name (another date) is not given the address too")
check("2001_INSC_1" not in off, "a title-index row that two different court files fit gets none")
check("2002_INSC_1" not in off and "2003_INSC_1" not in off, "a bucket address, or a High Court row, is not a court address of a Supreme Court judgment")
check("1997_INSC_54" not in off, "same date, same respondent, another FIRST party (Sodagar Singh v. State of Punjab, Teja Singh v. State of Punjab and Others): two cases, no address")
check("1967_INSC_272" not in off, "the same Reports page (1968) 2 SCR 408 for two judgments (State of Gujarat v. Jaswantlal Nathalal, Munshi Ram v. Delhi Administration): no address")
check(off.get("1964_INSC_285") == "https://api.sci.gov.in/jonew/judis/30.pdf", "the same Reports citation and parties that read alike through a spelling slip (Mobanlal, Mohanlal): the address is taken (pass 1)")
check(off.get("1999_INSC_125") == "https://api.sci.gov.in/jonew/judis/16470.pdf", "a header date misread by a year (2000 for 1999) with a near-identical name and no other row of that name: the address is taken (pass 3)")
check("2003_INSC_9" not in off, "a title-index row that no court file resembles gets none")
check(B.parties("A v. B") == ("a", "b") and B.parties("X versus Y & Ors") == ("x", "yors") and B.parties("no party word") is None, "parties(): split on versus / v. / vs; None without one")

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
check(len(real["links"]) / len(ids) > 0.99 and len(real["official"]) > 5500, f"it ties {len(real['links'])} of {len(ids)} judgments to a PDF and {len(real['official'])} to the court's own address")
check(all(k.startswith("data/pdf/year=") and k.endswith("_EN.pdf") for k in real["links"].values()) and all(u.startswith("https://api.sci.gov.in/") for u in real["official"].values()), "every key is a bucket PDF path and every official address is on api.sci.gov.in")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
