"""
test_passage_window.py -- passage_window.py and its three uses in sci_search_tier (the model's text, the page box of an answer, the "show" box), added 2026-11-09 (FOLLOW_UPS 2dz in the research repository).
Offline and free. The Papu Das passage is the first chunk of a public Gauhati High Court order (open High Court judgments bucket, Dattam Labs). Run: python -X utf8 test_passage_window.py
"""
import contextlib
import io
import json
import os
import re
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
os.environ.pop("PASSAGE_WINDOW", None)
os.environ.pop("PASSAGE_NOTES", None)
import passage_window as W
import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


PAPU = 'BEFORE HONOURABLE MRS. JUSTICE MALASRI NANDI ORDER 03.05.2024 Heard Mr. D. P. Borah, learned counsel appearing for the accused petitioners as well as Mr. D. P. Goswami, learned Additional Public Prosecutor, Assam. By this application under Section 482 Cr.P.C., the petitioner has prayed for quashing of the order dated 07.03.2024 passed by learned Special Judge, Nagaon in connection with Kampur PS Case No. 170/2023. The case of the petitioner is that the vehicle bearing No. AS 02 AN 0787 was seized in connection with Kampur PS Case No. 170/2023 along with other articles. On the date of incident, the petitioner was coming towards Hojai side and in the midst of his journey, the co-accused Mahabar Ali took lift from him and offered an amount of Rs.200/- only to drop him at Dhing Road Circle, Nagaon bypass. Accordingly, the petitioner gave lift to Mahabar Ali and dropped him there. While the petitioner after finishing his work, stopped at a dhaba namely, Ganesh Dhaba, Rangbang for refreshment, some police personnel with Mahabar Ali came there and told the petitioner that the said Mahabar Ali took lift in the vehicle of the petitioner and left a bag with full of contraband suspected heroin. Thereafter, the police searched the vehicle and suspected contraband was recovered inside the vehicle. Thereafter, the petitioner was also arrested along with other accused persons and released on bail.'
Q = "Police was looking for the prime accused in a criminal case. The prime accused was absconding. However Police arrested me since I gave a lift to the prime accused in a good intention. I never knew about his crime."
norm = lambda s: re.sub(r"[ \t]+", " ", s).strip()
bare = lambda s: re.sub(r"^\.\.\. ", "", re.sub(r" \.\.\.$", "", s))

# ---- 1. the Papu Das passage
check(len(PAPU) == 1405 and PAPU.find("took lift") == 706, "the test passage is the 1,405-character chunk with the lift sentences at character 706")
old_page = T._cut(PAPU, T.EXCERPT)
check("lift" not in old_page and old_page.startswith("BEFORE HONOURABLE"), "before: the page excerpt was the heading and stopped before the lift")
for lim in (600, 900):
    s, info = W.window(PAPU, Q, lim)
    check("gave lift" in s and "BEFORE HONOURABLE" not in s and "Heard Mr." not in s, f"window {lim}: the lift sentences, no heading")
    check(s.startswith("... ") and info == {"moved": True, "heading": True}, f"window {lim}: opens with the ellipsis; the heading was skipped and the window moved")
    check(len(s) <= lim + 8, f"window {lim}: no longer than the limit (plus the two ellipses): {len(s)}")
    check(bare(s) in norm(PAPU), f"window {lim}: the words are the passage's own, copied exactly")
s9, _ = W.window(PAPU, Q, 900)
check(s9.endswith("released on bail."), "window 900: runs to a sentence end, and the end of the passage's first paragraph (no trailing ellipsis needed there)" if False else "window 900: ends at a sentence end")
check("contraband" in s9 and "arrested" in s9, "window 900: holds the police search and the arrest, which the old 900-character cut never reached")

# ---- 2. nothing matches: the head, with the heading skipped
s, info = W.window(PAPU, "xyzzy quantum entanglement", 600)
check(s.startswith("By this application under Section 482") and info == {"moved": False, "heading": True}, "no word matches: the head after the skipped heading, with no leading ellipsis")
check(s.endswith(" ..."), "no word matches: the cut end is marked")

# ---- 3. short and plain passages are left alone
plain = "The appellant was convicted under section 302. The High Court affirmed the conviction."
check(W.window(plain, "murder conviction appeal", 600)[0] == plain, "a short passage with no heading is returned whole, no ellipsis")
long_plain = " ".join("Sentence number %d is about the sale of food." % i for i in range(60))
s, info = W.window(long_plain, "quantum entanglement", 300)
check(s == T._cut(long_plain, 300) or (s.endswith(" ...") and not s.startswith("...") and long_plain.startswith(bare(s)[:100])), "no word matches and no heading: the head, as the old cut gave it")

# ---- 4. the densest window
body = ("Introductory matter about nothing in particular. " * 12) + "The petitioner gave a lift to the absconding accused and dropped him at the bus stand without any knowledge of the crime. " + ("More talk about unrelated procedure. " * 12)
s, info = W.window(body, "I gave a lift to an absconding accused without knowledge", 400)
check("gave a lift to the absconding accused" in s and s.startswith("... ") and s.endswith(" ..."), "the window moves to the sentence that holds the question's words, with an ellipsis at both ends")
s, _ = W.window(body, "lift", 100000)
check(s == norm(body), "a limit longer than the passage returns it whole")

# ---- 5. headings and sentences
sc_head = "PETITIONER: SARJOO PRASAD Vs. RESPONDENT: THE STATE OF UTTAR PRADESH DATE OF JUDGMENT: 16/12/1960 BENCH: SHAH, J.C. CITATION: 1961 AIR 29. The appellant contended that a servant who sold food on behalf of his employer was not liable unless it was known that he had done so. The respondent denied this."
s, info = W.window(sc_head, "servant sold food employer liability", 600)
check(s.startswith("The appellant contended") and "PETITIONER" not in s and info["heading"], "an old Supreme Court header block is skipped")
sp = W._sentences("Heard Mr. D. P. Borah, learned counsel for the petitioner. By this application under Section 482 Cr.P.C., the petitioner prayed. The order of Dr. A. B. Rao was set aside. Next.")
check(len(sp) == 4, f"Mr., D. P., Cr.P.C., Dr. A. B. are not sentence ends ({len(sp)} sentences)")
only_head = "BEFORE HONOURABLE MR. JUSTICE X ORDER 03.05.2024 Heard Mr. Y."
check(W.window(only_head, "anything", 600)[0] == only_head, "a passage that is only a heading is not emptied")
check(W.window("", Q, 600) == ("", {"moved": False, "heading": False}) and W.window(None, Q, 600)[0] == "", "empty text -> empty")
one_long = "word " * 400
s, _ = W.window(one_long, "word", 300)
check(len(s) <= 308 and s.endswith(" ..."), "one very long sentence is cut at a word")

# ---- 6. the switch and the fallback
os.environ["PASSAGE_WINDOW"] = "off"
check(T._win(PAPU, T.EXCERPT, Q) == T._cut(PAPU, T.EXCERPT), "PASSAGE_WINDOW=off: the old head cut")
os.environ.pop("PASSAGE_WINDOW")
check("gave lift" in T._win(PAPU, T.EXCERPT, Q), "default: on")
real = W.window
W.window = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    check(T._win(PAPU, T.EXCERPT, Q) == T._cut(PAPU, T.EXCERPT), "a failure inside the window falls back to the old cut, no error")
finally:
    W.window = real

# ---- 7. in the feed: the model's text and the page box
def feed(results, question):
    found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": results}
    saved = T.search
    T.search = lambda *a, **k: found
    os.environ["SCI_SEARCH_MODE"] = "feed"
    os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
    buf = io.StringIO()
    try:
        T.reset()
        with contextlib.redirect_stdout(buf):
            return T.feed_block(question), list(T._LOCAL.cases), buf.getvalue()
    finally:
        T.search = saved


R = {"rank": 1, "doc": 2000754309, "case_name": "Papu Das @ Sanjoy Das v. The State of Assam", "date": "2024-05-02", "paragraph": None, "link": "https://x/papu.pdf", "link_kind": "high_court_bucket_pdf",
     "text": PAPU, "name_to_review": False, "citations": {}, "court": "Gauhati High Court", "passage_type": "argument"}
blk, cases, log = feed([R], Q)
check("gave lift" in blk and "BEFORE HONOURABLE" not in blk, "feed: the model's text holds the lift sentences and not the heading")
check(cases and "gave lift" in cases[0]["excerpt"] and "BEFORE HONOURABLE" not in cases[0]["excerpt"] and cases[0]["excerpt"].startswith("... "), "feed: the page box holds the lift sentences, no heading, an opening ellipsis")
check(len(cases[0]["excerpt"]) <= T.EXCERPT + 8, "feed: the page box is no longer than before")
check('PASSAGE_WINDOW {"passages": 1, "moved_off_the_head": 1, "heading_skipped": 1}' in log, "feed: one PASSAGE_WINDOW log line")
os.environ["PASSAGE_WINDOW"] = "off"
blk_off, cases_off, log_off = feed([R], Q)
check("BEFORE HONOURABLE" in blk_off and cases_off[0]["excerpt"].startswith("BEFORE HONOURABLE") and "PASSAGE_WINDOW" not in log_off, "feed with the switch off: the old head, no log line")
os.environ.pop("PASSAGE_WINDOW")

# the voice note: a party's-submission cue that sits in the head still counts once the window has moved on
os.environ["PASSAGE_NOTES"] = "on"
SUB = ("BEFORE HON'BLE MR. JUSTICE X ORDER 03.05.2024 Heard counsel. Learned counsel for the petitioner submitted that the order of the Special Judge is bad in law and must be set aside. "
       + ("Some unrelated procedural matter is recorded here. " * 25) + "The petitioner gave a lift to the absconding accused and dropped him at the bus stand without any knowledge of the crime. " + ("More unrelated procedural matter follows. " * 10))
R3 = dict(R, passage_type=None, text=SUB)
os.environ["PASSAGE_WINDOW"] = "off"
_b, c_off, _l = feed([R3], Q)
os.environ.pop("PASSAGE_WINDOW")
blk3, c_on, _l = feed([R3], Q)
check("gave a lift" in blk3 and "Learned counsel for the petitioner submitted" not in blk3, "PASSAGE_NOTES: the window moved to the lift sentence, past the counsel's submission")
check(c_off[0].get("passage_kinds") == ["submission"] and c_on[0].get("passage_kinds") == ["submission"] and "Note by code" in blk3, f"PASSAGE_NOTES: the submission note is kept although the window left the head ({c_on[0].get('passage_kinds')})")
os.environ.pop("PASSAGE_NOTES")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("ALL PASSED")
