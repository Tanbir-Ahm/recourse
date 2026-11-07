"""
test_hc_links.py -- build_hc_links.py (how a Gauhati High Court judgment is tied to the court's address and to the open bucket's copy), case_links.hc_entries (the runtime reader) and the Judgments page search for
those judgments (search_service._hc_cards), added 2026-11-07 (FOLLOW_UPS 2dt in the research repository). Offline and free: the builder runs on invented rows and a tiny metadata file; the shipped table is only read; no model is called.
Run: python -X utf8 test_hc_links.py
"""
import gzip
import json
import os
import sys
import tempfile

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ["SEARCH_MEANING"] = "off"
os.environ.pop("SCI_SEARCH_URL", None)
os.environ.pop("CASE_LINKS", None)
os.environ.pop("HC_LINKS_PATH", None)
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
import build_hc_links as B
import case_links as CL
import search_service as S

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---- 1. the builder's small functions
check(B.ck("Crl.Pet./268/2017") == B.ck("CRL.PET 268/2017") == "crlpet2682017", "a case number is compared by its letters and digits only")
check(B.first_party("WP(C)/5221/2014 of AMARJYOTI KARMAKAR Vs THE STATE OF ASSAM AND 2 ORS") == "AMARJYOTI KARMAKAR", "the first party is read from the bucket's title")
check(B.parties_agree("Amarjyoti Karmakar v. The State of Assam and 2 Ors", "WP(C)/5221/2014 of AMARJYOTI KARMAKAR Vs THE STATE OF ASSAM AND 2 ORS"), "the same first party agrees")
check(B.parties_agree("Md Elumuddin Ali @ Dilbar v. State of Assam", "Crl.A./191/2009 of MD ELUMUDDIN ALI @ DILBAR Vs THE STATE OF ASSAM"), "an '@' alias and a leading 'Md' do not break the match")
check(not B.parties_agree("Ram Singh v. State of Assam", "Crl.A./1/2010 of GOPAL DAS Vs THE STATE OF ASSAM"), "another first party does not agree")
check(not B.parties_agree("", "Crl.A./1/2010 of GOPAL DAS Vs X"), "an empty name never agrees")

# ---- 2. the build on invented rows: a tiny metadata file, a keys cache written beforehand (no network)
import pyarrow as pa
import pyarrow.parquet as pq
tmp = tempfile.mkdtemp()
meta_dir = os.path.join(tmp, "meta")
os.makedirs(meta_dir)
import datetime as dt
mrows = [
    {"title": "Crl.A./10/2018 of RAM DAS Vs THE STATE OF ASSAM", "pdf_link": "court/cnrorders/asghccis/orders/GAHC010000012018_1_2018-05-01.pdf", "decision_date": dt.datetime(2018, 5, 1)},
    {"title": "Crl.A./11/2018 of GOPAL RAI Vs THE STATE OF ASSAM", "pdf_link": "court/cnrorders/asghccis/orders/GAHC010000022018_1_2018-05-02.pdf", "decision_date": dt.datetime(2018, 5, 2)},
    {"title": "Crl.A./11/2018 of GOPAL RAI Vs THE STATE OF ASSAM", "pdf_link": "court/cnrorders/asghccis/orders/GAHC010000022018_2_2018-05-02.pdf", "decision_date": dt.datetime(2018, 5, 2)},     # a second order, same case, same day
    {"title": "Crl.A./12/2018 of SOMEONE ELSE Vs THE STATE OF ASSAM", "pdf_link": "court/cnrorders/asghccis/orders/GAHC010000032018_1_2018-05-03.pdf", "decision_date": dt.datetime(2018, 5, 3)},
    {"title": "Crl.A./13/2018 of HARI BORAH Vs THE STATE OF ASSAM", "pdf_link": "court/cnrorders/asghccis/orders/GAHC010000042018_1_2018-05-04.pdf", "decision_date": dt.datetime(2018, 5, 4)},     # file not in the listing
    {"title": "junk with no case number", "pdf_link": "court/cnrorders/asghccis/orders/X.pdf", "decision_date": dt.datetime(2018, 5, 5)},
]
pq.write_table(pa.Table.from_pylist(mrows), os.path.join(meta_dir, "2018_asghccis.parquet"))
BKT = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com/"
listing = {"data/pdf/year=2018/court=18_6/bench=asghccis/": [
    "data/pdf/year=2018/court=18_6/bench=asghccis/GAHC010000012018_1_2018-05-01.pdf",
    "data/pdf/year=2018/court=18_6/bench=asghccis/GAHC010000022018_1_2018-05-02.pdf", "data/pdf/year=2018/court=18_6/bench=asghccis/GAHC010000022018_2_2018-05-02.pdf",
    "data/pdf/year=2018/court=18_6/bench=asghccis/GAHC010000032018_1_2018-05-03.pdf",
    "data/pdf/year=2018/court=18_6/bench=asghccis/GAHC010000052018_1_2018-06-01.pdf"]}
keys_path = os.path.join(tmp, "keys.json")
json.dump(listing, open(keys_path, "w"))


def nrow(doc, name, date, case_no, link, neutral=None):
    c = {"case_no": case_no}
    if neutral:
        c["neutral"] = neutral
    return {"doc": doc, "name": name, "date": date, "year": int(date[:4]) if date else None, "citations": c, "link": link, "court": "Gauhati High Court"}


nrows = [
    nrow(2000000001, "Ram Das v. The State of Assam", "2018-05-01", "Crl.A./10/2018", "https://ghcservices.assam.gov.in/casestatus/pdfWatermark.php?file=2018/220900000102018_7.pdf", "2018:GAU-AS:10"),      # court address, copy found by metadata
    nrow(2000000002, "Gopal Rai v. The State of Assam", "2018-05-02", "Crl.A./11/2018", "https://ghcservices.assam.gov.in/casestatus/pdfWatermark.php?file=2018/220900000112018_7.pdf"),                  # two orders the same day: no copy tied
    nrow(2000000003, "Hari Borah v. The State of Assam", "2018-05-04", "Crl.A./13/2018", "https://ghcservices.assam.gov.in/casestatus/pdfWatermark.php?file=2018/220900000132018_7.pdf"),                 # the file is not in the listing
    nrow(2000000004, "Another Name v. The State of Assam", "2018-05-03", "Crl.A./12/2018", "https://ghcservices.assam.gov.in/casestatus/pdfWatermark.php?file=2018/220900000122018_7.pdf"),                # another first party than the bucket's row
    nrow(2000000005, "Old Case v. The State of Assam", "2011-01-25", "Crl.A. 5/2005", "https://ghconline.gov.in/Judgment/CrlA52005.pdf"),                                                                  # an old one: court address only
    nrow(2000000006, "Copy Only v. The State of Assam", "2018-06-01", "Crl.A./30/2018", BKT + "data/pdf/year=2018/court=18_6/bench=asghccis/GAHC010000052018_1_2018-06-01.pdf"),                           # the index's own bucket link
    nrow(2000000007, "Gone v. The State of Assam", "2018-07-01", "Crl.A./31/2018", BKT + "data/pdf/year=2018/court=18_6/bench=asghccis/NOT_THERE.pdf"),                                                    # a bucket link not in the listing: no usable address
    nrow(2000000008, None, "2011-02-23", "W.P.(Crl.) 8(K)/2009 SHRI LAVITO SEMA VS", "https://ghconline.gov.in/Judgment/WPCrlK82009.pdf"),                                                                  # no parsed name
    dict(nrow(2000000009, "Supreme One v. State", "2018-01-01", "SLP 1/2018", "https://api.sci.gov.in/jonew/judis/1.pdf"), court="Supreme Court of India"),                                               # not this court
]
nt = os.path.join(tmp, "names.json.gz")
with gzip.open(nt, "wt", encoding="utf-8") as fh:
    json.dump({"rows": nrows, "index_commit": "test"}, fh)
out = os.path.join(tmp, "hc.json.gz")
logs = []
doc = B.build(nt, meta_dir, keys_path, out, log=logs.append)
by = {e[0]: e for e in doc["entries"]}
check(len(doc["entries"]) == 7 and "Supreme One v. State" not in by, "only this court's rows are listed; the row with no usable address is left out (7 of 9)")
check(by["Ram Das v. The State of Assam"][5] == BKT + "data/pdf/year=2018/court=18_6/bench=asghccis/GAHC010000012018_1_2018-05-01.pdf" and by["Ram Das v. The State of Assam"][4].startswith("https://ghcservices.assam.gov.in/"),
      "the same case number, date and parties tie the court's address to the bucket's file")
check(by["Gopal Rai v. The State of Assam"][5] is None, "two orders of one case on one day: no copy is tied (not guessed)")
check(by["Hari Borah v. The State of Assam"][5] is None, "a file that the bucket's listing does not hold is not offered")
check(by["Another Name v. The State of Assam"][5] is None, "another first party than the bucket's row: no copy")
check(by["Old Case v. The State of Assam"][4] == "https://ghconline.gov.in/Judgment/CrlA52005.pdf" and by["Old Case v. The State of Assam"][5] is None, "an old judgment keeps its court address and has no copy")
check(by["Copy Only v. The State of Assam"][4] is None and by["Copy Only v. The State of Assam"][5].startswith(BKT), "a judgment the index linked to the bucket keeps that copy and no court address is made up")
check("Gone v. The State of Assam" not in by, "a bucket link that is not listed, with no court address, leaves the judgment out")
check("W.P.(Crl.) 8(K)/2009 SHRI LAVITO SEMA VS" in by and by["W.P.(Crl.) 8(K)/2009 SHRI LAVITO SEMA VS"][2] is None, "a row with no parsed name is shown under the court's title text, with no case number of its own")
check(doc["stats"]["court address"] == 6 and doc["stats"]["bucket copy"] == 2 and doc["stats"]["both"] == 1, "the counts add up (6 court addresses, 2 copies, 1 with both)")
out2 = os.path.join(tmp, "hc2.json.gz")
B.build(nt, meta_dir, keys_path, out2, log=lambda s: None)
check(open(out, "rb").read() == open(out2, "rb").read(), "the same inputs give the same bytes")

# ---- 3. the runtime reader
os.environ["HC_LINKS_PATH"] = out
CL._STATE.clear()
es = CL.hc_entries()
check(len(es) == 7 and all(e["court_url"] or e["copy_url"] for e in es), "the reader returns the 7 entries, each with an address")
links = CL.hc_links(next(e for e in es if e["name"].startswith("Ram Das")))
check([l["label"] for l in links] == [CL.HC_OFFICIAL_LABEL, CL.HC_MIRROR_LABEL] and links[0]["kind"] == "high_court_site_pdf", "the court's address comes first, the copy second")
bad = dict(doc)
bad["entries"] = [["Evil v. State", "2018-01-01", "Crl.A./1/2018", None, "https://evil.example/x.pdf", "http://indian-high-court-judgments.s3.ap-south-1.amazonaws.com/x.pdf"],
                  ["Fine v. State", "2018-01-02", "Crl.A./2/2018", None, "https://ghconline.gov.in/Judgment/x.pdf", "https://evil.example/y.pdf"], ["short row"]]
bp = os.path.join(tmp, "bad.json.gz")
with gzip.open(bp, "wt", encoding="utf-8") as fh:
    json.dump(bad, fh)
os.environ["HC_LINKS_PATH"] = bp
CL._STATE.clear()
es = CL.hc_entries()
check([e["name"] for e in es] == ["Fine v. State"] and es[0]["copy_url"] is None and es[0]["court_url"], "an address on another host or over http is dropped; a malformed row is dropped; an entry with no safe address is dropped")
os.environ["HC_LINKS_PATH"] = os.path.join(tmp, "missing.json.gz")
CL._STATE.clear()
check(CL.hc_entries() == [], "a missing file means no list, no error")
os.environ["HC_LINKS_PATH"] = out
CL._STATE.clear()
os.environ["CASE_LINKS"] = "off"
check(CL.hc_entries() == [], "CASE_LINKS=off turns the list off")
os.environ.pop("CASE_LINKS")

# ---- 4. the shipped table
os.environ.pop("HC_LINKS_PATH")
CL._STATE.clear()
S._HC_CACHE.clear()
d = json.load(gzip.open(os.path.join(HERE, "hc_links.json.gz"), "rt", encoding="utf-8"))
st = d["stats"]
check(d["schema"] == "case-hc-links-1" and len(d["entries"]) == st["entries"] == 7553, "the shipped table lists 7,553 Gauhati High Court judgments")
check(st["court address"] == 3340 and st["bucket copy"] == 6795 and st["both"] == 2582 and st["court address only"] == 758 and st["copy only"] == 4213, "3,340 with the court's address, 6,795 with a copy, 2,582 with both, 758 court only, 4,213 copy only")
es = CL.hc_entries()
check(len(es) == 7553 and all(e["court_url"] or e["copy_url"] for e in es), "the reader accepts every shipped entry (every address is on a known host)")
check(sum(1 for e in es if e["court_url"]) == 3340 and sum(1 for e in es if e["copy_url"]) == 6795, "the reader keeps all 3,340 court addresses and all 6,795 copies")
check(all(e["court_url"].startswith(("https://ghconline.gov.in/", "https://ghcservices.assam.gov.in/")) for e in es if e["court_url"]), "every court address is on ghconline.gov.in or ghcservices.assam.gov.in")
check(all(e["copy_url"].endswith(".pdf") and "court=18_6" in e["copy_url"] for e in es if e["copy_url"]), "every copy is a PDF in the Gauhati folder of the open bucket")
check(CL.stats()["hc"] == 7553, "stats() reports the list")

# ---- 5. the Judgments page
e1 = next(e for e in es if e["neutral"] and e["court_url"] and e["copy_url"])
r = S.search(e1["neutral"], "library")
cs = [c for c in r["cases"] if c["court"] == "Gauhati High Court"]
check(any(c["title"] == e1["name"] for c in cs), "a neutral citation (2019:GAU-AS:nnnn) finds the judgment")
c = next(c for c in cs if c["title"] == e1["name"])
check([l["label"] for l in c["links"]][:2] == [CL.HC_OFFICIAL_LABEL, CL.HC_MIRROR_LABEL] and c["links"][0]["url"] == e1["court_url"] and c["links"][1]["url"] == e1["copy_url"], "its card shows the court's address first, then the copy")
check(c["links"][-1]["label"].startswith("Search for it on Indian Kanoon") and c["tier"] == S.TIER_HC_LABEL and c["held"] == "index" and c["neutral"] == e1["neutral"] and c["citation"] == e1["case_no"], "then the Indian Kanoon search; the tier says what the list holds; the neutral citation and the case number are on the card")
check(c["status"] and c["status"]["source"] in ("not_checked", "card_quiet"), "it carries a verdict sentence like any card (not checked by us)")
r = S.search(e1["case_no"], "library")
check(any(c["title"] == e1["name"] for c in r["cases"]), "a case number with its type (Crl.A./nnn/yyyy) finds it")
variant = e1["case_no"].replace("/", " ", 1)
r = S.search(variant, "library")
check(any(c["title"] == e1["name"] for c in r["cases"]), "a case number typed with a space for the first slash finds it too")
r = S.search(e1["name"].split(" v. ")[0] + " " + e1["name"].split(" v. ")[1].replace(" and ", " "), "library")
check(any(c["title"] == e1["name"] for c in r["cases"]), "every word of the name finds it")
for flt, want in (("hc", True), (None, True), ("sc", False)):
    r = S.search(e1["neutral"], "library", court=flt)
    got = any(c["title"] == e1["name"] for c in r["cases"])
    check(got == want, f"court filter {flt!r}: the High Court judgment is {'shown' if want else 'not shown'}")
e2 = next(e for e in es if e["court_url"] and not e["copy_url"] and e["case_no"] and e["neutral"] is None)
r = S.search(e2["case_no"], "library", court="hc")
c2 = next((c for c in r["cases"] if c["title"] == e2["name"]), None)
check(c2 is not None and c2["links"][0]["label"] == CL.HC_OFFICIAL_LABEL and len(c2["links"]) == 2, "a judgment with only the court's address shows that and the Indian Kanoon search")
e3 = next(e for e in es if e["copy_url"] and not e["court_url"])
r = S.search(e3["case_no"], "library", court="hc")
c3 = next((c for c in r["cases"] if c["title"] == e3["name"]), None)
check(c3 is not None and c3["links"][0]["label"] == CL.HC_MIRROR_LABEL, "a judgment with only the bucket's copy shows the copy, labelled as a copy")
check(S.search("Keshavan Madhava Menon State of Bombay", "library")["cases"][0]["court"] != "Gauhati High Court", "a Supreme Court search is not changed")
r = S.search("State of Assam", "library", court="hc")
check(len([c for c in r["cases"] if c["court"] == "Gauhati High Court"]) <= 10, "a wide name returns at most ten High Court cards")
r = S.search("zzzz nothing matches this", "library", court="hc")
check(not r["cases"], "a name nobody has returns no High Court card")
os.environ["CASE_LINKS"] = "off"
S._HC_CACHE.clear()
r = S.search(e1["neutral"], "library", court="hc")
check(not any(c["court"] == "Gauhati High Court" for c in r["cases"]), "CASE_LINKS=off: no High Court card")
os.environ.pop("CASE_LINKS")
S._HC_CACHE.clear()

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("ALL PASSED")
