"""
test_evidence_bsa.py -- the Indian Evidence Act, 1872 and the Bharatiya Sakshya Adhiniyam, 2023 on the Act shelf (2026-10-31): the PDF-only loader (build_act_from_pdf.py), the section map (section_map.py), the counterpart
note (ea_bsa_map.py) and the data files themselves.  Offline and free.  Run: python -X utf8 test_evidence_bsa.py
"""
import json
import os
import sys

import build_act_from_pdf as P
import ea_bsa_map as M
import section_map as SM

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def jload(name):
    with open(os.path.join(HERE, "act_shelf", name), encoding="utf-8") as fh:
        return json.load(fh)


# ----------------------------------------------------------------------------------------------- the loader's pieces
j = P.join_paragraphs(["Provided that, when any", "fact is deposed to as discovered, so much", "of such information may be proved.", "(a) first item", "continues here", "Illustrations", "A police-", "officer is meant.", "Next sentence ends.", "Another begins here"])
check(j[0] == "Provided that, when any fact is deposed to as discovered, so much of such information may be proved.", "join: wrapped lines of one paragraph are joined")
check(j[1] == "(a) first item continues here", "join: an item '(a)' starts a paragraph and its wrapped line joins it")
check(j[2] == "Illustrations", "join: a heading word starts a paragraph")
check(any(x.startswith("A police-officer is meant.") for x in j), "join: a hyphen at the end of a line joins without a space when the next word is lower-case")
check(j[-1] == "Another begins here" and "Next sentence ends." in j[-2], "join: after a sentence end a capital letter starts a new paragraph")

ls = ["CHAPTER I.––PRELIMINARY", "13", "1. Short title.––This Act may be called the Indian Evidence Act, 1872.", "STATE AMENDMENT", "Haryana", "SCHEDULE", "never"]
cl = P.clean_body_lines(ls)
check(cl == ["1. Short title.––This Act may be called the Indian Evidence Act, 1872.", "STATE AMENDMENT", "Haryana"], "clean: chapter headings and page numbers dropped, STATE AMENDMENT kept as a marker, the Schedule ends the body")
t, rest = P.split_heading("106. Burden of proving fact especially within knowledge.––When any fact is especially within the")
check(t == "Burden of proving fact especially within knowledge." and rest.startswith("When any fact"), "split_heading: title and first words of the text")
t2, _r = P.split_heading("3. Interpretation-clause.––In this Act the following words")
check(t2 == "Interpretation-clause.", "split_heading: a hyphen inside the title is not the dash")

toc = [("1", "Short title."), ("2", "[Repealed.]"), ("3", "Interpretation-clause."), ("3A", "Added section.")]
body = ["1. Short title.––This Act may be called the Indian Evidence Act, 1872.", "Extent.––It extends to the whole of India.", "2.  [Repeal of enactments.].––Rep. by the Repealing Act, 1938.",
        "3. Interpretation-clause.––In this Act the following words", "are used.", "Illustrations", "(a) one.", "STATE AMENDMENT", "Haryana: changed.", "[Vide Haryana Act 1.]", "3A. Added section.––Text of the added section."]
ACT = {"code": "IEA", "key": "k", "name": "n", "citation": "c", "sections_url": "u"}
ch = P.cut_sections(body, toc, "2026-10-31", ACT)
check([c["section_number"] for c in ch] == ["1", "2", "3", "3A"], "cut: the sections equal the arrangement in number and order")
check(ch[0]["text"].startswith("1. Short title.\n") and "Extent.––It extends" in ch[0]["text"], "cut: heading line, then the body with its own sub-heads")
check(ch[2]["text"].count("Haryana") == 0 and ch[2]["state_amendments"].startswith("Haryana: changed.") and P.STATE_NOTE in ch[2]["text"], "cut: a State amendment block is moved to state_amendments and replaced by the one-line note")
check(ch[3]["text"].endswith("Text of the added section."), "cut: the last section runs to the end")
try:
    P.cut_sections(body[:3], toc, "x", ACT)
    check(False, "cut: a missing heading stops the load")
except Exception as exc:  # noqa: BLE001
    check("3 of the arrangement has no heading" in str(exc), "cut: a missing heading stops the load")

check(P.compare_titles(ch[:1], toc[:1], None) == [], "titles: equal headings pass")
bad = P.compare_titles(ch[1:2], toc[1:2], None)
check(len(bad) == 1 and bad[0]["section"] == "2", "titles: a heading that differs from the arrangement is reported")
check(P.compare_titles(ch[1:2], toc[1:2], [{"section": "2", "why": "x"}]) == [], "titles: a manifest entry accepts it")

# second reading: footnote text in Poppler's stream is explained, a changed word is not
sec = {"section_number": "9", "text": "9. T\nthe court may presume that a thing which has been shown to exist still exists unless the contrary is proved by the party"}
pop_ok = P.norm_words("the court may presume that a thing which 12 has been shown to exist still exists 1. Subs. by Act 21 of 2000, s. 92 and the Second Schedule unless the contrary is proved by the party")
une, expl, absent = P.second_reading([sec], pop_ok)
check(not une and not absent, "second reading: footnote text and numbers inside Poppler's stream are explained")
pop_bad = P.norm_words("the court may presume that a thing which has been shown to exist still exists unless the contrary is disproved by the party")
une2, _e, absent2 = P.second_reading([sec], pop_bad)
check(une2 or absent2, "second reading: a word that the two readings do not share is reported")

# ----------------------------------------------------------------------------------------------- the section map
ea = [{"section_number": "10", "title": "Burden.", "text": "10. Burden.\nWhen any fact is especially within the knowledge of any person, the burden of proving that fact is upon him.\nIllustrations\n(a) A is charged with travelling without a ticket. The burden of proving that he had a ticket is on him."},
      {"section_number": "11", "title": "Gone.", "text": "11. Gone.\nA matter nobody enacted again about cession of territory by the Crown to a foreign state."}]
bsa = [{"section_number": "20", "title": "Burden.", "text": "20. Burden.\nWhen any fact is especially within the knowledge of any person, the burden of proving that fact is upon him.\nIllustrations\n(a) A is charged with travelling without a ticket. The burden of proving that he had a ticket is on him."},
       {"section_number": "21", "title": "Other.", "text": "21. Other.\n(1) Something else entirely.\n(2) Unrelated words appear here.\nProvided that this proviso is unrelated."}]
mp = SM.build(ea, bsa, "2026-10-31")
check(mp["pairs"][0]["bsa"][0]["section"] == "20" and mp["pairs"][0]["kind"] == "same_wording", "map: identical wording is paired and called same_wording")
check(mp["pairs"][1]["kind"] == "no_counterpart_found", "map: a section nobody enacted again has no counterpart")
check(mp["status"] == "machine_built_not_reviewed", "map: the status says it was built by program and not read")
check(SM.subsection_of({("5", 0): "(1) a", ("5", 1): "(2) b", ("5", 2): "Provided that c"}, "5", 2) == "(2)", "map: a proviso is tied to the sub-section it hangs from")

real = jload("section_map_ea_bsa.json")
pr = {p["ea"]: p for p in real["pairs"]}
check(len(real["pairs"]) == 185, "real map: one pair for each of the 185 Evidence Act sections")
check(pr["106"]["bsa"][0]["section"] == "109" and pr["106"]["kind"] == "same_wording", "real map: Evidence Act 106 (burden, fact within knowledge) -> Adhiniyam 109")
check(pr["27"]["bsa"][0]["section"] == "23" and pr["27"]["bsa"][0]["bsa_subsection"] == "(2)" and pr["27"]["bsa"][0]["bsa_part"].lower().startswith("provided"), "real map: Evidence Act 27 -> the proviso to Adhiniyam 23(2)")
check(pr["25"]["bsa"][0]["section"] == "23" and pr["25"]["bsa"][0]["bsa_subsection"] == "(1)", "real map: Evidence Act 25 -> Adhiniyam 23(1)")
check(pr["24"]["bsa"][0]["section"] == "22", "real map: Evidence Act 24 -> Adhiniyam 22")
check(pr["115"]["bsa"][0]["section"] == "121", "real map: Evidence Act 115 (estoppel) -> Adhiniyam 121")
check(pr["145"]["bsa"][0]["section"] == "148", "real map: Evidence Act 145 -> Adhiniyam 148")
check(pr["113"]["kind"] == "no_counterpart_found", "real map: cession of territory (113) has no counterpart found")

# ----------------------------------------------------------------------------------------------- the counterpart note
n = M.note_for("evidence_act_1872", "106")
check("section 109" in n and "1 July 2024" in n and "not read it" in n.replace("has not read it", "not read it") or "has not read it" in n, "note: Evidence Act 106 names Adhiniyam 109, the repeal date, and says nobody has read the pairing")
check("proviso to section 23(2)" in M.note_for("evidence_act_1872", "27"), "note: Evidence Act 27 names the proviso to Adhiniyam 23(2)")
nb = M.note_for("bsa_2023", "23")
check("25" in nb and "26" in nb and "27" in nb and "Evidence Act" in nb, "note: Adhiniyam 23 names Evidence Act 25, 26 and 27")
check("do not say it was dropped" in M.note_for("evidence_act_1872", "113"), "note: a section with no counterpart is not said to be dropped or carried over")
check(M.note_for("pc_act_1988", "17") == "" and M.note_for("evidence_act_1872", "2") == "", "note: other Acts and the repealed section 2 give no note")
check(M.note_for("evidence_act_1872", "106", path="/nonexistent/map.json") == "", "note: fail-open with no map file")
check("means the same" not in n and "good law" not in n, "note: never says the sections mean the same or that anything is good law")

# ----------------------------------------------------------------------------------------------- the data files and the shelf
man = {a["key"]: a for a in jload("manifest.json")["acts"]}
check(man["evidence_act_1872"]["text_status"] == "machine_extracted" and man["evidence_act_1872"]["sections_loaded"] == 185 and man["evidence_act_1872"]["source"] == "pdf_only", "manifest: the Evidence Act is machine_extracted, PDF-only, 185 sections")
check(man["bsa_2023"]["text_status"] == "machine_checked" and man["bsa_2023"]["sections_loaded"] == 170, "manifest: the Adhiniyam is machine_checked, 170 sections")
bs = {c["section_number"]: c for c in jload("bsa_2023.json")}
check("(c) If a bill of exchange is drawn in a set of three, one only need be proved." in bs["94"]["text"], "BSA s.94: illustration (c) missing from India Code's database is restored from the PDF")
check(bs["119"]["text"].count("(a) a man who is in possession of stolen goods") == 1, "BSA s.119: India Code's doubled illustration (a) is printed once")
check("B's death" in bs["2"]["text"] and "Bs death" not in bs["2"]["text"], "BSA s.2: the lost apostrophe is back")
check(bs["109"]["title"].startswith("Burden of proving fact especially"), "BSA s.109 is the section on the burden of proving a fact especially within knowledge")
eas = {c["section_number"]: c for c in jload("evidence_act_1872.json")}
check(len(eas) == 185 and all(c["text_status"] == "machine_extracted" for c in eas.values()), "Evidence Act: 185 sections, each machine_extracted")
check("especially within the knowledge of any person" in eas["106"]["text"] and "inconsequence" in eas["27"]["text"], "Evidence Act: s.106 and s.27 are the PDF's text (s.27's 'inconsequence' is the PDF's own reading and is kept as printed)")
check(all("STATE AMENDMENT" not in c["text"] and "Subs. by" not in c["text"] for c in eas.values()), "Evidence Act: no State-amendment block and no footnote text is inside a section")
check(sorted(c["section_number"] for c in eas.values() if c["state_amendments"]) == ["114A", "146", "53A"], "Evidence Act: State amendments are set aside in 53A, 114A and 146 only")

import act_shelf  # noqa: E402

sh = act_shelf.load(refresh=True)
check(sh["acts"]["evidence_act_1872"]["ok"] and sh["acts"]["bsa_2023"]["ok"], "shelf: both Acts load with fresh embeddings")
m106 = act_shelf._match(sh["acts"]["evidence_act_1872"], sh["acts"]["evidence_act_1872"]["by_num"]["106"], "named", 1.0)
check("section 109" in (m106.get("context_note") or ""), "shelf: a matched Evidence Act section carries the counterpart note as its context_note")
mp17 = act_shelf._match(sh["acts"]["pc_act_1988"], sh["acts"]["pc_act_1988"]["by_num"]["17"], "named", 1.0)
check(not mp17.get("context_note"), "shelf: another Act's section gets no note")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")
