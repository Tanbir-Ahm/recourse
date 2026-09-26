
"""
whatsapp_db_stats.py

Raw usage counts over whatsapp_store's database -- distinct phone numbers,
total questions, a per-number breakdown, and a per-day trend. Built
2026-09-26 after a real quoting failure: piping an inline `python3 -c
"..."` one-liner through `railway ssh` worked from the Bash tool but broke
when re-run from PowerShell, because PowerShell's `\"` does not escape a
double quote the way Bash's does -- it closes the string early, and every
line after it gets interpreted as separate PowerShell commands (exactly
what happened). A real script file sidesteps this permanently: there is
no shell-quoting-sensitive code left to get wrong, in any shell, ever.

This is the sibling to whatsapp_weekly_report.py (which reports on
CONFIDENCE -- how often the engine was sure of an answer). This one
reports on RAW VOLUME -- how many people, how many questions, when.
Same discipline as that script: pure counting, no AI, nothing here ever
changes what the bot tells anyone.

Run (locally, or via `railway ssh -s whatsapp-bot -- "python3 whatsapp_db_stats.py"` --
that plain double-quoted form has no inner quotes, so it is safe from
PowerShell, Bash, or cmd alike):
    python whatsapp_db_stats.py            # last 30 days for the daily trend
    python whatsapp_db_stats.py --days 7   # last 7 days for the daily trend
Per-phone-number totals and the date range are always all-time, since
those numbers are cheap and more useful unfiltered.
"""
import argparse
import time

import whatsapp_store


def generate_report(days: int = 30) -> str:
    conn = whatsapp_store._connect()
    try:
        lines = []

        n_numbers = conn.execute("SELECT COUNT(DISTINCT phone_number) FROM qa_log").fetchone()[0]
        n_questions = conn.execute("SELECT COUNT(*) FROM qa_log").fetchone()[0]
        lines.append(f"Distinct phone numbers (all-time): {n_numbers}")
        lines.append(f"Total questions logged (all-time): {n_questions}")

        date_range = conn.execute("SELECT MIN(created_at), MAX(created_at) FROM qa_log").fetchone()
        if date_range[0] is not None:
            first = time.strftime("%Y-%m-%d", time.localtime(date_range[0]))
            last = time.strftime("%Y-%m-%d", time.localtime(date_range[1]))
            lines.append(f"Date range: {first} to {last}")
        lines.append("")

        n_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        lines.append(
            f"Rows currently in the live conversation-memory table: {n_messages} "
            "(lower than the question count above is normal -- this table is wiped "
            "whenever someone types \"reset\"/\"new question\"/\"start over\")"
        )
        lines.append("")

        lines.append("Questions per phone number (all-time, busiest first):")
        for phone, count in conn.execute(
            "SELECT phone_number, COUNT(*) FROM qa_log GROUP BY phone_number ORDER BY 2 DESC"
        ):
            lines.append(f"  {phone}: {count}")
        lines.append("")

        cutoff = time.time() - days * 86400
        lines.append(f"Questions per day, last {days} day(s):")
        rows = conn.execute(
            "SELECT date(created_at, 'unixepoch', 'localtime'), COUNT(*) "
            "FROM qa_log WHERE created_at >= ? GROUP BY 1 ORDER BY 1",
            (cutoff,),
        ).fetchall()
        if not rows:
            lines.append(f"  No questions in the last {days} day(s).")
        else:
            for day, count in rows:
                lines.append(f"  {day}: {count}")

        return "\n".join(lines)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="window for the per-day trend")
    args = parser.parse_args()
    print(generate_report(args.days))
