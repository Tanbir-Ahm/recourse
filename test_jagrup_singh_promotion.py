"""
test_jagrup_singh_promotion.py -- promotes Jagrup Singh v State of Haryana from the pilot,
NOT-independently-reviewed judgment pool into the fully-reviewed core corpus, via the SAME
judgment_doctrine_map.py mechanism already used for Arnesh Kumar, D.K. Basu, etc. Written BEFORE
the promotion (the chunk file did not yet exist under chunks/, and no doctrine-map entry existed,
at the time this was written).

WHY THIS EXISTS (2026-09-24): at the user's explicit request, after independently reading the full
judgment text (pilot_corpus/jagrup_singh_v_state_of_haryana.json, all 8 pages) and confirming it
genuinely holds what a prior chat answer had (correctly, hedgedly) described -- a single blow in a
sudden fight, with no premeditation, falls under Exception 4 to murder (BNS Section 101), reducing
the offence to culpable homicide not amounting to murder (BNS Section 105). Once a person has done
that reading, the case is no longer "unread" -- it belongs in the SAME curated-anchor mechanism as
every other hand-verified judgment this project trusts as authority, not the hedged pilot pool.

Confirms:
1. The chunk file is discoverable by retrieval.py's real registry (copied into chunks/, not left
   in pilot_chunks/ -- retrieval._auto_register_judgment_chunks() only scans chunks/).
2. get_judgment_paragraphs resolves the two specific paragraphs actually read and chosen (the
   headnote's HELD summary, and the final operative holding), with the real holding language intact.
3. judgment_doctrine_map fires on realistic "sudden fight / no premeditation / single blow"
   phrasing and NOT on an unrelated question.
4. get_judgment_doctrine_override returns the real text, tagged as a curated (fully-authoritative)
   override -- not routed through the hedged pilot-tier mechanism at all.
5. Once this fires, chat_assistant's exclude_case_names logic (already built for the pilot-tier
   wiring) automatically keeps this same case OUT of the separate "wider, unverified" list --
   confirming no double-citation, one case cited once, at full authority.

Run: python -X utf8 test_jagrup_singh_promotion.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---------------------------------------------------------------- 1. the file is in the real corpus
CHUNK_PATH = "chunks/jagrup_singh_v_state_of_haryana_chunks.json"
check(os.path.exists(CHUNK_PATH), f"{CHUNK_PATH} exists -- promoted out of pilot_chunks/, not left behind")

import json
with open(CHUNK_PATH, encoding="utf-8") as f:
    promoted_chunks = json.load(f)
check(len(promoted_chunks) == 8, f"all 8 chunks carried over -- got {len(promoted_chunks)}")
check(all("embedding" not in c for c in promoted_chunks),
      "the pilot pool's embedding vectors were stripped -- core corpus chunk files never carry them "
      "inline (embeddings/corpus_embeddings.json is the separate, real embeddings store), and leaving "
      "them in would be dead weight, not a functional problem, but inconsistent with every other file here")

# ---------------------------------------------------------------- 2. real text resolves via retrieval.py
import importlib
import retrieval
importlib.reload(retrieval)  # re-run auto-registration now that the file exists under chunks/

check("jagrup_singh" in retrieval._JUDGMENT_CHUNK_FILES,
      "auto-registered under the same 'stem before _v_' convention as every other judgment "
      "(arnesh_kumar_v_state_of_bihar -> 'arnesh_kumar')")

paras = retrieval.get_judgment_paragraphs("jagrup_singh", ["fallback_2", "fallback_8"])
check(paras is not None and len(paras) == 2, f"both chosen paragraphs resolve -- got {paras and len(paras)}")
if paras:
    combined = " ".join(p["text"] for p in paras)
    check("all the requirements of Exception 4" in combined,
          "the headnote's HELD summary (fallback_2) is genuinely present, not a different chunk")
    check("altered to one under s. 304" in combined,
          "the final operative holding (fallback_8) is genuinely present -- the actual order the "
          "Court made, not just a paraphrase")
    check(paras[0]["case_name"] == "Jagrup Singh v State of Haryana", "case_name carried through correctly")

# ---------------------------------------------------------------- 3 & 4. the doctrine map entry itself
import judgment_doctrine_map as jdm
importlib.reload(jdm)

ON_POINT_QUESTION = (
    "During a sudden quarrel with a relative, with no planning and no weapon brought in advance, "
    "I hit him once in the heat of the moment and he died. Does this count as murder, or is it "
    "treated as a lesser offence because it happened suddenly without premeditation?"
)
UNRELATED_QUESTION = "My bank account has been frozen and I can't access my salary."

matched = jdm.match_judgment_doctrine(ON_POINT_QUESTION)
check(any("jagrup" in k.lower() or "sudden_fight" in k.lower() for k in matched),
      f"the on-point question triggers the new entry -- matched keys: {matched}")
check(not any("jagrup" in k.lower() or "sudden_fight" in k.lower()
              for k in jdm.match_judgment_doctrine(UNRELATED_QUESTION)),
      "a completely unrelated question (bank freeze) never triggers this")

override = jdm.get_judgment_doctrine_override(ON_POINT_QUESTION)
jagrup_entries = [o for o in override if o.get("case_name") == "Jagrup Singh v State of Haryana"]
check(len(jagrup_entries) >= 1, f"get_judgment_doctrine_override actually returns Jagrup Singh -- got {len(jagrup_entries)} entries")
if jagrup_entries:
    check(jagrup_entries[0]["source"] == "curated_judgment_override",
          "tagged as a curated override -- the SAME full-authority tag every other hand-verified "
          "judgment gets, not the pilot-tier hedge")
    check("Exception 4" in jagrup_entries[0]["text"], "the real holding text reaches the match dict")
    check(jagrup_entries[0].get("context_note"), "a context_note explaining the holding is attached")

# ---------------------------------------------------------------- 5. no double-citation with the pilot tier
# Once Jagrup Singh is a genuine `matches` entry (via the doctrine override above), chat_assistant's
# existing exclude_case_names logic (built for the pilot-tier wiring, unmodified here) must keep it
# OUT of the separate "wider, unverified" list -- this is the ALREADY-BUILT mechanism, not new code,
# confirmed here so the promotion doesn't silently produce a confusing double mention.
import chat_assistant as ca
from unittest.mock import patch

FAKE_PILOT_HIT = {"case_name": "Jagrup Singh v State of Haryana",
                   "source_url": "https://api.sci.gov.in/jonew/judis/10048.pdf",
                   "chunk_method": "fixed_size_fallback", "paragraph_number": None,
                   "citation": "[1981] 3 S.C.R. 839", "text": "some pilot chunk text"}
with patch("pilot_tier_search.search_pilot_tier", return_value=[FAKE_PILOT_HIT]):
    out = ca._fetch_pilot_related_judgments(
        ON_POINT_QUESTION, exclude_case_names={"Jagrup Singh v State of Haryana"}
    )
    check(out == [],
          "once Jagrup Singh is a verified match (case_name excluded), the pilot-tier fetch correctly "
          "omits it -- no case is ever shown twice, once as authority and once as a hedge")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
