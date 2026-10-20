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
  4. the strict, two-way, in-order comparison (2026-10-17): each section's text is read against the PDF's running text word by word, in order, in BOTH directions. A word that the database has and the PDF
     does not (a doubled 'or or', a lost apostrophe) and a run of words that the PDF has and the database lacks (a whole proviso) are both found, which check 3 cannot do (it asks only whether each word
     occurs SOMEWHERE in the PDF). The PDF's footnotes, page marks, chapter headings and footnote numbers are left out by layout (the rule India Code draws above the footnotes, the superscript size, capitals).
     Every difference left is either corrected in the manifest, or listed under 'ordered_accepted' with a reason (a harmless wording difference, the omitted-section stubs the PDF prints, the Schedules that
     follow the last section and are NOT loaded); anything else stops the Act, and so does an accepted entry that no longer matches anything.
  5. no HTML left over; the footnotes are kept (they carry the amendment history). Two tidy-ups are made and recorded: the heading that India Code repeats at the start of the body of an amended section
     ("[7. Offence ... .--Any public servant ...") is dropped, and the State or Union Territory amendments that India Code prints INSIDE a central section (under "STATE AMENDMENT") are moved to the field
     'state_amendments' and replaced in the text by a one-line note: they apply only in that State, and one of them was 84% of the text (and of the embedding) of PC Act s.17A.
  Only the numbered sections are loaded. The Schedules (POCSO: the armed and security forces; PMLA: the scheduled offences; UAPA: four Schedules; SC/ST Act: the table of IPC offences) are NOT: India Code's SCHEDULE
  records have an empty text field, their text exists only in the PDF, and the comparison ends where a Schedule begins. The Rules made under an Act are not loaded either.
  What the PDF check cannot show: that the text is the law today (India Code's PDF is a snapshot, its date is printed on its first page and recorded as 'pdf_as_on'; the database records are newer), or that
  India Code itself is right. The status stays 'machine_checked' until a person reads the sections (see the sheet for Mr. Advocate); the site words it "official text loaded <date>, not yet read by our reviewer".

Usage (needs indiacode.gov.in reachable, python 'requests' and PyMuPDF):
    python build_act_chunks.py                       # every Act in act_shelf/manifest.json
    python build_act_chunks.py --only pc_act_1988    # one Act
    python build_act_chunks.py --report-only         # fetch and check, print the report, write nothing
"""
import argparse
import datetime
import difflib
import hashlib
import html as _html
import itertools
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
NO_PDF_DATE = "not printed on the PDF"          # what the manifest records as 'pdf_as_on' when the PDF carries no "[As on the ...]" line (the Prevention of Damage to Public Property Act's PDF has none)


class LoadError(Exception):
    """A check failed: the Act is not written."""


# ----------------------------------------------------------------------------------------------- text helpers

def norm_words(text):
    """Lower-case words: the unit every check compares in (case, punctuation and typographic quotes do not matter)."""
    t = (text or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.findall(r"[a-z0-9]+", t)


def _norm_title(text):
    return " ".join(norm_words(text))


CMP_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def cmp_tokens(text):
    """The unit of the strict comparison: lower-case words and numbers, an apostrophe inside a word kept ("person's" is one word, "persons" is another: that is the point), typographic quotes read as plain."""
    return CMP_TOKEN.findall((text or "").lower().replace("\u2019", "'").replace("\u2018", "'"))


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


SCHEDULE_HEAD = re.compile(r"^\s*(THE\s+)?((FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH)\s+)?SCHEDULE\b")


def _fitz():
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    return fitz


def _footnote_rule_y(page):
    """India Code draws a thin filled rectangle (about 144pt wide, under 2pt high, at the left margin) above the footnotes of a page; its y, or None when the page has no footnotes. The lowest one counts."""
    ys = []
    for d in page.get_drawings():
        r = d["rect"]
        if (r.y1 - r.y0) < 2.0 and 100 < (r.x1 - r.x0) < 200 and r.x0 < 120 and r.y0 > page.rect.height * 0.3:
            ys.append(r.y0)
    return max(ys) if ys else None


def _is_furniture(span):
    """The 'IndiaCode' mark at the foot of every page, the page numbers and the rule lines. Words that India Code's PDF sets in a stand-in font (a stray 'y.' in Calibri) are text and stay."""
    font = span["font"]
    if font.startswith("Helvetica"):
        return True
    if font.startswith(("Calibri", "ArialMT")):
        return re.fullmatch(r"[\s\d_.\-]*", span["text"]) is not None
    return False


def pdf_body_lines(pdf_bytes):
    """The running text of the PDF, line by line, WITHOUT what is not the Act's text: the footnotes (everything below the footnote rule of a page), the page furniture, and the superscript footnote numbers
    (digits set at 8pt or less). Needs PyMuPDF."""
    doc = _fitz().open(stream=pdf_bytes, filetype="pdf")
    out = []
    for page in doc:
        ry = _footnote_rule_y(page)
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                if ry is not None and ln["bbox"][1] >= ry - 1:
                    continue
                spans = [sp for sp in ln["spans"] if not _is_furniture(sp)]
                txt = "".join(sp["text"] for sp in spans if not (sp["size"] <= 8.0 and re.fullmatch(r"\s*\d+\s*", sp["text"])))
                if txt.strip():
                    out.append(txt)
    return out


def is_caps_line(line):
    """A heading set in capitals (CHAPTER III, PART A, THE FIRST SCHEDULE, STATE AMENDMENT): letters all capital and no digit in the line ('1[14A.' is a section number, not a heading)."""
    letters = re.sub(r"[^A-Za-z]", "", line or "")
    return bool(letters) and letters == letters.upper() and not re.search(r"\d", line)


def body_text(lines):
    """The Act's own text from the PDF's lines: after the enacting words, capital-letter headings left out, ending where a Schedule begins (the Schedules are not loaded). LoadError if the enacting words are absent."""
    enacting, start = re.compile(r"enacted\s+by\s+parliament", re.I), None
    for i, ln in enumerate(lines):
        if enacting.search(ln):
            start = i + 1
            break
        if i + 1 < len(lines) and enacting.search(ln + " " + lines[i + 1]):          # 'BE it enacted by' / 'Parliament in the ... Year ... as follows:'
            start = i + 2
            break
    if start is None:
        raise LoadError("the PDF's running text has no 'enacted by Parliament': the Act's body cannot be told from its front matter")
    kept = []
    for ln in lines[start:]:
        if is_caps_line(ln.strip()):
            if SCHEDULE_HEAD.match(ln.strip()):
                break
            continue
        kept.append(ln)
    return "\n".join(kept)


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


def compare_toc(toc, chunks, toc_absent=()):
    """The PDF's arrangement of sections against what was loaded: same numbers, same order, same titles (words only, 'non-compliance' = 'noncompliance').
    `toc_absent` are section numbers the manifest declares the PDF's printed arrangement-of-sections omits although the PDF's BODY has them (a real section the front index was not updated for, e.g. an
    amendment-inserted section); they are allowed to be 'only in loaded' and are ignored for the order check, but the section's text is still verified against the PDF's running text by ordered_compare, so the
    guarantee that every loaded section is in the PDF is not weakened. A declared number that is NOT actually only-in-loaded is reported in 'toc_absent_unused' and makes the load fail (a stale declaration)."""
    absent = set(toc_absent or ())
    t_nums, c_nums = [n for n, _ in toc], [c["section_number"] for c in chunks]
    only_toc = [n for n in t_nums if n not in c_nums]
    only_loaded_all = [n for n in c_nums if n not in t_nums]
    only_loaded = [n for n in only_loaded_all if n not in absent]           # the ones that still fail the check
    toc_absent_seen = [n for n in only_loaded_all if n in absent]
    toc_absent_unused = [n for n in sorted(absent) if n not in only_loaded_all]
    order_nums = [n for n in c_nums if n not in absent]                     # the order check ignores the declared-absent sections
    tmap = {n: t for n, t in toc}
    squash = lambda s: "".join(norm_words(s))  # noqa: E731
    title_diffs = [(c["section_number"], c["title"], tmap[c["section_number"]]) for c in chunks
                   if c["section_number"] in tmap and squash(c["title"]) != squash(tmap[c["section_number"]])
                   and not (squash(c["title"]) in squash(tmap[c["section_number"]]) or squash(tmap[c["section_number"]]) in squash(c["title"]))]
    return {"toc_entries": len(toc), "loaded": len(chunks), "only_in_pdf": only_toc, "only_in_loaded": only_loaded, "toc_absent_seen": toc_absent_seen, "toc_absent_unused": toc_absent_unused,
            "same_order": order_nums == t_nums, "title_differences": title_diffs,
            "ok": bool(toc) and not only_toc and not only_loaded and not toc_absent_unused and order_nums == t_nums and not title_diffs}


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
        whole = full_section_text(c)                      # the shelf's own note is not India Code's text; the State amendments set aside are
        body = whole.split("\n", 1)[1] if "\n" in whole else whole
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
    """Exact replacements the manifest lists: {'section', 'from', 'to', 'why', optional 'field': 'footnotes' or 'title', optional 'count': n}. Each must find its text exactly n times (default once) in that
    section; the text becomes the corrected text and the correction is recorded on the chunk. A 'title' correction changes the title AND the heading line ('N. Title') that starts the text; it is for the
    case where India Code's database title differs from the heading of the PDF's running text (the PDF's own arrangement of sections is not updated for amendments)."""
    by = {c["section_number"]: c for c in chunks}
    for fix in corrections or []:
        c = by.get(str(fix["section"]))
        if c is None:
            raise LoadError(f"correction for a section that was not loaded: {fix}")
        field = fix.get("field", "text")                 # 'text' (default), 'footnotes' or 'title'
        if field not in ("text", "footnotes", "title"):
            raise LoadError(f"correction field must be 'text', 'footnotes' or 'title': {fix}")
        want = int(fix.get("count", 1))                  # how many times the text occurs in that section: stated, so a correction can never hit more or less than the person who wrote it saw
        n = c[field].count(fix["from"])
        if n != want:
            raise LoadError(f"correction {fix['from']!r} in section {fix['section']} ({field}) matches {n} times (the manifest says {want})")
        c[field] = c[field].replace(fix["from"], fix["to"])
        if field == "title":
            head, sep, rest = c["text"].partition("\n")
            if head.count(fix["from"]) != 1:
                raise LoadError(f"title correction {fix['from']!r} in section {fix['section']}: the heading line {head!r} does not carry the title exactly once")
            c["text"] = head.replace(fix["from"], fix["to"]) + sep + rest
        c.setdefault("corrections", []).append({"field": field, "from": fix["from"], "to": fix["to"], "count": want, "why": fix.get("why", "")})
    return chunks


def check_corrections_in_pdf(corrections, vocab, pages, body=None):
    """A correction is itself checked: every word of the corrected wording must be in the PDF, and the corrected phrase (words only) must occur in the PDF text. `body` is the PDF's running text without its
    footnotes and footnote numbers (body_text): a phrase that the PDF prints with a footnote number inside it ('Power of 1[Chairman] to transfer') is found there."""
    flat = " ".join(norm_words("\n".join(pages)))
    flat_joined = " ".join(norm_words(re.sub(r"-\s*\n\s*", "", "\n".join(pages))))
    flat_body = " ".join(norm_words(body)) if body else ""
    bad = []
    for fix in corrections or []:
        words = norm_words(fix["to"])
        phrase = " ".join(words)
        if any(w not in vocab for w in words) or (phrase not in flat and phrase not in flat_joined and (not flat_body or phrase not in flat_body)):
            bad.append(fix)
    return bad


# ----------------------------------------------------------------------------------------------- two tidy-ups, and the strict comparison

STATE_AMENDMENT_LABEL = re.compile(r"^\s*STATE\s+AMENDMENTS?\s*:?\s*$", re.I)
NOTE_PREFIX = "[Note: India Code also prints State or Union Territory amendments of this section"


def _state_label(lines):
    """The name that follows the 'STATE AMENDMENT' label ('Karnataka', 'Arunachal Pradesh.--'), or None when the next line is not a name."""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        ln = re.sub(r"[\s.\-–—:]+$", "", ln)
        if not ln or len(ln) > 100 or re.match(r"(amendment|insertion|substitution|in section)\b", ln, re.I):
            return None
        return ln
    return None


def strip_repeated_heading(c):
    """India Code's body of an amended section starts with the section's number and heading again ("[7. Offence relating to public servant being bribed.-- Any public servant who,--"), and the chunk already
    starts with 'N. Title': the second heading is dropped (an opening bracket stays, so the brackets still balance). Only when it is the same number and title word for word. True when it was dropped."""
    head, sep, body = c["text"].partition("\n")
    ht = cmp_tokens(head)
    m = re.match(r"\s*(\[?)\s*", body)
    rest = body[m.end():]
    low = rest.lower().replace("\u2019", "'").replace("\u2018", "'")
    found = list(itertools.islice(CMP_TOKEN.finditer(low), len(ht)))
    if len(ht) < 2 or len(found) != len(ht) or [f.group() for f in found] != ht:
        return False
    rest = re.sub(r"^[\s.\-–—:,;]+", "", rest[found[-1].end():])
    c["text"] = head + sep + m.group(1) + rest
    return True


def set_aside_state_amendments(c):
    """A State or Union Territory amendment that India Code prints inside a central section (after a line 'STATE AMENDMENT') applies only there. It is moved to c['state_amendments'] and the text ends with a
    one-line note, so the answer model neither applies Karnataka's wording to everyone nor spends 8,500 characters on it. True when something was set aside."""
    lines = c["text"].split("\n")
    for i, ln in enumerate(lines):
        if STATE_AMENDMENT_LABEL.match(ln):
            central, tail = "\n".join(lines[:i]).rstrip(), "\n".join(lines[i:]).strip()
            label = _state_label(lines[i + 1:])
            c["state_amendments"] = tail
            c["text"] = central + "\n" + NOTE_PREFIX + (f" ({label})" if label else "") + "; they apply only there and are not set out here.]"
            return True
    return False


def tidy_chunks(chunks):
    """strip_repeated_heading and set_aside_state_amendments on every section; returns {'heading_repeated_removed': n, 'state_amendments_set_aside': [sections]}."""
    removed, aside = 0, []
    for c in chunks:
        if strip_repeated_heading(c):
            removed += 1
            c["heading_repeat_removed"] = True
        if set_aside_state_amendments(c):
            aside.append(c["section_number"])
    return {"heading_repeated_removed": removed, "state_amendments_set_aside": aside}


def full_section_text(c):
    """India Code's whole text of a section as the PDF prints it: the chunk's text without the note, then the State amendments that were set aside."""
    t = "\n".join(ln for ln in c["text"].split("\n") if not ln.startswith(NOTE_PREFIX))
    return t + ("\n" + c["state_amendments"] if c.get("state_amendments") else "")


def _find_seq(hay, needle, start):
    n = len(needle)
    for i in range(start, len(hay) - n + 1):
        if hay[i:i + n] == needle:
            return i
    return -1


def ordered_compare(chunks, pdf_text):
    """The strict comparison: each section against the PDF's running text, word by word, in order, both ways. `pdf_text` is body_text(...). Every non-omitted section is located in the PDF by its heading
    (number and title, the longest prefix that is found, in order); its words are then aligned (difflib) with the PDF's words up to the next section's heading. Returns
      {'sections', 'words', 'digits_ignored', 'diffs': [{'section', 'tag': 'delete'|'insert'|'replace', 'loaded', 'pdf', 'tail', 'loaded_ctx', 'pdf_ctx'}]}
    'loaded' is what the database has and the PDF does not, 'pdf' what the PDF has and the database does not ('tail': the PDF has more after the section's last word). Not counted as differences: the same
    letters split differently (a hyphen at a line end), and a bare number the PDF has (a footnote number set in full size). LoadError when a section cannot be located."""
    pdf = cmp_tokens(pdf_text)
    anchors, ptr = {}, 0
    for idx, c in enumerate(chunks):
        if c.get("omitted"):
            continue
        t = cmp_tokens(c["text"].split("\n", 1)[0])
        pos = -1
        for n in (6, 5, 4, 3, 2):
            if len(t) >= n:
                pos = _find_seq(pdf, t[:n], ptr)
                if pos >= 0:
                    break
        if pos >= 0:
            anchors[idx] = pos
            ptr = pos + 1
    missing = [c["section_number"] for idx, c in enumerate(chunks) if not c.get("omitted") and idx not in anchors]
    if missing:
        raise LoadError(f"section(s) {missing} cannot be located in the PDF's running text by their heading, so they cannot be compared")
    order = sorted(anchors.items())
    out = {"sections": 0, "words": 0, "digits_ignored": 0, "diffs": []}
    for k, (idx, pos) in enumerate(order):
        c = chunks[idx]
        a = cmp_tokens("\n".join(ln for ln in full_section_text(c).split("\n") if not is_caps_line(ln)))
        end = order[k + 1][1] if k + 1 < len(order) else min(len(pdf), pos + int(len(a) * 1.25) + 80)
        b = pdf[pos:end]
        out["sections"] += 1
        out["words"] += len(a)
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            lw, pw = a[i1:i2], b[j1:j2]
            if tag == "replace" and "".join(lw) == "".join(pw):
                continue
            if tag == "insert" and all(re.fullmatch(r"\d{1,3}[a-z]?", w) for w in pw):
                out["digits_ignored"] += 1
                continue
            out["diffs"].append({"section": c["section_number"], "tag": tag, "loaded": " ".join(lw), "pdf": " ".join(pw), "tail": tag == "insert" and i1 == len(a),
                                 "loaded_ctx": " ".join(a[max(0, i1 - 6):i2 + 6]), "pdf_ctx": " ".join(b[max(0, j1 - 6):j2 + 6])})
    return out


def _entry_matches(entry, d):
    if str(entry.get("section")) != d["section"]:
        return False
    if entry.get("pdf_starts") is not None:                                    # a tail: what the PDF prints after the section's last word
        return d["tail"] and not d["loaded"] and d["pdf"].startswith(" ".join(cmp_tokens(entry["pdf_starts"])))
    same = lambda x, y: sorted(cmp_tokens(x)) == sorted(cmp_tokens(y))         # noqa: E731 -- the same words, in whatever order the alignment found them
    return not d["tail"] and same(entry.get("loaded", ""), d["loaded"]) and same(entry.get("pdf", ""), d["pdf"])


def explain_differences(diffs, accepted):
    """The manifest's 'ordered_accepted' entries ({'section', 'loaded', 'pdf', optional 'count', 'why'} or {'section', 'pdf_starts', 'why'}) against the differences found. Returns (unexplained differences,
    accepted entries that matched nothing or fewer than their count). Both must be empty for the Act to load."""
    left = [dict(a, _left=int(a.get("count", 1))) for a in accepted or []]
    unexplained = []
    for d in diffs:
        for a in left:
            if a["_left"] > 0 and _entry_matches(a, d):
                a["_left"] -= 1
                break
        else:
            unexplained.append(d)
    unused = [{k: v for k, v in a.items() if k != "_left"} for a in left if a["_left"] > 0]
    return unexplained, unused


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
    cmp_ = compare_toc(toc, chunks, entry.get("toc_absent"))
    report["pdf"] = {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "pages": len(pages), "as_on": pdf_as_on(pages), "toc": cmp_}
    if not cmp_["ok"]:
        raise LoadError(f"the loaded sections do not equal the PDF's arrangement of sections: {json.dumps({k: v for k, v in cmp_.items() if k != 'ok'}, ensure_ascii=False)[:600]}")
    vocab = pdf_vocabulary(pages)
    body = body_text(pdf_body_lines(data))
    bad_fix = check_corrections_in_pdf(entry.get("corrections"), vocab, pages, body)
    if bad_fix:
        raise LoadError(f"a correction is not what the PDF reads: {bad_fix}")
    apply_corrections(chunks, entry.get("corrections"))
    report["tidy"] = tidy_chunks(chunks)
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
    ordered = ordered_compare(chunks, body)
    unexplained, unused = explain_differences(ordered["diffs"], entry.get("ordered_accepted"))
    report["ordered_check"] = {"sections_compared": ordered["sections"], "words_compared": ordered["words"], "bare_numbers_ignored": ordered["digits_ignored"], "differences": len(ordered["diffs"]),
                               "accepted_in_manifest": len(ordered["diffs"]) - len(unexplained), "unexplained": unexplained, "accepted_unused": unused}
    if unexplained and not discover:
        raise LoadError("the loaded text differs from the PDF's running text, and the manifest neither corrects nor accepts it: " +
                        "; ".join(f"s.{d['section']} [{d['tag']}] loaded={d['loaded'][:80]!r} pdf={d['pdf'][:80]!r} ...{d['pdf_ctx'][:80]}..." for d in unexplained[:8]))
    if unused and not discover:
        raise LoadError(f"the manifest accepts differences that are not (or no longer) there: {unused}")
    if any(re.search(r"[<>]|&[a-z]+;|\bstyle=", c["text"] + c.get("state_amendments", "") + c["footnotes"]) for c in chunks):
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
        oc = report.get("ordered_check") or {}
        strict = f"; strict comparison: {oc.get('words_compared')} words, {oc.get('differences')} differences, {oc.get('accepted_in_manifest')} accepted in the manifest" if oc else ""
        print(f"   {report['sections']} sections ({len(report['omitted_sections'])} omitted/repealed); PDF {pdf.get('name')} as on {pdf.get('as_on')}; corrections {len(report.get('corrections', []))}, accepted words {len(report.get('accepted', []))}{strict}")
        if args.discover:
            for u in report.get("absent_words_unresolved", []):
                print(f"   ABSENT s.{u['section']:<5} [{u['word']}]  ...{u['context']}...")
            print(f"   ({len(report.get('absent_words_unresolved', []))} words not in the PDF; PDF check of the arrangement of sections: {report['pdf']['toc']['ok']})")
            oc = report.get("ordered_check") or {}
            for d in oc.get("unexplained", []):
                print(f"   ORDERED s.{d['section']:<5} [{d['tag']}{', tail' if d['tail'] else ''}] loaded={d['loaded'][:100]!r} pdf={d['pdf'][:100]!r}\n         loaded: ...{d['loaded_ctx'][:140]}...\n         pdf   : ...{d['pdf_ctx'][:140]}...")
            for u in oc.get("accepted_unused", []):
                print(f"   ORDERED accepted but not found: {u}")
            print(f"   (strict comparison: {oc.get('sections_compared')} sections, {oc.get('words_compared')} words, {oc.get('differences')} differences, {oc.get('accepted_in_manifest')} accepted in the manifest, {len(oc.get('unexplained', []))} not explained)")
        if not args.report_only and not args.discover:
            entry["loaded_on"], entry["sections_loaded"], entry["pdf_as_on"] = report["loaded_on"], report["sections"], pdf.get("as_on") or NO_PDF_DATE
            entry["text_status"] = "machine_checked" if not args.no_pdf else "unchecked"
            print("   wrote", write_act(entry, chunks, report, out_dir))
    if not args.report_only and not args.discover and reports:
        report_path = os.path.join(out_dir, "LOAD_REPORT.json")
        merged = {}
        try:                                                    # a run with --only must not erase the reports of the Acts it did not load (found 2026-10-17, when the sixth and seventh Acts were added)
            with open(report_path, encoding="utf-8") as fh:
                merged = dict((json.load(fh) or {}).get("reports") or {})
        except (OSError, ValueError, AttributeError):
            merged = {}
        merged.update(reports)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump({"written": datetime.date.today().isoformat(), "reports": merged}, fh, indent=1, ensure_ascii=False)
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
