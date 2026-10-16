
"""
whatsapp_formatter.py

Turns a chat_assistant.answer_question() result dict into a list of
plain-text WhatsApp-ready messages. No HTML, no CSS -- WhatsApp only
understands plain text plus a small set of its own markdown-like
symbols (*bold*, _italic_), so this is deliberately simpler than
recourse_app.py's answer-card rendering: WhatsApp has no equivalent of
the browser's `p:has(> strong:only-child)` CSS quirk that caused the
caps-block bugs on the website (2026-09-10/11), because there's no CSS
here at all -- *bold* just renders bold, nothing more.

Every branch of answer_question()'s state machine gets its own honest
message -- this mirrors render_answer()/render_chat_reply() in
recourse_app.py, which never lets a state fall through silently.
"""
import re as _re

import answer_style

_BOLD_MD = _re.compile(r"\*\*(.+?)\*\*")


def _md_to_whatsapp(text: str) -> str:
    """Markdown **bold** -> WhatsApp's own *bold* syntax."""
    return _BOLD_MD.sub(r"*\1*", text)


_ITALIC_MD = _re.compile(r"(?<![\w*])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![\w*])")
_HASH_HEADING = _re.compile(r"(?m)^#{1,6}[ \t]*(.+?)[ \t]*$")
_WA_HEADING = _re.compile(r"\*[^*\n]{2,90}\*")


def _md_to_whatsapp_v3(text: str) -> str:
    """Answer style v3: '#' headings and **bold** become WhatsApp *bold*, and the single-asterisk italics the v3 prompt uses for case names become WhatsApp _italic_ (a bare *x* would show as bold there)."""
    text = _HASH_HEADING.sub(lambda m: "**" + m.group(1).strip("* ") + "**", text)
    stash = []
    text = _BOLD_MD.sub(lambda m: (stash.append(m.group(1)) or "\x00%d\x00" % (len(stash) - 1)), text)
    text = _ITALIC_MD.sub(r"_\1_", text)
    return _re.sub("\x00(\\d+)\x00", lambda m: "*" + stash[int(m.group(1))] + "*", text)


def _split_v3(response_text: str) -> list:
    """Answer style v3 is a few headed parts, so it is sent as a few messages -- the opening, then one message per headed part (heading and its paragraphs together) -- instead of one message per
    paragraph, which would leave every heading alone in its own message."""
    blocks = [b.strip() for b in _re.split(r"\n\s*\n", _md_to_whatsapp_v3((response_text or "").strip())) if b.strip()]
    groups, cur = [], []
    for b in blocks:
        if _WA_HEADING.fullmatch(b) and cur:
            groups.append("\n\n".join(cur))
            cur = []
        cur.append(b)
    if cur:
        groups.append("\n\n".join(cur))
    return groups


def _split_into_messages(response_text: str) -> list:
    """Split the engine's answer into one WhatsApp message per
    paragraph (blank-line-separated), the way a person would actually
    send a few short texts instead of one wall of text. The engine
    already writes labeled sections ("Right now", "The law...",
    "Arrest procedure") as separate paragraphs, so this needs no
    special-casing -- it just follows the paragraph breaks that are
    already there."""
    if answer_style.is_v3():
        return _split_v3(response_text)
    text = _md_to_whatsapp((response_text or "").strip())
    paragraphs = [p.strip() for p in _re.split(r"\n\s*\n", text) if p.strip()]
    return paragraphs or ([text] if text else [])


_CONSULT_LINE = (
    "For a real situation, please consult a lawyer or your nearest "
    "District Legal Services Authority (free)."
)


def _format_unverified_judgments(unverified: list) -> str:
    """The WIDER, honestly UNVERIFIED judgment pool (vaquill_search.py --
    see its module docstring and memory/vaquill-search-pool.md) as one
    extra WhatsApp message, clearly separate from and less confident
    than the answer above it. Never presented as something the tool
    itself vouches for -- each case links to an Indian Kanoon search so
    the person (or their lawyer) can read the real thing themselves."""
    lines = ["*Other real court cases that might also be relevant* "
             "(I haven't personally checked these -- read them carefully "
             "before relying on them):"]
    for j in unverified:
        flag = " (may be a procedural/bail order, not a full judgment)" if j.get("procedural_disposal") else ""
        # paragraph_number is only ever set when the source genuinely has a real, earned paragraph
        # marker (see pilot_tier_search.py / _fetch_pilot_related_judgments) -- never invented here.
        para = f" -- paragraph {j['paragraph_number']}" if j.get("paragraph_number") else ""
        lines.append(f"- {j['case_name']}{para}{flag}\n  {j['ik_search_url']}")
    return "\n".join(lines)


def _format_cited_judgments(links: list) -> str:
    """The judgments this answer actually relies on, each with the real link stored for it (ADDED 2026-09-28 -- see
    chat_assistant._attach_cited_judgment_links). Unlike the hedged 'other cases' list below it, these are the
    tool's own verified sources, so no 'not checked' caution -- but the person is still told to read them."""
    lines = ["*Sources* -- you can read each one yourself:" if answer_style.is_v3() else "*Judgments this answer relies on* -- you can read each one yourself:"]
    for l in links:
        lines.append(f"- {l['case_name']} ({l.get('source_label', 'source link')})\n  {l['url']}")
    return "\n".join(lines)


def format_answer_for_whatsapp(result: dict) -> list:
    """Returns a list of message strings to send, in order. Never
    returns an empty list -- every state gets at least one honest
    message, same discipline as the website's render_answer()."""
    state = result.get("state")

    if state == "budget_paused":
        return ["Recourse has reached its usage limit for today, so I can't answer new questions until tomorrow.", _CONSULT_LINE]

    if state == "classifier_unavailable":
        return ["Sorry, I'm having a technical issue right now. Please try again in a moment."]

    if state == "unrelated":
        return [
            "I couldn't tell this was a legal question. Try describing "
            "what's actually happening -- for example, an arrest, a "
            "frozen bank account, or a bounced cheque."
        ]

    if state == "retrieval_unavailable":
        return ["Sorry, I'm having trouble reaching my legal database right now. Please try again shortly."]

    if state == "adjacent_uncovered":
        msg = "This looks like it's related to law, but it's outside what I can confidently answer right now."
        reasoning = (result.get("reasoning") or "").strip()
        if reasoning:
            msg += "\n\n" + reasoning
        return [msg, _CONSULT_LINE]

    if state == "covered_elsewhere_in_tool":
        domain = (result.get("redirect_domain") or "").replace("_", " ").strip()
        if domain:
            return [f"This looks like a {domain} question -- ask me about that directly and I can help."]
        return ["This is something I can help with -- try rephrasing what's happening."]

    if state == "no_match":
        return [
            "I don't have a confident, sourced answer for this yet.",
            _CONSULT_LINE,
        ]

    if state in ("single_match", "conflicting_matches"):
        messages = _split_into_messages(result.get("response_text"))
        if not messages:
            return ["Sorry, something went wrong putting that answer together. Please try again."]
        if state == "conflicting_matches":
            messages.insert(
                0,
                "More than one legal provision applies here, and they "
                "don't all say the same thing -- here's each one, "
                "rather than picking one for you:",
            )
        pdf_n = result.get("pdf_offer_count")
        if result.get("situation_detected") and not pdf_n:
            messages.append(
                "Want a draft court petition based on this? Reply *DRAFT* and I'll prepare one you can download."
            )
        # Overruled Register (register_hooks.py via chat_assistant._attach_register_notes): added by code, not written by the model.
        notes = list(result.get("register_notes") or []) + list(result.get("register_possible") or [])
        not_checked = result.get("register_not_checked")
        if notes or not_checked:
            messages.append("\n".join(["*Currency notes* (checked by code, not by the model):"] + [f"- {n}" for n in notes] + ([not_checked] if not_checked else [])))
        g_notes = result.get("grounding_notes")
        if g_notes:
            messages.append("\n".join(["*Checked by code against the sources we read:*"] + [f"- {n}" for n in g_notes]))
        cited = result.get("cited_judgment_links")
        if cited:
            messages.append(_format_cited_judgments(cited))
        unverified = result.get("unverified_related_judgments")
        if unverified:
            messages.append(_format_unverified_judgments(unverified))
        if pdf_n:
            # ADDED 2026-09-28: the closing offer -- always the LAST message, after any links and the other-cases list.
            # One message carries both offers when a petition is also on offer, so the person sees a single closing line.
            offer = "Reply *PDF* to get this answer as a PDF"
            if pdf_n > 1:
                offer += f", or *PDF ALL* for all {pdf_n} of your questions so far"
            offer += "."
            if result.get("situation_detected"):
                offer += " Want a draft court petition based on this? Reply *DRAFT* and I'll prepare one you can download."
            messages.append(offer)
        return messages

    # Unknown/unhandled state -- fail honestly, never silently.
    return ["Sorry, something went wrong on my end. Please try again."]
