"""
test_api_matter_depth.py -- MATTER_DEPTH and LAW_ON_HAND through the API (api/chat_service._route_decision, pins_for, _attach_route, route_intent_question; the intents of POST /api/chats/{id}/ask; the small-talk and
draft notices). MATTER_WORKSPACE_PLAN.md W1 + W2, built 2026-11-20. Free and offline: a throwaway PostgreSQL (exits 0 where none exists), the Streamlit service's signed token, a fake engine (no model), no Voyage.
Proves: with every switch off nothing changes (no size argument, no size in the result); with LAW_ON_HAND alone a question that asks to explain the sections reaches the engine as size 'explain' with the sections the
documents charge (read by code from a labelled line) and the whole (short) matter, and every other question is untouched; with MATTER_DEPTH on: a lookup is 'file'; the typed follow-up 'explain the sections' takes its sections
from the code-checked list the last answer gave (never from model text) and is 'explain'; a legal question is 'standard' and carries the pinned sections; a request for cases is 'research' with no pins; an unclear question is
'standard'; thanks and a draft request never reach the engine and use no answer of the day; the answers carry their size label and 'Go deeper' (a Research answer does not); the Go-deeper tap re-asks the stored question as
'research' and is refused when not offered; without LAW_ON_HAND a question about sections is 'standard'; in shadow the plan is logged and nothing else changes; a matter with no documents is never planned.
Run: python -X utf8 test_api_matter_depth.py
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
           "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL", "ANON_TRIAL", "CHAT_MODE", "API_RATE_LIMIT_PER_MINUTE", "REFUSAL_DAILY_LIMIT", "MATTER_FILES", "MATTER_INSTRUCTIONS", "MATTER_ROUTING", "MATTER_DEPTH", "LAW_ON_HAND",
           "VOYAGE_API_KEY", "CASE_FILE"):
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
    pg.create_db("mdepth")
    os.environ.update({"DATABASE_URL": pg.url("mdepth"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "GOOGLE_CLIENT_ID": "client.example", "API_COOKIE_SECURE": "off",
                       "API_RATE_LIMIT_PER_MINUTE": "0", "MATTER_FILES": "on"})
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())
    ratelimit.reset()

    LOH_VIEW = {"sections": [{"ref": "BNS 309(4)", "on_hand": True, "text": "(4) Whoever commits robbery ...", "cut": False, "source": "our library copy", "status": "library"},
                             {"ref": "BNS 115(2)", "on_hand": True, "text": "(2) Whoever ... voluntarily causes hurt ...", "cut": False, "source": "our library copy", "status": "library"}],
                "table": [{"ref": "BNS 309(4)", "offence": "Robbery.", "punishment": "RI 10 years", "cognizable": "Cognizable.", "bailable": "Non-bailable.", "court": "Magistrate of the first class."}],
                "no_row": ["BNS 115(2)"], "note": "The text above is our own copy of the law, shown word for word."}

    class FakeEngine:
        calls = []

        def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None, **kw):
            import cost_log
            self.calls.append({"question": question, **kw})
            cost_log.begin(question)
            try:
                d = kw.get("matter_depth")
                if kw.get("matter_route") == "file":
                    return {"state": "single_match", "response_text": "FILE ANSWER [Doc 1, para 2]", "matches": [], "route": "file", "depth": "file", "documents_only": True,
                            "explain_sections": ["BNS 309(4)", "BNS 115(2)"], "coverage": "Looked at: Doc 1 note.txt (all 3 paragraphs)"}
                if d == "explain":
                    return {"state": "single_match", "response_text": "EXPLAINED", "matches": [], "route": "explain", "depth": "explain", "law_on_hand": LOH_VIEW}
                if d == "standard":
                    return {"state": "single_match", "response_text": "STANDARD", "matches": [], "depth": "standard"}
                if d == "research":
                    return {"state": "single_match", "response_text": "RESEARCH", "matches": [], "depth": "research"}
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
    state = {"k": 0, "chat": None}

    def new_chat(matter=m1):
        state["chat"] = c.post("/api/chats", json={"audience": "lawyer", "matter_id": matter}, headers=A()).json()["id"]
        return state["chat"]

    def ask(q, intent=None, chat_id=None):
        chat_id = chat_id or state["chat"]
        state["k"] += 1
        body = {"question": q} if intent is None else {"question": q, "intent": intent}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = c.post(f"/api/chats/{chat_id}/ask", json=body, headers={**A(), "Idempotency-Key": f"depth-key-{state['k']:04d}"})
        return r, buf.getvalue()

    used = lambda: str(c.get("/api/me", headers=A()).json().get("usage"))  # noqa: E731
    new_chat()

    # ------------------------------------------------------------ every switch off
    r, log = ask("explain the sections in a clear manner")
    check(r.status_code == 200 and "matter_depth" not in ENG.calls[-1] and "matter_pins" not in ENG.calls[-1] and "matter_route" not in r.json()["result"] and "MATTER_ROUTE" not in log,
          "every switch off: no size argument, no size in the result, no log line (today's behaviour)")

    # ------------------------------------------------------------ LAW_ON_HAND alone
    os.environ["LAW_ON_HAND"] = "on"
    new_chat()
    r, log = ask("explain the sections in a clear manner")
    call, res, view = ENG.calls[-1], r.json()["result"], r.json()["view"]
    md = call.get("matter_docs") or {}
    check(call.get("matter_depth") == "explain" and call.get("matter_pins") == ["BNS 309(4)", "BNS 115(2)"] and md.get("whole") is True and "matter_route" not in call,
          f"LAW_ON_HAND alone: 'explain the sections' reaches the engine as 'explain' with the sections the documents charge (read from the labelled line) and the whole matter ({call.get('matter_pins')})")
    check((res.get("matter_route") or {}).get("size") == "explain" and (view.get("matter_route") or {}).get("label", "").startswith("Quick answer: the sections explained") and (view.get("law_on_hand") or {}).get("sections")
          and view["law_on_hand"]["table"][0]["ref"] == "BNS 309(4)" and view.get("depth") == "explain", "the view carries the label, the law on hand (word for word) and the table")
    check(not ((res.get("matter_route") or {}).get("offers") or {}).get("go_deeper"), "no 'Go deeper' while MATTER_DEPTH is off")
    r, log = ask("Is he entitled to default bail on these dates?")
    check("matter_depth" not in ENG.calls[-1] and "matter_route" not in r.json()["result"], "LAW_ON_HAND alone: a legal question is untouched")
    r, log = ask("what are the sections charged here?")
    check("matter_depth" not in ENG.calls[-1] and "matter_route" not in r.json()["result"], "LAW_ON_HAND alone: a file question is untouched (MATTER_ROUTING is off)")
    os.environ.pop("LAW_ON_HAND")

    # ------------------------------------------------------------ MATTER_DEPTH on, LAW_ON_HAND on
    os.environ.update({"MATTER_DEPTH": "on", "LAW_ON_HAND": "on"})
    new_chat()
    r, log = ask("what are the sections charged here?")
    mr = r.json()["result"].get("matter_route") or {}
    check(ENG.calls[-1].get("matter_route") == "file" and "matter_depth" not in ENG.calls[-1] and mr.get("size") == "file" and mr["offers"]["with_law"] is True and mr["offers"]["go_deeper"] is True
          and mr["offers"]["explain_sections"] == ["BNS 309(4)", "BNS 115(2)"], f"a lookup: size 'file', with its offers ({mr.get('size')})")
    r, log = ask("explain the sections in a clear manner")
    call, mr = ENG.calls[-1], r.json()["result"].get("matter_route") or {}
    check(call.get("matter_depth") == "explain" and call.get("matter_pins") == ["BNS 309(4)", "BNS 115(2)"] and mr.get("size") == "explain" and mr["offers"]["go_deeper"] is True
          and "MATTER_ROUTE" in log and "explain the sections" not in log.split("MATTER_ROUTE", 1)[1].split("\n")[0],
          "the typed follow-up: 'explain', its sections taken from the list the last answer gave by code; the log line carries no question")
    r, log = ask("Is he entitled to default bail on these dates?")
    call, mr = ENG.calls[-1], r.json()["result"].get("matter_route") or {}
    check(call.get("matter_depth") == "standard" and call.get("matter_pins") == ["BNS 309(4)", "BNS 115(2)"] and mr.get("size") == "standard" and mr["label"].startswith("Standard answer") and mr["offers"]["go_deeper"] is True,
          "a legal question: 'standard', with the pinned sections (from the last explain answer's own sections); a Go-deeper offer")
    r, log = ask("what is the position here?")
    check(ENG.calls[-1].get("matter_depth") == "standard", "an unclear question: 'standard' (not the full path)")
    # Go deeper
    r, log = ask("whatever", intent="go_deeper")
    call, mr = ENG.calls[-1], r.json()["result"].get("matter_route") or {}
    check(r.status_code == 200 and call.get("matter_depth") == "research" and "matter_pins" not in call and call["question"].endswith("what is the position here?") and "whatever" not in call["question"]
          and mr.get("size") == "research" and mr["offers"]["go_deeper"] is False and mr["label"].startswith("Research answer"), "Go deeper: the stored question, size 'research', no pins; a Research answer offers no further 'deeper'")
    r, log = ask("x", intent="go_deeper")
    check(r.status_code == 409 and r.json()["detail"] == "intent_not_ready", "the Go-deeper tap is refused when the last answer did not offer it")
    new_chat()
    r, log = ask("Which Supreme Court judgments deal with default bail?")
    check(ENG.calls[-1].get("matter_depth") == "research" and "matter_pins" not in ENG.calls[-1], "a request for cases: 'research', no pins")
    # tapped buttons
    new_chat()
    ask("what are the sections charged here?")
    r2, _ = ask("ignored client text", intent="explain_sections")
    check(r2.status_code == 200 and ENG.calls[-1].get("matter_depth") == "explain" and ENG.calls[-1]["question"].endswith("say what the documents of this matter allege about them.")
          and "ignored client text" not in ENG.calls[-1]["question"], "Explain these sections: the server writes the words; size 'explain'")
    new_chat()
    ask("what are the sections charged here?")
    r3, _ = ask("something else", intent="with_law")
    check(r3.status_code == 200 and ENG.calls[-1].get("matter_depth") == "standard" and ENG.calls[-1]["question"].endswith("what are the sections charged here?"), "Ask this with the law: the same question, size 'standard' (MATTER_DEPTH on)")
    # small talk and drafts use nothing
    new_chat()
    me0, before = used(), len(ENG.calls)
    r, log = ask("thanks")
    j = r.json()
    check(len(ENG.calls) == before and j["result"]["state"] == "smalltalk" and j["view"]["kind"] == "notice" and j["view"]["notice"]["footer"] == "No answer was used up by this message." and used() == me0,
          "thanks: a fixed line, no engine call, no answer of the day used")
    r, log = ask("go through the material I uploaded and draft a bail petition for me")
    check(len(ENG.calls) == before and r.json()["result"]["state"] == "draft_unavailable" and used() == me0, "a request to draft: the notice, no engine call, nothing used")

    # ------------------------------------------------------------ LAW_ON_HAND off: sections go to Standard
    os.environ.pop("LAW_ON_HAND")
    new_chat()
    r, log = ask("explain the sections in a clear manner")
    check(ENG.calls[-1].get("matter_depth") == "standard", "MATTER_DEPTH on, LAW_ON_HAND off: a question about sections takes the Standard size")

    # ------------------------------------------------------------ shadow
    os.environ.pop("MATTER_DEPTH")
    os.environ["MATTER_DEPTH"] = "shadow"
    new_chat()
    r, log = ask("Is he entitled to default bail on these dates?")
    line = log.split("MATTER_ROUTE", 1)[1].split("\n")[0] if "MATTER_ROUTE" in log else ""
    check('"depth_mode": "shadow"' in line and '"plan": "standard"' in line and "matter_depth" not in ENG.calls[-1] and "matter_route" not in r.json()["result"], "shadow: the size it would choose is logged; nothing else changes")

    # ------------------------------------------------------------ never planned
    os.environ.update({"MATTER_DEPTH": "on", "LAW_ON_HAND": "on"})
    other = new_chat(m_empty)
    r, log = ask("explain the sections in a clear manner", chat_id=other)
    check("matter_depth" not in ENG.calls[-1] and "MATTER_ROUTE" not in log and "matter_route" not in r.json()["result"], "a matter with no documents: never planned")
    plain = c.post("/api/chats", json={"audience": "lawyer"}, headers=A()).json()["id"]
    r, log = ask("thanks", chat_id=plain)
    check("matter_depth" not in ENG.calls[-1] and r.json()["result"]["state"] == "single_match", "a conversation not filed under a matter: never planned")
    r6, _ = ask("x", chat_id=plain, intent="go_deeper")
    check(r6.status_code == 409, "the buttons are refused outside a planned matter")
    os.environ["MATTER_FILES"] = "off"
    new_chat()
    r, log = ask("explain the sections in a clear manner")
    check("matter_depth" not in ENG.calls[-1] and "MATTER_ROUTE" not in log, "MATTER_FILES off: no sizes even with MATTER_DEPTH on")
finally:
    pg.stop()

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PASS")
