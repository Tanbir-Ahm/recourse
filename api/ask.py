"""
api/ask.py -- POST /api/ask (WEBSITE_DESIGN.md section 5.1): one question in, the real steps and the answer out.
Server-sent events when the caller sends "Accept: text/event-stream" (events: start, step, result, error, done; a comment line every 15 s keeps proxies from closing the stream); otherwise one JSON reply.
Fails closed: without API_ACCESS_TOKEN the route answers 503, with a wrong X-API-Key 401. Sign-in and per-person quotas arrive with steps A2 and A3; until then this key is the only gate and the route must be
reached only by the owner's own staging tests. The question is never logged and never put in an error. An engine failure reaches the caller as a fixed sentence, never the exception text.
"""
import asyncio
import hmac
import json
import logging
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import config, engine_adapter, steps

logger = logging.getLogger("recourse.api")
router = APIRouter()
HEARTBEAT_SECONDS = 15
ERROR_TEXT = "The answer could not be produced. Please try again."


class AskBody(BaseModel):
    question: str = Field(min_length=1, description="The person's own words.")
    audience: Literal["layman", "lawyer"] = "layman"


def require_key(x_api_key: Optional[str] = Header(default=None)):
    token = config.access_token()
    if not token:
        raise HTTPException(status_code=503, detail="ask is not enabled")
    if not x_api_key or not hmac.compare_digest(x_api_key.encode("utf-8"), token.encode("utf-8")):
        raise HTTPException(status_code=401, detail="invalid key")


def _ev(name, data):
    body = json.dumps(data, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return f"event: {name}\ndata: {body}\n\n"


def _start(question, audience, loop, q):
    """Submit the question to a worker; its live steps and its end are put on q (thread-safe)."""
    _start_job(lambda on_step: engine_adapter.work(question, audience, on_step), loop, q)


def _start_job(job, loop, q):
    """Run job(on_step) in an engine worker thread (it may save things to the database before it returns); its live steps and its end are put on q (thread-safe). Raises engine_adapter.EngineBusy when the service is full."""
    def put(item):
        try:
            loop.call_soon_threadsafe(q.put_nowait, item)
        except RuntimeError:         # the loop is gone (the caller left or the service is stopping)
            pass

    def on_step(step, detail):
        d = steps.describe(step, detail)
        if d is not None:
            put(("step", {"id": step, **d}))

    fut = engine_adapter.get_runner().submit(job, on_step)

    def done(f):
        try:
            put(("result", f.result()))
        except BaseException as exc:  # noqa: BLE001 -- the caller gets a fixed sentence; the type goes to the log, never the text
            logger.warning("engine failed: %s", type(exc).__name__)
            put(("error", {"code": "engine_error", "message": ERROR_TEXT}))
    fut.add_done_callback(done)


async def _sse(q, rid, loop, timeout):
    yield _ev("start", {"request_id": rid})
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            yield _ev("error", {"code": "timeout", "message": "The answer is taking too long. Please try again."})
            yield _ev("done", {})
            return
        try:
            kind, data = await asyncio.wait_for(q.get(), min(HEARTBEAT_SECONDS, remaining))
        except asyncio.TimeoutError:
            yield ": keep-alive\n\n"
            continue
        if kind == "step":
            yield _ev("step", data)
        elif kind == "result":
            yield _ev("result", {**_payload(data), "request_id": rid})
            yield _ev("done", {})
            return
        else:
            yield _ev("error", data)
            yield _ev("done", {})
            return


EXTRA_KEYS = ("chat_id", "message_id", "saved", "usage", "trial", "turn", "replayed")      # what a saving route adds to the engine's reply


def _payload(out):
    res = out.get("result") if isinstance(out, dict) else None
    body = {"result": res, "text": (res or {}).get("response_text") if isinstance(res, dict) else None, "cost_inr": out.get("cost_inr"), "elapsed_ms": out.get("elapsed_ms")}
    body.update({k: out[k] for k in EXTRA_KEYS if k in out})
    return body


@router.post("/api/ask", summary="Ask one question", description="Send 'Accept: text/event-stream' for the live steps (events start, step, result, error, done); otherwise one JSON reply with the same result. Header X-API-Key is required.")
async def ask(body: AskBody, request: Request, _=Depends(require_key)):
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is empty")
    if len(question) > config.max_question_chars():
        raise HTTPException(status_code=413, detail="question is too long")
    rid = uuid.uuid4().hex[:16]
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()
    try:
        _start(question, body.audience, loop, q)
    except engine_adapter.EngineBusy:
        raise HTTPException(status_code=429, detail="busy, try again shortly", headers={"Retry-After": "5"})
    return await deliver(request, q, loop, rid)


async def deliver(request, q, loop, rid):
    """The reply for a question already started: server-sent events when the caller asked for them, else one JSON reply (shared by every route that asks)."""
    timeout = config.ask_timeout_seconds()
    if "text/event-stream" in (request.headers.get("accept") or ""):
        return StreamingResponse(_sse(q, rid, loop, timeout), media_type="text/event-stream",
                                 headers={"X-Request-Id": rid, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    end = loop.time() + timeout
    while True:
        remaining = end - loop.time()
        if remaining <= 0:
            raise HTTPException(status_code=504, detail="timeout", headers={"X-Request-Id": rid})
        try:
            kind, data = await asyncio.wait_for(q.get(), remaining)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="timeout", headers={"X-Request-Id": rid})
        if kind == "step":
            continue
        if kind == "result":
            return JSONResponse({**_payload(data), "request_id": rid}, headers={"X-Request-Id": rid})
        return JSONResponse({"request_id": rid, "error": data}, status_code=500, headers={"X-Request-Id": rid})
