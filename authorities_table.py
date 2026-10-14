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


def build(matches, named_cases, links, sci_cases, status_fn, bench_key="bench"):
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
                        "bench": next((m.get(bench_key) for m in ms if m.get(bench_key)), None), "tier": TIER_LIBRARY,
                        "status": SHORT_STATUS.get(st.get("source")) or st.get("note"), "status_source": st.get("source"),
                        "link": link_by_name.get(name) or next((m.get("source_url") for m in ms if isinstance(m.get("source_url"), str) and m["source_url"].startswith("http")), None)})
    wider, seen = [], set()
    for j in sci_cases or []:
        if not isinstance(j, dict) or not j.get("case_name") or j["case_name"] in seen:
            continue
        seen.add(j["case_name"])
        st = status_fn(j["case_name"], _year_of(j), _one(j.get("citation"))) or {}
        note = j.get("register_note") or SHORT_STATUS.get(st.get("source")) or st.get("note")
        wider.append({"case": j["case_name"], "year": _year_of(j), "citation": _one(j.get("citation")), "paragraphs": _paras([j]), "bench": j.get(bench_key), "tier": TIER_WIDER,
                      "status": note, "status_source": "register" if j.get("register_note") else st.get("source"), "link": j.get("link"),
                      "link_kind": j.get("link_kind")})
    return {"library": library, "wider": wider, "has_bench": any(r.get("bench") for r in library + wider)}


def _cell(text):
    return re.sub(r"\s+", " ", str(text or "")).replace("|", "\\|").strip()


def _table(rows, has_bench):
    head = ["Case", "Citation", "Paragraph"] + (["Bench"] if has_bench else []) + ["Where it stands on our lists", "Link"]
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for r in rows:
        name = _cell(r["case"]) + (f" ({r['year']})" if r.get("year") else "")
        link = f"[open]({r['link']})" if r.get("link") else "no link held"
        if r.get("link_kind") == "open_bucket_pdf":
            link += " (open bucket, CC-BY-4.0, Dattam Labs)"
        cells = [name, _cell(r.get("citation")) or "not held", ", ".join(r.get("paragraphs") or []) or "-"]
        if has_bench:
            cells.append(_cell(r.get("bench")) or "not held")
        cells += [_cell(r.get("status")) or "-", link]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_markdown(table):
    """[(heading, markdown table)] for the page; empty list when there is nothing to show."""
    out = []
    if table.get("library"):
        out.append(("Authorities (reviewed library)", _table(table["library"], table.get("has_bench"))))
    if table.get("wider"):
        out.append(("Further reading from a wider search (not independently verified)", _table(table["wider"], table.get("has_bench"))))
    return out
