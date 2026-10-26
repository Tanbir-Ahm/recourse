"""test_followup_merge.py -- the second search for a follow-up question (chat_assistant._add_own_words_search and
_merge_follow_up_results, FOLLOW_UPS 2cl/2cm): a follow-up is searched on the person's own words as well as on the whole
message (own words plus rewrite), and what the second search finds is merged in. Offline and free: retrieval is replaced by
a stub that returns canned results and records the queries. Run: python -X utf8 test_followup_merge.py"""
import contextlib
import io
import json
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
import chat_assistant as CA
import web_chat as W
import semantic_retrieval as SR

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def st(act, num, score):
    return {"type": "statute", "act": act, "section_number": num, "score": score, "chunk_id": f"statute:{act}:{num}", "text": f"{act} {num}"}


def jd(name, para, score):
    return {"type": "judgment", "case_name": name, "paragraph_number": para, "score": score, "text": f"{name} {para}"}


def res(state, statutes=(), judgments=()):
    if state in ("no_match", "unavailable"):
        return {"state": state}
    return {"state": state, "matches": list(statutes), "judgment_matches": list(judgments)}


OWN = "is bail possible in this case?"
REWRITE = "Is bail possible for a person arrested by the army under a special law where the trial is delayed?"
FOLLOW_UP = OWN + "\n" + W.REWRITE_LEAD + REWRITE + ")"

# ---------------------------------------------------------------- the own-words extractor
check(CA._follow_up_own_words(FOLLOW_UP) == OWN, "own words = what the person typed, before the rewrite")
check(CA._follow_up_own_words(OWN) == "", "a message with no rewrite has no 'own words' (first message: nothing changes)")
check(CA._follow_up_own_words("") == "" and CA._follow_up_own_words(None) == "", "empty and None are safe")
check(CA._follow_up_own_words("a (Read with the earlier messages, this asks: x)") == "", "the lead without the line break before it is not a rewrite")
check(CA._follow_up_own_words(CA._extract_current_message(W.fold(["I was arrested under AFSPA"], FOLLOW_UP))) == OWN,
      "through the fold and _extract_current_message the own words are still just the new message")
check(W.REWRITE_LEAD == CA._FOLLOW_UP_REWRITE_FALLBACK, "the fallback lead equals web_chat.REWRITE_LEAD")

# ---------------------------------------------------------------- the merge (pure)
combined = res("single_match", [st("BNSS", "42", .45), st("BNSS", "521", .50), st("BNSS", "60", .44)], [jd("Vihaan Kumar v State of Haryana", "9", .40)])
own = res("single_match", [st("BNSS", "480", .36), st("BNSS", "482", .34), st("BNSS", "521", .50)], [])
m = CA._merge_follow_up_results(combined, own)
ids = [(x["act"], x["section_number"]) for x in m["matches"]]
check(m["state"] == "single_match", "merged state stays single_match")
check(("BNSS", "480") in ids and ("BNSS", "482") in ids, "the bail sections from the own-words search reach the merged list")
check(("BNSS", "42") in ids and ("BNSS", "521") in ids and ("BNSS", "60") in ids, "the context sections of the combined search stay")
check(len(ids) == len(set(ids)), "no section twice (BNSS 521 came from both searches)")
check(ids[0] == ("BNSS", "480"), "the person's own words come first")
check(m["judgment_matches"] == combined["judgment_matches"], "judgments kept when the own-words search has none")
check(combined["matches"][0]["section_number"] == "42" and len(combined["matches"]) == 3, "the input result is not mutated")

# caps
many_c = res("single_match", [st("BNSS", str(100 + i), .5 - i * .01) for i in range(5)], [jd("A", str(i), .5) for i in range(4)])
many_o = res("single_match", [st("BNSS", str(200 + i), .4 - i * .01) for i in range(5)], [jd("B", str(i), .5) for i in range(4)])
mm = CA._merge_follow_up_results(many_c, many_o)
check(len(mm["matches"]) == CA.FOLLOW_UP_MAX_STATUTES == 7, "statutes capped at 7 after the merge")
check(len(mm["judgment_matches"]) == CA.FOLLOW_UP_MAX_JUDGMENTS == 5, "judgments capped at 5 after the merge")
check([x["section_number"] for x in mm["matches"]][:4] == ["200", "100", "201", "101"], "interleaved: own, combined, own, combined")
check({x["case_name"] for x in mm["judgment_matches"]} == {"A", "B"}, "both searches contribute judgments")

# each judgment paragraph is its own match; the same paragraph twice is one
j1 = res("single_match", [], [jd("X v Y", "5", .5), jd("X v Y", "6", .45)])
j2 = res("single_match", [], [jd("X v Y", "5", .5)])
check(len(CA._merge_follow_up_results(j1, j2)["judgment_matches"]) == 2, "the same paragraph of a case is not listed twice, another paragraph is")

# other states
nm = res("no_match")
check(CA._merge_follow_up_results(nm, own) is own, "combined found nothing and own found something: own is used")
check(CA._merge_follow_up_results(nm, res("no_match")) == nm, "both found nothing: unchanged")
conf = res("conflicting_matches", [st("BNS", "303", .5), st("BNS", "318", .49)])
check(CA._merge_follow_up_results(conf, own) is conf, "a conflicting_matches result is left alone")
check(CA._merge_follow_up_results(combined, res("unavailable")) is combined, "own unavailable: unchanged")
check(CA._merge_follow_up_results(combined, res("no_match")) is combined, "own found nothing: unchanged")
check(CA._merge_follow_up_results(res("unavailable"), own)["state"] == "unavailable", "combined unavailable: unchanged")
check(CA._merge_follow_up_results(combined, None) is combined and CA._merge_follow_up_results(None, own) is None, "None is safe")
check(CA._merge_follow_up_results(combined, {"state": "single_match", "matches": "oops"}) is not None, "a malformed own result does not raise")
own_conf = res("conflicting_matches", [st("BNS", "303", .5)])
check(CA._merge_follow_up_results(combined, own_conf)["state"] == "single_match", "own 'conflicting_matches' adds its sections but never turns the answer into a fork")

# ---------------------------------------------------------------- the search wrapper
calls = []


def stub_search(query, **kw):
    calls.append((query, dict(kw)))
    return own if query == OWN else combined


def run_wrapper(result, message, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = CA._add_own_words_search(result, message, stub_search, **kw)
    return out, buf.getvalue()


calls.clear()
out, log = run_wrapper(combined, OWN)
check(out is combined and not calls and "CHAT_MERGE" not in log, "no rewrite: no second search, no log line, same object back")
calls.clear()
out, log = run_wrapper(combined, FOLLOW_UP, domain="freeze")
check(calls == [(OWN, {"domain": "freeze"})], "a follow-up is searched once more, on the own words only, with the caller's keyword arguments")
check(out is not combined and ("BNSS", "480") in [(x["act"], x["section_number"]) for x in out["matches"]], "and its sections are merged in")
line = [l for l in log.splitlines() if l.startswith("CHAT_MERGE ")]
check(len(line) == 1, "one CHAT_MERGE line")
rec = json.loads(line[0][len("CHAT_MERGE "):]) if line else {}
check(rec.get("merged") is True and rec.get("statutes") == [3, 3, 5], "the line holds counts: [combined, own, merged] statutes")
check(OWN not in log and "BNSS" not in log and "bail" not in log.lower(), "the line holds no words of the person and no section")


def boom(query, **kw):
    raise RuntimeError("voyage down")


buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    safe = CA._add_own_words_search(combined, FOLLOW_UP, boom)
check(safe is combined, "the second search failing leaves the first result as it was (fail-open)")

# ---------------------------------------------------------------- through _find_relevant_sections_for_turn
seen = []


def fake_find(query, **kw):
    seen.append(query)
    return own if query == OWN else (combined if query == FOLLOW_UP else res("no_match"))


orig = SR.find_relevant_sections
SR.find_relevant_sections = fake_find
try:
    with contextlib.redirect_stdout(io.StringIO()):
        seen.clear()
        r1 = CA._find_relevant_sections_for_turn(FOLLOW_UP, W.fold(["I was arrested"], FOLLOW_UP))
        q1 = list(seen)
        seen.clear()
        r2 = CA._find_relevant_sections_for_turn("is theft cognizable?", "is theft cognizable?")
        q2 = list(seen)
finally:
    SR.find_relevant_sections = orig
check(q1 == [FOLLOW_UP, OWN], "follow-up: the whole message first, then the own words")
check(("BNSS", "480") in [(x["act"], x["section_number"]) for x in r1["matches"]], "the engine's entry point returns the merged list")
check(q2 == ["is theft cognizable?"], "an ordinary message is searched exactly once, as before")

# combined finds nothing -> the old full-question fallback runs first, then the own words are tried
seen2 = []


def fake_find2(query, **kw):
    seen2.append(query)
    return own if query == OWN else res("no_match")


SR.find_relevant_sections = fake_find2
try:
    with contextlib.redirect_stdout(io.StringIO()):
        r3 = CA._find_relevant_sections_for_turn(FOLLOW_UP, "EARLIER\n\nNow the person says: " + FOLLOW_UP)
finally:
    SR.find_relevant_sections = orig
check(seen2[0] == FOLLOW_UP and seen2[-1] == OWN and len(seen2) == 3, "nothing found: whole message, then the full question (old fallback), then the own words")
check(r3["state"] == "single_match" and r3["matches"][0]["section_number"] == "480", "and the own-words result is used when the others found nothing")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
