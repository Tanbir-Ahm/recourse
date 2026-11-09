"""
test_harbour_alias.py -- the harbouring entries of statute_aliases.py (BNS 249, 253, 254), added 2026-11-09 (FOLLOW_UPS 2dw in the research repository). Offline and free: hand-written sentences that are NOT the
pre-registered measurement sets (those live in review_results/2026-11-09_harbouring_alias/ in the research repository); the model and the Voyage call are stubbed out in the pipeline check.
Run: python -X utf8 test_harbour_alias.py
"""
import contextlib
import io
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ.pop("STATUTE_ALIASES", None)
import statute_aliases as AL

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


ids = lambda q: sorted(e["id"] for e in AL.fired(q) if e["id"].startswith("bns_2"))
check([e["id"] for e in AL._COMPILED if e["id"].startswith("bns_2")] == ["bns_249_harbour", "bns_253_harbour_escaped_or_ordered", "bns_254_harbour_robbers"], "the three harbouring entries exist, after the two earlier ones")

# ---- fires (version 1 groups)
P249 = ["I gave a lift to a man the police were after, not knowing anything. Am I guilty?", "Is harbouring an offender a crime?",
        "She sheltered the fugitive for a night.", "I let my friend stay in my house while he was on the run.", "Is a person who is an accessory after the fact punishable?", "What if I screen an offender from legal punishment?", "I gave shelter to an absconding accused."]
for q in P249:
    check(ids(q) == ["bns_249_harbour"], f"249 fires: {q}")
# ---- fires (version 2 groups)
V2 = ["The main accused was staying at my guest house while the police were searching for him.", "I rented a room to a man wanted by the police.", "My driver took the main accused to another town."]
for q in V2:
    check(ids(q) == ["bns_249_harbour"], f"249 fires (v2 groups): {q}")
# ---- known limits of the groups as written (found by this file's own hand-written sentences, 2026-11-09; NOT tuned: a change needs a new measured question set). A person named with his/her/their, or "the wanted man" / "the absconding accused", is not read as the object.
LIMITS = ["My uncle hid his nephew who is absconding from a theft case.", "He helped his brother to hide from the police.", "I drove the wanted man to the station in my taxi.", "We took the absconding accused to his village in our van."]
for q in LIMITS:
    check(not ids(q), f"known limit (does not fire, on purpose left as written): {q}")

# ---- 253 and 254
check("bns_253_harbour_escaped_or_ordered" in ids("I hid a man who escaped from police custody yesterday."), "253 fires: hiding a man who escaped from custody")
check("bns_253_harbour_escaped_or_ordered" in ids("The magistrate issued a warrant for his arrest and I concealed him in my cellar."), "253 fires: concealing a man whose arrest was ordered")
check("bns_254_harbour_robbers" in ids("I harboured the robbers after the bank job."), "254 fires: harbouring robbers")
check("bns_254_harbour_robbers" not in ids("I harboured the accused after the cheating case."), "254 does not fire without robbers or dacoits")
# ---- does not fire
N = ["Police arrested me without telling me the reason.", "The accused absconded. Can the trial go on without him?", "Can I get anticipatory bail while I am hiding from the police?", "Is it legal to give a lift to a hitchhiker?",
     "I hid my savings from my spouse.", "What is the punishment for hiding a dead body?", "Is it an offence to harbour a minor for exploitation?", "The accused escaped from custody. Is the jailer liable?",
     "I provided shelter to a victim of violence.", "The police took the accused to the court for the hearing.", "My guest staying at my hotel was arrested.", "Who is a proclaimed offender?",
     "I gave a lift to a colleague and we had an accident.", "Police are looking for my brother. They threatened my family.", "I carried the complainant to the hospital.", ""]
for q in N:
    check(not ids(q), f"does not fire: {q[:70]}")
check(not ids(None), "None fires nothing")

# ---- the switch and the match
check(AL.mode() == "off" and AL.matches("I hid my friend who is absconding.") == [], "STATUTE_ALIASES unset: nothing is returned")
os.environ["STATUTE_ALIASES"] = "on"
ms, out = quiet(AL.matches, "Police arrested me since I gave a lift to the prime accused who was absconding. I never knew.")
ms = [m for m in ms if m["act"] == "BNS"]          # the sentence also says "Police arrested me", which since 2026-11-09 brings the bail entries (BNSS 478 and 480) as well
check(len(ms) == 1 and ms[0]["act"] == "BNS" and ms[0]["section_number"] == "249" and ms[0]["retrieval"] == "alias" and ms[0]["source"] == "statute_alias", "on: BNS 249 is returned, marked alias")
check("harbours or conceals a person whom he knows or has reason to believe" in " ".join(ms[0]["text"].split()) and "context_note" not in ms[0], "on: the text is the library's own official wording, no commentary attached")
check("bns_249_harbour" in out and out.startswith("STATUTE_ALIAS {"), "on: one STATUTE_ALIAS log line")
ms, _ = quiet(AL.matches, "I hid a man who escaped from police custody.", already={("BNS", "253")})
check(["253" not in [m["section_number"] for m in ms]][0], "a section already supplied is not added again")

# ---- the pipeline, model stubbed
import chat_assistant as CA
import semantic_retrieval as sr

REAL = (CA.classify_scope, CA._fetch_pilot_related_judgments, CA.generate_grounded_response, CA._answer_from_wider_search_only, CA._answer_single_match, sr.semantic_search, sr.lexical_search)
CA.classify_scope = lambda q: ("in_scope", "stub", None)
CA._fetch_pilot_related_judgments = lambda *a, **k: []
CA.generate_grounded_response = lambda *a, **k: ""
CA._answer_from_wider_search_only = lambda *a, **k: None
CA._answer_single_match = lambda question, matches: {"state": "single_match", "matches": matches}
sr.semantic_search = lambda q, top_k=50, _raise_errors=False: []
sr.lexical_search = lambda q, top_k=50: []
Q = "Police was looking for the prime accused. He was absconding. Police arrested me since I gave a lift to the prime accused. I never knew about his crime."
try:
    r, _ = quiet(CA._answer_question_core, Q)
    check(("BNS", "249") in [(m.get("act"), str(m.get("section_number"))) for m in r.get("matches") or [] if m.get("type") == "statute"], "pipeline, on: a question the library search cannot place still brings BNS 249")
    os.environ["STATUTE_ALIASES"] = "off"
    r, _ = quiet(CA._answer_question_core, Q)
    check(("BNS", "249") not in [(m.get("act"), str(m.get("section_number"))) for m in r.get("matches") or [] if m.get("type") == "statute"], "pipeline, off: BNS 249 does not arrive")
finally:
    (CA.classify_scope, CA._fetch_pilot_related_judgments, CA.generate_grounded_response, CA._answer_from_wider_search_only, CA._answer_single_match, sr.semantic_search, sr.lexical_search) = REAL
    os.environ.pop("STATUTE_ALIASES", None)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("ALL PASSED")
