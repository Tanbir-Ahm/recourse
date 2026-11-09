"""
test_charge_map.py -- "What else could he be charged with?" (charge_map.py, chat_assistant._charge_matches / _charge_block, web_chat.engine_case_file, answer_view / export table; owner's go 2026-11-09, step 3). Free: no network, no model, the search is a stub.
Proves: the candidates for the 9 Nov molestation facts are the sections of the pattern table with their reasons and the BNSS Schedule's rows; a pattern fires only when its words are there; a meaning search can add only BNS OFFENCES (a section of the Schedule), never a procedure section such as BNSS 358, 234 or 244, and
at most three; the switch needs CASE_FILE; the engine turns the candidates into matches marked 'charge_map', puts them and the clause in the prompt (Hard rules unchanged), remembers them for the page's table; nothing happens for any other turn; the page and the Word/PDF file carry the table.
Run: python -X utf8 test_charge_map.py
"""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for v in ("CHARGE_MAP", "CASE_FILE", "AGE_CARD", "RESPONSE_STYLE", "ANSWER_SHAPE", "OFFENCE_CLASS"):
    os.environ.pop(v, None)

import charge_map as C

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


FACTS = ("My client was arrested on the charges that he was recording a sexual molestation case. The prime accused was arrested on the charges of rape. My client was arrested as the said video was phone on his phone and was widely shared, "
         "and he was apparently present at the crime spot")
none = lambda t: []

cs = C.candidates(FACTS, search=none)
keys = [f"{c['act']} {c['section']}" for c in cs]
check(keys == ["BNS 77", "ITACT 66E", "ITACT 67", "ITACT 67A", "BNS 70", "BNS 3", "BNS 61", "BNS 45", "BNS 49"], f"the molestation facts give the table's sections in its order ({keys})")
c45 = next(c for c in cs if c["section"] == "45")
check(c45["pattern"] == "present_at_rape" and "intentionally aids" in c45["why"] and c45["class"] is None, "BNS 45 (the definition of abetment) is its own candidate, with no Schedule row invented (the punishment is in 49)")
c77 = next(c for c in cs if c["section"] == "77")
check(c77["source"] == "pattern" and c77["pattern"] == "recording_sexual" and c77["class"] and "Voyeurism" in c77["class"]["lines"][0] and c77["class"]["lines"][0].startswith("BNS 77:"), "BNS 77 carries its reason and the Schedule's row")
check(next(c for c in cs if c["section"] == "66E")["class"] is None and next(c for c in cs if c["section"] == "3")["class"] is None, "an IT Act section and BNS 3 (a rule, not an offence) have no Schedule row: no classification is invented")
check(next(c for c in cs if c["section"] == "70")["class"]["summary"][0] == "cognizable, non-bailable", "BNS 70: the Schedule's classification")

check(C.candidates("", search=none) == [] and C.candidates(None, search=none) == [] and C.candidates("My client was arrested for stealing a bicycle.", search=none) == [], "no text, or facts that fit no pattern: no candidate")
check([c["section"] for c in C.candidates("He deleted the video from the phone after the rape to hide the evidence.", search=none) if c["pattern"] == "evidence_deleted"] == ["238"], "evidence deleted in a crime context: BNS 238")
check(not [c for c in C.candidates("The witness deleted old messages from her phone to free storage space.", search=none)], "deleting messages with no crime in the words: nothing")

# the meaning search can add offences only
def stub(t):
    return [{"act": "BNSS", "section_number": "358"}, {"act": "BNSS", "section_number": "234"}, {"act": "BNSS", "section_number": "244"}, {"act": "BNS", "section_number": "3"},
            {"act": "BNS", "section_number": "74"}, {"act": "BNS", "section_number": "79"}, {"act": "BNS", "section_number": "77"}, {"act": "BNS", "section_number": "75"}, {"act": "BNS", "section_number": "76"}, {"case_name": "A v. B"}]
cs2 = C.candidates(FACTS, search=stub)
sr = [f"{c['act']} {c['section']}" for c in cs2 if c["source"] == "search"]
check(sr == ["BNS 74", "BNS 79", "BNS 75"] and len(sr) == C.MAX_SEARCHED, f"the search adds at most three BNS offences, none already listed, no BNSS procedure section, no rule, no case ({sr})")
check(all(c["why"] == "Found by meaning from the facts; check that it fits." and c["class"] for c in cs2 if c["source"] == "search"), "...each labelled as found by meaning, with its Schedule row")
check(len(C.candidates(FACTS, search=stub, limit=5)) == 5 + 3 and len([c for c in C.candidates(FACTS, search=stub, limit=5) if c["source"] == "pattern"]) == 5, "the limit holds for the table's sections; the search adds its three on top")

# the switch
check(not C.enabled(), "off by default")
os.environ["CHARGE_MAP"] = "on"
check(not C.enabled(), "CHARGE_MAP needs CASE_FILE")
os.environ["CASE_FILE"] = "on"
check(C.enabled(), "on with CASE_FILE")

# ---------------------------------------------------------------- the engine
import chat_assistant as CA
import answer_style

CA._CASE.arg = None
check(CA._charge_matches(set()) == [] and CA._charge_block() == "", "any other turn: nothing")
CA._CASE.arg = {"charges": {"facts": FACTS}, "victim_minor": None}
CA.C = None
import charge_map
_orig = charge_map._default_search
charge_map._default_search = none
have = {("BNS", "77")}
ms = CA._charge_matches(have)
secs = [(m["act"], str(m["section_number"])) for m in ms]
check(("BNS", "77") not in secs and ("BNS", "70") in secs and ("BNS", "49") in secs and ("ITACT", "67A") in secs and all(m["retrieval"] == "charge_map" and m["charge_why"] for m in ms), f"the candidates become statute matches marked charge_map, a section already present is not added twice ({secs})")
blk = CA._charge_block()
check("## Sections the facts may bring in" in blk and "BNS section 70" in blk and "Schedule: BNS 70(1): Gang rape." in blk and "the list is NOT complete" in blk and "Do not add a section that is not in the material" in blk, "the block lists them with their reasons and Schedule lines and says the list is not complete")
check(len(CA._CASE.charge_candidates) == 9, "the candidates are remembered for the page's table")
txt = CA.format_retrieved_text_for_prompt(ms)
check("(A section the facts may bring in, chosen by a program:" in txt, "each match is introduced as a section the facts may bring in")

sent = {}


class _M:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["p"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="**Bottom line**\n\nx")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_M())
CA.generate_grounded_response("What other sections can he be charged with?", txt, matches=ms)
check("## Sections the facts may bring in" in sent["p"] and sent["p"].index("Gang rape") < sent["p"].index("Write the answer now") and "## Hard rules (never break)" in sent["p"] and "Use ONLY the legal information given below" in sent["p"], "the prompt carries the block and the Hard rules are unchanged")
CA._CASE.arg = None
CA._CASE.charge_candidates = None
charge_map._default_search = _orig
CA.generate_grounded_response("What other sections can he be charged with?", txt, matches=ms)
check("## Sections the facts may bring in" not in sent["p"], "without the case-file argument the prompt has no block")

# web_chat: the separate argument
import case_file as CF
import web_chat as W
cf = CF.add_from_message(None, FACTS)
ecf = W.engine_case_file(cf, {"turn": 2, "rewrite": "used", "carry": []}, [], "x", intent="charges")
check(ecf["charges"]["facts"] and "present at the crime spot" in ecf["charges"]["facts"] and ecf["search_hint"], "the 'charges' intent hands the engine the facts")
check(W.engine_case_file(cf, {"turn": 2, "rewrite": "used", "carry": []}, [], "x")["charges"] is None, "any other turn: no charges argument")

# the page and the file
import answer_export as AE
import answer_view as AV
res = {"state": "single_match", "audience": "lawyer", "response_text": "**Bottom line**\n\nx", "matches": [], "charge_candidates": cs}
v = AV.build(res)
ct = v["charge_table"]
check(ct and len(ct["items"]) == 9 and ct["items"][0]["section"] == "BNS section 77" and ct["items"][1]["section"] == "IT Act section 66E" and ct["items"][0]["class_lines"] and "not been read by a lawyer" in ct["note"], "the view carries the table with plain section names and the Schedule lines")
check(AV.build({"state": "single_match", "response_text": "x", "matches": []})["charge_table"] is None, "none without candidates")
blocks = AE._answer_blocks(v, True)
t = " ".join(" ".join(r.get("text", "") for r in b.get("runs", [])) + " " + str(b.get("text", "")) for b in blocks)
check("Sections considered for the question of other charges" in t and "Voyeurism" in t and "not been read by a lawyer" in t, "the Word and PDF file carry the table")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
