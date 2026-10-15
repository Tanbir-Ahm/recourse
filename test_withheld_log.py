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


CALLS = {"n": 0}


class _Msgs:
    def create(self, **kw):
        CALLS["n"] += 1
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=TEXT["t"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
matches = [{"type": "statute", "act": "BNS", "section_number": "318", "text": "318. Cheating ...", "case_name": None},
           {"type": "statute", "act": "BNSS", "section_number": "35", "text": "35. When police may arrest without warrant ...", "case_name": None}]


def run():
    CALLS["n"] = 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = CA.generate_grounded_response("Can police arrest me for cheating?", "[BNS 318]\ncheating text\n[BNSS 35]\narrest text", matches=matches)
    return out, buf.getvalue()


# 1. the Act name is never written: since 2026-10-15 the code adds it from the retrieved sections on the FIRST pass, so there is no second paid call
out, log = run()
check(out is not None and "Section 318(4) of the BNS" in out and "Section 35 of the BNSS" in out, f"missing Act names are added by code ({out!r})")
check(CALLS["n"] == 1 and "RECHECK" not in log, f"one model call only, no recheck (calls={CALLS['n']})")
check("ACT_NAME_ADDED_BY_CODE first_pass sections=35,318" in log, "and the log says which sections were repaired on the first pass")
check(not CA._find_sections_missing_act(out, CA._section_act_map(matches)), "the repaired answer passes the same check")

# 2. a mention that already names some other Act is not 'repaired' into something wrong: the number stays missing, the paid second try runs, and if it is still missing the answer is withheld with the reason in the log
TEXT["t"] = "Cheating is punished under Section 318(4) and arrest powers sit in Section 35 of the Act."
out, log = run()
check(out is None and CALLS["n"] == 2 and "RECHECK reasons=missing_act detail=" in log and "ANSWER_WITHHELD after the second try: reasons=missing_act detail=" in log,
      f"a section number that names another Act right after it is not touched: second try, then withheld, and the log says why (calls={CALLS['n']})")
# 2a. an OLD-law mention ('of the CrPC') is not a BNSS mention at all (2026-10-15): nothing to repair for it, the other section is repaired on the first pass
TEXT["t"] = "Cheating is punished under Section 318(4) and arrest powers sit in Section 35 of the CrPC."
out, log = run()
check(out is not None and "Section 35 of the CrPC" in out and "Section 318(4) of the BNS" in out and CALLS["n"] == 1 and "RECHECK" not in log, f"an old-law mention is left alone and costs no second call ({out!r}, calls={CALLS['n']})")
TEXT["t"] = "Cheating is punished under Section 318(4) of the BNS and arrest powers sit in Section 35 of the BNSS."
out, log = run()
check(out is not None and "RECHECK" not in log and "ACT_NAME_ADDED_BY_CODE" not in log and CALLS["n"] == 1, "an answer that names its Acts is untouched and not rechecked")

# 2b. the phone-number check was removed (owner, 2026-10-15): an answer that states a helpline is not rechecked
TEXT["t"] = "Cheating is punished under Section 318(4) of the BNS and arrest powers sit in Section 35 of the BNSS. For help call the helpline 1800 123 4567."
out, log = run()
check(out is not None and "1800 123 4567" in out and "RECHECK" not in log and CALLS["n"] == 1, "no phone-number check any more: no recheck, one call")
check(not hasattr(CA, "_find_unverified_contact_numbers") and not hasattr(CA, "_UNVERIFIED_CONTACT_RETRY_INSTRUCTION"), "and the function and its retry text are gone")
TEXT["t"] = "Cheating is punished under Section 318(4) and arrest powers sit in Section 35."

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

# 4. OWNER'S DECISION 2026-10-14: in feed mode the pilot cases (all 25 are judgments of the wider index) are cited like wider-search cases: no overreach check, same instruction, same label
import os
os.environ["SCI_SEARCH_MODE"] = "feed"
check(CA._find_pilot_tier_overreach(ans, pilot) == [] and CA._find_pilot_tier_overreach("In Union of India v Mohanlal the Court held X.", pilot) == [], "feed mode: the pilot-overreach check does not withhold an answer for naming a pilot case with 'held'")
pm = [{"case_name": "Mohan Lal v State of Punjab", "citation": "(2018) 17 SCC 627", "text": "The complainant may not investigate his own complaint."}, {"case_name": "Gurbaksh Singh Sibbia v State of Punjab", "citation": "(1980) 2 SCC 565", "text": "Conditions must be reasonable."}]
blk = CA._format_pilot_context_for_prompt(pm)
check("WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: Gurbaksh Singh Sibbia" in blk and "describe ONLY what its own passage literally says" in blk and T.LABEL in blk and 'NEVER say it' not in blk, "feed mode: the pilot passages are handed over like wider-search passages (no 'never say held')")
check("REGISTER" in blk and "Mohan Lal" in blk, "and a pilot case on the Overruled Register carries its register line")
os.environ["SCI_SEARCH_MODE"] = "off"
blk0 = CA._format_pilot_context_for_prompt(pm)
check('NEVER say it' in blk0 and CA._find_pilot_tier_overreach(ans, pilot) == ["Gurbaksh Singh Sibbia v State of Punjab"], "feed off (production today): the old instruction and the old check, exactly as before")
os.environ["SCI_SEARCH_MODE"] = "feed"
T.reset()
res = T.attach("q", {"state": "single_match", "response_text": "In Gurbaksh Singh Sibbia v. State of Punjab (1980) the Court said conditions must be reasonable.", "unverified_related_judgments": pilot})
check(res["response_text"].count(T.LABEL) == 1 and "(1980) " + T.LABEL in res["response_text"], f"feed mode: a pilot case named in the answer gets the wider-search label ({res['response_text']!r})")
nc = CA._attach_register_notes({"state": "single_match", "response_text": "In Gurbaksh Singh Sibbia v. State of Punjab (1980) the Court said X. In Ram Prasad v. State of Bihar (2001) it said Y.", "unverified_related_judgments": pilot}).get("register_not_checked") or ""
check("Ram Prasad" in nc and "Sibbia" not in nc, f"and it is not listed as 'not checked' ({nc!r})")
os.environ["SCI_SEARCH_MODE"] = "off"
T.reset()
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
