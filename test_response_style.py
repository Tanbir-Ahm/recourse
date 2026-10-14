"""test_response_style.py -- RESPONSE_STYLE=v2 (the livelier answer prompt). Offline and free. Run: python -X utf8 test_response_style.py
Gates: the default is v1 (production unchanged); v2 keeps every hard rule and the whole 'what to include' section word for word; only the voice and shape block differs; both templates format cleanly;
the generation call really uses the selected template."""
import os
import sys
import types

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


V1, V2 = CA.RESPONSE_GENERATION_PROMPT, CA.RESPONSE_GENERATION_PROMPT_V2
os.environ.pop("RESPONSE_STYLE", None)
check(CA.response_style() == "v1" and CA._response_prompt_template() is V1, "the default is v1: production is unchanged until RESPONSE_STYLE=v2 is set")
for val, want in (("v2", "v2"), ('"v2"', "v2"), (" 'V2' ", "v2"), ("banana", "v1"), ("", "v1")):
    os.environ["RESPONSE_STYLE"] = val
    check(CA.response_style() == want, f"RESPONSE_STYLE={val!r} is read as {want}")
os.environ["RESPONSE_STYLE"] = "v2"
check(CA._response_prompt_template() is V2, "v2 selects the v2 template")

head1, head2 = V1[:V1.index("## Shape and length")], V2[:V2.index("## Voice and shape")]
tail1, tail2 = V1[V1.index("{conflict_instruction}"):], V2[V2.index("{conflict_instruction}"):]
check(head1 == head2 and tail1 == tail2, "everything before the shape block (hard rules, what to include or leave out, REGISTER lines) and everything after it is identical in v1 and v2")
check("## Hard rules (never break)" in V2 and "A line that starts REGISTER FACT is not optional" in V2 and "Cite AT MOST 4 distinct section numbers" in V2, "v2 still carries the hard rules, the REGISTER rule and the cap of four sections")
check("Keep the whole answer under about 300 words" not in V2 and "250-400 words" in V2, "v2 replaces the 300-word cap with 250-400 words")
check("FIRST sentence answers the question" in V2 and "Never write a report citation" in V2 and "ONE next step that is specific" in V2, "v2 asks for a direct first sentence, an in-sentence citation without invented report numbers, and one specific next step")
for name, tpl in (("v1", V1), ("v2", V2)):
    try:
        out = tpl.format(question="Q?", retrieved_text="TEXT", conflict_instruction="", pilot_context="")
        check("Q?" in out and "TEXT" in out, f"{name} fills in cleanly")
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name} fills in cleanly ({exc})")

sent = {}
class _Msgs:
    def create(self, **kw):
        sent["prompt"] = kw["messages"][0]["content"]
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Not automatically, but nine years is a long time.")])
CA.client = types.SimpleNamespace(messages=_Msgs())
CA.generate_grounded_response("My trial has gone on 9 years", "[BNSS Section 346]\nTrial text.", matches=[])
check("## Voice and shape" in sent["prompt"], "generate_grounded_response sends the v2 prompt when RESPONSE_STYLE=v2")
os.environ["RESPONSE_STYLE"] = "v1"
CA.generate_grounded_response("My trial has gone on 9 years", "[BNSS Section 346]\nTrial text.", matches=[])
check("## Shape and length" in sent["prompt"] and "## Voice and shape" not in sent["prompt"], "and the v1 prompt when it is not")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
