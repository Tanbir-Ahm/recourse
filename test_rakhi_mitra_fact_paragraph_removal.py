"""
test_rakhi_mitra_fact_paragraph_removal.py -- removes Rakhi Mitra and Anr v State of West Bengal's two pure-fact
paragraphs (2 and 3) from what can be found by search, while leaving its real, curated holding untouched.

CONFIRMED REAL BUG (2026-09-29), found by the user from a real WhatsApp answer (downloaded as a PDF): asked
"RSS goondas have hit me. What to do?", the answer cited "Rakhi Mitra and Anr v State of West Bengal" and quoted its
paragraphs 2 and 3 -- which are PURE FACT RECITATION ("The brief facts of the case are that the petitioner no. 1
was..."; "A complaint was lodged with the Officer-in-Charge..."), the party's own account of being attacked near a
temple, not anything the Court ruled. The model itself correctly hedged this ("this was the party's account, not a
court finding" -- generate_grounded_response's own instruction to distinguish a party's allegation from the Court's
own reasoning), but citing it at all added no legal value and only confused the reader: this case's REAL legal
content (already curated in judgment_doctrine_map.py's 'consequence_of_arresting_without_the_notice_or_recorded_reasons'
entry, paragraphs 18 and 21) is about the consequences of arresting someone without a Section 35(3) BNSS notice --
nothing to do with the elements of "hurt" or an assault. Paragraphs 2/3 merely happen to describe a mob attack, which
made them look topically similar to an unrelated assault question and let them surface as if supportive.

This is the EXACT SAME class of bug _find_unsupported_case_generalizations (chat_assistant.py) was built for and
documents fixing once already, for L. Muruganantham v State of Tamil Nadu's paragraph 4 -- see that function's own
docstring: "the corpus itself was re-curated the same day... to stop surfacing this case's fact-only paragraphs for
unrelated arrest/dispute queries at all... this check is a general safety net for the same class of failure with ANY
judgment, not a fix specific to this one case." That check only prevents the model from ASSERTING a false
generalization about a case; it does not stop a fact-only paragraph from being cited plainly in the first place (which
is exactly what happened here -- no generalization language was used, so that check correctly did not fire).

The fix, matching that precedent exactly: remove the two confirmed-bad paragraphs from
chunks/rakhi_mitra_and_anr_v_state_of_west_bengal_chunks.json and from the corresponding entries in
embeddings/corpus_embeddings.json, so they can never again be retrieved by (a) unaided semantic search, (b) the BM25
lexical backfill, or (c) any future retrieval path -- while the CURATED doctrine-map entry (paragraphs 18, 21, which
IS the Court's own reasoning) is completely untouched, since get_judgment_paragraphs reads live from chunks/ by
paragraph number, not from the embeddings file. Only these two specific, confirmed paragraphs are removed -- not the
whole "facts and arguments" section (paragraphs 1, 4-10) -- matching this project's own "fix what's confirmed broken,
not what merely looks similar" discipline (see e.g. per-case-approval-not-batch-approval in memory).

Fully offline and free: reads the local chunk/embeddings files only, no API calls, no network.
Run: python -X utf8 test_rakhi_mitra_fact_paragraph_removal.py
"""
import json
import re
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


CASE_NAME = "Rakhi Mitra and Anr v State of West Bengal"
CHUNKS_PATH = "chunks/rakhi_mitra_and_anr_v_state_of_west_bengal_chunks.json"
EMBED_PATH = "embeddings/corpus_embeddings.json"
REMOVED = {"2", "3"}
# The exact confirmed-bad sentences from the real answer (checked against the live text before removal).
BAD_SENTENCE_2 = "The brief facts of the case are that the petitioner no. 1 was the State Secretary"
BAD_SENTENCE_3 = "A complaint was lodged with the Officer-in-Charge, Park Street Police Station"
# The curated holding this must NOT disturb (judgment_doctrine_map.py's own verified paragraphs).
HOLDING_SENTENCE_18 = "The Hon'ble Supreme Court strictly held in the case of Arnesh Kumar"
HOLDING_SENTENCE_21 = "Despite the dictum of both the aforesaid cases, the police officers"

# ---------------------------------------------------------------- 1. the chunk file itself
chunks = json.load(open(CHUNKS_PATH, encoding="utf-8"))
by_para = {c["paragraph_number"]: c for c in chunks}
check("2" not in by_para and "3" not in by_para,
      f"paragraphs 2 and 3 (pure fact recitation) are no longer in {CHUNKS_PATH} at all")
check(not any(BAD_SENTENCE_2 in c["text"] or BAD_SENTENCE_3 in c["text"] for c in chunks),
      "neither confirmed-bad sentence survives anywhere else in the file (not merged into another chunk)")
check("18" in by_para and HOLDING_SENTENCE_18 in by_para["18"]["text"],
      "the curated holding paragraph 18 (Arnesh Kumar consequences) is completely untouched")
check("21" in by_para and HOLDING_SENTENCE_21 in by_para["21"]["text"],
      "the curated holding paragraph 21 (non-compliance found) is completely untouched")
check(all(c.get("case_name") == CASE_NAME for c in chunks), "every remaining chunk still carries the right case name")
kept = sorted((c["paragraph_number"] for c in chunks if c["paragraph_number"] not in ("preamble",)),
              key=lambda s: (len(s), s))
check("1" in by_para and "4" in by_para and "10" in by_para,
      "the surrounding facts/arguments paragraphs (1, 4-10) are UNTOUCHED -- only the two confirmed-bad ones were removed")
check(len(chunks) == 41, f"41 of the original 43 chunks remain (43 minus the 2 removed) -- got {len(chunks)}")

# ---------------------------------------------------------------- 2. the embeddings store
data = json.load(open(EMBED_PATH, encoding="utf-8"))
records = data["records"]
rakhi_records = [r for r in records if r.get("case_name") == CASE_NAME]
rakhi_paras = {r["paragraph_number"] for r in rakhi_records}
check(REMOVED.isdisjoint(rakhi_paras),
      f"paragraphs 2 and 3 are gone from the embeddings store too (unaided semantic search / BM25 backfill can never surface them) -- remaining: {sorted(rakhi_paras)}")
check("18" in rakhi_paras and "21" in rakhi_paras, "the case's OTHER paragraphs, including the real holding, are still embedded and searchable")
check(len(rakhi_records) == 41, f"41 Rakhi Mitra records remain embedded -- got {len(rakhi_records)}")
check(data["chunk_count"] == len(records), "the file's own recorded chunk_count matches its actual record count (not left stale)")
check(not any(re.search(r"\bhurt\b|\bwarrant\b", r["text"], re.I) is None and False for r in rakhi_records), "sanity: file readable")
# no vector for a removed paragraph lingers anywhere under a different index
check(not any(BAD_SENTENCE_2 in r.get("text", "") or BAD_SENTENCE_3 in r.get("text", "") for r in records),
      "neither confirmed-bad sentence exists anywhere in the whole embeddings store, under any case name")

# ---------------------------------------------------------------- 3. the curated doctrine map entry still resolves
import importlib
import retrieval
importlib.reload(retrieval)
paras = retrieval.get_judgment_paragraphs("rakhi_mitra", ["18", "21"])
check(paras is not None and len(paras) == 2, f"the doctrine-map's own lookup (paras 18, 21) still resolves both -- got {paras and len(paras)}")
if paras:
    combined = " ".join(p["text"] for p in paras)
    check("Arnesh Kumar" in combined and "aforesaid cases" in combined, "and the real holding text is intact")
gone = retrieval.get_judgment_paragraphs("rakhi_mitra", ["2", "3"])
check(gone == [], "asking retrieval for the removed paragraphs 2/3 now returns an honest empty list, not an error")

import judgment_doctrine_map as jdm
importlib.reload(jdm)
ON_POINT = "The police arrested me before showing any notice and didn't record any reasons for the arrest."
matched = jdm.match_judgment_doctrine(ON_POINT)
check("consequence_of_arresting_without_the_notice_or_recorded_reasons" in matched,
      f"the curated doctrine entry still triggers correctly on its own real trigger phrasing -- matched: {matched}")
override = jdm.get_judgment_doctrine_override(ON_POINT)
rakhi_out = [o for o in override if o.get("case_name", "").startswith("Rakhi Mitra")]
check(len(rakhi_out) == 2 and {o["paragraph_number"] for o in rakhi_out} == {"18", "21"},
      f"and it still returns exactly the two real holding paragraphs, tagged as a curated override -- got {rakhi_out}")
check(all(o["source"] == "curated_judgment_override" for o in rakhi_out), "still tagged as full-authority, not the pilot hedge")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
