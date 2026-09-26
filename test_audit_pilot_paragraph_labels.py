
"""
test_audit_pilot_paragraph_labels.py

Regression suite for audit_pilot_paragraph_labels.py -- proves the collision detector actually
catches the real failure it was built for (found 2026-09-26: Pravat Chandra Mohanty v State of
Odisha had roughly half its paragraph numbers pointing to two different, unrelated pieces of text
each), and that it stays quiet on everything that ISN'T that.

Pure Python, synthetic fixture files in a temp directory -- no network, no API calls, does not
touch the real pilot_chunks/ directory. Run directly:
    python -X utf8 test_audit_pilot_paragraph_labels.py
"""
import json
import os
import shutil
import tempfile

from audit_pilot_paragraph_labels import find_paragraph_label_collisions

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


def _write(chunk_dir, filename, chunks):
    with open(os.path.join(chunk_dir, filename), "w", encoding="utf-8") as fh:
        json.dump(chunks, fh)


tmp_dir = tempfile.mkdtemp()
try:
    # ---- a clean case: every paragraph number appears exactly once ----
    _write(tmp_dir, "clean_case_chunks.json", [
        {"case_name": "Clean Case v State", "chunk_method": "paragraph_number", "paragraph_number": "1", "text": "First real paragraph."},
        {"case_name": "Clean Case v State", "chunk_method": "paragraph_number", "paragraph_number": "2", "text": "Second real paragraph."},
        {"case_name": "Clean Case v State", "chunk_method": "paragraph_number", "paragraph_number": "3", "text": "Third real paragraph."},
    ])

    # ---- the real failure shape: a quoted list's own numbering collides with the real paragraphs ----
    _write(tmp_dir, "colliding_case_chunks.json", [
        {"case_name": "Colliding Case v State", "chunk_method": "paragraph_number", "paragraph_number": "1", "text": "The real first paragraph, about the appeal."},
        {"case_name": "Colliding Case v State", "chunk_method": "paragraph_number", "paragraph_number": "2", "text": "The real second paragraph, about the facts."},
        # a quoted injury list, embedded inside a later real paragraph, whose OWN numbering
        # restarted from 1/2 and got mistaken for this document's own paragraph boundaries
        {"case_name": "Colliding Case v State", "chunk_method": "paragraph_number", "paragraph_number": "1", "text": "Pressure abrasion on the right leg."},
        {"case_name": "Colliding Case v State", "chunk_method": "paragraph_number", "paragraph_number": "2", "text": "Lacerated wound on the left knee."},
    ])

    # ---- an exact duplicate (same label, IDENTICAL text) is not a collision -- nothing ambiguous ----
    _write(tmp_dir, "exact_duplicate_chunks.json", [
        {"case_name": "Duplicate Case v State", "chunk_method": "paragraph_number", "paragraph_number": "5", "text": "The same paragraph, stored twice."},
        {"case_name": "Duplicate Case v State", "chunk_method": "paragraph_number", "paragraph_number": "5", "text": "The same paragraph, stored twice."},
    ])

    # ---- fixed_size_fallback chunks never claim a real paragraph number -- must never be flagged ----
    _write(tmp_dir, "fallback_case_chunks.json", [
        {"case_name": "Fallback Case v State", "chunk_method": "fixed_size_fallback", "paragraph_number": "chunk_1", "text": "Some text."},
        {"case_name": "Fallback Case v State", "chunk_method": "fixed_size_fallback", "paragraph_number": "chunk_2", "text": "Different text, same non-numeric label pattern."},
    ])

    # ---- a preamble label is not numeric -- must never be flagged even if it repeats ----
    _write(tmp_dir, "preamble_case_chunks.json", [
        {"case_name": "Preamble Case v State", "chunk_method": "paragraph_number", "paragraph_number": "preamble", "text": "Case caption text."},
        {"case_name": "Preamble Case v State", "chunk_method": "paragraph_number", "paragraph_number": "1", "text": "The one real paragraph."},
    ])

    # ---- a malformed file is reported as its own finding, never crashes the whole audit ----
    with open(os.path.join(tmp_dir, "broken_case_chunks.json"), "w", encoding="utf-8") as fh:
        fh.write("{ this is not valid JSON")

    findings = find_paragraph_label_collisions(tmp_dir)

    colliding = [f for f in findings if f["file"] == "colliding_case_chunks.json"]
    check(
        len(colliding) == 2 and {f["paragraph_number"] for f in colliding} == {"1", "2"},
        "the real failure shape (a quoted list's numbers colliding with real paragraphs) is caught, "
        "for both affected labels ('1' and '2'), not just one",
    )
    check(
        all(f["distinct_texts"] == 2 for f in colliding),
        "each collision correctly reports exactly 2 distinct texts, not just 'more than one'",
    )
    check(
        not any(f["file"] == "clean_case_chunks.json" for f in findings),
        "a genuinely clean case (every paragraph number appears once) is never flagged",
    )
    check(
        not any(f["file"] == "exact_duplicate_chunks.json" for f in findings),
        "the SAME text stored twice under the same label is not ambiguous, so it's not flagged -- "
        "only genuinely DIFFERENT text under the same label is a real problem",
    )
    check(
        not any(f["file"] == "fallback_case_chunks.json" for f in findings),
        "fixed_size_fallback chunks are never flagged -- they never claim a real paragraph number in the first place",
    )
    check(
        not any(f["file"] == "preamble_case_chunks.json" for f in findings),
        "a non-numeric label ('preamble') is never flagged even though it's a repeatable string across cases",
    )
    broken = [f for f in findings if f["file"] == "broken_case_chunks.json"]
    check(
        len(broken) == 1 and broken[0]["error"] is not None,
        "a malformed/unparseable chunk file is reported as its own finding, not silently skipped and not a crash",
    )

    # ---- the real pilot_chunks/ directory itself, right now, is clean ----
    # (this is the actual, permanent point of building this tool: it should be run against the
    # real directory from time to time, and 2026-09-26's real finding -- Pravat Chandra Mohanty --
    # has already been removed as a direct result of this same tool)
    real_findings = find_paragraph_label_collisions("pilot_chunks")
    check(
        real_findings == [],
        f"the real pilot_chunks/ directory is currently clean -- got {len(real_findings)} unexpected finding(s): {real_findings}",
    )

finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)


if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
