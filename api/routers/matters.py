"""
api/routers/matters.py -- a lawyer's matters (LAWYER_RETENTION_PLAN.md, "from a question to a matter"; built 2026-11-06 on the owner's go). A matter is a case file the lawyer writes once: a label, the court, the case number, the sections charged, the stage,
the next hearing date and the facts. Conversations are filed under it (POST /api/chats with matter_id, PATCH /api/chats/{id}) and every question asked inside one is read together with these notes (chat_service.py + web_chat.matter_block).
Everything here is the lawyer's own free text: nothing is checked against a court record, no date is computed from it, and nothing is sent to a court. No clocks, reminders or drafting (not approved).
The label should not be a client's name: the page says so, because the notes go to the model provider with each question exactly as a question does.
Every route needs a signed-in person who has accepted the documents and declared being 18+ (deps.ready_user); a matter belongs to its person and anyone else gets 404. Open matters are limited by the plan (matters_active; a plan that lists none has none);
archived matters do not count. Deleting a matter keeps its conversations (unfiled) unless with_chats=true, which deletes them with it.
"""
import datetime
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import quota
from ..db import models as M
from ..deps import Principal, get_db, ready_user

router = APIRouter()
MAX_FACTS = 4000
Stage = Literal["fir", "arrest", "remand", "bail", "chargesheet", "trial", "appeal", "other"]


def _iso(v):
    return v.isoformat() if v is not None else None


def _line(v, n):
    t = " ".join((v or "").split())
    return t[:n] or None


def matter_view(m, chats=None):
    return {"id": str(m.id), "title": m.title, "court": m.court, "case_number": m.case_number, "sections": m.sections, "stage": m.stage, "next_date": _iso(m.next_date),
            "facts": m.facts, "archived": m.archived, "created_at": _iso(m.created_at), "updated_at": _iso(m.updated_at), "chat_count": chats}


def _own_matter(db, user, matter_id):
    m = db.execute(select(M.Matter).where(M.Matter.id == matter_id, M.Matter.user_id == user.id)).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="not_found")
    return m


def own_matter_or_none(db, user, matter_id):
    """For the chat routes: the person's own matter, 404 for anyone else's (never told apart from one that does not exist)."""
    return None if matter_id is None else _own_matter(db, user, matter_id)


class MatterIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    court: Optional[str] = Field(default=None, max_length=200)
    case_number: Optional[str] = Field(default=None, max_length=100)
    sections: Optional[str] = Field(default=None, max_length=300)
    stage: Optional[Stage] = None
    next_date: Optional[datetime.date] = None
    facts: Optional[str] = Field(default=None, max_length=MAX_FACTS)


class MatterPatch(BaseModel):
    """Only the fields that are sent change; null (or an empty text) clears a field except the title."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    court: Optional[str] = Field(default=None, max_length=200)
    case_number: Optional[str] = Field(default=None, max_length=100)
    sections: Optional[str] = Field(default=None, max_length=300)
    stage: Optional[Stage] = None
    next_date: Optional[datetime.date] = None
    facts: Optional[str] = Field(default=None, max_length=MAX_FACTS)
    archived: Optional[bool] = None


def _counts(db, ids):
    if not ids:
        return {}
    return {mid: n for mid, n in db.execute(select(M.Chat.matter_id, func.count()).where(M.Chat.matter_id.in_(ids)).group_by(M.Chat.matter_id)).all()}


def _active_limit(db, user):
    ent = quota.entitlement(db, user.plan_id, "matters_active")
    return ent[1] if ent else 0


@router.get("/api/matters", summary="My matters", description="Open matters by default, the one with the nearest next hearing date first (those with no date after, newest first); archived=true lists the archived ones. `limit` is the plan's number of open matters.")
def list_matters(archived: bool = False, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    user = principal.user
    rows = db.execute(select(M.Matter).where(M.Matter.user_id == user.id, M.Matter.archived.is_(archived))).scalars().all()
    counts = _counts(db, [m.id for m in rows])
    far = datetime.date.max
    rows.sort(key=lambda m: (m.next_date or far, -(m.updated_at.timestamp() if m.updated_at else 0)))
    open_n = db.execute(select(func.count()).select_from(M.Matter).where(M.Matter.user_id == user.id, M.Matter.archived.is_(False))).scalar()
    return {"matters": [matter_view(m, counts.get(m.id, 0)) for m in rows], "open": open_n, "limit": _active_limit(db, user)}


@router.post("/api/matters", status_code=201, summary="Open a matter", description="409 matter_limit when the plan's number of open matters is reached (the body of the error says the limit).")
def create_matter(body: MatterIn, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    user = principal.user
    db.execute(select(M.User.id).where(M.User.id == user.id).with_for_update()).scalar_one()      # two creations at once cannot both take the last place
    limit = _active_limit(db, user)
    n = db.execute(select(func.count()).select_from(M.Matter).where(M.Matter.user_id == user.id, M.Matter.archived.is_(False))).scalar()
    if n >= limit:
        raise HTTPException(status_code=409, detail="matter_limit")
    title = _line(body.title, 200)
    if not title:
        raise HTTPException(status_code=422, detail="title_required")
    m = M.Matter(user_id=user.id, title=title, court=_line(body.court, 200), case_number=_line(body.case_number, 100), sections=_line(body.sections, 300), stage=body.stage,
                 next_date=body.next_date, facts=(body.facts or "").strip() or None)
    db.add(m)
    db.commit()
    return matter_view(m, 0)


@router.get("/api/matters/{matter_id}", summary="One matter with its conversations")
def get_matter(matter_id: uuid.UUID, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    from .chats import chat_view
    m = _own_matter(db, principal.user, matter_id)
    chats = db.execute(select(M.Chat).where(M.Chat.matter_id == m.id, M.Chat.user_id == principal.user.id).order_by(M.Chat.updated_at.desc(), M.Chat.id)).scalars().all()
    return {**matter_view(m, len(chats)), "chats": [chat_view(c) for c in chats]}


@router.patch("/api/matters/{matter_id}", summary="Change a matter, archive it or bring it back")
def patch_matter(matter_id: uuid.UUID, body: MatterPatch, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    user = principal.user
    db.execute(select(M.User.id).where(M.User.id == user.id).with_for_update()).scalar_one()
    m = _own_matter(db, user, matter_id)
    sent = body.model_fields_set
    if body.archived is False and m.archived:                                          # bringing one back takes an open place
        n = db.execute(select(func.count()).select_from(M.Matter).where(M.Matter.user_id == user.id, M.Matter.archived.is_(False))).scalar()
        if n >= _active_limit(db, user):
            raise HTTPException(status_code=409, detail="matter_limit")
    if "title" in sent and body.title is not None:
        t = _line(body.title, 200)
        if not t:
            raise HTTPException(status_code=422, detail="title_required")
        m.title = t
    for f, n in (("court", 200), ("case_number", 100), ("sections", 300)):
        if f in sent:
            setattr(m, f, _line(getattr(body, f), n))
    if "stage" in sent:
        m.stage = body.stage
    if "next_date" in sent:
        m.next_date = body.next_date
    if "facts" in sent:
        m.facts = (body.facts or "").strip() or None
    if body.archived is not None:
        m.archived = body.archived
    m.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return matter_view(m, _counts(db, [m.id]).get(m.id, 0))


@router.delete("/api/matters/{matter_id}", summary="Delete a matter", description="Its conversations stay, unfiled, unless with_chats=true: then they are deleted with it, with their messages, now.")
def delete_matter(matter_id: uuid.UUID, with_chats: bool = False, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    m = _own_matter(db, principal.user, matter_id)
    removed = 0
    if with_chats:
        for c in db.execute(select(M.Chat).where(M.Chat.matter_id == m.id, M.Chat.user_id == principal.user.id)).scalars().all():
            db.delete(c)
            removed += 1
    db.delete(m)
    db.commit()
    return {"deleted": True, "chats_deleted": removed}
