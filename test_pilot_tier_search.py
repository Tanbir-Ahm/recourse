"""
test_pilot_tier_search.py -- the WIDER, less-reviewed judgment pool (built from the 9 hand-verified
hurt/assault cases), kept deliberately separate from Recourse's 46 core, fully-reviewed cases.
Written BEFORE the code. Synthetic fixtures throughout -- never real judgment text in a test file,
same convention as every other test suite in this project.

Contract:
- A completely separate search, never merged into the main corpus search.
- A stricter similarity bar than the main corpus (less individual review => higher bar to admit a match).
- A paragraph number is cited ONLY for a chunk that genuinely has one (chunk_method == 'paragraph_number');
  a fixed-size-fallback chunk must never be presented with an invented paragraph number.
- Every result is formatted with an explicit, unmissable "wider tier, not the core library" label.
- The output never states a legal conclusion about the user's own situation.
- This module has ZERO import-time or call-time connection to chat_assistant.py / the live answer
  path -- it is proven correct in isolation before anything wires it in.
Run: python -X utf8 test_pilot_tier_search.py
"""
import os
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


try:
    import pilot_tier_search as p
except ImportError:
    p = None
check(p is not None, "pilot_tier_search module exists")
if p is None:
    print("\nFAILED (module missing)")
    sys.exit(1)

# ---------------------------------------------------------------- 0. isolation from the live answer path
import ast
with open("pilot_tier_search.py", encoding="utf-8") as f:
    tree = ast.parse(f.read())
imported = {n.names[0].name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for _ in [0]}
check("chat_assistant" not in imported and "whatsapp_bot" not in imported,
      "the module does not import chat_assistant or whatsapp_bot -- proven standalone, not wired into the live answer path")

# ---------------------------------------------------------------- 0.5. _embed_one caches by exact text (2026-09-25 cost bug fix)
# CONFIRMED REAL BUG, found independently 2026-09-25 after the NDPS pilot pool grew this file's
# real chunk count from 114 to 678: search_pilot_tier's per-chunk loop re-embedded the SAME
# question string on every iteration (one live Voyage call PER CHUNK instead of one call total per
# search). Run BEFORE the p._embed_one/p._similarity monkeypatches below (section 2) so this tests
# the real, undecorated-by-a-test-mock caching behavior of the actual production function.
class _FakeVoyageClient:
    call_count = 0

    def embed(self, texts, model, input_type):
        _FakeVoyageClient.call_count += len(texts)
        class _Result:
            embeddings = [[0.1, 0.2, 0.3] for _ in texts]
        return _Result()


import voyageai
_real_voyage_client_cls = voyageai.Client
voyageai.Client = _FakeVoyageClient
p._embed_one.cache_clear()
_FakeVoyageClient.call_count = 0
for _ in range(5):
    p._embed_one("the exact same question text, asked repeatedly")
check(_FakeVoyageClient.call_count == 1,
      f"_embed_one caches by exact input text -- 5 calls with the identical string made only 1 "
      f"real API call, got {_FakeVoyageClient.call_count}")
p._embed_one.cache_clear()
voyageai.Client = _real_voyage_client_cls

# ---------------------------------------------------------------- 1. threshold is stricter than the main corpus
import semantic_retrieval
check(p.PILOT_TIER_SIMILARITY_THRESHOLD >= semantic_retrieval.JUDGMENT_SIMILARITY_THRESHOLD,
      f"the wider tier's bar ({p.PILOT_TIER_SIMILARITY_THRESHOLD}) is at least as strict as the core "
      f"corpus's ({semantic_retrieval.JUDGMENT_SIMILARITY_THRESHOLD}), since this pool has less individual review")

# ---------------------------------------------------------------- 2. search: synthetic embeddings, no real API call, no real judgment text
def fake_embed(text):
    """A tiny deterministic stand-in for a real embedding -- just enough dimensions to test matching
    logic, never a real API call."""
    import hashlib
    h = hashlib.md5(text.encode()).digest()
    return [b / 255 for b in h[:8]]


POOL = [
    {"case_name": "Test Case A v State", "citation": "[2000] 1 S.C.R. 1", "source_url": "https://api.sci.gov.in/jonew/judis/1.pdf",
     "chunk_method": "paragraph_number", "paragraph_number": "12", "text": "synthetic passage about a wooden stick and a head injury", "chunk_id": "a-12"},
    {"case_name": "Test Case B v State", "citation": "[2001] 2 S.C.R. 2", "source_url": "https://api.sci.gov.in/jonew/judis/2.pdf",
     "chunk_method": "fixed_size_fallback", "paragraph_number": None, "text": "synthetic passage about a dangerous weapon and manner of use", "chunk_id": "b-3"},
    {"case_name": "Test Case C v State", "citation": "[2002] 3 S.C.R. 3", "source_url": "https://api.sci.gov.in/jonew/judis/3.pdf",
     "chunk_method": "paragraph_number", "paragraph_number": "7", "text": "synthetic passage about an unrelated tax assessment dispute", "chunk_id": "c-7"},
]
p._TEST_POOL = POOL
p._embed_one = fake_embed


def fake_similarity(q, chunk):
    # deterministic stand-in: "high" if the query and chunk share a topic word, "low" otherwise
    shared = set(q.lower().split()) & set(chunk["text"].lower().split())
    return 0.9 if len(shared) >= 2 else 0.1


p._similarity = fake_similarity

results = p.search_pilot_tier("a wooden stick caused a head injury", pool=POOL)
check(len(results) >= 1 and results[0]["case_name"] == "Test Case A v State",
      f"a genuinely on-topic question matches the right synthetic case -- got {[r['case_name'] for r in results]}")
check(all(r["case_name"] != "Test Case C v State" for r in results),
      "an unrelated (tax dispute) chunk is never returned for an on-topic question")

results2 = p.search_pilot_tier("weather forecast rainfall patterns next monsoon season", pool=POOL)
check(results2 == [], "a question matching nothing in the pool returns an empty list, not a forced weak match")

# ---------------------------------------------------------------- 3. formatting: paragraph number cited only when earned
with_para = {"case_name": "Test Case A v State", "citation": "[2000] 1 S.C.R. 1", "source_url": "https://api.sci.gov.in/jonew/judis/1.pdf",
             "chunk_method": "paragraph_number", "paragraph_number": "12", "text": "synthetic passage text here"}
without_para = {"case_name": "Test Case B v State", "citation": "[2001] 2 S.C.R. 2", "source_url": "https://api.sci.gov.in/jonew/judis/2.pdf",
                "chunk_method": "fixed_size_fallback", "paragraph_number": None, "text": "synthetic passage text here"}

fmt_with = p.format_pilot_result(with_para)
check("paragraph 12" in fmt_with.lower() or "¶12" in fmt_with or "para 12" in fmt_with.lower(),
      f"a genuine paragraph-numbered chunk cites its real paragraph number -- got {fmt_with!r}")

fmt_without = p.format_pilot_result(without_para)
check("paragraph" not in fmt_without.lower() and "¶" not in fmt_without,
      f"a fixed-size-fallback chunk NEVER invents a paragraph number -- got {fmt_without!r}")
check(with_para["source_url"] in fmt_with and without_para["source_url"] in fmt_without,
      "the real, verified source link is always included, for both chunk types")

# ---------------------------------------------------------------- 4. the label is unmissable, every time
for r in (with_para, without_para):
    out = p.format_pilot_result(r)
    check(("not part of" in out.lower() or "wider" in out.lower() or "not independently" in out.lower())
          and ("core" in out.lower() or "verified" in out.lower()),
          f"every single result carries the 'wider tier, not the core library' label -- got {out[:200]!r}")

# ---------------------------------------------------------------- 5. never states a conclusion about the user's own case
forbidden = ["your case will", "this means you will", "you are guilty", "you are innocent", "this proves your",
             "you will win", "you will lose", "the court will rule in your favor", "your situation is exactly"]
for r in (with_para, without_para):
    out = p.format_pilot_result(r).lower()
    check(not any(f in out for f in forbidden), f"no forbidden certainty phrase appears -- checked against {r['case_name']}")
check("discussed a similar" in p.format_pilot_result(with_para).lower() or "similar question" in p.format_pilot_result(with_para).lower(),
      "the framing is explicitly 'discussed a similar question', not a conclusion about the user's own case")

# ---------------------------------------------------------------- 6. loading the real pilot pool (built earlier) doesn't crash
# Back to 8, not 16: the 8 NDPS pilot candidates added 2026-09-25 (Tofan Singh, Mohanlal,
# Vijaysinh Chandubha Jadeja, Noor Aga, Karnail Singh, Mohan Lal v State of Punjab, State of
# Rajasthan v Parmanand, Union of India v Shiv Shanker Kesari) were ALL promoted to the core
# corpus by 2026-09-25 -- their leftover pilot copies were deliberately deleted 2026-09-26 after
# a real production bug: a promoted case's old copy could still surface here, mislabeled "not
# independently verified" (false -- it had been) and with no topic boundary at all (an NDPS case
# surfaced as "possibly relevant" under an unrelated BNS religious-offence question). Once a case
# is promoted, its pilot copy is deleted, not kept as a "backup" search path -- a real trigger-
# phrase gap found later gets fixed by widening the core doctrine map's triggers, the same
# precise, controllable fix already used elsewhere in this project, not by leaving a second,
# harder-to-keep-honest copy lying around. See memory: "pilot tier leftover copy cleanup". This
# leaves the original 8 hurt/assault cases (Mathai Verghese was promoted OUT of this pool earlier
# the same day -- wrong domain entirely, now lives in the core corpus; see
# test_mathai_verghese_promotion.py).
#
# DOWN TO 7, not 8, as of 2026-09-26: audit_pilot_paragraph_labels.py (built the same day, after
# the NDPS cleanup above prompted a closer look at what else might be sitting in this pool
# undetected) found that Pravat Chandra Mohanty v State of Odisha had roughly half its paragraph
# numbers pointing to TWO different, unrelated pieces of text each -- the judgment quotes an
# injury list and cites another case (Jetha Ram v State of Rajasthan) whose own internal
# numbering got mistaken for this judgment's own paragraphs by the automatic chunker, the same
# failure class documented extensively in ndps_doctrine_map.py's module docstring for several
# CORE-tier promotions this same week. Removed from the active pool (its original full text is
# preserved in pilot_corpus/, so nothing is lost -- it can be properly re-chunked if anyone ever
# wants to promote it) rather than left live with half its citations unreliable.
try:
    real_chunk_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pilot_chunks")
    real_pool = p.load_pilot_pool(real_chunk_dir)
    n_cases = len({c["case_name"] for c in real_pool})
    check(n_cases == 7 and len(real_pool) > 7, f"the real pilot pool loads chunks spanning all 7 remaining (clean, non-promoted) cases -- got {n_cases} cases, {len(real_pool)} chunks")
    check(all("source_url" in c and c["source_url"].startswith("https://api.sci.gov.in") for c in real_pool),
          "every real case in the pool carries its verified api.sci.gov.in link")
except FileNotFoundError:
    check(False, "pilot_chunks directory not found -- run build_pilot_corpus first")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
