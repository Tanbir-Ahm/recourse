"""
test_cited_judgment_links.py -- a "read the judgment" link for every judgment an answer actually relies on.

WHY (2026-09-28): the only place any answer showed a link was the "Other real court cases" list, which is built from
the hedged pilot pool and deliberately leaves out any case already used in the answer. So the moment a case became a
verified core anchor (Inder Mohan Goswami, on non-bailable-warrant questions) it would be NAMED in the answer but its
real api.sci.gov.in link would disappear. Core cases such as Md. Ibrahim and Bhajan Lal had never shown a link at all.
User decision: show the stored link for every judgment the answer relies on, for ALL core cases with a stored link.

Rules under test:
  * a case gets a link only if the answer TEXT actually names it (a case merely retrieved but unmentioned gets none);
  * never a wrong link: "State of Haryana v Bhajan Lal" must not be linked because the answer names "Jagrup Singh v State
    of Haryana" (the shared party is the State, so the distinctive party is used);
  * a case already listed in the pilot list is not linked twice;
  * every core judgment file has a resolvable link;
  * WhatsApp and the website both render it; an answer with no cited cases gets no extra message.

Fully offline and free. Run: python -X utf8 test_cited_judgment_links.py
"""
import glob
import json
import sys

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


import chat_assistant as ca
import retrieval
import whatsapp_formatter as wf

GOSWAMI = "Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors."
GOV = "https://api.sci.gov.in/jonew/judis/29628.pdf"

# ---------------------------------------------------------------- 1. the distinctive name of a case
NAMES = {
    "State of Haryana v Bhajan Lal": "Bhajan Lal",
    "G. Sagar Suri and Anr. v State of U.P. and Ors.": "G. Sagar Suri",
    "Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors.": "Inder Mohan Goswami",
    "Union of India v Md Nawaz Khan": "Md Nawaz Khan",
    "Md. Ibrahim & Ors v State of Bihar & Anr": "Md. Ibrahim",
    "Arnesh Kumar v State of Bihar": "Arnesh Kumar",
    "State (NCT of Delhi) v Somebody Else": "Somebody Else",
    "Prabir Purkayastha v State (NCT of Delhi)": "Prabir Purkayastha",
}
for full, want in NAMES.items():
    got = ca._case_distinctive_name(full)
    check(got == want, f"distinctive party of {full!r} is {want!r} -- got {got!r}")

# ---------------------------------------------------------------- 2. every core judgment resolves to a link
files = [f for f in glob.glob("chunks/*_chunks.json")]
names, missing = 0, []
for f in files:
    try:
        rows = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    if not (isinstance(rows, list) and rows and isinstance(rows[0], dict) and "case_name" in rows[0]):
        continue
    names += 1
    url = retrieval.get_judgment_source_url(rows[0]["case_name"])
    if not (url and url.startswith("https://")):
        missing.append(rows[0]["case_name"])
check(names >= 60 and not missing, f"all {names} core judgment files resolve to a stored https link -- missing: {missing[:5]}")
check(retrieval.get_judgment_source_url(GOSWAMI) == GOV, "Goswami resolves to the real government link")
check(retrieval.get_judgment_source_url("A Case That Does Not Exist v Nobody") is None, "an unknown case resolves to None, never a guess")
check(retrieval.get_judgment_source_url("") is None and retrieval.get_judgment_source_url(None) is None, "empty/None never raises")

# ---------------------------------------------------------------- 3. which cases get a link
def result(text, cases, unverified=(), state="single_match"):
    return {"state": state, "response_text": text,
            "matches": [{"type": "judgment", "case_name": c} for c in cases] + [{"type": "statute", "act": "BNSS", "section_number": "73"}],
            "unverified_related_judgments": [{"case_name": u, "ik_search_url": "https://x"} for u in unverified]}


r = ca._attach_cited_judgment_links(result("In Inder Mohan Goswami v State of Uttaranchal the Court said warrants need care.", [GOSWAMI, "Arnesh Kumar v State of Bihar"]))
links = r["cited_judgment_links"]
check([l["case_name"] for l in links] == [GOSWAMI] and links[0]["url"] == GOV,
      "only the case the answer TEXT names gets a link (Arnesh Kumar was retrieved but not mentioned)")

r = ca._attach_cited_judgment_links(result("Jagrup Singh v State of Haryana reduced murder to culpable homicide.", ["Karnail Singh v State of Haryana", "Jagrup Singh v State of Haryana"]))
check([l["case_name"] for l in r["cited_judgment_links"]] == ["Jagrup Singh v State of Haryana"],
      "Karnail Singh is NOT linked just because the answer names another case against the same State (Haryana)")

r = ca._attach_cited_judgment_links(result("Union of India v Md Nawaz Khan was discussed.", ["Union of India v Mohanlal", "Union of India v Md Nawaz Khan"]))
check([l["case_name"] for l in r["cited_judgment_links"]] == ["Union of India v Md Nawaz Khan"],
      "two 'Union of India v ...' cases: naming one links only that one (the shared party is never the match key)")

r = ca._attach_cited_judgment_links(result("Union of India v Mohanlal is an older decision.", ["Union of India v Mohanlal", "Union of India v Md Nawaz Khan"]))
check([l["case_name"] for l in r["cited_judgment_links"]] == ["Union of India v Mohanlal"], "and the reverse")

r = ca._attach_cited_judgment_links(result("The Goswami case says warrants need care.", [GOSWAMI]))
check([l["case_name"] for l in r["cited_judgment_links"]] == [GOSWAMI], "a lone distinctive surname ('the Goswami case') is enough")
r = ca._attach_cited_judgment_links(result("Kumar was there.", ["Arnesh Kumar v State of Bihar"]))
check(r["cited_judgment_links"] == [], "but a short/common word ('Kumar') alone never links a case")

r = ca._attach_cited_judgment_links(result("goswami is discussed here, in Inder Mohan Goswami", [GOSWAMI], unverified=[GOSWAMI]))
check(r["cited_judgment_links"] == [], "a case already shown in the pilot list is not linked twice")

r = ca._attach_cited_judgment_links(result("The Court in Inder Mohan Goswami said this. Inder Mohan Goswami also said that.", [GOSWAMI, GOSWAMI]))
check(len(r["cited_judgment_links"]) == 1, "a case appearing twice in the matches is linked once")

r = ca._attach_cited_judgment_links(result("no case named at all here", [GOSWAMI]))
check(r["cited_judgment_links"] == [], "an answer that names no case gets no links")

for st in ("unrelated", "no_match", "adjacent_uncovered", "covered_elsewhere_in_tool", "retrieval_unavailable", "classifier_unavailable"):
    r = ca._attach_cited_judgment_links({"state": st, "response_text": "Inder Mohan Goswami", "matches": [{"type": "judgment", "case_name": GOSWAMI}]})
    check("cited_judgment_links" not in r or r["cited_judgment_links"] == [], f"state {st!r} never gets links")

r = ca._attach_cited_judgment_links(result("Inder Mohan Goswami v State of Uttaranchal is relevant.", [GOSWAMI], state="conflicting_matches"))
check(len(r["cited_judgment_links"]) == 1, "the conflicting_matches state gets links too")

check(ca._attach_cited_judgment_links({"state": "single_match"}) == {"state": "single_match"} or True, "a malformed result never raises")
try:
    ca._attach_cited_judgment_links({"state": "single_match", "response_text": None, "matches": None})
    ca._attach_cited_judgment_links({"state": "single_match", "response_text": "x", "matches": [None, {"type": "judgment"}]})
    check(True, "None / partial matches never raise")
except Exception as exc:
    check(False, f"None / partial matches must not raise -- {exc!r}")

# an Indian Kanoon link is labelled as such, a government link is not
ik_case = "Arnesh Kumar v State of Bihar"
r = ca._attach_cited_judgment_links(result("Arnesh Kumar v State of Bihar says arrest is not automatic.", [ik_case]))
link = r["cited_judgment_links"][0]
check("indiankanoon.org" in link["url"] and link["source_label"] == "Indian Kanoon", "an Indian Kanoon link is labelled 'Indian Kanoon'")
check(ca._attach_cited_judgment_links(result("Inder Mohan Goswami v State", [GOSWAMI]))["cited_judgment_links"][0]["source_label"] == "Supreme Court of India (official)",
      "a government link is labelled as the official source")


# ---------------------------------------------------------------- 3b. an entry shown under ANOTHER case's name never borrows the file's link
# REAL BUG found in the first end-to-end run (2026-09-28): the doctrine entry that presents "State of Haryana v Bhajan Lal"
# reads its text from the Usha Chakraborty file (display_case_name), so the override match carried Usha Chakraborty's link
# and the answer showed the SAME Indian Kanoon link for both names -- a wrong link for Bhajan Lal.
import judgment_doctrine_map as jdm
qs = "They filed a false cheating FIR against me over a business partnership, it is a civil dispute and a criminal case, can it be quashed?"
ov = jdm.get_judgment_doctrine_override(qs)
bh = [o for o in ov if o.get("case_name") == "State of Haryana v Bhajan Lal"]
check(bh, "sanity: the Bhajan Lal display entry fires on a civil-dispute-criminal-case question")
check(all(not o.get("source_url") for o in bh), "a match shown under a DIFFERENT case's name carries no source_url (never the file's own link)")
ush = [o for o in ov if o.get("case_name") == "Usha Chakraborty v State of West Bengal"]
check(all(o.get("source_url") for o in ush), "while a match shown under its own name keeps its link")
r = ca._attach_cited_judgment_links({"state": "single_match", "response_text": "State of Haryana v Bhajan Lal and Usha Chakraborty v State of West Bengal.",
                                     "matches": ov})
names_linked = {l["case_name"]: l["url"] for l in r["cited_judgment_links"]}
check("State of Haryana v Bhajan Lal" not in names_linked, "Bhajan Lal (no link of its own in the corpus) is NOT given Usha Chakraborty's link")
check("Usha Chakraborty v State of West Bengal" in names_linked, "Usha Chakraborty is still linked")
check(len(set(names_linked.values())) == len(names_linked), "no two different cases ever share one link in the same answer")

# ---------------------------------------------------------------- 4. answer_question attaches them on the real return path
import unittest.mock as um
fake = {"state": "single_match", "response_text": "Inder Mohan Goswami v State of Uttaranchal matters.", "matches": [{"type": "judgment", "case_name": GOSWAMI}]}
with um.patch.object(ca, "_answer_question_core", return_value=fake):
    out = ca.answer_question("anything")
    check(out.get("cited_judgment_links") and out["cited_judgment_links"][0]["url"] == GOV, "answer_question() attaches the links to what the core returns")
with um.patch.object(ca, "_answer_question_core", return_value={"state": "unrelated"}):
    check(ca.answer_question("x") == {"state": "unrelated"}, "an 'unrelated' answer passes through unchanged")
with um.patch.object(ca, "_answer_question_core", return_value=fake), um.patch.object(ca, "_attach_cited_judgment_links", side_effect=RuntimeError("boom")):
    check(ca.answer_question("x") == fake, "if attaching links ever fails, the real answer still goes out untouched (fail-open)")

# ---------------------------------------------------------------- 5. WhatsApp rendering
base = {"state": "single_match", "response_text": "First paragraph.\n\nSecond paragraph.", "unverified_related_judgments": []}
none_msgs = wf.format_answer_for_whatsapp(dict(base))
check(not any("relies on" in m for m in none_msgs), "no cited cases -> no extra message")
with_links = wf.format_answer_for_whatsapp({**base, "cited_judgment_links": [{"case_name": GOSWAMI, "url": GOV, "source_label": "Supreme Court of India (official)"}]})
block = [m for m in with_links if "relies on" in m]
check(len(block) == 1 and GOSWAMI in block[0] and GOV in block[0], "one extra message names the case and carries the real government link")
check("Supreme Court of India (official)" in block[0], "the source label is shown so the reader knows what kind of link it is")
both = wf.format_answer_for_whatsapp({**base, "cited_judgment_links": [{"case_name": GOSWAMI, "url": GOV, "source_label": "x"}],
                                      "unverified_related_judgments": [{"case_name": "Other Case", "ik_search_url": "https://example.test/o"}]})
idx_links = next(i for i, m in enumerate(both) if "relies on" in m)
idx_pilot = next(i for i, m in enumerate(both) if "Other real court cases" in m)
check(idx_links < idx_pilot, "the cited-judgments message comes BEFORE the hedged 'other cases' list")
check(both[0] == "First paragraph." and both[1] == "Second paragraph.", "the answer's own paragraphs are untouched and still first")

# ---------------------------------------------------------------- 6. website rendering
src = open("recourse_app.py", encoding="utf-8").read()
check("cited_judgment_links" in src, "the website's result renderer reads cited_judgment_links")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
