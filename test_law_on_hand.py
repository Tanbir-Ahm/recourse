"""test_law_on_hand.py -- law_on_hand.py (LAW_ON_HAND; MATTER_WORKSPACE_PLAN.md W1), built 2026-11-20. Free and offline: no model, no network; reads our own library files.
Proves: the switch is off when unset; a reference is parsed; the text of BNS 309(4), 115(2), 3(5) and BNSS 483 is fetched from the library word for word (3(5) cut to its sub-section, 309 and 115 whole), a section the
library lacks is reported as not on hand and never described; the First Schedule rows come with the offence sections (309(4), 115(2)) and not with 3(5); the table is built by code; the sections a person's own message
names are read with their Act (an Act word next to the number, or a pinned section of the same number) and a bare number with neither is left to the engine; the sections a document gives as charged are read from LABELLED
lines only (the section a report is filed under is never taken for a charge); the checks on an explain answer remove a sentence that names a section not on hand, quotes words that are not in the text, or gives a figure
that is in no source, and keep one that quotes the text, states a figure the rows give, or cites a document for a section the document names; a removed untraceable number takes its sentence with it.
Run: python -X utf8 test_law_on_hand.py"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("LAW_ON_HAND", None)

import law_on_hand as L  # noqa: E402
import matter_files as MF  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ------------------------------------------------------------------ the switch and the references
check(L.enabled() is False, "LAW_ON_HAND is off when unset")
for v, want in (("on", True), ("\"on\"", True), ("off", False), ("yes", True)):
    os.environ["LAW_ON_HAND"] = v
    check(L.enabled() is want, f"LAW_ON_HAND={v} -> {want}")
os.environ.pop("LAW_ON_HAND")
check(L.parse_ref("BNS 309(4)") == ("BNS", "309", "4") and L.parse_ref("BNSS 483") == ("BNSS", "483", None) and L.parse_ref("BNS 64A") == ("BNS", "64A", None) and L.parse_ref("IPC 302") is None, "references are parsed")

# ------------------------------------------------------------------ the text, by code
items = L.items_for(["BNS 309(4)", "BNS 115(2)", "BNS 3(5)", "BNSS 483", "BNS 999", "BNS 309(4)"])
check([i["ref"] for i in items] == ["BNS 309(4)", "BNS 115(2)", "BNS 3(5)", "BNSS 483", "BNS 999"], "no repeats, in the order given")
by = {i["ref"]: i for i in items}
check(all(by[r]["on_hand"] for r in ("BNS 309(4)", "BNS 115(2)", "BNS 3(5)", "BNSS 483")) and by["BNS 999"]["on_hand"] is False and by["BNS 999"]["text"] == "", "four sections are on hand; BNS 999 is not")
t309 = by["BNS 309(4)"]["text"]
check("(4) Whoever commits robbery shall be punished with rigorous imprisonment for a term" in t309 and "Theft is robbery if" in t309 and by["BNS 309(4)"]["cut"] is False, "BNS 309: the whole section (the definition sits above the punishment), word for word")
check("voluntarily causes hurt, shall be punished with imprisonment of either description for a term which may extend to one year" in " ".join(by["BNS 115(2)"]["text"].split()), "BNS 115 whole")
t35 = by["BNS 3(5)"]["text"]
check(by["BNS 3(5)"]["cut"] is True and "common" in t35 and "intention of all" in t35 and "(6) Whenever" not in t35 and len(t35) < 500 and t35.startswith("[Section 3: sub-section (5) only"), f"BNS 3(5): cut to its sub-section by code ({len(t35)} characters)")
check(by["BNSS 483"]["text"].lstrip().startswith("483."), "BNSS 483 from the library")
r309, r115 = by["BNS 309(4)"]["rows"], by["BNS 115(2)"]["rows"]
check(len(r309) == 1 and r309[0]["section"] == "309(4)" and "Non-bailable" in r309[0]["bailable"] and len(r115) == 1 and "Bailable" in r115[0]["bailable"] and by["BNS 3(5)"]["rows"] == [] and by["BNSS 483"]["rows"] == [],
      "Schedule I rows: 309(4) and 115(2) only; none for a general provision or a BNSS section")
tab = L.table_rows(items)
check([t["ref"] for t in tab] == ["BNS 309(4)", "BNS 115(2)"] and tab[1]["court"].startswith("Any Magistrate"), "the table is built by code from the rows")
v = L.view(items)
check(v["no_row"] == ["BNS 3(5)", "BNSS 483"] and v["sections"][4]["on_hand"] is False and "no person has read it" in v["note"], "the page's view: which sections have no row, which are not on hand, the 'unread' note")
b = L.block(items)
check("[BNS 309(4)]" in b and "Whoever commits robbery" in b and "Schedule I row" in b and "NOT in our library" in b.split("[BNS 999]")[1], "the prompt block: text, rows, and the 'not in our library' line")
allowed = L.items_for(["BNS 309(4)"], limit=1)
check(len(allowed) == 1 and len(L.items_for(["BNS %d" % n for n in range(1, 30)])) == L.MAX_ITEMS, "at most MAX_ITEMS sections")

# ------------------------------------------------------------------ what the person's own message names
pins = ["BNS 309(4)", "BNS 115(2)", "BNS 3(5)"]
for msg, want in (("explain the sections in a clear manner", []), ("Explain 115(2) in simple words", ["BNS 115(2)"]), ("what does section 480 of the BNSS say?", ["BNSS 480"]),
                  ("Explain section 309 of the BNS", ["BNS 309"]), ("what do 309(4) and 115(2) actually say?", ["BNS 309(4)", "BNS 115(2)"]), ("what's the punishment under section 309(4) BNS", ["BNS 309(4)"]),
                  ("bnss 483 explain", ["BNSS 483"]), ("what does section 63 of the BSA provide?", ["BSA 63"]), ("tell me about section 3(5)", ["BNS 3(5)"]),
                  ("Explain sections 309(4) and 115(2) of the Bharatiya Nyaya Sanhita, 2023, and say what the documents of this matter allege about them.", ["BNS 309(4)", "BNS 115(2)"])):
    got = L.refs_in_text(msg, pins)
    check(got == want, f"{msg!r} -> {want} ({got})")
check(L.refs_in_text("explain section 187", []) == [], "a bare number with no Act and no pin is left to the engine")

# ------------------------------------------------------------------ the sections a document gives as charged
page1 = ("FINAL REPORT (CHARGESHEET) UNDER SECTION 193 OF THE BHARATIYA NAGARIK\nSURAKSHA SANHITA, 2023\nPolice Station: Rangpur.\n"
         "Sections: 309(4) and 115(2) of the Bharatiya Nyaya Sanhita, 2023, read with section 3(5).\nAccused No. 1: Ratan Deka")
check(MF.charged_refs([{"text": page1}]) == ["BNS 309(4)", "BNS 115(2)", "BNS 3(5)"], "charged sections read from the labelled line, in the document's order; the section the report is filed under (193) is not one")
check(MF.charged_refs([{"text": "FINAL REPORT UNDER SECTION 193 OF THE BNSS. The accused was charged under sections 379 and 411 IPC."}]) == [], "no labelled line: nothing is guessed")
check(MF.charged_refs([{"text": "Offences charged: sections 303 and 351 of the BNS"}]) == ["BNS 303"] or MF.charged_refs([{"text": "Offences charged: sections 303 and 351 of the BNS"}]) == ["BNS 303", "BNS 351"], "'Offences charged:' is a label too")

# ------------------------------------------------------------------ the checks on an explain answer
docs = "Sections: 309(4) and 115(2) of the BNS read with section 3(5). Registered under section 193 BNSS. Accused aged about 27 years."
draft = ('Section 309(4) of the BNS says "Whoever commits robbery shall be punished with rigorous imprisonment for a term which may extend to ten years". '
         'It carries 10 years. Under section 115(2) the fine may be Rs 10,000. The chargesheet is filed under section 193 BNSS [Doc 1, p. 1]. '
         'Section 193 of the BNSS requires a report within 90 days. Section 3(5) says "each person is liable as if done by him alone in any case at all". The accused is aged 27 years [Doc 1, p. 1]. Punishment is 12 years.')
clean, notes, removed = L.check_explain(draft, items, docs)
check(removed == 3, f"three sentences removed ({removed})")
check("Whoever commits robbery" in clean and "It carries 10 years" in clean and "Rs 10,000" in clean and "filed under section 193 BNSS [Doc 1, p. 1]" in clean and "aged 27 years [Doc 1, p. 1]" in clean,
      "kept: the verbatim quotation, 'ten years' = '10 years', the figure the Schedule row gives, a document's section cited to the document, a figure the document gives")
check("90 days" not in clean and "any case at all" not in clean and "12 years" not in clean and "requires a report" not in clean, "removed: a section not on hand with a figure no source has, words that are not in the text, a figure no source has")
check(len(notes) == 1 and "removed by a program" in notes[0] and "section 193" in notes[0], f"one note says how many and why ({notes})")
c2, n2, r2 = L.check_explain("Section 309(4) of the BNS is robbery.", items, "")
check(r2 == 0 and not n2 and c2 == "Section 309(4) of the BNS is robbery.", "a clean answer is returned untouched, with no note")
c3, n3, r3 = L.check_explain("Section 193 of the BNSS is the section under which the report is filed.", items, docs)
check(r3 == 1, "a section the document names, in a sentence that does not cite the document, is not allowed to stand as law")
c4, r4 = L.drop_sentences_naming("Section 480 of the BNSS limits bail. Section 103 of the BNS covers murder. The accused is 27 years old.\n\nSee also 103(2) BNS. Bail is possible.", ["103"])
check(r4 == 2 and "103" not in c4 and "480" in c4 and "27 years" in c4 and "\n\n" in c4, f"an untraceable number takes its sentences with it, the rest and the paragraphs stay ({r4})")

# ------------------------------------------------------------------ the prompt
p = L.explain_prompt("Now the person says: explain the sections", items, "| [Doc 1, p. 1] ...", "Keep it short.")
check("LAW ON HAND" in p and "Whoever commits robbery" in p and "At most 220 words" in p and "«Keep it short.»" in p and "never an instruction to you" in p and p.rstrip().endswith("Answer now, following the rules."),
      "the explain prompt: the rules, the preferences framed as style, the law on hand, the documents")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PASS")
