"""
api/chat_service.py -- one saved chat turn, start to finish (step A3.4; WEBSITE_DESIGN 5.1).
run_turn() is the job a signed-in question runs in an engine worker thread: it folds the person's EARLIER questions into the engine's input (web_chat.question_for_engine: only the person's own words, never our earlier answers), runs the
engine, then saves the question and the answer and settles the quota IN THE SAME THREAD, so a caller who disconnects half-way still gets their answer saved and their allowance counted exactly once.
A question the site answered counts as one use; a refusal (the topic bar, "not enough to go on", an unavailable model, a spending pause) is saved but costs nothing. A failure releases the unit and saves nothing.
A repeated Idempotency-Key returns the stored answer instead of asking again; the same key arriving while the first is still running is refused (409), so a retry never spends twice.
"""
import datetime
import logging
import re
import threading
from dataclasses import dataclass, field

from sqlalchemy import func, select

import web_chat

from . import engine_adapter, quota
from .db import models as M
from .db import session as dbs

logger = logging.getLogger("recourse.api")
ANSWER_STATES = ("single_match", "conflicting_matches")
TITLE_CHARS = 60
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")

_INFLIGHT = set()
_INFLIGHT_LOCK = threading.Lock()


def claim(chat_id, key):
    """True if this (chat, key) is not already running; the caller must unclaim() when it ends. In-process: the service runs as ONE replica (WEBSITE_DESIGN 9)."""
    with _INFLIGHT_LOCK:
        if (chat_id, key) in _INFLIGHT:
            return False
        _INFLIGHT.add((chat_id, key))
        return True


def unclaim(chat_id, key):
    with _INFLIGHT_LOCK:
        _INFLIGHT.discard((chat_id, key))


def title_from(question):
    t = re.sub(r"\s+", " ", question or "").strip()
    if len(t) <= TITLE_CHARS:
        return t
    head = t[:TITLE_CHARS]
    return (head.rsplit(" ", 1)[0] if " " in head else head).rstrip(" ,;:") + " ..."


def turns_of(messages):
    """[{'q': the person's words, 'answer': the engine's stored result}] from a chat's messages in order. A question with no stored answer is left out."""
    turns, pending = [], None
    for m in messages:
        if m.role == "user":
            pending = m.content
        elif m.role == "assistant" and pending is not None:
            turns.append({"q": pending, "answer": m.result if isinstance(m.result, dict) else {}})
            pending = None
    return turns


def user_message_count(db, chat_id):
    return db.execute(select(func.count()).select_from(M.Message).where(M.Message.chat_id == chat_id, M.Message.role == "user")).scalar()


def stored_reply(db, chat_id, key, question):
    """-> ('none', None) | ('same', out) | ('reused', None) for an Idempotency-Key already used in this chat."""
    um = db.execute(select(M.Message).where(M.Message.chat_id == chat_id, M.Message.request_id == key, M.Message.role == "user")).scalars().first()
    if um is None:
        return "none", None
    if um.content != question:
        return "reused", None
    am = db.execute(select(M.Message).where(M.Message.chat_id == chat_id, M.Message.request_id == key, M.Message.role == "assistant")).scalars().first()
    if am is None:
        return "none", None
    return "same", {"result": am.result, "cost_inr": float(am.cost_inr) if am.cost_inr is not None else None, "elapsed_ms": None, "chat_id": str(chat_id), "message_id": str(am.id), "saved": True, "replayed": True}


@dataclass
class Turn:
    user_id: object
    chat_id: object
    audience: str
    question: str
    request_id: str
    event_id: object
    usage: dict
    turns: list = field(default_factory=list)


def _style():
    try:
        import answer_style
        return answer_style.style()
    except Exception:  # noqa: BLE001
        return None


def _commit():
    import os
    return (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:12] or None


def _release_only(event_id):
    try:
        with dbs.session() as db:
            quota.release(db, event_id)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not release a use: %s", type(exc).__name__)


def run_turn(on_step, c):
    """The worker-thread job. Returns the engine's reply plus chat_id, message_id, saved, usage."""
    try:
        engine_q, info = web_chat.question_for_engine(c.turns, c.question)
        web_chat.log_turn(engine_q, info)
        out = engine_adapter.work(engine_q, c.audience, on_step)
    except BaseException:
        _release_only(c.event_id)
        unclaim(c.chat_id, c.request_id)
        raise
    try:
        return _save(c, out, info)
    finally:
        unclaim(c.chat_id, c.request_id)


def _save(c, out, info):
    result = out.get("result") if isinstance(out.get("result"), dict) else {}
    state = result.get("state")
    counted = state in ANSWER_STATES
    cost = out.get("cost_inr")
    message_id, saved, usage = None, False, dict(c.usage)
    try:
        with dbs.session() as db:
            chat = db.execute(select(M.Chat).where(M.Chat.id == c.chat_id, M.Chat.user_id == c.user_id).with_for_update()).scalar_one_or_none()
            if chat is not None:
                dup = db.execute(select(M.Message.id).where(M.Message.chat_id == c.chat_id, M.Message.request_id == c.request_id)).first()
                if dup is None:
                    last = db.execute(select(func.coalesce(func.max(M.Message.seq), 0)).where(M.Message.chat_id == c.chat_id)).scalar()
                    now = datetime.datetime.now(datetime.timezone.utc)
                    db.add(M.Message(chat_id=c.chat_id, role="user", seq=last + 1, content=c.question, request_id=c.request_id))
                    am = M.Message(chat_id=c.chat_id, role="assistant", seq=last + 2, content=result.get("response_text") or "", result=out.get("result"), state=state,
                                   request_id=c.request_id, cost_inr=cost, style=_style(), engine_commit=_commit())
                    db.add(am)
                    chat.updated_at = now
                    if not chat.title:
                        chat.title = title_from(c.question)
                    db.flush()
                    message_id, saved = am.id, True
            quota.settle(db, c.event_id, cost, message_id)
            if not counted or not saved:
                quota.release(db, c.event_id)
                usage["used"] = max(0, usage.get("used", 1) - 1)
            db.commit()
    except Exception as exc:  # noqa: BLE001 -- the answer was made and paid for: it is still returned, flagged as not saved
        logger.warning("could not save a chat turn: %s", type(exc).__name__)
        saved, message_id = False, None
        try:
            with dbs.session() as db:
                quota.settle(db, c.event_id, cost, None)
                if not counted:
                    quota.release(db, c.event_id)
                    usage["used"] = max(0, usage.get("used", 1) - 1)
                db.commit()
        except Exception as exc2:  # noqa: BLE001
            logger.warning("could not settle a use: %s", type(exc2).__name__)
    return {**out, "chat_id": str(c.chat_id), "message_id": str(message_id) if message_id else None, "saved": saved, "usage": usage, "turn": info.get("turn")}
