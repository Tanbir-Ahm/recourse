"""authorities_table.py -- the lawyers' module's table of authorities, built by CODE from what the answer was given (never written by the model, so no citation in it can be invented).

Two tiers, always shown apart:
  1. 'Reviewed library': the judgments in the site's own library that the answer names, with the register / card line beside each.
  2. 'Wider search (not independently verified)': Supreme Court passages from the sci-search tier that the answer read (feed mode) or lists (show mode).
Columns: case, citation (or 'not held'), paragraph(s), where it stands on our lists, link. A bench column is added only when the data carries it; the site's data does not hold bench size today, so it is left out rather than guessed.
Nothing here says a case is good law. Pure functions; the caller supplies the status function so the module needs no register to be tested.
"""
import re

# In the table a quiet card or a missing check gets a short line (the full sentences would repeat in every row); the register and warning-card sentences are kept whole.
SHORT_STATUS = {"not_checked": "Not checked by us.", "card_quiet": "No adverse later judgment found by our automatic check (silence, not a finding)."}
TABLE_NOTE = ("Where it stands on our lists: \"Not checked by us\" means neither our Overruled Register nor our automatic check covers the case. Neither list ever says that a decision is still good law. "
              "Please ask a lawyer before relying on any case here.")
TIER_LIBRARY = "Reviewed library"
TIER_WIDER = "Wider search (not independently verified)"
TIER_ANCHOR = "Verbatim excerpts"
_SC = "Supreme Court of India"               # a wider-search row with no court recorded is a Supreme Court one (the search service sent no court before 2026-10)


_LIB_COURTS = {}


def library_court(name, citation=None):
    """The court recorded for a reviewed-library judgment (the metadata record in corpus/<name>.json), or None when no record is found. 2026-11-12: the export and the page printed 'Supreme Court of India' for a Karnataka
    High Court judgment of the library (Sri Manjunath M P) because library rows carried no court at all and the default was the Supreme Court. Read once; every failure gives None (the cell then says 'not recorded')."""
    try:
        if not _LIB_COURTS:
            import glob
            import json
            import os
            here = os.path.dirname(os.path.abspath(__file__))
            by_name, by_cit = {}, {}
            for f in glob.glob(os.path.join(here, "corpus", "*.json")) + glob.glob(os.path.join(here, "pilot_corpus", "*.json")):
                try:
                    with open(f, encoding="utf-8") as fh:
                        d = json.load(fh)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(d, dict) or not d.get("case_name"):
                    continue
                court = str(d.get("court") or "").strip()
                if not court and "api.sci.gov.in/jonew/judis/" in str(d.get("source_url") or ""):
                    court = _SC                                                    # a pilot record with no court field whose source is the Supreme Court's own archive address
                if court:
                    by_name.setdefault(re.sub(r"\s+", " ", str(d["case_name"])).strip().lower(), court)
                    if d.get("citation"):
                        by_cit.setdefault(re.sub(r"\s+", " ", str(d["citation"])).strip().lower(), court)
            _LIB_COURTS.update({"name": by_name, "cit": by_cit, "ok": True})
        n = re.sub(r"\s+", " ", str(name or "")).strip().lower()
        c = re.sub(r"\s+", " ", str(citation or "")).strip().lower()
        return _LIB_COURTS["name"].get(n) or (_LIB_COURTS["cit"].get(c) if c else None)
    except Exception:  # noqa: BLE001
        return None


def _other_court(c):
    """True for a court that is not the Supreme Court of India (a Constitution Bench of it is still the Supreme Court)."""
    return bool(c) and not str(c).startswith(_SC)


def _paras(ms):
    out = []
    for m in ms:
        head = str(m.get("paragraph_number") or m.get("paragraph") or "").split("_")[0].strip()
        if head and head not in out:
            out.append(head)
    return out


def _year_of(m):
    y = m.get("year")
    if y:
        try:
            return int(y)
        except (TypeError, ValueError):
            pass
    d = str(m.get("date") or "")
    return int(d[:4]) if d[:4].isdigit() else None


def _one(v):
    return v[0] if isinstance(v, (list, tuple)) and v else (v if isinstance(v, str) else None)


def build(matches, named_cases, links, sci_cases, status_fn, bench_key="bench", anchors=None):
    """matches: the answer's retrieved matches; named_cases: case names the answer actually names (the caller decides how names are matched); links: cited_judgment_links;
    sci_cases: result['sci_related_judgments']; status_fn(name, year, citation) -> {'source','note'}. Returns {'library': [rows], 'wider': [rows], 'has_bench': bool}."""
    link_by_name = {l.get("case_name"): l.get("url") for l in (links or []) if isinstance(l, dict)}
    named = set(named_cases or [])
    grouped, order = {}, []
    for m in matches or []:
        if not isinstance(m, dict) or m.get("type") != "judgment" or not m.get("case_name") or m["case_name"] not in named:
            continue
        k = (m["case_name"], m.get("citation"))
        if k not in grouped:
            grouped[k] = []
            order.append(k)
        grouped[k].append(m)
    library = []
    for k in order:
        ms = grouped[k]
        name, cit = k
        st = status_fn(name, _year_of(ms[0]), cit if isinstance(cit, str) else None) or {}
        library.append({"case": name, "year": _year_of(ms[0]), "citation": cit if isinstance(cit, str) and cit.strip() else None, "paragraphs": _paras(ms),
                        "bench": next((m.get(bench_key) for m in ms if m.get(bench_key)), None), "tier": TIER_LIBRARY, "court": library_court(name, cit if isinstance(cit, str) else None),
                        "status": SHORT_STATUS.get(st.get("source")) or st.get("note"), "status_source": st.get("source"),
                        "link": link_by_name.get(name) or next((m.get("source_url") for m in ms if isinstance(m.get("source_url"), str) and m["source_url"].startswith("http")), None)})
    wider, seen = [], set()
    for j in sci_cases or []:
        if not isinstance(j, dict) or not j.get("case_name") or j["case_name"] in seen:
            continue
        seen.add(j["case_name"])
        st = status_fn(j["case_name"], _year_of(j), _one(j.get("citation"))) or {}
        note = j.get("register_note") or SHORT_STATUS.get(st.get("source")) or st.get("note")
        if j.get("passage_note"):                                   # PASSAGE_NOTES=on: whose voice the passage we read is in
            note = ((note + " ") if note else "") + "Reading note: " + j["passage_note"]
        wider.append({"case": j["case_name"], "year": _year_of(j), "citation": _one(j.get("citation")), "paragraphs": _paras([j]), "bench": j.get(bench_key), "tier": TIER_WIDER,
                      "status": note, "status_source": "register" if j.get("register_note") else st.get("source"), "link": j.get("link"),
                      "link_kind": j.get("link_kind"), "court": j.get("court") or _SC})
    ex_rows = []                                              # the verbatim excerpts (excerpt_anchors.py) the answer was given
    for j in anchors or []:
        if not isinstance(j, dict) or not j.get("case_name"):
            continue
        st = status_fn(j["case_name"], _year_of(j), _one(j.get("citation"))) or {}
        unconfirmed = j.get("status") != "reviewer_confirmed"
        ex_rows.append({"case": j["case_name"], "year": _year_of(j), "citation": _one(j.get("citation")), "paragraphs": [str(j["paragraph"])] if j.get("paragraph") else [], "bench": None,
                        "tier": TIER_ANCHOR, "status": ("Excerpt not yet confirmed by our reviewer. " if unconfirmed else "Excerpt confirmed by our reviewer. ") + (SHORT_STATUS.get(st.get("source")) or st.get("note") or ""),
                        "status_source": st.get("source"), "link": j.get("link")})
    out = {"library": library, "wider": wider, "anchors": ex_rows, "has_bench": any(r.get("bench") for r in library + wider)}
    if any(r.get("court") != _SC for r in wider) or any(_other_court(r.get("court")) for r in library):               # a Court column only when a wider-search or library row is not a Supreme Court one; otherwise the result is exactly what it was before
        out["has_court"] = True
    return out


def _cell(text):
    return re.sub(r"\s+", " ", str(text or "")).replace("|", "\\|").strip()


_PARA_OK = re.compile(r"\d+[A-Za-z]?(?:\s*(?:,|and|to|-|–)\s*\d+[A-Za-z]?)*(?:\s*\([A-Za-z ]+\))?")


def paragraph_label(p):
    """A paragraph label as the table shows it (2026-11-02): a number, a range or a list of numbers as written; the search index's own passage ids ('preamble/128', '423/5', '9/3') mean nothing to a reader -> 'not numbered'."""
    s = str(p or "").strip()
    if not s or s == "-":
        return s
    return s if _PARA_OK.fullmatch(s) else "not numbered"


def _table(rows, has_bench, has_court=False):
    """`has_court`: a Court column (only when some wider-search row is not a Supreme Court judgment; otherwise the table is the one that was here before the High Court judgments came)."""
    head = ["Case", "Citation", "Paragraph"] + (["Court"] if has_court else []) + (["Bench"] if has_bench else []) + ["Where it stands on our lists", "Link"]
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for r in rows:
        name = _cell(r["case"]) + (f" ({r['year']})" if r.get("year") else "")
        link = f"[open]({r['link']})" if r.get("link") else "no link held"
        import sci_search_tier as _T
        credit = _T.credit_for(r.get("link_kind"))                 # '' since 2026-11-02 (SOURCE_TAGS=on brings the tag back); the credit is in the page footer
        if credit:
            link += " (" + credit + ")"
        cells = [name, _cell(r.get("citation")) or "not held", ", ".join(paragraph_label(x) for x in (r.get("paragraphs") or [])) or "-"]
        if has_court:
            cells.append(_cell(r.get("court")) or "not recorded")
        if has_bench:
            cells.append(_cell(r.get("bench")) or "not held")
        cells += [_cell(r.get("status")) or "-", link]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_markdown(table):
    """[(heading, markdown table)] for the page; empty list when there is nothing to show."""
    out = []
    if table.get("library"):
        out.append(("Authorities (reviewed library)", _table(table["library"], table.get("has_bench"), bool(table.get("has_court")))))
    if table.get("anchors"):
        out.append(("Verbatim excerpts the answer read (copied word for word from the judgment; checked by code against the Supreme Court's own PDF)", _table(table["anchors"], table.get("has_bench"))))
    if table.get("wider"):
        out.append(("Further reading from a wider search (not independently verified)", _table(table["wider"], table.get("has_bench"), bool(table.get("has_court")))))
    return out
