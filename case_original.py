"""
case_original.py -- fetch the ORIGINAL Supreme Court Reports page-image PDF of a judgment.

WHY (2026-09-20): the text we re-type from the dataset is OCR of scanned printed-book pages, so it
carries scan errors ('Jn' for 'In') however well it is cleaned. The scanned pages themselves are
perfectly legible, and they are published, free, in the open AWS bucket 'indian-supreme-court-judgments'
(CC-BY-4.0, maintained by Dattam Labs, sourced from the courts' sites, 1950-2025). Sending the page
images as they are gives the reader a book-quality document and removes every re-typing error.

The bucket names each file after the printed citation: data/pdf/year=YYYY/english/YYYY_<vol>_<start>_<end>_EN.pdf
so "[2017] 8 S.C.R. 785" -> 2017_8_785_851_EN.pdf. We list a year's files once (cached), pick the
file(s) starting at the cited page, DOWNLOAD it, and VERIFY the first pages carry the case's party
names before it is ever returned -- a wrong-case file is the worst failure this feature can have.
get_original() never raises: every failure is a status the caller turns into a fallback.
"""
import logging
import re
import time

import requests

logger = logging.getLogger("case_original")

BUCKET_URL = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com"
MAX_ORIGINAL_BYTES = 25 * 1024 * 1024      # bigger files fall back to the text PDF (memory + WhatsApp friendliness)
HTTP_TIMEOUT = 40
YEAR_CACHE_SECONDS = 6 * 3600              # the bucket is refreshed only every couple of months

CREDIT = ("Source: open dataset 'Indian Supreme Court Judgments' (Dattam Labs, CC-BY-4.0), "
          "which republishes the Supreme Court Reports.")

_SCR_RE = re.compile(r"\[(\d{4})\]\s*(?:Suppl?\.?\s*)?(\d+)\s*(?:Suppl?\.?\s*)?S\.?\s?C\.?\s?R\.?\s*(\d+)", re.I)
_KEY_RE = re.compile(r"/(\d{4})_(\d+)_(\d+)_(\d+)_EN\.pdf$")
_GENERIC = frozenset({
    "the", "and", "ors", "anr", "others", "another", "state", "union", "india", "versus", "vs", "thr", "through",
    "secretary", "ministry", "government", "govt", "pradesh", "of", "in", "re", "etc", "board", "commissioner",
    "corporation", "company", "limited", "ltd", "pvt", "department", "director", "general", "central",
    "bureau", "investigation", "police", "station", "officer", "national", "public", "petitioner", "respondent",
})

_YEAR_CACHE = {}   # year -> (fetched_at, {start_page: [(volume, key)]})


class TooLarge(Exception):
    pass


def parse_scr_citation(citation):
    """(year, volume, start_page) from '[2017] 8 S.C.R. 785' (also 'SUPP.' forms), else None."""
    m = _SCR_RE.search(citation or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# ---------------------------------------------------------------------------
# Bucket access (each is one small function so tests can replace it)
# ---------------------------------------------------------------------------

def _list_page(prefix: str, token: str = None):
    """One page (<=1000 keys) of the bucket listing -> ([keys], next_token_or_None)."""
    params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
    if token:
        params["continuation-token"] = token
    r = requests.get(BUCKET_URL + "/", params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    keys = re.findall(r"<Key>([^<]+)</Key>", r.text)
    nxt = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", r.text)
    return keys, (nxt.group(1) if nxt else None)


def _download(key: str, max_bytes: int) -> bytes:
    r = requests.get(f"{BUCKET_URL}/{key}", timeout=HTTP_TIMEOUT * 3, stream=True)
    r.raise_for_status()
    declared = int(r.headers.get("Content-Length") or 0)
    if declared > max_bytes:
        r.close()
        raise TooLarge(key)
    buf, size = [], 0
    for chunk in r.iter_content(256 * 1024):
        size += len(chunk)
        if size > max_bytes:
            r.close()
            raise TooLarge(key)
        buf.append(chunk)
    return b"".join(buf)


def _year_files(year: int) -> dict:
    hit = _YEAR_CACHE.get(year)
    if hit and time.time() - hit[0] < YEAR_CACHE_SECONDS:
        return hit[1]
    files, token = {}, None
    while True:
        keys, token = _list_page(f"data/pdf/year={year}/english/", token)
        for k in keys:
            m = _KEY_RE.search(k)
            if m:
                files.setdefault(int(m.group(3)), []).append((int(m.group(2)), k))
        if not token:
            break
    _YEAR_CACHE[year] = (time.time(), files)
    return files


def candidate_keys(citation) -> list:
    """Bucket keys whose file starts at the cited page: same volume first (a 'SUPP.' volume may be
    numbered differently, so other volumes are offered after it and rely on verification)."""
    parsed = parse_scr_citation(citation)
    if not parsed:
        return []
    year, vol, start = parsed
    found = _year_files(year).get(start, [])
    return [k for v, k in sorted(found, key=lambda x: (x[0] != vol, x[0]))]


# ---------------------------------------------------------------------------
# Verification: is this file really this case?
# ---------------------------------------------------------------------------

def _distinctive_tokens(title: str) -> list:
    words = re.findall(r"[a-z]{4,}", (title or "").lower())
    return list(dict.fromkeys(w for w in words if w not in _GENERIC))


def _close(a: str, b: str) -> bool:
    """Same word allowing one letter of scan noise."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1 or len(a) < 5:
        return False
    i = j = miss = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1; j += 1
        else:
            miss += 1
            if miss > 1:
                return False
            if len(a) > len(b): i += 1
            elif len(b) > len(a): j += 1
            else: i += 1; j += 1
    return miss + (len(a) - i) + (len(b) - j) <= 1


def verify_matches_case(pdf_bytes: bytes, title: str) -> bool:
    """True only if the first pages of the PDF carry the case's distinctive party-name words
    (allowing one letter of scan noise per word). A title with no distinctive words never passes."""
    wanted = _distinctive_tokens(title)
    if not wanted:
        return False
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = " ".join(doc[i].get_text() for i in range(min(2, len(doc))))
    except Exception:
        return False
    have = set(re.findall(r"[a-z]{4,}", text.lower()))
    hits = sum(1 for w in wanted if any(_close(w, h) for h in have))
    return hits >= max(1, -(-len(wanted) * 6 // 10))   # at least 60% (rounded up) of the distinctive words


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_original(case: dict) -> dict:
    """{'status': 'ok', 'bytes', 'key'} or {'status': not_found|mismatch|too_large|unreachable}.
    NEVER raises. Only a file that passed verification is ever returned as 'ok'."""
    try:
        keys = candidate_keys((case or {}).get("citation"))
    except Exception:
        logger.exception("case_original: bucket listing failed")
        return {"status": "unreachable"}
    if not keys:
        return {"status": "not_found"}
    worst = "mismatch"
    for key in keys:
        try:
            data = _download(key, MAX_ORIGINAL_BYTES)
        except TooLarge:
            worst = "too_large"
            continue
        except Exception:
            logger.exception("case_original: download failed for %s", key)
            return {"status": "unreachable"}
        if verify_matches_case(data, (case or {}).get("title")):
            return {"status": "ok", "bytes": data, "key": key}
    return {"status": worst}
