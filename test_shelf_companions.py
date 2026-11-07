"""
test_shelf_companions.py -- SHELF_COMPANIONS (shelf_companions.py), the proviso note for sections the answer relies on although nobody named them (section_rule._relied_notes), and the prompt's "Every section you rely on"
block (act_directory._prompt_relied). All of it written 2026-11-07 after the owner's question "can an arrest in a disproportionate assets case be made without an enquiry?": the answer gave the main rule of section 17 of the
Prevention of Corruption Act and left out its second proviso (an offence under section 13(1)(b) needs the order of an officer not below Superintendent of Police), never mentioned section 17A, and no note appeared because the
person had not typed "section 17". Free and offline: no model, no network; the real Act shelf text of this checkout.
Run: python -X utf8 test_shelf_companions.py
"""
import contextlib
import io
import json
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ["ACT_SHELF"] = "on"
for v in ("SHELF_COMPANIONS", "SECTION_RULE", "SECTION_XREF", "EVIDENCE_COMPANIONS"):
    os.environ.pop(v, None)

import act_directory as AD
import act_shelf
import section_rule as R
import shelf_companions as C

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


SH = act_shelf.load()
PC = SH["acts"]["pc_act_1988"]


def match(num, how="meaning"):
    return act_shelf._match(PC, PC["by_num"][num], how, 0.3)


Q = "can an arrest in a disproportionate assets case be made without an enquiry?"
# the owner's answer of 2026-11-06 (the paragraphs about section 17, as written)
OWNER_ANSWER = (
    "Yes, an arrest in a disproportionate assets case can be made without a preliminary enquiry, provided the information already on record discloses a cognizable offence of criminal misconduct.\n\n"
    "What the law says\n\n"
    "Disproportionate assets fall under Section 13 of the Prevention of Corruption Act, 1988, which treats a public servant as guilty of criminal misconduct if he holds property disproportionate to his known income.\n\n"
    "Investigation itself has its own gatekeeping: Section 17 of the Prevention of Corruption Act requires that, outside specified cities, no officer below the rank of Deputy Superintendent of Police investigate such an "
    "offence or arrest without a warrant, unless authorised.\n\n"
    "What to keep in mind\n\n"
    "The rank and authorisation requirement in Section 17 of the Prevention of Corruption Act applies regardless of whether a preliminary enquiry was conducted.")

# ---------------------------------------------------------------- the companions
check(C.enabled(), "SHELF_COMPANIONS is on by default")
quiet = io.StringIO()
with contextlib.redirect_stdout(quiet):
    got = C.add(Q, [match("13")])
check([m["section_number"] for m in got] == ["17", "17A"] and all(m["retrieval"] == "companion" and m["source"] == "act_shelf" and m["companion"] is True for m in got),
      f"a PC Act section is in the material and the question is about an enquiry: sections 17 and 17A are added as companions ({[m['section_number'] for m in got]})")
check(got[0]["text"] == PC["by_num"]["17"]["text"] and got[1]["text"] == PC["by_num"]["17A"]["text"], "...with their whole official text from the shelf")
line = [l for l in quiet.getvalue().splitlines() if l.startswith("SHELF_COMPANIONS ")]
check(len(line) == 1 and json.loads(line[0][len("SHELF_COMPANIONS "):]) == {"added": ["PCACT s.17", "PCACT s.17A"]} and "Section" not in line[0], "...and one log line names them, with no text and no question")
have17 = [match("17")]
got = C.add(Q, have17)
check([m["section_number"] for m in got] == ["17A"] and have17[0]["companion"] is True, "section 17 is already there: only 17A is added, and the one that was there is marked")
both = [match("17"), match("17A")]
check(C.add(Q, both) == [] and all(m.get("companion") for m in both), "both are already there: nothing is added, both are marked")
check(C.add(Q, [{"source": "act_shelf", "act_key": "other_act", "section_number": "13"}]) == [] and C.add(Q, []) == [], "no section of the Prevention of Corruption Act in the material: nothing")
for q in ("What is the punishment for accepting a bribe?", "can a public servant be arrested", "what is criminal misconduct"):
    check(C.add(q, [match("13")]) == [], f"no word for an enquiry or approval in the question: nothing ({q!r})")
for q in ("Is prior approval needed to investigate a public servant?", "Can the police start an inquiry on a source information report?", "who must sanction the investigation", "is permission needed"):
    check([m["section_number"] for m in C.add(q, [match("13")])] == ["17", "17A"], f"a word for an enquiry, investigation, approval, sanction or permission: companions ({q!r})")
os.environ["SHELF_COMPANIONS"] = "off"
check(C.add(Q, [match("13")]) == [], "SHELF_COMPANIONS=off: nothing")
os.environ.pop("SHELF_COMPANIONS")
os.environ["ACT_SHELF"] = "off"
check(C.add(Q, [match("13")]) == [], "ACT_SHELF off: nothing")
os.environ["ACT_SHELF"] = "on"
check(C.add("", [match("13")]) == [] and C.add(None, [match("13")]) == [], "an empty question: nothing, no crash")

import chat_assistant as CA
with contextlib.redirect_stdout(io.StringIO()):
    joined = CA._companion_shelf_matches(Q, [match("13"), match("18")])
check([m["section_number"] for m in joined] == ["13", "18", "17", "17A"], f"the engine's hook puts the companions after what the shelf found ({[m['section_number'] for m in joined]})")
fold = "Earlier in this same conversation (the person's earlier messages only; your earlier answers are not repeated here):\n- The person asked: is prior approval needed?" + "\n\nNow the person says: what is the punishment for bribery?"
with contextlib.redirect_stdout(io.StringIO()):
    check([m["section_number"] for m in CA._companion_shelf_matches(fold, [match("13")])] == ["13"], "a word for an enquiry in an EARLIER message does not bring them: only the current message counts")

# ---------------------------------------------------------------- the proviso note for sections nobody named
MS = [match("17", "companion"), match("17A", "companion"), match("13"), match("18")]
for m in MS[:2]:
    m["companion"] = True
notes = R.notes(OWNER_ANSWER, MS)
kinds = [(n["kind"], n["section"]) for n in notes]
check(("provisos", "17") in kinds, f"the owner's answer: section 17, relied on, two provisos not set out: its whole text under a note ({kinds})")
n17 = next(n for n in notes if n["section"] == "17")
check(n17["relied"] is True and n17["texts"][0] == PC["by_num"]["17"]["text"].strip() and len(n17["provisos"]) == 2 and "Superintendent of Police" in n17["provisos"][1] and "Provided further that an offence referred to in" in n17["texts"][0],
      "...the whole official text, the second proviso included")
check("relies on section 17" in n17["lead"] and "two provisos" in n17["lead"] and "does not clearly set them out" in n17["lead"], f"...in plain words ({n17['lead']})")
n17a = next((n for n in notes if n["section"] == "17A"), None)
check(n17a is not None and n17a["kind"] == "companion" and "enquiry or an investigation" in n17a["lead"] and "does not mention it" in n17a["lead"] and "for a lawyer to say" in n17a["lead"] and n17a["texts"][0] == PC["by_num"]["17A"]["text"].strip(),
      "section 17A, never mentioned: a companion note with its official text, and a lead that says only that it is for a lawyer to say whether it applies")
check(all(n["section"] not in ("13", "18") for n in notes), "section 13 (no proviso) and section 18 (never mentioned) get no note")
check(len([n for n in notes if n.get("relied") is not None]) <= R.MAX_RELIED + R.MAX_NOTES, "the number of notes is limited")

covered = OWNER_ANSWER.replace("unless authorised.", "unless authorised. Section 17 has a first proviso (an Inspector the State Government has authorised may also investigate) and a second proviso: an offence under section 13(1)(b) needs "
                               "the order of a Superintendent of Police or above. Section 17A is a different provision: it requires previous approval for an enquiry or investigation relatable to an official decision.")
check(R.notes(covered, MS) == [], "an answer that sets out both provisos of section 17 and mentions 17A: no note at all")
elsewhere = OWNER_ANSWER + "\n\nOn section 13, note the second proviso of another section that is not this one."
check(any(n["section"] == "17" for n in R.notes(elsewhere, MS)), "a mention of 'second proviso' in a paragraph about ANOTHER section does not cover section 17")
only_first = OWNER_ANSWER.replace("unless authorised.", "unless authorised, under the first proviso of section 17.")
check(any(n["section"] == "17" for n in R.notes(only_first, MS)), "one proviso mentioned of two: still not covered")
plural = OWNER_ANSWER.replace("unless authorised.", "unless authorised. The provisos to Section 17 also matter.")
check(not any(n["section"] == "17" for n in R.notes(plural, MS)), "'the provisos' in the paragraph about the section counts as covering them (a rough test by words, as before)")
check(R.notes("", MS) == [] and R.notes(None, MS) == [], "no answer: no note")
os.environ["SECTION_RULE"] = "off"
check(R.notes(OWNER_ANSWER, MS) == [], "SECTION_RULE=off: no note")
os.environ.pop("SECTION_RULE")
named = [match("17", "named")]
nn = R.notes(OWNER_ANSWER, named + [match("13")])
check([(n["kind"], n["section"]) for n in nn] == [("provisos", "17")] and not nn[0].get("relied"), "a section the person NAMED keeps its own (older) note, once: no second note for it as 'relied'")
many = [match(n, "meaning") for n in ("19", "17", "20", "7", "8")]
big = "Section 19 of the Act, section 17, section 20, section 7 and section 8 all matter here."
check(len([n for n in R.notes(big, many) if n.get("relied")]) <= R.MAX_RELIED, "at most two further sections are noted")
check(R.notes(OWNER_ANSWER, [dict(match("17"), shelf={"omitted": True})]) == [], "an omitted section is never noted")

# ---------------------------------------------------------------- the prompt
ACTS = [{"id": "pc_act_1988", "short": "Prevention of Corruption Act", "name": "Prevention of Corruption Act, 1988"}]
held = {"pc_act_1988": {"state": "used", "loaded_on": SH["acts"]["pc_act_1988"]["loaded_on"]}}
pb = AD.prompt_block(ACTS, held=held)
check("## Every section you rely on" in pb and "whether or not the person named it" in pb and "EVERY proviso" in pb and "17 and 17A" in pb, "an Act whose text reached the answer: the prompt carries the rule for every section the answer relies on")
check(pb.index("## Act text in the material") < pb.index("## Every section you rely on"), "...after the block that says the Act's text is in the material")
held_named = {"pc_act_1988": dict(held["pc_act_1988"], named=["17"])}
check(AD.prompt_block(ACTS, held=held_named).startswith(pb), "a named section's block is added AFTER it, the block before it unchanged")
check("## Hard rules" not in pb, "the Hard rules block is not touched (the clause is outside it)")
unused = {"pc_act_1988": {"state": "unused", "loaded_on": "x"}}
check("## Every section you rely on" not in AD.prompt_block(ACTS, held=unused), "an Act with nothing handed over: no such rule")
os.environ["SECTION_RULE"] = "off"
check("## Every section you rely on" not in AD.prompt_block(ACTS, held=held), "SECTION_RULE=off: no such rule")
os.environ.pop("SECTION_RULE")

# ---------------------------------------------------------------- what the page and the download receive
import answer_view
view = answer_view.section_notes(notes)
check(len(view) == len(notes) and any("relies on section 17" in v["lead"] for v in view) and any(v["texts"] for v in view), "the page's and the download's view carries the new notes like the old ones")

print()
print(f"{len(FAILURES)} FAILED" if FAILURES else "ALL PASSED")
sys.exit(1 if FAILURES else 0)
