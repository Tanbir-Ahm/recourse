"""test_polish_fixes.py -- three small defects seen in the live Q7 answer (2026-10-14): a doubled wider-search label after an italic case name that ends in a bracket, a v3 lawyer heading with a colon
split into a heading plus a stray paragraph, and the quote-check log now saying what the closest wording in the sources was. Offline and free. Run: python -X utf8 test_polish_fixes.py"""
import re
import sys

import grounding_checks as G
import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# 1. the label goes AFTER the closing italics mark when the bracket is part of the italic name, so the model's own label after the mark is recognised and not doubled
cases = [{"case_name": "Sumit Mehta v. State of N.C.T. of Delhi"}]
L = T.LABEL
for src in ("3. *Sumit Mehta v State (NCT of Delhi)* %s held a condition onerous." % L,
            "3. *Sumit Mehta v State (NCT of Delhi)* held a condition onerous.",
            "3. **Sumit Mehta v State (NCT of Delhi)** %s held a condition onerous." % L,
            "3. Sumit Mehta v State (NCT of Delhi) %s held a condition onerous." % L):
    out = T.label_fed_cases(src, cases)
    check(out.count(L) == 1, f"one label only ({out!r})")
check(T.label_fed_cases("3. *Sumit Mehta v State (NCT of Delhi)* held.", cases) == "3. *Sumit Mehta v State (NCT of Delhi)* %s held." % L, "and it sits after the closing mark, outside the italics")
check(T.label_fed_cases("*Sumit Mehta v State* (2013) held.", cases) == "*Sumit Mehta v State* (2013) %s held." % L, "a year after the name still works as before")

# 2. a v3 heading that is a whole bold line and contains a colon stays one heading (the page code is read from the file: importing recourse_app would start Streamlit)
src = open("recourse_app.py", encoding="utf-8").read()
start = src.index("import re as _re_lbl")
end = src.index("# hero", start)
ns = {}
exec(src[start:end].replace("\n# ----", "\n# ----"), ns)
promote = ns["_promote_answer_labels"]
md = "**Bottom line**\n\nText.\n\n**1. Section 482(2) of the BNSS: scope of conditions on anticipatory bail**\n\nSection 482(2) lets the court attach conditions.\n"
out = promote(md, "lawyer")
check("**1. Section 482(2) of the BNSS: scope of conditions on anticipatory bail**\n\nSection 482(2)" in out, f"the lawyer heading is not split at its colon ({out!r})")
out_old = promote("**What the law says:** the court may attach conditions.\n", "")
check(out_old.startswith("**What the law says:**\n\nthe court may attach"), "v1/v2 behaviour is unchanged: 'Label: body' still becomes a sub-head plus a paragraph")
out_l = promote("**Right now:** do this first.\n", "layman")
check(out_l.startswith("**Right now:**\n\ndo this first."), "a v3 layman line with text after the bold label is still split as before")

# 3. the quote-check log names the closest wording, so a false alarm can be told from a real misquote
mat = "The Court observed that it would not be justified in imposing freak- ish conditions on the applicant and may impose necessary just and efficacious conditions."
q = "would not be justified in imposing freakish conditions"
check(G.check_quotes('The court "%s" here.' % q, mat) == [q], "a hyphenated 'freak-ish' in the source is flagged (the check itself is unchanged)")
near = G.nearest_wording(q, mat)
check("freak ish conditions" in near and near.split(":")[0] != "", f"the closest wording is found ({near!r})")
import contextlib
import io
import json
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    G.log_line("abc", [], [q], material=mat)
rec = json.loads(buf.getvalue().split("GROUNDING_CHECK ", 1)[1])
check(rec["quotes"] == [q] and rec["nearest"] and "freak ish" in rec["nearest"][0], "GROUNDING_CHECK carries a 'nearest' field for a flagged quote")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    G.log_line("abc", ["x"], [])
check("nearest" not in buf.getvalue(), "and nothing extra when no quote is flagged")


# 4. exact-quote instruction (owner's "do only 3", 2026-10-15): quotation marks only for exact copies; a cut-off passage is not completed from memory
import chat_assistant as CA
check("exactly, letter for letter" in T.FEED_INSTRUCTION and "WITHOUT quotation marks" in T.FEED_INSTRUCTION and "ends in \"...\" is cut off" in T.FEED_INSTRUCTION, "the wider-search instruction says: quotation marks only for exact copies, and do not complete a cut-off passage")
check("copied letter for letter" in CA._V3_LAWYER_SHAPE and "without quotation marks" in CA._V3_LAWYER_SHAPE, "the lawyers' template says the same")


# 5. the lawyers' case-check box follows REGISTER_HOOKS (hidden when off)
src = open("recourse_app.py", encoding="utf-8").read()
i = src.index("def _footer():")
seg = src[i:i + 600]
check("register_hooks._off()" in seg and seg.index("_case_check_box()") > seg.index("register_hooks._off()"), "the footer shows the lawyers' case-check box only when REGISTER_HOOKS is not off")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
