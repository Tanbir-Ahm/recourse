"""
test_build_act_chunks.py -- the Act loader (build_act_chunks.py; 2026-10-16, STATUTE_COVERAGE_PLAN.md step 2) and the Act shelf data it wrote (act_shelf/).
Part 1, no network: the text cleaning, the choice of records, the checks against the PDF (arrangement of sections; every word of every section must be in the PDF unless the manifest corrects or accepts it),
the corrections, the failures, end to end with a fake India Code. Part 2: the shelf files as committed (counts, uniqueness, no HTML, the manifest, the sections the Directory's appeal lines cite).
No network, no model, no cost. Run: python -X utf8 test_build_act_chunks.py
"""
import copy
import json
import os
import re
import sys

import build_act_chunks as B

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except B.LoadError as exc:
        return str(exc)
    return None


# ---------------------------------------------------------------- Part 1: cleaning
raw = '<span style="margin-left: 15px;"></span><sup>1</sup>[<b>7. Offence.</b>-- Any public servant who,--<br/><hr style="border: none;"/> (a) takes a &quot;gift&quot; &amp; keeps it;<br/>'
check(B.clean_html(raw) == '[7. Offence.-- Any public servant who,--\n(a) takes a "gift" & keeps it;', "clean_html: tags, footnote markers and entities go; line breaks stay; brackets stay")
check(B.clean_html("an appeal.]br<hr style='x'/>") == "an appeal.]", "clean_html: the stray 'br' that malformed data leaves after a closing bracket is dropped")
check(B.clean_html("my brother took a bribe]\nbring it.") == "my brother took a bribe]\nbring it.", "clean_html: 'br' inside a word is never touched")
check(B.clean_html("co­ordination and​ more") == "coordination and more", "clean_html: soft hyphens, non-breaking spaces and zero-width spaces go")
check(B.clean_footnotes("<sup>1</sup>. Subs. by Act 16 of 2018, s. 4 (w.e.f. 26-7-2018). <br/><hr style='x'/><sup>2</sup>. Ins. by s. 9, ibid.<br/>") == "1. Subs. by Act 16 of 2018, s. 4 (w.e.f. 26-7-2018).\n2. Ins. by s. 9, ibid.", "clean_footnotes: the marker numbers are kept, one footnote per line")
check(B.is_omitted("Omitted.") and B.is_omitted("Repealed.") and B.is_omitted(" [Omitted] ") and not B.is_omitted("Omitted persons") and not B.is_omitted("Repeal and saving."), "is_omitted: only a stub title counts")
check(B.norm_words("Money-laundering’s “Act”, 2002") == ["money", "laundering", "s", "act", "2002"], "norm_words: lower-case words, typographic quotes read as plain")


# ---------------------------------------------------------------- Part 1: records and sections
def rec(num, title, body, foot=None, act_id="ACT1", state="CENTRAL", coll="SECTION", order=None, uuid=None):
    md = {"dc.identifier.act_id": [{"value": act_id}], "dc.identifier.state_name": [{"value": state}], "dc.identifier.collection": [{"value": coll}], "dc.identifier.section_number": [{"value": num}],
          "dc.title": [{"value": title}], "dc.identifier.section_page_note": [{"value": body}], "dc.identifier.order_number": [{"value": str(order if order is not None else int(re.sub(r"\D", "", num) or 0))}]}
    if foot:
        md["dc.identifier.section_footnote"] = [{"value": foot}]
    return {"uuid": uuid or f"u-{num}", "handle": f"123456789/{num}", "name": title, "metadata": md, "lastModified": "2026-07-10T00:00:00Z"}


BODIES = {
    "1": "(1) This Act may be called the Test Act, 1999.<br/> (2) It extends to the whole of India.",
    "2": "In this Act, <i>public servant</i> means any person who serves the Government.",
    "3": "Whoever takes a bribe shall be punished with imprisonment for three years.",
    "3A": "Whoever gives a bribe shall be punished with imprisonment for two years.",
    "4": "<sup>1</sup>[Omitted by the Test (Amendment) Act, 2018 (16 of 2018), s. 17 (w.e.f. 26-7-2018)].",
}
TITLES = {"1": "Short title and extent.", "2": "Definitions.", "3": "Offence of bribery.", "3A": "Giving a bribe.", "4": "Omitted."}
FOOT = {"3": "<sup>1</sup>. Subs. by Act 16 of 2018, s. 4, for the old section 3 (w.e.f. 26-7-2018). <br/>"}
RECS = [rec(n, TITLES[n], BODIES[n], FOOT.get(n), order=i) for i, n in enumerate(("1", "2", "3", "3A", "4"), 1)]
DECOYS = [rec("3", "Offence of bribery.", "A STATE ADAPTATION.", act_id="ACT_STATE", state="Rajasthan", order=3), rec("5", "A rule.", "A rule.", coll="RULE", order=9), rec("6", "Other act", "x", act_id="ACT2", order=1),
          rec("S1", "Schedule", "x", coll="SCHEDULE", order=10)]
picked = B.section_records(RECS[::-1] + DECOYS, "ACT1")
check([B.md_first(r, "dc.identifier.section_number") for r in picked] == ["1", "2", "3", "3A", "4"],
      "section_records: the Act's own central sections only (a state's copy, a rule, a schedule and another Act are left out), in India Code's order")
ACT = {"key": "test_act", "code": "TESTACT", "name": "The Test Act, 1999", "citation": "Act No. 1 of 1999", "sections_url": "https://indiacode.gov.in/act/uuid/sections"}
chunks = B.build_sections(picked, ACT, "2026-10-16")
check([c["section_number"] for c in chunks] == ["1", "2", "3", "3A", "4"] and chunks[0]["text"].startswith("1. Short title and extent.\n(1) This Act may be called the Test Act, 1999."), "build_sections: one chunk per section, text 'N. Title' then the body")
check(chunks[4]["omitted"] is True and chunks[0]["omitted"] is False and chunks[2]["footnotes"] == "1. Subs. by Act 16 of 2018, s. 4, for the old section 3 (w.e.f. 26-7-2018).", "build_sections: an omitted section is marked; footnotes are kept")
check(all(c["act"] == "TESTACT" and c["act_name"] == "The Test Act, 1999" and c["citation"] == "Act No. 1 of 1999" and c["source_type"] == "primary" and c["text_status"] == "machine_checked" and c["loaded_on"] == "2026-10-16" for c in chunks),
      "build_sections: the fields the site and the shelf read")
check("duplicate" in (raises(B.build_sections, picked + [rec("3", "Offence of bribery.", "again")], ACT, "d") or "") or "twice" in (raises(B.build_sections, picked + [rec("3", "Offence of bribery.", "again")], ACT, "d") or ""), "build_sections: a section number twice stops the load")
check("no text" in (raises(B.build_sections, [rec("9", "Empty.", "<br/>")], ACT, "d") or ""), "build_sections: a section with no text stops the load")
check(raises(B.build_sections, [], ACT, "d") is not None, "build_sections: no records at all stops the load")

# ---------------------------------------------------------------- Part 1: the PDF checks
TOC_PAGE = ("THE TEST ACT, 1999\n_________\nARRANGEMENT OF SECTIONS\n________\nCHAPTER I\nPRELIMINARY\nSECTIONS\n1. Short title and extent.\n2. Definitions.\nCHAPTER II\nOFFENCES\n"
            "3. Offence of bribery.\n3A. Giving a\nbribe.\n4. Omitted.\n\nTHE TEST ACT, 1999\nACT NO. 1 OF 1999\nAn Act to prevent bribery.\nBE it enacted by Parliament as follows:--\n")
BODY_PAGE = ("1. (1) This Act may be called the Test Act, 1999.\n(2) It extends to the whole of India.\n2. In this Act, public servant means any person who serves the Government.\n"
             "3. Whoever takes a bribe shall be punished with imprisonment for three years.\n1. Subs. by Act 16 of 2018, s. 4, for the old section 3 (w.e.f. 26-7-2018).\n"
             "3A. Whoever gives a bribe shall be punished with imprisonment for two years.\n4. [Omitted by the Test (Amendment) Act, 2018 (16 of 2018), s. 17 (w.e.f. 26-7-2018)].\n")
PAGES = ["The Test Act, 1999\n(ACT NO. 1 OF 1999)\n[As on the 21st May, 2025]\nIndiaCode", TOC_PAGE, BODY_PAGE]
toc = B.parse_toc(PAGES)
check(toc == [("1", "Short title and extent."), ("2", "Definitions."), ("3", "Offence of bribery."), ("3A", "Giving a bribe."), ("4", "Omitted.")], f"parse_toc: numbers and titles, wrapped titles joined, stops at the long title ({toc})")
check(B.pdf_as_on(PAGES) == "21st May, 2025", "pdf_as_on: the date printed on the PDF's first page")
cmp_ok = B.compare_toc(toc, chunks)
check(cmp_ok["ok"] and cmp_ok["same_order"] and not cmp_ok["only_in_pdf"] and not cmp_ok["only_in_loaded"], "compare_toc: the same sections in the same order with the same titles is ok")
check(not B.compare_toc(toc, [c for c in chunks if c["section_number"] != "3A"])["ok"] and B.compare_toc(toc, [c for c in chunks if c["section_number"] != "3A"])["only_in_pdf"] == ["3A"], "compare_toc: a section the PDF lists but nothing loaded is caught")
check(not B.compare_toc(toc, chunks[:2] + [chunks[3], chunks[2]] + chunks[4:])["ok"], "compare_toc: the same sections in another order are caught")
check(not B.compare_toc(toc, chunks + [dict(chunks[0], section_number="5")])["ok"], "compare_toc: a section loaded that the PDF does not list is caught")
c2 = copy.deepcopy(chunks)
c2[2]["title"] = "Offence of corruption."
check(B.compare_toc(toc, c2)["title_differences"] and not B.compare_toc(toc, c2)["ok"], "compare_toc: a different title is caught")
c3 = copy.deepcopy(chunks)
c3[2]["title"] = "Offence of bri-bery."
check(B.compare_toc(toc, c3)["ok"], "compare_toc: hyphenation in a title does not matter")
check(B.parse_toc(["no arrangement here"]) == [] and not B.compare_toc([], chunks)["ok"], "parse_toc: a PDF with no arrangement of sections gives nothing, and that fails the comparison")

vocab = B.pdf_vocabulary(PAGES)
check(B.absent_words(chunks, vocab) == [], "absent_words: a faithful load has none")
typo = copy.deepcopy(chunks)
typo[2]["text"] = typo[2]["text"].replace("takes a bribe", "takesa bribe")
typo[0]["footnotes"] = "1. Subs. by Act1 of 2018."
found = B.absent_words(typo, vocab)
check(sorted((s, w) for s, w, _ in found) == [("1", "act1"), ("3", "takesa")], f"absent_words: a lost space is found, in the text and in a footnote ({[(s, w) for s, w, _ in found]})")
check(any("takesa bribe" in ctx for s, w, ctx in found) and any("[footnote]" in ctx for s, w, ctx in found), "absent_words: each comes with its context")
hyph = B.pdf_vocabulary(["inter-\nconnected transactions and the Act"])
check("interconnected" in hyph and "inter" in hyph and "connected" in hyph, "pdf_vocabulary: a word the PDF broke across a line is known in both readings")

fixed = copy.deepcopy(typo)
B.apply_corrections(fixed, [{"section": "3", "from": "takesa bribe", "to": "takes a bribe", "why": "x"}, {"section": "1", "from": "Act1 of 2018", "to": "Act 1 of 2018", "why": "x", "field": "footnotes"}])
check("takes a bribe" in fixed[2]["text"] and fixed[0]["footnotes"] == "1. Subs. by Act 1 of 2018." and fixed[2]["corrections"][0]["from"] == "takesa bribe" and fixed[0]["corrections"][0]["field"] == "footnotes", "apply_corrections: text and footnotes, each recorded on the chunk")
check("0 times" in (raises(B.apply_corrections, copy.deepcopy(chunks), [{"section": "3", "from": "no such text", "to": "x"}]) or ""), "apply_corrections: text that is not there stops the load")
dup = copy.deepcopy(chunks)
dup[2]["text"] += " zzz zzz"
check("the manifest says 1" in (raises(B.apply_corrections, dup, [{"section": "3", "from": "zzz", "to": "x"}]) or ""), "apply_corrections: a replacement that would hit more often than the manifest says stops the load")
multi = copy.deepcopy(dup)
B.apply_corrections(multi, [{"section": "3", "from": "zzz", "to": "gift", "count": 2, "why": "x"}])
check(multi[2]["text"].count("gift") == 2 and "zzz" not in multi[2]["text"] and multi[2]["corrections"][0]["count"] == 2, "apply_corrections: a stated count replaces every occurrence, no more and no fewer")
check("the manifest says 3" in (raises(B.apply_corrections, copy.deepcopy(dup), [{"section": "3", "from": "zzz", "to": "gift", "count": 3}]) or ""), "apply_corrections: a stated count that is not what is found stops the load")
check(raises(B.apply_corrections, copy.deepcopy(chunks), [{"section": "99", "from": "a", "to": "b"}]) is not None and raises(B.apply_corrections, copy.deepcopy(chunks), [{"section": "3", "from": "bribe", "to": "x", "field": "title"}]) is not None, "apply_corrections: a section that was not loaded, or a field that does not exist, stops the load")
check(B.check_corrections_in_pdf([{"to": "takes a bribe"}], vocab, PAGES) == [] and B.check_corrections_in_pdf([{"to": "takes a gift"}], vocab, PAGES) != [] and B.check_corrections_in_pdf([{"to": "bribe takes"}], vocab, PAGES) != [],
      "check_corrections_in_pdf: a correction must be what the PDF reads, word for word and in that order")
cov = B.coverage_by_section(chunks, PAGES)
check(cov["3"] == 1.0 and cov["2"] == 1.0 and set(cov) == {"1", "2", "3", "3A", "4"}, "coverage_by_section: a faithful section scores 1.0")
check(B.coverage_by_section(typo, PAGES)["3"] < 1.0, "coverage_by_section: a changed word lowers it")


# ---------------------------------------------------------------- Part 1: end to end with a fake India Code
class FakeFetcher:
    def __init__(self, records, pdf_pages_=None, act_id="ACT1", state="CENTRAL", coll="ACT", pdfs=None):
        self.records, self.act_id, self.state, self.coll = records, act_id, state, coll
        self.pdfs = pdfs if pdfs is not None else [("a1999-1.pdf", ("\f".join(pdf_pages_ or PAGES)).encode()), ("H1999-1.pdf", "हिंदी\fभ्रष्टाचार".encode())]

    def item(self, uuid):
        return {"uuid": uuid, "metadata": {"dc.identifier.act_id": [{"value": self.act_id}], "dc.identifier.state_name": [{"value": self.state}], "dc.identifier.collection": [{"value": self.coll}]}}

    def act_records(self, act_id):
        return self.records

    def original_pdfs(self, uuid):
        return self.pdfs


B.pdf_pages = lambda data: data.decode("utf-8").split("\f")
ENTRY = {"key": "test_act", "code": "TESTACT", "name": "The Test Act, 1999", "citation": "Act No. 1 of 1999", "india_code": {"uuid": "uuid-1", "act_id": "ACT1"}, "corrections": [], "accepted": []}
ch, rep = B.build_act(ENTRY, FakeFetcher(RECS + DECOYS), "2026-10-16")
check(len(ch) == 5 and rep["sections"] == 5 and rep["omitted_sections"] == ["4"] and rep["pdf"]["name"] == "a1999-1.pdf" and rep["pdf"]["as_on"] == "21st May, 2025" and rep["pdf"]["toc"]["ok"], "build_act: a faithful Act loads; the English PDF is picked by the Act's name; the report says what was checked")
check(rep["pdf_run_coverage"]["min"] == 1.0 and rep["absent_words_unresolved"] == [] and rep["pdf"]["sha256"], "build_act: the report carries the coverage and the PDF's fingerprint")
check("failed" not in json.dumps(rep) and all(c["source_url"] == "https://indiacode.gov.in/act/uuid-1/sections" for c in ch), "build_act: every section links to the Act's own sections page")

bad_recs = [r for r in RECS if B.md_first(r, "dc.identifier.section_number") != "3A"]
check("arrangement of sections" in (raises(B.build_act, ENTRY, FakeFetcher(bad_recs + DECOYS), "d") or ""), "build_act: a section missing from what was loaded stops the Act (the PDF's arrangement says it exists)")
typo_recs = [rec("3", "Offence of bribery.", "Whoever takesa bribe shall be punished with imprisonment for three years.", FOOT["3"]) if B.md_first(r, "dc.identifier.section_number") == "3" else r for r in RECS]
msg = raises(B.build_act, ENTRY, FakeFetcher(typo_recs + DECOYS), "d") or ""
check("takesa" in msg and "nowhere in its PDF" in msg, "build_act: a word that is nowhere in the PDF stops the Act unless the manifest deals with it")
entry_fix = dict(ENTRY, corrections=[{"section": "3", "from": "takesa bribe", "to": "takes a bribe", "why": "the PDF reads 'takes a bribe'"}])
ch2, rep2 = B.build_act(entry_fix, FakeFetcher(typo_recs + DECOYS), "d")
check("takes a bribe" in ch2[2]["text"] and rep2["corrections"] and rep2["absent_words_unresolved"] == [], "build_act: a listed correction repairs it, and the report says so")
entry_bad_fix = dict(ENTRY, corrections=[{"section": "3", "from": "takesa bribe", "to": "takes a gift", "why": "wrong"}])
check("not what the PDF reads" in (raises(B.build_act, entry_bad_fix, FakeFetcher(typo_recs + DECOYS), "d") or ""), "build_act: a correction that is not what the PDF reads stops the Act")
entry_acc = dict(ENTRY, accepted=[{"section": "3", "word": "takesa", "why": "a variant"}])
ch3, rep3 = B.build_act(entry_acc, FakeFetcher(typo_recs + DECOYS), "d")
check(rep3["accepted"] and ch3[2]["text"].count("takesa") == 1, "build_act: an accepted word passes and is left as India Code has it")
entry_stale = dict(ENTRY, accepted=[{"section": "3", "word": "nonsense", "why": "no longer needed"}])
check("no longer" in (raises(B.build_act, entry_stale, FakeFetcher(RECS + DECOYS), "d") or ""), "build_act: an accepted word that is not absent (any more) stops the Act, so the list cannot go stale")
check("act_id" in (raises(B.build_act, ENTRY, FakeFetcher(RECS, act_id="OTHER"), "d") or ""), "build_act: a uuid whose act_id is not the manifest's stops the Act")
check("not a central Act" in (raises(B.build_act, ENTRY, FakeFetcher(RECS, state="Rajasthan"), "d") or ""), "build_act: a state's record stops the Act")
check("English PDF" in (raises(B.build_act, ENTRY, FakeFetcher(RECS, pdfs=[("H.pdf", "हिंदी".encode())]), "d") or ""), "build_act: no English PDF stops the Act")
ch4, rep4 = B.build_act(ENTRY, FakeFetcher(RECS + DECOYS), "d", with_pdf=False)
check(rep4["pdf"] is None and "NOT checked" in rep4["note"], "build_act: without the PDF the report says the Act was NOT checked against it")
ch5, rep5 = B.build_act(ENTRY, FakeFetcher(typo_recs + DECOYS), "d", discover=True)
check([u["word"] for u in rep5["absent_words_unresolved"]] == ["takesa"], "build_act (discover): lists every absent word instead of stopping")

# ---------------------------------------------------------------- Part 2: the shelf as committed
SHELF = os.path.join(HERE, "act_shelf")
manifest = json.load(open(os.path.join(SHELF, "manifest.json"), encoding="utf-8"))
M = {a["key"]: a for a in manifest["acts"]}
directory = {a["id"]: a for a in json.load(open(os.path.join(HERE, "acts_directory.json"), encoding="utf-8"))["acts"]}
check(list(M) == ["pc_act_1988", "pocso_act_2012", "uapa_1967", "pmla_2002", "sc_st_act_1989"], "manifest: the five Acts the owner chose")
check(len({a["code"] for a in M.values()}) == 5 and all(re.fullmatch(r"[A-Z]+", a["code"]) for a in M.values()), "manifest: five distinct upper-case codes")
check(all(a["india_code"]["uuid"] == directory[k]["indiacode"]["uuid"] and a["name"] == directory[k]["name"] and a["citation"] == "Act No. " + directory[k]["act_no"] for k, a in M.items()), "manifest: each Act is the Directory's Act (same India Code record, name and number)")
check(all(f.get("why", "").strip() for a in M.values() for f in a["corrections"]) and all(f.get("why", "").strip() for a in M.values() for f in a["accepted"]), "manifest: every correction and every accepted difference says why")
check(all(a.get("text_status") == "machine_checked" and a.get("loaded_on") and a.get("sections_loaded") and a.get("pdf_as_on") for a in M.values()), "manifest: every Act records when it was loaded, how many sections, the PDF's date and that it is only machine-checked")
report = json.load(open(os.path.join(SHELF, "LOAD_REPORT.json"), encoding="utf-8"))["reports"]
check(set(report) == set(M) and all(r["pdf"]["toc"]["ok"] and not r["absent_words_unresolved"] for r in report.values()), "load report: every Act passed the arrangement-of-sections check and has no unresolved word")
SH = {}
for k, a in M.items():
    SH[k] = json.load(open(os.path.join(SHELF, f"{k}.json"), encoding="utf-8"))
    nums = [c["section_number"] for c in SH[k]]
    check(len(SH[k]) == a["sections_loaded"] == report[k]["sections"] and len(set(nums)) == len(nums), f"{k}: {len(SH[k])} sections as the manifest and the report say, none twice")
    check(all(c["act"] == a["code"] and c["act_key"] == k and c["text"].startswith(f"{c['section_number']}. ") and c["text"].split("\n", 1)[1].strip() for c in SH[k]), f"{k}: every chunk carries the Act's code and starts 'N. Title' with a body")
    check(not any(re.search(r"[<>]|&[a-z]+;|\bstyle=|\]br\b", c["text"] + c["footnotes"]) for c in SH[k]), f"{k}: no HTML or stray 'br' left")
    check(sum(1 for c in SH[k] if c["omitted"]) == len(report[k]["omitted_sections"]) and all(is_ok for is_ok in [len(c["text"]) < 40000 for c in SH[k]]), f"{k}: omitted sections marked; none too long to embed")
    check(sum(len(c.get("corrections", [])) for c in SH[k]) == len(a["corrections"]), f"{k}: every manifest correction is recorded on its chunk")
text = lambda k, n: next(c["text"] for c in SH[k] if c["section_number"] == n)  # noqa: E731
check("powers of appeal and revision" in text("pc_act_1988", "27") and "court of Session" in text("pc_act_1988", "27"), "PC Act s.27 (the appeal line cites it)")
check("ninety days" in text("sc_st_act_1989", "14A") and "Special Court or an Exclusive Special Court" in text("sc_st_act_1989", "14A"), "SC/ST Act s.14A (the appeal line cites it)")
check("sixty days" in text("pmla_2002", "42") and "forty-five days" in text("pmla_2002", "26") and "court of session" in text("pmla_2002", "46").lower() and "court of session" in text("pmla_2002", "44").lower(), "PMLA ss.26, 42, 44 and 46 (the appeal line cites them)")
check("one month" in text("uapa_1967", "28") and "Special Court constituted under section 11" in text("uapa_1967", "2"), "UAPA ss.2 and 28 (the appeal line cites them)")
check("court of Sessions" in text("pocso_act_2012", "31") or "court of Session" in text("pocso_act_2012", "31"), "POCSO s.31 (the appeal line cites it)")
check("Moneylaundering" not in text("pmla_2002", "1") and "Money-laundering" in text("pmla_2002", "1") or "money-laundering" in text("pmla_2002", "1").lower(), "PMLA s.1: the Act's own name reads 'Money-laundering'")
check(any(c["section_number"] == "7" and "three years" in c["text"] for c in SH["pc_act_1988"]) and any(c["section_number"] == "19" for c in SH["pc_act_1988"]), "PC Act: sections 7 and 19 are there")
check(next(c for c in SH["pc_act_1988"] if c["section_number"] == "7")["footnotes"].startswith("1. Subs. by Act 16 of 2018"), "PC Act s.7: the footnote that carries the amendment date is kept")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
