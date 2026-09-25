"""
test_sakharam_promotion.py -- promotes Sakharam v State of Madhya Pradesh from the pilot pool to
the core corpus. Written BEFORE the promotion.

WHY THIS EXISTS (2026-09-25): judgment_promotion_assistant.py's verified quote (fallback_3, "mere
presence isn't sufficient to convict") checked out accurate on independent review of the full
judgment -- and that same chunk turned out to already contain two MORE real, separate holdings the
draft's quote didn't surface: absence of motive as a "plus-point" for the accused in a
circumstantial case, and a failed defence plea (alibi/suicide theory) NOT itself being evidence of
guilt. A fourth point (juvenile-innocence presumption) lives in a different chunk (fallback_4) and
is added as a second paragraph, framed carefully since it cites the since-superseded Children Act,
1960 -- the underlying evidentiary PRINCIPLE (heightened proof standard when youth triggers an
innocence presumption) is what's reusable, not that specific old Act.

Run: python -X utf8 test_sakharam_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/sakharam_v_state_of_madhya_pradesh_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 4, f"all 4 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors stripped")

import importlib
import retrieval
importlib.reload(retrieval)

check("sakharam" in retrieval._JUDGMENT_CHUNK_FILES, "auto-registered as 'sakharam'")

paras = retrieval.get_judgment_paragraphs("sakharam", ["fallback_3", "fallback_4"])
check(paras is not None and len(paras) == 2, f"both chosen paragraphs resolve -- got {paras and len(paras)}")
if paras:
    combined_norm = " ".join(" ".join(p["text"].split()) for p in paras).lower()
    check("this circumstance alone is not sufficient to conclude" in combined_norm,
          "the tool-verified quote (presence insufficient) is genuinely present")
    check("no adverse inference can be drawn against the appellant" in combined_norm,
          "the independently-found failed-defence-plea point is genuinely present, same chunk")
    check("plus-point for the accused" in combined_norm,
          "the absence-of-motive point is genuinely present, same chunk")
    check("presumption of juvenile-innocence" in combined_norm,
          "the juvenile-innocence point (fallback_4) is genuinely present")
    check(all(p["case_name"] == "Sakharam v State of Madhya Pradesh" for p in paras), "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

PRESENCE_QUESTION = (
    "I was present when my relative died from a gunshot in the room, but I didn't shoot them. "
    "Can the police charge me with murder just because I was there and there's no other "
    "evidence?"
)
FAILED_DEFENSE_QUESTION = (
    "My alibi didn't hold up in court and got rejected. Does that automatically make me look "
    "guilty, or count as evidence against me?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."

matched_presence = jdm.match_judgment_doctrine(PRESENCE_QUESTION)
check("mere_presence_and_circumstantial_evidence_insufficient_for_murder" in matched_presence,
      f"the presence question triggers the entry -- matched keys: {matched_presence}")

matched_defense = jdm.match_judgment_doctrine(FAILED_DEFENSE_QUESTION)
check("mere_presence_and_circumstantial_evidence_insufficient_for_murder" in matched_defense,
      f"the failed-defence question also triggers the SAME entry -- matched keys: {matched_defense}")

check("mere_presence_and_circumstantial_evidence_insufficient_for_murder" not in jdm.match_judgment_doctrine(UNRELATED_QUESTION),
      "a completely unrelated question never triggers this")

override = jdm.get_judgment_doctrine_override(PRESENCE_QUESTION)
entries = [o for o in override if o.get("case_name") == "Sakharam v State of Madhya Pradesh"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Sakharam -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
