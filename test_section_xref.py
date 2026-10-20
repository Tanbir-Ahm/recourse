"""
test_section_xref.py -- SECTION_XREF (act_shelf.cited_sections / _add_cited, section_rule._cites, act_directory._cited_clause, the page; default OFF, effective only with ACT_SHELF on). Added 2026-10-20 after the owner's
staging test of the section 17 questions (Prevention of Corruption Act): section 17's second proviso says "an offence referred to in [clause (b) of sub-section (1)] of section 13 shall not be investigated without the
order of a police officer not below the rank of a Superintendent of Police", and section 13(1)(b) with its Explanation 1 is the disproportionate-assets offence, but section 13 never reached the answer model (its meaning
score against the question, 0.174, was under the 0.22 floor) and nothing followed the reference.
What the switch does: a section the person asked about, that cites another section of its OWN Act by number, brings that section too (at most two, none over 4,000 characters, none from a section that cites more than two),
the prompt says so, and the grey box under the answer carries the cited section's official text word for word.  A reference to another enactment ("section 8 of the Code of Criminal Procedure, 1973") is skipped.
No network, no model, no cost: question vectors are stored section vectors; the model is a stub.
Run: python -X utf8 test_section_xref.py
"""
import contextlib
import io
import json
import os
import re
import sys
import types

import numpy as np

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("ACT_SHELF", "ACT_DIRECTORY", "ACT_DETECT", "CHAT_MODE", "SECTION_RULE", "SECTION_XREF", "REGISTER_HOOKS", "RESPONSE_STYLE", "SCOPE_GATE", "SCI_SEARCH_MODE", "ANCHORS", "GROUNDING_CHECKS", "PASSAGE_NOTES"):
    os.environ.pop(_v, None)

import act_directory as AD
import act_shelf as S
import chat_assistant as CA
import section_rule as R

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def boom(text):
    raise AssertionError("the test reached the real Voyage call")


S._embed_query = boom
EMB = json.load(open(os.path.join(S.SHELF_DIR, "shelf_embeddings.json"), encoding="utf-8"))
VEC = {r["chunk_id"]: np.array(r["embedding"], dtype=float) for r in EMB["records"]}


def like(code, sec):
    return lambda text: VEC[f"act:{code}:{sec}"]


PC = "pc_act_1988"
SH = S.load()
os.environ["ACT_SHELF"] = "on"
ST = SH["acts"][PC]
s13 = ST["by_num"]["13"]["text"]
s17 = ST["by_num"]["17"]["text"]
ACTS = [{"id": PC, "short": "Prevention of Corruption Act, 1988", "how": "named"}]
Q1 = "Can a disproportionate assets case under PC act be filed without section 17 approval?"

# ---------------------------------------------------------------- the switch
for v, want in ((None, False), ("", False), ("off", False), ("banana", False), ("on", True), (' "ON" ', True), ("On", True)):
    if v is None:
        os.environ.pop("SECTION_XREF", None)
    else:
        os.environ["SECTION_XREF"] = v
    check(S.xref_enabled() is want, f"SECTION_XREF={v!r}: {'on' if want else 'off'} (default OFF)")
os.environ.pop("SECTION_XREF", None)

# ---------------------------------------------------------------- the owner's case: section 17 cites section 13; the Code of Criminal Procedure is skipped
c17, i17 = S.cited_sections(ST, "17")
check(c17 == ["13"] and i17 == {}, f"section 17 of the PC Act cites section 13 and nothing else ({c17})")
check("section 8 of the Code of Criminal Procedure, 1973" in s17 and "8" not in c17 and "8" in ST["by_num"], "...although section 17 also says 'section 8 of the Code of Criminal Procedure, 1973' and the PC Act has a section 8 of its own: that reference is skipped")
check("Notwithstanding anything contained in the Code of Criminal Procedure, 1973" in s17 and S.cited_sections(ST, "17A") == ([], {}), "section 17A cites nothing of its own Act's (it names the Code only); section 13 cites nothing")
check(S.cited_sections(ST, "13") == ([], {}), "section 13 itself cites no other section")
check(S.cited_sections(ST, "18") == (["17"], {}), "section 18 (the officer empowered to investigate 'under section 17') cites section 17")
c19, i19 = S.cited_sections(ST, "19")
check(c19 == [] and i19 == {"fanout": 4}, f"section 19 cites four sections (7, 11, 13, 15): none is followed, and the log says how many ({c19}, {i19})")
check(S.cited_sections(ST, "6") == (["3", "5"], {}), "section 6 cites 3 and 5 (two: followed); its 'section 260 of the Code of Criminal Procedure' and 'sections 262 to 265 ... of the said Code' are skipped")
check(S.cited_sections(ST, "999") == ([], {}) and S.cited_sections(ST, None) == ([], {}) and S.cited_sections({}, "17") == ([], {}) and S.cited_sections(None, "17") == ([], {}), "an unknown section, None, an empty Act, None: ([], {}), no error")

# ---------------------------------------------------------------- the other-enactment test, case by case
T = lambda tail: S._tied_elsewhere(tail, PC)
CASES = {
    " of the Code of Criminal Procedure, 1973 (2 of 1974), of an Assistant Commissioner of Police": True,
    " shall not be investigated without the order of a police officer not below the rank of a Superintendent of Police.": False,
    " to 265 (both inclusive) of the said Code shall, as far as may be": True,
    " of the Companies Act, 1956 (1 of 1956); (x) any person": True,
    " (45 of 1860) or section 153B of the Indian Penal Code": True,
    " of this Act for that area": False,
    " of the Prevention of Corruption Act, 1988 applies": False,
    " and [Chapter XXVI] of the [Code].": True,
    " of the Persons with Disabilities (Equal Opportunities, Protection of Rights and Full Participation) Act, 1995": True,
    " of that Code; and (ii) the arrest": True,
    " of the Act, before the Court of Sessions": True,
    ", sub-section (1) of section 12AA] and any additional information": False,
    " of the Cr.P.C. read with": True,
    " of Chapter III of this Act": False,
    " of the Delhi Special Police Establishment Act, 1946": True,
    "": False,
}
bad = [(k, want, T(k)) for k, want in CASES.items() if T(k) != want]
check(not bad, f"{len(CASES)} 'which enactment follows the number' cases: {bad or 'all right'}")
check(S._tied_elsewhere("", "no_such_act") is False and S._tied_elsewhere(None or "", PC) is False, "an unknown Act or an empty tail: not tied elsewhere, no error")

# ---------------------------------------------------------------- reference forms, on a synthetic Act
def fake(**sections):
    by = {n: {"text": t, "omitted": n in ("OM",)} for n, t in sections.items()}
    return {"key": PC, "by_num": by}


syn = fake(**{
    "1": "1. Title.\nA person who contravenes section 2 shall be punished.",
    "2": "2. Definitions.\nThe rule.",
    "3": "3. Another.\nThe rule.",
    "4": "4. Yet another.\nThe rule.",
    "5": "5. Fifth.\nThe rule.",
    "OM": "OM. Omitted.\n[Omitted.]",
    "10": "10. Self.\nSection 10 applies; see also section 10 of this Act and section 3 of this Act.",
    "11": "11. Note.\nThe rule is as in section 4.\n[Note: Subs. by Act 16 of 2018, s. 3 (w.e.f. 26-7-2018); see also section 5 as inserted.]",
    "12": "12. Amending.\nThe rule applies to section 2 [Subs. by the Amendment Act, 2013 (3 of 2013), s. 3 (w.e.f. 1-2-2013)].",
    "13": "13. Plural.\nSections 2, 3 and 4 apply, and section 5 or 7 years of imprisonment.",
    "20": "20. Plural two.\nSections 2 and 3 apply.",
    "21": "21. Singular.\nThe term shall be section 4 or 5 years of imprisonment.",
    "14": "14. Absent.\nThe rule applies to section 99 and to section OM of this Act.",
    "15": "15. List shares a name.\nA person under section 2, or as the case may be under section 3 of the Commissions for Protection of Child Rights Act, 2005 (4 of 2006), shall act.",
    "16": "16. Mixed.\nUnder section 2 of this Act and section 3 of the Code of Criminal Procedure, 1973 (2 of 1974), and section 4.",
    "17": "17. Range.\nSections 2 to 3 of the said Code apply, and section 4 of this Act.",
    "18": "18. Abbrev.\nSection 2 of the Cr.P.C. and section 3 of the IPC and section 4 apply.",
    "19": "19. Fanout.\nSections 2, 3, 4 and 5 apply.",
})
check(S.cited_sections(syn, "1") == (["2"], {}), "'section 2' in an ordinary sentence is a citation")
check(S.cited_sections(syn, "10") == (["3"], {}), "a section that cites itself ('section 10') does not follow itself; 'section 3 of this Act' is followed")
check(S.cited_sections(syn, "11") == (["4"], {}), "a reference inside India Code's '[Note: ...]' paragraph (an amending Act's section 3, 'section 5 as inserted') is not read")
check(S.cited_sections(syn, "12") == (["2"], {}), "an amending Act's 's. 3 (w.e.f. ...)' after '(3 of 2013),' is not a citation")
check(S.cited_sections(syn, "13") == ([], {"fanout": 4}), "'Sections 2, 3 and 4' and 'section 5' are four sections: fan-out, none followed")
check(S.cited_sections(syn, "20") == (["2", "3"], {}), "'Sections 2 and 3' (plural) are two sections")
check(S.cited_sections(syn, "21") == (["4"], {}), "'section 4 or 5 years' (singular 'section') is section 4 only: the 5 is a number of years, not a section (and the Act does have a section 5)")
check(S.cited_sections(syn, "14") == ([], {}), "a number the Act does not have (99) and an omitted section: not followed")
check(S.cited_sections(syn, "15") == ([], {}), "'section 2, or as the case may be under section 3 of the Commissions ... Act, 2005': one name for the whole enumeration, so neither is this Act's")
check(S.cited_sections(syn, "16") == (["2", "4"], {}), "a sentence that cites a section of this Act, then one of the Code, then another of this Act: only the Code's is skipped")
check(S.cited_sections(syn, "17") == (["4"], {}), "'Sections 2 to 3 of the said Code' (a range of the Code) is skipped; 'section 4 of this Act' is followed")
check(S.cited_sections(syn, "18") == (["4"], {}), "'section 2 of the Cr.P.C.' and 'section 3 of the IPC' are skipped by their abbreviations")
check(S.cited_sections(syn, "19") == ([], {"fanout": 4}), "four citations: fan-out, none followed")
check(S.MAX_FANOUT == S.MAX_CITED == 2, "the limits: at most two cited sections, all or none")

# ---------------------------------------------------------------- the sweep over the nine Acts: invariants, and nothing for an Act whose text did not pass
total = with_c = fan = 0
broken = []
for aid, st in SH["acts"].items():
    if not st.get("ok"):
        continue
    for n, c in st["by_num"].items():
        total += 1
        cites, info = S.cited_sections(st, n)
        with_c += bool(cites)
        fan += bool(info.get("fanout"))
        if len(cites) > S.MAX_FANOUT or n in cites or any(x not in st["by_num"] or st["by_num"][x].get("omitted") for x in cites) or (cites and info):
            broken.append((aid, n, cites, info))
check(total == 396 and not broken, f"all nine Acts, {total} sections: no section follows itself, an absent or omitted section, or more than {S.MAX_FANOUT} ({broken[:3]})")
check(with_c >= 80 and fan >= 10, f"...{with_c} sections cite one or two sections of their own Act, {fan} cite more (none followed)")

# ---------------------------------------------------------------- the search
def got(res):
    return [(m["section_number"], m["retrieval"]) for m in res["matches"]]


base = S.search(Q1, ACTS, embed_fn=like("PCACT", "17A"))
check(not any(m["retrieval"] == "cited" for m in base["matches"]) and "cited" not in base["info"]["per_act"][PC], "SECTION_XREF off (default): no cited section, no new key in the log record: the search is as before")
os.environ["SECTION_XREF"] = "on"
on = S.search(Q1, ACTS, embed_fn=like("PCACT", "17A"))
g = got(on)
check(g[0] == ("17", "named") and ("13", "cited") in g and ("17A", "meaning") in g, f"on: section 17 named, 17A by meaning, section 13 CITED ({g})")
m13 = [m for m in on["matches"] if m["section_number"] == "13"][0]
check(m13["text"] == s13 and m13["cited_by"] == "17" and m13["source"] == "act_shelf" and m13["shelf"]["text_status"] == "machine_checked", "...section 13 whole, word for word, marked cited by 17, with the shelf's own source data")
m17 = [m for m in on["matches"] if m["section_number"] == "17"][0]
check(m17.get("cites") == ["13"], "...and section 17's own match says it cites 13")
check(on["info"]["per_act"][PC]["cited"] == [{"s": "13", "by": "17"}], "...the log record (ACT_SHELF line) says what was added and for which section")
check([x for x in g if x[0] == "13"] == [("13", "cited")], "section 13 is there once")
off_ids = [x for x in got(base) if x[1] != "cited"]
check([x for x in g if x[1] != "cited"] == off_ids, "everything else is exactly what it was without the switch (same sections, same order)")
r19 = S.search("What does section 19 of the PC Act say?", ACTS, embed_fn=like("PCACT", "19"))
check(not any(m["retrieval"] == "cited" for m in r19["matches"]) and r19["info"]["per_act"][PC]["cite_skipped"] == [{"by": "19", "why": "cites 4 sections"}], f"section 19: four citations, none followed; the log record says why ({r19['info']['per_act'][PC].get('cite_skipped')})")
r6 = S.search("What does section 6 of the PC Act say?", ACTS, embed_fn=like("PCACT", "14"))
check(sorted(x[0] for x in got(r6) if x[1] == "cited") == ["3", "5"], "section 6: both cited sections come (3 and 5)")
r17_13 = S.search("Do sections 17 and 13 of the PC Act apply?", ACTS, embed_fn=like("PCACT", "17A"))
g2 = got(r17_13)
check([x for x in g2 if x[0] == "13"] == [("13", "named")] and "cited" not in r17_13["info"]["per_act"][PC], f"a cited section the person also named stays 'named' and is not added twice ({[x for x in g2 if x[0] == '13']})")
check([m for m in r17_13["matches"] if m["section_number"] == "17"][0].get("cites") == ["13"], "...and section 17 still says it cites 13")
rm = S.search(Q1, ACTS, embed_fn=like("PCACT", "13"))
gm = got(rm)
check([x for x in gm if x[0] == "13"] == [("13", "meaning")] and [m for m in rm["matches"] if m["section_number"] == "17"][0].get("cites") == ["13"] and "cited" not in rm["info"]["per_act"][PC],
      f"a cited section that the meaning search already brought stays 'meaning', is not added again, and section 17 still says it cites 13 ({[x for x in gm if x[0] == '13']})")
saved = S.CITED_MAX_CHARS
S.CITED_MAX_CHARS = 500
rl = S.search(Q1, ACTS, embed_fn=like("PCACT", "17A"))
check(not any(m["retrieval"] == "cited" for m in rl["matches"]) and rl["info"]["per_act"][PC]["cite_skipped"] == [{"s": "13", "by": "17", "why": "too long"}], "a cited section over the length limit is not added (a section is never cut); the log says so")
S.CITED_MAX_CHARS = saved
saved = S.MAX_CITED
S.MAX_CITED = 1
rc = S.search("What does section 6 of the PC Act say?", ACTS, embed_fn=like("PCACT", "14"))
check(sorted(x[0] for x in got(rc) if x[1] == "cited") == ["3"] and rc["info"]["per_act"][PC]["cite_skipped"] == [{"s": "5", "by": "6", "why": "cap"}], "the cap: with room for one, the first is added and the second is logged as skipped")
S.MAX_CITED = saved
rb = S.search("What does section 8 of the BNS say?", ACTS, embed_fn=like("PCACT", "7"))
check(not any(m["retrieval"] == "cited" for m in rb["matches"]), "a section only found by meaning, never asked about, is not followed")
ri = S.search("No section 17 order exists for this case of disproportionate assets", ACTS, embed_fn=like("PCACT", "17A"))
check(("17", "implied") in got(ri) and ("13", "cited") in got(ri), "a bare 'section 17' in a conversation about the Act (implied) is followed too")
os.environ["SECTION_RULE"] = "off"
rr = S.search(Q1, ACTS, embed_fn=like("PCACT", "17A"))
check(("13", "cited") in got(rr), "SECTION_RULE=off with SECTION_XREF=on: the named section is still followed (a separate switch)")
os.environ.pop("SECTION_RULE")
MW = "muslim_women_act_2019"
rw = S.search("What does section 5 of the Muslim Women Act, 2019 say?", [{"id": MW, "short": "Muslim Women Act", "how": "named"}], embed_fn=boom)
check(not any(m["retrieval"] == "cited" for m in rw["matches"]) and all(m["retrieval"] in ("named", "whole") for m in rw["matches"]), "an Act handed over whole: nothing is added, it is all there")

# ---------------------------------------------------------------- held_state and the prompt
hs = S.held_state(on["matches"], ACTS)
check(hs[PC]["named"] == ["17"] and hs[PC]["cited"] == [{"by": "17", "section": "13"}], f"held_state: the cited section is listed with the section that cites it ({hs})")
check("cited" not in S.held_state(base["matches"], ACTS)[PC], "...and not at all without the switch")
pb = AD.prompt_block(ACTS, held=hs)
check("- Section 17 refers to section 13 of the same Act, which is also in the material above (marked as cited by the section asked about)." in pb, "the prompt says section 17 refers to section 13, which is in the material")
check("say in one sentence, in your own words and from that text only, what the cited section covers, so that the person can see which kind of case the reference concerns." in pb and "Do not go beyond the words of the cited section" in pb, "...and asks for one sentence on what it covers, from its text only, without going beyond it")
check(pb.startswith(AD.prompt_block(ACTS, held={PC: {"state": "used", "loaded_on": hs[PC]["loaded_on"]}})), "...it is added after the blocks that existed before, which are unchanged")
check("## The section the person asked about" in pb and pb.count("## The section the person asked about") == 1, "...inside the one clause about the asked section")
pb_off = AD.prompt_block(ACTS, held=S.held_state(base["matches"], ACTS))
check("refers to" not in pb_off and pb_off == pb.replace(pb[pb.index("- Section 17 refers to"):], ""), "without the switch the prompt has no such bullet, byte for byte what it was")
two = {PC: {"state": "used", "loaded_on": "2026-10-17", "named": ["6"], "cited": [{"by": "6", "section": "3"}, {"by": "6", "section": "5"}]}}
check("Section 6 refers to sections 3 and 5 of the same Act, which are also in the material above" in AD.prompt_block(ACTS, held=two), "two cited sections: 'sections 3 and 5 ... which are also in the material'")
stray = {PC: {"state": "used", "loaded_on": "2026-10-17", "named": ["17"], "cited": [{"by": "99", "section": "13"}]}}
check("refers to" not in AD.prompt_block(ACTS, held=stray), "a cited section whose citing section is not one the person asked about: no bullet")
check(AD._cited_clause(ACTS[0], ["17"], None) == "" and AD._cited_clause(ACTS[0], ["17"], []) == "" and AD._cited_clause(ACTS[0], [], [{"by": "17", "section": "13"}]) == "", "no cited sections, an empty list, no asked section: '' and no error")
check("## Hard rules" not in AD._prompt_named([(ACTS[0], ["17"])], {PC: [{"by": "17", "section": "13"}]}), "the clause is not a copy of the Hard rules block, and does not touch it")

# ---------------------------------------------------------------- the notes: the cited section under the asked one, word for word
ANS = "Section 17 of the Prevention of Corruption Act, 1988 has a main rule and two provisos. The first proviso lets the State Government authorise an Inspector. The second proviso needs an officer not below Superintendent of Police."
nt = R.notes(ANS, on["matches"])
check(len(nt) == 1 and nt[0]["section"] == "17" and nt[0]["kind"] == "official", f"the note for section 17 is as before ({[(n['section'], n['kind']) for n in nt]})")
cs = nt[0].get("cites") or []
check(len(cs) == 1 and cs[0]["section"] == "13" and cs[0]["texts"] == [s13.strip()] and cs[0]["cut"] is False, "...and carries section 13's whole official text, word for word")
check(cs[0]["lead"] == "Section 17 of the Prevention of Corruption Act, 1988 refers to section 13 of the same Act. So that you can read what the reference points to, here is the official text of section 13, as loaded from India Code:", f"...under one plain sentence that says nothing about what it means ({cs[0]['lead']})")
check("Explanation 1.--A person shall be presumed to have intentionally enriched himself illicitly if he or any person on his behalf" in cs[0]["texts"][0] and "disproportionate to his known sources of income" in cs[0]["texts"][0], "...and the box therefore shows the disproportionate-assets wording of section 13(1)(b) and Explanation 1, whatever the model wrote")
check("cites" not in R.notes(ANS, base["matches"])[0], "without the switch: no 'cites' key")
n2 = R.notes(ANS, r17_13["matches"])
check({n["section"] for n in n2} == {"17", "13"} and all("cites" not in n or n["section"] == "17" and n["cites"] == [] for n in n2) and not any(c["section"] == "13" for n in n2 for c in n.get("cites", [])), "section 13 asked about too: it has its own note and is not repeated under section 17's")
nm = R.notes(ANS, rm["matches"])
check(nm[0].get("cites") and nm[0]["cites"][0]["section"] == "13", "a cited section that came by meaning is shown under the section that cites it as well")
junk = dict(on["matches"][0], cites=["99", None, 5])
check(R.notes(ANS, [junk]) and "cites" not in R.notes(ANS, [junk])[0], "a cites list with junk or unknown numbers: skipped, no error")
check(R._cites({}, [], "17", "X", set()) == [] and R._cites(None, None, "17", "X", set()) == [], "_cites on junk: [], no error")
long_m = [dict(m) for m in on["matches"]]
for m in long_m:
    if m["section_number"] == "13":
        m["text"] = "13. Long.\n" + ("line of text here\n" * 700)
nl = R.notes(ANS, long_m)
check(nl[0]["cites"][0]["cut"] is True and len(nl[0]["cites"][0]["texts"][0]) <= R.OFFICIAL_CHARS, "a very long cited section is cut at a line end and says so")

# ---------------------------------------------------------------- end to end, with a stub model
sent = {}
REPLY = {"text": ""}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=REPLY["text"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
CA.classify_scope = lambda q: ("in_scope", "arrest", None)
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "no_match"}
CA._fetch_pilot_related_judgments = lambda *a, **k: []
import answer_cache
answer_cache.get_cached = lambda m: None
answer_cache.record_candidate = lambda *a, **k: None


def ask(question, embed, reply):
    REPLY["text"] = reply
    sent.clear()
    S._embed_query = embed
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            res = CA._answer_question_inner(question)
    finally:
        S._embed_query = boom
    return res, buf.getvalue()


res, out = ask(Q1, like("PCACT", "17A"), ANS)
p = sent.get("prompt", "")
shelf = [(m["section_number"], m["retrieval"]) for m in res["matches"] if m.get("source") == "act_shelf"]
check(res["state"] == "single_match" and ("13", "cited") in shelf, f"end to end: section 13 reaches the answer as 'cited' ({shelf})")
check("[Prevention of Corruption Act, 1988 Section 13, Section/Para 13]\n(Cited by section 17 of the same Act, the section the person asked about.)\n13. Criminal misconduct by a public servant." in p, "the prompt shows section 13 under its own label with the line that says why it is there")
check("Explanation 1.--A person shall be presumed to have intentionally enriched himself illicitly" in p, "...with Explanation 1 (the disproportionate-assets wording) in the material the model reads")
check("- Section 17 refers to section 13 of the same Act" in p and "## Hard rules (never break)" in p and p.index("## Hard rules (never break)") < p.index("- Section 17 refers to section 13"), "the prompt carries the bullet, after the unchanged Hard rules block")
check(len([l for l in p.split("\n") if l.startswith("[Prevention of Corruption Act, 1988 Section 13,")]) == 1, "section 13 is in the prompt once")
sn = res.get("section_note") or []
check(len(sn) == 1 and sn[0].get("cites") and sn[0]["cites"][0]["section"] == "13", "the result carries section 17's note with section 13 under it")
lines = [l for l in out.splitlines() if l.startswith("SECTION_NOTE ")]
check(len(lines) == 1 and json.loads(lines[0][len("SECTION_NOTE "):]) == {"sections": ["Prevention of Corruption Act, 1988 s.17: official +cites 13"]}, f"the SECTION_NOTE log line says so, without text ({lines})")
lines = [l for l in out.splitlines() if l.startswith("ACT_SHELF ")]
check(len(lines) == 1 and json.loads(lines[0][len("ACT_SHELF "):])["per_act"][PC]["cited"] == [{"s": "13", "by": "17"}], "the ACT_SHELF log line records the cited section")
os.environ.pop("SECTION_XREF")
res, out = ask(Q1, like("PCACT", "17A"), ANS)
p = sent.get("prompt", "")
check(("13", "cited") not in [(m["section_number"], m["retrieval"]) for m in res["matches"] if m.get("source") == "act_shelf"] and "refers to section 13" not in p and "(Cited by section" not in p and not any("cites" in n for n in res.get("section_note") or []),
      "SECTION_XREF off: nothing cited, no bullet, no label, no 'cites': the answer path is as before")
os.environ["SECTION_XREF"] = "on"
os.environ.pop("ACT_SHELF")
res, out = ask(Q1, like("PCACT", "17A"), ANS)
check(not any(m.get("source") == "act_shelf" for m in res.get("matches") or []) and "SECTION_NOTE" not in out, "ACT_SHELF off (the default of the whole shelf): SECTION_XREF=on changes nothing")
os.environ["ACT_SHELF"] = "on"

# ---------------------------------------------------------------- the page
from streamlit.testing.v1 import AppTest
import whatsapp_formatter as WF

STUB = {"v": None}
CA.answer_question = lambda question, inline_domains=frozenset(), audience=None, channel=None: STUB["v"]


def page(result):
    STUB["v"] = result
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.text_area(key="text").set_value("Does section 17 of the PC Act apply?").run()
    [b for b in at.button if "Check my situation" in b.label][0].click().run()
    return at, [m.value for m in at.markdown]


reply = "Section 17 has two provisos; the second proviso needs a Superintendent of Police."
res_page = {"state": "single_match", "response_text": reply, "matches": on["matches"], "situation_detected": False, "section_note": R.notes(reply, on["matches"])}
at, vals = page(res_page)
joined = "\n".join(vals)
check(not at.exception, f"page: renders (exception={at.exception})")
check("Section 17 of the Prevention of Corruption Act, 1988 refers to section 13 of the same Act. So that you can read what the reference points to" in joined, "page: the sentence about the reference is shown")
check("13. Criminal misconduct by a public servant." in joined and "Explanation 1.--A person shall be presumed to have intentionally enriched himself illicitly" in joined, "page: section 13's official words are on the page")
i17 = [i for i, v in enumerate(vals) if "Provided further that an offence referred to in" in v]
i13 = [i for i, v in enumerate(vals) if "Explanation 1.--A person shall be presumed to have intentionally enriched himself illicitly" in v]
ifo = [i for i, v in enumerate(vals) if "Official text from India Code, loaded" in v]
check(i17 and i13 and i13[0] > i17[0] and ifo and ifo[0] > i13[0], f"page: section 13 stands directly under section 17, before the one source line ({i17[:1]}, {i13[:1]}, {ifo[:1]})")
src = [v for v in vals if "Prevention of Corruption Act, 1988 Section 13**" in v]
check(bool(src), "page: 'Read the source' lists section 13 although the answer never says 'section 13'")
res_page2 = dict(res_page, section_note=R.notes(reply, base["matches"]), matches=base["matches"])
at, vals = page(res_page2)
check(not at.exception and "refers to section 13 of the same Act" not in "\n".join(vals), "page: without the switch the result has no 'cites' and the page shows nothing about section 13")
bad_notes = [dict(R.notes(reply, on["matches"])[0], cites=[None, 5, {"lead": 1, "texts": None}])]
at, vals = page(dict(res_page, section_note=bad_notes))
check(not at.exception, "page: a malformed 'cites' is skipped, never an error on the page")
msgs = WF.format_answer_for_whatsapp(dict(res_page, act_notice=None))
check(isinstance(msgs, list) and msgs and not any("refers to section 13 of the same Act" in m for m in msgs), "WhatsApp: ignores the key (the box is not wired there, by the owner's rule)")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
