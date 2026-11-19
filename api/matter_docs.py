"""
api/matter_docs.py -- the database side of a matter's documents (MATTER_FILES; matter_files.py holds the reading, the search and the checks). Built 2026-11-19 (owner: "go on P0 and P1").

store()        reads one uploaded file, keeps its passages (and their vectors when the meaning search answers), never the file's bytes.
for_question() the passages of ONE matter (selected by matter id AND the person's id) that match a question, as the engine's separate argument (never folded into the question's words).
full_text()    the whole read text of every file of a matter, by document number and page/paragraph, for the quote-on-page check after the answer.
Everything here fails open for the answer: if the documents cannot be read at question time, the question is answered without them and the log says so.
"""
import array
import hashlib
import logging
import os
import time

from sqlalchemy import func, select

import matter_files as MF

from .db import models as M

logger = logging.getLogger("recourse.api")
EMBED_MODEL = "voyage-law-2"
EMBED_BATCH = 64
EMBED_SECONDS = 60


def _voyage():
    if not os.environ.get("VOYAGE_API_KEY"):
        return None
    try:
        import voyageai
        return voyageai.Client(max_retries=1, timeout=30)
    except Exception:  # noqa: BLE001
        return None


def embed(texts, input_type):
    """Vectors for the texts, or None when the meaning search cannot be reached (no key, no package, an error, too slow). Never raises; never logs the text."""
    client = _voyage()
    if client is None or not texts:
        return None
    out, t0 = [], time.monotonic()
    try:
        for i in range(0, len(texts), EMBED_BATCH):
            if time.monotonic() - t0 > EMBED_SECONDS:
                return None
            r = client.embed(texts[i:i + EMBED_BATCH], model=EMBED_MODEL, input_type=input_type)
            out.extend(r.embeddings)
            try:
                import cost_log
                cost_log.note_voyage("matter_" + input_type, EMBED_MODEL, getattr(r, "total_tokens", 0))
            except Exception:  # noqa: BLE001
                pass
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("matter files: meaning search unavailable: %s", type(exc).__name__)
        return None


def _pack(vec):
    return array.array("f", vec).tobytes() if vec else None


def _unpack(b):
    if not b:
        return None
    a = array.array("f")
    a.frombytes(b)
    return list(a)


def used_bytes(db, user_id):
    return int(db.execute(select(func.coalesce(func.sum(M.MatterFile.size_bytes), 0)).where(M.MatterFile.user_id == user_id)).scalar() or 0)


def file_view(f):
    return {"id": str(f.id), "doc_no": f.doc_no, "name": f.name, "kind": f.kind, "unit": f.unit, "units": f.units, "unread": list(f.unread or []), "passages": f.passages, "size_bytes": f.size_bytes,
            "searchable_by_meaning": bool(f.embedded), "created_at": f.created_at.isoformat() if f.created_at else None}


def store(db, user_id, matter_id, name, data):
    """Reads the file and adds it to the matter. Raises MF.Refused. The caller has checked who may, the counts and the sizes, and commits."""
    kind = MF.sniff(data, name)
    ex = MF.extract(data, kind)
    ps = MF.passages(ex)
    if not ps:
        raise MF.Refused("empty")
    vecs = embed([p["text"] for p in ps], "document")
    last = db.execute(select(func.coalesce(func.max(M.MatterFile.doc_no), 0)).where(M.MatterFile.matter_id == matter_id)).scalar() or 0
    f = M.MatterFile(matter_id=matter_id, user_id=user_id, doc_no=int(last) + 1, name=_safe_name(name), kind=kind, unit=ex["unit"], size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                     units=ex["count"], unread=ex["unread"], passages=len(ps), embedded=vecs is not None)
    db.add(f)
    db.flush()
    for i, p in enumerate(ps):
        db.add(M.MatterFilePassage(file_id=f.id, matter_id=matter_id, seq=p["seq"], loc=p["loc"], loc_to=p["loc_to"], text=p["text"], vec=_pack(vecs[i]) if vecs else None))
    db.flush()
    return f


def _safe_name(name):
    base = os.path.basename((name or "").replace("\\", "/")).strip() or "document"
    base = "".join(ch for ch in base if ch.isprintable())
    return base[:200]


def docs_meta(db, user_id, matter_id):
    """{doc_no: {'name', 'unit', 'unread', 'kind'}} for the matter's files (the person's own only)."""
    rows = db.execute(select(M.MatterFile).where(M.MatterFile.matter_id == matter_id, M.MatterFile.user_id == user_id).order_by(M.MatterFile.doc_no)).scalars().all()
    return {f.doc_no: {"name": f.name, "unit": f.unit, "unread": list(f.unread or []), "kind": f.kind, "id": str(f.id)} for f in rows}


def _rows(db, user_id, matter_id):
    q = (select(M.MatterFile.doc_no, M.MatterFilePassage.loc, M.MatterFilePassage.loc_to, M.MatterFilePassage.text, M.MatterFilePassage.vec, M.MatterFilePassage.seq)
         .join(M.MatterFile, M.MatterFile.id == M.MatterFilePassage.file_id)
         .where(M.MatterFilePassage.matter_id == matter_id, M.MatterFile.matter_id == matter_id, M.MatterFile.user_id == user_id)
         .order_by(M.MatterFile.doc_no, M.MatterFilePassage.seq))
    return db.execute(q).all()


def for_question(db, user_id, matter_id, query_text):
    """{'docs': docs_meta, 'chosen': [passages handed over]} or None when the matter has no files. The search sees only this matter's passages, read with the person's id as well as the matter's."""
    meta = docs_meta(db, user_id, matter_id)
    if not meta:
        return None
    rows = [{"doc": r.doc_no, "loc": r.loc, "loc_to": r.loc_to, "text": r.text, "vec": _unpack(r.vec)} for r in _rows(db, user_id, matter_id)]
    qv = None
    if any(r["vec"] for r in rows):
        e = embed([query_text[:2000]], "query")
        qv = e[0] if e else None
    chosen = MF.search(query_text, rows, qvec=qv)
    return {"docs": meta, "chosen": chosen, "meaning": qv is not None}


def full_text(db, user_id, matter_id):
    """{doc_no (str): {'unit', 'units': {loc: text}}}: every passage of every file of the matter, joined page by page (or paragraph by paragraph), for matter_files.check_quotes."""
    meta = docs_meta(db, user_id, matter_id)
    out = {str(no): {"unit": m["unit"], "units": {}} for no, m in meta.items()}
    for r in _rows(db, user_id, matter_id):
        d = out.get(str(r.doc_no))
        if d is None:
            continue
        if r.loc == r.loc_to:
            d["units"][r.loc] = (d["units"].get(r.loc, "") + " " + r.text).strip()
        else:                                            # a Word passage that joins paragraphs loc..loc_to: its lines are those paragraphs, in order
            parts = r.text.split("\n")
            span = list(range(r.loc, r.loc_to + 1))
            if len(parts) == len(span):
                for loc, t in zip(span, parts):
                    d["units"][loc] = (d["units"].get(loc, "") + " " + t).strip()
            else:
                d["units"][r.loc] = (d["units"].get(r.loc, "") + " " + r.text).strip()
    return out


def page_text(db, user_id, matter_id, doc_no, loc):
    """The read text of one page (or paragraph) of one document, or None."""
    t = full_text(db, user_id, matter_id).get(str(doc_no))
    return None if t is None else t["units"].get(int(loc))
