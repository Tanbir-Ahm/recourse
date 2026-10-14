"""test_withheld_log.py -- when a hard check still fails after the second try the answer is withheld AND the log says which check and on what (RECHECK ... detail=, ANSWER_WITHHELD ...).
Offline and free. Run: python -X utf8 test_withheld_log.py"""
import contextlib
import io
import sys
import types

import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


class _Msgs:
    def create(self, **kw):
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Cheating is punished under Section 318(4) and arrest powers sit in Section 35.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
matches = [{"type": "statute", "act": "BNS", "section_number": "318", "text": "318. Cheating ...", "case_name": None},
           {"type": "statute", "act": "BNSS", "section_number": "35", "text": "35. When police may arrest without warrant ...", "case_name": None}]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    out = CA.generate_grounded_response("Can police arrest me for cheating?", "[BNS 318]\ncheating text\n[BNSS 35]\narrest text", matches=matches)
log = buf.getvalue()
check(out is None, "an answer that still names no Act after the second try is withheld (None)")
check("RECHECK reasons=missing_act detail=" in log and "ANSWER_WITHHELD after the second try: reasons=missing_act detail=" in log, "the log carries both lines with the reason")
check('"missing_act": ["318", "35"]' in log or '"missing_act": ["35", "318"]' in log, f"and the section numbers whose Act was never named ({log.strip()[:300]!r})")
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
