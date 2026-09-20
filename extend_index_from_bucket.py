"""
extend_index_from_bucket.py -- add cases to the CASE search catalogue (case_lookup_index.db) from the open
bucket's OWN case list (https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/metadata/parquet/
year=YYYY/metadata.parquet; CC-BY-4.0, Dattam Labs).

WHY (2026-09-20): the catalogue was built from Vaquill's dataset, which lists 437 Supreme Court cases for 2025
while the bucket lists 897 -- so e.g. Gayatri Balasamy v ISG Novasoft (2025) was "not found" although its original
PDF exists. Measured on 2025 / 2017 / 1996 / 1973: ids use the same scheme ('2025 INSC 605' -> '2025_INSC_605'),
zero title+date lookalikes, +458 / +14 / +8 / 0 genuinely new cases.

Run by a PERSON, offline, one year (or a few) at a time -- never in a request:
    python extend_index_from_bucket.py 2025                # DRY RUN: prints what WOULD be added
    python extend_index_from_bucket.py 2025 --apply        # writes the new rows
    python extend_index_from_bucket.py 1950-2025 --apply   # a range, one year at a time (memory-friendly)
Only NEW cases are added; existing rows are never touched; running it twice adds nothing.
New rows carry source='bucket' (no re-typed text exists for them -- the bot sends the ORIGINAL pdf).
"""
import re
import sys

COURT = "Supreme Court of India"
_CIT_RE = re.compile(r"\[(\d{4})\]\s*(?:Suppl?\.?\s*)?(\d+)\s*(?:Suppl?\.?\s*)?S\.?\s?C\.?\s?R\.?\s*(\d+)", re.I)
_BUCKET_META = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com/metadata/parquet/year=%d/metadata.parquet"


def _norm_title(t) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _iso_date(d):
    m = re.match(r"^\s*(\d{1,2})-(\d{1,2})-(\d{4})\s*$", d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def bucket_row_to_case(row: dict):
    """A catalogue row from one bucket metadata row, or None if it can't be keyed safely."""
    title = " ".join(str(row.get("title") or "").split())
    if not title:
        return None
    cid = re.sub(r"\s+", "_", str(row.get("case_id") or "").strip())
    citation = (row.get("citation") or "").strip() or None
    if not cid:
        m = _CIT_RE.search(citation or "")
        if not m:
            return None
        cid = f"{m.group(1)}_SCR_{int(m.group(2))}_{int(m.group(3))}"
    return {"case_id": cid, "title": title, "court": row.get("court") or COURT, "decision_date": _iso_date(row.get("decision_date")),
            "citation": citation, "source": "bucket"}


def merge_new_cases(conn, cases: list, dry_run: bool = False) -> dict:
    """Insert only genuinely new cases (not the same id, not the same normalised title + date). Repeatable.
    dry_run=True counts exactly what would be added and writes NOTHING."""
    have_ids = {r[0] for r in conn.execute("SELECT case_id FROM cases")}
    have_td = {(_norm_title(t), d) for t, d in conn.execute("SELECT title, decision_date FROM cases")}
    out = {"added": 0, "skipped_same_id": 0, "skipped_same_title_date": 0, "skipped_invalid": 0}
    with conn:
        for c in cases:
            if not c:
                out["skipped_invalid"] += 1
                continue
            key = (_norm_title(c["title"]), c["decision_date"])
            if c["case_id"] in have_ids:
                out["skipped_same_id"] += 1
                continue
            if c["decision_date"] and key in have_td:
                out["skipped_same_title_date"] += 1
                continue
            if not dry_run:
                conn.execute(
                    "INSERT INTO cases (case_id, title, court, decision_date, citation, source_url, n_chunks, source) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (c["case_id"], c["title"], c["court"], c["decision_date"], c["citation"], None, None, "bucket"),
                )
                conn.execute("INSERT INTO cases_fts (case_id, title) VALUES (?, ?)", (c["case_id"], c["title"]))
            have_ids.add(c["case_id"])
            have_td.add(key)
            out["added"] += 1
    return out


def load_year(year: int) -> list:
    """The bucket's metadata rows for one year (one small file, ~1 MB)."""
    import duckdb
    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs; LOAD httpfs;")
        rows = con.execute(
            "SELECT case_id, title, decision_date, citation, court FROM read_parquet('%s')" % (_BUCKET_META % year)
        ).fetchall()
    finally:
        con.close()
    return [{"case_id": r[0], "title": r[1], "decision_date": r[2], "citation": r[3], "court": r[4]} for r in rows]


def _parse_years(arg: str) -> list:
    if "-" in arg:
        a, b = arg.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in arg.split(",")]


def main(argv):
    apply = "--apply" in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    import case_lookup
    conn = case_lookup._index_conn()
    total = 0
    try:
        for year in _parse_years(args[0]):
            try:
                rows = load_year(year)
            except Exception as exc:
                print(f"{year}: could not read the bucket's list ({type(exc).__name__}) -- skipped")
                continue
            cases = [bucket_row_to_case(r) for r in rows]
            r = merge_new_cases(conn, cases, dry_run=not apply)     # a dry run writes nothing at all
            total += r["added"]
            print(f"{year}: bucket {len(rows):5d} | {'ADDED' if apply else 'would add'} {r['added']:4d} | same id {r['skipped_same_id']:5d} "
                  f"| same title+date {r['skipped_same_title_date']:3d} | unusable {r['skipped_invalid']:3d}")
        print(f"\nTOTAL {'added' if apply else 'that would be added'}: {total}   catalogue now: "
              f"{conn.execute('SELECT COUNT(*) FROM cases').fetchone()[0]} cases" + ("" if apply else "  (dry run, nothing written)"))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
