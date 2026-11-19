"""
api/routers/matter_files.py -- the documents a lawyer files under a matter (MATTER_FILES, default off; matter_files.py, api/matter_docs.py). Built 2026-11-19 on the owner's "go on P0 and P1": lawyers first, staging only
until a lawyer has written the privacy and consent text, text-based PDF / Word / plain text only, no OCR. Limits: 10 files per matter and 10 MB per file (fixed, matter_files.py), and the plan's matter_files_mb for
the whole account (provisional: 50 on the free plan).

The file's bytes are read once and NOT kept: only the text a program read from it, cut into passages with their page or paragraph numbers. The upload is JSON ({name, content_base64}) because the website's server
forwards JSON only. Every route needs a signed-in person who has accepted the documents (deps.ready_user); a matter and its files belong to that person and anyone else gets 404.
"""
import base64
import binascii
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import matter_files as MF

from .. import matter_docs, quota
from ..db import models as M
from ..deps import Principal, get_db, ready_user
from .matters import _own_matter

router = APIRouter()
MAX_B64 = (MF.MAX_FILE_BYTES * 4) // 3 + 8
STATUS = {"unsupported_type": 415, "too_large": 413, "too_many_pages": 422, "unreadable": 422, "empty": 422, "no_text": 422}


def _on():
    if not MF.enabled():
        raise HTTPException(status_code=404, detail="feature_off")


def _limit_bytes(db, user):
    ent = quota.entitlement(db, user.plan_id, "matter_files_mb")
    return None if ent is None or ent[1] is None else int(ent[1]) * 1024 * 1024


def _summary(db, user, m):
    files = db.execute(select(M.MatterFile).where(M.MatterFile.matter_id == m.id, M.MatterFile.user_id == user.id).order_by(M.MatterFile.doc_no)).scalars().all()
    limit = _limit_bytes(db, user)
    return {"files": [matter_docs.file_view(f) for f in files], "files_max": MF.MAX_FILES_PER_MATTER, "file_max_bytes": MF.MAX_FILE_BYTES,
            "account_used_bytes": matter_docs.used_bytes(db, user.id), "account_limit_bytes": limit if limit is not None else 0}


class Upload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=4, max_length=MAX_B64)


@router.get("/api/matters/{matter_id}/files", summary="The documents of a matter", description="404 feature_off while MATTER_FILES is off.")
def list_files(matter_id: uuid.UUID, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    _on()
    m = _own_matter(db, principal.user, matter_id)
    return _summary(db, principal.user, m)


@router.post("/api/matters/{matter_id}/files", status_code=201, summary="Add a document to a matter",
             description="JSON {name, content_base64}. PDF (with text), Word (.docx) or plain text. 409 file_limit (10 per matter), storage_limit (the plan's total), matter_archived; 413 too_large (10 MB); 415 unsupported_type; "
                         "422 unreadable, empty, no_text (a scan: there is no OCR), too_many_pages. The file's bytes are not kept.")
def add_file(matter_id: uuid.UUID, body: Upload, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    _on()
    user = principal.user
    db.execute(select(M.User.id).where(M.User.id == user.id).with_for_update()).scalar_one()          # two uploads at once cannot both take the last place or the last megabytes
    m = _own_matter(db, user, matter_id)
    if m.archived:
        raise HTTPException(status_code=409, detail="matter_archived")
    n = db.execute(select(func.count()).select_from(M.MatterFile).where(M.MatterFile.matter_id == m.id)).scalar()
    if n >= MF.MAX_FILES_PER_MATTER:
        raise HTTPException(status_code=409, detail="file_limit")
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="bad_file_data")
    if len(data) > MF.MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="too_large")
    limit = _limit_bytes(db, user)
    if limit is None or matter_docs.used_bytes(db, user.id) + len(data) > limit:
        raise HTTPException(status_code=409, detail="storage_limit")
    try:
        f = matter_docs.store(db, user.id, m.id, body.name, data)
    except MF.Refused as e:
        db.rollback()
        raise HTTPException(status_code=STATUS.get(e.code, 422), detail=e.code)
    db.commit()
    print("MATTER_FILE_ADDED " + __import__("json").dumps({"kind": f.kind, "units": f.units, "unread": len(f.unread or []), "passages": f.passages, "meaning": bool(f.embedded), "kb": len(data) // 1024}), flush=True)   # no name, no text
    return matter_docs.file_view(f)


@router.delete("/api/matters/{matter_id}/files/{file_id}", summary="Remove a document from a matter", description="Its read text goes with it, now.")
def delete_file(matter_id: uuid.UUID, file_id: uuid.UUID, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    _on()
    m = _own_matter(db, principal.user, matter_id)
    f = db.execute(select(M.MatterFile).where(M.MatterFile.id == file_id, M.MatterFile.matter_id == m.id, M.MatterFile.user_id == principal.user.id)).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="not_found")
    db.delete(f)
    db.commit()
    return {"deleted": True}


@router.get("/api/matters/{matter_id}/files/{doc_no}/text", summary="The read text of one page or paragraph of a document", description="?loc=N. What the program read, so a citation under an answer can be checked against it.")
def page(matter_id: uuid.UUID, doc_no: int, loc: int, principal: Principal = Depends(ready_user), db=Depends(get_db)):
    _on()
    m = _own_matter(db, principal.user, matter_id)
    meta = matter_docs.docs_meta(db, principal.user.id, m.id).get(doc_no)
    if meta is None or loc < 1:
        raise HTTPException(status_code=404, detail="not_found")
    t = matter_docs.page_text(db, principal.user.id, m.id, doc_no, loc)
    unread = loc in (meta.get("unread") or [])
    if t is None and not unread:
        raise HTTPException(status_code=404, detail="not_found")
    return {"doc_no": doc_no, "name": meta["name"], "unit": meta["unit"], "loc": loc, "text": t or "", "unread": unread}
