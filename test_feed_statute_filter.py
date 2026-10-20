"""
test_feed_statute_filter.py -- a wider-search passage that cites the section number the person NAMED, but of another statute, is left out of the feed (sci_search_tier._statute_filter; FEED_STATUTE_FILTER=on|off,
default on, and it only has anything to do when the Act shelf found an Act and the question names a section of it).

Why: the owner's staging test of 2026-10-19 asked about section 17 of the Prevention of Corruption Act. The wider search ranks a passage that holds the section NUMBER higher, so "Sri Radhy Shyam v. State of U.P."
(section 17 of the land-acquisition law: urgency) came up and was listed under the answer. The passages below are the 900-character excerpts exactly as the owner's page showed them.
Offline, free, no model. Run: python -X utf8 test_feed_statute_filter.py
"""
import contextlib
import io
import json
import os
import sys

import numpy as np

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("ACT_SHELF", "ACT_DIRECTORY", "REGISTER_HOOKS", "RESPONSE_STYLE", "SCOPE_GATE", "SCI_SEARCH_MODE", "ANCHORS", "GROUNDING_CHECKS", "FEED_STATUTE_FILTER", "ACT_DETECT"):
    os.environ.pop(_v, None)

import act_shelf as S
import chat_assistant as CA
import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


EMB = json.load(open(os.path.join(S.SHELF_DIR, "shelf_embeddings.json"), encoding="utf-8"))
VEC = {r["chunk_id"]: np.array(r["embedding"], dtype=float) for r in EMB["records"]}


def like(code, sec):
    return lambda text: VEC[f"act:{code}:{sec}"]


os.environ["ACT_SHELF"] = "on"
Q17 = "Can a disproportionate assets case under the Prevention of Corruption Act be filed without section 17 approval?"
res17 = S.search(Q17, [{"id": "pc_act_1988"}], embed_fn=like("PCACT", "17"))
CTX = S.statute_context(res17["matches"])
check(len(CTX) == 1 and list(CTX[0]["sections"]) == ["17"] and "Deputy Superintendent" in CTX[0]["sections"]["17"] and CTX[0]["aliases"] is not None and CTX[0]["aliases"].search("the Prevention of Corruption Act, 1988"),
      "the context holds the section the question NAMED (not the ones found by meaning), its words and the Act's names")
check(S.statute_context([]) == [] and S.statute_context(None) == [] and S.statute_context([{"source": "act_shelf", "retrieval": "meaning", "act": "PCACT", "section_number": "17", "text": "x"}]) == [],
      "a section found only by meaning, or nothing at all, gives no context")

# the passages exactly as the owner's page showed them (the first 900 characters the model also saw)
P = {
    "radhy": "42. In Esso Fabs Private Limited vs. State of Haryana (supra), the Court again dealt with the question whether the State was justified in invoking Section 17(1) and 17(4) and dispensing with the inquiry under Section 5-A and held: “53. Section 17, no doubt, deals with special situations and exceptional circumstances covering cases of “urgency” and “unforeseen emergency”. ...",
    "ram_singh": "In Bhajan Lals case this Court had found on facts that the SP had passed the order mechanically and in a very casual manner regardless of the settled principles of law. The provisions of Section 17 of the Act had not been complied with. As earlier noticed the SP while authorising the SHO to investigate had made only endorsement to the effect please register the case and investigate. The SP was shown to be not aware either of allegations or the nature of the offences and the pressure of work-load requiring investigation by an Inspector. ...",
    "sudhakar33": "33. Therefore, according to the High Court, the Superintendent of Police is not competent to pass an order under Section 17 of the PC Act until a formally registered FIR came into existence. In other words, registration of the FIR is sine qua non for issuance of an order to investigate the case. The High Court framed a four-step procedure: first, the police must verify the facts upon receiving the source information report; second, a preliminary inquiry is to be conducted by the police; third, the FIR is registered; ...",
    "sudhakar45": "45. As a consequence of the above discussion, we are convinced that the High Court erred in holding that the Superintendent of Police must first direct the registration of an FIR and only after it is registered, he would be competent to issue an order for investigation under Section 17 of the PC Act. This interpretation could be permissible only if the subordinates of the Superintendent of Police had a discretion to either comply with or disregard the latter’s directive to register the FIR. ...",
    "yunus": "23. There is no dispute that though these officers are on deputation, they are otherwise of the requisite rank as contemplated by Section 17 of the Prevention of Corruption Act, 1988 and that other formalities under that Act are satisfied for entrustment of duties under the Prevention of Corruption Act, 1988. Question is whether these police officers of the State can be invested with powers of investigation under Section 17 of the Prevention of Corruption Act, 1988 by the State under its statutory powers traceable to the same section?”",
    "naidu28": "28. Having considered the different contours of Section 17A, I am of the opinion that Section 17A would be applicable to the offences under the PC Act as amended by the Amendment Act, 2018, and not to the offences existing prior to the said amendment. Even otherwise, absence of an approval as contemplated in Section 17A for conducting enquiry, inquiry or investigation of the offences alleged to have been committed by a public servant in purported exercise of his official functions or duties, would neither vitiate the proceedings nor would be a ground to quash the proceedings or the FIR ...",
    "mayawati": "From the perusal of those orders, we are also satisfied that there could not have been any material before this Court about the disproportionate assets case of the petitioner beyond the Taj Corridor Project case and there was no such question or issue about disproportionate assets of the petitioner. In view of the same, giving any direction to lodge FIR relating to disproportionate assets case did not arise. ...",
    "lokayukta": "11. The order passed by Superintendent of Police reads as follows: “KARNATAKA LOKAYUKTA NO: KLA/PW/SP/City.Dn./99-2000 Superintendent of Police City Division, M.S. Buildings, Dr. Ambedkar Veedhi, Bangalore-560 001. Dated: 12th June, 2000. Sub: Possession of Disproportionate Assets to the known source of income by Sri. B. Srinivasa, Engineer-in-chief, Rural Development Engineering Department-reg. I have gone through the report of Sri. Md. ...",
}
CTXI = T.make_statute_context(CTX)
why = {k: T._off_statute(v, CTXI) for k, v in P.items()}
check(why["radhy"] is not None, f"the land-acquisition passage (section 17(1) and 17(4), urgency, section 5-A) is recognised as another statute's ({why['radhy']!r})")
for k in ("ram_singh", "sudhakar33", "sudhakar45", "yunus", "naidu28", "mayawati", "lokayukta"):
    check(why[k] is None, f"'{k}' is kept ({why[k]!r})")

# explicit evidence: the number is tied, in so many words, to another statute
ACT = lambda s: s + " " + "The Court examined the matter at length and recorded its reasons for the conclusion that it reached in this appeal. " * 2
for name, txt in (("land acquisition", "Section 17 of the Land Acquisition Act, 1894 allows the Collector to take possession in a case of urgency."),
                  ("arbitration", "An application under Section 17 of the Arbitration and Conciliation Act, 1996 for interim measures of protection is maintainable before the Arbitral Tribunal."),
                  ("code", "Section 17 of the Code of Civil Procedure provides for the place of suing where immovable property lies in the jurisdiction of different courts."),
                  ("ndps", "Under Section 17 of the NDPS Act the punishment for contravention in relation to poppy straw is rigorous imprisonment which may extend to ten years.")):
    check(T._off_statute(ACT(txt), CTXI) is not None, f"explicit other statute ({name}): left out")
check(T._off_statute(ACT("Section 17 of the Prevention of Corruption Act, 1988 and Section 17 of the Land Acquisition Act, 1894 are different provisions."), CTXI) is None, "a passage that names the Act itself is kept even when it also names another")
check(T._off_statute(ACT("Section 17 of the PC Act and Section 17 of the Land Acquisition Act are different provisions."), CTXI) is None, "the short name 'PC Act' counts as naming the Act")
check(T._off_statute(ACT("The conditions in Section 17 of the Act were not satisfied: the order was not passed by the officer of the required rank, the Magistrate had not authorised the investigation."), CTXI) is None, "'Section 17 of the Act' with the section's own words (rank, officer, Magistrate, investigation) is kept")
check(T._off_statute(ACT("Section 17 of the Act deals with special situations of urgency and the authority acquiring land may dispense with the inquiry."), CTXI) is not None, "'Section 17 of the Act' with nothing of the section's own words is left out")
check(T._off_statute("Section 17 of the Land Acquisition Act, 1894.", CTXI) is not None, "a short passage that ties the number to another named Act is still left out (explicit evidence needs no length)")
check(T._off_statute("Section 17 of the Act deals with urgency.", CTXI) is None, "a passage shorter than 150 characters is not judged by the yardstick of the section's own words")
check(T._off_statute(ACT("Section 19 of the Land Acquisition Act, 1894 provides for the declaration of the land to be acquired."), CTXI) is None, "a section number the person did not name is not our business")
check(T._off_statute(ACT("Section 17A of the Land Acquisition Act, 1894 is a different section."), CTXI) is None, "17A is not 17")
check(T._off_statute(ACT("Sections 13 and 17 of the Land Acquisition Act, 1894 deal with different things."), CTXI) is not None, "a list of sections ('Sections 13 and 17 of the ... Act') counts as a reference to 17")
check(T._off_statute(P["radhy"], []) is None and T._off_statute(P["radhy"], None) is None and T._off_statute("", CTXI) is None and T._off_statute(None, CTXI) is None, "no context, or no text: nothing is left out; nothing raises")

# a judgment's short name for the Act is its year: 'the Act of 2002' (the PMLA), 'the 1988 Act'
resP = S.search("What are the grounds for arrest under section 19 of the PMLA?", [{"id": "pmla_2002"}], embed_fn=like("PMLA", "19"))
CTXP = T.make_statute_context(S.statute_context(resP["matches"]))
check(CTXP and CTXP[0]["year"] == 2002, "the context knows the year of the Act (2002) from its official name")
act2002 = "10. Though the appellants did not challenge the constitutional validity of Section 19 of the Act of 2002 in their writ petitions and had only sought reading down of the provision, the Court considered the matter. " * 2
check(T._off_statute(act2002, CTXP) is None, "'Section 19 of the Act of 2002' is the PMLA's own way of naming itself: kept")
check(T._off_statute(act2002.replace("Act of 2002", "2002 Act"), CTXP) is None, "'the 2002 Act' is kept too")
check(T._off_statute(act2002.replace("Act of 2002", "Act of 1894"), CTXP) is not None, "'Section 19 of the Act of 1894' (another year, nothing of the section's words) is left out")
check(T._off_statute(ACT("Section 17 of the Motor Vehicles Act, 1988 deals with something else entirely about vehicles."), CTXI) is not None, "an explicit other Act of the SAME year (Motor Vehicles Act, 1988) is still left out: the name beats the year")
check(T._off_statute(ACT("Section 17 of the Act of 1988 requires that the investigation be by an officer of the stated rank, authorised by a Magistrate."), CTXI) is None, "'Act of 1988' with the section's own words: kept")

# a section with too few words of its own cannot be judged
tiny_ctx = T.make_statute_context([{"act": "X Act", "aliases": None, "sections": {"5": "Short title."}}])
check(T._off_statute(ACT("Section 5 of the Act provides for the hearing of objections by the Collector."), tiny_ctx) is None, "a section of fewer than 12 content words is not used to judge a passage (explicit naming still is)")
check(T._off_statute(ACT("Section 5 of the Land Acquisition Act, 1894 provides for the hearing of objections by the Collector."), tiny_ctx) is not None, "but a passage that ties the number to another named Act is still left out")

# the Act's name as judgments write it: small words and brackets inside it, an acronym with no 'of', 'read with' chains, 'thereof', a repeat of the bare number.  Passages: the library's own judgments
# (Pankaj Bansal, Prabir Purkayastha, Vihaan Kumar, L. Muruganantham, Sri Manjunath; found by running the filter over the 168 library passages that cite one of fifteen shelf sections; before this block 74 were left
# out, now 94, and every one of the 94 was read: each is about another statute).
def ctx_for(aid, code, num, actname):
    r = S.search(f"What does section {num} of the {actname} say?", [{"id": aid}], embed_fn=like(code, num))
    return T.make_statute_context(S.statute_context(r["matches"]))


C19 = ctx_for("pc_act_1988", "PCACT", "19", "Prevention of Corruption Act")
C13 = ctx_for("pc_act_1988", "PCACT", "13", "Prevention of Corruption Act")
C45P = ctx_for("pmla_2002", "PMLA", "45", "Prevention of Money-laundering Act")
CD3 = ctx_for("dowry_prohibition_act_1961", "DOWRY", "3", "Dowry Prohibition Act")
NAMEDTESTS = [
    ("Section 19 of the Prevention of Money Laundering Act, 2002 (for brevity)", "Prevention of Money Laundering Act, 2002"),
    ("Sections 3 and 4 of the Prevention of Money Laundering Act, 2002(for short ‘PMLA’)", "Prevention of Money Laundering Act, 2002"),
    ("Section 5 of the Narcotic Drugs and Psychotropic Substances Act, 1985", "Narcotic Drugs and Psychotropic Substances Act, 1985"),
    ("Sections 13, 16, 17, 18, 22C of the Unlawful Activities(Prevention) Act,\n1967(for short “UAPA”)", "Unlawful Activities(Prevention) Act, 1967"),
    ("Section 21 of the Protection of Children from Sexual Offences Act, 2012", "Protection of Children from Sexual Offences Act, 2012"),
    ("Section 14 of the Scheduled Castes and the Scheduled Tribes (Prevention of Atrocities) Act, 1989", "Scheduled Castes and the Scheduled Tribes (Prevention of Atrocities) Act, 1989"),
    ("Section 2 of the Right of Persons with Disabilities Act, 2016", "Right of Persons with Disabilities Act, 2016"),
    ("Section 45 read with Section 40 of the RPwD Act, 2016, Rule 15", "RPwD Act, 2016"),
    ("Section 482 Cr.P.C. is wide", "Cr.P.C."),
    ("under Section 19(1) PMLA.” (emphasis added)", "PMLA"),
    ("Section 17 of the Act of 1894 provides", "Act of 1894"),
]
for txt, want in NAMEDTESTS:
    refs = T._section_refs(txt)
    got = T._statute_named_after(txt, refs[0][2], None, start=refs[0][1])
    check(got is not None and got.replace("\n", " ") == want, f"the statute named after {txt[:50]!r} is {want!r} (got {got!r})")
for txt in ("Section 17 in Chapter IV of the Act provides", "Section 17 of the Act provides", "Section 17 under Part II of the Rules framed", "Section 17 read with Section 18 of the Act"):
    refs = T._section_refs(txt)
    check(T._statute_named_after(txt, refs[0][2], None, start=refs[0][1]) is None, f"no statute is named in {txt!r}: 'the Act', 'Chapter IV of the Act', 'the Rules framed' are not names")
t_th = "were incorporated in the Prevention of Money Laundering Act, 2002 under Section 19 thereof and has been succinctly reiterated."
r_th = T._section_refs(t_th)[0]
check(T._statute_named_after(t_th, r_th[2], None, start=r_th[1]) == "Prevention of Money Laundering Act, 2002", "'... Act, 2002 under Section 19 thereof': the Act named just before")
check(T._statute_named_after("the Prevention of Corruption Act, 1988 under Section 19 thereof", 54, C19[0]["aliases"], 1988, start=47) is None, "...but not when that Act is the target Act's own")
# the library's own passages
VIHAAN = ("10. As far as Article 22(1) is concerned, the legal position is well settled. In the case of Pankaj Bansal1, this Court dealt with Section 19 of the Prevention of Money Laundering Act, 2002 (for\n"
          "short, ‘the PMLA’). Section 19 reads thus:\n“19. Power to arrest.—(1) If the Director, Deputy Director, Assistant Director or any other officer authorised in this behalf by the Central Government by general or\n"
          "special order, has on the basis of material in his possession, reason to believe that any person has been guilty of an offence punishable under this Act, he may arrest such person.")
C19P = ctx_for("pmla_2002", "PMLA", "19", "Prevention of Money-laundering Act")
check(T._off_statute(VIHAAN, C19) is not None and T._off_statute(VIHAAN, C19P) is None, "Vihaan Kumar (section 19 of the PMLA): left out for the Prevention of Corruption Act's section 19, kept for the PMLA's own section 19")
check("cites section 19 of Prevention of Money Laundering Act, 2002" in (T._off_statute(VIHAAN, C19) or ""), f"...by the explicit name, with the bare 'Section 19 reads thus' inheriting it ({T._off_statute(VIHAAN, C19)!r})")
ONLY_A = T.make_statute_context([{"act": "X Act", "aliases": None, "sections": {"19": "Short title."}}])           # a section too short to be a yardstick: only an explicit name can leave a passage out
near = "Section 19 of the Prevention of Money Laundering Act, 2002 is the power to arrest." + " The Court then turned to the facts of the arrest and the order of remand." * 20 + " Section 19 was not complied with."
far = "Section 19 of the Prevention of Money Laundering Act, 2002 is the power to arrest." + " The Court then turned to the facts of the arrest and the order of remand." * 40 + " Section 19 was not complied with."
def gap(txt):
    r = [x for x in T._section_refs(txt) if x[0] == "19"]
    return r[1][1] - r[0][2]


check(gap(near) <= T.FILTER_ANAPHORA < gap(far), f"the two test passages straddle the window ({gap(near)} and {gap(far)} characters apart; the window is {T.FILTER_ANAPHORA})")
check(T._off_statute(near, ONLY_A) is not None, "a bare repeat within the window of the last mention inherits the tie: the passage is left out")
check(T._off_statute(far, ONLY_A) is None, "a bare repeat beyond the window does not: with an explicit name for only one of the two references the passage is not left out")
slide = "Section 19 of the Prevention of Money Laundering Act, 2002 is the power to arrest." + " The Court then turned to the facts of the arrest and the order of remand." * 20 + " Section 19 was not complied with." + " The Court then turned to the facts of the arrest and the order of remand." * 20 + " Section 19 is mandatory."
check(T._off_statute(slide, ONLY_A) is not None, "the window slides: a second bare repeat 1,500 characters after the first repeat still inherits")
PRABIR13 = ("2. The appellant was arrested by the Special Cell, Lodhi Colony, New Delhi for the offences punishable under Sections 13, 16, 17, 18, 22C of the Unlawful Activities(Prevention) Act,\n"
            "1967(for short “UAPA”) read with Section 120B IPC, and the Court examined the grounds of arrest at length in this appeal.")
check("Unlawful Activities(Prevention) Act, 1967" in (T._off_statute(PRABIR13, C13) or ""), f"UAPA written with a bracket inside its name is recognised ({T._off_statute(PRABIR13, C13)!r})")
RPWD = "The petitioner seeks directions to mandate full accessibility of prisons in Tamil Nadu as required under Section 45 read with Section 40 of the RPwD Act, 2016, Rule 15 of the Rights of Persons with Disabilities Rules, 2017."
check("RPwD Act, 2016" in (T._off_statute(RPWD, C45P) or ""), f"'Section 45 read with Section 40 of the RPwD Act': both numbers are the RPwD Act's ({T._off_statute(RPWD, C45P)!r})")
PMLA_ACR = "... and the statutory mandate under Section 19(1) PMLA.” (emphasis added) The Court also noted the safeguards that apply when a person is arrested."
check("PMLA" in (T._off_statute(PMLA_ACR, C19) or ""), f"an acronym with no 'of' and a full stop after it ('Section 19(1) PMLA.') is recognised ({T._off_statute(PMLA_ACR, C19)!r})")
OWN7 = "3 registered by the Anti-Corruption Bureau, Panchkula, Haryana, under Sections 7, 8, 11 and 13 of the Prevention of Corruption Act, 1988, read with Section 120B IPC for the offence of taking a bribe."
check(T._off_statute(OWN7, C13) is None, "a passage that names the Act itself ('Sections 7, 8, 11 and 13 of the Prevention of Corruption Act, 1988') is kept")
OWNDOWRY = "The petitioners are accused under Sections 498(A), 406, 504, 506 R/w Section 149 of Indian Penal Code and Sections 3 and 4 of Dowry Prohibition Act, and seek to quash the criminal proceedings."
check(T._off_statute(OWNDOWRY, CD3) is None, "'Sections 3 and 4 of Dowry Prohibition Act' is the Dowry Act's own: kept")
check(T._off_statute(OWNDOWRY, ctx_for("pmla_2002", "PMLA", "3", "Prevention of Money-laundering Act")) is not None, "...and left out for the PMLA's section 3")
import time
t0 = time.time()
for adversarial in ("Section 17 of " + "of and the for " * 400 + "Act", "Section 17 of the " + "Alpha of " * 300 + "Act", "Section 17 " + "read with Section 18 " * 300 + "of the X Act", "Sections " + ", ".join(str(i) for i in range(1, 400)) + " of the Land Acquisition Act"):
    T._off_statute(adversarial, CTXI)
check(time.time() - t0 < 5, f"adversarial text (long runs of small words, 300 'read with' links, 400 section numbers) is handled in {time.time() - t0:.1f} s")

# switch
os.environ["FEED_STATUTE_FILTER"] = "off"
check(T._filter_on() is False, "FEED_STATUTE_FILTER=off switches it off")
os.environ["FEED_STATUTE_FILTER"] = ' "OFF" '
check(T._filter_on() is False, "quotes and capitals are tolerated")
os.environ.pop("FEED_STATUTE_FILTER")
check(T._filter_on() is True, "on by default (it only acts when the shelf found an Act and the question names a section)")

# feed_block end to end: the search service is replaced by canned results
os.environ["SCI_SEARCH_MODE"] = "feed"
NAMES = {"radhy": "Sri Radhy Shyam (Dead) Through L.Rs. and others v. State of U.P. and others", "ram_singh": "State of Madhya Pradesh & Ors v. Shri Ram Singh", "sudhakar33": "State of Karnataka v. T.N. Sudhakar Reddy",
         "yunus": "Yunus Zia v. State of Karnataka & Anr", "naidu28": "Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr", "mayawati": "Ms. Mayawati v. Union of India & Ors"}


def results():
    out = []
    for i, k in enumerate(NAMES, 1):
        out.append({"rank": i, "doc": i, "case_name": NAMES[k], "date": "2011-04-15", "paragraph": str(i), "link": f"https://x/{i}.pdf", "link_kind": "open_bucket_pdf", "text": P[k], "name_to_review": False, "citations": {}})
    return out


T.search = lambda question, timeout=None, k=10, label="sci_search": {"results": results(), "as_of": "2026-08-12"}
T.reset()
T.set_statute_context(CTX)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    blk = T.feed_block(Q17)
out_txt = buf.getvalue()
check("Radhy Shyam" not in blk and "Ram Singh" in blk and "Sudhakar Reddy" in blk and "Mayawati" in blk and "Naidu" in blk and "Yunus Zia" in blk, "feed_block: the land-acquisition case is not in the block; the others are")
check(all("Radhy" not in c["case_name"] for c in T._LOCAL.cases) and len(T._LOCAL.cases) == 5, f"feed_block: nor in the list the page shows ({len(T._LOCAL.cases)} cases)")
line = [l for l in out_txt.splitlines() if l.startswith("SCI_FEED_FILTER ")]
rec = json.loads(line[0][len("SCI_FEED_FILTER "):]) if line else {}
check(len(line) == 1 and rec.get("dropped") and rec["dropped"][0]["case"].startswith("Sri Radhy Shyam") and "why" in rec["dropped"][0] and "Sri Radhy" in rec["dropped"][0]["case"], f"one SCI_FEED_FILTER log line names the case and the reason, never the passage ({line})")
check("SCI_FEED fed 5 case(s)" in out_txt, "the usual SCI_FEED line counts the five that were fed")
# off: the same results, nothing dropped
T.reset()
T.set_statute_context(CTX)
os.environ["FEED_STATUTE_FILTER"] = "off"
with contextlib.redirect_stdout(io.StringIO()):
    blk_off = T.feed_block(Q17)
check("Radhy Shyam" in blk_off and len(T._LOCAL.cases) == 6, "with the switch off the wider search is exactly as before (six cases)")
os.environ.pop("FEED_STATUTE_FILTER")
# no context (the shelf did not find an Act, or no section was named)
T.reset()
with contextlib.redirect_stdout(io.StringIO()):
    blk_none = T.feed_block(Q17)
check("Radhy Shyam" in blk_none and len(T._LOCAL.cases) == 6, "with no statute context nothing is left out")
# reset forgets the context
T.set_statute_context(CTX)
T.reset()
check(getattr(T._LOCAL, "statute_ctx", None) in (None, []), "reset() forgets the context of the previous question")

# chat_assistant publishes the context when the shelf handed over a named section
T.reset()
S._embed_query = like("PCACT", "17")
with contextlib.redirect_stdout(io.StringIO()):
    ms = CA._act_shelf_matches(Q17, Q17)
ctx2 = getattr(T._LOCAL, "statute_ctx", None) or []
check(ms and len(ctx2) == 1 and "17" in ctx2[0]["sections"], "chat_assistant._act_shelf_matches publishes the named section to the search tier")
T.reset()
Q_no = "A government clerk was arrested for taking a bribe. What should the family do?"
with contextlib.redirect_stdout(io.StringIO()):
    CA._act_shelf_matches(Q_no, Q_no)
check(not (getattr(T._LOCAL, "statute_ctx", None) or []), "a question that names no section publishes nothing")
os.environ["ACT_SHELF"] = "off"
T.reset()
with contextlib.redirect_stdout(io.StringIO()):
    CA._act_shelf_matches(Q17, Q17)
check(not (getattr(T._LOCAL, "statute_ctx", None) or []), "with ACT_SHELF off nothing is published (the whole thing does nothing)")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
