"""
build_bnss_schedule1.py -- the First Schedule of the Bharatiya Nagarik Suraksha Sanhita, 2023 ("Classification of offences"), read from the Gazette PDF the library already holds (raw_pdfs/bnss_2023_gazette.pdf) into schedules/bnss_schedule_I.json
(owner's go 2026-11-09: "Yes, build this change, then step 3"; research repository FOLLOW_UPS 2ef).

Why. The library's BNSS text has the Schedule's HEADINGS inside the huge s.531 chunk but none of its rows (a search of that chunk for "rape", "sexual" or "Voyeurism" finds nothing), so no answer could say whether an offence is cognizable or bailable
or which court tries it; every lawyers' note had to say "the classification is not shown in the material".

What it does. The table has six columns (section, offence, punishment, cognizable or non-cognizable, bailable or non-bailable, by what court triable) and no ruling lines, so each word of Part I is placed in its column by its position on the page, and a section's
block runs from its number in column 1 to the next section's number (a block that continues on the next page is continued). A section with several variants (for example 356(3) with two entries) keeps ALL its entries in order in each column; a summary field
(cognizable / non-cognizable / bailable / non-bailable) is filled ONLY when every entry of the column says the same, and is 'varies' or 'depends on the offence abetted' otherwise; nothing is inferred. Part II (offences against other laws) is kept as the Schedule's own text.

Status of the file: `machine_extracted` from ONE source (the Gazette PDF); nobody has read it. build() also checks that every section number it found exists in the library's BNS and reports the rows it could not place. Run: python build_bnss_schedule1.py
"""
import collections
import datetime
import json
import os
import re
import sys

import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = os.path.join(HERE, "raw_pdfs", "bnss_2023_gazette.pdf")
OUT = os.path.join(HERE, "schedules", "bnss_schedule_I.json")
COLS = [("section", 0, 90), ("offence", 90, 190), ("punishment", 190, 290), ("cognizable", 290, 382), ("bailable", 382, 452), ("court", 452, 600)]
SEC = re.compile(r"^\d{1,3}(?:\([0-9A-Za-z]+\))*$")


def col_of(xc):
    for name, a, b in COLS:
        if a <= xc < b:
            return name
    return "court"


def find_pages(doc):
    start = end = part2 = None
    for i, p in enumerate(doc):
        t = p.get_text()
        if start is None and "THE FIRST SCHEDULE" in t and "CLASSIFICATION OF OFFENCES" in t and "OFFENCES UNDER THE BHARATIYA NYAYA SANHITA" in t:
            start = i
        if start is not None and "THE SECOND SCHEDULE" in t:
            end = i
            break
    return start, end


def words_of(page, first):
    out = []
    for x0, y0, x1, y1, w, b, l, n in page.get_text("words"):
        if y1 < 100 or y0 > 745:             # page headers, the numbers row and the page foot
            continue
        out.append((x0, y0, x1, y1, w))
    return out


def build(log=print):
    doc = pymupdf.open(PDF)
    start, end = find_pages(doc)
    sections, cur = [], None
    part2_text = []
    in_part2 = False
    for pi in range(start, end):
        page = doc[pi]
        ws = words_of(page, pi == start)
        txt = page.get_text()
        if "II.—CLASSIFICATION OF OFFENCES AGAINST OTHER LAWS" in txt:
            in_part2 = True
        if in_part2:
            part2_text.append(txt)
        # the explanatory notes and the Part I heading on the first page: start below the row of column numbers "1 2 3 4 5 6" (y about 86 on later pages; on the first page below "I.—OFFENCES ...")
        if pi == start:
            ys = [w[1] for w in ws if w[4] == "I.—OFFENCES" or w[4].startswith("I.—OFFENCES")]
            top = max([w[3] for w in page.get_text("words") if w[4] == "6" and 70 < w[0] < 90] or [0])
            ws = [w for w in ws if w[1] > (top or 0) + 1]
        ws.sort(key=lambda w: (round(w[1]), w[0]))
        if in_part2:
            continue
        # section tokens: column 1, matching the pattern, starting a line
        marks = [w for w in ws if w[0] < 90 and SEC.match(w[4])]
        marks.sort(key=lambda w: w[1])
        # words before the first mark belong to the section that is still open (a block continued from the previous page)
        bounds = [(m[1] - 2, m) for m in marks]
        def assign(w):
            if not bounds or w[1] < bounds[0][0]:
                return None
            k = 0
            for j, (y, m) in enumerate(bounds):
                if w[1] >= y:
                    k = j
            return k
        blocks = collections.defaultdict(list)
        for w in ws:
            k = assign(w)
            blocks[k].append(w)
        for k in sorted(blocks, key=lambda z: (-1 if z is None else z)):
            if k is None:
                if cur is not None:
                    add(cur, blocks[k])
                continue
            m = bounds[k][1]
            if cur is not None:
                sections.append(cur)
            cur = {"section": m[4], "page": pi + 1, "cells": collections.defaultdict(list)}
            add(cur, [w for w in blocks[k] if not (w is m)])
    if cur is not None:
        sections.append(cur)
    rows = []
    for s in sections:
        cells = {c: re.sub(r"\s+", " ", " ".join(s["cells"].get(c, []))).strip() for c, _, _ in COLS[1:]}
        if all(re.fullmatch(r"\d", v) for v in cells.values() if v):          # the row of column numbers "1 2 3 4 5 6" at the top of a page, not a section
            continue
        n_c, n_b = len(_COG.findall(cells["cognizable"])), len(_BAIL.findall(cells["bailable"]))
        rows.append({"section": s["section"], "page": s["page"], **cells, "cognizable_summary": summarise(cells["cognizable"], "cognizable"), "bailable_summary": summarise(cells["bailable"], "bailable"),
                     "entries_misaligned": bool(n_c != n_b and "according as" not in (cells["cognizable"] + cells["bailable"]).lower())})
    part2 = "\n".join(part2_text)
    m = re.search(r"II\.—CLASSIFICATION OF OFFENCES AGAINST OTHER LAWS.*", part2, re.S)
    part2 = re.sub(r"[ \t]+", " ", m.group(0)).strip() if m else ""
    PART2_ROWS = [  # the three rows of Part II, read from the page text above (the extractor scrambles a table this small); the builder checks that each condition stands in the page text
        {"if": "If punishable with death, imprisonment for life, or imprisonment for more than 7 years.", "cognizable": "Cognizable.", "bailable": "Non-bailable.", "court": "Court of Session."},
        {"if": "If punishable with imprisonment for 3 years and upwards but not more than 7 years.", "cognizable": "Cognizable.", "bailable": "Non-bailable.", "court": "Magistrate of the first class."},
        {"if": "If punishable with imprisonment for less than 3 years or with fine only.", "cognizable": "Non-cognizable.", "bailable": "Bailable.", "court": "Any Magistrate."},
    ]
    flat = re.sub(r"\s+", " ", part2)
    for r in PART2_ROWS:
        assert r["if"].rstrip(".") in flat, "Part II condition not found in the page text: " + r["if"]
    doc_out = {"schema": "bnss-schedule-I-1", "part_II_rows": PART2_ROWS, "built": datetime.date.today().isoformat(), "status": "machine_extracted",
               "source": "Bharatiya Nagarik Suraksha Sanhita, 2023, The Gazette of India, the First Schedule (raw_pdfs/bnss_2023_gazette.pdf, pages %d to %d); one source, extracted by position on the page, not read by a person" % (start + 1, end),
               "columns": ["section", "offence", "punishment", "cognizable", "bailable", "court"], "rows": rows, "part_II": part2}
    return doc_out


def add(cur, words):
    byc = collections.defaultdict(list)
    for x0, y0, x1, y1, w in words:
        byc[col_of((x0 + x1) / 2)].append((round(y0 / 3), x0, w))
    for c, lst in byc.items():
        if c == "section":
            continue
        lst.sort()
        cur["cells"][c].extend(w for _, _, w in lst)


_COG = re.compile(r"\b(Non-?\s*cognizable|Cognizable)\b", re.I)
_BAIL = re.compile(r"\b(Non-?\s*bailable|Bailable)\b", re.I)


def summarise(text, kind):
    """'cognizable' / 'non-cognizable' ('bailable' / 'non-bailable') when every entry of the column says the same; 'depends on the offence abetted' for 'According as ...'; 'varies' when entries differ; '' when nothing is recognised ('Ditto' and the like)."""
    t = re.sub(r"\s+", " ", text or "")
    if re.search(r"according as", t, re.I):
        return "depends on the offence abetted"
    pat = _COG if kind == "cognizable" else _BAIL
    found = {re.sub(r"\s+", "", m.group(1)).lower().replace("non-", "non-") for m in pat.finditer(t)}
    if re.search(r"\bditto\b", t, re.I):
        return "varies" if len(found) > 1 else ""
    if len(found) == 1:
        return found.pop()
    return "varies" if len(found) > 1 else ""


def check(doc_out, log=print):
    import glob
    lib = set()
    for f in glob.glob(os.path.join(HERE, "chunks", "bharatiya_nyaya_sanhita_2023_chunks.json")):
        d = json.load(open(f, encoding="utf-8"))
        for r in (d if isinstance(d, list) else d.get("chunks", [])):
            if isinstance(r, dict) and r.get("section_number"):
                lib.add(str(r["section_number"]).split("(")[0])
    rows = doc_out["rows"]
    nums = [r["section"].split("(")[0] for r in rows]
    missing = sorted({n for n in nums if n not in lib}, key=lambda x: int(re.sub(r"\D", "", x) or 0))
    empty = [r["section"] for r in rows if not r["offence"] or not r["punishment"] or not r["cognizable"] or not r["bailable"] or not r["court"]]
    order = [int(re.sub(r"\D", "", n) or 0) for n in nums]
    inversions = sum(1 for a, b in zip(order, order[1:]) if b < a)
    mis = [r["section"] for r in rows if r.get("entries_misaligned")]
    log(f"rows whose cognizable and bailable columns hold a different number of entries (flagged, shown with a caution): {len(mis)} {mis[:20]}")
    log(f"{len(rows)} rows, {len(set(nums))} distinct sections; sections not in the library's BNS: {missing}; rows with an empty cell: {len(empty)} {empty[:15]}; order inversions: {inversions}")
    return {"misaligned": mis, "rows": len(rows), "distinct": len(set(nums)), "not_in_library": missing, "empty_cells": empty, "inversions": inversions}


if __name__ == "__main__":
    out = build()
    rep = check(out)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out["check"] = rep
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("wrote", OUT)
