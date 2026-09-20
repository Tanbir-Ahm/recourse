"""
test_case_cleaning.py -- legibility cleaning of retrieved judgments (case_lookup.clean_judgment_text and
its use in assemble_case / the cache / the disclaimer). Written BEFORE the code.

The rule these tests enforce: remove ONLY scan debris (text repeated across overlapping pieces, page-margin
letters A-H that landed inside sentences, paragraph breaks that split a sentence). NEVER change the
judgment's own words -- 'accused A', 'Schedule C', 'Article 21 A' must survive.
Run: python -X utf8 test_case_cleaning.py
"""
import os
import sys
import tempfile

import case_document
import case_lookup

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def clean(*chunks):
    return case_lookup.clean_judgment_text(list(chunks))


def paras(t):
    return [p for p in t.split("\n\n") if p.strip()]


check(hasattr(case_lookup, "clean_judgment_text"), "case_lookup exposes clean_judgment_text()")

# ------------------------------------------------------------------ 1. repeated text across overlapping pieces
p1 = "Paragraph one is a long enough paragraph of ordinary judgment text about arrest."
p2 = "Paragraph two carries on with the reasoning of the Court about default bail rights."
p3 = "Paragraph three concludes the reasoning and states the operative direction clearly."
out = clean(p1 + "\n\n" + p2, p2 + "\n\n" + p3)
check(paras(out) == [p1, p2, p3], f"a whole paragraph repeated at the seam is kept once -- got {paras(out)}")

tail = "4. While interpreting any statutory provision, it has always"
out = clean("Earlier text that is long enough to matter here.\n\n" + tail,
            tail + " been accepted as a golden rule of interpretation.")
check(out.count("While interpreting any statutory provision") == 1 and "been accepted as a golden rule" in out,
      f"a paragraph cut mid-sentence and repeated at the start of the next piece is kept once and completed -- got {out!r}")

out = clean("First piece ends with an ordinary sentence.", "Second piece starts with something entirely different.")
check(paras(out) == ["First piece ends with an ordinary sentence.", "Second piece starts with something entirely different."],
      "pieces that do NOT overlap are left exactly as they are")

out = clean("The Court held so. [Para 19]", "[Para 19] It then went on to hold otherwise entirely.")
check("[Para 19]" in out.split("It then")[0] and out.count("[Para 19]") == 2,
      "a short coincidental repeat (under 30 characters) is NOT treated as an overlap")

# ------------------------------------------------------------------ 2. page-margin letters
check("the petitioner" in clean("He asked whether the D petitioner could apply.") and " D " not in clean("He asked whether the D petitioner could apply."),
      "a margin letter between lowercase words is removed ('the D petitioner' -> 'the petitioner')")
check(clean("imprisonment for not less than ten C years and fine") == "imprisonment for not less than ten years and fine",
      "'ten C years' -> 'ten years'")
out = clean("Held: Jn matters concerning personal liberty H\n\nA and penal statutes, it is the obligation of the court.")
check("personal liberty and penal statutes" in out and " H" not in out.split("liberty")[1][:3],
      f"a trailing margin letter plus a leading one across a paragraph break are removed and the sentence is rejoined -- got {out!r}")
check(clean("Disposing of the petitions, the Court · F\n\nHELD: MAJORITY OPINION").split("\n\n")[0].endswith("Court ·"),
      "a margin letter trailing a stray mark is removed")

# things that LOOK like margin letters but are the judgment's own words must be left alone
for keep in ["Accused A and accused B were tried together.", "the accused A and B were arrested", "witness B stated that he saw it",
             "as set out in Schedule C to the Act", "as Exhibit A shows the amount", "under Article 21 A of the Constitution",
             "the petitioner A was a public servant", "Part B of the plan describes", "Mr. A and Mr. B appeared", "Form B is to be filed",
             "the appellant D was convicted"]:
    check(clean(keep) == keep, f"legitimate letter left alone: {keep!r} -> {clean(keep)!r}")

# ------------------------------------------------------------------ 2b. margin letters before a CAPITALISED word
# Riskier: a letter before a capital word can be a person's initial ("Ram B Singh") or a real word ("(3) A
# Magistrate"). So it is only removed when it FITS THE PAGE'S MARGIN SEQUENCE (A-H run down each page, so the
# letter must follow, within ~1500 characters, one already confirmed as a margin letter) and passes every keep rule.
out = clean("Held that the F petitioner was arrested on 5 November. Reference was made to the First G Information Report of the case.")
check("First Information Report" in out and " G " not in out,
      f"'First G Information Report' -> the G is removed because it follows the confirmed margin letter F -- got {out!r}")
out = clean("The Court applied the D principle here and cited E Section 139 of the Act for the point.")
check(" E " not in out, f"a capital-word margin letter that follows a confirmed one (D then E) is removed -- got {out!r}")

for keep in ["Mr. Ram B Singh appeared for the State.",                       # a person's initial, no margin context
             "Justice A K Sikri delivered a separate opinion.",               # initials chain
             "the accused A Kumar was produced before the Magistrate.",        # keep-list word
             "M/s A Traders Private Limited was the complainant.",             # M/s + name
             "the D petitioner argued, A Bench of five judges was constituted."]:   # 'A' after punctuation = a real word
    got = clean(keep)
    exp = "the petitioner argued, A Bench of five judges was constituted." if keep.startswith("the D petitioner") else keep
    check(got == exp, f"real text left alone: {keep!r} -> {got!r}")

out = clean("the C petitioner replied.\n\n(3) A Magistrate authorizing detention under this section shall record his reasons.")
check("(3) A Magistrate authorizing" in out, f"a statute sub-section that starts 'A Magistrate' is never treated as a margin letter -- got {out!r}")

out = clean("the F petitioner said. Later Ram B Singh appeared before the Court in the matter.")
check("Ram B Singh" in out, f"a capital-word letter that does NOT follow the page sequence (F then B) is kept -- got {out!r}")

far = "the D petitioner argued. " + ("Ordinary sentence about the case goes here. " * 60) + "Reference to Ram E Singh was made."
check("Ram E Singh" in clean(far), "a capital-word letter far (1500+ chars) from any confirmed margin letter is kept")

# ------------------------------------------------------------------ 3. paragraph breaks that split a sentence
out = clean("The petitioner relied upon Rajeev Chaudhary v. State\n\n(NCT) of Delhi) case to contend that the term means ten years.")
check(paras(out) == ["The petitioner relied upon Rajeev Chaudhary v. State (NCT) of Delhi) case to contend that the term means ten years."],
      f"a sentence split across two paragraphs is rejoined -- got {paras(out)}")
out = clean("it has always\n\nbeen accepted as a golden rule.")
check(paras(out) == ["it has always been accepted as a golden rule."], "a lowercase continuation is rejoined")
out = clean("The Court concluded the matter.\n\n2. The petitioner relied upon a decision of this Court.")
check(len(paras(out)) == 2, "a numbered paragraph after a full stop stays a separate paragraph")
out = clean("The conditions are as follows\n\n(a) the accused shall appear;\n\n(b) the accused shall not leave.")
check(len(paras(out)) == 3, "list items '(a)', '(b)' are not glued to the line before them")
out = clean("Duty of Courts:\n\nIn matters of liberty the court must act.")
check(len(paras(out)) == 2, "a heading ending in a colon stays on its own")
out = clean("HELD: MAJORITY OPINION\n\nper Madan B. Lokur, J.: the primary question is the meaning.")
check(len(paras(out)) == 2, "an ALL-CAPS heading stays on its own")

# ------------------------------------------------------------------ 3b. running page headers (the case name printed on every page)
head = "NAVTEJ SINGH JOHAR v. UOI THR. SECY. MINISTRY OF LAW & JUSTICE[DIPAK MISRA, CJI ]"
body = [("The reasoning continues here with substantive discussion number %d of the constitutional question, "
         "examining the text, the precedents and the purpose of the provision at some length before it moves on "
         "to the next point that the Court has to decide in this matter." % i) for i in range(6)]
out = clean("\n\n".join(x for pair in zip([head] * 6, body) for x in pair))
check(head not in out and all(b in out for b in body),
      "a running page header repeated on every page (5+ times, in capitals) is removed; the real text between stays")
sentence = "The appeal is dismissed as prayed for here."
out = clean("\n\n".join(x for pair in zip([sentence] * 6, body) for x in pair))
check(out.count(sentence) == 6, "an ordinary repeated sentence (not a header-looking line) is NOT removed")
few = clean(head + "\n\n" + body[0] + "\n\n" + head + "\n\n" + body[1])
check(few.count(head) == 2, "a header-looking line that appears only twice is left alone")

# ------------------------------------------------------------------ 4. safety net + idempotence
same = "A sentence that is untouched by cleaning and long enough to count."
check(clean(same) == same, "clean text passes through unchanged")
messy = clean("He said the D petitioner\n\nwas heard. " + p1 + "\n\n" + p2, p2 + "\n\n" + p3)
check(clean(messy) == messy, "cleaning is idempotent: running it on already-clean text changes nothing")

dup = "A long repeated paragraph of judgment text that goes on for a fair while so it counts as substantial. " * 3
out, note = case_lookup.clean_judgment_text([dup.strip() + "\n\n" + dup.strip(), dup.strip(), dup.strip()], with_note=True)
check(note and "skipped" in note.lower() and out.count("A long repeated paragraph") >= 3,
      "if cleaning would remove more than half the text, it is SKIPPED (raw text kept) and says so -- never silently gutting a judgment")

# ------------------------------------------------------------------ 5. wired into assemble_case
big = lambda s: (s + " ") * 40
a = big("First part of the reasoning about the meaning of the statute.")
b = big("Second part of the reasoning about the accused and the period of custody.")
rows = [(0, "Case: X v Y\nSection: BODY\n\n" + a + "\n\n" + b, "body", 2), (1, "Case: X v Y\nSection: PARAGRAPH\n\n" + b + "\n\nFinal directions of the Court.", "paragraph", 2)]
doc = case_lookup.assemble_case("c1", rows)
check(doc["text"].count("Second part of the reasoning") <= 1 or doc["text"].count(b.strip()) == 1,
      "assemble_case removes the piece that overlaps between two source chunks")
check("Final directions of the Court." in doc["text"] and doc["complete"], "assemble_case still returns the full, complete judgment")

# ------------------------------------------------------------------ 6. old cached (uncleaned) copies must not be served
_TMP = tempfile.mkdtemp()
case_lookup.INDEX_PATH = os.path.join(_TMP, "index.db")
case_lookup.STATE_PATH = os.path.join(_TMP, "state.db")
import sqlite3
old = sqlite3.connect(case_lookup.STATE_PATH)
old.execute(f"CREATE TABLE IF NOT EXISTS doc_cache ({case_lookup._DOC_COLUMNS})")
old.execute("INSERT INTO doc_cache (case_id, text, complete, is_procedural, n_chunks, expected_chunks, warnings_json, fetched_at) "
            "VALUES ('cOLD', ?, 1, 0, 2, 2, '[]', 0)", ("STALE MESSY COPY " * 200,))
old.commit(); old.close()


class FakeCon:
    def __init__(self, rows): self.rows, self.calls = rows, 0
    def execute(self, *a, **k): self.calls += 1; return self
    def fetchall(self): return self.rows


fresh = [(0, big("Freshly fetched and cleaned judgment text."), "body", 1)]
fc = FakeCon(fresh)
case_lookup._duckdb = lambda: fc
d = case_lookup.fetch_case_text("cOLD")
check(fc.calls == 1 and "STALE" not in d["text"], "a copy saved by the OLD (uncleaned) code is not served -- the case is fetched again and cleaned")
d2 = case_lookup.fetch_case_text("cOLD")
check(fc.calls == 1 and d2["from_cache"], "...and the new cleaned copy is then cached as before")

# ------------------------------------------------------------------ 7. the file tells the reader what was done
check("removed" in case_document.DISCLAIMER.lower() and "wording" in case_document.DISCLAIMER.lower(),
      "the disclaimer inside the file says repeated text/margin letters were removed and the wording was not changed")
check("NOT been independently verified" in case_document.DISCLAIMER, "the original 'not independently verified' warning is still there")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
