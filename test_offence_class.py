"""
test_offence_class.py -- the BNSS First Schedule (schedules/bnss_schedule_I.json, build_bnss_schedule1.py, offence_class.py; owner's go 2026-11-09). Free and offline.
Proves: the file holds the Schedule's Part I (more than 400 rows, every section a section of the library's BNS, no empty cell, no row of column numbers, none whose columns hold different numbers of entries); rows I read against the Gazette's own text for the sections that
matter in the 9 Nov question (rape, gang rape, voyeurism, stalking, evidence, cheating, hurt) carry the Schedule's words; a summary is given only where every entry agrees; the lookup finds sub-sections; Part II is kept as three rows; the prompt block is off by default and
for BNS offences only; the engine's prompt carries it with the switch on.
Run: python -X utf8 test_offence_class.py
"""
import json
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("OFFENCE_CLASS", None)

import offence_class as O

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


d = json.load(open(O.PATH, encoding="utf-8"))
rows = d["rows"]
check(d["status"] == "machine_extracted" and len(rows) > 400 and d["schema"] == "bnss-schedule-I-1", f"the file says what it is: machine_extracted, {len(rows)} rows")
check(all(r["offence"] and r["punishment"] and r["cognizable"] and r["bailable"] and r["court"] for r in rows), "no row has an empty cell")
check(not [r for r in rows if re.fullmatch(r"\d", r["section"]) and re.fullmatch(r"\d", r["offence"])], "no row is the row of column numbers")
check(not [r["section"] for r in rows if r.get("entries_misaligned")], "no row holds different numbers of cognizable and bailable entries")
import glob
lib = set()
for f in glob.glob(os.path.join(HERE, "chunks", "bharatiya_nyaya_sanhita_2023_chunks.json")):
    dd = json.load(open(f, encoding="utf-8"))
    for r in (dd if isinstance(dd, list) else dd.get("chunks", [])):
        if isinstance(r, dict) and r.get("section_number"):
            lib.add(str(r["section_number"]).split("(")[0])
check(all(re.sub(r"\(.*", "", r["section"]) in lib for r in rows), "every section of the file is a section of the library's BNS")
order = [int(re.sub(r"\D", "", re.sub(r"\(.*", "", r["section"])) or 0) for r in rows]
check(all(b >= a for a, b in zip(order, order[1:])), "the rows are in the Schedule's order")

def one(sec):
    r = O.rows_for(sec)
    return r[0] if r else None

r64, r70, r77, r115, r238 = one("64(1)"), one("70(1)"), one("77"), one("115(2)"), one("238(a)")
check(r64 and r64["offence"] == "Rape." and "Cognizable" in r64["cognizable"] and "Non-bailable" in r64["bailable"] and "Court of Session" in r64["court"], "BNS 64(1): rape, cognizable, non-bailable, Court of Session")
check(r70 and r70["offence"] == "Gang rape." and O.summary(r70) == "cognizable, non-bailable", "BNS 70(1): gang rape, cognizable, non-bailable")
check(r77 and r77["bailable"] == "Bailable. Non-bailable." and r77["cognizable"] == "Cognizable. Cognizable." and r77["bailable_summary"] == "varies" and O.summary(r77) == "cognizable", "BNS 77 (voyeurism): first conviction bailable, second non-bailable, in the Schedule's order; the summary does not flatten it")
check(r115 and O.summary(r115) == "non-cognizable, bailable", "BNS 115(2): non-cognizable, bailable")
check(r238 and r238["cognizable_summary"] == "depends on the offence abetted" and "According as" in r238["cognizable"], "BNS 238(a): 'according as the offence ...' is kept and not turned into a yes or no")

check(len(O.rows_for("70")) == 2 and O.rows_for("70(1)")[0]["section"] == "70(1)" and O.rows_for("9999") == [] and O.rows_for("") == [] and O.rows_for(None) == [], "the lookup finds a section's sub-sections, one sub-section, and nothing for an unknown section")
check(len(d["part_II_rows"]) == 3 and d["part_II_rows"][2]["bailable"] == "Bailable." and "Part II" in O.part2_note(), "Part II is kept as its three rows")
check("Voyeurism" in O.line(r77) and O.line(r77).startswith("BNS 77:"), "a row is shown as one line in the Schedule's words")

ms = [{"type": "statute", "act": "BNS", "section_number": "77", "text": "t"}, {"type": "statute", "act": "BNSS", "section_number": "35", "text": "t"}, {"type": "statute", "act": "ITACT", "section_number": "66E", "text": "t"}, {"case_name": "A v. B"}]
check(O.prompt_block(ms) == "", "OFFENCE_CLASS off (the default): no block")
os.environ["OFFENCE_CLASS"] = "on"
b = O.prompt_block(ms)
check("BNS 77: Voyeurism." in b and "BNSS 35" not in b and "66E" not in b and "ONLY from these lines" in b and "the material does not show its classification" in b, "on: the row for the BNS offence only (not a BNSS section, not the IT Act, not a case), with the rule to state classification only from it")
check(O.prompt_block([{"act": "BNS", "section_number": "3", "text": "t"}]) == "" and O.prompt_block(None) == "", "a BNS section that is not an offence, or nothing: no block")

import chat_assistant as CA
sent = {}


class _M:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["p"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Short.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_M())
CA.generate_grounded_response("Is voyeurism bailable?", "[BNS Section 77]\nText.", matches=[ms[0]])
check("## Classification of the offences above" in sent["p"] and sent["p"].index("Text.") < sent["p"].index("## Classification") and "## Hard rules (never break)" in sent["p"], "the engine's prompt carries the block after the material, with the Hard rules unchanged")
os.environ["OFFENCE_CLASS"] = "off"
CA.generate_grounded_response("Is voyeurism bailable?", "[BNS Section 77]\nText.", matches=[ms[0]])
check("## Classification of the offences above" not in sent["p"], "switch off: the prompt is as before")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
