"""excerpt_anchors.py -- verbatim Supreme Court excerpts ("anchors") handed to the answer-writing model for a whole KIND of question.

Why: a model can only rely on what it is given, and the library and the wider search do not always put the controlling authority in front of it. For a question about delay in a criminal trial the
answers left out Article 21 and the High Court route, although the seven-judge Bench in P. Ramachandra Rao (2002) states both. An anchor is a short passage of the judgment itself, chosen once by a
person, checked by code against the Supreme Court's own archive PDF (recourse-sci-pool: sci_anchors.py), and then given to the model next to the library text. Nothing here is generated, summarised or
guessed; nothing here says a case is good law.

    ANCHORS    off (default) | on       switch for the kind of question "delay in a criminal trial" (a hosting-dashboard value such as ' "on" ' is read as on)
    LANDMARKS  off (default) | on       switch for the LANDMARK topics added on 2026-10-29 (the landmark case fix): today "circumstantial_evidence" (Sharad Birdhi Chand Sarda 1984, Hanumant 1952)

Why two switches: ANCHORS has been on in production since 2026-10-16. A topic added later gets a switch of its own, so that merging the code changes nothing on the live site until the owner sets the new variable.
The landmark fix exists because the library holds no authority on circumstantial evidence and the wider search put recent restatements (and Gauhati High Court cases) in front of the model instead of the Supreme Court's
own five conditions: an answer to "Can a person be convicted on circumstantial evidence alone? What must the prosecution prove?" never named Sharad Birdhi Chand Sarda (see review_results/2026-10-29_landmark_circumstantial).

Status. Until a person confirms an anchor its status is "machine_checked": the words are the judgment's (checked by code) but the legal reading is not yet confirmed by our reviewer, and the answer says
so, right after the case name (LABEL_UNCONFIRMED). After the reviewer confirms (sci_anchors.py confirm) the status is "reviewer_confirmed" and no label is needed.

Data: excerpt_anchors.json, exported by sci_anchors.py in recourse-sci-pool (only anchors that passed the check are exported). Every function is fail-open: with the switch off, a missing file or any
error the answer is built exactly as without this module.
"""
import json
import logging
import os
import re
import threading

logger = logging.getLogger(__name__)
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "excerpt_anchors.json")
_LOCAL = threading.local()
_CACHE = {}
LABEL_UNCONFIRMED = "(verbatim excerpt, not yet confirmed by our reviewer)"
_LABEL_NOTE = re.compile(r"\(\s*[^()]{0,40}(?:verbatim excerpt|excerpt)[^()]{0,40}not yet confirmed by our reviewer", re.I)
_LABEL_SPAN = re.compile(r"\([^()]{0,100}not yet confirmed by our reviewer[^()]{0,80}\)", re.I)


def _env(name, default=""):
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().strip("\"'").strip()
    return v if v else default


def _on(name):
    return _env(name, "off").lower() in ("on", "1", "true", "yes")


def mode():
    """The switch for the trial-delay anchors (ANCHORS)."""
    return "on" if _on("ANCHORS") else "off"


def landmarks_mode():
    """The switch for the landmark topics (LANDMARKS)."""
    return "on" if _on("LANDMARKS") else "off"


def reset():
    """Forget what was handed to the model for the previous question (called at the start of every answer)."""
    _LOCAL.fed = []


def load(path=None):
    """The exported anchors (a list of dicts); [] when the file is missing or unreadable."""
    p = path or _PATH
    if p in _CACHE:
        return _CACHE[p]
    try:
        doc = json.load(open(p, encoding="utf-8"))
        anchors = [a for a in doc.get("anchors", []) if a.get("excerpts") and (a.get("check") or {}).get("all_found") and a.get("status") in ("machine_checked", "reviewer_confirmed")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("excerpt anchors not loaded: %s", type(exc).__name__)
        anchors = []
    _CACHE[p] = anchors
    return anchors


# ---- which questions each topic covers (plain patterns; a question that matches none gets nothing) -------------------------------------------------------------------------------------------

_TRIAL = re.compile(r"\b(?:trial|trials|case|cases|proceedings?|prosecution|charge[- ]?sheet|hearings?)\b", re.I)
_SPEEDY = re.compile(r"\bspeedy\s+(?:trial|justice|disposal)|right to (?:a )?speedy|outer\s+(?:time[- ])?limit|\b(?:time[- ]?limit|limitation|time[- ]?bar)\w*\s+(?:for|on|to)\s+(?:a\s+|the\s+)?(?:criminal\s+)?(?:trial|case|proceedings?)"
                     r"|article\s*21\b.{0,80}\b(?:delay\w*|trial|speedy)\b|\b(?:delay\w*|trial|speedy)\b.{0,80}article\s*21\b", re.I | re.S)
_DRAG = re.compile(r"\b(?:going on|dragging|dragged|drags|still (?:on|running)|not (?:yet )?(?:ended|concluded|over|finished)|no (?:hearing|progress|end)|adjourn\w*|postpone\w*|"
                   r"(?:keeps?|kept) (?:asking|taking|seeking|getting)|asking for (?:more )?time|seeking (?:more )?time|taking (?:more )?time|delay\w*|too long|so long|years? (?:and|but) (?:no|still))\b", re.I)
_LONG = re.compile(r"\b(?:[2-9]|[1-9]\d)\s*[- ]?(?:years?|yrs?)\b|\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)\s*[- ]?(?:years?|yrs?)\b|\bdecades?\b|\b(?:many|several|long) years\b", re.I)
_OTHER_DELAY = re.compile(r"\bdelay(?:ed|s)?\s+(?:in|of|on|by)\s+(?:the\s+)?(?:filing|lodging|registering|registration|reporting|presenting|presentation|giving|sending|issuing|paying|payment|returning|serving|service|"
                          r"submitting|appeal\w*|fir|complaint|notice|cheque|sanction|granting|grant|release|bail|refund|salary)\b", re.I)
_NUM = r"(?:[2-9]|[1-9]\d|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)"
_PUNISHMENT_YEARS = re.compile(r"\b(?:sentenc\w+|imprisonment|punish\w*|rigorous|term|maximum|minimum|upto|up to|not less than|not exceeding|exceeding)\b[^.?!]{0,40}?\b" + _NUM + r"\s*[- ]?(?:years?|yrs?)\b", re.I)
_TRIAL_YEARS = re.compile(r"\b(?:trial|trials|case|cases|proceedings?|prosecution|charge[- ]?sheet|hearings?)\b[^.?!]{0,60}?\b" + _NUM + r"\s*[- ]?(?:years?|yrs?)\b|\b" + _NUM + r"\s*[- ]?(?:years?|yrs?)\b[^.?!]{0,60}?\b(?:trial|trials|case|cases|proceedings?|prosecution|charge[- ]?sheet|hearings?)\b", re.I)


def _trial_delay(question):
    """A question about delay in a criminal trial: an explicit mention of the right to a speedy trial, a time limit for trials or Article 21 with delay; or a trial/case/proceeding that is 'going on',
    'dragging' or being adjourned, with a number of years or a plain complaint of delay; or a number of years next to the trial itself. A delay in filing an FIR, a complaint or an appeal is not this,
    and neither is a number of years of punishment."""
    q = question or ""
    if _SPEEDY.search(q):
        return True
    q = _PUNISHMENT_YEARS.sub(" ", _OTHER_DELAY.sub(" ", q))
    if _TRIAL_YEARS.search(q):
        return True
    return bool(_TRIAL.search(q) and _DRAG.search(q) and (_LONG.search(q) or re.search(r"\b(?:adjourn\w*|postpone\w*|delay\w*|dragg\w*|asking for (?:more )?time|seeking (?:more )?time|taking (?:more )?time)\b", q, re.I)))


# ---- circumstantial evidence (the landmark case fix, 2026-10-29) --------------------------------------------------------------------------------------------------------------------------------
# A question about whether a criminal conviction can rest on circumstantial evidence and what the prosecution must then prove. The patterns were written AFTER a set of 90 questions had been frozen and committed
# (review_results/2026-10-29_landmark_circumstantial/frozen_questions_set1.json); the measurement is in that folder's RESULTS.md. "Circumstantial evidence" in a divorce, an insurance claim, a will or a motor
# accident claim is not this topic, so a civil marker blocks the words alone; a question that names the case, the "five golden principles" or the panchsheel is this topic whatever else it says.
_CIRC_WORD = re.compile(r"\bcircumstan[tcs]ial\b", re.I)                       # circumstantial, and the usual misspellings circumstancial / circumstansial
_CIVIL = re.compile(r"\b(?:divorce|matrimonial|adultery|civil\s+(?:suit|case|court|dispute|litigation|claim)|insurance|insurer|insured|tenant|landlord|evict\w*|subletting|probate|testament|consumer\s+(?:forum|commission|court)|"
                    r"partition|inherit\w*|motor\s+accident|accident\s+claim|compensation\s+claim|income\s+tax|contract\w*|plaintiff|defendant|decree|damages|specific\s+performance|injunction|"
                    r"employer|employee|dismiss\w*|domestic\s+inquiry|disciplinary|negligen\w+)\b", re.I)
_STRONG_CRIM = re.compile(r"\b(?:convict\w*|acquit\w*|prosecution|accused|murder\w*|homicide|dowry\s+death|rape|sessions|guilty|guilt)\b", re.I)
_CRIM_CONTEXT = re.compile(r"\b(?:convict\w*|acquit\w*|guilty|guilt|punish\w*|sentenc\w+|jail|prison|imprison\w*|prosecution|accused)\b", re.I)
_NO_DIRECT = re.compile(r"\b(?:(?:no|without|absence\s+of|lack\s+of|not\s+any)\s+(?:\w+\s+){0,2}?(?:eye[\s-]?witness\w*|direct\s+(?:evidence|proof))|"
                        r"(?:no|without)\s+(?:any\s+)?witness(?:es)?\b|"
                        r"(?:nobody|no[\s-]?one|not\s+a\s+single\s+person)\s+(?:has\s+|had\s+)?(?:saw|seen|witnessed))\b", re.I)
_CHAIN = re.compile(r"\b(?:chain\s+of\s+circumstances|links?\s+in\s+the\s+chain|chain\s+(?:is|was|remains?)\s+(?:in)?complete|(?:in)?complete\s+chain|broken\s+chain)\b", re.I)
_CHAIN_LOOSE = re.compile(r"\bchain\s+of\s+(?:events|evidence)\b", re.I)                    # too common outside this topic to count without a conviction in question
_SERIES = re.compile(r"\bseries\s+of\s+(?:circumstances|facts|events)\b", re.I)
_MAY_MUST = re.compile(r"(?:\bmust\s+be|\bshould\s+be)['’\"]?\s+and\s+not\s+(?:merely\s+)?['‘\"]?may\s+be\b|\b(?:may\s+be|must\s+be)['’\"]?\s+(?:and|versus|vs\.?|as\s+against|as\s+opposed\s+to)\s+['‘\"]?(?:may\s+be|must\s+be)\b", re.I)
_ENOUGH = re.compile(r"\b(?:enough|sufficient|suffice[sd]?)\b", re.I)
_CONVICT = re.compile(r"\bconvict\w*\b", re.I)
_NAMED = re.compile(r"\b(?:sharad\s+(?:birdhi\s*chand|birdhichand|sarda)\b(?:\s+sarda)?|birdhi\s*chand\s+sarda|sarda\s+(?:principles?|test|conditions|case|judg\w+)|five\s+golden\s+principles|"
                    r"hanumant(?:\s+govind\s+nargundkar)?\s+(?:v\.?|vs\.?|versus)\s)", re.I)
_PANCHSHEEL = re.compile(r"\bpanchsh?eel\b", re.I)
_PANCH_CONTEXT = re.compile(r"\b(?:evidence|proof|prove[nd]?|circumstan\w*|convict\w*|acquit\w*|guilt\w*|criminal)\b", re.I)
_HYPOTHESIS = re.compile(r"\b(?:consistent\s+with\s+(?:his\s+|her\s+|the\s+accused'?s?\s+)?innocence|hypothes[ie]s\s+of\s+(?:the\s+)?(?:guilt|innocence)|exclude\s+every\s+(?:other\s+|possible\s+)?hypothesis)\b", re.I)
_SUSPICION = re.compile(r"\bsuspicion\b", re.I)
_SUSPICION_CONTEXT = re.compile(r"\b(?:convict\w*|guilty|legal\s+proof|sentenc\w+|punish\w*)\b", re.I)


def _circumstantial(question):
    """A question about conviction on circumstantial evidence: the words 'circumstantial evidence' (not in a civil setting); or no eyewitness / no direct evidence / nobody saw it, with a conviction or punishment in
    question; a chain of circumstances, with guilt or conviction in question; the case, the five golden principles or the panchsheel of proof by name; a hypothesis consistent with innocence; or suspicion that is
    said to be enough to convict. A question on another subject, or on circumstantial evidence in a civil dispute, is not."""
    q = question or ""
    if _NAMED.search(q):
        return True
    if _PANCHSHEEL.search(q) and _PANCH_CONTEXT.search(q):
        return True
    civil = bool(_CIVIL.search(q))
    strong = bool(_STRONG_CRIM.search(q))
    if _CIRC_WORD.search(q) and (not civil or strong):
        return True
    if civil and not strong:
        return False
    if _NO_DIRECT.search(q) and _CRIM_CONTEXT.search(q):
        return True
    if _CHAIN.search(q) or (_CHAIN_LOOSE.search(q) and strong):
        return True
    if _HYPOTHESIS.search(q):
        return True
    if _SERIES.search(q) and strong:
        return True
    if _MAY_MUST.search(q):
        return True
    if re.search(r"\bcircumstances\b", q, re.I) and _ENOUGH.search(q) and _CONVICT.search(q):
        return True
    return bool(_SUSPICION.search(q) and _SUSPICION_CONTEXT.search(q))


# topic -> the switch that turns it on and the test of which questions it covers. A topic with no switch on, or whose test the question fails, hands over nothing.
TOPICS = {
    "trial_delay": {"switch": "ANCHORS", "match": _trial_delay},
    "circumstantial_evidence": {"switch": "LANDMARKS", "match": _circumstantial},
}


def active_topics(question):
    """The topics whose switch is on and whose test this question passes, in the order of TOPICS."""
    return [t for t, spec in TOPICS.items() if _on(spec["switch"]) and spec["match"](question)]


def selected(question):
    """The anchors that apply to this question: [] with every switch off, for a question that matches no topic, or on any problem."""
    try:
        if not question:
            return []
        topics = active_topics(question)
        if not topics:
            return []
        return [a for a in load() if a.get("topic") in topics]
    except Exception as exc:  # noqa: BLE001
        logger.warning("excerpt anchors selection failed: %s", type(exc).__name__)
        return []


def applies(question):
    return bool(selected(question))


# ---- wording ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def label_for(a):
    return "" if a.get("status") == "reviewer_confirmed" else LABEL_UNCONFIRMED


def excerpt_text(ex):
    return " ... ".join(s.strip() for s in ex["segments"])


def _date_words(iso):
    import datetime
    try:
        d = datetime.date.fromisoformat(iso)
        return f"{d.day} {d.strftime('%B %Y')}"
    except Exception:  # noqa: BLE001
        return iso


def _head(a):
    bits = [f"{a['case_name']} ({a['year']})"]
    if a.get("citation"):
        bits.append(a["citation"])
    if a.get("date"):
        bits.append("decided " + _date_words(a["date"]))
    if a.get("bench_note"):
        bits.append(a["bench_note"])
    return "[VERBATIM EXCERPTS -- " + ", ".join(bits) + "]"


def _para_phrase(ex):
    """'paragraph 29 of the SCC report'; 'paragraphs 152 to 154 of the SCC report'; 'paragraph 10 of the AIR report' (an excerpt may name another report with "report")."""
    p = str(ex.get("paragraph") or "")
    plural = bool(re.search(r"[-,&]|\bto\b|\band\b", p))
    return ("paragraphs " if plural else "paragraph ") + p + " of the " + (ex.get("report") or "SCC") + " report"


def _ex_title(i, ex):
    return f"({i}) {ex['label']}" + (f" -- {_para_phrase(ex)}" if ex.get("paragraph") else "")


def _para_shown(ex):
    """The paragraph as the page and the table show it: the number alone for the SCC report (as before), and '10 (AIR report)' for another report."""
    p = str(ex.get("paragraph") or "")
    rep = ex.get("report")
    return p if not p or not rep or rep == "SCC" else f"{p} ({rep} report)"


def _statute_pointers(anchors):
    """One sentence from the site's own table of old and new section numbers for the Code of Criminal Procedure sections that the excerpts name (a pointer to verify)."""
    try:
        import statute_concordance as SC
        out = []
        for a in anchors:
            for sec in (a.get("statute_pointers") or {}).get("CrPC", []):
                new = SC.to_new("CrPC", sec) or []
                if new:
                    out.append(f"CrPC Section {sec} corresponds to BNSS Section " + " and ".join(n["section"] for n in new))
        return ("Statute pointers (from the site's own table of old and new section numbers; a pointer to verify, not part of the judgments): " + "; ".join(out) + ".") if out else ""
    except Exception:  # noqa: BLE001
        return ""


def _closing_guidance(anchors):
    """How to answer "can the case be closed because of the delay?" from the excerpts, using only what they literally say (added 2026-10-16 after a live answer said only that delay does not end a case, left out
    that Antulay's guideline (9), as the Bench extracts it, ordinarily quashes, and turned guideline (11), which says where to go, into a remedy). '' unless the excerpts handed over contain guidelines (9) and (11)."""
    text = " ".join(excerpt_text(ex) for a in anchors for ex in a["excerpts"])
    if "shall be quashed" not in text or "(11)" not in text or "(9)" not in text:
        return ""
    return ("If the person asks whether the case can be closed, ended or dropped because of the delay, answer THAT in your opening and say all three parts: "
            "(a) the seven-judge Bench holds that no outer time limit can be fixed and that a court is not obliged to end a trial merely because time has passed (its conclusion (4)); "
            "(b) but guideline (9) of Antulay, as the Bench extracts it, says that where the court concludes that the right to speedy trial has been infringed, the charges or the conviction \"shall be quashed\" "
            "-- this is the ordinary consequence -- though it is not the only course: the court may instead make another appropriate order, including an order to conclude the trial within a fixed time; "
            "(c) guideline (11) says WHERE to go, not what the remedy is: an objection based on denial of the right should first be addressed to the High Court, which ordinarily should not stay the proceedings "
            "except in a grave and exceptional case. Do not describe guideline (11) as a remedy, and do not attribute the fixed-time order or the quashing to it. "
            "Do not leave the reader with only \"delay alone does not end a case\".\n")


def _circumstantial_guidance(anchors):
    """How to answer "can a conviction rest on circumstantial evidence alone? what must the prosecution prove?" from the excerpts, using only what they literally say (the landmark case fix, 2026-10-29: the answer the
    owner compared with Anrak's rested on recent restatements and never gave the Supreme Court's five conditions). '' unless the excerpts handed over contain the five conditions. Each further point is added only if
    its own words are among the excerpts."""
    text = " ".join(excerpt_text(ex) for a in anchors for ex in a["excerpts"]).lower()
    if "panchsheel" not in text or "following conditions must be fulfilled" not in text:
        return ""
    out = ("If the person asks whether a conviction can rest on circumstantial evidence alone, or what the prosecution must prove, say in your opening that it can, but only if every one of the Bench's five conditions is met, "
           "and then set those five conditions out as a numbered list, in the order and words of the excerpt, attributed to the Supreme Court in Sharad Birdhichand Sarda (a Bench of three judges), "
           "saying that the Bench drew them from the passage of Mahajan J. in Hanumant (the second case below). ")
    extras = []
    if "stand or fall on its own legs" in text and "false defence" in text:
        extras.append("a false defence or a false explanation cannot make up for a missing link in the prosecution's chain (the Bench allows it only as an additional link, to give assurance to the court, and only if the three conditions in the excerpt are met)")
    if "two possibilities are available" in text:
        extras.append("where the evidence leaves two views open, the accused is entitled to the benefit of doubt")
    if "suspicion, however great" in text:
        extras.append("suspicion, however great, cannot take the place of legal proof")
    if extras:
        out += "Then add, each attributed to the Court and each only as the excerpts say it: " + "; ".join(extras) + ". "
    return out + "Do not describe the five conditions as a statute.\n"


def _length_note(parts="the right, its limits, the route to court"):
    """Under the v1 and v2 styles (a 300 to 400 word limit) this multi-part answer would have to squeeze two judgments into a few lines, which is where the live answer garbled a sentence. Say that 400 words
    are allowed. Nothing for v3 (its own length rules) or WhatsApp (a character limit)."""
    try:
        import answer_style
        if answer_style.template_key() in ("v1", "v2") and answer_style.get_channel() != "whatsapp":
            return (f"This is a multi-part question ({parts}): up to about 400 words are allowed for this answer, so that these points are not squeezed into one crowded sentence. "
                    "Keep it plain, keep each sentence to one idea, and keep the single next step.\n")
    except Exception:  # noqa: BLE001
        pass
    return ""


# What each topic's prompt section says about its subject: (the kind of question, the topic's own notes for the model, the function that gives the topic's guidance, the parts of the multi-part length note).
_TRIAL_NOTES = ("The guidelines of A.R. Antulay and the passage of Kartar Singh are known to us only as the seven-judge Bench quotes them: if you mention either, say so. The four factors (length of delay, the justification for it, "
                "the accused's assertion of the right, and prejudice) are Kartar Singh's words as the Bench quotes them, not Antulay's; the duty of the prosecution to justify the delay is Antulay's guideline (10), not a provision of any statute. ")
_CIRC_NOTES = ("The five conditions are the Bench's own, in Sharad Birdhichand Sarda (1984), a Bench of three judges; the Bench draws them from the judgment of Mahajan J. in Hanumant (1952), which it calls the most fundamental "
               "and basic decision of the Court on the subject, and it calls them the panchsheel of the proof of a case based on circumstantial evidence. Give the conditions in the order and words of the excerpt: do not add a "
               "sixth, and do not reword one so that its meaning changes. A paragraph number may be given only as it is shown with the excerpt. These excerpts say what the prosecution must prove where it relies on circumstantial "
               "evidence; they say nothing about direct evidence, motive, last seen together, recovery of articles, dying declarations or any provision of the Evidence Act or the Bharatiya Sakshya Adhiniyam, so say nothing on "
               "those points from them. Where an excerpt states the rule, state the rule from that judgment first, and use a case from a wider search only for what these excerpts do not say. ")
TOPIC_WORDING = {
    "trial_delay": ("a question about delay in a criminal trial", _TRIAL_NOTES, _closing_guidance, "the right, its limits, the route to court"),
    "circumstantial_evidence": ("a question about proving guilt by circumstantial evidence in a criminal case", _CIRC_NOTES, _circumstantial_guidance, "the rule, its five conditions, what the Court adds"),
}


def _section(topic, anchors):
    """The prompt section of one topic: the heading and instructions, the topic's guidance and length note, then each case's excerpts, the statute pointers and the register's lines."""
    subject, notes, guidance, parts = TOPIC_WORDING[topic]
    unconfirmed = [a for a in anchors if label_for(a)]
    lines = ["\n\n## Verbatim Supreme Court excerpts (copied word for word from the judgments; checked by code against the Supreme Court's own PDF)\n"
             f"These excerpts bear on {subject}. "
             + ("Their legal reading has NOT yet been confirmed by our reviewer. " if unconfirmed else "Our reviewer has confirmed them. ")
             + "You may name these cases and describe ONLY what an excerpt literally says, attributed to the court (\"the Supreme Court in X said ...\"); you may quote an excerpt word for word. "
             "Where two parts of an excerpt are joined by \"...\", words of the judgment are left out between them. Never state more than the excerpts show, and never say that a case is good law. "
             + notes
             + (f"The first time you name one of these cases, put the words {LABEL_UNCONFIRMED} right after its name. " if unconfirmed else "")
             + "If the person's facts do not fit these excerpts, say what is missing instead of stretching them.\n"]
    for extra in (guidance(anchors), _length_note(parts)):
        if extra:
            lines.append(extra)
    for a in anchors:
        lines.append(_head(a))
        for i, ex in enumerate(a["excerpts"], 1):
            lines.append(_ex_title(i, ex) + ":\n" + excerpt_text(ex) + "\n")
    pointers = _statute_pointers(anchors)
    if pointers:
        lines.append(pointers + "\n")
    try:                                                    # the register's own lines for cases the excerpts name (Raj Deo Sharma, Common Cause), so the facts ride with the excerpt
        from register_hooks import text_mentions
        men = text_mentions(" ".join(excerpt_text(ex) for a in anchors for ex in a["excerpts"]))
        if men["lines"]:
            lines.append("[Overruled Register -- not optional: the excerpts name cases on our register; if you mention one of them at all, state this fact in the same sentence]\n" + "\n".join(men["lines"]) + "\n")
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lines)


def block(question):
    """The prompt section for this question ('' when no anchor applies): one section for each topic that applies. Remembers which anchors it handed over so the finished answer can be labelled and the page can list them."""
    try:
        anchors = selected(question)
        _LOCAL.fed = anchors
        if not anchors:
            return ""
        sections = []
        for topic in TOPICS:
            group = [a for a in anchors if a.get("topic") == topic]
            if group:
                sections.append(_section(topic, group))
        print("ANCHORS handed over: %s" % "; ".join(a["id"] for a in anchors), flush=True)
        return "\n".join(sections)
    except Exception as exc:  # noqa: BLE001
        logger.warning("excerpt anchors block failed: %s", type(exc).__name__)
        _LOCAL.fed = []
        return ""


def fed():
    return list(getattr(_LOCAL, "fed", None) or [])


def case_names():
    """Names of the cases of the anchors handed over for this question (for the wider-search tier to leave out, and for the 'not checked' sentence)."""
    return [a["case_name"] for a in fed()]


def _para_order(p):
    m = re.match(r"\d+", str(p))
    return (int(m.group()) if m else 10 ** 9, str(p))


def cases():
    """The anchors handed over, in the shape the page and the table of authorities read: result['anchor_excerpts']."""
    out = []
    for a in fed():
        paras = []
        for ex in a["excerpts"]:
            for part in (p.strip() for p in _para_shown(ex).split(", ")):          # an excerpt may span '151, 159 to 161': each piece takes its own place in the order
                if part and part not in paras:
                    paras.append(part)
        paras = sorted(paras, key=_para_order) if len(paras) > 1 else paras
        out.append({"case_name": a["case_name"], "year": a.get("year"), "date": a.get("date"), "citation": a.get("citation"), "paragraph": ", ".join(paras) or a.get("paragraph"), "link": a.get("link"),
                    "bench_note": a.get("bench_note"), "status": a.get("status"), "confirmed_by": a.get("confirmed_by"), "confirmed_on": a.get("confirmed_on"), "label": label_for(a),
                    "excerpts": [{"label": ex["label"], "paragraph": _para_shown(ex) or None, "text": excerpt_text(ex), "note": ex.get("note")} for ex in a["excerpts"]]})
    return out


def _label_targets(text):
    """The unconfirmed anchor cases to label in a finished answer, each by the name the answer uses FIRST: the anchor's full name or one of its `aliases` (a short form the data lists, such as 'Sharad Sarda').
    One entry per case, so a case named both ways is labelled once, at its first mention."""
    import sci_search_tier as T
    out = []
    for a in fed():
        if not label_for(a):
            continue
        best = None
        for name in [a["case_name"]] + list(a.get("aliases") or []):
            span = T._locate(text or "", name)
            if span is not None and (best is None or span[0] < best[0]):
                best = (span[0], name)
        out.append({"case_name": best[1] if best else a["case_name"]})
    return out


def attach(question, result):
    """Called at the end of chat_assistant.answer_question: labels the anchor cases in the finished answer (first mention, unless the answer already says so) and adds result['anchor_excerpts'].
    Only when this question's prompt really carried anchors. Never raises; the answer is untouched otherwise."""
    try:
        if not isinstance(result, dict) or result.get("state") not in ("single_match", "conflicting_matches") or not fed():
            return result
        import sci_search_tier as T
        pending = _label_targets(result.get("response_text") or "")
        if pending and result.get("response_text"):
            result["response_text"] = T.label_cases(result["response_text"], pending, LABEL_UNCONFIRMED, _LABEL_NOTE, _LABEL_SPAN)
            result["response_text"] = T.only_at_first_mentions(result["response_text"], pending, LABEL_UNCONFIRMED, _LABEL_NOTE)       # one label per case, right after its first mention
        result["anchor_excerpts"] = cases()
    except Exception as exc:  # noqa: BLE001
        logger.warning("excerpt anchors attach failed: %s", type(exc).__name__)
    return result


def names_in(text):
    """Names of the anchor cases that a finished answer mentions, as written there plus the anchors' own names, for the 'not checked' sentence to skip (they carry their own label)."""
    try:
        import sci_search_tier as T
        out = []
        for a in fed():
            out.append(a["case_name"])
            for name in [a["case_name"]] + list(a.get("aliases") or []):
                span = T._locate(text or "", name)
                if span:
                    out.append((text or "")[span[0]:span[1]])
                    try:
                        from overruled_register.overlay import case_mentions
                        out.extend(m["name"] for m in case_mentions(text or "") if m["start"] < span[1] and m["end"] > span[0])
                    except Exception:  # noqa: BLE001
                        pass
        return out
    except Exception:  # noqa: BLE001
        return []
