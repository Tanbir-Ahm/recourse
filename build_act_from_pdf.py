"""
build_act_from_pdf.py -- loads an Act that India Code holds ONLY as a PDF (no section records in its database) onto the Act shelf (act_shelf/<key>.json).  Written 2026-10-31 for the Indian Evidence Act, 1872.

Why a second loader.  build_act_chunks.py takes each section from India Code's data API and checks it against India Code's PDF of the same Act: two sources.  A repealed central Act (the Evidence Act, repealed by the
Bharatiya Sakshya Adhiniyam, 2023 with effect from 1 July 2024) is kept by India Code as an archive stub: one record, one PDF (A1872-1.pdf), no section records, and the state copies are stubs too (checked 2026-10-31).
So there is ONE source here, and the checks are weaker.  The status written is therefore "machine_extracted", never "machine_checked":  the text is the PDF's own, cut into sections by program, and the checks below
show that the cutting is complete and in order, not that every word was read correctly.

What is checked (any failure stops the Act; nothing is written)
  1. the sections found in the PDF's running text equal the PDF's own ARRANGEMENT OF SECTIONS in number and ORDER, one heading line each (the manifest may list sections whose heading wording differs from the
     arrangement's: 'title_accepted', with the reason);
  2. the text is not empty and carries no footnote leftovers, page numbers or HTML;
  3. the PDF is read by TWO programs (PyMuPDF line by line, and Poppler's pdftotext on the same page area); every word of every section must be found in the Poppler reading's words (a way to see an extraction slip that only
     one of the two programs makes), and the two word sequences must agree for at least 99.5% of the words of each section (the layout engines break lines and hyphens differently, so equality is not demanded);
  4. State amendments printed inside a section (STATE AMENDMENT blocks) are moved to the field 'state_amendments' and replaced in the text by a one-line note, as build_act_chunks.py does;
  5. the Schedule (the list of repealed enactments) and the Preamble are not loaded.
What the checks cannot show:  that India Code's PDF is the law as amended (it is an archive copy; its date is not printed), that nothing in a bracketed amendment was lost in the PDF itself, or that a word the PDF
shares with both programs is right.  The first sheet for Mr. Advocate asks him to read a sample of sections against the Gazette.  Nothing is marked reviewed.

Usage (needs indiacode.gov.in reachable, PyMuPDF and pdftotext):
    python build_act_from_pdf.py --only evidence_act_1872
    python build_act_from_pdf.py --only evidence_act_1872 --report-only
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

import build_act_chunks as B
from build_act_chunks import LoadError

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(HERE, "act_shelf", "manifest.json")
STATE_NOTE = "[State amendments printed here by India Code are not part of the central Act and are not loaded.]"
HEADING_DASH = re.compile(r"(?:[–—]{1,3}|--+)\s*")


def norm_words(text):
    return B.norm_words(text)


def lines_of(data):
    """The running text (PyMuPDF, footnotes and furniture left out) as a list of right-stripped lines."""
    return [l.rstrip() for l in B.pdf_body_lines(data)]


def body_start(lines, preamble_pat):
    for i, ln in enumerate(lines):
        if re.search(preamble_pat, ln, re.I):
            return i + 1
    raise LoadError("the PDF's running text has no preamble line: cannot tell the body from the arrangement of sections")


def clean_body_lines(lines):
    """Drops page numbers (digit-only lines), chapter / part / group headings set in capitals (but not 'STATE AMENDMENT', which is kept as a marker) and stops at the Schedule."""
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if B.SCHEDULE_HEAD.match(s):
            break
        if re.fullmatch(r"\d{1,3}", s):
            continue
        if s != "STATE AMENDMENT" and B.is_caps_line(s):
            continue
        out.append(ln)
    return out


def find_headings(lines, toc):
    """For each arrangement entry, in order, the first line from the previous heading on that starts with its number: '106. Burden', '[54. Previous', '2.  [Repeal'. Returns [(index, number)]."""
    found, at = [], 0
    for num, _title in toc:
        pat = re.compile(r"^\s*\[?\s*%s\.\s" % re.escape(num))
        for i in range(at, len(lines)):
            if pat.match(lines[i]):
                found.append((i, num))
                at = i + 1
                break
        else:
            raise LoadError(f"section {num} of the arrangement has no heading line after the previous heading (line {at})")
    return found


def split_heading(first_line_and_more):
    """'106. Burden of proving ....--When ...' -> (title, rest).  The heading may wrap onto the next line (joined by the caller)."""
    m = re.match(r"^\s*\[?\s*(\d{1,3}[A-Z]{0,3})\.\s+(.*)$", first_line_and_more, re.S)
    if not m:
        raise LoadError("not a heading: " + first_line_and_more[:80])
    rest = m.group(2)
    d = HEADING_DASH.search(rest)
    if not d:
        return rest.strip().rstrip("."), ""
    return rest[:d.start()].strip(), rest[d.end():].strip()


def split_state_amendments(chunk_lines, headings_after):
    """Lines of one section -> (central lines, state-amendment lines): a block starts at a 'STATE AMENDMENT' line and runs to the end of the section's lines."""
    for i, ln in enumerate(chunk_lines):
        if ln.strip() == "STATE AMENDMENT":
            return chunk_lines[:i], chunk_lines[i + 1:]
    return chunk_lines, []


PARA_START = re.compile(r"^(\([a-zA-Z0-9]{1,6}\)|Illustrations?\b|Explanations?\b|Exceptions?\b|Provided\b|Proviso\b|\*\s*\*|[\u201c\"])")
LONE_HEAD = re.compile(r"^(Illustrations?|Explanations?|Exceptions?)\s*[.:\u2013\u2014-]*$")        # a line that is only such a word is a heading: the next line starts a new paragraph
LINE_END = re.compile(r"[.;:\u2014\u2013]\s*$")


def join_paragraphs(lines):
    """The PDF's lines are broken where the page's width ends. A line joins the one before it unless it starts a paragraph: an item '(a)' / '(1)', a heading word (Illustration, Explanation, Exception, Provided), an opening quotation mark,
    or the previous line ended a sentence (. ; : or a dash) and this one starts with a capital letter. A hyphen at the end of a line joins without a space only when the next word is lower-case ('police-' + 'officer')."""
    out = []
    for ln in lines:
        t = ln.strip()
        if not t:
            continue
        if not out:
            out.append(t)
            continue
        prev = out[-1]
        if PARA_START.match(t) or (LINE_END.search(prev) and re.match(r"^[A-Z(]", t)) or LONE_HEAD.match(prev):
            out.append(t)
        elif prev.endswith("-") and t[:1].islower():
            out[-1] = prev + t
        else:
            out[-1] = prev + " " + t
    return out


def cut_sections(lines, toc, loaded_on, act):
    heads = find_headings(lines, toc)
    chunks = []
    for k, (i, num) in enumerate(heads):
        j = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        block = lines[i:j]
        central, state = split_state_amendments(block, None)
        first = " ".join(x.strip() for x in central[:2]) if len(central) > 1 else central[0].strip()
        title_part, rest_first = split_heading(" ".join(x.strip() for x in central[:1]))
        # the heading may wrap: if the first line holds no dash, read the second line too
        if not HEADING_DASH.search(central[0]) and len(central) > 1:
            title_part, rest_first = split_heading(central[0].strip() + " " + central[1].strip())
            body_lines = ([rest_first] if rest_first else []) + [x.strip() for x in central[2:]]
        else:
            body_lines = ([rest_first] if rest_first else []) + [x.strip() for x in central[1:]]
        body = "\n".join(join_paragraphs(body_lines))
        text_title = re.sub(r"\s+", " ", title_part).strip()
        text_title = text_title.strip("[] ").strip()
        text = f"{num}. {text_title}\n{body}".rstrip()
        sa = "\n".join(join_paragraphs(state)) if state else ""
        if sa:
            text += "\n" + STATE_NOTE
        chunks.append({"act": act["code"], "act_key": act["key"], "act_name": act["name"], "citation": act["citation"], "section_number": num, "title": text_title, "text": text,
                       "footnotes": "", "omitted": bool(re.search(r"\b(repealed|rep\.|omitted)\b", body[:200], re.I)) and len(body) < 200, "order": k + 1, "uuid": None, "handle": None,
                       "source_url": act["sections_url"], "source_type": "primary", "loaded_on": loaded_on, "text_status": "machine_extracted", "last_modified": None,
                       "state_amendments": sa})
    return chunks


def compare_titles(chunks, toc, accepted):
    """The arrangement's first title sentence must open the heading's title (words only); a manifest entry accepts a different wording with a reason. Returns the list of mismatches that are not accepted."""
    acc = {str(a["section"]) for a in accepted or []}
    bad = []
    for c, (num, ttl) in zip(chunks, toc):
        assert c["section_number"] == num
        prim = (re.match(r"^(.*?\.[\u201d\"]?)(?:\s|$)", ttl.strip()) or re.match(r"^(.*)$", ttl.strip())).group(1)
        a, b = " ".join(norm_words(prim)), " ".join(norm_words(c["title"]))
        if not b.startswith(a) and num not in acc:
            bad.append({"section": num, "arrangement": ttl[:100], "heading": c["title"][:100]})
    return bad


def poppler_words(data):
    """Words of the whole PDF read by Poppler (pdftotext, raw reading order), for the second reading."""
    p = subprocess.run(["pdftotext", "-raw", "-", "-"], input=data, capture_output=True, check=True)
    words = norm_words(p.stdout.decode("utf-8", "replace"))
    return [re.sub(r"^([a-z]+)\d{1,2}$", r"\1", w) for w in words]           # a footnote number glued to a word ('affidavits8') is not part of the word


def _keep(ws):
    """Digit-only tokens and single letters other than 'a' and 'i' are dropped from BOTH readings before they are compared: they are footnote numbers, illustration letters and Poppler's spaced-out 'I n d i a C o d e' mark."""
    return [w for w in ws if not (w.isdigit() or (len(w) == 1 and w not in ("a", "i")))]


def second_reading(chunks, pop_words, window=400):
    """Compares each section with Poppler's reading of the same PDF.  4-word runs of the section that Poppler's text also holds are agreed.  The runs it does not hold are almost always places where Poppler
    has put a page's footnote text, the page mark or a footnote number INTO the sentence (PyMuPDF takes the footnotes out by their rule).  Such a run is EXPLAINED when the words of the section between the
    last agreed words before it and the first agreed words after it all occur, in the same order, inside a Poppler stretch of at most `window` words between those two anchors; it is UNEXPLAINED otherwise.
    Returns (unexplained runs, number of explained runs, words that Poppler never printed)."""
    pop = _keep(pop_words)
    vocab = set(pop)
    grams = set(zip(pop, pop[1:], pop[2:], pop[3:]))
    first3 = {}
    for k in range(len(pop) - 2):
        first3.setdefault(tuple(pop[k:k + 3]), []).append(k)
    unexplained, explained, absent = [], 0, []
    for c in chunks:
        text = c["text"].replace(STATE_NOTE, "")
        ws = _keep(norm_words(text))
        gs = list(zip(ws, ws[1:], ws[2:], ws[3:]))
        miss = sorted({w for w in ws if w not in vocab})
        if miss:
            absent.append({"section": c["section_number"], "words": miss[:10]})
        bad = [i for i, g in enumerate(gs) if g not in grams]
        runs = []
        for i in bad:
            if runs and i <= runs[-1][1] + 1:
                runs[-1][1] = i
            else:
                runs.append([i, i])
        for a, b in runs:
            lo, hi = max(0, a - 3), min(len(ws), b + 4 + 3)             # the agreed words just before and just after the run
            mine = ws[lo:hi]
            start_anchor, end_anchor = tuple(mine[:3]), tuple(mine[-3:])
            ok = False
            for p0 in first3.get(start_anchor, []):
                seg = pop[p0:p0 + len(mine) + window]
                j = 0                                                  # mine must be a subsequence of the Poppler stretch, and the stretch must end on the end anchor
                for w in seg:
                    if j < len(mine) and w == mine[j]:
                        j += 1
                if j == len(mine):
                    ok = True
                    break
            if ok:
                explained += 1
            else:
                unexplained.append({"section": c["section_number"], "words": " ".join(ws[max(0, a - 1):b + 5])})
    return unexplained, explained, absent


def build_act(entry, fetcher, loaded_on=None):
    loaded_on = loaded_on or datetime.date.today().isoformat()
    ic = entry["india_code"]
    act = {"key": entry["key"], "code": entry["code"], "name": entry["name"], "citation": entry["citation"], "sections_url": f"https://indiacode.gov.in/items/{ic['uuid']}"}
    item = fetcher.item(ic["uuid"])
    title = (B.md_first(item, "dc.title") or "")
    if entry["name"].split(",")[0].replace("The ", "").lower() not in title.lower():
        raise LoadError(f"India Code's record {ic['uuid']} is {title!r}, not {entry['name']!r}")
    name, data, pages = B.pick_english_pdf(fetcher.original_pdfs(ic["uuid"]), entry["name"])
    toc = B.parse_toc(pages)
    lines = lines_of(data)
    start = body_start(lines, entry.get("preamble_pattern", r"^\s*Preamble\.[–—-]+\s*WHEREAS"))
    body = clean_body_lines(lines[start:])
    chunks = cut_sections(body, toc, loaded_on, act)
    nums = [c["section_number"] for c in chunks]
    if nums != [n for n, _ in toc] or len(set(nums)) != len(nums):
        raise LoadError("the sections cut from the running text do not equal the arrangement of sections")
    bad_titles = compare_titles(chunks, toc, entry.get("title_accepted"))
    if bad_titles:
        raise LoadError("headings that differ from the arrangement of sections and are not accepted in the manifest: " + json.dumps(bad_titles, ensure_ascii=False)[:800])
    if any(not c["text"].split("\n", 1)[-1].strip() for c in chunks):
        raise LoadError("a section has no text: " + ", ".join(c["section_number"] for c in chunks if not c["text"].split("\n", 1)[-1].strip())[:200])
    if any(re.search(r"[<>]|&[a-z]+;|\bstyle=", c["text"]) for c in chunks):
        raise LoadError("HTML is left in a section")
    pop = poppler_words(data)
    unexplained, explained, absent = second_reading(chunks, pop)
    acc_missing = {(str(a["section"]), a["word"]) for a in entry.get("second_reading_accepted") or []}
    still = [m for m in ({"section": x["section"], "word": w} for x in absent for w in x["words"]) if (m["section"], m["word"]) not in acc_missing]
    if unexplained or still:
        raise LoadError("the second reading (Poppler) does not explain: runs " + json.dumps(unexplained, ensure_ascii=False)[:700] + " ; words Poppler never printed " + json.dumps(still)[:500])
    report = {"key": entry["key"], "loaded_on": loaded_on, "sections": len(chunks), "source": "PDF only (India Code holds no section records for this repealed Act)",
              "pdf": {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "pages": len(pages), "as_on": B.pdf_as_on(pages), "toc": {"ok": True, "about": "the sections cut from the running text equal the PDF's arrangement of sections in number and order"}},
              "absent_words_unresolved": [],
              "toc_equal": True, "titles_accepted": entry.get("title_accepted") or [], "second_reading": {"engine": "pdftotext -raw", "runs_explained_by_footnote_or_page_text": explained, "runs_unexplained": unexplained, "words_not_printed_by_poppler": still},
              "state_amendment_blocks": [c["section_number"] for c in chunks if c["state_amendments"]]}
    return chunks, report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=MANIFEST_PATH)
    ap.add_argument("--only", required=True)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)
    with open(args.manifest, encoding="utf-8") as fh:
        manifest = json.load(fh)
    entry = next((a for a in manifest["acts"] if a["key"] == args.only), None)
    if entry is None or entry.get("source") != "pdf_only":
        print("the manifest entry must exist and say \"source\": \"pdf_only\"")
        return 2
    try:
        chunks, report = build_act(entry, B.Fetcher())
    except LoadError as exc:
        print("FAILED:", exc)
        return 1
    print(f"{report['sections']} sections; PDF {report['pdf']['name']} ({report['pdf']['pages']} pages); second-reading runs explained by footnote/page text: {report['second_reading']['runs_explained_by_footnote_or_page_text']}, unexplained: {len(report['second_reading']['runs_unexplained'])}; words Poppler never printed: {len(report['second_reading']['words_not_printed_by_poppler'])}; State amendment blocks in sections {report['state_amendment_blocks']}")
    if args.report_only:
        return 0
    out_dir = os.path.dirname(os.path.abspath(args.manifest))
    path = os.path.join(out_dir, f"{entry['key']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(chunks, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    entry["loaded_on"], entry["sections_loaded"], entry["pdf_as_on"], entry["text_status"] = report["loaded_on"], report["sections"], report["pdf"]["as_on"] or B.NO_PDF_DATE, "machine_extracted"
    rp = os.path.join(out_dir, "LOAD_REPORT.json")
    merged = {}
    try:
        with open(rp, encoding="utf-8") as fh:
            merged = dict((json.load(fh) or {}).get("reports") or {})
    except (OSError, ValueError, AttributeError):
        merged = {}
    merged[entry["key"]] = report
    with open(rp, "w", encoding="utf-8") as fh:
        json.dump({"written": datetime.date.today().isoformat(), "reports": merged}, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    with open(args.manifest, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
