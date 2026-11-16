"""test_retry_by_code.py -- RETRY_BY_CODE (default off; 2026-11-16): for the lawyers' research note only, when the ONLY thing a check found is a fact the answer left out (a cognizable / bailable status our table holds, a companion
section that reached the material), the answer is kept and the fact is added by code instead of a whole second paid answer; 'soft' also covers a case credited with more than its excerpt shows. A wrong statement still gets the second answer.
The model is stubbed. Offline and free. Run: python -X utf8 test_retry_by_code.py"""
import contextlib
import io
import os
import types

os.environ["RESPONSE_STYLE"] = "v3"
import answer_style
import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


V = {"344": {"cognizable": False, "bailable": True}}
TEXT = {"t": ""}
CALLS = {"n": 0}


class _Msgs:
    def create(self, **kw):
        CALLS["n"] += 1
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=TEXT["t"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
M344 = {"type": "statute", "act": "BNS", "section_number": "344", "text": "344. Falsification of accounts ...", "case_name": None, "all_variants": V}
M164 = {"type": "statute", "act": "BNSS", "section_number": "164", "text": "164. Hindrance to a right of way ...", "case_name": None}
M166 = {"type": "statute", "act": "BNSS", "section_number": "166", "text": "166. Dispute about the right to use water ...", "case_name": None}
CASE = {"type": "case", "case_name": "Prabir Purkayastha v. State", "text": "The appellant alleged that a false complaint was lodged and he was arrested.", "case_id": "x"}


def run(text, mode, audience, matches, material="[BNS 344]\nfalsification text [BNSS 164] [BNSS 166]"):
    TEXT["t"] = text
    CALLS["n"] = 0
    if mode is None:
        os.environ.pop("RETRY_BY_CODE", None)
    else:
        os.environ["RETRY_BY_CODE"] = mode
    answer_style.set_audience(audience)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            out = CA.generate_grounded_response("What is the offence for an accountant who falsifies accounts?", material, matches=matches)
    finally:
        answer_style.set_audience(None)
        os.environ.pop("RETRY_BY_CODE", None)
    return out, buf.getvalue(), CALLS["n"]


OMIT = "Falsification of accounts is punished under Section 344 of the BNS. It is bailable."
# 1. off (default): the old behaviour, a second answer
out, log, n = run(OMIT, None, "lawyer", [M344])
check(n == 2 and "RETRY_SKIPPED_BY_CODE" not in log, f"off: a second answer is paid for (calls={n})")
# 2. on, lawyer: one call, a note with the table's status, a log line
out, log, n = run(OMIT, "on", "lawyer", [M344])
check(n == 1 and out is not None and "BNS section 344: non-cognizable, bailable" in out and "leaves out the status" in out and OMIT in out, f"on, lawyer: one call, answer kept, the table's status added (calls={n})")
check("RETRY_SKIPPED_BY_CODE" in log and '"omissions": ["344"]' in log, "the log line names the section")
# 3. on, layman: unchanged (the switch is for the lawyers' note)
out, log, n = run(OMIT, "on", "layman", [M344])
check(n == 2 and "RETRY_SKIPPED_BY_CODE" not in log, f"on, layman: still the second answer (calls={n})")
# 4. a WRONG status is never left to a note
out, log, n = run("Falsification of accounts is punished under Section 344 of the BNS. It is cognizable and bailable.", "on", "lawyer", [M344])
check(n == 2 and "RETRY_SKIPPED_BY_CODE" not in log, f"on: a wrong status still gets the second answer (calls={n})")
# 5. a left-out fact together with an ungrounded section: the second answer
out, log, n = run(OMIT + " Section 500 also applies.", "on", "lawyer", [M344])
check(n == 2 and "RETRY_SKIPPED_BY_CODE" not in log, f"on: a left-out fact PLUS a section not in the material still gets the second answer (calls={n})")
# 6. a right answer: untouched
out, log, n = run("Falsification of accounts is punished under Section 344 of the BNS. It is non-cognizable and bailable.", "on", "lawyer", [M344])
check(n == 1 and "Classification check" not in out and "leaves out" not in out and "RETRY_SKIPPED_BY_CODE" not in log, "a right answer is untouched, one call")
# 7. companion section missing
COMP = "A boundary dispute with threats is covered by Section 164 of the BNSS."
out, log, n = run(COMP, "on", "lawyer", [M164, M166])
check(n == 1 and out is not None and "Not discussed above" in out and "section 166" in out and "RETRY_SKIPPED_BY_CODE" in log, f"on: a missing companion section is named by code, one call (calls={n}; {out[-160:] if out else out!r})")
out, log, n = run(COMP, None, "lawyer", [M164, M166])
check(n == 2, f"off: the companion gap still costs a second answer (calls={n})")
# 8. a case credited with more than its excerpt: 'on' keeps the second answer, 'soft' replaces it with a note
GEN = "The case of Prabir Purkayastha illustrates how courts scrutinise arrests. Section 344 of the BNS is non-cognizable and bailable."
out, log, n = run(GEN, "on", "lawyer", [M344, CASE])
check(n == 2, f"on: an unsupported generalisation still gets the second answer (calls={n})")
out, log, n = run(GEN, "soft", "lawyer", [M344, CASE])
check(n == 1 and out is not None and "Check the excerpt" in out and "Prabir Purkayastha" in out and "RETRY_SKIPPED_BY_CODE" in log, f"soft: one call, a 'check the excerpt' note (calls={n})")
# 9. soft does not widen what is skipped: a wrong status with a generalisation still retries
out, log, n = run(GEN.replace("non-cognizable and bailable", "cognizable and bailable"), "soft", "lawyer", [M344, CASE])
check(n == 2 and "RETRY_SKIPPED_BY_CODE" not in log, f"soft: a wrong status still gets the second answer (calls={n})")
# 10. unknown value of the switch = off
out, log, n = run(OMIT, "maybe", "lawyer", [M344])
check(n == 2, "an unknown value is off")
# 11. the cost line records the switch
check(CA._retry_by_code_mode() == "", "default: off")
os.environ["RETRY_BY_CODE"] = "ON"
check(CA._retry_by_code_mode() == "on", "case-insensitive")
os.environ.pop("RETRY_BY_CODE", None)
print()
print("FAILED:" if FAILURES else "all passed", FAILURES if FAILURES else "")
raise SystemExit(1 if FAILURES else 0)
