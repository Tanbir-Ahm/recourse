"""excerpt_anchors.py -- verbatim Supreme Court excerpts ("anchors") handed to the answer-writing model for a whole KIND of question.

Why: a model can only rely on what it is given, and the library and the wider search do not always put the controlling authority in front of it. For a question about delay in a criminal trial the
answers left out Article 21 and the High Court route, although the seven-judge Bench in P. Ramachandra Rao (2002) states both. An anchor is a short passage of the judgment itself, chosen once by a
person, checked by code against the Supreme Court's own archive PDF (recourse-sci-pool: sci_anchors.py), and then given to the model next to the library text. Nothing here is generated, summarised or
guessed; nothing here says a case is good law.

    ANCHORS   off (default) | on        switch (a hosting-dashboard value such as ' "on" ' is read as on)

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


def mode():
    return "on" if _env("ANCHORS", "off").lower() in ("on", "1", "true", "yes") else "off"


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


TOPICS = {"trial_delay": _trial_delay}


def selected(question):
    """The anchors that apply to this question: [] with the switch off, for a question that matches no topic, or on any problem."""
    try:
        if mode() != "on" or not question:
            return []
        return [a for a in load() if a.get("topic") in TOPICS and TOPICS[a["topic"]](question)]
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


def _ex_title(i, ex):
    return f"({i}) {ex['label']}" + (f" -- paragraph {ex['paragraph']} of the SCC report" if ex.get("paragraph") else "")


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


def _length_note():
    """Under the v1 and v2 styles (a 300 to 400 word limit) this multi-part answer would have to squeeze two judgments into a few lines, which is where the live answer garbled a sentence. Say that 400 words
    are allowed. Nothing for v3 (its own length rules) or WhatsApp (a character limit)."""
    try:
        import answer_style
        if answer_style.template_key() in ("v1", "v2") and answer_style.get_channel() != "whatsapp":
            return ("This is a multi-part question (the right, its limits, the route to court): up to about 400 words are allowed for this answer, so that these points are not squeezed into one crowded sentence. "
                    "Keep it plain, keep each sentence to one idea, and keep the single next step.\n")
    except Exception:  # noqa: BLE001
        pass
    return ""


def block(question):
    """The prompt section for this question ('' when no anchor applies). Remembers which anchors it handed over so the finished answer can be labelled and the page can list them."""
    try:
        anchors = selected(question)
        _LOCAL.fed = anchors
        if not anchors:
            return ""
        unconfirmed = [a for a in anchors if label_for(a)]
        lines = ["\n\n## Verbatim Supreme Court excerpts (copied word for word from the judgments; checked by code against the Supreme Court's own PDF)\n"
                 "These excerpts bear on a question about delay in a criminal trial. "
                 + ("Their legal reading has NOT yet been confirmed by our reviewer. " if unconfirmed else "Our reviewer has confirmed them. ")
                 + "You may name these cases and describe ONLY what an excerpt literally says, attributed to the court (\"the Supreme Court in X said ...\"); you may quote an excerpt word for word. "
                 "Where two parts of an excerpt are joined by \"...\", words of the judgment are left out between them. Never state more than the excerpts show, and never say that a case is good law. "
                 "The guidelines of A.R. Antulay and the passage of Kartar Singh are known to us only as the seven-judge Bench quotes them: if you mention either, say so. The four factors (length of delay, the justification for it, the accused's assertion of the right, and prejudice) are Kartar Singh's words as the Bench quotes them, not Antulay's; the duty of the prosecution to justify the delay is Antulay's guideline (10), not a provision of any statute. "
                 + (f"The first time you name one of these cases, put the words {LABEL_UNCONFIRMED} right after its name. " if unconfirmed else "")
                 + "If the person's facts do not fit these excerpts, say what is missing instead of stretching them.\n"]
        for extra in (_closing_guidance(anchors), _length_note()):
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
        print("ANCHORS handed over: %s" % "; ".join(a["id"] for a in anchors), flush=True)
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        logger.warning("excerpt anchors block failed: %s", type(exc).__name__)
        _LOCAL.fed = []
        return ""


def fed():
    return list(getattr(_LOCAL, "fed", None) or [])


def case_names():
    """Names of the cases of the anchors handed over for this question (for the wider-search tier to leave out, and for the 'not checked' sentence)."""
    return [a["case_name"] for a in fed()]


def cases():
    """The anchors handed over, in the shape the page and the table of authorities read: result['anchor_excerpts']."""
    out = []
    for a in fed():
        paras = []
        for ex in a["excerpts"]:
            if ex.get("paragraph") and str(ex["paragraph"]) not in paras:
                paras.append(str(ex["paragraph"]))
        out.append({"case_name": a["case_name"], "year": a.get("year"), "date": a.get("date"), "citation": a.get("citation"), "paragraph": ", ".join(paras) or a.get("paragraph"), "link": a.get("link"),
                    "bench_note": a.get("bench_note"), "status": a.get("status"), "confirmed_by": a.get("confirmed_by"), "confirmed_on": a.get("confirmed_on"), "label": label_for(a),
                    "excerpts": [{"label": ex["label"], "paragraph": ex.get("paragraph"), "text": excerpt_text(ex), "note": ex.get("note")} for ex in a["excerpts"]]})
    return out


def attach(question, result):
    """Called at the end of chat_assistant.answer_question: labels the anchor cases in the finished answer (first mention, unless the answer already says so) and adds result['anchor_excerpts'].
    Only when this question's prompt really carried anchors. Never raises; the answer is untouched otherwise."""
    try:
        if not isinstance(result, dict) or result.get("state") not in ("single_match", "conflicting_matches") or not fed():
            return result
        import sci_search_tier as T
        pending = [{"case_name": a["case_name"]} for a in fed() if label_for(a)]
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
            span = T._locate(text or "", a["case_name"])
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
