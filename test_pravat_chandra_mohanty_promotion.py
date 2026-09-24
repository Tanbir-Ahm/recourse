"""
test_pravat_chandra_mohanty_promotion.py -- promotes Pravat Chandra Mohanty v State of Odisha from
the pilot pool to the core corpus. Written BEFORE the promotion.

WHY THIS EXISTS (2026-09-24): judgment_promotion_assistant.py drafted a summary + verified quote
for this case; independently reading the full 35-page judgment (pilot_corpus/pravat_chandra_
mohanty_v_state_of_odisha.json) confirmed the draft's central factual claim -- that this is a
genuine custodial-violence death case, not an embellishment -- and confirmed the Court's actual
holding (refused to compound the offence, citing the gravity of police custodial violence).
Promoted with the single quote as originally drafted; the case's separate sentence-reduction
point is deliberately left uncited here since it overlaps with (and is better covered by) the
Nanda Gopalan entry promoted earlier this same session.

Run: python -X utf8 test_pravat_chandra_mohanty_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/pravat_chandra_mohanty_v_state_of_odisha_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 56, f"all 56 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors stripped")

import importlib
import retrieval
importlib.reload(retrieval)

check("pravat_chandra_mohanty" in retrieval._JUDGMENT_CHUNK_FILES, "auto-registered as 'pravat_chandra_mohanty'")

paras = retrieval.get_judgment_paragraphs("pravat_chandra_mohanty", ["30"])
check(paras is not None and len(paras) == 1, f"the chosen paragraph resolves -- got {paras and len(paras)}")
if paras:
    text_norm = " ".join(paras[0]["text"].split())
    check("not automatic nor it has to be mechanical" in text_norm,
          "the tool-verified quote (compounding leave is not automatic) is genuinely present")
    check(paras[0]["case_name"] == "Pravat Chandra Mohanty v State of Odisha", "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

ON_POINT_QUESTION = (
    "The police officers who assaulted my brother in custody are offering to pay compensation if "
    "we agree to compound the case under section 324. Can the court just let the case be settled "
    "like this since they're offering money?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."

matched = jdm.match_judgment_doctrine(ON_POINT_QUESTION)
check("compounding_not_automatic_for_custodial_or_public_office_offences" in matched,
      f"the on-point question triggers the new entry -- matched keys: {matched}")
check("compounding_not_automatic_for_custodial_or_public_office_offences" not in jdm.match_judgment_doctrine(UNRELATED_QUESTION),
      "a completely unrelated question never triggers this")

override = jdm.get_judgment_doctrine_override(ON_POINT_QUESTION)
entries = [o for o in override if o.get("case_name") == "Pravat Chandra Mohanty v State of Odisha"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Pravat Chandra Mohanty -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")
    check("not automatic" in entries[0]["text"], "the real text reaches the match dict")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
