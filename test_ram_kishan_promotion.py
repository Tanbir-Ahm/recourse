"""
test_ram_kishan_promotion.py -- promotes State of Uttar Pradesh v Ram Kishan from the pilot pool
to the core corpus. Written BEFORE the promotion.

WHY THIS EXISTS (2026-09-25): this is the case that originally exposed the pilot-tier-to-prose
gap (Q1 of the very first live-testing round) -- its summary claimed a "material prejudice from
altering a conviction on appeal" holding, but the tool's verified quote only supported a separate,
more generic point (the standard for interfering with an acquittal on appeal). Independent review
of the full judgment found the real material-prejudice sentence -- and found it is literally SPLIT
across two fixed-size chunks (fallback_7 / fallback_8) by the chunking itself. fallback_7 also
contains a rich, case-specific holding neither tool draft surfaced: the Court assessed each
co-accused's INDIVIDUAL liability by their actual role (physically restraining the victim vs.
merely shouting encouragement), not a blanket conviction. Given judgment_doctrine_map.py caps
each entry at 2 paragraphs, promoted with fallback_7 + fallback_8 (both case-specific holdings),
dropping the more generic, boilerplate-ish appellate-review-standard quote the tool originally
selected.

Run: python -X utf8 test_ram_kishan_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/state_of_uttar_pradesh_v_ram_kishan_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 8, f"all 8 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors stripped")

import importlib
import retrieval
importlib.reload(retrieval)

check("state_of_uttar_pradesh_v_ram_kishan" in retrieval._JUDGMENT_CHUNK_FILES,
      "auto-registered under the FULL stem -- NOT 'ram_kishan': since the case is 'State of "
      "Uttar Pradesh v Ram Kishan' (state listed first), the short auto-key "
      "('state_of_uttar_pradesh'.split('_v_')[0]) is the generic state name, not the distinctive "
      "second party -- a real bug this test caught before it shipped")

paras = retrieval.get_judgment_paragraphs("state_of_uttar_pradesh_v_ram_kishan", ["fallback_7", "fallback_8"])
check(paras is not None and len(paras) == 2, f"both chosen paragraphs resolve -- got {paras and len(paras)}")
if paras:
    # order matters: concatenating fallback_7 then fallback_8 should complete the split sentence
    combined = paras[0]["text"] + paras[1]["text"]
    combined_norm = " ".join(combined.split()).lower()
    check("no prejudice" in combined_norm and "is caused to the" in combined_norm,
          "the START of the material-prejudice sentence (fallback_7) is present")
    check("which they had to meet in the trial" in combined_norm,
          "the END of the same sentence (fallback_8, split by the chunker) is present -- together "
          "these form the complete holding, not half of it")
    check("found  guilty" in " ".join(paras[0]["text"].split()) or "found guilty" in combined_norm,
          "the individual-liability-by-role point (Ram Kishan's own lesser conviction) is present")
    check(all(p["case_name"] == "State of Uttar Pradesh v Ram Kishan" for p in paras), "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

MATERIAL_PREJUDICE_QUESTION = (
    "I was originally accused under section 103 for murder along with others as an unlawful "
    "assembly, but now the court wants to convict me alone under section 118 for grievous hurt "
    "instead. Can they change the charge against me like this without telling me in advance, and "
    "is that unfair to me?"
)
ROLE_QUESTION = (
    "During a group attack, I only shouted at everyone to beat the victim but never touched him "
    "myself -- someone else did the actual stabbing. Am I guilty of the same serious offence as "
    "the person who actually attacked him?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."

matched_prejudice = jdm.match_judgment_doctrine(MATERIAL_PREJUDICE_QUESTION)
check("altering_conviction_on_appeal_is_not_material_prejudice" in matched_prejudice,
      f"the material-prejudice question triggers the entry -- matched keys: {matched_prejudice}")

matched_role = jdm.match_judgment_doctrine(ROLE_QUESTION)
check("altering_conviction_on_appeal_is_not_material_prejudice" in matched_role,
      f"the individual-role question also triggers the SAME entry -- matched keys: {matched_role}")

check("altering_conviction_on_appeal_is_not_material_prejudice" not in jdm.match_judgment_doctrine(UNRELATED_QUESTION),
      "a completely unrelated question never triggers this")

override = jdm.get_judgment_doctrine_override(MATERIAL_PREJUDICE_QUESTION)
entries = [o for o in override if o.get("case_name") == "State of Uttar Pradesh v Ram Kishan"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Ram Kishan -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")
    # fallback_7 and fallback_8 arrive as TWO separate match dicts (the round-robin system's normal
    # shape -- each paragraph is its own labeled block in the prompt), so check across both, not
    # just the first entry, for the complete split sentence to actually reach the model.
    all_entry_text = " ".join(" ".join(e["text"].split()) for e in entries)
    check("which they had to meet in the trial" in all_entry_text,
          "the complete (not split-in-half) material-prejudice text reaches the model, across "
          "both of Ram Kishan's match entries")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
