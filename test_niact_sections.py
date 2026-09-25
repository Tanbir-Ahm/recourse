"""Checks that the 19 Negotiable Instruments Act sections are sourced, registered as a
STATUTE (not mistaken for a judgment), embedded, and reachable by retrieval.
Run: python -X utf8 test_niact_sections.py

COST NOTE (added 2026-09-25, found by an independent cloud-session review -- this file was
making real, unmocked, billed calls with no warning at all): most of this file is genuinely free
(static chunk-file/embeddings-file checks, retrieval.get_statute_section is a pure local lookup).
The last section, "Retrieval reaches the new sections for real questions", calls
semantic_retrieval.find_relevant_sections with real question text -- that's a real Voyage embed
call each time, deliberately not mocked, for the same reason this project's other live tests
aren't: a mock only proves the mock does what it was told, never that the REAL retrieval actually
surfaces these sections for a real question. Added to LIVE_API_TEST_FILES accordingly."""
import json
import sys

import retrieval

fails = []


def check(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok:
        fails.append(msg)


EXPECTED = {"6", "20", "30", "31", "87", "118", "138", "139", "140", "141", "142", "142A",
            "143", "143A", "144", "145", "146", "147", "148"}

chunks = json.load(open("chunks/negotiable_instruments_act_1881_chunks.json", encoding="utf-8"))
have = {c["section_number"] for c in chunks}
check(have == EXPECTED, f"chunk file holds exactly the 19 expected sections (missing {EXPECTED - have}, extra {have - EXPECTED})")
check(all(len(c["text"]) > 150 and c["source_url"].startswith("https://indiacode.gov.in/") for c in chunks),
      "every section has real text and an India Code source link")

# The statute lookup works, and returns the operative wording
for sec, phrase in [("148", "minimum of twenty per cent"), ("146", "presume the fact of dishonour"),
                    ("144", "refused to take delivery"), ("138", "cheque"),
                    ("20", "prima facie authority"), ("87", "material alteration")]:
    r = retrieval.get_statute_section("NIACT", sec)
    check(bool(r) and phrase.lower() in r["text"].lower(), f"get_statute_section('NIACT','{sec}') returns text containing '{phrase}'")
check(retrieval.get_statute_section("NIACT", "999") is None, "an unknown NI Act section returns None, not a crash")

# It must not be swallowed as a judgment (the bug that produced 12 bogus records before)
check(not any("negotiable_instruments" in k for k in retrieval._JUDGMENT_CHUNK_FILES),
      "the NI Act file is not auto-registered as a judgment")

# Embedded, once each, with no bogus judgment records
recs = json.load(open("embeddings/corpus_embeddings.json", encoding="utf-8"))["records"]
recs = list(recs.values()) if isinstance(recs, dict) else recs
ni = [r for r in recs if r.get("act") == "NIACT"]
check(len(ni) == 19 and {r.get("section_number") for r in ni} == EXPECTED, "19 NIACT sections embedded, one each")
check(not any("unknown" in str(r.get("id", "")) for r in recs), "no bogus 'judgment:unknown' records in the embeddings")

# Retrieval reaches the new sections for real questions (cheque-bounce domain)
import semantic_retrieval as s
for q, want in [("If I lose the cheque case do I have to deposit money to appeal the conviction?", "148"),
                ("Is the bank's return memo enough proof that the cheque was dishonoured?", "146"),
                ("I signed a blank cheque and the other person filled in a bigger amount", "20"),
                ("Is the drawer bound to compensate the holder if the cheque bounces?", "30")]:
    got = [m.get("section_number") for m in s.find_relevant_sections(q, domain="cheque_bounce").get("matches", []) if m.get("act") == "NIACT"]
    check(want in got, f"'{q[:55]}...' retrieves NI Act s.{want} (got {got})")

# It must NOT leak into an arrest answer
arrest = s.find_relevant_sections("Police arrested my brother last night without telling us why")
check(not any(m.get("act") == "NIACT" for m in arrest.get("matches", [])), "an arrest question retrieves no NI Act sections")

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILED"))
sys.exit(1 if fails else 0)
