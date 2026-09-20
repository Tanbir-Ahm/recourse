
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

SECURITY (added 2026-09-14 after a security review found the webhook had
no authentication at all): set WHATSAPP_WEBHOOK_SECRET in the environment,
and configure Gupshup's dashboard callback URL as
    https://<host>/whatsapp/webhook/<that same secret value>
Without WHATSAPP_WEBHOOK_SECRET set, every request is rejected -- there is
no "unauthenticated mode".
"""
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import time

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import Response

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv should already be installed (main.py depends on it)

import case_document
import case_original
import case_lookup
import chat_assistant
import petition_draft
import whatsapp_store
from arrest_safeguard_checklist import evaluate as _evaluate_arrest_safeguards
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
_DRAFT_WORDS = {"draft"}

GUPSHUP_API_URL = "https://api.gupshup.io/wa/api/v1/msg"
GUPSHUP_SOURCE_NUMBER = os.environ.get("GUPSHUP_SOURCE_NUMBER", "917834811114")
GUPSHUP_APP_NAME = os.environ.get("GUPSHUP_APP_NAME", "RecourseA2J")

# CONFIRMED REAL GAP (found 2026-09-14, re-reading this file after shipping
# the answer cache): whatsapp_formatter's "Reply *DRAFT*" nudge has been
# live since the very first WhatsApp deploy, but nothing ever caught that
# reply -- the website's single most concrete feature (a real, downloadable
# petition PDF) was advertised on WhatsApp and silently did nothing. Fixed
# below. Sending a document via Gupshup needs a URL it can fetch (unlike
# text, there is no "just POST the bytes" option) -- this service has no
# other public file host, so the generated PDF is served from a short-
# lived, one-per-request URL on this same app instead of a real object
# store, matching this project's "build the smallest real thing" pattern.
WHATSAPP_PUBLIC_BASE_URL = os.environ.get("WHATSAPP_PUBLIC_BASE_URL")
_PENDING_PDFS = {}  # token -> (pdf_bytes, expires_at)
_PENDING_PDF_TTL_SECONDS = 600
_PENDING_PDFS_CAP = 50
_PENDING_MAX_TOTAL_BYTES = 120 * 1024 * 1024


_PENDING_DOCX = {}  # token -> (docx_bytes, expires_at), same TTL/cap as _PENDING_PDFS


def _store_pending(store: dict, data: bytes) -> str:
    now = time.time()
    for tok in [t for t, (_, exp) in store.items() if exp <= now]:
        del store[tok]
    if len(store) >= _PENDING_PDFS_CAP:
        oldest = min(store, key=lambda t: store[t][1])
        del store[oldest]
    # Original judgment PDFs can be several MB each: also cap the TOTAL bytes held, evicting the oldest.
    while store and sum(len(v[0]) for v in store.values()) + len(data) > _PENDING_MAX_TOTAL_BYTES:
        del store[min(store, key=lambda t: store[t][1])]
    token = secrets.token_urlsafe(24)
    store[token] = (data, now + _PENDING_PDF_TTL_SECONDS)
    return token


def _store_pending_pdf(pdf_bytes: bytes) -> str:
    return _store_pending(_PENDING_PDFS, pdf_bytes)


def _store_pending_docx(docx_bytes: bytes) -> str:
    return _store_pending(_PENDING_DOCX, docx_bytes)


def _build_petition_pdf(question: str, matches: list):
    """The general-form draft petition (recourse_app.py's own fallback
    when no uploaded document or completed checklist exists yet --
    `arrest_safeguard_checklist.evaluate({})`) -- the only version that
    makes sense on WhatsApp, since there's no document-upload or
    multi-question checklist flow here. Pure Python, no LLM, same as the
    website. Returns the PDF bytes, or None if anything went wrong (a
    failed PDF must not crash the request)."""
    try:
        civil, secs = petition_draft.derive_draft_context(matches)
        seed = _evaluate_arrest_safeguards({})
        draft_text = petition_draft.from_checklist(question, seed, civil_dispute=civil, offence_sections=secs)
        out_path = os.path.join(tempfile.gettempdir(), f"whatsapp_petition_{secrets.token_hex(8)}.pdf")
        petition_draft.to_pdf(draft_text, output_path=out_path)
        with open(out_path, "rb") as fh:
            data = fh.read()
        os.remove(out_path)
        return data
    except Exception:
        logger.exception("Failed to build petition PDF for a WhatsApp DRAFT request")
        return None

# CONFIRMED REAL VULNERABILITY (found by security review, 2026-09-14): this
# webhook had NO authentication at all -- anyone who found the URL could
# POST any phone_number + text and it would be processed exactly like a
# real incoming WhatsApp message (real Anthropic API spend, a real outbound
# WhatsApp send to any destination they named, and unauthenticated writes/
# deletes against that phone number's stored conversation). Gupshup's
# sandbox dashboard doesn't offer a signed-webhook option, so the fix is a
# shared secret embedded in the callback URL PATH itself (the one thing
# every webhook provider supports, since it's just "the URL you configure
# them to POST to") -- see whatsapp_webhook below. WHATSAPP_WEBHOOK_SECRET
# must be set in the deployment environment; if it is not, EVERY request is
# rejected (fail closed, never fail open) rather than silently running
# unauthenticated.
WEBHOOK_SECRET = os.environ.get("WHATSAPP_WEBHOOK_SECRET")


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
        # DIAGNOSTIC (2026-09-16): logged unconditionally, not just on an
        # obvious HTTP error -- a real production send silently reached
        # neither branch below (no error log, no exception, message never
        # arrived), right after this number was Go-Live'd via Gupshup's
        # "MM Lite" embedded signup. The existing code only ever checked
        # resp.status_code, never the response BODY -- if Gupshup accepts
        # the request (2xx) but the body itself reports a soft failure
        # (e.g. an app/number mismatch specific to the new production
        # onboarding), that would previously have been invisible. This
        # logs source/app-name actually used plus the full raw response
        # every time, so the next real send reveals the truth instead of
        # requiring another guess. Safe to remove once the real cause is
        # confirmed and fixed.
        logger.info(
            "Gupshup send to %s -- source=%s app_name=%s status=%s body=%s",
            phone_number, GUPSHUP_SOURCE_NUMBER, GUPSHUP_APP_NAME, resp.status_code, resp.text[:1000],
        )
        if resp.status_code >= 400:
            logger.error(
                "Gupshup send to %s failed (%s): %s",
                phone_number, resp.status_code, resp.text[:500],
            )
    except Exception:
        logger.exception("Gupshup send to %s raised an exception", phone_number)


def send_whatsapp_document(phone_number: str, url: str, filename: str, caption: str = None) -> bool:
    """Sends a file/document message via Gupshup -- the 'file' message
    type shape per Gupshup's own docs (mirrors send_whatsapp_message's
    'text' shape exactly, just a different `message` JSON payload).
    UNLIKE a text message, Gupshup must be able to fetch `url` itself, so
    it needs to be a real, reachable, public URL (see WHATSAPP_PUBLIC_BASE_URL
    and _store_pending_pdf above) -- not tested against a real send yet as
    of writing this; the shape is the best-documented guess, matching this
    project's established pattern of shipping the best-understood shape and
    correcting it against the first real send if needed. Returns True only
    if the send looks like it succeeded, so the caller can fall back to a
    text-only message rather than silently pretending a file arrived."""
    api_key = os.environ.get("GUPSHUP_API_KEY")
    if not api_key:
        logger.info("GUPSHUP_API_KEY not set -- WOULD SEND FILE to %s: %s", phone_number, url)
        return False
    destination = phone_number.lstrip("+")
    message = {"type": "file", "url": url, "filename": filename}
    if caption:
        message["caption"] = caption
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
                "message": json.dumps(message),
                "src.name": GUPSHUP_APP_NAME,
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            logger.error(
                "Gupshup file send to %s failed (%s): %s",
                phone_number, resp.status_code, resp.text[:500],
            )
            return False
        return True
    except Exception:
        logger.exception("Gupshup file send to %s raised an exception", phone_number)
        return False


# --- Case lookup ("CASE: <name>" -> the judgment as a PDF/Word file) --------
# Designed 2026-09-16 (memory/case-lookup-whatsapp-feature-design.md). A plain
# keyword command, deliberately NOT routed through classify_scope: a lookup
# request must never depend on an AI judgment call to be recognised (the same
# class of misrouting bug found twice on 2026-09-15). A bare "case ..." is NOT
# a command (people write "case of theft..." in ordinary questions) -- only
# "CASE:" with a colon, or "FIND CASE ...". Phase 1 covers the Supreme Court.
_CASE_USAGE = (
    "To get a judgment as a document, send:\n"
    "*CASE: <case name>*  (for example: CASE: Arnesh Kumar v State of Bihar)\n"
    "You get the original Supreme Court Reports pages as a PDF. Add *WORD* at the end for an editable "
    "Word file, or *TEXT* for a re-typed text PDF.\n"
    "This currently covers Supreme Court judgments only."
)


def _parse_case_command(text: str):
    """(query, fmt) if `text` is a case-lookup command, else None. fmt is
    'pdf' or 'docx'. query may be '' (bare command -> usage help)."""
    m = re.match(r"^\s*(?:find\s+case\b\s*:?|case\s*:)\s*(.*)$", text or "", re.I | re.S)
    if not m:
        return None
    query, fmt = m.group(1).strip(), "pdf"
    fm = re.search(r"\b(word|docx|pdf|text)\s*$", query, re.I)
    if fm:
        kind = fm.group(1).lower()
        fmt = "docx" if kind in ("word", "docx") else ("textpdf" if kind == "text" else "pdf")
        query = query[:fm.start()].strip()
    return query, fmt


def _log(phone_number: str, event: str, **fields) -> None:
    """CASE usage log -- fail-open: nothing in here may ever affect the reply."""
    try:
        case_lookup.log_event(phone_number, event, **fields)
    except Exception:
        logger.exception("case lookup: usage log failed (ignored)")


def _reply(phone_number: str, text: str) -> list:
    send_whatsapp_message(phone_number, text)
    return [text]


def _try_original_pdf(phone_number: str, case_id: str, started: float, editable_available: bool = True):
    """The judgment's ORIGINAL Supreme Court Reports page-image PDF, verified against the case name.
    Returns the list of reply texts on success, or None (after logging why) so the caller falls back
    to the re-typed text PDF -- this must never leave the person with nothing, and never raise."""
    try:
        case = case_lookup.get_case(case_id)
        if not case or not WHATSAPP_PUBLIC_BASE_URL:
            return None
        result = case_original.get_original(case)
        if result["status"] != "ok":
            _log(phone_number, "original_unavailable", case_id=case_id, detail=result["status"])
            return None
        url = f"{WHATSAPP_PUBLIC_BASE_URL}/whatsapp/files/{_store_pending_pdf(result['bytes'])}.pdf"
        if not send_whatsapp_document(phone_number, url, case_document.suggested_filename(case, "pdf")):
            _log(phone_number, "original_unavailable", case_id=case_id, detail="send_failed")
            return None
        _log(phone_number, "doc_delivered", case_id=case_id, detail="pdf_original",
             elapsed_ms=int((time.time() - started) * 1000), cached=False)
        tail = (" For an editable version send the same command with WORD at the end." if editable_available else
                " An editable / re-typed version isn't available for this case yet, so this is the original.")
        return _reply(phone_number, (
            "Here is the original Supreme Court Reports page-image PDF (headnote and margin letters are as "
            "printed). " + case_original.CREDIT + " It is NOT independently verified against the official law "
            "reporter -- confirm the citation before relying on it." + tail))
    except Exception:
        logger.exception("case lookup: original-PDF path failed for %s (falling back to text)", case_id)
        return None


def _send_case_document(phone_number: str, case_id: str, fmt: str) -> list:
    """Fetch one confirmed case, build the file, send it. Every failure is
    a plain sentence to the person -- never a crash, never a guess, never
    a garbled file. Falls back to plain text if the file can't be built or
    delivered, so they are never left with nothing."""
    if not case_lookup.check_and_record(phone_number, "fetch"):
        _log(phone_number, "fetch_rate_limited", case_id=case_id)
        return _reply(phone_number, "You've reached today's limit for judgment downloads -- please try again tomorrow.")
    started = time.time()
    replies = [_reply(phone_number, "Fetching the judgment -- this can take up to a minute...")[0]]
    if fmt == "pdf":
        original = _try_original_pdf(phone_number, case_id, started)
        if original:
            return replies + original
    else:
        # A case added to the catalogue from the bucket's own list has NO re-typed text (that came from
        # Vaquill). WORD / TEXT can't be built for it: say so, and send the original instead.
        try:
            bucket_only = (case_lookup.get_case(case_id) or {}).get("source") == "bucket"
        except Exception:
            bucket_only = False
        if bucket_only:
            _log(phone_number, "text_unavailable", case_id=case_id, detail="word" if fmt == "docx" else "text")
            original = _try_original_pdf(phone_number, case_id, started, editable_available=False)
            if original:
                return replies + original
            return replies + _reply(phone_number, "I couldn't retrieve that record just now, and an editable version "
                                                  "isn't available for it. Please try again in a few minutes.")
    try:
        case = case_lookup.get_case(case_id) or {"case_id": case_id, "title": "Judgment"}
        doc = case_lookup.fetch_case_text(case_id)
    except case_lookup.CaseLookupUnavailable:
        _log(phone_number, "fetch_unavailable", case_id=case_id)
        return replies + _reply(phone_number, "The judgment source isn't reachable right now -- please try again in a few minutes.")
    except case_lookup.CaseNotFound:
        _log(phone_number, "fetch_not_found", case_id=case_id)
        return replies + _reply(phone_number, "I couldn't retrieve that record. Please try another search.")
    except Exception:
        logger.exception("case lookup: unexpected failure fetching %s", case_id)
        _log(phone_number, "fetch_error", case_id=case_id)
        return replies + _reply(phone_number, "Sorry, something went wrong fetching that judgment. Please try again.")

    if len(doc["text"]) < case_lookup.DOC_MIN_CHARS:
        _log(phone_number, "doc_too_short", case_id=case_id)
        return replies + _reply(phone_number, "That record looks broken or almost empty, so I haven't sent it. Please try another search.")

    sent = False
    try:
        if fmt == "docx":
            data, store, ext = case_document.build_docx(case, doc), _store_pending_docx, "docx"
        else:
            data, store, ext = case_document.build_pdf(case, doc), _store_pending_pdf, "pdf"
        if WHATSAPP_PUBLIC_BASE_URL:
            url = f"{WHATSAPP_PUBLIC_BASE_URL}/whatsapp/files/{store(data)}.{ext}"
            sent = send_whatsapp_document(phone_number, url, case_document.suggested_filename(case, ext))
    except Exception:
        logger.exception("case lookup: building/sending the document for %s failed", case_id)

    if sent:
        _log(phone_number, "doc_delivered", case_id=case_id, detail="docx" if fmt == "docx" else "pdf",
             elapsed_ms=int((time.time() - started) * 1000), cached=doc.get("from_cache"))
        caption = ("Here is the judgment. It comes from an open dataset and has NOT been checked against "
                   "the official law reporter -- confirm the citation and wording before relying on it.")
        if doc.get("is_procedural"):
            caption += " Note: this looks like an interim/procedural order, not a final judgment."
        if not doc.get("complete"):
            caption += " Warning: this record may be incomplete."
        return replies + _reply(phone_number, caption)

    _log(phone_number, "doc_text_fallback", case_id=case_id, detail=fmt)
    excerpt = doc["text"][:3000].strip()
    return replies + _reply(
        phone_number,
        "I couldn't prepare the file just now, so here is the start of the text instead "
        "(from an open dataset, not independently verified):\n\n" + excerpt + "\n\n[...truncated]",
    )


# "CASE Gayatri Balasamy v ISG Novasoft" -- someone forgot the colon. Deliberately narrow:
# must start with the word CASE, contain a "v"/"vs"/"versus" between two names, be short,
# and not be a question -- so an ordinary sentence containing "case" is never intercepted.
_CASE_NO_COLON = re.compile(r"^\s*case\s+(?!of\b)(\S.*?\s+(?:v|vs|vs\.|v\.|versus)\s+\S.*)$", re.I)


def _case_hint(text: str):
    m = _CASE_NO_COLON.match(text or "")
    if not m or "?" in text or len(text) > 120 or len(text.split()) > 14:
        return None
    return m.group(1).strip()


def _handle_case_command(phone_number: str, query: str, fmt: str) -> list:
    if not query:
        _log(phone_number, "usage_help")
        return _reply(phone_number, _CASE_USAGE)
    if not case_lookup.check_and_record(phone_number, "search"):
        _log(phone_number, "search_rate_limited", query=query)
        return _reply(phone_number, "You've reached today's limit for case searches -- please try again tomorrow.")
    try:
        found = case_lookup.search_cases_detailed(query)
    except case_lookup.IndexNotBuilt:
        _log(phone_number, "search_unavailable", query=query)
        return _reply(phone_number, "Judgment lookup isn't available yet -- please check back soon.")
    except Exception:
        logger.exception("case lookup: search failed")
        _log(phone_number, "search_error", query=query)
        return _reply(phone_number, "Sorry, the search failed just now. Please try again.")
    results, exact = found["cases"], found["exact"]
    if not results:
        _log(phone_number, "search_no_match", query=query)
        return _reply(
            phone_number,
            "I couldn't find a Supreme Court case matching that name. Try just the main party's name, or check "
            "the spelling. Note that this collection does not contain every judgment (very recent ones in "
            "particular), so not finding a case here doesn't mean it doesn't exist. (This command only finds "
            "judgments by name -- if you meant to ask a question, just send it without \"CASE:\".)",
        )
    # Auto-send ONLY a single exact match. A fuzzy lookalike sent as though it were
    # the case asked for is the worst failure this feature can have -- always a menu.
    if exact and len(results) == 1:
        _log(phone_number, "exact_auto_send", case_id=results[0]["case_id"], query=query, detail=fmt)
        return _send_case_document(phone_number, results[0]["case_id"], fmt)
    case_lookup.save_choices(phone_number, results, fmt)
    _log(phone_number, "menu_exact" if exact else "menu_fuzzy", query=query, detail=f"{len(results)} options")
    return _reply(phone_number, case_lookup.format_choices(results, exact))


def _handle_case_choice(phone_number: str, number: int) -> list:
    pending = case_lookup.get_choices(phone_number)
    case_ids, fmt = pending
    if number > len(case_ids):
        _log(phone_number, "pick_invalid", detail=str(number))
        return _reply(phone_number, f"Please reply with a number from 1 to {len(case_ids)}, or send CASE: <name> to search again.")
    case_lookup.clear_choices(phone_number)
    _log(phone_number, "pick_ok", case_id=case_ids[number - 1], detail=str(number))
    return _send_case_document(phone_number, case_ids[number - 1], fmt)


def handle_incoming_message(phone_number: str, message_text: str) -> list:
    """The whole pipeline for one incoming message, kept in its own
    plain function (no FastAPI/HTTP involved) so it can be called
    directly in tests, and later from whatever the real BSP's webhook
    shape turns out to be."""
    message_text = (message_text or "").strip()

    # Case lookup: an explicit command, or a bare 1-9 answering an
    # unexpired numbered menu. Handled before anything touches chat
    # history or the AI engine -- these are not questions.
    case_cmd = _parse_case_command(message_text)
    if case_cmd is not None:
        return _handle_case_command(phone_number, *case_cmd)
    hinted = _case_hint(message_text)
    if hinted:
        _log(phone_number, "case_hint", query=hinted)
        return _reply(phone_number, f"Did you mean to look up a judgment? Send it like this, with a colon:\n\nCASE: {hinted}")
    if re.fullmatch(r"[1-9]", message_text) and case_lookup.get_choices(phone_number) is not None:
        return _handle_case_choice(phone_number, int(message_text))

    if message_text.lower() in _RESET_WORDS:
        whatsapp_store.clear_history(phone_number)
        reply = "Starting fresh -- tell me what's happening."
        send_whatsapp_message(phone_number, reply)
        return [reply]

    # CONFIRMED REAL GAP, fixed 2026-09-14: format_answer_for_whatsapp has
    # always invited "Reply *DRAFT*" after an arrest-shaped answer, but
    # nothing ever caught that reply -- see the module-level comment above
    # _build_petition_pdf. Checked before the reset-word style early-return
    # above would otherwise treat it as just another free-text question.
    if message_text.lower() in _DRAFT_WORDS:
        ctx = whatsapp_store.get_draft_context(phone_number)
        if ctx is None:
            reply = "I don't have a situation to draft from yet -- describe what's happening first, then reply DRAFT."
            send_whatsapp_message(phone_number, reply)
            return [reply]
        pdf_bytes = _build_petition_pdf(ctx["question"], ctx["matches"])
        sent = False
        if pdf_bytes is not None and WHATSAPP_PUBLIC_BASE_URL:
            token = _store_pending_pdf(pdf_bytes)
            url = f"{WHATSAPP_PUBLIC_BASE_URL}/whatsapp/files/{token}.pdf"
            sent = send_whatsapp_document(phone_number, url, "recourse_draft_petition.pdf")
        if sent:
            reply = ("Here's a draft petition based on what you've told me -- edit it and take it "
                      "to a lawyer before filing. It's a starting point, not a filed document.")
        else:
            reply = "Sorry, I couldn't prepare the draft just now -- please try again in a moment."
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
    result = chat_assistant.answer_question(
        question, inline_domains={"cheque_bounce", "freeze", "domestic_violence"})
    messages = format_answer_for_whatsapp(result)

    # The safe learning loop, part 1: quietly note how confident the
    # engine was on this real question. Never changes this reply or any
    # future one -- purely raw material for a person to review later via
    # whatsapp_weekly_report.py. Logs the person's own original message,
    # not the context-prefixed `question` sent to the engine.
    whatsapp_store.log_qa(phone_number, message_text, result.get("state", "unknown"))

    # Save what a "DRAFT" reply would need, exactly matching when the
    # formatter actually offers that reply (single_match/conflicting_matches
    # + situation_detected) -- see _DRAFT_WORDS handling above.
    if result.get("state") in ("single_match", "conflicting_matches") and result.get("situation_detected"):
        whatsapp_store.save_draft_context(phone_number, message_text, result.get("matches", []))

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


@app.post("/whatsapp/webhook/{secret}")
async def whatsapp_webhook(secret: str, request: Request, background_tasks: BackgroundTasks):
    """The secret path segment is checked FIRST, before touching the
    request body at all -- Gupshup's dashboard is configured with this
    exact URL (secret included) as the callback, so a real delivery
    always carries it; anything else is rejected as a plain 404 (never
    a distinguishing error) so a prober can't tell "wrong secret" from
    "route doesn't exist". Uses hmac.compare_digest for a constant-time
    comparison -- low cost, standard practice for secret comparison.

    Logs the FULL raw payload on every call -- kept even after
    confirming the real Meta-format shape, since a malformed or
    unexpected payload should still be diagnosable from logs, not just
    silently dropped."""
    if not WEBHOOK_SECRET or not hmac.compare_digest(secret, WEBHOOK_SECRET):
        raise HTTPException(status_code=404)

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


@app.get("/whatsapp/files/{token}.pdf")
async def whatsapp_file(token: str):
    """Serves a generated petition PDF for Gupshup to fetch and relay --
    see the WHATSAPP_PUBLIC_BASE_URL/_store_pending_pdf comment above
    _build_petition_pdf for why this exists instead of a real object
    store. `token` is an unguessable secrets.token_urlsafe(24) value, so
    (per this project's own established precedent that unguessable
    tokens don't need extra validation) a bare lookup is the actual
    access control here -- there is no separate per-user auth because
    only the person the PDF was generated for (via their own WhatsApp
    conversation) ever receives this exact URL."""
    entry = _PENDING_PDFS.get(token)
    if entry is None or entry[1] <= time.time():
        raise HTTPException(status_code=404)
    pdf_bytes, _expires_at = entry
    return Response(content=pdf_bytes, media_type="application/pdf")


@app.get("/whatsapp/files/{token}.docx")
async def whatsapp_docx_file(token: str):
    """Word counterpart of whatsapp_file above -- same unguessable-token
    access model, its own store so a token can never be served under the
    wrong content type."""
    entry = _PENDING_DOCX.get(token)
    if entry is None or entry[1] <= time.time():
        raise HTTPException(status_code=404)
    return Response(
        content=entry[0],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
