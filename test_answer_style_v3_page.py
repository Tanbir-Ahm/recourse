"""test_answer_style_v3_page.py -- the page side of answer style v3: the Layman / Lawyer switch (only under RESPONSE_STYLE=v3), the audience reaching answer_question, headings kept as headings,
the lawyers' authorities tables, and no change to a v1 answer. Offline and free (the model is replaced by a stub). Run: python -X utf8 test_answer_style_v3_page.py"""
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ.pop("RESPONSE_STYLE", None)
from streamlit.testing.v1 import AppTest
import chat_assistant as CA

FAILURES = []
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


SEEN = {}
TEXT = ("Not automatically, but nine years is a long time.\n\n**Can the case be closed because of delay?**\n\nIn *Arnesh Kumar v. State of Bihar* (2014) the Supreme Court directed X.\n\n"
        "**How this cuts for and against you**\n*For you:*\n- the delay comes from the prosecution\n\n**What you can do right now**\n\n1. Ask your lawyer to object on record.")
LAWYER_TEXT = ("**Bottom line**\n\nDelay alone does not end a trial.\n\n**1. A fixed period of delay does not by itself terminate a criminal trial under the BNSS**\nSection 346 of the BNSS ... *Arnesh Kumar v. State of Bihar* (2014).")


def stub(question, inline_domains=frozenset(), audience=None, channel=None):
    SEEN["audience"], SEEN["channel"] = audience, channel
    lawyer = audience == "lawyer"
    res = {"state": "single_match", "response_text": LAWYER_TEXT if lawyer else TEXT, "matches": [], "situation_detected": False}
    if os.environ.get("RESPONSE_STYLE") == "v3":
        res["audience"] = "lawyer" if lawyer else "layman"
        if lawyer:
            res["authorities"] = {"library": [{"case": "Arnesh Kumar v. State of Bihar", "year": 2014, "citation": "(2014) 8 SCC 273", "paragraphs": ["11"], "tier": "Reviewed library",
                                               "status": "quiet note", "status_source": "card_quiet", "link": "https://l/a"}], "wider": [], "has_bench": False}
    return res


CA.answer_question = stub


def md_values(at):
    return [m.value for m in at.markdown]


# ---- default (v1): no switch; the same text keeps v1 treatment ----
at = AppTest.from_file(APP, default_timeout=90).run()
check(not at.exception and not [r for r in at.radio if getattr(r, "key", "") == "audience_choice"], "v1: the page has no Layman / Lawyer switch")
at.text_area(key="text").set_value("My trial has gone on 9 years").run()
[b for b in at.button if "Check my situation" in b.label][0].click().run()
check(not at.exception and SEEN.get("audience") is None, f"v1: answer_question is called without an audience ({SEEN.get('audience')!r}, exception={at.exception})")
vals = md_values(at)
check(any("Can the case be closed because of delay?" in v and "**Can the case" not in v for v in vals), "v1: a question-style bold line is NOT kept as a heading (today's behaviour is unchanged)")

# ---- v3: the switch, the audience, headings ----
os.environ["RESPONSE_STYLE"] = "v3"
at = AppTest.from_file(APP, default_timeout=90).run()
radios = [r for r in at.radio if getattr(r, "key", "") == "audience_choice"]
check(not at.exception and len(radios) == 1 and list(radios[0].options) == ["Layman", "Lawyer"] and radios[0].value == "Layman", "v3: the page shows the Layman / Lawyer switch, Layman first")
at.text_area(key="text").set_value("My trial has gone on 9 years").run()
[b for b in at.button if "Check my situation" in b.label][0].click().run()
check(not at.exception and SEEN.get("audience") == "layman", f"v3 layman: audience 'layman' reaches answer_question ({SEEN.get('audience')!r}, exception={at.exception})")
vals = md_values(at)
check(any("**Can the case be closed because of delay?**" in v for v in vals) and any("**How this cuts for and against you**\n\n" in v for v in vals), "v3 layman: headings stay bold, a heading followed by one newline gets a blank line")
check(any("In *Arnesh Kumar v. State of Bihar* (2014)" in v for v in vals), "v3: case names stay in italics")
check(not any("Authorities (reviewed library)" in v for v in vals), "v3 layman: no table of authorities")

at.radio(key="audience_choice").set_value("Lawyer").run()
at.text_area(key="text").set_value("My trial has gone on 9 years").run()
[b for b in at.button if "Check my situation" in b.label][0].click().run()
check(not at.exception and SEEN.get("audience") == "lawyer", f"v3 lawyer: audience 'lawyer' reaches answer_question ({SEEN.get('audience')!r}, exception={at.exception})")
vals = md_values(at)
check(any("Authorities (reviewed library)" in v for v in vals), "v3 lawyer: the 'Authorities (reviewed library)' heading is shown")
check(any("| Case | Citation | Paragraph | Where it stands on our lists | Link |" in v and "(2014) 8 SCC 273" in v for v in vals), "v3 lawyer: the table of authorities is shown with the held citation")
check(any("**1. A fixed period of delay does not by itself terminate a criminal trial under the BNSS**\n\n" in v for v in vals), "v3 lawyer: a long proposition heading (up to 90 characters) stays a heading, with a blank line after it")
check(not any("Judgments this answer relies on" in v for v in vals), "v3 lawyer: the plain link list is replaced by the table")

os.environ.pop("RESPONSE_STYLE", None)
print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
