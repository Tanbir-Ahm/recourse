"""test_claim_window.py -- the cognizable / bailable check reads the sentence about a section, not the next 300 characters (staging 2026-11-09: an answer was withheld after two tries for a 'cognizable' in a sentence about ANOTHER offence), logs the sentence it objected to, and when the answer still contradicts our table after the second try it is kept with a note written by code instead of being withheld.
Offline and free. Run: python -X utf8 test_claim_window.py"""
import contextlib
import io
import types

import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


V = {"344": {"cognizable": False, "bailable": True}}
mm = lambda t: CA._find_cognizable_bailable_mismatches(t, V)

# 1. a status word in a sentence about something else is not a claim about the section
check(not mm("Section 344 BNS is bailable. The alleged cheating is a cognizable offence."), "another offence's 'cognizable' in the next sentence: no mismatch (the staging case)")
check(not mm("Section 344 BNS is bailable and non-cognizable. The police still arrest on the cognizable cheating charge."), "...also when the section's own claim is right")
check(not mm("Section 344 BNS is non-cognizable and bailable. Section 318 is cognizable."), "...and another section after it")
# 2. a real contradiction is still found, in the same sentence, the next sentence that carries on, an indented sub-line, a table row
check(mm("Section 344 BNS is cognizable and bailable.") and mm("Section 344 BNS is cognizable and bailable.")[0]["claimed"] is True, "same sentence")
check(mm("Section 344 BNS: falsification of accounts. It is bailable and cognizable."), "a following sentence that begins with 'It'")
check(mm("Section 344 BNS: falsification of accounts.\n  - Cognizable: yes; bailable: yes"), "an indented sub-line")
check(mm("| Section 344 | Falsification | Cognizable | Bailable |\n| Section 61 | Conspiracy | Cognizable | Non-bailable |"), "a table row")
check(mm("Section 344 BNS: falsification of accounts. Cognizable and bailable."), "a following sentence that is only the status")
check(not mm("Section 344 BNS: falsification of accounts. Non-cognizable and bailable."), "...and a right one passes")
# 3. the objection carries the sentence
p = mm("Section 344 BNS is cognizable and bailable.")[0]
check(p["text"].startswith("Section 344") and "cognizable" in p["text"], f"the problem carries the text it objected to ({p['text']!r})")
# 4. the omission check uses the same window
check(CA._find_cognizable_bailable_omissions("Section 344 is bailable. The cheating charge is cognizable.", V) == [{"section": "344", "missing_field": "cognizable", "value": False}], "omission: a neighbouring sentence's 'cognizable' does not count as the section's")
check(not CA._find_cognizable_bailable_omissions("Section 344 is bailable. It is non-cognizable.", V), "omission: the carrying-on sentence does")

# 5. the note
note = CA._classification_note(mm("Section 344 BNS is cognizable and bailable."), V)
check("BNS section 344: non-cognizable, bailable" in note and "written by our program" in note, f"the note names the table's values ({note[-90:]!r})")
check(CA._classification_note([], V) == "" and CA._classification_note([{"section": "999"}], V) == "", "nothing to say: no note")
V2 = {"303(2)": {"cognizable": True, "bailable": False, "has_multiple_conditions": True, "all_conditions": [{"cognizable": True, "bailable": False}, {"cognizable": False, "bailable": True}]}}
n2 = CA._classification_note([{"section": "303(2)"}], V2)
check("cognizable or non-cognizable" in n2 and "bailable or non-bailable" in n2, f"a section with two conditions lists both values ({n2[-80:]!r})")

# 6. the whole path: the model contradicts the table twice; the answer is kept, the note is added, the log says so, and a different remaining reason still withholds
TEXT = {"t": "Falsification of accounts is punished under Section 344 of the BNS. It is cognizable and bailable."}
CALLS = {"n": 0}


class _Msgs:
    def create(self, **kw):
        CALLS["n"] += 1
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=TEXT["t"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
matches = [{"type": "statute", "act": "BNS", "section_number": "344", "text": "344. Falsification of accounts ...", "case_name": None, "all_variants": V}]


def run():
    CALLS["n"] = 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = CA.generate_grounded_response("What is the offence for an accountant who falsifies accounts?", "[BNS 344]\nfalsification text", matches=matches)
    return out, buf.getvalue()


out, log = run()
check(out is not None and "It is cognizable and bailable." in out and "BNS section 344: non-cognizable, bailable" in out and CALLS["n"] == 2, f"kept with the note after the second try (calls={CALLS['n']})")
check("CLASSIFICATION_NOTE_ADDED_BY_CODE" in log and "ANSWER_WITHHELD" not in log, "the log says the note was added, not withheld")
TEXT["t"] = "Falsification of accounts is punished under Section 344 of the BNS. It is non-cognizable and bailable."
out, log = run()
check(out is not None and "Classification check" not in out and CALLS["n"] == 1, "a right answer is untouched, one call")
TEXT["t"] = "Falsification of accounts is punished under Section 344 of the BNS and Section 500 also applies. It is cognizable and bailable."
out, log = run()
check(out is None and "ANSWER_WITHHELD" in log and "ungrounded_sections" in log, "another reason still withholds (a section not in the material)")
print()
print("FAILED:" if FAILURES else "all passed", FAILURES if FAILURES else "")
raise SystemExit(1 if FAILURES else 0)
