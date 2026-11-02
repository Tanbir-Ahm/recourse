"""
carry_forward.py -- the sections an earlier answer in the same conversation relied on, offered again to a follow-up question (owner's go, 2026-11-02: "Carry the sections the earlier answer relied on into a follow-up's search, so BNSS 482
and 483 reach Q2").

The problem (staging, anticipatory bail): question 1 was answered from BNSS 482 and 483; the follow-up "Can the court cancel it later, and on what grounds?" searched on its own words and found BNSS 142 (security bonds for
keeping the peace), so the second answer said the material held no BNSS provision on anticipatory bail or its cancellation. A bare follow-up carries no subject of its own.

What this does, and what it does not:
  - It reads the STORED results of the earlier answers and takes the statute sections (library or Act shelf) that the answer's own text NAMES by number: a section that was only handed over and never used is not carried.
  - The sections travel as a separate list (never as words in the person's question: the engine treats the whole question string as the person's own words, and our words must not pass as theirs).
  - They are carried only when the new message is a follow-up (web_chat.should_carry): the rewrite judged it one, or it is a short message that points back ("what about him?").
  - The engine adds them to the sections it hands over, marked retrieval 'carried', with a line in the prompt that they were relied on earlier and are to be used only if they bear on the new question.
  - At most MAX_CARRIED sections, from the latest answers first. Nothing is carried from a refusal, a notice or small talk.
Pure functions, no model, no network.
"""
import re

MAX_CARRIED = 3
STATES = ("single_match", "conflicting_matches")


def _named_in(text, num):
    """True when `text` names section `num` ('Section 482', 'sections 482 and 483', 's. 482(1)'): the word 'section' or 's.' a few words before the number, the number a whole token."""
    n = re.escape(str(num))
    return bool(re.search(r"(?<![\w.])(?:sections?|sec\.|ss?\.)\s+[^.;:\n]{0,40}?(?<![\w.])" + n + r"(?![\w])", text or "", re.I))


def refs_from_turns(turns, limit=MAX_CARRIED):
    """[{'act', 'section', 'act_key'}] for the statute sections the earlier answers named, latest answer first, no repeats, at most `limit`. `turns`: [{'q', 'answer': the stored result}]."""
    out, seen = [], set()
    for t in reversed(turns or []):
        a = t.get("answer") if isinstance(t, dict) else None
        if not isinstance(a, dict) or a.get("state") not in STATES:
            continue
        text = a.get("response_text") or ""
        for m in a.get("matches") or []:
            if not isinstance(m, dict) or m.get("type") not in (None, "statute") or m.get("case_name") or not m.get("act") or m.get("section_number") in (None, ""):
                continue
            if m.get("retrieval") == "cited" or not m.get("text"):
                continue
            num = str(m["section_number"]).strip()
            key = (str(m["act"]).upper(), num.upper())
            if key in seen or not _named_in(text, num):
                continue
            seen.add(key)
            ref = {"act": str(m["act"]), "section": num}
            if m.get("act_key"):
                ref["act_key"] = str(m["act_key"])
            out.append(ref)
            if len(out) >= limit:
                return out
    return out
