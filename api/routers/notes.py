"""
api/routers/notes.py -- a person's notes and "report an error" feedback (step A3.4). Notes are the person's own, limited by their plan (notes_max; a plan that lists none has none), and deleted with the account.
Feedback names one of OUR answers (an assistant message in the person's own chat) and feeds the weekly review; the comment is the person's words and stays private to the owner and the reviewer. Both need a person who accepted the documents.
"""
import datetime
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import quota
from ..db import models as M
from ..deps import Principal, get_db, ready_user

router = APIRouter()
NOTE_CHARS = 10000
FEEDBACK_PER_DAY = 50


def _iso(v):
    return v.isoformat() if v is not None else None


def note_view(n):
    return {"id": str(n.id), "body": n.body, "message_id": str(n.message_id) if n.message_id else None, "created_at": _iso(n.created_at), "updated_at": _iso(n.updated_at)}


def _own_message(db, user, message_id):
    """The message, only if it sits in one of THIS person's chats."""
    m = db.execute(select(M.Message).join(M.Chat, M.Chat.id == M.Message.chat_id).where(M.Message.id == message_id, M.Chat.user_id == user.id)).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="message_not_found")
    return m


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=NOTE_CHARS)
    message_id: Optional[uuid.UUID] = None


class NotePatch(BaseModel):
    body: str = Field(min_length=1, max_length=NOTE_CHARS)


@router.get("/api/notes", summary="My notes")
def list_notes(principal: Principal = Depends(ready_user), db=Depends(get_db)):
    rows = db.execute(select(M.Note).where(M.Note.user_id == principal.user.id).order_by(M.Note.updated_at.desc(), M.Note.id)).scalars().all()
    ent = quota.entitlement(db, principal.user.plan_id, "notes_max")
    return {"notes": [note_view(n) for n in rows], "limit": ent[1] if ent else 0}


@router.post("/api/notes", status_code=201, summary="Add a note")
def add_note(body: NoteIn, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    user = principal.user
    db.execute(select(M.User.id).where(M.User.id == user.id).with_for_update()).scalar_one()      # two adds at once cannot both take the last place
    ent = quota.entitlement(db, user.plan_id, "notes_max")
    limit = ent[1] if ent else 0
    n = db.execute(select(func.count()).select_from(M.Note).where(M.Note.user_id == user.id)).scalar()
    if limit is not None and n >= limit:
        db.rollback()
        raise HTTPException(status_code=403, detail="notes_limit")
    if body.message_id is not None:
        _own_message(db, user, body.message_id)
    note = M.Note(user_id=user.id, message_id=body.message_id, body=body.body)
    db.add(note)
    db.commit()
    return note_view(note)


def _own_note(db, user, note_id):
    n = db.execute(select(M.Note).where(M.Note.id == note_id, M.Note.user_id == user.id)).scalar_one_or_none()
    if n is None:
        raise HTTPException(status_code=404, detail="not_found")
    return n


@router.patch("/api/notes/{note_id}", summary="Change a note")
def patch_note(note_id: uuid.UUID, body: NotePatch, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    n = _own_note(db, principal.user, note_id)
    n.body = body.body
    n.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return note_view(n)


@router.delete("/api/notes/{note_id}", summary="Delete a note")
def delete_note(note_id: uuid.UUID, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    db.delete(_own_note(db, principal.user, note_id))
    db.commit()
    return {"deleted": True}


class FeedbackIn(BaseModel):
    message_id: uuid.UUID
    kind: str = Field(min_length=1, max_length=20)
    comment: Optional[str] = Field(default=None, max_length=4000)


@router.post("/api/feedback", status_code=201, summary="Report a problem with an answer, or say it helped")
def send_feedback(body: FeedbackIn, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    if body.kind not in M.FEEDBACK_KINDS:
        raise HTTPException(status_code=422, detail="unknown kind")
    user = principal.user
    msg = _own_message(db, user, body.message_id)
    if msg.role != "assistant":
        raise HTTPException(status_code=422, detail="feedback is about an answer")
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    if db.execute(select(func.count()).select_from(M.Feedback).where(M.Feedback.user_id == user.id, M.Feedback.created_at >= since)).scalar() >= FEEDBACK_PER_DAY:
        raise HTTPException(status_code=429, detail="too_many_reports")
    row = M.Feedback(user_id=user.id, message_id=msg.id, kind=body.kind, comment=(body.comment or "").strip() or None)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}
