"""test_answer_style_v3.py -- answer style v3: 'The Adviser' (laypeople) and 'The Research Note' (lawyers), the Layman/Lawyer switch, the table of authorities, the WhatsApp version.
Offline and free (no model, no network). Run: python -X utf8 test_answer_style_v3.py"""
import os
import sys
import types

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.pop("RESPONSE_STYLE", None)
import answer_style as AS
import authorities_table as AT
import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ---- answer_style ----
check(AS.style() == "v1" and not AS.is_v3() and AS.effective_audience() == "layman" and AS.uses_cache(), "default: v1, not v3, layman, the approved-answer cache is used")
for val, want in (("v3", "v3"), ('"v3"', "v3"), (" 'V3-Lawyer' ", "v3-lawyer"), ("v4", "v1"), ("", "v1"), ("v2", "v2")):
    os.environ["RESPONSE_STYLE"] = val
    check(AS.style() == want, f"RESPONSE_STYLE={val!r} is read as {want}")
os.environ["RESPONSE_STYLE"] = "v3"
AS.set_audience("lawyer")
check(AS.effective_audience() == "lawyer" and AS.template_key() == "v3-lawyer" and not AS.uses_cache(), "under v3 the page's audience 'lawyer' selects the research note, and the cache is bypassed")
AS.set_audience("Advocate")
check(AS.effective_audience() == "lawyer", "'advocate' is read as lawyer")
AS.set_audience("banana")
check(AS.effective_audience() == "layman" and AS.template_key() == "v3", "anything else is layman")
AS.set_audience(None)
os.environ["RESPONSE_STYLE"] = "v3-lawyer"
check(AS.effective_audience() == "lawyer" and AS.template_key() == "v3-lawyer", "v3-lawyer gives the research note to everybody")
os.environ["RESPONSE_STYLE"] = "v2"
AS.set_audience("lawyer")
check(AS.effective_audience() == "layman" and AS.template_key() == "v2", "under v1 and v2 the audience has no effect")
AS.set_audience(None)
os.environ["RESPONSE_STYLE"] = "v1"

# ---- templates ----
V1, V2, V3, V3L = CA.RESPONSE_GENERATION_PROMPT, CA.RESPONSE_GENERATION_PROMPT_V2, CA.RESPONSE_GENERATION_PROMPT_V3, CA.RESPONSE_GENERATION_PROMPT_V3_LAWYER


def block(t, start, end):
    return t[t.index(start):t.index(end)]


hard = block(V1, "## Hard rules (never break)", "## What to include")
check(all(hard in t for t in (V2, V3, V3L)), "the Hard rules block is word for word the same in v1, v2, v3 and the lawyer note")
inc = block(V1, "## What to include", "## Shape and length")
check(inc in V3 and inc in V2, "the layman 'what to include / leave out' section (cap of 4 sections, REGISTER lines) is identical in v3")
for must in ("A line that starts REGISTER FACT is not optional", "REGISTER NOTE (not yet confirmed)", "ONE short plain clause"):
    check(must in V3 and must in V3L or must.startswith("ONE short") and "ONE short clause" in V3L, f"register / currency wording kept in both v3 templates: {must[:40]}")
check(V3.startswith(V1[:V1.index("## Hard rules")]), "the layman v3 keeps the v1 opening (warm guide for a layperson)")
check(V3L.startswith("You are a careful legal research assistant") and "layperson" not in V3L.split("## Hard rules")[0], "the lawyer note has its own opening, no layperson")
tail = V1[V1.index("{conflict_instruction}"):]
check(V3.endswith(tail) and V3L.endswith(tail), "both v3 templates end with the same question / material / conflict slots as v1")
check("Shape and length" not in V3 and "Shape and length" not in V3L and "Right now**" not in V3, "the v1 shape block (300 words, 'Right now' opening) is gone from v3")
# layman spec A1-A6
for must in ("The first sentence answers the question itself", "ONE short sentence using their facts", "**How this cuts for and against you**", "*For you:*", "*Against you:*", "What I can't tell from here:",
             "**What you can do right now**", "**What you can do now**", "Put nothing after the steps", "at most 45 characters", "ONLY bold text", "italics", "about 250 words", "about 350 words", "about 400 words",
             "Never go over 450 words", "Never talk down", "never \"you must\"", "No reassurance", "Never write a report citation", "Never say that a case \"is good law\""):
    check(must in V3, f"layman v3 carries: {must}")
# lawyer spec B1-B5
for must in ("**Bottom line**", "ONLY summary", "**Facts assumed**", "proposition or a question", "**Application to the facts**", "For the client | Against the client", "**Grounds that can be urged**",
             "**Gaps and checks**", "exactly **Bottom line**, with no title or headline", "never stop before it", "Do NOT write a table of authorities", "at most 90 characters", "35 words or fewer", "\"held\", \"observed\", \"directed\", \"reiterated\"", "\"decisive\"", "capitalised NOT",
             "40 words", "never in the Bottom line", "about 500-900 words", "never \"you should\"", "up to 8 distinct section numbers", "Never say that a case \"is good law\""):
    check(must in V3L, f"lawyer note carries: {must}")
for name, t in (("v3", V3), ("v3-lawyer", V3L)):
    out = t.format(question="Q?", retrieved_text="TEXT", conflict_instruction="", pilot_context="")
    check("Q?" in out and "TEXT" in out and "{" not in out, f"{name} fills in cleanly")

# ---- the template is chosen per call, and the audience does not leak between calls ----
sent = {}
class _Msgs:
    def create(self, **kw):
        sent["prompt"] = kw["messages"][0]["content"]
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Not automatically.")])
CA.client = types.SimpleNamespace(messages=_Msgs())
os.environ["RESPONSE_STYLE"] = "v3"
AS.set_audience("layman")
CA.generate_grounded_response("Q about delay", "[BNSS Section 346]\nTrial text.", matches=[])
check("## Voice and shape (the Adviser)" in sent["prompt"] and "WhatsApp" not in sent["prompt"], "generation uses the Adviser template for a layman (no WhatsApp note on the web)")
AS.set_channel("whatsapp")
CA.generate_grounded_response("Q about delay", "[BNSS Section 346]\nTrial text.", matches=[])
check("1,800 characters" in sent["prompt"], "the WhatsApp note (about 1,800 characters, no table) is added for the layman style on WhatsApp")
AS.set_channel(None)
AS.set_audience("lawyer")
CA.generate_grounded_response("Q about delay", "[BNSS Section 346]\nTrial text.", matches=[])
check("## Voice and shape (the Research Note)" in sent["prompt"] and "1,800 characters" not in sent["prompt"], "generation uses the Research Note for a lawyer")
AS.set_audience(None)
os.environ["RESPONSE_STYLE"] = "v1"
CA.generate_grounded_response("Q about delay", "[BNSS Section 346]\nTrial text.", matches=[])
check("## Shape and length" in sent["prompt"], "and v1 when the style is not v3")

# ---- answer_question: audience and authorities, and nothing left over ----
MATCHES = [
    {"type": "judgment", "case_name": "Arnesh Kumar v. State of Bihar", "citation": "(2014) 8 SCC 273", "paragraph_number": "11_2", "text": "x", "source_url": "https://example/arnesh.pdf", "year": 2014},
    {"type": "judgment", "case_name": "Mohan Lal v. State of Punjab", "citation": "(2018) 17 SCC 627", "paragraph_number": "7", "text": "y", "year": 2018},
    {"type": "judgment", "case_name": "Unmentioned v. State", "citation": "(2001) 1 SCC 1", "paragraph_number": "1", "text": "z"},
    {"type": "statute", "act": "BNSS", "section_number": "346", "text": "s"},
]
TEXT = "Under Section 346 of the BNSS the court may adjourn only for recorded reasons. In *Arnesh Kumar v. State of Bihar* (2014) the Supreme Court directed X. In *Mohan Lal v. State of Punjab* (2018) it said Y."
CA._answer_question_core = lambda q, inline_domains=frozenset(): {"state": "single_match", "response_text": TEXT, "matches": list(MATCHES)}
os.environ["RESPONSE_STYLE"] = "v1"
r = CA.answer_question("q")
check("audience" not in r and "authorities" not in r, "under v1 the result carries no audience and no authorities table")
os.environ["RESPONSE_STYLE"] = "v3"
r = CA.answer_question("q", audience="layman")
check(r.get("audience") == "layman" and "authorities" not in r, "v3 layman: result says layman, no authorities table")
r = CA.answer_question("q", audience="lawyer")
check(r.get("audience") == "lawyer" and r.get("authorities"), "v3 lawyer: result says lawyer and carries the authorities table")
names = [x["case"] for x in r["authorities"]["library"]]
check(names == ["Arnesh Kumar v. State of Bihar", "Mohan Lal v. State of Punjab"], f"the table lists only the library cases the answer names ({names})")
mohan = [x for x in r["authorities"]["library"] if x["case"].startswith("Mohan")][0]
arn = [x for x in r["authorities"]["library"] if x["case"].startswith("Arnesh")][0]
check(mohan["status_source"] == "register" and "overruled" in (mohan["status"] or "").lower(), "Mohan Lal's row carries the register line")
check(arn["citation"] == "(2014) 8 SCC 273" and arn["paragraphs"] == ["11"] and arn["link"] == "https://example/arnesh.pdf" and arn["tier"] == AT.TIER_LIBRARY, "Arnesh Kumar's row: citation, paragraph, link and tier come from the data")
check(AS.requested_audience() == "layman" and AS.get_channel() is None, "the audience and channel are reset after the call")
check(CA.answer_question("q").get("audience") == "layman", "a call with no audience under v3 is a layman call")
os.environ["RESPONSE_STYLE"] = "v3-lawyer"
check(CA.answer_question("q").get("audience") == "lawyer", "v3-lawyer: everybody gets the note")
os.environ["RESPONSE_STYLE"] = "v1"

# ---- the cache: read and written only under v1 ----
import answer_cache
calls = {"get": 0, "rec": 0}
orig_get, orig_rec = answer_cache.get_cached, answer_cache.record_candidate
answer_cache.get_cached = lambda m: (calls.__setitem__("get", calls["get"] + 1) or None)
answer_cache.record_candidate = lambda *a, **k: calls.__setitem__("rec", calls["rec"] + 1)
CA.generate_grounded_response = lambda *a, **k: "An answer."
CA._inject_definitional_companions = lambda m: m
CA.format_retrieved_text_for_prompt = lambda m: "text"
CA._fetch_pilot_related_judgments = lambda *a, **k: []
for style_name, expect in (("v1", (1, 1)), ("v2", (0, 0)), ("v3", (0, 0)), ("v3-lawyer", (0, 0))):
    os.environ["RESPONSE_STYLE"] = style_name
    calls.update(get=0, rec=0)
    CA._answer_single_match("q", [dict(MATCHES[0])])
    check((calls["get"], calls["rec"]) == expect, f"cache lookups / candidate records under {style_name}: {(calls['get'], calls['rec'])}")
answer_cache.get_cached, answer_cache.record_candidate = orig_get, orig_rec
os.environ["RESPONSE_STYLE"] = "v1"

# ---- situation detection still works for v1, v2 and v3 ----
L = CA._looks_like_situation
check(L("**Right now**\n\n1. Ask for the FIR.") and L("Right now, ask for the FIR."), "v1: an answer that opens with 'Right now' is a situation")
check(L("Not automatically, but nine years is long.\n\n**Right now**\n\n- Ask.") and L("Opening.\n\n**What you can do right now**\n\n1. Ask."), "v2 and v3 headings 'Right now' / 'What you can do right now' count")
check(not L("Opening.\n\n**What you can do now**\n\n1. Ask.") and not L("Many courts have to decide questions like this one right now in busy districts.") and not L(""), "a general question's 'What you can do now', a mid-sentence 'right now' and an empty text do not")

# ---- authorities_table ----
def fake_status(name, year, cit):
    return {"source": "card_quiet" if "Arnesh" in name else "not_checked", "note": "quiet note" if "Arnesh" in name else "Not checked by us."}
tab = AT.build(MATCHES, ["Arnesh Kumar v. State of Bihar"], [{"case_name": "Arnesh Kumar v. State of Bihar", "url": "https://l/a"}],
               [{"case_name": "Hemendra Reddy v. State", "date": "2023-04-28", "paragraph": "84", "link": "https://s3/x.pdf", "link_kind": "open_bucket_pdf", "register_note": None},
                {"case_name": "Hemendra Reddy v. State", "date": "2023-04-28", "paragraph": "85", "link": "https://s3/x.pdf"},
                {"case_name": "Overruled v. State", "date": "1999-05-03", "paragraph": "5", "register_note": "Overruled v. State (1999) was overruled by X (2002)."}], fake_status)
check([r["case"] for r in tab["library"]] == ["Arnesh Kumar v. State of Bihar"] and tab["library"][0]["link"] == "https://l/a", "library rows: only named cases, link from the cited links")
check([r["case"] for r in tab["wider"]] == ["Hemendra Reddy v. State", "Overruled v. State"] and tab["wider"][0]["tier"] == AT.TIER_WIDER, "wider rows: one row per case, tier is the unverified one")
check(tab["wider"][1]["status"].endswith("(2002).") and tab["wider"][1]["status_source"] == "register", "a wider-search case keeps its register note")
check(tab["library"][0]["status"] == AT.SHORT_STATUS["card_quiet"] and tab["wider"][0]["status"] == AT.SHORT_STATUS["not_checked"], "a quiet card and a missing check get the short table lines, not the long sentences")
check("still good law" in AT.TABLE_NOTE and "ever says" in AT.TABLE_NOTE, "one note under the tables explains 'Not checked by us' and says neither list ever calls a case good law")
check(not tab["has_bench"], "no bench column when the data holds no bench")
md = AT.render_markdown(tab)
check([h for h, _ in md] == ["Authorities (reviewed library)", "Further reading from a wider search (not independently verified)"], "two tiers, two headings")
check("| Case | Citation | Paragraph | Where it stands on our lists | Link |" in md[0][1] and "(2014)" in md[0][1] and "(2014) 8 SCC 273" in md[0][1] and "[open](https://l/a)" in md[0][1], "the table has the columns, the year, the held citation and a link")
check("not held" in md[1][1] and "[open](https://s3/x.pdf)" in md[1][1], "a wider-search row with no citation says 'not held' and keeps its link")
check("open bucket, CC-BY-4.0, Dattam Labs" in md[1][1], "an open-bucket copy is credited")
tab2 = AT.build([{"type": "judgment", "case_name": "A | B v. C", "citation": "(1) 1 SCC 1", "paragraph_number": "3", "bench": "5 judges"}], ["A | B v. C"], [], [], fake_status)
md2 = AT.render_markdown(tab2)
check(tab2["has_bench"] and "| Bench |" in md2[0][1] and "A \\| B v. C" in md2[0][1], "a bench column appears only when the data has one, and a pipe in a name is escaped")
check(AT.render_markdown({"library": [], "wider": [], "has_bench": False}) == [] and AT.build(None, None, None, None, fake_status)["library"] == [], "nothing to show gives nothing, and None inputs do not fail")

# ---- register_hooks.case_status ----
import register_hooks as RH
s1, s2, s3 = RH.case_status("Mohan Lal v. State of Punjab", 2018, "(2018) 17 SCC 627"), RH.case_status("Arnesh Kumar v. State of Bihar", 2014, "(2014) 8 SCC 273"), RH.case_status("Ram Prasad v. State of Bihar", 2012, "(2012) 3 SCC 100")
check(s1["source"] == "register" and s2["source"] in ("card_quiet", "card") and s3["source"] == "not_checked" and "Not checked by us" in (s3["note"] or ""), f"case_status: register / card / not checked ({s1['source']}, {s2['source']}, {s3['source']})")
check("good law" not in (s2["note"] or "").replace("not a finding that it is still good law", ""), "a quiet card's line never says a case is good law")
os.environ["REGISTER_HOOKS"] = "off"
check(RH.case_status("Mohan Lal v. State of Punjab", 2018)["source"] == "off", "REGISTER_HOOKS=off is honoured")
os.environ.pop("REGISTER_HOOKS")

# ---- the WhatsApp version (A7) ----
import whatsapp_formatter as W
WA_TEXT = ("Not automatically, but nine years is a long time.\n\n**Can the case be closed because of delay?**\n\nSection 346 of the BNSS lets a court adjourn only for recorded reasons. "
           "In *Arnesh Kumar v. State of Bihar* (2014), the Supreme Court directed X.\n\n## How this cuts for and against you\n\n*For you:*\n- the delay comes from the prosecution\n\n"
           "**What you can do right now**\n\n1. Ask your lawyer to object.\n2. Bring the order sheets.")
RES = {"state": "single_match", "response_text": WA_TEXT, "cited_judgment_links": [{"case_name": "Arnesh Kumar", "url": "https://x"}]}
os.environ["RESPONSE_STYLE"] = "v3"
msgs = W.format_answer_for_whatsapp(RES)
check(len(msgs) == 5 and msgs[0] == "Not automatically, but nine years is a long time.", f"v3: the opening is its own message, then one message per headed part, then the sources ({len(msgs)} messages)")
check(msgs[1].startswith("*Can the case be closed because of delay?*\n\nSection 346") and msgs[3].startswith("*What you can do right now*\n\n1. Ask"), "each heading travels with its paragraphs, as WhatsApp *bold*")
check("_Arnesh Kumar v. State of Bihar_ (2014)" in msgs[1] and "_For you:_" in msgs[2], "italic case names become WhatsApp _italics_ (a bare *x* would show as bold)")
check(msgs[2].startswith("*How this cuts for and against you*") and not any("##" in m or "**" in m for m in msgs), "a '#' heading is turned into a bold line and no markdown marker is left")
check(msgs[4].startswith("*Sources*") and "https://x" in msgs[4], "the closing message is headed Sources and carries the link")
os.environ["RESPONSE_STYLE"] = "v1"
msgs1 = W.format_answer_for_whatsapp(RES)
check(len(msgs1) > 5 and msgs1[0] == "Not automatically, but nine years is a long time." and any(m.startswith("*Judgments this answer relies on*") for m in msgs1), "v1: one message per paragraph and the old sources header, exactly as before")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "whatsapp_bot.py"), encoding="utf-8").read()
check('{"audience": "layman", "channel": "whatsapp"} if answer_style.is_v3() else {}' in src, "the WhatsApp bot asks for the layman voice and tells the engine it is on WhatsApp, under v3 only")
import tempfile
os.environ.setdefault("WHATSAPP_DB_PATH", os.path.join(tempfile.mkdtemp(), "wa.db"))
import whatsapp_bot
got = {}
whatsapp_bot.chat_assistant.answer_question = lambda q, **kw: (got.update(kw) or {"state": "no_match", "response_text": "ok"})
for st_, want in (("v1", {}), ("v3", {"audience": "layman", "channel": "whatsapp"})):
    os.environ["RESPONSE_STYLE"] = st_
    got.clear()
    try:
        whatsapp_bot.handle_incoming_message("whatsapp:+910000000001", "My trial has gone on nine years and nobody tells me anything")
    except Exception:
        pass
    got.pop("inline_domains", None)
    check(got == want, f"the bot's call to the engine under {st_}: {got}")
os.environ["RESPONSE_STYLE"] = "v1"


# --- staging 2026-10-14: lawyers' note must open with the Bottom line heading
check(CA._ensure_bottom_line("No provision allows closure.\n\nFacts assumed\n\nX").startswith("**Bottom line**\n\nNo provision"), "a note that opens with plain text gets the Bottom line heading")
check(CA._ensure_bottom_line("**Bottom line**\n\nNo.") == "**Bottom line**\n\nNo." and CA._ensure_bottom_line("Bottom line\n\nNo.") == "Bottom line\n\nNo.", "a note that already has it is left alone")
check(CA._ensure_bottom_line("**Delay and trials**\n\nNo.") == "**Delay and trials**\n\nNo." and CA._ensure_bottom_line("") == "" and CA._ensure_bottom_line(None) is None, "another heading is not guessed at; empty and None are safe")
check("Not automatically, but nine years" not in CA.RESPONSE_GENERATION_PROMPT_V3 and "never reuse a stock opener" in CA.RESPONSE_GENERATION_PROMPT_V3, "the v3 prompt no longer carries a sentence the model copies as its opener")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
