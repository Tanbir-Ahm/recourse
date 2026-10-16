"""The three locks that keep an overruled decision from being stated as current law (register.py holds the facts; this file uses them).

    lock (a) before the model writes   retrieval_flags(): a retrieved passage whose own case is on the register is demoted and badged; a passage that merely mentions one is noted.
    lock (b) while the model writes    prompt_facts(): fixed lines for the prompt ("A was overruled by B (year); do not state A's holding as current law").
    lock (c) after the model wrote     guard_answer(): plain code scans the finished answer, including cases the model recalled from memory, and adds a standard clause for every register case
                                       that appears without a word of overruling next to it. This is the lock that matters most: it needs no cooperation from the model.

Nothing here decides law. A row is worded by what it says (register.Register.clause): firm for verified and reviewer-confirmed rows, "reported ... not yet confirmed by our reviewer" for candidates,
nothing for unchecked rows. A weak match (both names, no year) is never worded; it is listed for a person.

The Recourse site is read-only for this project: the patch for its owner is in REGISTER_SITE_PATCH.md.
"""
import re

from . import register as R

# a word of overruling that belongs to the mention: after it in its sentence (or the next one), or directly before it ("In overruling Mohan Lal ...", "the decision in")
_ACK = (r"overrul|over-rul|reversed|set aside|no longer (?:good )?law|not (?:a )?good law|per incuriam|not (?:a )?binding|disapprov|not approv|"
        r"(?:stands?|stood|been) (?:displaced|superseded)|held (?:not|to be (?:incorrect|wrong|bad))|bad in law|wrongly decided|no longer (?:holds|stands)")
ACK = re.compile(_ACK, re.I)
ACK_BEFORE = re.compile(r"(?:overrul(?:ing|ed)|disapprov(?:ing|ed)|revers(?:ing|ed)|not following|per incuriam)\s+(?:the\s+)?(?:(?:decision|judgment|view|ruling|case)\s+(?:in|of)\s+)?$", re.I)
MAX_FACTS = 8


_BACK_REF = re.compile(r"\s*(?:It|That|This|These|Those|Both|The (?:decision|judgment|case|ruling|view|holding)|However|But|Subsequently|Later|Thereafter|Since|Now)\b")


def acknowledged(text, start, end):
    """True if a word of overruling belongs to the mention: it follows the mention in the same sentence, or opens the next sentence when that refers back ('It was later overruled'), or directly
    precedes the mention ('In overruling X'). 'X was overruled by Y' acknowledges X, not Y; a neighbouring case's overruling does not count."""
    sents = R.sentences(text)
    for i, (s0, s1, _) in enumerate(sents):
        if s0 <= start < max(s1, s0 + 1):
            if ACK.search(text[end:s1]):
                return True
            if i + 1 < len(sents):
                n0, n1, ns = sents[i + 1]
                if _BACK_REF.match(ns) and ACK.search(ns[:160]):
                    return True
            break
    return bool(ACK_BEFORE.search(text[max(0, start - 80):start]))


# ----- lock (b) ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def prompt_facts(reg, texts, limit=MAX_FACTS):
    """Lines for the prompt about every register case named in `texts` (the question, the retrieved passages' case names, the passages). Unchecked rows give no line."""
    seen, lines = set(), []
    for t in texts:
        for h in reg.scan(t or ""):
            r = h["row"]
            if h["strength"] != "strong" or r["id"] in seen:
                continue
            group = [r] + reg.same_decision_rows(r)
            seen.update(x["id"] for x in group)
            c = reg.clause_group(group)
            if not c:
                continue
            lead = sorted((x for x in group if not R.unwordable(x)), key=lambda x: (R.TRUSTS.index(x["trust"]), x["id"]))[0]
            if lead["trust"] in R.TRUST_FIRM:
                lines.append(f"REGISTER FACT: {c} Do not state its holding as current law; if you mention it, say it was {reg.phrase(lead)}.")
            else:
                lines.append(f"REGISTER NOTE (not yet confirmed): {c} Do not state its holding as settled; if you mention it, say it is reported to have been {reg.phrase(lead)}.")
    return lines[:limit]


# ----- lock (a) ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def retrieval_flags(reg, chunks):
    """For each retrieved passage {case_name, citation, year, text?}: what the register says about its own case and about cases its text names.
    action: 'demote_and_badge' (own case, firm row), 'badge' (own case, candidate row), 'note' (a named case only), None."""
    out = []
    for i, c in enumerate(chunks):
        own = [h for h in reg.lookup_case(c.get("case_name"), c.get("year"), c.get("citation")) if h["strength"] == "strong" and reg.clause(h["row"])]
        men = [h for h in reg.scan(c.get("text") or "") if h["strength"] == "strong" and reg.clause(h["row"])] if c.get("text") else []
        men = [h for h in men if all(h["row"]["id"] != o["row"]["id"] for o in own)]
        if any(h["row"]["trust"] in R.TRUST_FIRM for h in own):
            action = "demote_and_badge"
        elif own:
            action = "badge"
        elif men:
            action = "note"
        else:
            action = None
        out.append({"index": i, "action": action, "own": [reg.clause(h["row"]) for h in own], "mentions": [reg.clause(h["row"], with_chain=False) for h in men],
                    "row_ids": [h["row"]["id"] for h in own + men]})
    return out


# ----- lock (c) ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def guard_answer(reg, answer):
    """Scan a finished answer. Returns {'findings': [...], 'notes': [sentences to add], 'review': [weak matches for a person], 'badge': bool}.
    A finding is acknowledged when the answer already says overruled/reversed/etc. next to the mention; only unacknowledged firm or candidate rows produce a note. A row whose overruling case
    was itself later overruled gets its chain note even when acknowledged, unless the answer already mentions that later step."""
    findings, notes, review, seen = [], [], [], set()
    for h in reg.scan(answer or ""):
        r = h["row"]
        if h["strength"] != "strong":
            review.append({"row_id": r["id"], "mention": answer[h["start"]:h["end"]], "why": "both party names but no year or citation: not worded as a fact"})
            continue
        ack = acknowledged(answer, h["start"], h["end"])
        group = [r] + reg.same_decision_rows(r)
        clause = reg.clause_group(group)
        findings.append({"row_id": r["id"], "how": h["how"], "trust": r["trust"], "treatment": r["treatment"], "mention": answer[h["start"]:h["end"]][:120], "acknowledged": ack,
                         "clause": reg.clause(r)})
        if r["id"] in seen or clause is None:
            continue
        seen.update(x["id"] for x in group)
        if not ack:
            notes.append(clause)
        else:
            later = []
            for x in group:
                for n in reg.chain(x):
                    if n["overruled"]["name"].lower().split(" v")[0] not in answer.lower():
                        later.append((x, n))
            if later:
                x, n = later[0]
                notes.append(f"{x['overruling']['name']} (cited above as the overruling decision) was itself later {reg.phrase(n)}; the current position should be checked.")
    return {"findings": findings, "notes": notes, "review": review, "badge": bool(notes)}


def _answer_says(reg, answer, group):
    """True when the answer names a case of this decision group (with or without a year) and says next to it that it was overruled or the like."""
    ids = {x["id"] for x in group}
    return any(h["row"]["id"] in ids and acknowledged(answer, h["start"], h["end"]) for h in reg.scan(answer or ""))


def extra_notes(reg, question, answer, base=None):
    """2026-10-16 (the four levels): the notes the page adds beyond guard_answer(), from the person's QUESTION as well as the answer. {'notes': [sentences in the register's firm or hedged wording],
    'possible': [sentences for name-only mentions]}. One note per overruled decision, the strongest level wins, and nothing is added for a decision the answer already speaks for (it names the case with
    a year and the guard notes it or the answer says overruled next to it).
      level 1  the question names the case with a year or citation and the answer neither names it nor says it was overruled -> the register's own clause (firm or 'reported ... not yet confirmed').
      level 2  both full party names, no year or citation, in the question or the answer -> Register.possible_clause ('Possible match: ...'); several decisions with that name are all listed.
      level 3  the QUESTION names a first party only ('Mohan Lal v. State') -> Register.list_clause: the register's decisions with that first party (at most ten shown).
      level 4  a bare name, or a first party made of common words -> nothing."""
    answer, question = answer or "", question or ""
    base = base if base is not None else guard_answer(reg, answer)
    done = set()
    for f in base["findings"]:
        row = reg.by_id.get(f["row_id"])
        if row:
            done |= reg.decision_ids(row)
    notes, possible = [], []
    for h in reg.scan(question):                                                  # level 1 from the question
        if h["strength"] != "strong":
            continue
        r = h["row"]
        ids = reg.decision_ids(r)
        if ids & done:
            continue
        group = [r] + reg.same_decision_rows(r)
        clause = reg.clause_group(group)
        done |= ids
        if clause is None or _answer_says(reg, answer, group):
            continue
        notes.append(clause)
    for source, text in (("question", question), ("answer", answer)):               # level 2
        by_pos = {}
        for h in reg.scan(text):
            if h["strength"] == "weak":
                by_pos.setdefault(h["start"], []).append(h)
        for _start, hs in sorted(by_pos.items()):
            groups = [g for g in reg.groups([h["row"] for h in hs]) if not (reg.decision_ids(g[0]) & done)]
            if not groups:
                continue
            ack = source == "answer" and acknowledged(answer, hs[0]["start"], hs[0]["end"])
            for g in groups:
                done |= reg.decision_ids(g[0])
            if ack:
                continue
            clause = reg.possible_clause([g[0] for g in groups], source)
            if clause and clause not in possible:
                possible.append(clause)
    for hit in reg.first_party_hits(question):                                     # level 3: the question only
        groups = [g for g in reg.groups(hit["rows"]) if not (reg.decision_ids(g[0]) & done)]
        if not groups:
            continue
        clause = reg.list_clause(hit["typed"], [g[0] for g in groups])
        for g in groups:
            done |= reg.decision_ids(g[0])
        if clause and clause not in possible:
            possible.append(clause)
    return {"notes": notes, "possible": possible}


def question_prompt_lines(reg, question, limit=MAX_FACTS):
    """Lock (b) for the person's own question: the REGISTER FACT / REGISTER NOTE lines for the cases it names with a year or citation (prompt_facts), and one 'REGISTER POSSIBLE MATCH' line for each
    case it names by both full party names without a year when that name belongs to one decision. Several decisions with one name, and first-party-only mentions, give no line (the page's note
    covers them). The lines say how the case was treated and nothing about what it held."""
    lines = prompt_facts(reg, [question], limit=limit)
    strong_ids = set()
    for h in reg.scan(question or ""):
        if h["strength"] == "strong":
            strong_ids |= reg.decision_ids(h["row"])
    by_pos = {}
    for h in reg.scan(question or ""):
        if h["strength"] == "weak":
            by_pos.setdefault(h["start"], []).append(h)
    done = set(strong_ids)
    for _start, hs in sorted(by_pos.items()):
        groups = [g for g in reg.groups([h["row"] for h in hs]) if not (reg.decision_ids(g[0]) & done)]
        if len(groups) != 1:
            continue
        lead = groups[0][0]
        done |= reg.decision_ids(lead)
        firm = lead["trust"] in R.TRUST_FIRM
        typed = question[hs[0]["start"]:hs[0]["end"]]
        lines.append(f'REGISTER POSSIBLE MATCH: the question names "{typed}". Our register {"lists" if firm else "reports"} {reg._label(lead)} as {reg.phrase(lead)}'
                     f'{"" if firm else " (not yet confirmed by our reviewer)"}. No year or citation was given, so we cannot be sure it is the same case; if it may be, say so plainly in your opening '
                     "paragraph and say how it was treated. Do not describe its holding as current law.")
    return lines[:limit]


def apply_notes(answer, result):
    """The answer with the standard block appended (the site may instead render the notes as a badge)."""
    if not result["notes"]:
        return answer
    block = "\n\nCurrency notes (from the Overruled Register, checked by code, not by the model):\n" + "\n".join(f"- {n}" for n in result["notes"])
    return answer.rstrip() + block
