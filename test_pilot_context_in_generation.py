"""
test_pilot_context_in_generation.py -- lets generate_grounded_response DESCRIBE a pilot-tier
(wider, unverified) judgment in its prose, instead of only listing it separately, while keeping
the same safety property the separate list had: a pilot-tier case can never be used as AUTHORITY
for the user's own outcome. Written BEFORE the code. Mocked Anthropic client throughout -- no real
API calls, no real judgment text (synthetic fixtures only), same convention as this project's other
test suites.

WHY THIS EXISTS: the user explicitly asked for pilot-tier text to reach the answer generator
("let the model describe, not conclude... woven into the prose"), after being told the real risk --
the pilot pool is only IDENTITY-verified (real PDF, real names/dates), not legal-content-reviewed
like the 46-case core corpus, so letting the model treat it as authority (as it's normally allowed
to for a fully-reviewed case, e.g. "the Court held...") would let an unverified claim reach a real
person in a real arrest situation with full confidence. This suite is the deterministic backstop
for that specific risk, mirroring the existing _find_unsupported_case_generalizations pattern but
STRICTER: unlike a core-corpus case (where generalization language is fine if the excerpt actually
supports it), a pilot-tier case's generalization/holding language is ALWAYS flagged, regardless of
what its excerpt says, because nobody has verified that excerpt is representative of the case's real
holding at all.

Run: python -X utf8 test_pilot_context_in_generation.py
"""
import sys
from unittest.mock import MagicMock, patch

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


import chat_assistant as ca

PILOT_MATCH = {
    "source": "pilot_wider_tier",
    "case_name": "State of Uttar Pradesh v Ram Kishan",
    "ik_search_url": "https://api.sci.gov.in/jonew/judis/5725.pdf",
    "citation": "[1976] 3 S.C.R. 379",
    "paragraph_number": None,
    "text": "The accused and the deceased are close relatives. " * 80,  # long, to test truncation
}

# ---------------------------------------------------------------- 1. _fetch_pilot_related_judgments
# now also carries text/citation, not just the UI-list fields
check(hasattr(ca, "_fetch_pilot_related_judgments"), "chat_assistant exposes _fetch_pilot_related_judgments")
FAKE_HIT = {"case_name": "Prabhu v State of Madhya Pradesh", "citation": "[2008] 16 S.C.R. 1095",
            "source_url": "https://api.sci.gov.in/jonew/judis/33220.pdf", "chunk_method": "paragraph_number",
            "paragraph_number": "12", "text": "some real chunk text about grievous hurt", "score": 0.55}
with patch("pilot_tier_search.search_pilot_tier", return_value=[FAKE_HIT]):
    out = ca._fetch_pilot_related_judgments("a wooden stick caused a head injury", exclude_case_names=set())
    check(out[0].get("text") == FAKE_HIT["text"], "the raw chunk text is now carried through, not just the UI-list fields")
    check(out[0].get("citation") == FAKE_HIT["citation"], "the citation is carried through too")

# ---------------------------------------------------------------- 2. _format_pilot_context_for_prompt
check(hasattr(ca, "_format_pilot_context_for_prompt"), "chat_assistant exposes _format_pilot_context_for_prompt")

empty = ca._format_pilot_context_for_prompt([])
check(empty == "", "no pilot matches -> empty prompt addition, not a header with nothing under it")
none_case = ca._format_pilot_context_for_prompt(None)
check(none_case == "", "None (the common case, no pilot hits) -> empty string, not a crash")

block = ca._format_pilot_context_for_prompt([PILOT_MATCH])
check("State of Uttar Pradesh v Ram Kishan" in block, "the case name appears in the prompt block")
check("not independently verified" in block.lower() or "not been independently" in block.lower()
      or "nobody has read" in block.lower() or "hasn't been read" in block.lower(),
      "the block explicitly tells the model this pool is unverified")
check("never" in block.lower() and ("held" in block.lower() or "holds" in block.lower()),
      "the block explicitly forbids holding/authority language")
check(len(block) < len(PILOT_MATCH["text"]) + 2000, "a very long chunk is truncated, not dumped in full")

# ---------------------------------------------------------------- 3. _find_pilot_tier_overreach:
# stricter than _find_unsupported_case_generalizations -- ALWAYS flags, no excerpt-support exception,
# since nobody has verified a pilot excerpt represents the case's real holding at all.
check(hasattr(ca, "_find_pilot_tier_overreach"), "chat_assistant exposes _find_pilot_tier_overreach")

overreach_text = "As held in Ram Kishan, you cannot be convicted separately from your co-accused."
check(ca._find_pilot_tier_overreach(overreach_text, [PILOT_MATCH]) == ["State of Uttar Pradesh v Ram Kishan"],
      "holding language ('held') tied to a pilot case name is flagged")

illustrates_text = "A similar case, Ram Kishan, illustrates how courts treat grievous hurt convictions."
check(ca._find_pilot_tier_overreach(illustrates_text, [PILOT_MATCH]) == ["State of Uttar Pradesh v Ram Kishan"],
      "'illustrates' tied to a pilot case name is flagged even though a core-corpus case with a supporting "
      "excerpt would NOT be (this pool never gets that exception)")

safe_text = "A similar case, Ram Kishan v Uttar Pradesh, discusses a comparable situation -- you may want to read it."
check(ca._find_pilot_tier_overreach(safe_text, [PILOT_MATCH]) == [],
      "a purely descriptive mention with no generalization/holding language is never flagged")

no_mention_text = "Section 117(2) of the BNS covers voluntarily causing grievous hurt."
check(ca._find_pilot_tier_overreach(no_mention_text, [PILOT_MATCH]) == [],
      "no pilot case named at all -> nothing to flag")

check(ca._find_pilot_tier_overreach(overreach_text, []) == [], "no pilot matches given -> never flags anything")
check(ca._find_pilot_tier_overreach(overreach_text, None) == [], "None pilot matches -> never flags anything (no crash)")

# ---------------------------------------------------------------- 4. generate_grounded_response wiring:
# the pilot block reaches the actual prompt sent to the model, and the overreach check gates a retry
# exactly like the other hard checks (ungrounded sections, mismatches, ...).
fake_client = MagicMock()


def _resp(text):
    r = MagicMock()
    r.content = [MagicMock(type="text", text=text)]
    return r


with patch.object(ca, "client", fake_client):
    # 4a. a clean answer that safely, descriptively mentions the pilot case -- no retry needed
    fake_client.messages.create.return_value = _resp(
        "Section 117(2) of the BNS covers this. A similar case, Ram Kishan v Uttar Pradesh, discusses a "
        "comparable situation, though it hasn't been independently reviewed here."
    )
    out = ca.generate_grounded_response(
        "some question", "[BNS Section 117(2)]\nsome real statute text", matches=[
            {"act": "BNS", "section_number": "117(2)", "text": "some real statute text"}
        ], pilot_matches=[PILOT_MATCH],
    )
    check(fake_client.messages.create.call_count == 1, "a safe, descriptive answer needs no retry")
    sent_prompt = fake_client.messages.create.call_args.kwargs["messages"][0]["content"]
    check("State of Uttar Pradesh v Ram Kishan" in sent_prompt,
          "the pilot case's text actually reaches the prompt sent to the model -- this is the whole point")
    check(out is not None and "Ram Kishan" in out, "the response is returned as-is")

    # 4b. an overreaching answer on the first try -- triggers exactly one retry with the correction
    fake_client.reset_mock()
    fake_client.messages.create.side_effect = [
        _resp("As held in Ram Kishan, your conviction should be reduced to grievous hurt."),
        _resp("Section 117(2) of the BNS covers this. A similar case, Ram Kishan v Uttar Pradesh, discusses "
              "a comparable situation."),
    ]
    out = ca.generate_grounded_response(
        "some question", "[BNS Section 117(2)]\nsome real statute text", matches=[
            {"act": "BNS", "section_number": "117(2)", "text": "some real statute text"}
        ], pilot_matches=[PILOT_MATCH],
    )
    check(fake_client.messages.create.call_count == 2, "an overreaching first answer triggers exactly one retry")
    retry_prompt = fake_client.messages.create.call_args_list[1].kwargs["messages"][0]["content"]
    check("Ram Kishan" in retry_prompt and ("held" in retry_prompt.lower() or "authority" in retry_prompt.lower()),
          "the retry prompt explains the specific mistake, same pattern as the other retry instructions")
    check(out is not None and "held" not in out.lower(), "the corrected retry answer is returned")

    # 4c. STILL overreaches after the retry -- same 'give up honestly' pattern as the other hard checks
    fake_client.reset_mock()
    fake_client.messages.create.side_effect = [
        _resp("As held in Ram Kishan, your conviction should be reduced to grievous hurt."),
        _resp("The Court in Ram Kishan established that your case will succeed."),
    ]
    out = ca.generate_grounded_response(
        "some question", "[BNS Section 117(2)]\nsome real statute text", matches=[
            {"act": "BNS", "section_number": "117(2)", "text": "some real statute text"}
        ], pilot_matches=[PILOT_MATCH],
    )
    check(out is None,
          "a still-overreaching answer after the retry is discarded entirely, not shown -- the same honest "
          "'give up' signal already used for an ungrounded section or a cognizable/bailable mismatch")

    # 4d. no pilot_matches at all -- behaves exactly as before this feature (regression guard)
    fake_client.reset_mock()
    fake_client.messages.create.return_value = _resp("Section 117(2) of the BNS covers this.")
    out = ca.generate_grounded_response(
        "some question", "[BNS Section 117(2)]\nsome real statute text", matches=[
            {"act": "BNS", "section_number": "117(2)", "text": "some real statute text"}
        ],
    )
    check(fake_client.messages.create.call_count == 1, "with no pilot_matches passed at all, behavior is unchanged")
    sent_prompt = fake_client.messages.create.call_args.kwargs["messages"][0]["content"]
    check("WIDER" not in sent_prompt.upper() or "Ram Kishan" not in sent_prompt,
          "with no pilot_matches, no pilot block is added to the prompt at all")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
