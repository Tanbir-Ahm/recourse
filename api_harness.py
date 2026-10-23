"""
api_harness.py -- a real API server for the tests that need real HTTP (test_site_client.py and friends; not a test itself, so the suite does not run it). start() runs `uvicorn` in a child process on a free local port with a stub engine in place of the
answer engine (no model, no cost): the answer is "Stub answer to: <end of the question>", the steps are real progress events, the state is 'single_match' unless the question contains REFUSE (a topic-bar refusal) or BOOM (an engine failure).
The caller supplies DATABASE_URL (pg_harness) and any settings. stop() ends it.
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
            return {"state": "single_match", "response_text": "Stub answer to: " + question[-70:], "matches": [], "audience": audience}
        finally:
            cost_log.finish(style="v1", audience=audience or "")
engine_adapter.set_engine(E())
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
