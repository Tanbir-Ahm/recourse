"""
case_lookup.py -- "type a case name, get the judgment" for the WhatsApp bot.

DESIGN (agreed 2026-09-16, see memory/case-lookup-whatsapp-feature-design.md):
a plain command (never AI-classified), a free search over a small LOCAL
title index, and a live fetch of the full text of the ONE case the person
confirms, straight from Vaquill's open dataset (CC BY 4.0, no per-call
cost -- unlike the paid Indian Kanoon API).

PHASE 1 SCOPE: Supreme Court only. Verified live 2026-09-18: a remote
title scan of the SC file alone takes ~8s, so scanning 26 court files per
request would be far too slow -- instead a title-only index (a few tens of
thousands of rows) is built ONCE by build_index() and searched locally;
only the full-text fetch for the chosen case goes remote. High Courts are
a later phase, decided by measurement, not assumed.

THIS IS NOT A TRUSTED-TIER SOURCE. Nobody has hand-verified this dataset;
citations and source links are missing for some records (a confirmed data
gap). Everything delivered from here must carry the "retrieved from an open
dataset, not independently verified" disclaimer inside the document itself
(see case_document.py) -- a PDF outlives the chat that produced it.

Every failure mode here is honest and non-fatal: callers get an exception
type they can turn into a plain sentence, never a crash and never a guess.
"""
import json
import logging
import math
import os
import re
import sqlite3
import time

logger = logging.getLogger(__name__)

# TWO databases, deliberately. The INDEX (cases, cases_fts, doc_bundle) holds only
# public court data, is built/refreshed by a person, and is committed to git so it
# ships with every deploy (see the .gitignore exception). The STATE file (fetch
# cache, pending menus, rate-limit log) is written by the running server -- it
# contains phone numbers, so it must never be committed and lives on the
# persistent volume (point CASE_LOOKUP_STATE_PATH into it, set via PowerShell --
# Git Bash mangles a leading "/").
INDEX_PATH = os.environ.get("CASE_LOOKUP_INDEX_PATH", "case_lookup_index.db")
STATE_PATH = os.environ.get("CASE_LOOKUP_STATE_PATH", "case_lookup_state.db")

MAX_CHOICES = 5
CHOICES_TTL_SECONDS = 10 * 60
DOC_MIN_CHARS = 300
# Per phone number, per rolling 24h. Vaquill costs no money, but every
# fetch costs real bandwidth/time on a single small container.
SEARCH_DAILY_LIMIT = int(os.environ.get("CASE_LOOKUP_SEARCH_LIMIT", "40"))
FETCH_DAILY_LIMIT = int(os.environ.get("CASE_LOOKUP_FETCH_LIMIT", "15"))

_STOPWORDS = {"v", "vs", "versus", "the", "of", "and", "anr", "ors", "another", "others"}


class CaseLookupError(Exception):
    """Base class -- every failure here is one the caller can phrase plainly."""


class IndexNotBuilt(CaseLookupError):
    """The local title index doesn't exist yet (build_index() never ran)."""


class CaseNotFound(CaseLookupError):
    """The remote dataset returned nothing for a case_id that was in the index."""


class CaseLookupUnavailable(CaseLookupError):
    """The remote dataset could not be reached (network / DuckDB error)."""


def _open(path: str):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return sqlite3.connect(path, timeout=5.0)


_DOC_COLUMNS = """case_id TEXT PRIMARY KEY, text TEXT NOT NULL, complete INTEGER,
            is_procedural INTEGER, n_chunks INTEGER, expected_chunks INTEGER,
            warnings_json TEXT, fetched_at REAL"""


# The runtime cache table is versioned: copies saved by the older, un-cleaned code sit in
# 'doc_cache' and are simply never read again, so every case is re-fetched once and cleaned.
# Bump the suffix whenever the cleaning changes what a saved copy should contain.
_CACHE_TABLE = "doc_cache_v3"   # v2 = first cleaning; v3 = + margin letters before capitalised words


def _index_conn():
    conn = _open(INDEX_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY, title TEXT NOT NULL, petitioner TEXT,
            respondent TEXT, court TEXT, decision_date TEXT, citation TEXT,
            source_url TEXT, n_chunks INTEGER, source TEXT)"""
    )
    # 'source' marks where a catalogue row came from: NULL = the original Vaquill catalogue (re-typed text
    # available); 'bucket' = added from the open bucket's own case list (original PDF only). A catalogue file
    # built before this column existed gains it on open.
    if "source" not in [r[1] for r in conn.execute("PRAGMA table_info(cases)")]:
        try:
            conn.execute("ALTER TABLE cases ADD COLUMN source TEXT")
        except sqlite3.OperationalError:
            pass
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts USING fts5(case_id UNINDEXED, title)")
    # Judgments pre-fetched by a person in ONE batch pass (see prewarm) so the
    # cases people actually ask for are instant instead of a ~30-50s remote fetch.
    conn.execute(f"CREATE TABLE IF NOT EXISTS doc_bundle ({_DOC_COLUMNS})")
    return conn


def _state_conn():
    conn = _open(STATE_PATH)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} ({_DOC_COLUMNS})")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS pending_choices (
            phone_number TEXT PRIMARY KEY, choices_json TEXT NOT NULL,
            fmt TEXT, created_at REAL)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS lookup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, phone_number TEXT NOT NULL,
            kind TEXT NOT NULL, created_at REAL NOT NULL)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lookup_log ON lookup_log(phone_number, kind, created_at)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, phone_number TEXT NOT NULL, event TEXT NOT NULL,
            case_id TEXT, query TEXT, detail TEXT, elapsed_ms INTEGER, cached INTEGER, created_at REAL NOT NULL)"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_events_time ON case_events(created_at)")
    return conn


# ---------------------------------------------------------------------------
# Index: built once, offline, by a person -- never in a user's request path
# ---------------------------------------------------------------------------

def _duckdb():
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET enable_progress_bar=false")
    # Bounded on purpose: this runs on a small shared container (and a
    # dev laptop that has already had heavy background jobs killed for
    # memory) -- spill/slow down rather than take the whole process down.
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=2")
    return con


def build_index(limit=None) -> dict:
    """Pulls one metadata row per Supreme Court case (title, parties,
    court, date, citation, source link, chunk count -- NO judgment text)
    from Vaquill's remote parquet into the local SQLite title index.
    Real network scan of a ~3.5GB remote file: run by a person, minutes,
    never per-request. Idempotent -- re-running refreshes rows in place."""
    from vaquill_search import VAQUILL_SC_JUDGMENTS_URL as url

    # Every case is stored ONCE PER LANGUAGE (en, hin, mar, ori, pun, tam ... --
    # the Supreme Court's vernacular translations, some badly OCR'd), each with
    # its own chunk numbering. Only English is ever indexed or fetched: mixing
    # them produced interleaved garbage plus chunk counts inflated ~4x.
    sql = (
        "SELECT case_id, any_value(title) FILTER (WHERE language_code = 'en'), "
        "any_value(petitioner) FILTER (WHERE language_code = 'en'), "
        "any_value(respondent) FILTER (WHERE language_code = 'en'), "
        "any_value(court), any_value(decision_date), any_value(citation), "
        "any_value(source_url), count(*) FILTER (WHERE language_code = 'en') AS n_en "
        f"FROM read_parquet('{url}') GROUP BY case_id HAVING n_en > 0"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = _duckdb().execute(sql).fetchall()

    conn = _index_conn()
    inserted = 0
    try:
        with conn:
            for cid, title, pet, res, court, date, cit, src, n in rows:
                if not cid or not title:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO cases (case_id, title, petitioner, respondent, court, "
                    "decision_date, citation, source_url, n_chunks) VALUES (?,?,?,?,?,?,?,?,?)",
                    (cid, title, pet, res, court, str(date) if date else None, cit, src, n),
                )
                conn.execute("DELETE FROM cases_fts WHERE case_id = ?", (cid,))
                conn.execute("INSERT INTO cases_fts (case_id, title) VALUES (?, ?)", (cid, title))
                inserted += 1
    finally:
        conn.close()
    return {"cases_found": len(rows), "cases_indexed": inserted}


def index_size() -> int:
    conn = _index_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _tokens(query: str) -> list:
    """Alphanumeric words only. Anything else (quotes, commas, FTS5
    operators like * : - ( ) ) is dropped BEFORE it can reach a MATCH
    string, so no user text can ever produce an FTS5 syntax error --
    a fragility vaquill_search.search() has (it quotes whole
    whitespace-split words, so punctuation glued to a word survives).
    Single letters are KEPT: "D.K. Basu" and "K.S. Puttaswamy" are found
    by their initials, and the any-word fallback covers a query that
    leaves them out."""
    return [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if w not in _STOPWORDS]


# Indian case titles abbreviate inconsistently ("STATE OF U.P." vs "STATE OF UTTAR
# PRADESH", "GOVT." vs "GOVERNMENT"), so a person typing the long form would
# otherwise miss the very case they named. FTS5 splits "U.P." into the words
# "u" and "p", so the abbreviation is the two-word phrase "u p".
_ALIASES = [("uttar pradesh", "u p"), ("madhya pradesh", "m p"), ("andhra pradesh", "a p"),
            ("himachal pradesh", "h p"), ("government", "govt")]
_CANON = [("uttar pradesh", "up"), ("u p", "up"), ("madhya pradesh", "mp"), ("m p", "mp"),
          ("andhra pradesh", "ap"), ("a p", "ap"), ("himachal pradesh", "hp"), ("h p", "hp"),
          ("govt", "government")]


def _alias_groups(text: str):
    """(remaining_tokens, groups): every alias phrase found in the query is
    pulled out and returned as a pair of alternative spellings, so the
    exact search can accept either one."""
    low = " " + " ".join(_tokens(text)) + " "
    groups = []
    for a, b in _ALIASES:
        for x, y in ((a, b), (b, a)):
            if f" {x} " in low:
                low = low.replace(f" {x} ", " ", 1)
                groups.append((x, y))
                break
    return low.split(), groups


def _phrase_expr(phrase: str) -> str:
    return "(" + " AND ".join(f'"{w}"' for w in phrase.split()) + ")"


def _canon_tokens(text: str) -> list:
    """Tokens with the alias spellings collapsed to one form, used to
    compare a query against a title when scoring fuzzy matches."""
    s = " " + " ".join(_tokens(text)) + " "
    for a, b in _CANON:
        s = s.replace(f" {a} ", f" {b} ")
    return s.split()


def _row_to_case(r) -> dict:
    return {
        "case_id": r[0], "title": r[1], "court": r[2], "decision_date": r[3],
        "citation": r[4], "source_url": r[5], "n_chunks": r[6], "source": r[7] if len(r) > 7 else None,
    }


def search_cases_detailed(query: str, limit: int = MAX_CHOICES) -> dict:
    """{"cases": [...], "exact": bool}. exact=True means EVERY query word
    appears in each title. exact=False means the closest matches by a
    relaxed any-word search -- kept only if a title matches at least 60%
    of the query's words (and at least 2), so 'Lata Singh v State of
    Uttar Pradesh' still finds 'LATA SINGH v STATE OF U.P.' but a single
    shared surname does not. A caller must NEVER auto-deliver a
    non-exact result: a lookalike sent as if it were the case asked for
    is the worst failure this feature can have."""
    toks = _tokens(query)
    if not toks:
        return {"cases": [], "exact": True}
    rest, groups = _alias_groups(query)
    and_expr = " AND ".join([f'"{t}"' for t in rest] + [
        "(" + _phrase_expr(x) + " OR " + _phrase_expr(y) + ")" for x, y in groups])
    conn = _index_conn()
    try:
        if conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0:
            raise IndexNotBuilt("case title index is empty -- build_index() has not been run")
        cols = ("SELECT c.case_id, c.title, c.court, c.decision_date, c.citation, c.source_url, c.n_chunks, c.source "
                "FROM cases_fts f JOIN cases c ON c.case_id = f.case_id WHERE cases_fts MATCH ? ")
        # Every word matched: title length says nothing about relevance, so prefer
        # the fuller record (a landmark judgment over a one-page order).
        rows = conn.execute(
            cols + "ORDER BY c.n_chunks DESC, c.decision_date DESC LIMIT ?", (and_expr, limit),
        ).fetchall()
        if rows or len(toks) < 2:
            return {"cases": [_row_to_case(r) for r in rows], "exact": True}
        qcanon = list(dict.fromkeys(_canon_tokens(query)))
        need = max(2, math.ceil(0.6 * len(qcanon)))
        any_words = list(dict.fromkeys(rest + [w for x, y in groups for w in (x + " " + y).split()]))
        cands = conn.execute(
            cols + "ORDER BY bm25(cases_fts) LIMIT 80",
            (" OR ".join(f'"{w}"' for w in any_words),),
        ).fetchall()
    finally:
        conn.close()
    qset, scored = set(qcanon), []
    for r in cands:
        hits = len(qset & set(_canon_tokens(r[1])))
        if hits >= need:
            scored.append((hits, r[6] or 0, r))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return {"cases": [_row_to_case(x[2]) for x in scored[:limit]], "exact": False}


def search_cases(query: str, limit: int = MAX_CHOICES) -> list:
    return search_cases_detailed(query, limit)["cases"]


def get_case(case_id: str):
    conn = _index_conn()
    try:
        r = conn.execute(
            "SELECT case_id, title, court, decision_date, citation, source_url, n_chunks, source "
            "FROM cases WHERE case_id = ?", (case_id,),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_case(r) if r else None


# ---------------------------------------------------------------------------
# Fetch the ONE confirmed case's full text (+ sanity checks + cache)
# ---------------------------------------------------------------------------

def _row_to_doc(case_id, r):
    return {
        "case_id": case_id, "text": r[0], "complete": bool(r[1]),
        "is_procedural": None if r[2] is None else bool(r[2]),
        "n_chunks": r[3], "expected_chunks": r[4],
        "warnings": json.loads(r[5] or "[]"), "from_cache": True,
    }


_DOC_SELECT = ("SELECT text, complete, is_procedural, n_chunks, expected_chunks, warnings_json "
               "FROM {table} WHERE case_id = ?")


def _cache_get(case_id: str):
    """Runtime cache first, then the pre-warmed bundle that ships with the index."""
    for opener, table in ((_state_conn, _CACHE_TABLE), (_index_conn, "doc_bundle")):
        conn = opener()
        try:
            r = conn.execute(_DOC_SELECT.format(table=table), (case_id,)).fetchone()
        finally:
            conn.close()
        if r:
            return _row_to_doc(case_id, r)
    return None


def _cache_put(doc: dict) -> None:
    conn = _state_conn()
    try:
        with conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {_CACHE_TABLE} (case_id, text, complete, is_procedural, n_chunks, "
                "expected_chunks, warnings_json, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                (doc["case_id"], doc["text"], int(doc["complete"]),
                 None if doc["is_procedural"] is None else int(doc["is_procedural"]),
                 doc["n_chunks"], doc["expected_chunks"], json.dumps(doc["warnings"]), time.time()),
            )
    finally:
        conn.close()


_CHUNK_HEADER_RE = re.compile(r"\A\s*Case:[^\n]*\n\s*Section:[^\n]*\n?")
_MARKER_RE = re.compile(r"(?m)^\[(?:TITLE|SECTION|[A-Z_]+)\][ \t]*#{0,6}[ \t]*")


def clean_chunk_text(text: str) -> str:
    """Removes ONLY structure the dataset pipeline added around the
    judgment, never the judgment's own words: the per-chunk
    'Case: ... / Section: ...' header, '[TITLE] #' / '[SECTION] ##'
    markers, and stray one-letter lines (reporter margin letters A-H and
    OCR specks). Lone roman numerals I/V/X are kept -- they can be real
    headings."""
    t = _CHUNK_HEADER_RE.sub("", text or "")
    t = _MARKER_RE.sub("", t)
    kept = [ln for ln in t.split("\n")
            if not (len(ln.strip()) == 1 and ln.strip().isalpha() and ln.strip() not in "IVX")]
    return "\n".join(kept).strip()


# ---------------------------------------------------------------------------
# Legibility cleaning. The source stores each judgment as OVERLAPPING pieces (the tail of one
# piece is repeated at the start of the next), printed-report MARGIN LETTERS (A-H) that the scan
# left inside sentences, and one paragraph per printed LINE. Measured 2026-09-20 on Rakesh Kumar
# Paul v State of Assam: 49 repeated paragraphs, 189 stray letters, 525 paragraphs where ~375 are
# real. This removes ONLY that debris. It never rewrites the judgment's own words -- scan errors
# such as 'Jn' for 'In' are left as they are, on purpose.
# ---------------------------------------------------------------------------

CLEANING_MIN_OVERLAP_CHARS = 30      # a shorter repeat is coincidence, not an overlap
CLEANING_MAX_REMOVED_FRACTION = 0.4  # removing more than this means something is wrong: keep the raw text

# A capital letter A-H after one of these words is the judgment's own text ("accused A", "Schedule C",
# "A and B"), never a page-margin letter. Keeping a genuine margin letter is a harmless blemish;
# deleting a real party label would change the meaning -- so when in doubt, keep.
_MARGIN_KEEP_AFTER = frozenset({
    "accused", "co-accused", "witness", "petitioner", "respondent", "appellant", "defendant", "plaintiff",
    "complainant", "victim", "deceased", "person", "party", "prosecutrix", "pw", "dw", "mr", "mrs", "ms",
    "dr", "shri", "smt", "schedule", "form", "part", "annexure", "annex", "exhibit", "list", "appendix",
    "category", "class", "group", "clause", "sub-clause", "article", "section", "column", "table", "point",
    "item", "plan", "block", "type", "grade", "para", "paragraph", "chapter", "rule", "order", "entry",
    "serial", "tier", "option", "plot", "house", "flat", "unit", "lot", "zone", "ward", "wing", "stage",
    "phase", "step", "and", "or", "nor", "either", "neither", "between", "v", "vs",
})
_MARGIN_RUN_RE = re.compile(r"(?<=[a-z,;)]) ((?:[A-H] )+)(?=[a-z(])")
_MARGIN_TRAIL_RE = re.compile(r"(?<=[a-z,;·]) [A-H]\s*$")
_LEADING_MARGIN_RE = re.compile(r"^[A-H] (?=[a-z(])")
_TERMINAL_RE = re.compile(r"[.?!:;\]\)\"'”’]\s*$")
_LIST_MARKER_RE = re.compile(r"^\((?:[a-z]{1,4}|\d+)\)")


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _prev_word(text: str) -> str:
    words = text.split()
    return words[-1].lower().strip(".,;()") if words else ""


# A margin letter can also sit before a CAPITALISED word ("the First G Information Report"). That
# looks like a person's initial ("Ram B Singh") or a real word ("(3) A Magistrate ..."), so it is
# removed only when it FITS THE PAGE'S MARGIN SEQUENCE: the letters run A..H down each printed page,
# so it must be the same/next/next-but-one letter after one already CONFIRMED as a margin letter
# (one between lowercase words), within ~1500 characters. 'A' is also a real word, so it is only
# accepted straight after a lowercase letter. Anything that fails a test is kept.
_MARGIN_ANY_RE = re.compile(
    r"(?<=[a-z,;)]) ((?:[A-H] )+)(?=[a-z(])"            # confirmed: between lowercase words
    r"|(?<=[A-Za-z,;]) ([A-H]) (?=[A-Z][a-z]{2,})"      # candidate: before a Capitalised word
)
MARGIN_SEQUENCE_WINDOW_CHARS = 1500


def _strip_margin_letters(p: str, state: dict = None, offset: int = 0) -> str:
    """state = {"last": (letter_ordinal, position)} shared across the paragraphs of one judgment."""
    state = state if state is not None else {}

    def run(m):
        prev = _prev_word(m.string[:m.start()])
        if prev in _MARGIN_KEEP_AFTER:
            return m.group(0)
        pos = offset + m.start()
        if m.group(1) is not None:                       # confirmed margin letter(s)
            state["last"] = (ord(m.group(1).split()[-1]) - 65, pos)
            return " "
        letter = m.group(2)
        before = m.string[m.start() - 1:m.start()]
        if letter == "A" and not before.islower():
            return m.group(0)
        last = state.get("last")
        if last and pos - last[1] <= MARGIN_SEQUENCE_WINDOW_CHARS and ((ord(letter) - 65 - last[0]) % 8) in (0, 1, 2):
            state["last"] = (ord(letter) - 65, pos)
            return " "
        return m.group(0)

    p = _MARGIN_ANY_RE.sub(run, p)
    m = _MARGIN_TRAIL_RE.search(p)
    if m and _prev_word(p[:m.start()]) not in _MARGIN_KEEP_AFTER:
        state["last"] = (ord(p[m.start() + 1:].strip()[:1] or "A") - 65, offset + m.start())
        p = p[:m.start()]
    return p


def _merge_overlaps(chunks: list) -> list:
    """Paragraph list with the repeated seam between consecutive pieces removed."""
    out = []
    for ch in chunks:
        paras = [p for p in re.split(r"\n\s*\n", ch) if p.strip()]
        if out and paras:
            done = False
            for j in range(min(8, len(out), len(paras)), 0, -1):
                if [_norm_ws(p) for p in out[-j:]] == [_norm_ws(p) for p in paras[:j]]:
                    paras, done = paras[j:], True
                    break
            if not done:
                last, first = _norm_ws(out[-1]), _norm_ws(paras[0])
                for k in range(min(len(last), len(first)), CLEANING_MIN_OVERLAP_CHARS - 1, -1):
                    if last.endswith(first[:k]):
                        paras[0] = first[k:]
                        break
        out.extend(p for p in paras if p.strip())
    return out


RUNNING_HEADER_MIN_REPEATS = 5


def _running_headers(paras: list) -> set:
    """The law report prints the case name at the top of EVERY page; the scan keeps those lines.
    A short, mostly-capitals (or bracket-ending) line repeated 5+ times is that header, not text."""
    counts = {}
    for p in paras:
        n = _norm_ws(p)
        counts[n] = counts.get(n, 0) + 1
    heads = set()
    for n, k in counts.items():
        if k >= RUNNING_HEADER_MIN_REPEATS and 25 <= len(n) <= 250:
            letters = [ch for ch in n if ch.isalpha()]
            if letters and (sum(ch.isupper() for ch in letters) / len(letters) > 0.5 or n.endswith("]")):
                heads.add(n)
    return heads


def _is_heading(p: str) -> bool:
    s = p.strip()
    return s.endswith(":") or (len(s) < 80 and s.upper() == s and any(c.isalpha() for c in s))


def _unfinished(p: str) -> bool:
    return bool(p.strip()) and not _is_heading(p) and not _TERMINAL_RE.search(p)


def clean_judgment_text(chunk_texts: list, with_note: bool = False):
    """Readable text from a judgment's pieces (see the block comment above). With
    with_note=True returns (text, note); note is None unless the safety net fired: if cleaning
    would remove more than CLEANING_MAX_REMOVED_FRACTION of the text, the raw joined text is
    returned instead and the note says so -- a judgment is never silently gutted."""
    pieces = [c for c in (clean_chunk_text(t) for t in chunk_texts) if c]
    raw = "\n\n".join(pieces)
    out = []
    merged = _merge_overlaps(pieces)
    heads = _running_headers(merged)
    seq, offset = {}, 0
    for p in merged:
        if _norm_ws(p) in heads:
            continue
        p = _strip_margin_letters(p, seq, offset).strip()
        offset += len(p) + 2
        if not p:
            continue
        if out and _unfinished(out[-1]):
            m = _LEADING_MARGIN_RE.match(p)
            if m and _prev_word(out[-1]) not in _MARGIN_KEEP_AFTER:
                seq["last"] = (ord(p[0]) - 65, offset)
                p = p[m.end():]
            if p[:1].islower() or (p[:1] == "(" and not _LIST_MARKER_RE.match(p)):
                out[-1] = out[-1].rstrip() + " " + p
                continue
        out.append(p)
    text = "\n\n".join(out)
    note = None
    if raw and len(text) < (1 - CLEANING_MAX_REMOVED_FRACTION) * len(raw):
        note = "cleaning skipped: it would have removed an unusually large share of the text"
        text = raw
    return (text, note) if with_note else text


def assemble_case(case_id: str, rows: list) -> dict:
    """rows: [(chunk_index, text, section_type, total_chunks), ...] for
    ONE language (English), in any order. Reassembles by chunk_index,
    cleans dataset markup, and runs the honest checks: a judgment with
    missing chunks or almost no text is flagged incomplete (still
    returned, so the caller can decide -- never silently 'fixed')."""
    from ik_triage import classify_document_finality
    from vaquill_search import _SECTION_TYPE_TO_IK_STRUCTURE

    rows = sorted(rows, key=lambda r: r[0])
    warnings = []
    text, clean_note = clean_judgment_text([r[1] for r in rows], with_note=True)
    if clean_note:
        warnings.append(clean_note)
    expected = max((r[3] or 0 for r in rows), default=0)
    have = len({r[0] for r in rows})
    complete = True
    if expected and have < expected:
        complete = False
        warnings.append(f"only {have} of {expected} parts of this record were available")
    if len(text) < DOC_MIN_CHARS:
        complete = False
        warnings.append("the record contains very little text")

    finality = classify_document_finality(
        [{"text": r[1], "structure": _SECTION_TYPE_TO_IK_STRUCTURE.get(r[2])} for r in rows]
    )
    return {
        "case_id": case_id, "text": text, "complete": complete,
        "is_procedural": finality["is_procedural_order"],
        "n_chunks": have, "expected_chunks": expected, "warnings": warnings,
        "from_cache": False,
    }


def fetch_case_text(case_id: str, *, use_cache: bool = True) -> dict:
    """Full English text of one case by id: local cache / pre-warmed bundle
    first, else one live remote query. MEASURED 2026-09-18: a remote fetch
    costs ~30-50s (sometimes far more) whatever the case's size -- a case's
    chunks are scattered across the whole file and no column has usable
    statistics, so nothing can be skipped. That is why results are cached
    and popular cases are pre-warmed. Raises CaseLookupUnavailable /
    CaseNotFound -- never returns a guess."""
    if use_cache:
        hit = _cache_get(case_id)
        if hit:
            return hit
    from vaquill_search import VAQUILL_SC_JUDGMENTS_URL as url
    try:
        rows = _duckdb().execute(
            "SELECT chunk_index, text, section_type, total_chunks "
            f"FROM read_parquet('{url}') WHERE case_id = ? AND language_code = 'en' ORDER BY chunk_index",
            [case_id],
        ).fetchall()
    except Exception as exc:
        logger.warning("case_lookup: remote fetch for %s failed: %s", case_id, exc)
        raise CaseLookupUnavailable(str(exc)) from exc
    if not rows:
        raise CaseNotFound(case_id)
    doc = assemble_case(case_id, rows)
    if doc["complete"]:
        _cache_put(doc)  # never cache a broken record -- a retry may fetch it whole
    return doc


def prewarm(case_ids: list, *, write: bool = False) -> list:
    """Fetch MANY judgments in ONE remote pass (the cost is one scan of the
    file however many cases are asked for) and store the complete ones in
    the shipped doc_bundle, so the cases people actually look up are
    instant. Run by a person, never per-request. write=False only reports
    what it would store (a person reviews the list first)."""
    from vaquill_search import VAQUILL_SC_JUDGMENTS_URL as url
    ids = list(dict.fromkeys(case_ids))
    if not ids:
        return []
    try:
        rows = _duckdb().execute(
            "SELECT case_id, chunk_index, text, section_type, total_chunks "
            f"FROM read_parquet('{url}') WHERE language_code = 'en' AND case_id IN (SELECT unnest(?))",
            [ids],
        ).fetchall()
    except Exception as exc:
        raise CaseLookupUnavailable(str(exc)) from exc
    by_case = {}
    for cid, *rest in rows:
        by_case.setdefault(cid, []).append(tuple(rest))
    report, conn = [], _index_conn()
    try:
        for cid in ids:
            if cid not in by_case:
                report.append({"case_id": cid, "stored": False, "reason": "not found"})
                continue
            doc = assemble_case(cid, by_case[cid])
            if not doc["complete"]:
                report.append({"case_id": cid, "stored": False, "reason": "; ".join(doc["warnings"])})
                continue
            if write:
                with conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO doc_bundle (case_id, text, complete, is_procedural, n_chunks, "
                        "expected_chunks, warnings_json, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                        (cid, doc["text"], 1, None if doc["is_procedural"] is None else int(doc["is_procedural"]),
                         doc["n_chunks"], doc["expected_chunks"], json.dumps(doc["warnings"]), time.time()),
                    )
            report.append({"case_id": cid, "stored": write, "chars": len(doc["text"]), "chunks": doc["n_chunks"]})
    finally:
        conn.close()
    return report


# ---------------------------------------------------------------------------
# Per-phone state: pending numbered choices, and the daily rate limit
# ---------------------------------------------------------------------------

def save_choices(phone_number: str, choices: list, fmt: str = "pdf") -> None:
    conn = _state_conn()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO pending_choices (phone_number, choices_json, fmt, created_at) "
                "VALUES (?,?,?,?)",
                (phone_number, json.dumps([c["case_id"] for c in choices]), fmt, time.time()),
            )
    finally:
        conn.close()


def get_choices(phone_number: str, ttl: int = CHOICES_TTL_SECONDS):
    """(case_ids, fmt) if this phone has an unexpired pending menu, else None."""
    conn = _state_conn()
    try:
        r = conn.execute(
            "SELECT choices_json, fmt, created_at FROM pending_choices WHERE phone_number = ?",
            (phone_number,),
        ).fetchone()
    finally:
        conn.close()
    if not r or time.time() - r[2] > ttl:
        return None
    return json.loads(r[0]), r[1]


def clear_choices(phone_number: str) -> None:
    conn = _state_conn()
    try:
        with conn:
            conn.execute("DELETE FROM pending_choices WHERE phone_number = ?", (phone_number,))
    finally:
        conn.close()


def check_and_record(phone_number: str, kind: str) -> bool:
    """True (and records the use) if this phone is still under today's cap
    for `kind` ('search' or 'fetch'); False if it has hit it."""
    limit = SEARCH_DAILY_LIMIT if kind == "search" else FETCH_DAILY_LIMIT
    cutoff = time.time() - 24 * 3600
    conn = _state_conn()
    try:
        used = conn.execute(
            "SELECT COUNT(*) FROM lookup_log WHERE phone_number = ? AND kind = ? AND created_at >= ?",
            (phone_number, kind, cutoff),
        ).fetchone()[0]
        if used >= limit:
            return False
        with conn:
            conn.execute(
                "INSERT INTO lookup_log (phone_number, kind, created_at) VALUES (?,?,?)",
                (phone_number, kind, time.time()),
            )
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Usage log: one row per CASE interaction, so the feature can be measured
# ---------------------------------------------------------------------------

QUERY_LOG_CHARS = 80  # a typed query is stored truncated -- a long message can't be kept whole


def log_event(phone_number: str, event: str, *, case_id=None, query=None, detail=None,
              elapsed_ms=None, cached=None) -> None:
    """Record what just happened in a CASE interaction. FAIL-OPEN by design: a
    logging failure must never break or slow the person's real answer, so every
    error is swallowed (and logged to the server log) instead of raised."""
    try:
        conn = _state_conn()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO case_events (phone_number, event, case_id, query, detail, elapsed_ms, cached, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (phone_number, event, case_id, (query or None) and query[:QUERY_LOG_CHARS], detail, elapsed_ms,
                     None if cached is None else int(bool(cached)), time.time()),
                )
        finally:
            conn.close()
    except Exception:
        logger.exception("case_lookup: could not log event %r (ignored -- logging never blocks a reply)", event)


def event_summary(days: int = 7) -> dict:
    """Aggregate counts for a person to read. NEVER returns a phone number --
    only how many distinct people there were."""
    cutoff = time.time() - days * 86400
    conn = _state_conn()
    try:
        rows = conn.execute(
            "SELECT phone_number, event, elapsed_ms, cached FROM case_events WHERE created_at >= ?", (cutoff,)
        ).fetchall()
    finally:
        conn.close()
    by_event = {}
    for _, ev, _, _ in rows:
        by_event[ev] = by_event.get(ev, 0) + 1
    delivered = [r for r in rows if r[1] == "doc_delivered"]
    live_ms = sorted(r[2] for r in delivered if r[2] is not None and not r[3])
    return {
        "days": days,
        "total": len(rows),
        "users": len({r[0] for r in rows}),
        "by_event": by_event,
        "deliveries": len(delivered),
        "cache_hits": sum(1 for r in delivered if r[3]),
        "median_live_fetch_ms": live_ms[len(live_ms) // 2] if live_ms else None,
    }


# ---------------------------------------------------------------------------
# Presentation helpers (WhatsApp text)
# ---------------------------------------------------------------------------

def clean_title(title: str) -> str:
    t = re.sub(r"\s+versus\s+", " v ", title or "", flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def case_year(case: dict) -> str:
    d = case.get("decision_date") or ""
    return d[:4] if re.match(r"\d{4}", d) else ""


def format_choices(choices: list, exact: bool = True) -> str:
    lines = ["I found these -- reply with a number:" if exact else
             "I couldn't find an exact match. These are the closest -- reply with a number ONLY if one is the case "
             "you meant:"]
    for i, c in enumerate(choices, 1):
        bits = [clean_title(c["title"])]
        tail = ", ".join(x for x in ((c.get("court") or "").replace(" of India", ""), case_year(c)) if x)
        if tail:
            bits.append(f"({tail})")
        if c.get("citation"):
            bits.append(c["citation"])
        if c.get("n_chunks") is not None and c["n_chunks"] < 3:     # None = unknown (bucket-added case): say nothing
            bits.append("[very short record -- possibly just an order]")
        lines.append(f"{i}. " + " ".join(bits))
    lines.append("Or send *CASE: <name>* to search again.")
    return "\n".join(lines)
