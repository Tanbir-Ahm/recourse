
"""
test_candidate_pipeline.py

Regression suite for candidate_pipeline.py (see that module's docstring
for the architecture boundary it must never cross: it stages evidence,
it never makes anything live on its own). Same lightweight
check()/FAILURES convention as the rest of this repo's test_*.py files;
run directly: `python test_candidate_pipeline.py`. No real network calls
-- judgment_corroboration.full_corroboration_report is mocked.
"""
import tempfile
from unittest.mock import patch

import candidate_pipeline

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


candidate_pipeline.DB_PATH = tempfile.mktemp(suffix=".db")

_FAKE_REPORT = {
    "cross_source": {"checked": True, "found_in_vaquill": True, "vaquill_case_id": "2020_INSC_1"},
    "citation_corroboration": {"checked": True, "documents_scanned": 5, "corroborating_documents": [
        {"title": "Some Citing Case", "court": "Delhi High Court", "matched_headline": "..."},
    ]},
    "independent_agreement": {"checked": True, "best_matching_rank": 1, "candidates": []},
}

with patch("judgment_corroboration.full_corroboration_report", return_value=_FAKE_REPORT) as mock_report:
    cid = candidate_pipeline.propose_candidate(
        case_name="Test Case v Someone", citation="(2020) 1 SCC 1",
        source_url="https://indiankanoon.org/doc/1/", paragraph_number="10",
        holding_text="This is the proposed holding text.",
        case_title_contains="TEST CASE", case_name_for_search="Test Case v Someone",
        key_phrase_groups=[("test",)], doctrine_keywords=["test"],
    )

check(isinstance(cid, int) and cid > 0, "propose_candidate runs the corroboration pipeline and returns a real id")
check(mock_report.called, "the automated corroboration checks (Ideas 1+2) actually ran, not skipped")

pending = candidate_pipeline.list_candidates(status="pending")
check(
    len(pending) == 1 and pending[0]["case_name"] == "Test Case v Someone",
    "the new candidate is staged as 'pending', not silently anywhere else",
)
check(
    pending[0]["corroboration"] == _FAKE_REPORT,
    "the full corroboration evidence is saved alongside the candidate, not just a summary",
)

fetched = candidate_pipeline.get_candidate(cid)
check(fetched is not None and fetched["id"] == cid, "get_candidate retrieves the exact staged candidate by id")
check(
    candidate_pipeline.get_candidate(999999) is None,
    "a non-existent candidate id returns None honestly, never crashes",
)

# ---- the architecture boundary: approving in this database changes NOTHING live ----

import domestic_violence_doctrine_map as dvdm
_overrides_before = dvdm.get_domestic_violence_override("This is the proposed holding text about test case")

ok = candidate_pipeline.approve(cid, note="looks solid, corroborated by two independent sources")
check(ok is True, "approve() succeeds for a real pending candidate")

_overrides_after = dvdm.get_domestic_violence_override("This is the proposed holding text about test case")
check(
    _overrides_before == _overrides_after,
    "CRITICAL: approving a candidate in this database does NOT change what the live tool answers -- "
    "promoting an approved candidate to a real trusted anchor stays a separate, deliberate code change",
)

check(
    candidate_pipeline.get_candidate(cid)["status"] == "approved"
    and candidate_pipeline.get_candidate(cid)["reviewer_note"] == "looks solid, corroborated by two independent sources",
    "the approval decision and the reviewer's own note are both recorded",
)
check(
    candidate_pipeline.list_candidates(status="pending") == [],
    "an approved candidate no longer shows up in the pending list",
)

check(
    candidate_pipeline.approve(cid) is False,
    "approving an already-decided candidate again fails honestly rather than silently re-approving",
)

with patch("judgment_corroboration.full_corroboration_report", return_value=_FAKE_REPORT):
    cid2 = candidate_pipeline.propose_candidate(
        case_name="Second Test Case", citation="(2021) 2 SCC 2",
        source_url="https://x", paragraph_number="5", holding_text="Another holding.",
        case_title_contains="SECOND TEST", case_name_for_search="Second Test Case",
        key_phrase_groups=[("second",)], doctrine_keywords=["second"],
    )
rejected_ok = candidate_pipeline.reject(cid2, note="the corroborating court was actually discussing a different point")
check(rejected_ok is True, "reject() works the same way as approve()")
check(
    candidate_pipeline.get_candidate(cid2)["status"] == "rejected",
    "a rejected candidate is recorded as rejected, not silently deleted -- the decision and reasoning stay auditable",
)

check(
    len(candidate_pipeline.list_candidates()) == 2
    and len(candidate_pipeline.list_candidates(status="approved")) == 1
    and len(candidate_pipeline.list_candidates(status="rejected")) == 1,
    "list_candidates filters correctly by status across a mixed batch",
)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
