"""
test_dv_case_leak_guard.py

Regression guard for the 2026-09-20 gap: the six curated domestic-violence
Supreme Court judgments embedded in the shared corpus (Hiral P. Harsora,
D. Velusamy, Satish Chander Ahuja, Indra Sarma, Prabha Tyagi, S. Vanitha --
see domestic_violence_doctrine_map.py) were not on
OUT_OF_CHAT_DOMAIN_CASE_NAMES, so nothing structurally stopped one of them
matching an ordinary arrest question by vocabulary overlap alone (the same
category of failure documented for the cheque-bounce cases; see
test_cheque_bounce_chat.py / test_freeze_chat.py for the established
pattern this test follows).

Two case names that superficially look like family-law disputes were
deliberately NOT added, because they are seeded for OTHER domains and must
stay visible on arrest questions:
  - Lata Singh v State of Uttar Pradesh (false-kidnapping / right-to-marry
    arrest scenario; judgment_doctrine_map.py)
  - Deepa v S. Vijayalakshmi (BNSS 43(5) night-arrest-of-women rights;
    seed_scenario_corpus.py)

Run with: python test_dv_case_leak_guard.py
"""

import sys

FAILURES = []


def check(condition, description):
    print(f"[{'PASS' if condition else 'FAIL'}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- offline: the retrieval-filter carve-out ----

from semantic_retrieval import (
    OUT_OF_CHAT_DOMAIN_CASE_NAMES, DOMESTIC_VIOLENCE_CASE_NAMES,
    CHEQUE_BOUNCE_CASE_NAMES, FREEZE_CASE_NAMES, _DOMAIN_CARVE_OUT,
)

check(DOMESTIC_VIOLENCE_CASE_NAMES <= OUT_OF_CHAT_DOMAIN_CASE_NAMES,
      "every DV case is in the default OUT_OF_CHAT_DOMAIN exclusion set")
check(not (DOMESTIC_VIOLENCE_CASE_NAMES & CHEQUE_BOUNCE_CASE_NAMES)
      and not (DOMESTIC_VIOLENCE_CASE_NAMES & FREEZE_CASE_NAMES),
      "DV carve-out does not overlap the cheque or freeze carve-outs")
check(_DOMAIN_CARVE_OUT.get("domestic_violence") == DOMESTIC_VIOLENCE_CASE_NAMES,
      "domestic_violence is registered as its own carve-out domain")

for name in ("Lata Singh v State of Uttar Pradesh", "Deepa v S. Vijayalakshmi"):
    check(name not in DOMESTIC_VIOLENCE_CASE_NAMES,
          f"{name} is NOT in the DV carve-out (it belongs to the arrest domain)")


# ---- end-to-end: an arrest question must not surface a DV case ----

from chat_assistant import answer_question

arrest_q = (
    "My husband was arrested last night by the police over a dowry harassment "
    "complaint filed by my in-laws' family, no notice was shown and he was taken "
    "away in front of the children."
)
r = answer_question(arrest_q)
named = {a["case_name"] for a in r.get("matches", []) if a.get("case_name")}
check(not (named & DOMESTIC_VIOLENCE_CASE_NAMES),
      f"ordinary arrest question does not surface a DV case (matches: {named})")

# ---- end-to-end: a DV question, with the domain enabled, still can ----

dv_q = (
    "My in-laws are demanding I leave the shared household even though it belongs "
    "to my husband's mother, can they throw me out under the Domestic Violence Act?"
)
r2 = answer_question(dv_q, inline_domains={"domestic_violence"})
check(r2.get("state") == "single_match",
      f"DV question with inline_domains -> single_match (got {r2.get('state')!r})")
check(r2.get("redirect_domain") == "domestic_violence",
      "redirect_domain propagates as 'domestic_violence'")
named2 = {a["case_name"] for a in r2.get("matches", []) if a.get("case_name")}
check(bool(named2 & DOMESTIC_VIOLENCE_CASE_NAMES) or bool(r2.get("response_text")),
      "DV question still gets a grounded answer with the carve-out enabled")


print("\n" + "=" * 70)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("RESULT: ALL TESTS PASSED")
sys.exit(0)
