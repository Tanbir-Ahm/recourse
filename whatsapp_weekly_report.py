
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

By default only the two buckets worth a person's attention (thin,
technical_failure) get their raw question text printed -- confident and
out_of_scope questions are still counted in the "By confidence" summary,
but their text is deliberately left out, since a question the engine
already answered confidently isn't something that needs reviewing.

ADDED 2026-09-26 (real question asked: "why isn't the confident bucket's
text shown anywhere?") -- confidence here is the ENGINE's own self-report
of how sure it was, not an independent correctness check, so seeing the
confident/out_of_scope text too is a legitimate, permanent thing to want
(e.g. spot-checking that "confident" really did mean "correct"). --show
makes that a standing option instead of a one-off query:
    python whatsapp_weekly_report.py --show confident
    python whatsapp_weekly_report.py --show confident,out_of_scope
    python whatsapp_weekly_report.py --show all
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


_CATEGORY_HEADINGS = {
    "confident": "confidently-answered question(s)",
    "thin": "question(s) worth reviewing",
    "technical_failure": "technical failure(s) -- check the API/network, not the corpus",
    "out_of_scope": "out-of-scope question(s)",
}


def _raw_question_lines(rows: list, category: str) -> list:
    """Shared by every category's raw-question block below (thin,
    technical_failure, and -- since 2026-09-26 -- confident/out_of_scope
    on request via --show). A category whose rows span more than one
    underlying `state` (thin always does: no_match/adjacent_uncovered/
    conflicting_matches; out_of_scope can too) gets its own 'By reason'
    breakdown; a category that's always exactly one state (confident is
    always single_match) skips it, since a breakdown of one line is
    noise, not information."""
    cat_rows = [r for r in rows if r[3] == category]
    lines = [""]
    if not cat_rows:
        lines.append(f"No '{category}' questions this period.")
        return lines

    lines.append(f"--- {len(cat_rows)} {_CATEGORY_HEADINGS.get(category, category)} ---")
    lines.append("")
    state_counts = Counter(r[2] for r in cat_rows)
    if len(state_counts) > 1:
        lines.append("By reason:")
        for state, count in state_counts.most_common():
            lines.append(f"  {state}: {count}")
        lines.append("")
    lines.append("Raw questions, oldest first (read these for patterns):")
    for _phone, question, state, _confidence, created_at in cat_rows:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
        lines.append(f"  [{ts}] ({state}) {question}")
    return lines


def _questions_report(days: int = 7, show: tuple = ()) -> str:
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

    # thin and technical_failure are always shown -- these are the two
    # buckets worth reviewing by default (see module docstring). Anything
    # else in `show` (confident, out_of_scope, or 'all') is additive.
    requested = set(_CATEGORIES) if "all" in show else set(show)
    always_shown = ("thin", "technical_failure")
    for cat in always_shown:
        lines.extend(_raw_question_lines(rows, cat))
    for cat in _CATEGORIES:
        if cat in requested and cat not in always_shown:
            lines.extend(_raw_question_lines(rows, cat))

    return "\n".join(lines)


def _case_report(days: int = 7) -> str:
    """The CASE-command section: counts by outcome, cache-hit rate, median live
    fetch time. Never shows a phone number (case_lookup.event_summary only counts
    distinct people). A failure here must not take the rest of the report down."""
    try:
        import case_lookup
        s = case_lookup.event_summary(days)
    except Exception as exc:
        return f"CASE lookup usage: unavailable ({type(exc).__name__})"
    lines = [f"CASE lookup usage -- last {days} day(s)", f"Events: {s['total']} from {s['users']} distinct person(s)"]
    if not s["total"]:
        lines.append("No CASE commands used in this period.")
        return "\n".join(lines)
    for ev, n in sorted(s["by_event"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {ev}: {n}")
    if s["deliveries"]:
        lines.append(f"Judgments delivered: {s['deliveries']} ({s['cache_hits']} from cache)")
    if s["median_live_fetch_ms"] is not None:
        lines.append(f"Median time for a live (uncached) fetch: {s['median_live_fetch_ms'] / 1000:.0f}s")
    return "\n".join(lines)


def generate_report(days: int = 7, show: tuple = ()) -> str:
    return _questions_report(days, show) + "\n\n" + _case_report(days)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="how many days back to report on")
    parser.add_argument(
        "--show", default="",
        help="comma-separated: also print raw question text for these categories "
             "(confident, thin, technical_failure, out_of_scope, or 'all'). "
             "thin and technical_failure are always shown regardless.",
    )
    args = parser.parse_args()
    show = tuple(s.strip() for s in args.show.split(",") if s.strip())
    print(generate_report(args.days, show=show))
