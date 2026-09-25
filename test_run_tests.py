"""
test_run_tests.py -- tests for run_tests.py, the regression runner that stops this project from
re-paying for live Anthropic/Voyage API calls on every single test pass. Written BEFORE
run_tests.py itself.

WHY THIS EXISTS (2026-09-24): confirmed by two independent full-suite runs this session (one
local, one via a Claude Code cloud session with real keys) that only 6 of 53 test_*.py files
actually make live API calls -- the rest are already mocked. The other 47 were being re-run
alongside those 6 identically every single time, at real cost, even when nothing in the live
files' own code path had changed. run_tests.py fixes this by defaulting to the free 47 and
making the paid 6 an explicit, deliberate choice, not something that happens by accident every
time someone says "run the tests."

Run: python -X utf8 test_run_tests.py
"""
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


import run_tests as rt

# ---------------------------------------------------------------- 1. the manifest itself
check(hasattr(rt, "LIVE_API_TEST_FILES"), "run_tests exposes LIVE_API_TEST_FILES")
# 8, not 6, as of 2026-09-25: test_interview_flow.py and test_niact_sections.py added, both
# confirmed (by an independent cloud-session review) to make real calls that were never declared
# to this manifest. Checked as a superset rather than a fixed set, since this list is expected to
# keep growing as new live-by-design test files get written -- what actually matters is that the
# ORIGINAL 6, confirmed via real observed run time, are still present, not that the set is frozen.
EXPECTED_LIVE = {
    "test_chat_domain_handoff.py", "test_whatsapp_bot.py", "test_freeze_chat.py",
    "test_dv_case_leak_guard.py", "test_cheque_bounce_chat.py", "test_chat_grounding.py",
}
check(EXPECTED_LIVE.issubset(rt.LIVE_API_TEST_FILES),
      f"the manifest still contains the 6 original files confirmed (via real observed run time, "
      f"not a guess) to make live API calls -- got {rt.LIVE_API_TEST_FILES}")

# ---------------------------------------------------------------- 2. discovery + selection logic
ALL_FILES = {"test_answer_cache.py", "test_chat_grounding.py", "test_whatsapp_bot.py", "test_case_lookup.py"}

free_only = rt.select_test_files(ALL_FILES, mode="free")
check(free_only == {"test_answer_cache.py", "test_case_lookup.py"},
      f"default/'free' mode selects only the non-live files -- got {free_only}")

live_only = rt.select_test_files(ALL_FILES, mode="live")
check(live_only == {"test_chat_grounding.py", "test_whatsapp_bot.py"},
      f"'live' mode selects only the known live-API files -- got {live_only}")

everything = rt.select_test_files(ALL_FILES, mode="all")
check(everything == ALL_FILES, f"'all' mode selects every file -- got {everything}")

# a file this project doesn't know about yet (e.g. a brand-new test) must default to the FREE
# set unless explicitly marked live -- never silently costs money for a file nobody flagged.
new_file_set = ALL_FILES | {"test_brand_new_thing.py"}
check("test_brand_new_thing.py" in rt.select_test_files(new_file_set, mode="free"),
      "an unrecognised new test file defaults to the free set, not silently treated as live")
check("test_brand_new_thing.py" not in rt.select_test_files(new_file_set, mode="live"),
      "an unrecognised new test file is never assumed live either -- 'live' mode is opt-in per file, "
      "not everything-not-explicitly-free")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
