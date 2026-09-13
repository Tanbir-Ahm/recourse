
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

_BOLD_MD = _re.compile(r"\*\*(.+?)\*\*")


def _md_to_whatsapp(text: str) -> str:
    """Markdown **bold** -> WhatsApp's own *bold* syntax."""
    return _BOLD_MD.sub(r"*\1*", text)


def _split_into_messages(response_text: str) -> list:
    """Split the engine's answer into one WhatsApp message per
    paragraph (blank-line-separated), the way a person would actually
    send a few short texts instead of one wall of text. The engine
    already writes labeled sections ("Right now", "The law...",
    "Arrest procedure") as separate paragraphs, so this needs no
    special-casing -- it just follows the paragraph breaks that are
    already there."""
    text = _md_to_whatsapp((response_text or "").strip())
    paragraphs = [p.strip() for p in _re.split(r"\n\s*\n", text) if p.strip()]
    return paragraphs or ([text] if text else [])


_CONSULT_LINE = (
    "For a real situation, please consult a lawyer or your nearest "
    "District Legal Services Authority (free)."
)


def format_answer_for_whatsapp(result: dict) -> list:
    """Returns a list of message strings to send, in order. Never
    returns an empty list -- every state gets at least one honest
    message, same discipline as the website's render_answer()."""
    state = result.get("state")

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
        if result.get("situation_detected"):
            messages.append(
                "Want a draft court petition based on this? Reply *DRAFT* and I'll prepare one you can download."
            )
        return messages

    # Unknown/unhandled state -- fail honestly, never silently.
    return ["Sorry, something went wrong on my end. Please try again."]
