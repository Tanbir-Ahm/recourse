"""
api/consent.py -- the documents a person must accept before asking (step A3.2; gate G1). Texts and versions live in api/legal/ (placeholders until the lawyer's text); an acceptance records the document, its VERSION and the SHA-256 of the exact text shown,
so what a person agreed to can be proved later. A person who accepted an older version is asked again. While a required document is still a placeholder, accounts cannot be opened (config.accounts_open() plus legal_ready()) unless the
staging-only override ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL=on is set.
"""
import hashlib
import json
import os

from sqlalchemy import select

from .db import models as M

LEGAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "legal")


def _config():
    with open(os.path.join(LEGAL_DIR, "documents.json"), encoding="utf-8") as f:
        return json.load(f)


def required():
    return list(_config()["required"])


def current(document):
    """-> {'document', 'version', 'text', 'text_hash', 'placeholder'} or None for an unknown document."""
    d = _config()["documents"].get(document)
    if not d or document not in M.DOCUMENTS:
        return None
    with open(os.path.join(LEGAL_DIR, d["file"]), encoding="utf-8") as f:
        text = f.read()
    return {"document": document, "version": d["version"], "text": text, "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(), "placeholder": bool(d.get("placeholder"))}


def legal_ready():
    """True when every required document is the lawyer's text (not a placeholder)."""
    cfg = _config()
    return all(not cfg["documents"][d].get("placeholder") for d in cfg["required"])


def accepted_versions(db, user_id):
    """{document: {'version', 'accepted_at', 'text_hash'}} for the LATEST acceptance of each document."""
    out = {}
    for c in db.execute(select(M.Consent).where(M.Consent.user_id == user_id).order_by(M.Consent.accepted_at)).scalars():
        out[c.document] = {"version": c.version, "accepted_at": c.accepted_at, "text_hash": c.text_hash}
    return out


def status(db, user):
    """What the person still has to do before asking: documents (not accepted at the current version) and the age declaration."""
    have = accepted_versions(db, user.id)
    missing = []
    for doc in required():
        cur = current(doc)
        got = have.get(doc)
        if not got or got["version"] != cur["version"] or got["text_hash"] != cur["text_hash"]:
            missing.append({"document": doc, "version": cur["version"], "placeholder": cur["placeholder"]})
    return {"missing": missing, "age_confirmed": user.age_confirmed_at is not None, "ready": not missing and user.age_confirmed_at is not None,
            "legal_text_is_placeholder": not legal_ready()}


def accept(db, user, document, version, ip_hash=None):
    """Records an acceptance of the CURRENT version of a document. Returns the Consent row; raises ValueError('unknown_document'|'stale_version') otherwise. Accepting the same version twice returns the first record."""
    cur = current(document)
    if cur is None:
        raise ValueError("unknown_document")
    if version != cur["version"]:
        raise ValueError("stale_version")
    row = db.execute(select(M.Consent).where(M.Consent.user_id == user.id, M.Consent.document == document, M.Consent.version == cur["version"], M.Consent.text_hash == cur["text_hash"])).scalars().first()
    if row is not None:
        return row
    row = M.Consent(user_id=user.id, document=document, version=cur["version"], text_hash=cur["text_hash"], ip_hash=ip_hash)
    db.add(row)
    db.flush()
    return row
