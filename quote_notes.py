"""
quote_notes.py -- a wider-search passage whose number is not the judgment's own (added 2026-10-26, FOLLOW_UPS 2cm; prototype).

The wide index cuts a judgment at every line that starts "N. ", so a quotation of an earlier decision, a statute section, an affidavit, a wrapped citation or a numbered list inside paragraph 25 becomes a "passage" with the
number of the quoted thing: the owner's staging answer credited Sadhwi Pragyna Singh Thakur (2011) with "paragraph 8", which was a paragraph of an older decision quoted inside Sadhwi's paragraph 25. The search service (when
SCI_QUOTES=on there; sci_quotes.py in the research repository) finds such passages from the numbering alone and sends, with the result, {"quote": {"within": "25", "kind": "introduced" | "off_sequence", "intro": "<the
judgment's own words that end the paragraph before>", "block": n, "ends_at": "24"?}}. This module words that for three places: the head of the passage in the prompt, the "Note by code" under it, and the page.

Nothing here is switched on or off in this repository: a result without "quote" (a service that does not send it, SCI_QUOTES unset, a passage that is where it says it is) is worded exactly as before. What the service sends is a
reading of the NUMBERING: it says that the number is not a paragraph of the judgment, and where the passage is (inside paragraph 25). It does not say that the words are a quotation; "introduced" means the paragraph before ends in
words such as "has observed as under :-", which also introduce a list. The notes say so.

Used by sci_search_tier.feed_block (head and note), by passage_notes (the kind "quoted", for the page note and the notice) and by search_service.wider (the search page).
"""
import re

KINDS = ("introduced", "off_sequence")
_WITHIN = re.compile(r"^\d{1,4}$")
MAX_INTRO = 360


def clean(q):
    """The quote record if it is well formed ({'within': digits, 'kind': one of KINDS, optional 'intro': str, optional 'ends_at': digits}), else None. Never raises."""
    try:
        if not isinstance(q, dict) or not _WITHIN.match(str(q.get("within") or "")) or q.get("kind") not in KINDS:
            return None
        out = {"within": str(q["within"]), "kind": q["kind"]}
        intro = re.sub(r"\s+", " ", str(q.get("intro") or "")).strip()
        if q["kind"] == "introduced" and intro:
            out["intro"] = intro[:MAX_INTRO]
        if _WITHIN.match(str(q.get("ends_at") or "")):
            out["ends_at"] = str(q["ends_at"])
        return out
    except Exception:  # noqa: BLE001
        return None


def head_phrase(q):
    """The place in the heading of a passage, in place of ', paragraph 8': ', inside paragraph 25'."""
    return f", inside paragraph {q['within']}"


def own_number(text):
    """The number a passage starts with ('8. From the order-sheets ...' -> '8'), or None."""
    m = re.match(r"\s*(\d{1,4})\s*[.)]\s", text or "")
    return m.group(1) if m else None


def prompt_note(q, text=""):
    """The 'Note by code' paragraph put under a passage in the prompt (starts with a line break). `text`: the passage, to name the number it starts with."""
    n = own_number(text)
    num = f' (it starts with "{n}.")' if n else ""
    within = q["within"]
    if q["kind"] == "introduced" and q.get("intro"):
        what = (f'The judgment\'s own words just before the passage are: "{q["intro"]}" If those words introduce a quotation, the passage is the text of the quoted decision or document, NOT this court\'s own words: '
                f"do not say that the listed court held, decided, recorded or observed it, and build no ground and no For/Against point on it as this court's holding. If they introduce a list, the list belongs to what that paragraph describes.")
    elif q["kind"] == "introduced":
        what = "The paragraph before it ends in words that introduce a quotation or a list. If it is a quotation, the passage is NOT this court's own words: do not say that the listed court held, decided or recorded it."
    else:
        what = ("It can be a quotation from another decision or document, a statute section, a footnote, a wrapped citation or a numbered list, and nothing in the passage's number says which. Before you treat the words as this court's own "
                "holding, check from the passage itself that they are; if you cannot tell, say that it is a passage set out in paragraph " + within + " and do not credit it to the court.")
    tail = f" Its last part is the judgment's own paragraph {q['ends_at']}." if q.get("ends_at") else ""
    return (f"\n[Note by code -- read before using this passage: the number{num} is NOT a paragraph number of this judgment. The passage sits inside paragraph {within} of the judgment. {what}{tail} "
            f"Refer to it only as \"inside paragraph {within}\" and never give the number it starts with as a paragraph.]")


def page_note(q):
    """One or two plain sentences for the sources box and the table (the reader's version of the note)."""
    base = f"This passage is set out inside paragraph {q['within']} of the judgment; the number it starts with is not a paragraph of that judgment."
    if q["kind"] == "introduced" and q.get("intro"):
        base += f" The judgment introduces it with these words: “{q['intro'][:240].rstrip()}{'...' if len(q['intro']) > 240 else ''}” It may be a quotation from another decision or document, which is not this court's own holding."
    elif q["kind"] == "introduced":
        base += " It follows words that introduce a quotation or a list, and may be a quotation from another decision, which is not this court's own holding."
    else:
        base += " It may be a quotation, a statute section, a footnote, a wrapped citation or a list; check the judgment before treating the words as this court's own."
    return base
