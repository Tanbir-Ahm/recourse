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


MAX_CARRIED_CASES = 2


def _named_cases(a):
    """The library judgments an answer's own text names, from its stored matches: [match dict] with a passage, in the order handed over. Wider-search passages are not among them (they are not in `matches`)."""
    try:
        import answer_view
    except Exception:  # noqa: BLE001
        return []
    text = (a.get("response_text") or "").lower()
    out = []
    for m in a.get("matches") or []:
        if not isinstance(m, dict) or not m.get("case_name") or not str(m.get("text") or "").strip() or m.get("retrieval") in ("cited", "carried"):
            continue
        if answer_view.case_is_named(m, text):
            out.append(m)
    return out


def cases_from_turns(turns, limit=MAX_CARRIED_CASES):
    """Copies of the library judgment passages the earlier answers NAMED, marked retrieval 'carried', latest answer first, one per case, at most `limit`: they are offered again to a follow-up exactly as they were first handed over (the passage the answer
    saw), so the model can check them again; our conclusions about them are not carried. [] when none."""
    out, seen = [], set()
    for t in reversed(turns or []):
        a = t.get("answer") if isinstance(t, dict) else None
        if not isinstance(a, dict) or a.get("state") not in STATES:
            continue
        for m in _named_cases(a):
            key = str(m.get("case_name") or "").lower()
            if key in seen:
                continue
            seen.add(key)
            c = dict(m)
            c["retrieval"] = "carried"
            out.append(c)
            if len(out) >= limit:
                return out
    return out


def relied_on(turns, section_limit=8, case_limit=6):
    """What the earlier answers rested on, for the case-file panel: {'sections': [{'act','section'}], 'cases': [{'name','paragraph'}]} (the library cases an answer named). Display only."""
    sections = refs_from_turns(turns, limit=section_limit)
    cases, seen = [], set()
    for t in reversed(turns or []):
        a = t.get("answer") if isinstance(t, dict) else None
        if not isinstance(a, dict) or a.get("state") not in STATES:
            continue
        for m in _named_cases(a):
            key = str(m.get("case_name") or "").lower()
            if key in seen:
                continue
            seen.add(key)
            cases.append({"name": str(m.get("case_name")), "paragraph": str(m.get("paragraph_number") or "") or None})
            if len(cases) >= case_limit:
                return {"sections": sections, "cases": cases}
    return {"sections": sections, "cases": cases}
