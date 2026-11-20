"""test_matter_depth.py -- MATTER_DEPTH (matter_depth.py, depth_ctx.py) and the sizes in the engine (chat_assistant._answer_explain, the Standard answer), MATTER_WORKSPACE_PLAN.md W1 + W2, built 2026-11-20 on the owner's
"Go ahead with W1 and W2 together". Offline and free; the model is stubbed.
Proves: the switch defaults off; the planner on the frozen sets of review_results/2026-11-20_matter_depth (half A tuned on; half B run once: 86 of 92 on the first run, 88 of 92 after two declared changes; set C written after
B, for those two changes: 38 of 40) with the numbers measured on 2026-11-20 and NO law or draft sent to a no-law size on A and B; unsure means Standard; the Standard answer skips the wider search, the AI Act guess, the
scope check, the judgments and the verbatim excerpts, and thinks at 'low'; its template carries the Hard rules word for word; an untraceable section number in a Standard answer is removed with its sentence and costs NO
second answer; the explain answer is ONE call whose reply is checked by code (a section not on hand is removed), carries the law on hand and the Schedule table, and falls back to a Standard answer when nothing is on hand;
with no size given the engine behaves as before.
Run: python -X utf8 test_matter_depth.py"""
import contextlib
import io
import json
import os
import sys
import types
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for _v in ("MATTER_DEPTH", "LAW_ON_HAND", "SCI_SEARCH_MODE", "ACT_DETECT", "ANSWER_EFFORT", "ANCHORS", "LANDMARKS", "GROUNDING_CHECKS"):
    os.environ.pop(_v, None)
os.environ["RESPONSE_STYLE"] = "v3"

import depth_ctx  # noqa: E402
import matter_depth as D  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ------------------------------------------------------------------ the switch
check(D.mode() == "off", "MATTER_DEPTH is off when unset")
for v, want in (("shadow", "shadow"), ("ON", "on"), ("\"on\"", "on"), ("yes", "off")):
    os.environ["MATTER_DEPTH"] = v
    check(D.mode() == want, f"MATTER_DEPTH={v} -> {want}")
os.environ.pop("MATTER_DEPTH")

# ------------------------------------------------------------------ the frozen sets (the harness rule of measure.py: router-derived items get pins_available=True)
BASE = os.path.join(HERE, "..", "recourse-sci-pool", "review_results", "2026-11-20_matter_depth")
if os.path.exists(os.path.join(BASE, "planner_set.json")):
    S = json.load(open(os.path.join(BASE, "planner_set.json")))
    C = json.load(open(os.path.join(BASE, "planner_set_C.json")))["C"]
    NOLAW = {"file", "explain", "smalltalk"}

    def run(items):
        wrong, danger = [], []
        for x in items:
            pins = True if not str(x.get("kind") or "").startswith("new_") else bool(x["pins"])
            got = D.plan(x["q"], pins_available=pins)["size"]
            if got != x["expect"] and got not in x["also"]:
                wrong.append((x["id"], x["expect"], got))
                if x["expect"] in ("standard", "research", "draft") and got in NOLAW:
                    danger.append(wrong[-1])
        return wrong, danger
    for half, want_wrong, want_danger in (("A", 0, 0), ("B", 4, 0)):
        w, dg = run(S[half])
        check(len(w) == want_wrong and len(dg) == want_danger, f"half {half}: {len(S[half]) - len(w)} of {len(S[half])} as frozen; {len(dg)} law or draft sent to a no-law size ({w})")
    w, dg = run(C)
    check(sorted(x[0] for x in w) == ["C02", "C34"] and len(dg) == 1, f"set C: 38 of 40 as frozen; the two misses are the router's (a lookup sent up; 'Is anything missing from the chargesheet?' sent to the file path, which can answer NEEDS_LAW) ({w})")
else:
    print("[SKIP] the research checkout with planner_set.json is not next to this one")

# ------------------------------------------------------------------ a few by hand
for q, pins, want in (("explain the sections in a clear manner", True, "explain"), ("explain the sections in a clear manner", False, "standard"), ("what are the sections charged here?", True, "file"),
                      ("Is he entitled to default bail on these dates?", True, "standard"), ("Which Supreme Court judgments deal with default bail?", True, "research"),
                      ("go through the material I uploaded and draft a bail petition for me", True, "draft"), ("thanks", True, "smalltalk"), ("What is the law here?", True, "standard"),
                      ("Can you explain the sections and also say whether bail will be granted?", True, "standard"), ("explain section 309 of the BNS", False, "explain"),
                      ("Write a detailed legal research memo on default bail", True, "research"), ("Which court is the chargesheet filed in?", True, "file"),
                      ("what is the punishment for these sections", True, "explain"), ("is bail possible for these sections", True, "standard")):
    got = D.plan(q, pins_available=pins)
    check(got["size"] == want, f"{q!r} (pins {pins}) -> {want} ({got['size']}, {got['why']})")
check(D.plan("what are the sections charged here?", has_documents=False)["size"] == "standard", "a matter with no documents: Standard, never a file answer")
check(D.plan("explain the sections")["why"] == "law_signal" or D.plan("explain the sections")["size"] == "standard", "unsure means Standard")

# ------------------------------------------------------------------ depth_ctx and the places it gates
check(depth_ctx.depth() is None and not depth_ctx.skip_wider() and depth_ctx.effort() is None, "no size chosen: nothing is skipped")
import act_detect  # noqa: E402
import excerpt_anchors  # noqa: E402
import sci_search_tier  # noqa: E402

os.environ.update({"SCI_SEARCH_MODE": "feed", "ACT_DETECT": "ai", "ANCHORS": "on", "ANSWER_EFFORT": "medium"})
check(sci_search_tier.mode() == "feed" and act_detect.mode() == "ai", "before: the wider search is in feed mode and the AI Act guess is on")
depth_ctx.set_depth("standard")
check(sci_search_tier.mode() == "off" and act_detect.mode() == "wide" and excerpt_anchors.selected("my trial has gone on nine years, can the case be closed?") == [] and depth_ctx.effort() == "low",
      "Standard: no wider search, the free word pass only, no verbatim excerpts, thinking low")
depth_ctx.set_depth("research")
check(sci_search_tier.mode() == "feed" and act_detect.mode() == "ai" and depth_ctx.effort() is None, "Research: everything as before")
depth_ctx.set_depth(None)
for v in ("SCI_SEARCH_MODE", "ACT_DETECT", "ANCHORS"):
    os.environ.pop(v, None)

# ------------------------------------------------------------------ the engine
import chat_assistant as CA  # noqa: E402
import answer_style  # noqa: E402

CALLS = []


class _Msgs:
    replies = []

    def create(self, **kw):
        m = kw.get("messages") or []
        c = m[-1]["content"] if m else ""
        CALLS.append({"prompt": c if isinstance(c, str) else "".join(b.get("text", "") for b in c), "kw": {k: v for k, v in kw.items() if k != "messages"}})
        text = _Msgs.replies.pop(0) if len(_Msgs.replies) > 1 else _Msgs.replies[0]
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
t = CA.RESPONSE_GENERATION_PROMPT_STANDARD
v1 = CA.RESPONSE_GENERATION_PROMPT
hard = v1[v1.index("## Hard rules (never break)"):v1.index("## What to include, what to leave out")]
check(hard in t and hard in CA.RESPONSE_GENERATION_PROMPT_V3_LAWYER, "the Standard template carries the Hard rules word for word (as the research note does)")
check(all(x in t for x in ("{conflict_instruction}", "{question}", "{retrieved_text}", "{pilot_context}")) and "No judgments are given" in t and "Bottom line" in t and "[Doc 2, p. 3]" in t, "the Standard template: the same placeholders, no judgments, no research-note headings, documents cited")
depth_ctx.set_depth("standard")
check(CA._response_prompt_template() is CA.RESPONSE_GENERATION_PROMPT_STANDARD and CA._answer_max_tokens() == 5000 and CA._answer_effort() == "low", "Standard: its own template, a 5,000-token cap, effort low")
depth_ctx.set_depth(None)
check(CA._response_prompt_template() is CA.RESPONSE_GENERATION_PROMPT_V3_LAWYER or answer_style.template_key() != "v3-lawyer", "no size: the template as before")

# Standard: an untraceable section number never costs a second answer
answer_style.set_audience("lawyer")
CA._MATTER.notes = []
depth_ctx.set_depth("standard")
CALLS.clear()
_Msgs.replies = ["Section 309 of the BNS defines robbery. Section 103 of the BNS covers murder and applies here. The punishment is in sub-section (4)."]
RET = "[BNS Section 309, Section/Para 309]\n309. (1) In all robbery there is either theft or extortion.\n(4) Whoever commits robbery shall be punished with rigorous imprisonment for a term which may extend to ten years."
MATCHES = [{"type": "statute", "act": "BNS", "section_number": "309", "text": "309. (1) In all robbery there is either theft or extortion.\n(4) Whoever commits robbery shall be punished ..."}]
with contextlib.redirect_stdout(io.StringIO()) as buf:
    out = CA.generate_grounded_response("what is the punishment for robbery?", RET, matches=MATCHES, pilot_matches=[])
check(len(CALLS) == 1 and out and "103" not in out and "Section 309 of the BNS defines robbery" in out and "punishment is in sub-section (4)" in out and "STANDARD_FIXED_BY_CODE" in buf.getvalue()
      and "PROMPT_SIZES" in buf.getvalue() and "RECHECK" not in buf.getvalue(), "Standard: ONE call; the sentence naming section 103 is removed by code; the log says so and counts the prompt by block")
check(any("103" in n and "removed by a program" in n for n in CA._MATTER.notes), "a note says what was removed and why")
check(CALLS[0]["kw"].get("output_config") == {"effort": "low"} and CALLS[0]["kw"].get("max_tokens") == 5000, "the call thinks at 'low' with a 5,000-token cap")
CA._MATTER.notes = []
depth_ctx.set_depth("research")
CALLS.clear()
_Msgs.replies = ["Section 309 of the BNS defines robbery. Section 103 of the BNS covers murder and applies here.", "Section 309 of the BNS defines robbery."]
with contextlib.redirect_stdout(io.StringIO()):
    out = CA.generate_grounded_response("what is the punishment for robbery?", RET, matches=MATCHES, pilot_matches=[])
check(len(CALLS) == 2 and out == "Section 309 of the BNS defines robbery.", "Research: the same untraceable number still gets the second answer, as before")
depth_ctx.set_depth(None)

# the explain answer: one call, checked, with the law on hand
docs = {1: {"name": "chargesheet.pdf", "unit": "page", "units": 6, "unread": []}}
CH = [{"doc": 1, "loc": 1, "loc_to": 1, "text": "FINAL REPORT UNDER SECTION 193 OF THE BNSS.\nSections: 309(4) and 115(2) of the Bharatiya Nyaya Sanhita, 2023, read with section 3(5)."},
      {"doc": 1, "loc": 2, "loc_to": 2, "text": "The pillion rider snatched her gold chain weighing about 18 grams from her neck and pushed her, and she fell on the footpath."}]
MD = {"docs": docs, "chosen": CH[:1], "file_chosen": CH, "whole": True}
GOOD = ('BNS 309(4) is robbery: theft becomes robbery when the offender "voluntarily causes or attempts to cause" hurt or fear in committing it; the punishment is "rigorous imprisonment for a term which may extend to ten years". '
        'BNS 115(2): "voluntarily causes hurt" is punished with imprisonment up to one year. BNS 3(5) makes each person liable where a criminal act is done by several persons in furtherance of the common intention of all. '
        'The chargesheet states that the pillion rider snatched a gold chain [Doc 1, p. 2]. Section 103 of the BNS covers murder.')
_Msgs.replies = [GOOD]
CALLS.clear()
CA._MATTER.pins = ["BNS 309(4)", "BNS 115(2)", "BNS 3(5)"]
with contextlib.redirect_stdout(io.StringIO()) as buf:
    r = CA.answer_question("Now the person says: explain the sections in a clear manner", audience="lawyer", matter_docs=MD, matter_depth="explain", matter_pins=["BNS 309(4)", "BNS 115(2)", "BNS 3(5)"])
check(len(CALLS) == 1 and r["route"] == "explain" and r["depth"] == "explain" and r["state"] == "single_match" and r["matches"] == [], "an explain answer: ONE call, route and depth 'explain', no research-note matches")
check("Section 103" not in r["response_text"] and "ten years" in r["response_text"] and "[Doc 1, p. 2]" in r["response_text"], "the sentence naming section 103 (not on hand) was removed; the quotation and the document cite stayed")
check("Bottom line" not in r["response_text"] and "authorities" not in r, "no research-note dressing on an explain answer")
loh = r["law_on_hand"]
check([s["ref"] for s in loh["sections"]] == ["BNS 309(4)", "BNS 115(2)", "BNS 3(5)"] and all(s["on_hand"] for s in loh["sections"]) and [x["ref"] for x in loh["table"]] == ["BNS 309(4)", "BNS 115(2)"]
      and loh["no_row"] == ["BNS 3(5)"], "the answer carries the sections word for word and the Schedule table, built by code")
check(any("removed by a program" in n for n in r.get("matter_files_engine_notes") or []) and r["coverage"].startswith("Looked at: Doc 1"), "a note says a sentence was removed; the coverage line")
p = CALLS[0]["prompt"]
check("LAW ON HAND" in p and "(4) Whoever commits robbery" in p and "Schedule I row" in p and "Sections: 309(4)" in p and CALLS[0]["kw"].get("output_config") == {"effort": "low"}, "the prompt held the law on hand, the Schedule rows and the documents; low thinking")
check("explain_answer" not in json.dumps(r) and "EXPLAIN_ANSWER" in buf.getvalue(), "one log line, counts only")

# nothing on hand -> a Standard answer
os.environ.pop("ANSWER_EFFORT", None)
seen = {}
orig_inner = CA._answer_question_inner


def fake_inner(question, inline_domains=frozenset()):
    seen["depth"] = depth_ctx.depth()
    return {"state": "single_match", "matches": [], "response_text": "STANDARD ANSWER", "from_cache": False}


CA._answer_question_inner = fake_inner
CALLS.clear()
try:
    with contextlib.redirect_stdout(io.StringIO()):
        r2 = CA.answer_question("Now the person says: explain the sections", audience="lawyer", matter_docs=MD, matter_depth="explain", matter_pins=[])
    check(not CALLS and seen.get("depth") == "standard" and r2.get("depth") == "standard" and r2["response_text"] == "STANDARD ANSWER", "explain with nothing on hand: no call, a Standard answer instead")
    r3_calls = len(CALLS)
    with contextlib.redirect_stdout(io.StringIO()):
        r3 = CA.answer_question("Is he entitled to default bail?", audience="lawyer", matter_depth="standard", matter_pins=["BNS 309(4)"])
    check(seen.get("depth") == "standard" and r3["depth"] == "standard" and r3["response_text"] == "STANDARD ANSWER" and depth_ctx.depth() is None, "a Standard answer is tagged 'standard' and the size is cleared afterwards")
    with contextlib.redirect_stdout(io.StringIO()):
        r4 = CA.answer_question("Is he entitled to default bail?", audience="lawyer")
    check(seen.get("depth") is None and "depth" not in r4, "no size given: the engine behaves as before (no size, no tag)")
finally:
    CA._answer_question_inner = orig_inner
    answer_style.set_audience(None)

# ------------------------------------------------------------------ the download carries the law on hand and its table
import answer_export as AE  # noqa: E402
import answer_view as AVW  # noqa: E402
import law_on_hand as LH  # noqa: E402

_items = LH.items_for(["BNS 309(4)", "BNS 115(2)", "BNS 3(5)"])
_res = {"state": "single_match", "response_text": "Stub explanation.", "matches": [], "route": "explain", "depth": "explain", "law_on_hand": LH.view(_items), "audience": "lawyer",
        "matter_route": {"route": "law", "size": "explain", "label": "Quick answer", "escaped": False, "offers": {"go_deeper": True, "with_law": False, "documents_only": False, "explain_sections": []}}}
_view = AVW.build(_res)
check(_view and _view["law_on_hand"]["sections"][0]["ref"] == "BNS 309(4)" and _view["depth"] == "explain" and _view["matter_route"]["size"] == "explain" and _view["matter_route"]["offers"]["go_deeper"] is True,
      "answer_view: the law on hand, the size and the Go-deeper offer reach the page")
_doc = AE.build_document([{"question": "explain the sections", "view": _view, "answer_id": "RA-TEST01", "created_at": None, "audience": "lawyer"}], kind="answer")
_txt = AE.all_text(_doc)
check("Whoever commits robbery shall be punished" in _txt and "Magistrate of the first class" in _txt and "No First Schedule row for: BNS 3(5)" in _txt and AE.render_pdf(_doc)[:4] == b"%PDF" and len(AE.render_docx(_doc)) > 1000,
      "the PDF and Word download carry the sections word for word, the Schedule table and the 'no row' line")
_bad = dict(_res, law_on_hand={"sections": "x"})
check(AVW.build(_bad) is not None and AVW.build(_bad).get("law_on_hand") is None, "a malformed law-on-hand value is dropped, not shown")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PASS")
