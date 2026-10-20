"""
test_copy_button.py -- the Copy button under every answer on the page (recourse_app._render_copy_button, _plain_for_copy; owner's instruction 2026-10-20: "add a copy button to every response, like in chatgpt or claude").
Offline and free: the answer is a stub; the button is a component iframe, so the test replaces streamlit.components.v1.html with a recorder and reads the HTML the page would send. (The click itself was checked in a real
Chromium on 2026-10-20: the label turned to "Copied" and the clipboard held the answer text without markdown marks; that needs a browser and is not repeated here.)
Run: python -X utf8 test_copy_button.py
"""
import ast
import json
import os
import re
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("RESPONSE_STYLE", "ACT_SHELF", "SECTION_XREF"):
    os.environ.pop(_v, None)
from streamlit.testing.v1 import AppTest
import streamlit.components.v1 as components
import chat_assistant as CA

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---------------------------------------------------------------- _plain_for_copy, taken out of the app's source (importing the module would run the page)
src = open(APP, encoding="utf-8").read()
tree = ast.parse(src)
ns = {"_re_lbl": re}
for node in tree.body:
    if (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_COPY_EMPH" for t in node.targets)) or (isinstance(node, ast.FunctionDef) and node.name == "_plain_for_copy"):
        exec(compile(ast.Module([node], []), APP, "exec"), ns)
plain = ns["_plain_for_copy"]
check(plain("**What does the law say?**\n\nText.") == "What does the law say?\n\nText.", "a bold heading loses its asterisks, the line breaks stay")
check(plain("In *Arnesh Kumar v. State of Bihar* (2014), the Court said X.") == "In Arnesh Kumar v. State of Bihar (2014), the Court said X.", "an italic case name loses its asterisks")
check(plain("## How this cuts\n### Sub") == "How this cuts\nSub", "'#' heading marks are taken off")
check(plain("*For you:*\n- point one\n- point two\n\n1. Ask your lawyer.") == "For you:\n- point one\n- point two\n\n1. Ask your lawyer.", "bullets and numbered steps are kept exactly")
check(plain("The fine is 2 * 3 = 6 and 5*4 = 20.") == "The fine is 2 * 3 = 6 and 5*4 = 20.", "a multiplication sign is not taken for emphasis")
check(plain("**Bold** and *italic* and **another bold**") == "Bold and italic and another bold", "several pairs on a line")
check(plain("") == "" and plain(None) == "" and plain("   ") == "", "empty, None, blanks: empty text, no error")
check(plain("Section 17A(1)(b) of the Act; see *ibid.*") == "Section 17A(1)(b) of the Act; see ibid.", "section references are untouched")

# ---------------------------------------------------------------- the page: the recorder
CALLS = []
_real_html = components.html


def recorder(html, *a, **k):
    CALLS.append({"html": html, "height": k.get("height")})
    return None


components.html = recorder

REPLY = ("**What does the law say about delay?**\n\nIn *Arnesh Kumar v. State of Bihar* (2014), the Supreme Court said an arrest is not automatic.\n\n**What to keep in mind**\n\n"
         "- Delay alone does not end a trial.\n- Courts look at who caused the delay.\n\n**What you can do now**\n\n1. Ask your lawyer to object on record.")
STUB = {"v": None}
CA.answer_question = lambda question, inline_domains=frozenset(), audience=None, channel=None: STUB["v"]


def page(result):
    STUB["v"] = result
    del CALLS[:]
    at = AppTest.from_file(APP, default_timeout=90).run()
    del CALLS[:]
    at.text_area(key="text").set_value("What is the effect of delay in a criminal trial?").run()
    [b for b in at.button if "Check my situation" in b.label][0].click().run()
    return at, [c for c in CALLS if 'id="b"' in c["html"]]


def payload(html):
    m = re.search(r"var TEXT = (.*?);\n", html)
    return json.loads(m.group(1).replace("<\\/", "</"))


at, btn = page({"state": "single_match", "response_text": REPLY, "matches": [], "situation_detected": False, "audience": "layman"})
check(not at.exception and len(btn) == 1, f"page: one Copy button under the answer (exception={at.exception}, buttons={len(btn)})")
h = btn[0]["html"] if btn else ""
check(payload(h) == "What does the law say about delay?\n\nIn Arnesh Kumar v. State of Bihar (2014), the Supreme Court said an arrest is not automatic.\n\nWhat to keep in mind\n\n- Delay alone does not end a trial.\n- Courts look at who caused the delay.\n\nWhat you can do now\n\n1. Ask your lawyer to object on record.",
      "the button copies the answer as plain text: no markdown marks, same words, same breaks")
check("navigator.clipboard.writeText(TEXT)" in h and 'document.execCommand("copy")' in h and "function fallback()" in h, "it tries the clipboard API first and falls back to a hidden textarea and execCommand")
check(">Copy</span>" in h and '"Copied"' in h and "setTimeout" in h and "aria-label=\"Copy this response to the clipboard\"" in h and 'role="status"' in h, "the label is 'Copy', turns to 'Copied' for two seconds, has an accessible name and a status role")
check(btn and btn[0]["height"] == 40, "the iframe is 40 pixels high")
check("<script" in h and h.count("</script>") == 1, "one script, closed once")

tricky = "Section 17: </script><b>x</b> & \"quotes\" and a line separator."
at, btn = page({"state": "single_match", "response_text": tricky, "matches": [], "situation_detected": False})
h = btn[0]["html"] if btn else ""
check(len(btn) == 1 and h.count("</script>") == 1 and payload(h) == tricky, "text containing '</script>', quotes, '&' and a line separator cannot break the script and comes back exactly")

at, btn = page({"state": "conflicting_matches", "response_text": REPLY, "matches": [], "situation_detected": False})
check(not at.exception and len(btn) == 1, "a 'conflicting_matches' answer has the button too")

at, btn = page({"state": "single_match", "response_text": "", "matches": [{"type": "statute", "act": "BNSS", "section_number": "3", "text": "3. Definitions of the words used.", "source": "semantic", "all_variants": {}}], "situation_detected": False})
check(not at.exception and len(btn) == 1 and payload(btn[0]["html"]) == "Here is what the law says on this:\n\n3. Definitions of the words used.", "an answer with no text (the fallback 'Here is what the law says on this') has the button, copying that text")

for st_ in ("no_match", "unrelated", "adjacent_uncovered", "covered_elsewhere_in_tool", "classifier_unavailable", "budget_paused"):
    at, btn = page({"state": st_, "matches": [], "situation_detected": False})
    check(not at.exception and not btn, f"state {st_!r} (a fixed message, not an answer): no Copy button")

# a notice and the section box are separate from the answer text
at, btn = page({"state": "single_match", "response_text": REPLY, "matches": [], "situation_detected": False,
                "act_notice": {"kind": "answer", "acts": [], "text": "NOTICE TEXT", "html": "NOTICE TEXT"},
                "section_note": [{"act": "X", "section": "9", "kind": "official", "lead": "LEAD SENTENCE", "texts": ["OFFICIAL SECTION TEXT"], "cut": False, "loaded_on": None, "source_url": None}]})
h = btn[0]["html"] if btn else ""
check(len(btn) == 1 and "NOTICE TEXT" not in h and "OFFICIAL SECTION TEXT" not in h and "LEAD SENTENCE" not in h, "the copied text is the answer only, not the notice or the official-text box")
vals = [m.value for m in at.markdown]
ia = [i for i, v in enumerate(vals) if "Delay alone does not end a trial" in v]
inn = [i for i, v in enumerate(vals) if "NOTICE TEXT" in v]
check(ia and inn and inn[0] > ia[0], "the button sits between the answer and what follows it (the notice still comes under the answer)")

# a failure inside the button never breaks the page
def broken(html, *a, **k):
    if 'id="b"' in html:
        raise RuntimeError("component failed")


components.html = broken
STUB["v"] = {"state": "single_match", "response_text": REPLY, "matches": [], "situation_detected": False}
at = AppTest.from_file(APP, default_timeout=90).run()
at.text_area(key="text").set_value("What is the effect of delay in a criminal trial?").run()
[b for b in at.button if "Check my situation" in b.label][0].click().run()
check(not at.exception and any("Delay alone does not end a trial" in m.value for m in at.markdown), "if the component call raises, the page still shows the answer and no error")
components.html = _real_html

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
