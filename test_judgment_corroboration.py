
"""
test_judgment_corroboration.py

Regression suite for judgment_corroboration.py (see that module's
docstring for the full design -- two deterministic, non-AI corroboration
checks meant to make a human's final sign-off on a new curated judgment
anchor faster and more confident). Same lightweight check()/FAILURES
convention as the rest of this repo's test_*.py files; run directly:
`python test_judgment_corroboration.py`. No real network calls -- the
Indian Kanoon search is mocked; the Vaquill check uses a small,
directly-populated local SQLite file instead of the real 64MB pool.
"""
import tempfile
from unittest.mock import patch

import judgment_corroboration
import vaquill_search

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- cross_source_check: against a small, directly-populated test pool ----

_test_db = tempfile.mktemp(suffix=".db")
vaquill_search.DB_PATH = _test_db
conn = vaquill_search._connect()
with conn:
    conn.execute(
        "INSERT INTO metadata (case_id, title, court, decision_date, disposition, is_procedural_order, "
        "has_reasoning_structure, disposal_markers, ik_search_url, n_chunks, topic) "
        "VALUES ('2016_INSC_955', 'HIRAL P. HARSORA versus KUSUM NAROTTAMDAS HARSORA', "
        "'Supreme Court of India', '2016-10-06', 'Disposed off', NULL, NULL, '[]', 'https://x', 1, "
        "'domestic_violence')"
    )
    conn.execute(
        "INSERT INTO fts (case_id, title, full_text) VALUES (?, ?, ?)",
        ("2016_INSC_955", "HIRAL P. HARSORA versus KUSUM NAROTTAMDAS HARSORA",
         "...some earlier text... We therefore set aside the impugned judgment "
         "of the Bombay High Court and declare that the words adult male in "
         "Section 2(q) of the 2005 Act will stand deleted... more text follows..."),
    )
conn.close()

result = judgment_corroboration.cross_source_check(
    "HARSORA",
    "We, therefore, set aside the impugned judgment of the Bombay High Court and declare",
)
check(
    result["checked"] and result["found_in_vaquill"] is True and result["vaquill_case_id"] == "2016_INSC_955",
    "cross_source_check finds the real holding fingerprint inside an independently-scraped copy "
    "of the same judgment",
)

wrong_result = judgment_corroboration.cross_source_check(
    "HARSORA",
    "This exact sentence does not appear anywhere in the real judgment text",
)
check(
    wrong_result["checked"] and wrong_result["found_in_vaquill"] is False,
    "cross_source_check honestly reports False when the claimed holding text does NOT appear in the "
    "independent copy -- this is exactly the kind of mistake the check exists to catch",
)

missing_result = judgment_corroboration.cross_source_check(
    "SOME CASE NOT IN THE POOL AT ALL",
    "anything",
)
check(
    missing_result["checked"] and missing_result["found_in_vaquill"] is None,
    "when no matching case exists in the local pool at all, the result is honestly None "
    "('nothing to check against'), never treated as a confirmed absence",
)

# ---- citation_corroboration_check: Indian Kanoon search mocked, no network ----

_FAKE_SEARCH_RESULTS = {
    "docs": [
        {
            "tid": 1,
            "title": "Smt. Pooja vs Smt. Matura Bai on 12 December, 2025",
            "docsource": "Karnataka High Court",
            "headline": "In Hiral P. Harsora v. Kusum Narottamdas Harsora, AIR 2016 SC 4774, "
                        "the Hon'ble Supreme Court struck down the words &quot;adult male person&quot;",
        },
        {
            "tid": 2,
            "title": "Some Unrelated Case citing Harsora for a different point",
            "docsource": "Delhi High Court",
            "headline": "this document cites Harsora only regarding costs awarded, nothing about "
                        "adult male or Section 2(q)",
        },
        {
            "tid": 1,  # duplicate tid -- must not be double-counted
            "title": "Smt. Pooja vs Smt. Matura Bai on 12 December, 2025",
            "docsource": "Karnataka High Court",
            "headline": "adult male struck down",
        },
    ]
}

with patch("indiankanoon_client.search", return_value=_FAKE_SEARCH_RESULTS):
    citation_result = judgment_corroboration.citation_corroboration_check(
        "Hiral Harsora Kusum Narottamdas Harsora",
        key_phrase_groups=[("adult male", "struck")],
    )

check(
    citation_result["checked"] and citation_result["documents_scanned"] == 2,
    "documents_scanned counts DISTINCT documents by id, not raw search rows (the duplicate tid "
    "is not counted twice)",
)
check(
    len(citation_result["corroborating_documents"]) == 1
    and citation_result["corroborating_documents"][0]["court"] == "Karnataka High Court",
    "only the document whose headline actually matches the claimed holding phrase is reported as "
    "corroborating -- the unrelated citing document (about costs) is correctly excluded",
)

with patch("indiankanoon_client.search", side_effect=Exception("network exploded")):
    failed_result = judgment_corroboration.citation_corroboration_check(
        "anything", key_phrase_groups=[("x",)]
    )
check(
    failed_result == {"checked": False, "documents_scanned": 0, "corroborating_documents": []},
    "a real search failure is caught and reported honestly as checked=False, never raised",
)

with patch("indiankanoon_client.search", return_value={"docs": []}):
    empty_result = judgment_corroboration.citation_corroboration_check(
        "an obscure case nobody has cited yet", key_phrase_groups=[("x",)]
    )
check(
    empty_result["checked"] and empty_result["corroborating_documents"] == [],
    "zero citing documents is reported honestly as zero, never as an error or a false positive",
)

# ---- full_corroboration_report: both checks combined ----

with patch("indiankanoon_client.search", return_value=_FAKE_SEARCH_RESULTS):
    report = judgment_corroboration.full_corroboration_report(
        "HARSORA", "Hiral Harsora Kusum Narottamdas Harsora",
        "We, therefore, set aside the impugned judgment of the Bombay High Court and declare",
        key_phrase_groups=[("adult male", "struck")],
    )
check(
    report["cross_source"]["found_in_vaquill"] is True
    and len(report["citation_corroboration"]["corroborating_documents"]) == 1,
    "full_corroboration_report combines both independent checks into one result for a human to read",
)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
