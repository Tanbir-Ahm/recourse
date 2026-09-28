"""
test_whatsapp_answer_pdf.py -- the WhatsApp side of "download this answer as a PDF": saving a record of every answer,
the PDF / PDF ALL commands, the nudge after each answer, 24-hour retention and wipe-on-reset. Written BEFORE the code.

Fully offline and free: the engine (chat_assistant.answer_question) and the Gupshup send are mocked; temp database.
Run: python -X utf8 test_whatsapp_answer_pdf.py
"""
import os
import sys
import tempfile
import time
from unittest.mock import patch

import fitz

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


import whatsapp_store
import whatsapp_bot
import whatsapp_formatter as wf
import answer_pdf as ap

whatsapp_store.DB_PATH = tempfile.mktemp(suffix=".db")
PHONE, OTHER = "+911111111111", "+922222222222"
sent = []
whatsapp_bot.send_whatsapp_message = lambda phone, text: sent.append((phone, text))
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://example.test"


def pdf_of(token_url):
    tok = token_url.rsplit("/", 1)[1].rsplit(".", 1)[0]
    data = whatsapp_bot._PENDING_PDFS[tok][0]
    doc = fitz.open(stream=data, filetype="pdf")
    return "\n".join(p.get_text() for p in doc)


def answer(text, state="single_match", unclear=False, **extra):
    r = {"state": state, "response_text": text, "situation_detected": False, "matches": [],
         "cited_judgment_links": [], "unverified_related_judgments": []}
    r.update(extra)
    return r


Q1, A1 = "When can a court issue a non-bailable warrant?", "**The rule**\nCourts try a summons first.\n\n**What's unclear here:** whether summons were tried, and the nature of the offence."
Q2, A2 = "What about bail before arrest?", "Section 482 of the BNSS covers anticipatory bail.\n\nIf you have the FIR, you can upload it here for a closer look."

# ================================================================== 1. the store: records, 24h retention, wipe, isolation
rec1 = ap.record_from_result(Q1, answer(A1), created_at=time.time() - 60)
rec2 = ap.record_from_result(Q2, answer(A2), created_at=time.time() - 30)
check(whatsapp_store.get_answer_records(PHONE) == [], "a fresh number has no saved answers")
whatsapp_store.save_answer_record(PHONE, rec1)
whatsapp_store.save_answer_record(PHONE, rec2)
got = whatsapp_store.get_answer_records(PHONE)
check([g["question"] for g in got] == [Q1, Q2] and got[0]["answer_id"] == rec1["answer_id"], "records come back oldest first, intact")
check(whatsapp_store.get_answer_records(OTHER) == [], "another phone number sees none of them")
whatsapp_store.save_answer_record(PHONE, ap.record_from_result("stale", answer("Old."), created_at=time.time() - 30 * 3600))
check("stale" not in [g["question"] for g in whatsapp_store.get_answer_records(PHONE)], "anything older than 24 hours is not returned")
check(len(whatsapp_store.get_answer_records(PHONE, max_age_seconds=10 ** 9)) == 2, "and old records are actually deleted from the database on the next save, not just hidden")
for i in range(25):
    whatsapp_store.save_answer_record(PHONE, ap.record_from_result(f"bulk {i}", answer("x " * 5), created_at=time.time()))
check(len(whatsapp_store.get_answer_records(PHONE)) <= 20, "at most 20 records are kept per person")
whatsapp_store.add_message(PHONE, "user", "hello")
whatsapp_store.clear_history(PHONE)
check(whatsapp_store.get_answer_records(PHONE) == [] and whatsapp_store.get_recent_history(PHONE) == [], "a reset wipes the saved answers as well as the history")
whatsapp_store.save_answer_record(OTHER, rec1)
whatsapp_store.clear_history(PHONE)
check(len(whatsapp_store.get_answer_records(OTHER)) == 1, "and wipes only that person's")
whatsapp_store.clear_history(OTHER)

# ================================================================== 2. the nudge (formatter)
plain = wf.format_answer_for_whatsapp(answer("Para one.\n\nPara two."))
check(not any("PDF" in m for m in plain), "without pdf_offer_count nothing changes (old behaviour, old tests)")
one = wf.format_answer_for_whatsapp(answer("Para one.", pdf_offer_count=1))
check("Reply *PDF*" in one[-1] and "PDF ALL" not in one[-1], "the first answer offers *PDF* only")
two = wf.format_answer_for_whatsapp(answer("Para one.", pdf_offer_count=3))
check("Reply *PDF*" in two[-1] and "*PDF ALL*" in two[-1] and "3" in two[-1], "from the second answer on it also offers *PDF ALL* and says how many")
both = wf.format_answer_for_whatsapp(answer("Para one.", situation_detected=True, pdf_offer_count=2))
check(len([m for m in both if "Reply *DRAFT*" in m]) == 1 and "Reply *PDF*" in both[-1] and "Reply *DRAFT*" in both[-1],
      "when a petition is also on offer there is ONE closing message carrying both offers, and it is last")
withlinks = wf.format_answer_for_whatsapp(answer("Para one.", pdf_offer_count=1,
                                                cited_judgment_links=[{"case_name": "X v Y", "url": "https://u", "source_label": "L"}],
                                                unverified_related_judgments=[{"case_name": "Z", "ik_search_url": "https://z"}]))
check("Reply *PDF*" in withlinks[-1] and any("relies on" in m for m in withlinks[:-1]) and any("Other real court cases" in m for m in withlinks[:-1]),
      "the offer comes AFTER the links and the other-cases list")
for st in ("no_match", "unrelated", "adjacent_uncovered"):
    check(not any("PDF" in m for m in wf.format_answer_for_whatsapp({"state": st, "pdf_offer_count": 2, "reasoning": "r"})),
          f"state {st!r} never offers a PDF")

# ================================================================== 3. the bot end to end (engine mocked)
whatsapp_store.clear_history(PHONE)
canned = [answer(A1, matches=[{"type": "statute", "act": "BNSS", "section_number": "482", "text": "482. Direction for grant of bail."}]),
          answer(A2, matches=[{"type": "statute", "act": "BNSS", "section_number": "482", "text": "482. Direction for grant of bail."}])]
engine_calls = []


def fake_engine(question, inline_domains=frozenset()):
    engine_calls.append(question)
    return canned[min(len(engine_calls), len(canned)) - 1]


with patch("chat_assistant.answer_question", side_effect=fake_engine):
    m1 = whatsapp_bot.handle_incoming_message(PHONE, Q1)
    check("Reply *PDF*" in m1[-1] and "PDF ALL" not in m1[-1], "after the first answer the last message offers *PDF*")
    m2 = whatsapp_bot.handle_incoming_message(PHONE, Q2)
    check("*PDF ALL*" in m2[-1] and "2" in m2[-1], "after the second it also offers *PDF ALL* (2 questions)")
    recs = whatsapp_store.get_answer_records(PHONE)
    check([r["question"] for r in recs] == [Q1, Q2], "the person's OWN words are saved (not the history-folded question sent to the engine)")
    check(all("Earlier in this same conversation" not in r["question"] for r in recs), "no folded context inside the saved question")
    calls_before = len(engine_calls)

    with patch("whatsapp_bot.send_whatsapp_document", return_value=True) as doc:
        r = whatsapp_bot.handle_incoming_message(PHONE, "pdf")
        check(doc.call_count == 1 and doc.call_args.args[0] == PHONE and doc.call_args.args[2] == "recourse_answer.pdf",
              "PDF sends one document named recourse_answer.pdf to the right number")
        url = doc.call_args.args[1]
        check(url.startswith("https://example.test/whatsapp/files/") and url.endswith(".pdf"), "via this service's own short-lived file link")
        t = pdf_of(url)
        check(Q2 in t and Q1 not in t, "PDF = only the LATEST answer")
        check("answer id" in r[0].lower() and recs[1]["answer_id"] in r[0] and "not legal advice" in r[0].lower(), "the reply gives the answer ID and says it is not legal advice")
        check(len(engine_calls) == calls_before, "making the PDF does NOT call the engine again (zero AI cost)")

        r = whatsapp_bot.handle_incoming_message(PHONE, "PDF ALL")
        t = pdf_of(doc.call_args.args[1])
        check(Q1 in t and Q2 in t and t.index(Q1) < t.index(Q2), "PDF ALL = the whole conversation, oldest first")
        check(len(engine_calls) == calls_before, "still no engine call")

        doc.reset_mock()
        for variant in ("pdf all", "Pdf-All", "  PDF  ", "pdf_all"):
            whatsapp_bot.handle_incoming_message(PHONE, variant)
        check(doc.call_count == 4, "spelling, case and spacing variants all work")
        doc.reset_mock()
        whatsapp_bot.handle_incoming_message(PHONE, "can you make a pdf of my case please?")
        check(doc.call_count == 0 or len(engine_calls) > calls_before, "a long sentence that merely contains 'pdf' is treated as a normal question, not the command")

    history_now = [h["text"] for h in whatsapp_store.get_recent_history(PHONE)]
    check("pdf" not in [h.lower() for h in history_now] and "pdf all" not in [h.lower() for h in history_now],
          "the one-word PDF commands are not stored as conversation turns")

    with patch("whatsapp_bot.send_whatsapp_document", return_value=False):
        r = whatsapp_bot.handle_incoming_message(PHONE, "pdf")
        check("couldn't" in r[0].lower(), "a failed send is reported honestly")
    saved_url = whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL
    whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = None
    r = whatsapp_bot.handle_incoming_message(PHONE, "pdf")
    whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = saved_url
    check("couldn't" in r[0].lower(), "with no public base URL configured it fails honestly instead of pretending")

    r = whatsapp_bot.handle_incoming_message(OTHER, "pdf")
    check("ask me a question first" in r[0].lower() or "don't have an answer" in r[0].lower(), "a person with no answers yet is told so")

    whatsapp_bot.handle_incoming_message(PHONE, "new question")
    with patch("whatsapp_bot.send_whatsapp_document", return_value=True) as doc:
        r = whatsapp_bot.handle_incoming_message(PHONE, "pdf")
        check(doc.call_count == 0 and "don't have an answer" in r[0].lower(), "after 'new question' there is nothing to export (the records were wiped)")

# non-answer states: no record, no offer
whatsapp_store.clear_history(PHONE)
with patch("chat_assistant.answer_question", return_value={"state": "no_match"}):
    m = whatsapp_bot.handle_incoming_message(PHONE, "some unanswerable thing")
check(not any("PDF" in x for x in m) and whatsapp_store.get_answer_records(PHONE) == [], "a 'no answer' reply saves nothing and offers no PDF")

# a crash while saving/building must never lose the real answer
whatsapp_store.clear_history(PHONE)
with patch("chat_assistant.answer_question", return_value=answer("Real answer text here.")), \
     patch("whatsapp_store.save_answer_record", side_effect=RuntimeError("disk full")):
    m = whatsapp_bot.handle_incoming_message(PHONE, "a question")
check(m and "Real answer text here." in m[0], "if saving the record fails, the real answer is still sent (fail-open)")

# the engine's cited links / other cases reach the saved record and the PDF
whatsapp_store.clear_history(PHONE)
rich = answer("Inder Mohan Goswami v State of Uttaranchal matters.", state="conflicting_matches",
              matches=[{"type": "judgment", "case_name": "Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors.", "paragraph_number": "fallback_26", "text": "Non-bailable warrant should be issued to bring a person"}],
              cited_judgment_links=[{"case_name": "Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors.", "url": "https://api.sci.gov.in/jonew/judis/29628.pdf", "source_label": "Supreme Court of India (official)"}],
              unverified_related_judgments=[{"case_name": "Alpic Finance Ltd. v P. Sadasivan and Anr.", "ik_search_url": "https://api.sci.gov.in/jonew/judis/17594.pdf", "paragraph_number": None}])
with patch("chat_assistant.answer_question", return_value=rich), patch("whatsapp_bot.send_whatsapp_document", return_value=True) as doc:
    whatsapp_bot.handle_incoming_message(PHONE, "warrants?")
    whatsapp_bot.handle_incoming_message(PHONE, "pdf")
    t = pdf_of(doc.call_args.args[1]).replace("\n", "")
check("https://api.sci.gov.in/jonew/judis/29628.pdf" in t and "https://api.sci.gov.in/jonew/judis/17594.pdf" in t and "More than one legal provision" in t,
      "links, the other-cases list and the conflict opener all made it from the engine's result into the PDF")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
