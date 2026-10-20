"""
test_section_rule.py -- the named-section rule (section_rule.py, act_shelf.implied_sections, act_directory._prompt_named, chat_assistant._attach_section_note, the page; SECTION_RULE=on|off, default on, effective only with
ACT_SHELF on). Added 2026-10-19 after the owner's staging test of section 17 of the Prevention of Corruption Act: four questions, four answers (pasted below, word for word from the page):
  1. "Can a disproportionate assets case under PC act be filed without section 17 approval?"   the answer is about section 17A and never says "section 17"
  2. "I am asking about section 17, NOT section 17 A"                                         the answer gives the main rule and the first proviso of section 17, not the second
  3. "Does section 17 require authorisation of a police officer not below the rank of SP ..."  the answer gives the second proviso, not the first
  4. "No section 17 order exists for this case of disproportionate assets"                     the answer gives the second proviso, not the first; and in this turn (and in turn 3 when it comes after turn 1)
     the bare "section 17" was tied to no Act, so BNS section 17 was put into the material
No network, no model, no cost: question vectors are stored section vectors; the model is a stub that returns a chosen reply.
Run: python -X utf8 test_section_rule.py
"""
import contextlib
import io
import json
import os
import re
import sys
import types

import numpy as np

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("ACT_SHELF", "ACT_DIRECTORY", "ACT_DETECT", "CHAT_MODE", "SECTION_RULE", "REGISTER_HOOKS", "RESPONSE_STYLE", "SCOPE_GATE", "SCI_SEARCH_MODE", "ANCHORS", "GROUNDING_CHECKS", "PASSAGE_NOTES"):
    os.environ.pop(_v, None)

import act_directory as AD
import act_shelf as S
import chat_assistant as CA
import section_rule as R
import web_chat as W

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def boom(text):
    raise AssertionError("the test reached the real Voyage call")


S._embed_query = boom
EMB = json.load(open(os.path.join(S.SHELF_DIR, "shelf_embeddings.json"), encoding="utf-8"))
VEC = {r["chunk_id"]: np.array(r["embedding"], dtype=float) for r in EMB["records"]}


def like(code, sec):
    return lambda text: VEC[f"act:{code}:{sec}"]


# the owner's four real answers (staging test of 2026-10-19), verbatim from the page, without the notice and the 'Read the source' part (the 'Ans 1 - ' label the owner typed is left off)
ANS1 = 'Yes, a disproportionate assets case can generally be filed without prior approval under Section 17A of the Prevention of Corruption Act, because that approval requirement applies only to a specific kind of conduct — not to every case under the Act.\n\nWhat approval does Section 17A require?\n\nSection 17A of the Prevention of Corruption Act requires prior approval before a police officer enquires into, inquires into, or investigates an offence where the alleged offence is relatable to a recommendation made or decision taken by a public servant in discharge of official functions or duties. It exists so that public servants aren\'t harassed for good-faith decisions taken in their official role. In Nara Chandrababu Naidu v. State of Andhra Pradesh (2024) (from a wider search, not independently verified), the Supreme Court said Section 17A applies only to offences after the 2018 amendment, and that even absence of this approval would not vitiate the proceedings or justify quashing the FIR.\n\nA disproportionate-assets allegation is usually about possession of assets beyond known income, not about an official recommendation or decision — so Section 17A\'s condition may simply not be triggered on the facts at all. Separately, in State of Karnataka v. T.N. Sudhakar Reddy (2025) (from a wider search, not independently verified), the Court held that a source information report showing a prima facie picture of disproportionate assets was enough to justify investigative action, without needing to verify the information\'s absolute truth first.\n\nHow this cuts for and against you\n\nFor you:\n\nIf the alleged conduct is simply holding disproportionate assets, Section 17A\'s condition about "recommendation or decision" may not even apply.\nEven if 17A approval was missing, Nara Chandrababu Naidu says that alone would not vitiate the case.\nAgainst you:\n\nIf part of the allegation ties specific assets to an official decision you took, that slice of the case could need Section 17A approval.\nSeparately, cognizance by the court may still need sanction under Section 19 of the Prevention of Corruption Act for a public servant, which is a different requirement from Section 17A.\nWhat I can\'t tell from here: whether the specific allegations link any asset to an official decision or recommendation you made.\n\nWhat you can do now\n\nCheck whether the FIR or chargesheet describes the alleged assets as connected to any specific official decision or recommendation.\nAsk your lawyer to review whether Section 19 sanction (for cognizance) has been obtained, since that is separate from Section 17A.\nBring the FIR and any investigation order to a lawyer handling corruption-law matters for a point-by-point check against these sections.'
ANS2 = "Good question to clear up — Section 17 of the Prevention of Corruption Act is a different safeguard from Section 17A, and it does restrict who can investigate a disproportionate-assets case.\n\nWhat does Section 17 say?\n\nSection 17 of the Prevention of Corruption Act says that for offences under this Act, a police officer below a certain rank cannot investigate without the order of a Metropolitan Magistrate or first-class Magistrate, and cannot arrest without a warrant. The rank threshold depends on where the investigation happens: an Inspector for the Delhi Special Police Establishment, an Assistant Commissioner of Police in specified metropolitan areas, and a Deputy Superintendent of Police (or equivalent) elsewhere. The State Government can also authorise an Inspector-rank officer to investigate without that Magistrate's order, by a general or special order.\n\nThis exists so that corruption investigations, which can be used to harass public servants, are handled by a sufficiently senior or judicially-sanctioned officer rather than any constable. None of the material before me shows a court ruling specifically on what happens if a disproportionate-assets case is investigated in breach of Section 17 — so I can't tell you how courts have treated that particular defect, only what the section itself requires.\n\nHow this cuts for and against you\n\nFor you:\n\nIf the investigating officer was below the required rank and had no Magistrate's order or State Government authorisation, that is a departure from Section 17's requirement.\nIf an arrest was made without a warrant by such an officer, that too falls outside what Section 17 permits.\nAgainst you:\n\nIf the officer held the required rank (DSP or above, outside metropolitan areas), Section 17 is satisfied regardless of other objections.\nIf the State Government had issued a general order authorising Inspector-rank officers, that also satisfies Section 17.\nWhat I can't tell from here: the rank of the officer who actually investigated, whether any Magistrate's order or State Government authorisation existed, and whether this defect was raised at the right stage.\n\nWhat you can do now\n\nCheck the rank of the officer who conducted the investigation, and the location (metropolitan or not), since the required rank differs.\nAsk for the Magistrate's order or the State Government's authorisation order, if any, that permitted the investigation.\nBring these specific documents to a criminal lawyer, since whether a Section 17 defect affects the case depends on when and how it is raised."
ANS3 = 'Yes — Section 17 of the Prevention of Corruption Act does require this, specifically for the investigating rank, not a separate "registration" step.\n\nWhat does Section 17 require?\n\nSection 17 of the Prevention of Corruption Act says that no police officer below the rank of Deputy Superintendent of Police (or equivalent) may investigate an offence under the Act without the order of a Metropolitan Magistrate or Magistrate of the first class. A further proviso says an offence under clause (b) of sub-section (1) of section 13 — which covers disproportionate assets — cannot be investigated without the order of a police officer not below the rank of Superintendent of Police. So for a disproportionate assets case, SP-level authorisation to investigate is built into Section 17 itself.\n\nThis exists so that corruption investigations, which can be used to harass public servants, are screened at a senior enough level before they go forward. The Supreme Court in State of Karnataka (from a wider search, not independently verified) v. T.N. Sudhakar Reddy (2025) (from a wider search, not independently verified) rejected the idea that the SP must first direct registration of an FIR and only afterward issue the Section 17 investigation order — it held that Section 17\'s only requirement is that the SP authorise a competent subordinate officer to investigate, not that registration and authorisation happen in a fixed sequence.\n\nHow this cuts for and against you\n\nFor you:\n\nIf the SP\'s authorisation was mechanical or showed no awareness of the allegations, State of Madhya Pradesh (from a wider search, not independently verified) v. Shri Ram Singh (2000) (from a wider search, not independently verified) noted that in an earlier case (Bhajan Lal) such an order was found non-compliant with Section 17.\nIf no SP-level order exists at all for the disproportionate assets allegation, that touches the specific proviso.\nAgainst you:\n\nIf an SP did authorise investigation, even informally, T.N. Sudhakar Reddy (2025) treats that as sufficient without a strict FIR-first sequence.\nCourts generally resist staying proceedings over such procedural points unless a failure of justice is shown.\nWhat I can\'t tell from here: whether an SP-level order exists in this case, what it says, and whether it specifically addresses the disproportionate assets allegation.\n\nWhat you can do now\n\nAsk for a copy of the SP\'s authorisation order, if one exists, to see what it actually records.\nCheck whether the order was made before or in connection with the disproportionate assets investigation specifically.\nBring these documents to a criminal lawyer experienced in Prevention of Corruption Act matters to assess next steps.'
ANS4 = 'The absence of a Section 17 order doesn\'t automatically wipe out a disproportionate assets case, but it does affect how the investigation can be challenged, and courts have treated this differently depending on the facts.\n\nWhat the law says about this\n\nSection 17 of the Prevention of Corruption Act, 1988 says an officer below the rank set out there cannot investigate a Section 13 offence (which covers disproportionate assets) without authorisation — and for the specific clause dealing with disproportionate assets, that authorisation must come from an officer not below the rank of Superintendent of Police. This rank requirement exists so that sensitive corruption investigations aren\'t launched casually by junior officers.\n\nIn State of Madhya Pradesh (from a wider search, not independently verified) v. Shri Ram Singh (2000) (from a wider search, not independently verified), the Supreme Court noted that in an earlier case (Bhajan Lal), the SP had authorised investigation "mechanically and in a very casual manner," without complying with Section 17 — but the Court also observed that even without the SP\'s authority, the investigating officer was in law authorised to investigate offences under Section 13 except for the clause needing SP-level approval. In State of Karnataka v. T.N. Sudhakar Reddy (2025) (from a wider search, not independently verified), the passage describes a High Court\'s four-step procedure under which the SP only becomes competent to authorise investigation after the FIR is registered — meaning the order\'s validity can turn on the sequence followed, not just its existence.\n\nHow this cuts for and against you\n\nFor you:\n\nIf the offence falls under the specific disproportionate-assets clause, the second proviso to Section 17 requires SP-level authorisation, and its complete absence is a real procedural gap.\nA missing or defective order can be raised before the trial court or in a quash petition, depending on the stage.\nAgainst you:\n\nCourts have, in some instances, held that absence of proper authorisation doesn\'t void the whole investigation outright, if other authority to investigate existed.\nWhether the order was required to exist before or after FIR registration may itself be disputed, per the Sudhakar Reddy passage.\nWhat I can\'t tell from here: which specific clause of Section 13 is invoked, the stage of your case (FIR, charge sheet, trial), and whether any order exists in a different form.\n\nWhat you can do right now\n\nAsk for a certified copy of the case diary or investigation record to check if any Section 17 order was passed, in whatever form.\nRaise the absence of authorisation as a specific ground before the trial court, citing the rank requirement.\nBring this point to a lawyer handling corruption-law matters, to assess whether it supports a quash petition at this stage.'


PC = "pc_act_1988"
SH = S.load()
os.environ["ACT_SHELF"] = "on"
s17 = SH["acts"][PC]["by_num"]["17"]["text"]
s17a = SH["acts"][PC]["by_num"]["17A"]["text"]
s13 = SH["acts"][PC]["by_num"]["13"]["text"]
s19 = SH["acts"][PC]["by_num"]["19"]["text"]

# ---------------------------------------------------------------- the switch
for v, want in ((None, True), ("", True), ("on", True), (' "ON" ', True), ("off", False), (" Off ", False), ("0", False), ("false", False), ("no", False), ("banana", True)):
    if v is None:
        os.environ.pop("SECTION_RULE", None)
    else:
        os.environ["SECTION_RULE"] = v
    check(R.enabled() is want, f"SECTION_RULE={v!r}: {'on' if want else 'off'}")
os.environ.pop("SECTION_RULE", None)

# ---------------------------------------------------------------- the provisos of a section
p17 = R.provisos(s17)
check(len(p17) == 2 and p17[0].startswith("Provided that if a police officer not below the rank of an Inspector of Police is authorised by the State Government") and p17[0].endswith("without a warrant:"),
      f"section 17 has two provisos; the first is the State Government's authorisation of an Inspector ({p17[0][:60]!r} ... {p17[0][-20:]!r})")
check(p17[1] == "Provided further that an offence referred to in [clause (b) of sub-section (1)] of section 13 shall not be investigated without the order of a police officer not below the rank of a Superintendent of Police.",
      f"...and the second is the Superintendent of Police's order for an offence under section 13(1)(b), word for word ({p17[1]!r})")
p17a = R.provisos(s17a)
check(len(p17a) == 2 and p17a[0].startswith("Provided that no such approval shall be necessary for cases involving arrest of a person on the spot") and p17a[1].endswith("by a further period of one month."),
      f"section 17A: two provisos, the closing bracket of the amended passage is not part of the second ({p17a[1][-30:]!r})")
check(not any("[Note" in p or p.endswith("]") for p in p17a), "...and the note India Code prints under it is not part of any proviso")
check(R.provisos(s13) == [] and R.provisos("") == [] and R.provisos(None) == [], "section 13 (explanations, no proviso), empty and None: no provisos")
syn = "5. Heading.\n(1) The rule.\nProvided that the first thing:\n(a) one;\n(b) two.\nProvided also that the second thing.\nExplanation.--A word means this.\n(2) Another rule.\nProvided further that the third thing.\n[Note: printed by India Code.]"
check(R.provisos(syn) == ["Provided that the first thing: (a) one; (b) two.", "Provided also that the second thing.", "Provided further that the third thing."],
      f"a proviso keeps its (a), (b) lines and stops at 'Explanation', at the next sub-section, at a note ({R.provisos(syn)})")
check(R.provisos("The court may, provided that it records reasons, grant bail.\nSecond line.") == [], "'provided that' inside a sentence is not a proviso")

# every proviso is an exact excerpt of its section, nothing is lost or merged: all nine Acts
def norm(t):
    return re.sub(r"\s+", " ", t).strip()


total_line = total_parsed = 0
bad = []
for aid, st in SH["acts"].items():
    if not st.get("ok"):
        continue
    for num, c in st["by_num"].items():
        t = c["text"]
        n_line = sum(1 for ln in t.split("\n") if re.match(r"^[\[(\s]*Provided\b(?:\s+(?:further|also))?\s+that\b", ln.strip(), re.I))
        ps = R.provisos(t)
        total_line += n_line
        total_parsed += len(ps)
        if len(ps) != n_line or not all(norm(p) in norm(t) for p in ps) or any("\nProvided" in p or "[Note" in p for p in ps):
            bad.append((aid, num))
check(not bad and total_line == total_parsed and total_line > 100, f"all nine Acts: {total_parsed} provisos parsed from {total_line} proviso lines, each an exact excerpt of its section ({bad[:3]})")

# ---------------------------------------------------------------- is a proviso set out?
check(R.provisos_covered("anything", 0) is True and R.provisos_covered("", 0) is True, "a section with no proviso is always covered")
check(R.provisos_covered("The first proviso lets the State authorise an Inspector. The second proviso needs an SP's order.", 2) is True, "'first proviso' and 'second proviso': covered")
check(R.provisos_covered("The provisos change this.", 2) is True and R.provisos_covered("There are two provisos.", 5) is True, "the plural 'provisos': covered")
check(R.provisos_covered("A further proviso says an offence under clause (b) needs an SP's order.", 2) is False, "only 'a further proviso' for two provisos: not covered (the owner's answer 3 never gave the first)")
check(R.provisos_covered("The second proviso needs an SP's order. The proviso before it lets the State act.", 2) is True and R.provisos_covered("The second proviso needs an SP's order.", 2) is False, "the first proviso is recognised as 'the proviso' / 'a proviso'; 'the second proviso' alone is not enough")
check(R.provisos_covered("The State Government can authorise an Inspector.", 2) is False and R.provisos_covered("", 1) is False and R.provisos_covered(None, 1) is False, "the provisos described without the word: not covered")
check(R.provisos_covered("It is provided that the State may act.", 1) is True and R.provisos_covered("The section provides that the State may act.", 1) is False and R.provisos_covered("The proviso lets the State act.", 1) is True, "one proviso: 'provided that' or 'proviso' is enough, 'provides' is not")
check(R.provisos_covered("The first proviso. The second proviso. The third proviso.", 6) is True and R.provisos_covered("The first proviso. The second proviso.", 6) is False, "for a section with many provisos the first three must be referred to (or the plural used)")
check(R.provisos_covered("Provided further that the State may act.", 2) is False and R.provisos_covered("Provided that it applies. Provided further that it ends.", 2) is True, "the proviso formula quoted: 'Provided that' is the first, 'Provided further that' the second")

# ---------------------------------------------------------------- the numbers an answer uses
check(S.section_numbers_in("Section 17A of the PC Act says X. Section 19 needs sanction.") == {"17A", "19"}, "section_numbers_in: 17A is 17A, not 17")
check(S.section_numbers_in("Sections 7, 13 and 17 apply; see also s. 8(2)(b) and u/s 19.") == {"7", "13", "17", "8", "19"}, "...lists, 's.', sub-clauses and 'u/s'")
check(S.section_numbers_in("Section 17 of the Prevention of Corruption Act, 1988 says") == {"17"} and S.section_numbers_in("") == set() and S.section_numbers_in(None) == set(), "...a plain mention; empty and None")
check(S.section_numbers_in("The rank of Superintendent applies, see clause 17 below.") == set(), "...a bare '17' that is not after the word section is not a section")
check(S.section_numbers_in("Section 17-A, Section 17 A and section 17\u2013A all mean 17A.") == {"17A"}, "...'17-A', '17 A' and '17\u2013A' in an answer are 17A, not 17")
check(S.section_numbers_in("Under Section 17 a police officer must act; Section 17 of the Act says so.") == {"17"}, "...but 'Section 17 a police officer' (lower-case article) is section 17")
check(S.section_numbers_in("Section 17 \u2013 A police officer below the rank cannot investigate. Section 17 - Persons authorised.") == {"17"}, "...and a spaced dash before a sentence that starts with 'A' ('Section 17 \u2013 A police officer ...') is section 17, not 17A")

# ---------------------------------------------------------------- a bare number is taken for the one shelf Act of the question
PM = "pmla_2002"
Q4 = "No section 17 order exists for this case of disproportionate assets"
check(S.named_sections(Q4, [PC]) == {} and S.named_sections("Does section 17 of the PC Act apply?", [PC]) == {PC: ["17"]}, "named_sections is as before: a bare number is not named, 'section 17 of the PC Act' is")
check(S.implied_sections(Q4, [PC]) == {PC: ["17"]}, f"the owner's turn 4: the bare 'section 17' is taken for the Prevention of Corruption Act ({S.implied_sections(Q4, [PC])})")
check(S.implied_sections("Does section 17 of the PC Act apply?", [PC]) == {}, "a number with an Act name next to it is not implied (it is named)")
check(S.implied_sections("Is section 17 of the BNS relevant?", [PC]) == {}, "'section 17 of the BNS': another code's number, not ours")
check(S.implied_sections("What does section 438 say about bail?", [PC]) == {}, "a number the Act does not have (the Act has no section 438): not implied")
check(S.implied_sections("Section 17 of the BNS is about X, and what about section 17 here?", [PC]) == {}, "the same number also put next to another code: which is meant is not guessed")
check(S.implied_sections(Q4, [PC, PM]) == {}, "section 17 exists in the PMLA as well: with both Acts drawn, not guessed")
check(S.implied_sections("Can bail be refused under section 45?", [PC, PM]) == {PM: ["45"]}, "section 45 exists only in the PMLA: with both drawn it is the PMLA's")
check(S.implied_sections("I was told sections 7, 13 and 17 apply to me.", [PC]) == {PC: ["7", "13", "17"]}, "a list of bare numbers: each is taken")
check(S.implied_sections("Is section 17A needed, and what about section 19?", [PC]) == {PC: ["17A", "19"]}, "a lettered number is taken as typed")
check(S.implied_sections("I am asking about section 17, NOT section 17 A", [PC]) == {PC: ["17"]}, "'section 17 A' (typed with a space) is read as 17, as before: the clause that follows tells the model not to put 17A in its place")
check(S.implied_sections("Does section 17 of the PC Act apply, and what about section 19?", [PC]) == {PC: ["19"]}, "one number named, the next bare: only the bare one is implied")
check(S.implied_sections("", [PC]) == {} and S.implied_sections(None, [PC]) == {} and S.implied_sections(Q4, []) == {} and S.implied_sections(Q4, ["no_such_act"]) == {}, "empty text, None, no Act, an unknown Act: {}")
os.environ["SECTION_RULE"] = "off"
check(S.implied_sections(Q4, [PC]) == {}, "SECTION_RULE=off: nothing implied")
os.environ.pop("SECTION_RULE")

# ---------------------------------------------------------------- the search: an implied section comes first, once
r = S.search(Q4, [{"id": PC}], embed_fn=like("PCACT", "17A"))
got = [(m["section_number"], m["retrieval"]) for m in r["matches"]]
check(got[0] == ("17", "implied") and ("17A", "meaning") in got and [g for g, _ in got].count("17") == 1, f"search: section 17 first as 'implied', 17A by meaning, 17 not twice ({got})")
check(r["info"]["per_act"][PC]["implied"] == ["17"] and r["info"]["per_act"][PC]["named"] == [], "...and the log record says so")
r = S.search("I was told sections 7, 13, 17 and 19 apply to me.", [{"id": PC}], embed_fn=like("PCACT", "8"))
check([m["section_number"] for m in r["matches"] if m["retrieval"] == "implied"] == ["7", "13", "17"] and S.MAX_NAMED == 3, "search: implied sections are capped at MAX_NAMED like named ones")
r = S.search("Does section 17 of the PC Act apply, and what about section 19?", [{"id": PC}], embed_fn=like("PCACT", "8"))
got = [(m["section_number"], m["retrieval"]) for m in r["matches"]]
check(got[:2] == [("17", "named"), ("19", "implied")], f"search: the named section first, then the implied one ({got[:3]})")
os.environ["SECTION_RULE"] = "off"
r = S.search(Q4, [{"id": PC}], embed_fn=like("PCACT", "17A"))
check(not any(m["retrieval"] == "implied" for m in r["matches"]) and "implied" not in r["info"]["per_act"][PC], "SECTION_RULE=off: the search is as before (no implied section, no new key in the log record)")
os.environ.pop("SECTION_RULE")

# held_state says which sections the person asked about
ACTS = [{"id": PC, "short": "Prevention of Corruption Act, 1988", "how": "named"}]
r = S.search(Q4, ACTS, embed_fn=like("PCACT", "17A"))
hs = S.held_state(r["matches"], ACTS)
check(hs[PC]["named"] == ["17"] and hs[PC]["state"] == "used", f"held_state: the section asked about is listed ({hs})")
r2 = S.search("What is the punishment for taking a bribe under the Prevention of Corruption Act?", ACTS, embed_fn=like("PCACT", "7"))
hs2 = S.held_state(r2["matches"], ACTS)
check("named" not in hs2[PC] and hs2[PC]["state"] == "used", f"...and a question that names no section has no 'named' ({hs2})")
os.environ["SECTION_RULE"] = "off"
check("named" not in S.held_state(r["matches"], ACTS)[PC], "SECTION_RULE=off: no 'named' key")
os.environ.pop("SECTION_RULE")
ctx = S.statute_context(r["matches"])
check(len(ctx) == 1 and "17" in ctx[0]["sections"], "an implied section also goes to the wider search's statute filter")

# ---------------------------------------------------------------- the prompt clause
pb = AD.prompt_block(ACTS, held=hs)
check("## The section the person asked about" in pb and "The person's question is about section 17 of the Prevention of Corruption Act, 1988 (it is in the material above)." in pb, "the clause names the section and the Act")
check("A section whose number differs only by a letter (for example 17A for 17) is a different provision" in pb and "say in one sentence, in your own words, how it differs from the one asked about" in pb, "...tells the model not to put 17A in the place of 17, and to say how they differ")
check("EVERY proviso and Explanation" in pb and "introduce each proviso as the section's first, second (and so on) proviso" in pb and "say which cases it applies to" in pb, "...asks for every proviso, numbered, and for the cases each applies to")
check(pb.startswith(AD.prompt_block(ACTS, held={PC: {"state": "used", "loaded_on": hs[PC]["loaded_on"]}})), "...it is added AFTER the block that existed before it, which is unchanged")
check("## The section the person asked about" not in AD.prompt_block(ACTS, held=hs2) and AD.prompt_block(ACTS, held=hs2) == AD.prompt_block(ACTS, held={PC: {"state": "used", "loaded_on": hs2[PC]["loaded_on"]}}),
      "a question that names no section: no clause, the block exactly as before")
two = {PC: {"state": "used", "loaded_on": "2026-10-17", "named": ["17", "19"]}}
check("is about sections 17 and 19 of the Prevention of Corruption Act, 1988 (they are in the material above)" in AD.prompt_block(ACTS, held=two), "two sections: 'sections 17 and 19 ... (they are in the material above)'")
one_a = {PC: {"state": "used", "loaded_on": "2026-10-17", "named": ["17A"]}}
check("(for example 17 for 17A)" in AD.prompt_block(ACTS, held=one_a), "asked about 17A: the example is 17 for 17A")
unused = {PC: {"state": "unused", "loaded_on": "2026-10-17", "named": ["17"]}}
check("## The section the person asked about" not in AD.prompt_block(ACTS, held=unused), "an Act whose text did not reach the answer gets no such clause")
MW = "muslim_women_act_2019"
ACTS_MW = [{"id": MW, "short": "Muslim Women (Protection of Rights on Marriage) Act, 2019", "how": "named"}]
rw = S.search("What does section 5 of the Muslim Women Act, 2019 say?", ACTS_MW, embed_fn=boom)
hw = S.held_state(rw["matches"], ACTS_MW)
check(hw[MW].get("whole") is True and hw[MW]["named"] == ["5"] and "## The section the person asked about" in AD.prompt_block(ACTS_MW, held=hw), "an Act handed over whole: the clause is there as well")
check("## Hard rules" not in AD._prompt_named([(ACTS[0], ["17"])]), "the clause is not a copy of the Hard rules block, and does not touch it")

# ---------------------------------------------------------------- the owner's conversation, turn by turn (CHAT_MODE builds the engine question)
T1 = "Can a disproportionate assets case under PC act be filed without section 17 approval?"
T2 = "I am asking about section 17, NOT section 17 A"
T3 = "Does section 17 require authorisation of a police officer not below the rank of SP to register a case of disproportionate assets?"
T4 = "No section 17 order exists for this case of disproportionate assets"
os.environ["CHAT_MODE"] = "fold"                                    # fold only: no rewrite call (the rewrite is replaced by a stub below for turn 4)
thread = []


def engine_question(turns, current):
    q, _ = W.question_for_engine(turns, current)
    return q


def explicit_after_drop(question):
    cur = CA._extract_current_message(question)
    expl = CA._explicit_section_matches(cur)
    return [(e["act"], e["section_number"]) for e in expl], [(e["act"], e["section_number"]) for e in CA._drop_sections_claimed_by_shelf(expl, question, cur)]


Q1e = engine_question([], T1)
before1, after1 = explicit_after_drop(Q1e)
check(before1 == [("BNS", "17")] and after1 == [], f"turn 1 (the Act is named next to the number): BNS 17 is read, then dropped as the Act's ({before1} -> {after1})")
thread.append({"q": T1, "answer": {"state": "single_match", "response_text": "x"}})
Q2e = engine_question(thread, T2)
cur2 = CA._extract_current_message(Q2e)
acts2 = CA._acts_named(Q2e)
check([a["id"] for a in acts2] == [PC] and S.named_sections(cur2, [PC]) == {} and S.implied_sections(cur2, [PC]) == {PC: ["17"]}, f"turn 2: the Act comes from the earlier message, the bare 'section 17' is taken for it ({S.implied_sections(cur2, [PC])})")
b2, a2 = explicit_after_drop(Q2e)
check(b2 == [("BNS", "17")] and a2 == [], f"turn 2: BNS 17 is dropped ({b2} -> {a2})")
thread.append({"q": T2, "answer": {"state": "single_match", "response_text": "x"}})
Q3e = engine_question(thread, T3)
b3, a3 = explicit_after_drop(Q3e)
check(b3 == [("BNS", "17")] and a3 == [], f"turn 3: BNS 17 is dropped ({b3} -> {a3})")
thread.append({"q": T3, "answer": {"state": "single_match", "response_text": "x"}})
fake = lambda prompt, current: ('{"follow_up": true, "standalone": "No order from a Superintendent of Police exists for this case of disproportionate assets."}', 0.0)
os.environ["CHAT_MODE"] = "on"
Q4e, rec = W.question_for_engine(thread, T4, call=fake)
os.environ["CHAT_MODE"] = "fold"
cur4 = CA._extract_current_message(Q4e)
b4, a4 = explicit_after_drop(Q4e)
check(rec["rewrite"] == "used" and b4 == [("BNS", "17")] and a4 == [], f"turn 4 (with the rewrite line in the current message): BNS 17 is dropped ({b4} -> {a4})")
check(S.implied_sections(cur4, [PC]) == {PC: ["17"]}, "turn 4: section 17 is the Act's")
os.environ["SECTION_RULE"] = "off"
b4o, a4o = explicit_after_drop(Q4e)
check(a4o == [("BNS", "17")], f"SECTION_RULE=off: BNS 17 stays in, as before this fix ({a4o})")
os.environ.pop("SECTION_RULE")
b5, a5 = explicit_after_drop(engine_question([], "Does section 17 of the BNS cover this, and is a PC Act case different?"))
check(a5 == [("BNS", "17")], f"a number put next to the BNS is the BNS's, whatever other Act the question names ({a5})")
b6, a6 = explicit_after_drop("I was arrested for a bribe case. What does section 45 of the BNS say?")
check(a6 == [("BNS", "45")], "no shelf Act in the question: nothing is dropped")
os.environ.pop("CHAT_MODE", None)

# ---------------------------------------------------------------- the notes, on the owner's four real answers
MS1 = S.search(T1, [{"id": PC}], embed_fn=like("PCACT", "17A"))["matches"]
MS4 = S.search(Q4, ACTS, embed_fn=like("PCACT", "17A"))["matches"]
check(any(m["section_number"] == "17" and m["retrieval"] == "named" for m in MS1) and any(m["section_number"] == "17A" and m["retrieval"] == "meaning" for m in MS1), "turn 1's material: section 17 named, 17A by meaning")
n1 = R.notes(ANS1, MS1)
check(len(n1) == 1 and n1[0]["kind"] == "not_mentioned" and n1[0]["section"] == "17" and n1[0]["texts"][0] == SH["acts"][PC]["by_num"]["17"]["text"].strip(),
      f"answer 1 (about 17A, never says 'section 17'): the note gives section 17 whole ({[(n['kind'], n['section']) for n in n1]})")
check("does not set that section out by its number" in n1[0]["lead"] and "Provided further that an offence referred to in" in n1[0]["texts"][0] and n1[0]["cut"] is False and n1[0]["source_url"], "...with its official words, second proviso included, a link and nothing cut")
n2 = R.notes(ANS2, MS1)
check(len(n2) == 1 and n2[0]["kind"] == "provisos" and len(n2[0]["provisos"]) == 2 and "Superintendent of Police." in n2[0]["provisos"][1] and n2[0]["texts"] == [SH["acts"][PC]["by_num"]["17"]["text"].strip()],
      f"answer 2 (no second proviso): the note gives the whole section, and lists its two provisos ({[(n['kind'], len(n['provisos'])) for n in n2]})")
check("has two provisos" in n2[0]["lead"] and "does not clearly set them out" in n2[0]["lead"] and "the whole section" in n2[0]["lead"], f"...in plain words ({n2[0]['lead']})")
n3 = R.notes(ANS3, MS1)
check(len(n3) == 1 and n3[0]["kind"] == "provisos", "answer 3 (a 'further proviso', never the first): the note gives the provisos")
n4 = R.notes(ANS4, MS4)
check(len(n4) == 1 and n4[0]["kind"] == "provisos" and n4[0]["section"] == "17", "answer 4 (the second proviso only): the note gives the provisos")
GOOD = ("Section 17 of the Prevention of Corruption Act, 1988 has a main rule and two provisos. The first proviso lets the State Government authorise an Inspector of Police to investigate without a Magistrate's order. "
        "The second proviso says that an offence under clause (b) of section 13(1), which is the disproportionate assets offence, cannot be investigated without the order of an officer not below the rank of Superintendent of Police. Section 17A is a different provision.")
ng = R.notes(GOOD, MS1)
check(len(ng) == 1 and ng[0]["kind"] == "official" and ng[0]["texts"] == [SH["acts"][PC]["by_num"]["17"]["text"].strip()] and "plain-language reading of this text" in ng[0]["lead"],
      "an answer that names section 17 and sets out its first and second provisos: the official text is STILL given, with the plain sentence that the explanation is a reading of it (owner's choice of 2026-10-20)")
check([n["kind"] for n in R.notes("Section 17 has provisos that matter for a disproportionate assets case.", MS1)] == ["official"], "'provisos' in the plural: kind 'official' (the test counts words, it does not read meaning)")
n13 = R.notes("Section 17A is about approval. Section 19 is about sanction.", S.search("Is section 13 of the PC Act the right section?", ACTS, embed_fn=like("PCACT", "13"))["matches"])
check(len(n13) == 1 and n13[0]["section"] == "13" and n13[0]["kind"] == "not_mentioned", "a named section the answer never mentions is noted whatever its length")
n13b = R.notes("Section 13 makes it criminal misconduct.", S.search("Is section 13 of the PC Act the right section?", ACTS, embed_fn=like("PCACT", "13"))["matches"])
check(len(n13b) == 1 and n13b[0]["kind"] == "official" and n13b[0]["provisos"] == [] and "Explanation 1" in n13b[0]["texts"][0], "section 13 has no proviso and the answer names it: its whole official text (Explanations included) is given, kind 'official'")
mm = [m for m in MS1 if m["retrieval"] == "meaning"]
check(R.notes("Nothing about any section.", mm) == [], "sections found by meaning are never noted: the person did not ask about them")
n19 = R.notes("Nothing.", S.search("What does section 19 of the PC Act say?", ACTS, embed_fn=like("PCACT", "19"))["matches"])
check(n19 and n19[0]["cut"] is False and n19[0]["texts"][0] == SH["acts"][PC]["by_num"]["19"]["text"].strip(), f"a long section (5,206 characters) is given whole ({len(n19[0]['texts'][0]) if n19 else None})")
jj2 = SH["acts"]["jj_act_2015"]["by_num"]["2"]
njj = R.notes("Nothing.", [dict(S._match(SH["acts"]["jj_act_2015"], jj2, "named", None))])
check(njj and njj[0]["cut"] is True and len(njj[0]["texts"][0]) <= R.OFFICIAL_CHARS and njj[0]["texts"][0] == jj2["text"].strip()[:len(njj[0]["texts"][0])], f"the longest section (15,359 characters) is cut at a line end and says so ({len(njj[0]['texts'][0]) if njj else None})")
three = S.search("I was told sections 7, 13 and 17 apply to me.", ACTS, embed_fn=like("PCACT", "8"))["matches"]
check(len(R.notes("Nothing.", three)) == R.MAX_NOTES == 2, "three named sections that the answer ignores: two notes, not three")
om = [dict(m, shelf=dict(m["shelf"], omitted=True)) for m in MS1 if m["retrieval"] == "named"]
check(R.notes("Nothing.", om) == [], "an omitted section has nothing to set out: no note")
os.environ["SECTION_RULE"] = "off"
check(R.notes(ANS1, MS1) == [], "SECTION_RULE=off: no notes")
os.environ.pop("SECTION_RULE")
check(R.notes("", MS1) == [] and R.notes(None, MS1) == [] and R.notes(ANS1, None) == [] and R.notes(ANS1, [None, 5, {}]) == [], "empty answer, None, junk matches: no note, no error")

# ---------------------------------------------------------------- end to end, with a stub model
sent = {}
REPLY = {"text": ""}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        sent["calls"] = sent.get("calls", 0) + 1
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=REPLY["text"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
CA.classify_scope = lambda q: ("in_scope", "arrest", None)
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "no_match"}
CA._fetch_pilot_related_judgments = lambda *a, **k: []
import answer_cache
answer_cache.get_cached = lambda m: None
answer_cache.record_candidate = lambda *a, **k: None


def ask(question, embed, reply):
    REPLY["text"] = reply
    sent.clear()
    S._embed_query = embed
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            res = CA._answer_question_inner(question)
    finally:
        S._embed_query = boom
    return res, buf.getvalue()


res, out = ask(Q4e, like("PCACT", "17A"), ANS4)
p = sent.get("prompt", "")
shelf = [(m["section_number"], m["retrieval"]) for m in res["matches"] if m.get("source") == "act_shelf"]
check(res["state"] == "single_match" and shelf[0] == ("17", "implied"), f"turn 4 end to end: section 17 of the Act reaches the answer as 'implied' ({shelf})")
check(not any(m.get("act") == "BNS" and m.get("section_number") == "17" for m in res["matches"]), "...and BNS section 17 does not")
check("[Prevention of Corruption Act, 1988 Section 17, Section/Para 17]" in p and "Provided further that an offence referred to in" in p, "the prompt holds section 17 with its second proviso")
check("## The section the person asked about" in p and "The person's question is about section 17 of the Prevention of Corruption Act, 1988" in p, "the prompt carries the clause")
check("## Hard rules (never break)" in p and "Use ONLY the legal information given below" in p and p.index("## Hard rules (never break)") < p.index("## The section the person asked about"), "the Hard rules block is still in the prompt, unchanged, and comes before the clause")
sn = res.get("section_note")
check(isinstance(sn, list) and len(sn) == 1 and sn[0]["kind"] == "provisos", f"the owner's answer 4 comes out with the whole section and the sentence about the provisos ({[(n['kind'], n['section']) for n in sn or []]})")
lines = [l for l in out.splitlines() if l.startswith("SECTION_NOTE ")]
check(len(lines) == 1 and json.loads(lines[0][len("SECTION_NOTE "):]) == {"sections": ["Prevention of Corruption Act, 1988 s.17: provisos"]} and "Superintendent" not in lines[0], "one SECTION_NOTE log line: Act, section, kind; never text")
res, out = ask(Q4e, like("PCACT", "17A"), GOOD)
check(res["state"] == "single_match" and [n["kind"] for n in res.get("section_note") or []] == ["official"] and "SECTION_NOTE" in out, "an answer that sets out both provisos: the official text all the same, kind 'official'")
os.environ["SECTION_RULE"] = "off"
res, out = ask(Q4e, like("PCACT", "17A"), ANS4)
p = sent.get("prompt", "")
check("## The section the person asked about" not in p and "section_note" not in res and any(m.get("act") == "BNS" and m.get("section_number") == "17" for m in res["matches"]),
      "SECTION_RULE=off: the prompt has no clause, there is no note, and BNS 17 is in the material, exactly as before")
os.environ.pop("SECTION_RULE")
res, out = ask(Q1e, like("PCACT", "17A"), ANS1)
check(res["state"] == "single_match" and len(res.get("section_note") or []) == 1 and res["section_note"][0]["kind"] == "not_mentioned", "turn 1 end to end with the owner's answer 1: the note gives section 17")
os.environ.pop("ACT_SHELF")
res, out = ask(Q1e, like("PCACT", "17A"), ANS1)
check("section_note" not in res and "SECTION_NOTE" not in out and not any(m.get("source") == "act_shelf" for m in res.get("matches") or []), "ACT_SHELF off (the default): no shelf, no note: nothing changes")
os.environ["ACT_SHELF"] = "on"
r_ref = CA._attach_section_note({"state": "no_match", "response_text": ANS1, "matches": MS1})
check("section_note" not in r_ref and CA._attach_section_note(None) is None and CA._attach_section_note({"state": "single_match"}) == {"state": "single_match"}, "a state with no answer, None, a result without text: untouched, no error")

# ---------------------------------------------------------------- the page
from streamlit.testing.v1 import AppTest
import whatsapp_formatter as WF

STUB = {"v": None}
CA.answer_question = lambda question, inline_domains=frozenset(), audience=None, channel=None: STUB["v"]


def page(result):
    STUB["v"] = result
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.text_area(key="text").set_value("Does section 17 of the PC Act apply?").run()
    [b for b in at.button if "Check my situation" in b.label][0].click().run()
    return at, [m.value for m in at.markdown]


bns = {"type": "statute", "act": "BNS", "section_number": "17", "text": "17. " + "General exceptions apply to every offence in this Sanhita. " * 30, "source": "semantic", "all_variants": {}}
reply = "The approval rule is in Section 19, which needs sanction before a court takes cognizance."
res_page = {"state": "single_match", "response_text": reply, "matches": MS1 + [bns], "situation_detected": False, "section_note": R.notes(reply, MS1)}
at, vals = page(res_page)
joined = "\n".join(vals)
check(not at.exception, f"page: renders (exception={at.exception})")
check("You asked about section 17 of the Prevention of Corruption Act, 1988. The answer above does not set that section out by its number" in joined, "page: the lead sentence of the note is shown")
check("Provided further that an offence referred to in [clause (b) of sub-section (1)] of section 13 shall not be investigated without the order of a police officer not below the rank of a Superintendent of Police." in joined,
      "page: the official words of section 17, second proviso included, are on the page")
ia = [i for i, v in enumerate(vals) if reply in v]
inn = [i for i, v in enumerate(vals) if "You asked about section 17 of the Prevention of Corruption Act" in v]
check(ia and inn and inn[0] > ia[0], f"page: the note stands UNDER the answer (answer at {ia[:1]}, note at {inn[:1]})")
src = [v for v in vals if v.startswith("**Prevention of Corruption Act, 1988 Section 17**") or "Prevention of Corruption Act, 1988 Section 17**" in v]
check(bool(src), "page: 'Read the source' lists section 17 although the answer never says 'section 17' (the person asked about it)")
full17 = SH["acts"][PC]["by_num"]["17"]["text"]
check(len(full17) > 900 and sum(1 for v in vals if "Superintendent of Police." in v and "r-mono" in v) >= 2, "page: ...and shows it whole (1,354 characters), not cut at 900: the second proviso is there too")
check(any("shortened here" in v for v in vals) is False, "page: a section that fits is not described as shortened")
at, vals = page({"state": "single_match", "response_text": "Section 17 of the BNS has nothing to do with this.", "matches": [bns], "situation_detected": False})
bns_blocks = [v for v in vals if "General exceptions apply to every offence" in v]
check(bns_blocks and all(len(re.sub(r"<[^>]+>", "", b)) < 1000 for b in bns_blocks), f"page: a BNS section is still cut at 900 characters ({[len(b) for b in bns_blocks]})")
at, vals = page(res_page)
at, vals = page({"state": "single_match", "response_text": reply, "matches": MS1, "situation_detected": False})
check(not at.exception and not any("The answer above does not set that section out" in v for v in vals), "page: with no section_note key nothing extra is drawn")
LOADED_LABEL = S.loaded_label(SH["acts"][PC]["loaded_on"])
at, vals = page({"state": "single_match", "response_text": ANS2, "matches": MS1, "situation_detected": False, "section_note": R.notes(ANS2, MS1)})
joined = "\n".join(vals)
check(not at.exception and "Section 17 of the Prevention of Corruption Act, 1988 has two provisos" in joined and "does not clearly set them out" in joined, "page: the note for answer 2 says the section has two provisos and the answer does not clearly set them out")
check("Provided that if a police officer not below the rank of an Inspector of Police" in joined and "Provided further that an offence referred to in [clause (b) of sub-section (1)] of section 13" in joined, "page: ...and gives both provisos in the official words")
check(f"Official text from India Code, loaded {LOADED_LABEL}; not yet read by our reviewer" in joined and "the whole Act on India Code" in joined, "page: ...with the date, 'not yet read by our reviewer' and a link to the Act")
at, vals = page({"state": "single_match", "response_text": ANS2, "matches": MS1, "situation_detected": False, "section_note": R.notes(ANS2, MS1), "audience": "lawyer"})
check(not at.exception and any("has two provisos" in v for v in vals), "page: the same note under a lawyer's answer")
cut_note = [{"act": "X", "section": "9", "kind": "not_mentioned", "lead": "L.", "texts": ["abc"], "cut": True, "loaded_on": None, "source_url": None}]
at, vals = page({"state": "single_match", "response_text": reply, "matches": [], "situation_detected": False, "section_note": cut_note})
check(not at.exception and any("shortened here" in v for v in vals) and not any("Official text from India Code, loaded" in v or "the whole Act on India Code" in v for v in vals), "page: a cut note says so; a missing date or link is simply left out")
at, vals = page({"state": "single_match", "response_text": reply, "matches": MS1, "situation_detected": False, "section_note": [None, 5, {"lead": 1, "texts": None}]})
check(not at.exception, "page: a malformed note is skipped, never an error on the page")
msgs = WF.format_answer_for_whatsapp(dict(res_page, act_notice=None))
check(isinstance(msgs, list) and msgs and not any("You asked about section 17" in m for m in msgs), "WhatsApp: ignores the key (not wired, by the owner's rule)")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
