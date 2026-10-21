"""
api/engine_adapter.py -- runs the answer engine for the API (WEBSITE_DESIGN.md section 5.2).
The engine keeps its per-question state in threading.local (cost log, audience, grounding notes, Act cache, search tier), so ONE question must run start to finish in ONE thread: work() is the function a
worker thread runs. A bounded pool (API_ENGINE_WORKERS) limits how many run at once and a bounded count of waiting questions makes the service say "busy" (429) instead of piling up.
Nothing here edits the engine's result: it is made JSON-safe and handed on whole.
"""
import concurrent.futures
import json
import math
import threading
import time

from . import config


# The same four topics the Streamlit page and the WhatsApp bot always pass (recourse_app.py, whatsapp_bot.py): without them the engine answers a cheque-bounce, bank-freeze, domestic-violence or NDPS
# question with a redirect instead of an answer. test_api_ask.py compares this set with the one in recourse_app.py so the two cannot drift apart.
INLINE_DOMAINS = frozenset({"cheque_bounce", "freeze", "domestic_violence", "ndps"})


class EngineBusy(Exception):
    """Too many questions are running or waiting."""


_ENGINE = {"mod": None}
_ENGINE_LOCK = threading.Lock()


def set_engine(mod):
    """For tests: use this object (it needs answer_question(question, audience=..., channel=...)) instead of importing chat_assistant."""
    with _ENGINE_LOCK:
        _ENGINE["mod"] = mod


def _engine():
    with _ENGINE_LOCK:
        if _ENGINE["mod"] is None:
            import chat_assistant      # heavy: loads the library; done at the first question, never by /api/health
            _ENGINE["mod"] = chat_assistant
        return _ENGINE["mod"]


def _default(o):
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    return str(o)


def _scrub(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): _scrub(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_scrub(v) for v in o]
    return o


def jsonable(obj):
    """The engine's result as plain JSON values (sets and tuples to lists, numpy values to numbers, NaN and infinity to null). Nothing is dropped or renamed."""
    return _scrub(json.loads(json.dumps(obj, default=_default, ensure_ascii=False)))


def work(question, audience, on_step):
    """Runs in a worker thread: one question, start to finish. on_step(step_id, detail) hears the engine's live steps (this thread only)."""
    import cost_log
    import progress
    eng = _engine()
    t0 = time.monotonic()
    progress.set_listener(on_step)
    try:
        result = eng.answer_question(question, inline_domains=INLINE_DOMAINS, audience=audience, channel=None)
    finally:
        progress.clear()
    rec = None
    try:
        rec = cost_log.last_question()
    except Exception:  # noqa: BLE001
        pass
    return {"result": jsonable(result), "cost_inr": (rec or {}).get("inr"), "elapsed_ms": int((time.monotonic() - t0) * 1000)}


class Runner:
    def __init__(self, workers, waiting=None):
        self.workers = workers
        self.limit = workers + (workers * 2 if waiting is None else waiting)
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="engine")
        self._lock = threading.Lock()
        self._inflight = 0

    @property
    def inflight(self):
        with self._lock:
            return self._inflight

    def submit(self, fn, *args):
        with self._lock:
            if self._inflight >= self.limit:
                raise EngineBusy()
            self._inflight += 1

        def run():
            try:
                return fn(*args)
            finally:
                with self._lock:
                    self._inflight -= 1
        try:
            return self._pool.submit(run)
        except Exception:
            with self._lock:
                self._inflight -= 1
            raise


_RUNNER = {"r": None}
_RUNNER_LOCK = threading.Lock()


def get_runner():
    with _RUNNER_LOCK:
        if _RUNNER["r"] is None:
            _RUNNER["r"] = Runner(config.engine_workers())
        return _RUNNER["r"]


def reset_runner(runner=None):
    """For tests."""
    with _RUNNER_LOCK:
        _RUNNER["r"] = runner
