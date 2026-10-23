"""
site_client.py -- the Streamlit page as the FIRST CLIENT of the Recourse API (WEBSITE_DESIGN 1.3, step A5). Standard library plus PyJWT (already pinned). No Streamlit import here, so it is testable on its own.
Switch USE_API (default OFF; on|1|true|yes): off means the page calls the engine directly, exactly as before; that is the way back. On, the page signs the person in (site_account.py, st.login with Google), and every call to the API carries a
short-lived signed token (5 minutes, used once) minted here with STREAMLIT_API_SECRET, the secret shared with the API service. Settings (environment, never in the repository):
  USE_API               on = use the API (and sign-in); anything else = today's behaviour
  SITE_API_URL          the API's public address, e.g. https://staging-api-production-976b.up.railway.app (no trailing slash needed)
  STREAMLIT_API_SECRET  the shared secret (32 characters or more); the same value as on the API service
  SITE_API_TIMEOUT      seconds to wait for an answer (default 150)
A person is a dict {"sub", "email", "email_verified", "name"} taken from the sign-in. Errors reach the page as ApiError with a short code (never the exception text, never the question).
"""
import json
import os
import urllib.error
import urllib.request
import uuid

TOKEN_TTL = 300
_ISS, _AUD = "streamlit", "recourse-api"


def _env(name):
    return (os.environ.get(name) or "").strip().strip("\"'")


def enabled():
    return _env("USE_API").lower() in ("1", "on", "true", "yes")


def api_url():
    return _env("SITE_API_URL").rstrip("/")


def secret():
    v = _env("STREAMLIT_API_SECRET")
    return v if len(v) >= 32 else ""


def timeout_seconds():
    try:
        return max(10, min(600, int(_env("SITE_API_TIMEOUT"))))
    except ValueError:
        return 150


def configured():
    """True when the page can reach the API: switch on, an address, a secret."""
    return enabled() and bool(api_url()) and bool(secret())


class ApiError(Exception):
    """An API reply that is not a success. `status` is the HTTP status (0 = could not reach the service), `code` a short fixed word ('consent_required', 'limit_reached', 'turn_limit', 'unreachable' ...), `payload` the reply's body when it had one."""

    def __init__(self, status, code, payload=None):
        super().__init__(f"{status} {code}")
        self.status, self.code, self.payload = status, code, payload if isinstance(payload, dict) else {}


def mint(person, now=None):
    """The one-use token for this person and this call."""
    import time as _t

    import jwt             # imported here so that merely importing this module (the page always does) needs nothing when USE_API is off
    t = int(now if now is not None else _t.time())
    claims = {"iss": _ISS, "aud": _AUD, "sub": str(person["sub"]), "email": person["email"], "email_verified": bool(person.get("email_verified")), "iat": t, "exp": t + TOKEN_TTL, "jti": uuid.uuid4().hex}
    if person.get("name"):
        claims["name"] = str(person["name"])[:200]
    return jwt.encode(claims, secret(), algorithm="HS256")


def _request(method, path, person=None, body=None, headers=None, stream=False):
    h = {"Content-Type": "application/json", "Accept": "application/json", **(headers or {})}
    if person is not None:
        h["Authorization"] = "Bearer " + mint(person)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(api_url() + path, data=data, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout_seconds())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            payload = {}
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise ApiError(e.code, detail if isinstance(detail, str) and detail else "http_%d" % e.code, payload) from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise ApiError(0, "unreachable") from None
    if stream:
        return resp
    try:
        return json.loads(resp.read().decode("utf-8", "replace"))
    except ValueError:
        raise ApiError(resp.status, "bad_reply") from None


def me(person):
    return _request("GET", "/api/me", person)


def legal(document):
    return _request("GET", f"/api/legal/{document}")


def accept(person, document, version):
    return _request("POST", "/api/me/consent", person, {"document": document, "version": version})


def confirm_age(person):
    return _request("POST", "/api/me/age", person, {"confirmed": True})


def new_chat(person, audience="layman"):
    return _request("POST", "/api/chats", person, {"audience": audience})


def feedback(person, message_id, kind, comment=None):
    return _request("POST", "/api/feedback", person, {"message_id": message_id, "kind": kind, "comment": comment})


def export_my_data(person):
    return _request("POST", "/api/me/export", person)


def delete_account(person):
    return _request("DELETE", "/api/me?confirm=DELETE", person)


def events(resp):
    """(event, data) pairs from a server-sent-events reply as they arrive."""
    name, data = None, []
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith(":"):
            continue
        if line == "":
            if name:
                try:
                    yield name, json.loads("\n".join(data))
                except ValueError:
                    yield name, {}
            name, data = None, []
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())


def ask(person, chat_id, question, on_step=None, key=None):
    """One question in a saved chat. on_step(label) hears each real step as it happens. -> the API's whole reply {'result' (the engine's result, what the page draws), 'text', 'notice', 'usage', 'chat_id', 'message_id', 'saved', ...}.
    Raises ApiError: 403 consent_required, 429 limit_reached / too_many_refusals / busy / rate_limited, 409 turn_limit / in_progress / idempotency_key_reused, 404 not_found (chat gone), 0 unreachable, 500 engine_error, 504 timeout."""
    key = key or uuid.uuid4().hex[:24]
    resp = _request("POST", f"/api/chats/{chat_id}/ask", person, {"question": question}, {"Accept": "text/event-stream", "Idempotency-Key": key}, stream=True)
    final = None
    try:
        for name, d in events(resp):
            if name == "step" and on_step is not None:
                try:
                    on_step(d.get("label") or "")
                except Exception:  # noqa: BLE001 -- a page that cannot draw a step must not lose the answer
                    pass
            elif name == "result":
                final = d
            elif name == "error":
                raise ApiError(500, (d.get("code") if isinstance(d, dict) else None) or "engine_error", d if isinstance(d, dict) else {})
    except (OSError, TimeoutError):
        raise ApiError(0, "unreachable") from None
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    if final is None:
        raise ApiError(0, "unreachable")
    return final
