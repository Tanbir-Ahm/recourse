"""
test_search_service.py -- search_service.py, the engine of the website's search page. Offline and free: no model, no Voyage call (a stored corpus vector stands in for the query vector), no sci-search service
(a function stands in for it). It runs on the real data of this checkout: the BNS / BNSS / IT / NI chunk files, the Act shelf, the Supreme Court title index, the Overruled Register.
1. reading the query: citations, numbers, sections (lists, old codes, a bare number next to an Act's name), Acts, words, nothing to search; the word variants and the match rule;
2. the library text: the chunk's extra matter (next chapter's heading, Schedules, Gazette block) is cut off and said so, nothing inside a section is touched; the known gaps of Recourse's own copy;
3. named sections: the section and nothing else; IPC / CrPC numbers through the table of corresponding sections; sections that do not exist say so;
4. a bare number; 5. citations (SCC, SCR, neutral, AIR) with no junk sections and no false SQL matches; 6. words: every result holds the words (or their stems); the cases, the register verdict, the mentions;
6b. round 2 of the section search (2026-10-23): one stemmed index over the library's and the shelf's sections, the chunk's extra matter kept out of it, the cache key, a failed read not kept;
7. meaning (a stored vector as the query vector): used, shared with the shelf, off when asked, failures become notes; across the shelf's Acts (floor, cap per Act), scoped to a named Act;
8. the Act shelf (ACT_SHELF=on): named sections, bare "POCSO 19", missing numbers, an Act Recourse does not hold, searches scoped to a named Act; off by default;
9. the wider search with a stand-in service; 10. odd input, failures inside, JSON, no query text in the logs, threads, scope().
Run: python -X utf8 test_search_service.py
"""
import json
import logging
import os
import re
import sys
import threading

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ.pop("ACT_SHELF", None)
os.environ.pop("SECTION_XREF", None)
os.environ["SEARCH_MEANING"] = "off"                   # no Voyage call from this file, whatever keys the machine holds: a test that wants meaning gives its own embedder and turns it on
os.environ.pop("SCI_SEARCH_URL", None)

import numpy as np

import retrieval
import search_service as S
import search_stem as ST
import semantic_retrieval as SR

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def run(q, **kw):
    kw.setdefault("meaning", False)
    return S.search(q, **kw)


def keys(res):
    return [(p["act"], p["section"]) for p in res["provisions"]]


def words(text):
    return set(S._tok(text))


def stem_cover(terms, text):
    """How many of the query words the text holds, each in any form the stemmer counts as the same word."""
    have = {ST.stem(w) for w in words(text)}
    return len({ST.stem(t) for t in terms} & have)


# ======================================================================================================================
# 1. reading the query
# ======================================================================================================================
P = S.parse_query
check(P(None)["intent"] == "empty" and P("")["intent"] == "empty" and P("   ")["intent"] == "empty", "an empty query, None and blanks: intent 'empty'")
q = P("\x00\x01  bail \x7f   conditions\n\t")
check(q["q"] == "bail conditions", "control characters are taken out and white space is collapsed")
check(len(P("a" * 5000)["q"]) == S.MAX_QUERY_CHARS, f"a query is cut to {S.MAX_QUERY_CHARS} characters")
check(P(12345)["q"] == "12345", "a number that is not a string is read as text")

cit = {
    "(2014) 8 SCC 273": ("scc", ("scc", 2014, 8, 273)),
    "2014 8 SCC 273": ("scc", ("scc", 2014, 8, 273)),
    "[2014] 8 S.C.R. 128": ("scr", ("scr", 2014, 8, 128)),
    "[2006] Supp. 10 S.C.R. 60": ("scr", ("scr", 2006, 10, 60)),
    "2014 INSC 463": ("insc", ("insc", 2014, 463)),
    "2014_INSC_463": ("insc", ("insc", 2014, 463)),
    "AIR 2014 SC 1863": ("air", ("air", 2014, 1863)),
    "1963 AIR 1094": ("air", ("air", 1963, 1094)),
    "2023 SCC OnLine SC 90": ("online", ("online", 2023, "SC", 90)),
}
for text, (kind, key) in cit.items():
    c = P(text)["citation"]
    check(c is not None and c["kind"] == kind and c["key"] == key, f"citation {text!r}: kind {kind}, key {key}")
    check(P(text)["intent"] == "citation", f"citation {text!r}: intent 'citation'")
for text in ("2014 INSC", "[2014] 8 S.C.R.", "SCC 273", "8 SCC", "INSC 463"):
    check(P(text)["citation"] is None, f"an incomplete citation {text!r} is not read as one")
check(S.citation_keys("AIR 2016 SC 4774, (2016) 10 SCC 165") == {("air", 2016, 4774), ("scc", 2016, 10, 165)}, "a citation field with two citations gives both keys")
check(S.citation_keys("2025:CHC-AS:1826") == set() and S.citation_keys("Criminal Appeal No. 511 of 2022") == set() and S.citation_keys(None) == set(), "a High Court neutral citation, a case number and None give no key")
check(S.citation_keys("(2014) 8 SCC 2731") == {("scc", 2014, 8, 2731)} and ("scc", 2014, 8, 273) not in S.citation_keys("(2014) 8 SCC 2731"), "SCC page 2731 is not page 273")

for text, want in (("17", "17"), ("section 17", "17"), ("Sec. 17A", "17A"), ("u/s 420", "420"), ("s. 66c", "66C")):
    p = P(text)
    check(p["intent"] == "number" and p["number_only"] == want, f"a bare number {text!r}: intent 'number', number {want}")

secs = {
    "IPC 420": [("IPC", "420", "420")],
    "420 IPC": [("IPC", "420", "420")],
    "section 420 of the Indian Penal Code": [("IPC", "420", "420")],
    "u/s 420 IPC": [("IPC", "420", "420")],
    "BNS 318(4)": [("BNS", "318", "318(4)")],
    "sections 103 and 105 of the BNS": [("BNS", "103", "103"), ("BNS", "105", "105")],
    "BNS 103, IPC 302": [("BNS", "103", "103"), ("IPC", "302", "302")],
    "IT Act 66C": [("ITACT", "66C", "66C")],
    "NI Act 138": [("NIACT", "138", "138")],
    "CrPC 438": [("CrPC", "438", "438")],
    "BNSS section 187(3)": [("BNSS", "187", "187(3)")],
    "BNS 1, 2, 3, 4, 5, 6": [("BNS", str(i), str(i)) for i in (1, 2, 3, 4)],
    "BNS 103 BNS 103": [("BNS", "103", "103")],
}
for text, want in secs.items():
    p = P(text)
    got = [(s["act"], s["number"], s["ref"]) for s in p["sections"]]
    check(got == want and p["intent"] == "section", f"sections in {text!r}: {want}")
check(P("IPC 420 cheating")["rest_terms"] == ["cheating"] and P("IPC 420 cheating")["intent"] == "section", "words left over after a section reference are kept as the search words")
check(P("IPC 420")["rest_terms"] == [], "a section reference alone leaves no words")

p = P("section 17 PC Act")
check(p["intent"] == "section" and [a["id"] for a in p["acts"]] == ["pc_act_1988"] and p["sections"] == [], "section 17 PC Act: the Directory's Act, no library section")
check(P("POCSO 19")["q_shelf"] == "POCSO section 19" and P("POCSO 19")["intent"] == "section", "a bare number after an Act's name gets the word 'section' for the shelf")
check(P("45 PMLA")["q_shelf"] == "section 45 PMLA", "a bare number before an Act's name gets the word 'section'")
check(P("POCSO section 19")["q_shelf"] == "POCSO section 19" and P("section 19 POCSO")["q_shelf"] == "section 19 POCSO", "a number that already follows 'section' is left alone")
check(P("PMLA 2002")["q_shelf"] == "PMLA 2002" and P("PMLA 2002")["intent"] == "act", "a year after an Act's name is not a section")
check(P("Prevention of Corruption Act, 1988")["intent"] == "act" and P("Prevention of Corruption Act, 1988")["rest_terms"] == [], "an Act's full name with its year: intent 'act', no words left")
check(P("Hindu Marriage Act section 13")["intent"] == "section" and [a["id"] for a in P("Hindu Marriage Act section 13")["acts"]] == ["hma_1955"], "an Act the library does not hold is still found by name")
check(P("Prevention of Corruption Act bribe")["intent"] == "words" and P("Prevention of Corruption Act bribe")["rest_terms"] == ["bribe"], "an Act's name plus a word: words, scoped by the Act")
check(P("dowry death")["intent"] == "words" and P("dowry death")["terms"] == ["dowry", "death"], "words: dowry death")
check(P("the section of the act on bail")["terms"] == ["bail"], "stop words and words every legal text has are not search words")
for text in ("section", "u/s", "ss.", "[2014] 8 S.C.R.", "SCC", "' OR 1=1 --", "(", "\U0001F600", "ऊपर जमानत"):
    check(P(text)["intent"] == "nothing", f"nothing to search in {text!r}")
check(P("ऊपर")["tokens"] == [], "a query in Devanagari has no English tokens")

check(S._need(1) == 1 and S._need(2) == 2 and S._need(3) == 2 and S._need(4) == 3 and S._need(5) == 3 and S._need(6) == 4 and S._need(10) == 6, "the match rule: all of one or two words, otherwise 60% and at least two")
v = S._variants("bribe")
check({"bribe", "bribed", "bribes", "bribing"} <= v, "variants of 'bribe' include bribed, bribes, bribing")
check({"condition", "conditions"} <= S._variants("conditions"), "variants of 'conditions' include 'condition'")
check({"arrest", "arrested", "arresting"} <= S._variants("arrest"), "variants of 'arrest'")
check(S._variants("17") == {"17"} and S._variants("ipc") == {"ipc"}, "numbers and short words keep one spelling")
check("section" not in P("section bail")["terms"] and "act" not in S._content_terms(["act", "bail"]), "'section' and 'act' never count as search words")

# the year of a citation, the court a citation names
for text, want in (("(2014) 8 SCC 273", 2014), ("[1992] 1 S.C.R. 638", 1992), ("2025 INSC 162", 2025), ("AIR 2014 SC 1863", 2014), ("2025:CHC-AS:1826", 2025), ("AIRONLINE 2020 SC 784", 2020),
                   ("1963 AIR 1094", 1963), ("2013 AIR SCW 6783, (2013) 15 SCC 755", 2013), ("Criminal Appeal No. 511 of 2022 (SCC/AIR reporter citation not found)", None),
                   ("CRL.REV.P. 404/2016 (Delhi HC, 10 January 2017)", None), ("R/Criminal Misc. Application No. 18659 of 2023 (Gujarat HC)", None), ("Civil Writ Jurisdiction Case No. 20349 of 2019", None), (None, None)):
    check(S._year_of_citation(text) == want, f"year of citation {text!r} is {want}")
for text, want in (("2025 INSC 162", "Supreme Court"), ("(2014) 8 SCC 273", "Supreme Court"), ("[1992] 1 S.C.R. 638", "Supreme Court"), ("AIR 2014 SC 1863", "Supreme Court"), ("2023 SCC OnLine SC 90", "Supreme Court"),
                   ("2022 LiveLaw (SC) 305", "Supreme Court"), ("2025:CHC-AS:1826", "High Court"), ("CRL.REV.P. 404/2016 (Delhi HC, 10 January 2017)", "High Court"), ("2026 SCC OnLine Del 297", None),
                   ("1963 AIR 1094", None), (None, None)):
    check(S._court_of(text) == want, f"court of citation {text!r} is {want}")

# ======================================================================================================================
# 2. the library text
# ======================================================================================================================
t, ch, tr = S._tidy_library_text("12. Something.\n(1) A rule.\nCHAPTER III\nGENERAL EXCEPTIONS")
check(t == "12. Something.\n(1) A rule." and ch == "CHAPTER III GENERAL EXCEPTIONS" and tr is None, "the next chapter's heading is cut off and returned")
t, ch, tr = S._tidy_library_text("12. Something about CHAPTER III of the Act.\n(1) The chapter heading CHAPTER IV is cited.\n(2) End.")
check(t.endswith("(2) End.") and ch is None and tr is None, "the words CHAPTER inside a section are left alone")
t, ch, tr = S._tidy_library_text("531. (1) Repealed.\n(4) Last.\nTHE FIRST SCHEDULE\nCLASSIFICATION OF OFFENCES\nstuff\nDIWAKAR SINGH,\nJoint Secretary & Legislative Counsel to the Govt. of India.")
check(t == "531. (1) Repealed.\n(4) Last." and tr and "Schedules" in tr and ch is None, "the Schedules and the Gazette block are cut off and said so")
t, ch, tr = S._tidy_library_text("358. (4) Last words.\nDIWAKAR SINGH,\nJoint Secretary & Legislative Counsel to the Govt. of India.\nAND PUBLISHED BY THE CONTROLLER OF PUBLICATIONS, DELHI-110054.")
check(t == "358. (4) Last words." and tr and "signature block" in tr, "the Gazette's signature block is cut off and said so")
for code in ("BNS", "BNSS", "ITACT", "NIACT"):
    chunks = retrieval._load_statute_chunks(code)
    worst = max(((len(c["text"]) - len(S._tidy_library_text(c["text"])[0])), k) for k, c in chunks.items() if str(k)[:1].isdigit() and k != "531")
    check(worst[0] <= 300, f"{code}: tidying takes at most a chapter heading or the Gazette block from a section (most: {worst[0]} characters at section {worst[1]})")
    check(all(c["text"].startswith(S._tidy_library_text(c["text"])[0]) and S._tidy_library_text(c["text"])[0].startswith(str(k) + ".") for k, c in chunks.items() if str(k)[:1].isdigit()),
          f"{code}: what is left is always the start of the stored text, and begins with the section number")
bnss = retrieval._load_statute_chunks("BNSS")
bns = retrieval._load_statute_chunks("BNS")
t531, _, tr531 = S._tidy_library_text(bnss["531"]["text"])
check(len(bnss["531"]["text"]) > 90000 and len(t531) < 2100 and t531.startswith("531. (1) The Code of Criminal Procedure, 1973 is hereby repealed.") and tr531, "BNSS 531: the section alone (about 1,840 characters) is shown, the Schedules are said to be left out")
check(S._tidy_library_text(bns["13"]["text"])[1] == "CHAPTER III GENERAL EXCEPTIONS", "BNS 13 ends with the heading of Chapter III in Recourse's chunk: returned as next_chapter")
check(S._tidy_library_text(bns["358"]["text"])[2] and "signature block" in S._tidy_library_text(bns["358"]["text"])[2], "BNS 358: the Gazette's signature block is said to be left out")

for key in (("BNSS", "183"), ("BNSS", "401"), ("BNSS", "480"), ("BNSS", "359")):
    note, still = S.KNOWN_GAPS[key]
    text = bnss[key[1]]["text"]
    check(S.known_gap(key[0], key[1], text) == note, f"known gap {key}: the note is shown while the defect is in the stored text")
check(S.known_gap("BNSS", "480", bnss["480"]["text"].replace("o\nthe execution", "on the execution")) is None, "known gap BNSS 480: repaired text carries no note (self-clearing)")
check(S.known_gap("BNSS", "401", bnss["401"]["text"] + "\n(10) Nothing in this section shall affect the provisions of the Probation of Offenders Act, 1958") is None, "known gap BNSS 401: repaired text carries no note")
check(S.known_gap("BNSS", "183", bnss["183"]["text"] + "\n(Signed) A. B. Magistrate.") is None, "known gap BNSS 183: repaired text carries no note")
check(S.known_gap("BNSS", "187", bnss["187"]["text"]) is None and S.known_gap("BNS", "103", "x") is None, "other sections carry no known-gap note")

# ======================================================================================================================
# 3. named sections
# ======================================================================================================================
r = run("BNSS 187")
p = r["provisions"][0]
check(r["intent"] == "section" and len(r["provisions"]) == 1 and keys(r) == [("BNSS", "187")], "BNSS 187: that section and nothing else (no words matches, no cases, no passages)")
check(p["text"] == S._tidy_library_text(bnss["187"]["text"])[0] and not p["cut"] and p["how"] == "named" and p["held"] == "library", "BNSS 187: the stored text, word for word")
check(r["cases"] == [] and r["mentions"] == [], "BNSS 187: no cases and no passages")
check(any(c["act"] == "CrPC" and c["section"] == "167" for c in p["corresponds_to"]), "BNSS 187 corresponds to CrPC 167 in the table")
check(S.BNS_COMPARED_NOTE in r["notes"] and S.TABLE_NOTE not in r["notes"], "the comparison with India Code is in the notes; the table's caveat is on the cards, not repeated as a note")
check(p["caption"].startswith(S.LIBRARY_CAPTION) and "Act No. 46 of 2023" in p["caption"], "the caption says it is Recourse's stored copy")

r = run("IPC 420")
p = r["provisions"][0]
check(keys(r) == [("BNS", "318")] and p["section_ref"] == "318(4)", "IPC 420: BNS 318, with the sub-section the table gives (318(4))")
m = p["mapped_from"]
check(m and m["act"] == "IPC" and m["section"] == "420" and not m["change"] and "IPC 420 corresponds to BNS 318(4)" in m["note"] and S.TABLE_NOTE in m["note"], "IPC 420: the mapping is stated with the table's caveat")
check({"415", "417", "418", "420"} <= {c["section"] for c in p["corresponds_to"] if c["act"] == "IPC"}, "BNS 318 corresponds to IPC 415, 417, 418, 420")
r = run("IPC 302")
check(keys(r) == [("BNS", "103")] and r["provisions"][0]["mapped_from"]["change"] and "substantively changed" in r["provisions"][0]["mapped_from"]["note"], "IPC 302 -> BNS 103: the table's 'substantively changed' flag is passed on")
r = run("CrPC 438")
check(keys(r) == [("BNSS", "482")] and r["provisions"][0]["mapped_from"]["act"] == "CrPC", "CrPC 438 -> BNSS 482")
r = run("IPC 124A")
check(r["provisions"] == [] and any("no successor" in n for n in r["notes"]) and r["hint"], "IPC 124A: no BNS section in the table: a note says so, no lookalike")
r = run("BNS 999")
check(r["provisions"] == [] and any("no section 999" in n for n in r["notes"]), "BNS 999: a note says the Act has no such section")
r = run("IT Act 43")
check(r["provisions"] == [] and any("10 sections" in n for n in r["notes"]), "IT Act 43: a note says Recourse holds only 10 sections of the IT Act")
r = run("IT Act 66C")
check(keys(r) == [("ITACT", "66C")] and "Computer" in r["provisions"][0]["text"] or keys(r) == [("ITACT", "66C")], "IT Act 66C: the section")
r = run("NI Act 138")
check(keys(r) == [("NIACT", "138")] and r["provisions"][0]["text"].startswith("138."), "NI Act 138: the section, text as stored")
check(S.BNS_COMPARED_NOTE not in r["notes"], "no BNS comparison note for an NI Act section")
r = run("sections 103 and 105 of the BNS")
check(keys(r) == [("BNS", "103"), ("BNS", "105")], "sections 103 and 105 of the BNS: both, in the order typed")
check(len(run("BNS 1, 2, 3, 4, 5, 6")["provisions"]) == S.MAX_NAMED_SECTIONS, f"at most {S.MAX_NAMED_SECTIONS} named sections")
check(len(run("BNS 103 BNS 103")["provisions"]) == 1, "the same section named twice is shown once")
for sec in ("183", "401", "480", "359"):
    pr = run(f"BNSS {sec}")["provisions"][0]
    check(pr["warning"] == S.KNOWN_GAPS[("BNSS", sec)][0], f"BNSS {sec}: the known gap of Recourse's copy is shown beside the section")
check(run("BNS 103")["provisions"][0]["warning"] is None, "BNS 103: no warning")
pr = run("BNSS 531")["provisions"][0]
check(len(pr["text"]) < 2100 and pr["trimmed"] and "Schedules" in pr["trimmed"], "BNSS 531: only the section is shown and the cut is stated")
pr = run("BNS 13")["provisions"][0]
check(pr["next_chapter"] == "CHAPTER III GENERAL EXCEPTIONS" and "CHAPTER" not in pr["text"], "BNS 13: the next chapter's heading is returned apart from the text")
r = run("BNS 103 murder")
check(keys(r)[0] == ("BNS", "103") and r["provisions"][0]["how"] == "named" and len(r["provisions"]) > 1 and all(p["how"] in ("words", "both", "meaning") for p in r["provisions"][1:]), "a section plus a word: the section first, then sections that hold the word")
check(r["cases"] == [] and r["mentions"] == [], "a section plus a word: no cases")
r = run("BNS 358")
check(r["provisions"][0]["trimmed"], "BNS 358: the Gazette block is not part of the text")
r = run("IPC 420", meaning=True, embed_fn=lambda t: (_ for _ in ()).throw(AssertionError("the query vector must not be asked for a named section")))
check(keys(r) == [("BNS", "318")] and not r["meaning_used"], "a named section never asks for a query vector")

# ======================================================================================================================
# 4. a bare number
# ======================================================================================================================
r = run("17")
check(r["intent"] == "number" and keys(r) == [("BNS", "17"), ("BNSS", "17")] and all(p["how"] == "number" for p in r["provisions"]), "17: BNS 17 and BNSS 17 (the shelf is off)")
check(r["cases"] == [] and r["mentions"] == [], "17: no cases and no passages")
r = run("section 66C")
check(keys(r) == [("ITACT", "66C")], "section 66C: the only library Act with a 66C is the IT Act")
r = run("999")
check(r["provisions"] == [] and r["hint"] and r["suggestions"] == [], "999: nothing held under that number: a hint")
r = run("302")
check(("BNS", "302") in keys(r) and [x["query"] for x in r["suggestions"]] == ["IPC 302", "CrPC 302"], "302: the BNS and BNSS sections held, and the old codes' 302 offered as 'IPC 302' / 'CrPC 302'")
r = run("498A")
check(r["provisions"] == [] and [x["query"] for x in r["suggestions"]] == ["IPC 498A"] and not r["hint"], "498A: no section of the new codes, but 'IPC 498A' is offered")
check(run(r["suggestions"][0]["query"])["provisions"][0]["section"] == "85", "the offered query 'IPC 498A' gives BNS 85")
check(run("BNSS 187")["suggestions"] == [] and run("dowry death")["suggestions"] == [], "suggestions only for a bare number")

# ======================================================================================================================
# 5. citations
# ======================================================================================================================
r = run("(2014) 8 SCC 273")
check(r["intent"] == "citation" and r["provisions"] == [] and r["mentions"] == [] and len(r["cases"]) == 1, "an SCC citation: the case only (no sections, no passages)")
c = r["cases"][0]
check(c["title"] == "Arnesh Kumar v State of Bihar" and c["held"] == "library" and c["how"] == "citation" and c["court"] == "Supreme Court" and c["year"] == 2014, "(2014) 8 SCC 273: Arnesh Kumar, reviewed library, Supreme Court, 2014")
check(c["tier"] == S.TIER_LIBRARY_LABEL and c["links"] and c["links"][0]["url"].startswith("http"), "the library card has the tier label and a link")
for q in ("[2014] 8 S.C.R. 128", "2014 INSC 463", "2014_INSC_463"):
    r = run(q)
    c = r["cases"][0] if r["cases"] else {}
    check(len(r["cases"]) == 1 and c.get("title") == "Arnesh Kumar v State of Bihar" and c.get("held") == "library", f"{q}: one card, the library's Arnesh Kumar (the index row is merged into it)")
    check(c.get("scr_citation") == "[2014] 8 S.C.R. 128" and c.get("neutral") == "2014 INSC 463" and c.get("citation") == "(2014) 8 SCC 273", f"{q}: the card carries all three citations")
r = run("2014 INSC 221")
c = r["cases"][0]
check(len(r["cases"]) == 1 and c["held"] == "index" and c["tier"] == S.TIER_INDEX_LABEL and c["neutral"] == "2014 INSC 221" and c["scr_citation"] == "[2014] 9 S.C.R. 283", "an index-only case: tier label, neutral and SCR citations")
check(c["links"][0]["url"].startswith("https://indiankanoon.org/search/") and c["court"] == "Supreme Court of India", "an index-only case links to an Indian Kanoon search (no judgment link is held) and names its court")
check(run("2014 INSC 99999")["cases"] == [] and "SCC or AIR citation" in run("2014 INSC 99999")["hint"], "a citation that is not found: no cases and a hint that says what can be found by citation")
r = run("[2014] 18 S.C.R. 128")
check(all(("scr", 2014, 18, 128) in S.citation_keys(c.get("scr_citation")) for c in r["cases"]) and not any(c["title"].startswith("Arnesh") for c in r["cases"]), "[2014] 18 S.C.R. 128 is not [2014] 8 S.C.R. 128 (no loose SQL match)")
for q, name in (("AIR 2014 SC 1863", "National Legal Services Authority v Union of India"), ("2023 SCC OnLine SC 90", "Usha Chakraborty v State of West Bengal"), ("AIR 2016 SC 4774", "Hiral P. Harsora v Kusum Narottamdas Harsora"),
                ("(2016) 10 SCC 165", "Hiral P. Harsora v Kusum Narottamdas Harsora"), ("[2006] Supp. 10 S.C.R. 60", "Hori Lal v State of Uttar Pradesh"), ("1963 AIR 1094", "Pyare Lal Bhargava v State of Rajasthan")):
    r = run(q)
    check([c["title"] for c in r["cases"]][:1] == [name], f"{q}: {name}")
check(run("(2014) 8 SCC 2730")["cases"] == [], "(2014) 8 SCC 2730 is not 273")

# ======================================================================================================================
# 6. words
# ======================================================================================================================
r = run("dowry death")
check(keys(r)[0] == ("BNS", "80"), "dowry death: BNS 80 first")
check(all({"dowry"} & words(p["text"]) or {"dowries"} & words(p["text"]) for p in r["provisions"]) and all("death" in words(p["text"]) or "deaths" in words(p["text"]) for p in r["provisions"]), "dowry death: every section shown holds both words")
r = run("bail conditions")
need = 2
check(r["provisions"] and all(len(({"bail", "bails", "bailed", "bailing"} & words(p["text"])) | ({"condition", "conditions", "conditioned"} & words(p["text"]))) >= 1 for p in r["provisions"]), "bail conditions: every section shown holds the words")
check(all(stem_cover(["bail", "conditions"], p["text"]) == 2 for p in r["provisions"]), "bail conditions: both words (in any usual form) in each section")
check(("BNSS", "482") in keys(r) and ("BNSS", "480") in keys(r), "bail conditions: BNSS 482 and 480 among the sections")
check(all(p["how"] in ("words", "both") for p in r["provisions"]) and not r["meaning_used"], "words only when meaning is off")
check(all(len(p["text"]) <= S.TEXT_CAP_FOUND for p in r["provisions"]), "a section found by words is cut at the shorter cap")
r = run("arrest grounds information accused custody remand magistrate")
seven = ("arrest", "grounds", "information", "accused", "custody", "remand", "magistrate")
check(r["provisions"] and all(stem_cover(seven, p["text"]) >= S._need(7) for p in r["provisions"]), "a seven-word query: every section holds at least 5 of the words (in any usual form)")
check(run("zzzqqq")["provisions"] == [] and run("zzzqqq")["hint"], "words that match nothing: a hint")
r = run("arnesh kumar")
check(r["cases"] and r["cases"][0]["title"] == "Arnesh Kumar v State of Bihar" and r["cases"][0]["how"] == "name", "arnesh kumar: the library case first, found by name")
check(r["cases"][0]["passages"] == [], "a case found by name carries no passages of its own (they only repeat its name and its list of equivalent citations)")
names_c = {c["title"] for c in r["cases"]}
names_m = {c["title"] for c in r["mentions"]}
check(not (names_c & names_m), "a case is either in 'cases' or in 'mentions', never both")
check(all(p["text"] and "\n" not in p["text"] and len(p["text"]) <= S.EXCERPT_CAP + 4 for c in r["mentions"] for p in c["passages"]), "every passage is one line of at most the excerpt cap")
check(all(len(c["passages"]) <= S.MAX_PASSAGES_PER_CASE for c in r["cases"] + r["mentions"]) and len(r["mentions"]) <= S.MAX_MENTIONS, "passages and mentions are capped")
check(all(c["status"] and c["status"]["text"] for c in r["cases"] + r["mentions"]), "every case carries a status sentence")
r = run("mohan lal")
c = next(c for c in r["cases"] if c["title"].startswith("Mohan Lal v State of Punjab"))
check(c["status"]["source"] == "register" and "reported as overruled" in c["status"]["text"] and "not yet confirmed by our reviewer" in c["status"]["text"], "Mohan Lal: the Overruled Register's sentence is shown beside the case")
r = run("youth bar association")
c = r["cases"][0]
check(c["status"] == {"source": "not_checked", "text": "Not checked by us.", "detail": None}, "a case with no card and no register row: the fixed sentence 'Not checked by us.'")
r = run("arnesh kumar")
c = r["cases"][0]
check(c["status"]["source"] == "card_quiet" and c["status"]["text"].startswith("No adverse later judgment found by our automatic check") and c["status"]["detail"], "a quiet card: the short sentence, the full one as detail")
r = run("subramanian swamy juvenile justice board")
check(any(c["held"] == "index" and "SUBRAMANIAN SWAMY" in c["title"].upper() for c in r["cases"]), "the title index finds a case by words of its title")
check(all(c["how"] in ("name", "close", "citation") for c in r["cases"]), "case matches are labelled name / close")
close = run("lata singh state of uttar pradesh crime")
check((not any(c["how"] == "close" for c in close["cases"])) or S.CLOSE_NOTE in close["notes"], "a close (not exact) title match carries the warning note")
check(run("arnesh kumar") == run("arnesh kumar"), "the same search twice gives the same result")
check(run("Arnesh Kumar v. State of Bihar")["cases"][0]["title"] == "Arnesh Kumar v State of Bihar", "'Arnesh Kumar v. State of Bihar' finds the case with its full name")
r = run("lalita kumari")
c = r["cases"][0]
check(c["held"] == "library" and c["neutral"] == "2013 INSC 748" and c["scr_citation"] == "[2013] 14 S.C.R. 713", "Lalita Kumari: the index's 'GOVT. OF U.P.' row is the library's 'Government of Uttar Pradesh' case (one card, with all citations)")
check([x["held"] for x in r["cases"]].count("library") == 1 and len(r["cases"]) == 2, "Lalita Kumari: the 2012 reference order stays a separate index card")
check(run("lalita kumari up")["cases"][0]["title"] == "Lalita Kumari v Government of Uttar Pradesh", "'up' finds 'Uttar Pradesh' in a case name")
check(S._name_tokens("Satender Kumar Antil v Central Bureau of Investigation (2026)") == S._name_tokens("SATENDER KUMAR ANTIL v CENTRAL BUREAU OF INVESTIGATION AND ANR."), "a year in a case name is not part of its words")
r = run("kumar")
check(len(r["cases"]) >= 3 and len(r["cases"]) <= S.MAX_CASES, "a surname: several cases, within the cap")
r = run("Hindu Marriage Act cruelty")
check(r["provisions"] == [] and r["acts"] and r["acts"][0]["id"] == "hma_1955" and not r["acts"][0]["held"], "an Act Recourse does not hold: its card, and no section of another Act in its place")
check(any("does not hold the text of the Hindu Marriage Act, 1955" in n for n in r["notes"]), "the note says Recourse does not hold the Act's text")
check(r["acts"][0]["url"].startswith("https://indiacode.gov.in/") and r["acts"][0]["url_verified"], "the card links to India Code (the Directory's checked link)")
r = run("Hindu Marriage Act section 13")
check(r["provisions"] == [] and r["cases"] == [] and r["mentions"] == [] and len(r["acts"]) == 1, "section 13 of an Act not held: the Act's card only (not BNS 13)")
r = run("section 17 PC Act")
check(r["provisions"] == [] and r["acts"] and not r["acts"][0]["held"], "section 17 PC Act with the shelf off: the Act is not held, no BNS 17 in its place")

# ======================================================================================================================
# 6b. words, round 2: the stems, and one index over every section
# ======================================================================================================================
os.environ.pop("ACT_SHELF", None)
r = run("punishment for murder")
p103 = next((p for p in r["provisions"] if (p["act"], p["section"]) == ("BNS", "103")), None)
check(keys(r)[:1] == [("BNS", "103")] and p103 is not None, "punishment for murder: BNS 103 first")
check("punishment" not in words(p103["text"]) and "punished" in words(p103["text"]), "... though the section says 'punished', not 'punishment' (the words are matched by their stems)")
r = run("abetting suicide")
check(keys(r)[:1] == [("BNS", "108")], "abetting suicide: BNS 108 first ('abetment of suicide' in the Act)")
r = run("arrested without warrant")
check(r["provisions"] and all(stem_cover(["arrested", "without", "warrant"], p["text"]) >= 2 for p in r["provisions"]) and ("BNSS", "35") in keys(run("arrest police without warrant cognizable")), "arrested without warrant: sections that hold the words in their usual forms; BNSS 35 comes for the longer query")
ix = S._section_index({})
d531 = next(d for d in ix["docs"] if (d["act"], d["section"]) == ("BNSS", "531"))
check(len(d531["text"]) < 5000 and "SCHEDULE" not in d531["text"].upper() and len(retrieval._load_statute_chunks("BNSS")["531"]["text"]) > 50000, "BNSS 531 is indexed without the Schedules that Recourse's chunk runs together with it (they would match nearly every query)")
check(all(d["held"] == "library" for d in ix["docs"]) and {d["act"] for d in ix["docs"]} == {"BNS", "BNSS", "ITACT", "NIACT"} and len(ix["docs"]) > 900, "the shelf off: the index holds the library's four Acts only")
check(S._section_index({}) is ix, "the index is built once")
os.environ["ACT_SHELF"] = "on"
a1, a2 = S._section_index(S._shelf_state()), S._section_index(S._shelf_state())
check(a1 is a2 and a1 is not ix and any(d["held"] == "shelf" for d in a1["docs"]), "the shelf on: one index with the shelf's sections, built once although the shelf dict is rebuilt for every search")
check({d["act"] for d in a1["docs"]} >= {"BNS", "PCACT", "POCSO"} and len(a1["docs"]) > len(ix["docs"]) + 300, "... library and shelf sections in the one index")
os.environ.pop("ACT_SHELF")
check(S._section_index(S._shelf_state()) is not a1 and not any(d["held"] == "shelf" for d in S._section_index(S._shelf_state())["docs"]), "the shelf switched off again: the index is rebuilt without the shelf's sections")
real_load = retrieval._load_statute_chunks
retrieval._load_statute_chunks = lambda code: (_ for _ in ()).throw(RuntimeError("disk"))
S._CACHE.pop("section_ix", None)
check(S._section_index({}) is None and run("bail")["provisions"] == [], "the library cannot be read and the shelf is off: nothing to search, no crash")
retrieval._load_statute_chunks = real_load
check(S._section_index({}) is not None and len(S._section_index({})["docs"]) > 900 and run("bail")["provisions"], "a failed read of the library is not kept: the next search has the full index")
r = run("bail")
check(all("bail" in {ST.stem(w) for w in words(p["text"])} for p in r["provisions"]), "bail: every section holds the word (by stem)")
check(S.word_provisions([], None, {}, 5) == [] and S.word_provisions(["bail"], None, {}, 0) == [], "no words or no room: nothing")
real_mo = S._meaning_order
S._meaning_order = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("meaning list broke"))
r_ = S.word_provisions(["bail"], [0.1] * 1024, {}, 5)
S._meaning_order = real_mo
check(r_ and all(p["how"] == "words" for p in r_), "the meaning part failing inside the provisions search: the word matches still come")

# ======================================================================================================================
# 7. meaning (a stored corpus vector stands in for the query vector)
# ======================================================================================================================
corpus = SR._load_corpus_embeddings()
index = {r_["chunk_id"]: i for i, r_ in enumerate(corpus["records"])}


def vec(chunk_id):
    return lambda text: list(corpus["matrix"][index[chunk_id]])


calls = []


def counting(chunk_id):
    f = vec(chunk_id)

    def g(text):
        calls.append(text)
        return f(text)
    return g


os.environ["SEARCH_MEANING"] = "on"                    # from here to the end of section 7 every test brings its own embedder
r = S.search("pre arrest protection from police", embed_fn=counting("statute:BNSS:482"))
check(r["meaning_used"] and ("BNSS", "482") in keys(r), "meaning: the section closest to the query vector is found")
p482 = next(p for p in r["provisions"] if p["section"] == "482")
check(p482["how"] in ("meaning", "both") and len(calls) == 1, "meaning: asked for the vector once")
calls.clear()
r = S.search("pre arrest protection from police", meaning=False, embed_fn=counting("statute:BNSS:482"))
check(not calls and not r["meaning_used"], "meaning=False: the vector is not asked for")
os.environ["SEARCH_MEANING"] = "off"
r = S.search("pre arrest protection from police", embed_fn=counting("statute:BNSS:482"))
check(not calls and not r["meaning_used"], "SEARCH_MEANING=off: the vector is not asked for")
os.environ["SEARCH_MEANING"] = "on"
real_embed = S._embed_query
asked_default = []
S._embed_query = lambda text: (asked_default.append(text) or vec("statute:BNSS:482")(text))
r = S.search("pre arrest protection from police")
check(asked_default == ["pre arrest protection from police"] and r["meaning_used"] and ("BNSS", "482") in keys(r), "meaning on and no embedder given: the Voyage embedder is the default (stood in for here)")
S._embed_query = real_embed
# the real embedder, with the Voyage client stood in for: a short timeout (a person is waiting), one retry, the cost noted under its own label
import types as _types
seen_kw, noted = {}, []


class _FakeClient:
    def __init__(self, **kw):
        seen_kw.update(kw)

    def embed(self, texts, **kw):
        seen_kw["embed_kw"] = kw
        return _types.SimpleNamespace(embeddings=[[0.0] * 1024], total_tokens=7)


import cost_log
real_voyage_mod, real_note, real_key = sys.modules.get("voyageai"), cost_log.note_voyage, SR._resolve_voyage_api_key
sys.modules["voyageai"] = _types.SimpleNamespace(Client=_FakeClient)
cost_log.note_voyage = lambda label, model, tokens: noted.append((label, model, tokens))
SR._resolve_voyage_api_key = lambda: "k"
vec_ = S._embed_query("bail conditions")
sys.modules["voyageai"] = real_voyage_mod if real_voyage_mod is not None else sys.modules.pop("voyageai")
cost_log.note_voyage, SR._resolve_voyage_api_key = real_note, real_key
check(len(vec_) == 1024 and seen_kw.get("timeout") == S.EMBED_TIMEOUT == 8 and seen_kw.get("max_retries") == 1 and seen_kw["embed_kw"].get("input_type") == "query", "the query embedding: voyage-law-2, input type 'query', a short timeout and one retry")
check(noted == [("search_page_query_embed", SR.MODEL, 7)], "its cost is noted under the search page's own label, with no text")
r = S.search("pre arrest protection from police", embed_fn=lambda t: (_ for _ in ()).throw(RuntimeError("voyage down")))
check(not r["meaning_used"] and any("Meaning search was not available" in n for n in r["notes"]) and r["provisions"], "a failing embedder: a note, and the word matches still come")
r = S.search("pre arrest protection from police", embed_fn=lambda t: [0.1, 0.2])
check(not r["meaning_used"] and any("Meaning search was not available" in n for n in r["notes"]), "a vector of the wrong size: a note, no crash")
r = S.search("pre arrest protection from police", embed_fn=lambda t: [0.0] * 1024)
check(r["meaning_used"] and all(p["how"] == "words" for p in r["provisions"]), "a vector far from everything: no meaning matches, the word matches stay")
r = S.search("pre arrest protection from police", embed_fn=vec("statute:BNSS:482"))
check(all(p["how"] in ("words", "both", "meaning") for p in r["provisions"]) and all(isinstance(p["score"], float) for p in r["provisions"]), "scores are plain floats")
calls.clear()
S.search("17", embed_fn=counting("statute:BNSS:482"))
S.search("BNSS 187", embed_fn=counting("statute:BNSS:482"))
S.search("(2014) 8 SCC 273", embed_fn=counting("statute:BNSS:482"))
check(not calls, "a number, a section and a citation ask for no query vector")
os.environ["SEARCH_MEANING"] = "off"

# ======================================================================================================================
# 8. the Act shelf
# ======================================================================================================================
os.environ["ACT_SHELF"] = "on"
import act_shelf
SH = act_shelf.load()["acts"]
r = run("section 17 PC Act")
check(keys(r) == [("PCACT", "17")] and r["provisions"][0]["held"] == "shelf" and r["provisions"][0]["how"] == "named", "section 17 PC Act (shelf on): section 17 of the Prevention of Corruption Act")
p = r["provisions"][0]
check(p["text"] == SH["pc_act_1988"]["by_num"]["17"]["text"][:S.TEXT_CAP_ASKED], "the shelf section is India Code's text as stored, word for word")
check("Official text from India Code" in p["caption"] and "not yet read by our reviewer" in p["caption"], "the shelf caption says whose text it is and that no reviewer has read it")
check(r["acts"] and r["acts"][0]["held"] and r["acts"][0]["sections"] == len(SH["pc_act_1988"]["ranked"]) and r["acts"][0]["url"].startswith("https://indiacode.gov.in/"), "the Act's card: held, number of sections, official link")
check(S.BNS_COMPARED_NOTE not in r["notes"], "no BNS comparison note for a shelf section")
for q, want in (("POCSO 19", ("POCSO", "19")), ("PMLA 45", ("PMLA", "45")), ("45 PMLA", ("PMLA", "45")), ("pc act section 7", ("PCACT", "7")), ("UAPA 43D", ("UAPA", "43D")), ("PC Act 17", ("PCACT", "17")),
                ("section 13 of the Prevention of Corruption Act", ("PCACT", "13")), ("POCSO Act 2012 section 19", ("POCSO", "19"))):
    r = run(q)
    check(keys(r)[:1] == [want] and r["intent"] == "section", f"{q}: {want[0]} section {want[1]}")
r = run("sections 3 and 4 of POCSO")
check(keys(r) == [("POCSO", "3"), ("POCSO", "4")], "sections 3 and 4 of POCSO: both")
r = run("section 99 PC Act")
check(r["provisions"] == [] and any("no section 99" in n for n in r["notes"]), "section 99 PC Act: a note that the Act has no section 99")
r = run("BNS 103 and PMLA 45")
check(keys(r) == [("BNS", "103"), ("PMLA", "45")], "BNS 103 and PMLA 45: a library section and a shelf section together")
r = run("Hindu Marriage Act section 13")
check(r["provisions"] == [] and r["acts"] and not r["acts"][0]["held"], "the shelf on, an Act it does not hold: still only the Act's card")
r = run("UAPA")
check(r["intent"] == "act" and r["provisions"] == [] and r["acts"][0]["held"] and "section number" in r["hint"], "an Act alone: its card and a hint to add a section or words")
whole = [aid for aid, st in SH.items() if st.get("whole")]
check(bool(whole), "the shelf has at least one very short Act handed over whole")
import act_directory
D = act_directory.load()["by_id"]
for aid in whole:
    alias = D[aid]["aliases"][0]
    r = run(alias)
    check(r["intent"] == "act" and len(r["provisions"]) == min(len(SH[aid]["ranked"]), S.MAX_PROVISIONS) and all(p["how"] == "whole" for p in r["provisions"]), f"{alias!r}: a very short Act gives its sections")
r = run("17")
JJ = SH["jj_act_2015"]["code"]
check(keys(r)[:2] == [("BNS", "17"), ("BNSS", "17")] and ("PCACT", "17") in keys(r) and (JJ, "17") in keys(r), "17 with the shelf on: the section of every Act that has one")
check(all(p["how"] == "number" for p in r["provisions"]) and len({(p["act"], p["section"]) for p in r["provisions"]}) == len(r["provisions"]), "17: each Act once")
r = run("bribe")
check(("PCACT", "7") in keys(r) and ("PCACT", "8") in keys(r) and all(p["held"] == "shelf" for p in r["provisions"] if p["act"] == "PCACT"), "bribe: sections 7 and 8 of the Prevention of Corruption Act by words (bribed, bribing)")
r = run("Prevention of Corruption Act bribe")
check(r["provisions"] and all(p["act"] == "PCACT" for p in r["provisions"]) and ("PCACT", "7") in keys(r), "an Act's name plus a word: only that Act's sections (never the BNS or BNSS)")
r = run("pocso bail")
check(all(p["act"] == "POCSO" for p in r["provisions"]), "pocso bail: only POCSO sections")
r = run("juvenile justice board")
check(any(p["act"] == SH["jj_act_2015"]["code"] for p in r["provisions"]) and any(p["act"] in ("BNS", "BNSS") for p in r["provisions"]) and all(p["held"] in ("library", "shelf") for p in r["provisions"]), "no Act named: library and shelf sections together")
firsts = [p["held"] for p in r["provisions"][:4]]
check("library" in firsts and "shelf" in firsts, "library and shelf sections stand in one ranking (both among the first four)")
os.environ["SECTION_XREF"] = "on"
r = run("section 17 PC Act")
check(keys(r)[0] == ("PCACT", "17") and all(p["how"] in ("named", "cited") for p in r["provisions"]), "SECTION_XREF=on: the sections that section 17 cites follow it")
os.environ.pop("SECTION_XREF")
calls.clear()
os.environ["SEARCH_MEANING"] = "on"
r = S.search("Prevention of Corruption Act bribe taken by clerk", embed_fn=counting("statute:BNS:318"))
check(len(calls) == 1 and r["meaning_used"], "an Act plus words: one query vector for the corpus and the shelf together")
# meaning across the Acts on the shelf (round 2): a stored section vector stands in for the query vector, and no word of the query matches anything
os.environ["SEARCH_MEANING"] = "on"


def shelf_vec(aid, number):
    st_ = SH[aid]
    j = next(i for i, c in enumerate(st_["ranked"]) if str(c["section_number"]) == number)
    return [float(x) for x in st_["matrix"][j]]


v = shelf_vec("muslim_women_act_2019", "3")
r = S.search("zzzqqq", embed_fn=lambda t: v)
check(r["meaning_used"] and keys(r)[:1] == [("MWACT", "3")] and r["provisions"][0]["how"] == "meaning" and r["provisions"][0]["held"] == "shelf", "meaning across the Acts: a query close to a section of an Act that was not named finds that section first")
rv = np.random.default_rng(3).normal(size=1024)
rv = [float(x) for x in rv / np.linalg.norm(rv)]
r = S.search("zzzqqq", embed_fn=lambda t: rv)
check(r["meaning_used"] and r["provisions"] == [], "a query vector close to nothing: no section by meaning (the floors)")
jj = SH["jj_act_2015"]
mean = jj["matrix"].mean(axis=0)
mean = [float(x) for x in mean / np.linalg.norm(mean)]
r = S.search("zzzqqq", embed_fn=lambda t: mean)
n_jj = sum(1 for p in r["provisions"] if p["act"] == jj["code"])
check(0 < n_jj <= S.SHELF_MEANING_PER_ACT, f"no Act fills the list by meaning: at most {S.SHELF_MEANING_PER_ACT} sections of one Act ({n_jj} here)")
v = shelf_vec("pocso_act_2012", "7")
r = S.search("POCSO zzzqqq", embed_fn=lambda t: v)
check(r["provisions"] and all(p["act"] == "POCSO" for p in r["provisions"]) and ("POCSO", "7") in keys(r)[:3], "naming the Act: only its sections, the closest by meaning first (never a section of the BNS or BNSS)")
v = shelf_vec("pc_act_1988", "7")
r = S.search("bribe", embed_fn=lambda t: v)
p7 = next(p for p in r["provisions"] if (p["act"], p["section"]) == ("PCACT", "7"))
check(p7["how"] == "both" and ("PCACT", "7") in keys(r)[:2] and keys(r).index(("PCACT", "7")) < next(i for i, p in enumerate(r["provisions"]) if p["how"] == "meaning"), "a section that holds the word and is close in meaning is labelled 'both' and comes before the ones found by meaning alone")
check(all(isinstance(p["score"], float) and p["score"] > 0 for p in r["provisions"]), "every section carries its score")
# the library's own statute records still reach the list by meaning when no Act is named
r = S.search("zzzqqq", embed_fn=vec("statute:BNSS:482"))
check(keys(r)[:1] == [("BNSS", "482")] and r["provisions"][0]["how"] == "meaning", "a library section close in meaning is found with the shelf on as well")
os.environ["SEARCH_MEANING"] = "off"
os.environ.pop("ACT_SHELF")
r = run("POCSO 19")
check(r["provisions"] == [] and r["acts"] and not r["acts"][0]["held"], "the shelf off: 'POCSO 19' is an Act Recourse does not hold")

# ======================================================================================================================
# 9. the wider search (a function stands in for the sci-search service)
# ======================================================================================================================
FAKE = {"ok": True, "as_of": "2026-08-12", "results": [
    {"rank": 1, "doc": "d1", "case_name": "Mohan Lal v. State of Punjab", "date": "2018-07-24", "paragraph": 12, "link": "https://example.org/1", "link_kind": "pdf", "text": "reasoning " * 100, "citations": {"scr": "[2018] 8 S.C.R. 1"}},
    {"rank": 2, "doc": "d1", "case_name": "Mohan Lal v. State of Punjab", "date": "2018-07-24", "paragraph": 13, "link": "https://example.org/1", "text": "same document again"},
    {"rank": 3, "doc": "d2", "case_name": "Some Case v. State", "date": "2020-01-01", "paragraph": "4", "link": "javascript:alert(1)", "link_kind": "pdf", "text": "passage two"},
    {"rank": 4, "doc": "d3", "case_name": "Needs Review", "name_to_review": True, "date": "2021-01-01", "text": "skip me"},
    {"rank": 5, "doc": "d4", "case_name": "", "date": "2021-01-01", "text": "no name"},
]}
asked = []
r = S.search("search and seizure", mode="wider", sci_fn=lambda t: (asked.append(t) or FAKE))
w = r["wider"]
check(r["mode"] == "wider" and r["provisions"] == [] and r["cases"] == [] and r["mentions"] == [] and asked == ["search and seizure"], "wider: only the wider search runs, with the query as typed")
check(w["available"] and [i["title"] for i in w["items"]] == ["Mohan Lal v. State of Punjab", "Some Case v. State"], "wider: one item per document; passages marked for review and nameless ones are left out")
check(w["items"][0]["status"]["source"] == "register" and "reported as overruled" in w["items"][0]["status"]["text"], "wider: the register's sentence beside a wider-search case")
check(w["items"][1]["status"] == {"source": "not_checked", "text": "Not checked by us."}, "wider: 'Not checked by us.' beside the others")
check(w["items"][1]["link"] is None and w["items"][1]["link_kind"] is None and w["items"][0]["link"] == "https://example.org/1", "wider: only web links are passed on")
check(len(w["items"][0]["excerpt"]) <= S.EXCERPT_CAP + 4 and w["as_of"] == "2026-08-12", "wider: excerpts are cut, the index date is passed on")
check(w["label"] == "(from a wider search, not independently verified)" and w["tier"].startswith("Wider search (not independently verified)"), "wider: the label and the tier name")
many = {"ok": True, "results": [{"rank": i, "doc": f"d{i}", "case_name": f"Case {i} v. State", "date": "2020-01-01", "paragraph": "1", "text": "t"} for i in range(30)]}
check(len(S.search("bail", mode="wider", sci_fn=lambda t: many)["wider"]["items"]) == S.MAX_WIDER, f"wider: at most {S.MAX_WIDER} items")
check(S.search("search seizure", mode="wider", sci_fn=lambda t: None)["wider"]["note"] == S.WIDER_UNAVAILABLE, "wider: the service answers nothing: a note")
check(S.search("search seizure", mode="wider", sci_fn=lambda t: (_ for _ in ()).throw(RuntimeError("down")))["wider"]["note"] == S.WIDER_UNAVAILABLE, "wider: the service fails: a note, no crash")
check(S.search("search seizure", mode="wider")["wider"]["note"] == S.WIDER_UNAVAILABLE, "wider: SCI_SEARCH_URL unset: a note")
asked.clear()
for q in ("17", "(2014) 8 SCC 273", "section"):
    rr = S.search(q, mode="wider", sci_fn=lambda t: (asked.append(t) or FAKE))
    check(rr["wider"]["note"] == S.WIDER_NEEDS_WORDS and not rr["wider"]["items"], f"wider: {q!r} needs words: the service is not called")
check(not asked, "wider: the service was not called for a number, a citation or no words")
check(S.search("search seizure", mode="wider", sci_fn=lambda t: {"ok": True, "results": []})["wider"]["note"] == "The wider search found no passage for these words.", "wider: no passage: a note")
check(S.search("x", mode="nonsense")["mode"] == "library", "an unknown mode is the library search")

# ======================================================================================================================
# 10. odd input, failures inside, JSON, logs, threads, scope
# ======================================================================================================================
KEYS = {"q", "mode", "intent", "acts", "provisions", "cases", "mentions", "wider", "suggestions", "elsewhere", "notes", "meaning_used", "scope_note", "hint"}
weird = [None, 123, "\x00\x01 bail \x7f", "a" * 5000, "\"*()-:", "' OR 1=1 --", "section", "u/s", "v", "ऊपर जमानत", "\U0001F600", "NEAR(a b)", "AND OR NOT", "2014 INSC", "INSC 463",
         "[2014] 8 S.C.R.", "SCC", "(", ")" * 50, "%", "_", "\\", "'; DROP TABLE cases; --", "<script>alert(1)</script>", "IPC", "BNS", "section 0", "section 99999", "BNS 0", "IPC 0"]
bad = []
for w in weird:
    try:
        rr = S.search(w)
        if not KEYS <= set(rr) or not isinstance(rr["notes"], list) or rr["scope_note"] != S.SCOPE_NOTE:
            bad.append(w)
        json.dumps(rr)
    except Exception as exc:  # noqa: BLE001
        bad.append((w, repr(exc)))
check(not bad, f"odd input never raises and always returns every key as JSON-serialisable data ({bad[:3]})")
check(run("")["hint"] and run("")["provisions"] == [] and run("")["elsewhere"] == [], "an empty query: a hint, nothing else")
check(run("bail")["elsewhere"] and run("bail")["elsewhere"][0]["url"].startswith("https://indiankanoon.org/search/?formInput="), "a link to an Indian Kanoon search for the same words")

# JSON for every kind of result, with the shelf on and off
for flag in (None, "on"):
    if flag:
        os.environ["ACT_SHELF"] = flag
    for q in ("BNSS 187", "IPC 420", "17", "(2014) 8 SCC 273", "2014 INSC 221", "arnesh kumar", "dowry death", "section 17 PC Act", "Prevention of Corruption Act bribe", "Hindu Marriage Act section 13", "UAPA", "mohan lal"):
        try:
            json.dumps(run(q))
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check(ok, f"the result of {q!r} (shelf {flag or 'off'}) is JSON-serialisable")
os.environ.pop("ACT_SHELF", None)

# failures inside
import case_lookup
import register_hooks
orig_cl, orig_cs, orig_lex = S.library_cases, register_hooks.case_status, SR.lexical_search
case_lookup_orig = case_lookup.search_cases_detailed
case_lookup.search_cases_detailed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("index down"))
r = run("arnesh kumar")
check(any("title index is not available" in n for n in r["notes"]) and r["cases"], "the title index fails: a note, the library cases still come")
case_lookup.search_cases_detailed = case_lookup_orig
register_hooks.case_status = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("register down"))
r = run("arnesh kumar")
check(r["cases"] and all(c["status"]["source"] == "not_checked" and c["status"]["text"] == "Not checked by us." for c in r["cases"]), "the register fails: every case says 'Not checked by us.'")
register_hooks.case_status = orig_cs
SR.lexical_search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("index missing"))
r = run("bail conditions")
check(any("could not be searched" in n for n in r["notes"]), "the word index fails: a note")
check(keys(run("BNSS 187")) == [("BNSS", "187")], "a named section does not need the word index")
SR.lexical_search = orig_lex
with S._LOCK:
    S._CACHE.pop("library", None)
S.library_cases = lambda: (_ for _ in ()).throw(RuntimeError("no library"))
r = run("arnesh kumar")
check(isinstance(r["notes"], list) and KEYS <= set(r), "the library list fails: the search still answers")
S.library_cases = orig_lex and orig_cl
check(len(S.library_cases()) == 68, "the library list: 68 distinct cases")

# no query text in the logs
logger = logging.getLogger("search_service")
records = []


class Grab(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


h = Grab()
logger.addHandler(h)
old_level = logger.level
logger.setLevel(logging.DEBUG)
SR.lexical_search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("zqxjkw"))
case_lookup.search_cases_detailed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("zqxjkw"))
S.search("zqxjkw secret bail words", embed_fn=lambda t: (_ for _ in ()).throw(RuntimeError("zqxjkw")))
S.search("zqxjkw secret IPC 420", mode="wider", sci_fn=lambda t: (_ for _ in ()).throw(RuntimeError("zqxjkw")))
SR.lexical_search = orig_lex
case_lookup.search_cases_detailed = case_lookup_orig
logger.removeHandler(h)
logger.setLevel(old_level)
check(records and not any("zqxjkw" in m or "secret" in m for m in records), f"the log lines name the kind of failure, never the query ({len(records)} lines)")

# threads
os.environ["ACT_SHELF"] = "on"
qs = ["section 17 PC Act", "bribe", "BNSS 187", "arnesh kumar", "dowry death", "17", "POCSO 19", "(2014) 8 SCC 273"]
expected = {q: json.dumps(run(q), sort_keys=True) for q in qs}
out, errs = {}, []


def worker(i):
    try:
        for q in qs:
            out[(i, q)] = json.dumps(run(q), sort_keys=True)
    except Exception as exc:  # noqa: BLE001
        errs.append(repr(exc))


threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
[t.start() for t in threads]
[t.join() for t in threads]
check(not errs and all(out[(i, q)] == expected[q] for i in range(8) for q in qs), "eight threads searching at once get the same results as one thread")
sc = S.scope()
check({s["act"]: s["sections"] for s in sc["statutes"]} == {"BNS": 358, "BNSS": 531, "ITACT": 10, "NIACT": 19}, "scope(): the sections held of BNS, BNSS, the IT Act and the NI Act")
check(len(sc["shelf"]) == 11 and sc["library_cases"] == 68 and sc["indexed_cases"] and sc["indexed_cases"] > 30000, "scope(): eleven shelf Acts, 68 library cases, the Supreme Court index")
os.environ.pop("ACT_SHELF")
check(S.scope()["shelf"] == [], "scope(): no shelf Acts while ACT_SHELF is off")
check(S.warm() is None, "warm() runs and returns nothing")

print()
print(f"{len(FAILURES)} FAILED" if FAILURES else "ALL PASSED")
sys.exit(1 if FAILURES else 0)
