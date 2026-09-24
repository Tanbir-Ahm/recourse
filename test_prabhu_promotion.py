"""
test_prabhu_promotion.py -- promotes Prabhu v State of Madhya Pradesh from the pilot pool to the
core corpus. Written BEFORE the promotion.

WHY THIS EXISTS (2026-09-24): judgment_promotion_assistant.py drafted a summary + verified quote
for this case; independently reading the full judgment (pilot_corpus/prabhu_v_state_of_madhya_
pradesh.json) confirmed the draft accurate and complete -- promoted with the single quote as
originally drafted, same as Nanda Gopalan. Same judge (Dr. Arijit Pasayat) as Anwarul Haq, and this
judgment explicitly cites Mathai v State of Kerala (already in the core corpus) as the source of
its reasoning -- another independent corroboration of Mathai's continued good-law status.

Run: python -X utf8 test_prabhu_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/prabhu_v_state_of_madhya_pradesh_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 17, f"all 17 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors stripped")

import importlib
import retrieval
importlib.reload(retrieval)

check("prabhu" in retrieval._JUDGMENT_CHUNK_FILES, "auto-registered as 'prabhu'")

paras = retrieval.get_judgment_paragraphs("prabhu", ["13"])
check(paras is not None and len(paras) == 1, f"the chosen paragraph resolves -- got {paras and len(paras)}")
if paras:
    text_norm = " ".join(paras[0]["text"].split())
    check("no such thing as a regular or earmarked weapon" in text_norm,
          "the tool-verified quote (the dangerous-weapon test) is genuinely present")
    check(paras[0]["case_name"] == "Prabhu v State of Madhya Pradesh", "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

ON_POINT_QUESTION = (
    "I was accused of grievous hurt under section 326 IPC for hitting someone with a stick during "
    "a fight. Does a stick even count as a dangerous weapon, or only knives and guns?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."

matched = jdm.match_judgment_doctrine(ON_POINT_QUESTION)
check("what_makes_a_weapon_dangerous_for_grievous_hurt" in matched,
      f"the on-point question triggers the new entry -- matched keys: {matched}")
check("what_makes_a_weapon_dangerous_for_grievous_hurt" not in jdm.match_judgment_doctrine(UNRELATED_QUESTION),
      "a completely unrelated question never triggers this")

override = jdm.get_judgment_doctrine_override(ON_POINT_QUESTION)
entries = [o for o in override if o.get("case_name") == "Prabhu v State of Madhya Pradesh"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Prabhu -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")
    check("earmarked weapon" in entries[0]["text"], "the real text reaches the match dict")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
