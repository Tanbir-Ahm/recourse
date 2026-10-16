"""Fail-open hooks around the Overruled Register bundle (overruled_register/, exported by `python sci_goodlaw.py register-export-site`).
Order of lookup for a case: the register (person-confirmed rows firmly, candidates as "reported ... not yet confirmed"), then the cards overlay (the checker's reading, precomputed),
then the fixed "not checked by us" sentence. Nothing here ever says a case is good law. Every function returns its input unchanged (or empty notes) on any error, and REGISTER_HOOKS=off turns all of it off."""
import logging
import os
import re

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


def answer_notes(text, exclude_names=(), question=None):
    """Lock (c): {'notes': [sentences to show], 'possible': [name-only sentences], 'not_checked': one fixed sentence or None, 'review': [weak matches for a person]} for a finished answer.
    notes = the register's sentences, then the checker's warning cards (worded as the card words them); a quiet card adds nothing. `question` (2026-10-16, the four levels): the person's own words are
    read too: a case they name with a year or citation adds a note (level 1); a case named by both full party names without a year adds a 'Possible match' sentence (level 2, in the question or
    the answer); a first party only ('Mohan Lal v. State') adds the list of the register's decisions with that first party (level 3, the question only)."""
    empty = {"notes": [], "possible": [], "not_checked": None, "review": []}
    if _off():
        return empty
    try:
        from overruled_register import overlay as OV
        reg, ov = _load()
        res = OV.audit_answer(reg, ov, text or "", exclude_names=exclude_names, question=question)
        notes = list(res["register_notes"])
        for c in res["card_notes"]:
            notes.append(f'{c["case"]}: {c["note"]}')
        return {"notes": notes, "possible": list(res.get("possible") or []), "not_checked": res.get("not_checked_sentence"), "review": res["review"]}
    except Exception as exc:
        logger.warning("register guard failed: %s", exc)
        return empty


def question_block(question):
    """Lock (b) for the person's own question (2026-10-16): '' or a prompt section naming the register cases the question names with a year or citation (REGISTER FACT / REGISTER NOTE) or by both full party
    names without a year (REGISTER POSSIBLE MATCH, one decision only). The model is told to say plainly, in its opening paragraph, how the case was treated and to name the overruling case only as the
    one that overruled it. Never raises; REGISTER_HOOKS=off gives ''."""
    if _off() or not question:
        return ""
    try:
        from overruled_register import register_guard as G
        reg, _ = _load()
        lines = G.question_prompt_lines(reg, question)
        if not lines:
            return ""
        return ("\n\n## Overruled Register -- the person's own question names a case on our register (not optional)\n"
                "They may be about to rely on this case. In your OPENING paragraph, before anything else about it, tell them plainly, in your own words, how the case was treated. "
                "Name the overruling case only as the one that overruled it: do not describe what that case held. Do not state the older case's holding as current law. "
                "Saying that the older case was overruled by it is fine; do not suggest that the person cite, raise or rely on the overruling case for any other point, because you have not been shown what it held on that point.\n"
                + "\n".join(lines) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("register question block failed: %s", exc)
        return ""


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


_BACK_REF_SUFFIX = re.compile(r"\s*(?:\((?:I{1,3}|IV|[1-4])\)|[\u2019']s\s+cases?\b|\s+cases?\b|-(?:I{1,3}|IV)\b)", re.I)
_FOOTNOTE = re.compile(r"(?<=[A-Za-z])(\d{1,3})(?=[\s).,;:])")


def _loose_rows(reg, text):
    """Register rows whose overruled case a passage refers back to by its first party's words alone: three or more distinctive words in a row, none of them a common word such as a state or an office,
    followed by a back-reference mark: 'Raj Deo Sharma (II)', 'the Raj Deo Sharma case', 'Abdul Rehman Antulay's case'. A name without such a mark is not matched (the same first party often sits in a
    different case), and a two-word name ('Mohan Lal') is never matched this way. Used only to decide what to hand the model, never to word an answer."""
    from overruled_register import register as RR
    toks = RR.tokenize(text)
    found = {}                                                                 # first-party triple -> the rows it matched at this reading
    for i, (t, _s, _e) in enumerate(toks):
        for r in reg._by_first.get(t, ()):                                     # noqa: SLF001
            for s1, _s2 in reg._variants[r["id"]]:                             # noqa: SLF001
                if len(s1) < 3 or s1[0] != t or any(x in RR._GENERIC for x in s1[:3]):
                    continue
                j = reg._seq(toks, i, s1, 3)                                   # noqa: SLF001
                if j is not None and _BACK_REF_SUFFIX.match(text[toks[j - 1][2]:toks[j - 1][2] + 30]):
                    found.setdefault(tuple(s1[:3]), {})[r["id"]] = r
                    break
    out = {}
    for rows in found.values():
        decisions = {frozenset([rid] + [x["id"] for x in reg.same_decision_rows(r)]) for rid, r in rows.items()}
        merged = []
        for d in decisions:                                                    # rows of one decision count once; two different decisions with the same first party are ambiguous: skip
            if not any(d & m for m in merged):
                merged.append(set(d))
            else:
                for m in merged:
                    if d & m:
                        m |= d
        if len(merged) == 1:
            out.update(rows)
    return list(out.values())


def text_mentions(text):
    """For the wider-pool feed (sci_search_tier.py): the register cases that a passage NAMES (other than the passage's own case).
    {'lines': [REGISTER FACT / REGISTER NOTE lines for the prompt], 'clauses': [the register's own sentence for each, for the page], 'overruling': [(name, year), ...] of the case(s) that corrected them}.
    A case is found by a reported citation, by both party names with a year, or by its first party's distinctive words alone (see _loose_rows); a row with no wording (unchecked) gives nothing. Never raises."""
    empty = {"lines": [], "clauses": [], "overruling": []}
    if _off() or not text:
        return empty
    try:
        from overruled_register import register as RR
        from overruled_register import register_guard as G
        reg, _ = _load()
        text = _FOOTNOTE.sub(r" \1", text)                               # extracted judgments glue footnote numbers to words ('State of Bihar30)')
        rows = [h["row"] for h in reg.scan(text) if h["strength"] == "strong"] + _loose_rows(reg, text)
        lines, clauses, overruling, seen = [], [], [], set()
        for row in rows:
            if row["id"] in seen:
                continue
            group = [row] + reg.same_decision_rows(row)
            seen.update(x["id"] for x in group)
            clause = reg.clause_group(group)
            if not clause:
                continue
            o = row["overruled"]
            line = (G.prompt_facts(reg, [o["name"] + (f" ({o['year']})" if o.get("year") else "")], limit=1) or [None])[0]
            if not line:
                continue
            lines.append(line)
            clauses.append(clause)
            lead = sorted((x for x in group if reg.clause(x)), key=lambda x: (RR.TRUSTS.index(x["trust"]), x["id"]))[0]        # the firmest row: the case the REGISTER FACT line names as the corrector
            b = lead.get("overruling") or {}
            yr = (b.get("date") or "")[:4] or b.get("year")
            if b.get("name") and (b["name"], yr) not in overruling:
                overruling.append((b["name"], yr))
        return {"lines": lines, "clauses": clauses, "overruling": overruling}
    except Exception as exc:  # noqa: BLE001
        logger.warning("register text mentions failed: %s", exc)
        return empty


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
