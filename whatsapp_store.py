
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
import os
import sqlite3
import time

DB_PATH = os.environ.get("WHATSAPP_DB_PATH", "whatsapp_conversations.db")
MAX_AGE_SECONDS = 24 * 3600  # one day of silence resets the conversation
MAX_HISTORY_MESSAGES = 6     # how many recent turns to carry into a follow-up


def _connect():
    conn = sqlite3.connect(DB_PATH)
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
    return conn


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
