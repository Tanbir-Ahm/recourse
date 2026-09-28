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

# ---------------------------------------------------------------- 6. topic inference (added 2026-09-27)
# CONFIRMED REAL BUG, found by re-checking wiring before adding a third pilot topic: search_pilot_tier's
# `topic` parameter existed and was tested since 2026-09-26, but the only real caller never passed it --
# every question searched the WHOLE pilot pool (hurt_assault + anticipatory_bail together) regardless of
# topic, silently defeating the cross-topic-leakage protection the parameter exists for. See the
# CONFIRMED REAL BUG comment directly above _infer_pilot_topic in chat_assistant.py for the full story.

HURT_MATCH = {"type": "statute", "act": "BNS", "section_number": "117"}
BAIL_MATCH = {"type": "statute", "act": "BNSS", "section_number": "482"}
THEFT_MATCH = {"type": "statute", "act": "BNS", "section_number": "304"}  # real signal: snatching, not hurt
DEFAULT_BAIL_MATCH = {"type": "statute", "act": "BNSS", "section_number": "479"}  # real signal: default bail, not anticipatory
JUDGMENT_MATCH = {"type": "judgment", "case_name": "Arnesh Kumar v State of Bihar"}  # no act/section_number at all
# CHEATING_MATCH deliberately carries a sub-clause ("318(4)"), the exact real shape confirmed live
# 2026-09-27 for "does non-payment of a loan count as cheating" -- a bare string-equality check
# against "318" would silently miss this; _base_section_number exists specifically to catch it.
CHEATING_MATCH = {"type": "statute", "act": "BNS", "section_number": "318(4)"}
BREACH_OF_TRUST_MATCH = {"type": "statute", "act": "BNS", "section_number": "316"}

check(chat_assistant._infer_pilot_topic([HURT_MATCH]) == "hurt_assault",
      "a real hurt-chapter BNS section (confirmed empirically: 115/117/122 fire for genuine hurt/assault questions) infers hurt_assault")
check(chat_assistant._infer_pilot_topic([BAIL_MATCH]) == "anticipatory_bail",
      "BNSS 482 (confirmed empirically: fires only for genuine anticipatory-bail questions) infers anticipatory_bail")
check(chat_assistant._infer_pilot_topic([CHEATING_MATCH]) == "cheating_civil_dispute",
      "BNS 318 (confirmed empirically for a real loan-non-payment question) infers cheating_civil_dispute, even with a sub-clause suffix")
check(chat_assistant._infer_pilot_topic([BREACH_OF_TRUST_MATCH]) == "cheating_civil_dispute",
      "BNS 316 (confirmed empirically for a real breach-of-trust question) also infers cheating_civil_dispute -- same topic, sibling doctrine")
check(chat_assistant._infer_pilot_topic([HURT_MATCH, BAIL_MATCH]) is None,
      "two signals present at once (ambiguous) -- deliberately falls back to None, never guesses which one wins")
check(chat_assistant._infer_pilot_topic([HURT_MATCH, CHEATING_MATCH]) is None,
      "ambiguity check generalises to the third topic too, not just the original two")
check(chat_assistant._infer_pilot_topic([THEFT_MATCH]) is None,
      "an unrelated statute section (theft, not hurt) infers no topic -- never wrongly narrows to hurt_assault")
check(chat_assistant._infer_pilot_topic([DEFAULT_BAIL_MATCH]) is None,
      "default bail's own section (479) is deliberately NOT in the anticipatory-bail signal set -- the two are different doctrines")
check(chat_assistant._infer_pilot_topic([]) is None, "no matches at all -> None, not an error")
check(chat_assistant._infer_pilot_topic([JUDGMENT_MATCH]) is None,
      "a judgment match with no act/section_number is skipped cleanly, not treated as a signal")
check(chat_assistant._infer_pilot_topic([JUDGMENT_MATCH, HURT_MATCH]) == "hurt_assault",
      "a real signal is still found even when mixed with non-statute matches that carry no act/section_number")
check(chat_assistant._base_section_number("318(4)") == "318" and chat_assistant._base_section_number("122") == "122"
      and chat_assistant._base_section_number(None) is None,
      "_base_section_number strips a sub-clause suffix, leaves a bare number unchanged, and never raises on None")

# ---------------------------------------------------------------- 7. the inferred topic actually reaches search_pilot_tier
with patch("pilot_tier_search.search_pilot_tier", return_value=[]) as fake_search:
    chat_assistant._fetch_pilot_related_judgments("He hit me with a stick and broke my arm", exclude_case_names=set(), matches=[HURT_MATCH])
    check(fake_search.call_args.kwargs.get("topic") == "hurt_assault",
          "a hurt-shaped question's real statute matches narrow the pilot search to topic='hurt_assault'")

with patch("pilot_tier_search.search_pilot_tier", return_value=[]) as fake_search:
    chat_assistant._fetch_pilot_related_judgments("Can I get anticipatory bail before they arrest me?", exclude_case_names=set(), matches=[BAIL_MATCH])
    check(fake_search.call_args.kwargs.get("topic") == "anticipatory_bail",
          "an anticipatory-bail-shaped question's real statute matches narrow the pilot search to topic='anticipatory_bail'")

with patch("pilot_tier_search.search_pilot_tier", return_value=[]) as fake_search:
    chat_assistant._fetch_pilot_related_judgments("q", exclude_case_names=set(), matches=[THEFT_MATCH])
    check(fake_search.call_args.kwargs.get("topic") is None,
          "a question with no confident topic signal still searches the whole pool -- old behaviour, nothing hidden")

with patch("pilot_tier_search.search_pilot_tier", return_value=[]) as fake_search:
    chat_assistant._fetch_pilot_related_judgments("q", exclude_case_names=set())  # matches omitted entirely
    check(fake_search.call_args.kwargs.get("topic") is None,
          "a caller that doesn't pass matches at all keeps the exact old, unfiltered behaviour -- fully backward compatible")

# ---------------------------------------------------------------- 8. end-to-end proof the leakage is actually closed:
# a real hurt_assault question's inferred topic must exclude a real anticipatory_bail case even if it would have
# scored higher on plain similarity -- this is the actual bug from the top of this section, closed for real.
import pilot_tier_search as _pts

REAL_POOL = [
    {"case_name": "Jagrup Singh v State of Haryana", "citation": "", "source_url": "https://example.test/jagrup",
     "chunk_method": "paragraph_number", "paragraph_number": "9", "topic": "hurt_assault",
     "text": "grievous hurt by a dangerous weapon", "embedding": [1.0, 0.0]},
    {"case_name": "Gurbaksh Singh Sibbia v State of Punjab", "citation": "", "source_url": "https://example.test/sibbia",
     "chunk_method": "fixed_size_fallback", "paragraph_number": "fallback_0", "topic": "anticipatory_bail",
     "text": "anticipatory bail under section 438", "embedding": [1.0, 0.0]},  # deliberately IDENTICAL embedding
]
with patch("pilot_tier_search._embed_one", return_value=[1.0, 0.0]), \
     patch("pilot_tier_search.load_pilot_pool", return_value=REAL_POOL):
    unfiltered = _pts.search_pilot_tier("some question")
    check({r["case_name"] for r in unfiltered} == {"Jagrup Singh v State of Haryana", "Gurbaksh Singh Sibbia v State of Punjab"},
          "sanity: with identical scores and no topic filter, BOTH cases are eligible -- reproducing the pre-fix bug")

with patch("pilot_tier_search.search_pilot_tier", wraps=_pts.search_pilot_tier) as wrapped_search, \
     patch("pilot_tier_search._embed_one", return_value=[1.0, 0.0]), \
     patch("pilot_tier_search.load_pilot_pool", return_value=REAL_POOL):
    out = chat_assistant._fetch_pilot_related_judgments("some hurt question", exclude_case_names=set(), matches=[HURT_MATCH])
    names = {o["case_name"] for o in out}
    check("Gurbaksh Singh Sibbia v State of Punjab" not in names,
          "THE ACTUAL FIX: a hurt_assault-shaped question no longer surfaces an anticipatory_bail case, even with an identical similarity score")
    check("Jagrup Singh v State of Haryana" in names,
          "the genuinely on-topic case still comes through correctly")

# ---------------------------------------------------------------- 9. a statute signal alone must not pick the topic
# CONFIRMED REAL BUG (2026-09-28, live WhatsApp): "When can a court issue a non-bailable warrant?" retrieved BNSS 482
# among its side matches; the old inference read that as an anticipatory-bail question and narrowed the pilot search to
# the 3 bail cases (best score 0.454, below the 0.50 bar), hiding Inder Mohan Goswami (0.596 unfiltered) -- the case
# that answers the question. A topic is now inferred only when the section signal AND the question's own wording agree.
WARRANT_Q = "When can a court issue a non-bailable warrant?"
BAIL_Q = "I am scared the police will arrest me. Can I get anticipatory bail?"
WARRANT_SIDE_MATCHES = [{"type": "statute", "act": "BNSS", "section_number": s} for s in ("482", "83", "92", "132", "73")]

check(chat_assistant._infer_pilot_topic(WARRANT_SIDE_MATCHES, WARRANT_Q) is None,
      "THE LIVE BUG: BNSS 482 among a warrant question's side matches no longer infers anticipatory_bail")
check(chat_assistant._infer_pilot_topic(WARRANT_SIDE_MATCHES, BAIL_Q) == "anticipatory_bail",
      "the same matches with a genuine anticipatory-bail question still infer anticipatory_bail")
for phrasing in ("Can I get bail before I am arrested?", "Sessions court advance bail for my brother", "police may arrest me tomorrow, what is section 438?",
                 "I fear arrest in a false case, what can I do to be protected?"):
    check(chat_assistant._infer_pilot_topic([BAIL_MATCH], phrasing) == "anticipatory_bail",
          f"anticipatory-bail wording is recognised -- {phrasing!r}")
check(chat_assistant._infer_pilot_topic([BAIL_MATCH], "Can the High Court quash the FIR under section 482?") is None,
      "'482' alone is NOT an anticipatory-bail cue (old CrPC 482 is the power to quash, the Goswami case itself)")
check(chat_assistant._infer_pilot_topic([CHEATING_MATCH], WARRANT_Q) is None,
      "a stray BNS 318 side match on a warrant question does not narrow to cheating_civil_dispute either")
for phrasing in ("Is not repaying a loan cheating under section 420?", "Can a cheating and forgery FIR be quashed when it is a civil land dispute?",
                 "my partner committed breach of trust with my money"):
    check(chat_assistant._infer_pilot_topic([CHEATING_MATCH], phrasing) == "cheating_civil_dispute",
          f"cheating wording is recognised -- {phrasing!r}")
check(chat_assistant._infer_pilot_topic([HURT_MATCH], "What is the punishment for it?") is None,
      "a hurt-chapter side match on a question with no hurt wording does not narrow to hurt_assault")
check(chat_assistant._infer_pilot_topic([HURT_MATCH], "He beat me with a lathi and I was injured") == "hurt_assault",
      "genuine hurt wording still narrows to hurt_assault")
check(chat_assistant._infer_pilot_topic([HURT_MATCH, BAIL_MATCH], "He hit me and now I fear arrest, is anticipatory bail possible?") is None,
      "two topics BOTH confirmed by wording is still ambiguous -> None, never a guess")
check(chat_assistant._infer_pilot_topic([BAIL_MATCH]) == "anticipatory_bail",
      "with no question passed, the old signal-only inference is unchanged (backward compatible)")

with patch("pilot_tier_search.search_pilot_tier", return_value=[]) as fake_search:
    chat_assistant._fetch_pilot_related_judgments(WARRANT_Q, exclude_case_names=set(), matches=WARRANT_SIDE_MATCHES)
    check(fake_search.call_args.kwargs.get("topic") is None,
          "the fetch path passes NO topic for the warrant question -> the whole pilot pool is searched")

# end to end, on a pool shaped like the real one: the warrant question must reach a cheating-topic case that answers it
WARRANT_POOL = [
    {"case_name": "Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors.", "citation": "", "source_url": "https://example.test/goswami",
     "chunk_method": "fixed_size_fallback", "paragraph_number": "fallback_26", "topic": "cheating_civil_dispute",
     "text": "non-bailable warrants should be avoided", "embedding": [1.0, 0.0]},
    {"case_name": "Gurbaksh Singh Sibbia v State of Punjab", "citation": "", "source_url": "https://example.test/sibbia",
     "chunk_method": "fixed_size_fallback", "paragraph_number": "fallback_0", "topic": "anticipatory_bail",
     "text": "anticipatory bail under section 438", "embedding": [0.0, 1.0]},   # orthogonal: scores 0 for this question
]
with patch("pilot_tier_search._embed_one", return_value=[1.0, 0.0]), patch("pilot_tier_search.load_pilot_pool", return_value=WARRANT_POOL):
    out = chat_assistant._fetch_pilot_related_judgments(WARRANT_Q, exclude_case_names=set(), matches=WARRANT_SIDE_MATCHES)
    check([o["case_name"] for o in out] == ["Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors."],
          "END TO END: the warrant question now surfaces Goswami despite BNSS 482 among its matches")
    out = chat_assistant._fetch_pilot_related_judgments(BAIL_Q, exclude_case_names=set(), matches=WARRANT_SIDE_MATCHES)
    check(all(o["case_name"] != "Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors." for o in out),
          "and a genuine anticipatory-bail question is still confined to the bail topic (cross-topic protection intact)")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
