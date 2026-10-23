"""
test_answer_view.py -- answer_view.py: the engine's result as presentation data for the new front end (WEBSITE_DESIGN 17). Offline and free.
1. the helper copies give exactly the page's output (the page's functions are taken out of recourse_app.py's source by AST, since importing it starts Streamlit);
2. build() on rich answers, non-answers and junk: the pieces, their order and the page's rules (sources worth showing, Act notice hides the scope note, lawyer vs layman);
3. build() never raises; 4. the API puts `view` in the reply (ask) and in saved messages.
Run: python -X utf8 test_answer_view.py
"""
import ast
import html as _html
import os
import random
import re
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
import answer_view as V
import refusal_text

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---------------------------------------------------------------- 1. parity with the page's helpers
src = open(APP, encoding="utf-8").read()
tree = ast.parse(src)
WANT_ASSIGN = {"_LEAD_LABEL", "_WHOLE_LINE_BOLD", "_CAP_AFTER_HEADING", "_V3_HEADING_THEN_TEXT", "_COPY_EMPH", "_PAGE_CRUFT", "_CASE_GENERIC_PARTY", "SHELF_EXCERPT_CHARS"}
WANT_FUNC = {"_tame_sentence_bold", "_promote_answer_labels", "_plain_for_copy", "_clean_excerpt", "_case_is_named", "_sources_worth_showing", "_statute_excerpt"}
ns = {"_re_lbl": re, "_re": re, "_html": _html}
found = set()
for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in WANT_ASSIGN for t in node.targets):
        exec(compile(ast.Module([node], []), APP, "exec"), ns)
        found.update(t.id for t in node.targets)
    elif isinstance(node, ast.FunctionDef) and node.name in WANT_FUNC:
        exec(compile(ast.Module([node], []), APP, "exec"), ns)
        found.add(node.name)
check(found == WANT_ASSIGN | WANT_FUNC, f"every page helper was found in the page's source (missing: {sorted((WANT_ASSIGN | WANT_FUNC) - found)})")
check(ns["SHELF_EXCERPT_CHARS"] == V.SHELF_EXCERPT_CHARS, "the shelf excerpt length is the page's")
for name in ("_LEAD_LABEL", "_WHOLE_LINE_BOLD", "_CAP_AFTER_HEADING", "_V3_HEADING_THEN_TEXT", "_COPY_EMPH", "_PAGE_CRUFT"):
    check(ns[name].pattern == getattr(V, name).pattern and ns[name].flags == getattr(V, name).flags, f"{name}: same pattern and flags as the page")
check(tuple(ns["_CASE_GENERIC_PARTY"]) == V._CASE_GENERIC_PARTY, "generic party names: same list as the page")

MD = [
    "**What does the law say?**\n\nText.", "**What the law says:** the court may attach conditions.\n", "**Right now:** do this first.\n", "**Bottom line**\n\nText.\n\n**1. Section 482(2) of the BNSS: scope of conditions**\n\nBody.\n",
    "1. **But safeguards still apply fully at this stage.** More prose follows here.", "- **Note:** something\n- plain", "In *Arnesh Kumar v. State of Bihar* (2014), the Court said X.", "## How this cuts\n### Sub",
    "*For you:*\n- point one\n- point two\n\n1. Ask your lawyer.", "The fine is 2 * 3 = 6 and 5*4 = 20.", "", None, "   ", "**x**", "**Whole line bold sentence that is long enough to be a clause, not a label.**\nNext line.",
    "Section 17A(1)(b) of the Act; see *ibid.*", "**Your situation**\nYou were arrested.\n\n**What to do**\nCall a lawyer.", "\n\n**A**: b\n", "**Heading?**\nText follows directly",
]
for audience in ("", "layman", "lawyer", "other"):
    for i, md in enumerate(MD):
        a, b = ns["_promote_answer_labels"](md, audience), V.promote_answer_labels(md, audience)
        check(a == b, f"promote_answer_labels parity (audience {audience!r}, sample {i})")
for i, md in enumerate(MD):
    check(ns["_plain_for_copy"](md) == V.plain_for_copy(md), f"plain_for_copy parity (sample {i})")
    for lm in (0, 48, 90):
        check(ns["_tame_sentence_bold"](md or "", lm) == V.tame_sentence_bold(md or "", lm), f"tame_sentence_bold parity (sample {i}, max {lm})")
EXC = ["", None, "Page 8 of 25\nThe Court held &amp; said\n\n\n\n12\n   indented   line  with   gaps</div>\f<br>text\n3 | P a g e\nend", "plain text", "\x0c\x0c12\n\n\n\nbody &nbsp;text"]
for i, t in enumerate(EXC):
    check(ns["_clean_excerpt"](t) == V.clean_excerpt(t), f"clean_excerpt parity (sample {i})")
MATCHES = [
    {"case_name": "Arnesh Kumar v. State of Bihar", "citation": "(2014) 8 SCC 273", "paragraph_number": "7_a", "text": "Arrest is not routine.", "source": "curated"},
    {"case_name": "State of Punjab v. Ram Singh", "paragraph_number": "3", "text": "x", "source": "library"},
    {"case_name": "Ram v. Shyam (Delhi)", "paragraph_number": "9", "text": "y", "source": "library"},
    {"section_number": "35", "act": "BNSS", "text": "Arrest without warrant", "source": "curated_statute"},
    {"section_number": "35", "act": "BNSS", "text": "dup"},
    {"case_name": "", "text": "no name"},
]
for reply in ("", "In Arnesh Kumar the court said so.", "Nothing named here, see section 35.", "In Ram v. Shyam it was held."):
    for cap in (1, 3, 16):
        a = ns["_sources_worth_showing"](MATCHES, reply, cap)
        b = V.sources_worth_showing(MATCHES, reply, cap)
        check(a == b, f"sources_worth_showing parity (reply {reply[:20]!r}, cap {cap})")
for m in MATCHES + [{"text": "z" * 20000, "shelf": {"loaded_on": "2026-10-17"}}, {"text": "z" * 20000}]:
    check(ns["_statute_excerpt"](m) == V.statute_excerpt(m), "statute_excerpt parity")
for m in MATCHES[:2]:
    check(ns["_case_is_named"](m, "in arnesh kumar the court") == V.case_is_named(m, "in arnesh kumar the court"), "case_is_named parity")

# ---------------------------------------------------------------- 2. build()
TEXT = ("**Your situation**\nYou were arrested on a *bailable* charge.\n\n**What the law says**\n**Section 35** of the BNSS limits arrest. In *Arnesh Kumar v. State of Bihar* (2014) the Supreme Court said arrest is not routine.\n\n"
        "**What you can do**\n1. Ask for the grounds of arrest.\n2. Call a lawyer.")
RES = {
    "state": "single_match", "audience": "layman", "response_text": TEXT, "matches": MATCHES,
    "act_notice": None, "outside_scope_note": "This looks like a civil matter.", "register_notes": ["Reported as overruled; not yet confirmed by our reviewer."], "register_possible": ["A possible later case."],
    "register_not_checked": "Not checked by us.", "grounding_notes": ["One quotation could not be matched."],
    "cited_judgment_links": [{"case_name": "Arnesh Kumar v. State of Bihar", "url": "https://example.org/a", "source_label": "Indian Kanoon"}, "junk"],
    "sci_related_judgments": [{"case_name": "X v. Y", "link": "https://sci.gov.in/x", "date": "2020-01-01", "paragraph": "4", "excerpt": "text", "passage_note": "a note"}, "junk"], "sci_fed": True, "sci_as_of": "2026-10-01",
    "anchor_excerpts": [{"case_name": "P. Ramachandra Rao", "status": "machine_checked", "year": 2002, "excerpts": [{"label": "Held", "paragraph": 29, "text": "word for word"}]}],
    "unverified_related_judgments": [{"case_name": "Z v. W", "ik_search_url": "https://indiankanoon.org/search/?formInput=z", "paragraph_number": "2", "procedural_disposal": True}],
    "section_note": [{"lead": "Section 17 in full", "texts": ["The text of 17."], "cites": [{"lead": "Section 13", "texts": ["The text of 13."]}], "loaded_on": "2026-10-17", "cut": True, "source_url": "https://indiacode.nic.in/x"}],
}
v = V.build(RES)
check(v and v["kind"] == "answer" and v["conflicting"] is False and v["label"] == "Your situation", "an answer gives kind answer, not conflicting, the page's label")
check(v["outside_scope_note"] == "This looks like a civil matter." and v["act_notice_html"] is None, "the scope note shows when there is no Act notice")
check("\n\n" in v["answer_markdown"] and v["answer_markdown"].startswith("**Your situation**"), "the answer's bold labels are turned into headings the page's way")
check("**" not in v["copy_text"] and "*" not in v["copy_text"].replace("2. Call", "") and "Arnesh Kumar v. State of Bihar" in v["copy_text"], "the Copy text has no markdown marks")
check(v["fallback_text"] is None, "no fallback text when the answer text exists")
check([s["heading"] for s in v["statutes"]] == ["BNSS Section 35"], f"the statute section the answer names is listed once ({[s['heading'] for s in v['statutes']]})")
check([c["name"] for c in v["judgments"]] == ["Arnesh Kumar v. State of Bihar"], "only the case the answer names is listed as a judgment")
ex = v["judgments"][0]["excerpts"][0]
check(ex["paragraph"] is None or ex["paragraph"].isdigit(), "a paragraph label is a number or null")
check(v["cited_links"] == [{"case_name": "Arnesh Kumar v. State of Bihar", "url": "https://example.org/a", "source_label": "Indian Kanoon"}], "cited links: junk entries dropped")
check(v["register"] == {"notes": RES["register_notes"], "possible": ["A possible later case."], "not_checked": "Not checked by us."}, "register notes in one block")
check(v["grounding_notes"] == ["One quotation could not be matched."], "grounding notes kept")
check(v["sci_related"]["fed"] is True and len(v["sci_related"]["items"]) == 1 and v["sci_related"]["items"][0]["link"] == "https://sci.gov.in/x", "wider-search list, junk dropped")
check(v["anchors"]["unconfirmed"] is True and v["anchors"]["items"][0]["excerpts"][0]["paragraph"] == "29", "anchors: unconfirmed flag, paragraph as text")
check(v["unverified"] == [{"case_name": "Z v. W", "url": "https://indiankanoon.org/search/?formInput=z", "paragraph": "2", "procedural": True}], "unverified related judgments")
sn = v["section_notes"][0]
check(sn["lead"] == "Section 17 in full" and sn["texts"] == ["The text of 17."] and sn["cites"][0]["texts"] == ["The text of 13."] and "shortened here" in sn["caption"] and sn["url"] == "https://indiacode.nic.in/x", "section note: lead, whole text, cited section, caption, link")
check(v["authorities"] is None, "layman: no table of authorities")

# the Act notice hides the scope note (as the page does); conflicting; lawyer: no cited links
r2 = dict(RES, act_notice={"html": "<b>Act</b> notice &amp; more"}, state="conflicting_matches", audience="lawyer")
v2 = V.build(r2)
check(v2["act_notice_html"] == "<b>Act</b> notice &amp; more" and v2["outside_scope_note"] is None and v2["conflicting"] is True, "Act notice replaces the scope note; conflicting flag set")
check(v2["cited_links"] is None, "lawyer: the layman's cited-links list is not offered")
r3 = dict(RES, audience="lawyer", authorities={"library": [], "wider": [], "anchors": []})
v3 = V.build(r3)
check(v3["authorities"] is None or isinstance(v3["authorities"]["tables"], list), "lawyer with an authorities dict: tables are a list (or none if the module declines)")

# no answer text: the first matching text is shown instead
r4 = dict(RES, response_text="")
v4 = V.build(r4)
check(v4["answer_markdown"] is None and v4["fallback_text"] == "Arrest is not routine." and v4["copy_text"].startswith("Here is what the law says on this:"), "no answer text: the first match's text is the fallback")

# non-answers
for st_ in ("no_match", "outside_scope", "adjacent_uncovered", "error"):
    n = V.build({"state": st_, "act_notice": {"html": "x"}, "register_notes": ["r"]})
    want = refusal_text.notice({"state": st_})
    check((n is None) == (want is None) and (n is None or (n["kind"] == "notice" and n["notice"] == refusal_text.notice({"state": st_, "act_notice": {"html": "x"}, "register_notes": ["r"]}))), f"non-answer state {st_}: the shared refusal wording")

# ---------------------------------------------------------------- 3. never raises
JUNK = [None, 0, "x", [], {}, {"state": None}, {"state": "single_match"}, {"state": "single_match", "matches": "no"}, {"state": "single_match", "matches": [None, 3, {"case_name": 5}], "response_text": 5},
        {"state": "single_match", "response_text": "t", "act_notice": "str", "section_note": "str", "anchor_excerpts": [1], "sci_related_judgments": ["a"], "cited_judgment_links": 4, "register_notes": "a string", "audience": "lawyer", "authorities": "x"},
        {"state": "conflicting_matches", "response_text": "t", "section_note": [None, {"cites": [None], "texts": 5}]}, {"state": "single_match", "response_text": "t" * 100000}]
rng = random.Random(7)
for j in JUNK:
    try:
        out = V.build(j)
        check(out is None or isinstance(out, dict), f"junk input handled ({str(j)[:50]!r})")
    except Exception as e:  # noqa: BLE001
        check(False, f"build raised {e!r} on {str(j)[:50]!r}")
import json
check(json.dumps(V.build(RES)) and json.dumps(V.build(r2)), "the view is plain JSON data")

# ---------------------------------------------------------------- 4. the API carries it
import api.ask as ask
import api.routers.chats as chats
body = ask._payload({"result": RES, "cost_inr": 1.0, "elapsed_ms": 5})
check(body["view"] and body["view"]["kind"] == "answer" and body["notice"] is None, "ask reply: `view` next to the engine result")
body2 = ask._payload({"result": {"state": "no_match"}})
check(body2["view"]["kind"] == "notice" and body2["view"]["notice"]["title"] == body2["notice"]["title"], "ask reply for a non-answer: view carries the same notice")
body3 = ask._payload({"result": None})
check(body3["view"] is None, "no result: view is null")


class _M:
    id = "1"; seq = 2; role = "assistant"; content = "x"; result = RES; state = "done"; created_at = None


class _U(_M):
    role = "user"; result = None


check(chats.message_view(_M())["view"]["kind"] == "answer", "a saved assistant message carries the view")
check(chats.message_view(_U())["view"] is None, "a saved user message has no view")

print()
print("ALL PASSED" if not FAILURES else f"{len(FAILURES)} FAILED")
sys.exit(1 if FAILURES else 0)
