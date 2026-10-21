"""
api/try_ask.py -- ask the API one question from the command line and watch the real steps arrive. Standard library only (no installs).

    python api/try_ask.py --url https://YOUR-API-DOMAIN [--audience layman|lawyer] "your question"

The key is read from the environment variable API_ACCESS_TOKEN (PowerShell: $env:API_ACCESS_TOKEN = "the key"), so it is never typed into the command or kept in the shell history.
Prints each step as it happens, then the answer, then the cost and time. Exit code 0 = an answer arrived; 1 = anything else. It prints no key and sends nothing but the question.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ask the Recourse API one question and watch the steps.")
    ap.add_argument("question")
    ap.add_argument("--url", required=True, help="the API's address, e.g. https://recourse-api-production.up.railway.app")
    ap.add_argument("--audience", choices=["layman", "lawyer"], default="layman")
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    key = (os.environ.get("API_ACCESS_TOKEN") or "").strip()
    if not key:
        print("Set the environment variable API_ACCESS_TOKEN to the service's key first (PowerShell: $env:API_ACCESS_TOKEN = \"the key\").")
        return 1
    req = urllib.request.Request(a.url.rstrip("/") + "/api/ask", data=json.dumps({"question": a.question, "audience": a.audience}).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Accept": "text/event-stream", "X-API-Key": key}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=a.timeout)
    except urllib.error.HTTPError as e:
        why = {401: "the key was refused (401)", 503: "the ask route is switched off: API_ACCESS_TOKEN is not set on the service (503)", 429: "the service is busy, try again in a few seconds (429)",
               413: "the question is too long (413)", 422: "the question or audience was not accepted (422)"}.get(e.code, f"HTTP {e.code}")
        print("Not answered: " + why)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"Could not reach the service: {type(e).__name__}")
        return 1
    cur, got = None, False
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.startswith("event: "):
                cur = line[7:]
            elif line.startswith("data: ") and cur:
                d = json.loads(line[6:])
                if cur == "step":
                    print(f"  [{d.get('status', '')}] {d.get('label', d.get('id'))}")
                elif cur == "result":
                    got = True
                    print("\n" + (d.get("text") or "(no answer text; state: %s)" % ((d.get("result") or {}).get("state"))))
                    print(f"\nstate: {(d.get('result') or {}).get('state')}   cost: {('Rs %s' % d.get('cost_inr')) if d.get('cost_inr') is not None else 'not recorded'}   time: {d.get('elapsed_ms')} ms   request: {d.get('request_id')}")
                elif cur == "error":
                    print(f"\nError: {d.get('code')}: {d.get('message')}")
                cur = None
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
