"""
quote_notes.py -- a wider-search passage whose number is not the judgment's own (added 2026-10-26, FOLLOW_UPS 2cm; prototype).

The wide index cuts a judgment at every line that starts "N. ", so a quotation of an earlier decision, a statute section, an affidavit, a wrapped citation or a numbered list inside paragraph 25 becomes a "passage" with the
number of the quoted thing: the owner's staging answer credited Sadhwi Pragyna Singh Thakur (2011) with "paragraph 8", which was a paragraph of an older decision quoted inside Sadhwi's paragraph 25. The search service (when
SCI_QUOTES=on there; sci_quotes.py in the research repository) finds such passages from the numbering alone and sends, with the result, {"quote": {"within": "25", "kind": "introduced" | "off_sequence", "intro": "<the
judgment's own words that end the paragraph before>", "block": n, "ends_at": "24"?}}. This module words that for three places: the head of the passage in the prompt, the "Note by code" under it, and the page.

Nothing here is switched on or off in this repository: a result without "quote" (a service that does not send it, SCI_QUOTES unset, a passage that is where it says it is) is handled exactly as before. What the service sends is a
reading of the NUMBERING: it says that the number is not a paragraph of the judgment, and where the passage is (inside paragraph 25). It does not say that the words are a quotation; "introduced" means the paragraph before ends in
words such as "has observed as under :-", which also introduce a list.

WHAT IS DONE WITH IT (changed 2026-10-27, FOLLOW_UPS 2cn). The first version told the answer model about such a passage (a note under it, "refer to it only as inside paragraph 25", and the older rule "if you mention it, say it is a
quotation"). The model obeyed: the lawyer-mode answer to the owner's circumstantial-evidence question carried a sentence about "a passage inside paragraph 19 of Hongro Ngotan ... appears to reproduce an earlier decision's
reasoning (G. Parshwanath ...) and should not be treated as that court's holding", and a "Gaps" sentence about the same, in the middle of the argument. So now: (1) sci_search_tier.feed_block leaves such a passage out of what the model
reads (another passage of the same case may take its place); (2) the prompt rule says never to mention a quotation at all; (3) drop_provenance_sentences removes, from the finished answer, a sentence that names a wider-search case
AND talks about where a passage sits or what it quotes. The search page (no model) still shows "inside paragraph 25" with page_note.
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


# ---- the finished answer: no talk about where a passage sits or what it may quote
_TALK = re.compile(
    r"appears?\s+(?:to\s+)?(?:partly\s+|partially\s+)?(?:reproduc\w*|quot\w*)|appears?\s+to\s+be\s+(?:partly\s+|partially\s+)?quoted|"
    r"\b(?:partly|partially|probably|possibly)\s+quoted|\binside\s+paragraph\s+\d+|\bwithin\s+paragraph\s+\d+\s+of\b|"
    r"should\s+not\s+be\s+treated\s+as\s+(?:that|the|this|its)\s+court'?s?\s+(?:own\s+)?holding|passages?\s+quoted\s+in\b|"
    r"(?:original|source)\s+(?:should|must)\s+be\s+(?:checked|verified)|unnamed\s+earlier\s+decision|quoted\s+(?:in|from)\s+an?\s+earlier\s+decision|"
    r"reproduc\w+\s+an\s+earlier\s+decision", re.I)


def drop_provenance_sentences(text, case_names, locate):
    """(text without the sentences that name one of `case_names` AND talk about where a passage sits or what it may quote, how many were removed). `locate(text, name)` finds a name in a stretch of text ((start, end) or None).
    A sentence is a stretch between sentence ends (passage_notes._BOUND, with the full stops of 'v.', 'Ors.' and initials not counted); the line breaks after a removed sentence are kept, so headings and paragraphs stay.
    Only those words in that company are removed: 'X quoted Y with approval' stays. Returns the text unchanged on any problem."""
    try:
        import passage_notes
        text = text or ""
        if not text or not case_names:
            return text, 0
        flat = passage_notes._flat(text)
        cuts = [0] + [m.end() for m in passage_notes._BOUND.finditer(flat)] + [len(text)]
        out, dropped = [], 0
        for i in range(len(cuts) - 1):
            seg = text[cuts[i]:cuts[i + 1]]
            if seg and _TALK.search(seg) and any(locate(seg, n) for n in case_names if n):
                dropped += 1
                tail = seg[len(seg.rstrip()):]
                if "\n" in tail:
                    out.append(tail)
                continue
            out.append(seg)
        if not dropped:
            return text, 0
        new = "".join(out)
        new = re.sub(r"[ \t]+(\n)", r"\1", new)
        new = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", new)
        return new, dropped
    except Exception:  # noqa: BLE001
        return text, 0
