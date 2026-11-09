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

import carry_forward
import case_file as CF
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


def matter_notes(db, chat):
    """The notes of the matter a chat is filed under, as the dict web_chat.matter_lines reads; None when it is not filed under one (or the matter is gone)."""
    if chat.matter_id is None:
        return None
    m = db.execute(select(M.Matter).where(M.Matter.id == chat.matter_id, M.Matter.user_id == chat.user_id)).scalar_one_or_none()
    if m is None:
        return None
    return {"title": m.title, "court": m.court, "case_number": m.case_number, "sections": m.sections, "stage": m.stage, "next_date": m.next_date.isoformat() if m.next_date else None, "facts": m.facts}


FACT_LABELS = {"typed": "From your message", "edited": "You edited this", "added": "You added this", "button": "You tapped this"}


def case_file_view(cf, turns, audience=None):
    """What the page draws as the conversation's case file (case_file.py): the facts (id, text, kind, label, whether the text can be changed), what the earlier answers relied on (display only), and the age card when it is due. None when
    CASE_FILE is off. `turns`: [{'q', 'answer'}] of the saved conversation."""
    if not CF.enabled():
        return None
    cf = cf if isinstance(cf, dict) else CF.new_file()
    facts = [{"id": f["id"], "text": f["text"], "kind": f.get("kind", "typed"), "label": FACT_LABELS.get(f.get("kind", "typed"), ""), "editable": f.get("kind") != "button"} for f in cf.get("facts") or [] if isinstance(f, dict) and f.get("text")]
    try:
        relied = carry_forward.relied_on(turns)
    except Exception:  # noqa: BLE001
        relied = {"sections": [], "cases": []}
    person_text = " ".join(t.get("q") or "" for t in turns or [])
    import charge_map
    asked = any((t.get("q") or "").strip() == charge_map.CHARGES_QUESTION for t in turns or [])
    last = (turns or [])[-1] if turns else None
    shown = any((t.get("answer") or {}).get("charge_candidates") for t in turns or [])                 # the table already came with an answer (the person asked which offences apply): the button would give the same sections again
    offer = bool(charge_map.enabled() and audience == "lawyer" and facts and not asked and not shown and last and (last.get("answer") or {}).get("state") in ANSWER_STATES)
    return {"enabled": True, "facts": facts, "limit": CF.MAX_FACTS, "max_chars": CF.MAX_FACT_CHARS, "relied_on": relied, "card": CF.card_for(cf, person_text),
            "charges": {"offer": True, "text": "What else could he be charged with?", "note": "Sections the facts may bring in, chosen by a program from your case file; not complete and not read by a lawyer."} if offer else None}


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
    matter: dict | None = None                  # the notes of the matter the chat is filed under (title, court, case_number, sections, stage, next_date, facts), read once when the question was accepted
    case_file: dict | None = None               # the chat's case file (case_file.py) as it was when the question was accepted; None when CASE_FILE is off
    intent: str | None = None                   # 'age_minor': the question is the person's tap on 'under 18' (the server wrote its words)


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
        engine_q, info = web_chat.question_for_engine(c.turns, c.question, matter=c.matter, case_file=c.case_file)
        web_chat.log_turn(engine_q, info)
        ecf = web_chat.engine_case_file(c.case_file, info, c.turns, c.question, intent=c.intent, audience=c.audience) if c.case_file is not None or CF.enabled() else None
        out = engine_adapter.work(engine_q, c.audience, on_step, carried=info.get("carry") or None, case_file=ecf)
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
                    if CF.enabled() and c.intent is None and state != "unrelated":          # the sentences the person typed join the case file (a tap's own words are not facts; small talk is not part of the matter)
                        chat.case_file = CF.add_from_message(chat.case_file, c.question)
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
    reply = {**out, "chat_id": str(c.chat_id), "message_id": str(message_id) if message_id else None, "saved": saved, "usage": usage, "turn": info.get("turn")}
    try:
        if CF.enabled() and saved:
            with dbs.session() as db:
                chat = db.execute(select(M.Chat).where(M.Chat.id == c.chat_id, M.Chat.user_id == c.user_id)).scalar_one_or_none()
                if chat is not None:
                    reply["case_file"] = case_file_view(chat.case_file, turns_of(chat.messages), chat.audience)
    except Exception as exc:  # noqa: BLE001 -- the answer is returned without the panel's data
        logger.warning("could not read the case file back: %s", type(exc).__name__)
    return reply
