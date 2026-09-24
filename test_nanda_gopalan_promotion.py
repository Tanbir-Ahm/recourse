"""
test_nanda_gopalan_promotion.py -- promotes Nanda Gopalan v State of Kerala from the pilot pool to
the core corpus. Written BEFORE the promotion.

WHY THIS EXISTS (2026-09-24): judgment_promotion_assistant.py drafted a summary + verified quote
for this case; independently reading the full judgment (pilot_corpus/nanda_gopalan_v_state_of_
kerala.json) confirmed the draft accurate AND found unusually strong corroboration -- this 2015
judgment independently quotes both Mathai v State of Kerala (already in the core 46-case corpus)
and Anwarul Haq v State of Uttar Pradesh (promoted earlier this same session) verbatim, at length,
reaffirming both as still-good-law. Unlike Anwarul Haq, nothing important was missing from the
tool's original draft -- promoted with the single quote as originally drafted.

Run: python -X utf8 test_nanda_gopalan_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/nanda_gopalan_v_state_of_kerala_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 11, f"all 11 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors stripped")

import importlib
import retrieval
importlib.reload(retrieval)

check("nanda_gopalan" in retrieval._JUDGMENT_CHUNK_FILES, "auto-registered as 'nanda_gopalan'")

paras = retrieval.get_judgment_paragraphs("nanda_gopalan", ["fallback_4"])
check(paras is not None and len(paras) == 1, f"the chosen paragraph resolves -- got {paras and len(paras)}")
if paras:
    text_norm = " ".join(paras[0]["text"].split())
    check("we do no find any ground to interfere with the conviction" in text_norm,
          "the tool-verified quote (sentence reduction despite non-compoundability) is genuinely present")
    check(paras[0]["case_name"] == "Nanda Gopalan v State of Kerala", "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

ON_POINT_QUESTION = (
    "My relative and I settled our dispute privately after he was charged under section 326 IPC "
    "for grievous hurt against me. Can the case be dropped since we've compromised, or reduce his "
    "punishment at least since we made up?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."

matched = jdm.match_judgment_doctrine(ON_POINT_QUESTION)
check(any("nanda" in k.lower() or "compound" in k.lower() for k in matched),
      f"the on-point question triggers the new entry -- matched keys: {matched}")
check(not any("nanda" in k.lower() or "compound" in k.lower()
              for k in jdm.match_judgment_doctrine(UNRELATED_QUESTION)),
      "a completely unrelated question never triggers this")

override = jdm.get_judgment_doctrine_override(ON_POINT_QUESTION)
entries = [o for o in override if o.get("case_name") == "Nanda Gopalan v State of Kerala"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Nanda Gopalan -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")
    check("interfere with the conviction" in entries[0]["text"], "the real text reaches the match dict")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
