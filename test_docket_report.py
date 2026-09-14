
"""
test_docket_report.py

Regression suite for docket_report.py -- pure string generation, no
network, no side effects. Run directly: `python test_docket_report.py`.
"""
import docket_report

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


check(
    "Nothing pending review" in docket_report.generate_docket_html([]),
    "an empty candidate list produces an honest empty-state message, not a broken/blank page",
)

_CANDIDATE = {
    "id": 7, "case_name": "Test v Someone <script>", "citation": "(2020) 1 SCC 1",
    "paragraph_number": "12", "holding_text": "The holding text with a \"quote\" & an ampersand.",
    "corroboration": {
        "cross_source": {"checked": True, "found_in_vaquill": True},
        "citation_corroboration": {"checked": True, "documents_scanned": 8, "corroborating_documents": [
            {"title": "Citing Case", "court": "Delhi High Court", "matched_headline": "confirms the holding"},
        ]},
        "independent_agreement": {"checked": True, "best_matching_rank": 1, "candidates": [{}, {}]},
    },
}

html_out = docket_report.generate_docket_html([_CANDIDATE])
check(
    "Test v Someone &lt;script&gt;" in html_out and "Someone <script>" not in html_out,
    "case names are HTML-escaped -- a stray '<script>' in real-world scraped text renders as inert "
    "text, never as an actual tag (the page's own legitimate <script> block for the buttons is a "
    "separate, expected thing, not what this check is about)",
)
check(
    "&quot;quote&quot;" in html_out or "&#34;quote&#34;" in html_out,
    "the holding text itself is also escaped safely",
)
check(
    "text confirmed present" in html_out and "matches rank 1 of 2" in html_out,
    "cross-source and independent-agreement evidence both render into the page",
)
check(
    "1 of 8 confirm" in html_out,
    "citation corroboration count renders as 'N of M confirm'",
)
check(
    "approve #7" in html_out,
    "the page tells the reviewer the exact command to give Claude, using the real candidate id",
)

_weak_candidate = dict(_CANDIDATE, id=8)
_weak_candidate["corroboration"] = {
    "cross_source": {"checked": True, "found_in_vaquill": False},
    "citation_corroboration": {"checked": True, "documents_scanned": 5, "corroborating_documents": []},
    "independent_agreement": {"checked": False},
}
weak_html = docket_report.generate_docket_html([_weak_candidate])
check(
    "NOT found" in weak_html and 'class="verdict-pill weak"' in weak_html,
    "a candidate with WEAK evidence (not found in the second source, zero corroborating documents) is "
    "visibly flagged differently from a strong one -- never rendered with the same confident styling",
)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
