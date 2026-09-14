
"""
test_candidate_pipeline_report.py

Regression suite for candidate_pipeline_report.py -- the human-review
CLI for candidate_pipeline.py. Run directly:
`python test_candidate_pipeline_report.py`. No network calls --
candidate_pipeline.propose_candidate's corroboration step is mocked.
"""
import tempfile
from unittest.mock import patch

import candidate_pipeline
import candidate_pipeline_report as report

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


candidate_pipeline.DB_PATH = tempfile.mktemp(suffix=".db")

_FAKE_REPORT = {
    "cross_source": {"checked": True, "found_in_vaquill": True},
    "citation_corroboration": {"checked": True, "documents_scanned": 4, "corroborating_documents": [
        {"title": "A Citing Case", "court": "Bombay High Court", "matched_headline": "confirms it"},
    ]},
    "independent_agreement": {"checked": True, "best_matching_rank": 1, "candidates": []},
}

check(
    "none right now" in report.generate_report(),
    "an empty pipeline reports honestly, no crash on a fresh database",
)

with patch("judgment_corroboration.full_corroboration_report", return_value=_FAKE_REPORT):
    cid = candidate_pipeline.propose_candidate(
        case_name="Report Test Case", citation="(2020) 1 SCC 1", source_url="https://x",
        paragraph_number="9", holding_text="A holding worth reading.",
        case_title_contains="REPORT TEST", case_name_for_search="Report Test Case",
        key_phrase_groups=[("report",)], doctrine_keywords=["report"],
    )

pending_report = report.generate_report()
check(
    f"#{cid} Report Test Case" in pending_report and "1 awaiting your review" in pending_report,
    "a freshly-proposed candidate shows up in the pending list with its real id and name",
)
check(
    "citing courts confirm" in pending_report,
    "the corroboration summary (second source / citing courts / independent rank) renders per candidate",
)

show_text = report._show(cid)
check(
    "A holding worth reading." in show_text and "A Citing Case" in show_text,
    "--show prints the full holding text and the real corroborating document, not just a summary",
)
check(
    report._show(999999) == "No candidate with id 999999.",
    "--show on a non-existent id fails honestly instead of crashing",
)

ok = candidate_pipeline.approve(cid, note="test approval")
check(ok, "approving via the underlying pipeline function still works exactly as before")

after_report = report.generate_report()
check(
    "0 awaiting your review" in after_report and f"#{cid} Report Test Case -- APPROVED (test approval)" in after_report,
    "once approved, the candidate moves out of 'pending' and into 'already decided' with its own note",
)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
