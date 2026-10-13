"""
test_case_check.py -- the lawyers' case check (case_check.py + its box in recourse_app.py). Offline and free: no model, no network. Run: python -X utf8 test_case_check.py
"""
import os
import sys

import case_check as CC

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


os.environ.pop("REGISTER_HOOKS", None)
r = CC.check_case("")
check(r["status"] == "empty" and r["notes"] == [], "an empty box gives nothing")
r = CC.check_case("Raj Deo Sharma v. State of Bihar (1999)")
check(r["status"] == "register" and "was overruled by" in r["notes"][0] and "Ramachandra Rao" in r["notes"][0], f"a verified row is worded firmly: {r['notes']}")
r = CC.check_case("Mohan Lal v. State of Punjab (2018)")
check(r["status"] == "register" and "reported as" in r["notes"][0] and "not yet confirmed by our reviewer" in r["notes"][0], f"a candidate row is 'reported ... not yet confirmed': {r['notes']}")
r = CC.check_case("(2018) 17 SCC 627")
check(r["status"] == "register" and "Mohan Lal" in r["notes"][0], "a citation alone finds it")
r = CC.check_case("Arnesh Kumar v. State of Bihar (2014)")
check(r["status"] == "card_quiet" and "not a finding that it is still good law" in r["notes"][0], f"a quiet card says it is silence, not a finding: {r['notes']}")
r = CC.check_case("Ram Prasad v. State of Bihar (2003)")
check(r["status"] == "not_checked" and r["notes"][0].startswith("Not checked by us"), "an unknown case gets the fixed 'not checked by us' sentence")
r = CC.check_case("the Mohan Lal case")
check(r["status"] == "need_more" and "both party names and the year" in r["notes"][0], "a bare name is not matched; it asks for the year or citation")
r = CC.check_case("Mohan Lal v. State of Punjab")
check(r["status"] == "need_more", f"both names but no year or citation: asks, does not guess ({r['status']})")
r = CC.check_case("Mohan Lal v. State of Punjab (2005)")
check(r["status"] != "register", "a wrong year is not matched")
allout = " ".join(" ".join(CC.check_case(q)["notes"]) for q in ("Raj Deo Sharma v. State of Bihar (1999)", "Mohan Lal v. State of Punjab (2018)", "Arnesh Kumar v. State of Bihar (2014)", "Ram Prasad v. State of Bihar (2003)", "(2018) 17 SCC 627"))
check("is good law" not in allout.replace("not a finding that it is still good law", "").replace("still good law?", "") and "are good law" not in allout, "no result calls a case good law")
os.environ["REGISTER_HOOKS"] = "off"
check(CC.check_case("Raj Deo Sharma v. State of Bihar (1999)")["status"] == "unavailable", "REGISTER_HOOKS=off switches the case check off too, without raising")
os.environ.pop("REGISTER_HOOKS")
check(CC.check_case("x" * 5000)["status"] in ("need_more", "not_checked"), "a very long input does not raise")

from streamlit.testing.v1 import AppTest


at = AppTest.from_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), "recourse_app.py"), default_timeout=90).run()
check(not at.exception, "the page with the case check box renders")
check(any("check whether one case has been overruled" in e.label for e in at.expander), "the box is there, labelled for lawyers")
at.text_input(key="case_check_q").set_value("Raj Deo Sharma v. State of Bihar (1999)").run()
check(any("was overruled by" in m.value for m in at.markdown), "typing a case in the box shows the register note")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
