
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
from fastapi import FastAPI, Request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv should already be installed (main.py depends on it)

import chat_assistant
import whatsapp_store
from whatsapp_formatter import format_answer_for_whatsapp

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

    result = chat_assistant.answer_question(question)
    messages = format_answer_for_whatsapp(result)

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
    unhandled on purpose -- return (None, None) honestly rather than
    guess at content that isn't there. Also still accepts the plain
    {"phone_number": ..., "text": ...} shape from Phase 1's local
    tests, so that coverage keeps working unchanged."""
    if "phone_number" in payload and "text" in payload:
        return payload["phone_number"], payload["text"]
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        if message.get("type") != "text":
            return None, None
        return message["from"], message["text"]["body"]
    except (KeyError, IndexError, TypeError):
        return None, None


@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """Logs the FULL raw payload on every call -- Gupshup's exact
    inbound shape hasn't been confirmed against a real message yet, so
    the first real one arriving is what fixes _extract_incoming_gupshup
    for good, not further guessing. handle_incoming_message() itself
    never changes regardless of what the real shape turns out to be."""
    payload = await request.json()
    logger.info("RAW incoming webhook payload: %s", json.dumps(payload)[:2000])

    phone_number, message_text = _extract_incoming_gupshup(payload)
    if phone_number is None:
        logger.warning("Could not parse an incoming message out of this payload shape -- see raw log above.")
        return {"status": "unrecognised_payload"}

    messages = handle_incoming_message(phone_number, message_text)
    return {"status": "ok", "messages_sent": len(messages)}


@app.get("/whatsapp/health")
async def health():
    return {"status": "ok"}
