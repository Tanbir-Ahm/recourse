
"""
whatsapp_bot.py -- the WhatsApp "front desk" for Recourse.

Receives an incoming WhatsApp message, hands it to the SAME
chat_assistant.answer_question() engine recourse_app.py already uses
(completely unchanged -- this file never imports or modifies anything
in recourse_app.py itself, which is a Streamlit script and can't be
safely imported as a module anyway), and sends back a WhatsApp-
formatted reply.

PHASE 1 (this file, right now): fully runnable and testable on a
laptop with NO WhatsApp Business account, no BSP, no real phone number
at all -- see test_whatsapp_bot.py. The "actually send a WhatsApp
message" step is the one deliberately pluggable piece
(send_whatsapp_message below); right now it just logs what it would
send. Wiring in a real BSP's API call later (see
memory/whatsapp-interface-technical-plan.md) is a one-function change
-- nothing else in this file needs to change when that happens.

PHASE 2 (not yet built): swap send_whatsapp_message's body for a real
HTTP call to the chosen BSP, and change whatsapp_webhook()'s body-
parsing to match whatever shape that BSP actually posts (every BSP's
webhook payload looks slightly different) -- handle_incoming_message()
itself, and everything downstream of it, does not change.

Run locally:
    uvicorn whatsapp_bot:app --reload --port 8001
Then POST to http://localhost:8001/whatsapp/webhook with
{"phone_number": "+911234567890", "text": "..."}
"""
import logging

from fastapi import FastAPI, Request

import chat_assistant
import whatsapp_store
from whatsapp_formatter import format_answer_for_whatsapp

logger = logging.getLogger("whatsapp_bot")
app = FastAPI()

_RESET_WORDS = {"new question", "start over", "reset"}


def send_whatsapp_message(phone_number: str, text: str) -> None:
    """PLACEHOLDER -- Phase 2 replaces this body with a real BSP send-
    message API call. Kept as its own function specifically so that
    swap is the only thing that changes."""
    logger.info("WOULD SEND to %s: %s", phone_number, text)


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


@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """PHASE 1 shape only: a plain {"phone_number": ..., "text": ...}
    body. A real BSP's actual webhook payload will look different --
    this function's body is what Phase 2 rewrites; handle_incoming_message
    itself does not change."""
    payload = await request.json()
    phone_number = payload["phone_number"]
    message_text = payload["text"]
    messages = handle_incoming_message(phone_number, message_text)
    return {"status": "ok", "messages_sent": len(messages)}


@app.get("/whatsapp/health")
async def health():
    return {"status": "ok"}
