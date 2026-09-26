
"""
test_old_code_note_for_classifier.py

Regression suite for chat_assistant._old_code_note_for_classifier() -- the fix for a real
confirmed failure (2026-09-26, found via real WhatsApp use): "What is section 302 of IPC" was
refused as out of scope; "What is section 302 BNS", the identical question, was answered in full
one minute later by the same person, because the scope classifier's own rubric is worded "under
BNS/BNSS" and has no way to know IPC/CrPC are that same law's old names.

Pure Python, no API calls, no network -- this function is a regex detection + table lookup, same
discipline as every other curated override in this project. Run directly:
    python -X utf8 test_old_code_note_for_classifier.py
"""
from chat_assistant import _old_code_note_for_classifier, _find_ungrounded_reasoning_sections

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- the exact real failures this fix closes ----

note = _old_code_note_for_classifier("What is section 302 of IPC")
check(
    "IPC Section 302" in note and "BNS 103" in note,
    "the exact real failing question ('section 302 of IPC') produces a note naming the real BNS 103 equivalent",
)

note_bare = _old_code_note_for_classifier("What is 420 IPC")
check(
    "IPC Section 420" in note_bare and "BNS 318" in note_bare,
    "a BARE old-code reference with no 'Section' word ('420 IPC') is detected too -- "
    "this is the exact phrasing that repeatedly failed in real WhatsApp use",
)

check(
    _old_code_note_for_classifier("Ingredients of 420 IPC") != ""
    and _old_code_note_for_classifier("What are the ingredients for 420 IPC ?") != "",
    "every real failing phrasing variant from the actual logs produces a note, not just one exact wording",
)

# ---- must never fire on current-law questions ----

check(
    _old_code_note_for_classifier("What is section 302 BNS") == "",
    "a question already using the CURRENT law's name (BNS) produces no note -- nothing to translate",
)
check(
    _old_code_note_for_classifier("What is section 318 BNS") == "",
    "same for BNSS/BNS section numbers generally -- this fix is old-code-specific, not a general section detector",
)

# ---- honest edge cases ----

check(
    _old_code_note_for_classifier("My cousin was arrested and the police didn't explain anything") == "",
    "a question naming no section number at all produces no note",
)
check(
    _old_code_note_for_classifier("") == "" and _old_code_note_for_classifier(None) == "",
    "an empty or None question never raises, just returns no note",
)
check(
    _old_code_note_for_classifier("Section 124A IPC -- is this still a real offence?") == "",
    "a repealed-with-no-successor old section (124A, sedition) produces no note -- "
    "there is nothing current to translate it to, so it is honestly left alone",
)

# ---- CrPC works the same way as IPC, not just IPC ----

note_crpc = _old_code_note_for_classifier("What is section 41 CrPC")
check(
    "CrPC Section 41" in note_crpc and "BNSS 35" in note_crpc,
    "CrPC old-code references are translated the same way IPC ones are, not a special case",
)

# ---- the note explicitly tells the model not to repeat it to the user ----

check(
    "do not state this mapping to the user" in note,
    "the note is explicitly marked internal-only -- the classifier must never announce the mapping itself",
)

# ---- the note protects its own translated number from the ungrounded-number guard ----
# (this is the second half of the real fix: without it, a reasoning sentence that correctly
# repeats the NEW section number this note supplied would be wrongly flagged as "invented",
# since the user's own raw question only ever said the OLD number)

question = "What is section 302 of IPC"
reasoning_using_new_number = "This asks about BNS Section 103, a general criminal law question with no arrest described."
check(
    _find_ungrounded_reasoning_sections(reasoning_using_new_number, question) != [],
    "sanity check: comparing against the BARE question alone, '103' correctly looks ungrounded "
    "(the user only ever typed '302') -- proving the guard is real, not a no-op",
)
check(
    _find_ungrounded_reasoning_sections(reasoning_using_new_number, question + note) == [],
    "but comparing against question + the trusted note (the actual fix), '103' is correctly "
    "recognised as grounded -- it came from a verified lookup table, not a model guess",
)


if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
