"""
test_pilot_tier_wiring.py -- wiring pilot_tier_search into chat_assistant's live answer path,
via the SAME already-proven "unverified_related_judgments" mechanism the domestic-violence pool
already uses. Written BEFORE the code. Mocked pilot_tier_search throughout -- no real API calls.

Contract: additive only (never changes response_text/matches/state), never breaks the main answer
if the pilot module fails, excludes cases already cited as curated anchors, and produces entries
in the exact shape both renderers (website + WhatsApp) already know how to display.
Run: python -X utf8 test_pilot_tier_wiring.py
"""
import sys
from unittest.mock import patch

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


import chat_assistant

check(hasattr(chat_assistant, "_fetch_pilot_related_judgments"), "chat_assistant exposes _fetch_pilot_related_judgments")

# ---------------------------------------------------------------- 1. shape + exclusion, mocked
FAKE_HIT = {"case_name": "Prabhu v State of Madhya Pradesh", "citation": "[2008] 16 S.C.R. 1095",
            "source_url": "https://api.sci.gov.in/jonew/judis/33220.pdf", "chunk_method": "paragraph_number",
            "paragraph_number": "12", "score": 0.55}

with patch("pilot_tier_search.search_pilot_tier", return_value=[FAKE_HIT]):
    out = chat_assistant._fetch_pilot_related_judgments("a wooden stick caused a head injury", exclude_case_names=set())
    check(len(out) == 1, f"a genuine match is returned -- got {len(out)}")
    check(out[0]["case_name"] == "Prabhu v State of Madhya Pradesh" and out[0]["ik_search_url"] == FAKE_HIT["source_url"],
          "the real verified government link is carried through into the field the renderers already read")
    check(out[0].get("source") == "pilot_wider_tier", "tagged distinctly from the vaquill pool ('pilot_wider_tier' not 'vaquill')")
    check(out[0].get("paragraph_number") == "12", "the real, earned paragraph number is carried through")

with patch("pilot_tier_search.search_pilot_tier", return_value=[FAKE_HIT]):
    out = chat_assistant._fetch_pilot_related_judgments("q", exclude_case_names={"Prabhu v State of Madhya Pradesh"})
    check(out == [], "a case already cited as a curated anchor is excluded -- never shown twice")

with patch("pilot_tier_search.search_pilot_tier", return_value=[]):
    out = chat_assistant._fetch_pilot_related_judgments("irrelevant question", exclude_case_names=set())
    check(out == [], "no match -> empty list, not an error")

# ---------------------------------------------------------------- 2. fails safe, never breaks the caller
with patch("pilot_tier_search.search_pilot_tier", side_effect=RuntimeError("embeddings file missing")):
    try:
        out = chat_assistant._fetch_pilot_related_judgments("q", exclude_case_names=set())
        check(out == [], "a broken/missing pilot pool returns [] instead of raising -- the main answer is never put at risk")
    except Exception as exc:
        check(False, f"FAIL-OPEN violated: raised {exc!r} instead of returning []")

# ---------------------------------------------------------------- 3. a fixed_size_fallback chunk never claims a fake paragraph
FAKE_FALLBACK = {**FAKE_HIT, "chunk_method": "fixed_size_fallback", "paragraph_number": None}
with patch("pilot_tier_search.search_pilot_tier", return_value=[FAKE_FALLBACK]):
    out = chat_assistant._fetch_pilot_related_judgments("q", exclude_case_names=set())
    check(not out[0].get("paragraph_number"), "a fallback-chunked result carries no paragraph number through -- nothing invented")

# ---------------------------------------------------------------- 4. rendering: both surfaces already handle this shape
import whatsapp_formatter
msg = whatsapp_formatter._format_unverified_judgments([{**FAKE_HIT, "ik_search_url": FAKE_HIT["source_url"], "source": "pilot_wider_tier"}])
check(FAKE_HIT["source_url"] in msg and "Prabhu" in msg, "the WhatsApp renderer displays the real case + real link with zero changes needed")
check("paragraph 12" in msg.lower() or "¶12" in msg, "the WhatsApp message includes the specific paragraph when the entry carries one")

# ---------------------------------------------------------------- 5. answer_question end to end: EVERY branch that
# shares the single_match/conflicting_matches renderer must carry the field, not just _answer_single_match itself.
# CONFIRMED REAL FAILURE (2026-09-23, live site): a real question landed on the 'conflicting_matches' branch of
# answer_question (a separate return statement, never routed through _answer_single_match), so
# unverified_related_judgments was silently absent from the response entirely -- not empty, MISSING -- and the
# pilot tier never got a chance to run. Both renderers treat 'single_match' and 'conflicting_matches' identically
# (recourse_app.py / whatsapp_formatter.py both check `state in ("single_match", "conflicting_matches")`), so both
# must expose the same field.
from unittest.mock import MagicMock

with patch("chat_assistant.classify_scope", return_value=("in_scope", None, None)), \
     patch("chat_assistant._find_relevant_sections_for_turn", return_value={
         "state": "conflicting_matches",
         "matches": [{"case_name": None, "act": "BNS", "section_number": "117", "text": "grievous hurt text"}],
         "judgment_matches": [],
     }), \
     patch("chat_assistant.generate_grounded_response", return_value="a grounded answer"), \
     patch("chat_assistant._fetch_pilot_related_judgments", return_value=[{"case_name": "State of Uttar Pradesh v Ram Kishan"}]) as fake_fetch:
    result = chat_assistant.answer_question("some question that produces conflicting matches")
    check(result.get("state") == "conflicting_matches", "sanity: this test actually exercises the conflicting_matches branch")
    check("unverified_related_judgments" in result, "conflicting_matches carries the SAME field single_match does -- not silently missing")
    check(result.get("unverified_related_judgments") == [{"case_name": "State of Uttar Pradesh v Ram Kishan"}],
          "the pilot tier's real result reaches the conflicting_matches response, not just single_match")
    check(fake_fetch.called, "_fetch_pilot_related_judgments is actually invoked on the conflicting_matches path")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
