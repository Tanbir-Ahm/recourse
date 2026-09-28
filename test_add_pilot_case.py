"""
test_add_pilot_case.py -- the one-command "stage, then approve" tool for adding a pilot case.
Fully offline and free: a synthetic PDF built in memory, a fake embedder, temp folders. No network,
no API calls, never touches the real pilot_chunks/ or pilot_corpus/.
Run: python -X utf8 test_add_pilot_case.py
"""
import json
import os
import sys
import tempfile

import fitz

import add_pilot_case as apc

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def make_pdf(header_date="01/02/2003", pages=2) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        lines = []
        if i == 0:
            lines += ["SUPREME COURT OF INDIA", "CASE NO.:", "Appeal (crl.) 5 of 2003", "PETITIONER:",
                      "JOHN QUINCEDOE AND ANR.", "RESPONDENT:", "STATE OF NOWHERE AND ORS.",
                      f"DATE OF JUDGMENT: {header_date}", "BENCH:", "A. BEE & C. DEE", "JUDGMENT:",
                      "2003 (1) SCR 100"]
        lines += [f"This is line {j} of page {i} of a synthetic judgment used only for testing the tool." for j in range(14)]
        page.insert_text((40, 40), "\n".join(lines), fontsize=8)
    data = doc.tobytes()
    doc.close()
    return b"\x00\x00\x00\x00" + data   # sci.gov.in files have junk bytes before %PDF


def fake_embed(texts):
    return [[0.1 * (i % 7 + 1), 0.2, 0.3] for i, _ in enumerate(texts)]


def fake_query(q):
    return [0.1, 0.2, 0.3]


QUOTE = "This is line 3 of page 0 of a synthetic judgment used only for testing the tool."
NO_VAQUILL = lambda token, sentence: {"found_in_vaquill": None, "vaquill_case_id": None}


def run(tmp, **kw):
    lines = []
    base = dict(link="https://example.test/x.pdf", name="John Quincedoe and Anr. v State of Nowhere and Ors.",
                citation="(2003) 1 SCC 1", topic="test_topic", pdf_bytes=make_pdf(),
                quotes=[QUOTE], use_ik=False, vaquill_fn=NO_VAQUILL,
                staging_dir=os.path.join(tmp, "stg"), corpus_dir=os.path.join(tmp, "corp"),
                chunks_dir=os.path.join(tmp, "chunks"), embed_fn=fake_embed, query_fn=fake_query,
                out=lines.append)
    base.update(kw)
    return apc.stage_case(**base), "\n".join(lines)


# ---------------------------------------------------------------- 1. names and small helpers
check(apc.slugify("Sushila Aggarwal v State (NCT of Delhi)") == "sushila_aggarwal_v_state_nct_of_delhi",
      "the bracket problem: '(NCT of Delhi)' produces a clean filename, no literal brackets")
check(apc.slugify("G. Sagar Suri and Anr. v State of U.P. and Ors.") == "g_sagar_suri_and_anr_v_state_of_up_and_ors",
      "an ordinary name slugs exactly the way the existing chunker named the real Sagar Suri file")
check(apc._looks_like_pdf(b"\x00\x00\x00\x00%PDF-1.2\n") and not apc._looks_like_pdf(b"<html>blocked</html>"),
      "a PDF with junk bytes before the marker is recognised; a web page is not")
hdr = apc.parse_header("CASE NO.:\nAppeal 1\nPETITIONER:\nG. SAGAR SURI AND ANR.\nRESPONDENT:\nSTATE OF UP. AND ORS.\n"
                       "DATE OF JUDGMENT: 28/01/2000\nBENCH:\nS. SAGHIR AHMAD & D. P. WADHWA\nJUDGMENT:\nJUDGMENT\n2000 (1) SCR 417\n")
check(hdr.get("date") == "28/01/2000" and hdr.get("petitioner") == "G. SAGAR SURI AND ANR."
      and hdr.get("bench") == "S. SAGHIR AHMAD & D. P. WADHWA" and hdr.get("reporter") == "2000 (1) SCR 417",
      f"the real judis header shape is read correctly -- got {hdr}")
check(apc.parse_header("just some prose with no header at all") == {}, "no header -> empty, not a crash or a guess")
hdr3 = apc.parse_header("PETITIONER:\nALPIC FINANCE LTD.\n        Vs.\nRESPONDENT:\nP. SADASIVAN AND ANR.\nDATE OF JUDGMENT:       16/02/2001\n"
                        "BENCH:\nS. Rajendra Babu & K.G. Balakrishnan.\nJUDGMENT:\n")
check(hdr3.get("petitioner") == "ALPIC FINANCE LTD." and hdr3.get("date") == "16/02/2001",
      f"a header with its own 'Vs.' line (the real Alpic Finance PDF) is read without the stray 'Vs.' -- got {hdr3.get('petitioner')!r}")
hdr2 = apc.parse_header("PETITIONER:\nS.W. PALANITKAR AND ORS.\nRESPONDENT:\nSTATE OF BIHAR AND ANR.\nDATE OF JUDGMENT: 18/10/2001\n"
                        "BENCH:\nD.P. MOHAPATRA & SHIVARAJ V. PATIL\nJUDGMENT:\nJUDGMENT\n2001 ( 4 )   Suppl.  SCR  397\n")
check(hdr2.get("reporter") == "2001 ( 4 ) Suppl. SCR 397",
      f"the real Palanitkar reporter line (extra spaces, 'Suppl.') is found -- a gap the first fresh-case run exposed; got {hdr2.get('reporter')!r}")
batches = list(apc._batches_by_chars(["a" * 40] * 5, budget=100, max_items=100))
check([len(b) for b in batches] == [2, 2, 1] and sum(len(b) for b in batches) == 5,
      f"embedding batches respect the character budget, keep every item, in order -- got {[len(b) for b in batches]}")
check(list(apc._batches_by_chars(["x"] * 250, budget=10**9, max_items=100)) and
      all(0 < len(b) <= 100 for b in apc._batches_by_chars(["x"] * 250, budget=10**9, max_items=100)),
      "batches also respect the max item count, and never yield an empty batch")

# ---------------------------------------------------------------- 2. a clean case stages -- and stays OUT of the live folders
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, expected_date="01/02/2003", questions=["is a late repayment cheating?"])
    check(res["status"] == "staged" and not res["blockers"], f"a clean synthetic case stages cleanly -- {res['blockers']}")
    d = res["case_dir"]
    files = set(os.listdir(d))
    check({"source.pdf", "record.json", "report.txt", "status.json", f"{res['slug']}_chunks.json"} <= files,
          f"everything a person needs is in the staging folder -- got {sorted(files)}")
    check(not os.path.exists(os.path.join(tmp, "chunks")) and not os.path.exists(os.path.join(tmp, "corp")),
          "NOTHING was written to the live pilot folders during stage")
    chunks = json.load(open(os.path.join(d, f"{res['slug']}_chunks.json"), encoding="utf-8"))
    check(chunks and all(c["topic"] == "test_topic" and len(c["embedding"]) == 3 for c in chunks),
          "every chunk carries the topic tag and an embedding")
    check("(" not in res["slug"] and all("(" not in f for f in files), "no brackets anywhere in the staged filenames")
    check("Header in PDF:" in report and "JOHN QUINCEDOE" in report and "date 01/02/2003" in report,
          "the report shows the header that was actually read from the PDF, for a person to compare")
    check("this case scores" in report and "test_topic" in report, "the report shows how the real test question scored")
    check("NOT live" in report and "approve" in report, "the report says plainly that it is not live and how to approve")

    # ------------------------------------------------------------ 3. approve moves it in, once
    out_lines = []
    ap = apc.approve_case(res["slug"], staging_dir=os.path.join(tmp, "stg"), corpus_dir=os.path.join(tmp, "corp"),
                          chunks_dir=os.path.join(tmp, "chunks"), out=out_lines.append)
    check(os.path.isfile(os.path.join(tmp, "chunks", f"{res['slug']}_chunks.json"))
          and os.path.isfile(os.path.join(tmp, "corp", f"{res['slug']}.json")),
          "approve copies the chunks and the record into the live folders")
    check(ap["cases_in_pool"] == 1 and "NOT committed, NOT deployed" in "\n".join(out_lines),
          "approve reports the new pool size and says it did not commit or deploy")
    try:
        apc.approve_case(res["slug"], staging_dir=os.path.join(tmp, "stg"), corpus_dir=os.path.join(tmp, "corp"),
                         chunks_dir=os.path.join(tmp, "chunks"), out=lambda s: None)
        check(False, "approving the same case twice must be refused")
    except apc.CaseError:
        check(True, "approving an already-approved case is refused")
    try:
        run(tmp)
        check(False, "staging a case that is already live must be refused")
    except apc.CaseError as exc:
        check("already in the live" in str(exc), "staging a case that is already live is refused -- no silent duplicates")

# ---------------------------------------------------------------- 4. blockers stop the case and are never fixed silently
with tempfile.TemporaryDirectory() as tmp:
    def boom(texts):
        raise AssertionError("embedding must NOT run for a blocked case (no wasted spend)")
    res, report = run(tmp, expected_date="09/09/1999", embed_fn=boom)
    check(res["status"] == "blocked" and any("wrong file" in b for b in res["blockers"]),
          "a date that contradicts the PDF header BLOCKS the case")
    check("BLOCKED:" in report and "Nothing was put in the live" in report, "the report shows the blocker and says nothing went live")
    try:
        apc.approve_case(res["slug"], staging_dir=os.path.join(tmp, "stg"), corpus_dir=os.path.join(tmp, "corp"),
                         chunks_dir=os.path.join(tmp, "chunks"), out=lambda s: None)
        check(False, "a blocked case must not be approvable")
    except apc.CaseError as exc:
        check("blocked" in str(exc), "approve refuses a blocked case")

with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, pdf_bytes=b"<html>Access denied</html>", embed_fn=lambda t: 1 / 0)
    check(res["status"] == "blocked" and any("not a PDF" in b for b in res["blockers"]),
          "a web page instead of a PDF is caught and blocked, not passed to the chunker")

with tempfile.TemporaryDirectory() as tmp:
    real = apc._collisions
    apc._collisions = lambda d: [{"file": "x_chunks.json", "case_name": "X", "paragraph_number": "5",
                                  "distinct_texts": 2, "error": None}]
    try:
        res, report = run(tmp, embed_fn=lambda t: 1 / 0)
    finally:
        apc._collisions = real
    check(res["status"] == "blocked" and any("paragraph 5" in b for b in res["blockers"]),
          "a paragraph-number collision BLOCKS the case and names the paragraph -- it is never deleted or fixed silently")

with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, name="Zzyzx Qwerty v State of Nowhere")
    check(res["status"] == "staged" and any("qwerty" in w for w in res["warnings"]),
          "a name word missing from the PDF header is a WARNING (a person decides), not a block")

# ---------------------------------------------------------------- 5. it never overwrites work in progress
with tempfile.TemporaryDirectory() as tmp:
    run(tmp)
    try:
        run(tmp)
        check(False, "restaging over a case in progress must need --replace")
    except apc.CaseError:
        check(True, "a case already in staging is not silently overwritten")
    res, _ = run(tmp, replace=True)
    check(res["status"] == "staged", "--replace deliberately starts a staged case over")

# ---------------------------------------------------------------- 6. the quote check (manual check #1, now mechanical)
OFFICIAL = ("The Court held as follows. A mere failure to keep up promise\nsubsequently cannot be pre-sumed as an act "
            "leading to cheating.\nLooking to the complaint and the grievances it is clear that the dispute is civil.")
r_exact = apc.check_quote("A mere failure to keep up promise subsequently cannot be pre-sumed as an act leading to cheating.", OFFICIAL)
check(r_exact["status"] == "exact", f"a quote that is really there, word for word, is EXACT -- got {r_exact['status']}")
check(r_exact["before"].endswith("The Court held as follows.") and r_exact["after"].startswith("Looking to the complaint"),
      "the text just before and just after the quote is returned, so a person can see what sits next to it")
r_cos = apc.check_quote("A mere failure to keep up promise subsequently cannot be presumed as an act leading to cheating.", OFFICIAL)
check(r_cos["status"] == "cosmetic" and "pre-sumed" in r_cos["matched"],
      "'presumed' vs the official 'pre-sumed' is flagged as cosmetic AND the real official wording is shown -- the exact case found in Palanitkar")
check(apc.check_quote("A mere failure to keep up promise subsequently WILL be treated as an act leading to cheating.", OFFICIAL)["status"] == "missing",
      "a quote with even one word changed is MISSING -- it can't be passed off as verbatim")
check(apc.check_quote("too short", OFFICIAL)["status"] == "too_short", "a quote too short to mean anything is refused, not waved through")

PAGED = ("The appellant company filed a private complaint under Section 200 before the Chief Metropolitan Magistrate, Bangalore alleging\n"
         "http://JUDIS.NIC.IN \nSUPREME COURT OF INDIA\nPage 2 of 6 \n"
         "that the respondents had committed offences under Sections 420, 406 and 423. The Magistrate took cognizance.")
r_paged = apc.check_quote("before the Chief Metropolitan Magistrate, Bangalore alleging that the respondents had committed offences under Sections 420, 406 and 423.", PAGED)
check(r_paged["status"] == "exact" and "JUDIS" not in r_paged["matched"],
      f"a quote that runs across a PDF page break (the running header sits mid-sentence) is still found -- the real Alpic case; got {r_paged['status']}")

# ---------------------------------------------------------------- 7. the similarity score
base_text = " ".join(f"word{i % 97} filler{i} sentence{i % 13}" for i in range(400))
same = apc.compare_texts(base_text, base_text)
check(same["similarity"] == 1.0 and same["official_covered"] == 1.0 and same["other_covered"] == 1.0,
      "identical texts score exactly 1.0 on similarity and 100% coverage both ways")
with_header = apc.compare_texts(base_text, "Some Case vs State on 1 January, 2000 Equivalent citations: AIR 2000 SC 1 " + base_text)
check(with_header["similarity"] > 0.97 and with_header["official_covered"] > 0.99,
      f"a copy with an extra header line still scores very high -- got similarity {with_header['similarity']:.3f}")
unrelated = apc.compare_texts(base_text, " ".join(f"other{i} thing{i * 7}" for i in range(400)))
check(unrelated["similarity"] < 0.2 and unrelated["official_covered"] < 0.05, "an unrelated document scores very low")
huge = " ".join(f"w{i}" for i in range(apc.MAX_SEQUENCE_WORDS + 50))
big = apc.compare_texts(huge, huge)
check(big["similarity"] is None and big["official_covered"] == 1.0 and apc._score(big) == 1.0,
      "a text too long for the word-by-word comparison falls back to coverage instead of hanging")

# ---------------------------------------------------------------- 8. citations written two ways, and finding the right Indian Kanoon page
check(apc._citation_keys("(2002) 1 SCC 241") & apc._citation_keys("AIR 2001 SC 2960, 2002 (1) SCC 241, 2001 (4) Suppl. SCR 397"),
      "'(2002) 1 SCC 241' and '2002 (1) SCC 241' are recognised as the same citation")
check(("2001", "4", "SCR", "397") in apc._citation_keys("2001 ( 4 )   Suppl.  SCR  397"),
      "the 'Suppl.' reporter form with extra spaces is read correctly")
docs = {"docs": [
    {"tid": 1, "title": "S.W. Palanitkar And Ors vs State Of Bihar And Anr on 18 October, 2001"},
    {"tid": 2, "title": "Some Other Case vs State Of Bihar on 3 March, 2005"},
    {"tid": 3, "title": "<b>S.W. Palanitkar</b> And Ors vs State Of Bihar And Anr on 5 June, 2010"}]}
nm = "S.W. Palanitkar and Ors. v State of Bihar and Anr."
check(apc._find_ik_case(nm, "18/10/2001", docs)[0] == "1", "exactly one result matches both name and date -> picked automatically")
check(apc._find_ik_case(nm, "01/01/1999", docs)[0] is None, "a date that matches no result -> NO pick (never guesses)")
check(apc._find_ik_case(nm, None, docs)[0] is None and len(apc._find_ik_case(nm, None, docs)[2]) == 2,
      "two results match the name and no date was given -> no pick, both listed for a person")

check(apc._ik_query("S.W. Palanitkar and Ors. v State of Bihar and Anr.") == "palanitkar bihar doctypes: supremecourt",
      "the search query is the distinctive word from each party, limited to Supreme Court -- NOT the formal name, which returned ten unrelated cases live")
check(apc._ik_query("Alpic Finance Ltd. v P. Sadasivan and Anr.").endswith("sadasivan doctypes: supremecourt"),
      "and it keeps the rare surname for a case whose first party has a generic word in its name")

# ---------------------------------------------------------------- 9. the Indian Kanoon copy, end to end with fakes
def ik_fixture(pdf_bytes, mutate=lambda t: t, listed="2003 (1) SCC 1, AIR 2003 SC 9"):
    with tempfile.TemporaryDirectory() as t2:
        pth = os.path.join(t2, "x.pdf")
        with open(pth, "wb") as fh:
            fh.write(pdf_bytes)
        official = apc.extract_text(pth)[0]
    ik_html = ("<html><body><h1>John Quincedoe And Anr vs State Of Nowhere And Ors on 1 February, 2003</h1>"
               f"<p>Equivalent citations: {listed} Author: A. Bee</p><p>" + mutate(official).replace("\n", "</p><p>") + "</p></body></html>")
    search = {"docs": [{"tid": 77, "title": "John Quincedoe And Anr vs State Of Nowhere And Ors on 1 February, 2003",
                        "docsource": "Supreme Court of India", "headline": "the intention ... inducement ... synthetic"}]}
    return search, {"doc": ik_html}


pdf = make_pdf()
search, doc = ik_fixture(pdf)
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, use_ik=True, expected_date="01/02/2003", ik_search_fn=lambda q: search, ik_doc_fn=lambda tid: doc)
    check(res["status"] == "staged", f"a matching Indian Kanoon copy leaves the case staged -- {res['blockers']}")
    check("SIMILARITY to the official text: 0.9" in report or "SIMILARITY to the official text: 1.0" in report,
          "the report PRINTS the similarity score")
    check("Coverage:" in report and "of the official text's phrases are in the Indian Kanoon copy" in report, "and the coverage figures")
    check("Quotes also in the Indian Kanoon copy: 1 of 1" in report, "and whether each quote is also in that copy")
    check("is among them" in report and "NOT among" not in report, "the recorded citation is matched against Indian Kanoon's listed citations, written either way")
    check("does not independently confirm" in report, "the report says plainly this copy shares its source with the official file")
    check("NONE AVAILABLE" in report and "NOT a pass" in report, "and that there is no independent-origin copy, and that this is NOT a pass")
    st = json.load(open(os.path.join(res["case_dir"], "status.json"), encoding="utf-8"))
    check(st["indian_kanoon"]["ran"] and st["indian_kanoon"]["similarity"] > 0.9 and st["quotes_verified"] and st["independent_copy"] == "none_available",
          "the score and results are recorded in status.json, not just printed")

search, doc = ik_fixture(pdf, listed="2003 (9) SCC 999")
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, use_ik=True, ik_search_fn=lambda q: search, ik_doc_fn=lambda tid: doc)
    check(any("not among Indian Kanoon" in w for w in res["warnings"]) and res["status"] == "staged",
          "a recorded citation Indian Kanoon does not list is a WARNING for a person, not a block")

search, doc = ik_fixture(pdf, mutate=lambda t: "Completely unrelated text about something else entirely. " * 60)
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, use_ik=True, ik_search_fn=lambda q: search, ik_doc_fn=lambda tid: doc, embed_fn=lambda t: 1 / 0)
    check(res["status"] == "blocked" and any("different or truncated" in b for b in res["blockers"]),
          "an Indian Kanoon copy that is nothing like the official text BLOCKS the case, before any embedding spend")

search, doc = ik_fixture(pdf, mutate=lambda t: t[: int(len(t) * 0.75)] + " extra words that are not in the official text at all " * 12)
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, use_ik=True, ik_search_fn=lambda q: search, ik_doc_fn=lambda tid: doc)
    check(res["status"] == "staged" and any("compare by hand" in w for w in res["warnings"]),
          "a copy that is only somewhat different (a truncated one) WARNS, and the score is still printed")


def dead(q):
    raise RuntimeError("no network")


with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, use_ik=True, ik_search_fn=dead)
    check(res["status"] == "staged" and any("could not run" in w and "NOT a pass" in w for w in res["warnings"]),
          "if Indian Kanoon can't be reached, that is a loud warning that says NOT a pass -- never a silent pass, never a crash")

two = {"docs": [{"tid": 1, "title": "John Quincedoe And Anr vs State Of Nowhere on 1 February, 2003"},
                {"tid": 2, "title": "John Quincedoe vs State Of Nowhere And Ors on 1 February, 2003"}]}
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, use_ik=True, expected_date="01/02/2003", ik_search_fn=lambda q: two, ik_doc_fn=lambda t: 1 / 0)
    check(any("--ik-doc-id" in w for w in res["warnings"]), "two equally good Indian Kanoon matches -> it does not guess, it tells you to pass --ik-doc-id")
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, use_ik=True, ik_doc_id="77", ik_search_fn=lambda q: two, ik_doc_fn=lambda t: doc if t == "77" else 1 / 0)
    check("document 77" in report and "SIMILARITY" in report, "--ik-doc-id skips the pick and fetches exactly that document")

# ---------------------------------------------------------------- 10. the independent-origin copy (Vaquill)
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, vaquill_fn=lambda tok, sent: {"found_in_vaquill": True, "vaquill_case_id": "c1"})
    check("ARE in it" in report and res["status"] == "staged", "an independent copy that contains the key sentence is reported as found")
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, vaquill_fn=lambda tok, sent: {"found_in_vaquill": False, "vaquill_case_id": "c1"})
    check(any("independent-origin copy does not contain" in w for w in res["warnings"]), "an independent copy that lacks it is a warning to check by hand")

# ---------------------------------------------------------------- 11. approve is gated on the quote check
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, quotes=[])
    check(res["status"] == "staged" and any("no --quote given" in w for w in res["warnings"]),
          "staging with no quotes works but says plainly that nothing was verified")
    try:
        apc.approve_case(res["slug"], staging_dir=os.path.join(tmp, "stg"), corpus_dir=os.path.join(tmp, "corp"),
                         chunks_dir=os.path.join(tmp, "chunks"), out=lambda s: None)
        check(False, "a case whose quotes were never verified must not be approvable")
    except apc.CaseError as exc:
        check("word for word" in str(exc) and not os.path.exists(os.path.join(tmp, "chunks")),
              "approve REFUSES a case whose quotes were never verified, and puts nothing in the live folders")
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, quotes=["This sentence is certainly not anywhere in the synthetic document at all."], embed_fn=lambda t: 1 / 0)
    check(res["status"] == "blocked" and "NOT FOUND" in report and any("NOT in the official text" in b for b in res["blockers"]),
          "a quote that is not in the official text BLOCKS the case before any embedding spend")

# ---------------------------------------------------------------- 12. the automatic second reader, wired into stage
import second_reader as sr


def canned_reader(**kw):
    return {"models": ["fake-model", "fake-model"], "usage": [None, None],
            "blind": {"key_points": [{"point": "p", "quote": QUOTE, "whose_words": "court's own reasoning"}],
                      "final_order": "x", "dissent": "none"},
            "compare": {"claims": [{"id": 1, "verdict": "SUPPORTED", "reason": "r", "quote": QUOTE},
                                   {"id": 2, "verdict": "NOT_SUPPORTED", "reason": "the text says otherwise", "quote": QUOTE}],
                        "quotes": [{"id": 1, "whose_words": "quotation of an earlier case", "quoted_source": "Some v Case"}],
                        "missing_important_points": []}}


with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, claims=["claim a", "claim b"], reader_fn=canned_reader)
    check(res["status"] == "staged" and "Second reader (blind, different model: fake-model)" in report,
          "with a claims list, stage runs the second reader and prints its section")
    check("FLAG claim 2" in report and "FLAG quote 1" in report, "the reader's flags appear in the report")
    check(any("flagged summary claim(s) [2]" in w for w in res["warnings"]) and any("NOT the Court's own words" in w for w in res["warnings"]),
          "flags become warnings a person must read -- but never blockers, the reader approves and rejects nothing")
    st = json.load(open(os.path.join(res["case_dir"], "status.json"), encoding="utf-8"))
    check(st["second_reader"]["ran"] and st["second_reader"]["supported_verified"] == 1 and st["second_reader"]["flagged_claims"] == [2],
          "the outcome is recorded in status.json")
    check(os.path.isfile(os.path.join(res["case_dir"], "second_reader.json")), "the reader's full raw answer is kept in the case folder for audit")


def unavailable(**kw):
    raise sr.ReaderUnavailable("gemini-x: HTTP 503")


with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, claims=["claim a"], reader_fn=unavailable)
    check(res["status"] == "staged" and any("second reader unavailable" in w and "NOT a pass" in w for w in res["warnings"]),
          "if no model answers, the case still stages, with a loud 'NOT a pass' warning pointing at the ChatGPT step")
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp)
    check(any("no --claims-file" in w for w in res["warnings"]), "no claims given -> a warning that the summary was NOT second-read")
with tempfile.TemporaryDirectory() as tmp:
    res, report = run(tmp, claims=["claim a"], use_reader=False, reader_fn=lambda **k: 1 / 0)
    check("Second reader: skipped" in report, "--no-reader skips it and never calls it")

# ---------------------------------------------------------------- 12b. second-read on an ALREADY-staged case (the normal order)
with tempfile.TemporaryDirectory() as tmp:
    res, _ = run(tmp)          # staged with no claims, as happens before the summary is written
    stg, corp, chk = os.path.join(tmp, "stg"), os.path.join(tmp, "corp"), os.path.join(tmp, "chunks")
    st0 = json.load(open(os.path.join(res["case_dir"], "status.json"), encoding="utf-8"))
    check(st0["quotes"] == [QUOTE] and any("no --claims-file" in w for w in st0["warnings"]),
          "staging remembers the quotes, and warns that no claims were second-read yet")
    seen = {}

    def spy_reader(**kw):
        seen.update(kw)
        return canned_reader(**kw)

    lines_out = []
    r2 = apc.second_read_case(res["slug"], ["claim a", "claim b"], staging_dir=stg, reader_fn=spy_reader, out=lines_out.append)
    st1 = json.load(open(os.path.join(res["case_dir"], "status.json"), encoding="utf-8"))
    check(r2["ran"] and seen["quotes"] == [QUOTE] and st1["second_reader"]["flagged_claims"] == [2],
          "second-read reuses the quotes given at stage and records the result")
    check(not any("no --claims-file" in w for w in st1["warnings"]) and any("flagged summary claim(s) [2]" in w for w in st1["warnings"]),
          "the 'not second-read' warning is replaced by the reader's real flags")
    check("Second reader (blind" in open(os.path.join(res["case_dir"], "report.txt"), encoding="utf-8").read()
          and os.path.isfile(os.path.join(res["case_dir"], "second_reader.json")),
          "the report file gets the second-reader section, and the raw answer is kept")
    check(st1["status"] == "staged" and st1["quotes_verified"], "a flagged claim never changes the case's status -- flags are for a person")
    apc.second_read_case(res["slug"], ["claim a"], staging_dir=stg, reader_fn=unavailable, out=lambda s: None)
    st2 = json.load(open(os.path.join(res["case_dir"], "status.json"), encoding="utf-8"))
    check(not st2["second_reader"]["ran"] and any("NOT a pass" in w for w in st2["warnings"]) and not any("flagged summary claim" in w for w in st2["warnings"]),
          "if the reader is unavailable on a re-run, the old flags are cleared and a 'NOT a pass' warning takes their place")
    for bad, why in (((), "empty claims"), (None, "unknown case")):
        try:
            apc.second_read_case("nope" if why == "unknown case" else res["slug"], ["c"] if why == "unknown case" else bad,
                                 staging_dir=stg, reader_fn=canned_reader, out=lambda s: None)
            check(False, f"second-read must refuse {why}")
        except apc.CaseError:
            check(True, f"second-read refuses {why}")

# ---------------------------------------------------------------- 13. claims files, verify-quotes, review-pack
with tempfile.TemporaryDirectory() as tmp:
    cf = os.path.join(tmp, "claims.txt")
    with open(cf, "w", encoding="utf-8") as fh:
        fh.write("# a comment\n1. First claim here.\n\n2) Second claim here.\nThird claim, no number.\n")
    check(apc.read_claims(cf) == ["First claim here.", "Second claim here.", "Third claim, no number."],
          "a claims file: numbering stripped, comments and blank lines ignored")

check(apc.extract_quoted_passages('He said “the Court held that this is a long enough quoted sentence” and "another quoted passage that is long enough" but "short".')
      == ["the Court held that this is a long enough quoted sentence", "another quoted passage that is long enough"],
      "quoted passages are pulled out of a pasted answer, curly or straight quotes, and short ones are ignored")

with tempfile.TemporaryDirectory() as tmp:
    res, _ = run(tmp)
    stg, corp = os.path.join(tmp, "stg"), os.path.join(tmp, "corp")
    af = os.path.join(tmp, "chatgpt_answer.txt")
    with open(af, "w", encoding="utf-8") as fh:
        fh.write(f'The Court said "{QUOTE}" and also "This sentence was invented by the assistant and is nowhere in the judgment."')
    out_lines = []
    vq = apc.verify_quotes(res["slug"], af, staging_dir=stg, corpus_dir=corp, out=out_lines.append)
    check(vq["passages"] == 2 and vq["exact"] == 1 and vq["missing"] == 1, f"verify-quotes: one real quote passes, one invented quote is caught -- got {vq}")
    check("NOT IN THE OFFICIAL TEXT" in "\n".join(out_lines), "and it says plainly that the missing one may have been paraphrased or invented")

    cf = os.path.join(tmp, "claims.txt")
    with open(cf, "w", encoding="utf-8") as fh:
        fh.write("Cheating needs dishonest intent at the start.\nThe appeal was dismissed.\n")
    pk = apc.review_pack(res["slug"], cf, quotes=[QUOTE], staging_dir=stg, corpus_dir=corp, out=lambda s: None)
    s1 = open(pk["step1"], encoding="utf-8").read()
    s2 = open(pk["step2"], encoding="utf-8").read()
    check("synthetic judgment used only for testing" in s1 and "Cheating needs dishonest intent" not in s1 and "ONLY this text" in s1,
          "review-pack step 1 is BLIND: the judgment text, an instruction to use only it, and none of our claims")
    check("1. Cheating needs dishonest intent" in s2 and "2. The appeal was dismissed." in s2 and "Do not say SUPPORTED without a quote" in s2 and "Q1." in s2,
          "step 2 carries the numbered claims, the quote-attribution question, and the no-verdict-without-a-quote rule")
    check("This is line 5 of page 0" not in s2 and "This is line 5 of page 0" in s1,
          "step 2 does not repeat the judgment text (it is pasted in the same chat after step 1) -- only the quote we pass in appears")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
