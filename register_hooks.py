"""Fail-open hooks around the Overruled Register bundle (overruled_register/, exported by `python sci_goodlaw.py register-export-site`).
Order of lookup for a case: the register (person-confirmed rows firmly, candidates as "reported ... not yet confirmed"), then the cards overlay (the checker's reading, precomputed),
then the fixed "not checked by us" sentence. Nothing here ever says a case is good law. Every function returns its input unchanged (or empty notes) on any error, and REGISTER_HOOKS=off turns all of it off."""
import logging
import os

logger = logging.getLogger(__name__)
_STATE = {}


def _off():
    return os.environ.get("REGISTER_HOOKS", "on").strip().lower() in ("off", "0", "false", "no")


def _load():
    if "reg" not in _STATE:
        import overruled_register as OR
        _STATE["reg"] = OR.load()
        try:
            _STATE["ov"] = OR.load_overlay()
        except Exception as exc:  # the register alone still works
            logger.warning("cards overlay not loaded: %s", exc)
            _STATE["ov"] = None
    return _STATE["reg"], _STATE["ov"]


def prompt_lines_for_match(m):
    """Lock (b): lines for the prompt about the retrieved case itself."""
    if _off():
        return []
    try:
        from overruled_register import register_guard as G
        reg, _ = _load()
        return G.prompt_facts(reg, [" ".join(str(x) for x in (m.get("case_name"), m.get("year"), m.get("citation")) if x)])
    except Exception as exc:
        logger.warning("register prompt lines failed: %s", exc)
        return []


def demote_matches(matches):
    """Lock (a): a retrieved judgment whose own case is a firm register row goes to the end of the list and carries m['register_badge']; a candidate row only carries the badge."""
    if _off():
        return matches
    try:
        from overruled_register import register_guard as G
        reg, _ = _load()
        chunks = [{"case_name": m.get("case_name"), "year": m.get("year"), "citation": m.get("citation"), "text": None} for m in matches]
        flags = G.retrieval_flags(reg, chunks)
        keep, last = [], []
        for m, f in zip(matches, flags):
            if f["action"] in ("badge", "demote_and_badge") and isinstance(m, dict):
                m["register_badge"] = f["own"]
            (last if f["action"] == "demote_and_badge" else keep).append(m)
        return keep + last
    except Exception as exc:
        logger.warning("register demotion failed: %s", exc)
        return matches


def answer_notes(text, exclude_names=()):
    """Lock (c): {'notes': [sentences to show], 'not_checked': one fixed sentence or None, 'review': [weak matches for a person]} for a finished answer.
    notes = the register's sentences, then the checker's warning cards (worded as the card words them); a quiet card adds nothing."""
    empty = {"notes": [], "not_checked": None, "review": []}
    if _off():
        return empty
    try:
        from overruled_register import overlay as OV
        reg, ov = _load()
        res = OV.audit_answer(reg, ov, text or "", exclude_names=exclude_names)
        notes = list(res["register_notes"])
        for c in res["card_notes"]:
            notes.append(f'{c["case"]}: {c["note"]}')
        return {"notes": notes, "not_checked": res.get("not_checked_sentence"), "review": res["review"]}
    except Exception as exc:
        logger.warning("register guard failed: %s", exc)
        return empty


def result_flags(results):
    """For the wider-pool search tier (sci_search_tier.py): one dict per result, in order -- {'source': 'register'|'card'|'card_quiet'|'none', 'note': sentence or None}.
    The register first (firm or 'reported ... not yet confirmed'), then the cards overlay's warning or caution, else nothing; a quiet card is recorded but gives no sentence. Never raises."""
    out = [{"source": "none", "note": None} for _ in results]
    if _off():
        return out
    try:
        reg, ov = _load()
        for i, r in enumerate(results):
            name = r.get("case_name")
            if not name or r.get("name_to_review"):
                continue
            year = int(r["date"][:4]) if r.get("date") else None
            cits = r.get("citations") or {}
            def _one(v):                       # the names table holds a string for open-bucket judgments and a list for crawl judgments
                return v[0] if isinstance(v, (list, tuple)) and v else (v if isinstance(v, str) else None)
            cit = _one(cits.get("scr")) or _one(cits.get("insc")) or _one(cits.get("air")) or None
            hits = [h for h in reg.lookup_case(name, year, cit) if h["strength"] == "strong" and reg.clause(h["row"])]
            if hits:
                row = hits[0]["row"]
                out[i] = {"source": "register", "note": reg.clause_group([row] + reg.same_decision_rows(row)),
                          "overruling": row["overruling"]["name"], "overruling_year": (row["overruling"].get("date") or "")[:4] or row["overruling"].get("year")}
                continue
            e = ov.lookup(name, year, cit) if ov else None
            if e and e["kind"] in ("warning", "caution"):
                out[i] = {"source": "card", "note": e["note"]}
            elif e and e["kind"] == "quiet":
                out[i] = {"source": "card_quiet", "note": None}
    except Exception as exc:
        logger.warning("register result flags failed: %s", exc)
    return out


def case_status(name, year=None, citation=None):
    """For the lawyers' authorities table: one line saying where a case stands on our lists. {'source': 'register'|'card'|'card_quiet'|'not_checked'|'off', 'note': sentence}.
    The register first (firm or 'reported ... not yet confirmed'), then the cards overlay (warning, caution or quiet), else the fixed 'Not checked by us' sentence. Never says a case is good law. Never raises."""
    if _off():
        return {"source": "off", "note": "Register checks are switched off on this site."}
    try:
        reg, ov = _load()
        if not name:
            return {"source": "not_checked", "note": None}
        cit = citation if isinstance(citation, str) else None
        yr = int(year) if year not in (None, "") else None
        hits = [h for h in reg.lookup_case(name, yr, cit) if h["strength"] == "strong" and reg.clause(h["row"])]
        if hits:
            row = hits[0]["row"]
            return {"source": "register", "note": reg.clause_group([row] + reg.same_decision_rows(row))}
        e = ov.lookup(name, yr, cit) if ov else None
        if e and e["kind"] in ("warning", "caution"):
            return {"source": "card", "note": e["note"]}
        if e and e["kind"] == "quiet":
            return {"source": "card_quiet", "note": e["note"]}
        from overruled_register import overlay as OV
        return {"source": "not_checked", "note": OV.NOT_CHECKED}
    except Exception as exc:  # fail-open
        logger.warning("register case status failed: %s", exc)
        return {"source": "not_checked", "note": None}
