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
# the companion rule: abetment (45, 49) and conspiracy (61) when more than one person is in the offence itself
def keys_of(t):
    return [f"{c['act']} {c['section']}" for c in C.candidates(t, search=none)]
multi = keys_of("My client and two of his friends beat the complainant with sticks and fractured his arm.")
check(multi == ["BNS 115", "BNS 117", "BNS 118", "BNS 61", "BNS 45", "BNS 49"] and all(c["pattern"] == "companion" for c in C.candidates("My client and two of his friends beat the complainant with sticks and fractured his arm.", search=none) if c["section"] in ("61", "45", "49")), f"several persons + a hurt pattern: the companions come after the pattern's own sections ({multi})")
check(not {"BNS 45", "BNS 49", "BNS 61"} & set(keys_of("My client beat the complainant with an iron rod during a quarrel.")), "one person: no abetment or conspiracy")
check(not {"BNS 45", "BNS 49", "BNS 61"} & set(keys_of("My uncle cheated a widow of her savings using a forged signature.")), "a single-actor cheating case no longer carries conspiracy (it moved from the cheating pattern to the companion rule)")
check({"BNS 45", "BNS 49", "BNS 61"} <= set(keys_of("My uncle and his partner cheated a widow of her savings with a forged sale deed.")), "...and a cheating case with a partner does")
check(not {"BNS 45", "BNS 49", "BNS 61"} & set(keys_of("He and his friends gave a lift to a man who was absconding in a murder case.")), "after-the-fact patterns (harbouring) get no abetment or conspiracy from this rule")
check(not {"BNS 45", "BNS 49", "BNS 61"} & set(keys_of("My client and his brother deleted the CCTV footage from the shop's system after the police registered the FIR.")), "...nor does evidence deleted")
check(keys_of("My client and his friends were arrested for selling liquor without a licence.") == [], "several persons but no pattern fires: nothing")
check(keys_of(FACTS).count("BNS 45") == 1 and keys_of(FACTS).count("BNS 61") == 1, "a section the rape pattern already brought is not listed twice")
# breach of trust (BNS 316) and the offence-ask detector (owner's go 2026-11-09, after the bank-accountant test whose first answer named only BNS 344)
cbt = keys_of("The treasurer of the housing society embezzled the maintenance fund of Rs 8 lakh.")
check(cbt[0] == "BNS 316" and C.candidates("The treasurer of the housing society embezzled the maintenance fund of Rs 8 lakh.", search=none)[0]["class"]["lines"][0].startswith("BNS 316(2)"), f"embezzlement by an office-bearer: BNS 316 with its Schedule rows ({cbt})")
check("BNS 316" not in keys_of("An agent sold my client's plot of land for Rs 40 lakh and my client received the full price."), "a sale with no entrustment is not a breach of trust")
check("BNS 316" in keys_of("The estate agent collected Rs 9 lakh as advance from buyers on behalf of the builder and spent it on his own business.") and "BNS 316" not in keys_of("The bank refused to release the funds in my client's account because of a court order."), "a plain verb needs a sign of entrustment")
check({"BNS 316", "BNS 61", "BNS 45", "BNS 49"} <= set(keys_of("The cashier and his friends diverted Rs 14 lakh of the members' deposits to a private firm.")), "breach of trust with several persons: the companions follow")
check(all(C.asks_offences(a) for a in ["What offences is he likely to face?", "Which sections can he be charged under?", "What charges will the police add?"]), "asks about offences are recognised")
check(not any(C.asks_offences(a) for a in ["What are the grounds to seek bail?", "What is the punishment under section 318?", "Is section 316 of the BNS bailable?", "What does section 344 say?", "", None]), "asks about bail, a named section and nothing are not")
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
CA._CASE.arg = {"charges": {"facts": FACTS, "implicit": True}, "victim_minor": None}
CA._charge_matches(have)
_blk2 = CA._charge_block()
check("which offences the client may face" in _blk2 and "what else the client can be charged with" not in _blk2 and "the list is NOT complete" in _blk2, "a first-question hand-over words the block as 'which offences', not 'what else'")
CA._CASE.arg = {"charges": {"facts": FACTS}, "victim_minor": None}
CA._charge_matches(have)
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
_ic = W.engine_case_file(None, {"turn": 1}, [], "My client is the cashier of a society and diverted Rs 14 lakh of deposits. He was arrested yesterday. What offences is he likely to face?", audience="lawyer")
check(_ic and _ic["charges"] and _ic["charges"].get("implicit") and "diverted Rs 14 lakh" in _ic["charges"]["facts"], "a lawyer's first question that asks which offences hands the engine the facts of the message itself")
check(W.engine_case_file(None, {"turn": 1}, [], "My client is the cashier of a society and diverted Rs 14 lakh of deposits. What are the grounds to seek bail?", audience="lawyer")["charges"] is None, "...not when the ask is about bail")
check(W.engine_case_file(None, {"turn": 1}, [], "My client is the cashier of a society and diverted Rs 14 lakh of deposits. What offences is he likely to face?", audience="layman")["charges"] is None, "...and not for the layman")


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
