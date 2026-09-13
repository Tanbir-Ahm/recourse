
"""
test_whatsapp_bot.py

Proves the whole WhatsApp pipeline (formatter + store + bot glue)
works correctly WITHOUT any WhatsApp account, BSP, or real phone
number -- Phase 1's entire point. Same lightweight check()/FAILURES
convention as the rest of this repo's test_*.py files (no pytest);
run directly: `python test_whatsapp_bot.py`.

The only real API cost this file could incur is chat_assistant's
Anthropic calls, so those are mocked exactly the way test_chat_grounding.py
already does it (patch chat_assistant.client, feed canned responses) --
this file makes zero real network calls.
"""
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- whatsapp_formatter: every answer_question() state, no API cost at all ----

from whatsapp_formatter import format_answer_for_whatsapp

check(
    format_answer_for_whatsapp({"state": "unrelated"}) != [],
    "unrelated state returns a non-empty, honest message (never silently drops the reply)",
)
check(
    "technical issue" in format_answer_for_whatsapp({"state": "classifier_unavailable"})[0],
    "classifier_unavailable gets its own honest message",
)
check(
    format_answer_for_whatsapp({"state": "no_match"})
    == [
        "I don't have a confident, sourced answer for this yet.",
        "For a real situation, please consult a lawyer or your nearest "
        "District Legal Services Authority (free).",
    ],
    "no_match points to real human help rather than guessing",
)

adjacent = format_answer_for_whatsapp({"state": "adjacent_uncovered", "reasoning": "This touches tax law."})
check(
    len(adjacent) == 2 and "This touches tax law." in adjacent[0] and "District Legal Services" in adjacent[1],
    "adjacent_uncovered includes the reasoning AND the consult line, as two messages",
)

redirect = format_answer_for_whatsapp({"state": "covered_elsewhere_in_tool", "redirect_domain": "cheque_bounce"})
check(
    "cheque bounce" in redirect[0],
    "covered_elsewhere_in_tool turns the redirect_domain into a readable phrase",
)

single = format_answer_for_whatsapp({
    "state": "single_match",
    "response_text": "**Right now**\nAsk for the FIR.\n\nSection 318 of the BNS covers cheating.",
    "situation_detected": True,
})
check(
    single == [
        "*Right now*\nAsk for the FIR.",
        "Section 318 of the BNS covers cheating.",
        "Want a draft court petition based on this? Reply *DRAFT* and I'll prepare one you can download.",
    ],
    "single_match: markdown **bold** -> WhatsApp *bold*, paragraphs split into separate messages, "
    "DRAFT nudge appended only when situation_detected is True",
)

no_draft = format_answer_for_whatsapp({
    "state": "single_match",
    "response_text": "Just an informational answer with no actionable situation.",
    "situation_detected": False,
})
check(
    "DRAFT" not in " ".join(no_draft),
    "the DRAFT nudge is NOT shown when situation_detected is False",
)

conflict = format_answer_for_whatsapp({
    "state": "conflicting_matches",
    "response_text": "Version A applies.\n\nVersion B also applies.",
    "situation_detected": False,
})
check(
    conflict[0].startswith("More than one legal provision"),
    "conflicting_matches gets its own explanatory first message, matching the website's r-conf note",
)

check(
    format_answer_for_whatsapp({"state": "some_future_unknown_state"}) != [],
    "an unrecognised state still fails honestly with a real message, never an empty/silent list",
)


# ---- whatsapp_store: conversation memory, isolated in a real temp file (not :memory:, "
#      since :memory: doesn't persist across the separate connections _connect() opens) ----

import whatsapp_store

_tmp_db = tempfile.mktemp(suffix=".db")
whatsapp_store.DB_PATH = _tmp_db

PHONE = "+911234567890"

whatsapp_store.add_message(PHONE, "user", "My brother was arrested for stealing a goat")
whatsapp_store.add_message(PHONE, "assistant", "Right now, ask for the FIR...")
whatsapp_store.add_message(PHONE, "user", "He doesn't have a lawyer yet")

history = whatsapp_store.get_recent_history(PHONE)
check(
    len(history) == 3 and history[0]["text"] == "My brother was arrested for stealing a goat",
    "get_recent_history returns messages oldest-first, in the order they were added",
)
check(
    history[-1]["role"] == "user" and history[-1]["text"] == "He doesn't have a lawyer yet",
    "the most recent message is last, matching how a follow-up prompt should read",
)

whatsapp_store.clear_history(PHONE)
check(
    whatsapp_store.get_recent_history(PHONE) == [],
    "clear_history actually empties this phone number's conversation",
)

whatsapp_store.add_message(PHONE, "user", "old message")
old_row_time = 0.0  # simulate a message from far in the past directly, bypassing time.time()
import sqlite3
conn = sqlite3.connect(whatsapp_store.DB_PATH)
conn.execute("UPDATE messages SET created_at = ? WHERE phone_number = ?", (old_row_time, PHONE))
conn.commit()
conn.close()
check(
    whatsapp_store.get_recent_history(PHONE, max_age_seconds=3600) == [],
    "a message older than max_age_seconds is treated as an expired, separate conversation",
)

check(
    whatsapp_store.build_question_with_context([], "fresh question") == "fresh question",
    "with no history, the question passed to the engine is unchanged (Phase 1's base case)",
)
built = whatsapp_store.build_question_with_context(
    [{"role": "user", "text": "My brother was arrested for stealing a goat"}],
    "He doesn't have a lawyer yet",
)
check(
    "Earlier in this same conversation" in built
    and "goat" in built
    and built.strip().endswith("He doesn't have a lawyer yet"),
    "with history, the context is prepended in plain prose and the new message stays clearly last",
)

try:
    os.remove(_tmp_db)
except OSError:
    pass


# ---- whatsapp_bot.handle_incoming_message: end to end, chat_assistant.client mocked ----

import whatsapp_bot

_real_send_whatsapp_message = whatsapp_bot.send_whatsapp_message  # saved before it gets monkeypatched below

_tmp_db2 = tempfile.mktemp(suffix=".db")
whatsapp_store.DB_PATH = _tmp_db2

_sent = []
whatsapp_bot.send_whatsapp_message = lambda phone, text: _sent.append((phone, text))


def _fake_response(text):
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    return resp


def _classify_in_scope():
    return _fake_response('{"category": "in_scope", "redirect_domain": null, "reasoning": "arrest, theft"}')


with patch("chat_assistant.client") as mock_client, \
     patch("semantic_retrieval.find_relevant_sections", lambda q: {"state": "no_match", "results": []}):
    mock_client.messages.create.side_effect = [
        _classify_in_scope(),
        _fake_response("**Right now**\nAsk for a copy of the FIR.\n\nSection 303 of the BNS covers theft."),
    ]
    messages = whatsapp_bot.handle_incoming_message(PHONE, "My brother was arrested for stealing a goat")

check(
    len(_sent) == len(messages) and all(p == PHONE for p, _ in _sent),
    "every formatted message actually goes through send_whatsapp_message, addressed to the right phone number",
)
check(
    whatsapp_store.get_recent_history(PHONE)[0]["text"] == "My brother was arrested for stealing a goat",
    "the incoming message gets saved to history before the engine is even called",
)
check(
    "Section 303" in whatsapp_store.get_recent_history(PHONE)[-1]["text"],
    "the engine's clean response_text (not the DRAFT-nudge-decorated WhatsApp messages) is what's stored for future follow-ups",
)

_sent.clear()
reset_reply = whatsapp_bot.handle_incoming_message(PHONE, "new question")
check(
    whatsapp_store.get_recent_history(PHONE) == [],
    "sending 'new question' clears history -- the explicit reset path works without calling the engine at all",
)
check(
    "Starting fresh" in reset_reply[0],
    "the reset path replies immediately, confirming the reset happened",
)

try:
    os.remove(_tmp_db2)
except OSError:
    pass

# The handle_incoming_message tests above monkeypatched
# whatsapp_bot.send_whatsapp_message with a plain lambda (to capture
# what was "sent" without a real call) and never put the real
# implementation back -- restore it, or every test below would
# silently exercise that lambda instead of the actual Gupshup code.
whatsapp_bot.send_whatsapp_message = _real_send_whatsapp_message


# ---- send_whatsapp_message: the real Gupshup call, requests.post mocked (no real send, no real key needed) ----

_orig_api_key = os.environ.pop("GUPSHUP_API_KEY", None)

with patch("whatsapp_bot.logger") as mock_logger:
    whatsapp_bot.send_whatsapp_message("+919876543210", "hello")
    check(
        mock_logger.info.called and not mock_logger.error.called,
        "with no GUPSHUP_API_KEY set, send_whatsapp_message falls back to logging only -- "
        "never makes a real network call, so tests/local dev never need a real key",
    )

os.environ["GUPSHUP_API_KEY"] = "fake-test-key"
with patch("whatsapp_bot.requests") as mock_requests:
    mock_requests.post.return_value = MagicMock(status_code=202, text="")
    whatsapp_bot.send_whatsapp_message("+919876543210", "Right now, ask for the FIR.")
    call = mock_requests.post.call_args
    check(
        call.args[0] == "https://api.gupshup.io/wa/api/v1/msg",
        "hits the exact Gupshup sandbox endpoint shown in the dashboard's Test access API panel",
    )
    check(
        call.kwargs["headers"]["apikey"] == "fake-test-key"
        and call.kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded",
        "sends the api key and content-type headers exactly as Gupshup's own curl example requires",
    )
    data = call.kwargs["data"]
    check(
        data["channel"] == "whatsapp"
        and data["destination"] == "919876543210"  # leading + stripped
        and json.loads(data["message"]) == {"type": "text", "text": "Right now, ask for the FIR."},
        "builds the destination (no leading +) and the message as Gupshup's expected JSON-in-a-form-field shape",
    )

with patch("whatsapp_bot.requests") as mock_requests, patch("whatsapp_bot.logger") as mock_logger:
    mock_requests.post.return_value = MagicMock(status_code=401, text="Invalid API key")
    whatsapp_bot.send_whatsapp_message("+919876543210", "hello")
    check(
        mock_logger.error.called,
        "an error response from Gupshup (e.g. a bad key) is logged, not silently ignored",
    )

with patch("whatsapp_bot.requests") as mock_requests, patch("whatsapp_bot.logger") as mock_logger:
    mock_requests.post.side_effect = Exception("network exploded")
    whatsapp_bot.send_whatsapp_message("+919876543210", "hello")
    check(
        mock_logger.exception.called,
        "a real network failure is caught and logged, never raised -- one failed send must not crash the request",
    )

if _orig_api_key is not None:
    os.environ["GUPSHUP_API_KEY"] = _orig_api_key
else:
    os.environ.pop("GUPSHUP_API_KEY", None)


# ---- _extract_incoming_gupshup: both accepted shapes, plus the honest "unrecognised" case ----

check(
    whatsapp_bot._extract_incoming_gupshup({"phone_number": "+91123", "text": "hi"}) == ("+91123", "hi"),
    "still accepts Phase 1's plain test shape, so test coverage above keeps working unchanged",
)
check(
    whatsapp_bot._extract_incoming_gupshup({
        "entry": [{"changes": [{"value": {
            "messages": [{"from": "919876543210", "type": "text", "text": {"body": "hi there"}}]
        }}]}]
    }) == ("919876543210", "hi there"),
    "parses the real 'Meta format (v3)' shape confirmed from Gupshup's own webhook setup screen",
)
check(
    whatsapp_bot._extract_incoming_gupshup({
        "entry": [{"changes": [{"value": {
            "messages": [{"from": "919876543210", "type": "image"}]
        }}]}]
    }) == (None, None),
    "a non-text message type (image, location, etc.) is honestly left unhandled, not guessed at",
)
check(
    whatsapp_bot._extract_incoming_gupshup({"something": "totally different"}) == (None, None),
    "an unrecognised shape returns (None, None) honestly, rather than crashing or guessing wrong",
)


# ---- summary ----
print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
