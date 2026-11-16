"""test_wide_labels.py -- the Judgments page label (2026-11-16, the owner's "Fix the Judgments page label"). A card from the Supreme Court title list said "title and citation only" for judgments whose full text IS in the wide
search index (Gunmala, S.M.S. Pharmaceuticals, Bridgestone, HDFC Bank 2025, Kamalkishor): a tester read them as unreadable and the article blamed a coverage gap. Now case_links knows which title-list judgments (and which
court-linked extras, and every Gauhati one) are also in the wide index and the label says so; a judgment that is not in it (the Ayodhya title suit) keeps the old words. Offline and free. Run: python -X utf8 test_wide_labels.py"""
import gzip
import json
import os
import sys
import tempfile

import build_case_links as B
import case_links as CL

os.environ["API_SEARCH_WARM"] = "off"
import search_service as S  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


BASE = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/"
# ---- 1. the builder, on made-up rows ----
links = {"2014_INSC_1": "data/pdf/year=2014/english/2014_1_1_9_EN.pdf", "2019_INSC_2": "data/pdf/year=2019/english/2019_2_1_9_EN.pdf", "2020_INSC_3": "data/pdf/year=2020/english/2020_3_1_9_EN.pdf", "2021_INSC_4": "S_data/pdf/year=2021/english/2021_4_1_9_EN.pdf"}
official = {"2005_INSC_5": "https://api.sci.gov.in/jonew/judis/5.pdf", "2006_INSC_6": "https://api.sci.gov.in/jonew/judis/6.pdf"}
extras = [{"name": "Extra One", "url": "https://api.sci.gov.in/jonew/judis/7.pdf"}, {"name": "Extra Two", "url": "https://api.sci.gov.in/jonew/judis/8.pdf"}]
new_rows = [{"court": "Supreme Court of India", "link": BASE + "data/pdf/year=2014/english/2014_1_1_9_EN.pdf", "link_kind": "open_bucket_pdf"},
            {"court": "Supreme Court of India", "link": BASE + "data/pdf/year=2019/english/2019_2_1_9_EN.pdf", "link_kind": "open_bucket_pdf"},
            {"court": "Supreme Court of India", "link": BASE + "data/pdf/year=2021/english/2021_4_1_9_EN.pdf", "link_kind": "open_bucket_pdf"},
            {"court": "Supreme Court of India", "link": "https://api.sci.gov.in/jonew/judis/5.pdf", "link_kind": "court_archive_pdf"},
            {"court": "Gauhati High Court", "link": BASE + "data/pdf/year=2020/english/2020_3_1_9_EN.pdf", "link_kind": "open_bucket_pdf"}]
old_rows = [{"link": BASE + "data/pdf/year=2014/english/2014_1_1_9_EN.pdf", "link_kind": "open_bucket_pdf"}, {"link": "https://api.sci.gov.in/jonew/judis/5.pdf", "link_kind": "court_archive_pdf"},
            {"link": "https://api.sci.gov.in/jonew/judis/7.pdf", "link_kind": "court_archive_pdf"}]
f = B.wide_flags(links, official, extras, new_rows, old_rows, base=BASE)
check(f["both"] == ["2005_INSC_5", "2014_INSC_1"], f"in both indexes: the bucket file the pinned table also holds, and the court address the pinned table also holds ({f['both']})")
check(f["newer"] == ["2019_INSC_2", "2021_INSC_4", "2006_INSC_6"] or sorted(f["newer"]) == ["2006_INSC_6", "2019_INSC_2", "2021_INSC_4"], f"only in the newer: a bucket file only the newer table holds (also with the 'S_' prefix), a court address only it holds ({f['newer']})")
check("2020_INSC_3" not in f["both"] + f["newer"], "a Gauhati High Court row of the table never flags a Supreme Court title row")
check(f["extras"] == {"https://api.sci.gov.in/jonew/judis/7.pdf": "both", "https://api.sci.gov.in/jonew/judis/8.pdf": "newer"}, "extras: 'both' when the pinned table has the address, else 'newer'")
check(B.wide_flags(links, official, extras, new_rows, None, base=BASE)["both"] == [], "with no pinned table nothing is claimed for the pinned index")
check("2013_INSC_9" not in f["both"] + f["newer"], "a title row with no tie is not flagged (archive-list-only matches are never passed in)")

# ---- 2. annotate: a round trip changes nothing but the flags ----
tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "links.json.gz")
doc = {"schema": "case-pdf-links-1", "bucket_base": BASE, "built": "2026-01-01", "links": links, "official": official, "official_list": {"2013_INSC_9": "https://api.sci.gov.in/jonew/judis/9.pdf"}, "extras": extras, "title_rows": 4}
json.dump(doc, gzip.open(src, "wt", encoding="utf-8"))
for name, rows, extra in (("new.json.gz", new_rows, {"index_commit": "NEW"}), ("old.json.gz", old_rows, {"index_commit": "OLD"})):
    json.dump({"rows": rows, **extra}, gzip.open(os.path.join(tmp, name), "wt", encoding="utf-8"))
B.annotate(src, os.path.join(tmp, "new.json.gz"), os.path.join(tmp, "old.json.gz"), log=lambda *_: None)
d = json.load(gzip.open(src, "rt", encoding="utf-8"))
check(d["wide_index"]["both"] == ["2005_INSC_5", "2014_INSC_1"] and d["wide_index"]["commits"] == {"newer": "NEW", "pinned": "OLD"} and [e.get("wide") for e in d["extras"]] == ["both", "newer"], "annotate writes the flags, the two index commits and the extras' field")
check(d["links"] == links and d["official"] == official and d["official_list"] == doc["official_list"] and d["built"] == "2026-01-01", "...and changes nothing else in the file")

# ---- 3. case_links reads them ----
real_before = os.environ.get("CASE_LINKS_PATH")
os.environ["CASE_LINKS_PATH"] = src
CL._STATE.clear()
check(CL.wide_status("2014_INSC_1") == "both" and CL.wide_status("2019_INSC_2") == "newer" and CL.wide_status("2013_INSC_9") is None and CL.wide_status("") is None, "wide_status: both / newer / None (a judgment only the archive list tied is None)")
os.environ["CASE_LINKS"] = "off"
check(CL.wide_status("2014_INSC_1") is None, "CASE_LINKS=off: no flag, the old label")
os.environ.pop("CASE_LINKS")
if real_before is None:
    os.environ.pop("CASE_LINKS_PATH")
else:
    os.environ["CASE_LINKS_PATH"] = real_before
CL._STATE.clear()

# ---- 4. the labels ----
check(S._index_tier("both") == S.TIER_INDEX_WIDE_LABEL and S._index_tier("newer") == S.TIER_INDEX_WIDE_MAYBE_LABEL and S._index_tier(None) == S.TIER_INDEX_LABEL, "label by status")
check("title and citation only" in S.TIER_INDEX_LABEL and "wider search" in S.TIER_INDEX_WIDE_LABEL and "may be in the wider search" in S.TIER_INDEX_WIDE_MAYBE_LABEL and "may be in the wider search" in S.TIER_HC_WIDE_LABEL, "the wording: 'is' only for the judgments in both indexes, 'may be' otherwise")
check("only" not in S.TIER_INDEX_WIDE_LABEL.replace("title and citation here", ""), "the new label no longer says 'only'")

# ---- 5. on the real data and the real title index ----
def card(q, title_part):
    r = S.search(q)
    return next((c for c in r["cases"] if title_part in c["title"].upper()), None)

for q, part in (("Gunmala Sales Private Ltd v. Anu Mehta", "GUNMALA"), ("Bridgestone India Inderpal Singh", "BRIDGESTONE"), ("Kamalkishor Shrigopal Taparia", "KAMALKISHOR"), ("2014 INSC 736", "GUNMALA"), ("[2014] 10 S.C.R. 1117", "GUNMALA")):
    c = card(q, part)
    check(c is not None and c["tier"] == S.TIER_INDEX_WIDE_LABEL, f"the card for {q!r} says its full text is in the wider search")
r = S.search("S.M.S. Pharmaceuticals Neeta Bhalla")
check(len([c for c in r["cases"] if "PHARMACEUTICALS" in c["title"].upper()]) == 2 and all(c["tier"] == S.TIER_INDEX_WIDE_LABEL for c in r["cases"] if "PHARMACEUTICALS" in c["title"].upper()), "both S.M.S. Pharmaceuticals judgments (2005 and 2007)")
c = card("M. Siddiq (D) Thr Lrs v. Mahant Suresh Das", "SIDDIQ")
check(c is not None and c["tier"] == S.TIER_INDEX_LABEL, "the Ayodhya title suit (not in the wide index) keeps 'title and citation only'")
c = card("Arnesh Kumar", "ARNESH")
check(c is not None and c["tier"] == S.TIER_LIBRARY_LABEL, "a library judgment is still 'Reviewed library'")
ex = CL.extras()
check(ex and all(e.get("wide") in ("both", "newer") for e in ex), f"every court-linked extra carries a flag ({len(ex)})")
e0 = next(e for e in ex if e.get("scr") and len(e["name"].split()) >= 3)
r = S.search(e0["scr"])
cs = [c for c in r["cases"] if c["court"] == "Supreme Court of India" and c["tier"] in (S.TIER_INDEX_WIDE_LABEL, S.TIER_INDEX_WIDE_MAYBE_LABEL)]
check(bool(cs), f"an extras card (found by its Reports citation {e0['scr']!r}) carries the wide-index wording")

print()
print(f"{len(FAILURES)} failed" if FAILURES else "all passed")
sys.exit(1 if FAILURES else 0)
