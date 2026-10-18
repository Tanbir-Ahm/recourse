"""test_grounding_checks.py -- the citation check and the quote check (grounding_checks.py) and their wiring in generate_grounded_response / answer_question. Offline and free. Run: python -X utf8 test_grounding_checks.py"""
import contextlib
import io
import os
import sys
import types

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.pop("GROUNDING_CHECKS", None)
import grounding_checks as G
import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


MATERIAL = ("My trial has gone on nine years. [BNSS Section 346] Adjournments only for recorded reasons. "
            "P. Ramachandra Rao Vs. State of Karnataka [(2002) 4 SCC 578]: \"It is neither advisable, nor feasible, nor judicially permissible to draw or prescribe an outer limit for conclusion of all criminal proceedings.\" "
            "The directions in Common Cause (I), Raj Deo Sharma (1) and Raj Deo Sharma (II) could not have been so prescribed. Arnesh Kumar v. State of Bihar: arrest guidelines. "
            "The user wrote: Mohan Lal v. State of Punjab was cited by my lawyer.")

# ---- settings ----
check(G.mode() == "log", "the default mode is log: nothing the user sees changes")
for v, want in (("warn", "warn"), (' "ENFORCE" ', "enforce"), ("off", "off"), ("banana", "log"), ("", "log")):
    os.environ["GROUNDING_CHECKS"] = v
    check(G.mode() == want, f"GROUNDING_CHECKS={v!r} is read as {want}")
os.environ.pop("GROUNDING_CHECKS")

# ---- citation check ----
ans = ("In P. Ramachandra Rao v. State of Karnataka (2002) the Court spoke of an outer limit. Arnesh Kumar v. State of Bihar gave arrest guidelines. "
       "In Ramesh Chandra v. State of Madhya Pradesh (2011) 4 SCC 112 the Court held that nine years ends any trial.")
res = G.check_cases(ans, MATERIAL)
check([c["name"] for c in res] == ["Ramesh Chandra v. State of Madhya Pradesh"], f"only the invented case is flagged; cases in the passages are not ({res})")
check(res and res[0]["status"] == "not_found", "a case that is neither in the material nor in the site's Supreme Court list is 'not_found'")
check(G.check_cases("Under Arnesh Kumar v. State of Bihar police must give notice.", "no passages at all")[0]["status"] == "real_not_supplied", "a real Supreme Court case that was not among the passages is 'real_not_supplied'")
check(G.check_cases("In Mohan Lal v. State of Punjab (2018) the Court held X.", MATERIAL) == [], "a case the user named in the question counts as part of the material")
check(G.check_cases("In Raj Deo Sharma v. The State of Bihar (1999) time limits were set.", MATERIAL) == [], "a case that a passage names (even in short form) is part of the material")
check(G.check_cases("In P. Rama Chandra Rao v. State of Karnataka the Court held X.", MATERIAL) == [], "spacing differences in a party name do not matter ('Rama Chandra' and 'Ramachandra')")
check(G.check_cases("State of Bihar v. Union of India was decided long ago.", "nothing") == [], "a name with no distinctive party (State v. Union) is never a basis for a notice")
check(G.check_cases("In Zorro Unreal v. State of Nowhere the Court held X.", "nothing", exists_fn=lambda n: None)[0]["status"] == "unknown", "when the list cannot be searched the status is 'unknown', not 'not_found'")
check(G.check_cases("In Zorro Unreal v. State of Nowhere the Court held X. In Zorro Unreal v. State of Nowhere again.", "nothing", exists_fn=lambda n: False).__len__() == 1, "the same case named twice is reported once")
check(G.check_cases("", MATERIAL) == [] and G.check_cases(None, None) == [], "empty input does not fail")
check(G.sc_list_has("Arnesh Kumar v. State of Bihar") is True and G.sc_list_has("Ramesh Chandra v. State of Madhya Pradesh") is False and G.sc_list_has("Zorro Unreal v. State of Nowhere") is False, "the Supreme Court list lookup wants the same first party: a longer lookalike title is not a match")
check(G.sc_list_has("Raj Deo Sharma v. The State of Bihar") is True, "a case with 'The State of Bihar' matches the list title")

# ---- quote check ----
q_ok = 'The Court said it is "neither advisable, nor feasible, nor judicially permissible to draw or prescribe an outer limit" for criminal proceedings.'
check(G.check_quotes(q_ok, MATERIAL) == [], "an exact quotation passes")
check(G.check_quotes('It is “Neither advisable, nor feasible, nor judicially permissible to draw or prescribe an outer limit.”', MATERIAL) == [], "curly quotes, capital letters and the final full stop do not matter")
check(G.check_quotes('The Court held "neither advisable ... judicially permissible to draw or prescribe an outer limit for conclusion of all criminal proceedings" there.', MATERIAL) == [], "an ellipsis splits a quotation and each piece is checked")
check(G.check_quotes('The Court said "it is [in our view] neither advisable, nor feasible, nor judicially permissible to draw" a limit.', MATERIAL) == [], "a [bracketed] insertion splits a quotation too")
bad = G.check_quotes('The Court held that "delay of five years ends any trial automatically in every case" and so on.', MATERIAL)
check(bad == ["delay of five years ends any trial automatically in every case"], f"words that are in no passage are flagged ({bad})")
check(G.check_quotes('The Court said it is "neither advisable, nor feasible, nor judicially forbidden to draw or prescribe an outer limit" for criminal proceedings.', MATERIAL) != [], "one changed word in a quotation is flagged")
check(G.check_quotes('This is "not good law" and "a crime never dies".', MATERIAL) == [], "short phrases (under five words) are not checked")
check(G.check_quotes('My lawyer cited "Mohan Lal v. State of Punjab was cited by my lawyer" in court.', MATERIAL) == [], "words the user wrote count as part of the material")
check(G.check_quotes("", MATERIAL) == [] and G.check_quotes(None, None) == [], "empty input does not fail")

# ---- wording ----
ns = G.notices([{"name": "A v. B", "status": "not_found"}, {"name": "C v. D", "status": "real_not_supplied"}], ["some words quoted here that are not real"])
check(len(ns) == 3 and "could not find it in our list" in ns[0] and "could not find it" not in ns[1] and "Treat them as unverified" in ns[2], "three notices: not found, real but not supplied, unverified words")
check(all("good law" not in n for n in ns), "no notice says a case is good law")

# ---- wiring in generate_grounded_response ----
CALLS = []
REPLIES = []


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        CALLS.append(c if isinstance(c, str) else "".join(b["text"] for b in c))
        text = REPLIES.pop(0) if REPLIES else "Plain answer."
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], stop_reason="end_turn", usage=types.SimpleNamespace(input_tokens=10, output_tokens=10))


CA.client = types.SimpleNamespace(messages=_Msgs())
RET = "[BNSS Section 346]\nAdjournments only for recorded reasons.\nP. Ramachandra Rao v. State of Karnataka held: \"neither advisable, nor feasible, nor judicially permissible to draw or prescribe an outer limit\"."
BADANS = ("Under Section 346 of the BNSS adjournments need reasons. In Ramesh Chandra v. State of Madhya Pradesh (2011) 4 SCC 112 the Court held that "
          "\"delay of five years ends any trial automatically in every case\".")
GOODANS = "Under Section 346 of the BNSS adjournments need reasons. The Supreme Court in P. Ramachandra Rao v. State of Karnataka said an outer limit is not permissible."


def run(mode_value, replies):
    if mode_value is None:
        os.environ.pop("GROUNDING_CHECKS", None)
    else:
        os.environ["GROUNDING_CHECKS"] = mode_value
    CALLS.clear()
    REPLIES[:] = replies
    G.reset_notes()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = CA.generate_grounded_response("My trial has gone on nine years", RET, matches=[])
    return out, buf.getvalue(), G.pop_notes()


out, log, notes = run(None, [BADANS])
check(out == BADANS and len(CALLS) == 1 and "GROUNDING_CHECK" in log and not notes, "log mode: the answer goes out unchanged, one model call, one GROUNDING_CHECK line, no notice")
out, log, notes = run("off", [BADANS])
check(out == BADANS and "GROUNDING_CHECK" not in log and not notes, "off: nothing is checked or printed")
out, log, notes = run("warn", [BADANS])
check(out == BADANS and len(CALLS) == 1 and len(notes) == 2, f"warn: the answer goes out unchanged with two notices (the case and the quotation) ({len(notes)})")
out, log, notes = run("enforce", [BADANS, GOODANS])
check(out == GOODANS and len(CALLS) == 2 and "Ramesh Chandra" in CALLS[1] and "CORRECTION NEEDED" in CALLS[1] and not notes, "enforce: the model is asked once more with the invented case and the quotation named, and the corrected answer is used")
out, log, notes = run("enforce", [BADANS, BADANS])
check(out is None and len(CALLS) == 2, "enforce: a case that cannot be found anywhere and is still there after the second try withholds the answer")
SOFT = "Under Section 346 of the BNSS adjournments need reasons. The Court held that \"delay of five years ends any trial automatically in every case\"."
out, log, notes = run("enforce", [SOFT, SOFT])
check(out == SOFT and len(CALLS) == 2 and len(notes) == 1 and "quotation marks" in notes[0], "enforce: a quotation that is still unsupported after the second try is shown with a notice, not withheld")
out, log, notes = run("enforce", [GOODANS])
check(out == GOODANS and len(CALLS) == 1 and not notes and "GROUNDING_CHECK" not in log, "enforce: a clean answer costs one call and prints nothing")
REAL = "Under Section 346 of the BNSS adjournments need reasons. In Arnesh Kumar v. State of Bihar the Court gave guidelines on arrest."
out, log, notes = run("enforce", [REAL, REAL])
check(out == REAL and len(CALLS) == 2 and len(notes) == 1 and "could not find it in our list" not in notes[0], "enforce: a real case that was not among the passages is retried, then shown with a notice, not withheld")
os.environ.pop("GROUNDING_CHECKS", None)

# ---- wiring in answer_question ----
CA._answer_question_core = lambda q, inline_domains=frozenset(): {"state": "single_match", "response_text": CA.generate_grounded_response(q, RET, matches=[]) or "x"}
os.environ["GROUNDING_CHECKS"] = "warn"
REPLIES[:] = [BADANS]
with contextlib.redirect_stdout(io.StringIO()):
    r = CA.answer_question("My trial has gone on nine years")
check(len(r.get("grounding_notes") or []) == 2, "answer_question puts the notices on the result (warn)")
os.environ["GROUNDING_CHECKS"] = "log"
REPLIES[:] = [BADANS]
with contextlib.redirect_stdout(io.StringIO()):
    r = CA.answer_question("My trial has gone on nine years")
check("grounding_notes" not in r, "in log mode the result carries no notices")
os.environ.pop("GROUNDING_CHECKS", None)


# --- staging 2026-10-14: a short quoted word must not pair with a quotation mark far away (false alarm in question 7)
_ans = 'The bench called it "freakish" and went on. It held "evidently onerous and unreasonable" here.\n| Sumit Mehta | condition "disproportionate to a legitimate bail purpose. If the amount is modest" |\n| B. Ramu | said "freakish" |'
_mat = "evidently onerous and unreasonable. freakish. disproportionate to a legitimate bail purpose. If the amount is modest"
check(G.check_quotes(_ans, _mat) == [], f"short quoted words and table cells do not produce a false alarm ({G.check_quotes(_ans, _mat)})")
check(G.check_quotes('He said "this phrase was never in any passage at all" ok', _mat) == ["this phrase was never in any passage at all"], "a real invented quotation is still found")

# --- situation exam run 3 (2026-10-16), question S18: the answer put its own paraphrase of the person's question in quotation marks and the quote check flagged it
_q18 = "The police filed a charge sheet and the magistrate took cognizance. The complainant now asks the magistrate to order further investigation. Can the magistrate do that?"
_a18 = 'None of the material covers this exact situation, so I can only tell you what is available on related powers, not a direct answer to "can the magistrate do this after cognizance on a police report."'
_m18 = _q18 + "\nSection 175(3) of the BNSS lets a magistrate order an investigation."
check(G.check_quotes(_a18, _m18) == ["can the magistrate do this after cognizance on a police report."], "without the question the paraphrase is flagged (the behaviour until now)")
check(G.check_quotes(_a18, _m18, question=_q18) == [], "a paraphrase of the person's question, introduced as the answer to it, is not flagged")
check(G.check_quotes(_a18, _m18, question=None) == G.check_quotes(_a18, _m18), "question=None behaves exactly as before")
_inv = 'In reply to your question: the Court held "a magistrate cannot order further investigation after cognizance on a police report" in that case.'
check(G.check_quotes(_inv, _m18, question=_q18) == [], "(documented limit) a quotation introduced as the reply to the question and made of the question's own words is excused")
_inv2 = 'The Supreme Court held "a magistrate cannot order further investigation after cognizance on a police report" in that case.'
check(G.check_quotes(_inv2, _m18, question=_q18) == ["a magistrate cannot order further investigation after cognizance on a police report"], "an invented holding NOT introduced as the person's question is still flagged, even when it shares the question's words")
_inv3 = 'As you asked about the magistrate, the Court said "the quick brown fox jumps over the lazy dog every single day" there.'
check(G.check_quotes(_inv3, _m18, question=_q18) == ["the quick brown fox jumps over the lazy dog every single day"], "a quotation introduced as the question but sharing none of its words is still flagged")

# --- 2026-10-18: a near-match quotation (not an exact copy) must agree with the material on the words that decide a legal meaning
# Found by testing the 95% letter match: in a 44-word quotation "may not" -> "shall not" and a deleted "not" both passed.
_MAT = ("The Court held that the right to a speedy trial is not a mere formality but flows from Article 21 of the Constitution, and the accused person may not be kept in custody indefinitely "
        "without a trial beginning within a reasonable time after the charge sheet is filed. The offence is punishable with imprisonment for a term of three years and a fine, and the Magistrate "
        "may grant bail only after hearing the woman, unless the Court records reasons in writing for refusing it.")
_L = ("the right to a speedy trial is not a mere formality but flows from Article 21 of the Constitution and the accused person may not be kept in custody indefinitely "
      "without a trial beginning within a reasonable time after the charge sheet is filed")
_Q = lambda t: 'It held "%s" there.' % t  # noqa: E731
check(G.check_quotes(_Q(_L), _MAT) == [], "(meaning words) an exact long quotation still passes")
check(G.check_quotes(_Q(_L.upper().replace(" OF THE CONSTITUTION AND", ", OF THE CONSTITUTION, AND")), _MAT) == [], "(meaning words) capitals and commas still do not matter")
check(G.check_quotes(_Q(_L.replace("may not", "shall not")), _MAT) != [], "(meaning words) 'may not' -> 'shall not' in a long quotation is flagged")
check(G.check_quotes(_Q(_L.replace("is not a mere", "is a mere")), _MAT) != [], "(meaning words) a deleted 'not' in a long quotation is flagged")
check(G.check_quotes(_Q(_L.replace("is not a mere", "is not not a mere")), _MAT) != [], "(meaning words) an added word of this kind is flagged too")
check(G.check_quotes(_Q(_L.replace("may not", "may")), _MAT) != [], "(meaning words) 'may not' -> 'may' is flagged")
check(G.check_quotes(_Q(_L.replace("Article 21", "Article 31")), _MAT) != [], "(meaning words) a changed number ('Article 21' -> 'Article 31') is flagged")
_L2 = "the offence is punishable with imprisonment for a term of three years and a fine and the Magistrate may grant bail only after hearing the woman unless the Court records reasons in writing"
check(G.check_quotes(_Q(_L2), _MAT) == [], "(meaning words) the second test quotation passes as an exact copy")
check(G.check_quotes(_Q(_L2.replace("three years", "five years")), _MAT) != [], "(meaning words) 'three years' -> 'five years' is flagged")
check(G.check_quotes(_Q(_L2.replace("years and a fine and the", "years or a fine and the")), _MAT) != [], "(meaning words) 'and' -> 'or' is flagged")
check(G.check_quotes(_Q(_L2.replace("only after", "after")), _MAT) != [], "(meaning words) a dropped 'only' is flagged")
check(G.check_quotes(_Q(_L2.replace("unless the Court", "if the Court")), _MAT) != [], "(meaning words) 'unless' -> 'if' is flagged")
# differences that do NOT change the meaning still pass (the near-match is there for them)
check(G.check_quotes(_Q(_L.replace("a mere formality", "mere formality")), _MAT) == [], "(harmless) a dropped article is not flagged")
check(G.check_quotes(_Q(_L.replace("accused person", "accused-person")), _MAT) == [], "(harmless) a hyphen for a space is not flagged")
check(G.check_quotes(_Q(_L.replace("kept in custody", "held in custody")), _MAT) == [], "(harmless, documented limit) a swapped ordinary word in a long quotation is not flagged")
# edges: one extra or one missing word at the very start or end of the quotation must not be mistaken for a changed meaning word
_MAT_E = "The Court held that " + _L + " and not otherwise, and no appeal lies."
check(G.check_quotes(_Q(_L.replace("a mere formality", "mere formality")), _MAT_E) == [], "(edges) a harmless difference when the next word in the material is 'and'/'not': the one-word-wider window is not mistaken for a changed meaning word")
check(G.check_quotes(_Q(_L.replace("a mere formality", "mere formality").replace("The", "the")), "No. " + _MAT_E) == [], "(edges) the same with a word in front of the quotation in the material")
check(G.check_quotes(_Q(_L.replace("may not", "shall not")), _MAT_E) != [], "(edges) a real change is still flagged there")
_short = "right to a speedy trial is a mere formality but flows from Article 21 of the Constitution"
check(G.check_quotes(_Q(_short), _MAT) != [], "(short quotation) a missing 'not' in a short quotation is still flagged (as before)")
check(G.check_quotes('The Court said "it is neither advisable, nor feasible, nor judicially forbidden to draw or prescribe an outer limit" for criminal proceedings.', MATERIAL) != [], "(meaning words) the older 'one changed word' test still flags")
# the flagged text is reported the same way as before
_bad = G.check_quotes(_Q(_L.replace("may not", "shall not")), _MAT)
check(len(_bad) == 1 and _bad[0].startswith("the right to a speedy trial") and "shall not" in _bad[0], "(report) a flagged quotation is returned in its original wording, once")
# speed: a long material and many near-match quotations
import time as _t
_big = (_MAT + " ") + " ".join("Filler sentence number %d about nothing in particular, with the words may and not and shall appearing now and then." % i for i in range(800))   # about 12,000 words, the size of our largest prompts
_t0 = _t.time()
_n = 0
for _i in range(25):
    _n += len(G.check_quotes(_Q(_L.replace("a reasonable time", "a reasonable time period")), _big))
_dt = _t.time() - _t0
check(_dt < 4.0, f"(speed) 25 near-match quotations against a 12,000-word material take {_dt:.1f} s (limit 4 s)")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
