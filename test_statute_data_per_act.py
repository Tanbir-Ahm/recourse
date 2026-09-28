"""
test_statute_data_per_act.py -- each statute match gets classification data from ITS OWN act's table, or none.

REAL BUG (found 2026-09-28 from a live WhatsApp question, "When can a court issue a non-bailable warrant?"):
semantic_retrieval.find_relevant_sections looked up every statute match in BNS_SECTION_DATA whenever its act had no
table of its own. BNSS section 83 therefore received BNS section 83's row (an offence, 7 years, non-cognizable), BNSS 73
received BNS 73's row (a court-reporting offence, 2 years, bailable), BNSS 92 got BNS 92's (10 years). The answer then
told a real user that procedural sections were "cognizable, bailable, up to 2 years", and the fake differences made the
system think the provisions conflicted ("More than one legal provision applies here..."). 285 of 531 BNSS sections and 12
of 19 NI Act sections share a number with a BNS table row, so this could hit any of them.

Fully offline and free: reads the local corpus file only, no API calls, no network.
Run: python -X utf8 test_statute_data_per_act.py
"""
import re

import semantic_retrieval as sr
from main import BNS_SECTION_DATA
from itact_section_data import ITACT_SECTION_DATA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def rule_variants(table, sec):
    """The lookup rule, written independently of the code under test."""
    v = {k: val for k, val in table.items() if k == sec or k.startswith(f"{sec}(")}
    if table.get(sec) is not None and sec not in v:
        v[sec] = table[sec]
    return v


records = [r for r in sr._load_corpus_embeddings()["records"] if r.get("type") == "statute"]
by_act = {}
for r in records:
    by_act.setdefault(r["act"], []).append(r)
check({"BNS", "BNSS", "ITACT", "NIACT"} <= set(by_act), f"the real corpus has all four statute acts -- {sorted(by_act)}")

# ---------------------------------------------------------------- 1. the reported bug, by name
for sec in ("73", "83", "92"):
    m = sr._enrich_statute_match({"act": "BNSS", "section_number": sec, "type": "statute", "score": 0.5})
    check(m["section_data"] is None and m["all_variants"] == {},
          f"BNSS {sec} carries NO classification data (it used to inherit BNS {sec}'s row)")

# ---------------------------------------------------------------- 2. exhaustive: no BNSS / NI Act section inherits BNS data
for act in ("BNSS", "NIACT"):
    bad = []
    for r in by_act[act]:
        m = sr._enrich_statute_match({**{k: r[k] for k in ("act", "section_number", "type")}, "score": 0.5})
        if m["section_data"] is not None or m["all_variants"]:
            bad.append(r["section_number"])
    check(not bad, f"none of the {len(by_act[act])} {act} sections in the corpus picks up another law's classification -- offenders: {bad[:8]}")

# ---------------------------------------------------------------- 3. BNS behaviour is exactly what it was
diffs = []
for r in by_act["BNS"]:
    m = sr._enrich_statute_match({"act": "BNS", "section_number": r["section_number"], "type": "statute", "score": 0.5})
    if m["all_variants"] != rule_variants(BNS_SECTION_DATA, r["section_number"]) or m["section_data"] != BNS_SECTION_DATA.get(r["section_number"]):
        diffs.append(r["section_number"])
check(not diffs, f"all {len(by_act['BNS'])} BNS sections still get exactly their own BNS rows, unchanged -- differences: {diffs[:8]}")
m318 = sr._enrich_statute_match({"act": "BNS", "section_number": "318", "type": "statute", "score": 0.5})
check({"318(2)", "318(3)", "318(4)"} <= set(m318["all_variants"]), "BNS 318 (cheating) still carries its subsection variants")

# ---------------------------------------------------------------- 4. IT Act keeps ITS table, never BNS's
for r in by_act["ITACT"]:
    m = sr._enrich_statute_match({"act": "ITACT", "section_number": r["section_number"], "type": "statute", "score": 0.5})
    expected = rule_variants(ITACT_SECTION_DATA, r["section_number"])
    check(m["all_variants"] == expected and all(v is ITACT_SECTION_DATA.get(k) for k, v in m["all_variants"].items()),
          f"IT Act {r['section_number']} gets its own IT Act rows only ({len(expected)} variants)")

# ---------------------------------------------------------------- 5. an unknown act gets nothing, and the act name's case doesn't matter
m = sr._enrich_statute_match({"act": "SOMEFUTUREACT", "section_number": "83", "type": "statute", "score": 0.5})
check(m["section_data"] is None and m["all_variants"] == {}, "a law with no table of its own gets none (never a guess from BNS)")
m = sr._enrich_statute_match({"act": "bns", "section_number": "318", "type": "statute", "score": 0.5})
check(bool(m["all_variants"]), "the act name is matched case-insensitively (as before)")
m = sr._enrich_statute_match({"section_number": "318", "type": "statute", "score": 0.5})
check(m["all_variants"] == {}, "a match with no act at all gets no classification data")

# ---------------------------------------------------------------- 6. the real conflict the user saw can no longer be manufactured
q2 = [("482", 0.518), ("83", 0.513), ("92", 0.507), ("132", 0.502), ("73", 0.491)]   # the live warrant question's statute matches
enriched = [sr._enrich_statute_match({"act": "BNSS", "section_number": s, "type": "statute", "score": sc}) for s, sc in q2]
check(sr._conflict_state(enriched) == "single_match",
      "the live 'non-bailable warrant' matches (BNSS 482/83/92/132/73) no longer count as a conflict")
genuine = [sr._enrich_statute_match({"act": "BNS", "section_number": "318", "type": "statute", "score": 0.6})]
check(sr._conflict_state(genuine) == "conflicting_matches",
      "a GENUINE fork (cheating: 318(2) non-cognizable vs 318(4) cognizable) is still detected")

print()
print("ALL PASSED" if not FAILURES else f"{len(FAILURES)} FAILED: {FAILURES}")
raise SystemExit(0 if not FAILURES else 1)
