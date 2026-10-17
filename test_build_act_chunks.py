"""
test_build_act_chunks.py -- the Act loader (build_act_chunks.py; 2026-10-16, STATUTE_COVERAGE_PLAN.md step 2) and the Act shelf data it wrote (act_shelf/).
Part 1, no network: the text cleaning, the choice of records, the checks against the PDF (arrangement of sections; every word of every section must be in the PDF unless the manifest corrects or accepts it;
the strict, two-way, in-order comparison of 2026-10-17 and the two tidy-ups), the corrections, the failures, end to end with a fake India Code and with a small PDF made on the spot. Part 2: the shelf files as
committed (counts, uniqueness, no HTML, the manifest, the sections the Directory's appeal lines cite, the defects the strict comparison found and the corrections that fixed them).
No network, no model, no cost. Run: python -X utf8 test_build_act_chunks.py
"""
import contextlib
import copy
import io
import json
import os
import re
import shutil
import sys
import tempfile

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
BODY_PAGE = ("1. Short title and extent.—(1) This Act may be called the Test Act, 1999.\n(2) It extends to the whole of India.\n2. Definitions.—In this Act, public servant means any person who serves the Government.\n"
             "3. Offence of bribery.—Whoever takes a bribe shall be punished with imprisonment for three years.\n1. Subs. by Act 16 of 2018, s. 4, for the old section 3 (w.e.f. 26-7-2018).\n"
             "3A. Giving a bribe.—Whoever gives a bribe shall be punished with imprisonment for two years.\n4. Omitted.—[Omitted by the Test (Amendment) Act, 2018 (16 of 2018), s. 17 (w.e.f. 26-7-2018)].\n")
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

# toc_absent: a section in the body but missing from the PRINTED arrangement-of-sections (e.g. the Dowry Act's 8A, an amendment-inserted section the front index was not updated for)
chunks_8a = chunks[:4] + [dict(chunks[3], section_number="3B", title="Inserted.")] + chunks[4:]        # 3B is only in loaded, not in the toc
c_bad = B.compare_toc(toc, chunks_8a)
check(not c_bad["ok"] and c_bad["only_in_loaded"] == ["3B"], "compare_toc: a body-only section still fails when it is NOT declared toc_absent")
c_ok = B.compare_toc(toc, chunks_8a, toc_absent=["3B"])
check(c_ok["ok"] and c_ok["only_in_loaded"] == [] and c_ok["toc_absent_seen"] == ["3B"] and c_ok["same_order"], "compare_toc: declaring the body-only section toc_absent passes, and it is recorded in toc_absent_seen")
c_stale = B.compare_toc(toc, chunks, toc_absent=["9Z"])
check(not c_stale["ok"] and c_stale["toc_absent_unused"] == ["9Z"], "compare_toc: a toc_absent declaration that is not actually only-in-loaded is reported as unused and fails (no stale declarations)")

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
check(raises(B.apply_corrections, copy.deepcopy(chunks), [{"section": "99", "from": "a", "to": "b"}]) is not None and raises(B.apply_corrections, copy.deepcopy(chunks), [{"section": "3", "from": "bribe", "to": "x", "field": "nonsense"}]) is not None, "apply_corrections: a section that was not loaded, or a field that does not exist, stops the load")
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
REAL_PDF_BODY_LINES = B.pdf_body_lines
B.pdf_body_lines = lambda data: [ln for pg in data.decode("utf-8").split("\f") for ln in pg.split("\n") if ln.strip() and not re.match(r"^\d{1,2}\. (Subs|Ins)\b", ln)]    # the fake PDF is plain text; the real layout rules are tested below on a real PDF
ENTRY = {"key": "test_act", "code": "TESTACT", "name": "The Test Act, 1999", "citation": "Act No. 1 of 1999", "india_code": {"uuid": "uuid-1", "act_id": "ACT1"}, "corrections": [], "accepted": [],
         "ordered_accepted": [{"section": "3A", "pdf_starts": "4 omitted omitted by the test amendment act", "why": "the stub of the omitted section 4, as the PDF prints it after section 3A"}]}
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

# main(): a run with --only must not erase the other Acts' reports (found 2026-10-17, when the sixth and seventh Acts were added), and a PDF with no "[As on the ...]" line is recorded as such
tmpd = tempfile.mkdtemp()
mpath = os.path.join(tmpd, "manifest.json")
E1 = copy.deepcopy(ENTRY)
E2 = dict(copy.deepcopy(ENTRY), key="test_act2", code="TESTACT2", whole_act=True)                 # a flag set by hand in the manifest must survive a reload
json.dump({"schema": 1, "about": "test", "acts": [E1, E2]}, open(mpath, "w"))
REAL_FETCHER = B.Fetcher
try:
    quiet = io.StringIO()
    B.Fetcher = lambda: FakeFetcher(RECS + DECOYS)
    with contextlib.redirect_stdout(quiet):
        rc1 = B.main(["--manifest", mpath, "--only", "test_act"])
    B.Fetcher = lambda: FakeFetcher(RECS + DECOYS, pdf_pages_=[PAGES[0].replace("[As on the 21st May, 2025]\n", ""), TOC_PAGE, BODY_PAGE])
    with contextlib.redirect_stdout(quiet):
        rc2 = B.main(["--manifest", mpath, "--only", "test_act2"])
    rep_all = json.load(open(os.path.join(tmpd, "LOAD_REPORT.json"), encoding="utf-8"))["reports"]
    man_all = {a["key"]: a for a in json.load(open(mpath, encoding="utf-8"))["acts"]}
    check(rc1 == 0 and rc2 == 0 and set(rep_all) == {"test_act", "test_act2"} and os.path.exists(os.path.join(tmpd, "test_act.json")) and os.path.exists(os.path.join(tmpd, "test_act2.json")),
          "main(--only): the second run adds its report to the first's instead of replacing it, and each Act has its own file")
    check(man_all["test_act"]["pdf_as_on"] == "21st May, 2025" and man_all["test_act2"]["pdf_as_on"] == B.NO_PDF_DATE == "not printed on the PDF" and rep_all["test_act2"]["pdf"]["as_on"] is None,
          "main(): the manifest records the PDF's date, or 'not printed on the PDF' when it has none (the raw report keeps None)")
    check(man_all["test_act2"].get("whole_act") is True and "whole_act" not in man_all["test_act"], "main(): a reload keeps the hand-set 'whole_act' flag of an entry and does not add it to another")
finally:
    B.Fetcher = REAL_FETCHER
    shutil.rmtree(tmpd, ignore_errors=True)


# ---------------------------------------------------------------- Part 1: the strict, two-way, in-order comparison (2026-10-17) and the two tidy-ups
check(B.cmp_tokens("That person’s handwriting; the Act, 1999 (2 of 1974)") == ["that", "person's", "handwriting", "the", "act", "1999", "2", "of", "1974"] and B.cmp_tokens("persons") != B.cmp_tokens("person's"),
      "cmp_tokens: an apostrophe inside a word is kept (\"person's\" and \"persons\" are different words), typographic quotes read as plain")
check(B.is_caps_line("CHAPTER III") and B.is_caps_line("THE FIRST SCHEDULE") and B.is_caps_line("STATE AMENDMENT") and not B.is_caps_line("1[14A. ") and not B.is_caps_line("(a) the Act") and not B.is_caps_line("") and not B.is_caps_line("CHAPTER 3"),
      "is_caps_line: a heading in capitals with no digit; '1[14A.' (a section number) and ordinary text are not")
LINES = ["The Test Act, 1999", "ARRANGEMENT OF SECTIONS", "1. Short title.", "BE it enacted by", "Parliament as follows:—", "CHAPTER I", "1. Short title.—This Act applies.", "2. Definitions.—In this Act, word means thing.", "THE FIRST SCHEDULE", "Organisation One"]
check(B.body_text(LINES) == "1. Short title.—This Act applies.\n2. Definitions.—In this Act, word means thing.", "body_text: starts after the enacting words (even when they run over two lines), leaves out capital-letter headings, ends where a Schedule begins")
check("enacted by Parliament" in (raises(B.body_text, ["1. Short title.—x"]) or ""), "body_text: a PDF with no enacting words stops the load")

# strip_repeated_heading
def chunk_of(num, title, body, **kw):
    return dict({"section_number": num, "title": title, "text": f"{num}. {title}\n{body}", "footnotes": "", "omitted": False}, **kw)


c = chunk_of("7", "Offence relating to public servant being bribed.", "[7. Offence relating to public servant being bribed.-- Any public servant who,--\n(a) takes a gift;]")
check(B.strip_repeated_heading(c) and c["text"] == "7. Offence relating to public servant being bribed.\n[Any public servant who,--\n(a) takes a gift;]", f"strip_repeated_heading: the heading that India Code repeats at the start of the body goes, the opening bracket stays ({c['text']!r})")
c = chunk_of("11", "Public servant obtaining undue advantage, without consideration.", "11. Public servant obtaining [undue advantage], without consideration.--Whoever, being a public servant, accepts ***")
check(B.strip_repeated_heading(c) and c["text"] == "11. Public servant obtaining undue advantage, without consideration.\nWhoever, being a public servant, accepts ***", "strip_repeated_heading: brackets inside the repeated heading do not matter; no bracket, none added")
c = chunk_of("42", "Alternative punishment.", "[42. Alternate punishment.-- Where an act is an offence]")
before = c["text"]
check(not B.strip_repeated_heading(c) and c["text"] == before, "strip_repeated_heading: a heading that differs by a word is NOT dropped (the title is corrected first; the comparison with the PDF would show it otherwise)")
c = chunk_of("5", "Omitted.", "Omitted by Act 1 of 2000.")
check(not B.strip_repeated_heading(c), "strip_repeated_heading: a body that does not start with the heading is left alone")

# set_aside_state_amendments
c = chunk_of("14", "Special Court.", "The State shall set up courts.\nSTATE AMENDMENT\nKarnataka\nAmendment of section 14.--In section 14 for the words \"x\" substitute \"y\".\n[Vide Karnataka Act 35 of 2003, s. 2 ]")
check(B.set_aside_state_amendments(c) and c["text"] == "14. Special Court.\nThe State shall set up courts.\n[Note: India Code also prints State or Union Territory amendments of this section (Karnataka); they apply only there and are not set out here.]"
      and c["state_amendments"].startswith("STATE AMENDMENT\nKarnataka\nAmendment of section 14.") and c["state_amendments"].endswith("s. 2 ]"), "set_aside_state_amendments: the State's text moves to its own field; the text keeps one note naming the State")
c = chunk_of("42", "Alternate punishment.", "Where an act is an offence.\nState Amendment:\nArunachal Pradesh.--\nAmendment of section 42.--text")
check(B.set_aside_state_amendments(c) and "(Arunachal Pradesh)" in c["text"], "set_aside_state_amendments: the label may be in any case and carry a colon; 'Arunachal Pradesh.--' is read as the name")
c = chunk_of("9", "Offence.", "Text.\nSTATE AMENDMENT\nAmendment of section 9.--text")
check(B.set_aside_state_amendments(c) and "amendments of this section; they apply only there" in c["text"] and "(" not in c["text"].split("\n")[-1], "set_aside_state_amendments: when the line after the label is not a name, the note names none")
c = chunk_of("9", "Offence.", "Text without any State amendment.")
check(not B.set_aside_state_amendments(c) and "state_amendments" not in c, "set_aside_state_amendments: nothing to set aside, nothing changed")
c = chunk_of("17A", "Approval.", "[17A. Approval.-- No police officer shall act.]\nSTATE AMENDMENT\nUnion Territory of Jammu and Kashmir and Union Territory of Ladakh\n17B. A new section.")
tidy = B.tidy_chunks([c])
check(tidy == {"heading_repeated_removed": 1, "state_amendments_set_aside": ["17A"]} and c["heading_repeat_removed"] is True, "tidy_chunks: both tidy-ups on a section, counted and recorded")
whole = B.full_section_text(c)
check("Note:" not in whole and whole.startswith("17A. Approval.\n[No police officer shall act.]") and whole.endswith("17B. A new section."), "full_section_text: India Code's whole text again (the shelf's note out, the State amendment back in)")

# the comparison itself
TXT = "1. Short title.—(1) This Act may be called the Test Act. (2) It extends to the whole of India.\n2. Definitions.—In this Act, a public servant means any person who serves the Government.\n3. Offence.—Whoever takes a bribe shall be punished. Provided that the court may reduce it. Explanation.—Gift includes money."
CH = [chunk_of("1", "Short title.", "(1) This Act may be called the Test Act. (2) It extends to the whole of India."), chunk_of("2", "Definitions.", "In this Act, a public servant means any person who serves the Government."),
      chunk_of("3", "Offence.", "Whoever takes a bribe shall be punished. Provided that the court may reduce it. Explanation.—Gift includes money.")]
oc = B.ordered_compare(CH, TXT)
check(oc["diffs"] == [] and oc["sections"] == 3 and oc["words"] > 40, f"ordered_compare: text that equals the PDF's has no difference ({oc['diffs']})")


def variant(sec, old_, new_):
    cs = copy.deepcopy(CH)
    for c_ in cs:
        if c_["section_number"] == sec:
            assert old_ in c_["text"], (old_, c_["text"])
            c_["text"] = c_["text"].replace(old_, new_)
    return B.ordered_compare(cs, TXT)["diffs"]


d = variant("2", "a public servant means", "a public public servant means")
check(len(d) == 1 and d[0]["tag"] == "delete" and d[0]["loaded"] == "public" and d[0]["pdf"] == "" and not d[0]["tail"], f"ordered_compare: a word the database doubles is found ({d})")
d = variant("3", "takes a bribe", "takes a bribes")
check(len(d) == 1 and d[0]["tag"] == "replace" and d[0]["loaded"] == "bribes" and d[0]["pdf"] == "bribe", "ordered_compare: a changed word is found")
d = variant("3", " Provided that the court may reduce it.", "")
check(len(d) == 1 and d[0]["tag"] == "insert" and d[0]["pdf"] == "provided that the court may reduce it" and not d[0]["tail"], f"ordered_compare: a whole proviso lost from the middle of a section is found ({d})")
d = variant("3", " Explanation.—Gift includes money.", "")
check(len(d) == 1 and d[0]["tag"] == "insert" and d[0]["tail"] and d[0]["pdf"] == "explanation gift includes money", f"ordered_compare: a sentence lost from the END of a section is found, and called a tail ({d})")
d = variant("1", "the Test Act.", "the Test Act's")
check(len(d) == 1 and d[0]["loaded"] == "act's" and d[0]["pdf"] == "act", "ordered_compare: an apostrophe that the PDF does not have is found")
cs = copy.deepcopy(CH)
oc2 = B.ordered_compare(cs, TXT.replace("Whoever takes", "Whoever 1 takes").replace("the Government.\n3.", "the Government.\n3."))
check(oc2["diffs"] == [] and oc2["digits_ignored"] == 1, "ordered_compare: a bare footnote number in the PDF is not a difference, and is counted")
oc3 = B.ordered_compare(CH, TXT.replace("any person who", "any per-\nson who"))
check(oc3["diffs"] == [], "ordered_compare: the same letters split at a line end are not a difference")
check("cannot be located" in (raises(B.ordered_compare, CH, TXT.replace("2. Definitions", "2. Meanings")) or ""), "ordered_compare: a section whose heading is not in the PDF stops the load (it cannot be compared)")
om = copy.deepcopy(CH)
om.insert(2, chunk_of("2A", "Omitted.", "Omitted by Act 3 of 2005.", omitted=True))
check(B.ordered_compare(om, TXT)["sections"] == 3, "ordered_compare: an omitted record is not compared (the PDF's stub for it is an accepted tail instead)")
sa = copy.deepcopy(CH)
sa[1]["text"] += "\nSTATE AMENDMENT\nKarnataka\nIn section 2 insert x."
B.set_aside_state_amendments(sa[1])
pdf_sa = B.body_text(["BE it enacted by Parliament as follows:"] + TXT.replace("Government.\n3.", "Government.\nSTATE AMENDMENT\nKarnataka\nIn section 2 insert x.\n3.").split("\n"))
check(B.ordered_compare(sa, pdf_sa)["diffs"] == [] and B.ordered_compare(sa, TXT)["diffs"] != [],
      "ordered_compare: a State amendment set aside is read back in, so it is still compared with the PDF (equal when the PDF has it, a difference when it does not)")

# explain_differences
dd = [{"section": "7", "tag": "replace", "loaded": "gazetted", "pdf": "gazette", "tail": False}, {"section": "7", "tag": "replace", "loaded": "gazetted", "pdf": "gazette", "tail": False},
      {"section": "16", "tag": "insert", "loaded": "", "pdf": "16a punishment for making demands omitted by act 3 of 2013 and more text", "tail": True},
      {"section": "1", "tag": "delete", "loaded": "1967 37 of", "pdf": "", "tail": False}]
acc = [{"section": "7", "loaded": "gazetted", "pdf": "gazette", "count": 2, "why": "x"}, {"section": "16", "pdf_starts": "16A. Punishment for making demands, omitted", "why": "x"}, {"section": "1", "loaded": "37 of 1967", "pdf": "", "why": "x"}]
un, unused = B.explain_differences(dd, acc)
check(un == [] and unused == [], f"explain_differences: accepted entries explain what they say (a count of 2, a tail by its first words, the same words in another order) ({un}, {unused})")
un, unused = B.explain_differences(dd, acc[:1] + acc[2:])
check([d_["section"] for d_ in un] == ["16"] and unused == [], "explain_differences: a difference nobody accepted is left over")
un, unused = B.explain_differences(dd[:1] + dd[2:], acc)
check(len(unused) == 1 and unused[0]["section"] == "7" and "_left" not in unused[0], "explain_differences: an accepted entry that matches fewer differences than its count is reported as unused")
un, unused = B.explain_differences([dict(dd[2], pdf="a lost sentence then 16a punishment for making demands omitted")], acc[1:2])
check(len(un) == 1 and len(unused) == 1, "explain_differences: a tail that does not START with the accepted words (a sentence lost before an omitted stub) is NOT explained")
un, unused = B.explain_differences([dict(dd[0], section="8")], acc[:1])
check(len(un) == 1, "explain_differences: an entry applies to its own section only")

# title corrections
tc = copy.deepcopy(chunks)
B.apply_corrections(tc, [{"section": "3", "field": "title", "from": "Offence of bribery.", "to": "Offence of corruption.", "why": "the PDF's running text says so"}])
check(tc[2]["title"] == "Offence of corruption." and tc[2]["text"].startswith("3. Offence of corruption.\n") and tc[2]["corrections"][0]["field"] == "title", "apply_corrections (title): the title and the heading line both change, and it is recorded")
check("0 times" in (raises(B.apply_corrections, copy.deepcopy(chunks), [{"section": "3", "field": "title", "from": "Offence of corruption.", "to": "x"}]) or ""), "apply_corrections (title): text that is not the title stops the load")
check(B.check_corrections_in_pdf([{"to": "Power of Chairman to transfer"}], B.pdf_vocabulary(["Power of 1[Chairman] to transfer cases"]), ["Power of 1[Chairman] to transfer cases"]) != []
      and B.check_corrections_in_pdf([{"to": "Power of Chairman to transfer"}], B.pdf_vocabulary(["Power of 1[Chairman] to transfer cases"]), ["Power of 1[Chairman] to transfer cases"], "Power of [Chairman] to transfer cases") == [],
      "check_corrections_in_pdf: a phrase the PDF prints with a footnote number inside it is found in the running text, where the footnote numbers are left out")

# end to end with the strict comparison
doubled = [rec("2", "Definitions.", "In this Act, public public servant means any person who serves the Government.") if B.md_first(r, "dc.identifier.section_number") == "2" else r for r in RECS]
msg = raises(B.build_act, ENTRY, FakeFetcher(doubled + DECOYS), "d") or ""
check("differs from the PDF" in msg and "public" in msg and "s.2" in msg, f"build_act: a doubled word that every other check passes stops the Act ({msg[:120]})")
ch6, rep6 = B.build_act(dict(ENTRY, corrections=[{"section": "2", "from": "public public servant", "to": "public servant", "why": "the PDF reads 'public servant'"}]), FakeFetcher(doubled + DECOYS), "d")
check(rep6["ordered_check"]["unexplained"] == [] and "public servant means" in ch6[1]["text"] and "public public" not in ch6[1]["text"], "build_act: the manifest's correction repairs it and the strict comparison then passes")
lost = [rec("3", "Offence of bribery.", "Whoever takes a bribe.", FOOT["3"]) if B.md_first(r, "dc.identifier.section_number") == "3" else r for r in RECS]
msg = raises(B.build_act, ENTRY, FakeFetcher(lost + DECOYS), "d") or ""
check("differs from the PDF" in msg and "s.3" in msg and "shall be punished" in msg, f"build_act: a sentence lost from a section (every word of it is still in the PDF somewhere) stops the Act ({msg[:140]})")
no_acc = {k: v for k, v in ENTRY.items() if k != "ordered_accepted"}
check("neither corrects nor accepts" in (raises(B.build_act, no_acc, FakeFetcher(RECS + DECOYS), "d") or "") and "4 omitted" in (raises(B.build_act, no_acc, FakeFetcher(RECS + DECOYS), "d") or ""), "build_act: the PDF's stub of an omitted section is a difference until the manifest accepts it")
check("no longer" in (raises(B.build_act, dict(ENTRY, ordered_accepted=ENTRY["ordered_accepted"] + [{"section": "2", "loaded": "x", "pdf": "y", "why": "z"}]), FakeFetcher(RECS + DECOYS), "d") or ""), "build_act: an accepted difference that is not there any more stops the Act")
ch7, rep7 = B.build_act(dict(ENTRY, ordered_accepted=[]), FakeFetcher(RECS + DECOYS), "d", discover=True)
check(len(rep7["ordered_check"]["unexplained"]) == 1 and rep7["ordered_check"]["unexplained"][0]["tail"], "build_act (discover): lists the differences instead of stopping")
check(rep["ordered_check"]["differences"] == 1 and rep["ordered_check"]["accepted_in_manifest"] == 1 and rep["ordered_check"]["sections_compared"] == 4 and rep["tidy"] == {"heading_repeated_removed": 0, "state_amendments_set_aside": []}, "build_act: the report says what the strict comparison covered")

# the layout rules on a real PDF made on the spot
try:
    import pymupdf as _fz
except ImportError:
    import fitz as _fz
doc = _fz.open()
pg = doc.new_page()
pg.insert_text((72, 100), "BE it enacted by Parliament as follows:", fontsize=11, fontname="tiro")
pg.insert_text((72, 120), "CHAPTER I", fontsize=11, fontname="tiro")
pg.insert_text((72, 140), "1. Short title.", fontsize=11, fontname="tibo")
pg.insert_text((130, 140), "This Act applies", fontsize=11, fontname="tiro")
pg.insert_text((230, 134), "3", fontsize=7, fontname="tiro")
pg.insert_text((240, 140), "to all.", fontsize=11, fontname="tiro")
pg.insert_text((72, 160), "2. Definitions.", fontsize=11, fontname="tibo")
pg.insert_text((150, 160), "A word means a thing.", fontsize=11, fontname="tiro")
pg.insert_text((250, 800), "IndiaCode", fontsize=30, fontname="hebo")
pg.draw_rect(_fz.Rect(76.6, 700, 220.6, 700.7), color=None, fill=(0, 0, 0))
pg.insert_text((72, 712), "3. Subs. by Act 16 of 2018, s. 4, for the old section 1.", fontsize=9, fontname="tiro")
pg.insert_text((72, 726), "A note that wraps onto a second line.", fontsize=9, fontname="tiro")
pdf_lines = REAL_PDF_BODY_LINES(doc.tobytes())
doc.close()
joined = "\n".join(pdf_lines)
check("This Act applies" in joined and "A word means a thing." in joined and "CHAPTER I" in joined, f"pdf_body_lines (a real PDF): the Act's lines are there ({pdf_lines})")
check("Subs. by Act 16" not in joined and "wraps onto" not in joined, "pdf_body_lines: everything below the footnote rule of a page is left out")
check("IndiaCode" not in joined and not re.search(r"applies\s*3", joined) and "3" not in "".join(ln for ln in pdf_lines if "applies" in ln).replace("1.", ""), "pdf_body_lines: the IndiaCode mark and the superscript footnote number are left out")
check(B.body_text(pdf_lines) == "\n".join(ln for ln in pdf_lines if "CHAPTER" not in ln and "enacted" not in ln) and "CHAPTER" not in B.body_text(pdf_lines), "body_text on those lines: the enacting line and the capital heading are left out")

# ---------------------------------------------------------------- Part 2: the shelf as committed
SHELF = os.path.join(HERE, "act_shelf")
manifest = json.load(open(os.path.join(SHELF, "manifest.json"), encoding="utf-8"))
M = {a["key"]: a for a in manifest["acts"]}
directory = {a["id"]: a for a in json.load(open(os.path.join(HERE, "acts_directory.json"), encoding="utf-8"))["acts"]}
check(list(M) == ["pc_act_1988", "pocso_act_2012", "uapa_1967", "pmla_2002", "sc_st_act_1989", "muslim_women_act_2019", "pdpp_act_1984", "dowry_prohibition_act_1961", "jj_act_2015"],
      "manifest: the five Acts the owner chose, the two very short ones, then the Dowry (1961) and Juvenile Justice (2015) Acts added on 2026-10-17")
check(len({a["code"] for a in M.values()}) == 9 and all(re.fullmatch(r"[A-Z]+", a["code"]) for a in M.values()), "manifest: nine distinct upper-case codes")
check([k for k, a in M.items() if a.get("whole_act")] == ["muslim_women_act_2019", "pdpp_act_1984"], "manifest: only the two very short Acts are marked whole_act (the Dowry and JJ Acts are over the size limit)")
check(M["dowry_prohibition_act_1961"].get("toc_absent") == ["8A"] and all("toc_absent" not in a for k, a in M.items() if k != "dowry_prohibition_act_1961"),
      "manifest: only the Dowry Act declares toc_absent (section 8A, in the PDF body but omitted from the printed arrangement of sections)")
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


# ---- the strict comparison and the two tidy-ups, as committed (2026-10-17)
for k, a in M.items():
    oc_ = report[k]["ordered_check"]
    n_real = len([c for c in SH[k] if not c["omitted"]])
    check(oc_["unexplained"] == [] and oc_["accepted_unused"] == [] and oc_["sections_compared"] == n_real and oc_["words_compared"] > 500 and oc_["differences"] == oc_["accepted_in_manifest"] == sum(int(x.get("count", 1)) for x in a["ordered_accepted"]),
          f"{k}: the strict comparison covered all {n_real} sections ({oc_['words_compared']} words); every difference ({oc_['differences']}) is accepted in the manifest with a reason, none is left over")
    check(all(x.get("why", "").strip() for x in a["ordered_accepted"]), f"{k}: every accepted difference says why")
    check(not any(B.strip_repeated_heading(copy.deepcopy(c)) for c in SH[k]), f"{k}: no section starts its body with its own heading again")
    check(not any(re.search(r"STATE\s+AMENDMENT", c["text"], re.I) for c in SH[k]), f"{k}: no State amendment text is left inside a section's text")
    check(all((B.NOTE_PREFIX in c["text"]) == bool(c.get("state_amendments")) and c["text"].count(B.NOTE_PREFIX) <= 1 for c in SH[k]), f"{k}: a section that has State amendments set aside carries exactly one note, and no other section has one")
    check(not any(re.search(r"\b([A-Za-z]+)\s+\1\b", (c.get(f) or ""), re.I) for c in SH[k] for f in ("text", "footnotes", "state_amendments")), f"{k}: no word is doubled anywhere ('or or', 'of of' were database slips)")
check({c["section_number"] for k in SH for c in SH[k] if c.get("state_amendments")} == {"17A", "42", "14"} and len(SH["pc_act_1988"][[c["section_number"] for c in SH["pc_act_1988"]].index("17A")]["text"]) < 2500,
      "State amendments set aside: PC Act 17A (Jammu and Kashmir / Ladakh), POCSO 42 (Arunachal Pradesh), SC/ST 14 (Karnataka); section 17A is now short (it was 10,167 characters, 84% of them the Union Territory text)")
sec = lambda k, n: next(c for c in SH[k] if c["section_number"] == n)  # noqa: E731
check("closure report before the Special Court; or]" in sec("pmla_2002", "44")["text"] and sec("pmla_2002", "44")["text"].index("closure report") < sec("pmla_2002", "44")["text"].index("[(c) if the court which has taken cognizance"),
      "PMLA s.44: the proviso the database had lost (closure report) is there, between clause (b) and clause (c)")
check("property or lease-hold" in sec("pmla_2002", "9")["text"] and "section 12 of the Smugglers" in sec("pmla_2002", "25")["text"] and "that person's handwriting" in sec("pmla_2002", "22")["text"] and "victim's age" in sec("sc_st_act_1989", "15A")["text"],
      "PMLA ss.9, 22, 25 and SC/ST s.15A: the doubled words and the lost apostrophes are repaired")
t9 = sec("pocso_act_2012", "9")["text"]
check(t9.count("is said to commit aggravated sexual assault") == 1 and t9.rstrip().endswith("attains early sexual maturity,]\nis said to commit aggravated sexual assault.") and "naked in public;\n[(v)" in t9,
      "POCSO s.9: 'is said to commit aggravated sexual assault' comes once, after the last clause (v), as in the PDF (the database had put it after (u))")
check(sec("pocso_act_2012", "42")["title"] == "Alternate punishment." and sec("pocso_act_2012", "42")["text"].startswith("42. Alternate punishment.\n") and sec("uapa_1967", "43")["title"].endswith("offences under Chapters IV and VI.") and sec("pmla_2002", "37")["title"] == "Power of Chairman to transfer cases.",
      "titles corrected to the heading of the PDF's running text: POCSO 42, UAPA 43, PMLA 37")

# ---- the two very short Acts (2026-10-17)
mw7 = sec("muslim_women_act_2019", "7")["text"]
check(mw7.count("or any person related to her by blood or marriage") == 1 and "(a) an offence punishable under this Act shall be cognizable, if information relating to the commission of the offence is given to an officer in charge of a police station by the married Muslim woman upon whom talaq is pronounced or any person related to her by blood or marriage;" in mw7
      and "compoundable, at the instance of the married Muslim woman upon whom talaq is pronounced with the permission of the Magistrate, on such terms and conditions as he may determine;" in mw7
      and "after hearing the married Muslim woman upon whom talaq is pronounced, is satisfied that there are reasonable grounds for granting bail" in mw7 and "; is pronounced" not in mw7,
      "Muslim Women Act s.7: the clause (a) wording stays, and the splice India Code's database had copied into clauses (b) and (c) ('or any person related to her by blood or marriage; is pronounced') is gone: compounding and the bail hearing are the woman's, as in the PDF")
check(len(M["muslim_women_act_2019"]["corrections"]) == 2 and all(c["section"] == "7" for c in M["muslim_women_act_2019"]["corrections"]) and sum(len(c.get("corrections", [])) for c in SH["muslim_women_act_2019"]) == 2,
      "Muslim Women Act: exactly two corrections, both in s.7, each recorded on the chunk")
check("rigrous imprisonment" in sec("pdpp_act_1984", "4")["text"] and "rigorous imprisonment" in sec("pdpp_act_1984", "3")["text"] and M["pdpp_act_1984"]["pdf_as_on"] == B.NO_PDF_DATE and M["pdpp_act_1984"]["accepted"][0]["word"] == "rigrous",
      "Public Property Act: 'rigrous' in s.4 is left as India Code's database has it (its PDF reads 'regorous'; s.3(2) of both reads 'rigorous'), the manifest accepts it with a reason, and the PDF carries no date")
check(len(SH["muslim_women_act_2019"]) == 8 and len(SH["pdpp_act_1984"]) == 7 and not any(c["omitted"] for k in ("muslim_women_act_2019", "pdpp_act_1984") for c in SH[k]) and all(c.get("footnotes") == "" for c in SH["pdpp_act_1984"] if c["section_number"] != "1"),
      "the two short Acts: 8 and 7 sections, none omitted; the Public Property Act's only footnote is the one on section 1")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
