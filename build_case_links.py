"""
build_case_links.py -- where to READ each judgment of the Supreme Court title index (case_lookup_index.db): writes case_pdf_links.json.gz (added 2026-11-07, FOLLOW_UPS 2ds in the research repository).

Why. The title index (38,026 Supreme Court judgments, to 12 December 2025) holds a name, a date and a citation for each, no text and no link (its source_url column is empty), so the Judgments page showed a card with
"Not checked by us." and nothing to open. The judgments themselves are public: the open Supreme Court bucket (CC-BY-4.0, Dattam Labs) holds a PDF of nearly every one, and the court's own website holds many.

What it writes. For each title-index row, at most one entry in each of two tables:
  links     case_id -> the key of its PDF in the open bucket (https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/<key>). Only a key that the bucket's own listing shows is ever written, so no address is guessed.
  official  case_id -> the court's own address (https://api.sci.gov.in/...), taken from the names table of the wide search index (`--names-table`), for judgments that the court archive crawl holds.
How a row is tied to a PDF (all of it must hold, else the row gets no link):
  * the bucket's metadata (metadata/parquet/year=YYYY/metadata.parquet) has a row with the same case_id (INSC number), the same title (letters and digits only) and the same decision date;
    or, for a row whose id is not an INSC number (2015_SCR_14_269), a row with the same citation, title and date;
  * all such rows name ONE path, and the bucket's listing holds a key for that path (a path may be listed under two year folders: the folder of the decision year is taken, else of the citation year, else the first by name).
  * an official address is tied in three guarded passes (see match_official): the same Supreme Court Reports citation; or the same date and parties that read alike, the FIRST party above all; or, for a header whose date was
    misread, a near-identical name inside 400 days; a row that two candidates fit, or that two different court files claim, gets none.
It is run by a PERSON, offline, when the title index or the bucket changes (the bucket's monthly refresh adds judgments; the title index would need extending first, extend_index_from_bucket.py):
    python build_case_links.py --cache DIR [--names-table ../recourse-sci-pool/names_table/names_table_d8811a9.json.gz] [--out case_pdf_links.json.gz]
  DIR holds the downloaded bucket metadata and the key listing (downloaded on the first run, politely: about 80 small requests, 50 MB, 80 listing pages). Nothing here says anything about whether a case is good law.
"""
import argparse
import collections
import glob
import gzip
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BUCKET = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/"
SCHEMA = "case-pdf-links-1"
FIRST_YEAR, LAST_YEAR = 1950, 2026
_SP = re.compile(r"\s+")


def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def norm_name(t):
    """A case name with versus / v. / vs written alike and only letters and digits kept."""
    t = (t or "").lower()
    t = re.sub(r"\bversus\b|\bvs?\.?(?=\s)", " v ", t)
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\s+v\s+", "v", t))


def iso_date(d):
    m = re.match(r"^\s*(\d{1,2})-(\d{1,2})-(\d{4})\s*$", d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else (d if re.match(r"^\d{4}-\d{2}-\d{2}$", d or "") else None)


def case_id_of(x):
    return _SP.sub("_", str(x or "").strip())


def path_norm(p):
    """The bucket's path of a judgment without the 'S_' (supplement) prefix its file names sometimes carry."""
    return re.sub(r"^S_", "", str(p or ""))


def key_index(keys):
    """{normalised path: [keys]} from the bucket's listing of English PDFs."""
    out = collections.defaultdict(list)
    for k in keys:
        base = k.rsplit("/", 1)[-1]
        if base.endswith("_EN.pdf"):
            out[path_norm(base[: -len("_EN.pdf")])].append(k)
    return out


def pick_key(keys, decision_year, citation_year=None):
    for yr in (decision_year, citation_year):
        if yr:
            hit = sorted(k for k in keys if f"/year={yr}/" in k)
            if hit:
                return hit[0]
    return sorted(keys)[0] if keys else None


def match_bucket(title_rows, meta_rows, keys):
    """title_rows: [(case_id, title, decision_date, citation)]; meta_rows: dicts with case_id, path, decision_date (dd-mm-yyyy), citation, title; keys: the bucket listing.
    Returns ({case_id: key}, {reason: count})."""
    kidx = key_index(keys)
    by_id, by_cit = collections.defaultdict(list), collections.defaultdict(list)
    for r in meta_rows:
        by_id[case_id_of(r.get("case_id"))].append(r)
        by_cit[_SP.sub(" ", str(r.get("citation") or "")).strip()].append(r)
    links, why = {}, collections.Counter()
    for cid, title, date, cit in title_rows:
        cands = by_id.get(cid) or []
        if not cands:
            cands = by_cit.get(_SP.sub(" ", str(cit or "")).strip(), []) if cit else []
        good = [r for r in cands if norm_title(r.get("title")) == norm_title(title) and iso_date(r.get("decision_date")) == date]
        if not cands:
            why["no row in the bucket's metadata"] += 1
            continue
        if not good:
            why["a row with that id or citation, but another title or date"] += 1
            continue
        paths = {path_norm(r.get("path")) for r in good}
        if len(paths) != 1:
            why["more than one path"] += 1
            continue
        ks = kidx.get(paths.pop())
        if not ks:
            why["no key in the bucket's listing"] += 1
            continue
        m = re.search(r"\[(\d{4})\]", str(cit or ""))
        links[cid] = pick_key(ks, (date or "")[:4], m.group(1) if m else None)
        why["linked"] += 1
    return links, why


_SPLIT = re.compile(r"\s+(?:versus|vs?\.?)\s+", re.I)
_STOP = frozenset("versus state union india others another and the ors anr etc through secretary".split())


def parties(name):
    """('petitioner', 'respondent') of a case name written 'X versus Y', 'X v. Y' or 'X vs Y', each normalised; None when the name has no such word."""
    parts = _SPLIT.split(_SP.sub(" ", str(name or "")).strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    a, b = norm_name(parts[0]), norm_name(parts[1])
    return (a, b) if a and b else None


def _ratio(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _same_parties(p, q, first, second):
    """True when the first parties read alike (at least `first`) and the second parties too (at least `second`). The first party decides: 'Sodagar Singh v. State of Punjab' and 'Teja Singh v. State of Punjab and Others'
    share a date and most of their letters, and are two cases."""
    return bool(p and q) and _ratio(p[0], q[0]) >= first and _ratio(p[1], q[1]) >= second


def _scr_key_names(r):
    out = set()
    for s_ in (r.get("citations") or {}).get("scr", []) or []:
        m = re.search(r"(\d{4})\s+SCR\s*(?:\(Supp\.?\)\s*)?\((\d+)\)\s*(\d+)", s_) or re.search(r"(\d{4})\s+SCR\s*(?:Supp\.?\s*)?(\d+)\s+(\d+)", s_)
        if m:
            out.add((m.group(1), m.group(2), m.group(3)))
    return out


def _scr_key_title(cit):
    m = re.search(r"\[(\d{4})\]\s*(?:Suppl?\.?\s*)?(\d+)\s*(?:Suppl?\.?\s*)?S\.?\s?C\.?\s?R\.?\s*(\d+)", str(cit or ""), re.I)
    return (m.group(1), m.group(2), m.group(3)) if m else None


def _day(s_):
    import datetime
    try:
        return datetime.date.fromisoformat(s_)
    except (TypeError, ValueError):
        return None


def match_official(title_rows, names_rows, log=None):
    """{case_id: the court's own address} from the names table (the wide index's). A Supreme Court row of the names table whose link is the court's own is tied to a title-index row in three passes, each only when it
    gives ONE candidate (a pass that gives two leaves the row to the next pass, and a row that is still ambiguous gets nothing):
      1. the same Supreme Court Reports citation (year, volume, page), a date within 400 days (a date the header parse got wrong is forgiven) and parties that read alike, loosely (two judgments can begin on one page of a volume);
      2. the same date and parties that read alike (first party at least 0.85 alike, second at least 0.75), the best candidate clearly ahead of the next (by 0.05 on the first party);
      3. no usable date, or a date that differs: first party at least 0.93 and second at least 0.85 alike, within 400 days when both dates are known, the name used by no other title-index row.
    Then a title-index row claimed by two different court files gets none (connected appeals decided together share names)."""
    official = [r for r in names_rows if r.get("link_kind") in ("court_archive_pdf", "court_site_pdf") and r.get("court") == "Supreme Court of India" and r.get("name") and r.get("link")]
    by_scr, by_date, by_tok = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(set)
    prepared = {}
    namecount = collections.Counter()
    for t in title_rows:
        cid, title, date, cit = t
        pt = parties(title)
        prepared[cid] = (t, pt)
        namecount[norm_name(title)] += 1
        k = _scr_key_title(cit)
        if k:
            by_scr[k].append(cid)
        by_date[date].append(cid)
        for w in re.findall(r"[a-z]{3,}", str(title).lower()):
            if w not in _STOP:
                by_tok[w].add(cid)
    claims = collections.defaultdict(dict)       # case_id -> {url: pass}
    stats = collections.Counter()
    for r in official:
        pn = parties(r["name"])
        dd = _day(r.get("date"))
        cand = {}
        for k in _scr_key_names(r):
            for cid in by_scr.get(k, []):
                t, pt = prepared[cid]
                td = _day(t[2])
                if dd and td and abs((td - dd).days) > 400:
                    continue
                # two judgments can begin on the same page of a Reports volume (State of Gujarat v. Jaswantlal Nathalal and Munshi Ram v. Delhi Administration, [1968] 2 S.C.R. 408): the parties must read alike too, loosely
                if pn and pt:
                    if not _same_parties(pn, pt, 0.6, 0.5):
                        continue
                elif _ratio(norm_name(r["name"]), norm_name(t[1])) < 0.6:
                    continue
                cand[cid] = 1
        if not cand and r.get("date") and pn:
            scored = []
            for cid in by_date.get(r["date"], []):
                pt = prepared[cid][1]
                if _same_parties(pn, pt, 0.85, 0.75):
                    scored.append((_ratio(pn[0], pt[0]) + _ratio(pn[1], pt[1]), cid, _ratio(pn[0], pt[0])))
            scored.sort(reverse=True)
            if scored and (len(scored) == 1 or scored[0][2] - scored[1][2] >= 0.05):
                cand[scored[0][1]] = 2
        if not cand and pn:
            toks = [w for w in re.findall(r"[a-z]{3,}", r["name"].lower()) if w not in _STOP]
            cnt = collections.Counter(cid for w in toks for cid in by_tok.get(w, ()))
            scored = []
            for cid, k in cnt.most_common(60):
                if k < 2 and len(toks) >= 2:
                    continue
                t, pt = prepared[cid]
                td = _day(t[2])
                if dd and td and abs((dd - td).days) > 400:
                    continue
                if _same_parties(pn, pt, 0.93, 0.85) and namecount[norm_name(t[1])] == 1:
                    scored.append((_ratio(pn[0], pt[0]) + _ratio(pn[1], pt[1]), cid, _ratio(pn[0], pt[0])))
            scored.sort(reverse=True)
            if scored and (len(scored) == 1 or scored[0][2] - scored[1][2] >= 0.05):
                cand[scored[0][1]] = 3
        if len(cand) == 1:
            cid, which = next(iter(cand.items()))
            claims[cid][r["link"]] = which
            stats[f"pass {which}"] += 1
        elif len(cand) > 1:
            stats["ambiguous"] += 1
        else:
            stats["no title-index row"] += 1
    out = {}
    for cid, urls in claims.items():
        if len(urls) == 1:
            out[cid] = next(iter(urls))
        else:
            stats["a title-index row claimed by two court files"] += 1
    if log:
        log(f"  court addresses: {dict(stats)}")
    return out


# ---------------------------------------------------------------- network (a person runs these)
def _get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "recourse-case-links/1"}), timeout=timeout) as r:
        return r.read()


def fetch_metadata(cache, pause=0.2, log=print):
    os.makedirs(cache, exist_ok=True)
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        p = os.path.join(cache, f"meta_{y}.parquet")
        if os.path.exists(p):
            continue
        try:
            data = _get(f"{BUCKET}metadata/parquet/year={y}/metadata.parquet")
        except Exception as e:  # noqa: BLE001
            log(f"  metadata {y}: {type(e).__name__} (skipped)")
            continue
        with open(p, "wb") as fh:
            fh.write(data)
        time.sleep(pause)


def read_metadata(cache):
    import pyarrow.parquet as pq
    rows = []
    for f in sorted(glob.glob(os.path.join(cache, "meta_*.parquet"))):
        rows += pq.read_table(f, columns=["case_id", "path", "decision_date", "citation", "title"]).to_pylist()
    return rows


def fetch_keys(cache, pause=0.1, log=print):
    p = os.path.join(cache, "bucket_keys.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    keys = []
    for y in range(FIRST_YEAR, LAST_YEAR + 1):
        tok = None
        while True:
            q = {"list-type": "2", "prefix": f"data/pdf/year={y}/english/", "max-keys": "1000"}
            if tok:
                q["continuation-token"] = tok
            x = _get(BUCKET + "?" + urllib.parse.urlencode(q)).decode("utf-8")
            keys += re.findall(r"<Key>([^<]+)</Key>", x)
            m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", x)
            if not m:
                break
            tok = m.group(1)
            time.sleep(pause)
        time.sleep(pause)
    json.dump(keys, open(p, "w", encoding="utf-8"))
    return keys


def title_rows(db):
    conn = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
    try:
        return [(a, b, c, d) for a, b, c, d in conn.execute("select case_id, title, decision_date, citation from cases")]
    finally:
        conn.close()


def build(db, cache, names_table=None, out=None, log=print):
    rows = title_rows(db)
    fetch_metadata(cache, log=log)
    keys = fetch_keys(cache, log=log)
    meta = read_metadata(cache)
    links, why = match_bucket(rows, meta, keys)
    official = {}
    if names_table:
        nd = json.load(gzip.open(names_table, "rt", encoding="utf-8"))
        official = match_official(rows, nd["rows"], log=log)
    doc = {"schema": SCHEMA, "built": time.strftime("%Y-%m-%d", time.gmtime()), "title_rows": len(rows), "bucket_base": BUCKET, "bucket_keys_listed": len(keys), "bucket_metadata_rows": len(meta),
           "names_table_commit": (nd.get("index_commit") if names_table else None), "not_linked": {k: v for k, v in why.items() if k != "linked"},
           "source": "open Supreme Court bucket (CC-BY-4.0, Dattam Labs): metadata and listing; the court's own addresses from the names table of the wide search index", "links": links, "official": official}
    out = out or os.path.join(HERE, "case_pdf_links.json.gz")
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    log(f"{len(rows)} title rows; {len(links)} with a bucket PDF ({len(links) / len(rows):.2%}); {len(official)} with the court's own address; not linked: {dict(doc['not_linked'])}; wrote {out} ({os.path.getsize(out) / 1e6:.2f} MB)")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True, help="folder for the downloaded bucket metadata and listing")
    ap.add_argument("--db", default=os.path.join(HERE, "case_lookup_index.db"))
    ap.add_argument("--names-table", help="names_table_<index commit>.json.gz of the research repository (adds the court's own addresses)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    build(a.db, a.cache, a.names_table, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
