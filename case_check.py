"""Case check: type one case, get what our Overruled Register and our automatic check say about it -- no model, no network, no cost, the same answer every time.

Order: the register (a person-confirmed row is worded firmly, a candidate row as "reported ... not yet confirmed by our reviewer"), then the checker's card for the 76 library cases (a warning is
shown with its quote; "no later adverse judgment found" is silence in the judgments we hold, not a finding about the law), then the fixed sentence "Not checked by us ...". A bare name ("the Mohan Lal case")
is never matched: the register recognises a case by its reported citation, or by both party names plus the year. Nothing here says a case is good law. Fail-open: any error gives the 'not available' result.
"""
import logging

logger = logging.getLogger(__name__)
ASK_MORE = ("To look a case up we need both party names and the year, for example Mohan Lal v. State of Punjab (2018), or its reported citation, for example (2018) 17 SCC 627. "
            "A single name is not enough: many cases share one.")
LIMIT = ("This check reads only our Overruled Register and an automatic check of 76 library cases. Finding nothing is not a finding that a case is still good law; "
         "a lawyer must confirm any case before it is cited.")


def check_case(text):
    """{'status': 'empty'|'need_more'|'register'|'card_warning'|'card_quiet'|'not_checked'|'unavailable', 'notes': [sentences], 'case': name or None, 'evidence': quote dict or None, 'limit': LIMIT}."""
    out = {"status": "empty", "notes": [], "case": None, "evidence": None, "limit": LIMIT}
    text = (text or "").strip()
    if not text:
        return out
    try:
        from overruled_register import overlay as OV
        from overruled_register import cites as C
        import register_hooks as RH
        if RH._off():
            return {"status": "unavailable", "notes": ["The case check is switched off."], "case": None, "evidence": None, "limit": LIMIT}
        reg, ov = RH._load()
        mentions = OV.case_mentions(text)
        cits = C.find_cites(text)
        name = mentions[0]["name"] if mentions else None
        year = mentions[0]["year"] if mentions else None
        cit = OV._key_text(cits[0][0]) if cits else None
        if cit == "":
            cit = None
        if not (name or cit):
            out.update(status="need_more", notes=[ASK_MORE])
            return out
        out["case"] = name or text[:120]
        hits = reg.lookup_case(name, year, cit)
        strong = [h for h in hits if h["strength"] == "strong" and reg.clause(h["row"])]
        if strong:
            row = strong[0]["row"]
            out.update(status="register", notes=[reg.clause_group([row] + reg.same_decision_rows(row))], case=name or row["overruled"]["name"])
            return out
        entry = ov.lookup(name, year, cit) if ov else None
        if entry is None and hits and not year and not cit:
            out.update(status="need_more", notes=["We hold a case with these party names, but without the year or the citation we cannot tell which one you mean. " + ASK_MORE])
            return out
        if entry is not None and entry["kind"] in ("warning", "caution"):
            out.update(status="card_warning", notes=[entry["note"]], evidence=entry.get("evidence"), case=entry["name"])
        elif entry is not None and entry["kind"] == "quiet":
            out.update(status="card_quiet", notes=[entry["note"]], case=entry["name"])
        else:
            out.update(status="not_checked", notes=[OV.NOT_CHECKED])
        return out
    except Exception as exc:  # noqa: BLE001 -- fail-open
        logger.warning("case check failed: %s", type(exc).__name__)
        return {"status": "unavailable", "notes": ["The case check is not available right now."], "case": None, "evidence": None, "limit": LIMIT}
