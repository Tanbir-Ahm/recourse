"""
build_hc_links.py -- writes hc_links.json.gz: every Gauhati High Court judgment of the wide search index, with the address of the court's own file where one is known and the open bucket's copy where one is listed.
(Owner's go 2026-11-07: "Build the court link like the 20000+ supreme court judgements for every judgement of the guwahati high court"; FOLLOW_UPS 2dt in the research repository.)

A person runs this offline; the site only reads the file (case_links.hc_entries). Inputs:
  --names-table  names_table_<commit>.json.gz of the wide index (rows with court "Gauhati High Court": name, date, case number, neutral citation, link, link_kind)
  --meta-dir     a folder of the open High Court bucket's metadata files, <year>_<bench>.parquet, from s3://indian-high-court-judgments/metadata/parquet/year=Y/court=18_6/bench=B/metadata.parquet
  --keys         a JSON file {"<prefix>": [keys]} caching the bucket's own key listing (written when missing; needs network)
Nothing is guessed:
  * the court's own address is the one the wide index already holds (host ghconline.gov.in or ghcservices.assam.gov.in); no address is built from a case number;
  * a bucket copy is tied to a judgment only when the metadata row has the same case number and the same decision date, the parties read alike, exactly one such row exists, and the bucket's listing holds the file.
A judgment with no court address and no copy keeps whatever its single link was; the file says which of the two each address is.
"""
import argparse
import collections
import difflib
import glob
import gzip
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

SCHEMA = "case-hc-links-1"
BUCKET = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com/"
COURT_HOSTS = ("ghconline.gov.in", "ghcservices.assam.gov.in")
COURT = "Gauhati High Court"
FIELDS = ["name", "date", "case_no", "neutral", "court_url", "copy_url"]


def ck(s):
    """A case number in comparable form: letters and digits only, lower case ('Crl.Pet./268/2017' -> 'crlpet2682017')."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def words(s):
    return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in ("shri", "sri", "smt", "smti", "mr", "mrs", "ms", "dr", "the", "m", "s", "and", "ors", "anr", "others", "another", "of", "state", "vs", "v")]


def first_party(title):
    t = re.sub(r"^\s*.+?\s+of\s+", "", title or "", count=1)         # 'WP(C)/5221/2014 of AMARJYOTI KARMAKAR Vs THE STATE ...' -> 'AMARJYOTI KARMAKAR Vs THE STATE ...'
    return re.split(r"\s+vs\.?\s+", t, maxsplit=1, flags=re.I)[0]


def parties_agree(name, meta_title):
    """The first party of the names-table name reads like the first party of the bucket's title (token overlap or string ratio)."""
    a = words(re.split(r"\s+v\.?\s+", name or "", maxsplit=1)[0])
    b = words(first_party(meta_title))
    if not a or not b:
        return False
    sa, sb = set(a), set(b)
    overlap = len(sa & sb) / min(len(sa), len(sb))
    ratio = difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    return overlap >= 0.5 or ratio >= 0.75


def read_meta(meta_dir):
    import pyarrow.parquet as pq
    idx = collections.defaultdict(list)
    n = 0
    for f in sorted(glob.glob(os.path.join(meta_dir, "*.parquet"))):
        bench_hint = os.path.basename(f).split("_", 1)[1].rsplit(".", 1)[0]
        for r in pq.read_table(f, columns=["title", "pdf_link", "decision_date"]).to_pylist():
            title, link, dd = r.get("title") or "", r.get("pdf_link") or "", r.get("decision_date")
            m = re.match(r"\s*(.+?)\s+of\s+", title)
            if not m or not link or dd is None:
                continue
            date = str(dd)[:10]
            bm = re.search(r"/cnrorders/([a-z]+)/orders/([^/]+\.pdf)$", link)
            if not bm:
                continue
            idx[(ck(m.group(1)), date)].append({"title": title, "bench": bm.group(1), "file": bm.group(2), "date": date})
            n += 1
    return idx, n


def list_prefix(prefix):
    keys, token = [], None
    while True:
        u = BUCKET + "?list-type=2&prefix=" + prefix + (("&continuation-token=" + urllib.request.quote(token)) if token else "")
        x = urllib.request.urlopen(u, timeout=60).read()
        root = ET.fromstring(x)
        ns = {"s": root.tag.split("}")[0].strip("{")}
        keys += [k.text for k in root.findall("s:Contents/s:Key", ns)]
        if (root.findtext("s:IsTruncated", namespaces=ns) or "") != "true":
            return keys
        token = root.findtext("s:NextContinuationToken", namespaces=ns)


def bucket_key(m):
    return f"data/pdf/year={m['date'][:4]}/court=18_6/bench={m['bench']}/{m['file']}"


def build(names_table, meta_dir, keys_path, out, log=print):
    d = json.load(gzip.open(names_table, "rt", encoding="utf-8")) if names_table.endswith(".gz") else json.load(open(names_table, encoding="utf-8"))
    rows = [dict(r) for r in d["rows"] if r.get("court") == COURT and r.get("link")]
    for r in rows:
        if not r.get("name"):            # 25 rows whose header could not be split into parties: the case-number field holds the court's own title text ('W.P.(Crl.) 8(K)/2009 SHRI LAVITO SEMA VS'); it is shown as that text, flagged
            r["name"] = re.sub(r"\s+", " ", (r.get("citations") or {}).get("case_no") or "").strip()
            r["_untitled"] = True
    rows = [r for r in rows if r["name"]]
    log(f"{len(rows)} {COURT} judgments in the names table ({sum(1 for r in rows if r.get('_untitled'))} shown under the court's title text)")
    idx, nmeta = read_meta(meta_dir)
    log(f"{nmeta} bucket metadata rows read")
    # the bucket's own listing, for the folders the matches point at
    plan = {}
    for r in rows:
        for m in idx.get((ck((r.get("citations") or {}).get("case_no")), r.get("date")), []):
            plan.setdefault(f"data/pdf/year={m['date'][:4]}/court=18_6/bench={m['bench']}/", None)
    cache = json.load(open(keys_path)) if os.path.exists(keys_path) else {}
    for p in sorted(plan):
        if p not in cache:
            log("listing " + p)
            cache[p] = list_prefix(p)
    json.dump(cache, open(keys_path, "w"))
    listed = {k for v in cache.values() for k in v}
    stats = collections.Counter()
    entries = []
    for r in rows:
        link = r["link"]
        host = re.sub(r"^https?://([^/]+)/.*$", r"\1", link)
        court_url = link if host in COURT_HOSTS else None
        copy_url = link if (host == BUCKET.split("/")[2] and link[len(BUCKET):] in listed) else None
        if host == BUCKET.split("/")[2] and not copy_url:
            stats["own bucket link not in the listing"] += 1
        cn = (r.get("citations") or {}).get("case_no") or ""
        hits = [] if r.get("_untitled") else [m for m in idx.get((ck(cn), r.get("date")), []) if parties_agree(r["name"], m["title"])]
        if copy_url is None and court_url is not None:
            if len(hits) == 1 and bucket_key(hits[0]) in listed:
                copy_url = BUCKET + bucket_key(hits[0])
                stats["copy tied by case number, date and parties"] += 1
            elif len(hits) > 1:
                stats["copy not tied: several orders fit"] += 1
            elif not idx.get((ck(cn), r.get("date"))):
                stats["copy not tied: no metadata row for this case number and date"] += 1
            else:
                stats["copy not tied: parties do not read alike or file not listed"] += 1
        elif copy_url is not None and hits and len(hits) == 1 and BUCKET + bucket_key(hits[0]) != copy_url:
            stats["own bucket link differs from the metadata's file"] += 1
        if not court_url and not copy_url:
            stats["no usable address"] += 1
            continue
        entries.append([r["name"], r.get("date"), None if r.get("_untitled") else (cn or None), (r.get("citations") or {}).get("neutral"), court_url, copy_url])
    entries.sort(key=lambda e: (e[1] or "", e[0]))
    stats["entries"] = len(entries)
    stats["court address"] = sum(1 for e in entries if e[4])
    stats["bucket copy"] = sum(1 for e in entries if e[5])
    stats["both"] = sum(1 for e in entries if e[4] and e[5])
    stats["court address only"] = sum(1 for e in entries if e[4] and not e[5])
    stats["copy only"] = sum(1 for e in entries if e[5] and not e[4])
    doc = {"schema": SCHEMA, "built": time.strftime("%Y-%m-%d"), "court": COURT, "fields": FIELDS, "entries": entries, "bucket_base": BUCKET, "court_hosts": list(COURT_HOSTS),
           "names_table_commit": d.get("index_commit"), "stats": dict(stats),
           "source": "names table of the wide search index (the court's own addresses and the bucket links it holds) and the open High Court bucket's metadata and listing (CC-BY-4.0 per its page, Dattam Labs; licence terms to be confirmed before public use)"}
    with open(out, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as fh:          # no file name or time in the header: the same inputs give the same bytes
        fh.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    for k, v in stats.items():
        log(f"  {k}: {v}")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--names-table", required=True)
    ap.add_argument("--meta-dir", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "hc_links.json.gz"))
    a = ap.parse_args(argv)
    build(a.names_table, a.meta_dir, a.keys, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
