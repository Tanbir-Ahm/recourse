"""
test_carry_forward.py -- sections an earlier answer relied on are offered again to a follow-up (carry_forward.py, web_chat.should_carry, chat_assistant._carried_matches; owner's go 2026-11-02: "Carry the sections the earlier
answer relied on into a follow-up's search, so BNSS 482 and 483 reach Q2") and the Gaps instruction of the Research Note.  Offline and free: a stub model, the library's real text.
Run: python -X utf8 test_carry_forward.py
"""
import contextlib
import io
import json
import os
import sys
import types

os.environ.pop("ACT_SHELF", None)
os.environ.pop("RELEVANCE_GATE", None)
os.environ["CHAT_MODE"] = "on"

import carry_forward as C
import chat_assistant as CA
import web_chat as W

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def stat(act, num, text="x"):
    return {"type": "statute", "act": act, "section_number": num, "text": text}


Q1 = "Does an anticipatory bail order expire after a fixed period, or can it continue until the end of the trial?"
A1 = {"state": "single_match", "response_text": "Section 482 of the BNSS lets a person apply for pre-arrest bail. Section 483(3) of the BNSS allows the court to direct arrest. Sections 480 and 482 are different.",
      "matches": [stat("BNSS", "482"), stat("BNSS", "483"), stat("BNSS", "35"), stat("BNSS", "480"), {"type": "judgment", "case_name": "A v. B", "text": "t", "act": None},
                  dict(stat("BNSS", "58"), retrieval="cited")]}
T1 = [{"q": Q1, "answer": A1}]

# 1. which sections are carried
refs = C.refs_from_turns(T1)
check([(r["act"], r["section"]) for r in refs] == [("BNSS", "482"), ("BNSS", "483"), ("BNSS", "480")], f"the sections the answer's text names, in the order of the matches ({refs})")
check(("BNSS", "35") not in [(r["act"], r["section"]) for r in refs], "a section that was handed over but never named in the answer is not carried")
check(len(C.refs_from_turns(T1, limit=2)) == 2, "at most `limit` sections")
check(C.refs_from_turns([{"q": "x", "answer": {"state": "no_match"}}, {"q": "y", "answer": {"state": "unrelated"}}]) == [] and C.refs_from_turns([]) == [] and C.refs_from_turns(None) == [], "no answer, a refusal or small talk: nothing")
T2 = T1 + [{"q": "and what about bail?", "answer": {"state": "single_match", "response_text": "Section 480 of the BNSS covers bail in bailable offences.", "matches": [stat("BNSS", "480")]}}]
check([r["section"] for r in C.refs_from_turns(T2)][:1] == ["480"] and len({(r["act"], r["section"]) for r in C.refs_from_turns(T2)}) == len(C.refs_from_turns(T2)), "latest answer first, no repeats")
check(C._named_in("Section 482 of the BNSS", "482") and C._named_in("sections 482 and 483", "483") and C._named_in("s. 482(1)", "482") and not C._named_in("the 1482 cases", "482") and not C._named_in("Section 4821", "482") and not C._named_in("482 alone", "482"),
      "'named' means the word section (or s.) a few words before the number, the number a whole token")
sh = dict(stat("PMLA", "45"), act_key="pmla_2002", source="act_shelf")
# ranking within one answer (2026-11-12): the section the answer leans on comes first, whatever order the sections were handed over in
def _sh(num):
    return {"type": "statute", "act": "MVACT", "act_key": "mv_act_1988", "section_number": num, "text": "x", "source": "act_shelf"}
_txt = ("**Bottom line** Section 185 of the Motor Vehicles Act is the charge. Section 206(4) governs the licence and under Section 206(4) it goes to the licensing authority. Section 203(3) allows arrest. "
        "Section 185 punishes the first offence with six months. For a first offence under Section 185 the bracket is lower. Section 205 and Section 204 add little.")
_T = [{"q": "q", "answer": {"state": "single_match", "response_text": _txt, "matches": [_sh("203"), _sh("205"), _sh("204"), _sh("185"), _sh("206")]}}]
_r = [x["section"] for x in C.refs_from_turns(_T)]
check(_r[0] == "185" and "206" in _r and len(_r) == C.MAX_CARRIED == 4, f"the section named most often comes first and the limit is four ({_r})")
check([x["section"] for x in C.refs_from_turns(_T, limit=1)] == ["185"], "with a limit of one it is the section the answer leans on")
check(C.refs_from_turns([{"q": "q", "answer": {"state": "single_match", "response_text": "Section 45 of the PMLA restricts bail.", "matches": [sh]}}]) == [{"act": "PMLA", "section": "45", "act_key": "pmla_2002"}], "a shelf section is carried with its Act's key")

# 2. when it is carried
check(W.should_carry("used", "Can the court cancel it later?") and W.should_carry("unchanged", "Can the court cancel it later, and on what grounds, if the accused misuses it?"), "the rewrite judged it a follow-up: carry")
check(not W.should_carry("new_topic", "My neighbour has stolen my goat and refuses to return it, what can I do about it now?"), "a new topic that does not point back: nothing")
check(W.should_carry("new_topic", "what about him?") and W.should_carry("failed", "Can the court cancel it later?") and W.should_carry("off", "is that bailable?"), "a short message that points back is carried whatever the rewrite said")
check(W.should_carry("dropped_guard:number_not_in_person_messages", "what are the other sections my client can be charged with? and how can i counter them? give detailed explanations") and W.should_carry("dropped_guard:case_name_not_in_person_messages", "and the other charges?"), "a rewrite dropped by the guard was still judged a follow-up: carry (staging 2026-11-09)")
check(not W.should_carry("failed", "Tell me about the law of cheating in a business partnership dispute"), "a long message that does not point back, no rewrite: nothing")
out, info = W.question_for_engine(T1, "Can the court cancel it later, and on what grounds?", call=lambda prompt, cur: ('{"follow_up": true, "standalone": "Can the court cancel an anticipatory bail order later, and on what grounds?"}', 0.1))
check(info["rewrite"] == "used" and [(r["act"], r["section"]) for r in info["carry"]] == [("BNSS", "482"), ("BNSS", "483"), ("BNSS", "480")], f"question_for_engine: the record carries the sections ({info})")
check("482" not in out and "483" not in out and "BNSS" not in out, "...and no section number is put into the question string (the person's own words only)")
out, info = W.question_for_engine(T1, "what other sections can he be charged with and how do I counter them?", call=lambda prompt, cur: ('{"follow_up": true, "standalone": "What other sections than 482 and 999 can he be charged with?"}', 0.1))
check(info["rewrite"].startswith("dropped_guard:") and [(r["act"], r["section"]) for r in info["carry"]] == [("BNSS", "482"), ("BNSS", "483"), ("BNSS", "480")] and "999" not in out, f"question_for_engine: a rewrite the guard drops still carries the earlier sections, and its words do not reach the engine ({info})")
out, info = W.question_for_engine(T1, "My neighbour has stolen my goat and refuses to return it, what can I do about it now?", call=lambda prompt, cur: ('{"follow_up": false, "standalone": "x"}', 0.1))
check(info["carry"] == [], "a new topic: nothing carried")
out, info = W.question_for_engine([], "first question")
check(info["carry"] == [] and out == "first question", "the first question: nothing")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    W.log_turn("q", {"turn": 2, "rewrite": "used", "folded": 1, "rewrite_inr": 0.1, "carry": [{"act": "BNSS", "section": "482"}, {"act": "BNSS", "section": "483"}]})
rec = json.loads(buf.getvalue().split(" ", 1)[1])
check(rec["carry"] == ["BNSS 482", "BNSS 483"], f"the CHAT_TURN line names the carried sections, never text ({rec})")

# 3. the engine
sent = {}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Bail can be cancelled under Section 483(3) of the BNSS.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
CA.classify_scope = lambda q: ("in_scope", "arrest", None)
LIB = {"v": {"state": "single_match", "matches": [dict(stat("BNSS", "142", "142. Discharge of persons imprisoned for failing to give security."), source="semantic", all_variants={})], "judgment_matches": []}}
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: LIB["v"]
CA._fetch_pilot_related_judgments = lambda *a, **k: []
import answer_cache
answer_cache.get_cached = lambda m: None
answer_cache.record_candidate = lambda *a, **k: None


def ask(carried):
    sent.clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = CA.answer_question("Can the court cancel it later, and on what grounds?", audience=None, carried_sections=carried)
    return res, buf.getvalue()


res, out = ask([{"act": "BNSS", "section": "482"}, {"act": "BNSS", "section": "483"}])
p = sent.get("prompt", "")
got = {(m.get("act"), m.get("section_number")): m for m in res["matches"] if m.get("type") == "statute"}
check(("BNSS", "482") in got and ("BNSS", "483") in got and ("BNSS", "142") in got, f"the follow-up's matches hold the carried sections beside what its own search found ({sorted(got)})")
check(got[("BNSS", "482")].get("retrieval") == "carried" and "482" in got[("BNSS", "482")]["text"][:12] and len(got[("BNSS", "482")]["text"]) > 300, "...with the library's own text of the section, marked 'carried'")
check("Relied on in your earlier answer in this same conversation" in p and p.count("Relied on in your earlier answer in this same conversation") == 2, "the prompt says why the two sections are there")
check("CARRY_FORWARD " in out and json.loads(out.split("CARRY_FORWARD ", 1)[1].splitlines()[0]) == {"offered": ["BNSS 482", "BNSS 483"], "added": ["BNSS 482", "BNSS 483"]}, "one CARRY_FORWARD log line: the sections offered and added, never text")
check(getattr(CA._CARRIED, "refs", None) is None, "the carried list is cleared when the question ends")
res, out = ask(None)
check(not any(m.get("retrieval") == "carried" for m in res["matches"]) and "CARRY_FORWARD" not in out and "Relied on in your earlier answer" not in sent["prompt"], "no carried sections: exactly as before")
LIB["v"] = {"state": "single_match", "matches": [dict(stat("BNSS", "482", "482. (1) When any person has reason to believe ..."), source="semantic", all_variants={})], "judgment_matches": []}
res, out = ask([{"act": "BNSS", "section": "482"}, {"act": "BNSS", "section": "483"}])
check(sum(1 for m in res["matches"] if m.get("act") == "BNSS" and m.get("section_number") == "482") == 1 and sum(1 for m in res["matches"] if m.get("act") == "BNSS" and m.get("section_number") == "483" and m.get("retrieval") == "carried") == 1,
      "a section the follow-up's own search found is not added twice; the other is carried")
res, out = ask([{"act": "BNSS", "section": "99999"}, {"act": "NOSUCHACT", "section": "1"}, {"act": "", "section": ""}])
check(res["state"] == "single_match" and not any(m.get("retrieval") == "carried" for m in res["matches"]), "a section that cannot be fetched is left out; the answer goes on")
LIB["v"] = {"state": "no_match"}
res, out = ask([{"act": "BNSS", "section": "483"}])
check(res["state"] == "single_match" and any(m.get("retrieval") == "carried" for m in res["matches"]), "the follow-up's own search finds nothing: the carried section alone still reaches the answer (as any curated section does)")

# 4. the API path hands the list to the engine only when there is one
import api.engine_adapter as EA
seen = {}


class _Eng:
    @staticmethod
    def answer_question(question, inline_domains=None, audience=None, channel=None, **kw):
        seen["kw"] = kw
        return {"state": "no_match"}


EA.set_engine(_Eng)
EA.work("q", "layman", lambda *a: None)
check(seen["kw"] == {}, "the API passes no extra argument when nothing is carried (an engine without the argument still works)")
EA.work("q", "layman", lambda *a: None, carried=[{"act": "BNSS", "section": "482"}])
check(seen["kw"] == {"carried_sections": [{"act": "BNSS", "section": "482"}]}, "...and the list when there is one")
EA.set_engine(None)

# 5. the Research Note's Gaps instruction
L = CA.RESPONSE_GENERATION_PROMPT_V3_LAWYER
check('Do NOT say in this part that a case comes from a wider search or is unverified or unreviewed' in L and "each case that comes only from the wider search" not in L and "What our register says about a case is still stated in the sentence that mentions the case" in L,
      "Gaps: no restating that a case is from the wider search or unverified; the register's sentence beside a case stays")


def hard(t):
    return t[t.index("## Hard rules (never break)"):t.index("## What to include, what to leave out")]


check(hard(CA.RESPONSE_GENERATION_PROMPT) == hard(CA.RESPONSE_GENERATION_PROMPT_V3) == hard(L), "the Hard rules block is identical in every style")

print()
if FAILURES:
    print(len(FAILURES), "FAILED:", FAILURES)
    sys.exit(1)
print("ALL PASSED")
