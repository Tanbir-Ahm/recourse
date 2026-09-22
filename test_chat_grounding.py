
"""
test_chat_grounding.py

Regression suite for the deterministic safety nets around
chat_assistant.py's generate_grounded_response(): grounding verification
(2026-09-01) and cognizable/bailable verification (2026-09-01, Phase 2
of the chat-quality plan).

CONFIRMED REAL BUG the grounding net guards against: asked "police came
to my house and arrested me directly saying that i stole a goat" via
the live chat feature, the model's answer confidently named "Section
274 of the BNSS" (summons-case procedure) with an accurate description
of its real text -- but Section 274 never appeared anywhere in what was
actually retrieved for that query. Reproducing the identical question+
retrieved_text pair 9 more times found 0/9 repeats -- a real but
low-frequency, stochastic failure of the "use ONLY the information
provided" instruction, not a deterministic bug, and NOT caused by
citation_currency.py's prompt injection (ruled out via the same
before/after trials). Since no prompt wording can be proven to
eliminate a stochastic LLM failure, this is a deterministic Python
safety net instead.

CONFIRMED GAP the cognizable/bailable net closes: the grounding check
only proves a cited section NUMBER was really retrieved -- it says
nothing about whether the model's CLAIM about that section (cognizable?
bailable?) is correct. find_relevant_sections() already computes that
fact deterministically from BNS_SECTION_DATA (the same table the
compliance engine uses); nothing verified the model's prose against it.

Run with: python test_chat_grounding.py
No API cost -- the Anthropic client is mocked throughout.
"""

import json
import sys
from unittest.mock import patch, MagicMock

import whatsapp_store
from chat_assistant import (
    _extract_section_numbers,
    _find_ungrounded_sections,
    _extract_text_from_response,
    _explicit_section_matches,
    _bns_section_variants,
    _itact_section_variants,
    _gather_offence_variants,
    _find_cognizable_bailable_mismatches,
    _format_mismatch,
    _find_cognizable_bailable_omissions,
    _format_omission,
    _find_unverified_contact_numbers,
    _section_act_map,
    _find_sections_missing_act,
    _find_missing_companion_sections,
    _find_unsupported_case_generalizations,
    _find_court_misattributions,
    generate_grounded_response,
)
from itact_section_data import ITACT_SECTION_DATA

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- _extract_section_numbers ----

check(
    _extract_section_numbers("Section 274 of the BNSS says...") == {"274"},
    "extracts a simple 'Section N' reference",
)
check(
    _extract_section_numbers("section 35(3) applies here, per Section 106.") == {"35", "106"},
    "extracts multiple references, case-insensitive, strips subsection suffix",
)
check(
    _extract_section_numbers("nothing relevant here") == set(),
    "returns an empty set when no section is mentioned",
)
check(
    _extract_section_numbers("") == set(),
    "returns an empty set for empty text, never crashes",
)
check(
    _extract_section_numbers("Section 67A of the IT Act was cited, along with Section 318.") == {"67A", "318"},
    "extracts a lettered section reference ('67A') alongside a bare numeric one "
    "(2026-09-05, Phase 3b -- was silently truncated to '67' before this fix)",
)

# ---- _find_ungrounded_sections: the real confirmed scenario, reproduced with real text ----

REAL_RETRIEVED_TEXT_EXCERPT = (
    "[Vihaan Kumar v State of Haryana, Section/Para 7]\n"
    "7. Sub-Section (1) of Section 41 of CrPC lists cases where police may "
    "arrest a person without a warrant. The corresponding provision in the "
    "Bharatiya Nagarik Suraksha Sanhita, 2023 (for short the BNSS) is "
    "Section 35.\n\n---\n\n"
    "[Malabar Gold and Diamond Limited v Union of India, Section/Para fallback_9]\n"
    "106. Power of police officer to seize certain property."
)

check(
    _find_ungrounded_sections("Section 35 of the BNSS governs this.", REAL_RETRIEVED_TEXT_EXCERPT) == [],
    "a section actually present in retrieved_text is NOT flagged",
)
check(
    _find_ungrounded_sections("Section 106 lets police seize the property.", REAL_RETRIEVED_TEXT_EXCERPT) == [],
    "a second real section, also present, is NOT flagged",
)
check(
    _find_ungrounded_sections(
        "Section 274 of the BNSS covers summons-case procedure, and Section 35 also applies.",
        REAL_RETRIEVED_TEXT_EXCERPT,
    ) == ["274"],
    "REPRODUCES THE CONFIRMED BUG: Section 274 (real, accurately described, but never retrieved for "
    "this query) is correctly flagged as ungrounded, while the real Section 35 reference alongside it is not",
)
check(
    _find_ungrounded_sections("Nothing with a section number here.", REAL_RETRIEVED_TEXT_EXCERPT) == [],
    "a response with no section references at all is trivially not flagged",
)


# ---- generate_grounded_response: retry behavior, client mocked (no API cost) ----

def _fake_response(text):
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    return resp


class _ThinkingBlock:
    """Mimics the real anthropic SDK's ThinkingBlock -- has no .text
    attribute at all, matching the real confirmed crash."""
    def __init__(self):
        self.type = "thinking"
        self.thinking = "some internal reasoning"


class _TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


# ---- _extract_text_from_response: the confirmed real crash ----
# CONFIRMED REAL FAILURE, live 2026-09-01: response.content[0].text raised
# "'ThinkingBlock' object has no attribute 'text'" when the model
# returned a thinking block before its text block, for exactly the goat-
# theft query once the retrieval fix (semantic_retrieval.py's
# TOP_MATCHES_TO_CONSIDER) surfaced enough real candidates to trigger a
# conflicting_matches, more complex prompt. This crash was swallowed by
# generate_grounded_response's try/except and silently returned None,
# masking a client bug as "generation failed."

check(
    _extract_text_from_response(MagicMock(content=[_TextBlock("hello")])) == "hello",
    "extracts text when content[0] is a normal text block",
)
check(
    _extract_text_from_response(MagicMock(content=[_ThinkingBlock(), _TextBlock("the real answer")])) == "the real answer",
    "REPRODUCES THE CONFIRMED CRASH: finds the real text block even when a ThinkingBlock (no .text attribute) comes first",
)
try:
    _extract_text_from_response(MagicMock(content=[_ThinkingBlock()]))
    check(False, "raises (not crashes with AttributeError) when content has no text block at all")
except ValueError:
    check(True, "raises a clean ValueError (not crashes with AttributeError) when content has no text block at all")


with patch("chat_assistant.client") as mock_client:
    # First call hallucinates Section 274; retry is clean -> should return the RETRY text.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 274 of the BNSS covers this, per Section 35."),
        _fake_response("Section 35 of the BNSS covers this."),
    ]
    result = generate_grounded_response("test question", REAL_RETRIEVED_TEXT_EXCERPT)
    check(mock_client.messages.create.call_count == 2, "one retry call is made when the first response is ungrounded")
    check(result == "Section 35 of the BNSS covers this.", "the corrected retry text is returned, not the hallucinated original")

with patch("chat_assistant.client") as mock_client:
    # First call is already clean -> no retry should happen at all.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 35 of the BNSS covers this."),
    ]
    result = generate_grounded_response("test question", REAL_RETRIEVED_TEXT_EXCERPT)
    check(mock_client.messages.create.call_count == 1, "no retry call is made when the first response is already grounded")
    check(result == "Section 35 of the BNSS covers this.", "the original clean text is returned unchanged")

with patch("chat_assistant.client") as mock_client:
    # Both the original AND the retry hallucinate -> must give up honestly (None),
    # never show an unverified claim to the user.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 274 covers this."),
        _fake_response("Section 999 covers this instead."),
    ]
    result = generate_grounded_response("test question", REAL_RETRIEVED_TEXT_EXCERPT)
    check(result is None, "returns None (honest give-up) when even the retry is still ungrounded, never a second wrong answer")


# ---- classify_scope: retry behavior, client mocked (no API cost) ----
# CONFIRMED REAL FAILURE (2026-09-05): a live user question got
# "classifier_unavailable" (the app's generic "something on my end isn't
# working" dead end) even though the SAME question, sampled 20/20 moments
# later directly against classify_scope, classified correctly every
# time -- a single transient failure (API hiccup or an occasional
# malformed-JSON response) with zero retry immediately gave up. Fixed
# with one retry, matching generate_grounded_response's own established
# "one retry, then trust or honestly give up" pattern tested above.

from chat_assistant import classify_scope as _classify_scope_for_mock


def _fake_scope_response(category="in_scope", reasoning="test reasoning", redirect_domain=None):
    body = json.dumps({"category": category, "reasoning": reasoning, "redirect_domain": redirect_domain})
    return _fake_response(body)


with patch("chat_assistant.client") as mock_client:
    # First call raises (simulates a transient network/API failure);
    # second call succeeds cleanly.
    mock_client.messages.create.side_effect = [
        Exception("simulated transient API failure"),
        _fake_scope_response("in_scope", "a real reasoning sentence"),
    ]
    category, reasoning, redirect = _classify_scope_for_mock("test question")
    check(mock_client.messages.create.call_count == 2, "one retry call is made when the first attempt raises")
    check(category == "in_scope" and reasoning == "a real reasoning sentence",
          "the successful retry's result is returned, not a silent None")

with patch("chat_assistant.client") as mock_client:
    # First call returns malformed JSON (simulates the model adding stray
    # text despite the "ONLY a JSON object" instruction); second call is clean.
    mock_client.messages.create.side_effect = [
        _fake_response("Sure, here you go: {\"category\": \"in_scope\""),  # truncated/invalid JSON
        _fake_scope_response("adjacent_uncovered", "a clean second attempt"),
    ]
    category, reasoning, redirect = _classify_scope_for_mock("test question")
    check(mock_client.messages.create.call_count == 2, "one retry call is made when the first response fails to parse")
    check(category == "adjacent_uncovered", "the successful retry's category is returned")

with patch("chat_assistant.client") as mock_client:
    # First call is already clean -> no retry, no wasted second call.
    mock_client.messages.create.side_effect = [
        _fake_scope_response("unrelated", "no legal question here"),
    ]
    category, reasoning, redirect = _classify_scope_for_mock("test question")
    check(mock_client.messages.create.call_count == 1, "no retry call is made when the first attempt already succeeds")
    check(category == "unrelated", "the original clean result is returned unchanged")

with patch("chat_assistant.client") as mock_client:
    # BOTH attempts fail -> honest (None, None, None) give-up, exactly 2
    # calls made (not an infinite loop, not zero).
    mock_client.messages.create.side_effect = [
        Exception("simulated failure 1"),
        Exception("simulated failure 2"),
    ]
    result = _classify_scope_for_mock("test question")
    check(mock_client.messages.create.call_count == 2, "exactly 2 attempts are made, never more")
    check(result == (None, None, None), "returns the honest (None, None, None) give-up when both attempts fail")


# ---------------------------------------------------------------------------
# BATCH 5 (2026-09-22): CONFIRMED REAL FAILURE, TWICE -- classify_scope's
# own reasoning invented a plausible-but-wrong section number when the user
# named none at all ("BNS Section 420" for cheating; "BNS 354" for
# outraging modesty, when the real current section is BNS 74). This field
# is shown VERBATIM to a real person (whatsapp_formatter.py / recourse_
# app.py's adjacent_uncovered handling), so it's a live hallucination risk,
# not an internal curiosity.
# ---------------------------------------------------------------------------
from chat_assistant import _reasoning_section_mentions, _find_ungrounded_reasoning_sections

check(_reasoning_section_mentions("An arrest for cheating falls under BNS Section 420.") == {"420"},
      "'BNS Section 420' phrasing is extracted")
check(_reasoning_section_mentions("Inappropriate touching falls under BNS 354, outraging modesty.") == {"354"},
      "'BNS 354' (no word 'Section' at all -- the harder, real confirmed case) is also extracted")
check(_reasoning_section_mentions("This is about outraging a woman's modesty, a BNS offence.") == set(),
      "reasoning naming no number at all extracts nothing")

check(_find_ungrounded_reasoning_sections("BNS Section 420 covers cheating.",
                                           "my father was arrested for cheating") == ["420"],
      "REPRODUCES THE CONFIRMED FAILURE: a section number in reasoning the user never mentioned "
      "is flagged as ungrounded")
check(_find_ungrounded_reasoning_sections("BNS Section 420 covers cheating.",
                                           "is this covered under BNS 420?") == [],
      "the SAME number is NOT flagged when the user named it themselves")
check(_find_ungrounded_reasoning_sections("This is a cheating offence under the BNS.",
                                           "my father was arrested for cheating") == [],
      "reasoning describing the offence by NAME only (no number) is never flagged")

with patch("chat_assistant.client") as mock_client:
    # A wrong/unprompted number on attempt 1 -> retry WITH a specific
    # correction (not a blind re-roll) -> a clean, number-free retry
    # preserves its full, useful reasoning text.
    mock_client.messages.create.side_effect = [
        _fake_scope_response("in_scope", "This falls under BNS 354, outraging modesty."),
        _fake_scope_response("in_scope", "This is an in-scope offence of outraging a woman's modesty."),
    ]
    category, reasoning, redirect = _classify_scope_for_mock(
        "a colleague touched her inappropriately, he was arrested")
    check(mock_client.messages.create.call_count == 2,
          "an unprompted section number in reasoning triggers exactly one retry")
    _retry_prompt = mock_client.messages.create.call_args_list[1].kwargs["messages"][0]["content"]
    check("IMPORTANT CORRECTION" in _retry_prompt and "354" in _retry_prompt,
          "the retry prompt carries a specific correction naming the bad number, not a blind re-roll")
    check(reasoning == "This is an in-scope offence of outraging a woman's modesty.",
          "a clean, number-free retry's FULL reasoning is preserved (not blanked)")

with patch("chat_assistant.client") as mock_client:
    # Still names an ungrounded number after retry -> reasoning is
    # dropped, but category/redirect_domain are NOT discarded (they're a
    # closed-set classification, not a free-text guess at risk here).
    mock_client.messages.create.side_effect = [
        _fake_scope_response("in_scope", "This falls under BNS 354, outraging modesty."),
        _fake_scope_response("in_scope", "This still falls under BNS 354, outraging modesty."),
    ]
    category, reasoning, redirect = _classify_scope_for_mock(
        "a colleague touched her inappropriately, he was arrested")
    check(category == "in_scope" and reasoning == "",
          "REPRODUCES THE CONFIRMED FAILURE, NOW FIXED: a still-fabricated section number after "
          "retry blanks the reasoning rather than showing a second wrong guess, while the "
          "reliable category is kept")

with patch("chat_assistant.client") as mock_client:
    # No number mentioned at all -> no retry, completely unchanged
    # behaviour for the overwhelming common case.
    mock_client.messages.create.side_effect = [
        _fake_scope_response("in_scope", "This is an in-scope cheating offence."),
    ]
    category, reasoning, redirect = _classify_scope_for_mock("my father was arrested for cheating")
    check(mock_client.messages.create.call_count == 1,
          "no retry call when reasoning names no unprompted section number")
    check(reasoning == "This is an in-scope cheating offence.", "the original reasoning is returned unchanged")

with patch("chat_assistant.client") as mock_client:
    # The user naming their OWN number must never be scrubbed, even if
    # reasoning repeats it back -- only an UNPROMPTED number is a problem.
    mock_client.messages.create.side_effect = [
        _fake_scope_response("in_scope", "BNS Section 420 covers cheating, which is what's described."),
    ]
    category, reasoning, redirect = _classify_scope_for_mock("is 420 IPC applicable to my father's arrest?")
    check(mock_client.messages.create.call_count == 1,
          "no retry when the reasoning's number was already named by the user themselves")
    check("420" in reasoning, "a user-provided number is never scrubbed from reasoning")


# ---------------------------------------------------------------------------
# BATCH 6 (2026-09-22): CONFIRMED REAL FAILURE -- every deterministic keyword/
# pattern matcher in chat_assistant.py (offence anchors, explicit-section
# lookup, statute/judgment doctrine overrides) and the semantic search itself
# were run against the FULL history-included question on WhatsApp, not just
# what the person is currently asking. Reproduced directly: a brand-new
# "my uncle snatched a gold chain" message, sent right after two earlier,
# unrelated exchanges still sitting in the same conversation, re-anchored
# their OLD sections instead of the new one (BNS 304, chain-snatching) --
# see test_whatsapp_bot.py for the full live end-to-end reproduction.
# ---------------------------------------------------------------------------
from chat_assistant import _extract_current_message, _find_relevant_sections_for_turn

check(_extract_current_message("a fresh question with no history") == "a fresh question with no history",
      "no history marker present -> the question is returned unchanged (every non-WhatsApp caller)")
check(_extract_current_message(
    "Earlier in this same conversation:\n- The person asked: old question\n- I answered: old answer"
    "\n\nNow the person says: the actual current question"
) == "the actual current question",
      "REPRODUCES THE CONFIRMED FAILURE'S ROOT CAUSE: the folded-in history is stripped, leaving "
      "only what the person is currently asking")
check(_extract_current_message("") == "" and _extract_current_message(None) == "",
      "empty/None input never crashes")

check(_find_relevant_sections_for_turn(
    "police arrested my brother at night for a fake instagram account", "irrelevant full text"
).get("state") in ("single_match", "conflicting_matches"),
      "a narrow search that finds something real is trusted outright, no fallback needed")
check(_find_relevant_sections_for_turn(
    "asdkjhasdkjh gibberish nonsense", "asdkjhasdkjh gibberish nonsense"
).get("state") == "no_match",
      "when the narrow and full text are IDENTICAL (no history at all) and nothing matches, "
      "there is no redundant second call -- state is simply no_match")


# ---- _explicit_section_matches: "what is section N" lookup (real get_statute_section, no API) ----

from chat_assistant import _explicit_section_matches

m = _explicit_section_matches("what is section 318 of BNS")
check(len(m) == 1 and (m[0]["act"], m[0]["section_number"]) == ("BNS", "318"),
      "'section 318 of BNS' resolves to BNS 318 with real statute text")
check(bool(m[0].get("text")) and m[0]["source"] == "explicit_section_ref",
      "the resolved match carries real text and the explicit_section_ref source tag")

check(_explicit_section_matches("police said i violated section 420") == [],
      "'section 420' (a famous old IPC number, not in BNS) resolves to nothing -- no fabricated section")

mb = _explicit_section_matches("does BNSS 35 require a notice")
check(len(mb) == 1 and mb[0]["act"] == "BNSS" and mb[0]["section_number"] == "35",
      "an explicit 'BNSS 35' is looked up in BNSS, not BNS")

check(_explicit_section_matches("what are my rights if arrested") == [],
      "a question naming no section number yields no explicit match")

multi = _explicit_section_matches("compare section 303 and section 316 of BNS")
check({(x["act"], x["section_number"]) for x in multi} == {("BNS", "303"), ("BNS", "316")},
      "two explicitly named sections both resolve (capped at 2)")

# explicit BNS lookups now carry the Phase 2 enrichment via the shared
# _bns_section_as_match, so they must not have lost all_variants in the refactor
check(bool(_explicit_section_matches("what is section 318 of BNS")[0].get("all_variants")),
      "an explicit BNS section still carries the BNS_SECTION_DATA all_variants enrichment")


# ---- Phase 3b (2026-09-05): IT Act explicit section lookups, including lettered ones ----

itact_66c = _explicit_section_matches("what is section 66C of the IT Act")
check(len(itact_66c) == 1 and (itact_66c[0]["act"], itact_66c[0]["section_number"]) == ("ITACT", "66C"),
      "'section 66C of the IT Act' resolves to ITACT 66C with real statute text")
check(bool(itact_66c[0].get("all_variants")),
      "the resolved ITACT match carries the ITACT_SECTION_DATA all_variants enrichment")

lettered = _explicit_section_matches("what does section 67A of information technology act say")
check(len(lettered) == 1 and lettered[0]["section_number"] == "67A",
      "a LETTERED IT Act section ('67A', no parenthesized subsection) resolves correctly -- "
      "was silently truncated to bare '67' before the digit-group widening")

check(_explicit_section_matches("what is section 66A of the IT Act") == [],
      "'section 66A of the IT Act' resolves to NOTHING via this path -- deliberately excluded "
      "from ITACT_SECTION_DATA/chunks, handled instead by itact_section_status.py's own override")

check(_explicit_section_matches("what is section 67A") == [],
      "an UNQUALIFIED lettered number (no act named) does not silently default to ITACT -- "
      "BNS has no '67A', so this safely resolves to nothing rather than guessing")

bns_still_works = _explicit_section_matches("what is section 318 of BNS")
check(len(bns_still_works) == 1 and bns_still_works[0]["act"] == "BNS",
      "ordinary BNS explicit lookups are unaffected by the IT Act widening")


# ---- Phase 5: offence-keyword anchors (real get_statute_section, no API) ----

from chat_assistant import _offence_keyword_matches

goat = _offence_keyword_matches("police came to my house and arrested me saying that i stole a goat")
check(len(goat) == 1 and (goat[0]["act"], goat[0]["section_number"]) == ("BNS", "303"),
      "REAL-SHAPED GAP: 'stole a goat' anchors deterministically to BNS 303 (theft), not left to the embedding")
check(bool(goat[0].get("text")) and bool(goat[0].get("all_variants")),
      "the anchored match carries real statute text AND the cognizable/bailable enrichment")

check((_offence_keyword_matches("they are accusing me of cheating a customer")[0]["section_number"]) == "318",
      "'cheating' anchors to BNS 318")

check(_offence_keyword_matches("attempted to murder")[0]["section_number"] == "109"
      and _offence_keyword_matches("they say i murdered him")[0]["section_number"] == "103",
      "'attempt to murder' resolves to 109 BEFORE the bare 'murder' -> 103 (order matters)")

check(_offence_keyword_matches("what are my rights if the police arrest me") == [],
      "a message describing no specific offence yields no anchor")

_combo = _offence_keyword_matches("they say i stole the goat and also cheated the buyer")
check(len(_combo) == 2 and {m["section_number"] for m in _combo} == {"303", "318"},
      "REAL-SHAPED GAP FIX (2026-09-04): two distinct named offences both anchor now -- "
      "capping at one silently dropped a genuinely alleged second offence")

_overlap = _offence_keyword_matches("he attempted to murder his neighbour")
check(len(_overlap) == 1 and _overlap[0]["section_number"] == "109",
      "a more specific pattern's own words (\"murder\" inside \"attempted to murder\") do not "
      "ALSO trigger the more general pattern -- span-overlap suppression, not just list order")

# ---- Phase 3b (2026-09-05): IT Act offence-keyword anchors ----

_hack = _offence_keyword_matches("someone hacked into my computer and accessed my files")
check(len(_hack) == 1 and (_hack[0]["act"], _hack[0]["section_number"]) == ("ITACT", "66"),
      "'hacked into my computer' anchors to ITACT 66")

_idtheft = _offence_keyword_matches("my ex is using my password to access my account, that is identity theft")
check({(m["act"], m["section_number"]) for m in _idtheft} == {("ITACT", "66C")},
      "REAL-SHAPED BUG FIX: 'identity theft' anchors ONLY ITACT 66C, not also BNS 303 (theft) -- "
      "the bare word 'theft' inside the phrase must not ALSO trigger the generic theft anchor")

_stolen_pw = _offence_keyword_matches("someone stole my password and logged into my account")
check({(m["act"], m["section_number"]) for m in _stolen_pw} == {("ITACT", "66C")},
      "REAL-SHAPED BUG FIX: 'stole my password' anchors ONLY ITACT 66C, not also BNS 303 -- "
      "the word 'stole' inside the phrase must not ALSO trigger the generic theft anchor")

check([(m["act"], m["section_number"]) for m in _offence_keyword_matches("someone stole my bicycle")] == [("BNS", "303")],
      "an UNRELATED 'stole' (a bicycle, not a password) still anchors ordinary BNS 303 theft")

_fakeprofile = _offence_keyword_matches("a stranger made a fake profile impersonating me online")
check(len(_fakeprofile) == 1 and (_fakeprofile[0]["act"], _fakeprofile[0]["section_number"]) == ("ITACT", "66D"),
      "'fake profile impersonating me' anchors to ITACT 66D")

_morphed = _offence_keyword_matches("someone shared a morphed photo of me without my consent")
check(len(_morphed) == 1 and (_morphed[0]["act"], _morphed[0]["section_number"]) == ("ITACT", "66E"),
      "'morphed photo ... without my consent' anchors to ITACT 66E")

_mixed = _offence_keyword_matches("he hacked my account and also cheated me out of Rs 50000")
check({(m["act"], m["section_number"]) for m in _mixed} == {("ITACT", "66"), ("BNS", "318")},
      "a message naming BOTH a BNS offence and an IT Act one anchors both, in the same pass")

check(_offence_keyword_matches("i was charged under section 66A of the IT act") == [],
      "66A is NEVER keyword-anchored, even when the message names it -- only "
      "itact_section_status.get_itact_status_override handles that, deliberately, "
      "so a struck-down-section flag is never inferred from vocabulary alone")

# ---------------------------------------------------------------------------
# CONFIRMED SERIOUS BUG CLASS (2026-09-04), found via eval_chat_answers.py's
# dowry-wife-complaint case: "my wife has filed a dowry case against me" (the
# wife is ALIVE, this is a harassment complaint) was retrieved and explained
# against BNS 80 (dowry DEATH, 7 years to life) purely on generic "dowry"
# vocabulary overlap. Fixed with an order-sensitive anchor pair -- the death-
# specific pattern must be checked BEFORE the general "dowry" pattern (same
# convention as "attempt to murder" before bare "murder").
# ---------------------------------------------------------------------------
check(_offence_keyword_matches("my wife has filed a dowry case against me and police are "
                                "asking me to come")[0]["section_number"] == "85",
      "REPRODUCES THE CONFIRMED BUG, FIXED: a living wife's dowry-harassment complaint anchors "
      "to BNS 85 (cruelty by husband/relatives), NOT 80 (dowry death)")
check(_offence_keyword_matches("my daughter-in-law keeps demanding dowry and harassing my "
                                "son")[0]["section_number"] == "85",
      "a second dowry-harassment phrasing (no death implied) also anchors to 85")
check(_offence_keyword_matches("my sister died within a year of her marriage after being "
                                "harassed for dowry by her husband")[0]["section_number"] == "80",
      "a GENUINE dowry-death fact pattern (explicit 'died', within the marriage) still anchors "
      "to 80 -- the death-specific pattern is not disabled, only no longer the default for "
      "every 'dowry' mention")
check(_offence_keyword_matches("my sister was burned to death by her in-laws over a dowry "
                                "demand")[0]["section_number"] == "80",
      "a second death-word ('burned to death') also correctly anchors to 80")
_death_case = _offence_keyword_matches("my sister died within a year of her marriage after "
                                        "being harassed for dowry by her husband")
check({m["section_number"] for m in _death_case} == {"80"},
      "a genuine dowry-death case anchors to 80 only -- the general 85 pattern is correctly "
      "suppressed since its match falls entirely inside the death pattern's wider span")


# ---------------------------------------------------------------------------
# CONFIRMED REAL GAP (2026-09-22, found via a ChatGPT side-by-side test):
# "my father hit my uncle during a fight" scored BNS 122 (a narrow,
# provocation-specific section) at 0.36 via semantic search alone -- barely
# above threshold, and the wrong section for a plain "he hit him" claim.
# "he touched her inappropriately" returned no_match outright. Four new
# anchors close this: BNS 115 (simple hurt), 117(2) (grievous hurt,
# specifically -- never the ambiguous bare 117 family), 75 (sexual
# harassment), 74 (assault/force intending to outrage modesty).
# ---------------------------------------------------------------------------
check(_offence_keyword_matches("my father hit my uncle during a fight at a family "
                                "function")[0]["section_number"] == "115",
      "a plain 'X hit Y' claim with no injury detail anchors to BNS 115 (simple hurt)")
check(_offence_keyword_matches("he slapped me in front of everyone")[0]["section_number"] == "115",
      "first-person 'slapped me' phrasing also anchors to 115")
check(_offence_keyword_matches("the news hit me hard when I heard about the arrest") == [],
      "the figurative idiom 'hit me hard' does NOT anchor 115 -- 'hit' alone is not enough")
check(_offence_keyword_matches("it really hit home when I saw him in custody") == [],
      "'hit home' (another figurative idiom) does not anchor 115 either")

_grievous = _offence_keyword_matches("he hit him and broke his arm during the fight")
check([m["section_number"] for m in _grievous] == ["117(2)"],
      "'hit him AND broke his arm' anchors ONLY 117(2) (grievous hurt), not also 115 -- one "
      "injury, one severity tier, not two separate offences")
check(_grievous[0]["all_variants"] == {"117(2)": _grievous[0]["all_variants"]["117(2)"]},
      "the grievous-hurt match keeps 117(2) specifically -- 117(3) (permanent disability, "
      "non-bailable) is never pulled in as a false conflict the facts never implied")
check(_offence_keyword_matches("they broke his arm and he needed surgery")[0]["section_number"] == "117(2)",
      "a standalone injury description with no explicit hit-word still anchors 117(2)")

check(_offence_keyword_matches("he touched her inappropriately and made her "
                                "uncomfortable")[0]["section_number"] == "75",
      "unwelcome-contact/advance phrasing anchors to BNS 75 (sexual harassment)")
check(_offence_keyword_matches("he molested her on the bus")[0]["section_number"] == "74",
      "'molested' anchors to BNS 74 (assault/force intending to outrage modesty) -- a "
      "distinct offence from 75, not the same word list")

for _q in ("the truck hit a pothole on the highway",
           "he hit the road early to reach the court on time",
           "she touched on an important point during the hearing"):
    check(not any(m["section_number"] in ("115", "117(2)", "74", "75")
                  for m in _offence_keyword_matches(_q)),
          f"ordinary non-offence use of these words does not false-positive: {_q!r}")


# ---------------------------------------------------------------------------
# answer_question: 'situation_detected' must survive the statute-override
# FALLBACK paths too, not just the main single_match / conflicting_matches
# branches.
#
# CONFIRMED REAL FAILURE (2026-09-04): when find_relevant_sections()
# returns "no_match" (or "unavailable") and a curated statute_override
# still produces an answer, that fallback returned {"state":
# "single_match", ...} WITHOUT a 'situation_detected' key at all -- so
# app.py's la.get("situation") silently defaulted to falsy and the
# "Prepare a draft to send" button never appeared, for a real arrest
# situation whose only matches were statute overrides. This became more
# likely to actually fire after the out-of-domain judgment-match fix
# above (fewer false-positive judgment_matches padding a real no_match
# result out into the normal single_match branch), which is exactly how
# it was first found live.
# ---------------------------------------------------------------------------
from chat_assistant import answer_question as _answer_question


def _classify_in_scope_response():
    return _fake_response('{"category": "in_scope", "redirect_domain": null, "reasoning": "arrest, cheating"}')


with patch("chat_assistant.client") as mock_client, \
     patch("semantic_retrieval.find_relevant_sections", lambda q: {"state": "no_match", "results": []}):
    mock_client.messages.create.side_effect = [
        _classify_in_scope_response(),
        _fake_response("**Right now**\n1. Ask for a copy of the FIR.\n\nSection 318 of the BNS covers cheating."),
    ]
    fb_result = _answer_question("he cheated me and the police arrested me for it")
    check(fb_result["state"] == "single_match",
          "the no_match + statute_override fallback still answers as single_match")
    check("situation_detected" in fb_result,
          "REAL-SHAPED GAP FIX: the fallback branch now carries 'situation_detected' like every "
          "other answering branch, so the draft button's la.get('situation') check never silently "
          "defaults to falsy for this path")
    check(fb_result["situation_detected"] is True,
          "and it correctly reads True for an answer that opens with the 'Right now' block")


# ---- Phase 2: cognizable/bailable verification -- real BNS_SECTION_DATA, no API cost ----

BNS_318_VARIANTS = _gather_offence_variants(_explicit_section_matches("what is section 318 of BNS"))
BNS_303_VARIANTS = _gather_offence_variants(_explicit_section_matches("what is section 303 of BNS"))

# Distinct from REAL_RETRIEVED_TEXT_EXCERPT (which is about Sections 35/106,
# not 318) so the retry-integration tests below exercise ONLY the
# cognizable/bailable check -- using REAL_RETRIEVED_TEXT_EXCERPT with a
# "Section 318" answer would ALSO trip the (unrelated) grounding check,
# since "318" never appears in that excerpt, confounding the test.
BNS_318_RETRIEVED_TEXT = (
    "[BNS Section 318]\n"
    "318(4). Whoever cheats and thereby dishonestly induces the person "
    "deceived to deliver any property to any person shall be punished "
    "with imprisonment for a term which may extend to seven years, and "
    "shall also be liable to fine."
)

check(
    set(_bns_section_variants("318").keys()) == {"318(2)", "318(3)", "318(4)"},
    "_bns_section_variants('318') returns all three real subsection entries",
)
check(
    _bns_section_variants("999999") == {},
    "_bns_section_variants for a non-existent section returns {}, never crashes",
)
check(
    _itact_section_variants("66D") == {"66D": ITACT_SECTION_DATA["66D"]},
    "_itact_section_variants('66D') returns the real ITACT_SECTION_DATA entry",
)
check(
    set(_itact_section_variants("67").keys()) == {"67"} and _itact_section_variants("67")["67"]["has_multiple_conditions"] is True,
    "_itact_section_variants('67') surfaces the real multi-condition (first/subsequent conviction) entry",
)
check(
    _itact_section_variants("66A") == {},
    "_itact_section_variants('66A') returns {} -- 66A is deliberately absent from ITACT_SECTION_DATA",
)
check(
    _itact_section_variants("999999") == {},
    "_itact_section_variants for a non-existent section returns {}, never crashes",
)
check(
    _gather_offence_variants([]) == {} and _gather_offence_variants(None) == {},
    "_gather_offence_variants handles an empty/None match list",
)
check(
    _gather_offence_variants([{"all_variants": {"a": 1}}, {"all_variants": {"b": 2}}]) == {"a": 1, "b": 2},
    "_gather_offence_variants merges all_variants across every match fed to the prompt",
)

# ---- _gather_offence_variants(extra_text=...): batch 4, hardening the ----
# ---- verified-context callback (see test_whatsapp_bot.py for the full ----
# ---- confirmed-gap writeup and the realistic conversation-history case) --
check(
    _gather_offence_variants([], extra_text="Section 318(4) is cognizable and non-bailable.")
    .get("318(4)", {}).get("bailable") is False,
    "extra_text alone (no matches at all) resolves a specific subsection's real ground truth",
)
check(
    _gather_offence_variants([], extra_text="Section 303 covers theft.") == {"303(2)": BNS_303_VARIANTS["303(2)"]},
    "a bare 'Section 303' in extra_text (no bare '303' key exists in BNS_SECTION_DATA) "
    "resolves to its one real subsection variant, 303(2) -- same lookup _bns_section_variants "
    "does everywhere else, not a fabricated bare-number entry",
)
check(
    _gather_offence_variants([], extra_text="") == {}
    and _gather_offence_variants([], extra_text=None) == {},
    "empty or absent extra_text is a pure no-op",
)

check(
    _find_cognizable_bailable_mismatches("Section 318(4) is cognizable and non-bailable.", BNS_318_VARIANTS) == [],
    "a CORRECT cognizable/bailable claim for a single-condition section is not flagged",
)
_wrong = _find_cognizable_bailable_mismatches(
    "Section 318(4) is non-cognizable and bailable, punishable up to 7 years.", BNS_318_VARIANTS
)
check(
    len(_wrong) == 2 and {p["field"] for p in _wrong} == {"cognizable", "bailable"},
    "REPRODUCES A REAL-SHAPED FAILURE: a wrong cognizable/bailable claim for 318(4) is flagged on both fields",
)
_wrong_by_field = {p["field"]: p for p in _wrong}
check(
    all(p["section"] == "318(4)" for p in _wrong)
    and _wrong_by_field["cognizable"]["claimed"] is False   # text said "non-cognizable"
    and _wrong_by_field["bailable"]["claimed"] is True,     # text said "bailable"
    "each flagged problem carries the exact section and the model's (wrong) claimed value",
)
check(
    "Section 318(4) is cognizable, not non-cognizable as you wrote." in {_format_mismatch(p) for p in _wrong},
    "_format_mismatch renders a clear, specific correction sentence",
)

check(
    _find_cognizable_bailable_mismatches(
        "Section 303(2) is cognizable and non-bailable in the general case.", BNS_303_VARIANTS
    ) == [],
    "303(2) general-case claim NOT flagged -- a real, valid answer for this multi-condition section",
)
check(
    _find_cognizable_bailable_mismatches(
        "Section 303(2) is non-cognizable and bailable if the value is under Rs.5,000 and returned.",
        BNS_303_VARIANTS,
    ) == [],
    "303(2) low-value-carveout claim ALSO not flagged -- the other real, valid answer for the same "
    "section (this is the exact goat-theft fact pattern) -- no false positive on genuine ambiguity",
)
check(
    _find_cognizable_bailable_mismatches("Section 303 covers theft and is cognizable.", BNS_303_VARIANTS) == [],
    "a bare 'Section 303' mention (no subsection) is not flagged even though 303(2)'s two conditions "
    "disagree -- genuinely ambiguous from the number alone, so this stays silent rather than guessing",
)

check(
    _find_cognizable_bailable_mismatches("nothing about any section here", BNS_318_VARIANTS) == [],
    "a response naming no section is trivially not flagged",
)
check(
    _find_cognizable_bailable_mismatches("Section 318(4) is cognizable.", {}) == [],
    "an empty variants dict (no matches carried BNS_SECTION_DATA, e.g. a judgment-only answer) is a pure no-op",
)


# ---------------------------------------------------------------------------
# CONFIRMED REAL GAP (2026-09-22, batch 3 of the ChatGPT side-by-side fix
# queue): a real answer stated BOTH cognizable and bailable for one section
# (117(2)) but only bailable for two others (117(3), 122(2)) discussed the
# same way, despite having the cognizable fact for all three available.
# ---------------------------------------------------------------------------
check(
    _find_cognizable_bailable_omissions("Section 318(4) is cognizable and non-bailable.", BNS_318_VARIANTS) == [],
    "both facts stated for a single-condition section -> nothing omitted",
)
_bail_only = _find_cognizable_bailable_omissions("Section 318(4) is non-bailable, punishable up to 7 years.",
                                                   BNS_318_VARIANTS)
check(_bail_only == [{"section": "318(4)", "missing_field": "cognizable", "value": True}],
      "REPRODUCES THE CONFIRMED GAP: only bailable stated -> the available cognizable fact is flagged missing")
_cog_only = _find_cognizable_bailable_omissions("Section 318(4) is cognizable, punishable up to 7 years.",
                                                  BNS_318_VARIANTS)
check(_cog_only == [{"section": "318(4)", "missing_field": "bailable", "value": False}],
      "the reverse also flags: only cognizable stated -> the available bailable fact is flagged missing")
check(
    "Section 318(4) is also cognizable -- say so." in {_format_omission(p) for p in _bail_only},
    "_format_omission renders a clear, specific 'add this' sentence",
)
check(
    _find_cognizable_bailable_omissions(
        "Section 303(2) is cognizable and non-bailable in the general case.", BNS_303_VARIANTS
    ) == [],
    "a multi-condition section (303(2)) is never flagged for omission -- same carve-out as the mismatch check, "
    "since which of its two real conditions is being described can't be determined from a keyword window alone",
)
check(
    _find_cognizable_bailable_omissions("Section 303 covers theft and is cognizable.", BNS_303_VARIANTS) == [],
    "a bare 'Section 303' mention (genuinely ambiguous subsection) is not flagged for omission either",
)
check(
    _find_cognizable_bailable_omissions("nothing about any section here", BNS_318_VARIANTS) == [],
    "a response naming no section is trivially not flagged",
)
check(
    _find_cognizable_bailable_omissions("Section 318(4) is bailable.", {}) == [],
    "an empty variants dict is a pure no-op, same as the mismatch check",
)


# ---------------------------------------------------------------------------
# CONFIRMED REAL FAILURE this guards against -- not in this project's own
# output, but in a direct side-by-side comparison (2026-09-22): ChatGPT
# stated a specific, invented phone number ("ASLSA helpline: 6901281650")
# for a state the user never named, for a question that gave no location at
# all. This project's own generator is checked against exactly that failure
# class before anything reaches a real user.
# ---------------------------------------------------------------------------
_q = "My father was arrested last night, what should we do?"
_retrieved = "[BNSS Section 41A] Notice of appearance before arrest..."
check(_find_unverified_contact_numbers(
    "You should call the ASLSA helpline at 6901281650 for free legal help.", _q, _retrieved
) == ["6901281650"],
      "REPRODUCES THE CONFIRMED FAILURE CLASS: a helpline number never given by the user or the "
      "retrieved material is flagged")
check(_find_unverified_contact_numbers(
    "You can dial the national emergency number, 100, right away.", _q, _retrieved
) == [],
      "a short (<4-digit) number like the emergency line '100' is below the flag floor -- common "
      "knowledge, not the kind of specific fabricated contact detail this guards against")
check(_find_unverified_contact_numbers(
    "You should consult a lawyer or your nearest District Legal Services Authority.", _q, _retrieved
) == [],
      "ordinary advice with no phone number at all is never flagged")
check(_find_unverified_contact_numbers(
    "Section 302 is punishable with life imprisonment or up to 10 years.", _q, _retrieved
) == [],
      "ordinary legal numbers (punishment years, section numbers) with no contact-type keyword nearby "
      "never trip this -- it is keyword-gated, not a generic 'flag every number' check")
check(_find_unverified_contact_numbers(
    "You can contact the helpline at 6901281650.",
    "My father was arrested, please call 6901281650 for help", _retrieved,
) == [],
      "a number the USER themselves already provided in the question is never flagged -- it wasn't invented")
check(_find_unverified_contact_numbers(
    "You can call the helpline mentioned: 1930.",
    _q, "[Cybercrime helpline] Report financial fraud by calling 1930 immediately.",
) == [],
      "a number that genuinely appears in the retrieved material is never flagged")
check(_find_unverified_contact_numbers("", _q, _retrieved) == [],
      "empty response text is a no-op, never crashes")


with patch("chat_assistant.client") as mock_client:
    # First response gets 318(4)'s status backwards; retry corrects it ->
    # the CORRECTED retry text is returned, mirroring the ungrounded-retry
    # contract exactly (same "one retry, then trust or give up" shape).
    mock_client.messages.create.side_effect = [
        _fake_response("Section 318(4) is non-cognizable and bailable, up to 7 years."),
        _fake_response("Section 318(4) is cognizable and non-bailable, up to 7 years."),
    ]
    result = generate_grounded_response(
        "test question", BNS_318_RETRIEVED_TEXT,
        matches=[{"all_variants": BNS_318_VARIANTS}],
    )
    check(mock_client.messages.create.call_count == 2, "a wrong cognizable/bailable claim triggers exactly one retry")
    check(result == "Section 318(4) is cognizable and non-bailable, up to 7 years.",
          "the corrected retry text is returned")

with patch("chat_assistant.client") as mock_client:
    # Both the original AND the retry get it wrong -> give up honestly (None).
    mock_client.messages.create.side_effect = [
        _fake_response("Section 318(4) is non-cognizable and bailable."),
        _fake_response("Section 318(4) is non-cognizable and bailable."),
    ]
    result = generate_grounded_response(
        "test question", BNS_318_RETRIEVED_TEXT,
        matches=[{"all_variants": BNS_318_VARIANTS}],
    )
    check(result is None, "returns None when even the retry still has the wrong cognizable/bailable claim")

with patch("chat_assistant.client") as mock_client:
    # Correct on the first try -> no retry call, matches param is a pure
    # backward-compatible no-op when the answer is already right.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 318(4) is cognizable and non-bailable."),
    ]
    result = generate_grounded_response(
        "test question", BNS_318_RETRIEVED_TEXT,
        matches=[{"all_variants": BNS_318_VARIANTS}],
    )
    check(mock_client.messages.create.call_count == 1, "no retry call when the claim is already correct")
    check(result == "Section 318(4) is cognizable and non-bailable.", "the original text is returned unchanged")

with patch("chat_assistant.client") as mock_client:
    # BATCH 4 END-TO-END PROOF: matches=[] (THIS TURN's own retrieval found
    # nothing about 318 -- e.g. the question is genuinely about something
    # else) but `question` is a realistic whatsapp_store.build_question_
    # with_context() composite whose folded-in history recalls 318(4).
    # Before this batch, a WRONG recollection here would sail through
    # uncaught (variants would have been {}, a guaranteed no-op). Now it's
    # caught and corrected, exactly like a same-turn mismatch.
    _composite = whatsapp_store.build_question_with_context(
        [{"role": "user", "text": "What are the ingredients for 420 IPC?"},
         {"role": "assistant", "text": "Section 318(4) of the BNS is non-cognizable and bailable."}],
        "Is that the kind of case where police need a warrant?",
    )
    mock_client.messages.create.side_effect = [
        _fake_response("Right, since Section 318(4) is non-cognizable and bailable, a warrant is "
                        "generally needed."),
        _fake_response("Actually, Section 318(4) is cognizable and non-bailable -- a warrant is not "
                        "required."),
    ]
    result = generate_grounded_response(_composite, BNS_318_RETRIEVED_TEXT, matches=[])
    check(mock_client.messages.create.call_count == 2,
          "REPRODUCES THE CONFIRMED GAP, NOW FIXED: a WRONG fact recalled from folded-in "
          "conversation history (not this turn's own retrieval) triggers exactly one retry, "
          "the same as a same-turn mismatch would")
    check(result == "Actually, Section 318(4) is cognizable and non-bailable -- a warrant is not "
                     "required.",
          "the corrected retry text is returned")

with patch("chat_assistant.client") as mock_client:
    # matches=None (every pre-Phase-2 call site/test shape) -> the
    # cognizable/bailable check is a guaranteed no-op, ungrounded-only
    # behavior is completely unchanged.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 35 of the BNSS covers this."),
    ]
    result = generate_grounded_response("test question", REAL_RETRIEVED_TEXT_EXCERPT)
    check(mock_client.messages.create.call_count == 1,
          "backward compatibility: matches=None makes zero difference to the ungrounded-only path")
    check(result == "Section 35 of the BNSS covers this.", "unchanged result for a call with no matches param")


with patch("chat_assistant.client") as mock_client:
    # Omission check is SOFT: a retry is attempted, and the CORRECTED
    # (complete) retry text is returned when the retry adds the missing fact.
    mock_client.messages.create.side_effect = [
        _fake_response("BNS Section 318(4) is non-bailable, up to 7 years."),
        _fake_response("BNS Section 318(4) is cognizable and non-bailable, up to 7 years."),
    ]
    result = generate_grounded_response(
        "test question", BNS_318_RETRIEVED_TEXT,
        matches=[{"all_variants": BNS_318_VARIANTS}],
    )
    check(mock_client.messages.create.call_count == 2,
          "stating only one of two available facts triggers exactly one retry")
    check(result == "BNS Section 318(4) is cognizable and non-bailable, up to 7 years.",
          "the completed retry text is returned")

with patch("chat_assistant.client") as mock_client:
    # Omission check is SOFT: even if the retry is STILL incomplete, the
    # answer is not discarded -- unlike the hard (correctness) checks.
    mock_client.messages.create.side_effect = [
        _fake_response("BNS Section 318(4) is non-bailable, up to 7 years."),
        _fake_response("BNS Section 318(4) is non-bailable, still up to 7 years."),
    ]
    result = generate_grounded_response(
        "test question", BNS_318_RETRIEVED_TEXT,
        matches=[{"all_variants": BNS_318_VARIANTS}],
    )
    check(result == "BNS Section 318(4) is non-bailable, still up to 7 years.",
          "a still-incomplete answer after retry is NOT discarded, unlike a wrong (mismatch) claim")


with patch("chat_assistant.client") as mock_client:
    # Contact-number check is HARD: a fabricated helpline number triggers a
    # retry, and the corrected (number-free) retry text is returned.
    mock_client.messages.create.side_effect = [
        _fake_response("Call the ASLSA helpline at 6901281650 for free legal help."),
        _fake_response("Consult a lawyer or your nearest District Legal Services Authority for free help."),
    ]
    result = generate_grounded_response("what should I do if arrested", REAL_RETRIEVED_TEXT_EXCERPT)
    check(mock_client.messages.create.call_count == 2,
          "REPRODUCES THE CONFIRMED FAILURE CLASS: a fabricated helpline number triggers exactly one retry")
    check(result == "Consult a lawyer or your nearest District Legal Services Authority for free help.",
          "the number-free corrected retry text is returned")

with patch("chat_assistant.client") as mock_client:
    # Contact-number check is HARD: still-fabricated after retry gives up
    # honestly (None), unlike the soft completeness checks.
    mock_client.messages.create.side_effect = [
        _fake_response("Call the ASLSA helpline at 6901281650 for free legal help."),
        _fake_response("Call the ASLSA helpline at 6901281650 again for free legal help."),
    ]
    result = generate_grounded_response("what should I do if arrested", REAL_RETRIEVED_TEXT_EXCERPT)
    check(result is None,
          "a fabricated helpline number still present after retry gives up honestly, unlike a soft omission")


# ---------------------------------------------------------------------------
# Act-name verification (2026-09-04): CONFIRMED REAL BUG -- a live 'Right
# now' answer named Section 36, 58, 166, 164 (all real BNSS sections)
# without ever saying "BNSS" anywhere in the whole answer. BNS and BNSS
# both number from 1, so a bare "Section 36" doesn't tell the reader
# which code applies.
# ---------------------------------------------------------------------------

check(
    _section_act_map([{"act": "BNSS", "section_number": "36"}, {"act": "BNS", "section_number": "318(4)"}])
    == {"36": "BNSS", "318": "BNS"},
    "_section_act_map keys on the base section number, subsection dropped",
)
check(
    _section_act_map([{"act": "BNSS", "section_number": "36"}, {"section_number": "58"}, {"act": "BNS"}]) == {"36": "BNSS"},
    "_section_act_map skips matches missing either 'act' or 'section_number'",
)
check(_section_act_map([]) == {} and _section_act_map(None) == {}, "_section_act_map handles an empty/None match list")

_ACT_MAP = {"36": "BNSS", "58": "BNSS", "166": "BNSS"}
check(
    _find_sections_missing_act(
        "Section 36 of the BNSS requires an arrest memo. Section 58 caps custody at 24 hours.", _ACT_MAP
    ) == [],
    "every cited section's Act is named somewhere in the answer -- nothing flagged",
)
check(
    _find_sections_missing_act(
        "1. Ask for the arrest memo under Section 36. 2. Section 58 caps custody at 24 hours. "
        "3. Section 166 lets a Magistrate intervene in the land dispute.",
        _ACT_MAP,
    ) == ["36", "58", "166"],
    "REPRODUCES THE CONFIRMED BUG: three real BNSS sections cited with 'BNSS' named nowhere in the "
    "whole answer are all flagged",
)
check(
    _find_sections_missing_act("Under the BNSS: Section 36 requires an arrest memo.", _ACT_MAP) == [],
    "naming the Act once, anywhere in the answer, clears every section from that Act -- no per-mention "
    "proximity requirement",
)
check(
    _find_sections_missing_act("Section 36 requires an arrest memo.", {}) == [],
    "an empty section_act_map (no matches carried an 'act', e.g. a judgment-only answer) is a pure no-op",
)
check(
    _find_sections_missing_act("nothing about any section here", _ACT_MAP) == [],
    "a response naming no section is trivially not flagged",
)

# ---------------------------------------------------------------------------
# Phase 3b (2026-09-05): ITACT act-name checking. CONFIRMED REAL GAP,
# caught before it shipped: this check used to search the response text
# for the literal act CODE string -- fine for "BNS"/"BNSS" (the model
# does write those short forms verbatim), but "ITACT" is only this
# project's internal code; a real answer names it "IT Act" or
# "Information Technology Act", never the bare code. Also confirmed:
# sorted(referenced, key=int) crashes outright on a lettered section
# ("67A") before this fix.
# ---------------------------------------------------------------------------

_ITACT_MAP = {"66D": "ITACT", "318": "BNS"}
check(
    _find_sections_missing_act(
        "Section 66D of the Information Technology Act covers this, alongside Section 318 of the BNS.",
        _ITACT_MAP,
    ) == [],
    "naming 'Information Technology Act' in full satisfies the ITACT check (not the bare code 'ITACT')",
)
check(
    _find_sections_missing_act("Section 66D of the IT Act applies here.", {"66D": "ITACT"}) == [],
    "naming the short form 'IT Act' also satisfies the ITACT check",
)
check(
    _find_sections_missing_act("Section 66D applies here, with no Act named.", {"66D": "ITACT"}) == ["66D"],
    "REPRODUCES THE CONFIRMED GAP (pre-fix): an ITACT section cited with neither 'IT Act' nor "
    "'Information Technology Act' anywhere is correctly flagged",
)
check(
    _find_sections_missing_act(
        "Section 67A of the IT Act and Section 36 require attention.", {"67A": "ITACT", "36": "BNSS"}
    ) == ["36"],
    "CONFIRMED FIX: does not crash on a lettered section number when sorting mixed lettered/bare "
    "numbers, and correctly still flags the OTHER section (36/BNSS) whose Act was never named",
)

_ACT_RETRIEVED_TEXT = "[BNSS Section 36]\n36. Every police officer... shall furnish an entry regarding the arrest."

with patch("chat_assistant.client") as mock_client:
    # First response never names the Act; retry names it -> corrected retry text returned.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 36 requires an arrest memo."),
        _fake_response("Section 36 of the BNSS requires an arrest memo."),
    ]
    result = generate_grounded_response(
        "test question", _ACT_RETRIEVED_TEXT,
        matches=[{"act": "BNSS", "section_number": "36"}],
    )
    check(mock_client.messages.create.call_count == 2, "a section cited with no Act name triggers exactly one retry")
    check(result == "Section 36 of the BNSS requires an arrest memo.", "the corrected retry text is returned")

with patch("chat_assistant.client") as mock_client:
    # Both the original AND the retry omit the Act -> give up honestly (None).
    mock_client.messages.create.side_effect = [
        _fake_response("Section 36 requires an arrest memo."),
        _fake_response("Section 36 still requires an arrest memo."),
    ]
    result = generate_grounded_response(
        "test question", _ACT_RETRIEVED_TEXT,
        matches=[{"act": "BNSS", "section_number": "36"}],
    )
    check(result is None, "returns None when even the retry still omits the Act name")

with patch("chat_assistant.client") as mock_client:
    # Already names the Act -> no retry call.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 36 of the BNSS requires an arrest memo."),
    ]
    result = generate_grounded_response(
        "test question", _ACT_RETRIEVED_TEXT,
        matches=[{"act": "BNSS", "section_number": "36"}],
    )
    check(mock_client.messages.create.call_count == 1, "no retry call when the Act is already named")
    check(result == "Section 36 of the BNSS requires an arrest memo.", "the original text is returned unchanged")


# ---------------------------------------------------------------------------
# Companion-section verification (2026-09-04): CONFIRMED REAL GAP -- a
# boundary-plus-shared-irrigation-channel dispute retrieved BOTH BNSS 164
# (possession) and BNSS 166 (right of user), both well within the kept
# matches, but across two live runs of the same fact pattern the model
# named only one of the pair each time.
# ---------------------------------------------------------------------------

_COMPANION_MAP = {"164": "BNSS", "166": "BNSS"}
_SINGLE_MAP = {"164": "BNSS"}

check(
    _find_missing_companion_sections("Section 164 of the BNSS and Section 166 of the BNSS both apply.", _COMPANION_MAP) == [],
    "both companion sections cited -- nothing flagged",
)
check(
    _find_missing_companion_sections("Section 164 of the BNSS lets a Magistrate intervene.", _COMPANION_MAP) == ["166"],
    "REPRODUCES THE CONFIRMED GAP: both 164 and 166 reached the prompt but only 164 was cited -- 166 flagged",
)
check(
    _find_missing_companion_sections("Section 164 of the BNSS lets a Magistrate intervene.", _SINGLE_MAP) == [],
    "only 164 reached the prompt (166 never retrieved) -- never flagged, this question may genuinely not involve a right-of-user dispute",
)
check(
    _find_missing_companion_sections("nothing about any section here", _COMPANION_MAP) == ["164", "166"],
    "neither companion section cited when both were available -- both flagged",
)
check(
    _find_missing_companion_sections("Section 164 of the BNSS applies.", {}) == [],
    "an empty section_act_map is a pure no-op",
)

_COMPANION_RETRIEVED_TEXT = (
    "[BNSS Section 164]\n164. (1) Whenever an Executive Magistrate is satisfied ... concerning any "
    "land or water or the boundaries thereof ...\n\n---\n\n"
    "[BNSS Section 166]\n166. (1) Whenever an Executive Magistrate is satisfied ... regarding any "
    "alleged right of user of any land or water ..."
)
_COMPANION_MATCHES = [
    {"act": "BNSS", "section_number": "164"},
    {"act": "BNSS", "section_number": "166"},
]

with patch("chat_assistant.client") as mock_client:
    # First response names only 164; retry adds 166 -> corrected retry text returned.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 164 of the BNSS lets a Magistrate intervene in the boundary dispute."),
        _fake_response("Section 164 of the BNSS covers the boundary; Section 166 of the BNSS covers the "
                        "irrigation channel's right of use."),
    ]
    result = generate_grounded_response("test question", _COMPANION_RETRIEVED_TEXT, matches=_COMPANION_MATCHES)
    check(mock_client.messages.create.call_count == 2, "a missing companion section triggers exactly one retry")
    check("166" in result, "the retry text that added the companion section is returned")

with patch("chat_assistant.client") as mock_client:
    # Retry STILL omits the companion section -- unlike ungrounded/mismatch/missing-act,
    # this must NOT discard the answer; the retry text is still returned.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 164 of the BNSS lets a Magistrate intervene in the boundary dispute."),
        _fake_response("Section 164 of the BNSS still just covers the boundary dispute."),
    ]
    result = generate_grounded_response("test question", _COMPANION_RETRIEVED_TEXT, matches=_COMPANION_MATCHES)
    check(result is not None and "164" in result,
          "a companion section still missing after retry does NOT give up -- an otherwise-correct "
          "answer is still returned, unlike the other three (correctness) checks")

with patch("chat_assistant.client") as mock_client:
    # Both companion sections already cited -- no retry call.
    mock_client.messages.create.side_effect = [
        _fake_response("Section 164 of the BNSS covers the boundary; Section 166 of the BNSS covers "
                        "the channel's right of use."),
    ]
    result = generate_grounded_response("test question", _COMPANION_RETRIEVED_TEXT, matches=_COMPANION_MATCHES)
    check(mock_client.messages.create.call_count == 1, "no retry call when both companion sections are already cited")


# ---------------------------------------------------------------------------
# Case-generalization verification (2026-09-04): CONFIRMED REAL BUG -- a
# live answer cited "L. Muruganantham v. State of Tamil Nadu" as
# illustrating "how courts do scrutinise whether an arrest in a personal
# dispute was properly justified", but the excerpt actually fed in was
# pure background-fact narrative (what the appellant ALLEGED), never the
# court's own reasoning.
# ---------------------------------------------------------------------------

_MURUGANANTHAM_FACT_MATCH = [{
    "case_name": "L. Muruganantham v State of Tamil Nadu",
    "text": ("It is alleged by the appellant that due to a civil dispute, a false complaint was "
              "lodged against him, and the same was registered as an FIR. Based on the said FIR, "
              "the appellant was arrested and produced before the Judicial Magistrate, who remanded "
              "him to judicial custody."),
}]
_MURUGANANTHAM_HOLDING_MATCH = [{
    "case_name": "L. Muruganantham v State of Tamil Nadu",
    "text": ("Both the SHRC and the High Court unequivocally held that the FIR, arrest, and "
              "incarceration of the appellant were carried out at the behest of his paternal uncle. "
              "The arrest was illegal and did not comply with the safeguards prescribed by this Court."),
}]

check(
    _find_unsupported_case_generalizations(
        "In L. Muruganantham v State of Tamil Nadu, the court illustrates how personal disputes "
        "can lead to arrest.",
        _MURUGANANTHAM_FACT_MATCH,
    ) == ["L. Muruganantham v State of Tamil Nadu"],
    "REPRODUCES THE CONFIRMED BUG: a generalization about a case whose only excerpt is pure "
    "background facts (no holding language) is flagged",
)
check(
    _find_unsupported_case_generalizations(
        "In L. Muruganantham v State of Tamil Nadu, the court illustrates how personal disputes "
        "can lead to arrest.",
        _MURUGANANTHAM_HOLDING_MATCH,
    ) == [],
    "the SAME generalization is NOT flagged when the case's excerpt actually contains the court's "
    "own holding language ('held that...')",
)
check(
    _find_unsupported_case_generalizations(
        "A similar situation was described in L. Muruganantham v State of Tamil Nadu.",
        _MURUGANANTHAM_FACT_MATCH,
    ) == [],
    "a plain factual mention of a case, with no generalization language, is never flagged",
)
check(
    _find_unsupported_case_generalizations(
        "Section 318 of the BNS covers cheating.", _MURUGANANTHAM_FACT_MATCH
    ) == [],
    "an answer with no generalization language at all is trivially not flagged",
)
check(
    _find_unsupported_case_generalizations(
        "This illustrates a general principle.", []
    ) == [],
    "an empty/None match list is a pure no-op even when generalization language is present",
)

_MURUGANANTHAM_RETRIEVED_TEXT = (
    "[L. Muruganantham v State of Tamil Nadu, Section/Para 4]\n" + _MURUGANANTHAM_FACT_MATCH[0]["text"]
)

with patch("chat_assistant.client") as mock_client:
    # First response makes the unsupported generalization; retry drops it -> corrected text returned.
    mock_client.messages.create.side_effect = [
        _fake_response("In L. Muruganantham v State of Tamil Nadu, the case illustrates how courts "
                        "scrutinise arrests in personal disputes."),
        _fake_response("A similar situation was described in L. Muruganantham v State of Tamil Nadu, "
                        "where a false complaint led to an arrest."),
    ]
    result = generate_grounded_response(
        "test question", _MURUGANANTHAM_RETRIEVED_TEXT, matches=_MURUGANANTHAM_FACT_MATCH
    )
    check(mock_client.messages.create.call_count == 2, "an unsupported case generalization triggers exactly one retry")
    check("illustrates" not in (result or ""), "the corrected retry text (generalization dropped) is returned")

with patch("chat_assistant.client") as mock_client:
    # Retry STILL makes the unsupported generalization -- unlike ungrounded/mismatch/missing-act,
    # this must NOT discard the answer; the retry text is still returned.
    mock_client.messages.create.side_effect = [
        _fake_response("L. Muruganantham v State of Tamil Nadu illustrates arrest scrutiny."),
        _fake_response("L. Muruganantham v State of Tamil Nadu still illustrates arrest scrutiny."),
    ]
    result = generate_grounded_response(
        "test question", _MURUGANANTHAM_RETRIEVED_TEXT, matches=_MURUGANANTHAM_FACT_MATCH
    )
    check(result is not None and "Muruganantham" in result,
          "a case generalization still unsupported after retry does NOT give up -- an otherwise-correct "
          "answer is still returned, unlike the other three (correctness) checks")

with patch("chat_assistant.client") as mock_client:
    # No generalization language at all -- no retry call.
    mock_client.messages.create.side_effect = [
        _fake_response("A similar situation was described in L. Muruganantham v State of Tamil Nadu."),
    ]
    result = generate_grounded_response(
        "test question", _MURUGANANTHAM_RETRIEVED_TEXT, matches=_MURUGANANTHAM_FACT_MATCH
    )
    check(mock_client.messages.create.call_count == 1, "no retry call when the response makes no case generalization")


# ---------------------------------------------------------------------------
# Court-attribution verification (2026-09-15): CONFIRMED REAL BUG, found via
# live end-to-end WhatsApp testing of the freeze domain -- asked a real
# freeze question, the model correctly retrieved and correctly described
# Neelkanth Pharma Logistics Pvt. Ltd. v Union of India's real holding, but
# wrote "the Kerala High Court in Neelkanth Pharma Logistics... held..." --
# wrong; Neelkanth is a Delhi High Court case. The mix-up traced to a
# DIFFERENT paragraph from the same case's chunk file (which discusses a
# genuinely different, Kerala-High-Court-decided case) also clearing the
# semantic-search threshold and landing in the same prompt.
# ---------------------------------------------------------------------------

_NEELKANTH_MALABAR_MATCHES = [
    {"case_name": "Neelkanth Pharma Logistics Pvt. Ltd. v Union of India",
     "text": "freezing the entire account is disproportionate"},
    {"case_name": "Malabar Gold and Diamond Limited v Union of India",
     "text": "attachment can only be done under Section 107"},
]

check(
    _find_court_misattributions(
        "Even where a specific sum is genuinely suspected, the Kerala High Court in Neelkanth "
        "Pharma Logistics Pvt. Ltd. v Union of India held that freezing your entire account is "
        "disproportionate. Separately, the Delhi High Court in Malabar Gold and Diamond Limited "
        "v Union of India held that attachment can only be done under Section 107.",
        _NEELKANTH_MALABAR_MATCHES,
    ) == [("Neelkanth Pharma Logistics Pvt. Ltd. v Union of India", "Kerala High Court", "Delhi High Court")],
    "REPRODUCES THE CONFIRMED BUG: Neelkanth misattributed to the Kerala High Court is flagged, "
    "correctly-attributed Malabar Gold is not",
)
check(
    _find_court_misattributions(
        "The Delhi High Court in Neelkanth Pharma Logistics Pvt. Ltd. v Union of India held that "
        "freezing your entire account is disproportionate. The Delhi High Court in Malabar Gold "
        "and Diamond Limited v Union of India held that attachment can only be done under Section 107.",
        _NEELKANTH_MALABAR_MATCHES,
    ) == [],
    "the corrected text (both correctly attributed to the Delhi High Court) is not flagged",
)
check(
    _find_court_misattributions(
        "Neelkanth Pharma Logistics Pvt. Ltd. v Union of India held that freezing an entire "
        "account is disproportionate.",
        _NEELKANTH_MALABAR_MATCHES,
    ) == [],
    "a case mentioned with NO court name at all is never flagged -- this check only catches a "
    "wrong claim, it never demands one",
)
check(
    _find_court_misattributions(
        "The Kerala High Court in an unrelated case held something else entirely.",
        _NEELKANTH_MALABAR_MATCHES,
    ) == [],
    "a court name near a case that was never actually retrieved for this answer is ignored -- "
    "only checks cases present in `matches`",
)
check(
    _find_court_misattributions("", _NEELKANTH_MALABAR_MATCHES) == [],
    "empty response text is a no-op, never crashes",
)
check(
    _find_court_misattributions("The Kerala High Court held something.", []) == [],
    "an empty/None match list is a no-op even when a court name is present",
)

with patch("chat_assistant.client") as mock_client:
    # First response misattributes Neelkanth to the Kerala High Court;
    # retry correctly names the Delhi High Court -> corrected text returned.
    mock_client.messages.create.side_effect = [
        _fake_response(
            "The Kerala High Court in Neelkanth Pharma Logistics Pvt. Ltd. v Union of India held "
            "that freezing your entire account is disproportionate."
        ),
        _fake_response(
            "The Delhi High Court in Neelkanth Pharma Logistics Pvt. Ltd. v Union of India held "
            "that freezing your entire account is disproportionate."
        ),
    ]
    result = generate_grounded_response(
        "test question",
        "[Neelkanth Pharma Logistics Pvt. Ltd. v Union of India, Section/Para 17]\n"
        "freezing the entire account is disproportionate",
        matches=_NEELKANTH_MALABAR_MATCHES,
    )
    check(mock_client.messages.create.call_count == 2, "a court misattribution triggers exactly one retry")
    check(result is not None and "Delhi High Court" in result,
          "the corrected retry text (right court named) is returned")

with patch("chat_assistant.client") as mock_client:
    # Retry STILL misattributes the court -- unlike the case-generalization
    # check, this IS a correctness error and must give up (None), same as
    # ungrounded/mismatch/missing-act.
    mock_client.messages.create.side_effect = [
        _fake_response(
            "The Kerala High Court in Neelkanth Pharma Logistics Pvt. Ltd. v Union of India held "
            "that freezing your entire account is disproportionate."
        ),
        _fake_response(
            "The Kerala High Court in Neelkanth Pharma Logistics Pvt. Ltd. v Union of India still "
            "held that freezing your entire account is disproportionate."
        ),
    ]
    result = generate_grounded_response(
        "test question",
        "[Neelkanth Pharma Logistics Pvt. Ltd. v Union of India, Section/Para 17]\n"
        "freezing the entire account is disproportionate",
        matches=_NEELKANTH_MALABAR_MATCHES,
    )
    check(result is None,
          "a court misattribution still wrong after retry gives up honestly (None), unlike the "
          "soft case-generalization check")


# ---- old IPC/CrPC -> BNS/BNSS translation in retrieved judgment text ----
# (statute_concordance wired into format_retrieved_text_for_prompt, 2026-09-02)

from chat_assistant import _old_code_equivalents, _old_code_refs_note, format_retrieved_text_for_prompt

_JUDG = ("The petitioner was booked under Section 420 of the Indian Penal Code "
         "and the arrest ignored Section 41A of the Code of Criminal Procedure, 1973. "
         "A separate charge under Section 124A IPC was also pressed.")

eqs = _old_code_equivalents(_JUDG)
pairs = {(e["old"], e["new"]) for e in eqs}
check(("IPC 420", "BNS 318(4)") in pairs,
      "judgment text 'Section 420 IPC' -> BNS 318(4) equivalent extracted")
check(any(e["old"] == "CrPC 41A" and e["new"] and "BNSS 35(3)" in e["new"] for e in eqs),
      "'Section 41A of the Code of Criminal Procedure' -> BNSS 35(3)")
check(any(e["old"] == "IPC 124A" and e["new"] is None for e in eqs),
      "repealed 'Section 124A IPC' surfaces with new=None (no re-enacted successor)")
check(any(e["old"] == "IPC 420" and e["changed"] is False for e in eqs)
      and any(e["old"] == "CrPC 41A" for e in eqs),
      "the change flag rides along per-mapping")

check(_old_code_equivalents("your rights on arrest, plainly stated, no section numbers") == [],
      "plain text with no old-code citation -> no equivalents, no false positives")
check(_old_code_equivalents("This turns on Section 35 of the BNSS and Section 103 BNS") == [],
      "a NEW-code 'Section 35 BNSS' reference is never mistaken for an old-code one")

note = _old_code_refs_note(_JUDG)
check("IPC 420 -> BNS 318(4)" in note and "not re-enacted: IPC 124A" in note,
      "the prompt note is one compact line: current equivalents + not-re-enacted list")
check(note.startswith("\n\n[") and note.rstrip().endswith("]")
      and "\n" not in note.strip(),
      "the note stays terse (single appended line) so it can't crowd the answer")

# end to end: format_retrieved_text_for_prompt appends the note to a judgment match,
# and the modern numbers become part of retrieved_text (so the grounding net treats
# an answer that cites BNS 318(4) as grounded, not a hallucination)
rt = format_retrieved_text_for_prompt([{"case_name": "Some v State", "paragraph_number": "7", "text": _JUDG}])
check("318(4)" in rt and "35(3)" in rt,
      "format_retrieved_text_for_prompt folds the modern numbers into retrieved_text")
check(_find_ungrounded_sections("This is now Section 318 of the BNS.", rt) == [],
      "an answer citing the concordance-supplied modern section is NOT flagged ungrounded")


# ---------------------------------------------------------------------------
# extract_arrest_situation -- the bounded fact-extraction for the chat draft
# (client mocked, no API). EXTRACTION ONLY -- decides no verdict.
# ---------------------------------------------------------------------------
from chat_assistant import extract_arrest_situation

_EXTRACT_JSON = """{
  "sections_cited": ["303"],
  "arrestee_gender": "male",
  "arrest_datetime_full": null,
  "production_datetime_full": null,
  "chargesheet_filed_date": null,
  "punishment_years_upper_bound": null,
  "41A_or_35_BNSS_notice_issued_before_arrest": false,
  "grounds_of_arrest_in_writing_furnished_to_arrestee": "unclear",
  "witness_attested_memo": "unclear",
  "family_or_friend_informed": "unclear",
  "medical_exam_at_arrest_recorded": false,
  "female_officer_present_for_female_arrestee": "not applicable",
  "matters_raised": ["he was slapped and kept awake all night", "handcuffed to the hospital bed"]
}"""

with patch("chat_assistant.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response(_EXTRACT_JSON)]
    fields, matters = extract_arrest_situation("user: my uncle was picked up for theft and beaten in custody")
    check(fields is not None, "extract_arrest_situation parses a clean JSON response")
    check(fields["sections_cited"] == ["303"] and fields["medical_exam_at_arrest_recorded"] is False,
          "compliance fields come through; 'no medical' -> False, not 'unclear'")
    check("matters_raised" not in fields, "matters_raised is split out of the fields dict")
    check(matters == ["he was slapped and kept awake all night", "handcuffed to the hospital bed"],
          "matters_raised carries the verbatim-ish grievance phrases")

_EXTRACT_JSON_NO_SEC = _EXTRACT_JSON.replace('"sections_cited": ["303"]', '"sections_cited": []')
with patch("chat_assistant.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response(_EXTRACT_JSON_NO_SEC)]
    fields, _ = extract_arrest_situation("user: my uncle was picked up for theft and beaten in custody")
    check(fields["sections_cited"] == ["303"],
          "when the person says 'theft' but no number, the offence-keyword anchor supplies BNS 303")

with patch("chat_assistant.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response("I can't do that")]
    f, m = extract_arrest_situation("something")
    check(f is None and m == [], "an unparseable response -> (None, []), never a raise")

with patch("chat_assistant.client", None):
    check(extract_arrest_situation("x") == (None, []), "client unavailable -> (None, [])")

check(extract_arrest_situation("   ") == (None, []), "blank conversation -> (None, []), no call")


print("\n" + "=" * 70)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("RESULT: ALL TESTS PASSED")
    sys.exit(0)
