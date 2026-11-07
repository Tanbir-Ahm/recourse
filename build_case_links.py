"""
build_case_links.py -- where to READ each judgment of the Supreme Court title index (case_lookup_index.db): writes case_pdf_links.json.gz (added 2026-11-07, FOLLOW_UPS 2ds in the research repository).

Why. The title index (38,026 Supreme Court judgments, to 12 December 2025) holds a name, a date and a citation for each, no text and no link (its source_url column is empty), so the Judgments page showed a card with
"Not checked by us." and nothing to open. The judgments themselves are public: the open Supreme Court bucket (CC-BY-4.0, Dattam Labs) holds a PDF of nearly every one, and the court's own website holds many.

What it writes. For each title-index row, at most one entry in each of two tables:
  links     case_id -> the key of its PDF in the open bucket (https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/<key>). Only a key that the bucket's own listing shows is ever written, so no address is guessed.
  official_list  case_id -> the court's own address for judgments the names table does not hold (the civil and other judgments the crawl fetched but the criminal-law index never embedded), found from the Court's own LIST of its
    archive (--archive-list: every archive id with the first 140 characters of the judgment) by the parties' words and the archive's order of decision; see match_archive. Measured on 5,778 pairs the names table knows: 3,210 found,
    3 wrong; 120 of 120 list matches opened at the Court were the right case.
  extras    judgments of the wide index that have the court's own address and that the title index does not list (it lists reported cases): name, date, citations, address, so that a name or citation search can find them.
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
WIDE_WINDOW = 730            # days: the most a match may be allowed where the archive is not in the order of decision (see DateGuide.at_spread)
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


def _resembles(pn, dd, prepared, by_tok, name):
    """True when some title-index row is plausibly the same judgment (the first party at least 0.75 alike, the second at least 0.6, within 400 days when both dates are known): such a row must not ALSO get a card of
    its own, whatever the three passes decided."""
    toks = [w for w in re.findall(r"[a-z]{3,}", name.lower()) if w not in _STOP]
    cnt = collections.Counter(cid for w in toks for cid in sorted(by_tok.get(w, ())))
    for cid, k in cnt.most_common(80):
        if k < 2 and len(toks) >= 2:
            continue
        t, pt = prepared[cid]
        td = _day(t[2])
        if dd and td and abs((dd - td).days) > 400:
            continue
        if _same_parties(pn, pt, 0.75, 0.6):
            return True
    return False


def scr_text(r):
    """The Supreme Court Reports citation of a names-table row in the form the search page reads, '[1961] 3 S.C.R. 324', or None."""
    for k in sorted(_scr_key_names(r)):
        return f"[{k[0]}] {k[1]} S.C.R. {k[2]}"
    return None


def air_text(r):
    for s_ in (r.get("citations") or {}).get("air", []) or []:
        m = re.search(r"(\d{4})\s+AIR\s+(\d+)", s_)
        if m:
            return f"AIR {m.group(1)} SC {m.group(2)}"
    return None


def _strip_case_number(name):
    """A case number written in front of the parties, in brackets that may nest: '(Crlmp.No(S). 16406/2011) State of U.P v. Alok Verma' -> 'State of U.P v. Alok Verma'. Brackets with no digit in them are kept."""
    n = name
    if n.startswith("("):
        depth = 0
        for i, ch in enumerate(n):
            depth += (ch == "(") - (ch == ")")
            if depth == 0:
                inner = n[: i + 1]
                if re.search(r"\d", inner) and n[i + 1:].strip():
                    return n[i + 1:].strip()
                break
    return n


def make_extras(rows):
    """The table entries for the leftovers: {'name', 'date', 'year', 'scr', 'air', 'url'}, in a fixed order."""
    out = []
    for r in rows:
        name = _strip_case_number(_SP.sub(" ", r["name"]).strip())
        out.append({"name": name or _SP.sub(" ", r["name"]).strip(), "date": r.get("date"), "year": int(r["date"][:4]) if r.get("date") else None, "scr": scr_text(r), "air": air_text(r), "url": r["link"]})
    out.sort(key=lambda e: (e["year"] or 0, e["name"].lower(), e["url"]))
    return out


def match_official(title_rows, names_rows, log=None, leftovers=None):
    """{case_id: the court's own address} from the names table (the wide index's). A Supreme Court row of the names table whose link is the court's own is tied to a title-index row in three passes, each only when it
    gives ONE candidate (a pass that gives two leaves the row to the next pass, and a row that is still ambiguous gets nothing):
      1. the same Supreme Court Reports citation (year, volume, page), a date within 400 days (a date the header parse got wrong is forgiven) and parties that read alike, loosely (two judgments can begin on one page of a volume);
      2. the same date and parties that read alike (first party at least 0.85 alike, second at least 0.75), the best candidate clearly ahead of the next (by 0.05 on the first party);
      3. no usable date, or a date that differs: first party at least 0.93 and second at least 0.85 alike, within 400 days when both dates are known, the name used by no other title-index row.
    Then a title-index row claimed by two different court files gets none (connected appeals decided together share names).
    leftovers (a list, optional): receives every court-linked row that no pass could tie to a title-index row AND that resembles no title-index row either (see _resembles): judgments the title index does not list
    (it lists reported cases; the wide index also holds unreported ones, and judgments after the index ended). They become the `extras` of the table."""
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
            cnt = collections.Counter(cid for w in toks for cid in sorted(by_tok.get(w, ())))
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
            if leftovers is not None and pn and not _resembles(pn, dd, prepared, by_tok, r["name"]):
                leftovers.append(r)
                stats["no title-index row (kept as an extra)"] += 1
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


_BOILER = re.compile(r"^\s*(?:https?://\S*judis\.nic\.in\s+)?supreme\s+court\s+of\s+india\s+(?:page\s+\d+\s+of\s+\d+\s+)?", re.I)


def _words(text):
    """The words of an archive judgment's opening lines, without the page header every old file starts with ('http://JUDIS.NIC.IN SUPREME COURT OF INDIA Page 1 of 5'): those words belong to every judgment and would
    'find' a case whose name has 'Supreme Court' in it."""
    t = _BOILER.sub("", str(text or ""))
    return set(re.findall(r"[a-z]{3,}", t.lower()))


def _ordered_words(text):
    """The words (3 letters or more) of an archive judgment's opening lines in order, the page header left out."""
    return re.findall(r"[a-z]{3,}", _BOILER.sub("", str(text or "")).lower())


def _title_parts(title):
    parts = re.split(r"\s+versus\s+", str(title or ""), maxsplit=1, flags=re.I)
    a = [w for w in re.findall(r"[a-z]{3,}", parts[0].lower()) if w not in _STOP]
    b = [w for w in re.findall(r"[a-z]{3,}", parts[1].lower()) if w not in _STOP] if len(parts) > 1 else []
    return a, b


class DateGuide:
    """An estimate of the decision date of an archive id. The Court's archive numbers its judgments almost in the order of decision (the median distance of a judgment's date from the median date of its twelve neighbours
    is a day; 90% are within 58 days), so the dates the names table knows (for 7,386 archive ids) give a date for every id between them."""

    def __init__(self, points):
        self.points = sorted((int(i), _day(d) if isinstance(d, str) else d) for i, d in points if d)
        self.points = [(i, d) for i, d in self.points if d]
        self.ids = [i for i, _ in self.points]

    def at(self, i, near=6):
        """The estimated date of archive id i (the median of the dates of its nearest known neighbours, i itself left out), or None."""
        return self.at_spread(i, near)[0]

    def at_spread(self, i, near=6):
        """(estimated date, spread in days): the spread is the distance between the quartiles of the neighbours' dates. Where the archive runs in the order of decision it is small; in the early ids (the 1950s, numbered volume by
        volume) it is large, and a match there is allowed a window as wide as the spread."""
        import bisect
        k = bisect.bisect_left(self.ids, i)
        pts = sorted(d for j, d in self.points[max(0, k - near): k + near] if j != i)
        if not pts:
            return None, 0
        return pts[len(pts) // 2], (pts[(3 * len(pts)) // 4] - pts[len(pts) // 4]).days


def match_archive(title_rows, archive_rows, guide, skip_ids=(), skip_titles=(), window=120, log=None):
    """{archive id: case_id}: an archive judgment (the Court's own list of what its archive holds: id, and the first 140 characters of the judgment, rough) tied to a title-index row when ALL of these hold:
      * the first party's words of the title (at least 85%) and the first three words of the second party's (at least 60%) are among the words of the opening lines;
      * the title's date is within `window` days (120, or twice the spread of the neighbours' dates, at most 730, where the archive is not in the order of decision, as in the 1950s) of the date estimated for the archive id (DateGuide);
      * the first party's words come before the second party's in the opening lines (the parties are not the other way round), and a first party of one distinctive word needs the whole second party as well;
      * exactly one title row fits, or the best leads the next by 0.3 (the sum of the two fractions); a name that two title rows share gets the narrow window only;
      * no other archive judgment fits the same title row (a title row claimed twice gets neither).
    Archive ids in skip_ids (already tied by the names table) and title rows in skip_titles (already linked) are left out. Measured on the 5,778 pairs the names table ties by header, date and citation (each archive id's own
    date left out of the guide): 3,339 found, 5 wrong (0.15%), the rest not matched; 291 further matches were opened at the Court and all were the right case."""
    inv = collections.defaultdict(set)
    tt, td = {}, {}
    for cid, title, date, _cit in title_rows:
        if cid in skip_titles:
            continue
        tt[cid] = _title_parts(title)
        d = _day(date)
        if d:
            td[cid] = d
        for w in set(tt[cid][0] + tt[cid][1]):
            inv[w].add(cid)
    norms = collections.Counter(norm_name(t[1]) for t in title_rows)
    shared = {t[0]: norms[norm_name(t[1])] > 1 for t in title_rows}
    claims, stats = {}, collections.Counter()
    for row in archive_rows:
        i = row["id"]
        if i in skip_ids:
            continue
        clean = _BOILER.sub("", str(row.get("open") or ""))
        ordered = re.findall(r"[a-z]{3,}", clean.lower())
        words = set(ordered)
        first_at = {}
        for pos, w in enumerate(ordered):
            first_at.setdefault(w, pos)
        sides = re.split(r"(?:\bversus\b|\bvs\b\.?|\bv\.)", clean, maxsplit=1, flags=re.I)
        left = set(re.findall(r"[a-z]{3,}", sides[0].lower())) if len(sides) == 2 else None      # the words before 'Vs.' / 'Versus', when the lines show one
        right = set(re.findall(r"[a-z]{3,}", sides[1].lower())) if len(sides) == 2 else None
        if len(words) < 4:
            stats["unreadable opening lines"] += 1
            continue
        ed, spread = guide.at_spread(i)
        win = max(window, min(2 * spread, WIDE_WINDOW))
        cnt = collections.Counter(cid for w in words for cid in sorted(inv.get(w, ())))
        ok = []
        for cid, _k in cnt.most_common(120):
            a, b = tt[cid]
            if not a:
                continue
            hit_a = sum(1 for w in a if w in words) / len(a)
            if hit_a < 0.85:
                continue
            bb = b[:3]
            hit_b = (sum(1 for w in bb if w in words) / len(bb)) if bb else 1.0
            if hit_b < 0.6:
                continue
            if len(a) < 2 and (not bb or hit_b < 1.0):
                continue                                   # a first party of one distinctive word ('Haryana', 'Punjab') needs the whole second party as well
            pa = [first_at[w] for w in a if w in first_at]
            pb = [first_at[w] for w in bb if w in first_at]
            if pa and pb and max(pa) > min(pb):
                continue                                   # the parties are the other way round, or the words come from elsewhere in the lines ('the High Court of Punjab & Haryana')
            if left is not None and sum(1 for w in a if w in left) / len(a) < 0.85:
                continue                                   # the lines show where the first party ends ('Vs.', 'Versus'): the title's first party must be left of it
            lim = window if shared.get(cid) else win       # a name that two title rows share is not given the wide window
            if ed and cid in td and abs((td[cid] - ed).days) > lim:
                continue
            ok.append((hit_a + hit_b, cid))
        if not ok:
            stats["no title row fits"] += 1
            continue
        ok.sort(key=lambda x: (-x[0], x[1]))
        if len(ok) > 1 and ok[0][0] - ok[1][0] < 0.3:
            stats["two title rows fit"] += 1
            continue
        claims[i] = ok[0][1]
    by_title = collections.defaultdict(set)
    for i, cid in claims.items():
        by_title[cid].add(i)
    final = {i: cid for i, cid in claims.items() if len(by_title[cid]) == 1}
    stats["claimed by two archive judgments (dropped)"] = len(claims) - len(final)
    stats["matched"] = len(final)
    if log:
        log(f"  archive list: {dict(stats)}")
    return final


def holdout_archive(title_rows, archive_rows, known, guide, window=120):
    """How the matcher does on pairs that are known: `known` is {archive id: case_id} (the names table's own). The matcher runs over the WHOLE list, as in a build (so every judgment competes for every title row), the date guide
    never using an id's own date, and only the known ids are scored. Returns (correct, wrong, not matched)."""
    got = match_archive(title_rows, archive_rows, guide, window=window)
    ids = {r["id"] for r in archive_rows}
    right = sum(1 for i, cid in got.items() if i in known and known[i] == cid)
    wrong = sum(1 for i, cid in got.items() if i in known and known[i] != cid)
    return right, wrong, len([i for i in known if i in ids]) - right - wrong


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


def read_archive_list(path):
    """[{'id', 'type', 'open'}] from the Court's archive list (names_table/archive_list_*.json.gz of the research repository, made by archive_list_from_docx.py)."""
    d = json.load(gzip.open(path, "rt", encoding="utf-8"))
    return [{"id": int(r[0]), "type": r[1], "open": r[2]} for r in d["rows"]]


def build(db, cache, names_table=None, out=None, log=print, archive_list=None):
    rows = title_rows(db)
    fetch_metadata(cache, log=log)
    keys = fetch_keys(cache, log=log)
    meta = read_metadata(cache)
    links, why = match_bucket(rows, meta, keys)
    official, extras, official_list, arch_info = {}, [], {}, None
    if names_table:
        nd = json.load(gzip.open(names_table, "rt", encoding="utf-8"))
        left = []
        official = match_official(rows, nd["rows"], log=log, leftovers=left)
        extras = make_extras(left)
        if archive_list:
            arch = read_archive_list(archive_list)
            pts = [(r["doc"], r["date"]) for r in nd["rows"] if r.get("doc") and r["doc"] < 1_000_000_000 and r.get("date") and r.get("link_kind") == "court_archive_pdf"]
            guide = DateGuide(pts)
            in_names = {r["doc"] for r in nd["rows"] if r.get("doc") and r["doc"] < 1_000_000_000}
            known = {}
            for cid, url in official.items():
                m = re.search(r"/judis/(\d+)\.pdf$", url)
                if m:
                    known[int(m.group(1))] = cid
            got = match_archive(rows, arch, guide, skip_ids=in_names, skip_titles=set(official), log=log)
            official_list = {cid: f"https://api.sci.gov.in/jonew/judis/{i}.pdf" for i, cid in got.items()}
            right, wrong, none = holdout_archive(rows, arch, known, guide)
            arch_info = {"archive_judgments": len(arch), "matched_to_a_title_row": len(got), "holdout_known_pairs": len(known), "holdout_correct": right, "holdout_wrong": wrong, "holdout_not_matched": none}
            log(f"  archive list: hold-out on {len(known)} known pairs: {right} found, {wrong} wrong, {none} not matched")
    doc = {"schema": SCHEMA, "built": time.strftime("%Y-%m-%d", time.gmtime()), "title_rows": len(rows), "bucket_base": BUCKET, "bucket_keys_listed": len(keys), "bucket_metadata_rows": len(meta),
           "names_table_commit": (nd.get("index_commit") if names_table else None), "not_linked": {k: v for k, v in why.items() if k != "linked"},
           "source": "open Supreme Court bucket (CC-BY-4.0, Dattam Labs): metadata and listing; the court's own addresses from the names table of the wide search index", "links": links, "official": official, "official_list": official_list, "archive_list_check": arch_info, "extras": extras}
    out = out or os.path.join(HERE, "case_pdf_links.json.gz")
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    log(f"{len(rows)} title rows; {len(links)} with a bucket PDF ({len(links) / len(rows):.2%}); {len(official)} with the court's own address; {len(extras)} court-linked judgments the title index does not list (extras); {len(official_list)} more court addresses from the Court's archive list; not linked: {dict(doc['not_linked'])}; wrote {out} ({os.path.getsize(out) / 1e6:.2f} MB)")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True, help="folder for the downloaded bucket metadata and listing")
    ap.add_argument("--db", default=os.path.join(HERE, "case_lookup_index.db"))
    ap.add_argument("--names-table", help="names_table_<index commit>.json.gz of the research repository (adds the court's own addresses)")
    ap.add_argument("--archive-list", help="the Court's archive list (names_table/archive_list_*.json.gz of the research repository): adds court addresses for judgments the names table does not hold")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    build(a.db, a.cache, a.names_table, a.out, archive_list=a.archive_list)
    return 0


if __name__ == "__main__":
    sys.exit(main())
