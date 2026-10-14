"""test_withheld_log.py -- when a hard check still fails after the second try the answer is withheld AND the log says which check and on what (RECHECK ... detail=, ANSWER_WITHHELD ...).
Offline and free. Run: python -X utf8 test_withheld_log.py"""
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


TEXT = {"t": "Cheating is punished under Section 318(4) and arrest powers sit in Section 35."}


class _Msgs:
    def create(self, **kw):
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=TEXT["t"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
matches = [{"type": "statute", "act": "BNS", "section_number": "318", "text": "318. Cheating ...", "case_name": None},
           {"type": "statute", "act": "BNSS", "section_number": "35", "text": "35. When police may arrest without warrant ...", "case_name": None}]


def run():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = CA.generate_grounded_response("Can police arrest me for cheating?", "[BNS 318]\ncheating text\n[BNSS 35]\narrest text", matches=matches)
    return out, buf.getvalue()


# 1. the Act name is never written: after the second try the code adds it from the retrieved sections instead of withholding the answer
out, log = run()
check(out is not None and "Section 318(4) of the BNS" in out and "Section 35 of the BNSS" in out, f"missing Act names are added by code ({out!r})")
check("RECHECK reasons=missing_act detail=" in log and '"missing_act": ["35", "318"]' in log and "ACT_NAME_ADDED_BY_CODE sections=35,318" in log, "and the log says which sections, before and after")
check(not CA._find_sections_missing_act(out, CA._section_act_map(matches)), "the repaired answer passes the same check")

# 2. a mention that already names another Code is not 'repaired' into something wrong: the answer is still withheld, with the reason in the log
TEXT["t"] = "Cheating is punished under Section 318(4) and arrest powers sit in Section 35 of the CrPC."
out, log = run()
check(out is None and "ANSWER_WITHHELD after the second try: reasons=missing_act detail=" in log, "a section number that names another Code right after it is not touched: withheld, and the log says why")
TEXT["t"] = "Cheating is punished under Section 318(4) of the BNS and arrest powers sit in Section 35 of the BNSS."
out, log = run()
check(out is not None and "RECHECK" not in log, "an answer that names its Acts is untouched and not rechecked")

# 3. a pilot case that this question's wider search also supplied is not 'pilot overreach'
import sci_search_tier as T
ans = "In Gurbaksh Singh Sibbia v. State of Punjab the Court held that conditions must be reasonable."
pilot = [{"case_name": "Gurbaksh Singh Sibbia v State of Punjab"}, {"case_name": "Union of India v Mohanlal"}]
T.reset()
check(CA._find_pilot_tier_overreach(ans, pilot) == ["Gurbaksh Singh Sibbia v State of Punjab"], "a pilot case named with 'held' is still flagged when the wider search did not supply it")
T._LOCAL.cases = [{"case_name": "Gurbaksh Singh Sibbia etc v. State of Punjab"}]
check(CA._find_pilot_tier_overreach(ans, pilot) == [], "and not when the wider search supplied it (another spelling of the name)")
check(CA._find_pilot_tier_overreach("In Union of India v Mohanlal the Court held X.", pilot) == ["Union of India v Mohanlal"], "other pilot cases are still checked")
T.reset()
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
