
"""
answer_cache.py

A safe, human-approved answer-reuse cache for chat_assistant.answer_question().
Design discussed and approved 2026-09-14 (see
memory/live-judgment-retrieval-plan.md's "OPEN" section for the original,
deferred version of this idea, and memory/whatsapp-interface-technical-plan.md
for the WhatsApp-side motivation: minimise Anthropic API cost on repeat
questions without ever weakening the tool's grounding guarantees).

WHY THIS IS SAFE (the design point that unlocked building it): a naive
version would compare the person's raw WORDING to decide "is this the same
question as before" -- fragile (real users never phrase things identically)
and risky (two similarly-worded questions can have a legally different
answer). Instead, this caches on chat_assistant's own DETERMINISTIC
conclusion -- the exact set of statute sections / judgment paragraphs it
already decided are the single, solid match for the question (the
'single_match' state). Two different questions only ever share a cache
entry when the tool's own grounded matching independently landed on the
IDENTICAL set of legal sources -- never on textual similarity. The
expensive step this skips is ONLY the final wording (generate_grounded_response,
the Sonnet call) -- the classification and retrieval steps that decide
whether reuse is even eligible always still run in full, so nothing about
the safety/grounding path is bypassed.

A generated answer is NEVER served from cache automatically. It is only
recorded as a CANDIDATE (see record_candidate()); a person reviews
candidates (answer_cache_report.py) and explicitly approves the ones worth
reusing (approve()) -- mirroring related_judgments.py's existing
record_approved()/approved_candidates() pattern for judgments, applied
here to full generated answers instead.

Approved entries expire after DEFAULT_TTL_DAYS so a stale answer can't be
served forever if the underlying law changes -- there is no automatic
re-verification, only automatic EXPIRY back to "generate fresh, and let a
person decide whether to re-approve."
"""
import hashlib
import json
import os
import sqlite3
import time

DB_PATH = os.environ.get("ANSWER_CACHE_DB_PATH", "answer_cache.db")
DEFAULT_TTL_DAYS = 30


def _connect():
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candidates (
            cache_key TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            sample_question TEXT NOT NULL,
            response_text TEXT NOT NULL,
            situation_detected INTEGER NOT NULL,
            hit_count INTEGER NOT NULL,
            first_seen REAL NOT NULL,
            last_seen REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approved (
            cache_key TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            response_text TEXT NOT NULL,
            situation_detected INTEGER NOT NULL,
            approved_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    return conn


def _match_identity(match: dict):
    """A deterministic identity for one retrieved match -- reuses the exact
    same 'chunk_id, else (case_name, paragraph_number, section_number)'
    convention semantic_retrieval.hybrid_search already uses to dedupe
    matches, extended with 'act' so BNS/BNSS/ITACT sections sharing a
    number are never confused."""
    chunk_id = match.get("chunk_id")
    if chunk_id:
        return ("chunk", chunk_id)
    return (
        "fields",
        match.get("act"),
        match.get("section_number"),
        match.get("case_name"),
        match.get("paragraph_number"),
    )


def cache_key(matches: list) -> str:
    """A stable key for a set of matches, independent of their order.
    Two questions worded completely differently produce the SAME key if
    and only if chat_assistant's own retrieval independently landed on
    the identical set of sources -- see module docstring."""
    identities = sorted((_match_identity(m) for m in matches), key=lambda t: json.dumps(t, default=str))
    canonical = json.dumps(identities, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def describe_matches(matches: list) -> str:
    """Human-readable summary for the review report -- e.g.
    'BNS 303; BNSS 187; Judgment: Arnesh Kumar v State of Bihar'."""
    parts = []
    for m in matches:
        if m.get("case_name"):
            parts.append(f"Judgment: {m['case_name']}")
        elif m.get("act") and m.get("section_number"):
            parts.append(f"{m['act']} {m['section_number']}")
    return "; ".join(parts) if parts else "(no identifiable sources)"


def get_cached(matches: list):
    """Returns {'response_text', 'situation_detected'} for an approved,
    not-yet-expired answer matching this exact set of sources, or None."""
    key = cache_key(matches)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT response_text, situation_detected, expires_at FROM approved WHERE cache_key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    response_text, situation_detected, expires_at = row
    if expires_at <= time.time():
        return None
    return {"response_text": response_text, "situation_detected": bool(situation_detected)}


def record_candidate(matches: list, question: str, response_text: str, situation_detected: bool) -> None:
    """Records that this exact set of sources produced a fresh, confident
    ('single_match') answer -- raw material for a person to review later.
    Never changes what any user is told; purely a log for
    answer_cache_report.py."""
    key = cache_key(matches)
    description = describe_matches(matches)
    now = time.time()
    conn = _connect()
    try:
        with conn:
            existing = conn.execute(
                "SELECT hit_count FROM candidates WHERE cache_key = ?", (key,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO candidates (cache_key, description, sample_question, response_text, "
                    "situation_detected, hit_count, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                    (key, description, question, response_text, int(situation_detected), now, now),
                )
            else:
                conn.execute(
                    "UPDATE candidates SET response_text = ?, situation_detected = ?, hit_count = hit_count + 1, "
                    "last_seen = ? WHERE cache_key = ?",
                    (response_text, int(situation_detected), now, key),
                )
    finally:
        conn.close()


def list_candidates() -> list:
    """All candidates, most-repeated first -- what a person reviews to
    decide what's worth approving for reuse."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT cache_key, description, sample_question, response_text, situation_detected, "
            "hit_count, first_seen, last_seen FROM candidates ORDER BY hit_count DESC, last_seen DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "cache_key": r[0], "description": r[1], "sample_question": r[2], "response_text": r[3],
            "situation_detected": bool(r[4]), "hit_count": r[5], "first_seen": r[6], "last_seen": r[7],
        }
        for r in rows
    ]


def list_approved() -> list:
    """All currently-approved entries, for the report to show what's live
    and how long until each expires."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT cache_key, description, approved_at, expires_at FROM approved ORDER BY expires_at ASC"
        ).fetchall()
    finally:
        conn.close()
    return [{"cache_key": r[0], "description": r[1], "approved_at": r[2], "expires_at": r[3]} for r in rows]


def approve(cache_key_value: str, ttl_days: float = DEFAULT_TTL_DAYS) -> bool:
    """Promotes a candidate into the approved table -- a person's explicit
    decision, never automatic. Returns False if no such candidate exists."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT description, response_text, situation_detected FROM candidates WHERE cache_key = ?",
            (cache_key_value,),
        ).fetchone()
        if row is None:
            return False
        description, response_text, situation_detected = row
        now = time.time()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO approved (cache_key, description, response_text, situation_detected, "
                "approved_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cache_key_value, description, response_text, situation_detected, now, now + ttl_days * 86400),
            )
        return True
    finally:
        conn.close()


def revoke(cache_key_value: str) -> bool:
    """Undoes an approval immediately (e.g. the reviewer changes their
    mind) -- the corresponding question just goes back to always
    generating fresh."""
    conn = _connect()
    try:
        with conn:
            cur = conn.execute("DELETE FROM approved WHERE cache_key = ?", (cache_key_value,))
        return cur.rowcount > 0
    finally:
        conn.close()
