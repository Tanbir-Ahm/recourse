"""
run_tests.py

Fixes a real, confirmed cost problem: of this repo's 53 test_*.py files, only 6 make live
Anthropic/Voyage API calls -- the other 47 are already mocked and free. But "run the test suite"
has meant re-running all 53, identically, every single time, whether local or in a Claude Code
cloud session -- paying for those 6 again even when nothing in their own code path changed.

CONFIRMED (2026-09-24) via two independent full-suite runs (one local, one via a cloud session
with real keys): the 6 live files and their own real wall-clock time when run for real:

    test_chat_domain_handoff.py   ~208s  (classify_scope + interview_flow + full chat pipeline)
    test_whatsapp_bot.py           ~92s  (one deliberate real case, see its own module docstring)
    test_freeze_chat.py            ~37s  (classify_scope + generation)
    test_dv_case_leak_guard.py     ~50s  (classify_scope)
    test_cheque_bounce_chat.py     ~21s  (generation)
    test_chat_grounding.py         ~29s  (grounding-check behaviour against a real model)

Every one of these was made live DELIBERATELY, not by oversight -- each has its own "COST NOTE"
or equivalent docstring explaining why a mock can't prove what it needs to prove (you cannot mock
your way to confidence that the REAL model's behaviour is correct; a mock only proves the mock
does what you told it to). This tool does not change that. It changes WHEN they run.

USAGE
-----
    python run_tests.py            # the default, and what "run the tests" should mean day to day:
                                    # only the 47 free files. No API cost.
    python run_tests.py --live     # only the 6 live files. Real cost -- run this deliberately,
                                    # e.g. right before a deploy, or after touching their code path
                                    # (chat_assistant's generation/scope logic, the WhatsApp flow).
    python run_tests.py --all      # all 53. The full, expensive check -- same as this project's
                                    # pre-deploy discipline already called for, just explicit now
                                    # instead of accidentally re-triggered by habit.

A test file this manifest doesn't know about (a new one someone just wrote) defaults to the FREE
set, never silently treated as live -- being live is something a file's own author must opt into
here, by adding it to LIVE_API_TEST_FILES below, the same deliberate step as writing its own COST
NOTE docstring. This is a whitelist of what costs money, not a blacklist of what's safe.
"""
import glob
import subprocess
import sys
import time

LIVE_API_TEST_FILES = {
    "test_chat_domain_handoff.py",
    "test_whatsapp_bot.py",
    "test_freeze_chat.py",
    "test_dv_case_leak_guard.py",
    "test_cheque_bounce_chat.py",
    "test_chat_grounding.py",
}


def discover_test_files() -> set:
    """Every test_*.py in the repo root, INCLUDING this file's own test (test_run_tests.py) and
    run_tests.py's own presence never matters here -- glob only ever returns real test_*.py
    files, this module isn't named that way itself."""
    return {p for p in glob.glob("test_*.py")}


def select_test_files(all_files: set, mode: str) -> set:
    """mode: 'free' (default -- excludes LIVE_API_TEST_FILES), 'live' (only
    LIVE_API_TEST_FILES, intersected with what's actually present), or 'all' (everything).
    Never raises on an unknown file -- an unrecognised test_*.py defaults to 'free', per this
    module's own docstring (opt-in to live, not opt-out)."""
    if mode == "all":
        return set(all_files)
    if mode == "live":
        return set(all_files) & LIVE_API_TEST_FILES
    return set(all_files) - LIVE_API_TEST_FILES


def _run_one(path: str) -> tuple:
    """Runs one test file as a subprocess with the SAME interpreter running this script (works
    whether that's a local venv or a cloud session's own venv -- never hard-codes a path).
    Returns (path, exit_code, elapsed_seconds, tail_of_output). Never raises -- a file that
    itself crashes just reports a non-zero exit code, exactly like a real failure."""
    start = time.time()
    result = subprocess.run(
        [sys.executable, "-X", "utf8", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    elapsed = time.time() - start
    output = (result.stdout or "") + (result.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-3:])
    return path, result.returncode, elapsed, tail


def main():
    mode = "free"
    if "--live" in sys.argv:
        mode = "live"
    elif "--all" in sys.argv:
        mode = "all"

    all_files = discover_test_files()
    selected = sorted(select_test_files(all_files, mode))

    if mode == "free":
        skipped = sorted(set(all_files) & LIVE_API_TEST_FILES)
        print(f"Running {len(selected)} free (mocked, no API cost) test file(s). "
              f"Skipping {len(skipped)} live-API file(s): {', '.join(skipped) or 'none'}. "
              f"Use --live or --all to include them.\n")
    elif mode == "live":
        print(f"Running {len(selected)} LIVE-API test file(s) -- this costs real money. "
              f"Only the pre-flagged set: {', '.join(selected) or 'none present'}.\n")
    else:
        print(f"Running all {len(selected)} test file(s), including the live-API ones -- "
              f"this costs real money.\n")

    results = []
    for path in selected:
        print(f"=== {path} ===")
        result = _run_one(path)
        results.append(result)
        _, code, elapsed, tail = result
        print(f"{path} : exit {code} ({elapsed:.0f}s)")

    print("\n" + "=" * 70)
    failed = [r for r in results if r[1] != 0]
    print(f"{len(results)} run, {len(results) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("\nFAILED:")
        for path, code, elapsed, tail in failed:
            print(f"\n--- {path} (exit {code}) ---")
            print(tail)
        sys.exit(1)


if __name__ == "__main__":
    main()
