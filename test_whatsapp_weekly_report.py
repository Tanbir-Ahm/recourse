
"""
test_whatsapp_weekly_report.py

Proves whatsapp_weekly_report.py counts and lists correctly -- pure
data-shape checks, no API calls, same check()/FAILURES convention as
the rest of this repo's test_*.py files. Run directly:
    python test_whatsapp_weekly_report.py
"""
import os
import sys
import tempfile
import time

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


import whatsapp_store

_tmp_db = tempfile.mktemp(suffix=".db")
whatsapp_store.DB_PATH = _tmp_db

import whatsapp_weekly_report as report

PHONE_A = "+911111111111"
PHONE_B = "+912222222222"

# Seed a realistic mix, including one question deliberately OLD (outside
# the report window) to prove the time filter actually filters.
whatsapp_store.log_qa(PHONE_A, "My brother was arrested for stealing a goat", "single_match")
whatsapp_store.log_qa(PHONE_A, "What is criminal intimidation?", "no_match")
whatsapp_store.log_qa(PHONE_B, "What about cattle theft specifically?", "adjacent_uncovered")
whatsapp_store.log_qa(PHONE_B, "Three strong but conflicting matches here", "conflicting_matches")
whatsapp_store.log_qa(PHONE_A, "Random small talk", "unrelated")
whatsapp_store.log_qa(PHONE_A, "API hiccup case", "classifier_unavailable")

# Backdate one row to 15 days ago -- outside the default 7-day window,
# safely inside a 30-day one with margin either side of any timing jitter
# between this UPDATE and the report's own time.time() call later.
import sqlite3
conn = sqlite3.connect(whatsapp_store.DB_PATH)
conn.execute(
    "UPDATE qa_log SET created_at = ? WHERE question = ?",
    (time.time() - 15 * 86400, "Random small talk"),
)
conn.commit()
conn.close()

report_text = report.generate_report(days=7)

check(
    "Total real questions: 5" in report_text,
    "the 30-day-old row is correctly excluded from the default 7-day window -- 6 logged, 5 counted",
)
check(
    "confident: 1" in report_text and "thin: 3" in report_text and "technical_failure: 1" in report_text,
    "counts land in the right confidence buckets: 1 confident, 3 thin (no_match + adjacent_uncovered + "
    "conflicting_matches), 1 technical_failure",
)
check(
    "no_match: 1" in report_text and "adjacent_uncovered: 1" in report_text and "conflicting_matches: 1" in report_text,
    "the thin bucket is further broken down by the real reason, not just a single count",
)
check(
    "What is criminal intimidation?" in report_text
    and "What about cattle theft specifically?" in report_text
    and "Three strong but conflicting matches here" in report_text,
    "every thin question's actual raw text appears in the report, for a person to read and judge",
)
check(
    "API hiccup case" in report_text and "check the API/network" in report_text,
    "technical failures get their own section, correctly distinguished from real coverage gaps",
)

# A genuinely separate, empty database -- none of the seeded rows above
# are old enough to naturally fall outside any positive day window, so
# "empty" has to mean "no rows logged at all," not a narrow time window.
_tmp_db_empty = tempfile.mktemp(suffix=".db")
whatsapp_store.DB_PATH = _tmp_db_empty
empty_report = report.generate_report(days=7)
check(
    "Total real questions: 0" in empty_report,
    "a database with nothing logged yet reports honestly as zero, not an error",
)
whatsapp_store.DB_PATH = _tmp_db
try:
    os.remove(_tmp_db_empty)
except OSError:
    pass

thirty_day_report = report.generate_report(days=30)
check(
    "Total real questions: 6" in thirty_day_report,
    "widening the window to 30 days picks up the backdated row too -- the time filter is real, not decorative",
)

try:
    os.remove(_tmp_db)
except OSError:
    pass


print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
