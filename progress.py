"""
progress.py -- live steps for a question being answered (website design WEBSITE_DESIGN.md section 3; A1.0).

A listener is set for the CURRENT THREAD by whoever wants the steps (the API service); the engine calls emit() at points it already passes. With no listener, emit() does nothing and active() is False,
so the Streamlit page and the WhatsApp bot behave exactly as before. A step says only what the code did: an id and short, plain details (counts, Act names), never the question or any passage text.
emit() never raises: a failing listener must not change an answer.
"""
import threading

_LOCAL = threading.local()
MAX_STR = 80
MAX_ITEMS = 10


def set_listener(fn):
    """fn(step_id: str, detail: dict) for this thread only; None removes it."""
    _LOCAL.fn = fn


def clear():
    _LOCAL.fn = None


def active():
    return getattr(_LOCAL, "fn", None) is not None


def _clean(v):
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v[:MAX_STR]
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_clean(x) for x in list(v)[:MAX_ITEMS] if x is None or isinstance(x, (bool, int, float, str))]
    return None          # anything else (dicts, objects) is dropped, so no passage or result can slip into a step


def emit(step, **detail):
    fn = getattr(_LOCAL, "fn", None)
    if fn is None:
        return
    try:
        fn(str(step), {k: _clean(v) for k, v in detail.items()})
    except Exception:  # noqa: BLE001 -- a listener must never change an answer
        pass
