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


def answer_notes(text):
    """Lock (c): {'notes': [sentences to show], 'not_checked': one fixed sentence or None, 'review': [weak matches for a person]} for a finished answer.
    notes = the register's sentences, then the checker's warning cards (worded as the card words them); a quiet card adds nothing."""
    empty = {"notes": [], "not_checked": None, "review": []}
    if _off():
        return empty
    try:
        from overruled_register import overlay as OV
        reg, ov = _load()
        res = OV.audit_answer(reg, ov, text or "")
        notes = list(res["register_notes"])
        for c in res["card_notes"]:
            notes.append(f'{c["case"]}: {c["note"]}')
        return {"notes": notes, "not_checked": res.get("not_checked_sentence"), "review": res["review"]}
    except Exception as exc:
        logger.warning("register guard failed: %s", exc)
        return empty
