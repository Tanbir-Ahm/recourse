
"""
candidate_pipeline_report.py

The human-review CLI for candidate_pipeline.py -- lets a person list,
inspect, approve, and reject staged judgment candidates directly from
the terminal, without needing to ask Claude to run a Python snippet
each time. Same shape as answer_cache_report.py's --approve/--revoke
pattern, applied here.

IMPORTANT: --approve only records your decision in candidate_anchors.db
-- it does NOT make the case live. Promoting an approved candidate into
a real, trusted answer still needs the deliberate follow-up (a chunk
file + a doctrine map entry with real trigger phrases + tests), because
picking good trigger phrases is a judgment call, not something safe to
automate (see candidate_pipeline.py's module docstring). Tell Claude
which candidate you approved and it'll do that follow-up work.

Run:
    python candidate_pipeline_report.py                       # list pending
    python candidate_pipeline_report.py --show 3              # full evidence for one candidate
    python candidate_pipeline_report.py --approve 3 --note "looks solid"
    python candidate_pipeline_report.py --reject 3 --note "corroborating case was off point"
"""
import argparse

import candidate_pipeline


def _summary_line(c: dict) -> str:
    corr = c["corroboration"]
    cross = "✓ second source" if corr.get("cross_source", {}).get("found_in_vaquill") else "✗ second source"
    n_cite = len(corr.get("citation_corroboration", {}).get("corroborating_documents", []))
    rank = corr.get("independent_agreement", {}).get("best_matching_rank")
    rank_txt = f"rank {rank}" if rank else "no independent match"
    return f"[{cross} | {n_cite} citing courts confirm | {rank_txt}]"


def generate_report() -> str:
    lines = ["Candidate judgment pipeline report", ""]

    pending = candidate_pipeline.list_candidates(status="pending")
    lines.append(f"--- {len(pending)} awaiting your review ---")
    if not pending:
        lines.append("  none right now")
    for c in pending:
        lines.append(f"  #{c['id']} {c['case_name']} ({c.get('citation') or 'no citation recorded'})")
        lines.append(f"      domain: {c['domain']}  {_summary_line(c)}")
    lines.append("")

    decided = candidate_pipeline.list_candidates(status="approved") + candidate_pipeline.list_candidates(status="rejected")
    decided.sort(key=lambda c: c.get("decided_at") or 0, reverse=True)
    if decided:
        lines.append(f"--- {len(decided)} already decided ---")
        for c in decided[:10]:
            lines.append(f"  #{c['id']} {c['case_name']} -- {c['status'].upper()}"
                         + (f" ({c['reviewer_note']})" if c.get("reviewer_note") else ""))
        lines.append("")

    lines.append("Approve: python candidate_pipeline_report.py --approve <id> --note \"...\"")
    lines.append("Reject:  python candidate_pipeline_report.py --reject <id> --note \"...\"")
    lines.append("Full evidence for one candidate: python candidate_pipeline_report.py --show <id>")
    return "\n".join(lines)


def _show(candidate_id: int) -> str:
    c = candidate_pipeline.get_candidate(candidate_id)
    if c is None:
        return f"No candidate with id {candidate_id}."
    lines = [
        f"#{c['id']} {c['case_name']}", c.get("citation") or "(no citation recorded)",
        f"status: {c['status']}", "",
        f"Proposed holding{' (' + c['paragraph_number'] + ')' if c.get('paragraph_number') else ''}:",
        c["holding_text"], "",
    ]
    corr = c["corroboration"]
    cross = corr.get("cross_source", {})
    lines.append(f"Independent second source: found_in_vaquill={cross.get('found_in_vaquill')}")
    cite = corr.get("citation_corroboration", {})
    lines.append(f"Citing courts: {len(cite.get('corroborating_documents', []))} of "
                 f"{cite.get('documents_scanned', 0)} confirm the same holding")
    for d in cite.get("corroborating_documents", [])[:5]:
        lines.append(f"  - {d.get('title')} ({d.get('court')})")
        lines.append(f"    \"{d.get('matched_headline')}\"")
    agree = corr.get("independent_agreement", {})
    lines.append(f"Independent re-derivation: best_matching_rank={agree.get('best_matching_rank')}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--approve", type=int, metavar="ID", help="approve a pending candidate by id")
    parser.add_argument("--reject", type=int, metavar="ID", help="reject a pending candidate by id")
    parser.add_argument("--note", default="", help="your reasoning, attached to the decision")
    parser.add_argument("--show", type=int, metavar="ID", help="print full evidence for one candidate")
    args = parser.parse_args()

    if args.approve:
        ok = candidate_pipeline.approve(args.approve, note=args.note)
        print(f"Approved #{args.approve}." if ok else "No pending candidate with that id.")
    elif args.reject:
        ok = candidate_pipeline.reject(args.reject, note=args.note)
        print(f"Rejected #{args.reject}." if ok else "No pending candidate with that id.")
    elif args.show:
        print(_show(args.show))
    else:
        print(generate_report())
