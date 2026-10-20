"""
passage_notes.py -- whose VOICE a wider-search passage is in (added 2026-10-19 after the owner's staging test of section 17 of the Prevention of Corruption Act).

Two real failures:
  * "State of Karnataka v. T.N. Sudhakar Reddy (2025)", paragraph 33 describes the HIGH COURT's four-step procedure; the answer used it as the law. Paragraph 45 of the same judgment says the High Court erred.
  * "Nara Chandrababu Naidu v. State of Andhra Pradesh (2024)", paragraph 28 begins "I am of the opinion ...": it is ONE judge's opinion on a split bench; the answer wrote "the Supreme Court said".
(The earlier search-step marks found the same family: 8 of 34 passages marked misleading were a party's submission presented as the court's holding.)

This module reads a passage and says which of four voices it is in. It is pure code (no model, no network), deliberately conservative: a passage that mixes voices ("It was contended ... We reject that") gets no submission note, and
every cue is a construction a judge or a lower court's reporter uses, not a bare word. It never decides whether a case is good law and never decides what a passage means; it only tells the model, and the reader, whose
voice the words are in.

PASSAGE_NOTES=on|off, default OFF (it changes the prompt of every wider-search answer, so it waits for the owner's staging test; DEPLOY_STAGING.md Part 4q).
Used by sci_search_tier.feed_block (a "Note by code" line under the passage, and a line on the page) and sci_search_tier.attach (a notice when the answer calls such a passage "the Supreme Court" in so many words).
"""
import os
import re

KINDS = ("lower_court", "lower_court_rejected", "one_judge", "submission")

_LOWER_FORUM = (r"(?:High\s+Court|(?:Single|Division)\s+Bench(?:\s+of\s+the\s+High\s+Court)?|Full\s+Bench|Trial\s+Court|Sessions\s+(?:Judge|Court)|Special\s+(?:Judge|Court)|"
                r"(?:Chief\s+Judicial\s+|Judicial\s+|Metropolitan\s+)?Magistrate|Tribunal|Appellate\s+(?:Court|Tribunal)|Courts?\s+below|(?:impugned|appellate)\s+(?:judgment|order))")
_LOWER = re.compile(r"\baccording\s+to\s+(?:the\s+)?(?:learned\s+)?" + _LOWER_FORUM + r"\b|"
                    r"\b(?:the\s+)?(?:learned\s+)?" + _LOWER_FORUM + r"\b[^.?!]{0,70}?\b(?:held|holds|observed|observes|opined|noted|concluded|took\s+the\s+view|was\s+of\s+the\s+view|came\s+to\s+the\s+conclusion|"
                    r"framed|reasoned|rejected|accepted|erred|ruled|found|directed|quashed|interpreted|read\s+(?:down|into))\b", re.I)
_REJECTED = re.compile(r"\b(?:erred|was\s+in\s+error|fell\s+into\s+(?:an\s+)?error|is\s+not\s+(?:correct|sustainable|tenable)|cannot\s+be\s+sustained|unsustainable|not\s+sustainable|"
                       r"(?:we|this\s+court)\s+(?:do\s+not\s+agree|disagree|cannot\s+agree|are\s+unable\s+to\s+agree|do\s+not\s+approve)|bad\s+in\s+law|wrongly|incorrectly)\b", re.I)
_ONE_JUDGE = re.compile(r"\bI\s+(?:am\s+of\s+the\s+(?:considered\s+|firm\s+|humble\s+)?(?:opinion|view)|hold|would\s+(?:allow|dismiss|answer|hold|have)|respectfully\s+(?:agree|disagree|dissent|differ)|dissent|concur|"
                        r"agree\s+with\s+my|have\s+had\s+the\s+benefit|shall\s+examine|am\s+unable\s+to\s+(?:agree|subscribe))\b|"
                        r"\b(?:in|to)\s+my\s+(?:considered\s+|humble\s+)?(?:opinion|view|judgment)\b|(?-i:\bmy\s+(?:learned\s+)?(?:Brother|Sister|Colleague)s?\b)|\bmy\s+learned\s+(?:brother|sister|colleague)s?\b", re.I)
_HOLD = re.compile(r"\b(?:we\s+(?:hold|are\s+of\s+the\s+(?:considered\s+)?(?:view|opinion)|find|agree|reject|are\s+convinced|are\s+satisfied|answer)|in\s+our\s+(?:considered\s+)?(?:view|opinion))\b", re.I)
_SUBMIT = re.compile(r"\bit\s+(?:was|is|has\s+been)\s+(?:further\s+|also\s+|then\s+|strenuously\s+|vehemently\s+)?(?:submitted|contended|argued|urged)\b|"
                     r"\b(?:submitted|contended|argued|urged)\s+(?:before\s+us\s+)?that\b|"
                     r"\b(?:learned\s+)?(?:senior\s+|additional\s+solicitor\s+general\s+|standing\s+)?(?:counsel|advocate)s?\b[^.?!]{0,60}\b(?:submit|contend|argue|urge)\w*|"
                     r"\b(?:the\s+)?(?:appellants?|respondents?|petitioners?|accused|complainant|prosecution|state)\b[^.?!]{0,40}\b(?:contends?|submits?|urges?|argues?)\b", re.I)


def enabled():
    return (os.environ.get("PASSAGE_NOTES") or "off").strip().strip("\"'").strip().lower() in ("on", "1", "true", "yes")


def kinds(text, passage_type=None):
    """The voices a passage is in, from KINDS (a list; [] when it is the Court's own voice or cannot be told). `passage_type` is the search service's soft tag ('argument', 'reasoning', ...)."""
    try:
        t = text or ""
        if not t.strip():
            return []
        out = []
        sub = bool((passage_type == "argument" or _SUBMIT.search(t)) and not _HOLD.search(t))          # a party's submission, with no word of the Court's own in it
        if _LOWER.search(t):                                                                           # 'the High Court erred' inside a SUBMISSION is the party's view, not this Court's finding
            out.append("lower_court_rejected" if (_REJECTED.search(t) and not sub) else "lower_court")
        one = bool(_ONE_JUDGE.search(t))
        if one:
            out.append("one_judge")
        if sub and not one:
            out.append("submission")
        return out
    except Exception:  # noqa: BLE001
        return []


_PROMPT = {
    "lower_court": "this passage reports what a lower court (the High Court, a trial court or a tribunal) held or reasoned. It is not necessarily this Court's holding. Describe it as that court's view, and say that this "
                   "Court agreed with it only if the passage itself says so.",
    "lower_court_rejected": "this passage reports what a lower court held AND shows this Court finding that court to be wrong. The lower court's view is NOT the law laid down: do not present it as the law.",
    "one_judge": "this passage is written in the first person: it reflects the view of ONE judge (a separate, concurring or dissenting opinion, or the opinion of the only judge). Unless the passage shows that the whole "
                 "bench agreed, do not write that 'the Supreme Court held' or 'the Court said' it: say that it is one judge's opinion.",
    "submission": "this passage records what a party or its counsel submitted, not what the Court decided. Do not present it as the Court's holding.",
}
_PAGE = {
    "lower_court": "This passage reports what a lower court held; it is not necessarily the Supreme Court's own holding.",
    "lower_court_rejected": "This passage reports what a lower court held and shows the Supreme Court finding that court wrong.",
    "one_judge": "This passage is one judge's own opinion (written in the first person), not necessarily the judgment of the whole bench.",
    "submission": "This passage records a party's submission, not the Court's decision.",
}
INSTRUCTION = ("\nA line starting \"Note by code\" under a passage states whose voice the passage is in. Follow it: never present a lower court's reasoning, a party's submission or one judge's separate opinion as what "
               "\"the Supreme Court held\", and when a note says a passage is one judge's opinion, do not call it the Court's.\n")


def prompt_note(kind_list):
    """The 'Note by code' line to put under a passage ('' for none)."""
    ks = [k for k in kind_list or [] if k in _PROMPT]
    return "\n[Note by code -- read before using this passage: " + " Also, ".join(_PROMPT[k] for k in ks) + "]" if ks else ""


def page_note(kind_list):
    """One short plain sentence for the page's list of wider-search passages ('' for none)."""
    ks = [k for k in kind_list or [] if k in _PAGE]
    return " ".join(_PAGE[k] for k in ks)


_FORUMS = r"High\s+Court|trial\s+court|lower\s+court|Sessions|Magistrate|Tribunal|Division\s+Bench|Single\s+Judge|Special\s+Judge|Court\s+below"
_VERBS = (r"(?:held|holds|ruled|rules|decided|decides|laid\s+down|lays\s+down|concluded|said|says|observed|observes|clarified|emphasi[sz]ed|reiterated|stated|states|found|finds|opined|treats|treated|"
          r"rejected|rejects|accepted|accepts|upheld|upholds|affirmed|approved|endorsed|adopted|agreed|disagreed|took\s+the\s+view|was\s+of\s+the\s+view)")
# 'the Supreme Court' / 'the Court' followed (in the same clause) by a verb that says what it decided. A forum named in between ('the Supreme Court noted that the High Court held') means the verb is that forum's, so it does not count.
_COURT_SAYS = re.compile(r"(?:\bSupreme\s+Court\b|(?-i:\b[Tt]he\s+Court\b)(?!\s+below))(?:(?!" + _FORUMS + r")[^.?!;]){0,200}?\b" + _VERBS + r"\b", re.I)
# the case's own name as the subject: 'Naidu (2024) says that ...' (matched against the text that follows the name)
_NAME_SAYS = re.compile(r"\s*(?:\([^()]{0,80}\)\s*)*(?:the\s+)?(?:case\s+|judgment\s+|decision\s+|ruling\s+)?(?:also\s+|therefore\s+|thus\s+|again\s+)?" + _VERBS + r"\b", re.I)
# words by which the answer itself already says whose voice it is: then there is nothing to warn about
_HEDGE = re.compile(r"\b(?:one\s+judge|a\s+judge|single\s+judge|Justice\s+\w+|separate\s+(?:opinion|judgment|judgement|view|concurring)|separately\s+(?:opined|held|said|wrote)|dissent\w*|concurr\w*|minority|"
                    r"individual\s+(?:opinion|view)|(?:was|were|been|is|are)\s+(?:submitted|contended|argued|urged)|(?:submitted|contended|argued|urged)\s+(?:that|before)|counsel|"
                    r"(?:appellants?|respondents?|petitioners?|accused|prosecution|complainant)\s+(?:submitted|contended|argued|urged|says?|said)|passage\s+(?:describes|records|reports|sets\s+out))\b", re.I)
# the full stops of 'v.', 'Ors.', 'T.N.' are not the end of a sentence
_ABBREV = re.compile(r"\b(?i:v|vs|ors|anr|dr|smt|shri|sri|mr|mrs|ms|prof|addl|govt|pvt|no|nos)\.|\b[A-Z]\.(?=\s?[A-Z]\.|\s+[A-Z][a-z])")
_BOUND = re.compile(r"[.?!]+[\"')\]]*\s+(?=[A-Z\"'(\[0-9])|;\s*|\n+")


def _flat(s):
    """`s` with the full stop of every abbreviation of _ABBREV blanked out (same length, so positions stay valid)."""
    return _ABBREV.sub(lambda m: m.group(0)[:-1] + " ", s)


def _sentence(text, span, others=(), with_tail=False):
    """The stretch of `text` around `span` (a case's name): from the last sentence or clause boundary before it to the first one after it, never running into the name of another case (`others`: their spans).
    With `with_tail` the pair (that stretch, the part of it that follows the name)."""
    lo, hi = max(0, span[0] - 400), min(len(text), span[1] + 500)
    seg = _flat(text[lo:hi])
    a, b = span[0] - lo, span[1] - lo
    start, end = 0, len(seg)
    for m in _BOUND.finditer(seg):
        if m.end() <= a:
            start = m.end()
        elif m.start() >= b:
            end = m.start()
            break
    for s, e in others or ():
        s, e = s - lo, e - lo
        if b <= s < end:
            end = s
        elif start < e <= a:
            start = e
    return (seg[start:end], seg[b:end]) if with_tail else seg[start:end]


def overstated(window, kind_list, tail=None):
    """True when `window` (the sentence around a case's name) says that 'the Supreme Court' / 'the Court' held or said something (or, with `tail`, the text after the name, when the case itself is the subject:
    'Naidu says that ...'), although the passage read for that case is a lower court's view (not rejected by this Court), one judge's opinion, or a submission -- and the sentence itself does not already say whose
    voice it is."""
    try:
        if not any(k in ("lower_court", "one_judge", "submission") for k in kind_list or []):
            return False
        w = _flat(window or "")
        if _HEDGE.search(w):
            return False
        return bool(_COURT_SAYS.search(w)) or bool(tail and _NAME_SAYS.match(_flat(tail)))
    except Exception:  # noqa: BLE001
        return False


def answer_notes(text, cases, locate):
    """Notices for the page (GROUNDING_CHECKS=warn or enforce): one per wider-search case whose passage was flagged and which the answer describes, in so many words, as what 'the Supreme Court' held or said.
    `cases`: sci_search_tier's case dicts (with 'case_name' and 'passage_kinds'); `locate(text, case_name)` finds the name in the answer ((start, end) or None). Every mention of the case is read, each only within its own
    sentence. [] on any problem."""
    out = []
    try:
        text = text or ""
        names = [c["case_name"] for c in cases or [] if c.get("case_name")]
        spans = {}
        for n in names:                                            # every mention of every case
            found, pos = [], 0
            while len(found) < 6:
                sp = locate(text[pos:], n)
                if not sp:
                    break
                found.append((sp[0] + pos, sp[1] + pos))
                pos += max(sp[1], 1)
            spans[n] = found
        for c in cases or []:
            ks = c.get("passage_kinds") or []
            n = c.get("case_name")
            if not ks or not n or not spans.get(n):
                continue
            others = [sp for m, lst in spans.items() if m != n for sp in lst]
            if any(overstated(w, ks, tail) for w, tail in (_sentence(text, sp, others, with_tail=True) for sp in spans[n])):
                out.append(f"{n}: the passage we read is not the Court's own holding. " + page_note(ks) + " Check the judgment before relying on what this answer says it held.")
        return out
    except Exception:  # noqa: BLE001
        return []
