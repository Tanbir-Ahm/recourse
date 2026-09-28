"""
add_pilot_case.py -- the mechanical half of adding one judgment to the pilot corpus, as one command.

Adding a case used to be ~a dozen identical hand-run steps (download, extract, save, chunk, collision
check, topic tag, embed, test search). Only the READING and JUDGING are real thinking; the rest is the
same every time and easy to slip on (e.g. the chunker builds the output filename from the case name, so
"State (NCT of Delhi)" produced a file with literal brackets in its name, fixed by hand twice).

TWO COMMANDS, and a case is never live until the second one:

    python add_pilot_case.py stage --link <api.sci.gov.in pdf> --name "<case name>" \
        --citation "<citation>" --topic <topic> [--date dd/mm/yyyy] [--question "..." ...]
        Downloads, extracts, chunks, collision-checks, tags, embeds, and test-searches -- into
        pilot_staging/<slug>/ ONLY. Prints a short report. Nothing enters the live pilot folders.

    python add_pilot_case.py approve <slug>
        Run ONLY after a person has read the case and approved it. Copies the staged files into
        pilot_corpus/ and pilot_chunks/. Refuses to overwrite, refuses anything that was blocked, and
        refuses a case whose quotes were never verified.

WHAT THIS NEVER DOES: read or judge a case; decide relevance; deploy; commit; or fix a problem silently.
A numbering collision, a wrong date in the PDF header, or an unreadable PDF BLOCKS the case and is shown,
because deciding what to do about it is a judgment call (see the Mhetre / Sushila Aggarwal cleanups).
"""
import argparse
import difflib
import html
import json
import os
import re
import shutil
import sys
from datetime import datetime

DEFAULT_STAGING_DIR = "pilot_staging"
DEFAULT_CORPUS_DIR = "pilot_corpus"
DEFAULT_CHUNKS_DIR = "pilot_chunks"
SOURCE_TYPE = "pilot_wider_tier"
MIN_PAGE_CHARS = 200          # same blank/scanned-page threshold build_judgment_corpus.py uses
MIN_TOTAL_CHARS = 1000
BIG_CHUNK_CHARS = 20000
EMBED_BATCH_CHARS = 60000     # comfortably under Voyage's 120,000-token-per-request cap
EMBED_BATCH_MAX_ITEMS = 100
_NAME_STOPWORDS = {"state", "union", "india", "and", "ors", "anr", "others", "another", "versus", "the", "of"}


class CaseError(Exception):
    """A precondition failed (already live, staging dir in use, unknown slug...). Not a blocked case."""


def slugify(name: str) -> str:
    """Same as chunk_judgments' own filename rule for ordinary names (lowercase, '.' and ',' dropped,
    spaces to underscores), plus every other non-alphanumeric run (brackets, hyphens...) becomes one
    underscore -- which is what fixes the '(NCT of Delhi)' filename."""
    s = name.lower().replace(".", "").replace(",", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _looks_like_pdf(data: bytes) -> bool:
    # sci.gov.in files carry a few junk bytes before the marker (b'%c\x00\x00%PDF-1.2'), so look
    # near the start rather than at byte 0.
    return b"%PDF-" in (data or b"")[:1024]


def download_pdf(link: str) -> bytes:
    import requests
    resp = requests.get(link, timeout=60)
    resp.raise_for_status()
    return resp.content


def extract_text(pdf_path: str):
    import fitz
    doc = fitz.open(pdf_path)
    pages = [p.get_text() for p in doc]
    doc.close()
    return "".join(pages), [len(p) for p in pages]


def parse_header(text: str) -> dict:
    """Reads the standard judis header (PETITIONER / RESPONDENT / DATE OF JUDGMENT / BENCH, plus the
    printed reporter line like '2000 (1) SCR 417'). Any field it can't find is simply absent -- newer
    or unusual PDFs may not have this header at all, and that is reported, not guessed around."""
    head = text[:2500]
    out = {}
    m = re.search(r"PETITIONER:\s*(.+?)\s*RESPONDENT:\s*(.+?)\s*DATE OF JUDGMENT:\s*(\d{1,2}/\d{1,2}/\d{4})"
                  r"\s*BENCH:\s*(.+?)\s*JUDGMENT:", head, re.S)
    if m:
        squash = lambda s: re.sub(r"\s+", " ", s).strip()
        # some judis PDFs print their own "Vs." line between the two parties
        out.update(petitioner=re.sub(r"\s+Vs\.?$", "", squash(m.group(1)), flags=re.I), respondent=squash(m.group(2)),
                   date=m.group(3), bench=squash(m.group(4)))
    r = re.search(r"\b\d{4}\s*\(\s*\d+\s*\)\s*(?:Suppl\.?\s*)?(?:SCR|SCC)\s*\d+\b", head)
    if r:
        out["reporter"] = re.sub(r"\s+", " ", r.group(0))
    return out


def _date_tuple(s: str):
    try:
        d, m, y = (int(x) for x in s.split("/"))
        return (y, m, d)
    except Exception:
        return None


def _distinctive_token(party: str):
    toks = [t for t in re.findall(r"[a-z]{4,}", party.lower()) if t not in _NAME_STOPWORDS]
    return max(toks, key=len) if toks else None


def check_identity(name: str, header: dict, head_text: str, expected_date=None):
    """(blockers, warnings). A date that contradicts the PDF's own header is a BLOCKER (wrong file).
    A missing/unreadable date, or a name token not found in the header, is a WARNING for a person."""
    blockers, warnings = [], []
    if expected_date:
        got = header.get("date")
        if not got:
            warnings.append("could not read a date from the PDF header, so the expected date was NOT verified")
        elif _date_tuple(got) != _date_tuple(expected_date):
            blockers.append(f"PDF header says the judgment date is {got}, but you said {expected_date} -- wrong file?")
    haystack = re.sub(r"[^a-z]", "", head_text.lower())
    parts = re.split(r"\s+(?:v|vs|versus)\.?\s+", name, maxsplit=1, flags=re.I)
    for party in parts:
        tok = _distinctive_token(party)
        if tok and tok not in haystack:
            warnings.append(f"the distinctive name word '{tok}' was not found near the top of the PDF -- confirm identity")
    return blockers, warnings


def _collisions(chunk_dir: str) -> list:
    from audit_pilot_paragraph_labels import find_paragraph_label_collisions
    return find_paragraph_label_collisions(chunk_dir)


SIM_WARN_BELOW = 0.90    # an Indian Kanoon copy this different from the official text: compare by hand
SIM_BLOCK_BELOW = 0.60   # this different: almost certainly a different or truncated document
MAX_SEQUENCE_WORDS = 12000
IK_SAME_SOURCE_NOTE = ("NOTE: this copy comes from the same source as the official file (in every case tested, even its "
                       "typos match), so it confirms MY copy is complete and unaltered. It does not independently "
                       "confirm the court's own wording.")


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _letters_index(text: str):
    chars, idx = [], []
    for i, ch in enumerate(text):
        if ch.isalnum():
            chars.append(ch.lower())
            idx.append(i)
    return "".join(chars), idx


def check_quote(quote: str, text: str, context: int = 150) -> dict:
    """Is this quote in the official text, word for word? Compared on letters and digits only, so
    line-break hyphens ('pre-sumed'), spacing and punctuation can't hide or fake a match -- but the
    result says which it was: 'exact', or 'cosmetic' (same words, differing only in hyphens/punctuation/
    spacing; the official wording is returned so a person sees the real text), or 'missing'. Also returns
    the text just before and after, so a person can see whether an exception sits next to the quote."""
    q = "".join(ch.lower() for ch in quote if ch.isalnum())
    if len(q) < 20:
        return {"status": "too_short"}
    hay, idx = _letters_index(text)
    pos = hay.find(q)
    if pos < 0:
        return {"status": "missing"}
    start, end = idx[pos], idx[pos + len(q) - 1] + 1
    # A quote's own leading/trailing punctuation (a full stop, an opening quotation mark) isn't part of
    # the letters-only match; carry it across when the official text really has it there, so it isn't
    # mistaken for a difference.
    stripped = quote.strip()
    lead = re.match(r"^[^\w\s]+", stripped)
    trail = re.search(r"[^\w\s]+$", stripped)
    if lead and text[max(0, start - len(lead.group())):start] == lead.group():
        start -= len(lead.group())
    if trail and text[end:end + len(trail.group())] == trail.group():
        end += len(trail.group())
    matched = _squash(text[start:end])
    return {"status": "exact" if matched == _squash(quote) else "cosmetic", "matched": matched,
            "before": _squash(text[max(0, start - context):start]), "after": _squash(text[end:end + context])}


def compare_texts(official: str, other: str) -> dict:
    """How alike are two copies of the same judgment? 'similarity' is a word-by-word sequence
    comparison (1.0 = identical; None when a text is too long for it to be quick); the two coverage
    numbers are the share of each text's 5-word phrases that also appear in the other, which is quick
    at any length and doesn't mind a header being added to one copy."""
    a = re.findall(r"[a-z0-9]+", official.lower())
    b = re.findall(r"[a-z0-9]+", other.lower())

    def shingles(w, n=5):
        return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}

    sa, sb = shingles(a), shingles(b)
    both = len(sa & sb)
    out = {"official_covered": both / len(sa) if sa else 0.0,
           "other_covered": both / len(sb) if sb else 0.0, "similarity": None}
    if a and b and len(a) <= MAX_SEQUENCE_WORDS and len(b) <= MAX_SEQUENCE_WORDS:
        out["similarity"] = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    return out


def _score(cmp: dict) -> float:
    return cmp["similarity"] if cmp["similarity"] is not None else min(cmp["official_covered"], cmp["other_covered"])


def _ik_plain(doc_json: dict) -> str:
    raw = (doc_json or {}).get("doc") or ""
    raw = re.sub(r"<(script|style).*?</\1>", " ", raw, flags=re.S | re.I)
    return _squash(html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def _ik_equivalent_citations(ik_text: str) -> str:
    m = re.search(r"Equivalent citations:(.*?)(?:Author:|Bench:|Cites\b|$)", ik_text[:1500])
    return _squash(m.group(1)) if m else ""


def _citation_keys(text: str) -> set:
    """'(2002) 1 SCC 241' and '2002 (1) SCC 241' are the same citation written two ways -- reduce both
    to (year, volume, reporter, page) so they can be compared."""
    keys = set()
    for m in re.finditer(r"\(\s*(\d{4})\s*\)\s*(\d+)\s*(SCC|SCR)\s*(\d+)", text):
        keys.add((m.group(1), m.group(2), m.group(3), m.group(4)))
    for m in re.finditer(r"(\d{4})\s*\(\s*(\d+)\s*\)\s*(?:Suppl\.?\s*)?(SCC|SCR)\s*(\d+)", text):
        keys.add((m.group(1), m.group(2), m.group(3), m.group(4)))
    return keys


def _title_date(title: str):
    m = re.search(r"\bon (\d{1,2}) ([A-Za-z]+),? (\d{4})", title)
    if not m:
        return None
    try:
        d = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
        return (d.year, d.month, d.day)
    except ValueError:
        return None


def _find_ik_case(name: str, expected_date, search_result: dict):
    """Picks the Indian Kanoon document for this case ONLY when exactly one search result matches both
    parties' distinctive name words and (if given) the expected date. Otherwise returns no pick and
    the candidates, for a person to choose from (--ik-doc-id)."""
    docs = (search_result or {}).get("docs", [])
    parts = re.split(r"\s+(?:v|vs|versus)\.?\s+", name, maxsplit=1, flags=re.I)
    toks = [t for t in (_distinctive_token(p) for p in parts) if t]
    exp = _date_tuple(expected_date) if expected_date else None
    cands, seen = [], set()
    for d in docs:
        title = re.sub(r"<[^>]+>", "", d.get("title") or "")
        letters = re.sub(r"[^a-z]", "", title.lower())
        tid = str(d.get("tid"))
        if tid in seen or not all(t in letters for t in toks):
            continue
        if exp and _title_date(title) != exp:
            continue
        seen.add(tid)
        cands.append((tid, title))
    if len(cands) == 1:
        return cands[0][0], cands[0][1], cands
    return None, None, cands


def _ik_query(name: str) -> str:
    """Indian Kanoon's search treats a formal case name as a bag of common words ('Ors', 'State',
    'Anr') and never finds the case -- confirmed live 2026-09-28 (the Palanitkar name returned ten
    unrelated High Court cases). The distinctive word from each party, limited to Supreme Court
    documents, finds the case first, followed by later judgments that cite it."""
    parts = re.split(r"\s+(?:v|vs|versus)\.?\s+", name, maxsplit=1, flags=re.I)
    toks = [t for t in (_distinctive_token(p) for p in parts) if t]
    return " ".join(toks + ["doctypes: supremecourt"])


def _phrase_groups_from_quotes(quotes) -> list:
    groups = []
    for q in quotes:
        toks = list(dict.fromkeys(t for t in re.findall(r"[a-z]{6,}", q.lower()) if t not in _NAME_STOPWORDS))
        toks = sorted(toks, key=len, reverse=True)[:3]
        if toks:
            groups.append(tuple(toks))
    return groups


def _real_ik_search(q):
    import indiankanoon_client as ik
    return ik.search(q)


def _real_ik_doc(tid):
    import indiankanoon_client as ik
    return ik.get_document(tid)


def _real_vaquill(token, sentence):
    import judgment_corroboration as jc
    import vaquill_search
    if not os.path.exists(vaquill_search.DB_PATH):
        return {"found_in_vaquill": None, "vaquill_case_id": None}
    return jc.cross_source_check(case_title_contains=token, holding_text=sentence)


def run_ik_checks(*, name, expected_date, ik_doc_id, official_text, quotes, citation,
                  search_fn, doc_fn, lines, warnings, blockers) -> dict:
    """Two Indian Kanoon checks from one search: (1) a full second copy to compare with the official
    text -- prints the similarity score -- and (2) other real documents describing this case the same
    way. Any failure (no network, no key, no balance) is a WARNING, never a crash and never a pass."""
    import judgment_corroboration as jc
    summary = {"ran": False}
    try:
        sr = search_fn(_ik_query(name))
    except Exception as exc:
        warnings.append(f"Indian Kanoon checks could not run ({type(exc).__name__}: {exc}) -- NOT a pass")
        return summary

    groups = _phrase_groups_from_quotes(quotes)
    if groups:
        cit = jc.corroboration_from_search_result(sr, groups)
        n = len(cit["corroborating_documents"])
        summary["citing_documents"] = f"{n} of {cit['documents_scanned']}"
        lines.append(f"Other documents describing this case the same way: {n} of {cit['documents_scanned']} scanned "
                     "(zero neither supports nor counts against the case)")

    tid, title, cands = (ik_doc_id, None, []) if ik_doc_id else _find_ik_case(name, expected_date, sr)
    if not tid:
        shown = "; ".join(f"{t}: {ti}" for t, ti in cands[:5]) or "none matched the name/date"
        warnings.append(f"could not pick the Indian Kanoon document automatically ({shown}) -- "
                        "rerun with --ik-doc-id <id> to get the similarity check")
        return summary
    try:
        doc = doc_fn(tid)
    except Exception as exc:
        warnings.append(f"could not fetch Indian Kanoon document {tid} ({type(exc).__name__}: {exc}) -- NOT a pass")
        return summary

    ik_text = _ik_plain(doc)
    cmp = compare_texts(official_text, ik_text)
    score = _score(cmp)
    summary.update(ran=True, doc_id=str(tid), similarity=cmp["similarity"],
                   official_covered=cmp["official_covered"], other_covered=cmp["other_covered"])
    lines.append(f"Indian Kanoon copy (document {tid}{': ' + title if title else ''}):")
    if cmp["similarity"] is not None:
        lines.append(f"  SIMILARITY to the official text: {cmp['similarity']:.4f}  (word by word; 1.0000 = identical)")
    else:
        lines.append("  Similarity: not computed (a text is too long for the word-by-word comparison); coverage below is used")
    lines.append(f"  Coverage: {cmp['official_covered']:.1%} of the official text's phrases are in the Indian Kanoon copy; "
                 f"{cmp['other_covered']:.1%} of the copy's phrases are in the official text")
    if quotes:
        hay, _ = _letters_index(ik_text)
        found = sum(1 for q in quotes if "".join(c.lower() for c in q if c.isalnum()) in hay)
        lines.append(f"  Quotes also in the Indian Kanoon copy: {found} of {len(quotes)}")
        summary["quotes_in_ik"] = f"{found} of {len(quotes)}"
    eq = _ik_equivalent_citations(ik_text)
    if eq:
        ok = bool(_citation_keys(citation) & _citation_keys(eq))
        summary["citation_listed"] = ok
        lines.append(f"  Citations Indian Kanoon lists: {eq[:200]}")
        lines.append(f"  The recorded citation {citation} is " + ("among them" if ok else "NOT among them"))
        if not ok:
            warnings.append(f"the recorded citation {citation} is not among Indian Kanoon's listed citations -- check it")
    lines.append("  " + IK_SAME_SOURCE_NOTE)
    if score < SIM_BLOCK_BELOW:
        blockers.append(f"the Indian Kanoon copy is only {score:.2f} similar to the official text -- probably a different or truncated document")
    elif score < SIM_WARN_BELOW:
        warnings.append(f"the Indian Kanoon copy is only {score:.2f} similar to the official text (under {SIM_WARN_BELOW}) -- compare by hand")
    return summary


def _vaquill_line(name, quotes, vaquill_fn, lines, warnings) -> str:
    if not quotes:
        return "not_checked"
    parts = re.split(r"\s+(?:v|vs|versus)\.?\s+", name, maxsplit=1, flags=re.I)
    tok = _distinctive_token(parts[0]) or _distinctive_token(name)
    try:
        res = (vaquill_fn or _real_vaquill)((tok or "").upper(), quotes[0])
    except Exception:
        res = {"found_in_vaquill": None}
    found = res.get("found_in_vaquill")
    if found is None:
        lines.append("Independent-origin copy (Vaquill, a scan of the printed law report): NONE AVAILABLE -- this is NOT a pass")
        return "none_available"
    if found:
        lines.append(f"Independent-origin copy (Vaquill): the key sentence's opening words ARE in it (case id {res.get('vaquill_case_id')})")
        return "found"
    lines.append("Independent-origin copy (Vaquill): exists, but the key sentence's opening words are NOT in it (its scan may be poor) -- check by hand")
    warnings.append("the independent-origin copy does not contain the key sentence's opening words -- check by hand")
    return "not_found"


def _batches_by_chars(texts, budget=EMBED_BATCH_CHARS, max_items=EMBED_BATCH_MAX_ITEMS):
    batch, size = [], 0
    for t in texts:
        if batch and (size + len(t) > budget or len(batch) >= max_items):
            yield batch
            batch, size = [], 0
        batch.append(t)
        size += len(t)
    if batch:
        yield batch


def _real_embed(texts):
    from dotenv import load_dotenv
    load_dotenv()
    import voyageai
    import embed_corpus
    client = voyageai.Client()
    out = []
    for batch in _batches_by_chars(texts):
        out.extend(embed_corpus.embed_batch(client, batch))
    return out


def _real_query_embed(question):
    from dotenv import load_dotenv
    load_dotenv()
    import pilot_tier_search
    return pilot_tier_search._embed_one(question)


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _search_report(questions, chunks, topic, chunks_dir, query_fn, lines):
    import pilot_tier_search as pts
    live = [c for c in pts.load_pilot_pool(chunks_dir) if c.get("topic") == topic] if os.path.isdir(chunks_dir) else []
    staged_name = chunks[0]["case_name"]
    for q in questions:
        qv = query_fn(q)
        best = {}
        for c in live + chunks:
            s = pts._cosine(qv, c["embedding"])
            if c["case_name"] not in best or s > best[c["case_name"]]:
                best[c["case_name"]] = s
        ranked = sorted(best.items(), key=lambda kv: -kv[1])
        mine = best[staged_name]
        pos = [n for n, _ in ranked].index(staged_name) + 1
        verdict = "ABOVE" if mine >= pts.PILOT_TIER_SIMILARITY_THRESHOLD else "BELOW"
        lines.append(f"  Q: {q[:80]}")
        lines.append(f"     this case scores {mine:.3f} ({verdict} the {pts.PILOT_TIER_SIMILARITY_THRESHOLD} threshold), "
                     f"rank {pos} of {len(ranked)} case(s) in topic '{topic}'")


def stage_case(*, link, name, citation, topic, expected_date=None, questions=(), quotes=(), pdf_bytes=None,
               staging_dir=DEFAULT_STAGING_DIR, corpus_dir=DEFAULT_CORPUS_DIR, chunks_dir=DEFAULT_CHUNKS_DIR,
               embed_fn=None, query_fn=None, replace=False, out=print,
               use_ik=True, ik_doc_id=None, ik_search_fn=None, ik_doc_fn=None, vaquill_fn=None) -> dict:
    from chunk_judgments import chunk_judgment

    slug = slugify(name)
    if os.path.exists(os.path.join(chunks_dir, f"{slug}_chunks.json")) or \
       os.path.exists(os.path.join(corpus_dir, f"{slug}.json")):
        raise CaseError(f"'{slug}' is already in the live pilot folders -- refusing to stage a duplicate")
    case_dir = os.path.join(staging_dir, slug)
    if os.path.exists(case_dir):
        if not replace:
            raise CaseError(f"{case_dir} already exists (a case in progress) -- use --replace to start it over")
        shutil.rmtree(case_dir)
    os.makedirs(case_dir)

    blockers, warnings, lines = [], [], []
    data = pdf_bytes if pdf_bytes is not None else download_pdf(link)
    lines.append(f"Case:           {name}  [{slug}]")
    lines.append(f"Topic:          {topic}")
    lines.append(f"Source:         {link}")

    text, chunks = "", []
    quotes_ok, vaquill_status, ik_summary = False, "not_checked", {"ran": False}
    if not _looks_like_pdf(data):
        blockers.append("the downloaded file is not a PDF (no %PDF marker) -- wrong link, or the site returned a web page")
    else:
        pdf_path = os.path.join(case_dir, "source.pdf")
        with open(pdf_path, "wb") as f:
            f.write(data)
        try:
            text, page_lens = extract_text(pdf_path)
        except Exception as exc:
            blockers.append(f"could not open the file as a PDF ({type(exc).__name__}: {exc})")
            page_lens = []
        if page_lens:
            lines.append(f"PDF:            {len(page_lens)} pages, {len(text):,} characters")
            for i, n in enumerate(page_lens, 1):
                if n < MIN_PAGE_CHARS:
                    warnings.append(f"page {i} has only {n} characters -- blank or scanned? read the PDF itself")
            if len(text) < MIN_TOTAL_CHARS:
                blockers.append(f"only {len(text)} characters of text in the whole PDF -- probably a scanned image, no usable text")

    if text and not blockers:
        header = parse_header(text)
        if header:
            lines.append(f"Header in PDF:  {header.get('petitioner')} v {header.get('respondent')} | "
                         f"date {header.get('date')} | bench {header.get('bench')}"
                         + (f" | {header['reporter']}" if header.get("reporter") else ""))
        else:
            first = [ln.strip() for ln in text.splitlines() if ln.strip()][:8]
            lines.append("Header in PDF:  standard header NOT found. First lines: " + " / ".join(first))
        b, w = check_identity(name, header, text[:2500], expected_date)
        blockers += b
        warnings += w

        record = {"case_name": name, "citation": citation, "source_url": link,
                  "source_type": SOURCE_TYPE, "text": text}
        _write_json(os.path.join(case_dir, "record.json"), record)
        chunks = chunk_judgment(record)
        methods = {}
        for c in chunks:
            methods[c["chunk_method"]] = methods.get(c["chunk_method"], 0) + 1
            c["topic"] = topic
        sizes = [len(c["text"]) for c in chunks]
        lines.append(f"Chunks:         {len(chunks)} ({methods}), sizes {min(sizes)}-{max(sizes)} characters")
        authors = sorted({c["opinion_author"] for c in chunks if c.get("opinion_author")})
        if len(authors) > 1:
            warnings.append(f"{len(authors)} separate opinions detected ({authors}) -- read each; numbering restarts per opinion")
        if max(sizes) > BIG_CHUNK_CHARS:
            warnings.append(f"a chunk is {max(sizes):,} characters -- chunking probably failed on part of this file")

        chunks_path = os.path.join(case_dir, f"{slug}_chunks.json")
        _write_json(chunks_path, chunks)
        found = _collisions(case_dir)
        for f_ in found:
            blockers.append(f"paragraph-number collision: {f_.get('error') or ('paragraph ' + str(f_['paragraph_number']) + ' points to ' + str(f_['distinct_texts']) + ' different texts')}")
        lines.append("Collision check: " + ("clean" if not found else f"{len(found)} PROBLEM(S) -- see BLOCKED below"))

        quotes_ok = bool(quotes)
        if not quotes:
            warnings.append("no --quote given: the key sentence(s) were NOT verified word for word, so this case cannot be approved")
        else:
            lines.append("Quote checks (word for word against the official PDF text):")
            for n, q in enumerate(quotes, 1):
                res = check_quote(q, text)
                short = (q[:80] + "...") if len(q) > 80 else q
                st = res["status"]
                if st == "exact":
                    lines.append(f"  [{n}] EXACT   \"{short}\"")
                elif st == "cosmetic":
                    lines.append(f"  [{n}] SAME WORDS, differing only in hyphens/punctuation/spacing. The official text reads: \"{res['matched'][:220]}\"")
                elif st == "too_short":
                    quotes_ok = False
                    lines.append(f"  [{n}] TOO SHORT to verify  \"{short}\"")
                    blockers.append(f"quote {n} is too short to verify (needs at least 20 letters)")
                else:
                    quotes_ok = False
                    lines.append(f"  [{n}] NOT FOUND  \"{short}\"")
                    blockers.append(f"quote {n} is NOT in the official text: \"{short}\"")
                if st in ("exact", "cosmetic"):
                    lines.append(f"        just before: \"...{res['before'][-150:]}\"")
                    lines.append(f"        just after:  \"{res['after'][:150]}...\"")
        vaquill_status = _vaquill_line(name, list(quotes), vaquill_fn, lines, warnings)
        ik_summary = {"ran": False}
        if use_ik:
            ik_summary = run_ik_checks(name=name, expected_date=expected_date, ik_doc_id=ik_doc_id, official_text=text,
                                       quotes=list(quotes), citation=citation,
                                       search_fn=ik_search_fn or _real_ik_search, doc_fn=ik_doc_fn or _real_ik_doc,
                                       lines=lines, warnings=warnings, blockers=blockers)
        else:
            lines.append("Indian Kanoon checks: skipped (--no-ik)")

    if chunks and not blockers:
        embeds = (embed_fn or _real_embed)([c["text"] for c in chunks])
        if len(embeds) != len(chunks) or not embeds or not embeds[0] or all(v == 0 for v in embeds[0]):
            blockers.append("embedding step returned the wrong number of vectors, or an empty/all-zero one")
        else:
            for c, e in zip(chunks, embeds):
                c["embedding"] = e
            _write_json(os.path.join(case_dir, f"{slug}_chunks.json"), chunks)
            lines.append(f"Embeddings:     {len(embeds)} of {len(chunks)} present, {len(embeds[0])} dimensions")
            if questions:
                lines.append("Test searches:")
                _search_report(questions, chunks, topic, chunks_dir, query_fn or _real_query_embed, lines)
            else:
                lines.append("Test searches:  none requested (pass --question to see how real questions score)")

    status = "blocked" if blockers else "staged"
    for w in warnings:
        lines.append(f"WARNING: {w}")
    for b in blockers:
        lines.append(f"BLOCKED: {b}")
    if status == "staged":
        lines.append(f"STAGED in {case_dir}. NOT live. After a person has read the case and approved it:")
        lines.append(f"    python add_pilot_case.py approve {slug}")
    else:
        lines.append("NOT staged for approval. Nothing was put in the live pilot folders.")

    report = "\n".join(lines)
    with open(os.path.join(case_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    _write_json(os.path.join(case_dir, "status.json"),
                {"slug": slug, "status": status, "case_name": name, "topic": topic,
                 "quotes_verified": bool(quotes_ok and not blockers), "independent_copy": vaquill_status,
                 "indian_kanoon": ik_summary, "blockers": blockers, "warnings": warnings})
    out(report)
    return {"slug": slug, "status": status, "blockers": blockers, "warnings": warnings, "case_dir": case_dir}


def approve_case(slug, *, staging_dir=DEFAULT_STAGING_DIR, corpus_dir=DEFAULT_CORPUS_DIR,
                 chunks_dir=DEFAULT_CHUNKS_DIR, out=print) -> dict:
    case_dir = os.path.join(staging_dir, slug)
    status_path = os.path.join(case_dir, "status.json")
    if not os.path.isfile(status_path):
        raise CaseError(f"no staged case called '{slug}' in {staging_dir}")
    with open(status_path, encoding="utf-8") as f:
        st = json.load(f)
    if st.get("status") != "staged":
        raise CaseError(f"'{slug}' is {st.get('status')}, not staged -- only a clean staged case can be approved"
                        + (f" (blockers: {st.get('blockers')})" if st.get("blockers") else ""))
    if not st.get("quotes_verified"):
        raise CaseError(f"'{slug}' was staged without its key quotes verified word for word against the official "
                        "text -- re-stage it with --quote (at least one) before it can be approved")
    src_chunks = os.path.join(case_dir, f"{slug}_chunks.json")
    src_record = os.path.join(case_dir, "record.json")
    with open(src_chunks, encoding="utf-8") as f:
        chunks = json.load(f)
    if not chunks or not all(c.get("embedding") and c.get("topic") for c in chunks):
        raise CaseError("the staged chunks are missing embeddings or a topic tag -- re-stage this case")
    dest_chunks = os.path.join(chunks_dir, f"{slug}_chunks.json")
    dest_record = os.path.join(corpus_dir, f"{slug}.json")
    for d in (dest_chunks, dest_record):
        if os.path.exists(d):
            raise CaseError(f"{d} already exists -- refusing to overwrite a live file")
    os.makedirs(chunks_dir, exist_ok=True)
    os.makedirs(corpus_dir, exist_ok=True)
    shutil.copyfile(src_chunks, dest_chunks)
    shutil.copyfile(src_record, dest_record)
    problems = [f for f in _collisions(chunks_dir) if f.get("file") == os.path.basename(dest_chunks)]
    st["status"] = "approved"
    _write_json(status_path, st)
    n_cases = len({json.load(open(p, encoding="utf-8"))[0]["case_name"]
                   for p in (os.path.join(chunks_dir, x) for x in os.listdir(chunks_dir) if x.endswith("_chunks.json"))})
    msg = [f"Approved: {slug} is now in {chunks_dir}/ and {corpus_dir}/.",
           "NOT committed, NOT deployed.",
           f"The live pilot pool now holds {n_cases} cases -- update the hardcoded case count in "
           "test_pilot_tier_search.py if it disagrees."]
    if problems:
        msg.append(f"WARNING: the collision check on the live copy found {len(problems)} problem(s)")
    out("\n".join(msg))
    return {"slug": slug, "cases_in_pool": n_cases}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage")
    s.add_argument("--link", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--citation", required=True)
    s.add_argument("--topic", required=True)
    s.add_argument("--date", help="expected judgment date, dd/mm/yyyy -- checked against the PDF's own header")
    s.add_argument("--question", action="append", default=[], help="a real question to test-search (repeatable)")
    s.add_argument("--pdf-file", help="use this local PDF instead of downloading --link")
    s.add_argument("--replace", action="store_true")
    s.add_argument("--quote", action="append", default=[],
                   help="a key sentence to verify word for word against the official text (repeatable, at least one)")
    s.add_argument("--ik-doc-id", help="Indian Kanoon document id, if the automatic pick can't be made")
    s.add_argument("--no-ik", action="store_true", help="skip the (paid) Indian Kanoon checks")
    a = sub.add_parser("approve")
    a.add_argument("slug")
    for p in (s, a):
        p.add_argument("--staging-dir", default=DEFAULT_STAGING_DIR)
        p.add_argument("--corpus-dir", default=DEFAULT_CORPUS_DIR)
        p.add_argument("--chunks-dir", default=DEFAULT_CHUNKS_DIR)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "stage":
            pdf = open(args.pdf_file, "rb").read() if args.pdf_file else None
            res = stage_case(link=args.link, name=args.name, citation=args.citation, topic=args.topic,
                             expected_date=args.date, questions=args.question, quotes=args.quote, pdf_bytes=pdf,
                             staging_dir=args.staging_dir, corpus_dir=args.corpus_dir,
                             chunks_dir=args.chunks_dir, replace=args.replace,
                             use_ik=not args.no_ik, ik_doc_id=args.ik_doc_id)
            return 0 if res["status"] == "staged" else 2
        approve_case(args.slug, staging_dir=args.staging_dir, corpus_dir=args.corpus_dir, chunks_dir=args.chunks_dir)
        return 0
    except CaseError as exc:
        print(f"REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
