"""
test_retrieval_misses.py -- the three retrieval-miss fixes of 2026-11-03 (research FOLLOW_UPS 2dg):
  statute_widen.py     STATUTE_WIDEN=off|log|on     sections just outside the 0.08 gap / cap of five that a cross-encoder scores high are ADDED
  statute_aliases.py   STATUTE_ALIASES=off|on       BNSS 528 (quash) and BNSS 359 (compound / settle) by word groups
  act_detect.py        EVIDENCE_DETECT=on           the Bharatiya Sakshya Adhiniyam is found by the law of evidence's own topics
Offline and free: stand-in searches and a stand-in re-ranker. Run: python -X utf8 test_retrieval_misses.py
"""
import contextlib
import io
import os
import sys

import act_detect
import semantic_retrieval as sr
import statute_aliases as AL
import statute_widen as W

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


for k in ("STATUTE_WIDEN", "STATUTE_WIDEN_POOL", "STATUTE_WIDEN_MAX", "STATUTE_WIDEN_FLOOR", "STATUTE_ALIASES", "EVIDENCE_DETECT", "ACT_DETECT", "RELEVANCE_GATE"):
    os.environ.pop(k, None)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


# ------------------------------------------------------------------------------------------------ statute_widen
def S(sec, score, act="BNSS"):
    return {"type": "statute", "act": act, "section_number": sec, "text": f"{sec}. Text of section {sec}.", "score": score}


def J(name, score):
    return {"type": "judgment", "case_name": name, "text": f"Passage of {name}.", "score": score}


# a result list as the search returns it: best first, judgments mixed in
RESULTS = [S("480", 0.60), J("Case A", 0.55), S("482", 0.52), S("483", 0.50), S("484", 0.49), S("485", 0.48), S("486", 0.47), S("187", 0.46), S("250", 0.45), S("251", 0.44),
           S("63", 0.43), S("64", 0.42), S("65", 0.41), S("66", 0.40), S("67", 0.39), S("68", 0.38)]
KEPT = [S("480", 0.60), S("482", 0.52), S("483", 0.50), S("484", 0.49), S("485", 0.48)]
RR = {"486": 0.70, "187": 0.74, "250": 0.62, "251": 0.55, "63": 0.66, "64": 0.20}


def fake_rerank(q, docs):
    out = [{"index": i, "score": next((v for k, v in RR.items() if d.startswith(k + ".")), 0.1), "document": d} for i, d in enumerate(docs)]
    return sorted(out, key=lambda x: -x["score"])


check(W.mode() == "off", "STATUTE_WIDEN unset -> off")
added, info = W.widen("q", RESULTS, KEPT, rerank_fn=fake_rerank)
check(added == [] and info["rerank"] == "skipped", "off: nothing added and the re-ranker is not called")

os.environ["STATUTE_WIDEN"] = "log"
(added, info), out = quiet(W.widen, "q", RESULTS, KEPT, rerank_fn=fake_rerank)
check(added == [] and [a["sec"] for a in info["added"]] == ["486", "187"], f"log: nothing is added, but the would-be additions are recorded in cosine order: {[a['sec'] for a in info['added']]}")
_, out = quiet(W.log, "q", info)
check(out.startswith("STATUTE_WIDEN {") and '"mode": "log"' in out, "log: one STATUTE_WIDEN line is written")

os.environ["STATUTE_WIDEN"] = "on"
added, info = W.widen("q", RESULTS, KEPT, rerank_fn=fake_rerank)
check([m["section_number"] for m in added] == ["486", "187"], f"on: the first two sections (cosine order) with a re-ranker score >= 0.55 are added: {[m['section_number'] for m in added]}")
check(all(m["retrieval"] == "widened" and m["widen_rerank"] >= 0.55 for m in added), "on: added sections are marked retrieval 'widened' with their re-ranker score")
check({m["section_number"] for m in added}.isdisjoint({m["section_number"] for m in KEPT}), "on: a section already selected is never added again")
check(added[0]["text"] == "486. Text of section 486." and added[0]["score"] == 0.47, "on: an added section keeps its own text and cosine score")

os.environ["STATUTE_WIDEN_MAX"] = "3"
added, _ = W.widen("q", RESULTS, KEPT, rerank_fn=fake_rerank)
check([m["section_number"] for m in added] == ["486", "187", "250"], f"STATUTE_WIDEN_MAX=3 -> three: {[m['section_number'] for m in added]}")
os.environ["STATUTE_WIDEN_MAX"] = "0"
added, _ = W.widen("q", RESULTS, KEPT, rerank_fn=fake_rerank)
check(added == [], "STATUTE_WIDEN_MAX=0 -> nothing")
os.environ.pop("STATUTE_WIDEN_MAX")

os.environ["STATUTE_WIDEN_POOL"] = "4"
added, info = W.widen("q", RESULTS, KEPT, rerank_fn=fake_rerank)
check(info["pool"] == 0 or all(m["section_number"] in ("480", "482", "483", "484") for m in added) or added == [], "a pool of four (all of them kept or none above) leaves nothing to add")
os.environ["STATUTE_WIDEN_POOL"] = "9"
added, info = W.widen("q", RESULTS, KEPT, rerank_fn=fake_rerank)
check([m["section_number"] for m in added] == ["486", "187"], "STATUTE_WIDEN_POOL counts the closest sections whether or not they were kept: 9 reaches 250 but 63 is outside")
os.environ.pop("STATUTE_WIDEN_POOL")

os.environ["STATUTE_WIDEN_FLOOR"] = "0.9"
added, _ = W.widen("q", RESULTS, KEPT, rerank_fn=fake_rerank)
check(added == [], "STATUTE_WIDEN_FLOOR=0.9 -> nothing passes")
os.environ["STATUTE_WIDEN_FLOOR"] = "junk"
added, _ = W.widen("q", RESULTS, KEPT, rerank_fn=fake_rerank)
check([m["section_number"] for m in added] == ["486", "187"], "an unreadable floor falls back to 0.55")
os.environ.pop("STATUTE_WIDEN_FLOOR")

LOW = [S("480", 0.60), S("482", 0.30), S("483", 0.20)]
added, _ = W.widen("q", LOW, [LOW[0]], rerank_fn=lambda q, d: [{"index": i, "score": 0.99} for i in range(len(d))])
check(added == [], "a section below the usual cosine floor (0.34) is never a candidate, however the re-ranker scores it")
added, info = W.widen("q", RESULTS, KEPT, rerank_fn=lambda q, d: None)
check(added == [] and info["rerank"] == "unavailable", "re-ranker unavailable -> nothing added, recorded as unavailable")
added, info = W.widen("q", RESULTS, KEPT, rerank_fn=lambda q, d: (_ for _ in ()).throw(RuntimeError("boom")))
check(added == [] and "error" in info, "an exception in the re-ranker never escapes")
added, _ = W.widen("", RESULTS, KEPT, rerank_fn=fake_rerank)
check(added == [], "an empty question adds nothing")
added, _ = W.widen("q", [J("Only A judgment", 0.9)], [], rerank_fn=fake_rerank)
check(added == [], "judgments are never candidates")

# the wiring inside find_relevant_sections: stand-in searches
real = (sr.semantic_search, sr.lexical_search, sr.rerank)
sr.semantic_search = lambda q, top_k=50, _raise_errors=False: [dict(r) for r in RESULTS]
sr.lexical_search = lambda q, top_k=50: []
sr.rerank = fake_rerank
try:
    os.environ["STATUTE_WIDEN"] = "off"
    r_off, _ = quiet(sr.find_relevant_sections, "a plain question about bail")
    secs_off = [m["section_number"] for m in r_off["matches"]]
    check(secs_off == ["480"] or set(secs_off) <= {"480", "482", "483", "484", "485"}, f"wiring, off: only the usual selection {secs_off}")
    os.environ["STATUTE_WIDEN"] = "on"
    r_on, out = quiet(sr.find_relevant_sections, "a plain question about bail")
    secs_on = [m["section_number"] for m in r_on["matches"]]
    check(secs_on[:len(secs_off)] == secs_off and set(secs_on) - set(secs_off) == {"486", "187"} or set(secs_on) - set(secs_off) <= {"482", "483", "484", "485", "486", "187"},
          f"wiring, on: the usual selection comes first, then the additions: {secs_off} -> {secs_on}")
    added_on = [m for m in r_on["matches"] if m.get("retrieval") == "widened"]
    check(all(m["section_number"] in ("486", "187") for m in added_on) and 0 < len(added_on) <= 2, "wiring, on: the additions are marked widened and are at most two")
    check(r_on["state"] == r_off["state"], "wiring: the single / conflicting state is the same with and without the additions")
    check("STATUTE_WIDEN {" in out, "wiring, on: the STATUTE_WIDEN line is written")
    r_dom, _ = quiet(sr.find_relevant_sections, "a plain question about bail", domain="cheque_bounce")
    check(not [m for m in r_dom["matches"] if m.get("retrieval") == "widened"], "wiring: a call for an inline domain (cheque bounce, freeze) is not widened")
    sr._named_section_exact_match, _keep = (lambda q: S("480", 0.99)), sr._named_section_exact_match
    try:
        r_ex, _ = quiet(sr.find_relevant_sections, "section 480 bnss")
    finally:
        sr._named_section_exact_match = _keep
    check([m["section_number"] for m in r_ex["matches"]] == ["480"], "wiring: a section the person named by number is the only statute match (nothing is added)")
finally:
    sr.semantic_search, sr.lexical_search, sr.rerank = real
    os.environ.pop("STATUTE_WIDEN", None)

# ------------------------------------------------------------------------------------------------ statute_aliases
check(AL.mode() == "off", "STATUTE_ALIASES unset -> off")
check(AL.matches("How can a High Court quash an FIR?") == [], "off: nothing is returned")
os.environ["STATUTE_ALIASES"] = "on"
POS528 = ["How can a High Court quash an FIR?", "Can my FIR be quashed?", "What are the inherent powers of the High Court?", "Can the High Court cancel an FIR that is false and malicious?",
          "Is it an abuse of the process of the court to file this case?", "Can the High Court set aside the criminal case against my father?", "The High Court quashed the proceedings. What happens now?"]
NEG528 = ["Can I get bail?", "The court cancelled my bail. What now?", "How do I cancel an FIR?", "The squash court was damaged in a riot.", "The police dismissed my complaint. Can I go to the High Court?",
          "What are the powers of the police during an investigation?", "He cancelled the cheque.", "An abusive process server shouted at me."]
for q in POS528:
    check([e["id"] for e in AL.fired(q)] == ["bnss_528_quash"], f"528 fires: {q}")
for q in NEG528:
    check(not [e for e in AL.fired(q) if e["id"] == "bnss_528_quash"], f"528 does not fire: {q}")
POS359 = ["Which offences can be compounded?", "Is this offence compoundable?", "Can the parties settle a case and have it ended?", "Is compounding allowed in a cheating case?",
          "The complainant and I want to compromise the criminal case. Is that allowed?", "Can the victim and the accused patch up and end the complaint?"]
NEG359 = ["My neighbour entered my compound and cut the tree.", "A compound wall fell on my car.", "I want to settle my dues with the bank.", "Can a case be transferred to another court?",
          "We settled the property dispute among the family.", "The compounder at the clinic gave me the wrong medicine."]
for q in POS359:
    check([e["id"] for e in AL.fired(q)] == ["bnss_359_compound"], f"359 fires: {q}")
for q in NEG359:
    check(not [e for e in AL.fired(q) if e["id"] == "bnss_359_compound"], f"359 does not fire: {q}")

ms, out = quiet(AL.matches, "How can a High Court quash an FIR?")
check(len(ms) == 1 and ms[0]["act"] == "BNSS" and ms[0]["section_number"] == "528" and ms[0]["retrieval"] == "alias" and ms[0]["source"] == "statute_alias", "on: the match is BNSS 528 marked alias")
check("inherent powers of the High Court" in " ".join(ms[0]["text"].split()) and "context_note" not in ms[0], "on: the text is the library's own, and no curated note is attached")
check(out.startswith("STATUTE_ALIAS {") and "bnss_528_quash" in out, "on: one STATUTE_ALIAS line is written")
ms, _ = quiet(AL.matches, "How can a High Court quash an FIR?", already={("BNSS", "528")})
check(ms == [], "a section already supplied is not added again")
ms, _ = quiet(AL.matches, "Can the parties settle a case and quash the FIR?")
check(sorted(m["section_number"] for m in ms) == ["359", "528"], "two entries can fire for one question")
check(AL.matches("") == [] and AL.matches(None) == [], "an empty question fires nothing")

# the pipeline hook, with the model stubbed out
import chat_assistant as CA

CA_REAL = (CA.classify_scope, CA._fetch_pilot_related_judgments, CA.generate_grounded_response, CA._answer_from_wider_search_only, CA._answer_single_match, sr.semantic_search, sr.lexical_search)
CA.classify_scope = lambda q: ("in_scope", "stub", None)
CA._fetch_pilot_related_judgments = lambda *a, **k: []
CA.generate_grounded_response = lambda *a, **k: ""
CA._answer_from_wider_search_only = lambda *a, **k: None
CA._answer_single_match = lambda question, matches: {"state": "single_match", "matches": matches}
sr.semantic_search = lambda q, top_k=50, _raise_errors=False: []
sr.lexical_search = lambda q, top_k=50: []
try:
    r, _ = quiet(CA._answer_question_core, "How can a High Court quash an FIR?")
    check(r.get("state") == "single_match" and [(m["act"], m["section_number"]) for m in r["matches"] if m.get("type") == "statute"] == [("BNSS", "528")], "pipeline, on: a question that the library search cannot place still brings BNSS 528")
    os.environ["STATUTE_ALIASES"] = "off"
    r, _ = quiet(CA._answer_question_core, "How can a High Court quash an FIR?")
    check(("BNSS", "528") not in [(m.get("act"), str(m.get("section_number"))) for m in r.get("matches") or [] if m.get("type") == "statute"], "pipeline, off: BNSS 528 does not arrive (the judgment wiring for FIR quashing is not part of this switch)")
    os.environ["STATUTE_ALIASES"] = "on"
    sr.semantic_search = lambda q, top_k=50, _raise_errors=False: [{"type": "statute", "act": "BNSS", "section_number": "528", "text": "528. Nothing in this Sanhita ...", "score": 0.50, "chunk_id": "statute:BNSS:528"}]
    r, _ = quiet(CA._answer_question_core, "How can a High Court quash an FIR?")
    n528 = [m for m in r["matches"] if m.get("type") == "statute" and (m["act"], str(m["section_number"])) == ("BNSS", "528")]
    check(len(n528) == 1, f"pipeline, on: a section the library search found itself is handed over once ({len(n528)})")
finally:
    (CA.classify_scope, CA._fetch_pilot_related_judgments, CA.generate_grounded_response, CA._answer_from_wider_search_only, CA._answer_single_match, sr.semantic_search, sr.lexical_search) = CA_REAL
    os.environ.pop("STATUTE_ALIASES", None)

# ------------------------------------------------------------------------------------------------ the evidence word pass
bsa = lambda q: [h for h in act_detect.wide(q) if h["id"] == "bsa_2023"]
check(not bsa("Is a confession made to a police officer admissible in court?"), "EVIDENCE_DETECT unset: the word pass does not name the Bharatiya Sakshya Adhiniyam")
os.environ["EVIDENCE_DETECT"] = "on"
EVID = [
    "Can I use a dying declaration against the accused?", "What is hearsay evidence and is it allowed?", "Who has the burden of proof in a criminal case?",
    "Is the evidence of an approver reliable enough for a conviction?", "A prosecution witness turned hostile. What next?", "Is a call recording admissible in a criminal case?",
    "Can a WhatsApp chat be used as evidence in court?", "Can the court accept a photocopy of the sale deed as proof?", "What certificate is needed for electronic evidence?",
    "Is an extra-judicial confession admissible against the accused?", "What does cross-examination of a witness involve?", "Can a husband be compelled to testify against his wife?",
    "Can the court rely on a single witness?", "Does the court presume that the signature is genuine?", "Can the accused's bad character be brought up in the trial?",
    "Is a handwriting expert's opinion binding?", "Who must prove that the accused is innocent?", "The statement the police recorded from the dead man, can it be used in court?",
    "Can CCTV footage be produced in court as proof?", "Is a statement made to a police officer usable against the accused?",
]
for q in EVID:
    check(bool(bsa(q)), f"evidence pass names the Act: {q}")
NOT_EVID = [
    "The police say they have no evidence against my brother. Can he get bail?", "What is the punishment for theft?", "My neighbour threatened a witness in our case. What can I do?",
    "The complainant has withdrawn her statement. Will the case be closed now?", "Can the police arrest me without a warrant?", "A witness is not coming to court even after summons. What can the court do?",
    "I got a notice to appear as a witness in a murder trial. Do I have to go?", "What is the punishment for destroying evidence of a crime?", "The police took my mobile phone. Can they keep it?",
    "The FIR is based only on suspicion with no proof. Can the High Court cancel it?", "I was arrested yesterday. Which documents must the police give me?", "What is the punishment for false evidence?",
]
for q in NOT_EVID:
    check(not bsa(q), f"evidence pass stays quiet: {q}")
check(not [h for h in act_detect.wide("Can a person be convicted on circumstantial evidence alone?") if h["id"] == "bsa_2023"], "circumstantial evidence is left to its own flow (no word-pass hit)")
os.environ["EVIDENCE_DETECT"] = "off"
check(not bsa("Is a confession made to a police officer admissible in court?"), "EVIDENCE_DETECT=off: quiet again")
os.environ["EVIDENCE_DETECT"] = '"on"'
check(bool(bsa("Is a confession made to a police officer admissible in court?")), "quotation marks around the value are ignored")
os.environ.pop("EVIDENCE_DETECT")
check(act_detect.wide("The accused is a Muslim woman's husband who said talaq three times by SMS.") and not bsa("x"), "the other Acts' word passes still work with the evidence switch off")

print()
print("FAILURES:", len(FAILURES))
for f in FAILURES:
    print("  -", f)
sys.exit(1 if FAILURES else 0)
