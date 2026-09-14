
"""
vaquill_search.py

A self-hosted, free, wide search pool of Supreme Court judgments, sourced
from Vaquill AI's open-india-law dataset (github.com/vaquill-AI/open-india-law,
CC BY 4.0), scoped narrowly to one legal topic at a time -- NOT the whole
37,000-judgment dataset. Design discussed and agreed with the user
2026-09-14, after a critical look at what "retrieve everything, make it
searchable" would actually mean for this project.

WHY THIS STAYS SEPARATE FROM THE TRUSTED CORPUS -- the core design
decision: every judgment this tool can CITE as grounded authority has
been read and approved by a person (see memory: "Knowledge base only
grows via manual, human-reviewed git commits"). 37,000 judgments cannot
be manually verified one by one, and this dataset has two confirmed real
gaps that make that worse: no finality tag (bail/interlocutory orders
mixed with real final judgments) and no citation/case-number data at all.
Automatically deciding "which of these are trustworthy" at this scale
would mean an algorithm making the exact kind of legal judgment call
this project's entire architecture refuses to hand to anything but a
human -- see [[model-never-states-conclusion]].

So this module is NOT a new trusted knowledge source. It is a much
bigger, freely-searchable CANDIDATE POOL, meant to power the same
"related, but NOT independently verified -- read carefully" panel
(`unverified_for_display`) related_judgments.py already has for exactly
this situation. Nothing found here should ever be folded into a
confident, grounded, cited answer without a person reading it first.

SCOPE (deliberately narrow, not "all 37,000"): one topic at a time,
built via build_index(keyword_filters=[...]). First scoped topic:
domestic violence / Protection of Women from Domestic Violence Act,
2005 (see domestic_violence_doctrine_map.py). Widen to other topics
only by calling build_index again with new keywords -- never "ingest
everything" in one step.

CONFIRMED DATA GAPS (checked directly against the real dataset,
2026-09-14): `source_url` is empty for every one of the 103 domestic-
violence-scoped candidates found -- this dataset does NOT reliably let
you link back to an original judgment page the way it claims to for
some records. `ik_search_url` below is a constructed Indian Kanoon
SEARCH link (by case title), not a direct citation -- an honest,
functional substitute, never presented as a verified citation.

Storage: local SQLite with FTS5 (lexical/keyword search only -- no
embeddings for this pool, deliberately, to keep this cheap and because
lexical search is enough for a "here's what might be relevant, go read
it" pool). NOT committed to git (see .gitignore's `*.db` rule).
"""
import json
import os
import sqlite3
import urllib.parse

DB_PATH = os.environ.get("VAQUILL_SEARCH_DB_PATH", "vaquill_search.db")
VAQUILL_SC_JUDGMENTS_URL = "https://oss-data-in.vaquill.ai/v2026.08.1/in_supreme-court_judgments.parquet"

# Vaquill's own chunk-level `section_type` tags -> the closest equivalent in
# ik_triage.REASONING_STRUCTURE_TAGS's vocabulary (Analysis/Precedent/
# CDiscource/Issue/Conclusion), so classify_document_finality (built for
# Indian Kanoon's tagging scheme) can be reused UNCHANGED rather than
# rewritten for this dataset's different vocabulary -- exactly the "shape-
# shim" approach already planned for this integration.
_SECTION_TYPE_TO_IK_STRUCTURE = {
    "ratio_decidendi": "Analysis",
    "obiter_dicta": "Analysis",
    "conclusion": "Conclusion",
    # "section", "body", "paragraph" (and anything else): no specific
    # reasoning signal -- left unmapped (None), same as IK returning no tag.
}


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            case_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            court TEXT,
            decision_date TEXT,
            disposition TEXT,
            is_procedural_order INTEGER,
            has_reasoning_structure INTEGER,
            disposal_markers TEXT NOT NULL,
            ik_search_url TEXT NOT NULL,
            n_chunks INTEGER NOT NULL,
            topic TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(case_id UNINDEXED, title, full_text)"
    )
    return conn


def _ik_search_url(title: str) -> str:
    return "https://indiankanoon.org/search/?formInput=" + urllib.parse.quote(title)


def _tri_to_int(value):
    if value is None:
        return None
    return 1 if value else 0


def build_index(keyword_filters: list, topic: str, limit_judgments: int = None) -> dict:
    """Queries the real, remote Vaquill parquet (no download, no local
    copy of the raw dataset) for judgments whose text matches ANY of
    keyword_filters, pulls their full chunked text, runs the SAME
    procedural-order detector the rest of this project already trusts,
    and stores the result locally under `topic`. Real network calls,
    can take several minutes (the dataset is 3.5GB, queried remotely).

    Returns a summary dict for a human to read before trusting anything
    this added -- this function only POPULATES the searchable pool, it
    never changes what any real user is told."""
    import duckdb
    from ik_triage import classify_document_finality

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")

    where_clause = " OR ".join(f"text ILIKE '%{kw}%'" for kw in keyword_filters)
    candidates = con.execute(
        f"""
        SELECT case_id, any_value(title), any_value(disposition),
               any_value(decision_date), any_value(court), count(*)
        FROM read_parquet('{VAQUILL_SC_JUDGMENTS_URL}')
        WHERE {where_clause}
        GROUP BY case_id
        """
    ).fetchall()
    if limit_judgments:
        candidates = candidates[:limit_judgments]

    case_ids = [c[0] for c in candidates]
    meta_by_id = {c[0]: c for c in candidates}

    placeholders = ", ".join(f"'{cid}'" for cid in case_ids)
    chunk_rows = con.execute(
        f"""
        SELECT case_id, chunk_index, text, section_type
        FROM read_parquet('{VAQUILL_SC_JUDGMENTS_URL}')
        WHERE case_id IN ({placeholders})
        ORDER BY case_id, chunk_index
        """
    ).fetchall()

    chunks_by_case = {}
    for case_id, chunk_index, text, section_type in chunk_rows:
        chunks_by_case.setdefault(case_id, []).append((chunk_index, text, section_type))

    conn = _connect()
    inserted = 0
    procedural_count = 0
    unknown_finality_count = 0
    try:
        with conn:
            for case_id in case_ids:
                chunks = sorted(chunks_by_case.get(case_id, []))
                full_text = "\n\n".join(text for _, text, _ in chunks if text)
                paragraphs = [
                    {"text": text, "structure": _SECTION_TYPE_TO_IK_STRUCTURE.get(section_type)}
                    for _, text, section_type in chunks
                ]
                finality = classify_document_finality(paragraphs)
                if finality["is_procedural_order"]:
                    procedural_count += 1
                if finality["has_reasoning_structure"] is None:
                    unknown_finality_count += 1

                _, title, disposition, decision_date, court, n_chunks = meta_by_id[case_id]
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (case_id, title, court, decision_date, disposition, "
                    "is_procedural_order, has_reasoning_structure, disposal_markers, ik_search_url, "
                    "n_chunks, topic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        case_id, title, court, str(decision_date), disposition,
                        _tri_to_int(finality["is_procedural_order"]),
                        _tri_to_int(finality["has_reasoning_structure"]),
                        json.dumps(finality["disposal_markers"]),
                        _ik_search_url(title), n_chunks, topic,
                    ),
                )
                conn.execute("DELETE FROM fts WHERE case_id = ?", (case_id,))
                conn.execute("INSERT INTO fts (case_id, title, full_text) VALUES (?, ?, ?)",
                             (case_id, title, full_text))
                inserted += 1
    finally:
        conn.close()

    return {
        "topic": topic, "judgments_found": len(case_ids), "judgments_stored": inserted,
        "flagged_procedural": procedural_count, "unknown_finality": unknown_finality_count,
    }


def search(query: str, topic: str = None, top_k: int = 5) -> list:
    """Lexical (FTS5) search over the locally-built pool. Returns
    candidates shaped for the SAME review/display path
    unverified_for_display already uses -- never auto-trusted, always
    carries `source='vaquill'` and its own finality flag so the existing
    'read carefully' framing applies. Empty list if nothing is built yet
    (never crashes on a fresh/empty database)."""
    conn = _connect()
    try:
        fts_query = " OR ".join(f'"{w}"' for w in query.split() if w.strip())
        if not fts_query:
            return []
        sql = (
            "SELECT m.case_id, m.title, m.court, m.decision_date, m.disposition, "
            "m.is_procedural_order, m.disposal_markers, m.ik_search_url, fts.full_text "
            "FROM fts JOIN metadata m ON m.case_id = fts.case_id "
            "WHERE fts MATCH ?"
        )
        params = [fts_query]
        if topic:
            sql += " AND m.topic = ?"
            params.append(topic)
        sql += " ORDER BY rank LIMIT ?"
        params.append(top_k)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [
        {
            "source": "vaquill",
            "case_name": r[1],
            "court": r[2],
            "decision_date": r[3],
            "disposition": r[4],
            "procedural_disposal": bool(r[5]) if r[5] is not None else None,
            "disposal_markers": json.loads(r[6]),
            "ik_search_url": r[7],
            "text": r[8],
        }
        for r in rows
    ]
