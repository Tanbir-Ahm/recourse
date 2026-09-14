
"""
whatsapp_store.py

The conversation memory Recourse doesn't have anywhere else in the
project (confirmed 2026-09-11: no database exists anywhere in the repo
-- recourse_app.py is fully stateless, st.session_state only survives
one open browser tab). This is the new piece: one running record per
WhatsApp phone number, so a follow-up like "what if it was a cow, not
a goat?" can be understood without the person re-explaining everything.

Deliberately plain SQLite (built into Python, zero setup, free) -- see
memory/whatsapp-interface-technical-plan.md section 7 for why this is
the right starting point before any real traffic exists. WHATSAPP_DB_PATH
lets this point at a real disk location once deployed (e.g. a Railway
volume); it defaults to a local file for development.

A conversation "resets" after MAX_AGE_SECONDS of silence -- old,
unrelated situations shouldn't bleed into a new one weeks later. A
person can also always start over explicitly (see chat commands in
whatsapp_bot.py).
"""
import json
import logging
import os
import sqlite3
import time

logger = logging.getLogger("whatsapp_store")

DB_PATH = os.environ.get("WHATSAPP_DB_PATH", "whatsapp_conversations.db")
MAX_AGE_SECONDS = 24 * 3600  # one day of silence resets the conversation
MAX_HISTORY_MESSAGES = 6     # how many recent turns to carry into a follow-up


def _connect():
    """CONFIRMED REAL BUG (2026-09-13): every real WhatsApp message
    started crashing with `sqlite3.OperationalError: unable to open
    database file` right after WHATSAPP_DB_PATH was pointed at the new
    Railway volume (/data/whatsapp_conversations.db). sqlite3.connect()
    auto-creates the DATABASE FILE itself if missing, but does NOT
    create missing PARENT DIRECTORIES -- this codebase's local dev
    default ("whatsapp_conversations.db", no directory component) never
    exercised that gap, so it went unnoticed until a real path with a
    directory was used for the first time. Defensive fix: ensure the
    parent directory exists before every connect. If it still fails,
    log exactly which path and directory were involved -- a bare
    "unable to open database file" with no context is what actually
    slowed down diagnosing this the first time."""
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.OperationalError:
        logger.exception(
            "Could not open DB at DB_PATH=%r (parent dir=%r, parent exists=%s, parent writable=%s)",
            DB_PATH, parent, os.path.isdir(parent) if parent else None,
            os.access(parent, os.W_OK) if parent and os.path.isdir(parent) else None,
        )
        raise
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            text TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_phone_time ON messages(phone_number, created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            question TEXT NOT NULL,
            state TEXT NOT NULL,
            confidence TEXT NOT NULL CHECK(confidence IN ('confident', 'thin', 'technical_failure', 'out_of_scope')),
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qa_confidence_time ON qa_log(confidence, created_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS draft_context (
            phone_number TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            matches_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    return conn


# ---------------------------------------------------------------------------
# The "reply DRAFT" command, added 2026-09-14: the formatter has always
# invited an arrest-shaped answer's DRAFT reply, but nothing on WhatsApp
# ever actually built one -- CONFIRMED REAL GAP, found by re-reading
# whatsapp_bot.py after shipping the answer-reuse cache. Building the
# petition needs the same `matches` chat_assistant.answer_question()
# returned for the ORIGINAL question, not the one-word "draft" reply --
# so the most recent arrest-shaped answer's context is saved here, one row
# per phone number (overwritten by each new one), and read back when
# "draft" arrives.
# ---------------------------------------------------------------------------

def save_draft_context(phone_number: str, question: str, matches: list) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO draft_context (phone_number, question, matches_json, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(phone_number) DO UPDATE SET question = excluded.question, "
                "matches_json = excluded.matches_json, created_at = excluded.created_at",
                (phone_number, question, json.dumps(matches), time.time()),
            )
    finally:
        conn.close()


def get_draft_context(phone_number: str):
    """Returns {'question', 'matches'} for the most recent arrest-shaped
    answer this phone number got, or None if there isn't one yet."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT question, matches_json FROM draft_context WHERE phone_number = ?",
            (phone_number,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {"question": row[0], "matches": json.loads(row[1])}


# ---------------------------------------------------------------------------
# The safe learning loop, part 1: quietly record how confident the engine
# was on every real question -- see memory/whatsapp-interface-technical-plan.md
# sections 3-4 for the full design and why NOT auto-learning is a deliberate
# safety choice here, not a missing feature. This never changes what the
# bot tells anyone; it only produces the raw material for
# whatsapp_weekly_report.py, which a PERSON reads to decide what's worth
# fixing -- the same "human reads the report" discipline
# eval_related_judgments.py / eval_chat_answers.py already use elsewhere
# in this project.
# ---------------------------------------------------------------------------

# A confident, real answer -- the engine found solid, sourced ground.
_CONFIDENT_STATES = {"single_match"}

# The engine itself flagged shaky ground: no real match, or several
# conflicting ones, or "related but outside what I can confidently cover."
# These are the states worth a person's attention -- real signal of a
# coverage gap, not a guess about one.
_THIN_STATES = {"adjacent_uncovered", "no_match", "conflicting_matches"}

# Not a knowledge gap -- an infrastructure hiccup (the classifier or
# retrieval call itself failed). Worth watching separately: a spike here
# means "check the API/network," not "the corpus is thin."
_TECHNICAL_FAILURE_STATES = {"classifier_unavailable", "retrieval_unavailable"}

# Everything else (unrelated, covered_elsewhere_in_tool, or any future/
# unrecognised state) -- not a legal question in this tool's scope at all,
# or already handled by a different inline path. Not a gap to fix.


def classify_confidence(state: str) -> str:
    """Maps an answer_question() state to one of four broad buckets for
    the weekly report. Deliberately coarse and rule-based -- no model
    involved in deciding what counts as "thin," same discipline as
    everything else legal-content-adjacent in this project."""
    if state in _CONFIDENT_STATES:
        return "confident"
    if state in _THIN_STATES:
        return "thin"
    if state in _TECHNICAL_FAILURE_STATES:
        return "technical_failure"
    return "out_of_scope"


def log_qa(phone_number: str, question: str, state: str) -> None:
    """Quietly records one real question and how confident the engine
    was -- nothing acted on automatically. Logs the person's own raw
    question text (not the context-prefixed version sent to the engine),
    since that's what a human reviewer actually wants to read."""
    confidence = classify_confidence(state)
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO qa_log (phone_number, question, state, confidence, created_at) VALUES (?, ?, ?, ?, ?)",
                (phone_number, question, state, confidence, time.time()),
            )
    finally:
        conn.close()


def add_message(phone_number: str, role: str, text: str) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO messages (phone_number, role, text, created_at) VALUES (?, ?, ?, ?)",
                (phone_number, role, text, time.time()),
            )
    finally:
        conn.close()


def get_recent_history(phone_number: str, *, max_messages: int = MAX_HISTORY_MESSAGES,
                        max_age_seconds: int = MAX_AGE_SECONDS) -> list:
    """Most recent messages for this phone number, oldest first.
    Anything older than max_age_seconds is treated as a different,
    expired conversation and left out."""
    conn = _connect()
    try:
        cutoff = time.time() - max_age_seconds
        rows = conn.execute(
            "SELECT role, text FROM messages WHERE phone_number = ? AND created_at >= ? "
            "ORDER BY created_at DESC LIMIT ?",
            (phone_number, cutoff, max_messages),
        ).fetchall()
    finally:
        conn.close()
    return [{"role": r[0], "text": r[1]} for r in reversed(rows)]


def clear_history(phone_number: str) -> None:
    """Explicit reset -- e.g. the person types "new question"."""
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM messages WHERE phone_number = ?", (phone_number,))
    finally:
        conn.close()


def build_question_with_context(history: list, new_message: str) -> str:
    """chat_assistant.answer_question() takes a single question string
    with no separate history parameter (confirmed 2026-09-11 -- its
    signature is answer_question(question, inline_domains=frozenset())),
    and it must stay that way: the engine itself doesn't change for
    WhatsApp. So a follow-up's context gets folded into the question
    text itself, in plain prose the same scope-classifier and
    response-generator prompts already know how to read -- no change
    needed inside chat_assistant.py for this to work."""
    if not history:
        return new_message
    lines = ["Earlier in this same conversation:"]
    for msg in history:
        speaker = "The person asked" if msg["role"] == "user" else "I answered"
        lines.append(f"- {speaker}: {msg['text']}")
    lines.append("")
    lines.append(f"Now the person says: {new_message}")
    return "\n".join(lines)
