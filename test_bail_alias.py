"""
test_bail_alias.py -- the bail entries of statute_aliases.py (BNSS 478, 480, 483), added 2026-11-09 (FOLLOW_UPS 2dx in the research repository). Offline and free: hand-written sentences that are NOT the pre-registered measurement sets
(those are in review_results/2026-11-09_bail_alias/ in the research repository); the model and Voyage are stubbed in the pipeline check. Run: python -X utf8 test_bail_alias.py
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


bail = lambda q: sorted(e["id"] for e in AL.fired(q) if e["id"].startswith("bnss_4") and "bail" in e["id"])
FIRST = ["bnss_478_bail_bailable", "bnss_480_bail_nonbailable"]
check([e["id"] for e in AL._COMPILED][-3:] == ["bnss_478_bail_bailable", "bnss_480_bail_nonbailable", "bnss_483_bail_higher_court"], "the three bail entries exist")
for q in ["My cousin got arrested in a brawl outside a wedding.", "He was detained at the border last night.", "The police arrested my uncle this morning.", "She is in judicial custody since Monday.",
          "My son is lying in jail and we do not know what to do.", "They remanded him to police custody for four days.", "We were arrested while walking home.", "I have been in police custody for two nights."]:
    check(bail(q) == FIRST, f"478 and 480 fire: {q}")
for q in ["The Sessions Court rejected the bail application of my brother.", "Can we ask the High Court for bail?", "The magistrate declined to grant him bail yesterday."]:
    check("bnss_483_bail_higher_court" in bail(q), f"483 fires: {q}")
check("bnss_483_bail_higher_court" not in bail("My brother was arrested yesterday. How do we get him out?"), "483 does not fire for an arrest alone")
for q in ["Can the police arrest me for this?", "What is anticipatory bail?", "How long can the police detain a suspect?", "Bail is a right in bailable offences, is it not?", "I want to file a complaint against my landlord.",
          "Police are looking for my cousin.", "The accused absconded and the trial is stuck.", "", "Who can stand surety?"]:
    check(not bail(q), f"does not fire: {q[:70]}")
check(not bail(None), "None fires nothing")
# ---- known limits of the groups as written (found on the earlier question sets, NOT tuned; a change needs a new measured set)
check(bail("The police took my phone and laptop during their investigation without giving me any paper.") == FIRST, "known limit: 'police took my phone' reads as an arrest (kept as written)")
check(bail("How long can a person be kept in custody before being produced before a magistrate?") == FIRST, "known limit: a general question that says 'kept in custody' fires (kept as written)")
# ---- the switch and the match
check(AL.matches("My brother was arrested last night.") == [], "STATUTE_ALIASES unset: nothing is returned")
os.environ["STATUTE_ALIASES"] = "on"
ms, out = quiet(AL.matches, "My brother was arrested last night for a fight. How can we get him out?")
check(sorted(m["section_number"] for m in ms) == ["478", "480"] and all(m["act"] == "BNSS" and m["retrieval"] == "alias" for m in ms), "on: BNSS 478 and 480, marked alias")
check("bailable offence" in " ".join(ms[0]["text"].split()).lower() or "bail" in ms[0]["text"].lower(), "on: the text is the library's own, no commentary attached")
check(all("context_note" not in m for m in ms) and "bnss_478_bail_bailable" in out, "on: no commentary; one STATUTE_ALIAS line names the entries")
ms, _ = quiet(AL.matches, "My brother was arrested last night.", already={("BNSS", "478")})
check([m["section_number"] for m in ms] == ["480"], "a section already supplied is not added again")
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
Q = "My brother was arrested last night for a fight. How can we get him out?"
secs = lambda r: {(m.get("act"), str(m.get("section_number"))) for m in r.get("matches") or [] if m.get("type") == "statute"}
try:
    r, _ = quiet(CA._answer_question_core, Q)
    check({("BNSS", "478"), ("BNSS", "480")} <= secs(r), "pipeline, on: a question the library search cannot place still brings BNSS 478 and 480")
    os.environ["STATUTE_ALIASES"] = "off"
    r, _ = quiet(CA._answer_question_core, Q)
    check(not ({("BNSS", "478"), ("BNSS", "480")} & secs(r)), "pipeline, off: neither arrives")
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
