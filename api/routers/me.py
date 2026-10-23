"""
api/routers/me.py -- who am I, what must I accept, and my data (steps A3.1 and A3.2). GET /api/me is also the first call the Streamlit path makes: the signed token creates the person on first use.
Consent and the 18+ declaration (owner's D6) are required before asking; export gives the person everything held about them; DELETE /api/me removes the account and everything the person owns AT ONCE (the billing and audit rows stay, with no
person and no text attached; backups roll off within about 35 days, which the notice says).
"""
import datetime
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import consent, netutil, quota
from ..db import models as M
from ..deps import Principal, current_user, get_db
from .auth import clear_session_cookies

router = APIRouter()


def user_view(db, user):
    plan = db.get(M.Plan, user.plan_id) if user.plan_id else None
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name, "role": user.role, "plan": plan.code if plan else None}


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime.datetime, datetime.date)) else v


@router.get("/api/me", summary="Who am I, and what must I still accept")
def me(principal: Principal = Depends(current_user), db=Depends(get_db)):
    st = consent.status(db, principal.user)
    return {"user": user_view(db, principal.user), "via": principal.via, "consent": {"missing": st["missing"], "age_confirmed": st["age_confirmed"], "ready": st["ready"],
                                                                                 "legal_text_is_placeholder": st["legal_text_is_placeholder"]},
            "usage": quota.usage_view(db, principal.user)}


@router.get("/api/legal/{document}", summary="The current text of a document the person must accept")
def legal_text(document: str):
    cur = consent.current(document)
    if cur is None:
        raise HTTPException(status_code=404, detail="unknown document")
    return {"document": cur["document"], "version": cur["version"], "text": cur["text"], "placeholder": cur["placeholder"]}


class ConsentBody(BaseModel):
    document: str = Field(min_length=1, max_length=20)
    version: str = Field(min_length=1, max_length=40)


@router.post("/api/me/consent", summary="Accept the current version of a document")
def accept_consent(body: ConsentBody, request: Request, principal: Principal = Depends(current_user), db=Depends(get_db)):
    try:
        row = consent.accept(db, principal.user, body.document, body.version, ip_hash=netutil.ip_hash(netutil.client_ip(request)))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409 if str(exc) == "stale_version" else 404, detail=str(exc)) from None
    db.commit()
    return {"document": row.document, "version": row.version, "accepted_at": _iso(row.accepted_at)}


class AgeBody(BaseModel):
    confirmed: bool


@router.post("/api/me/age", summary="Confirm being 18 or older")
def confirm_age(body: AgeBody, principal: Principal = Depends(current_user), db=Depends(get_db)):
    if not body.confirmed:
        raise HTTPException(status_code=422, detail="age must be confirmed")
    if principal.user.age_confirmed_at is None:
        principal.user.age_confirmed_at = datetime.datetime.now(datetime.timezone.utc)
        db.commit()
    return {"age_confirmed": True}


@router.post("/api/me/export", summary="Everything held about me, as a file")
def export_me(principal: Principal = Depends(current_user), db=Depends(get_db)):
    u = principal.user
    chats = []
    for ch in db.execute(select(M.Chat).where(M.Chat.user_id == u.id).order_by(M.Chat.created_at)).scalars():
        chats.append({"id": str(ch.id), "title": ch.title, "audience": ch.audience, "archived": ch.archived, "created_at": _iso(ch.created_at),
                      "messages": [{"seq": m.seq, "role": m.role, "content": m.content, "result": m.result, "state": m.state, "cost_inr": float(m.cost_inr) if m.cost_inr is not None else None,
                                    "created_at": _iso(m.created_at)} for m in ch.messages]})
    data = {
        "exported_at": _iso(datetime.datetime.now(datetime.timezone.utc)),
        "account": {"id": str(u.id), "email": u.email, "display_name": u.display_name, "role": u.role, "language": u.language, "age_confirmed_at": _iso(u.age_confirmed_at), "created_at": _iso(u.created_at), "last_seen_at": _iso(u.last_seen_at)},
        "sign_in_methods": [{"provider": i.provider, "since": _iso(i.created_at)} for i in db.execute(select(M.Identity).where(M.Identity.user_id == u.id)).scalars()],
        "consents": [{"document": c.document, "version": c.version, "accepted_at": _iso(c.accepted_at)} for c in db.execute(select(M.Consent).where(M.Consent.user_id == u.id).order_by(M.Consent.accepted_at)).scalars()],
        "chats": chats,
        "notes": [{"id": str(n.id), "body": n.body, "created_at": _iso(n.created_at), "updated_at": _iso(n.updated_at)} for n in db.execute(select(M.Note).where(M.Note.user_id == u.id)).scalars()],
        "feedback": [{"kind": f.kind, "comment": f.comment, "status": f.status, "created_at": _iso(f.created_at)} for f in db.execute(select(M.Feedback).where(M.Feedback.user_id == u.id)).scalars()],
        "usage": [{"kind": e.kind, "at": _iso(e.at), "cost_inr": float(e.cost_inr) if e.cost_inr is not None else None, "counted": e.counted} for e in db.execute(select(M.UsageEvent).where(M.UsageEvent.user_id == u.id).order_by(M.UsageEvent.at)).scalars()],
    }
    return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="recourse-my-data.json"', "Cache-Control": "no-store"})


@router.delete("/api/me", summary="Delete my account and everything I own, now")
def delete_me(response: Response, confirm: str = "", principal: Principal = Depends(current_user), db=Depends(get_db)):
    if confirm != "DELETE":
        raise HTTPException(status_code=422, detail="add ?confirm=DELETE to delete the account")
    u = principal.user
    now = datetime.datetime.now(datetime.timezone.utc)
    ref = hashlib.sha256(str(u.id).encode("utf-8")).hexdigest()[:16]
    db.add(M.AuditLog(actor_user_id=None, action="user_deleted", target_type="user", target_id=ref, detail={"via": principal.via}))
    db.add(M.DeletionRequest(user_id=None, requested_at=now, completed_at=now))
    db.delete(u)
    db.commit()
    clear_session_cookies(response)
    return {"deleted": True}
