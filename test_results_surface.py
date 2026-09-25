"""
test_results_surface.py

Covers the UX-redesign plumbing (2026-09-02): the audience-split PDFs
(main._build_kyr_pdf), the plain-language register of layman_summary,
the freeze/cheque payload -> full_analysis wrapper, and the
deterministic plain fallback. No API calls -- FIXED 2026-09-25 (found by
an independent cloud-session review): this docstring used to just claim
"layman_summary's client is absent under a bare import, so it returns
None", which is only true when no real ANTHROPIC_API_KEY happens to be
configured in the environment -- an assumption, not a guarantee. In an
environment where a real key IS ambiently present (e.g. a cloud session
with secrets configured), generate_layman_summary's real call would
actually succeed and cost money, silently, contradicting run_tests.py's
"free means free" default-mode promise. Now main.client is explicitly
forced to None for that one call, so this file's zero-cost guarantee
holds regardless of what's configured in the environment it runs in.

Run: python test_results_surface.py
"""

import os
import sys
from unittest.mock import patch

import fitz  # pymupdf

FAILURES = []


def check(cond, desc):
    print(f"[{'PASS' if cond else 'FAIL'}] {desc}")
    if not cond:
        FAILURES.append(desc)


def _pdf_text(path):
    return " ".join(pg.get_text() for pg in fitz.open(path))


_FA = {
    "classification": {"document_type": "Police & Criminal Process", "sub_type": "Arrest", "reasoning": "t"},
    "missing_info": {"missing_or_unclear": ["Arrest time not stated"], "completeness_assessment": "x"},
    "compliance": {"compliance_checks": [
        {"requirement": "S.35(3) BNSS notice before arrest [Arnesh Kumar v. State of Bihar, (2014) 8 SCC 273]",
         "status": "Non-Compliant", "explanation": "No notice was issued."},
        {"requirement": "Produced before magistrate within 24 hours [Art. 22(2)/S.58 BNSS]",
         "status": "Cannot Determine", "explanation": "Arrest time not stated."},
    ], "overall_assessment": "x"},
    "checklist": ["Arrest memo", "FIR copy"],
    "urgency": {"urgency_level": "Cannot Determine", "deadline_message": "", "days_remaining": None},
    "severity": {"severity_score": 4, "severity_label": "Serious concerns", "unresolved_checks": 1},
    "bail_pathway": None,
    "extracted_fields": {"sections_cited": ["303"]},
}

# ---- the two diagnostic PDFs are audience-separated ----

import main

a = main.generate_analysis_pdf(_FA, "scratch_a.pdf")
n = main.generate_next_steps_pdf(_FA, plain_text="You were arrested. Ask for the arrest memo.", output_path="scratch_n.pdf")
at, nt = _pdf_text(a), _pdf_text(n)

check("Procedural Compliance Findings" in at,
      "analysis PDF has the clause-by-clause compliance findings")
check("Arnesh Kumar" in at,
      "analysis PDF keeps the case-law citation")
check("Documents to gather" not in at and "Documents to Gather" not in at,
      "analysis PDF has NO 'documents to gather' checklist")
check("Recommended Action" not in at,
      "analysis PDF has NO 'recommended action plan'")

check("Documents to gather" in nt,
      "next-steps PDF DOES have the 'documents to gather' checklist")
check("Ask for the arrest memo" in nt,
      "next-steps PDF carries the plain-language summary text")
check("Procedural Compliance Findings" not in nt,
      "next-steps PDF does NOT repeat the clause-by-clause audit")

check(main.generate_compliance_brief(_FA, "scratch_c.pdf") and _pdf_text("scratch_c.pdf") == at,
      "generate_compliance_brief back-compat alias == the analysis PDF")

for f in ("scratch_a.pdf", "scratch_n.pdf", "scratch_c.pdf"):
    os.remove(f)

# ---- layman_summary: plain register formats without crashing, strips citations ----

from layman_summary import _format_compliance_for_prompt, PLAIN_SUMMARY_PROMPT, generate_layman_summary

plain_fmt = _format_compliance_for_prompt(_FA["compliance"], keep_citations=False)
check("[Arnesh Kumar" not in plain_fmt and "Arnesh Kumar" not in plain_fmt,
      "plain register strips the [citation] bracket before the prompt")
check("[Arnesh Kumar" in _format_compliance_for_prompt(_FA["compliance"], keep_citations=True),
      "counsel register keeps the [citation] bracket")
check("{compliance_summary}" in PLAIN_SUMMARY_PROMPT and "{statute_text}" not in PLAIN_SUMMARY_PROMPT,
      "PLAIN_SUMMARY_PROMPT has no statute_text slot (plain path never quotes statute)")
# the plain register runs end to end -- main.client forced to None (2026-09-25 fix) so this is
# guaranteed free regardless of what key is ambiently configured in the environment
with patch("main.client", None):
    _plain = generate_layman_summary(_FA["compliance"], _FA["severity"], None,
                                     offence_name="theft", audience="plain")
check(_plain is None,
      "generate_layman_summary(audience='plain') returns None when no client is available, never raises")

# the "real string returned" branch, restored with a deterministic fake client (2026-09-25 fix) --
# forcing main.client to None above means _plain is never a real string, so this branch would
# otherwise go untested in a free run rather than just untested-with-a-real-key
class _FakeTextBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeAnthropicClient:
    class messages:
        @staticmethod
        def create(**kwargs):
            return _FakeMessage(
                "You may be arrested if the police believe the allegation is true. "
                "You have the right to know why."
            )


with patch("main.client", _FakeAnthropicClient()):
    _plain_fake = generate_layman_summary(_FA["compliance"], _FA["severity"], None,
                                          offence_name="theft", audience="plain")
check(isinstance(_plain_fake, str) and len(_plain_fake) > 20,
      "with a client available, generate_layman_summary(audience='plain') returns real text")
if _plain_fake:
    low = _plain_fake.lower()
    check("section 35" not in low and "arnesh kumar" not in low and "cognizable" not in low,
          "the plain summary carries no section numbers, case names, or jargon")

# ---- app helpers: freeze/cheque wrapper + plain fallback ----

import app

fa_freeze = app._assessment_full_analysis("freeze", {
    "compliance_result": {"compliance_checks": [
        {"requirement": "Freeze cites a legal section", "status": "May be Non-Compliant", "explanation": "No section cited."}],
        "overall_assessment": "x"},
    "severity": {"severity_label": "Some concerns"},
    "fields_known": {"amount": "2 lakh"},
})
check(fa_freeze["classification"]["document_type"] == "Bank / Account Freezing"
      and fa_freeze["bail_pathway"] is None
      and fa_freeze["compliance"]["compliance_checks"][0]["status"] == "May be Non-Compliant",
      "_assessment_full_analysis('freeze', ...) produces a full_analysis-shaped dict")
check("checklist" in fa_freeze and isinstance(fa_freeze["checklist"], list),
      "the wrapped freeze analysis carries a document checklist")

fa_cheque = app._assessment_full_analysis("cheque_bounce", {
    "compliance_result": {"compliance_checks": [], "overall_assessment": "x"},
    "severity": {}, "fields_known": {}, "presumption_info": {"explanation": "e", "note": "n"},
})
check(fa_cheque["classification"]["document_type"] == "Cheque Bounce"
      and fa_cheque.get("presumption_info", {}).get("explanation") == "e",
      "_assessment_full_analysis('cheque_bounce', ...) carries presumption_info through")

fb = app._plain_fallback(_FA)
check("What was found" in fb and "What you can do now" in fb,
      "_plain_fallback has the plain structure")
check("Section 35" not in fb and "Arnesh Kumar" not in fb and "[" not in fb,
      "_plain_fallback strips section numbers and citation brackets")
check("District Legal Services Authority" in fb,
      "_plain_fallback points to a concrete free-help route, not just 'consult a lawyer'")

fb_clean = app._plain_fallback({"compliance": {"compliance_checks": [
    {"requirement": "X", "status": "Compliant", "explanation": "ok"}]}})
check("Nothing in the information given shows a clear procedural problem" in fb_clean,
      "_plain_fallback handles an all-clean analysis without implying wrongdoing")

# ---- the menu is exactly 4 options ----

check(len(app._MENU) == 4 and set(app._MENU.values()) == {"chat", "document", "guided", "triage"},
      "the entry menu is exactly 4 options -> chat/document/guided/triage")
check(app._HANDOFF_ROUTES == {"arrest_assess", "freeze_assess", "cheque_assess"},
      "the 3 handoff-only routes are defined")


print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL TESTS PASSED")
