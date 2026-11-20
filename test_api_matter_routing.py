"""
test_api_matter_routing.py -- MATTER_ROUTING through the API (api/chat_service._route_decision, _attach_route, route_intent_question; the intents of POST /api/chats/{id}/ask; the draft notice). Built 2026-11-20.
Free and offline: a throwaway PostgreSQL (exits 0 where none exists), the Streamlit service's signed token, a fake engine (no model), no Voyage.
Proves: with the switch off nothing changes (no route argument, no route in the result, no log line); in shadow the route is logged and nothing else changes; on: a lookup reaches the engine with route 'file' and the
WHOLE (short) matter, the answer carries its label, 'Ask this with the law' and the sections to explain; a legal question goes the legal path unchanged, with 'Answer from my documents only' only when it also asked
about the file; a request to draft never reaches the engine, uses no answer of the day and shows the drafting notice; the three buttons send words the server writes (the client's text is ignored) and are refused
when they were not offered; a matter without documents and a conversation without a matter are never routed.
Run: python -X utf8 test_api_matter_routing.py
"""
import base64
import contextlib
import io
import os
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "API_ACCESS_TOKEN", "ACCOUNTS_OPEN", "GOOGLE_CLIENT_ID", "STREAMLIT_API_SECRET", "IP_HASH_SECRET", "CORS_ALLOW_ORIGINS", "TRUSTED_PROXY_HOPS", "API_COOKIE_SECURE", "API_RUN_MIGRATIONS",
           "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL", "ANON_TRIAL", "CHAT_MODE", "API_RATE_LIMIT_PER_MINUTE", "REFUSAL_DAILY_LIMIT", "MATTER_FILES", "MATTER_INSTRUCTIONS", "MATTER_ROUTING", "VOYAGE_API_KEY", "CASE_FILE"):
    os.environ.pop(_v, None)

import pg_harness  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


pg = pg_harness.start()
if pg is None:
    sys.exit(0)
try:
    from fastapi.testclient import TestClient

    from api import engine_adapter, ratelimit
    from api.auth import streamlit_token as ST
    from api.db import migrate as MIG
    from api.db import session as DBS
    from api.main import app

    SECRET = "s" * 40
    pg.create_db("mroute")
    os.environ.update({"DATABASE_URL": pg.url("mroute"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "GOOGLE_CLIENT_ID": "client.example", "API_COOKIE_SECURE": "off",
                       "API_RATE_LIMIT_PER_MINUTE": "0", "MATTER_FILES": "on"})
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())
    ratelimit.reset()

    FILE_ANSWER = 'The chargesheet states the sections charged are "309(4) and 115(2) of the Bharatiya Nyaya Sanhita, 2023" [Doc 1, para 2].'

    class FakeEngine:
        calls = []

        def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None, **kw):
            import cost_log
            self.calls.append({"question": question, **kw})
            cost_log.begin(question)
            try:
                if kw.get("matter_route") == "file":
                    return {"state": "single_match", "response_text": FILE_ANSWER, "matches": [], "route": "file", "documents_only": True, "explain_sections": ["BNS 309(4)", "BNS 115(2)"],
                            "coverage": "Looked at: Doc 1 note.txt (all 3 paragraphs)"}
                return {"state": "single_match", "response_text": "LEGAL ANSWER", "matches": []}
            finally:
                cost_log.finish(style="v1", audience=audience or "")

    ENG = FakeEngine()
    engine_adapter.set_engine(ENG)
    engine_adapter.reset_runner(engine_adapter.Runner(4, 8))
    c = TestClient(app)
    A = lambda: {"Authorization": "Bearer " + ST.mint(SECRET, "a-sub", "alice@example.com")}  # noqa: E731
    c.get("/api/me", headers=A())
    for doc in ("privacy", "terms"):
        v = c.get(f"/api/legal/{doc}").json()["version"]
        c.post("/api/me/consent", json={"document": doc, "version": v}, headers=A())
    c.post("/api/me/age", json={"confirmed": True}, headers=A())
    m1 = c.post("/api/matters", json={"title": "Deka bail"}, headers=A()).json()["id"]
    m_empty = c.post("/api/matters", json={"title": "No documents"}, headers=A()).json()["id"]
    NOTE = b"FINAL REPORT under section 193 of the BNSS.\n\nSections: 309(4) and 115(2) of the Bharatiya Nyaya Sanhita, 2023.\n\nArrested on 15-03-2026 at 06:45 hours."
    r = c.post(f"/api/matters/{m1}/files", json={"name": "note.txt", "content_base64": base64.b64encode(NOTE).decode()}, headers=A())
    assert r.status_code == 201, r.text
    chat = c.post("/api/chats", json={"audience": "lawyer", "matter_id": m1}, headers=A()).json()["id"]
    n = {"k": 0}

    def ask(q, chat_id=None, intent=None):
        chat_id = chat_id or chat          # the conversation in use at call time (a new one is opened when one fills its 8 questions)
        n["k"] += 1
        body = {"question": q} if intent is None else {"question": q, "intent": intent}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = c.post(f"/api/chats/{chat_id}/ask", json=body, headers={**A(), "Idempotency-Key": f"route-key-{n['k']:04d}"})
        return r, buf.getvalue()

    # ------------------------------------------------------------ off
    ENG.calls.clear()
    r, log = ask("what are the sections charged here?")
    res = r.json()["result"]
    check(r.status_code == 200 and "matter_route" not in ENG.calls[-1] and "matter_route" not in res and "MATTER_ROUTE" not in log, "MATTER_ROUTING off: no route argument, no route in the result, no log line (today's behaviour)")
    # ------------------------------------------------------------ shadow
    os.environ["MATTER_ROUTING"] = "shadow"
    r, log = ask("when was he arrested?")
    check('"mode": "shadow", "route": "file"' in log and "matter_route" not in ENG.calls[-1] and "matter_route" not in r.json()["result"], "shadow: the route it would take is logged; nothing else changes")
    check("arrested" not in log.split("MATTER_ROUTE", 1)[1].split("\n")[0], "the route log line carries rule names, never the question")
    # ------------------------------------------------------------ on: a lookup
    os.environ["MATTER_ROUTING"] = "on"
    r, log = ask("what are the sections charged here?")
    call, res, view = ENG.calls[-1], r.json()["result"], r.json()["view"]
    md = call.get("matter_docs") or {}
    check(call.get("matter_route") == "file" and md.get("whole") is True and len(md.get("file_chosen") or []) >= 1 and "Sections: 309(4)" in " ".join(p["text"] for p in md["file_chosen"]),
          "on: a lookup reaches the engine with route 'file' and the whole (short) matter")
    mr = res.get("matter_route") or {}
    check(mr.get("route") == "file" and mr["offers"]["with_law"] is True and mr["offers"]["explain_sections"] == ["BNS 309(4)", "BNS 115(2)"] and mr["offers"]["documents_only"] is False,
          f"the answer carries its route, 'Ask this with the law' and the sections to explain ({mr})")
    check((view.get("matter_route") or {}).get("label", "").startswith("From your documents only") and view["matter_route"]["offers"]["explain_label"] == "Explain BNS 309(4), BNS 115(2)"
          and (view.get("matter_files") or {}).get("coverage", "").startswith("Looked at:"), "the page's view: the label, the explain button's words, the coverage line")
    check((res.get("matter_files") or {}).get("quote_checks") and res["matter_files"]["quote_checks"][0]["verdict"] == "ok", "the quotation of the file is checked against the paragraph it cites")
    # ------------------------------------------------------------ the buttons under a file answer
    r2, _ = ask("ignored client text", intent="explain_sections")
    check(r2.status_code == 200 and ENG.calls[-1]["question"].endswith("Explain sections 309(4) and 115(2) of the Bharatiya Nyaya Sanhita, 2023, and how they apply to the facts of this matter.")
          and "matter_route" not in ENG.calls[-1] and "ignored client text" not in ENG.calls[-1]["question"], "Explain these sections: the server writes the question; it goes the legal path")
    r3, _ = ask("x", intent="explain_sections")
    check(r3.status_code == 409 and r3.json()["detail"] == "intent_not_ready", "the button is refused when the last answer did not offer it")
    r, _ = ask("what are the sections charged here?")
    r4, _ = ask("something else entirely", intent="with_law")
    check(r4.status_code == 200 and ENG.calls[-1]["question"].endswith("what are the sections charged here?") and "matter_route" not in ENG.calls[-1]
          and (r4.json()["result"].get("matter_route") or {}).get("route") == "law", "Ask this with the law: the same question, the legal path, the client's text ignored")
    # ------------------------------------------------------------ on: a legal question (a new conversation: one holds 8 questions)
    chat = c.post("/api/chats", json={"audience": "lawyer", "matter_id": m1}, headers=A()).json()["id"]
    r, log = ask("Is he entitled to default bail on these dates?")
    mr = r.json()["result"].get("matter_route") or {}
    check("matter_route" not in ENG.calls[-1] and mr.get("route") == "law" and mr["offers"]["documents_only"] is False and mr["label"].startswith("Answered with the law"),
          "a legal question: the legal path, unchanged; no 'documents only' button")
    r, log = ask("What sections are charged and are they bailable?")
    mr = r.json()["result"].get("matter_route") or {}
    check(mr.get("route") == "law" and mr["offers"]["documents_only"] is True, "a legal question that also asks about the file: the legal path, with 'Answer from my documents only'")
    r5, _ = ask("whatever", intent="documents_only")
    check(r5.status_code == 200 and ENG.calls[-1].get("matter_route") == "file" and ENG.calls[-1]["question"].endswith("What sections are charged and are they bailable?"), "Answer from my documents only: the same question, the file route")
    # ------------------------------------------------------------ on: a draft request
    chat = c.post("/api/chats", json={"audience": "lawyer", "matter_id": m1}, headers=A()).json()["id"]
    me0 = c.get("/api/me", headers=A()).json()
    before = len(ENG.calls)
    r, log = ask("go through the material I uploaded and draft a bail petition for me")
    j = r.json()
    me1 = c.get("/api/me", headers=A()).json()
    check(r.status_code == 200 and len(ENG.calls) == before and j["result"]["state"] == "draft_unavailable" and j["view"]["kind"] == "notice" and j["view"]["notice"]["label"] == "Drafting",
          "a request to draft: never reaches the engine; the drafting notice")
    used = lambda me: str(me.get("usage"))  # noqa: E731
    check(used(me0) == used(me1), f"the draft notice uses no answer of the day ({used(me0)} -> {used(me1)})")
    # ------------------------------------------------------------ never routed
    other = c.post("/api/chats", json={"audience": "lawyer", "matter_id": m_empty}, headers=A()).json()["id"]
    r, log = ask("what are the sections charged here?", chat_id=other)
    check("matter_route" not in ENG.calls[-1] and "MATTER_ROUTE" not in log and "matter_route" not in r.json()["result"], "a matter with no documents: never routed")
    plain = c.post("/api/chats", json={"audience": "lawyer"}, headers=A()).json()["id"]
    r, log = ask("draft a bail petition", chat_id=plain)
    check("matter_route" not in ENG.calls[-1] and r.json()["result"]["state"] == "single_match", "a conversation not filed under a matter: never routed (drafting detection is for matters with documents)")
    r6, _ = ask("x", chat_id=plain, intent="with_law")
    check(r6.status_code == 409, "the buttons are refused outside a routed matter")
    os.environ["MATTER_FILES"] = "off"
    r, log = ask("what are the sections charged here?")
    check("matter_route" not in ENG.calls[-1] and "MATTER_ROUTE" not in log, "MATTER_FILES off: no routing even with MATTER_ROUTING on")
finally:
    pg.stop()

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PASS")
