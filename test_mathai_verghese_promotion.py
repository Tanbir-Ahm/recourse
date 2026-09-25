"""
test_mathai_verghese_promotion.py -- promotes Mathai Verghese v State of Kerala from the pilot
pool to the core corpus, but under a DIFFERENT topic than the rest of that pool. Written BEFORE
the promotion.

WHY THIS EXISTS (2026-09-25): this was the one pilot case whose quote never verified across two
runs of judgment_promotion_assistant.py. Reading the full judgment explains why: it has nothing to
do with hurt/assault at all -- it's about counterfeiting CURRENCY (IPC 489A/489C, whether the law
covers foreign currency notes like US dollar bills, not just Indian ones), a genuinely different
offence entirely. It was pulled into the hurt/assault pilot pool by mistake, almost certainly due
to its similar-sounding name to "Mathai v State of Kerala" (2005), an unrelated, already-trusted
case already in the core corpus. Confirmed via the case citations: Mathai Verghese is [1987] 1
S.C.R. 317; the existing Mathai v State of Kerala is (2005) 3 SCC 260 -- different years, different
citations, different subject matter.

At the user's explicit instruction: keep the judgment, but move it out of the hurt/assault pilot
pool (pilot_corpus/ + pilot_chunks/) entirely, and promote it into the core corpus under its own,
correctly-topicked doctrine-map entry (counterfeiting currency), the same way Md. Ibrahim's forgery
entries sit alongside Arnesh Kumar's arrest entries in the same file -- different offence, same
general corpus, never forced into the hurt/assault entries built earlier this session.

Run: python -X utf8 test_mathai_verghese_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CHUNK_PATH = "chunks/mathai_verghese_v_state_of_kerala_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/")

# CONFIRMED REMOVED from the hurt/assault pilot pool -- not left behind in the wrong place.
check(not os.path.exists("pilot_corpus/mathai_verghese_v_state_of_kerala.json"),
      "no longer sitting in pilot_corpus/ -- moved, not duplicated")
check(not os.path.exists("pilot_chunks/mathai_verghese_v_state_of_kerala_chunks.json"),
      "no longer sitting in pilot_chunks/ -- moved, not duplicated")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 9, f"all 9 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks), "embedding vectors stripped")

import importlib
import retrieval
importlib.reload(retrieval)

check("mathai_verghese" in retrieval._JUDGMENT_CHUNK_FILES, "auto-registered as 'mathai_verghese'")

paras = retrieval.get_judgment_paragraphs("mathai_verghese", ["fallback_2"])
check(paras is not None and len(paras) == 1, f"the chosen paragraph resolves -- got {paras and len(paras)}")
if paras:
    text_norm = " ".join(paras[0]["text"].split()).lower()
    check("be an offence to counterfeit a dollar bill" in text_norm,
          "the core holding (foreign currency IS covered) is genuinely present")
    check(paras[0]["case_name"] == "Mathai Verghese v State of Kerala", "case_name carried through correctly")

import judgment_doctrine_map as jdm
importlib.reload(jdm)

ON_POINT_QUESTION = (
    "I've been accused of having fake US dollar notes / counterfeit foreign currency. Is that "
    "even a crime under Indian law, or does the counterfeiting law only cover Indian rupee notes?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."
HURT_QUESTION_NOT_THIS_CASE = (
    "I was attacked with a stick during a fight and suffered a grievous injury -- does that count "
    "as a dangerous weapon?"
)

matched = jdm.match_judgment_doctrine(ON_POINT_QUESTION)
check("counterfeiting_currency_covers_foreign_notes_too" in matched,
      f"the currency-counterfeiting question triggers the entry -- matched keys: {matched}")
check("counterfeiting_currency_covers_foreign_notes_too" not in jdm.match_judgment_doctrine(UNRELATED_QUESTION),
      "a completely unrelated question never triggers this")
check("counterfeiting_currency_covers_foreign_notes_too" not in jdm.match_judgment_doctrine(HURT_QUESTION_NOT_THIS_CASE),
      "a genuine hurt/assault question does NOT trigger this -- confirms it's correctly kept "
      "separate from the hurt/assault entries, not accidentally lumped in with them")

override = jdm.get_judgment_doctrine_override(ON_POINT_QUESTION)
entries = [o for o in override if o.get("case_name") == "Mathai Verghese v State of Kerala"]
check(len(entries) >= 1, f"get_judgment_doctrine_override actually returns Mathai Verghese -- got {len(entries)}")
if entries:
    check(entries[0]["source"] == "curated_judgment_override", "tagged as a curated (full-authority) override")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
