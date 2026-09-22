"""
test_named_section_lookup.py

Regression guard for the 2026-09-22 fix: a question that names an exact
section number and Act ("420 IPC", "Section 318 BNS", "IT Act 66C") gets
that section's real text via a dictionary lookup
(_named_section_exact_match in semantic_retrieval.py), not similarity
search.

WHAT THIS GUARDS: "What are the ingredients for 420 IPC?" -- arguably the
single most commonly cited section number in Indian criminal law --
returned "no_match". BNS Section 318 (cheating, IPC 420's current-law
equivalent) was verified, present and correct in the corpus the whole
time; the query text just never resembled the statute's own wording
(which never contains the digits "420") closely enough to clear
STATUTE_SIMILARITY_THRESHOLD, or even to rank in the top statute
candidates at all. See semantic_retrieval._named_section_exact_match's
docstring for the full writeup.

Run with: python test_named_section_lookup.py
"""

import sys

FAILURES = []


def check(condition, description):
    print(f"[{'PASS' if condition else 'FAIL'}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- offline: detection (no API cost, no embeddings needed) ----

from semantic_retrieval import _detect_named_section, _named_section_exact_match

check(_detect_named_section("What are the ingredients for 420 IPC?") == ("IPC", "420"),
      "'420 IPC' detected as (IPC, 420)")
check(_detect_named_section("IPC 420 se kya hota hai") == ("IPC", "420"),
      "act-then-number order ('IPC 420') also detected")
check(_detect_named_section("Section 420 of the IPC") == ("IPC", "420"),
      "'Section 420 of the IPC' detected")
check(_detect_named_section("what happens u/s 420") is None,
      "'u/s 420' with NO Act named anywhere is left undetected (ambiguous, no guessing)")
check(_detect_named_section("what happens u/s 420 ipc") == ("IPC", "420"),
      "'u/s 420 ipc' detected")
check(_detect_named_section("IT Act 66C") == ("ITACT", "66C"),
      "'IT Act 66C' detected, letter-suffixed number handled")
check(_detect_named_section("Section 138 of the NI Act") == ("NIACT", "138"),
      "'Section 138 of the NI Act' detected")
check(_detect_named_section("BNS Section 318") == ("BNS", "318"),
      "'BNS Section 318' (act-then-number, bare) detected")

# deliberately ambiguous -- no Act named at all, must NOT guess one
check(_detect_named_section("my case is under section 420, what does that mean") is None,
      "a bare 'section 420' with NO Act named is left undetected (ambiguous IPC-vs-BNS)")
check(_detect_named_section("I was arrested last night near my house") is None,
      "ordinary prose with no section number is left undetected")


# ---- offline: exact lookup resolves to the right, real section ----

hit = _named_section_exact_match("What are the ingredients for 420 IPC?")
check(hit is not None, "420 IPC resolves to a real statute hit")
check(hit is not None and hit["act"] == "BNS" and hit["section_number"] == "318(4)",
      f"420 IPC resolves specifically to BNS 318(4), not bare 318 (got {hit and (hit['act'], hit['section_number'])!r})")
check(hit is not None and hit["score"] == 1.0 and hit.get("exact_section_lookup") is True,
      "the hit is marked as an exact lookup with certainty score 1.0")
check(hit is not None and "deceiving" in hit["text"] and "420" not in hit["text"],
      "the returned text is the REAL BNS 318 statute text (which never itself says '420')")

hit302 = _named_section_exact_match("IPC 302 murder ingredients")
check(hit302 is not None and hit302["act"] == "BNS" and hit302["section_number"] == "103",
      f"IPC 302 (murder) resolves to BNS 103 (got {hit302 and (hit302['act'], hit302['section_number'])!r})")

check(_named_section_exact_match("what does 124A IPC say") is None,
      "IPC 124A (sedition, repealed with no successor) resolves to None, not a wrong guess")

check(_named_section_exact_match("what is section 99999 IPC") is None,
      "a section number not in the concordance table at all resolves to None")


# ---- offline: a bare, genuinely ambiguous new-code number stays ambiguous ----
# (BNS 318's own subsections (2)/(3) are non-cognizable, (4) is cognizable --
# a bare "BNS 318" must NOT silently collapse to one of them)

hit_bare = _named_section_exact_match("What does BNS Section 318 say?")
check(hit_bare is not None and hit_bare["section_number"] == "318",
      "a bare 'BNS 318' (no subsection given) keeps the bare number, not a guessed subsection")


# ---- end-to-end: find_relevant_sections (real embeddings call) ----

from semantic_retrieval import find_relevant_sections

r = find_relevant_sections("What are the ingredients for 420 IPC?")
check(r.get("state") == "single_match",
      f"420 IPC -> single_match end-to-end (got {r.get('state')!r}), not no_match")
matches = r.get("matches", [])
check(len(matches) == 1 and matches[0].get("section_number") == "318(4)",
      "the single match is BNS 318(4)")
check(matches[0].get("section_data", {}).get("cognizable") is True
      and matches[0].get("section_data", {}).get("bailable") is False,
      "318(4)'s real cognizable=True/bailable=False data comes through (matches old 420's status)")

r_bare = find_relevant_sections("What does BNS Section 318 say?")
check(r_bare.get("state") == "conflicting_matches",
      f"a bare, genuinely ambiguous 'BNS 318' still surfaces the real subsection fork "
      f"(got {r_bare.get('state')!r}) -- the fast path must not paper over a real conflict")


# ---- end-to-end: a normal narrative question is untouched by this change ----

r_ordinary = find_relevant_sections(
    "police arrested my brother at night for a fake instagram account and have not "
    "told us where he is held")
check(not any(m.get("exact_section_lookup") for m in r_ordinary.get("matches", [])),
      "an ordinary narrative question with no named section never triggers the exact-lookup path")


print("\n" + "=" * 70)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL TESTS PASSED")
sys.exit(0)
