"""
refusal_text.py -- the words for a question the site cannot answer, in ONE place (2026-10-23, owner's go: "build the refusal wording"; FOLLOW_UPS 2bz).
The engine's result for a refusal carries only a state (and sometimes a one-sentence reason); until now the Streamlit page wrote the words itself, so the API sent `text: null` and a new front end would have had to copy the wording. The page
(recourse_app.render_answer) and the API (api/ask.py, api/routers/chats.py) now both take the words from here, so they cannot drift apart. test_refusal_text.py compares the page's rendered text with a golden copy.
Plain text only, no HTML: the page escapes it, a front end shows it as it likes. Nothing here says anything about the law; it only says what this tool covers and what to do next. WhatsApp (whatsapp_formatter.py) keeps its own shorter wording
and is not touched (WhatsApp work is on hold).
"""

OUT_OF_SCOPE_LABEL = "Out of scope"
DAILY_LIMIT_LABEL = "Daily limit reached"

TOPIC_LABELS = {"freeze": "a frozen bank account", "cheque_bounce": "a bounced cheque", "domestic_violence": "domestic violence"}

_BUDGET_BODY = ("Recourse has reached its usage limit for today, so it cannot answer new questions until tomorrow. "
                "If your situation is urgent, please contact a lawyer or your nearest District Legal Services Authority (free).")
_COVERED_BODY = ("This looks like it is about {topic}. Recourse focuses on arrest, FIR, police procedure and bail. For a cheque, "
                 "bank-freeze, or domestic violence matter, take the notice, letter, or details to a lawyer or your nearest District Legal Services Authority.")
_ADJACENT_BODY = ("This looks like a real legal question, but it is outside what Recourse checks — it covers police arrests, FIRs, "
                  "criminal procedure and bail under the BNS and BNSS.")
_ADJACENT_FOOTER = "For this kind of question, speak with a lawyer who handles that area of law."
_UNRELATED_BODY = "Recourse is built for police arrests, FIRs and criminal procedure under Indian law. Ask about any of those in your own words."
_NO_MATCH_BODY = ("Recourse looked but could not find anything in the law and judgments it holds that clearly matches this. Try adding detail "
                  "— what happened, and roughly when — or name the section of law if you know it.")
_TROUBLE_BODY = "This is a technical problem on Recourse's side, not your question. Try again in a moment."

ANSWER_STATES = ("single_match", "conflicting_matches")


def topic_label(domain):
    return TOPIC_LABELS.get(domain, "this")


def notice(result):
    """-> {'state', 'label', 'title', 'body', 'body_template', 'topic', 'reasoning', 'footer'} for a result that is NOT an answer, else None (an answer, or something that is not a result at all).
    `body` is the whole paragraph in plain text; `body_template` has {topic} where a page may want the topic in bold; `reasoning` is the engine's own one-sentence reason (adjacent_uncovered only), shown after the body; `footer` is the line to show last."""
    if not isinstance(result, dict):
        return None
    state = result.get("state")
    if state in ANSWER_STATES or state is None:
        return None
    base = {"state": state, "label": OUT_OF_SCOPE_LABEL, "title": None, "body": "", "body_template": "", "topic": None, "reasoning": None, "footer": None}
    if state == "budget_paused":
        return {**base, "label": DAILY_LIMIT_LABEL, "body": _BUDGET_BODY, "body_template": _BUDGET_BODY}
    if state == "covered_elsewhere_in_tool":
        topic = topic_label(result.get("redirect_domain"))
        return {**base, "title": "That's a different kind of matter", "body_template": _COVERED_BODY, "body": _COVERED_BODY.format(topic=topic), "topic": topic}
    if state == "adjacent_uncovered":
        reason = result.get("reasoning")
        return {**base, "title": "Recourse can't help with this one", "body": _ADJACENT_BODY, "body_template": _ADJACENT_BODY, "reasoning": reason if isinstance(reason, str) and reason else None, "footer": _ADJACENT_FOOTER}
    if state == "unrelated":
        return {**base, "title": "That doesn't look like a legal question", "body": _UNRELATED_BODY, "body_template": _UNRELATED_BODY}
    if state == "no_match":
        return {**base, "title": "Not enough to go on yet", "body": _NO_MATCH_BODY, "body_template": _NO_MATCH_BODY}
    return {**base, "title": "Something isn't working right now", "body": _TROUBLE_BODY, "body_template": _TROUBLE_BODY}      # classifier_unavailable, retrieval_unavailable, anything unexpected
