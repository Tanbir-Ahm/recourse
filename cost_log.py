"""cost_log.py -- what one question costs, measured from the tokens each call really used (not guessed).

Every model call the answer path makes reports its token counts; this module turns them into dollars and rupees and prints two kinds of line the hosting log search can find:
    COST_CALL {...}      one per call (scope check, the answer, a retry, a wider search, the question embedding), printed as it happens
    COST_QUESTION {...}  one per question, printed when the answer is finished: every call, the total in dollars and in rupees, the style and the audience
Questions appear only as a short hash (never the text). Nothing here can break an answer: every function swallows its own errors.

Prices are USD per million tokens, from Anthropic's price list of 2026-10-06 and (for Voyage) the figures recorded in this project; PRICES_JSON overrides them ('{"model": [in, out]}'; Voyage models take one number).
The rupee rate is USD_INR (default 96.5, a mid-market figure read 2026-10-14: set the real rate in the hosting variables).
"""
import hashlib
import json
import os
import threading

_LOCAL = threading.local()
ANTHROPIC = {                       # (input, output) dollars per million tokens
    "claude-sonnet-5": (2.0, 10.0), "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0), "claude-haiku-4-5": (1.0, 5.0), "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0),
}
VOYAGE = {"voyage-law-2": 0.12, "rerank-3-lite": 0.02, "rerank-2": 0.05}      # dollars per million tokens; the two re-ranker figures are third-party list prices, not checked with Voyage
DEFAULT_USD_INR = 96.5


def _prices():
    a, v = dict(ANTHROPIC), dict(VOYAGE)
    try:
        extra = json.loads(os.environ.get("PRICES_JSON") or "{}")
        for k, val in extra.items():
            if isinstance(val, (list, tuple)) and len(val) == 2:
                a[k] = (float(val[0]), float(val[1]))
            else:
                v[k] = float(val)
    except Exception:  # noqa: BLE001
        pass
    return a, v


def usd_inr():
    try:
        return float((os.environ.get("USD_INR") or "").strip().strip("\"'") or DEFAULT_USD_INR)
    except ValueError:
        return DEFAULT_USD_INR


def _qhash(question):
    return hashlib.sha256((question or "").encode("utf-8")).hexdigest()[:12]


def begin(question):
    _LOCAL.calls, _LOCAL.q = [], _qhash(question)


def _record(rec):
    try:
        rec["inr"] = round(rec["usd"] * usd_inr(), 4)
        rec["usd"] = round(rec["usd"], 8)
        if getattr(_LOCAL, "calls", None) is not None:
            _LOCAL.calls.append(rec)
        print("COST_CALL " + json.dumps({**rec, "q": getattr(_LOCAL, "q", None)}), flush=True)
    except Exception:  # noqa: BLE001
        pass


def note_anthropic(label, model, usage):
    """usage is the SDK's response.usage (input_tokens, output_tokens; output includes the model's thinking)."""
    try:
        a, _ = _prices()
        tin, tout = int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
        pin, pout = a.get(model, a.get(str(model).split("-2025")[0], (0.0, 0.0)))
        _record({"label": label, "model": model, "in": tin, "out": tout, "usd": (tin * pin + tout * pout) / 1e6, "priced": model in a or str(model).split("-2025")[0] in a})
    except Exception:  # noqa: BLE001
        pass


def note_voyage(label, model, tokens):
    try:
        _, v = _prices()
        tokens = int(tokens or 0)
        _record({"label": label, "model": model, "tokens": tokens, "usd": tokens * v.get(model, 0.0) / 1e6, "priced": model in v})
    except Exception:  # noqa: BLE001
        pass


def note_search_usage(label, usage):
    """The sci-search service's per-search usage block: {'embed_model','embed_tokens','rerank_model','rerank_tokens'}."""
    try:
        if isinstance(usage, dict):
            note_voyage(label + "_embed", usage.get("embed_model") or "voyage-law-2", usage.get("embed_tokens"))
            note_voyage(label + "_rerank", usage.get("rerank_model") or "rerank-3-lite", usage.get("rerank_tokens"))
    except Exception:  # noqa: BLE001
        pass


def finish(style="", audience=""):
    """Print the COST_QUESTION line for the question begun in this thread and clear it. Returns the dict (or None)."""
    try:
        calls = getattr(_LOCAL, "calls", None)
        if calls is None:
            return None
        usd = sum(c["usd"] for c in calls)
        rec = {"q": getattr(_LOCAL, "q", None), "style": style, "audience": audience, "calls": calls, "usd": round(usd, 8), "usd_inr": usd_inr(), "inr": round(usd * usd_inr(), 4),
               "unpriced": [c["model"] for c in calls if not c.get("priced")]}
        print("COST_QUESTION " + json.dumps(rec), flush=True)
        _LOCAL.calls = None
        return rec
    except Exception:  # noqa: BLE001
        return None
