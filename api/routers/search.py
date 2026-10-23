"""
api/routers/search.py -- the search page's route (built 2026-10-23; the engine is search_service.py).
POST /api/search {q, mode}: a search of the sections and judgments Recourse holds. mode 'library' (default; free of any model call) or 'wider' (the sci-search service's Supreme Court passages: a separate, slower request
that is always labelled "not independently verified"). A signed-in person who has accepted the documents and declared being 18+ (deps.ready_user), like every route that spends something. Each search counts one unit of the
plan's `search` (or `search_wider`) allowance per IST day (quota.py); a wider search that could not be served (the service is not configured or does not answer) gives its unit back. The query is NOT stored and NOT logged: the
only trace is the counted event (a kind, a time, no text). A flood guard per person per minute and a cap on searches running at the same moment protect the service; neither spends a unit.
"""
import logging
import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import search_service

from .. import config, quota, ratelimit
from ..deps import Principal, get_db, ready_user

router = APIRouter()
logger = logging.getLogger("api.search")
_SLOTS = {"n": None, "sem": None}


class SearchBody(BaseModel):
    q: str = Field(min_length=1, max_length=1000, description="What the person typed: a section, a case name, a citation or a few words. Only the first 300 characters are used.")
    mode: Literal["library", "wider"] = "library"


def _slot():
    n = config.search_parallel()
    if _SLOTS["sem"] is None or _SLOTS["n"] != n:
        _SLOTS["n"], _SLOTS["sem"] = n, threading.BoundedSemaphore(n)
    return _SLOTS["sem"]


@router.post("/api/search", summary="Search the sections and judgments Recourse holds",
             description="mode=library searches the stored Acts (BNS, BNSS, the IT and NI Acts, the Acts on the shelf), the reviewed library judgments and the Supreme Court title index; no model is called. mode=wider asks the sci-search service "
                         "for Supreme Court passages (labelled not independently verified). Each search counts one unit of the plan's daily `search` / `search_wider` allowance (429 limit_reached with `usage`); a wider search "
                         "that cannot be served gives its unit back. 429 rate_limited / busy: try again shortly. The query is not stored.")
def search(body: SearchBody, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    q = " ".join(body.q.split())
    if not q:
        raise HTTPException(status_code=422, detail="empty_query")
    user = principal.user
    limit = config.search_rate_per_minute()
    if limit and not ratelimit.hit("search:" + str(user.id), limit):
        raise HTTPException(status_code=429, detail="rate_limited", headers={"Retry-After": "30"})
    slot = _slot()
    if not slot.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="busy", headers={"Retry-After": "2"})
    try:
        feature = "search_wider" if body.mode == "wider" else "search"
        ok, event_id, info = quota.reserve(db, user, feature)
        db.commit()                                     # keeps the unit and lets go of the row lock and the connection before the search runs
        if not ok:
            return JSONResponse({"detail": info.get("reason", "limit_reached"), "usage": info}, status_code=429)
        try:
            result = search_service.search(q, body.mode)
        except Exception as exc:  # noqa: BLE001 -- search() does not raise; this guards an import or a bug
            logger.error("search failed: %s", type(exc).__name__)
            quota.release(db, event_id)
            db.commit()
            raise HTTPException(status_code=500, detail="search_failed") from None
        wider = result.get("wider")
        served = not (body.mode == "wider" and not (wider or {}).get("available"))
        if served:
            quota.settle(db, event_id)
        else:
            quota.release(db, event_id)
            info = {**info, "used": max(0, int(info.get("used") or 1) - 1)}
        db.commit()
        logger.info("search mode=%s intent=%s served=%s provisions=%d cases=%d mentions=%d", body.mode, result.get("intent"), served, len(result.get("provisions") or []), len(result.get("cases") or []),
                    len(result.get("mentions") or []))
        return {"result": result, "usage": info}
    finally:
        slot.release()
