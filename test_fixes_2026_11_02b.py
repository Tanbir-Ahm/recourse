"""
test_fixes_2026_11_02b.py -- the three builds after the owner's second anticipatory-bail test (owner: "Build 1, 2 and 3"). Offline and free; no model.
  1. a possible register match (a decision of the same name, another year) is said in the case's own row of the table of authorities and in the prompt line beside the passage; the Currency note the row already holds is not printed again
  2. a case of the 'Other real court cases' list that the answer names shows the passage the answer model was given
  3. 'the sections and judgments this answer rests on' lists, in the lawyers' note, only the judgments the answer names
Run: python -X utf8 test_fixes_2026_11_02b.py
"""
import os
import sys

os.environ["REGISTER_HOOKS"] = "on"

import answer_export as X
import answer_view as V
import chat_assistant as CA
import register_hooks as RH
import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


BH = "Bhadresh Bipinbhai Sheth v. State of Gujarat & Another"

# 1. the possible match
p = RH.possible_for_case(BH, 2013, None)
check(p and p["clause"].startswith("Possible match:") and "(2016)" in p["clause"] and "Sushila Aggarwal" in p["clause"] and p["line"].startswith("REGISTER POSSIBLE MATCH: Possible match:"), "possible_for_case: the same name, another year -> the register's 'Possible match' sentence and a prompt line")
check(RH.possible_for_case(BH, 2016, None) is None, "...a strong hit (the year agrees) is the register's firm reading, not a possible match")
check(RH.possible_for_case("Hanumant v. The State of Madhya Pradesh", 1952, "AIR 1952 SC 343") is None and RH.possible_for_case("Nobody v. Nowhere Tribunal", 2001, None) is None and RH.possible_for_case("", 2001) is None, "a strong hit, a case not on the register, no name: None")
os.environ["REGISTER_HOOKS"] = "off"
check(RH.possible_for_case(BH, 2013, None) is None, "REGISTER_HOOKS=off: None")
os.environ["REGISTER_HOOKS"] = "on"

res = {"state": "single_match", "response_text": "Bhadresh Bipinbhai Sheth v. State of Gujarat, as quoted in Sudhir, says the granting court may cancel bail.", "matches": [],
       "cited_judgment_links": [], "sci_related_judgments": [{"case_name": BH, "date": "2013-05-18", "paragraph": None, "link": "https://e.org/b", "court": "Supreme Court of India", "excerpt": "x"},
                                                                  {"case_name": "Nobody v. Nowhere Tribunal", "date": "2001-01-01", "paragraph": "3", "link": "https://e.org/n", "court": "Supreme Court of India", "excerpt": "y"}]}
auth = CA._build_authorities(res)
rows = {r["case"]: r for r in auth["wider"]}
check("Possible match" in (rows[BH]["status"] or "") and "(2016)" in rows[BH]["status"], f"the table: the case's own row carries the possible match ({rows[BH]['status'][:90]!r})")
check((rows["Nobody v. Nowhere Tribunal"]["status"] or "").startswith("Not checked by us"), "...a case that is not on the register still reads 'Not checked by us'")

pm = [{"case_name": BH, "citation": None, "text": "The court which grants the bail also has the power to cancel it.", "source": "pilot_wider_tier", "ik_search_url": "https://e.org/b"}]
blk = CA._format_pilot_context_as_wider_search(pm, T)
check("[Overruled Register -- possible match, not optional" in blk and "REGISTER POSSIBLE MATCH: Possible match:" in blk, "the prompt block of a pool case carries the possible-match line")
check("REGISTER POSSIBLE MATCH" in T.FEED_INSTRUCTION and "cannot tell whether it is the same case" in T.FEED_INSTRUCTION, "the wider-search instruction tells the model what the line means")

# the Currency note the row already holds is not printed again in the download
view = {"kind": "answer", "answer_markdown": "Short answer.", "authorities": {"tables": [{"heading": "Further reading from a wider search (not independently verified)",
        "markdown": "| Case | Citation | Paragraph | Where it stands on our lists | Link |\n|---|---|---|---|---|\n| " + BH + " (2013) | not held | - | " + p["clause"] + " | [open](https://e.org/b) |\n"}], "note": None},
        "register": {"notes": [], "possible": [p["clause"]], "not_checked": "Cases named in this answer that we have not checked: Z v. W."}}
doc = X.build_document([{"question": "q", "view": view, "answer_id": "a1", "created_at": None, "audience": "lawyer"}])
txt = X.all_text(doc)
check(txt.count("Possible match: the case named in this answer") == 1, f"the download prints the possible match once, in the case's row ({txt.count('Possible match: the case named in this answer')} times)")
check("Cases named in this answer that we have not checked: Z v. W." in txt and X.H_CURRENCY in txt, "...the rest of the Currency notes stays")
view2 = dict(view, register={"notes": [], "possible": [p["clause"]], "not_checked": None})
doc2 = X.build_document([{"question": "q", "view": view2, "answer_id": "a1", "created_at": None, "audience": "lawyer"}])
check(X.H_CURRENCY not in X.all_text(doc2), "a Currency section that would be empty is not printed")

# 2. the passage of a pool case the answer names
long_text = "The Court may, if there are reasons for doing so, limit the operation of the order. " * 30
base = {"state": "single_match", "response_text": "In Gurbaksh Singh Sibbia v. State of Punjab (1980) the Court said so.", "matches": [],
        "unverified_related_judgments": [{"case_name": "Gurbaksh Singh Sibbia v. State of Punjab", "ik_search_url": "https://e.org/s", "text": long_text, "paragraph_number": None},
                                         {"case_name": "Z v. W", "ik_search_url": None, "text": "a passage nobody names", "paragraph_number": "2"},
                                         {"case_name": "Q v. R", "ik_search_url": None, "text": None}]}
v = V.build(base)
u = {j["case_name"]: j for j in v["unverified"]}
ex = u["Gurbaksh Singh Sibbia v. State of Punjab"]["excerpt"]
check(ex and ex.startswith("The Court may, if there are reasons") and ex.endswith(" ...") and len(ex) <= V.UNVERIFIED_EXCERPT_CHARS + 6, f"a named pool case shows the first {V.UNVERIFIED_EXCERPT_CHARS} characters the model was given, cut with an ellipsis ({len(ex)} characters)")
check(u["Z v. W"]["excerpt"] is None and u["Q v. R"]["excerpt"] is None, "a pool case the answer does not name, or with no passage: no excerpt")
d3 = X.build_document([{"question": "q", "view": v, "answer_id": "a1", "created_at": None, "audience": "lawyer"}])
check("The Court may, if there are reasons for doing so" in X.all_text(d3) and "a passage nobody names" not in X.all_text(d3), "the download prints that passage under the case's name, and only that one")

# 3. what the lawyers' note rests on
cm = lambda name, **k: dict({"type": "judgment", "case_name": name, "text": "Excerpt of " + name, "paragraph_number": "5", "source": "semantic", "citation": "(2014) 8 SCC 273"}, **k)
sm = {"type": "statute", "act": "BNSS", "section_number": "482", "text": "482. Anticipatory bail.", "source": "semantic"}
R3 = {"state": "single_match", "response_text": "Section 482 of the BNSS lets a person apply for pre-arrest bail.", "matches": [sm, cm("Arnesh Kumar v State of Bihar"), cm("Satender Kumar Antil v CBI")]}
lawyer = V.build(dict(R3, audience="lawyer"))
layman = V.build(dict(R3, audience="layman"))
check([s["heading"] for s in lawyer["statutes"]] == ["BNSS Section 482"] and lawyer["judgments"] == [], f"the lawyers' note: the section the answer names, and no judgment it never names ({[j['name'] for j in lawyer['judgments']]})")
check([j["name"] for j in layman["judgments"]] != [] , "the layman's list keeps its fallback (sources shown even when no case is named)")
named = V.build(dict(R3, audience="lawyer", response_text="Arnesh Kumar v State of Bihar says arrest is not routine. Section 482 of the BNSS applies."))
check([j["name"] for j in named["judgments"]] == ["Arnesh Kumar v State of Bihar"], "...and a judgment the answer does name is listed")
check(V.sources_worth_showing([cm("A v B")], "no case named", strict=True) == [] and len(V.sources_worth_showing([cm("A v B")], "no case named")) == 1, "sources_worth_showing: strict gives none, the default gives the fallback")

print()
if FAILURES:
    print(len(FAILURES), "FAILED:", FAILURES)
    sys.exit(1)
print("ALL PASSED")
