"""
test_anwarul_haq_promotion.py -- promotes Anwarul Haq v State of Uttar Pradesh from the pilot pool
to the core corpus, via judgment_promotion_assistant.py's drafting + the same human-verification
step used for Jagrup Singh. Written BEFORE the promotion.

WHY THIS EXISTS (2026-09-24): judgment_promotion_assistant.py drafted a summary + verified quote
for this case (real, confirmed against the source text). Independently reading the full judgment
(pilot_corpus/anwarul_haq_v_state_of_uttar_pradesh.json) confirmed the draft was accurate but
INCOMPLETE -- it missed a second, genuinely useful legal test sitting in the same chunk: "the
expression 'an instrument... likely to cause death' should be construed with reference to the
NATURE of the instrument, not the MANNER of its use." Both the tool-verified quote and this
second sentence live in the SAME chunk (paragraph_number "2" -- really the passage following the
judgment's own injury-list item 2, not a real numbered judgment paragraph; this old, 2005
judgment has no real paragraph numbering, and the chunker's paragraph-number heuristic latched
onto the doctor's injury list instead), so one paragraph reference covers both.

Run: python -X utf8 test_anwarul_haq_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/anwarul_haq_v_state_of_uttar_pradesh_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 3, f"all 3 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors stripped, same as every other promoted file")

import importlib
import retrieval
importlib.reload(retrieval)

check("anwarul_haq" in retrieval._JUDGMENT_CHUNK_FILES,
      "auto-registered as 'anwarul_haq' (stem before _v_), same convention as every other judgment")

paras = retrieval.get_judgment_paragraphs("anwarul_haq", ["2"])
check(paras is not None and len(paras) == 1, f"the chosen paragraph resolves -- got {paras and len(paras)}")
if paras:
    text = paras[0]["text"]
    text_norm = " ".join(text.split())  # the source PDF line-wraps mid-sentence ("its \nuse.")
    check("nature of the instrument and not the manner of its use" in text_norm,
          "the substantive dangerous-weapon test (missed by the tool's own draft, added on independent review) is genuinely present")
    check("cannot be a factor to discard the evidence" in text,
          "the tool-verified non-recovery-of-weapon quote is genuinely present in the same chunk")
    check(paras[0]["case_name"] == "Anwarul Haq v State of Uttar Pradesh", "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

ON_POINT_QUESTION = (
    "The police say I attacked someone with a knife but the knife was never recovered during the "
    "investigation. Can I still be convicted if the weapon itself was never found?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."

matched = jdm.match_judgment_doctrine(ON_POINT_QUESTION)
check(any("anwarul" in k.lower() or "weapon_not_recovered" in k.lower() for k in matched),
      f"the on-point question triggers the new entry -- matched keys: {matched}")
check(not any("anwarul" in k.lower() or "weapon_not_recovered" in k.lower()
              for k in jdm.match_judgment_doctrine(UNRELATED_QUESTION)),
      "a completely unrelated question never triggers this")

override = jdm.get_judgment_doctrine_override(ON_POINT_QUESTION)
entries = [o for o in override if o.get("case_name") == "Anwarul Haq v State of Uttar Pradesh"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Anwarul Haq -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")
    check("nature of the instrument" in entries[0]["text"], "the real text reaches the match dict")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
