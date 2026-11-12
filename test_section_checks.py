"""test_section_checks.py -- section_checks.py: a word attributed to a section that its text lacks (borrowed from another section of the material), and an argument from what the material does not contain.
The first positive case is the sentence of the staging answer of 2026-11-12 (Motor Vehicles Act section 182 described with 'fraud or misrepresentation', which are the words of section 19(1)(e)). Offline and free.
Run: python -X utf8 test_section_checks.py"""
import json
import os
import sys
import types

import section_checks as SC

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def shelf(nums, key="mv_act_1988", disp="Motor Vehicles Act, 1988"):
    c = {str(y["section_number"]): y for y in json.load(open(os.path.join(HERE, "act_shelf", f"{key}.json"), encoding="utf-8"))}
    return [{"type": "statute", "act": c[n]["act"], "act_display": disp, "act_key": key, "section_number": n, "title": c[n]["title"], "text": c[n]["text"]} for n in nums]


M = shelf(["20", "182", "19", "23", "205"])
Q = "The challan also records that his driving licence had expired two weeks before the checkpoint."
bad = "Section 182(1) of the Motor Vehicles Act penalises a person who, being disqualified under the Act, drives, or who obtains a licence by fraud or misrepresentation, or without disclosing a prior endorsement."
g = SC.section_gloss(bad, M, Q)
check(len(g) == 1 and g[0]["section"] == "182" and g[0]["words"] == ["fraud", "misrepresentation"] and g[0]["borrowed_from"] == ["MVACT 19"], f"s.182 described with the words of s.19(1)(e) is reported ({g})")
good = "Section 182(1) of the Motor Vehicles Act penalises a person who, being disqualified under the Act, drives, or who applies for or obtains a driving licence without disclosing an endorsement."
check(SC.section_gloss(good, M, Q) == [], "the same sentence in the section's own words: nothing")
check(SC.section_gloss("Section 20(5) lets the appellate court set aside or vary a disqualification order.", M, Q) == [], "one borrowed word ('appellate') is a paraphrase, not reported")
check(SC.section_gloss("The risk is that Section 182 covers fraud and misrepresentation in getting a licence.", M, Q) == [], "a sentence that does not begin 'Section N verb' is not checked")
check(SC.section_gloss("Section 182 punishes fraud, and section 19 covers misrepresentation.", M, Q) == [], "a sentence naming two sections is not checked")
check(SC.section_gloss(bad, M, "He obtained the licence by fraud or misrepresentation, the police say.") == [], "words that are in the person's own question are not reported")
check(SC.section_gloss(bad, [m for m in M if m["section_number"] != "19"], Q) == [], "no other section of the material has the words: nothing")
check(SC.section_gloss("Section 185 of the Motor Vehicles Act supports a charge and the matter is shown.", shelf(["185", "205"]), "") == [], "discourse words ('supports', 'shown') are never a sign")
check(SC.section_gloss(bad, [], Q) == [] and SC.section_gloss("", M, Q) == [] and SC.section_gloss(bad, None, Q) == [], "no material, no answer: nothing, no error")
# two Acts with the same section number: the Act the sentence names is meant; when it names none and there are two, nothing is claimed
both = shelf(["182", "19"]) + [{"type": "statute", "act": "BNS", "act_display": "Bharatiya Nyaya Sanhita", "section_number": "182", "title": "t", "text": "A different section about public servants."}]
check(len(SC.section_gloss(bad, both, Q)) == 1 and SC.section_gloss(bad.replace("of the Motor Vehicles Act ", ""), both, Q) == [], "same number in two Acts: the named Act is used, an unnamed one is left alone")

ab = "That no Motor Vehicles Act section in the material penalises mere non-renewal of a licence, so the expired-licence fact alone should not be treated as a further substantive offence on these facts."
check(SC.absence_arguments(ab) == [ab], "an argument from absence is found")
check(SC.absence_arguments("The material does not show a section that penalises non-renewal; this needs to be checked on India Code.") == [], "a plain report of the gap is left alone")
check(SC.absence_arguments("I do not have information in the material on any other provision, so no further charge can be stated from the material.") == [], "'so ... cannot be stated' is a gap report, left alone")
check(SC.absence_arguments("**Bottom line**\nOne.\n**Gaps and checks**\n" + ab) == [], "the Gaps and checks part is not scanned")

n = SC.notices(g, [ab])
check(len(n) == 2 and "“fraud”" in n[0] and "section 182" in n[0] and "MVACT 19" in n[0] and "does not show that none exists" in n[1], "the notices say where the words are and that absence does not prove absence")

# mode: follows the grounding mode unless SECTION_CHECKS is set
import grounding_checks as GC
os.environ.pop("SECTION_CHECKS", None)
os.environ["GROUNDING_CHECKS"] = "warn"; check(SC.mode() == "warn", "GROUNDING_CHECKS=warn: warn")
os.environ["GROUNDING_CHECKS"] = "log"; check(SC.mode() == "log", "GROUNDING_CHECKS=log: log")
os.environ["GROUNDING_CHECKS"] = "off"; check(SC.mode() == "off", "GROUNDING_CHECKS=off: off")
os.environ["SECTION_CHECKS"] = "off"; os.environ["GROUNDING_CHECKS"] = "warn"; check(SC.mode() == "off", "SECTION_CHECKS=off wins")
os.environ.pop("SECTION_CHECKS", None)

# the engine: a finished answer with a borrowed description leaves a log line and, in warn mode, a notice
import chat_assistant as CA
os.environ["GROUNDING_CHECKS"] = "warn"
TEXT = {"t": bad + " It is a different wrong from simple non-renewal."}


class _Msgs:
    def create(self, **kw):
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=TEXT["t"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
import contextlib
import io
buf = io.StringIO()
GC.reset_notes()
with contextlib.redirect_stdout(buf):
    out = CA.generate_grounded_response(Q, "\n".join(m["text"] for m in M), matches=M)
notes = GC.pop_notes()
check(out is not None and "SECTION_CHECKS" in buf.getvalue() and any("section 182" in x and "fraud" in x for x in notes), "engine: SECTION_CHECKS log line and the notice (warn mode)")
os.environ["SECTION_CHECKS"] = "off"
buf = io.StringIO(); GC.reset_notes()
with contextlib.redirect_stdout(buf):
    CA.generate_grounded_response(Q, "\n".join(m["text"] for m in M), matches=M)
check("SECTION_CHECKS" not in buf.getvalue() and not GC.pop_notes(), "engine: switched off, nothing")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
