"""test_act_per_mention.py -- (1) the Act written right after a section number is checked mention by mention and the wrong one of BNS/BNSS is corrected by code; (2) the old law ("of the former Code",
"of the CrPC", "(now Section 346 of the BNSS)") is never completed, corrected or counted as a BNS/BNSS mention; (3) a number retrieved under both Acts is never repaired by guesswork and either Act's name satisfies the
check. Offline and free. Run: python -X utf8 test_act_per_mention.py"""
import contextlib
import io
import sys
import types

import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def mk(act, num, text="x"):
    return {"type": "statute", "act": act, "section_number": num, "text": f"{num}. text", "case_name": None}


# ---------- 1. wrong Act after a number ----------
m_bnss35 = [mk("BNSS", "35")]
acts = CA._section_acts_all(m_bnss35)
ret = "[BNSS Section 35, Section/Para 35]\n35. When police may arrest without warrant ..."
t, fx = CA._correct_wrong_acts("Under Section 35 of the BNS, police may arrest without a warrant.", acts, ret)
check(t == "Under Section 35 of the BNSS, police may arrest without a warrant." and fx == ["35:BNS->BNSS"], f"BNS written for a BNSS-only number is corrected ({t!r}, {fx})")
t, fx = CA._correct_wrong_acts("Under Section 35(1) of the BNSS, police may arrest.", acts, ret)
check(fx == [] and t.endswith("BNSS, police may arrest."), "the right Act is untouched")
t, fx = CA._correct_wrong_acts("Under section 35(1)(b), BNS, police may arrest.", acts, ret)
check(t == "Under section 35(1)(b), BNSS, police may arrest." and fx, f"also with a comma and a subsection ({t!r})")
m_bns = [mk("BNS", "318")]
t, fx = CA._correct_wrong_acts("Cheating is Section 318(4) of the BNSS.", CA._section_acts_all(m_bns), "[BNS Section 318, Section/Para 318]")
check(t == "Cheating is Section 318(4) of the BNS." and fx == ["318:BNSS->BNS"], f"and the other way round ({t!r})")

# not corrected
both = CA._section_acts_all([mk("BNS", "35"), mk("BNSS", "35")])
t, fx = CA._correct_wrong_acts("Section 35 of the BNS and Section 35 of the BNSS differ.", both, "[BNS Section 35, ...] [BNSS Section 35, ...]")
check(fx == [], "a number retrieved under BOTH Acts is never corrected")
t, fx = CA._correct_wrong_acts("Section 99 of the BNS says X.", acts, ret)
check(fx == [], "a number that was not retrieved is left alone (other checks handle it)")
pointer = "Statute pointers: CrPC Section 309 corresponds to BNSS Section 346 and 348."
t, fx = CA._correct_wrong_acts("Section 348 of the BNSS lets the court adjourn.", CA._section_acts_all([mk("BNS", "348")]), "[BNS Section 348, Section/Para 348]\n" + pointer)
check(fx == [], "a pair the material itself supports (a statute pointer 'BNSS Section 346 and 348') is not 'corrected'")
t, fx = CA._correct_wrong_acts("Section 35 of the BNSS, as the passage says.", CA._section_acts_all([mk("BNS", "35")]), "[BNS Section 35, ...]\nA passage: see Section 35 of the BNSS for arrests.")
check(fx == [], "a pair quoted in a passage ('Section 35 of the BNSS') is supported too")
t, fx = CA._correct_wrong_acts("Section 35 of the former Code and Section 35 of the CrPC were different.", acts, ret)
check(fx == [] and t.startswith("Section 35 of the former Code"), "old-law mentions are untouched")

# ---------- 2. the old law ----------
mp = [mk("BNSS", "482")]
amap, aall = CA._section_act_map(mp), CA._section_acts_all(mp)
txt = "Earlier the High Court used Section 482 of the former Code for this; it is now Section 528 of the BNSS."
check(CA._find_sections_missing_act(txt, amap, aall) == [], "'Section 482 of the former Code' does not count as a BNSS mention (no false 'missing Act')")
check(CA._add_missing_acts(txt, ["482"], amap) == txt, "and the repair does not complete it into 'of the BNSS of the former Code'")
txt2 = "Section 482 (now Section 528 of the BNSS) is the inherent power."
check(CA._find_sections_missing_act(txt2, amap, aall) == [] and CA._add_missing_acts(txt2, ["482"], amap) == txt2, "'Section 482 (now Section 528 ...)' is an old-law mention too")
txt3 = "The former Section 482 gave the power."
check(CA._find_sections_missing_act(txt3, amap, aall) == [], "'the former Section 482'")
txt4 = "The High Court may act under Section 482 to quash."
check(CA._find_sections_missing_act(txt4, amap, aall) == ["482"] and CA._add_missing_acts(txt4, ["482"], amap).startswith("The High Court may act under Section 482 of the BNSS to quash"), "a plain mention without an Act is still found and completed")
txt5 = "Section 482 of the CrPC was used and Section 482 applies here."
check(CA._add_missing_acts(txt5, ["482"], amap) == "Section 482 of the CrPC was used and Section 482 of the BNSS applies here.", "the old-law mention is skipped and the next plain mention is completed")

# ---------- 3. a number in both Acts ----------
both_map = CA._section_act_map([mk("BNS", "35"), mk("BNSS", "35")])
check(CA._find_sections_missing_act("Section 35 of the BNSS lets police arrest.", both_map, both) == [], "either Act's name satisfies the check when the number is in both")
check(CA._find_sections_missing_act("Section 35 of the BNSS lets police arrest.", both_map) == ["35"], "without the new argument the old first-seen-wins behaviour is unchanged")

# ---------- 4. end to end ----------
TEXT = {"t": "Under Section 35 of the BNS, police may arrest. Section 41A also matters."}
CALLS = {"n": 0}


class _Msgs:
    def create(self, **kw):
        CALLS["n"] += 1
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=TEXT["t"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
matches = [mk("BNSS", "35"), mk("BNSS", "41A")]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out = CA.generate_grounded_response("Can police arrest me?", "[BNSS Section 35, Section/Para 35]\n35 ...\n[BNSS Section 41A, Section/Para 41A]\n41A ...", matches=matches)
log = buf.getvalue()
check(out is not None and "Section 35 of the BNSS" in out and "of the BNS," not in out and CALLS["n"] == 1, f"end to end: the wrong Act is corrected and ONE model call is made ({out!r}, calls={CALLS['n']})")
check("ACT_NAME_CORRECTED_BY_CODE 35:BNS->BNSS" in log and "RECHECK" not in log, "and the log says so (41A needs nothing: the check is whole-answer, BNSS is named)")
TEXT["t"] = "Under Section 35 of the BNS, police may arrest. Section 41A also matters."
matches2 = [mk("BNSS", "35"), mk("BNS", "41A")]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out2 = CA.generate_grounded_response("Can police arrest me?", "[BNSS Section 35, Section/Para 35]\n35 ...\n[BNS Section 41A, Section/Para 41A]\n41A ...", matches=matches2)
log2 = buf.getvalue()
check(out2 is not None and "Section 35 of the BNSS" in out2 and "Section 41A of the BNS" in out2 and "ACT_NAME_ADDED_BY_CODE first_pass sections=41A" in log2, f"a corrected Act and a first-pass addition in one answer ({out2!r})")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
