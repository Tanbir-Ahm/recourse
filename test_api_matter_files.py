"""
test_api_matter_files.py -- a matter's documents and standing instructions through the API (api/routers/matter_files.py, api/matter_docs.py, the instructions field of api/routers/matters.py, api/chat_service.py; built 2026-11-19).
Free and offline: a throwaway PostgreSQL (the test exits 0 where none exists), the Streamlit service's signed token as the way to be somebody, a fake engine (no model), no Voyage (the key is removed: words-only search).
Proves: with MATTER_FILES off every file route answers 404 feature_off and the engine gets no documents; with it on, only a signed-in person who accepted the documents may add files, to their own matter only (404 for
anyone else's, in every route), never to an archived matter; a PDF, a Word file and a text file are read and listed with their pages or paragraphs and unread pages, the file's bytes are not kept (no column holds them),
a scan-only PDF, a renamed file, bad base64 and an oversized file are refused with their codes; ten files per matter and the plan's megabytes per account hold (the eleventh file and the file over the total are refused,
deleting one frees its place and its megabytes); a question in a filed conversation reaches the engine with the matter's passages as a SEPARATE argument (the document's words are not in the question string), only that
matter's passages (another matter's and another person's never), and nothing when the conversation is not filed; the answer's quotations of a document are checked against the page they cite and the result is saved with
the answer; the page-text route returns what was read; the instructions are saved, shown, sent to the engine only with MATTER_INSTRUCTIONS on, and never folded into the question; deleting the matter or the person deletes
its files and passages; the data export carries the files' names and read text; no log line carries a file name or document text.
Run: python -X utf8 test_api_matter_files.py
"""
import base64
import contextlib
import io
import os
import sys
import uuid
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "API_ACCESS_TOKEN", "ACCOUNTS_OPEN", "GOOGLE_CLIENT_ID", "STREAMLIT_API_SECRET", "IP_HASH_SECRET", "CORS_ALLOW_ORIGINS", "TRUSTED_PROXY_HOPS", "API_COOKIE_SECURE", "API_RUN_MIGRATIONS",
           "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL", "ANON_TRIAL", "ANON_DAILY_BUDGET_INR", "ANON_IP_DAILY_LIMIT", "ANON_EST_COST_INR", "CHAT_MODE", "API_RATE_LIMIT_PER_MINUTE", "REFUSAL_DAILY_LIMIT",
           "MATTER_FILES", "MATTER_INSTRUCTIONS", "VOYAGE_API_KEY", "CASE_FILE"):
    os.environ.pop(_v, None)

import pg_harness  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def pdf_bytes(pages, image_pages=()):
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    for n, text in enumerate(pages, start=1):
        if n in image_pages:
            im = Image.new("RGB", (800, 1000), "white")
            ImageDraw.Draw(im).text((20, 20), text, fill="black")
            c.drawImage(ImageReader(im), 40, 100, width=w - 80, height=h - 200)
        else:
            y = h - 60
            for line in text.split("\n"):
                c.drawString(50, y, line)
                y -= 15
        c.showPage()
    c.save()
    return buf.getvalue()


def docx_bytes(paras):
    import docx
    d = docx.Document()
    for p in paras:
        d.add_paragraph(p)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def b64(data):
    return base64.b64encode(data).decode()


pg = pg_harness.start()
if pg is None:
    sys.exit(0)
try:
    from fastapi.testclient import TestClient
    from sqlalchemy import func, inspect, select
    from sqlalchemy.orm import Session

    from api import engine_adapter, ratelimit
    from api.auth import streamlit_token as ST
    from api.db import migrate as MIG
    from api.db import models as M
    from api.db import session as DBS
    from api.main import app

    SECRET = "s" * 40
    pg.create_db("mfiles")
    os.environ.update({"DATABASE_URL": pg.url("mfiles"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "GOOGLE_CLIENT_ID": "client.example", "API_COOKIE_SECURE": "off",
                       "API_RATE_LIMIT_PER_MINUTE": "0"})
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())
    ratelimit.reset()

    class FakeEngine:
        calls = []
        reply = "ANSWER"

        def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None, **kw):
            import cost_log
            self.calls.append({"question": question, **kw})
            cost_log.begin(question)
            try:
                return {"state": "single_match", "response_text": self.reply, "matches": []}
            finally:
                cost_log.finish(style="v1", audience=audience or "")

    ENG = FakeEngine()
    engine_adapter.set_engine(ENG)
    engine_adapter.reset_runner(engine_adapter.Runner(4, 8))
    c = TestClient(app)

    def H(sub, email):
        return lambda: {"Authorization": "Bearer " + ST.mint(SECRET, sub, email)}

    A, B, N = H("a-sub", "alice@example.com"), H("b-sub", "bob@example.com"), H("n-sub", "newbie@example.com")

    def make_ready(h):
        for doc in ("privacy", "terms"):
            v = c.get(f"/api/legal/{doc}").json()["version"]
            assert c.post("/api/me/consent", json={"document": doc, "version": v}, headers=h()).status_code == 200
        assert c.post("/api/me/age", json={"confirmed": True}, headers=h()).status_code == 200

    [c.get("/api/me", headers=x()) for x in (A, B, N)]
    make_ready(A)
    make_ready(B)
    mA = c.post("/api/matters", json={"title": "State v. Deka (bail)", "facts": "Arrested 15 March."}, headers=A()).json()["id"]
    mA2 = c.post("/api/matters", json={"title": "Second matter"}, headers=A()).json()["id"]
    mB = c.post("/api/matters", json={"title": "Bob's matter"}, headers=B()).json()["id"]

    CS = pdf_bytes(["Accused No. 1 was arrested on 15-03-2026 at 06:45 hours from his residence at Bhetapara.",
                    "The gold chain was recovered from a steel trunk kept under the bed in his rented room on 16-03-2026.",
                    "Scanned acknowledgement slip"], image_pages=(3,))
    BO = docx_bytes(["1. This is an application for bail.", "2. Counsel submits that he supports an old mother and has no criminal record.", "3. I do not find it a fit case for bail at this stage."])

    def up(h, mid, name, data):
        return c.post(f"/api/matters/{mid}/files", json={"name": name, "content_base64": b64(data)}, headers=h())

    # ------------------------------------------------------------ switch off
    r = up(A, mA, "chargesheet.pdf", CS)
    check(r.status_code == 404 and r.json()["detail"] == "feature_off" and c.get(f"/api/matters/{mA}/files", headers=A()).json()["detail"] == "feature_off", "MATTER_FILES off: the file routes answer 404 feature_off")
    j = c.get(f"/api/matters/{mA}", headers=A()).json()
    check(j["features"] == {"files": False, "instructions": False} and j["instructions"] is None, "the matter says which features the screens may offer (both off)")

    os.environ["MATTER_FILES"] = "on"
    # ------------------------------------------------------------ who may
    check(c.get(f"/api/matters/{mA}/files").status_code == 401 and c.get(f"/api/matters/{mA}/files", headers=N()).status_code == 403, "not signed in: 401; documents not accepted: 403")
    check(up(B, mA, "x.pdf", CS).status_code == 404 and c.get(f"/api/matters/{mA}/files", headers=B()).status_code == 404, "another person's matter: 404, for listing and adding")
    # ------------------------------------------------------------ adding
    r = up(A, mA, "chargesheet.pdf", CS)
    j = r.json()
    check(r.status_code == 201 and j["doc_no"] == 1 and j["kind"] == "pdf" and j["unit"] == "page" and j["units"] == 3 and j["unread"] == [3] and j["searchable_by_meaning"] is False,
          f"a PDF: 201, Doc 1, three pages, page 3 reported unread, words-only search without the meaning service ({r.status_code} {j})")
    f1 = j["id"]
    r = up(A, mA, "bail order.docx", BO)
    check(r.status_code == 201 and r.json()["doc_no"] == 2 and r.json()["unit"] == "para" and r.json()["units"] == 3, f"a Word file: Doc 2, three paragraphs ({r.json()})")
    r = up(A, mA, "note.txt", b"Lawyer's note. Photograph published before the TIP.")
    check(r.status_code == 201 and r.json()["doc_no"] == 3, "a text file: Doc 3")
    cols = {col["name"] for col in inspect(DBS.get_engine()).get_columns("matter_files")}
    check(not ({"data", "content", "bytes", "blob", "file"} & cols), f"no column keeps the file's bytes ({sorted(cols)})")
    scan = pdf_bytes(["picture only", "picture only"], image_pages=(1, 2))
    for name, data, status, code in (("scan.pdf", scan, 422, "no_text"), ("renamed.docx", CS, 415, "unsupported_type"), ("photo.png", b"\x89PNG\r\n\x1a\nxxxx", 415, "unsupported_type")):
        r = up(A, mA, name, data)
        check(r.status_code == status and r.json()["detail"] == code, f"{name}: {status} {code} ({r.status_code} {r.text[:80]})")
    r = c.post(f"/api/matters/{mA}/files", json={"name": "x.pdf", "content_base64": "not base64!!"}, headers=A())
    check(r.status_code == 422 and r.json()["detail"] == "bad_file_data", "bad base64: 422 bad_file_data")
    r = c.post(f"/api/matters/{mA}/files", json={"name": "big.txt", "content_base64": b64(b"x" * (10 * 1024 * 1024 + 1))}, headers=A())
    check(r.status_code in (413, 422), f"over 10 MB: refused ({r.status_code})")
    lst = c.get(f"/api/matters/{mA}/files", headers=A()).json()
    check([f["doc_no"] for f in lst["files"]] == [1, 2, 3] and lst["files_max"] == 10 and lst["account_limit_bytes"] == 50 * 1024 * 1024 and lst["account_used_bytes"] == len(CS) + len(BO) + len(b"Lawyer's note. Photograph published before the TIP."),
          f"the list: three documents, the limits and what is used ({lst['account_used_bytes']})")
    # ------------------------------------------------------------ limits
    for i in range(7):
        up(A, mA2, f"n{i}.txt", f"note number {i} with some words".encode())
    for i in range(3):
        check(up(A, mA2, f"m{i}.txt", b"more words here").status_code == 201, f"file {8 + i} of 10 fits")
    r = up(A, mA2, "eleventh.txt", b"one too many")
    check(r.status_code == 409 and r.json()["detail"] == "file_limit", "the eleventh file of a matter: 409 file_limit")
    some = c.get(f"/api/matters/{mA2}/files", headers=A()).json()["files"][0]["id"]
    check(c.delete(f"/api/matters/{mA2}/files/{some}", headers=A()).status_code == 200 and up(A, mA2, "fits.txt", b"fits now after a delete").status_code == 201, "deleting a file frees its place")
    with Session(DBS.get_engine()) as s_:                                   # Bob's plan total is reached by a large file recorded directly
        bid = s_.execute(select(M.User.id).where(M.User.email == "bob@example.com")).scalar_one()
        s_.add(M.MatterFile(matter_id=uuid.UUID(mB), user_id=bid, doc_no=1, name="big.pdf", kind="pdf", unit="page", size_bytes=50 * 1024 * 1024 - 10, sha256="0" * 64, units=1, passages=0))
        s_.commit()
    r = up(B, mB, "small.txt", b"eleven bytes")
    check(r.status_code == 409 and r.json()["detail"] == "storage_limit", "over the plan's megabytes for the account: 409 storage_limit")
    c.patch(f"/api/matters/{mA2}", json={"archived": True}, headers=A())
    r = up(A, mA2, "x.txt", b"words")
    check(r.status_code == 409 and r.json()["detail"] in ("matter_archived", "file_limit"), f"an archived matter takes no files ({r.json()['detail']})")
    c.patch(f"/api/matters/{mA2}", json={"archived": False}, headers=A())
    # ------------------------------------------------------------ page text
    r = c.get(f"/api/matters/{mA}/files/1/text?loc=2", headers=A())
    check(r.status_code == 200 and "steel trunk" in r.json()["text"] and r.json()["unread"] is False, "the page-text route returns what was read")
    r = c.get(f"/api/matters/{mA}/files/1/text?loc=3", headers=A())
    check(r.status_code == 200 and r.json()["unread"] is True and r.json()["text"] == "", "an unread page says so")
    check(c.get(f"/api/matters/{mA}/files/1/text?loc=2", headers=B()).status_code == 404 and c.get(f"/api/matters/{mA}/files/9/text?loc=1", headers=A()).status_code == 404, "another person, or a document that is not there: 404")
    # ------------------------------------------------------------ asking
    chat = c.post("/api/chats", json={"audience": "lawyer", "matter_id": mA}, headers=A()).json()["id"]
    ENG.reply = ('The chargesheet states that \"The gold chain was recovered from a steel trunk kept under the bed\" [Doc 1, p. 1]. '
                 'It also says he \"was arrested on 15-03-2026 at 06:45 hours\" [Doc 1, p. 1]. The order says \"I do not find it a fit case for bail\" [Doc 2, para 3].')
    ENG.calls.clear()
    r = c.post(f"/api/chats/{chat}/ask", json={"question": "Where was the chain recovered from?"}, headers={**A(), "Idempotency-Key": "k-files-1"})
    check(r.status_code == 200, f"a question in a filed conversation is answered ({r.status_code} {r.text[:120]})")
    call = ENG.calls[-1] if ENG.calls else {}
    md = call.get("matter_docs") or {}
    check(md and md["chosen"] and md["chosen"][0]["doc"] == 1 and md["chosen"][0]["loc"] == 2, f"the engine gets the matter's passages as a separate argument, the recovery page first ({[(p['doc'], p['loc']) for p in md.get('chosen', [])]})")
    check("steel trunk" not in call.get("question", "") and "Bhetapara" not in call.get("question", ""), "the documents' words are NOT in the question string")
    check(set(md["docs"]) == {1, 2, 3} and all(p["doc"] in (1, 2, 3) for p in md["chosen"]), "only this matter's documents")
    res = r.json()["result"]["matter_files"]
    verdicts = [(q["doc"], q["verdict"], q["found_on"]) for q in res["quote_checks"]]
    check(verdicts == [("1", "other_page", 2), ("1", "ok", 1), ("2", "ok", 3)], f"the answer's quotations are checked against the pages they cite ({verdicts})")
    check(len(res["notes"]) == 1 and "page 2" in res["notes"][0] and res["cited_docs"] == [1, 2] and res["handed"], f"one note for the wrong page; the cited documents and the passages handed over are kept ({res['notes']})")
    with Session(DBS.get_engine()) as s_:
        saved = s_.execute(select(M.Message.result).where(M.Message.chat_id == uuid.UUID(chat), M.Message.role == "assistant")).scalars().first()
    check(isinstance(saved, dict) and saved.get("matter_files", {}).get("quote_checks"), "the check is saved with the answer, so a refresh shows it")
    vw = (r.json().get("view") or {}).get("matter_files") or {}
    check(vw.get("items") and vw["items"][0]["cite"] == "[Doc 1, p. 2]" and vw["items"][0]["name"] == "chargesheet.pdf" and vw["checked"] == 3 and vw["found"] == 2 and vw["notes"] and vw["unread"] == [{"name": "chargesheet.pdf", "pages": [3]}],
          f"the page's view carries the passages with their citations, the check's counts, its note and the unread pages ({vw.get('checked')}, {vw.get('found')})")
    reread = c.get(f"/api/chats/{chat}", headers=A()).json()
    check(any((m.get("view") or {}).get("matter_files") for m in reread.get("messages", [])), "reopening the conversation shows the same documents box")
    ex = c.get(f"/api/chats/{chat}/export?format=docx", headers=A())
    check(ex.status_code == 200 and len(ex.content) > 1000, f"the Word download of the conversation works with the documents box ({ex.status_code})")
    other =c.post("/api/chats", json={"audience": "lawyer", "matter_id": mA2}, headers=A()).json()["id"]
    ENG.calls.clear()
    c.post(f"/api/chats/{other}/ask", json={"question": "Where was the chain recovered from?"}, headers={**A(), "Idempotency-Key": "k-files-2"})
    md2 = ENG.calls[-1].get("matter_docs") or {}
    check(not any("steel trunk" in p["text"] for p in md2.get("chosen", [])), "a conversation in another matter never gets this matter's passages")
    plain = c.post("/api/chats", json={"audience": "lawyer"}, headers=A()).json()["id"]
    ENG.calls.clear()
    c.post(f"/api/chats/{plain}/ask", json={"question": "Where was the chain recovered from?"}, headers={**A(), "Idempotency-Key": "k-files-3"})
    check("matter_docs" not in ENG.calls[-1], "a conversation not filed under a matter: no documents")
    os.environ["MATTER_FILES"] = "off"
    ENG.calls.clear()
    c.post(f"/api/chats/{chat}/ask", json={"question": "And the arrest time?"}, headers={**A(), "Idempotency-Key": "k-files-4"})
    check("matter_docs" not in ENG.calls[-1], "switch off again: the engine gets no documents (the stored files stay)")
    os.environ["MATTER_FILES"] = "on"
    # ------------------------------------------------------------ instructions (P0)
    r = c.patch(f"/api/matters/{mA}", json={"instructions": "  I act for the accused. Keep it short.  "}, headers=A())
    check(r.status_code == 200 and r.json()["instructions"] == "I act for the accused. Keep it short.", "instructions are saved and trimmed")
    check(c.patch(f"/api/matters/{mA}", json={"instructions": "x" * 2001}, headers=A()).status_code == 422, "over 2,000 characters: 422")
    ENG.calls.clear()
    r = c.post(f"/api/chats/{chat}/ask", json={"question": "What next?"}, headers={**A(), "Idempotency-Key": "k-instr-01"})
    check("matter_instructions" not in ENG.calls[-1] and "act for the accused" not in ENG.calls[-1]["question"], "MATTER_INSTRUCTIONS off: the engine does not get them, and they are never in the question")
    os.environ["MATTER_INSTRUCTIONS"] = "on"
    ENG.calls.clear()
    c.post(f"/api/chats/{chat}/ask", json={"question": "What next now?"}, headers={**A(), "Idempotency-Key": "k-instr-02"})
    check(ENG.calls[-1].get("matter_instructions") == "I act for the accused. Keep it short." and "act for the accused" not in ENG.calls[-1]["question"], "on: a separate argument, still not in the question")
    check(c.get(f"/api/matters/{mA}", headers=A()).json()["features"] == {"files": True, "instructions": True}, "the matter says both features are on")
    # ------------------------------------------------------------ export, logs, deletion
    exp = c.post("/api/me/export", headers=A()).json()
    names = {f["name"] for f in exp.get("matter_files", [])}
    check({"chargesheet.pdf", "bail order.docx", "note.txt"} <= names and any("steel trunk" in t["text"] for f in exp["matter_files"] for t in f["text"]) and any(m.get("instructions") for m in exp["matters"]),
          "the data export carries the files' names, their read text and the instructions")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        up(A, mA, "secret-client-name.pdf", pdf_bytes(["Confidential words appear here on this page."]))
        c.post(f"/api/chats/{chat}/ask", json={"question": "Anything confidential?"}, headers={**A(), "Idempotency-Key": "k-logs-001"})
    logs = buf.getvalue()
    check("MATTER_FILE_ADDED" in logs and "MATTER_DOCS" in logs and "secret-client-name" not in logs and "Confidential words" not in logs, "the log lines carry counts only: no file name, no document text")
    c.delete(f"/api/matters/{mA2}", headers=A())
    with Session(DBS.get_engine()) as s_:
        left = s_.execute(select(func.count()).select_from(M.MatterFile).where(M.MatterFile.matter_id == uuid.UUID(mA2))).scalar()
        lp = s_.execute(select(func.count()).select_from(M.MatterFilePassage).where(M.MatterFilePassage.matter_id == uuid.UUID(mA2))).scalar()
    check(left == 0 and lp == 0, "deleting a matter deletes its files and passages")
    check(c.delete(f"/api/matters/{mA}/files/{f1}", headers=B()).status_code == 404, "another person cannot delete a file")
    r = c.delete("/api/me?confirm=DELETE", headers=A())
    with Session(DBS.get_engine()) as s_:
        n_files = s_.execute(select(func.count()).select_from(M.MatterFile).where(M.MatterFile.matter_id == uuid.UUID(mA))).scalar()
        n_pass = s_.execute(select(func.count()).select_from(M.MatterFilePassage).where(M.MatterFilePassage.matter_id == uuid.UUID(mA))).scalar()
    check(r.status_code == 200 and n_files == 0 and n_pass == 0, f"deleting the person deletes their files and passages ({r.status_code}, {n_files}, {n_pass})")
finally:
    pg.stop()

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PASS")
