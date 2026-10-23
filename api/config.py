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


# ---- accounts (step A3). Every switch here fails CLOSED: unset means the feature is off.
def _flag(name):
    return _env(name).lower() in ("1", "on", "true", "yes")


def accounts_open():
    """ACCOUNTS_OPEN=on lets real people sign in. It stays off until the lawyer's privacy notice and consent text are in place (gate G1): sign-in and every signed-in route answer 503 while it is off."""
    return _flag("ACCOUNTS_OPEN")


def anon_trial_on():
    """ANON_TRIAL=on opens the three-questions-without-signing-in route (owner's decision D4). Off by default: that route spends money without any sign-in."""
    return _flag("ANON_TRIAL")


def google_client_id():
    """The OAuth client id Google ID tokens must be issued for (the 'aud' claim). Unset: Google sign-in is off."""
    return _env("GOOGLE_CLIENT_ID")


def streamlit_secret():
    """The secret shared with the Streamlit service for its short-lived signed tokens (WEBSITE_DESIGN 1.3). Unset: that path is off. Shorter than 32 characters counts as unset."""
    v = _env("STREAMLIT_API_SECRET")
    return v if len(v) >= 32 else ""


def ip_hash_secret():
    """The secret that scrambles IP addresses before they are stored or counted (an HMAC). Unset: nothing that needs an IP works (the anonymous trial refuses). Shorter than 32 characters counts as unset."""
    v = _env("IP_HASH_SECRET")
    return v if len(v) >= 32 else ""


def session_days():
    return _int("API_SESSION_DAYS", 30, 1, 90)


def cookie_secure():
    """Session cookies carry the Secure flag unless API_COOKIE_SECURE=off (only for a local test over plain http)."""
    return _env("API_COOKIE_SECURE").lower() not in ("0", "off", "false", "no")


def cors_origins():
    """Origins allowed to call the API from a browser (the new front end), comma separated. Unset: none."""
    return [o.strip().rstrip("/") for o in _env("CORS_ALLOW_ORIGINS").split(",") if o.strip()]


def trusted_proxy_hops():
    """How many proxies in front of the service add to X-Forwarded-For (Railway's edge: 1). The client address is the entry that many from the RIGHT, so a caller cannot choose it by sending its own header."""
    return _int("TRUSTED_PROXY_HOPS", 1, 0, 5)


def anon_budget_inr():
    """The most the anonymous trial may spend in one IST day, in rupees (its own budget, apart from the signed-in users'). Unset or 0: the trial is closed."""
    try:
        return max(0.0, float(_env("ANON_DAILY_BUDGET_INR")))
    except ValueError:
        return 0.0


def allow_placeholder_legal():
    """ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL=on lets accounts open while the privacy notice and terms are still placeholders. FOR STAGING TESTS ONLY: real people must not be asked to accept placeholder text (gate G1)."""
    return _flag("ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL")


def anon_ip_daily_limit():
    """The most anonymous-trial questions one scrambled IP address may ask in an IST day: a flood guard, not the per-person cap (that is the device cap, three a day, from the 'anonymous' plan). Many people can share one address (mobile carriers), so
    this is much larger than three. Default 20."""
    return _int("ANON_IP_DAILY_LIMIT", 20, 1, 100000)


def anon_est_cost_inr():
    """What a trial question that is still running counts as against the trial's daily budget until its real cost is known (rupees; default 10, about the measured cost of a full answer)."""
    try:
        return max(0.0, float(_env("ANON_EST_COST_INR")))
    except ValueError:
        return 10.0


def rate_limit_per_minute():
    """Requests per minute one address may make to the /api routes (health excepted), 0 = no limit. Default 120."""
    return _int("API_RATE_LIMIT_PER_MINUTE", 120, 0, 100000)


def auth_rate_per_minute():
    """Requests per minute one address may make to the sign-in routes, 0 = no limit. Default 20."""
    return _int("API_AUTH_RATE_PER_MINUTE", 20, 0, 100000)


def purge_on():
    """The hourly retention purge runs unless API_PURGE=off."""
    return _env("API_PURGE").lower() not in ("0", "off", "false", "no")


def purge_interval_seconds():
    return _int("API_PURGE_INTERVAL_SECONDS", 3600, 60, 86400)


def anon_rate_per_minute():
    """Requests per minute one address may make to the free-trial route (default 6; 0 = no limit). Stricter than the general limit because every trial question, even a refused one, costs real money."""
    return _int("API_ANON_RATE_PER_MINUTE", 6, 0, 100000)


def refusal_daily_limit():
    """How many refused questions (turned away by the topic bar, "not enough to go on", and so on: free of the daily allowance but each costs the model's topic check, about Rs 0.4) one signed-in person may send in an IST day. Default 20."""
    return _int("REFUSAL_DAILY_LIMIT", 20, 1, 100000)


def anon_refusal_daily_limit():
    """The same for one free-trial device in an IST day. Default 10."""
    return _int("ANON_REFUSAL_DAILY_LIMIT", 10, 1, 100000)


def client_ip_header():
    """Which header holds the visitor's address: 'x-real-ip', 'xff-first' (the first entry of X-Forwarded-For) or '' (the default: the TRUSTED_PROXY_HOPS rule on X-Forwarded-For). Set it from evidence for the platform in front of the service: on Railway (measured 2026-10-23,
    FOLLOW_UPS 2bz) the edge replaces a caller's own X-Forwarded-For, puts the visitor first and an edge address last, and sets X-Real-IP to the visitor. A value that is not a valid address is ignored (the default rule is used)."""
    v = _env("CLIENT_IP_HEADER").lower()
    return v if v in ("x-real-ip", "xff-first") else ""
