
"""
test_answer_cache.py

Regression suite for answer_cache.py (the human-approved answer-reuse
cache, see that module's docstring for the full design) and its wiring
into chat_assistant._answer_single_match(). Same lightweight
check()/FAILURES convention as the rest of this repo's test_*.py files;
run directly: `python test_answer_cache.py`. No real API cost --
chat_assistant.generate_grounded_response is mocked in the integration
section below.
"""
import tempfile
from unittest.mock import patch

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


import answer_cache

answer_cache.DB_PATH = tempfile.mktemp(suffix=".db")

# ---- cache_key: the safety-critical part -- must depend on SOURCES, never wording ----

STATUTE_303 = {"act": "BNS", "section_number": "303", "text": "Whoever commits theft..."}
STATUTE_187 = {"act": "BNSS", "section_number": "187", "text": "Procedure when investigation cannot be completed..."}
JUDGMENT_ARNESH = {"case_name": "Arnesh Kumar v State of Bihar", "paragraph_number": "11", "text": "Police officers..."}

check(
    answer_cache.cache_key([STATUTE_303, STATUTE_187]) == answer_cache.cache_key([STATUTE_187, STATUTE_303]),
    "cache_key is independent of match order (same sources, different order -> same key)",
)
check(
    answer_cache.cache_key([STATUTE_303]) != answer_cache.cache_key([STATUTE_187]),
    "different sources produce different keys",
)
check(
    answer_cache.cache_key([{"act": "BNS", "section_number": "303"}])
    != answer_cache.cache_key([{"act": "IPC", "section_number": "303"}]),
    "same section NUMBER under a different act is NOT treated as the same source "
    "(the exact confusion this design deliberately avoids)",
)
check(
    answer_cache.cache_key([STATUTE_303, JUDGMENT_ARNESH]) == answer_cache.cache_key([STATUTE_303, JUDGMENT_ARNESH]),
    "the same statute+judgment combination always produces the same key",
)
check(
    answer_cache.cache_key([{"chunk_id": "abc123"}]) != answer_cache.cache_key([{"chunk_id": "def456"}]),
    "chunk_id-identified matches (used by hybrid_search results) are respected as the primary identity",
)

# ---- describe_matches: human-readable summary for the review report ----

check(
    answer_cache.describe_matches([STATUTE_303, JUDGMENT_ARNESH])
    == "BNS 303; Judgment: Arnesh Kumar v State of Bihar",
    "describe_matches produces a readable summary mixing a statute and a judgment",
)
check(
    answer_cache.describe_matches([]) == "(no identifiable sources)",
    "describe_matches never crashes or returns empty text for an empty match list",
)

# ---- record_candidate / list_candidates: the logging half ----

answer_cache.record_candidate([STATUTE_303], "My brother stole a goat", "first answer text", True)
candidates = answer_cache.list_candidates()
check(
    len(candidates) == 1 and candidates[0]["hit_count"] == 1,
    "a brand-new candidate is recorded with hit_count 1",
)

answer_cache.record_candidate([STATUTE_303], "He was arrested for stealing a goat", "second answer text", True)
candidates = answer_cache.list_candidates()
check(
    len(candidates) == 1,
    "a DIFFERENTLY WORDED question that resolves to the SAME sources updates the same "
    "candidate row rather than creating a second one -- the core design point",
)
check(
    candidates[0]["hit_count"] == 2,
    "hit_count increments on the repeat instead of staying at 1",
)
check(
    candidates[0]["response_text"] == "second answer text",
    "the candidate's stored text tracks the most recently generated wording",
)

# ---- get_cached: nothing served before approval ----

check(
    answer_cache.get_cached([STATUTE_303]) is None,
    "an unapproved candidate is never served from cache, no matter how many times it repeats",
)

# ---- approve / get_cached / revoke: the human-gated reuse path ----

key = answer_cache.cache_key([STATUTE_303])
ok = answer_cache.approve(key, ttl_days=30)
check(ok is True, "approving an existing candidate succeeds")

cached = answer_cache.get_cached([STATUTE_303])
check(
    cached is not None and cached["response_text"] == "second answer text",
    "after approval, get_cached returns the approved answer",
)
check(
    cached["situation_detected"] is True,
    "situation_detected is preserved through the cache so callers (e.g. the draft-petition button) "
    "still see it correctly",
)

check(
    answer_cache.approve("not-a-real-key") is False,
    "approving a cache key with no matching candidate fails honestly instead of inserting garbage",
)

revoked = answer_cache.revoke(key)
check(revoked is True, "revoke reports success when an approval existed")
check(
    answer_cache.get_cached([STATUTE_303]) is None,
    "after revoke, the question goes back to generating fresh instead of serving the old answer",
)
check(
    answer_cache.revoke(key) is False,
    "revoking something already revoked reports failure rather than pretending to succeed",
)

# ---- expiry: an approval doesn't last forever ----

answer_cache.approve(key, ttl_days=-1)  # already expired the moment it's approved
check(
    answer_cache.get_cached([STATUTE_303]) is None,
    "an approval with a TTL already in the past is treated as expired, not served",
)

approved_list = answer_cache.list_approved()
check(
    len(approved_list) == 1 and approved_list[0]["cache_key"] == key,
    "list_approved still shows the expired row (for the report to display as EXPIRED) "
    "rather than silently deleting it",
)


# ---------------------------------------------------------------------------
# Integration: chat_assistant._answer_single_match actually skips the
# expensive Sonnet call on a cache hit, and behaves identically to before
# on a miss. generate_grounded_response is mocked -- no real API cost.
# ---------------------------------------------------------------------------

import chat_assistant

answer_cache.DB_PATH = tempfile.mktemp(suffix=".db")

_generate_call_count = [0]


def _fake_generate(question, retrieved_text, is_conflict=False, model=None, matches=None):
    _generate_call_count[0] += 1
    return "**Right now**\nFresh generated answer."


with patch("chat_assistant.generate_grounded_response", side_effect=_fake_generate):
    result1 = chat_assistant._answer_single_match("My brother stole a goat", [STATUTE_303])
    check(
        result1["state"] == "single_match" and result1.get("from_cache") is False,
        "a fresh answer (no approved cache entry yet) is marked from_cache False",
    )
    check(_generate_call_count[0] == 1, "generate_grounded_response was actually called on a cache miss")

    answer_cache.approve(answer_cache.cache_key([STATUTE_303]))

    result2 = chat_assistant._answer_single_match(
        "He got arrested, they're saying he took a goat that wasn't his", [STATUTE_303]
    )
    check(
        result2.get("from_cache") is True and result2["response_text"] == result1["response_text"],
        "a DIFFERENTLY WORDED question resolving to the same approved sources is served from cache",
    )
    check(
        _generate_call_count[0] == 1,
        "generate_grounded_response is NOT called again on a cache hit -- this is the actual cost saving",
    )
    check(
        result2["situation_detected"] == result1["situation_detected"],
        "situation_detected survives the cache path unchanged",
    )

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
