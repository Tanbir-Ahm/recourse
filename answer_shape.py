"""
answer_shape.py -- the lawyers' note takes its shape from what the person ASKED (ANSWER_SHAPE, default off; owner's go 2026-11-09: "Yes, build this change, then step 3"; research repository FOLLOW_UPS 2ef).

The fault. The lawyers' note has one fixed skeleton (Bottom line, Facts, numbered issues, For/Against table, Grounds, Gaps), "about 500-900 words, each issue 80-150 words", at most 8 sections and 6 cases. On staging (2026-11-09) a lawyer asked
"what are the other sections my client can be charged with? And how can I counter them as his lawyer? Give me detailed explanations": the note answered the question with one offence section and three charge-framing sections of the BNSS, inside the same
short skeleton. The cap on length contradicted "detailed"; the skeleton had no place for "the other sections", so the ask was answered by whatever fitted the skeleton. Separately the Bottom line ("2-3 lines" holding the answer, the strongest authority and
the main risk, in sentences of 35 words or fewer) came out garbled or 100 words long in four of five saved notes.

What this does (lawyers' note only; the Hard rules block and every support rule are untouched; the page and the other voices are untouched):
  1. ASKS BECOME HEADINGS. The person's current message is split into the sentences that ask or request something (case_file.split_message); when there are two or more, the prompt gets a short block that lists them in order and asks for ONE numbered heading per ask,
     in the same order, each answered from the material only; an ask the material cannot answer gets a one-sentence heading saying what is missing, never a section that does not answer it (a procedure section is not an answer to "what can he be charged with").
  2. LENGTH FOLLOWS THEIR WORDS. "Detailed", "in detail", "elaborate", "step by step" lift the note to about 1,800 words and the limits of 8 sections and 6 cases to 14 and 10; "briefly", "in short", "yes or no" shorten it to about 300 words. Decided by a short word list in code, not by the model.
  3. THE BOTTOM LINE IS THREE SHORT LINES (Answer, Strongest authority, Main risk), each one sentence of at most 30 words, so there is no long compound sentence to garble.
  4. A CHECKLIST UNDER THE NOTE, built by code: "You asked for: A, B, C", each marked answered under heading N, answered by saying the material lacks it, or not found in the note. A silent skip becomes visible.
  5. A log line BOTTOM_LINE_CHECK (words and longest sentence of the Bottom line); nothing is rewritten.

Pure functions, no model, no network.
"""
import os
import re

import case_file as CF

MAX_ASKS = 5

_DETAILED = re.compile(
    r"\b(?:detailed|in[- ]detail|in[- ]depth|elaborat\w*|thorough\w*|comprehensive\w*|at (?:great )?length|step[- ]by[- ]step|full(?:y)? explain\w*|full explanation\w*|exhaustive\w*|explain (?:each|every|all)\b)", re.I)
_BRIEF = re.compile(r"\b(?:briefly|in brief|brief answer|in short|short answer|one[- ]line|in one line|yes or no|quick answer|in a nutshell|tl;?dr|summari[sz]e briefly|just tell me)\b", re.I)
_STYLE_ONLY = re.compile(
    r"^(?:please\s+|kindly\s+)?(?:and\s+|also\s+)?(?:give|provide|write|explain|answer|make|keep)\b(?:\s+(?:me|it|this|that|them|everything|all))?(?:\s+(?:a|an|the))?(?:\s+(?:very|more|really))?\s*"
    r"(?:detailed|brief|short|thorough|full|complete|comprehensive|elaborate|step[- ]by[- ]step|in[- ]depth|simple)?\s*(?:expl\w*|answers?|responses?|replies|detail|details|note|analysis|analyses|reasoning)?\s*(?:in detail|in depth|briefly|in brief|please|clearly|thoroughly|step by step)?[.!]?$", re.I)
_STANDARD = re.compile(r"^(?:bottom line|facts assumed|application to the facts|grounds that can be urged|gaps and checks)\b", re.I)
_LACKS = re.compile(r"(?:material|passages?|sections? (?:provided|shown))\s+(?:does|do|did)\s+not\s+(?:show|contain|include|address|hold)|not shown in the material|cannot be (?:determined|stated|answered) from the material|the material (?:holds|has) no", re.I)
_STOP = frozenset("the and with from that this these those what which when where whom whose have has had having been were was are will would could should shall might must can cannot does did doing done not nor but for into onto over under after before about against between during through than then there here their them they our your yours his her hers its who why how also only just very more most such some other any each every both either neither whether however though although because since until while once again further give detailed explanations explanation explain please tell".split())


def enabled():
    """ANSWER_SHAPE=on (default off). Quotation marks around the value are ignored."""
    return (os.environ.get("ANSWER_SHAPE") or "").strip().strip("\"'").strip().lower() in ("on", "true", "1", "yes")


def tier(message):
    """'detailed', 'brief' or 'normal', from the person's own words. Both kinds of word in one message: 'normal'."""
    d, b = bool(_DETAILED.search(message or "")), bool(_BRIEF.search(message or ""))
    return "detailed" if d and not b else ("brief" if b and not d else "normal")


def asks(message):
    """The things the person asked for in this message: its question and request sentences, in order, a pure style instruction ('give me detailed explanations') left out, each copied word for word, at most MAX_ASKS."""
    out = []
    for s in CF.split_message(message)[1]:
        s = re.sub(r"^(?:and|also|but|so|then|now)\s+", "", s.strip(), flags=re.I)
        if len(s) < 8 or _STYLE_ONLY.match(s):
            continue
        out.append(s)
    return out[:MAX_ASKS]


def applies(message):
    """True when the shape block has anything to say about this message: two or more asks, or a length tier other than normal."""
    return len(asks(message)) >= 2 or tier(message) != "normal"


LENGTH = {
    "detailed": ("The person asked for detail. Explain each heading as fully as the material supports, up to about 1,800 words in all (instead of 500-900), each numbered heading up to about 300 words; the limits of 8 sections and 6 cases become 14 "
                 "sections and 10 cases. Finish every part, ending with Gaps and checks."),
    "brief": "The person asked for a short answer. Keep the whole note to about 300 words; keep the Bottom line, the grounds and Gaps and checks; one sentence per numbered heading.",
    "normal": "",
}


def shape_block(message):
    """The prompt block for this message ('' when nothing applies). It is added after the rules (the cached part of the prompt) and says plainly which lines of the numbered shape it replaces; the Hard rules and every support rule still apply."""
    a, t = asks(message), tier(message)
    if len(a) < 2 and t == "normal":
        return ""
    lines = ["## Shape for THIS question (it replaces item 1, item 3 and the Length line of the numbered shape above; the Hard rules and every other rule still apply)"]
    lines.append("**Bottom line**: write exactly three short lines, each starting with its label in plain text: `Answer:`, `Strongest authority:`, `Main risk:`. One sentence each, at most 30 words, no semicolons, no parenthesis. "
                 "(Do not fold the three into one sentence.)")
    if len(a) >= 2:
        lines.append("The person asked for these things, in this order:")
        lines += [f"{i}. {x}" for i, x in enumerate(a, 1)]
        lines.append("Give ONE numbered heading for each of them, in the same order, written as that ask in your own words (for example `**1. Other sections he may be charged with**`), and answer what was asked under it, from the material only. "
                     "When an ask is how to counter, defend against or answer something, give for each point the argument, the provision or case it rests on, and what evidence would decide it. "
                     "If the material does not show what an ask needs, write ONE sentence under its heading saying what is missing and go on: never fill the gap with a section that does not answer it (a section on how charges are framed is not an answer "
                     "to \"what can he be charged with\"). Then keep **Application to the facts**, **Grounds that can be urged** and **Gaps and checks** as above.")
    if LENGTH[t]:
        lines.append("Length: " + LENGTH[t])
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ the checklist under the note
def _headings(text):
    out = []
    for m in re.finditer(r"(?m)^\s*\*\*([^*\n]{2,160})\*\*\s*$", text or ""):
        h = m.group(1).strip()
        if not _STANDARD.match(h):
            out.append((m.start(), m.end(), h))
    return out


def _words(s):
    return {w[:5] for w in re.findall(r"[a-z]{4,}", (s or "").lower()) if w not in _STOP}


def checklist(message, text):
    """-> None, or {'items': [{'ask', 'status', 'heading'}], 'answered': n, 'total': n}. Only for a message with two or more asks. status: 'answered' (a heading of the note answers it and says something), 'material_lacks' (the heading says the material does not show it),
    'not_found' (no heading of the note matches the ask). Headings are matched by their number first (the shape asks for the same order), then by shared content words."""
    try:
        a = asks(message)
        if len(a) < 2:
            return None
        hs = _headings(text)
        used, items = set(), []
        for i, ask in enumerate(a, 1):
            pick, aw = None, _words(ask)
            for k, (s, e, h) in enumerate(hs):                        # the number first, when the heading also shares a content word with the ask (a note that numbers its issues in its own way is not taken to answer ask N by its number)
                if k not in used and re.match(rf"{i}\s*[.)]", h) and aw & _words(h):
                    pick = k
                    break
            if pick is None:                                          # then the best overlap of content words
                best = 0
                for k, (s, e, h) in enumerate(hs):
                    ov = len(aw & _words(h))
                    if k not in used and ov > best:
                        pick, best = k, ov
            if pick is None:
                items.append({"ask": ask, "status": "not_found", "heading": None})
                continue
            used.add(pick)
            s, e, h = hs[pick]
            nxt = hs[pick + 1][0] if pick + 1 < len(hs) else len(text)
            body = text[e:nxt]
            lacks = bool(_LACKS.search(body[:400])) and len(body.strip()) < 600
            items.append({"ask": ask, "status": "material_lacks" if lacks else "answered", "heading": h})
        return {"items": items, "answered": sum(1 for x in items if x["status"] == "answered"), "total": len(items)}
    except Exception:  # noqa: BLE001
        return None


def bottom_line_stats(text):
    """(words in the Bottom line, words of its longest sentence); (0, 0) when it cannot be read. For a log line only."""
    try:
        m = re.search(r"(?is)\*\*\s*bottom line\s*\*\*\s*(.*?)(?=\n\s*\*\*|\Z)", text or "")
        if not m:
            return 0, 0
        body = m.group(1)
        sents = [s for s in re.split(r"(?<=[.!?])\s+|\n+", body) if s.strip()]
        return len(body.split()), max((len(s.split()) for s in sents), default=0)
    except Exception:  # noqa: BLE001
        return 0, 0
