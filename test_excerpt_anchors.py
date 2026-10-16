"""
test_excerpt_anchors.py -- verbatim Supreme Court excerpts for a kind of question (excerpt_anchors.py + its calls in chat_assistant.py, sci_search_tier.py, authorities_table.py).
Fully offline and free: no model, no network. Run: python -X utf8 test_excerpt_anchors.py
"""
import json
import os
import sys
import types

import authorities_table as AT
import chat_assistant as CA
import excerpt_anchors as E
import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


Q_DELAY = "My trial has been going on for 9 years and the prosecution keeps asking for time. Can the case be closed because of the delay?"
os.environ.pop("ANCHORS", None)

# --- the switch: off by default, nothing changes
check(E.mode() == "off" and E.selected(Q_DELAY) == [] and E.block(Q_DELAY) == "" and E.fed() == [], "off is the default: no anchor is selected and the prompt gets nothing")
for v in ('on', ' "on" ', "'ON'", "1", "true"):
    os.environ["ANCHORS"] = v
    check(E.mode() == "on", f"the value {v!r} switches it on")
for v in ("off", "banana", ""):
    os.environ["ANCHORS"] = v
    check(E.mode() == "off", f"the value {v!r} leaves it off")
os.environ["ANCHORS"] = "on"

# --- the data
anchors = E.load()
check(len(anchors) == 2 and {a["id"] for a in anchors} == {"trial_delay_ramachandra_rao", "trial_delay_hussainara_khatoon_i"}, f"two anchors loaded ({[a['id'] for a in anchors]})")
check(all((a.get("check") or {}).get("all_found") and a["status"] in ("machine_checked", "reviewer_confirmed") and a.get("link", "").startswith("https://api.sci.gov.in/") for a in anchors), "each has a passing check against the court's PDF, a status and the official link")
check(all(ex["segments"] and all(s.strip() for s in ex["segments"]) for a in anchors for ex in a["excerpts"]), "no empty excerpt or segment")
check(all(a["status"] == "machine_checked" and not a.get("confirmed_by") for a in anchors), "none is marked as confirmed by a person yet")
check(E.load("/nonexistent/excerpt_anchors.json") == [], "a missing file gives no anchors and no error")

# --- which questions
POS = [Q_DELAY,
       "My case has been pending for 10 years and I keep getting dates. What can I do?",
       "Is there a time limit for a criminal trial to finish?",
       "What is the right to speedy trial under Article 21?",
       "The trial is dragging on, the prosecution seeks more time at every hearing.",
       "Does Article 21 help if my trial has been delayed for seven years?",
       "Can the High Court quash the case because the trial took 12 years?",
       "I have been in jail for 4 years as an undertrial and my trial has not started. What can I do?",
       "My son has been in custody for 5 years and the case is still at the evidence stage"]
NEG = ["Can the police arrest me without a warrant for cheating?",
       "The court sentenced my brother to 7 years in a cheating case. Can he appeal?",
       "What is the maximum imprisonment of 3 years or fine case under this section?",
       "My cheque bounced, what should I do?",
       "There was a delay of three days in lodging the FIR. Does that matter?",
       "The delay in filing the appeal was 90 days, can the court condone it?",
       "What is the punishment for theft under the BNS?",
       "I was arrested yesterday. When must I be produced before a Magistrate?",
       "What bail conditions can a court impose?",
       "Chargesheet was not filed in 90 days, can I get default bail?",
       "How long does a trial usually take?",
       ""]
for q in POS:
    check(bool(E.selected(q)), f"applies: {q[:70]!r}")
for q in NEG:
    check(E.selected(q) == [], f"does not apply: {q[:70]!r}")

# --- the prompt block
b = E.block(Q_DELAY)
check(b.startswith("\n\n## Verbatim Supreme Court excerpts") and "P. Ramachandra Rao v. State of Karnataka (2002), (2002) 4 SCC 578, decided 16 April 2002, a Bench of seven judges" in b, "the block names the case, the citation, the date and the bench size")
check("paragraph 29 of the SCC report" in b and b.count("paragraph 29") == 1, "the paragraph is shown for the one excerpt it belongs to")
for a in anchors:
    for ex in a["excerpts"]:
        for seg in ex["segments"]:
            check(seg.strip() in b, f"segment is in the block word for word: {seg[:60]!r}")
check("Hussainara Khatoon (I) v. Home Secretary, State of Bihar (1979), (1980) 1 SCC 81" in b, "Hussainara is named with its year and citation")
check("The first time you name one of these cases, put the words (verbatim excerpt, not yet confirmed by our reviewer) right after its name." in b and "NOT yet been confirmed by our reviewer" in b, "unconfirmed: the instruction says to label the case and that the reading is not confirmed")
check("never say that a case is good law" in b, "the block forbids saying that a case is good law")
check("CrPC Section 309 corresponds to BNSS Section 346" in b and "CrPC Section 482 corresponds to BNSS Section 528" in b and "a pointer to verify" in b, "statute pointers come from the site's own concordance table")
check("REGISTER FACT: Raj Deo Sharma v. The State of Bihar (1999) was overruled by P. Ramachandra Rao" in b, "the register's fact about the cases the excerpt names rides with the excerpt")
check(len(E.fed()) == 2 and E.case_names() == ["P. Ramachandra Rao v. State of Karnataka", "Hussainara Khatoon (I) v. Home Secretary, State of Bihar"], "block() remembers what it handed over")
check(len(b) < 9500, f"the block stays small ({len(b)} characters; 2026-10-16: the closing guidance and the length note added about 1,400)")
check(E.block("Can the police arrest me for cheating?") == "" and E.fed() == [], "a question on another subject gets no block and the memory is cleared")

# --- a confirmed anchor needs no label
conf = json.load(open(E._PATH, encoding="utf-8"))
for a in conf["anchors"]:
    a["status"], a["confirmed_by"], a["confirmed_on"] = "reviewer_confirmed", "Mr. Advocate", "2026-10-20"
import tempfile
tmp = os.path.join(tempfile.mkdtemp(), "excerpt_anchors.json")
json.dump(conf, open(tmp, "w", encoding="utf-8"))
saved = E.load
E.load = lambda path=None: saved(tmp)
bc = E.block(Q_DELAY)
check("Our reviewer has confirmed them." in bc and "put the words" not in bc and "NOT yet" not in bc, "confirmed: no label instruction and the block says the reviewer confirmed them")
res_c = E.attach(Q_DELAY, {"state": "single_match", "response_text": "In P. Ramachandra Rao v. State of Karnataka (2002) the Court held X."})
check(res_c["response_text"] == "In P. Ramachandra Rao v. State of Karnataka (2002) the Court held X." and res_c["anchor_excerpts"][0]["label"] == "" and res_c["anchor_excerpts"][0]["status"] == "reviewer_confirmed", "confirmed: the answer text is not labelled")
E.load = saved

# --- labelling the finished answer
E.block(Q_DELAY)
ans = ("A seven-judge Bench in P. Ramachandra Rao v. State of Karnataka (2002) said that no fixed outer time limit can be laid down. "
       "Earlier, Hussainara Khatoon (I) v. Home Secretary, State of Bihar (1979) held that speedy trial is part of Article 21. In P. Ramachandra Rao v. State of Karnataka the Court said it again.")
res = E.attach(Q_DELAY, {"state": "single_match", "response_text": ans})
L = E.LABEL_UNCONFIRMED
check(res["response_text"].count(L) == 2 and "(2002) " + L in res["response_text"] and "(1979) " + L in res["response_text"], f"each anchor case gets the label once, after its year ({res['response_text'].count(L)})")
check(res["response_text"].endswith("the Court said it again."), "a later mention is left alone")
again = E.attach(Q_DELAY, dict(res))
check(again["response_text"] == res["response_text"], "labelling twice adds nothing")
own = E.attach(Q_DELAY, {"state": "single_match", "response_text": "In P. Ramachandra Rao v. State of Karnataka (2002) (verbatim excerpt, not yet confirmed by our reviewer) the Court held X."})
check(own["response_text"].count("not yet confirmed by our reviewer") == 1, "the model's own label is accepted")
ae = res["anchor_excerpts"]
check(len(ae) == 2 and ae[0]["case_name"].startswith("P. Ramachandra") and ae[0]["paragraph"] == "29" and ae[0]["citation"] == "(2002) 4 SCC 578" and ae[0]["link"].endswith("18409.pdf") and ae[0]["label"] == L and len(ae[0]["excerpts"]) == 4, "the result lists the anchors with citation, paragraph, link and every excerpt")
E.reset()
check(E.attach(Q_DELAY, {"state": "single_match", "response_text": ans}) == {"state": "single_match", "response_text": ans}, "an answer whose prompt carried no anchors is left exactly as it was")
E.block(Q_DELAY)
check("anchor_excerpts" not in E.attach(Q_DELAY, {"state": "no_match", "response_text": ans}), "a non-answer state gets nothing")
check(E.attach(Q_DELAY, "not a dict") == "not a dict", "bad input does not raise")

# --- where the label goes, for the ways a model writes these names
def _lab(ans):
    E.block(Q_DELAY)
    return E.attach(Q_DELAY, {"state": "single_match", "response_text": ans})["response_text"]


check(_lab("as held in Hussainara Khatoon v. Home Secretary, State of Bihar (1979).") == "as held in Hussainara Khatoon v. Home Secretary, State of Bihar (1979) " + L + ".", "'Hussainara Khatoon v. Home Secretary, State of Bihar (1979)' (no '(I)'): label after the year, not after 'v.'")
check(_lab("Hussainara Khatoon (I) v. Home Secretary, State of Bihar (1979) said so.").count(L) == 1 and "(1979) " + L in _lab("Hussainara Khatoon (I) v. Home Secretary, State of Bihar (1979) said so."), "with the '(I)' in the answer: label after the year")
check(_lab("In Hussainara Khatoon (1979) the Court said so.") == "In Hussainara Khatoon (1979) " + L + " the Court said so.", "the short name and a year")
check(_lab("In *P. Ramachandra Rao v. State of Karnataka* (2002) the Court said so.") == "In *P. Ramachandra Rao v. State of Karnataka* (2002) " + L + " the Court said so.", "a name in italics: label after the closing mark and the year")
check(_lab("A seven-judge bench in P. Ramachandra Rao v. State of Karnataka (2002) 4 SCC 578 said so.") == "A seven-judge bench in P. Ramachandra Rao v. State of Karnataka (2002) 4 SCC 578 " + L + " said so.", "a report citation after the year: label after the citation")
check(_lab("In P. Ramachandra Rao v. State of Karnataka, AIR 2002 SC 1856 the Court said so.") == "In P. Ramachandra Rao v. State of Karnataka, AIR 2002 SC 1856 " + L + " the Court said so.", "an AIR citation after a comma: label after it")
check(_lab("In P. Ramachandra Rao (2002) the Court said so, and in State of Karnataka v. Someone (2004) it did not.").count(L) == 1, "another case is not labelled")

# --- the label only once per case, right after the case (staging 2026-10-14: it also appeared after "a seven-judge Bench")
stray = ("The Supreme Court, in Hussainara Khatoon (I) v. Home Secretary, State of Bihar (1979) " + L + ", held X. But in P. Ramachandra Rao v. State of Karnataka (2002) " + L + ", a seven-judge Bench " + L + " held Y, as the Bench said later.")
fixed = _lab(stray)
check(fixed.count(L) == 2 and "a seven-judge Bench held Y" in fixed and "(1979) " + L in fixed and "(2002) " + L in fixed, f"a copy of the label that follows neither case's first mention is removed ({fixed.count(L)} left)")
check(_lab(fixed) == fixed, "and doing it again changes nothing")
check("The four factors" in E.block(Q_DELAY) and "Kartar Singh's words" in E.block(Q_DELAY), "the block says whose the four factors are")

# --- the 'not checked' sentence leaves them out
E.block(Q_DELAY)
text = ("In P. Ramachandra Rao v. State of Karnataka (2002) the Court held X. In Hussainara Khatoon (I) v. Home Secretary, State of Bihar (1979) it held Y. "
        "In Ram Prasad v. State of Bihar (2001) it held Z.")
nc = CA._attach_register_notes({"state": "single_match", "response_text": text}).get("register_not_checked") or ""
check("Ram Prasad" in nc and "Hussainara" not in nc and "Ramachandra" not in nc, f"the sentence names only the case that is neither an anchor nor a source ({nc!r})")
E.reset()
nc2 = CA._attach_register_notes({"state": "single_match", "response_text": text}).get("register_not_checked") or ""
check("Hussainara" in nc2 and "Ram Prasad" in nc2, "with no anchors handed over the sentence is as before")

# --- the table of authorities has a third tier
E.block(Q_DELAY)
table = AT.build([], [], [], [], lambda n, y, c: {"source": "not_checked", "note": "x"}, anchors=E.cases())
check(len(table["anchors"]) == 2 and table["anchors"][0]["paragraphs"] == ["29"] and "not yet confirmed" in table["anchors"][0]["status"] and table["library"] == [] and table["wider"] == [], "the table has a 'Verbatim excerpts' tier")
md = AT.render_markdown(table)
check(len(md) == 1 and md[0][0].startswith("Verbatim excerpts the answer read") and "(2002) 4 SCC 578" in md[0][1] and "18409.pdf" in md[0][1], "and it is rendered with citation and link")
check(AT.build([], [], [], [], lambda *a: {}) == {"library": [], "wider": [], "anchors": [], "has_bench": False}, "without anchors the table is as before")

# --- the wider-search tier does not hand over the same case twice, and needs no second search for a case an anchor supplies
os.environ.update(SCI_SEARCH_MODE="feed", SCI_SEARCH_URL="http://127.0.0.1:9", SCI_SEARCH_TOKEN="t")
calls = []
RDS = {"rank": 1, "doc": 1, "case_name": "Raj Deo Sharma v. The State of Bihar", "date": "1999-05-03", "paragraph": "5", "link": "https://x/1.pdf", "link_kind": "court_archive_pdf", "text": "Time limit held X.", "name_to_review": False, "citations": {}}
PRR2 = {"rank": 2, "doc": 18404, "case_name": "P. Ramachandra Rao, etc. Etc.Appellants v. State of Karnataka Respondent", "date": "2002-04-16", "paragraph": "3", "link": "https://x/18404.pdf", "link_kind": "court_archive_pdf", "text": "RAJU, J. I feel compelled to express my reservation.", "name_to_review": False, "citations": {}}
OTHER = {"rank": 3, "doc": 5, "case_name": "Arnesh Kumar v. State of Bihar", "date": "2014-07-02", "paragraph": "9", "link": "https://x/5.pdf", "link_kind": "open_bucket_pdf", "text": "Arrest guidelines.", "name_to_review": False, "citations": {}}


def fake_search(q, timeout=None, k=10, label="x"):
    calls.append(q)
    return {"results": [RDS, PRR2, OTHER]}


T.search = fake_search
T.reset()
E.block(Q_DELAY)
fb = T.feed_block(Q_DELAY)
check(len(calls) == 1 and "WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: P. Ramachandra" not in fb and "Arnesh Kumar" in fb and "Raj Deo Sharma" in fb, "anchors on: the anchor case (even in another spelling of its name) is not fed from the wider search and no second search is made for it")
os.environ["ANCHORS"] = "off"
calls.clear()
T.reset()
fb2 = T.feed_block(Q_DELAY)
check("WIDER SEARCH -- NOT INDEPENDENTLY VERIFIED: P. Ramachandra" in fb2, "anchors off: the wider search feeds the case as before")
os.environ["ANCHORS"] = "on"
os.environ.pop("SCI_SEARCH_MODE")

# --- the call in generate_grounded_response, and the answer cache
sent = {}


class _Msgs:
    def create(self, **kw):
        sent["prompt"] = kw["messages"][0]["content"] if isinstance(kw["messages"][0]["content"], str) else json.dumps(kw["messages"][0]["content"])
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Short answer.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
E.reset()
txt = CA.generate_grounded_response(Q_DELAY, "[BNSS Section 346]\nTrial text.", matches=[])
check(txt and "Verbatim Supreme Court excerpts" in sent["prompt"] and "[BNSS Section 346]" in sent["prompt"] and sent["prompt"].index("Trial text.") < sent["prompt"].index("Verbatim Supreme Court excerpts"), "the excerpts are put into the prompt after the library text")
sent.clear()
txt = CA.generate_grounded_response("Can police arrest me for cheating?", "[BNSS Section 35]\nArrest text.", matches=[])
check(txt and "Verbatim Supreme Court excerpts" not in sent["prompt"], "a question on another subject: nothing added")
os.environ["ANCHORS"] = "off"
sent.clear()
txt = CA.generate_grounded_response(Q_DELAY, "[BNSS Section 346]\nTrial text.", matches=[])
check(txt and "Verbatim Supreme Court excerpts" not in sent["prompt"], "switch off: nothing added")
os.environ["ANCHORS"] = "on"

# the full path: labels and the list ride on the result
CA._answer_question_core = lambda q, inline_domains=frozenset(): {"state": "single_match", "response_text": "The Supreme Court in P. Ramachandra Rao v. State of Karnataka (2002) said no fixed limit applies."}
out = CA._answer_question_inner(Q_DELAY)
check(out["response_text"].count(E.LABEL_UNCONFIRMED) == 0 and "anchor_excerpts" not in out, "an answer whose prompt carried no anchors (the core was stubbed) is untouched")
E.block(Q_DELAY)                                   # what generate_grounded_response does inside the core
CA._answer_question_core = lambda q, inline_domains=frozenset(): (E.block(q), {"state": "single_match", "response_text": "The Supreme Court in P. Ramachandra Rao v. State of Karnataka (2002) said no fixed limit applies."})[1]
out = CA._answer_question_inner(Q_DELAY)
check(E.LABEL_UNCONFIRMED in out["response_text"] and len(out.get("anchor_excerpts") or []) == 2, "through answer_question's inner path the answer is labelled and lists the excerpts")

# --- 2026-10-16: the guidance for "can the case be closed?" and the length note (a live answer said only that delay does not end a case, fused guidelines (9) and (11), and was squeezed by the 300-400 word limit)
import answer_style as AS
os.environ.pop("RESPONSE_STYLE", None)
bg = E.block(Q_DELAY)
check("guideline (9) of Antulay" in bg and "\"shall be quashed\"" in bg and "ordinary consequence" in bg and "conclude the trial within a fixed time" in bg, "the block tells the model that quashing is the ordinary consequence once the right is found infringed, and that a fixed-time order is the alternative")
check("guideline (11) says WHERE to go" in bg and "Do not describe guideline (11) as a remedy" in bg and "grave and exceptional case" in bg, "and that guideline (11) is about the High Court route and stays, not a remedy")
check("up to about 400 words" in bg, "v1: the block allows about 400 words for this multi-part answer")
os.environ["RESPONSE_STYLE"] = "v3"
bg3 = E.block(Q_DELAY)
check("up to about 400 words" not in bg3 and "guideline (9) of Antulay" in bg3, "v3 keeps its own length rules (no 400-word note) but still gets the guidance")
AS._LOCAL.channel = "whatsapp"
os.environ["RESPONSE_STYLE"] = "v1"
check("up to about 400 words" not in E.block(Q_DELAY), "WhatsApp keeps its character limit (no 400-word note)")
AS._LOCAL.channel = None
os.environ.pop("RESPONSE_STYLE", None)
# the guidance is added only when the excerpts handed over really contain guidelines (9) and (11)
fake = [{"excerpts": [{"segments": ["Only a general passage about Article 21."]}]}]
check(E._closing_guidance(fake) == "", "no guidance when the excerpts do not contain Antulay's guidelines (9) and (11)")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
