"""
api/routers/anon.py -- the free trial without signing in (step A3.4; owner's decision D4: three layman questions a day, stored for 90 days under a random device id with NO address, readable only by the owner and the reviewer).
POST /api/anon/ask is closed (503) unless ANON_TRIAL=on, IP_HASH_SECRET is set, a trial budget (ANON_DAILY_BUDGET_INR) is set and the database is configured. It is for the browser front end only: the device id lives in an HttpOnly cookie (rc_device),
so clearing cookies gives a new device, which is why a separate per-address flood guard and the trial's own daily budget stand behind the per-device cap. Layman answers only. A refusal or a failure costs the person nothing.
"""
import asyncio
import re
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import ask as ask_mod
from .. import chat_service, config, engine_adapter, netutil, quota
from ..db import session as dbs

router = APIRouter()
DEVICE_COOKIE = "rc_device"
DEVICE_RE = re.compile(r"^[0-9a-f]{32}$")
DEVICE_COOKIE_SECONDS = 90 * 86400
_STATUS = {"trial_closed": 503, "trial_budget_spent": 429, "device_limit": 429, "ip_limit": 429, "refusal_limit": 429}


class AnonAsk(BaseModel):
    question: str = Field(min_length=1, description="The person's own words.")


def _cookie(resp, device_id):
    resp.set_cookie(DEVICE_COOKIE, device_id, max_age=DEVICE_COOKIE_SECONDS, httponly=True, secure=config.cookie_secure(), samesite="lax", path="/")


def _start(device_id, iph, question):
    with dbs.session() as db:
        ok, info = quota.anon_start(db, device_id, iph, question)
        if ok:
            db.commit()
        else:
            db.rollback()
        return ok, info


def _finish(question_id, device_id, iph, cost, state, counted):
    try:
        with dbs.session() as db:
            quota.anon_finish(db, question_id, device_id, iph, cost, state, counted)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        chat_service.logger.warning("could not finish a trial question: %s", type(exc).__name__)


def _job(question, question_id, device_id, iph, info):
    def run(on_step):
        try:
            out = engine_adapter.work(question, "layman", on_step)
        except BaseException:
            _finish(question_id, device_id, iph, 0, "failed", False)
            raise
        res = out.get("result") if isinstance(out.get("result"), dict) else {}
        state = res.get("state")
        counted = state in chat_service.ANSWER_STATES
        _finish(question_id, device_id, iph, out.get("cost_inr") or 0, state, counted)
        used = info["used"] if counted else max(0, info["used"] - 1)
        return {**out, "trial": {"used": used, "limit": info["limit"]}}
    return run


@router.post("/api/anon/ask", summary="Ask without signing in (free trial)", description="Layman answers only; three a day per device. Send 'Accept: text/event-stream' for the live steps; otherwise one JSON reply.")
async def anon_ask(body: AnonAsk, request: Request):
    if not config.anon_trial_on() or not config.ip_hash_secret() or config.anon_budget_inr() <= 0 or not dbs.configured():
        raise HTTPException(status_code=503, detail="trial_closed")
    origin = (request.headers.get("origin") or "").rstrip("/")
    allowed = config.cors_origins()
    if origin and allowed and origin not in allowed:
        raise HTTPException(status_code=403, detail="origin")
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is empty")
    if len(question) > config.max_question_chars():
        raise HTTPException(status_code=413, detail="question is too long")
    iph = netutil.ip_hash(netutil.client_ip(request))
    if iph is None:
        raise HTTPException(status_code=503, detail="trial_closed")
    device = request.cookies.get(DEVICE_COOKIE) or ""
    fresh = not DEVICE_RE.match(device)
    if fresh:
        device = secrets.token_hex(16)
    ok, info = await asyncio.to_thread(_start, device, iph, question)
    if not ok:
        resp = JSONResponse({"detail": info.get("reason", "trial_closed"), "limit": info.get("limit")}, status_code=_STATUS.get(info.get("reason"), 429))
        return resp
    rid = uuid.uuid4().hex[:16]
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()
    try:
        ask_mod._start_job(_job(question, info["id"], device, iph, info), loop, q)
    except engine_adapter.EngineBusy:
        await asyncio.to_thread(_finish, info["id"], device, iph, 0, "busy", False)
        raise HTTPException(status_code=429, detail="busy, try again shortly", headers={"Retry-After": "5"})
    resp = await ask_mod.deliver(request, q, loop, rid)
    if fresh:
        _cookie(resp, device)
    return resp
