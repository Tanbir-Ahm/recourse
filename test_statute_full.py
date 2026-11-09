"""
test_statute_full.py -- a library statute section the answer rests on is shown WHOLE under the answer (2026-11-09; staging, the molestation-recording question: the box for BNS 77 stopped inside Explanation 1 ("where the victi"),
and the box for BNSS 35 showed a wrapped first line of the source and then sub-section (3), so sub-section (1)(b), the text the arrest argument rests on, was not on the page).

Proves, on the library's real text of BNS 77, BNSS 35, 187 and 480: the box holds the section's whole cleaned text; a section over LIBRARY_FULL_CHARS still gets the cut, whose opening is now whole words (not one wrapped line of the source);
the Act shelf is unchanged (whole up to 16,000).
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import answer_view as AV

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def lib(file_part, num):
    for f in glob.glob(os.path.join(HERE, "chunks", f"*{file_part}*_chunks.json")):
        d = json.load(open(f, encoding="utf-8"))
        for r in (d if isinstance(d, list) else d.get("chunks", [])):
            if isinstance(r, dict) and str(r.get("section_number")) == str(num):
                return r
    return None


bns77 = lib("bharatiya_nyaya_sanhita", "77")
bnss35 = lib("bharatiya_nagarik_suraksha", "35")
bnss187 = lib("bharatiya_nagarik_suraksha", "187")
bnss480 = lib("bharatiya_nagarik_suraksha", "480")
check(all([bns77, bnss35, bnss187, bnss480]), "the four real sections are in the library data")


def m(rec, act):
    return {"type": "statute", "act": act, "section_number": rec["section_number"], "text": rec["text"]}


for rec, act, name in ((bns77, "BNS", "BNS 77"), (bnss35, "BNSS", "BNSS 35"), (bnss187, "BNSS", "BNSS 187"), (bnss480, "BNSS", "BNSS 480")):
    whole = AV.clean_excerpt(rec["text"])
    for reply, q in (("", ""), ("Section %s of the Act applies; sub-section (3) too." % rec["section_number"], "my client was arrested on the charges that he was recording a sexual molestation case")):
        got = AV.statute_excerpt(m(rec, act), reply, q)
        check(got == whole and len(whole) > 900 or len(whole) <= 900 and got == whole, f"{name}: the box holds the whole cleaned section ({len(got)} of {len(whole)} characters; reply {'given' if reply else 'none'})")
check("(1)" in AV.statute_excerpt(m(bnss35, "BNSS"), "Section 35(1)(b) and 35(3) of the BNSS", "arrested") and "reasonable suspicion" in AV.statute_excerpt(m(bnss35, "BNSS"), "Section 35(1)(b) and 35(3) of the BNSS", "arrested"),
      "BNSS 35: sub-section (1) is on the page together with (3)")
t77 = AV.statute_excerpt(m(bns77, "BNS"), "", "")
check("Explanation 1" in t77 and "Explanation 2" in t77 and not t77.rstrip().endswith("victi"), "BNS 77: both Explanations are on the page")

# a section over the limit: the cut remains, with an opening of whole words
long_text = "99. Whoever, intentionally\nor knowingly does a thing described\nin this section, shall be punished with imprisonment. " + ("The court may consider the matter further. " * 260)
mm = {"type": "statute", "act": "BNS", "section_number": "99", "text": long_text}
check(len(AV.clean_excerpt(long_text)) > AV.LIBRARY_FULL_CHARS, "the long test section is over the limit")
check(len(AV.statute_excerpt(mm, "", "")) == AV.LIBRARY_FULL_CHARS, "a section over the limit is cut at the limit")
long_sub = "99. Whoever, intentionally\nor knowingly does a thing described\nin this section, shall be punished.\n" + ("The court may consider the matter further. " * 220) + "\n(7) The seventh sub-section stands last and holds the point."
ms = {"type": "statute", "act": "BNS", "section_number": "99", "text": long_sub}
out = AV.statute_excerpt(ms, "Section 99(7) of the BNS decides it.", "x")
check("\n\n[...]\n\n" in out and "(7) The seventh sub-section" in out and len(out.split(" ...\n\n[...]")[0]) > 200 and not out.startswith("99. Whoever, intentionally\nor knowingly does a thing described\nin this section ..."),
      f"a cited sub-section beyond the limit: an opening of whole words, a gap, the sub-section ({out[:120]!r})")
check(AV._opening("abcdef " * 100).endswith("abcdef") and len(AV._opening("abcdef " * 100)) <= 300 and AV._opening("short text") == "short text", "the opening is at most 300 characters and ends at a word")

# the shelf is unchanged
shelf = {"type": "statute", "act": "PCA", "section_number": "17", "text": "x " * 3000, "shelf": {"loaded_on": "2026-11-01"}}
check(len(AV.statute_excerpt(shelf, "", "")) == len(AV.clean_excerpt(shelf["text"])), "an Act-shelf section is shown whole as before")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
