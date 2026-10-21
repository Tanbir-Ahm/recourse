"""
api/config.py -- the API service's settings, all from the environment (never from the repository). Read at call time so a changed variable needs a restart only, not a code change.
API_ACCESS_TOKEN     secret that callers send as the X-API-Key header. UNSET = the ask route is switched off (503): the service fails closed, because an open ask route spends the owner's money.
API_ENGINE_WORKERS   how many questions run at once (default 4, 1 to 16). Each runs in ONE worker thread for its whole life (the engine's per-request state is thread-local).
API_ASK_TIMEOUT_SECONDS   how long a caller waits for an answer (default 120, 10 to 600). The model call itself is not cancelled.
API_MAX_QUESTION_CHARS    longest question accepted (default 6000, 200 to 20000).
"""
import os


def _env(name):
    return (os.environ.get(name) or "").strip().strip("\"'")


def access_token():
    return _env("API_ACCESS_TOKEN")


def _int(name, default, lo, hi):
    try:
        v = int(_env(name))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def engine_workers():
    return _int("API_ENGINE_WORKERS", 4, 1, 16)


def ask_timeout_seconds():
    return _int("API_ASK_TIMEOUT_SECONDS", 120, 10, 600)


def max_question_chars():
    return _int("API_MAX_QUESTION_CHARS", 6000, 200, 20000)
