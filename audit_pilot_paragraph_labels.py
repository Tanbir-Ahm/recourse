
"""
audit_pilot_paragraph_labels.py

A cheap, fully automatic, non-legal check over pilot_chunks/*.json: does the same
paragraph_number get attached to two genuinely DIFFERENT pieces of text within one case?

WHY THIS EXISTS (2026-09-26): found by accident while investigating a real WhatsApp bug (an NDPS
case surfacing under an unrelated BNS question) -- Tofan Singh v State of Tamil Nadu's pilot_chunks
file had FOUR different, unrelated pieces of text all labelled "paragraph 5" (a procedural
arguments paragraph, a drug-trafficking commentary paragraph, an Inspector-General powers clause,
and a cognizability clause). "Paragraph 5 of Tofan Singh" therefore didn't reliably point at one
specific passage at all -- whichever one the search happened to pick, the citation shown to a real
person would look equally confident and equally specific either way.

That case has since been deleted (it was promoted to the core corpus; see memory: "pilot tier
leftover copy cleanup"), so the collision that was actually FOUND is already gone. This script
exists to answer the next, more important question: is the SAME mistake sitting undetected in any
of the pilot cases that are still there? It only found the first instance by chance, while looking
closely for an unrelated reason -- this makes checking for it a standing, repeatable step instead
of something that only gets caught by luck.

This is NOT a legal judgment call -- it never reads or evaluates what a paragraph SAYS, only
whether its label is unambiguous. Pure Python, no API calls, no network. Run:
    python audit_pilot_paragraph_labels.py                 # pilot_chunks/, the default
    python audit_pilot_paragraph_labels.py --dir some/dir   # any other chunk directory
"""
import argparse
import glob
import json
import os


def find_paragraph_label_collisions(chunk_dir: str = "pilot_chunks") -> list:
    """Every (file, paragraph_number) pair that maps to more than one DISTINCT text within the
    same case file. Only checks genuinely numeric paragraph_number values (chunk_method ==
    'paragraph_number') -- a fixed_size_fallback chunk never claims a real paragraph number in the
    first place (see pilot_tier_search.format_pilot_result's own _NUMERIC_PARAGRAPH check), so
    there is nothing to collide there.

    Returns a list of {'file', 'case_name', 'paragraph_number', 'distinct_texts'} -- empty means
    clean. Never raises on a malformed file; reports it as its own finding instead, since a file
    this script can't even parse is itself worth a person's attention."""
    findings = []
    for path in sorted(glob.glob(os.path.join(chunk_dir, "*_chunks.json"))):
        fname = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as fh:
                chunks = json.load(fh)
        except Exception as exc:
            findings.append({
                "file": fname, "case_name": None, "paragraph_number": None,
                "distinct_texts": None, "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        seen = {}  # paragraph_number -> {text: first-seen chunk index}
        case_name = None
        for c in chunks:
            case_name = c.get("case_name", case_name)
            if c.get("chunk_method") != "paragraph_number":
                continue
            pn = c.get("paragraph_number")
            if not (isinstance(pn, str) and pn.strip().isdigit()):
                continue
            text = c.get("text", "")
            seen.setdefault(pn, {})[text] = True

        for pn, texts in seen.items():
            if len(texts) > 1:
                findings.append({
                    "file": fname, "case_name": case_name, "paragraph_number": pn,
                    "distinct_texts": len(texts), "error": None,
                })
    return findings


def _report(findings: list, chunk_dir: str) -> str:
    if not findings:
        return f"Clean -- no paragraph-label collisions found in {chunk_dir}."
    lines = [f"{len(findings)} problem(s) found in {chunk_dir}:"]
    for f in findings:
        if f["error"]:
            lines.append(f"  {f['file']}: could not read this file -- {f['error']}")
        else:
            lines.append(
                f"  {f['file']} ({f['case_name']}): 'paragraph {f['paragraph_number']}' points to "
                f"{f['distinct_texts']} different, unrelated pieces of text -- ambiguous, needs a "
                f"manual re-chunk before this case can be trusted to cite the right one"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="pilot_chunks", help="chunk directory to audit")
    args = parser.parse_args()
    print(_report(find_paragraph_label_collisions(args.dir), args.dir))
