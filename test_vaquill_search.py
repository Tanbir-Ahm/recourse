
"""
test_vaquill_search.py

Regression suite for vaquill_search.py -- the scoped, self-hosted Vaquill
judgment search pool (see that module's docstring for the full design and
why it stays separate from the trusted corpus). Same lightweight
check()/FAILURES convention as the rest of this repo's test_*.py files;
run directly: `python test_vaquill_search.py`.

build_index() itself (real duckdb + a real network call to Vaquill's
hosted parquet) is NOT exercised here -- that's a deliberate, real,
one-time ingestion operation, not something to run on every test pass.
These tests populate the SQLite tables directly to test search() and the
finality shim in isolation, no network, no API cost.
"""
import json
import tempfile

import vaquill_search

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


vaquill_search.DB_PATH = tempfile.mktemp(suffix=".db")

# ---- _ik_search_url / _tri_to_int: small pure helpers ----

check(
    vaquill_search._ik_search_url("D. Velusamy versus D. Patchaiammal")
    == "https://indiankanoon.org/search/?formInput=D.%20Velusamy%20versus%20D.%20Patchaiammal",
    "_ik_search_url builds a real, correctly-encoded Indian Kanoon search link from a case title",
)
check(
    vaquill_search._tri_to_int(True) == 1 and vaquill_search._tri_to_int(False) == 0
    and vaquill_search._tri_to_int(None) is None,
    "_tri_to_int preserves the three-valued True/False/None distinction as 1/0/None for SQLite storage",
)

# ---- the section_type -> IK structure shim: proves classify_document_finality ----
# ----   (built for Indian Kanoon's tag vocabulary) gets a fair signal from Vaquill's ----
# ----   different vocabulary, rather than silently seeing nothing ----

from ik_triage import classify_document_finality

_mapped = [
    {"text": "The facts are these.", "structure": vaquill_search._SECTION_TYPE_TO_IK_STRUCTURE.get("body")},
    {"text": "We hold that the appeal is allowed and the order is set aside.",
     "structure": vaquill_search._SECTION_TYPE_TO_IK_STRUCTURE.get("ratio_decidendi")},
]
_result = classify_document_finality(_mapped)
check(
    _result["has_reasoning_structure"] is True,
    "a chunk tagged 'ratio_decidendi' (Vaquill's own reasoning-content tag) correctly registers as real "
    "reasoning structure once mapped through the shim -- proves classify_document_finality gets a fair "
    "signal from Vaquill's different tag vocabulary instead of seeing nothing",
)

_unmapped = [{"text": "released on bail", "structure": vaquill_search._SECTION_TYPE_TO_IK_STRUCTURE.get("body")}]
check(
    classify_document_finality(_unmapped)["has_reasoning_structure"] is None,
    "when NOTHING in a document maps to a recognised reasoning tag, finality stays honestly 'unknown' "
    "rather than being guessed as procedural just because disposal language is present",
)

# ---- search(): populate the tables directly, no network, no duckdb ----

conn = vaquill_search._connect()
_ROWS = [
    ("2016_INSC_955", "HIRAL P. HARSORA versus KUSUM NAROTTAMDAS HARSORA", "Supreme Court of India",
     "2016-10-06", "Disposed off", None, None, [], "domestic_violence",
     "Section 2(q) adult male person struck down as violative of Article 14."),
    ("2010_INSC_716", "D. VELUSAMY versus D. PATCHAIAMMAL", "Supreme Court of India",
     "2010-10-21", "Appeal(s) allowed", 0, 1, [], "domestic_violence",
     "A relationship in the nature of marriage requires the couple to hold themselves out as spouses."),
    ("2011_INSC_500", "SOME BAIL MATTER versus STATE", "Supreme Court of India",
     "2011-01-01", "Bail granted", 1, 0, ["bail application is allowed"], "domestic_violence",
     "The bail application is allowed and the accused is released on bail."),
    ("1999_INSC_100", "UNRELATED TAX CASE versus COMMISSIONER", "Supreme Court of India",
     "1999-01-01", "Dismissed", None, None, [], "tax_law",
     "This case concerns income tax deductions under a completely different Act."),
]
with conn:
    for case_id, title, court, date, disp, proc, reason, markers, topic, text in _ROWS:
        conn.execute(
            "INSERT INTO metadata (case_id, title, court, decision_date, disposition, is_procedural_order, "
            "has_reasoning_structure, disposal_markers, ik_search_url, n_chunks, topic) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, title, court, date, disp, proc, reason, json.dumps(markers),
             vaquill_search._ik_search_url(title), 1, topic),
        )
        conn.execute("INSERT INTO fts (case_id, title, full_text) VALUES (?, ?, ?)", (case_id, title, text))
conn.close()

results = vaquill_search.search("relationship in the nature of marriage spouses", topic="domestic_violence")
check(
    len(results) >= 1 and results[0]["case_name"] == "D. VELUSAMY versus D. PATCHAIAMMAL",
    "a real lexical query finds the right case by its actual judgment text, ranked first",
)
check(
    all(r["source"] == "vaquill" for r in results),
    "every result is tagged source='vaquill' -- the existing unverified_for_display panel needs this "
    "to apply the 'read carefully, not independently verified' framing, never treat it as trusted",
)

results_other_topic = vaquill_search.search("income tax deductions Act", topic="tax_law")
check(
    len(results_other_topic) == 1 and results_other_topic[0]["case_name"] == "UNRELATED TAX CASE versus COMMISSIONER",
    "topic filtering actually isolates pools -- a domestic_violence query never surfaces a tax_law case",
)
check(
    vaquill_search.search("relationship in the nature of marriage", topic="tax_law") == [],
    "the same query against the WRONG topic pool finds nothing, proving topic scoping is real, not decorative",
)

bail_result = vaquill_search.search("bail application allowed accused released", topic="domestic_violence")
check(
    len(bail_result) >= 1 and bail_result[0]["procedural_disposal"] is True
    and bail_result[0]["disposal_markers"] == ["bail application is allowed"],
    "a flagged procedural/bail order still comes back from search (never silently hidden -- 'flag, don't "
    "hide' is this project's standing rule) but carries procedural_disposal=True so a caller can warn about it",
)

check(
    vaquill_search.search("") == [],
    "an empty query returns no results instead of matching everything or crashing",
)
check(
    vaquill_search.search("something nobody ever wrote about xyz123") == [],
    "a query matching nothing returns an honest empty list",
)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
