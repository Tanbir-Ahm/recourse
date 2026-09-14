
"""
candidate_pipeline.py

Automates judgment_corroboration.py's checks (Ideas 1 + 2 from the
2026-09-14 discussion) so proposing a new judgment anchor runs them
automatically and PERSISTS every piece of evidence, instead of being
re-run by hand each time and thrown away the moment the terminal
scrolls past it.

THE ONE BOUNDARY THIS AUTOMATION MUST NEVER CROSS -- kept on purpose:
this module never writes to any *_doctrine_map.py file and never makes
a candidate live on its own. It only stages a candidate plus its
automated evidence for a PERSON to review, and records that person's
decision. Turning an APPROVED candidate into a real, trusted anchor --
picking good trigger phrases, adding the chunks/*.json file, writing
tests -- stays a separate, deliberate, reviewed code change, exactly
like every anchor added so far this project. Automating THAT step too
would mean trigger-phrase quality (a real judgment call -- see the
Velusamy lesson, where the first search phrases tried simply missed
real corroboration) and final content review stop happening, which is
exactly the "AI decides what's trustworthy" failure mode this whole
architecture exists to avoid. This module only removes the TEDIOUS
work (searching, corroborating, remembering results); it never removes
the JUDGMENT work.
"""
import json
import os
import sqlite3
import time

import judgment_corroboration

DB_PATH = os.environ.get("CANDIDATE_PIPELINE_DB_PATH", "candidate_anchors.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_name TEXT NOT NULL,
            citation TEXT,
            source_url TEXT,
            paragraph_number TEXT,
            holding_text TEXT NOT NULL,
            domain TEXT NOT NULL,
            corroboration_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
            reviewer_note TEXT,
            proposed_at REAL NOT NULL,
            decided_at REAL
        )
        """
    )
    return conn


def propose_candidate(case_name: str, citation: str, source_url: str, paragraph_number: str,
                       holding_text: str, case_title_contains: str, case_name_for_search: str,
                       key_phrase_groups: list, doctrine_keywords: list,
                       domain: str = "domestic_violence") -> int:
    """The automated version of what used to be three separate manual
    terminal commands: runs judgment_corroboration.full_corroboration_report
    (real network calls -- Indian Kanoon search + the local Vaquill pool)
    and saves the candidate plus every piece of evidence as 'pending'.
    Returns the new candidate's id. Never touches any trusted file."""
    report = judgment_corroboration.full_corroboration_report(
        case_title_contains, case_name_for_search, holding_text,
        key_phrase_groups, doctrine_keywords,
    )
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO candidates (case_name, citation, source_url, paragraph_number, "
                "holding_text, domain, corroboration_json, status, proposed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (case_name, citation, source_url, paragraph_number, holding_text, domain,
                 json.dumps(report, default=str), time.time()),
            )
            return cur.lastrowid
    finally:
        conn.close()


def _row_to_dict(row) -> dict:
    (cid, case_name, citation, source_url, paragraph_number, holding_text, domain,
     corroboration_json, status, reviewer_note, proposed_at, decided_at) = row
    return {
        "id": cid, "case_name": case_name, "citation": citation, "source_url": source_url,
        "paragraph_number": paragraph_number, "holding_text": holding_text, "domain": domain,
        "corroboration": json.loads(corroboration_json), "status": status,
        "reviewer_note": reviewer_note, "proposed_at": proposed_at, "decided_at": decided_at,
    }


def list_candidates(status: str = None, domain: str = None) -> list:
    """All staged candidates, most recent first. Optionally filtered by
    status ('pending'/'approved'/'rejected') and/or domain."""
    conn = _connect()
    try:
        sql = "SELECT * FROM candidates"
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY proposed_at DESC"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def get_candidate(candidate_id: int):
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def _decide(candidate_id: int, status: str, note: str) -> bool:
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE candidates SET status = ?, reviewer_note = ?, decided_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, note, time.time(), candidate_id),
            )
        return cur.rowcount > 0
    finally:
        conn.close()


def approve(candidate_id: int, note: str = "") -> bool:
    """Records that a PERSON approved this candidate. Does NOT make it
    live -- that still requires the separate, deliberate step of writing
    it into the real *_doctrine_map.py (see module docstring). Returns
    False if the candidate doesn't exist or was already decided."""
    return _decide(candidate_id, "approved", note)


def reject(candidate_id: int, note: str = "") -> bool:
    return _decide(candidate_id, "rejected", note)
