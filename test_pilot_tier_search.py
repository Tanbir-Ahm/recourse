"""
test_pilot_tier_search.py -- the WIDER, less-reviewed judgment pool (10 hand-verified cases across
two topics: 7 hurt_assault, 3 anticipatory_bail), kept deliberately separate from Recourse's 46
core, fully-reviewed cases.
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

# ---------------------------------------------------------------- 2b. topic filtering (added 2026-09-26)
# CONFIRMED REAL BUG this closes: a case from one subject area (NDPS) surfaced as "possibly
# relevant" under a completely unrelated question (a BNS religious-offence question) because the
# pool had no way to tell subjects apart. `topic` on search_pilot_tier is the fix.
TOPIC_POOL = [
    {"case_name": "Assault Case v State", "citation": "[2010] 1 S.C.R. 1", "source_url": "https://api.sci.gov.in/jonew/judis/10.pdf",
     "chunk_method": "fixed_size_fallback", "paragraph_number": None, "topic": "hurt_assault",
     "text": "synthetic passage sharing bail words with the query below", "chunk_id": "assault-1"},
    {"case_name": "Anticipatory Bail Case v State", "citation": "[2020] 2 S.C.R. 2", "source_url": "https://api.sci.gov.in/jonew/judis/20.pdf",
     "chunk_method": "fixed_size_fallback", "paragraph_number": None, "topic": "anticipatory_bail",
     "text": "synthetic passage sharing bail words with the query below", "chunk_id": "bail-1"},
]
p._similarity = lambda q, chunk: 0.9  # both chunks score equally high on pure wording -- topic must be what separates them

check(
    {r["case_name"] for r in p.search_pilot_tier("q", pool=TOPIC_POOL, topic="anticipatory_bail")} == {"Anticipatory Bail Case v State"},
    "topic='anticipatory_bail' returns ONLY the anticipatory-bail chunk, even though the hurt/assault "
    "chunk scores identically on wording alone -- topic is a hard filter, not a tiebreaker",
)
check(
    {r["case_name"] for r in p.search_pilot_tier("q", pool=TOPIC_POOL, topic="hurt_assault")} == {"Assault Case v State"},
    "the same filter works the other way round too",
)
check(
    {r["case_name"] for r in p.search_pilot_tier("q", pool=TOPIC_POOL)} == {"Assault Case v State", "Anticipatory Bail Case v State"},
    "with NO topic given (every caller before this change), behaviour is unchanged -- the whole pool is searched",
)
check(
    p.search_pilot_tier("q", pool=TOPIC_POOL, topic="some_topic_that_does_not_exist") == [],
    "an unrecognised topic returns an honest empty list, not an error or the whole pool",
)
p._similarity = fake_similarity  # restore for the sections below

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
#
# UP TO 9, not 7, as of 2026-09-26: Gurbaksh Singh Sibbia AND Siddharam Satlingappa Mhetre v State
# of Maharashtra both added -- the first genuinely deliberate additions under the new sourcing plan
# (real government link, full read, 2 automated + 3 manual checks, explicit approval, THEN pilot
# entry -- not core yet). Sibbia is the case that made topic-tagging necessary rather than
# premature: it's the second real subject in the pool (the first 7 are hurt_assault; Sibbia and
# Mhetre are anticipatory_bail), so every chunk in the pool -- old and new -- now carries a `topic`
# field, checked below. Mhetre's own chunk file also had 2 of its own real paragraph numbers (1
# and 19) colliding with an unrelated appendix/index list's independent numbering inside the same
# document -- the same failure class as Pravat Chandra Mohanty above; the 4 ambiguous chunks (2
# labels x 2 texts each) were removed, keeping the other 150 genuinely clean ones.
#
# UP TO 10, not 9, as of 2026-09-26: Sushila Aggarwal v State (NCT of Delhi) added, the third and
# final case approved under the anticipatory-bail plan (also anticipatory_bail topic). Its source
# PDF is a 5-judge Constitution Bench ruling with two separately-numbered opinions (M.R. Shah, S.
# Ravindra Bhat); the audit above flagged 36 colliding paragraph numbers (1-43, plus 438-439) --
# far more than a simple two-opinion restart would explain. The real cause: M.R. Shah's opinion
# embeds an illustrative bail-bond-conditions template (a numbered list "1. the applicant shall
# furnish personal bond...", "2. ... shall remain present...", etc.) whose own numbering collided
# with his real paragraph numbers, and both opinions quote Sibbia/Mhetre's own numbered paragraphs
# at length while analysing them. All 36 flagged numbers were removed rather than guessed apart
# (99 of the original 175 chunks) -- this happens to remove nearly all of M.R. Shah's opinion (35
# of 36 chunks; only his one-paragraph preamble survives, since virtually all his real content sat
# inside the colliding 1-43 range) while leaving S. Ravindra Bhat's opinion largely intact,
# including its actual holding (paragraphs 77-81, "the reference is hereby answered in the above
# terms", confirmed clean before and after the fix) and paragraphs 94-125. Losing Shah's opinion
# from this pool is a real, deliberate cost of the fix, not an oversight.
#
# UP TO 11, not 10, as of 2026-09-27: Hridaya Rangan Pd. Verma and Ors. v State of Bihar and Anr.
# added -- the first case in a new third topic, `cheating_civil_dispute`, sourced the same way as
# the anticipatory-bail batch (real api.sci.gov.in link supplied by the user, full read, citation
# cross-checked against an independent source, explicit approval). Its own decision reads as
# continuous prose with no internal paragraph numbering, so it chunked entirely via
# fixed_size_fallback (14 chunks) -- no paragraph-label collision risk since there are no
# paragraph-number labels to collide. This addition is also what motivated generalising
# chat_assistant._infer_pilot_topic (see that function's own comment) from a hardcoded two-topic
# check to a dict-driven one, and fixing a real latent bug found while doing so: BNS 318 (cheating)
# comes back from the real answer pipeline as "318(4)" (a sub-clause), which the original
# hurt/bail-only exact-string check would never have been tested against, but would have missed.
#
# UP TO 12, not 11, as of 2026-09-27: G. Sagar Suri and Anr. v State of U.P. and Ors. added, second
# case in cheating_civil_dispute -- an even more directly on-point precedent (a loan secured by
# cheques that bounced, with a cheating FIR filed on top of a Section 138 NI Act complaint over the
# same money; the Court quashed the cheating prosecution). Also fixed entirely via
# fixed_size_fallback (16 chunks), no collision risk. Confirmed live against 3 real loan/cheque
# phrasings: it correctly ranks ABOVE Hridaya Rangan Pd. Verma for all three (0.44/0.50/0.46 vs
# 0.42/0.41/0.29) -- but two of those three sit at or just under the pool's strict 0.50 threshold,
# so this case will not surface for every real phrasing of the same underlying question. That's the
# pool's own deliberately conservative threshold working as designed, not a defect in this case.
#
# UP TO 13, as of 2026-09-28: S.W. Palanitkar and Ors. v State of Bihar and Anr. -- third case in
# cheating_civil_dispute, and the first added with add_pilot_case.py (stage, then approve). Partly
# allowed: cheating process kept alive against one appellant, so the topic is not one-directional.
#
# UP TO 14, as of 2026-09-28: Alpic Finance Ltd. v P. Sadasivan and Anr. -- fourth case in
# cheating_civil_dispute (appeal dismissed; the High Court's quashing of a cheating complaint over a
# hire-purchase default stood). First case checked by the automatic second reader (7 of 7 claims confirmed).
# UP TO 15, as of 2026-09-28: All Cargo Movers (I) Pvt. Ltd. v Dhanesh Badarmal Jain -- fifth case in
# cheating_civil_dispute (appeal allowed; cognizance set aside). 9 chunks labelled 1-4 deliberately dropped
# (quoted fax/defendants lists reuse those numbers); 19 chunks, paragraphs 5-22, remain.
# UP TO 16, as of 2026-09-28: Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors. -- sixth and last case
# in cheating_civil_dispute (FIR quashed; civil land dispute; also the Court's non-bailable-warrant guidance).
# The judgment has no numbered paragraphs, so it was chunked into fixed-size pieces by decision.
try:
    real_chunk_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pilot_chunks")
    real_pool = p.load_pilot_pool(real_chunk_dir)
    n_cases = len({c["case_name"] for c in real_pool})
    check(n_cases == 16 and len(real_pool) > 16, f"the real pilot pool loads chunks spanning all 16 current cases -- got {n_cases} cases, {len(real_pool)} chunks")
    check(all("source_url" in c and c["source_url"].startswith("https://api.sci.gov.in") for c in real_pool),
          "every real case in the pool carries its verified api.sci.gov.in link")
    check(all(c.get("topic") for c in real_pool),
          "every chunk in the real pool now carries a topic -- none were left untagged by the retrofit")
    real_topics = {c["topic"] for c in real_pool}
    check(real_topics == {"hurt_assault", "anticipatory_bail", "cheating_civil_dispute"},
          f"exactly the three real topics currently in the pool, nothing unexpected -- got {real_topics}")
except FileNotFoundError:
    check(False, "pilot_chunks directory not found -- run build_pilot_corpus first")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
