
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
this file makes zero real network calls, with ONE deliberate exception
(batch 6, near the end): a single real end-to-end case proving the
history-folding mechanism doesn't corrupt retrieval, which cannot be
reproduced against a mock -- the bug IS the real embedding search's
ranking behaviour. Same cost-tradeoff test_chat_domain_handoff.py already
accepts, kept to one case here too.
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

with_unverified = format_answer_for_whatsapp({
    "state": "single_match",
    "response_text": "Section 3 covers this.",
    "situation_detected": False,
    "unverified_related_judgments": [
        {"case_name": "Some Real Case v Someone", "ik_search_url": "https://indiankanoon.org/search/?formInput=x",
         "procedural_disposal": False},
        {"case_name": "A Bail Order Case", "ik_search_url": "https://indiankanoon.org/search/?formInput=y",
         "procedural_disposal": True},
    ],
})
check(
    len(with_unverified) == 2 and "haven't personally checked" in with_unverified[-1]
    and "Some Real Case v Someone" in with_unverified[-1]
    and "A Bail Order Case" in with_unverified[-1],
    "unverified_related_judgments becomes its own extra WhatsApp message, clearly separate from the "
    "answer and honestly labelled as not independently verified",
)
check(
    "procedural/bail order" in with_unverified[-1],
    "an entry flagged procedural_disposal=True carries a visible warning, never silently listed the "
    "same way as an unflagged one ('flag, never hide')",
)

without_unverified = format_answer_for_whatsapp({
    "state": "single_match",
    "response_text": "Section 3 covers this.",
    "situation_detected": False,
})
check(
    len(without_unverified) == 1,
    "when unverified_related_judgments is absent (every other domain today), nothing extra is appended",
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


# ---------------------------------------------------------------------------
# CONFIRMED REAL GAP (2026-09-22, batch 4 -- "harden the verified-context
# callback"): a real answer correctly RECALLED a cognizable/bailable fact
# from an earlier, unrelated turn ("Section 318(4)... non-bailable" from a
# question about cheating, reused answering a LATER question about
# anticipatory bail) -- but nothing verified that recollection, because
# chat_assistant._gather_offence_variants only ever read THIS TURN's own
# retrieval matches, which never mention 318 when the question is about
# bail. It was right once because the model is competent, not because
# anything checked it -- the same category of risk this project's entire
# "Python verifies, LLM only phrases" architecture exists to close
# everywhere else.
# ---------------------------------------------------------------------------
from chat_assistant import _gather_offence_variants

_history_with_318 = [
    {"role": "user", "text": "What are the ingredients for 420 IPC?"},
    {"role": "assistant", "text": "Section 318(4) of the BNS is cognizable and non-bailable, "
                                    "punishable with up to 7 years."},
]
_composite_question = whatsapp_store.build_question_with_context(
    _history_with_318, "What is anticipatory bail?"
)
_variants_from_history_alone = _gather_offence_variants([], extra_text=_composite_question)
check(
    _variants_from_history_alone.get("318(4)", {}).get("cognizable") is True
    and _variants_from_history_alone.get("318(4)", {}).get("bailable") is False,
    "REPRODUCES THE CONFIRMED GAP, NOW FIXED: a section mentioned only in the folded-in "
    "conversation history (not this turn's own retrieval) still gets its real, fresh "
    "cognizable/bailable ground truth from the deterministic table -- not just trusted "
    "from the model's own earlier recollection",
)
check(
    _gather_offence_variants([], extra_text="nothing about any section here") == {},
    "extra_text with no section mention is a pure no-op",
)
check(
    _gather_offence_variants([], extra_text=None) == {},
    "extra_text=None (the default -- every pre-batch-4 call site) is unchanged behaviour",
)
_current_turn_data = {"318(4)": {"cognizable": False, "bailable": True}}
_merged_with_both = _gather_offence_variants(
    [{"all_variants": _current_turn_data}], extra_text=_composite_question
)
check(
    _merged_with_both["318(4)"] == {"cognizable": False, "bailable": True},
    "when a section appears in both this turn's own matches AND the history text, this "
    "turn's own data takes precedence (a stable rule -- in practice both read the same "
    "real table, so they can never actually disagree)",
)


# ---- whatsapp_store.classify_confidence / log_qa: the safe learning loop, part 1 ----

check(
    whatsapp_store.classify_confidence("single_match") == "confident",
    "a real, single grounded answer is classified confident",
)
for _state in ("adjacent_uncovered", "no_match", "conflicting_matches"):
    check(
        whatsapp_store.classify_confidence(_state) == "thin",
        f"'{_state}' is classified thin -- the engine's own signal that this is worth a person's review",
    )
for _state in ("classifier_unavailable", "retrieval_unavailable"):
    check(
        whatsapp_store.classify_confidence(_state) == "technical_failure",
        f"'{_state}' is classified technical_failure, separate from a real knowledge gap",
    )
for _state in ("unrelated", "covered_elsewhere_in_tool", "some_future_unknown_state"):
    check(
        whatsapp_store.classify_confidence(_state) == "out_of_scope",
        f"'{_state}' (including an unrecognised future state) falls back to out_of_scope, never crashes",
    )

whatsapp_store.log_qa(PHONE, "What is criminal intimidation?", "no_match")
whatsapp_store.log_qa(PHONE, "My brother was arrested for stealing a goat", "single_match")
conn = sqlite3.connect(whatsapp_store.DB_PATH)
logged = conn.execute(
    "SELECT question, state, confidence FROM qa_log WHERE phone_number = ? ORDER BY created_at", (PHONE,)
).fetchall()
conn.close()
check(
    logged == [
        ("What is criminal intimidation?", "no_match", "thin"),
        ("My brother was arrested for stealing a goat", "single_match", "confident"),
    ],
    "log_qa records the original question, the raw state, AND the classified confidence -- nothing silently dropped",
)


# ---- whatsapp_store.save_draft_context / get_draft_context: what the DRAFT command needs ----

check(
    whatsapp_store.get_draft_context(PHONE) is None,
    "no draft context exists yet for a phone number that's never had an arrest-shaped answer",
)
_matches_1 = [{"act": "BNS", "section_number": "303"}]
whatsapp_store.save_draft_context(PHONE, "My brother was arrested for stealing a goat", _matches_1)
check(
    whatsapp_store.get_draft_context(PHONE) == {
        "question": "My brother was arrested for stealing a goat", "matches": _matches_1,
    },
    "save_draft_context / get_draft_context round-trips the question and matches exactly",
)
_matches_2 = [{"act": "BNS", "section_number": "318"}, {"case_name": "Arnesh Kumar v State of Bihar"}]
whatsapp_store.save_draft_context(PHONE, "a different, later situation", _matches_2)
check(
    whatsapp_store.get_draft_context(PHONE) == {"question": "a different, later situation", "matches": _matches_2},
    "a second save for the same phone number REPLACES the first, rather than accumulating -- "
    "DRAFT should always build from the MOST RECENT arrest-shaped answer",
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
    len(_sent) == len(messages) + 1 and all(p == PHONE for p, _ in _sent),
    "every formatted message goes through send_whatsapp_message, PLUS one immediate "
    "acknowledgment sent before the (slow) engine call -- addressed to the right phone number",
)
check(
    "give me a moment" in _sent[0][1],
    "the acknowledgment is genuinely the FIRST thing sent, before the real answer arrives",
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

# CONFIRMED REAL BUG (2026-09-13), from a real WhatsApp test: a
# bank-freeze question dead-ended with "This looks like a freeze
# question -- ask me about that directly", a redirect that only makes
# sense on the website's own separate freeze/cheque-bounce UI flow --
# there's no "directly" to ask on WhatsApp. recourse_app.py already
# avoids this by always passing inline_domains={"cheque_bounce",
# "freeze"} to answer_question(); this checks whatsapp_bot.py does the
# same, not just that the code happens to work for arrest questions.
with patch("chat_assistant.answer_question") as mock_answer_question:
    mock_answer_question.return_value = {"state": "no_match"}
    whatsapp_bot.handle_incoming_message(PHONE, "my bank account got frozen without notice")
    call_kwargs = mock_answer_question.call_args.kwargs
    check(
        call_kwargs.get("inline_domains") == {"cheque_bounce", "freeze", "domestic_violence"},
        "handle_incoming_message calls answer_question with inline_domains={'cheque_bounce','freeze',"
        "'domestic_violence'}, matching recourse_app.py's own fix for the exact same dead-end redirect "
        "problem -- WhatsApp has no separate UI to redirect these questions to, so they must be answered inline",
    )

# ---- "Reply DRAFT": CONFIRMED REAL GAP fixed 2026-09-14 -- the formatter has
#      always invited this reply, but nothing ever caught it. See
#      whatsapp_bot.py's comment above _build_petition_pdf. ----

with patch("chat_assistant.client") as mock_client, \
     patch("semantic_retrieval.find_relevant_sections", lambda q: {"state": "no_match", "results": []}):
    mock_client.messages.create.side_effect = [
        _classify_in_scope(),
        _fake_response("**Right now**\nAsk for a copy of the FIR.\n\nSection 303 of the BNS covers theft."),
    ]
    whatsapp_bot.handle_incoming_message(PHONE, "My brother was arrested for stealing a goat")

check(
    (whatsapp_store.get_draft_context(PHONE) or {}).get("question") == "My brother was arrested for stealing a goat",
    "an arrest-shaped ('Right now'-opening, situation_detected) answer now saves a draft context, "
    "so a later 'DRAFT' reply has something real to build from",
)

_sent.clear()
draft_no_context = whatsapp_bot.handle_incoming_message("+919999999999", "draft")
check(
    "describe what's happening first" in draft_no_context[0],
    "DRAFT with no prior arrest-shaped answer for THIS phone number replies honestly instead of "
    "crashing or building a blank petition",
)

_orig_base_url = whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://whatsapp-bot-production-969a.up.railway.app"
with patch("whatsapp_bot.send_whatsapp_document") as mock_send_doc:
    mock_send_doc.return_value = True
    draft_reply = whatsapp_bot.handle_incoming_message(PHONE, "draft")
    check(
        mock_send_doc.called and mock_send_doc.call_args.args[0] == PHONE,
        "DRAFT with a saved context actually calls send_whatsapp_document, addressed to the right phone number",
    )
    sent_url = mock_send_doc.call_args.args[1]
    check(
        sent_url.startswith("https://whatsapp-bot-production-969a.up.railway.app/whatsapp/files/")
        and sent_url.endswith(".pdf"),
        "the document URL passed to Gupshup points back at THIS service's own file-serving route",
    )
    check(
        "starting point, not a filed document" in draft_reply[0],
        "a successful DRAFT send tells the person this is a starting point, not legal advice to file as-is",
    )

with patch("whatsapp_bot.send_whatsapp_document") as mock_send_doc:
    mock_send_doc.return_value = False  # Gupshup rejected the send
    draft_reply_failed = whatsapp_bot.handle_incoming_message(PHONE, "DRAFT")  # also proves case-insensitivity
    check(
        "couldn't prepare the draft" in draft_reply_failed[0],
        "when the actual Gupshup send fails, DRAFT replies honestly instead of claiming success",
    )

whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = None
draft_reply_no_url = whatsapp_bot.handle_incoming_message(PHONE, "draft")
check(
    "couldn't prepare the draft" in draft_reply_no_url[0],
    "without WHATSAPP_PUBLIC_BASE_URL configured, DRAFT fails honestly (no URL to link to) "
    "rather than silently pretending to send a document",
)
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = _orig_base_url

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
    whatsapp_bot._extract_incoming_gupshup({"phone_number": "+91123", "text": "hi"}) == ("+91123", "hi", None),
    "still accepts Phase 1's plain test shape (message_id is None for it), so test coverage above keeps working unchanged",
)
check(
    whatsapp_bot._extract_incoming_gupshup({
        "entry": [{"changes": [{"value": {
            "messages": [{"from": "919876543210", "type": "text", "text": {"body": "hi there"}, "id": "wamid.ABC"}]
        }}]}]
    }) == ("919876543210", "hi there", "wamid.ABC"),
    "parses the real 'Meta format (v3)' shape confirmed from Gupshup's own webhook setup screen, including the message id used for dedup",
)
check(
    whatsapp_bot._extract_incoming_gupshup({
        "entry": [{"changes": [{"value": {
            "messages": [{"from": "919876543210", "type": "image"}]
        }}]}]
    }) == (None, None, None),
    "a non-text message type (image, location, etc.) is honestly left unhandled, not guessed at",
)
check(
    whatsapp_bot._extract_incoming_gupshup({"something": "totally different"}) == (None, None, None),
    "an unrecognised shape returns (None, None, None) honestly, rather than crashing or guessing wrong",
)


# ---- whatsapp_webhook endpoint: real HTTP calls via TestClient -- proves the actual retry-storm fix,
#      not just the helper function in isolation ----

from fastapi.testclient import TestClient

_tmp_db3 = tempfile.mktemp(suffix=".db")
whatsapp_store.DB_PATH = _tmp_db3
whatsapp_bot._seen_message_ids.clear()
whatsapp_bot.WEBHOOK_SECRET = "test-secret-value"

_handled = []
whatsapp_bot.handle_incoming_message = lambda phone, text: (_handled.append((phone, text)), [])[1]

client = TestClient(whatsapp_bot.app)

_SAMPLE_PAYLOAD = {
    "entry": [{"changes": [{"value": {
        "messages": [{"from": "919876543210", "type": "text", "text": {"body": "hi"}, "id": "wamid.AUTHCHECK"}]
    }}]}]
}

# ---- CONFIRMED REAL VULNERABILITY (security review, 2026-09-14): the
# webhook had no authentication at all -- these regression-test the fix.
check(
    client.post("/whatsapp/webhook/wrong-secret", json=_SAMPLE_PAYLOAD).status_code == 404
    and len(_handled) == 0,
    "a request with the WRONG secret is rejected with a plain 404, never reaches handle_incoming_message",
)
_saved_secret, whatsapp_bot.WEBHOOK_SECRET = whatsapp_bot.WEBHOOK_SECRET, None
check(
    client.post("/whatsapp/webhook/anything", json=_SAMPLE_PAYLOAD).status_code == 404
    and len(_handled) == 0,
    "FAIL CLOSED: with WHATSAPP_WEBHOOK_SECRET unset entirely, every request is rejected -- "
    "there is no accidental 'unauthenticated mode'",
)
whatsapp_bot.WEBHOOK_SECRET = _saved_secret

resp1 = client.post("/whatsapp/webhook/test-secret-value", json={
    "entry": [{"changes": [{"value": {
        "messages": [{"from": "919876543210", "type": "text", "text": {"body": "hi"}, "id": "wamid.DEDUP1"}]
    }}]}]
})
check(
    resp1.status_code == 200 and resp1.json()["status"] == "accepted",
    "a genuinely new message is accepted (the real work runs as a background task, not inline)",
)
check(
    len(_handled) == 1 and _handled[0] == ("919876543210", "hi"),
    "the background task actually ran and reached handle_incoming_message with the right phone/text",
)

resp2 = client.post("/whatsapp/webhook/test-secret-value", json={
    "entry": [{"changes": [{"value": {
        "messages": [{"from": "919876543210", "type": "text", "text": {"body": "hi"}, "id": "wamid.DEDUP1"}]
    }}]}]
})
check(
    resp2.json()["status"] == "duplicate_ignored" and len(_handled) == 1,
    "CONFIRMED REAL BUG regression check: a retried delivery of the SAME message id is recognised "
    "and skipped -- handle_incoming_message is NOT called a second time, so no duplicate paid answer "
    "and no duplicate WhatsApp reply, matching the exact failure seen live twice on 2026-09-13",
)

resp3 = client.post("/whatsapp/webhook/test-secret-value", json={
    "entry": [{"changes": [{"value": {
        "messages": [{"from": "919876543210", "type": "text", "text": {"body": "a different question"}, "id": "wamid.DEDUP2"}]
    }}]}]
})
check(
    resp3.json()["status"] == "accepted" and len(_handled) == 2,
    "a different, new message id is still processed normally -- dedup only blocks exact repeats",
)

try:
    os.remove(_tmp_db3)
except OSError:
    pass


# ---- _build_petition_pdf: the real reportlab call, no mocking -- cheap, local, no API cost ----

pdf_bytes = whatsapp_bot._build_petition_pdf(
    "My brother was arrested for stealing a goat", [{"act": "BNS", "section_number": "303"}]
)
check(
    isinstance(pdf_bytes, bytes) and pdf_bytes.startswith(b"%PDF"),
    "_build_petition_pdf produces a real, valid PDF file (checked by its own %PDF magic bytes), "
    "the same deterministic, no-LLM path recourse_app.py's own draft-petition feature uses",
)
check(
    whatsapp_bot._build_petition_pdf("anything", None) is not None,
    "a None matches list (e.g. an answer with no BNS sections at all) still produces a PDF, never crashes",
)


# ---- send_whatsapp_document: the Gupshup 'file' message shape, requests mocked ----

os.environ["GUPSHUP_API_KEY"] = "fake-test-key"
with patch("whatsapp_bot.requests") as mock_requests:
    mock_requests.post.return_value = MagicMock(status_code=202, text="")
    ok = whatsapp_bot.send_whatsapp_document(
        "+919876543210", "https://example.com/whatsapp/files/abc.pdf", "recourse_draft_petition.pdf"
    )
    check(ok is True, "a successful (< 400) Gupshup response reports success")
    call = mock_requests.post.call_args
    data = call.kwargs["data"]
    check(
        json.loads(data["message"]) == {
            "type": "file", "url": "https://example.com/whatsapp/files/abc.pdf",
            "filename": "recourse_draft_petition.pdf",
        },
        "sends Gupshup's documented 'file' message shape (type/url/filename), mirroring send_whatsapp_message's "
        "own 'text' shape exactly",
    )

with patch("whatsapp_bot.requests") as mock_requests:
    mock_requests.post.return_value = MagicMock(status_code=400, text="bad request")
    ok = whatsapp_bot.send_whatsapp_document("+919876543210", "https://example.com/x.pdf", "x.pdf")
    check(ok is False, "an error response from Gupshup is reported as failure, not silently swallowed")

with patch("whatsapp_bot.requests") as mock_requests:
    mock_requests.post.side_effect = Exception("network exploded")
    ok = whatsapp_bot.send_whatsapp_document("+919876543210", "https://example.com/x.pdf", "x.pdf")
    check(ok is False, "a real network failure is caught and reported as failure, never raised")

if _orig_api_key is not None:
    os.environ["GUPSHUP_API_KEY"] = _orig_api_key
else:
    os.environ.pop("GUPSHUP_API_KEY", None)


# ---- GET /whatsapp/files/{token}.pdf: serves a generated PDF for Gupshup to fetch ----

file_client = TestClient(whatsapp_bot.app)

_test_pdf_bytes = b"%PDF-1.4 fake pdf content for testing"
_test_token = whatsapp_bot._store_pending_pdf(_test_pdf_bytes)

resp = file_client.get(f"/whatsapp/files/{_test_token}.pdf")
check(
    resp.status_code == 200 and resp.content == _test_pdf_bytes and resp.headers["content-type"] == "application/pdf",
    "a valid, unexpired token serves back the exact PDF bytes with the right content type",
)

resp = file_client.get("/whatsapp/files/not-a-real-token.pdf")
check(
    resp.status_code == 404,
    "an unknown token is rejected with 404, not a crash or a leak of some other person's PDF",
)

import time as _time_module
_expired_token = "expired-test-token"
whatsapp_bot._PENDING_PDFS[_expired_token] = (b"%PDF-old", _time_module.time() - 1)
resp = file_client.get(f"/whatsapp/files/{_expired_token}.pdf")
check(
    resp.status_code == 404,
    "an expired token (past its TTL) is rejected with 404 even though it was once valid -- "
    "a PDF containing someone's real legal situation shouldn't stay fetchable indefinitely",
)


# ---------------------------------------------------------------------------
# BATCH 6 (2026-09-22): the ONE deliberate exception to this file's own
# "zero real network calls" rule (see the module docstring), for the same
# reason test_chat_domain_handoff.py accepts real API cost -- there is no
# way to prove this fix without exercising the ACTUAL history-folding
# mechanism (whatsapp_store.build_question_with_context) plus the real
# embedding search whose ranking behaviour is exactly what broke. Kept to
# a single case.
#
# CONFIRMED REAL FAILURE this reproduces: on the actual WhatsApp thread
# used for today's testing, a brand-new "my uncle snatched a gold chain"
# question -- sent after two earlier, unrelated exchanges (a grievous-hurt
# question, a sexual-harassment question) were still in the conversation --
# came back with NO offence identified at all ("I don't have information
# here on the specific section for chain-snatching/street robbery"), even
# though the exact same question asked fresh, with no history, was
# answered correctly and precisely (BNS 304, chain-snatching, cognizable
# and non-bailable). The old conversation's own sections (117, 75) were
# both re-anchored from the folded-in history text and out-scored the
# real answer in semantic search, crowding it out of the top 5 kept for
# the prompt.
# ---------------------------------------------------------------------------
import chat_assistant

_snatch_history = [
    {"role": "user", "text": "My brother got into an argument with a shopkeeper and ended up hitting "
                              "him -- the shopkeeper's arm got fractured and he needed surgery. The "
                              "police have arrested my brother. What offence would this fall under, "
                              "and is it bailable?"},
    {"role": "assistant", "text": "What is described -- a fracture requiring surgery -- fits grievous "
                                   "hurt under Section 117 of the BNS. Section 117(2) of the BNS "
                                   "applies -- punishable with up to seven years and a fine. This is "
                                   "cognizable and bailable."},
    {"role": "user", "text": "A woman at my sister's workplace has accused a colleague of touching her "
                              "inappropriately and making comments that made her uncomfortable. He has "
                              "been arrested. What section would this come under, and is it bailable?"},
    {"role": "assistant", "text": "What is described -- unwelcome physical contact/advances and "
                                   "sexually coloured remarks -- falls under Section 75 of the BNS, "
                                   "sexual harassment. This carries up to 3 years under Section 75(2), "
                                   "and is a cognizable, non-bailable offence."},
]
_snatch_question_with_history = whatsapp_store.build_question_with_context(
    _snatch_history,
    "The police say my uncle snatched a gold chain from a woman on the street while riding a bike "
    "with another man, and he has been arrested. What offence would this be, and is it bailable?",
)
_snatch_result = chat_assistant.answer_question(
    _snatch_question_with_history, inline_domains={"cheque_bounce", "freeze", "domestic_violence"}
)
_snatch_matches = {(m.get("act"), m.get("section_number")) for m in _snatch_result.get("matches", [])}
check(("BNS", "304") in _snatch_matches,
      f"REPRODUCES THE CONFIRMED FAILURE, NOW FIXED: a brand-new chain-snatching question, sent "
      f"with two earlier, unrelated exchanges still in the conversation, still correctly identifies "
      f"BNS 304 -- got {_snatch_matches!r}")
check(not ({("BNS", "117"), ("BNS", "75")} & _snatch_matches),
      "the OLD conversation's sections (117 grievous hurt, 75 sexual harassment) are NOT "
      "re-anchored from the folded-in history text into this brand-new question's own matches")
_snatch_text = (_snatch_result.get("response_text") or "").lower()
check("304" in _snatch_text,
      "the actual answer text names the correct section, not a generic 'I don't have information "
      "on the specific section' dead end")


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
