"""
api_harness.py -- a real API server for the tests that need real HTTP (test_site_client.py and friends; not a test itself, so the suite does not run it). start() runs `uvicorn` in a child process on a free local port with a stub engine in place of the
answer engine (no model, no cost): the answer is "Stub answer to: <end of the question>", the steps are real progress events, the state is 'single_match' unless the question contains REFUSE (a topic-bar refusal) or BOOM (an engine failure).
The caller supplies DATABASE_URL (pg_harness) and any settings. With HARNESS_FAKE_GOOGLE_DIR set, Google's signing keys are replaced by a key pair whose private half is written to <dir>/private.pem (the front end's browser tests sign ID tokens with it). stop() ends it.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

_SERVER = r'''
import os, sys, time
sys.path.insert(0, %(here)r)
from api import engine_adapter
class E:
    def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None):
        import cost_log, progress
        cost_log.begin(question)
        try:
            progress.emit("scope", category="in_scope"); time.sleep(0.15); progress.emit("write"); time.sleep(0.15)
            if "BOOM" in question:
                raise RuntimeError("secret failure")
            if "REFUSE" in question:
                return {"state": "adjacent_uncovered", "reasoning": "An employment dispute."}
            if "RICH" in question.rsplit("Now the person says:", 1)[-1]:        # an answer with sources and notes, for the front end's screens (a follow-up reaches the engine folded into the earlier questions: only the newest words decide)
                return {"state": "single_match", "audience": audience, "response_text": "**Your situation**\nYou were arrested.\n\n**What the law says**\nUnder **Section 35** of the BNSS arrest is limited. In *Arnesh Kumar v. State of Bihar* (2014) the Supreme Court said arrest is not routine.\n\n**What you can do**\n1. Ask for the grounds of arrest.\n2. Call a lawyer.",
                        "matches": [{"case_name": "Arnesh Kumar v. State of Bihar", "citation": "(2014) 8 SCC 273", "paragraph_number": "7_a", "text": "Arrest is not to be made routinely.", "source": "curated"},
                                    {"section_number": "35", "act": "BNSS", "act_display": "BNSS", "text": "Arrest without warrant, with notice of appearance.", "source": "curated_statute"}],
                        "register_notes": ["Reported as overruled; not yet confirmed by our reviewer."], "grounding_notes": ["One quotation could not be matched to the sources."],
                        "act_notice": {"html": "The <b>Bharatiya Nagarik Suraksha Sanhita</b> is on <a href=\"https://www.indiacode.nic.in/\">India Code</a><script>window.__xss=1</script>."},
                        "unverified_related_judgments": [{"case_name": "Z v. W", "ik_search_url": "https://indiankanoon.org/search/?formInput=z", "paragraph_number": "2"}]}
            return {"state": "single_match", "response_text": "Stub answer to: " + question[-70:], "matches": [], "audience": audience}
        finally:
            cost_log.finish(style="v1", audience=audience or "")
engine_adapter.set_engine(E())
if os.environ.get("HARNESS_FAKE_GOOGLE_DIR"):        # a stand-in for Google's signing keys: the test holds the private key (private.pem) and signs ID tokens with it
    import types
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from api.auth import google as G
    _key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with open(os.path.join(os.environ["HARNESS_FAKE_GOOGLE_DIR"], "private.pem"), "wb") as _f:
        _f.write(_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    class _Jw:
        def get_signing_key_from_jwt(self, t):
            return types.SimpleNamespace(key=_key.public_key())
    G._CLIENT["c"] = _Jw()
import uvicorn
from api.main import app
uvicorn.run(app, host="127.0.0.1", port=int(os.environ["HARNESS_PORT"]), log_level="warning")
'''


class Server:
    def __init__(self, env):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.url = f"http://127.0.0.1:{self.port}"
        e = {**os.environ, **env, "HARNESS_PORT": str(self.port), "API_RUN_MIGRATIONS": "on", "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen([sys.executable, "-X", "utf8", "-c", _SERVER % {"here": HERE}], env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=HERE)

    def wait(self, seconds=60):
        end = time.time() + seconds
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError("the API server stopped: " + (self.proc.stdout.read() or b"").decode("utf-8", "replace")[-500:])
            try:
                urllib.request.urlopen(self.url + "/api/health", timeout=2).read()
                return self
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("the API server did not start")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def start(env):
    return Server(env).wait()
