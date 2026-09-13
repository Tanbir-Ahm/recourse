
"""
whatsapp_bot.py -- the WhatsApp "front desk" for Recourse.

Receives an incoming WhatsApp message, hands it to the SAME
chat_assistant.answer_question() engine recourse_app.py already uses
(completely unchanged -- this file never imports or modifies anything
in recourse_app.py itself, which is a Streamlit script and can't be
safely imported as a module anyway), and sends back a WhatsApp-
formatted reply.

PHASE 1 (done): fully runnable and testable on a laptop with NO
WhatsApp Business account, no BSP, no real phone number at all -- see
test_whatsapp_bot.py.

PHASE 2 (this update, 2026-09-13): send_whatsapp_message now makes a
real call to Gupshup's sandbox API, confirmed against the exact
request shape shown in Gupshup's own "Test access API" panel:

    curl -X POST https://api.gupshup.io/wa/api/v1/msg \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -H "apikey: {{api_key}}" \
        -d "channel=whatsapp&source=<sandbox number>&destination=<recipient>
            &message={"type":"text","text":"..."}&src.name=<app name>"

Needs three environment variables (see .env): GUPSHUP_API_KEY
(required -- without it, this silently falls back to logging only, so
local dev/tests never accidentally need a real key), GUPSHUP_SOURCE_NUMBER
(defaults to the sandbox number from the dashboard), GUPSHUP_APP_NAME
(defaults to "RecourseA2J").

The INCOMING side (whatsapp_webhook below) is still a best-effort
guess at Gupshup's real inbound payload shape -- Gupshup's own docs
were inconsistent when checked, so this logs the FULL raw payload on
every request (visible in Railway logs) specifically so the very
first real incoming message tells us the ground truth, and the parser
can be corrected immediately against real data rather than guessed
further. handle_incoming_message() itself does not change either way.

Run locally:
    uvicorn whatsapp_bot:app --reload --port 8001
"""
import json
import logging
import os

import requests
from fastapi import BackgroundTasks, FastAPI, Request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv should already be installed (main.py depends on it)

import chat_assistant
import whatsapp_store
from whatsapp_formatter import format_answer_for_whatsapp

# CONFIRMED REAL BUG (2026-09-13): logger.info() calls (the raw-payload
# diagnostic logging on every webhook call, specifically added so the
# first real incoming message would reveal Gupshup's actual shape) were
# never actually appearing in Railway's logs. Python's root logger
# defaults to WARNING -- uvicorn's own request-access lines showed up
# only because uvicorn configures its own logger separately; ours never
# did. Without this, the diagnostic logging existed in the code but was
# invisible in practice.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp_bot")
app = FastAPI()

_RESET_WORDS = {"new question", "start over", "reset"}

GUPSHUP_API_URL = "https://api.gupshup.io/wa/api/v1/msg"
GUPSHUP_SOURCE_NUMBER = os.environ.get("GUPSHUP_SOURCE_NUMBER", "917834811114")
GUPSHUP_APP_NAME = os.environ.get("GUPSHUP_APP_NAME", "RecourseA2J")


def send_whatsapp_message(phone_number: str, text: str) -> None:
    """Real Gupshup sandbox send. Falls back to logging-only (Phase 1's
    original behaviour) if GUPSHUP_API_KEY isn't set at all, so local
    dev and the test suite never need a real key or make a real call.
    Any actual send failure is logged, never raised -- one WhatsApp
    send failing must not crash the whole request, same "fail honestly,
    keep going" discipline as the rest of this codebase."""
    api_key = os.environ.get("GUPSHUP_API_KEY")
    if not api_key:
        logger.info("GUPSHUP_API_KEY not set -- WOULD SEND to %s: %s", phone_number, text)
        return
    destination = phone_number.lstrip("+")
    try:
        resp = requests.post(
            GUPSHUP_API_URL,
            headers={
                "apikey": api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "channel": "whatsapp",
                "source": GUPSHUP_SOURCE_NUMBER,
                "destination": destination,
                "message": json.dumps({"type": "text", "text": text}),
                "src.name": GUPSHUP_APP_NAME,
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.error(
                "Gupshup send to %s failed (%s): %s",
                phone_number, resp.status_code, resp.text[:500],
            )
    except Exception:
        logger.exception("Gupshup send to %s raised an exception", phone_number)


def handle_incoming_message(phone_number: str, message_text: str) -> list:
    """The whole pipeline for one incoming message, kept in its own
    plain function (no FastAPI/HTTP involved) so it can be called
    directly in tests, and later from whatever the real BSP's webhook
    shape turns out to be."""
    message_text = (message_text or "").strip()

    if message_text.lower() in _RESET_WORDS:
        whatsapp_store.clear_history(phone_number)
        reply = "Starting fresh -- tell me what's happening."
        send_whatsapp_message(phone_number, reply)
        return [reply]

    whatsapp_store.add_message(phone_number, "user", message_text)
    history = whatsapp_store.get_recent_history(phone_number)[:-1]  # exclude the message just added
    question = whatsapp_store.build_question_with_context(history, message_text)

    # CONFIRMED REAL ISSUE (2026-09-13): with no immediate reply, a real
    # user sent the same question three times within about a minute
    # (~20s apart -- too spaced out to be a webhook retry, confirmed via
    # the deployed logs), because chat_assistant.answer_question() takes
    # several real seconds (Haiku classify + retrieval + Sonnet
    # generate) and nothing told them it had even been received. Each
    # resend re-ran the full engine for real -- a real, if small, cost,
    # not just a UX rough edge. This mirrors the same "Got it, give me a
    # moment..." acknowledgment already designed for the mocked-up
    # website conversation; it was designed then, never actually built
    # until now.
    send_whatsapp_message(phone_number, "Got it -- give me a moment while I check the law and real judgments...")

    # CONFIRMED REAL BUG (2026-09-13), from a real WhatsApp test: a
    # bank-freeze question came back as "This looks like a freeze
    # question -- ask me about that directly and I can help" -- a dead
    # end on WhatsApp, since there's no separate "directly" flow to ask
    # in a chat. recourse_app.py already solved this exact problem
    # (its own comment: "cheque-bounce and bank-freeze questions are
    # answered inline from the shared corpus rather than dead-ended
    # with a 'covered elsewhere' redirect that points nowhere here")
    # by always passing inline_domains -- WhatsApp needs the same fix,
    # for the same reason: no separate UI to redirect to here either.
    result = chat_assistant.answer_question(question, inline_domains={"cheque_bounce", "freeze"})
    messages = format_answer_for_whatsapp(result)

    # The safe learning loop, part 1: quietly note how confident the
    # engine was on this real question. Never changes this reply or any
    # future one -- purely raw material for a person to review later via
    # whatsapp_weekly_report.py. Logs the person's own original message,
    # not the context-prefixed `question` sent to the engine.
    whatsapp_store.log_qa(phone_number, message_text, result.get("state", "unknown"))

    # Store the engine's own response_text (clean prose) rather than the
    # WhatsApp-formatted messages (which may include the "reply DRAFT"
    # nudge) -- that keeps future follow-up context readable and doesn't
    # replay UI-only prompts back into the engine later.
    reply_for_history = result.get("response_text") or (messages[0] if messages else "")
    whatsapp_store.add_message(phone_number, "assistant", reply_for_history)

    for msg in messages:
        send_whatsapp_message(phone_number, msg)
    return messages


def _extract_incoming_gupshup(payload: dict):
    """Parses the webhook Gupshup's dashboard configures as "Meta
    format (v3)" -- deliberately chosen over Gupshup's own proprietary
    v2 shape specifically because it's Meta's own official, externally
    documented, stable WhatsApp Cloud API webhook format rather than
    something reverse-engineered. Shape:
        {"entry": [{"changes": [{"value": {
            "messages": [{"from": "91...", "type": "text",
                          "text": {"body": "..."}}]
        }}]}]}
    Non-text message types (image, location, etc.) and non-message
    events (delivery/read status, if ever subscribed to) are left
    unhandled on purpose -- return (None, None, None) honestly rather
    than guess at content that isn't there. Also still accepts the
    plain {"phone_number": ..., "text": ...} shape from Phase 1's
    local tests, so that coverage keeps working unchanged (message_id
    is None for that shape -- fine, it's test-only).

    Also returns Meta's own message id ("wamid...") when present, so
    the webhook handler can deduplicate a retried delivery of the SAME
    message (see CONFIRMED REAL BUG note on whatsapp_webhook below)."""
    if "phone_number" in payload and "text" in payload:
        return payload["phone_number"], payload["text"], None
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        if message.get("type") != "text":
            return None, None, None
        return message["from"], message["text"]["body"], message.get("id")
    except (KeyError, IndexError, TypeError):
        return None, None, None


# CONFIRMED REAL BUG (2026-09-13), found from TWO separate real WhatsApp
# tests: a question got answered 3 times, ~20-40s apart -- not a person
# resending (the "Got it, give me a moment" ack fix did NOT stop this,
# ruling that out), but Gupshup's own webhook retrying delivery of the
# SAME message, because handle_incoming_message() used to run the full
# slow pipeline (Haiku classify + retrieval + Sonnet generate -- several
# real seconds) BEFORE this endpoint ever returned an HTTP response.
# Most webhook senders assume "no fast response = failed" and retry.
# Fix, two layers: (1) respond in well under a second by handing the
# real work to FastAPI's BackgroundTasks instead of awaiting it inline;
# (2) belt-and-suspenders, deduplicate by Meta's own message id in case
# a retry still slips through for some other reason (network blip, a
# tighter timeout than expected) -- an in-memory set, capped, good
# enough given this service's storage is already ephemeral between
# deploys (see memory/whatsapp-interface-technical-plan.md).
_seen_message_ids = set()
_SEEN_IDS_CAP = 500


@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Logs the FULL raw payload on every call -- kept even after
    confirming the real Meta-format shape, since a malformed or
    unexpected payload should still be diagnosable from logs, not just
    silently dropped."""
    payload = await request.json()
    logger.info("RAW incoming webhook payload: %s", json.dumps(payload)[:2000])

    phone_number, message_text, message_id = _extract_incoming_gupshup(payload)
    if phone_number is None:
        logger.warning("Could not parse an incoming message out of this payload shape -- see raw log above.")
        return {"status": "unrecognised_payload"}

    if message_id is not None:
        if message_id in _seen_message_ids:
            logger.info("Duplicate delivery of message %s -- skipping, already handled", message_id)
            return {"status": "duplicate_ignored"}
        _seen_message_ids.add(message_id)
        if len(_seen_message_ids) > _SEEN_IDS_CAP:
            _seen_message_ids.pop()

    background_tasks.add_task(handle_incoming_message, phone_number, message_text)
    return {"status": "accepted"}


@app.get("/whatsapp/health")
async def health():
    return {"status": "ok"}
