"""
test_court_labels.py -- a High Court judgment among the wider-search passages is never worded as a Supreme Court one.

Since the wide index of 2026-10-24 the sci-search service can hold Gauhati High Court judgments beside the Supreme Court's, and sends a `court` for each result. This file checks every place that words the court:
the prompt (heading, the passage heads, the rule), the cases the engine returns, the sources box of the Streamlit page, the answer view, the PDF/Word export, the authorities table, the search page's wider search,
the notice for an answer that calls a High Court case a Supreme Court one -- and, as the main point, that when EVERY passage is a Supreme Court one (or the service sends no court, as the one on production does)
every string is exactly what it was before. Fully offline and free: a function stands in for the service. Run: python -X utf8 test_court_labels.py
"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import answer_export as X
import answer_view as V
import authorities_table as AT
import grounding_checks as G
import passage_notes as PN
import sci_search_tier as T
import search_service as SS

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


SC, HC, NR = "Supreme Court of India", "Gauhati High Court", "Court not recorded"


def res(doc, name, date, court=None, kind="court_archive_pdf", text="Arrest is not to be made routinely.", para="9"):
    r = {"rank": doc, "doc": doc, "case_name": name, "date": date, "paragraph": para, "link": f"https://x.example/{doc}.pdf", "link_kind": kind, "text": text, "name_to_review": False, "citations": {}}
    if court is not None:
        r["court"] = court
    return r


A_SC = res(1, "Arnesh Kumar v. State of Bihar", "2014-07-02", SC)
B_SC_OLD = res(1, "Arnesh Kumar v. State of Bihar", "2014-07-02")                       # a service that sends no court (production's)
C_HC = res(2000000001, "Dinathso Chaitom v. The State of AP", "2020-12-17", HC, "high_court_bucket_pdf", "The bail application is allowed on the following conditions.", "4")
D_NR = res(2000000004, "Unknown Petitioner v. The State", "2021-03-01", NR, "high_court_site_pdf", "A passage.", "2")


# ---- 1. the helpers ----
check(T.court_of({}) == SC and T.court_of({"court": ""}) == SC and T.court_of({"court": None}) == SC and T.court_of({"court": "  Gauhati   High Court "}) == HC and T.court_of(None) == SC, "court_of: none given means the Supreme Court; blanks are squeezed")
check(not T.mixed([A_SC, B_SC_OLD]) and T.mixed([A_SC, C_HC]) and T.mixed([C_HC]) and not T.mixed([]), "mixed: true only when some passage is not a Supreme Court one")
check(T.scope_phrase([SC]) == "Supreme Court" and T.scope_phrase([SC, HC]) == "Supreme Court and High Court" and T.scope_phrase([HC]) == "High Court" and T.scope_phrase([]) == "Supreme Court", "scope_phrase: Supreme Court / Supreme Court and High Court / High Court")
check(T.scope_phrase([SC, NR]) == "Supreme Court and other court" and T.scope_phrase([NR]) == "court" and T.scope_phrase([SC, HC, NR]) == "Supreme Court and other court", "scope_phrase: a court that is not recorded is not called a High Court")
check(T.short_court(SC) == "Supreme Court" and T.short_court(HC) == HC and T.short_court(None) == "Supreme Court", "short_court")
check(T.credit_for("open_bucket_pdf") == X.OPEN_BUCKET and T.credit_for("court_archive_pdf") == "" and T.credit_for(None) == "" and "licence terms to be confirmed" in T.credit_for("high_court_bucket_pdf")
      and "High Court's own website" in T.credit_for("high_court_site_pdf") and "Supreme Court" not in T.credit_for("high_court_bucket_pdf"), "credit_for: the old bucket credit unchanged; the High Court bucket is credited as one and its licence is said to be unconfirmed")
check(T.box_title([A_SC], True) == X.H_SCI_FED and T.box_title([B_SC_OLD], False) == X.H_SCI_SHOWN, "box_title: for Supreme Court passages the headings are the ones the page and the export had")
check(T.box_title([A_SC, C_HC], True) == "Supreme Court and High Court passages from a wider search that this answer also read (not independently verified)"
      and T.box_title([A_SC, C_HC], False) == "More Supreme Court and High Court judgments that may be relevant (a wider search; not independently verified)"
      and T.box_title([C_HC], True).startswith("High Court passages from a wider search"), "box_title: names the courts when a High Court passage is among them")
check(T.asof_sentence("2026-07-13") == " The collection ends 2026-07-13." and T.asof_sentence(None) == "" and T.asof_sentence("2026-07-13", {SC: "2026-07-13"}) == " The collection ends 2026-07-13.", "asof_sentence: the old sentence for one date")
check(T.asof_sentence("2026-10-16", {HC: "2026-10-14", SC: "2026-10-16"}) == " The collection ends 2026-10-16 for the Supreme Court and 2026-10-14 for the Gauhati High Court.", "asof_sentence: one date for each court, the Supreme Court first")

# ---- 2. the prompt's opening ----
check(T.feed_instruction([SC]) is T.FEED_INSTRUCTION and T.feed_instruction([SC, SC]) is T.FEED_INSTRUCTION and T.feed_instruction([]) is T.FEED_INSTRUCTION, "feed_instruction: all Supreme Court -> the very same text as before")
for old, new in T._feed_swaps("Supreme Court and High Court", "x"):
    check(T.FEED_INSTRUCTION.count(old) == 1, f"feed_instruction: the text it changes is in the old instruction exactly once ({old[:50]!r})")
mx = T.feed_instruction([SC, HC])
check("## Supreme Court and High Court passages from a wider, automatic search -- NOT independently verified" in mx and "a much larger collection of Supreme Court and High Court judgments" in mx, "feed_instruction (mixed): the heading and the first sentence name both courts")
check('("the Supreme Court in X said ..." or "the Gauhati High Court in X said ...")' in mx and T.COURT_RULE in mx and "NEVER call a High Court's decision a decision of the Supreme Court" in mx, "feed_instruction (mixed): the example names both courts and the rule is there")
check(T.LABEL in mx and "REGISTER FACT" in mx and "Do not say that a case is good law" in mx and mx.count("NOT independently verified") == 1, "feed_instruction (mixed): the label rule, the register rule and the good-law rule are kept")
hc_only = T.feed_instruction([HC])
check("## High Court passages from a wider, automatic search" in hc_only and '("the Gauhati High Court in X said ...")' in hc_only and "the Supreme Court in X said" not in hc_only, "feed_instruction (High Court only)")
nr_text = T.feed_instruction([NR])
check("## Court passages from a wider, automatic search" in nr_text and "a much larger collection of court judgments" in nr_text and "High Court passages" not in nr_text, "feed_instruction (court not recorded): a plain 'Court passages', never 'High Court'")


# ---- 3. the feed: the block and the cases ----
def feed(results, question="my bail question"):
    found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": results}
    saved = T.search
    T.search = lambda *a, **k: found
    os.environ["SCI_SEARCH_MODE"] = "feed"
    os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
    try:
        T.reset()
        with contextlib.redirect_stdout(io.StringIO()):
            return T.feed_block(question), list(T._LOCAL.cases)
    finally:
        T.search = saved


# ---- 2b. the rule for quoted passages (staging 2026-10-26: a paragraph of V.L. Rohlua, quoted in Sadhwi Pragyna Singh Thakur, was credited to Sadhwi with Rohlua's paragraph number) ----
RULE_PARTS = ("A passage can be a QUOTATION from another, earlier decision", "a 1968 arrest described in a judgment of 2011", "never say that the listed case decided, held or recorded it",
              "never give its paragraph number, which belongs to the quoted decision and not to the listed case", "build no ground and no For/Against point on it",
              "from an earlier decision that the passage does not name, and that the original must be checked", "A quoted section of a statute is not a problem")
check(all(x in T.FEED_INSTRUCTION for x in RULE_PARTS), "the instruction for wider-search passages holds the rule for quoted passages")
check(all(x in T.feed_instruction([SC, HC]) for x in RULE_PARTS) and all(x in T.feed_instruction([HC]) for x in RULE_PARTS), "and so does the court-aware one")
blk_old, cases_old = feed([B_SC_OLD])
check(blk_old.startswith(T.FEED_INSTRUCTION) and "[WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: Arnesh Kumar v. State of Bihar (2014-07-02), paragraph 9]" in blk_old, "feed (no court sent): the block opens with the old instruction and the head is the old head")
check(cases_old and cases_old[0]["court"] == SC, "feed (no court sent): the case is a Supreme Court one")
blk_sc, cases_sc = feed([A_SC])
check(blk_sc == blk_old, "feed: a service that says 'Supreme Court of India' gives the very same block as one that says nothing")
blk_mx, cases_mx = feed([A_SC, C_HC])
check(blk_mx.startswith(T.feed_instruction([SC, HC])) and "Supreme Court and High Court passages" in blk_mx, "feed (mixed): the block opens with the court-aware instruction")
check("[WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: Dinathso Chaitom v. The State of AP (2020-12-17), Gauhati High Court, paragraph 4]" in blk_mx
      and "[WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: Arnesh Kumar v. State of Bihar (2014-07-02), Supreme Court of India, paragraph 9]" in blk_mx, "feed (mixed): every head names its court, the Supreme Court's too")
check({c["case_name"]: c["court"] for c in cases_mx} == {"Arnesh Kumar v. State of Bihar": SC, "Dinathso Chaitom v. The State of AP": HC}, "feed (mixed): the cases carry their court")
blk_hc, cases_hc = feed([C_HC])
check("## High Court passages" in blk_hc and "Gauhati High Court, paragraph 4]" in blk_hc, "feed (High Court only)")
ROH = res(38684, "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", "2011-09-23", SC, text="8. From the order-sheets produced before us it is clear that the petitioner was first produced before the Magistrate on March 3, 1968. Under Section 5 of the Armed Forces (Assam and Manipur) Special Powers Act, he had to be made over to the officer in-charge of the nearest police station with the least possible delay.", para="8")
blk_roh, _c = feed([ROH])
check("paragraph 8]" in blk_roh and all(x in blk_roh for x in RULE_PARTS), "feed: the passage and the rule reach the model together")
check(blk_roh.count("A passage can be a QUOTATION") == 1, "and the rule is there once")


# ---- 3b. the register is about Supreme Court decisions: a High Court judgment with a register case's name is not that case ----
RDS_SC = res(7, "Raj Deo Sharma v. The State of Bihar", "1999-05-03", SC, text="Time limit held X.")
RDS_HC = res(2000000007, "Raj Deo Sharma v. The State of Bihar", "1999-05-03", HC, "high_court_bucket_pdf", text="A High Court passage with the same name.")
fl = T._flags([RDS_SC, RDS_HC, B_SC_OLD])
check(fl[0]["source"] == "register" and fl[1] == {"source": "none", "note": None} and fl[2]["source"] in ("none", "register", "card", "card_quiet"), f"flags: the register flags the Supreme Court case of that name, never a High Court judgment that shares it ({fl[0]['source']}, {fl[1]['source']})")
blk_rds, _c = feed([A_SC, RDS_HC])
check("[Overruled Register" not in blk_rds and "A High Court passage with the same name." in blk_rds, "feed: no REGISTER FACT line under a High Court passage")
blk_rds_sc, _c = feed([A_SC, RDS_SC])
check("[Overruled Register" in blk_rds_sc, "feed: the Supreme Court case of the same name still carries its REGISTER FACT line")


# ---- 3c. a High Court title that starts with the officer's service number (staging test 2026-10-26): the name in the answer is still found, labelled once, and left out of the 'not checked' sentence ----
SOW = {"case_name": "I C 62912 F, Major Sowmithri S v. The State of Assam and Ors", "court": HC}
t_sow = "In Major Sowmithri S v. State of Assam (Gauhati High Court, 2012), the Court stated X."
lab_sow = T.label_fed_cases(t_sow, [SOW])
check(lab_sow.count(T.LABEL) == 1 and lab_sow.index(T.LABEL) > lab_sow.index("2012)"), f"a service-number title: the case is found and labelled once, after the bracket ({lab_sow!r})")
check(T.label_fed_cases(lab_sow, [SOW]) == lab_sow, "and labelling again adds nothing")
T.reset()
T._LOCAL.cases = [SOW]
names_sow = T.fed_names_in(t_sow)
check(any(n.startswith("Major Sowmithri S v. State of Assam") for n in names_sow), f"the 'not checked' sentence can leave it out ({names_sow})")
T.reset()
check(T._parties("Rohit Kumar, Singh v. State")[0].startswith("Rohit Kumar") and T._parties("Smt. Kanwar v. State of Bihar") == ("Smt. Kanwar", "State of Bihar"), "a name without a digit before its comma is left alone")

# ---- 4. the attached result, show mode ----
def attach_show(results, by_court=None):
    found = {"ok": True, "as_of": "2026-10-16", "results": results}
    if by_court is not None:
        found["as_of_by_court"] = by_court
    saved = T.search
    T.search = lambda *a, **k: found
    os.environ["SCI_SEARCH_MODE"] = "show"
    os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return T.attach("q", {"state": "single_match", "response_text": "An answer."})
    finally:
        T.search = saved


old = attach_show([B_SC_OLD])
check(old["sci_as_of"] == "2026-10-16" and "sci_as_of_by_court" not in old and old["sci_related_judgments"][0]["court"] == SC, "show: no court sent -> no per-court dates, the judgment is a Supreme Court one")
two = attach_show([A_SC, C_HC], {HC: "2026-10-14", SC: "2026-10-16"})
check(two["sci_as_of_by_court"] == {HC: "2026-10-14", SC: "2026-10-16"} and [j["court"] for j in two["sci_related_judgments"]] == [SC, HC], "show: the date of each court and the court of each judgment")
check("sci_as_of_by_court" not in attach_show([A_SC], {SC: "2026-10-16"}), "show: one court's date is not a per-court list")

# ---- 5. the notice for a High Court case called a Supreme Court one ----
loc = lambda t, n: ((t.find(n.split(" v. ")[0]), t.find(n.split(" v. ")[0]) + len(n.split(" v. ")[0])) if n.split(" v. ")[0] in t else None)
cases = [{"case_name": "Arnesh Kumar v. State of Bihar", "court": SC}, {"case_name": "Dinathso Chaitom v. The State of AP", "court": HC}]
bad = PN.court_notes("The Supreme Court in Dinathso Chaitom v. The State of AP (2020) allowed bail on conditions.", cases, loc)
check(len(bad) == 1 and bad[0].startswith("Dinathso Chaitom v. The State of AP: our index records it as a judgment of the Gauhati High Court, not of the Supreme Court") and "Check which court decided it" in bad[0], f"court_notes: a High Court case that the sentence ties to the Supreme Court is flagged ({bad})")
check(PN.court_notes("The Gauhati High Court in Dinathso Chaitom v. The State of AP (2020) allowed bail on conditions.", cases, loc) == [], "court_notes: the sentence names the High Court -> nothing")
check(PN.court_notes("The Supreme Court in Arnesh Kumar v. State of Bihar (2014) gave guidelines. Dinathso Chaitom v. The State of AP (2020) is a Gauhati High Court decision.", cases, loc) == [], "court_notes: the Supreme Court is named in another sentence, about another case -> nothing")
check(PN.court_notes("The Supreme Court in Arnesh Kumar v. State of Bihar (2014) said so.", [cases[0]], loc) == [] and PN.court_notes("", cases, loc) == [] and PN.court_notes(None, None, loc) == [], "court_notes: a Supreme Court case is never flagged; empty input is fine")
nr = PN.court_notes("The Supreme Court in Unknown Petitioner v. The State held it.", [{"case_name": "Unknown Petitioner v. The State", "court": NR}], loc)
check(len(nr) == 1 and "does not record which court decided it" in nr[0], "court_notes: a court that is not recorded is said not to be recorded")
check(PN.court_notes("x", cases, lambda t, n: (_ for _ in ()).throw(RuntimeError("boom"))) == [], "court_notes: a failure inside gives no notice, never an error")

# attach in feed mode: the notice reaches the grounding notes and a log line
found_mx = {"ok": True, "as_of": "2026-10-16", "results": [A_SC, C_HC]}
saved = T.search
T.search = lambda *a, **k: found_mx
os.environ["SCI_SEARCH_MODE"] = "feed"
os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
try:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        T.reset()
        T.feed_block("my bail question")
        G.reset_notes()
        r = T.attach("my bail question", {"state": "single_match", "response_text": "The Supreme Court in Dinathso Chaitom v. The State of AP (2020) allowed bail on conditions."})
    notes = G.pop_notes()
    check(any("Dinathso" in n and "Gauhati High Court" in n for n in notes) and "COURT_LABEL_FLAG" in out.getvalue(), f"attach (feed): the notice reaches the grounding notes and the log ({notes})")
    check(r["sci_related_judgments"][1]["court"] == HC and r["sci_fed"], "attach (feed): the page's cases carry their court")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        T.reset()
        T.feed_block("my bail question")
        G.reset_notes()
        T.attach("my bail question", {"state": "single_match", "response_text": "The Gauhati High Court in Dinathso Chaitom v. The State of AP (2020) allowed bail on conditions."})
    check(G.pop_notes() == [] and "COURT_LABEL_FLAG" not in out.getvalue(), "attach (feed): an answer that names the High Court is not flagged")
    found_mx["results"] = [A_SC]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        T.reset()
        T.feed_block("my bail question")
        G.reset_notes()
        T.attach("my bail question", {"state": "single_match", "response_text": "The Supreme Court in Arnesh Kumar v. State of Bihar (2014) said so."})
    check(G.pop_notes() == [], "attach (feed): all Supreme Court -> nothing is checked or said")
finally:
    T.search = saved
    os.environ["SCI_SEARCH_MODE"] = "off"

# ---- 6. the reading notes ----
check(PN.page_note(["lower_court"]) == PN._PAGE["lower_court"] and PN.page_note(["lower_court"], SC) == PN._PAGE["lower_court"] and "Supreme Court" in PN.page_note(["lower_court_rejected"]), "page_note: the Supreme Court's sentences are as before")
hc_note = PN.page_note(["lower_court", "submission"], HC)
check("Supreme Court" not in hc_note and "this court's own holding" in hc_note and "party's submission" in hc_note, f"page_note: a High Court passage's note does not name the Supreme Court ({hc_note!r})")
check("Supreme Court" not in PN.page_note(["lower_court_rejected"], HC) and "one judge's own opinion" in PN.page_note(["one_judge"], HC), "page_note: the rejected-lower-court and one-judge notes for a High Court")

# ---- 7. the answer view, the export, the table ----
def result_with(items, fed=True, by_court=None):
    r = {"state": "single_match", "audience": "layman", "response_text": "Short answer.", "matches": [], "sci_related_judgments": items, "sci_fed": fed, "sci_as_of": "2026-10-16"}
    if by_court:
        r["sci_as_of_by_court"] = by_court
    return r


itm = lambda r, **kw: dict({"case_name": r["case_name"], "date": r["date"], "paragraph": r["paragraph"], "link": r["link"], "link_kind": r["link_kind"], "excerpt": r["text"]}, **kw)
v_old = V.build(result_with([itm(B_SC_OLD)]))["sci_related"]
check(v_old["scope"] == "Supreme Court" and v_old["court_tags"] is False and v_old["as_of_by_court"] is None and v_old["items"][0]["court"] == SC, "view: Supreme Court passages -> scope 'Supreme Court', no tags")
v_mx = V.build(result_with([itm(A_SC, court=SC), itm(C_HC, court=HC)], by_court={HC: "2026-10-14", SC: "2026-10-16"}))["sci_related"]
check(v_mx["scope"] == "Supreme Court and High Court" and v_mx["court_tags"] is True and [i["court"] for i in v_mx["items"]] == [SC, HC] and v_mx["as_of_by_court"] == {HC: "2026-10-14", SC: "2026-10-16"}, "view: scope, court tags, the court of each item and the date of each court")

ENT = lambda view: {"question": "My bail question", "view": view, "answer_id": "RA-1", "created_at": None, "audience": "layman"}


def texts(view):
    doc = X.build_document([ENT(view)])
    return X.all_text(doc), doc


t_old, _ = texts(V.build(result_with([itm(B_SC_OLD, link_kind="open_bucket_pdf")])))
check(X.H_SCI_FED in t_old and X.OPEN_BUCKET in t_old and "High Court" not in t_old and "The collection ends 2026-10-16." in t_old, "export: Supreme Court passages -> the old heading, credit and date sentence; no court named")
t_mx, doc_mx = texts(V.build(result_with([itm(A_SC, court=SC), itm(C_HC, court=HC)], by_court={HC: "2026-10-14", SC: "2026-10-16"})))
check("Supreme Court and High Court passages from a wider search that this answer also read (not independently verified)" in t_mx and "Gauhati High Court" in t_mx and "Supreme Court of India" in t_mx, "export: the heading and each passage name the court")
check("does not bind courts outside that High Court's territory" in t_mx and "The collection ends 2026-10-16 for the Supreme Court and 2026-10-14 for the Gauhati High Court." in t_mx, "export: the High Court sentence and one date for each court")
check("High Court judgments bucket (Dattam Labs; licence terms to be confirmed)" in t_mx, "export: the High Court bucket is credited, with its licence said to be unconfirmed")
pdf, info = X.export(doc_mx, "pdf")
dx, info2 = X.export(doc_mx, "docx")
check(info["ok"] and info2["ok"], f"export: the PDF and the Word file with a High Court passage are proved complete ({info}, {info2})")

AB = lambda r, **kw: dict(itm(r, **kw), citation=None)
tab_old = AT.build([], [], [], [AB(B_SC_OLD)], lambda *a: {})
check("has_court" not in tab_old and AT.render_markdown(tab_old)[0][1].split("\n")[0] == "| Case | Citation | Paragraph | Where it stands on our lists | Link |", "authorities table: Supreme Court passages -> no Court column (the table as before)")
tab_mx = AT.build([], [], [], [AB(A_SC, court=SC), AB(C_HC, court=HC)], lambda *a: {})
md = AT.render_markdown(tab_mx)[0][1]
check(tab_mx.get("has_court") is True and md.split("\n")[0] == "| Case | Citation | Paragraph | Court | Where it stands on our lists | Link |" and "Gauhati High Court" in md and "Supreme Court of India" in md, "authorities table: a Court column when a High Court row is there")
check("licence terms to be confirmed" in md, "authorities table: the High Court bucket credit")

# ---- 8. the search page's wider search ----
FAKE_OLD = {"ok": True, "as_of": "2026-07-13", "results": [B_SC_OLD]}
FAKE_MX = {"ok": True, "as_of": "2026-10-16", "as_of_by_court": {HC: "2026-10-14", SC: "2026-10-16"}, "results": [A_SC, C_HC]}
w_old = SS.search("bail conditions", mode="wider", sci_fn=lambda t: FAKE_OLD)["wider"]
check(w_old["scope"] == "Supreme Court" and w_old["court_tags"] is False and w_old["as_of_by_court"] is None and w_old["items"][0]["court"] == SC, "search page: Supreme Court passages -> scope 'Supreme Court', no tags")
w_mx = SS.search("bail conditions", mode="wider", sci_fn=lambda t: FAKE_MX)["wider"]
check(w_mx["scope"] == "Supreme Court and High Court" and w_mx["court_tags"] is True and [i["court"] for i in w_mx["items"]] == [SC, HC] and w_mx["as_of_by_court"] == {HC: "2026-10-14", SC: "2026-10-16"}, "search page: scope, court of each item, date of each court")
w_one = SS.search("bail conditions", mode="wider", sci_fn=lambda t: {"ok": True, "as_of": "2026-10-16", "as_of_by_court": {HC: "2026-10-14", SC: "2026-10-16"}, "results": [A_SC]})["wider"]
check(w_one["scope"] == "Supreme Court" and w_one["court_tags"] is False and w_one["as_of_by_court"] == {HC: "2026-10-14", SC: "2026-10-16"}, "search page: the dates of both courts are said even when this search returned only Supreme Court passages (the index holds both)")
w_hc = SS.search("bail conditions", mode="wider", sci_fn=lambda t: {"ok": True, "as_of": "2026-10-14", "results": [C_HC]})["wider"]
check(w_hc["scope"] == "High Court" and w_hc["court_tags"] is True, "search page: High Court passages only -> scope 'High Court'")
w_none = SS.search("bail conditions", mode="wider", sci_fn=lambda t: {"ok": True, "as_of": "2026-10-14", "results": []})["wider"]
check(w_none["available"] and w_none["items"] == [] and w_none["scope"] == "Supreme Court" and w_none["court_tags"] is False, "search page: no passage -> nothing about courts")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PASSED")
