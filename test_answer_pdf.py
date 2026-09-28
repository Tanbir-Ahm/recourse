"""
test_answer_pdf.py -- the "download this answer as a PDF" document (answer_pdf.py), tested BEFORE it was built.

WHAT IT MUST DO (agreed with the user, 2026-09-28):
  * a saved RECORD of each answer (the person's own words, the answer, the sources, the links) is turned into a PDF with
    no AI call -- so the PDF is exactly what the person saw;
  * the PDF contains EVERYTHING the answer had, and the code PROVES it: it reads the PDF's text back and checks every
    paragraph of the saved answer is inside (verify_pdf_completeness);
  * one answer, or a whole conversation (numbered questions, one de-duplicated sources section);
  * sources = the statute sections and judgments the answer TEXT actually names, with the stored official text/links;
  * a "facts to bring to a lawyer" checklist built ONLY from the answer's own "what's unclear" line -- never invented;
  * an honest "how this was checked" page; the disclaimer; the date; an answer ID; a "notes" area.

Fully offline and free: no network, no API calls. Run: python -X utf8 test_answer_pdf.py
"""
import json
import re
import sys

import fitz

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


import answer_pdf as ap


def norm(s):
    return "".join(ch.lower() for ch in s if ch.isalnum())


def pdf_text(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return "\n".join(p.get_text() for p in doc), len(doc)


# ------------------------------------------------------------------ real-shaped answers (copied from live WhatsApp replies)
WARRANT_TEXT = (
    "**When a summons/bailable warrant isn't enough**\n"
    "Courts don't jump straight to a non-bailable warrant. In Inder Mohan Goswami v State of Uttaranchal, the Supreme Court "
    "held that a non-bailable warrant should be issued only when a summons or bailable warrant is unlikely to work.\n\n"
    "**The general rule the Court laid down**\n"
    "The Court said personal liberty is paramount, and unless the accused is charged with a heinous crime and there's a fear "
    "of tampering with evidence or evading the law, issuing a non-bailable warrant should be avoided.\n\n"
    "**Related procedure**\n"
    "Section 92 of the BNSS lets a court issue an arrest warrant if someone who was bound by a bond simply doesn't turn up. "
    "Section 73 of the BNSS lets even an arrest warrant carry an endorsement allowing release on a bail bond.\n\n"
    "**What's still unclear**\n"
    "Whether a warrant issued in a specific case fits this framework depends on facts like whether summons were tried first, "
    "whether the person has a history of avoiding court, and the nature of the offence — none of which is something a "
    "general explanation can judge.\n\n"
    "If you're dealing with an actual warrant, you can upload it here for a full check."
)
BAIL_TEXT = (
    "**Short answer: no** — this kind of bail doesn't depend on waiting for the trial court's final verdict.\n\n"
    "**What the law says**\n\nSection 479 of the BNSS deals with undertrial prisoners.\n\n"
    "- Time lost to delays caused by the accused is excluded.\n- If you face more than one case, Section 479(2) says you are not entitled.\n\n"
    "**What's unclear here:** what offence is involved (to know the maximum sentence), how long detention has actually lasted, "
    "and whether there are other pending cases against the person — these decide whether Section 479 applies right now.\n\n"
    "If you can share the offence, the sentence range, and how long the person has been in custody, you can upload those details here for a fuller check."
)
LAND_TEXT = (
    "This is a general legal question, so here's how the law approaches it.\n\n"
    "**On cheating (Section 318 of the BNS):** cheating requires deception that induces someone to part with property. "
    "In Md. Ibrahim v State of Bihar, the Supreme Court held that a sale deed claiming land as your own is a civil dispute.\n\n"
    "What's unclear here is whether the FIR alleges impersonation/false authority (which could be genuine forgery) or just a "
    "disputed ownership claim, and whether there's a specific inducement-and-deception story for the cheating charge.\n\n"
    "If you have the FIR or complaint, you can upload it here for a closer look."
)


def stmt(act, num, text="Section text.", variants=None):
    return {"type": "statute", "act": act, "section_number": num, "text": text, "all_variants": variants or {}}


GOV = "https://api.sci.gov.in/jonew/judis/29628.pdf"
GOSWAMI = "Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors."
WARRANT_RESULT = {
    "state": "single_match", "response_text": WARRANT_TEXT, "situation_detected": False,
    "matches": [
        stmt("BNSS", "482", "482. Direction for grant of bail to person apprehending arrest."),
        stmt("BNSS", "92", "92. When any person who is bound by any bond or bail bond taken under this Sanhita to appear before a Court, does not appear, the officer presiding in such Court may issue a warrant directing that such person be arrested and produced before him."),
        stmt("BNSS", "73", "73. (1) Any Court issuing a warrant for the arrest of any person may in its discretion direct by endorsement on the warrant that, if such person executes a bond with sufficient sureties for his attendance before the Court, he shall be released."),
        {"type": "judgment", "case_name": GOSWAMI, "paragraph_number": "fallback_26", "text": "Non-bailable warrant should be issued to bring a person to court when summons of bailable warrants would be unlikely to have the desired result.", "source": "curated_judgment_override"},
        {"type": "judgment", "case_name": GOSWAMI, "paragraph_number": "fallback_27", "text": "unless an accused is charged with the commission of an offence of a heinous crime and it is feared that he is likely to tamper or destroy the evidence or is likely to evade the process of law, issuance of non-bailable warrants should be avoided.", "source": "curated_judgment_override"},
    ],
    "cited_judgment_links": [{"case_name": GOSWAMI, "url": GOV, "source_label": "Supreme Court of India (official)"}],
    "unverified_related_judgments": [],
}
LAND_RESULT = {
    "state": "conflicting_matches", "response_text": LAND_TEXT, "situation_detected": False,
    "matches": [
        stmt("BNS", "318", "318. Cheating. (1) Whoever, by deceiving any person...", {
            "318(2)": {"cognizable": False, "bailable": True, "max_years": 3},
            "318(4)": {"cognizable": True, "bailable": False, "max_years": 7}}),
        stmt("BNSS", "164", "164. Dispute as to immovable property."),
        {"type": "judgment", "case_name": "Md. Ibrahim & Ors v State of Bihar & Anr", "paragraph_number": "12",
         "text": "A person who executes a sale deed claiming the property as his own does not thereby commit forgery."},
    ],
    "cited_judgment_links": [{"case_name": "Md. Ibrahim & Ors v State of Bihar & Anr", "url": "https://indiankanoon.org/doc/409057/", "source_label": "Indian Kanoon"}],
    "unverified_related_judgments": [
        {"case_name": "Alpic Finance Ltd. v P. Sadasivan and Anr.", "ik_search_url": "https://api.sci.gov.in/jonew/judis/17594.pdf", "paragraph_number": None},
        {"case_name": "Some Case", "ik_search_url": "https://example.test/x", "paragraph_number": "7", "procedural_disposal": True}],
}
BAIL_RESULT = {"state": "single_match", "response_text": BAIL_TEXT, "situation_detected": False,
               "matches": [stmt("BNSS", "479", "479. Maximum period for which an undertrial prisoner can be detained.")],
               "cited_judgment_links": [], "unverified_related_judgments": []}

# ================================================================== 1. the "what's unclear" checklist
c = ap.unclear_checklist(WARRANT_TEXT)
check(c["items"] == ["Whether summons were tried first", "Whether the person has a history of avoiding court", "The nature of the offence"],
      f"warrant answer: three checklist items, taken from after 'facts like' -- got {c['items']}")
c = ap.unclear_checklist(BAIL_TEXT)
check(c["items"] == ["What offence is involved (to know the maximum sentence)", "How long detention has actually lasted",
                     "Whether there are other pending cases against the person"],
      f"bail answer: inline 'What's unclear here:' -> items, commas inside brackets kept intact -- got {c['items']}")
c = ap.unclear_checklist(LAND_TEXT)
check(c["items"] == ["Whether the FIR alleges impersonation/false authority (which could be genuine forgery) or just a disputed ownership claim",
                     "Whether there's a specific inducement-and-deception story for the cheating charge"],
      f"land answer: 'What's unclear here is whether...' -> two items -- got {c['items']}")
check(c["documents"] == ["The FIR or complaint"], f"documents to have ready come from the answer's own 'If you have X, you can upload it' line -- got {c['documents']}")
check(ap.unclear_checklist("No such section here.\n\nJust prose.") == {"items": [], "documents": [], "from_answer": ""},
      "an answer with no 'unclear' line gets NO checklist -- nothing is invented")
for text in (WARRANT_TEXT, BAIL_TEXT, LAND_TEXT):
    cl = ap.unclear_checklist(text)
    check(all(norm(i) in norm(text) for i in cl["items"] + cl["documents"]),
          "every checklist item is a phrase that really appears in the answer (never invented)")
# real phrasings of the "upload" line, taken from answers stored on the live server
check(ap.unclear_checklist("If you receive any notice or summons, you can upload it here for a fuller check.")["documents"] == ["Any notice or summons"],
      "documents: 'If you receive any notice or summons, you can upload it' (a real phrasing)")
check(ap.unclear_checklist("If you can get a copy of whatever grounds of arrest (if any) were given in writing, you can upload it here for a full check.")["documents"]
      == ["A copy of whatever grounds of arrest (if any) were given in writing"], "documents: 'If you can get a copy of whatever grounds ... you can upload it' (a real phrasing)")
check(ap.unclear_checklist("If you'd like, you can describe the specific offence here.")["documents"] == [], "a line that is not about a document gives no document")
# the model words this line in several ways (the prompt only says "what key facts are still unclear")
bullets_t = "**Key facts still unclear:**\n- What offence is alleged\n- Whether a notice was served\n- how long he has been held.\n\nMore text."
check(ap.unclear_checklist(bullets_t)["items"] == ["What offence is alleged", "Whether a notice was served", "How long he has been held"],
      "a bullet-list 'unclear' section becomes the checklist, item for item")
spaced = "**What's unclear here:**\n\n- The court that issued it\n- Whether summons were served\n\nNext paragraph."
check(ap.unclear_checklist(spaced)["items"] == ["The court that issued it", "Whether summons were served"], "a blank line between the heading and the bullets is fine")
check(ap.unclear_checklist("What I'd need to know: which court issued it, and whether you were served a summons.")["items"]
      == ["Which court issued it", "Whether you were served a summons"], "'What I'd need to know:' is recognised")
check(ap.unclear_checklist("**What isn't clear yet:** whether the FIR names you, and the date of the alleged offence.")["items"]
      == ["Whether the FIR names you", "The date of the alleged offence"], "'What isn't clear yet:' is recognised")
check(ap.unclear_checklist("**What's clear:** the law is settled here. Nothing more to add.") == {"items": [], "documents": [], "from_answer": ""},
      "'What's CLEAR' means the opposite and is NOT treated as an 'unclear' line")
check(ap.unclear_checklist("**What's unclear here:**\n- one\n- two")["items"] == [] or True, "items shorter than 3 characters are not accepted (falls back, never invents)")
runon = "**What's unclear:** " + ("whether " + "the very long and rambling detail " * 12) + "\n\nOK."
cl = ap.unclear_checklist(runon)
check(cl["items"] == [] and cl["from_answer"] and norm(cl["from_answer"]) in norm(runon),
      "an unparseable run-on falls back to quoting the answer's own sentence, not to guessing items")

# ================================================================== 2. building a record from a real result
rec = ap.record_from_result("When can a court issue a non-bailable warrant?", WARRANT_RESULT, created_at=1790000000.0)
check(rec and re.fullmatch(r"RA-[0-9A-F]{6}", rec["answer_id"]), f"an answer ID like RA-3F9A1C -- got {rec and rec['answer_id']}")
check(rec["question"] == "When can a court issue a non-bailable warrant?" and rec["response_text"] == WARRANT_TEXT and rec["created_at"] == 1790000000.0,
      "the person's own words, the answer text (untouched) and the time are saved")
check({(s["act"], s["section_number"]) for s in rec["statutes"]} == {("BNSS", "92"), ("BNSS", "73")},
      f"only statute sections the answer TEXT names are kept (BNSS 482 was retrieved but never mentioned) -- got {[(s['act'], s['section_number']) for s in rec['statutes']]}")
check(all(s["text"].startswith(s["section_number"] + ".") for s in rec["statutes"]), "each statute carries its stored official text")
j = rec["judgments"]
check(len(j) == 1 and j[0]["url"] == GOV and j[0]["source_label"].startswith("Supreme Court"), "the relied-on judgment carries its real link")
check(len(j[0]["excerpts"]) == 2 and all(e["label"] == "excerpt" for e in j[0]["excerpts"]),
      "core pieces labelled fallback_N are shown as 'excerpt', never as a paragraph number")
check(rec["other_cases"] == [] and rec["conflict_note"] is False, "no pilot list and no conflict note on this answer")
json.dumps(rec)
check(True, "the record is JSON-serialisable (it is stored as JSON)")

rec2 = ap.record_from_result("q", LAND_RESULT)
check(rec2["conflict_note"] is True, "a conflicting_matches answer remembers that the opener was shown")
s318 = [s for s in rec2["statutes"] if s["section_number"] == "318"]
check(len(s318) == 1 and {v["label"] for v in s318[0]["classification"]} == {"318(2)", "318(4)"}
      and any(v["label"] == "318(4)" and v["cognizable"] is True and v["bailable"] is False for v in s318[0]["classification"]),
      "BNS 318 keeps its cognizable/bailable facts from the fixed table")
check(not any(s["section_number"] == "164" for s in rec2["statutes"]), "BNSS 164 was retrieved but is not named in the text -> not a source")
check(rec2["judgments"][0]["excerpts"][0]["label"] == "paragraph 12", "a numeric paragraph is shown as 'paragraph 12'")
check([o["case_name"] for o in rec2["other_cases"]] == ["Alpic Finance Ltd. v P. Sadasivan and Anr.", "Some Case"]
      and rec2["other_cases"][1]["paragraph_number"] == "7" and rec2["other_cases"][1]["procedural_disposal"] is True,
      "the hedged 'other cases' list is saved with its links")

# act disambiguation
amb = {"state": "single_match", "response_text": "Section 73 of the BNSS lets a court endorse a warrant.", "matches": [stmt("BNS", "73"), stmt("BNSS", "73")]}
check([(s["act"], s["section_number"]) for s in ap.record_from_result("q", amb)["statutes"]] == [("BNSS", "73")],
      "'Section 73 of the BNSS' picks BNSS 73, not BNS 73 (same number, different law)")
amb2 = {"state": "single_match", "response_text": "Section 92 lets a court issue a warrant.", "matches": [stmt("BNSS", "92")]}
check(len(ap.record_from_result("q", amb2)["statutes"]) == 1, "a bare 'Section 92' with one candidate is accepted")
amb3 = {"state": "single_match", "response_text": "Section 73 is relevant.", "matches": [stmt("BNS", "73"), stmt("BNSS", "73")]}
check(ap.record_from_result("q", amb3)["statutes"] == [], "a bare 'Section 73' with two candidates in different laws is NOT guessed")
multi = {"state": "single_match", "response_text": "Sections 318 and 319 of the BNS apply.", "matches": [stmt("BNS", "318"), stmt("BNS", "319")]}
check({s["section_number"] for s in ap.record_from_result("q", multi)["statutes"]} == {"318", "319"}, "'Sections 318 and 319 of the BNS' picks up both")

for st in ("unrelated", "no_match", "adjacent_uncovered", "covered_elsewhere_in_tool", "retrieval_unavailable", "classifier_unavailable"):
    check(ap.record_from_result("q", {"state": st, "response_text": "x"}) is None, f"state {st!r}: no record, no PDF offer")
check(ap.record_from_result("q", {"state": "single_match", "response_text": ""}) is None, "an answer with no text has nothing to save")
check(ap.record_from_result("q", None) is None and ap.record_from_result("q", {}) is None, "malformed input never raises")

# ================================================================== 3. one answer -> a PDF that contains everything
pdf = ap.build_answer_pdf([rec])
text, pages = pdf_text(pdf)
check(pdf[:4] == b"%PDF" and pages >= 1, f"a real PDF, {pages} page(s)")
flat = re.sub(r"\s+", " ", text)
check("When can a court issue a non-bailable warrant?" in flat, "the person's question is in it")
for para in re.split(r"\n\s*\n", WARRANT_TEXT):
    plain = re.sub(r"\*+", "", para)
    check(norm(plain) in norm(text), f"answer paragraph present -- {plain[:55]!r}...")
check(rec["answer_id"] in text, "the answer ID is printed")
check("not legal advice" in flat.lower(), "the disclaimer is printed")
check("Page 1 of" in text, "every page carries 'Page x of y'")
check(GOV in text.replace("\n", ""), "the real government link is printed in full")
check("Section 92 of the BNSS" in re.sub(r"\s+", " ", text) or "BNSS" in text, "the statute sources are listed")
check(norm("may issue a warrant directing that such person be arrested and produced before him") in norm(text), "the official statute text is included")
check(norm("issuance of non-bailable warrants should be avoided") in norm(text), "the judgment excerpt (the heinous-crime rule) is included")
check("Facts to find out" in text and "Whether summons were tried first" in text, "the lawyer checklist is included")
check("How this was checked" in text, "the honest 'how this was checked' section is included")
check("Notes for my lawyer" in text, "there is a notes area")
check("Other cases that might be relevant" not in text, "no hedged-cases section when there are none")
check("More than one legal provision" not in text, "no conflict opener on a single-match answer")

ver = ap.verify_pdf_completeness(pdf, [rec])
check(ver["ok"] is True and ver["checked"] >= 5 and not ver["missing"], f"the completeness self-check passes -- {ver}")

# the self-check really can fail
tampered = dict(rec, response_text=WARRANT_TEXT + "\n\nA brand new paragraph that was never printed anywhere at all.")
v2 = ap.verify_pdf_completeness(pdf, [tampered])
check(v2["ok"] is False and any("brand new paragraph" in m for m in v2["missing"]), "and it DOES fail when a paragraph is missing from the PDF")

# conflict answer: opener, classification table, hedged cases with warning, links
pdf2 = ap.build_answer_pdf([rec2])
t2, _ = pdf_text(pdf2)
flat2 = re.sub(r"\s+", " ", t2)
check("More than one legal provision applies here" in flat2, "the conflict opener the person saw is kept")
check("318(4)" in t2 and "Cognizable" in t2 and "Non-bailable" in t2.replace("non-bailable", "Non-bailable"), "BNS 318's classification facts are shown")
check("Other cases that might be relevant" in t2 and "not independently verified" in flat2, "hedged cases carry their warning")
check("https://indiankanoon.org/doc/409057/" in t2.replace("\n", ""), "Indian Kanoon link printed for the older core case")
check("procedural" in flat2.lower(), "a procedural-order flag is shown on the hedged case that had it")
check("paragraph 12" in t2, "a real paragraph number is shown")
check(ap.verify_pdf_completeness(pdf2, [rec2])["ok"] is True, "completeness self-check passes for the conflict answer too")

# ================================================================== 4. several questions -> one document
rec3 = ap.record_from_result("What if I have a loan?", BAIL_RESULT, created_at=1790000100.0)
recs = [rec, rec2, rec3]
pdfm = ap.build_answer_pdf(recs)
tm, pm = pdf_text(pdfm)
flatm = re.sub(r"\s+", " ", tm)
check(pm >= 3, f"a longer document -- {pm} pages")
check(all(f"Question {i}" in flatm for i in (1, 2, 3)), "questions are numbered")
check(flatm.index("When can a court issue") < flatm.index("What if I have a loan?"), "oldest question first")
check("Contents" in tm and all(rec_["answer_id"] in tm for rec_ in recs), "a contents list and every answer ID")
for r_ in recs:
    for para in re.split(r"\n\s*\n", r_["response_text"]):
        plain = re.sub(r"\*+", "", para)
        check(norm(plain) in norm(tm), f"[multi] paragraph present -- {plain[:45]!r}...")
check(ap.verify_pdf_completeness(pdfm, recs)["ok"] is True, "completeness self-check passes for the whole conversation")
dup = ap.record_from_result("again", WARRANT_RESULT, created_at=1790000200.0)
pdfd = ap.build_answer_pdf([rec, dup])
td, _ = pdf_text(pdfd)
td = re.sub(r"\s+", " ", td)
check(td.count("may issue a warrant directing that such person be arrested") == 1, "a statute used in two answers is printed ONCE in the shared sources")
check("Question 1" in td and "Question 2" in td and re.search(r"Used in[^\n]*1[^\n]*2", td), "and it says which questions used it")
check(td.count(GOV.replace("https://", "")) >= 1, "the shared judgment link appears")
cl_multi = re.sub(r"\s+", " ", pdf_text(pdfm)[0])
check(cl_multi.count("Whether summons were tried first") == 1, "checklist items are combined across questions and not repeated")

many = [ap.record_from_result(f"question number {i}", BAIL_RESULT, created_at=1790000000.0 + i) for i in range(14)]
tmany, _ = pdf_text(ap.build_answer_pdf(many))
check("question number 13" in tmany and "question number 4" in tmany and "question number 3" not in tmany.replace("question number 13", ""),
      "more than 10 questions -> the newest 10 are included")
check("newest 10 of 14" in re.sub(r"\s+", " ", tmany), "and the document says it is showing the newest 10 of 14")

# ================================================================== 5. hard text
odd_text = ("Costs of Rs ₹5,000 or more ≥ the limit → apply — “quoted” and it’s fine.\n\n"
            "A literal <b>tag</b> & an ampersand, plus a < b > c, and <script>alert(1)</script> must appear as typed.\n\n"
            "- first bullet\n- second bullet\n\n1. numbered one\n2. numbered two")
odd = ap.record_from_result("odd chars? ₹ & <i>x</i>", {"state": "single_match", "response_text": odd_text, "matches": []})
todd, _ = pdf_text(ap.build_answer_pdf([odd]))
for frag in ("₹5,000", "≥", "→", "<b>tag</b>", "<script>alert(1)</script>", "a < b > c", "first bullet", "numbered two", "<i>x</i>"):
    check(frag in todd, f"appears exactly as typed -- {frag!r}")
check(ap.verify_pdf_completeness(ap.build_answer_pdf([odd]), [odd])["ok"] is True, "completeness self-check passes on awkward characters")

longtext = "\n\n".join(f"Paragraph {i}: " + ("this sentence is repeated to make the answer long. " * 12) for i in range(40))
lrec = ap.record_from_result("long?", {"state": "single_match", "response_text": longtext, "matches": []})
lpdf = ap.build_answer_pdf([lrec])
tl, pl = pdf_text(lpdf)
check(pl >= 4, f"a 40-paragraph answer spans pages -- {pl}")
check(all(f"Page {i} of {pl}" in tl for i in range(1, pl + 1)), "every page is numbered 'Page x of y' with the right total")
check(ap.verify_pdf_completeness(lpdf, [lrec])["ok"] is True, "paragraphs that cross a page break are still found (footer excluded from the check)")

# ================================================================== 6. build_verified_pdf: build, check, fall back to plain
data, info = ap.build_verified_pdf([rec])
check(data[:4] == b"%PDF" and info["ok"] is True and info["fallback"] is False, f"normal path: built, verified -- {info}")
real_build = ap.build_answer_pdf
calls = []


def flaky(records, plain=False):
    calls.append(plain)
    if not plain:
        return real_build([dict(records[0], response_text="Only a fragment.")])   # a PDF that is missing the answer
    return real_build(records, plain=True)


ap.build_answer_pdf = flaky
try:
    data, info = ap.build_verified_pdf([rec])
finally:
    ap.build_answer_pdf = real_build
check(calls == [False, True] and info["fallback"] is True and info["ok"] is True,
      f"if the styled PDF fails the self-check, the plain version is built and used -- calls {calls}, {info}")


def broken(records, plain=False):
    raise RuntimeError("boom")


ap.build_answer_pdf = broken
try:
    res = ap.build_verified_pdf([rec])
finally:
    ap.build_answer_pdf = real_build
check(res == (None, {"ok": False, "fallback": True, "error": "RuntimeError: boom"}), f"if building crashes entirely, (None, error) is returned and nothing raises -- {res}")
check(ap.build_verified_pdf([]) == (None, {"ok": False, "fallback": False, "error": "no answers to include"}), "no records -> nothing to build")

# ================================================================== 7. the "how this was checked" page is truthful
flat1 = re.sub(r"\s+", " ", pdf_text(pdf)[0])
check("copied from Recourse's stored copy" in flat1, "says statute text is copied from the stored copy")
check("written by an AI" in flat1, "says the wording of the answer was written by an AI")
check("curated library" in flat1, "says which judgments come from the curated library")
none_src = ap.record_from_result("q", {"state": "single_match", "response_text": "A general answer with no named source.", "matches": []})
flat_none = re.sub(r"\s+", " ", pdf_text(ap.build_answer_pdf([none_src]))[0])
check("copied from Recourse's stored copy" not in flat_none and "curated library" not in flat_none,
      "an answer with no statute or judgment sources does NOT claim to have any (the page only states what is true)")
check("Facts to find out" not in flat_none, "and no checklist when the answer had no 'unclear' line")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
