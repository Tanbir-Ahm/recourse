"""
api/routers/me.py -- who am I, and my data (step A3). GET /api/me is also the first call the Streamlit path makes: the signed token creates the person on first use.
(Consent, age, usage and limits, export and delete are added to this file in the next sub-steps.)
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select

from ..db import models as M
from ..deps import Principal, current_user, get_db

router = APIRouter()


def user_view(db, user):
    plan = db.get(M.Plan, user.plan_id) if user.plan_id else None
    return {"id": str(user.id), "email": user.email, "display_name": user.display_name, "role": user.role, "plan": plan.code if plan else None}


@router.get("/api/me", summary="Who am I")
def me(principal: Principal = Depends(current_user), db=Depends(get_db)):
    return {"user": user_view(db, principal.user), "via": principal.via}
