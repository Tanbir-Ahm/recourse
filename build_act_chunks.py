"""
build_act_chunks.py -- loads the FULL text of an Act from India Code into the Act shelf (act_shelf/<key>.json), checked by machine against India Code's own PDF of the same Act.
Step 2 of STATUTE_COVERAGE_PLAN.md (research repository); written 2026-10-16.  A maintenance tool, never run by the site.  Generalises build_ni_act_statute_chunks.py (which loads 19 chosen sections
of one Act): the Acts and their India Code ids come from act_shelf/manifest.json, and EVERY section of the central Act is loaded.

Where the text comes from (and why)
  India Code's data API (indiacode.gov.in/server/api/discover/search/objects) holds each section of a central Act as one record carrying the CURRENT in-force text (amendments in square brackets) and its
  footnotes ("Subs. by Act 16 of 2018, s. 4 ... (w.e.f. 26-7-2018)"). The site itself is a client-side app with nothing to read in plain HTML, which is why the API is used. Records are picked by the Act's own
  act_id and must be CENTRAL, collection SECTION: state adaptations and decoys share titles and are excluded.

The checks (any hard failure stops the Act; nothing is written)
  1. every record belongs to the Act (same act_id), is central, is a SECTION; no section number twice; no empty text (an omitted or repealed section keeps its short stub and is marked omitted);
  2. the PDF of the Act on India Code (the English one; found by the Act's name on its first pages) has an "ARRANGEMENT OF SECTIONS": its section numbers, their ORDER and their titles must equal what was loaded
     (an independent count: the loaded set is complete, nothing is cut off or doubled);
  3. every word of every loaded section must occur somewhere in that PDF. A word that does not is a typing slip in India Code's database (the files carry lost hyphens, apostrophes and spaces: "Moneylaundering",
     "childs mental", "otherlaw", "section44", a stray "br" after a bracket). Each is listed with the PDF's own reading; the manifest must either CORRECT it ('corrections': exact text, section, reason) or ACCEPT
     it ('accepted': a spelling variant that is not a slip, with the reason). A correction is itself checked: the corrected wording must be in the PDF. Nothing is corrected silently or by guesswork.
  4. no HTML left over; the footnotes are kept (they carry the amendment history).
  What the PDF check cannot show: that the text is the law today (India Code's PDF is a snapshot, its date is printed on its first page and recorded as 'pdf_as_on'; the database records are newer), or that
  India Code itself is right. The status stays 'machine_checked' until a person reads the sections (see the sheet for Mr. Advocate); the site words it "official text loaded <date>, not yet read by our reviewer".

Usage (needs indiacode.gov.in reachable, python 'requests' and PyMuPDF):
    python build_act_chunks.py                       # every Act in act_shelf/manifest.json
    python build_act_chunks.py --only pc_act_1988    # one Act
    python build_act_chunks.py --report-only         # fetch and check, print the report, write nothing
"""
import argparse
import datetime
import hashlib
import html as _html
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
API_BASE = "https://indiacode.gov.in/server/api"
SEARCH_URL = API_BASE + "/discover/search/objects"
MANIFEST_PATH = os.path.join(HERE, "act_shelf", "manifest.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SECTION_LINE = re.compile(r"^\s*(\d{1,3}[A-Z]{0,3})\.\s+(\S.*)$")


class LoadError(Exception):
    """A check failed: the Act is not written."""


# ----------------------------------------------------------------------------------------------- text helpers

def norm_words(text):
    """Lower-case words: the unit every check compares in (case, punctuation and typographic quotes do not matter)."""
    t = (text or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.findall(r"[a-z0-9]+", t)


def _norm_title(text):
    return " ".join(norm_words(text))


def clean_html(raw):
    """India Code's presentational HTML to plain text: <br/> and <hr/> become line breaks, footnote markers (<sup>3</sup>) and every other tag go, entities are decoded, the stray 'br' that malformed data leaves
    after a closing bracket is dropped, spaces are tidied. Amendment brackets and *** (words omitted) stay as India Code gives them."""
    t = raw or ""
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<hr[^>]*>", "\n", t, flags=re.I)
    t = re.sub(r"<sup>\s*\d+\s*</sup>", "", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t)
    t = t.replace(" ", " ").replace("­", "").replace("​", "")
    t = re.sub(r"(?<=[\]\).])br[ \t]*$", "", t, flags=re.M)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    t = re.sub(r"\n{2,}", "\n", t)
    return t.strip()


def clean_footnotes(raw):
    """The footnotes of a section as plain lines: '1. Subs. by Act 16 of 2018, s. 4, for sections 7, 8, 9 and 10 (w.e.f. 26-7-2018).' (the marker number kept)."""
    t = raw or ""
    t = re.sub(r"<sup>\s*(\d+)\s*</sup>", r"\1", t, flags=re.I)
    return clean_html(t)


def is_omitted(title):
    return bool(re.match(r"^\W*(omitted|repealed)\W*$", title or "", flags=re.I))


def md_first(item, key):
    v = (item.get("metadata") or {}).get(key)
    return v[0]["value"] if v else None


# ----------------------------------------------------------------------------------------------- network

class Fetcher:
    """The only thing that touches the network (replaced by a fake in the tests). Polite: a short pause between calls, retries on a blip."""

    def __init__(self, pause=0.4):
        import requests
        self.requests = requests
        self.pause = pause

    def _get(self, url, **kw):
        last = None
        for attempt in range(4):
            try:
                r = self.requests.get(url, headers=HEADERS, timeout=kw.pop("timeout", 90), **kw)
                r.raise_for_status()
                time.sleep(self.pause)
                return r
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(3 * (attempt + 1))
        raise LoadError(f"{url}: {type(last).__name__}: {str(last)[:120]}")

    def json(self, url, params=None):
        return self._get(url, params=params).json()

    def bytes(self, url):
        return self._get(url, timeout=180).content

    # --- India Code specifics
    def act_records(self, act_id):
        """Every record whose text search hits the act_id (sections, schedules, rules, notifications, decoys), as the indexable objects."""
        out, page = [], 0
        while True:
            data = self.json(SEARCH_URL, {"query": act_id, "dsoType": "item", "size": 100, "page": page})
            sr = data["_embedded"]["searchResult"]
            out += [o["_embedded"]["indexableObject"] for o in sr["_embedded"]["objects"]]
            page += 1
            if page >= sr["page"]["totalPages"]:
                return out

    def item(self, uuid):
        return self.json(f"{API_BASE}/core/items/{uuid}")

    def original_pdfs(self, uuid):
        """[(name, bytes)] for every PDF in the item's ORIGINAL bundle."""
        bundles = self.json(f"{API_BASE}/core/items/{uuid}/bundles")["_embedded"]["bundles"]
        out = []
        for b in bundles:
            if b.get("name") != "ORIGINAL":
                continue
            for bs in self.json(b["_links"]["bitstreams"]["href"])["_embedded"]["bitstreams"]:
                if str(bs.get("name", "")).lower().endswith(".pdf"):
                    out.append((bs["name"], self.bytes(bs["_links"]["content"]["href"])))
        return out


def pdf_pages(pdf_bytes):
    """The text of each page of a PDF (PyMuPDF)."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return [p.get_text() for p in doc]


# ----------------------------------------------------------------------------------------------- loading and checking

def section_records(records, act_id):
    """The Act's own central SECTION records, in India Code's order. Anything else that the text search returned (state adaptations with the same title, rules, notifications, schedules) is left out."""
    out = []
    for it in records:
        if md_first(it, "dc.identifier.act_id") != act_id:
            continue
        if md_first(it, "dc.identifier.collection") != "SECTION":
            continue
        if str(md_first(it, "dc.identifier.state_name") or "").upper() != "CENTRAL":
            continue
        out.append(it)
    out.sort(key=lambda r: int(md_first(r, "dc.identifier.order_number") or 0))
    return out


def build_sections(recs, act, loaded_on):
    """One chunk per section in the shape the site reads (act_name, citation, section_number, title, text, source_url, source_type) plus what the shelf needs: act (the code), footnotes, omitted, order, uuid."""
    chunks, seen = [], set()
    for it in recs:
        num = str(md_first(it, "dc.identifier.section_number") or "").strip()
        title = (md_first(it, "dc.title") or "").strip()
        if not num:
            raise LoadError(f"a record has no section number: {it.get('uuid')}")
        if num in seen:
            raise LoadError(f"section {num} appears twice")
        seen.add(num)
        body = clean_html(md_first(it, "dc.identifier.section_page_note") or "")
        if not body:
            raise LoadError(f"section {num} has no text")
        foot = clean_footnotes(md_first(it, "dc.identifier.section_footnote") or "")
        text = f"{num}. {title}\n{body}"
        chunks.append({
            "act": act["code"], "act_key": act["key"], "act_name": act["name"], "citation": act["citation"],
            "section_number": num, "title": title, "text": text, "footnotes": foot, "omitted": is_omitted(title),
            "order": int(md_first(it, "dc.identifier.order_number") or 0), "uuid": it.get("uuid"), "handle": it.get("handle"),
            "source_url": act["sections_url"], "source_type": "primary", "loaded_on": loaded_on, "text_status": "machine_checked",
            "last_modified": it.get("lastModified"),
        })
    if not chunks:
        raise LoadError("no section records found for this act_id")
    return chunks


def pick_english_pdf(pdfs, act_name):
    """Among the item's PDFs the one that is the English text of this Act: its first pages contain the Act's name. Exactly one must. Returns (name, bytes, pages)."""
    want = _norm_title(re.sub(r"^\s*the\s+", "", act_name, flags=re.I))
    hits = []
    for name, data in pdfs:
        try:
            pages = pdf_pages(data)
        except Exception:  # noqa: BLE001
            continue
        head = _norm_title(" ".join(pages[:3]))
        if want and want in head:
            hits.append((name, data, pages))
    if len(hits) != 1:
        raise LoadError(f"cannot pick the English PDF of {act_name!r}: {len(hits)} candidate(s) among {[n for n, _ in pdfs]}")
    return hits[0]


def pdf_as_on(pages):
    m = re.search(r"\[\s*As on the ([^\]]{4,40})\]", " ".join(pages[:3]))
    return m.group(1).strip() if m else None


def parse_toc(pages):
    """The 'ARRANGEMENT OF SECTIONS' of the PDF: [(number, title)], in order. Runs from that heading to the Act's long title ('An Act to ...')."""
    lines = []
    for p in pages:
        lines += p.splitlines()
    try:
        i0 = next(i for i, l in enumerate(lines) if "ARRANGEMENT OF SECTIONS" in l.upper())
    except StopIteration:
        return []
    out, cur = [], None
    for l in lines[i0 + 1:]:
        if re.match(r"^\s*(An Act\b|AN ACT\b|BE it enacted|Be it enacted|\(?ACT NO\b)", l):
            break
        mm = SECTION_LINE.match(l)
        if mm:
            cur = [mm.group(1), mm.group(2).strip()]
            out.append(cur)
        elif cur and l.strip() and not re.match(r"^\s*(CHAPTER|SECTIONS?\b|THE\b|_+\s*$|IndiaCode|\d+\s*$|[A-Z][A-Z0-9 ,\-—.()]+$)", l.strip()):
            cur[1] += " " + l.strip()
    return [(n, t) for n, t in out]


def compare_toc(toc, chunks):
    """The PDF's arrangement of sections against what was loaded: same numbers, same order, same titles (words only, 'non-compliance' = 'noncompliance')."""
    t_nums, c_nums = [n for n, _ in toc], [c["section_number"] for c in chunks]
    only_toc, only_loaded = [n for n in t_nums if n not in c_nums], [n for n in c_nums if n not in t_nums]
    tmap = {n: t for n, t in toc}
    squash = lambda s: "".join(norm_words(s))  # noqa: E731
    title_diffs = [(c["section_number"], c["title"], tmap[c["section_number"]]) for c in chunks
                   if c["section_number"] in tmap and squash(c["title"]) != squash(tmap[c["section_number"]])
                   and not (squash(c["title"]) in squash(tmap[c["section_number"]]) or squash(tmap[c["section_number"]]) in squash(c["title"]))]
    return {"toc_entries": len(toc), "loaded": len(chunks), "only_in_pdf": only_toc, "only_in_loaded": only_loaded, "same_order": t_nums == c_nums, "title_differences": title_diffs,
            "ok": bool(toc) and not only_toc and not only_loaded and t_nums == c_nums and not title_diffs}


def pdf_vocabulary(pages):
    """The PDF's words: as extracted, plus the words made by joining a hyphen at a line end ('where-\\nunder' -> 'whereunder'), so a word the PDF merely broke across lines is not called absent.
    EXCEPT a compound the PDF also writes with its hyphen in mid-line ('Money-laundering', 'sub-section', 'Non-Government'): the joined form of those ('moneylaundering') is exactly the slip the database
    makes (a lost hyphen), so a break at a line end must not excuse it."""
    text = "\n".join(pages)
    plain = set(norm_words(text))
    joined = set(norm_words(re.sub(r"-\s*\n\s*", "", text)))
    mid = {(a + b).lower() for a, b in re.findall(r"([A-Za-z]{2,})[-\u2010\u2011]([A-Za-z]{2,})", re.sub(r"-\s*\n\s*", "\n", text))}
    return plain | (joined - plain - mid)


def absent_words(chunks, vocab):
    """For every section: the words of its text and footnotes that occur nowhere in the PDF, each with a little context. [(section, word, context)]."""
    out = []
    for c in chunks:
        body = c["text"].split("\n", 1)[1] if "\n" in c["text"] else c["text"]
        foot = c.get("footnotes", "")
        for w in sorted({w for w in norm_words(body + " " + foot) if w not in vocab}):
            m, src = re.search(re.escape(w), body, re.I), body
            if not m:
                m, src = re.search(re.escape(w), foot, re.I), foot
            ctx = (("[footnote] " if src is foot else "") + src[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")) if m else ""
            out.append((c["section_number"], w, ctx))
    return out


def coverage_by_section(chunks, pages, n=4):
    """A soft measure, never a pass/fail: for each section, the share of its n-word runs (body text only) that occur in the PDF. Footnote numbers, clause letters and page breaks inside a section lower it
    (a short section 1 with a footnote scores about 0.8); a wrong word in the middle of a long section would too. Returns {section: share}."""
    text = "\n".join(pages)
    toks_plain, toks_joined = norm_words(text), norm_words(re.sub(r"-\s*\n\s*", "", text))
    runs = {tuple(toks_plain[i:i + n]) for i in range(len(toks_plain) - n + 1)} | {tuple(toks_joined[i:i + n]) for i in range(len(toks_joined) - n + 1)}
    out = {}
    for c in chunks:
        body = c["text"].split("\n", 1)[1] if "\n" in c["text"] else c["text"]
        tk = norm_words(body)
        mine = [tuple(tk[i:i + n]) for i in range(len(tk) - n + 1)]
        out[c["section_number"]] = round(sum(1 for r in mine if r in runs) / len(mine), 3) if mine else 1.0
    return out


def apply_corrections(chunks, corrections):
    """Exact replacements the manifest lists: {'section', 'from', 'to', 'why', optional 'field': 'footnotes', optional 'count': n}. Each must find its text exactly n times (default once) in that section;
    the text becomes the corrected text and the correction is recorded on the chunk."""
    by = {c["section_number"]: c for c in chunks}
    for fix in corrections or []:
        c = by.get(str(fix["section"]))
        if c is None:
            raise LoadError(f"correction for a section that was not loaded: {fix}")
        field = fix.get("field", "text")                 # 'text' (default) or 'footnotes'
        if field not in ("text", "footnotes"):
            raise LoadError(f"correction field must be 'text' or 'footnotes': {fix}")
        want = int(fix.get("count", 1))                  # how many times the text occurs in that section: stated, so a correction can never hit more or less than the person who wrote it saw
        n = c[field].count(fix["from"])
        if n != want:
            raise LoadError(f"correction {fix['from']!r} in section {fix['section']} ({field}) matches {n} times (the manifest says {want})")
        c[field] = c[field].replace(fix["from"], fix["to"])
        c.setdefault("corrections", []).append({"field": field, "from": fix["from"], "to": fix["to"], "count": want, "why": fix.get("why", "")})
    return chunks


def check_corrections_in_pdf(corrections, vocab, pages):
    """A correction is itself checked: every word of the corrected wording must be in the PDF, and the corrected phrase (words only) must occur in the PDF text."""
    flat = " ".join(norm_words("\n".join(pages)))
    flat_joined = " ".join(norm_words(re.sub(r"-\s*\n\s*", "", "\n".join(pages))))
    bad = []
    for fix in corrections or []:
        words = norm_words(fix["to"])
        phrase = " ".join(words)
        if any(w not in vocab for w in words) or (phrase not in flat and phrase not in flat_joined):
            bad.append(fix)
    return bad


def build_act(entry, fetcher, loaded_on=None, with_pdf=True, discover=False):
    """Loads and checks one Act of the manifest. Returns (chunks, report). Raises LoadError on a hard failure."""
    loaded_on = loaded_on or datetime.date.today().isoformat()
    ic = entry["india_code"]
    act = {"key": entry["key"], "code": entry["code"], "name": entry["name"], "citation": entry["citation"], "sections_url": f"https://indiacode.gov.in/act/{ic['uuid']}/sections"}
    item = fetcher.item(ic["uuid"])
    act_id = md_first(item, "dc.identifier.act_id")
    if not act_id or (ic.get("act_id") and act_id != ic["act_id"]):
        raise LoadError(f"India Code's act_id for {ic['uuid']} is {act_id!r}, the manifest says {ic.get('act_id')!r}")
    if str(md_first(item, "dc.identifier.state_name") or "").upper() != "CENTRAL" or md_first(item, "dc.identifier.collection") != "ACT":
        raise LoadError("the manifest's uuid is not a central Act record")
    recs = section_records(fetcher.act_records(act_id), act_id)
    chunks = build_sections(recs, act, loaded_on)
    report = {"key": entry["key"], "act_id": act_id, "loaded_on": loaded_on, "sections": len(chunks), "omitted_sections": [c["section_number"] for c in chunks if c["omitted"]],
              "record_last_modified": {"min": min(c["last_modified"] for c in chunks if c["last_modified"]), "max": max(c["last_modified"] for c in chunks if c["last_modified"])}}
    if not with_pdf:
        report["pdf"] = None
        report["note"] = "NOT checked against the PDF"
        return chunks, report
    name, data, pages = pick_english_pdf(fetcher.original_pdfs(ic["uuid"]), entry["name"])
    toc = parse_toc(pages)
    cmp_ = compare_toc(toc, chunks)
    report["pdf"] = {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "pages": len(pages), "as_on": pdf_as_on(pages), "toc": cmp_}
    if not cmp_["ok"]:
        raise LoadError(f"the loaded sections do not equal the PDF's arrangement of sections: {json.dumps({k: v for k, v in cmp_.items() if k != 'ok'}, ensure_ascii=False)[:600]}")
    vocab = pdf_vocabulary(pages)
    bad_fix = check_corrections_in_pdf(entry.get("corrections"), vocab, pages)
    if bad_fix:
        raise LoadError(f"a correction is not what the PDF reads: {bad_fix}")
    apply_corrections(chunks, entry.get("corrections"))
    left = absent_words(chunks, vocab)
    accepted = {(str(a["section"]), a["word"]) for a in entry.get("accepted") or []}
    unresolved = [(s, w, ctx) for s, w, ctx in left if (s, w) not in accepted]
    report["corrections"] = [dict(f) for f in entry.get("corrections") or []]
    report["accepted"] = [dict(a) for a in entry.get("accepted") or []]
    report["absent_words_unresolved"] = [{"section": s, "word": w, "context": ctx} for s, w, ctx in unresolved]
    stale = [a for a in entry.get("accepted") or [] if (str(a["section"]), a["word"]) not in {(s, w) for s, w, _ in left}]
    report["accepted_not_needed"] = stale
    if unresolved and not discover:
        raise LoadError("words in India Code's section text that are nowhere in its PDF, not corrected or accepted in the manifest: " + "; ".join(f"s.{s} '{w}' ...{ctx}..." for s, w, ctx in unresolved[:12]))
    if stale and not discover:
        raise LoadError(f"the manifest accepts words that are not (or no longer) absent: {stale}")
    if any(re.search(r"[<>]|&[a-z]+;|\bstyle=", c["text"] + c["footnotes"]) for c in chunks):
        raise LoadError("HTML is left in a section")
    cov = coverage_by_section(chunks, pages)
    report["pdf_run_coverage"] = {"measure": "share of 4-word runs of a section's body found in the PDF (soft; footnote numbers and page breaks lower it)", "min": min(cov.values()), "below_0.90": {k: v for k, v in cov.items() if v < 0.90}}
    return chunks, report


def write_act(entry, chunks, report, out_dir):
    path = os.path.join(out_dir, f"{entry['key']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(chunks, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=MANIFEST_PATH)
    ap.add_argument("--only", help="load only this Act key")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--no-pdf", action="store_true", help="skip the PDF checks (the Act is then NOT fit to go live)")
    ap.add_argument("--discover", action="store_true", help="list EVERY word that is not in the PDF (with context) instead of stopping at the first failure; writes nothing")
    args = ap.parse_args(argv)
    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)
    out_dir = os.path.dirname(os.path.abspath(args.manifest))
    f = Fetcher()
    reports, failed = {}, []
    for entry in manifest["acts"]:
        if args.only and entry["key"] != args.only:
            continue
        print(f"== {entry['key']}: {entry['name']}")
        try:
            chunks, report = build_act(entry, f, with_pdf=not args.no_pdf, discover=args.discover)
        except LoadError as exc:
            print("   FAILED:", exc)
            failed.append(entry["key"])
            continue
        reports[entry["key"]] = report
        pdf = report.get("pdf") or {}
        print(f"   {report['sections']} sections ({len(report['omitted_sections'])} omitted/repealed); PDF {pdf.get('name')} as on {pdf.get('as_on')}; corrections {len(report.get('corrections', []))}, accepted {len(report.get('accepted', []))}")
        if args.discover:
            for u in report.get("absent_words_unresolved", []):
                print(f"   ABSENT s.{u['section']:<5} [{u['word']}]  ...{u['context']}...")
            print(f"   ({len(report.get('absent_words_unresolved', []))} words not in the PDF; PDF check of the arrangement of sections: {report['pdf']['toc']['ok']})")
        if not args.report_only and not args.discover:
            entry["loaded_on"], entry["sections_loaded"], entry["pdf_as_on"] = report["loaded_on"], report["sections"], pdf.get("as_on")
            entry["text_status"] = "machine_checked" if not args.no_pdf else "unchecked"
            print("   wrote", write_act(entry, chunks, report, out_dir))
    if not args.report_only and not args.discover and reports:
        with open(os.path.join(out_dir, "LOAD_REPORT.json"), "w", encoding="utf-8") as fh:
            json.dump({"written": datetime.date.today().isoformat(), "reports": reports}, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        with open(args.manifest, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    if failed:
        print("FAILED:", failed)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
