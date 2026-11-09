"""
test_api_case_file.py -- the case file over the API (api/routers/chats.py, api/chat_service.py, api/db migration 0004; owner's go 2026-11-09). Free and offline: a throw-away Postgres (exit 0 where none exists), a stand-in engine, the Streamlit service's signed token.
Proves: with CASE_FILE off nothing changes (no case_file in a chat, the routes are 404, the engine gets no case_file argument); with it on, the sentences the person types become facts after the answer is saved; the person can edit, add and remove lines
(and nobody else can touch the file); the next question reaches the engine with the facts in the person's words, no answer of ours, and the facts as a separate search text; a tapped answer is a fixed fact; the age card is due for a case that mentions
a sexual offence and goes after the tap; the 'under 18' question is written by the server, needs the tap, and does not add its own words to the file; a refusal of small talk adds nothing.
Run: python -X utf8 test_api_case_file.py
"""
import os
import sys
import threading
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("DATABASE_URL", "API_ACCESS_TOKEN", "ACCOUNTS_OPEN", "GOOGLE_CLIENT_ID", "STREAMLIT_API_SECRET", "IP_HASH_SECRET", "CORS_ALLOW_ORIGINS", "TRUSTED_PROXY_HOPS", "API_COOKIE_SECURE", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL",
           "ANON_TRIAL", "CHAT_MODE", "CASE_FILE", "AGE_CARD"):
    os.environ.pop(_v, None)

import pg_harness

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
    from sqlalchemy import select

    import case_file as CF
    from api import engine_adapter
    from api.auth import streamlit_token as ST
    from api.db import migrate as MIG
    from api.db import models as M
    from api.db import session as DBS
    from api.main import app

    SECRET = "s" * 40
    pg.create_db("casefile")
    os.environ.update({"DATABASE_URL": pg.url("casefile"), "ACCOUNTS_OPEN": "on", "ACCOUNTS_ALLOW_PLACEHOLDER_LEGAL": "on", "STREAMLIT_API_SECRET": SECRET, "GOOGLE_CLIENT_ID": "client.example", "API_COOKIE_SECURE": "off"})
    DBS.reset_engine()
    MIG.upgrade(DBS.get_engine())

    class FakeEngine:
        calls = []
        mode = "ok"

        def answer_question(self, question, inline_domains=frozenset(), audience=None, channel=None, carried_sections=None, case_file=None):
            import cost_log
            cost_log.begin(question)
            try:
                FakeEngine.calls.append({"q": question, "case_file": case_file, "carried": carried_sections})
                if self.mode == "unrelated":
                    return {"state": "unrelated"}
                return {"state": "single_match", "response_text": "Section 77 of the BNS may apply to the clip. In Prabir Purkayastha v State (NCT of Delhi) the Court held that grounds must be written.",
                        "matches": [{"type": "statute", "act": "BNS", "section_number": "77", "text": "section text"},
                                    {"type": "judgment", "case_name": "Prabir Purkayastha v State (NCT of Delhi)", "paragraph_number": "30", "text": "the passage"}]}
            finally:
                cost_log.finish(style="v1", audience=audience or "")

    ENG = FakeEngine()
    engine_adapter.set_engine(ENG)
    engine_adapter.reset_runner(engine_adapter.Runner(4, 8))
    c = TestClient(app)

    def H(sub, email):
        return lambda: {"Authorization": "Bearer " + ST.mint(SECRET, sub, email)}

    A, B = H("a-sub", "alice@example.com"), H("b-sub", "bob@example.com")

    def make_ready(h):
        for doc in ("privacy", "terms"):
            v = c.get(f"/api/legal/{doc}").json()["version"]
            assert c.post("/api/me/consent", json={"document": doc, "version": v}, headers=h()).status_code == 200
        assert c.post("/api/me/age", json={"confirmed": True}, headers=h()).status_code == 200

    [c.get("/api/me", headers=x()) for x in (A, B)]
    make_ready(A)
    make_ready(B)

    def ask(h, chat, q, intent=None):
        body = {"question": q}
        if intent:
            body["intent"] = intent
        return c.post(f"/api/chats/{chat}/ask", json=body, headers=dict(h(), **{"Idempotency-Key": uuid.uuid4().hex[:20]}))

    def new_chat(h, audience="lawyer"):
        return c.post("/api/chats", json={"audience": audience}, headers=h()).json()["id"]

    Q1 = ("My client was arrested on the charges that he was recording a sexual molestation case. The prime accused was arrested on the charges of rape. My client was arrested as the said video was phone on his phone "
          "and was widely shared, and he was apparently present at the crime spot")
    FU = "what are the other sections my client can be charged with? and how can i counter them?"

    # ------------------------------------------------------------ switch off: nothing changes
    chat0 = new_chat(A)
    r = ask(A, chat0, Q1)
    g = c.get(f"/api/chats/{chat0}", headers=A()).json()
    check(r.status_code == 200 and g["case_file"] is None and "case_file" not in r.json() and FakeEngine.calls[-1]["case_file"] is None, "CASE_FILE off: no case file in the chat or the reply, and the engine is not given one")
    check(c.patch(f"/api/chats/{chat0}/case_file", json={"facts": []}, headers=A()).status_code == 404 and c.post(f"/api/chats/{chat0}/case_file/answer", json={"key": "victim_age", "value": "minor"}, headers=A()).status_code == 404,
          "...and its routes are 404")

    # ------------------------------------------------------------ switch on
    os.environ["CASE_FILE"] = "on"
    os.environ["AGE_CARD"] = "on"
    chat = new_chat(A)
    r = ask(A, chat, Q1)
    j = r.json()
    check(r.status_code == 200 and FakeEngine.calls[-1]["q"] == Q1, "the first question reaches the engine as typed (nothing to fold yet)")
    ecf = FakeEngine.calls[-1]["case_file"]
    check(isinstance(ecf, dict) and ecf["search_hint"] is None and ecf["age_gate"] is True and ecf["victim_minor"] is None, f"...with the case file's separate argument ({ecf})")
    cf = j["case_file"]
    check(cf and len(cf["facts"]) == 3 and all(f["kind"] == "typed" and f["editable"] for f in cf["facts"]), "the reply carries the case file: three typed facts the person can edit")
    check(cf["card"] and cf["card"]["key"] == "victim_age", "...and the age card (a sexual offence in a case, no age)")
    check([s["section"] for s in cf["relied_on"]["sections"]] == ["77"] and [x["name"] for x in cf["relied_on"]["cases"]] == ["Prabir Purkayastha v State (NCT of Delhi)"], f"...and what the answer relied on ({cf['relied_on']})")
    g = c.get(f"/api/chats/{chat}", headers=A()).json()
    check(g["case_file"]["facts"] == cf["facts"], "a reload shows the same file")
    with DBS.session() as s:
        stored = s.execute(select(M.Chat.case_file).where(M.Chat.id == uuid.UUID(chat))).scalar_one()
    check(len(stored["facts"]) == 3 and stored["facts"][0]["text"] in Q1, "the file is stored, its facts word for word from the message")

    # ------------------------------------------------------------ the person edits it
    f = g["case_file"]["facts"]
    put = c.patch(f"/api/chats/{chat}/case_file", json={"facts": [{"id": f[0]["id"], "text": "My client was arrested for being present when a clip was recorded."}, {"id": f[2]["id"], "text": f[2]["text"]}, {"id": None, "text": "The FIR was lodged on 2 May 2026."}]}, headers=A())
    pj = put.json()
    check(put.status_code == 200 and [x["kind"] for x in pj["facts"]] == ["edited", "typed", "added"] and pj["facts"][0]["label"] == "You edited this", f"edit, remove and add in one save ({[x['kind'] for x in pj['facts']]})")
    check(c.patch(f"/api/chats/{chat}/case_file", json={"facts": []}, headers=B()).status_code == 404, "another person cannot edit it (404)")
    check(c.patch(f"/api/chats/{chat}/case_file", json={"facts": [{"id": None, "text": "x" * 9000}]}, headers=A()).status_code == 422, "an absurd line is refused (422)")

    # ------------------------------------------------------------ a follow-up reaches the engine with the facts
    r = ask(A, chat, FU)
    call = FakeEngine.calls[-1]
    q = call["q"]
    check(r.status_code == 200 and CF.FACTS_HEADER in q and "My client was arrested for being present when a clip was recorded." in q and "The FIR was lodged on 2 May 2026." in q and q.endswith("Now the person says: " + FU), "the follow-up carries the person's edited facts")
    check("recording a sexual molestation case" not in q and "Section 77" not in q and "Prabir" not in q, "...not the sentence they removed, and none of our answer")
    check(call["case_file"]["search_hint"] and "present when a clip was recorded" in call["case_file"]["search_hint"], f"...and the facts as a separate search text ({(call['case_file'] or {}).get('search_hint', '')[:60]!r})")
    check([x["case_name"] for x in call["case_file"]["cases"]] == ["Prabir Purkayastha v State (NCT of Delhi)"] and call["case_file"]["cases"][0]["retrieval"] == "carried", "the library judgment the first answer named is offered again, as the passage it first saw")
    with DBS.session() as s:
        stored = s.execute(select(M.Chat.case_file).where(M.Chat.id == uuid.UUID(chat))).scalar_one()
    check(len(stored["facts"]) == 3, f"a question of requests adds no fact ({len(stored['facts'])})")

    # ------------------------------------------------------------ the card and the tap
    check(c.post(f"/api/chats/{chat}/case_file/answer", json={"key": "victim_age", "value": "teenager"}, headers=A()).status_code == 422, "an unknown answer is refused (422)")
    check(ask(A, chat, "x", intent="age_minor").status_code == 409, "the 'under 18' question needs the tap first (409 intent_not_ready)")
    tap = c.post(f"/api/chats/{chat}/case_file/answer", json={"key": "victim_age", "value": "minor"}, headers=A())
    tj = tap.json()
    check(tap.status_code == 200 and tj["card"] is None and [x["text"] for x in tj["facts"] if x["kind"] == "button"] == ["The victim is under 18 years old."] and not [x for x in tj["facts"] if x["kind"] == "button" and x["editable"]], "the tap is a fixed fact and the card goes")
    nfacts_before = len(tj["facts"])
    r = ask(A, chat, "anything the client sends here is ignored", intent="age_minor")
    call = FakeEngine.calls[-1]
    check(r.status_code == 200 and call["q"].endswith("Now the person says: The victim was under 18 years old. What changes in this case?"), f"the server writes the question's words ({call['q'][-80:]!r})")
    check(call["case_file"]["delta"] == "pocso" and call["case_file"]["victim_minor"] is True, "the engine is told to answer what changes under POCSO")
    g2 = c.get(f"/api/chats/{chat}", headers=A()).json()
    users = [m["content"] for m in g2["messages"] if m["role"] == "user"]
    check(users[-1] == "The victim was under 18 years old. What changes in this case?" and len(g2["case_file"]["facts"]) == nfacts_before, "the person sees that question in the conversation and it adds no fact of its own")

    # ------------------------------------------------------------ 'adult' and 'don't know' do not ask anything
    chat2 = new_chat(A)
    ask(A, chat2, Q1)
    n = len(FakeEngine.calls)
    a = c.post(f"/api/chats/{chat2}/case_file/answer", json={"key": "victim_age", "value": "adult"}, headers=A()).json()
    with DBS.session() as s_:
        stored2 = s_.execute(select(M.Chat.case_file).where(M.Chat.id == uuid.UUID(chat2))).scalar_one()
    check(a["card"] is None and len(FakeEngine.calls) == n and CF.victim_minor(stored2) is False, "'18 or over' stores the fact, the card goes, and the engine is asked nothing")

    # ------------------------------------------------------------ no card where there is no sexual offence; small talk adds nothing
    chat3 = new_chat(A)
    r = ask(A, chat3, "My brother was arrested for stealing a mobile phone from a shop and is in custody.")
    check(r.json()["case_file"]["card"] is None and len(r.json()["case_file"]["facts"]) == 1, "a theft case: one fact, no age card")
    ENG.mode = "unrelated"
    r = ask(A, chat3, "The weather today is lovely and everybody is out in the park.")
    ENG.mode = "ok"
    g3 = c.get(f"/api/chats/{chat3}", headers=A()).json()
    check(len(g3["case_file"]["facts"]) == 1, "small talk (state 'unrelated') adds no fact")

    # ------------------------------------------------------------ the 'what else could he be charged with' button (CHARGE_MAP)
    import charge_map
    check(c.get(f"/api/chats/{chat}", headers=A()).json()["case_file"]["charges"] is None and ask(A, chat, "x", intent="charges").status_code == 409, "CHARGE_MAP off: no offer, and the intent is refused (409)")
    os.environ["CHARGE_MAP"] = "on"
    chat5 = new_chat(A)
    r = ask(A, chat5, Q1)
    off = r.json()["case_file"]["charges"]
    check(off and off["offer"] is True and "not complete" in off["note"], "CHARGE_MAP on, a lawyer's conversation with facts and an answer: the offer is made")
    chat6 = new_chat(A, "layman")
    r6 = ask(A, chat6, Q1)
    check(r6.json()["case_file"]["charges"] is None and ask(A, chat6, "x", intent="charges").status_code == 409, "a layman's conversation: no offer, the intent is refused (lawyers first)")
    r = ask(A, chat5, "anything", intent="charges")
    call = FakeEngine.calls[-1]
    check(r.status_code == 200 and call["q"].endswith("Now the person says: " + charge_map.CHARGES_QUESTION), "the server writes the question's words")
    check(call["case_file"]["charges"] and "present at the crime spot" in call["case_file"]["charges"]["facts"], "the engine is given the facts for the charge map")
    check(r.json()["case_file"]["charges"] is None, "after it is asked the offer is not made again")
    g5 = c.get(f"/api/chats/{chat5}", headers=A()).json()
    check([m["content"] for m in g5["messages"] if m["role"] == "user"][-1] == charge_map.CHARGES_QUESTION and len(g5["case_file"]["facts"]) == 3, "the person sees that question in the conversation and it adds no fact")
    chat7 = new_chat(A)
    check(ask(A, chat7, "x", intent="charges").status_code == 409, "no facts yet: refused")
    os.environ["CHARGE_MAP"] = "off"

    # ------------------------------------------------------------ AGE_CARD off: no card, no tap
    os.environ["AGE_CARD"] = "off"
    check(c.get(f"/api/chats/{chat}", headers=A()).json()["case_file"]["card"] is None and c.post(f"/api/chats/{chat2}/case_file/answer", json={"key": "victim_age", "value": "minor"}, headers=A()).status_code == 404, "AGE_CARD off: no card and the tap is 404")
finally:
    pg.stop()

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
