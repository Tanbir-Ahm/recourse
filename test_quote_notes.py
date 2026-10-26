"""
test_quote_notes.py -- a wider-search passage whose number is not the judgment's own (quote_notes.py; FOLLOW_UPS 2cm).

The search service (SCI_QUOTES=on) sends {"quote": {"within": "25", "kind": "introduced"|"off_sequence", "intro": ...}} for a passage found inside paragraph 25 under another number ("8"). This file checks every place that words it:
the prompt (head of the passage, the Note by code, the instruction), the cases the engine returns (paragraph, reading note), the notice when the answer credits the court with the passage, the sources box (answer view), the
PDF/Word export, the authorities table and the search page -- and, as the main point, that a result WITHOUT a quote (a service that does not send one, SCI_QUOTES unset) is worded byte for byte as before.
Fully offline and free: a function stands in for the service. Run: python -X utf8 test_quote_notes.py
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
import quote_notes as QN
import sci_search_tier as T
import search_service as SS

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


SC = "Supreme Court of India"
INTRO = "In Saptawna vs. The State of Assam AIR (1971) SC 813, this Court has observed as under in paras 2 and 3 of the reported decision :"
Q_INTRO = {"within": "25", "kind": "introduced", "intro": INTRO, "block": 4}
Q_OFF = {"within": "21", "kind": "off_sequence", "block": 1}


def res(doc, name, date, text, para, quote=None):
    r = {"rank": doc, "doc": doc, "case_name": name, "date": date, "paragraph": para, "link": f"https://x.example/{doc}.pdf", "link_kind": "court_archive_pdf", "text": text, "name_to_review": False, "citations": {}, "court": SC}
    if quote is not None:
        r["quote"] = quote
    return r


SADHWI_TEXT = "8. From the order-sheets produced before us it is clear that the petitioner was first produced before the Magistrate on March 3, 1968. That was roughly two months after his arrest by the Armed Forces."
SADHWI = res(38684, "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", "2011-04-12", SADHWI_TEXT, "8", Q_INTRO)
SADHWI_PLAIN = res(38684, "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", "2011-04-12", SADHWI_TEXT, "8")           # the same passage from a service that sends no quote
ARNESH = res(41736, "Arnesh Kumar v. State of Bihar", "2014-07-02", "Arrest is not to be made routinely.", "9")

# ---- 1. quote_notes: the record
check(QN.clean(Q_INTRO) == {"within": "25", "kind": "introduced", "intro": INTRO}, "clean: a well-formed record is kept (block is not needed)")
check(QN.clean(Q_OFF) == {"within": "21", "kind": "off_sequence"}, "clean: off_sequence has no intro")
check(QN.clean({"within": "25", "kind": "off_sequence", "intro": "words"}) == {"within": "25", "kind": "off_sequence"}, "clean: an intro on an off_sequence record is dropped")
bad = [None, "x", [], {}, {"within": "25"}, {"kind": "introduced"}, {"within": "twenty", "kind": "introduced"}, {"within": "25", "kind": "quotation"}, {"within": "", "kind": "introduced"}, {"within": "25; DROP", "kind": "introduced"}, {"within": 99999, "kind": "off_sequence"}]
check(all(QN.clean(b) is None for b in bad), "clean: every malformed record is ignored (the passage is worded as before)")
check(QN.clean({"within": 25, "kind": "off_sequence"}) == {"within": "25", "kind": "off_sequence"}, "clean: a number is accepted as a string")
long = QN.clean({"within": "25", "kind": "introduced", "intro": "word " * 300})
check(len(long["intro"]) <= QN.MAX_INTRO, "clean: a long intro is cut")
check(QN.clean({"within": "25", "kind": "off_sequence", "ends_at": "24"})["ends_at"] == "24" and "ends_at" not in QN.clean({"within": "25", "kind": "off_sequence", "ends_at": "x"}), "clean: ends_at must be a number")
check(QN.own_number("8. From the order-sheets") == "8" and QN.own_number("  830. Only the spirit") == "830" and QN.own_number("The court said") is None and QN.own_number("") is None and QN.own_number(None) is None, "own_number")

# ---- 2. the words
head = QN.head_phrase(QN.clean(Q_INTRO))
check(head == ", inside paragraph 25", f"head_phrase ({head!r})")
note = QN.prompt_note(QN.clean(Q_INTRO), SADHWI_TEXT)
check(note.startswith("\n[Note by code -- read before using this passage: ") and note.endswith("]"), "prompt_note: a Note by code line")
check('(it starts with "8.")' in note and "NOT a paragraph number of this judgment" in note and "inside paragraph 25" in note, "prompt_note: it names the number the passage starts with and the paragraph it sits inside")
check(INTRO in note, "prompt_note: the judgment's own introducing words are given word for word")
check("do not say that the listed court held, decided, recorded or observed it" in note and "build no ground" in note and 'never give the number it starts with as a paragraph' in note, "prompt_note: no credit to the listed court, no ground, no number")
check("not this court's own words" in note.lower() or "NOT this court's own words" in note, "prompt_note: it says the words are not this court's own if they introduce a quotation")
off = QN.prompt_note(QN.clean(Q_OFF), "4. It may be mentioned that this judgment was delivered")
check("wrapped citation" in off and "numbered list" in off and "check from the passage itself" in off and "inside paragraph 21" in off and "do not credit it to the court" in off, "prompt_note: off_sequence says what it can be, and does not tell the model the words are a quotation")
check("do not say that the listed court held" not in off, "prompt_note: off_sequence does not forbid crediting the court outright (the words can be its own list)")
noi = QN.prompt_note(QN.clean({"within": "7", "kind": "introduced"}), "3. text")
check("introduce a quotation or a list" in noi and "inside paragraph 7" in noi, "prompt_note: introduced without words")
check("last part is the judgment's own paragraph 24" in QN.prompt_note(QN.clean({"within": "23", "kind": "off_sequence", "ends_at": "24"}), "8. x"), "prompt_note: a joined passage says where its own part is")
pg = QN.page_note(QN.clean(Q_INTRO))
check("inside paragraph 25" in pg and "is not a paragraph of that judgment" in pg and "Saptawna" in pg and "not this court's own holding" in pg, f"page_note (introduced): plain words, the introduction, no overclaim ({pg!r})")
check("Saptawna" not in QN.page_note(QN.clean(Q_OFF)) and "wrapped citation" in QN.page_note(QN.clean(Q_OFF)), "page_note (off_sequence)")
check(QN.page_note(QN.clean({"within": "25", "kind": "introduced", "intro": "w" * 360})).count("...") == 1, "page_note: a long introduction is shortened on the page")
check("{" not in pg and "None" not in pg, "page_note: nothing left over from the code")


# ---- 3. the feed
def feed(results, question="unlawful detention without being produced before a magistrate", pn="off"):
    found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": results}
    saved, saved_mode, saved_pn = T.search, os.environ.get("SCI_SEARCH_MODE"), os.environ.get("PASSAGE_NOTES")
    T.search = lambda *a, **k: found
    os.environ["SCI_SEARCH_MODE"] = "feed"
    os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
    os.environ["PASSAGE_NOTES"] = pn
    try:
        T.reset()
        with contextlib.redirect_stdout(io.StringIO()):
            return T.feed_block(question), list(T._LOCAL.cases)
    finally:
        T.search = saved
        for k, v in (("SCI_SEARCH_MODE", saved_mode), ("PASSAGE_NOTES", saved_pn)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


blk, cases = feed([SADHWI, ARNESH])
check("Sadhwi Pragyna Singh Thakur v. State of Maharashtra (2011-04-12), inside paragraph 25]" in blk, "feed: the head names the paragraph the passage sits inside")
check("paragraph 8]" not in blk and ", paragraph 8" not in blk, "feed: the head no longer says 'paragraph 8'")
check("Arnesh Kumar v. State of Bihar (2014-07-02), paragraph 9]" in blk, "feed: another passage in the same prompt keeps its own number")
check("[Note by code -- read before using this passage: the number (it starts with \"8.\") is NOT a paragraph number of this judgment" in blk and INTRO in blk, "feed: the Note by code with the introducing words sits under the passage")
check(blk.index(SADHWI_TEXT) < blk.index("[Note by code -- read before using this passage: the number") < blk.index("Arnesh Kumar"), "feed: the note is under the Sadhwi passage and before the next one")
check(T.QUOTE_INSTRUCTION in blk and blk.count("NOT a paragraph number of its judgment") == 1, "feed: the one-sentence instruction is in the prompt when a quoted passage is")
check(blk.count("Note by code -- read before using this passage") == 1, "feed: no note under the passage that has no quote")
c0 = cases[0]
check(c0["paragraph"] == "25" and "inside paragraph 25" in c0["passage_note"] and "Saptawna" in c0["passage_note"], f"cases: the page shows paragraph 25 and the reading note ({c0['paragraph']!r})")
check("quoted" in c0["passage_kinds"] and cases[1]["passage_kinds"] == [] and cases[1]["paragraph"] == "9" and cases[1]["passage_note"] is None, "cases: only the quoted passage carries the kind and the note")

blk_p, cases_p = feed([SADHWI_PLAIN, ARNESH])
check("Sadhwi Pragyna Singh Thakur v. State of Maharashtra (2011-04-12), paragraph 8]" in blk_p and "NOT a paragraph number" not in blk_p and T.QUOTE_INSTRUCTION not in blk_p and cases_p[0]["paragraph"] == "8" and cases_p[0]["passage_note"] is None
      and cases_p[0]["passage_kinds"] == [], "feed: a result with no quote is worded as before")
for badq in ("x", {"within": "abc", "kind": "introduced"}, {"within": "25", "kind": "quotation"}, [], {}):
    b, c = feed([dict(SADHWI_PLAIN, quote=badq), ARNESH])
    check(b == blk_p and c[0]["paragraph"] == "8", f"feed: a malformed quote ({str(badq)[:40]}) changes nothing")
b_old, _c = feed([SADHWI_PLAIN, ARNESH], pn="off")
check(b_old == blk_p, "feed: byte for byte the same as the result without a quote")

blk_pn, cases_pn = feed([SADHWI, ARNESH], pn="on")
check(PN.INSTRUCTION in blk_pn and T.QUOTE_INSTRUCTION in blk_pn and "inside paragraph 25" in blk_pn, "feed (PASSAGE_NOTES=on): both instructions, and the quote note")
check("quoted" in cases_pn[0]["passage_kinds"], "feed (PASSAGE_NOTES=on): the kind is there")

blk_o, cases_o = feed([res(38684, "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", "2011-04-12", "4. It may be mentioned that this judgment was delivered by a Three Judge Bench of this Court.", "4", Q_OFF)])
check(", inside paragraph 21]" in blk_o and "wrapped citation" in blk_o and cases_o[0]["paragraph"] == "21", "feed: an off_sequence passage is worded without a claim that it is a quotation")

# ---- 4. the passage_notes machinery
check("quoted" in PN.KINDS and PN.page_note(["quoted"]) and "Supreme Court" in PN.page_note(["quoted"]) and "Supreme Court" not in PN.page_note(["quoted"], "Gauhati High Court"), "passage_notes: the kind 'quoted' has page sentences, and the High Court one does not name the Supreme Court")
check(PN.prompt_note(["quoted"]) == "", "passage_notes: the kind adds nothing to the prompt by itself (quote_notes words the prompt)")
check(PN.overstated("The Supreme Court held that the petitioner must be produced within twenty-four hours.", ["quoted"]), "overstated: 'the Supreme Court held' about a quoted passage")
check(not PN.overstated("The judgment quotes an older decision, which held that the petitioner must be produced within twenty-four hours.", ["quoted"]), "overstated: the answer already says it is quoted -> nothing")


def attach(answer, results=None, pn="on", mode="feed"):
    found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": results or [SADHWI]}
    saved, saved_env = T.search, {k: os.environ.get(k) for k in ("SCI_SEARCH_MODE", "PASSAGE_NOTES")}
    T.search = lambda *a, **k: found
    os.environ["SCI_SEARCH_MODE"], os.environ["SCI_SEARCH_URL"], os.environ["PASSAGE_NOTES"] = mode, "http://127.0.0.1:9", pn
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            T.reset()
            T.feed_block("unlawful detention without being produced before a magistrate")
            G.reset_notes()
            r = T.attach("unlawful detention without being produced before a magistrate", {"state": "single_match", "response_text": answer})
        return r, G.pop_notes(), out.getvalue()
    finally:
        T.search = saved
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


r1, n1, log1 = attach("The Supreme Court in Sadhwi Pragyna Singh Thakur v. State of Maharashtra (2011) held that the petitioner must be produced before a magistrate.")
check(len(n1) == 1 and n1[0].startswith("Sadhwi Pragyna Singh Thakur v. State of Maharashtra: the passage we read is not the Court's own holding.") and "quoted from another decision or document" in n1[0], f"attach (PASSAGE_NOTES=on): the answer credits the Court with a quoted passage -> a notice ({n1})")
r2, n2, _l = attach("Sadhwi Pragyna Singh Thakur v. State of Maharashtra (2011) quotes an older decision, which held that the petitioner must be produced before a magistrate.")
check(n2 == [], "attach (PASSAGE_NOTES=on): the answer says it is a quotation -> no notice")
r3, n3, _l = attach("The Supreme Court in Sadhwi Pragyna Singh Thakur v. State of Maharashtra (2011) held that the petitioner must be produced.", pn="off")
check(n3 == [], "attach (PASSAGE_NOTES=off): no notice (that switch is the owner's), the page note and the prompt note are still there")
check(r3["sci_related_judgments"][0]["paragraph"] == "25" and "inside paragraph 25" in r3["sci_related_judgments"][0]["passage_note"], "attach: the case the page lists carries paragraph 25 and the note")

# ---- 5. the answer view, the export, the table
def result_with(items):
    return {"state": "single_match", "audience": "layman", "response_text": "Short answer.", "matches": [], "sci_related_judgments": items, "sci_fed": True, "sci_as_of": "2026-10-16"}


view = V.build(result_with(cases))
it0 = view["sci_related"]["items"][0]
check(it0["paragraph"] == "25" and "inside paragraph 25" in it0["passage_note"], "view: the sources box gets paragraph 25 and the note")
ENT = {"question": "My question", "view": view, "answer_id": "RA-1", "created_at": None, "audience": "layman"}
doc = X.build_document([ENT])
txt = X.all_text(doc)
check("paragraph 25" in txt and "paragraph 8" not in txt and "inside paragraph 25 of the judgment" in txt, "export: the document says paragraph 25 and carries the note")
pdf, info = X.export(doc, "pdf")
dx, info2 = X.export(doc, "docx")
check(info["ok"] and info2["ok"], f"export: the PDF and the Word file are proved complete ({info}, {info2})")
tab = AT.build([], [], [], [dict(c, citation=None) for c in cases], lambda *a: {})
md = AT.render_markdown(tab)[0][1]
check("| 25 |" in md and "| 8 |" not in md and "Reading note:" in md and "inside paragraph 25" in md, "authorities table: paragraph 25 and the reading note")

# ---- 6. the search page
w = SS.search("detention magistrate", mode="wider", sci_fn=lambda t: {"ok": True, "as_of": "2026-10-16", "results": [SADHWI, ARNESH]})["wider"]
i0, i1 = w["items"][0], w["items"][1]
check(i0["paragraph"] == "25" and "inside paragraph 25" in i0["passage_note"] and "passage_note" not in i1 and i1["paragraph"] == "9", "search page: the paragraph the passage sits inside and the note; the other item is as before")
w2 = SS.search("detention magistrate", mode="wider", sci_fn=lambda t: {"ok": True, "as_of": "2026-10-16", "results": [SADHWI_PLAIN, ARNESH]})["wider"]
check(w2["items"][0]["paragraph"] == "8" and "passage_note" not in w2["items"][0], "search page: no quote -> as before")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PASSED")
