
"""
answer_cache_report.py

The human-review half of answer_cache.py (see that module's docstring for
the full design). Lists every confident ('single_match') answer the tool
has generated, grouped by the exact set of legal sources it used, so a
person can decide which repeat questions are worth serving from cache
instead of paying for a fresh answer every time -- and separately lists
what's currently approved and when each approval expires.

This script changes nothing on its own read path; --approve / --revoke
are the only things that change what gets served, and both require an
explicit cache key a person chose after reading the report -- same "a
human reads the report, decides, and only then something changes"
discipline as whatsapp_weekly_report.py.

Run:
    python answer_cache_report.py                     # show the report
    python answer_cache_report.py --approve <key>      # approve for 30 days
    python answer_cache_report.py --approve <key> --ttl-days 14
    python answer_cache_report.py --revoke <key>       # undo an approval
"""
import argparse
import time

import answer_cache


def generate_report() -> str:
    candidates = answer_cache.list_candidates()
    approved = answer_cache.list_approved()
    approved_keys = {a["cache_key"] for a in approved}

    lines = []
    lines.append("Answer-reuse cache report")
    lines.append("")

    lines.append(f"--- {len(approved)} currently approved (served from cache) ---")
    if not approved:
        lines.append("  none yet")
    else:
        for a in approved:
            days_left = (a["expires_at"] - time.time()) / 86400
            status = f"expires in {days_left:.1f} day(s)" if days_left > 0 else "EXPIRED (will regenerate)"
            lines.append(f"  {a['description']} -- {status}")
            lines.append(f"      key: {a['cache_key']}")
    lines.append("")

    unapproved = [c for c in candidates if c["cache_key"] not in approved_keys]
    lines.append(f"--- {len(unapproved)} candidate(s) awaiting review ---")
    if not unapproved:
        lines.append("  none -- nothing new to approve")
    else:
        lines.append("Most-repeated first (a repeat count of 1 just means it's been asked once so far):")
        lines.append("")
        for c in unapproved:
            lines.append(f"  asked {c['hit_count']}x -- {c['description']}")
            lines.append(f"      e.g. \"{c['sample_question']}\"")
            lines.append(f"      key: {c['cache_key']}")
        lines.append("")
        lines.append("Approve one with: python answer_cache_report.py --approve <key>")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--approve", metavar="KEY", help="approve a candidate (by its cache key) for reuse")
    parser.add_argument("--ttl-days", type=float, default=answer_cache.DEFAULT_TTL_DAYS,
                         help=f"days an approval stays valid (default {answer_cache.DEFAULT_TTL_DAYS})")
    parser.add_argument("--revoke", metavar="KEY", help="undo an approval immediately")
    args = parser.parse_args()

    if args.approve:
        ok = answer_cache.approve(args.approve, ttl_days=args.ttl_days)
        print(f"Approved for {args.ttl_days} day(s)." if ok else "No candidate with that key -- check the report for the full key.")
    elif args.revoke:
        ok = answer_cache.revoke(args.revoke)
        print("Revoked." if ok else "No approved entry with that key.")
    else:
        print(generate_report())
