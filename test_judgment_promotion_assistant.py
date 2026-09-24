"""
test_judgment_promotion_assistant.py -- the tool that turns "read an 8-page judgment cold"
(what promoting Jagrup Singh required) into "read one paragraph of summary and check it against
one real quoted passage" (a couple of minutes). Written BEFORE the code. Synthetic fixtures
throughout, mocked LLM calls -- never real judgment text or a real API call in a test, same
convention as every other suite in this project.

WHY THIS EXISTS (2026-09-24): promoting a pilot-tier case to full authority requires a person to
confirm the judgment actually holds what it's claimed to -- that's the one step this project's
whole trust architecture refuses to let an LLM do alone (see judgment_corroboration.py's own
hard-won lesson: an AI reading a judgment once picked a plausible-looking but WRONG passage before
finding the real holding, while sourcing Satish Chander Ahuja). This tool does NOT remove that
step. It only removes the SLOW part around it: the LLM reads the full judgment and drafts a
summary + a claimed verbatim quote + suggested trigger words, but nothing is trusted from that
draft directly --
  1. the claimed quote is deterministically checked against the REAL source text (not the LLM's
     own paraphrase of it) -- a fabricated or misremembered quote is rejected outright, never
     shown as if it were real;
  2. a second, fully independent, non-LLM pass (sliding-window + holding-marker scoring, the same
     technique judgment_corroboration.py already uses) surfaces its own candidate passages from
     the SAME text with zero knowledge of what the LLM picked, as a corroboration signal -- never
     a verdict, exactly per that module's own explicit warning against treating agreement as "safe
     to skip reading."
This module has NO function that writes to chunks/ or judgment_doctrine_map.py -- it only ever
produces a report for a person to read and act on by hand, the same way Jagrup Singh was promoted.

Run: python -X utf8 test_judgment_promotion_assistant.py
"""
import sys
from unittest.mock import MagicMock, patch

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


import judgment_promotion_assistant as jpa

# ---------------------------------------------------------------- 1. quote grounding check
SOURCE_TEXT = (
    "The appellant and the deceased were collaterals. Something happened on the spur of the "
    "moment. HELD: the appellant having been struck the deceased in the heat of the moment "
    "without premeditation, all the requirements of Exception 4 are clearly met. The conviction "
    "is altered to one under a lesser section."
)

check(jpa._verify_quote_is_real("all the requirements of Exception 4 are clearly met", SOURCE_TEXT),
      "an exact real substring is confirmed real")
check(jpa._verify_quote_is_real(
    "all the requirements   of Exception 4\nare  clearly met", SOURCE_TEXT),
      "a real quote with different whitespace/line-wrapping (normal for a scanned judgment) still "
      "verifies -- must not falsely reject a real quote over cosmetic formatting")
check(not jpa._verify_quote_is_real("all the requirements of Exception 7 are clearly met", SOURCE_TEXT),
      "a fabricated/altered quote (wrong number) is correctly rejected, not treated as real")
check(not jpa._verify_quote_is_real("", SOURCE_TEXT), "an empty quote is never treated as verified")
check(not jpa._verify_quote_is_real("something not in the source at all", SOURCE_TEXT),
      "an invented quote with no relation to the source is rejected")

# ---------------------------------------------------------------- 2. independent, non-LLM candidate scan
holding_result = jpa._independent_holding_candidates(SOURCE_TEXT)
check(holding_result["candidates"], "text containing real holding-marker language produces at least one candidate")
check(any("exception 4" in c["text"].lower() for c in holding_result["candidates"]),
      "the independently-scored top candidate actually covers the real holding language -- not just "
      "any passage")

no_marker_text = "This is a routine procedural order listing the case for a future date."
empty_result = jpa._independent_holding_candidates(no_marker_text)
check(empty_result["candidates"] == [], "text with no holding-marker language honestly returns no candidates, not a guess")

# ---------------------------------------------------------------- 3. locating which real chunk contains the quote
FAKE_CHUNKS = [
    {"paragraph_number": "fallback_1", "text": "The appellant and the deceased were collaterals."},
    {"paragraph_number": "fallback_2", "text": "HELD: the appellant having been struck the deceased "
                                                "in the heat of the moment without premeditation, all "
                                                "the requirements of Exception 4 are clearly met."},
    {"paragraph_number": "fallback_3", "text": "The conviction is altered to one under a lesser section."},
]
located = jpa._locate_source_paragraphs("all the requirements of Exception 4 are clearly met", FAKE_CHUNKS)
check(located == ["fallback_2"], f"the quote is correctly traced to the one real chunk that contains it -- got {located}")
check(jpa._locate_source_paragraphs("something never said anywhere", FAKE_CHUNKS) == [],
      "a quote that matches no chunk honestly returns nothing, not a wrong guess")

# ---------------------------------------------------------------- 4. the full draft, LLM mocked
FAKE_LLM_RESPONSE_VALID = MagicMock()
FAKE_LLM_RESPONSE_VALID.content = [MagicMock(type="text", text=(
    '{"summary": "A single blow in a sudden fight, without premeditation, was reduced from murder '
    'to a lesser offence under Exception 4.", '
    '"quote": "all the requirements of Exception 4 are clearly met", '
    '"suggested_triggers": ["sudden fight", "no premeditation", "single blow"]}'
))]

with patch.object(jpa, "client", MagicMock(messages=MagicMock(create=MagicMock(return_value=FAKE_LLM_RESPONSE_VALID)))):
    report = jpa.draft_promotion(
        case_name="Test Case A v State", citation="[2000] 1 S.C.R. 1",
        full_text=SOURCE_TEXT, chunks=FAKE_CHUNKS,
    )
    check(report["quote_verified_real"] is True, "a genuine, real quote from the LLM is confirmed verified")
    check(report["source_paragraph_numbers"] == ["fallback_2"], "the real supporting chunk is correctly identified")
    check(report["rejected"] is False, "a verified draft is NOT flagged rejected")
    check("summary" in report and "quote" in report, "the human-facing summary and quote both reach the report")
    check(report["independent_corroboration"]["candidates"], "the independent, non-LLM corroboration pass is included in the report")

FAKE_LLM_RESPONSE_FABRICATED = MagicMock()
FAKE_LLM_RESPONSE_FABRICATED.content = [MagicMock(type="text", text=(
    '{"summary": "The court held the appellant fully liable for murder in all circumstances.", '
    '"quote": "the appellant is guilty of murder without any exception whatsoever", '
    '"suggested_triggers": ["murder"]}'
))]

with patch.object(jpa, "client", MagicMock(messages=MagicMock(create=MagicMock(return_value=FAKE_LLM_RESPONSE_FABRICATED)))):
    report = jpa.draft_promotion(
        case_name="Test Case B v State", citation="[2000] 1 S.C.R. 2",
        full_text=SOURCE_TEXT, chunks=FAKE_CHUNKS,
    )
    check(report["quote_verified_real"] is False,
          "a fabricated/misremembered quote (not actually in the source) is caught, not trusted")
    check(report["rejected"] is True, "a case whose quote cannot be verified is clearly flagged REJECTED -- never silently promotable")
    check(report["source_paragraph_numbers"] == [], "no paragraph is claimed to support an unverified quote")

# ---------------------------------------------------------------- 5. fails open, never crashes the batch
with patch.object(jpa, "client", MagicMock(messages=MagicMock(create=MagicMock(side_effect=RuntimeError("API down"))))):
    report = jpa.draft_promotion(
        case_name="Test Case C v State", citation="[2000] 1 S.C.R. 3",
        full_text=SOURCE_TEXT, chunks=FAKE_CHUNKS,
    )
    check(report["rejected"] is True, "an API failure produces an honest rejected/errored report, not a crash")
    check("error" in report, "the report says WHY it failed, for a human reviewing the batch")

# ---------------------------------------------------------------- 4b. strengthening #1: surrounding context
# CONFIRMED REAL GAP (2026-09-24, user question): quote-verification alone doesn't show whether the
# very next sentence reverses or qualifies the quoted holding. _context_paragraphs surfaces the
# chunk immediately before and after the matched one(s), purely mechanically (chunk list order),
# so a reviewer sees what's around the quote without having to open the full judgment themselves.
CONTEXT_CHUNKS = [
    {"paragraph_number": "fallback_1", "text": "Some earlier background paragraph."},
    {"paragraph_number": "fallback_2", "text": "HELD: the appellant having been struck the deceased "
                                                "in the heat of the moment without premeditation, all "
                                                "the requirements of Exception 4 are clearly met."},
    {"paragraph_number": "fallback_3", "text": "Some later paragraph about sentencing."},
]
ctx = jpa._context_paragraphs(["fallback_2"], CONTEXT_CHUNKS)
check(ctx["before"] and ctx["before"][0]["paragraph_number"] == "fallback_1",
      "the paragraph immediately before the matched one is surfaced")
check(ctx["after"] and ctx["after"][0]["paragraph_number"] == "fallback_3",
      "the paragraph immediately after the matched one is surfaced")
ctx_first = jpa._context_paragraphs(["fallback_1"], CONTEXT_CHUNKS)
check(ctx_first["before"] == [], "no crash / honestly empty when the match is the very first chunk (nothing before it)")
ctx_last = jpa._context_paragraphs(["fallback_3"], CONTEXT_CHUNKS)
check(ctx_last["after"] == [], "no crash / honestly empty when the match is the very last chunk (nothing after it)")

# ---------------------------------------------------------------- 4c. strengthening #2: holding-language check
# CONFIRMED REAL FINDING while building this (2026-09-24): the narrow marker list already used for
# independent corroboration matched 0 of the 5 real successful drafts from the actual pilot batch --
# too strict to be a hard gate without producing wall-to-wall false rejections. This check is
# therefore SOFT: it flags for extra scrutiny, it does not reject on its own.
check(jpa._quote_has_holding_language(
    "the conviction is altered to a lesser offence, all the requirements are clearly met"),
      "a quote using clear holding/disposition language is recognised as such")
check(not jpa._quote_has_holding_language(
    "the appellant travelled by bullock cart to the police station to report the matter"),
      "a quote that is plainly just narrative/background facts is correctly NOT flagged as holding language")

# ---------------------------------------------------------------- 4d. strengthening #3: old-code reference detection
# Mechanical only (statute_concordance.scan_old_refs, already built and proven elsewhere this
# session) -- this project's own citation_currency.py is explicit that whether a case is still GOOD
# LAW is a human research question no code may decide; this only surfaces the mechanical half (does
# the quote cite an old IPC/CrPC number, and what is it called now), never a staleness verdict.
old_refs = jpa._detect_old_code_references("the appellant has been rightly convicted under Section 324 IPC.")
check(old_refs and old_refs[0]["old"] == "IPC 324" and old_refs[0]["new"] == "BNS 118",
      f"an old IPC section in the quote is automatically resolved to its real modern BNS number -- got {old_refs}")
check(jpa._detect_old_code_references("no old-code section mentioned here at all") == [],
      "a quote with no old-code reference honestly returns nothing, not a guess")

# ---------------------------------------------------------------- 4e. all three reach the full report
with patch.object(jpa, "client", MagicMock(messages=MagicMock(create=MagicMock(return_value=FAKE_LLM_RESPONSE_VALID)))):
    report = jpa.draft_promotion(
        case_name="Test Case A v State", citation="[2000] 1 S.C.R. 1",
        full_text=SOURCE_TEXT, chunks=FAKE_CHUNKS,
    )
    check("context" in report and "before" in report["context"] and "after" in report["context"],
          "the full report includes surrounding context for a verified quote")
    check("holding_language_in_quote" in report, "the full report includes the holding-language soft-flag")
    check("old_code_references" in report, "the full report includes any detected old-code references")
    check("needs_extra_scrutiny" in report, "the full report includes the combined soft-scrutiny flag, separate from 'rejected'")

# ---------------------------------------------------------------- 6. never auto-promotes anything
import inspect
source = inspect.getsource(jpa)
check("import judgment_doctrine_map" not in source,
      "this module never IMPORTS judgment_doctrine_map.py -- it has no code path that could write "
      "an entry into it, promotion is always a separate, human-done step (a docstring may still "
      "mention the module by name to explain the workflow -- that's just prose, not a capability)")
check('open("chunks/' not in source and "open('chunks/" not in source,
      "this module never opens anything under chunks/ for writing -- the only file it writes is "
      "its own review report (judgment_promotion_drafts.json), never the trusted corpus itself")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
