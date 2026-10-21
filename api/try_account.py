"""
api/try_account.py -- use the API's accounts, saved chats and free trial from the command line, the way the Streamlit service and the new front end will. Standard library only (no installs).

    python api/try_account.py --url https://YOUR-API-DOMAIN me
    python api/try_account.py --url ... accept                       (accept the documents and say you are 18 or older)
    python api/try_account.py --url ... ask "your question"          (starts a chat, prints the steps and the answer, then the chat id)
    python api/try_account.py --url ... ask --chat CHAT_ID "a follow-up question"
    python api/try_account.py --url ... chats | show CHAT_ID | delete-chat CHAT_ID | export | delete-me
    python api/try_account.py --url ... anon "your question" [--times 4]    (the free trial without signing in; one cookie jar, so it is one device)

The signed-in commands act as the person --email (default tester@example.com) by signing a short-lived token with the secret in the environment variable STREAMLIT_API_SECRET (PowerShell: $env:STREAMLIT_API_SECRET = "the secret"),
exactly as the Streamlit service will; the secret is never printed or typed into the command. Each call gets its own one-use token. Exit code 0 = the call worked; 1 = anything else.
"""
import argparse
import base64
import hashlib
import hmac
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def mint(secret, sub, email, ttl=300):
    now = int(time.time())
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps({"iss": "streamlit", "aud": "recourse-api", "sub": sub, "email": email, "email_verified": True, "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


class Api:
    def __init__(self, url, secret, email, opener=None):
        self.url, self.secret, self.email = url.rstrip("/"), secret, email
        self.opener = opener or urllib.request.build_opener()

    def call(self, method, path, body=None, headers=None, signed=True, stream=False, timeout=240):
        h = {"Content-Type": "application/json", **(headers or {})}
        if signed:
            h["Authorization"] = "Bearer " + mint(self.secret, "try-" + hashlib.sha256(self.email.encode()).hexdigest()[:16], self.email)
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
        try:
            resp = self.opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            return e.code, _json(e.read())
        if stream:
            return resp.status, resp
        return resp.status, _json(resp.read())


def _json(raw):
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return {"raw": raw.decode("utf-8", "replace")[:300]}


def events(resp):
    """Yields (event, data) from a server-sent-events response as it arrives."""
    name, data = None, []
    for line in resp:
        line = line.decode("utf-8", "replace").rstrip("\r\n")
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


def show_stream(resp):
    ok = False
    for name, d in events(resp):
        if name == "step":
            print(f"  - {d.get('label')}")
        elif name == "result":
            ok = True
            print("\n" + (d.get("text") or "(no text)") + "\n")
            print(f"cost Rs {d.get('cost_inr')}, {d.get('elapsed_ms')} ms")
            for k in ("usage", "trial", "saved", "chat_id", "message_id", "replayed"):
                if k in d:
                    print(f"{k}: {d[k]}")
        elif name == "error":
            print(f"ERROR: {d}")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="Use the Recourse API's accounts, chats and free trial.")
    ap.add_argument("--url", required=True)
    ap.add_argument("--email", default="tester@example.com")
    ap.add_argument("--chat")
    ap.add_argument("--audience", choices=["layman", "lawyer"], default="layman")
    ap.add_argument("--times", type=int, default=1)
    ap.add_argument("command", choices=["me", "accept", "ask", "chats", "show", "delete-chat", "export", "delete-me", "anon"])
    ap.add_argument("arg", nargs="?")
    a = ap.parse_intermixed_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    secret = (os.environ.get("STREAMLIT_API_SECRET") or "").strip()
    if a.command != "anon" and len(secret) < 32:
        print("Set the environment variable STREAMLIT_API_SECRET to the service's secret first (at least 32 characters).")
        return 1
    jar = http.cookiejar.CookieJar()
    api = Api(a.url, secret, a.email, urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)))
    try:
        if a.command == "me":
            s, j = api.call("GET", "/api/me")
        elif a.command == "accept":
            for doc in ("privacy", "terms"):
                s, t = api.call("GET", f"/api/legal/{doc}", signed=False)
                s, j = api.call("POST", "/api/me/consent", {"document": doc, "version": t["version"]})
                print(doc, s, j)
            s, j = api.call("POST", "/api/me/age", {"confirmed": True})
        elif a.command in ("ask", "anon"):
            if not a.arg:
                print("Give the question after the command.")
                return 1
            worst = True
            for i in range(max(1, a.times)):
                print(f"--- question {i + 1}")
                if a.command == "anon":
                    s, r = api.call("POST", "/api/anon/ask", {"question": a.arg}, {"Accept": "text/event-stream"}, signed=False, stream=True)
                else:
                    chat = a.chat
                    if not chat:
                        s0, c = api.call("POST", "/api/chats", {"audience": a.audience})
                        if s0 != 201:
                            print(s0, c)
                            return 1
                        chat = a.chat = c["id"]
                    s, r = api.call("POST", f"/api/chats/{chat}/ask", {"question": a.arg}, {"Accept": "text/event-stream", "Idempotency-Key": uuid.uuid4().hex[:24]}, stream=True)
                if s != 200:
                    print(s, r)
                    worst = False
                    continue
                worst = show_stream(r) and worst
            if a.command == "ask":
                print(f"chat id: {a.chat}   (use --chat {a.chat} for a follow-up)")
            return 0 if worst else 1
        elif a.command == "chats":
            s, j = api.call("GET", "/api/chats")
        elif a.command == "show":
            s, j = api.call("GET", f"/api/chats/{a.arg}")
        elif a.command == "delete-chat":
            s, j = api.call("DELETE", f"/api/chats/{a.arg}")
        elif a.command == "export":
            s, j = api.call("POST", "/api/me/export")
        else:
            s, j = api.call("DELETE", "/api/me?confirm=DELETE")
    except (urllib.error.URLError, OSError) as e:
        print(f"Could not reach the service: {type(e).__name__}")
        return 1
    print(s, json.dumps(j, indent=2, ensure_ascii=False)[:6000])
    return 0 if 200 <= s < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
