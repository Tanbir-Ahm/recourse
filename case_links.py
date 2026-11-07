"""
case_links.py -- where to read a judgment of the Supreme Court title index (added 2026-11-07, FOLLOW_UPS 2ds in the research repository).

The title index (case_lookup_index.db) knows 38,026 judgments by name, date and citation, with no text and no link. case_pdf_links.json.gz, written by build_case_links.py, ties each of them (38,016) to the PDF of the
judgment in the open Supreme Court bucket and 4,035 of them to the court's own address (api.sci.gov.in). link_for(case_id) returns the court's own address when there is one, else the bucket's. Nothing here says anything
about whether a case is good law, and a link is a link to a document, not a statement that the document is the right authority.

CASE_LINKS=off turns it off (a card then carries the Indian Kanoon search link only, as before). Any problem with the file leaves the old behaviour in place. Only https addresses on the two known hosts are ever returned.
"""
import gzip
import json
import os
import threading
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
HOSTS = {"api.sci.gov.in", "indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com"}
OFFICIAL_LABEL = "Read the judgment (Supreme Court website)"
MIRROR_LABEL = "Read the judgment (PDF copy)"
_LOCK = threading.Lock()
_STATE = {}


def path():
    return (os.environ.get("CASE_LINKS_PATH") or "").strip().strip("\"'") or os.path.join(HERE, "case_pdf_links.json.gz")


def enabled():
    return (os.environ.get("CASE_LINKS") or "").strip().strip("\"'").lower() not in ("off", "0", "false", "no")


def _ok(url):
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and u.hostname in HOSTS


def _load():
    p = path()
    st = _STATE.get(p)
    if st is not None:
        return st
    with _LOCK:
        st = _STATE.get(p)
        if st is not None:
            return st
        out = {"links": {}, "official": {}, "base": "", "built": None}
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("schema") == "case-pdf-links-1" and _ok(str(d.get("bucket_base") or "")):
                out = {"links": d.get("links") or {}, "official": d.get("official") or {}, "base": d["bucket_base"], "built": d.get("built")}
        except Exception:  # noqa: BLE001 -- a missing or unreadable file means no links, never an error
            pass
        _STATE[p] = out
        return out


def link_for(case_id):
    """{'url', 'kind', 'label'} for a title-index case id ('2014_INSC_463'), or None. kind is 'court_site_pdf' (the court's own address) or 'open_bucket_pdf' (the open bucket's copy, CC-BY-4.0, Dattam Labs)."""
    if not enabled() or not case_id:
        return None
    st = _load()
    cid = str(case_id).strip().replace(" ", "_")
    url = st["official"].get(cid)
    if url and _ok(url):
        return {"url": url, "kind": "court_site_pdf", "label": OFFICIAL_LABEL}
    key = st["links"].get(cid)
    if key:
        url = st["base"] + key.lstrip("/")
        if _ok(url):
            return {"url": url, "kind": "open_bucket_pdf", "label": MIRROR_LABEL}
    return None


def stats():
    st = _load()
    return {"bucket": len(st["links"]), "official": len(st["official"]), "built": st["built"]}
