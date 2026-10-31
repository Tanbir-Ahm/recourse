"""
test_support_discipline.py -- the support rule in the two v3 prompts (2026-10-31, items 2 and 3 of the owner's answer-quality list): every point must rest on a provision or passage in the material and state only what the
passage shows; a general principle not in the material is flagged; each "ground that can be urged" names what it rests on.  Offline and free.  Run: python -X utf8 test_support_discipline.py
Prompt rules cannot be proved to work offline: whether the model obeys them is for the owner's staging test (DEPLOY_STAGING.md Part 4ag).
"""
import sys

import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


V1, L, N = CA.RESPONSE_GENERATION_PROMPT, CA.RESPONSE_GENERATION_PROMPT_V3_LAWYER, CA.RESPONSE_GENERATION_PROMPT_V3
GEN = "As a general rule, not from the material below,"
check("rest on a provision or a passage in the material" in N and GEN in N, "the Adviser prompt: points rest on the material; a general principle is flagged in a fixed clause")
check("must rest on a provision or a passage in the material" in L and GEN in L and "never in the Bottom line" in L, "the Research Note prompt: propositions rest on the material; a general principle is flagged and never in the Bottom line")
check("do not add a condition, a test, an exception or a phrase that the passage does not contain" in N and "do not add a condition, a test, an exception or a phrase that the passage does not contain" in L.replace("Do not", "do not"), "both: no condition, test, exception or phrase that the passage does not contain")
check("do not describe a case's facts" in N and "do not describe a case's facts" in L.replace("Do not", "do not"), "both: no description of a case's facts or holding beyond the passage's words")
check("Support:" not in V1 and GEN not in V1, "the default style (v1) is unchanged by the rule")
check("Put at the end of each ground, in brackets, the provision or the case it rests on" in L and "does not support a specific ground" in L, "grounds: each names what it rests on; none can be written without a basis")
check("exact subsection" not in L.split("## Voice and shape")[1] and "the subsection as the material shows it" in L, "the lawyer's note shape no longer asks for an 'exact subsection' the material may not show (the Hard rules block, shared by every style, is untouched)")
for must in ("**Bottom line**", "**Gaps and checks**", "Facts assumed", "Application to the facts", "Never say that a case \"is good law\""):
    check(must in L, f"the Research Note keeps {must!r}")
# the Hard rules block is identical across the styles (the owner's standing rule)
def hard(t):
    a = t.index("## Hard rules (never break)")
    b = t.index("## What to include, what to leave out")
    return t[a:b]


check(hard(V1) == hard(N) == hard(L), "the Hard rules block is identical in v1, the Adviser and the Research Note")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")
