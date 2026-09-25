"""
test_haidarali_kalubhai_promotion.py -- promotes State of Gujarat v Haidarali Kalubhai as the seed
of a NEW doctrine domain (accidental death / rash driving), not sourced from the original hurt/
assault pilot pool. Written BEFORE the doctrine-map entry existed.

Found via a scratch exploration of api.sci.gov.in's sequential JUDIS numbering scheme (ID 5735),
read in full and confirmed on point (old IPC 304A vs. 304 Part II / culpable homicide -- the line
between a genuine accident and a crime) before being built here, at the user's explicit instruction.

Run: python -X utf8 test_haidarali_kalubhai_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/state_of_gujarat_v_haidarali_kalubhai_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- chunked via chunk_judgments.py")

CORPUS_PATH = "corpus/state_of_gujarat_v_haidarali_kalubhai.json"
check(os.path.exists(CORPUS_PATH), f"{CORPUS_PATH} exists -- raw source saved, not just chunks")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 5, f"all 5 fallback chunks present -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors absent (curated, not semantic-search tier)")
check(all(c["chunk_method"] == "fixed_size_fallback" for c in promoted_chunks),
      "1976 judgment has no modern numbered-paragraph structure -- correctly fell back to fixed-size chunking")

import importlib
import retrieval
importlib.reload(retrieval)

check("state_of_gujarat_v_haidarali_kalubhai" in retrieval._JUDGMENT_CHUNK_FILES,
      "auto-registered under the FULL stem, not the naive post-split 'state_of_gujarat' key")

paras = retrieval.get_judgment_paragraphs("state_of_gujarat_v_haidarali_kalubhai", ["fallback_4", "fallback_5"])
check(paras is not None and len(paras) == 2, f"both chosen paragraphs resolve -- got {paras and len(paras)}")
if paras:
    text_norm = " ".join(" ".join(p["text"] for p in paras).split()).lower()
    check("totally excludes the ingredients" in text_norm,
          "the split-sentence 304A/culpable-homicide definitional test reads whole across both chunks")
    check("tangential" in text_norm and "loss of control" in text_norm,
          "the application-to-facts holding (loss of control, not intent) is genuinely present")
    check(all(p["case_name"] == "State of Gujarat v Haidarali Kalubhai" for p in paras),
          "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

ON_POINT_QUESTION = (
    "My brother was driving a truck and lost control, it hit someone and they died. He's been "
    "charged with murder but he never meant to kill anyone -- it was a genuine accident. Is that "
    "really murder?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."
HURT_QUESTION_NOT_THIS_CASE = (
    "I was attacked with a stick during a fight and suffered a grievous injury -- does that count "
    "as a dangerous weapon?"
)

matched = jdm.match_judgment_doctrine(ON_POINT_QUESTION)
check("rash_or_negligent_act_causing_death_is_not_culpable_homicide" in matched,
      f"the accidental-death question triggers the entry -- matched keys: {matched}")
check("rash_or_negligent_act_causing_death_is_not_culpable_homicide" not in jdm.match_judgment_doctrine(UNRELATED_QUESTION),
      "a completely unrelated question never triggers this")
check("rash_or_negligent_act_causing_death_is_not_culpable_homicide" not in jdm.match_judgment_doctrine(HURT_QUESTION_NOT_THIS_CASE),
      "a genuine hurt/assault question does NOT trigger this -- kept as its own domain, not lumped in")

override = jdm.get_judgment_doctrine_override(ON_POINT_QUESTION)
entries = [o for o in override if o.get("case_name") == "State of Gujarat v Haidarali Kalubhai"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Haidarali Kalubhai -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
