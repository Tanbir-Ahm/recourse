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
            lead = sorted((x for x in group if x["trust"] not in R.NO_WORDING), key=lambda x: (R.TRUSTS.index(x["trust"]), x["id"]))[0]
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


def apply_notes(answer, result):
    """The answer with the standard block appended (the site may instead render the notes as a badge)."""
    if not result["notes"]:
        return answer
    block = "\n\nCurrency notes (from the Overruled Register, checked by code, not by the model):\n" + "\n".join(f"- {n}" for n in result["notes"])
    return answer.rstrip() + block
