"""
test_register_hooks.py -- the Overruled Register hooks (register_hooks.py + the three call sites in chat_assistant.py / recourse_app.py).
Fully offline and free: no API calls, nothing written. Run: python -X utf8 test_register_hooks.py
"""
import os
import sys

import chat_assistant as CA
import register_hooks as RH

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


os.environ.pop("REGISTER_HOOKS", None)
OLD = {"case_name": "Raja Ram Verma v. State of U.P. and Others", "year": 1968, "text": "old holding", "paragraph_number": "5"}
CAND = {"case_name": "Mohan Lal v State of Punjab", "citation": "(2018) 17 SCC 627", "text": "x", "paragraph_number": "7"}
FINE = {"case_name": "Arnesh Kumar v State of Bihar", "citation": "(2014) 8 SCC 273", "text": "y", "paragraph_number": "9"}
STATUTE = {"act": "BNS", "section_number": "318", "text": "cheating"}

# lock (a): retrieval
out = RH.demote_matches([OLD, CAND, FINE, STATUTE])
check([m.get("case_name") or m.get("section_number") for m in out][-1] == OLD["case_name"], "a firm register case goes to the end of the list")
check(OLD.get("register_badge") and CAND.get("register_badge"), "firm and candidate rows both carry a badge")
check(out[0] is CAND and "register_badge" not in FINE, "a candidate row is badged but not demoted; an unlisted case is untouched")
check(RH.demote_matches(None) is None, "bad input is returned as it came (fail-open)")

# lock (b): prompt
text = CA.format_retrieved_text_for_prompt([dict(OLD), dict(CAND), dict(FINE)])
check("REGISTER FACT" in text and "Raja Ram Verma" in text, "a firm row puts a REGISTER FACT line in the prompt")
check("REGISTER NOTE (not yet confirmed)" in text, "a candidate row puts a 'not yet confirmed' line in the prompt")
check(text.count("[Overruled Register") == 2, "an unlisted case adds no register block")
check(text.index("Arnesh Kumar") < text.index("Raja Ram Verma"), "and the demoted case comes after the others in the prompt")
check("A line that starts REGISTER FACT is not optional" in CA.RESPONSE_GENERATION_PROMPT, "the system prompt carries the REGISTER FACT rule")

# lock (c): the finished answer
ans = {"state": "single_match", "response_text": "The Supreme Court in Mohan Lal v. State of Punjab (2018) 17 SCC 627 held that X. Also see Ram Prasad v. State of Bihar (2003) 1 SCC 1."}
res = CA._attach_register_notes(dict(ans))
check(len(res.get("register_notes", [])) >= 1 and any("Mohan Lal" in n for n in res["register_notes"]), "an answer that cites a register case gets its note")
check("Ram Prasad v. State of Bihar" in (res.get("register_not_checked") or ""), "a case on neither list is named in the fixed 'not checked' sentence")
ack = {"state": "single_match", "response_text": "Mohan Lal v. State of Punjab (2018) 17 SCC 627 was later overruled by Mukesh Singh (2020)."}
check("register_notes" not in CA._attach_register_notes(dict(ack)), "an answer that already says it was overruled gets no second note")
other = {"state": "no_match", "response_text": ans["response_text"]}
check("register_notes" not in CA._attach_register_notes(dict(other)), "a non-answer state is left alone")
check(CA._attach_register_notes("not a dict") == "not a dict", "bad input does not raise")

# switch and fail-open
os.environ["REGISTER_HOOKS"] = "off"
check(RH.demote_matches([OLD, CAND]) == [OLD, CAND] and RH.prompt_lines_for_match(OLD) == [] and RH.answer_notes(ans["response_text"])["notes"] == [], "REGISTER_HOOKS=off turns all three locks off")
check("REGISTER FACT" not in CA.format_retrieved_text_for_prompt([dict(OLD)]), "and the prompt is unchanged")
os.environ.pop("REGISTER_HOOKS")
RH._STATE.clear()
import builtins
real_import = builtins.__import__


def broken(name, *a, **k):
    if name.startswith("overruled_register"):
        raise ImportError("bundle missing")
    return real_import(name, *a, **k)


builtins.__import__ = broken
try:
    RH._STATE.clear()
    sys.modules.pop("overruled_register", None)
    ok = RH.answer_notes("x v. y (2001)")["notes"] == [] and RH.prompt_lines_for_match(OLD) == []
finally:
    builtins.__import__ = real_import
check(ok, "with the bundle missing every hook returns empty and does not raise")

# the case the answer itself relies on (listed by the site as a source) is not called "not checked"
scen = {"state": "single_match", "response_text": "The Constitution Bench in Mukesh Singh v. State (Narcotic Branch of Delhi) held that the dual role is not by itself fatal. It overruled the earlier line, including Mohan Lal v. State of Punjab (2018) 17 SCC 627.",
        "cited_judgment_links": [{"case_name": "Mukesh Singh v State (Narcotic Branch of Delhi)", "url": "https://x"}]}
r_s = CA._attach_register_notes(dict(scen))
check(any("Mohan Lal" in n for n in r_s.get("register_notes", [])) and "register_not_checked" not in r_s, f"the overruling case and the listed source are not called 'not checked': {r_s.get('register_not_checked')}")

# WhatsApp: the same notes go out as one message, before the judgment links
import whatsapp_formatter as WF
msgs = WF.format_answer_for_whatsapp({"state": "single_match", "response_text": "Some answer.", "register_notes": ["Mohan Lal v. State of Punjab (2018): reported to have been overruled."], "register_not_checked": "Cases named in this answer that we have not checked: X v. Y."})
check(any(m.startswith("*Currency notes*") and "Mohan Lal" in m and "not checked" in m for m in msgs), "WhatsApp carries the register notes and the 'not checked' sentence as one message")
check(WF.format_answer_for_whatsapp({"state": "single_match", "response_text": "Some answer."}) == ["Some answer."], "and an answer without notes is unchanged")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
