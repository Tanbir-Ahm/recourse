"""
test_answer_shape.py -- ANSWER_SHAPE (answer_shape.py, chat_assistant hooks, answer_view / export / web checklist; owner's go 2026-11-09). Free: no network, no model.
Proves: the length tier is read from the person's words by a word list (set below, written BEFORE the first run); the asks of a message are its question and request sentences with a pure style instruction left out; the prompt of the lawyers' note gets the shape block
only for two or more asks or a length word, only with the switch on, only for the lawyers' voice, and the Hard rules block is untouched; the checklist marks each ask answered, answered by 'the material does not show it', or not found; a Bottom line is measured, never rewritten.
Run: python -X utf8 test_answer_shape.py
"""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for v in ("ANSWER_SHAPE", "RESPONSE_STYLE", "CASE_FILE", "CHAT_MODE"):
    os.environ.pop(v, None)

import answer_shape as S

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ------------------------------------------------------------ 1. tiers: a set written before the first run (message, expected tier)
TIERS = [
    ("what are the other sections my client can be charged with? And how can I counter them as his lawyer? Give me detailed explainations", "detailed"),
    ("Please explain in detail how default bail works.", "detailed"),
    ("Give a thorough analysis of section 35 BNSS.", "detailed"),
    ("Explain step by step how to file an anticipatory bail application.", "detailed"),
    ("I want a comprehensive note on the law of abetment.", "detailed"),
    ("Elaborate on the grounds for quashing under section 528.", "detailed"),
    ("Explain each ground on which bail can be refused.", "detailed"),
    ("Briefly, is arrest necessary for a three-year offence?", "brief"),
    ("In short, can the court cancel bail?", "brief"),
    ("Yes or no: is section 77 bailable?", "brief"),
    ("Give me a quick answer: how long can police custody last?", "brief"),
    ("Tl;dr of the Antil judgment please.", "brief"),
    ("Explain in detail but briefly how remand works.", "normal"),          # both kinds of word: normal
    ("Is bail possible in this case?", "normal"),
    ("What is the punishment for cheating?", "normal"),
    ("My client was arrested yesterday for theft. What should we do?", "normal"),
    ("What does section 480 say?", "normal"),
    ("Can the accused be arrested without a notice?", "normal"),
    ("The detail of the FIR is unclear to me; what sections apply?", "normal"),      # 'detail' alone is not a request for detail
    ("He was held for a long time without charge.", "normal"),
]
bad = [(m, e, S.tier(m)) for m, e in TIERS if S.tier(m) != e]
check(not bad, f"the length tier of {len(TIERS)} messages is read as expected ({bad})")

# ------------------------------------------------------------ 2. asks
Q2 = "what are the other sections my client can be charged with? And how can I counter them as his lawyer? Give me detailed explainations"
a = S.asks(Q2)
check(a == ["what are the other sections my client can be charged with?", "how can I counter them as his lawyer?"], f"the owner's follow-up gives two asks, 'detailed explanations' is a style word not an ask ({a})")
check(S.asks("My client was arrested for theft. He is in custody.") == [] and S.asks("Is bail possible?") == ["Is bail possible?"], "statements are not asks; a single question is one ask")
check(S.asks("Tell me about section 35 and also explain section 47 and the bail rules in detail please.") == ["Tell me about section 35 and also explain section 47 and the bail rules in detail please."], "one sentence is one ask")
check(len(S.asks(" ".join(f"What about point number {i} here?" for i in range(9)))) == S.MAX_ASKS, "at most five asks")
check(S.applies(Q2) and not S.applies("Is bail possible?") and S.applies("Explain in detail how bail works.") and not S.applies("My client was arrested."), "the block applies to two asks or a length word")

# ------------------------------------------------------------ 3. the block
os.environ["ANSWER_SHAPE"] = "on"
b = S.shape_block(Q2)
check("1. what are the other sections my client can be charged with?" in b and "2. how can I counter them as his lawyer?" in b and "Answer:" in b and "Main risk:" in b and "1,800 words" in b and "14 sections and 10 cases" in b, "the block lists the asks in order, asks for three short Bottom-line lines and lifts the length for 'detailed'")
check("never fill the gap" in b and "Hard rules" in b, "the block says what to do when the material cannot answer, and that the Hard rules still apply")
check("1,800" not in S.shape_block("Is bail possible? And what about the surety?") and "about 300 words" in S.shape_block("Briefly, is arrest necessary for a three-year offence?") and S.shape_block("Is bail possible?") == "", "no length change without a length word; a brief tier; nothing for a single plain question")

# ------------------------------------------------------------ 4. the prompt
import chat_assistant as CA
import answer_style

sent = {}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="**Bottom line**\n\nShort.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())


def run(question, style="v3", audience="lawyer", shape="on"):
    os.environ["RESPONSE_STYLE"] = style
    os.environ["ANSWER_SHAPE"] = shape
    answer_style.set_audience(audience)
    sent.clear()
    try:
        CA.generate_grounded_response(question, "[BNS Section 77]\nText.", matches=[])
    finally:
        answer_style.set_audience(None)
    return sent.get("prompt", "")


p = run(Q2)
check("## Shape for THIS question" in p and "1. what are the other sections my client can be charged with?" in p and p.index("## Shape for THIS question") < p.index("Text."), "lawyer note, switch on, two asks: the prompt carries the block before the material")
check("## Hard rules (never break)" in p and "Use ONLY the legal information given below" in p, "...and the Hard rules block is still there, unchanged")
check("## Shape for THIS question" not in run(Q2, shape="off"), "switch off: no block")
check("## Shape for THIS question" not in run(Q2, audience="layman"), "the layman's voice: no block")
check("## Shape for THIS question" not in run("Is bail possible in this case?"), "a single plain question: no block")
folded = "Earlier in this same conversation (the person's earlier messages only; your earlier answers are not repeated here):\n- The person asked: Is bail possible?\n\nNow the person says: " + Q2
p2 = run(folded)
seg = p2.split("## Shape for THIS question")[1].split("The person's question:")[0] if "## Shape for THIS question" in p2 else ""
check(seg and "Is bail possible?" not in seg and "1. what are the other sections" in seg, "a folded follow-up: the asks are the CURRENT message's, not the earlier ones")
os.environ.pop("RESPONSE_STYLE", None)

# ------------------------------------------------------------ 5. the checklist
note_ok = ("**Bottom line**\n\nAnswer: x.\n\n**1. Other sections he may be charged with**\n\nBNS 77 applies if the footage shows a private act and the facts bring section 45 in.\n\n"
           "**2. How to counter them**\n\nThe material does not show the provisions on abetment, so no counter can be stated.\n\n**Application to the facts**\n\nx\n\n**Gaps and checks**\n\ny")
cl = S.checklist(Q2, note_ok)
check(cl and [i["status"] for i in cl["items"]] == ["answered", "material_lacks"] and cl["answered"] == 1 and cl["total"] == 2, f"an answered ask and an ask the note says the material cannot answer ({cl and [i['status'] for i in cl['items']]})")
note_skip = "**Bottom line**\n\nAnswer: x.\n\n**1. Other sections he may be charged with**\n\nBNS 77 and BNS 45 apply in these ways in this case.\n\n**Gaps and checks**\n\ny"
cl = S.checklist(Q2, note_skip)
check(cl and [i["status"] for i in cl["items"]] == ["answered", "not_found"], "an ask the note never takes up is 'not found'")
old_note = ("**Bottom line**\n\nx\n\n**1. Section 77 of the BNS governs recording and sharing such images**\n\ntext\n\n**2. Linkage to the prime accused's offence may be pressed separately**\n\ntext\n\n"
            "**3. The charge must specify the offence and the exact section**\n\ntext\n\n**4. Arrest and pre-arrest safeguards continue to apply to added charges**\n\ntext\n\n**Gaps and checks**\n\ny")
cl = S.checklist(Q2, old_note)
check(cl and cl["items"][1]["status"] == "not_found", f"the 9 Nov note (numbered issues, nothing about countering): the second ask is not found ({cl and [i['status'] for i in cl['items']]})")
check(S.checklist("Is bail possible?", note_ok) is None and S.checklist("", "") is None and S.checklist(None, None) is None, "one ask or nothing: no checklist; never raises")

# ------------------------------------------------------------ 6. the bottom line is measured, not rewritten
long_bl = "**Bottom line**\n\n" + ("Whether the client's conduct amounts to an offence turns on whether recording or sharing the clip meets the specific tests in several provisions of two different statutes " * 3) + "\n\n**Facts assumed**\n\nx"
w, l = S.bottom_line_stats(long_bl)
check(w > 60 and l > 45, f"a long Bottom line is measured ({w}, {l})")
check(S.bottom_line_stats("no heading here") == (0, 0) and S.bottom_line_stats(None) == (0, 0), "no Bottom line: (0, 0)")
res = {"audience": "lawyer", "response_text": note_ok}
res2 = CA._attach_ask_check(dict(res), Q2)
check(res2["ask_check"]["total"] == 2 and res2["response_text"] == note_ok, "the engine attaches the checklist and leaves the text alone")
os.environ["ANSWER_SHAPE"] = "off"
check("ask_check" not in CA._attach_ask_check(dict(res), Q2), "switch off: nothing attached")

# the page's view
import answer_view as AV
os.environ["ANSWER_SHAPE"] = "on"
v = AV.build({"state": "single_match", "audience": "lawyer", "response_text": note_ok, "matches": [], "ask_check": cl and S.checklist(Q2, note_ok)})
check(v["ask_check"]["total"] == 2 and v["ask_check"]["items"][1]["label"] == "the material does not show it" and AV.build({"state": "single_match", "response_text": "x", "matches": []})["ask_check"] is None, "the view carries the checklist with plain labels, None without one")
import answer_export as AE
blocks = AE._answer_blocks(v, True)
txt = " ".join(" ".join(r.get("text", "") for r in b.get("runs", [])) + " " + str(b.get("text", "")) for b in blocks)
check("What you asked, and where it is answered" in txt and "the material does not show it" in txt, "the Word and PDF file carry the checklist")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
