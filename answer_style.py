"""answer_style.py -- which answer style is switched on, and for which audience. Light on purpose (no heavy imports): chat_assistant, recourse_app and whatsapp_formatter all read it.

    RESPONSE_STYLE   v1 (default, today's answers) | v2 | v3 (the Adviser for laypeople, the Research Note for lawyers) | v3-lawyer (v3, Research Note for everybody)
    audience         'layman' or 'lawyer'; chosen on the page (a switch shown only when RESPONSE_STYLE=v3). It has an effect only under v3; under v1 and v2 everybody gets that style.

Values typed with quotation marks or spaces in a hosting dashboard are tolerated. The audience travels in a thread-local set by chat_assistant.answer_question for the length of one call, so the three places that
call the model need no new parameter.
"""
import os
import threading

STYLES = ("v1", "v2", "v3", "v3-lawyer")
_LOCAL = threading.local()


def style():
    v = (os.environ.get("RESPONSE_STYLE") or "v1").strip().strip("\"'").strip().lower()
    return v if v in STYLES else "v1"


def is_v3():
    return style() in ("v3", "v3-lawyer")


def normalise_audience(a):
    return "lawyer" if str(a or "").strip().lower() in ("lawyer", "lawyers", "advocate") else "layman"


def set_audience(a):
    _LOCAL.audience = normalise_audience(a) if a is not None else None


def set_channel(c):
    _LOCAL.channel = (str(c).strip().lower() if c else None)


def get_channel():
    return getattr(_LOCAL, "channel", None)


def requested_audience():
    return getattr(_LOCAL, "audience", None) or "layman"


def effective_audience():
    """'lawyer' only when v3 is on and either the whole site is v3-lawyer or this call asked for it; 'layman' otherwise."""
    s = style()
    if s == "v3-lawyer":
        return "lawyer"
    if s == "v3":
        return requested_audience()
    return "layman"


def template_key():
    """Which prompt template applies to this call: 'v1', 'v2', 'v3' (layman) or 'v3-lawyer'."""
    s = style()
    if s in ("v3", "v3-lawyer"):
        return "v3-lawyer" if effective_audience() == "lawyer" else "v3"
    return s


def uses_cache():
    """The human-approved answer cache holds v1 wording written for laypeople, so it is read and written only under v1."""
    return style() == "v1"
