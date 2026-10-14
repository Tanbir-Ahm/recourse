"""test_answer_truncation.py -- a model reply that runs out of tokens (staging 2026-10-14: the lawyers' note stopped in mid-sentence). Offline and free. Run: python -X utf8 test_answer_truncation.py
Gates: the research note gets a bigger budget than every other style; a reply cut off at the limit is asked for again with a bigger budget; one that is cut off twice is closed at the last complete sentence with a plain note;
a normal reply is untouched and costs one call."""
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


CALLS = []
PLAN = []


class _Msgs:
    def create(self, **kw):
        CALLS.append(kw["max_tokens"])
        text, stop = PLAN.pop(0) if PLAN else ("An answer.", "end_turn")
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], stop_reason=stop)


CA.client = types.SimpleNamespace(messages=_Msgs())


def run(style, plan):
    os.environ["RESPONSE_STYLE"] = style
    CALLS.clear()
    PLAN[:] = plan
    return CA._create_answer("m", "prompt")


check(run("v1", [("Fine.", "end_turn")]) == "Fine." and CALLS == [4000], "v1: a normal reply costs one call with the old 4000 budget")
check(run("v2", [("Fine.", "end_turn")]) == "Fine." and CALLS == [4000], "v2 keeps 4000")
check(run("v3", [("Fine.", "end_turn")]) == "Fine." and CALLS == [8000], "v3 (layman) gets 8000 (a 4000 cut-off was paid for twice on staging)")
os.environ["RESPONSE_STYLE"] = "v3"
import answer_style as AS
AS.set_audience("lawyer")
check(run("v3", [("Fine.", "end_turn")]) == "Fine." and CALLS == [12000], "v3 with the lawyer audience: the research note gets 12000")
AS.set_audience(None)
check(run("v3-lawyer", [("Fine.", "end_turn")]) == "Fine." and CALLS == [12000], "v3-lawyer: 12000")
t = run("v1", [("Half a sent", "max_tokens"), ("A complete answer.", "end_turn")])
check(t == "A complete answer." and CALLS == [4000, 8000], f"a reply cut off at the limit is asked for again with double the budget ({CALLS})")
t = run("v3-lawyer", [("Half a sent", "max_tokens"), ("A complete note.", "end_turn")])
check(t == "A complete note." and CALLS == [12000, 16000], f"the second budget is capped at 16000 ({CALLS})")
t = run("v1", [("First part is whole. Second part is whole too. Third part is cut in the mi", "max_tokens"), ("First part is whole. Second part is whole too. Third part is cut in the mi", "max_tokens")])
check(t.startswith("First part is whole. Second part is whole too.") and "cut in the mi" not in t and t.endswith(CA._TRUNCATED_NOTE) and CALLS == [4000, 8000], f"cut off twice: closed at the last complete sentence with a plain note ({t!r})")
check(CA._close_truncated("one two three four").endswith(CA._TRUNCATED_NOTE) and CA._close_truncated("one two three four").startswith("one two three"), "text with no sentence end is cut at a word")
check(CA._close_truncated("") .endswith(CA._TRUNCATED_NOTE), "empty text does not fail")

# the whole generation path uses it
CALLS.clear()
PLAN[:] = [("Delay alone does not end a trial. Under Section 346 of the BNSS the c", "max_tokens"), ("Delay alone does not end a trial. Under Section 346 of the BNSS the court may adjourn only for recorded reasons.", "end_turn")]
os.environ["RESPONSE_STYLE"] = "v3-lawyer"
out = CA.generate_grounded_response("Q?", "[BNSS Section 346]\nTrial text.", matches=[])
check(out and out.endswith("recorded reasons.") and CALLS == [12000, 16000], f"generate_grounded_response returns the complete second reply ({out!r}, {CALLS})")
os.environ.pop("RESPONSE_STYLE", None)
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
