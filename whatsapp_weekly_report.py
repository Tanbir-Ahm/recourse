
"""
whatsapp_weekly_report.py

The human-review half of the safe learning loop (see
memory/whatsapp-interface-technical-plan.md sections 3-4): counts how
often real WhatsApp questions landed in the "thin" (low-confidence)
bucket, and lists them so a person can spot patterns and decide what's
worth adding to the corpus. This script never changes anything the bot
tells anyone -- it only reads whatsapp_store.qa_log and prints a report.

Deliberately NOT AI-powered topic-clustering. Pure counting plus the
raw question text, closer to a spreadsheet than software -- the same
"a human reads the report, this is not a pass/fail gate" discipline
eval_related_judgments.py and eval_chat_answers.py already use
elsewhere in this project.

Run:
    python whatsapp_weekly_report.py            # last 7 days
    python whatsapp_weekly_report.py --days 30   # last 30 days
"""
import argparse
import time
from collections import Counter

import whatsapp_store

_CATEGORIES = ("confident", "thin", "technical_failure", "out_of_scope")


def _fetch_rows(days: int) -> list:
    """Uses whatsapp_store._connect() rather than a raw sqlite3.connect()
    specifically so the qa_log table gets created (CREATE TABLE IF NOT
    EXISTS) if this runs against a brand-new deployment that hasn't
    logged anything yet -- a raw connection to a file with no table
    would crash instead of honestly reporting zero questions."""
    cutoff = time.time() - days * 86400
    conn = whatsapp_store._connect()
    try:
        rows = conn.execute(
            "SELECT phone_number, question, state, confidence, created_at "
            "FROM qa_log WHERE created_at >= ? ORDER BY created_at",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return rows


def generate_report(days: int = 7) -> str:
    rows = _fetch_rows(days)
    lines = []
    lines.append(f"WhatsApp confidence report -- last {days} day(s)")
    lines.append(f"Total real questions: {len(rows)}")
    lines.append("")

    if not rows:
        lines.append("No questions logged in this period.")
        return "\n".join(lines)

    by_confidence = Counter(r[3] for r in rows)
    lines.append("By confidence:")
    for cat in _CATEGORIES:
        lines.append(f"  {cat}: {by_confidence.get(cat, 0)}")
    lines.append("")

    thin_rows = [r for r in rows if r[3] == "thin"]
    if not thin_rows:
        lines.append("No 'thin' (low-confidence) questions this period -- nothing to review.")
    else:
        lines.append(f"--- {len(thin_rows)} question(s) worth reviewing ---")
        lines.append("")
        state_counts = Counter(r[2] for r in thin_rows)
        lines.append("By reason:")
        for state, count in state_counts.most_common():
            lines.append(f"  {state}: {count}")
        lines.append("")
        lines.append("Raw questions, oldest first (read these for patterns):")
        for _phone, question, state, _confidence, created_at in thin_rows:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
            lines.append(f"  [{ts}] ({state}) {question}")

    failure_rows = [r for r in rows if r[3] == "technical_failure"]
    if failure_rows:
        lines.append("")
        lines.append(
            f"--- {len(failure_rows)} technical failure(s) -- check the API/network, "
            "not the corpus ---"
        )
        for _phone, question, state, _confidence, created_at in failure_rows:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
            lines.append(f"  [{ts}] ({state}) {question}")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="how many days back to report on")
    args = parser.parse_args()
    print(generate_report(args.days))
