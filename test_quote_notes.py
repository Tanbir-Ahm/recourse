"""
test_quote_notes.py -- a wider-search passage whose number is not the judgment's own (quote_notes.py; FOLLOW_UPS 2cm and 2cn).

The search service (SCI_QUOTES=on) sends {"quote": {"within": "25", "kind": "introduced"|"off_sequence", "intro": ...}} for a passage found inside paragraph 25 under another number ("8"). What Recourse does with it:
  * feed_block leaves such a passage OUT of what the answer model reads (another passage of the same case may take its place) and logs SCI_FEED_QUOTED;
  * the prompt rule says never to mention a quotation (the first version told the model to say so, and the owner's circumstantial-evidence answer carried sentences about "a passage inside paragraph 19 of Hongro Ngotan ...");
  * drop_provenance_sentences removes, from a finished answer, a sentence that names a wider-search case AND talks about where a passage sits or what it may quote;
  * the search page (no model) shows the paragraph the passage sits inside and a reading note.
A result WITHOUT a quote, and an answer without such sentences, are worded byte for byte as before. Offline and free. Run: python -X utf8 test_quote_notes.py
"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

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
SADHWI_OWN = res(38684, "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", "2011-04-12", "26. The decisions relied upon by the learned counsel for the appellant do not support the plea.", "26")
SADHWI_PLAIN = res(38684, "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", "2011-04-12", SADHWI_TEXT, "8")
ARNESH = res(41736, "Arnesh Kumar v. State of Bihar", "2014-07-02", "Arrest is not to be made routinely.", "9")

# ---- 1. the record
check(QN.clean(Q_INTRO) == {"within": "25", "kind": "introduced", "intro": INTRO}, "clean: a well-formed record is kept")
check(QN.clean(Q_OFF) == {"within": "21", "kind": "off_sequence"}, "clean: off_sequence has no intro")
check(QN.clean({"within": "25", "kind": "off_sequence", "intro": "words"}) == {"within": "25", "kind": "off_sequence"}, "clean: an intro on an off_sequence record is dropped")
bad = [None, "x", [], {}, {"within": "25"}, {"kind": "introduced"}, {"within": "twenty", "kind": "introduced"}, {"within": "25", "kind": "quotation"}, {"within": "", "kind": "introduced"}, {"within": "25; DROP", "kind": "introduced"}, {"within": 99999, "kind": "off_sequence"}]
check(all(QN.clean(b) is None for b in bad), "clean: every malformed record is ignored")
check(QN.clean({"within": 25, "kind": "off_sequence"}) == {"within": "25", "kind": "off_sequence"}, "clean: a number is accepted as a string")
check(len(QN.clean({"within": "25", "kind": "introduced", "intro": "word " * 300})["intro"]) <= QN.MAX_INTRO, "clean: a long intro is cut")
check(QN.clean({"within": "25", "kind": "off_sequence", "ends_at": "24"})["ends_at"] == "24" and "ends_at" not in QN.clean({"within": "25", "kind": "off_sequence", "ends_at": "x"}), "clean: ends_at must be a number")
pg = QN.page_note(QN.clean(Q_INTRO))
check("inside paragraph 25" in pg and "is not a paragraph of that judgment" in pg and "Saptawna" in pg and "not this court's own holding" in pg, f"page_note (introduced) ({pg!r})")
check("Saptawna" not in QN.page_note(QN.clean(Q_OFF)) and "wrapped citation" in QN.page_note(QN.clean(Q_OFF)), "page_note (off_sequence)")
check(QN.page_note(QN.clean({"within": "25", "kind": "introduced", "intro": "w" * 360})).count("...") == 1, "page_note: a long introduction is shortened")


# ---- 2. the feed
def feed(results, question="unlawful detention without being produced before a magistrate", pn="off"):
    found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": results}
    saved, saved_mode, saved_pn = T.search, os.environ.get("SCI_SEARCH_MODE"), os.environ.get("PASSAGE_NOTES")
    T.search = lambda *a, **k: found
    os.environ["SCI_SEARCH_MODE"] = "feed"
    os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
    os.environ["PASSAGE_NOTES"] = pn
    out = io.StringIO()
    try:
        T.reset()
        with contextlib.redirect_stdout(out):
            block = T.feed_block(question)
        return block, list(T._LOCAL.cases), out.getvalue()
    finally:
        T.search = saved
        for k, v in (("SCI_SEARCH_MODE", saved_mode), ("PASSAGE_NOTES", saved_pn)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


blk, cases, log = feed([SADHWI, ARNESH])
check("Sadhwi" not in blk and SADHWI_TEXT[:40] not in blk and "Saptawna" not in blk, "feed: a passage whose number is not the judgment's own is not in what the model reads")
check("Arnesh Kumar v. State of Bihar (2014-07-02), paragraph 9]" in blk and [c["case_name"] for c in cases] == ["Arnesh Kumar v. State of Bihar"], "feed: the other passage is unchanged")
check('SCI_FEED_QUOTED {"left_out": [{"case": "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", "para": "8", "within": "25"}]}' in log, f"feed: one log line says what was left out ({log.strip()[:200]})")
check("Note by code" not in blk and "inside paragraph" not in blk, "feed: no note about where a passage sits is given to the model")
blk2, cases2, _l = feed([SADHWI, SADHWI_OWN, ARNESH])
check([c["case_name"] for c in cases2] == ["Sadhwi Pragyna Singh Thakur v. State of Maharashtra", "Arnesh Kumar v. State of Bihar"] and "paragraph 26]" in blk2 and "order-sheets" not in blk2, "feed: another passage of the same case, whose number is its own, takes the place")
blk3, cases3, _l = feed([SADHWI, dict(SADHWI_PLAIN, quote=Q_OFF)])
check(cases3 == [] and blk3 == "", "feed: when every passage is flagged the feed is empty, as when nothing came back (introduced and off_sequence alike)")
blk_p, cases_p, log_p = feed([SADHWI_PLAIN, ARNESH])
check("Sadhwi Pragyna Singh Thakur v. State of Maharashtra (2011-04-12), paragraph 8]" in blk_p and len(cases_p) == 2 and "SCI_FEED_QUOTED" not in log_p, "feed: a result with no quote is worded and fed as before")
for badq in ("x", {"within": "abc", "kind": "introduced"}, {"within": "25", "kind": "quotation"}, [], {}):
    b, c, _l = feed([dict(SADHWI_PLAIN, quote=badq), ARNESH])
    check(b == blk_p and len(c) == 2, f"feed: a malformed quote ({str(badq)[:40]}) changes nothing")

# ---- 3. the prompt rule
RULE = ("do not mention it in your answer, and do not mention that it is a quotation", "never write a sentence about where it sits, which earlier decision it may reproduce, or that it needs checking",
        "leave it out as if you had not seen it", "never give its paragraph number")
check(all(x in T.FEED_INSTRUCTION for x in RULE) and "if you mention it at all, say that it is a passage" not in T.FEED_INSTRUCTION, "the rule for quotations in the instruction: never mention it (the old 'say that it is quoted' is gone)")
check(all(x in T.feed_instruction([SC]) for x in RULE) and all(x in blk_p for x in RULE[:2]), "the court-aware instruction and the prompt carry it too")

# ---- 4. the finished answer: no talk about where a passage sits or what it quotes
NAMES = ["Pawan Kumar Sharma v. Manoj Kumar & Ors", "Herman Tirky @ Herman Orang v. The State of Assam", "Hongro Ngotan v. The State of AP", "Majendran Langeswaran v. State (NCT of Delhi) & Anr", "Suresh Majhi v. The State of AP", "Mehtab v. State of Uttarakhand"]
loc = lambda t, n: T._locate(t, n, [])
ANS = ("4. The chain must exclude hypotheses of innocence\n\n"
       "The Gauhati High Court in Herman Tirky @ Herman Orang v. The State of Assam (2013) said the evidence must be inconsistent with every hypothesis of innocence before conviction can rest on it. "
       "A passage inside paragraph 19 of Hongro Ngotan v. The State of AP (2024) appears to reproduce an earlier decision's reasoning (G. Parshwanath v. State of Karnataka) rather than the Gauhati High Court's own words, "
       "and should not be treated as that court's holding; the same caution applies to a similarly placed passage inside paragraph 18 of Majendran Langeswaran v. State (NCT of Delhi) & Anr (2013).\n\n"
       "5. Procedure\n\nSection 249 of the BNSS requires the prosecutor to open the case.\n\n"
       "Gaps and checks\n\nThe dates shown for Pawan Kumar Sharma and Mehtab (2026) could not be checked. "
       "The passages inside Hongro Ngotan and Majendran Langeswaran appear to quote an unnamed earlier decision (possibly G. Parshwanath v. State of Karnataka) and that original should be checked before relying on its wording. "
       "The passage in Suresh Majhi v. The State of AP also appears partly quoted and should similarly be verified against its source before use.")
new, n = QN.drop_provenance_sentences(ANS, NAMES, loc)
check(n == 4, f"drop: the three sentences of the owner's answer are found (four stretches: a semicolon splits the first one in two) ({n})")
check("Hongro" not in new and "Majendran" not in new and "Suresh Majhi" not in new and "Parshwanath" not in new and "inside paragraph" not in new and "partly quoted" not in new, "drop: nothing about where a passage sits or what it quotes is left")
check("Herman Tirky @ Herman Orang v. The State of Assam (2013) said the evidence must be inconsistent with every hypothesis of innocence before conviction can rest on it." in new
      and "Section 249 of the BNSS requires the prosecutor to open the case." in new and "The dates shown for Pawan Kumar Sharma and Mehtab (2026) could not be checked." in new, "drop: the sentences around them stay, word for word")
check(new.count("\n\n") == ANS.count("\n\n") and "4. The chain must exclude hypotheses of innocence\n\n" in new and "Gaps and checks\n\n" in new, "drop: headings and paragraph breaks stay")
same = "The Supreme Court in Mehtab v. State of Uttarakhand (2026) stated that the prosecution must prove each circumstance beyond reasonable doubt. Pawan Kumar Sharma v. Manoj Kumar & Ors quoted the five principles with approval."
check(QN.drop_provenance_sentences(same, NAMES, loc) == (same, 0), "drop: an ordinary sentence, even one that says a case 'quoted' something, stays")
no_name = "Some passages appear to quote an earlier decision and should be checked."
check(QN.drop_provenance_sentences(no_name, NAMES, loc) == (no_name, 0), "drop: the same words with no wider-search case named in the sentence stay")
check(QN.drop_provenance_sentences("", NAMES, loc) == ("", 0) and QN.drop_provenance_sentences(ANS, [], loc) == (ANS, 0) and QN.drop_provenance_sentences(None, NAMES, loc) == ("", 0), "drop: empty input is safe")
check(QN.drop_provenance_sentences(ANS, NAMES, lambda t, n: (_ for _ in ()).throw(RuntimeError("x"))) == (ANS, 0), "drop: a failure inside leaves the text as it was")
labelled = ANS.replace("Hongro Ngotan v. The State of AP (2024)", "Hongro Ngotan v. The State of AP (2024) (from a wider search, not independently verified)")
nl, nn = QN.drop_provenance_sentences(labelled, NAMES, loc)
check(nn == 4 and "Hongro" not in nl, "drop: works on an answer that already carries the wider-search labels")

# ---- 5. attach: the backstop runs before the labels
ANS2 = ("The Gauhati High Court in Herman Tirky @ Herman Orang v. The State of Assam (2013) said the evidence must be inconsistent with every hypothesis of innocence. "
        "A passage inside paragraph 19 of Hongro Ngotan v. The State of AP (2024) appears to reproduce an earlier decision's reasoning and should not be treated as that court's holding.")
HERMAN = res(1, "Herman Tirky @ Herman Orang v. The State of Assam", "2013-05-01", "The evidence must be inconsistent with every hypothesis of innocence.", "12")
HONGRO = res(2, "Hongro Ngotan v. The State of AP", "2024-05-01", "The circumstances must form a complete chain.", "19")
saved, saved_env = T.search, {k: os.environ.get(k) for k in ("SCI_SEARCH_MODE", "PASSAGE_NOTES")}
T.search = lambda *a, **k: {"ok": True, "as_of": "2026-10-16", "results": [HERMAN, HONGRO]}
os.environ["SCI_SEARCH_MODE"], os.environ["SCI_SEARCH_URL"] = "feed", "http://127.0.0.1:9"
try:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        T.reset()
        T.feed_block("circumstantial evidence")
        r = T.attach("circumstantial evidence", {"state": "single_match", "response_text": ANS2})
finally:
    T.search = saved
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
check("Hongro" not in r["response_text"] and "inside paragraph" not in r["response_text"], "attach: the sentence about where a passage sits is gone from the finished answer")
check(r["response_text"].startswith("The Gauhati High Court in Herman Tirky @ Herman Orang v. The State of Assam (2013) (from a wider search, not independently verified) said the evidence"), "attach: the remaining case still gets its label")
check('QUOTE_TALK_DROPPED {"sentences": 1}' in out.getvalue(), "attach: one log line counts the sentences removed (no text)")

# ---- 6. the search page (no model)
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
