"""matter_depth.py -- W2 of MATTER_WORKSPACE_PLAN.md (research repo), built 2026-11-20 on the owner's "Go ahead with W1 and W2 together": the SIZE of the answer a question in a matter gets.

Sizes (the plan's section 4.2 and 4.3):
  file       the answer lives in the matter's documents (matter_routing's file path: one small call, no law)
  explain    explain named or charged sections: the text of the sections on hand (law_on_hand.py), one small call
  standard   apply the law on hand to the facts: the statute retrieval of the full path, but no judgments, no wider search, no scope check, no second answer, low thinking, a short shape
  research   today's full path (judgments, wider search, the research note); only for an explicit ask for cases or a detailed note, or a tap on 'Go deeper'
  draft      a request to draft a document (the fixed notice; drafting is not approved)
  smalltalk  thanks / hello: a fixed line, no model call
Unsure means STANDARD (the plan's decision D1, taken as recommended on the owner's go; his instruction of 2026-11-20 had been 'legal path when unsure').
Rules only, no model, no network. Switch MATTER_DEPTH = off | shadow | on (default off: nothing changes; shadow logs the size it would choose and changes nothing).
Written against half A of review_results/2026-11-20_matter_depth/planner_set.json (frozen 2026-11-20 in 8278a36); half B is run once.
"""
import os
import re

import matter_routing as MR

SIZES = ("file", "explain", "standard", "research", "draft", "smalltalk")


def mode():
    v = (os.environ.get("MATTER_DEPTH") or "").strip().strip("\"'").strip().lower()
    return v if v in ("shadow", "on") else "off"


def _norm(q):
    return " ".join((q or "").lower().replace("’", "'").split())


_SMALLTALK = re.compile(r"^(?:ok(?:ay)?[\s,.!]*)?(?:hi|hello|hey|hi there|hello there|good (?:morning|afternoon|evening)|thanks|thank you(?: so much| very much)?|thanks a lot|thank u|many thanks|great,? thanks|ok thanks|got it|ok|okay|alright|cool|noted|fine)[\s.!]*$", re.I)

_RESEARCH = [
    ("judgments", re.compile(r"\bjudg(?:e)?ments?\b|\bdecisions?\s+(?:of|on|by)\b|\brulings?\b")),
    ("case_law", re.compile(r"\bcase[- ]?laws?\b|\bprecedents?\b|\bauthorit(?:y|ies)\b|\blandmark\b|\bleading (?:cases?|authorities)\b|\bwhich cases\b|\bany cases?\b|\bcitations?\b|\bcite\b")),
    ("courts_say", re.compile(r"\bwhat (?:do|does|did|has|have) (?:the )?(?:courts?|supreme court|high courts?)\b|\bwhat (?:was|is) held in\b|\bhas any court\b|\b(?:supreme|high) court (?:held|said|decided|has held|has said|ruled)\b|\b(?:supreme|high) court (?:judg|decision|case)")),
    ("research_note", re.compile(r"\bresearch (?:note|memo|memorandum)\b|\bdetailed (?:research|note|memo|legal|analysis)\b|\blegal research\b|\bgo deeper\b|\bdig deeper\b|\bresearch this\b")),
    ("case_named", re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+)* v\.? [A-Z]|\bvs\.? [A-Z]")),
]

_RESEARCH_MEMO = re.compile(r"\bresearch (?:note|memo|memorandum)\b|\blegal research\b|\bdetailed (?:research|legal)\b")
_NAMED_SECTION = re.compile(r"\b(?:sections?|ss?\.|sec\.?)\s*\d{1,3}[a-z]?\b|\b\d{1,3}[a-z]?\s*\(\s*\d+\s*\)\s*(?:of\s+(?:the\s+)?)?(?:bnss|bns|bsa|bharatiya)?|\b(?:bnss|bns|bsa)\s*\d{1,3}[a-z]?\b|\b\d{1,3}[a-z]?(?:\s*\(\s*\d+\s*\))?\s+(?:bnss|bns|bsa)\b", re.I)
_BARE_SUB = re.compile(r"\b\d{1,3}[a-z]?\s*\(\s*\d+\s*\)")
_EXPLAINISH = re.compile(r"\b(?:explain|elaborate|break down|breakdown|what (?:is|are|does|do|'s)|what's|meaning|mean|means|say|says|provides?|provision|covers?|define[sd]?|definition|ingredients?|elements?|essentials?|punish\w*|sentence|penalty|cognizable|non-cognizable|bailable|non-bailable|compoundable|triable|tries|try|difference|serious|arrest without|tell me (?:about|what)|samjh\w*|matlab|batao)\b", re.I)
_POINTING = re.compile(r"\b(?:the|these|those|each|every|all)\s+(?:of\s+)?(?:the\s+|these\s+|those\s+)?(?:charged\s+|chargesheet\s+|fir\s+)?(?:sections?|charges?|provisions?|offen[cs]es?)\b|\bsections?\s+(?:are\s+|is\s+|were\s+|was\s+)?(?:charged|in the (?:charge ?sheet|fir|document))|\b(?:sections?|offen[cs]es?|charges?)\s+(?:he|she|they|the accused)\s+(?:is|are|was|were)\s+(?:facing|charged)\b|\bthis section\b|\beach of (?:them|these|those)\b|\bsections?\s+(?:he|she|they)\s+(?:is|are)\s+(?:facing|charged)|\bsections?\s+(?:is|are)\s+he\s+(?:charged|facing)|\bwhich sections\b|\bchargesheet\b|\bcharge sheet\b|\b(?:in|ye|yeh|is|un)\s+(?:sections?|dharaon?|dhara)\b|\bsections?\s+ko\b", re.I)
_PROPERTY = re.compile(r"\b(?:bailable|non-bailable|cognizable|non-cognizable|compoundable|punish\w*|punishment|sentence|maximum|penalty|(?:which|what) court (?:tries|try|can try|is competent|has jurisdiction)|court (?:tries|try|can try)|triable|tries|explain|meaning|mean|means|elaborate|break down|breakdown|ingredients?|elements?|in simple|in plain|in a clear|each one|each of)\b", re.I)
_APPLY = re.compile(r"\b(?:apply|applies|applied|fit|fits|attract\w*|made out|entitled|can (?:he|we|the accused|she|they)|could (?:he|we)|will (?:he|she|they)|should (?:we|he|i)|chances?|strong\w*|weak\w*|argue|arguments?|grounds?|best|how (?:good|strong)|bail(?!able)|whether|anticipatory|released?|my case|our case|these facts|on the facts|here\?)\b", re.I)


def research_signals(q):
    n = q or ""
    return [name for name, rx in _RESEARCH if rx.search(n if name == "case_named" else n.lower())]


def plan(question, pins_available=False, has_documents=True):
    """{'size', 'why', 'router': the matter_routing decision, 'signals': [...]} for a question asked inside a matter. `pins_available`: the sections to explain can be named by code (the last answer listed them, or the
    documents carry a labelled 'Sections:' line). Order: draft, small talk, a request for cases, explain, the router's file path, else standard."""
    n = _norm(question)
    base = MR.route(question, has_documents)
    out = {"router": {"route": base["route"], "why": base["why"]}, "signals": []}
    if not has_documents:
        return {**out, "size": "standard", "why": "no_documents"}
    if base["route"] == "draft" and _RESEARCH_MEMO.search(n):          # 'write a detailed legal research memo on default bail' asks for research, not for a document to file (a change after the held-out run of half B; checked on set C)
        return {**out, "size": "research", "why": "research_memo", "signals": ["research_note"]}
    if base["route"] == "draft":
        return {**out, "size": "draft", "why": "draft_request"}
    if _SMALLTALK.match(n):
        return {**out, "size": "smalltalk", "why": "smalltalk"}
    rs = research_signals(question)
    if rs:
        return {**out, "size": "research", "why": "research_ask", "signals": rs}
    named = bool(_NAMED_SECTION.search(question or "") or _BARE_SUB.search(question or ""))
    pointing = bool(_POINTING.search(n))
    explainish = bool(_EXPLAINISH.search(n)) or bool(_PROPERTY.search(n))
    applying = bool(_APPLY.search(n))
    if explainish and not applying:
        if named:
            return {**out, "size": "explain", "why": "named_sections"}
        if pointing and _PROPERTY.search(n) and pins_available:
            return {**out, "size": "explain", "why": "charged_sections"}
    if pins_available and not applying and len(n.split()) <= 8 and re.search(r"\b(?:explain|elaborate|break down|what do|what does|mean|means|meaning|matlab|samjh\w*)\b", n) and re.search(r"\b(?:them|these|those|this|it|each|each one|all)\b", n) or (pins_available and n in ("explain", "explain it", "explain please", "please explain")):
        return {**out, "size": "explain", "why": "explain_last_list"}
    if base["route"] == "file":
        return {**out, "size": "file", "why": "file_signal"}
    return {**out, "size": "standard", "why": "unsure" if base["why"] == "unsure" else "law_signal"}


# ----------------------------------------------------------------------------- how a size is shown
LABELS = {
    "file": "Quick answer, from your documents only. It states no law.",
    "explain": "Quick answer: the sections explained from the text of the law on hand.",
    "standard": "Standard answer: the law on hand applied to your facts. No case search.",
    "research": "Research answer: judgments and the wider search included.",
    "smalltalk": "",
}
