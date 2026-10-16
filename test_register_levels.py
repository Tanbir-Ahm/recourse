"""
test_register_levels.py -- the four levels of register matching on the site (2026-10-16): register_hooks.answer_notes(question=...), register_hooks.question_block(), the prompt block in
chat_assistant.generate_grounded_response, chat_assistant._attach_register_notes(result, question), the page and WhatsApp rendering. Real register bundle (overruled_register/), a stand-in model, no network,
no cost. Run: python -X utf8 test_register_levels.py
"""
import json
import os
import sys
import types

import chat_assistant as CA
import register_hooks as RH
import whatsapp_formatter as WF

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


os.environ.pop("REGISTER_HOOKS", None)
RH._STATE.clear()

Q_NAMED = ("The High Court gave my husband anticipatory bail only until the next hearing. His lawyer cites Salauddin Abdulsamad Shaikh v. State of Maharashtra (1996) to say it should end after a "
           "short fixed time. Is that correct?")
Q_NOYEAR = "Our lawyer cites Naresh Kumar Yadav v. Ravindra Kumar to ask that the bail be cancelled. Is that a good ground?"
Q_FIRST = "My lawyer cites Mohan Lal v. State for the appeal. Does it help?"
Q_PLAIN = "Can the police arrest me for cheating without a warrant?"
SILENT = "That is a debated question. Anticipatory bail is granted under Section 482 of the BNSS."

# --- answer_notes with the question
r = RH.answer_notes(SILENT, question=Q_NAMED)
check(len(r["notes"]) == 1 and r["notes"][0].startswith("Salauddin Abdulsamad Shaikh v. State of Maharashtra (1996) is reported as overruled by Sushila Aggarwal") and r["possible"] == [], "level 1: the question names the case with a year, the answer is silent -> a note")
r = RH.answer_notes(SILENT, question=Q_NOYEAR)
check(r["notes"] == [] and len(r["possible"]) == 1 and r["possible"][0].startswith("Possible match: the case you named may be Naresh Kumar Yadav v. Ravindra Kumar (2008)"), "level 2: both full names, no year -> 'Possible match'")
r = RH.answer_notes(SILENT, question=Q_FIRST)
check(len(r["possible"]) == 1 and r["possible"][0].startswith('Our register holds 4 decisions whose first party is "Mohan Lal"') and "Mohan Lal v. State of Punjab (2018)" in r["possible"][0], "level 3: 'Mohan Lal v. State' lists the register's four decisions with that first party")
r = RH.answer_notes(SILENT, question=Q_PLAIN)
check(r["notes"] == [] and r["possible"] == [], "level 4: a question that names no register case adds nothing")
r = RH.answer_notes("The witness Mohan Lal said so. State of Punjab v. Ram Singh was cited.", question="Mohan Lal was arrested. Is State of Punjab v. Ram Singh relevant?")
check(r["notes"] == [] and r["possible"] == [], "level 4: a bare name, and a first party of common words, add nothing")
check(RH.answer_notes(SILENT)["possible"] == [] and RH.answer_notes(SILENT, question=None)["notes"] == [], "without a question the old behaviour is unchanged")
check(RH.answer_notes("", question=Q_NAMED)["notes"] != [], "an empty or withheld answer still gets the note for the case the question names")

# --- the prompt block
b = RH.question_block(Q_NAMED)
check(b.startswith("\n\n## Overruled Register -- the person's own question names a case") and "REGISTER NOTE (not yet confirmed): Salauddin" in b and "OPENING paragraph" in b and "do not describe what that case held" in b, "the prompt block tells the model to say how the case was treated in its opening, without describing the overruling case's holding")
check("do not suggest that the person cite, raise or rely on the overruling case for any other point" in b and "Saying that the older case was overruled by it is fine" in b, "the prompt block also stops the model advising the person to rely on the overruling case for another point (situation exam run 3, S13)")
b2 = RH.question_block(Q_NOYEAR)
check("REGISTER POSSIBLE MATCH" in b2 and 'the question names "Naresh Kumar Yadav v. Ravindra Kumar"' in b2, "a case named without a year gets the POSSIBLE MATCH line")
check(RH.question_block(Q_FIRST) == "" and RH.question_block(Q_PLAIN) == "" and RH.question_block("") == "" and RH.question_block(None) == "", "a first party only, an unrelated question and bad input give no block")

sent = {}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Short answer.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
txt = CA.generate_grounded_response(Q_NAMED, "[BNSS Section 482]\nAnticipatory bail text.", matches=[])
check(txt and "the person's own question names a case on our register" in sent["prompt"] and sent["prompt"].index("Anticipatory bail text.") < sent["prompt"].index("REGISTER NOTE (not yet confirmed): Salauddin"), "generate_grounded_response puts the block after the library text")
sent.clear()
txt = CA.generate_grounded_response(Q_PLAIN, "[BNSS Section 35]\nArrest text.", matches=[])
check(txt and "the person's own question names a case on our register" not in sent["prompt"], "an unrelated question: nothing added to the prompt")
os.environ["REGISTER_HOOKS"] = "off"
sent.clear()
txt = CA.generate_grounded_response(Q_NAMED, "[BNSS Section 482]\nText.", matches=[])
check(txt and "the person's own question names a case on our register" not in sent["prompt"], "REGISTER_HOOKS=off: no block")
res_off = CA._attach_register_notes({"state": "single_match", "response_text": SILENT}, question=Q_NAMED)
check("register_notes" not in res_off and "register_possible" not in res_off and RH.answer_notes(SILENT, question=Q_NAMED) == {"notes": [], "possible": [], "not_checked": None, "review": []}, "REGISTER_HOOKS=off: no notes either")
os.environ.pop("REGISTER_HOOKS")

# --- the result
res = CA._attach_register_notes({"state": "single_match", "response_text": SILENT}, question=Q_NAMED)
check(len(res.get("register_notes", [])) == 1 and "register_possible" not in res, "_attach_register_notes(result, question): level 1 goes to register_notes")
res = CA._attach_register_notes({"state": "single_match", "response_text": SILENT}, question=Q_NOYEAR)
check("register_notes" not in res and len(res.get("register_possible", [])) == 1, "level 2 goes to register_possible")
res = CA._attach_register_notes({"state": "single_match", "response_text": SILENT}, question=Q_FIRST)
check(len(res.get("register_possible", [])) == 1 and "Mohan Lal" in res["register_possible"][0], "level 3 goes to register_possible")
res = CA._attach_register_notes({"state": "single_match", "response_text": SILENT})
check("register_notes" not in res and "register_possible" not in res, "called without a question it behaves as before")
res = CA._attach_register_notes({"state": "no_match", "response_text": SILENT}, question=Q_NAMED)
check("register_notes" not in res, "a non-answer state is left alone")
check(CA._attach_register_notes("not a dict", question=Q_NAMED) == "not a dict", "bad input does not raise")

# --- rendering
src = open("recourse_app.py", encoding="utf-8").read()
check('reg_possible = result.get("register_possible")' in src and "for n in reg_possible or []" in src, "the page renders register_possible in the currency-notes box")
wsrc = open("whatsapp_formatter.py", encoding="utf-8").read()
check('result.get("register_possible")' in wsrc, "the WhatsApp message carries register_possible")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
