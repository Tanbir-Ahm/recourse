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
HC_COURT_HOSTS = {"ghconline.gov.in", "ghcservices.assam.gov.in"}
HC_BUCKET_HOST = "indian-high-court-judgments.s3.ap-south-1.amazonaws.com"
HC_OFFICIAL_LABEL = "Read the judgment (Gauhati High Court website)"
HC_MIRROR_LABEL = "Read the judgment (PDF copy)"
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
        out = {"links": {}, "official": {}, "official_list": {}, "extras": [], "base": "", "built": None}
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("schema") == "case-pdf-links-1" and _ok(str(d.get("bucket_base") or "")):
                ex = [e for e in (d.get("extras") or []) if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"].strip() and _ok(str(e.get("url") or ""))]
                out = {"links": d.get("links") or {}, "official": d.get("official") or {}, "official_list": d.get("official_list") or {}, "extras": ex, "base": d["bucket_base"], "built": d.get("built")}
        except Exception:  # noqa: BLE001 -- a missing or unreadable file means no links, never an error
            pass
        _STATE[p] = out
        return out


def hc_path():
    return (os.environ.get("HC_LINKS_PATH") or "").strip().strip("\"'") or os.path.join(HERE, "hc_links.json.gz")


def _hc_ok(url, hosts):
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme == "https" and u.hostname in hosts


def _hc_load():
    """The Gauhati High Court list written by build_hc_links.py: [{'name', 'date', 'year', 'case_no', 'neutral', 'court_url', 'copy_url'}]. An address on any other host is dropped; an entry with neither address is dropped."""
    p = hc_path()
    st = _STATE.get(("hc", p))
    if st is not None:
        return st
    with _LOCK:
        st = _STATE.get(("hc", p))
        if st is not None:
            return st
        out = []
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("schema") == "case-hc-links-1" and isinstance(d.get("fields"), list):
                f = d["fields"]
                for row in d.get("entries") or []:
                    if not isinstance(row, list) or len(row) != len(f):
                        continue
                    e = dict(zip(f, row))
                    if not isinstance(e.get("name"), str) or not e["name"].strip():
                        continue
                    cu = e.get("court_url") if e.get("court_url") and _hc_ok(e["court_url"], HC_COURT_HOSTS) else None
                    mu = e.get("copy_url") if e.get("copy_url") and _hc_ok(e["copy_url"], {HC_BUCKET_HOST}) else None
                    if not (cu or mu):
                        continue
                    date = e.get("date") if isinstance(e.get("date"), str) else None
                    year = int(date[:4]) if date and date[:4].isdigit() else None
                    out.append({"name": e["name"].strip(), "date": date, "year": year, "case_no": e.get("case_no") or None, "neutral": e.get("neutral") or None, "court_url": cu, "copy_url": mu})
        except Exception:  # noqa: BLE001 -- a missing or unreadable file means no list, never an error
            out = []
        _STATE[("hc", p)] = out
        return out


def hc_entries():
    """The Gauhati High Court judgments of the wide index with the court's own address and/or the open bucket's copy (empty when CASE_LINKS=off or the file is unusable)."""
    if not enabled():
        return []
    return _hc_load()


def hc_links(entry):
    """Card links for one hc_entries() item: the court's own address first, then the bucket copy."""
    out = []
    if entry.get("court_url"):
        out.append({"url": entry["court_url"], "kind": "high_court_site_pdf", "label": HC_OFFICIAL_LABEL})
    if entry.get("copy_url"):
        out.append({"url": entry["copy_url"], "kind": "high_court_bucket_pdf", "label": HC_MIRROR_LABEL})
    return out


def _official(st, cid):
    url = st["official"].get(cid) or st["official_list"].get(cid)
    return url if url and _ok(url) else None


def _mirror(st, cid):
    key = st["links"].get(cid)
    url = st["base"] + key.lstrip("/") if key else None
    return url if url and _ok(url) else None


def link_for(case_id):
    """{'url', 'kind', 'label'} for a title-index case id ('2014_INSC_463'), or None: the court's own address when there is one, else the open bucket's PDF. kind is 'court_site_pdf' (the court's own address) or
    'open_bucket_pdf' (the open bucket's copy, CC-BY-4.0, Dattam Labs)."""
    ls = links_for(case_id)
    return ls[0] if ls else None


def links_for(case_id):
    """Every address a card can offer for a title-index case id: the court's own first, then the open bucket's PDF copy (a second way to the same judgment: the court's address of some judgments was found from the court's list
    of its archive by name and date, and the copy lets a reader check it). [] when none."""
    if not enabled() or not case_id:
        return []
    st = _load()
    cid = str(case_id).strip().replace(" ", "_")
    out = []
    off = _official(st, cid)
    if off:
        out.append({"url": off, "kind": "court_site_pdf", "label": OFFICIAL_LABEL})
    mir = _mirror(st, cid)
    if mir:
        out.append({"url": mir, "kind": "open_bucket_pdf", "label": MIRROR_LABEL})
    return out


def extras():
    """The judgments of the wide index that have the court's own address and that the title index does not list: [{'name', 'date', 'year', 'scr', 'air', 'url'}] (empty when CASE_LINKS=off or the file is unusable). Only https addresses on the court's host are kept."""
    if not enabled():
        return []
    return _load()["extras"]


def stats():
    st = _load()
    hc = _hc_load() if enabled() else []
    return {"bucket": len(st["links"]), "official": len(st["official"]), "official_list": len(st["official_list"]), "extras": len(st["extras"]), "built": st["built"],
            "hc": len(hc), "hc_court_address": sum(1 for e in hc if e["court_url"]), "hc_copy": sum(1 for e in hc if e["copy_url"])}
