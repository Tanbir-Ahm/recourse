"""
test_case_file.py -- the case file of a conversation (case_file.py, web_chat fold / engine_case_file, carry_forward.cases_from_turns, chat_assistant hooks; owner's go 2026-11-09). Free: no network, no model, no database.
Proves: the facts are the person's own sentences copied word for word (questions and requests are not facts); a deleted sentence is not taken again; an edited line stays edited; a tapped answer cannot be re-worded;
the engine's question carries the facts and the earlier QUESTIONS (never our answers); a follow-up is searched on the new message plus the facts while the question string stays the person's; the sections and library
judgments an answer named are offered again; the age card appears for a case that mentions a sexual offence and says nothing of the victim's age, not for a definition question or when the words already say a child;
a guess by the Haiku pass no longer hands over POCSO, a tapped 'under 18' does; the switches off change nothing.
Run: python -X utf8 test_case_file.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for v in ("CASE_FILE", "AGE_CARD", "CHAT_MODE"):
    os.environ.pop(v, None)

import case_file as C
import carry_forward as CARRY
import web_chat as W

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


Q1 = ("My client was arrested on the charges that he was recording a sexual molestation case. The prime accused was arrested on the charges of rape. My client was arrested as the said video was phone on his phone "
      "and was widely shared, and he was apparently present at the crime spot")
FU = "what are the other sections my client can be charged with? and how can i counter them? give detailed explanations"

# ------------------------------------------------------------ 1. the facts are the person's sentences
facts, asks = C.split_message(Q1)
check(len(facts) == 3 and asks == [] and all(f in Q1 for f in facts), f"a first message of three statements gives three facts, each a word-for-word piece of it ({len(facts)})")
f2, a2 = C.split_message(FU)
check(f2 == [] and len(a2) == 3, "a follow-up that only asks gives no fact")
f3, a3 = C.split_message("Mr. A. K. Das was arrested on 3 May. what can he do? please advise. he is in custody since then.")
check(f3 == ["Mr. A. K. Das was arrested on 3 May.", "he is in custody since then."] and a3 == ["what can he do?", "please advise."], f"abbreviations do not split a sentence; lower-case typing is split at the full stop ({f3}, {a3})")
check(C.split_message("ok")[0] == [] and C.split_message("")[0] == [] and C.split_message(None)[0] == [], "very short or empty text gives no fact")

cf = C.add_from_message(None, Q1)
check([f["kind"] for f in cf["facts"]] == ["typed"] * 3 and len({f["id"] for f in cf["facts"]}) == 3, "three typed facts with their own ids")
cf2 = C.add_from_message(cf, Q1 + ". He has been in custody for ten days.")
check(len(cf2["facts"]) == 4 and cf2["facts"][3]["text"] == "He has been in custody for ten days.", "a repeated sentence is not added twice; a new one is")
check(C.add_from_message(cf, FU) == cf, "a message of questions changes nothing")

# ------------------------------------------------------------ 2. edit, remove, add, tapped answer
ids = [f["id"] for f in cf["facts"]]
edited = C.apply_edit(cf, [{"id": ids[0], "text": "My client was arrested for recording a clip."}, {"id": ids[2], "text": cf["facts"][2]["text"]}, {"id": None, "text": "The FIR was lodged on 2 May."}])
kinds = [(f["kind"], f["text"][:20]) for f in edited["facts"]]
check([k for k, _ in kinds] == ["edited", "typed", "added"], f"an edited line is 'edited', an untouched one stays, a new one is 'added' ({kinds})")
check(len(edited["removed"]) >= 1, "the removed sentence is remembered")
again = C.add_from_message(edited, Q1)
check(len(again["facts"]) == 3 and all("prime accused was arrested" not in f["text"] for f in again["facts"]), "a sentence the person removed is not taken from their messages again")
check(len([f for f in again["facts"] if f["kind"] == "edited"]) == 1 and not any(f["text"].startswith("My client was arrested on the charges") for f in again["facts"]), "...and a sentence they edited is not added again in its old form")
check(C.apply_edit(cf, [{"id": ids[0], "text": "   "}])["facts"] == [], "a line emptied is removed")
n1 = C.apply_edit(cf, [{"id": ids[1], "text": cf["facts"][1]["text"]}, {"id": "abc123xyz", "text": "He was produced before the Magistrate on 3 May."}])
n2 = C.apply_edit(n1, [{"id": ids[1], "text": cf["facts"][1]["text"]}, {"id": "abc123xyz", "text": "He was produced before the Magistrate on 3 May."}])
check([f["id"] for f in n1["facts"]] == [ids[1], "abc123xyz"] and [f["id"] for f in n2["facts"]] == [ids[1], "abc123xyz"] and len(n2["facts"]) == 2, "a line the page has just written keeps the id the page gave it, so saving twice makes one line")
check(len(C.apply_edit(None, [{"id": None, "text": "x" * 900}])["facts"][0]["text"]) == C.MAX_FACT_CHARS, "a line is cut to the length limit")
check(len(C.apply_edit(None, [{"id": None, "text": f"line number {i} is here"} for i in range(80)])["facts"]) == C.MAX_FACTS, "the list is limited")

t = C.set_answer(cf, "victim_age", "minor")
b = [f for f in t["facts"] if f.get("key") == "victim_age"]
check(len(b) == 1 and b[0]["kind"] == "button" and b[0]["text"] == "The victim is under 18 years old." and C.victim_minor(t) is True, "a tapped answer is a fixed-text fact")
t2 = C.apply_edit(t, [{"id": f["id"], "text": "The victim is 30 years old." if f["kind"] == "button" else f["text"]} for f in t["facts"]])
check(C.victim_minor(t2) is True and [f for f in t2["facts"] if f["kind"] == "button"][0]["text"] == "The victim is under 18 years old.", "the text of a tapped answer cannot be re-worded")
t3 = C.apply_edit(t, [{"id": f["id"], "text": f["text"]} for f in t["facts"] if f["kind"] != "button"])
check(C.victim_minor(t3) is None and C.answer_of(t3) is None, "a tapped answer can be removed (the card may come back)")
check(C.victim_minor(C.set_answer(t, "victim_age", "adult")) is False and C.victim_minor(C.set_answer(t, "victim_age", "unknown")) is None and len([f for f in C.set_answer(t, "victim_age", "adult")["facts"] if f.get("key")]) == 1, "a new tap replaces the old one")
try:
    C.set_answer(cf, "victim_age", "x")
    ok = False
except ValueError:
    ok = True
check(ok, "an unknown answer is refused")

# ------------------------------------------------------------ 3. the fold and the search text
os.environ["CASE_FILE"] = "on"
lines = C.fold_lines(cf)
check(lines[0] == C.FACTS_HEADER and len(lines) == 4 and all(l.startswith("- ") for l in lines[1:]), "the facts fold into lines under a header that says they are the person's words")
check(C.fold_lines(C.new_file()) == [], "an empty file folds to nothing")
turns = [{"q": Q1, "answer": {"state": "single_match", "response_text": "Section 77 of the BNS ... OUR ANSWER TEXT", "matches": []}}]
q, info = W.question_for_engine(turns, FU, case_file=cf)
check(q.count(W.MARKER) == 1 and q.endswith(W.MARKER + FU) and C.FACTS_HEADER in q and "present at the crime spot" in q and "OUR ANSWER TEXT" not in q, "the follow-up carries the facts and no answer of ours")
check("- The person asked:" not in q or "what are" not in q.split(W.MARKER)[0], "...and the current question is not folded twice")
check(info["facts"] == 3 and info["folded"] == 0, f"the log record counts facts and earlier questions ({info})")
q_off_file, _ = W.question_for_engine(turns, FU, case_file=None)
check(C.FACTS_HEADER not in q_off_file and "The person asked: " + Q1[:30] in q_off_file, "without a file the fold is today's: the earlier messages")
os.environ["CASE_FILE"] = "off"
q_sw, _ = W.question_for_engine(turns, FU, case_file=cf)
check(C.FACTS_HEADER not in q_sw and "The person asked: " + Q1[:30] in q_sw, "CASE_FILE off: exactly today's fold, even when a file is passed")
os.environ["CASE_FILE"] = "on"

turns2 = turns + [{"q": "Is bail possible?", "answer": {"state": "single_match", "response_text": "x", "matches": []}}]
q2, i2 = W.question_for_engine(turns2, FU, case_file=cf)
check("- The person asked: Is bail possible?" in q2 and "- The person asked: " + Q1[:20] not in q2, "the person's earlier QUESTIONS stay, as 'asked' lines, while earlier statements move into the facts")

hint = C.search_hint(cf)
check("recording a sexual molestation case" in hint and len(hint) <= C.HINT_CHARS and C.search_hint(t).count("under 18") == 0, "the search text is the facts (a tapped answer is not a search word)")
ecf = W.engine_case_file(cf, {"turn": 2, "rewrite": "dropped_guard:number_not_in_person_messages", "carry": []}, turns, FU)
check(ecf["search_hint"] == hint and ecf["victim_minor"] is None and ecf["age_gate"] is False and ecf["delta"] is None, f"a follow-up gets the facts as a search text ({ecf and sorted(ecf)})")
check(W.engine_case_file(cf, {"turn": 1, "rewrite": "first", "carry": []}, [], Q1)["search_hint"] is None, "the first question gets none (its own words are the facts)")
check(W.engine_case_file(cf, {"turn": 2, "rewrite": "new_topic", "carry": []}, turns, "My neighbour has stolen my goat and refuses to return it, what do I do?")["search_hint"] is None, "a new topic gets none")
check(W.engine_case_file(cf, {"turn": 2, "rewrite": "off", "carry": []}, turns, FU)["search_hint"] == hint, "no rewrite was made: a later question counts as a follow-up")
os.environ["CASE_FILE"] = "off"
check(W.engine_case_file(cf, {"turn": 2, "rewrite": "used", "carry": []}, turns, FU) is None, "CASE_FILE off: nothing is passed to the engine")
os.environ["CASE_FILE"] = "on"
check(W.engine_case_file(t, {"turn": 2, "rewrite": "used", "carry": []}, turns, FU, intent="age_minor")["delta"] == "pocso" and W.engine_case_file(cf, {"turn": 2, "rewrite": "used", "carry": []}, turns, FU, intent="age_minor")["delta"] is None,
      "the POCSO delta needs the tapped 'under 18' in the file")

# ------------------------------------------------------------ 4. what the earlier answers relied on
A1 = {"state": "single_match", "response_text": "Section 77 of the BNS and Section 35 of the BNSS apply. In Prabir Purkayastha v State (NCT of Delhi) the Court held that grounds must be written.",
      "matches": [{"type": "statute", "act": "BNS", "section_number": "77", "text": "t"}, {"type": "statute", "act": "BNSS", "section_number": "35", "text": "t"},
                  {"type": "judgment", "case_name": "Prabir Purkayastha v State (NCT of Delhi)", "paragraph_number": "30", "text": "the passage", "citation": "2024 INSC 414"},
                  {"type": "judgment", "case_name": "Never Named v. Anyone", "paragraph_number": "2", "text": "other passage"}]}
cs = CARRY.cases_from_turns([{"q": Q1, "answer": A1}])
check(len(cs) == 1 and cs[0]["case_name"].startswith("Prabir") and cs[0]["retrieval"] == "carried" and cs[0]["text"] == "the passage", f"a library judgment the answer NAMED is offered again, as the passage it first saw ({[c.get('case_name') for c in cs]})")
r = CARRY.relied_on([{"q": Q1, "answer": A1}])
check([(s["act"], s["section"]) for s in r["sections"]] == [("BNS", "77"), ("BNSS", "35")] and [c["name"] for c in r["cases"]] == ["Prabir Purkayastha v State (NCT of Delhi)"], f"the panel's 'relied on' list ({r})")
check(CARRY.cases_from_turns([{"q": "x", "answer": {"state": "no_match"}}]) == [] and CARRY.cases_from_turns(None) == [], "a refusal or nothing: nothing")

# ------------------------------------------------------------ 5. the age card
os.environ["AGE_CARD"] = "on"
card = C.card_for(cf, Q1)
check(card and card["key"] == "victim_age" and [o["value"] for o in card["options"]] == ["minor", "adult", "unknown"], "a case that mentions a sexual offence and says nothing of the victim's age gets the card")
check(C.card_for(C.set_answer(cf, "victim_age", "adult"), Q1) is None and C.card_for(C.set_answer(cf, "victim_age", "unknown"), Q1) is None, "...not once it has been answered")
check(C.card_for(None, "What is the punishment for rape under the BNS?") is None, "not for a definition question (no case context)")
check(C.card_for(None, "My client was arrested for stealing a bicycle and wants bail.") is None, "not for a case without a sexual offence")
check(C.card_for(None, "My client was arrested for raping a minor girl of 15.") is None and C.card_for(None, "He was booked under POCSO for molesting a child.") is None, "not when the words already say the victim is a child")
check(C.card_for(None, "My son, who is 16, was arrested for rape of a woman.") is not None, "a young ACCUSED does not hide the card")
os.environ["AGE_CARD"] = "off"
check(C.card_for(cf, Q1) is None, "AGE_CARD off: no card")
os.environ["CASE_FILE"] = "off"
os.environ["AGE_CARD"] = "on"
check(C.card_for(cf, Q1) is None and not C.age_card_enabled(), "AGE_CARD needs CASE_FILE")
os.environ["CASE_FILE"] = "on"

# ------------------------------------------------------------ 6. the engine hooks
import chat_assistant as CA

CA._ACTS_CACHE.value = None
os.environ["AGE_CARD"] = "on"
Q = "My client was arrested for recording a clip of a sexual assault on his phone."
POCSO = {"id": "pocso_act_2012", "short": "POCSO", "how": "likely"}
IT = {"id": "it_act_2000", "short": "IT Act", "how": "likely"}


def with_core(acts, ai_ids, arg):
    saved = CA._acts_named_core
    CA._acts_named_core = lambda q: (setattr(CA._ACTS_CACHE, "ai", (q, set(ai_ids))), list(acts))[1]
    CA._CASE.arg = arg
    try:
        return [a["id"] for a in CA._acts_named(Q)]
    finally:
        CA._acts_named_core = saved
        CA._CASE.arg = None


check(with_core([POCSO, IT], {"pocso_act_2012", "it_act_2000"}, {"age_gate": True, "victim_minor": None}) == ["it_act_2000"], "AGE_CARD on: POCSO named only by the Haiku pass is dropped (the IT Act stays)")
check(with_core([POCSO, IT], {"pocso_act_2012"}, {"age_gate": False, "victim_minor": None}) == ["pocso_act_2012", "it_act_2000"], "gate off: unchanged")
check(with_core([POCSO], set(), {"age_gate": True, "victim_minor": None}) == ["pocso_act_2012"], "POCSO found by the word pass or by name is kept")
check(with_core([IT], set(), {"age_gate": True, "victim_minor": True}) == ["pocso_act_2012", "it_act_2000"], "a tapped 'under 18' hands POCSO over")
check(with_core([POCSO, IT], set(), {"age_gate": True, "victim_minor": False}) == ["it_act_2000"], "a tapped '18 or over' drops a POCSO that was only a likeness")
check(with_core([POCSO, IT], {"pocso_act_2012"}, None) == ["pocso_act_2012", "it_act_2000"], "no case file: unchanged")
CA._CASE.arg = {"search_hint": "recording a sexual molestation case"}
check(CA._hinted("what else?") == "what else?\nrecording a sexual molestation case" and CA._hinted("") == "", "the search text of a follow-up = the new message + the facts")
CA._CASE.arg = None
check(CA._hinted("what else?") == "what else?", "no case file: the search text is the message")
CA._CASE.arg = {"delta": "pocso"}
check("under 18" in CA._case_delta_block() and "Keep the whole answer short" in CA._case_delta_block(), "the delta clause asks for what changes, briefly")
CA._CASE.arg = {"delta": None}
check(CA._case_delta_block() == "", "no clause for an ordinary turn")
CA._CASE.arg = None

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
