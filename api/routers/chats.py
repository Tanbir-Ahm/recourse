"""
api/routers/chats.py -- saved conversations (step A3.4; WEBSITE_DESIGN 5.1). Every route needs a signed-in person who has accepted the documents and declared being 18+ (deps.ready_user); a chat belongs to its person and anyone else
gets 404 (never 403: whether a chat exists is not told). Deleting a chat deletes its messages at once (owner's D3: kept until the person deletes them).
POST /api/chats/{id}/ask is the question: header Idempotency-Key (8 to 40 letters, digits, - or _) is required; server-sent events or one JSON reply as for /api/ask; the answer is saved by the server even if the caller goes away.
"""
import asyncio
import datetime
import logging
import threading
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import answer_export
import answer_view
import refusal_text
import web_chat

from .. import ask as ask_mod
from .. import chat_service, config, engine_adapter, quota, ratelimit
from ..db import models as M
from ..deps import Principal, get_db, ready_user

router = APIRouter()
logger = logging.getLogger("api.chats")
MAX_CHATS = 500
_EXPORT_SLOTS = {"n": None, "sem": None}


def _iso(v):
    return v.isoformat() if v is not None else None


def chat_view(c):
    return {"id": str(c.id), "title": c.title, "audience": c.audience, "archived": c.archived, "created_at": _iso(c.created_at), "updated_at": _iso(c.updated_at)}


def message_view(m):
    return {"id": str(m.id), "seq": m.seq, "role": m.role, "content": m.content, "result": m.result, "state": m.state, "created_at": _iso(m.created_at),
            "notice": refusal_text.notice(m.result) if m.role == "assistant" else None,
            "view": answer_view.build(m.result) if m.role == "assistant" else None}


def _own_chat(db, user, chat_id):
    c = db.execute(select(M.Chat).where(M.Chat.id == chat_id, M.Chat.user_id == user.id)).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="not_found")
    return c


class CreateChat(BaseModel):
    audience: Literal["layman", "lawyer"] = "layman"
    title: str = Field(default="", max_length=200)


class PatchChat(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    archived: Optional[bool] = None


class AskChat(BaseModel):
    question: str = Field(min_length=1, description="The person's own words.")


@router.get("/api/chats", summary="My conversations, newest first")
def list_chats(q: str = "", archived: bool = False, limit: int = 50, offset: int = 0, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    stmt = select(M.Chat).where(M.Chat.user_id == principal.user.id, M.Chat.archived.is_(archived))
    q = (q or "").strip()[:100]
    if q:
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(M.Chat.title.ilike(f"%{esc}%", escape="\\"))
    rows = db.execute(stmt.order_by(M.Chat.updated_at.desc(), M.Chat.id).limit(limit).offset(offset)).scalars().all()
    return {"chats": [chat_view(c) for c in rows]}


@router.post("/api/chats", status_code=201, summary="Start a conversation")
def create_chat(body: CreateChat, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    n = db.execute(select(func.count()).select_from(M.Chat).where(M.Chat.user_id == principal.user.id)).scalar()
    if n >= MAX_CHATS:
        raise HTTPException(status_code=409, detail="chat_limit")
    c = M.Chat(user_id=principal.user.id, audience=body.audience, title=" ".join(body.title.split()))
    db.add(c)
    db.commit()
    return chat_view(c)


@router.get("/api/chats/{chat_id}", summary="One conversation with its messages and their results")
def get_chat(chat_id: uuid.UUID, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    c = _own_chat(db, principal.user, chat_id)
    return {**chat_view(c), "messages": [message_view(m) for m in c.messages], "turn_limit": web_chat.MAX_TURNS}


@router.patch("/api/chats/{chat_id}", summary="Rename or archive a conversation")
def patch_chat(chat_id: uuid.UUID, body: PatchChat, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    c = _own_chat(db, principal.user, chat_id)
    if body.title is not None:
        c.title = " ".join(body.title.split())
    if body.archived is not None:
        c.archived = body.archived
    db.commit()
    return chat_view(c)


@router.delete("/api/chats/{chat_id}", summary="Delete a conversation and its messages, now")
def delete_chat(chat_id: uuid.UUID, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    c = _own_chat(db, principal.user, chat_id)
    db.delete(c)
    db.commit()
    return {"deleted": True}


def _prepare(db, principal, chat_id, key, question):
    """Runs in a thread (database work). -> ('replay', out) | ('refused', info) | ('run', Turn); raises HTTPException for the plain refusals."""
    user = principal.user
    chat = _own_chat(db, user, chat_id)
    kind, out = chat_service.stored_reply(db, chat.id, key, question)
    if kind == "reused":
        raise HTTPException(status_code=409, detail="idempotency_key_reused")
    if kind == "same":
        return "replay", out
    if chat_service.user_message_count(db, chat.id) >= web_chat.MAX_TURNS:
        raise HTTPException(status_code=409, detail="turn_limit")
    if not chat_service.claim(chat.id, key):
        raise HTTPException(status_code=409, detail="in_progress")
    try:
        ok, event_id, info = quota.reserve(db, user, quota.FEATURE_FOR_AUDIENCE[chat.audience])
        db.commit()                      # keeps the unit and releases the row lock before the engine runs
        turns = chat_service.turns_of(chat.messages) if ok else []
    except BaseException:
        db.rollback()
        chat_service.unclaim(chat.id, key)
        raise
    if not ok:
        chat_service.unclaim(chat.id, key)
        return "refused", info
    return "run", chat_service.Turn(user_id=user.id, chat_id=chat.id, audience=chat.audience, question=question, request_id=key, event_id=event_id, usage=info, turns=turns)


@router.post("/api/chats/{chat_id}/ask", summary="Ask in a conversation", description="Header Idempotency-Key is required. Send 'Accept: text/event-stream' for the live steps; otherwise one JSON reply. The answer is saved by the server.")
async def ask_in_chat(chat_id: uuid.UUID, body: AskChat, request: Request, idempotency_key: Optional[str] = Header(default=None),
                      principal: Principal = Depends(ready_user), db=Depends(get_db)):
    key = (idempotency_key or "").strip()
    if not chat_service.KEY_RE.match(key):
        raise HTTPException(status_code=400, detail="idempotency_key_required")
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is empty")
    if len(question) > config.max_question_chars():
        raise HTTPException(status_code=413, detail="question is too long")
    kind, payload = await asyncio.to_thread(_prepare, db, principal, chat_id, key, question)
    if kind == "refused":
        return JSONResponse({"detail": payload.get("reason", "limit_reached"), "usage": payload}, status_code=429)
    rid = uuid.uuid4().hex[:16]
    loop = asyncio.get_running_loop()
    q = asyncio.Queue()
    if kind == "replay":
        q.put_nowait(("result", payload))
        return await ask_mod.deliver(request, q, loop, rid)
    turn = payload
    try:
        ask_mod._start_job(lambda on_step: chat_service.run_turn(on_step, turn), loop, q)
    except engine_adapter.EngineBusy:
        await asyncio.to_thread(chat_service._release_only, turn.event_id)
        chat_service.unclaim(turn.chat_id, turn.request_id)
        raise HTTPException(status_code=429, detail="busy, try again shortly", headers={"Retry-After": "5"})
    return await ask_mod.deliver(request, q, loop, rid)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# download: one answer or the whole conversation as a PDF or a Word file (answer_export.py). Built ONLY from the saved messages of the person's own conversation, so a document cannot be forged by editing a request.
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _export_slot():
    n = config.export_parallel()
    if _EXPORT_SLOTS["sem"] is None or _EXPORT_SLOTS["n"] != n:
        _EXPORT_SLOTS["n"], _EXPORT_SLOTS["sem"] = n, threading.BoundedSemaphore(n)
    return _EXPORT_SLOTS["sem"]


def export_entries(chat):
    """[(entry, ids)] one per question, oldest first: the person's own words and the answer that followed (answer_view's data for it). ids = the ids of the messages the entry came from."""
    out, msgs, i = [], list(chat.messages), 0
    while i < len(msgs):
        m = msgs[i]
        if m.role != "user":
            i += 1
            continue
        nxt = msgs[i + 1] if i + 1 < len(msgs) and msgs[i + 1].role == "assistant" else None
        src = nxt or m
        out.append(({"question": m.content, "view": answer_view.build(nxt.result) if nxt is not None else None, "plain": (nxt.content if nxt is not None else None) or None,
                     "answer_id": "RA-" + src.id.hex[:6].upper(), "created_at": src.created_at, "audience": chat.audience},
                    {str(m.id)} | ({str(nxt.id)} if nxt is not None else set())))
        i += 2 if nxt is not None else 1
    return out


@router.get("/api/chats/{chat_id}/export", summary="Download a conversation, or one answer, as a PDF or Word file",
            description="format=pdf|docx. With message=<id of a question or its answer> only that question and answer; without it the whole conversation (newest 12 questions). The file carries every box and warning the page shows. "
                        "No model is called. 422 pdf_script_unsupported: the text has letters the PDF font cannot draw (ask for docx).",
            response_class=Response, responses={200: {"content": {"application/pdf": {}, "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}}}})
def export_chat(chat_id: uuid.UUID, fmt: Literal["pdf", "docx"] = Query("pdf", alias="format"), message: Optional[uuid.UUID] = None,
                principal: Principal = Depends(ready_user), db=Depends(get_db)):
    chat = _own_chat(db, principal.user, chat_id)
    entries = export_entries(chat)
    if message is not None:
        entries = [e for e in entries if str(message) in e[1]]
        if not entries:
            raise HTTPException(status_code=404, detail="not_found")
    if not entries:
        raise HTTPException(status_code=409, detail="nothing_to_export")
    limit = config.export_rate_per_minute()
    if limit and not ratelimit.hit("export:" + str(principal.user.id), limit):
        raise HTTPException(status_code=429, detail="rate_limited", headers={"Retry-After": "30"})
    slot = _export_slot()
    if not slot.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="busy", headers={"Retry-After": "5"})
    try:
        doc = answer_export.build_document([e[0] for e in entries], kind="answer" if message is not None else "conversation", title_chat=chat.title or None)
        try:
            data, _info = answer_export.export(doc, fmt)
        except answer_export.ScriptNotSupported:
            raise HTTPException(status_code=422, detail="pdf_script_unsupported") from None
        except answer_export.ExportError as exc:
            logger.error("export failed: %s", exc)
            raise HTTPException(status_code=500, detail="export_failed") from None
    finally:
        slot.release()
    today = datetime.datetime.now(answer_export.IST).strftime("%Y-%m-%d")
    name = f"recourse-{'answer' if message is not None else 'conversation'}-{today}.{fmt}"
    return Response(content=data, media_type=answer_export.MIME[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
