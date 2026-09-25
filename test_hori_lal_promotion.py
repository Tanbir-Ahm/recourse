"""
test_hori_lal_promotion.py -- promotes Hori Lal v State of Uttar Pradesh from the pilot pool to
the core corpus. Written BEFORE the promotion.

WHY THIS EXISTS (2026-09-25): judgment_promotion_assistant.py drafted a verified quote (real,
confirmed) about FIR "ante-timing" not being fatal to a case, but flagged it for extra scrutiny
since the exact wording ("we do not think that...") doesn't match any of the tool's holding-
language markers -- confirmed on independent review to be a false alarm in the CHECK, not a real
problem with the quote. Independent review of the full judgment also found a second, genuinely
separate and reusable passage the tool's draft did not select: the Court's own explanation of how
Section 149 IPC ("common object" / unlawful assembly liability) works, in a different chunk.
Promoted with BOTH paragraphs, same pattern as Anwarul Haq.

Run: python -X utf8 test_hori_lal_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/hori_lal_v_state_of_uttar_pradesh_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 7, f"all 7 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors stripped")

import importlib
import retrieval
importlib.reload(retrieval)

check("hori_lal" in retrieval._JUDGMENT_CHUNK_FILES, "auto-registered as 'hori_lal'")

paras = retrieval.get_judgment_paragraphs("hori_lal", ["fallback_3", "fallback_5"])
check(paras is not None and len(paras) == 2, f"both chosen paragraphs resolve -- got {paras and len(paras)}")
if paras:
    combined_norm = " ".join(" ".join(p["text"].split()) for p in paras).lower()
    check("would negate the entire prosecution story" in combined_norm,
          "the tool-verified FIR-timing quote (fallback_3) is genuinely present")
    check("common object would mean the purpose or design shared" in combined_norm,
          "the independently-added common-object/Section 149 passage (fallback_5) is genuinely present")
    check(all(p["case_name"] == "Hori Lal v State of Uttar Pradesh" for p in paras), "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

FIR_TIMING_QUESTION = (
    "The police only sent my FIR to the magistrate a day late. Does that delay in reaching "
    "the magistrate ruin the whole case against me, or is it not that serious?"
)
COMMON_OBJECT_QUESTION = (
    "I was just standing with a group of people when one of them suddenly attacked someone. "
    "Can I be held responsible too just for being part of the group, even though I didn't do "
    "anything myself?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."

matched_fir = jdm.match_judgment_doctrine(FIR_TIMING_QUESTION)
check("fir_ante_timing_delay_not_automatically_fatal" in matched_fir,
      f"the FIR-timing question triggers the entry -- matched keys: {matched_fir}")

matched_common_object = jdm.match_judgment_doctrine(COMMON_OBJECT_QUESTION)
check("fir_ante_timing_delay_not_automatically_fatal" in matched_common_object,
      f"the common-object question also triggers the SAME entry (both paragraphs live under one "
      f"doctrine key) -- matched keys: {matched_common_object}")

check("fir_ante_timing_delay_not_automatically_fatal" not in jdm.match_judgment_doctrine(UNRELATED_QUESTION),
      "a completely unrelated question never triggers this")

override = jdm.get_judgment_doctrine_override(FIR_TIMING_QUESTION)
entries = [o for o in override if o.get("case_name") == "Hori Lal v State of Uttar Pradesh"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Hori Lal -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
