"""
test_passage_notes.py -- whose VOICE a wider-search passage is in (passage_notes.py; PASSAGE_NOTES=on|off, default off).

The owner's staging test of 2026-10-19 (section 17 of the Prevention of Corruption Act): paragraph 33 of "State of Karnataka v. T.N. Sudhakar Reddy" reports the HIGH COURT's four-step procedure and the answer used it as the
law (paragraph 45 says the High Court erred); paragraph 28 of "Nara Chandrababu Naidu" starts "I am of the opinion": one judge's opinion, which the answer called "the Supreme Court said".
The passages are the first 900 characters exactly as the owner's page showed them. Offline, free, no model. Run: python -X utf8 test_passage_notes.py
"""
import contextlib
import io
import json
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("PASSAGE_NOTES", "FEED_STATUTE_FILTER", "SCI_SEARCH_MODE", "GROUNDING_CHECKS", "ACT_SHELF"):
    os.environ.pop(_v, None)

import authorities_table as AT
import grounding_checks as GC
import passage_notes as N
import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


EX = {
    "sudhakar33": "33. Therefore, according to the High Court, the Superintendent of Police is not competent to pass an order under Section 17 of the PC Act until a formally registered FIR came into existence. In other words, registration of the FIR is sine qua non for issuance of an order to investigate the case. The High Court framed a four-step procedure: first, the police must verify the facts upon receiving the source information report; second, a preliminary inquiry is to be conducted by the police; third, the FIR is registered; ...",
    "sudhakar45": "45. As a consequence of the above discussion, we are convinced that the High Court erred in holding that the Superintendent of Police must first direct the registration of an FIR and only after it is registered, he would be competent to issue an order for investigation under Section 17 of the PC Act. This interpretation could be permissible only if the subordinates of the Superintendent of Police had a discretion to either comply with or disregard the latter’s directive to register the FIR. ...",
    "sudhakar27": "27. Thus, in our view the source information report dated 10th November, 2023, served as a critical piece of information which not only documented the financial discrepancies but also presented a clear, prima facie picture of disproportionate assets accumulated by the respondent but also demanded immediate and thorough investigative action. As we have noted above, the scope of preliminary inquiries is not to verify the absolute truthfulness of information, and it is only to ascertain whether a cognizable offence is disclosed or not therefrom. ...",
    "naidu28": "28. Having considered the different contours of Section 17A, I am of the opinion that Section 17A would be applicable to the offences under the PC Act as amended by the Amendment Act, 2018, and not to the offences existing prior to the said amendment. Even otherwise, absence of an approval as contemplated in Section 17A for conducting enquiry, inquiry or investigation of the offences alleged to have been committed by a public servant in purported exercise of his official functions or duties, would neither vitiate the proceedings nor would be a ground to quash the proceedings or the FIR ...",
    "naidu25": "25. Now I shall examine the legality of a proceeding which is started without complying with the requirement of previous approval under 572 Section 17A of the 1988 Act. In the case of Yashwant Sinha and Others -vs- Central Bureau of Investigation through its Director and Another [(2020) 2 SCC 338], a Bench of this Court comprising of three Hon’ble Judges, while dealing with power of review had also examined this question. The Bench was unanimous in rejecting the review plea. In a concurring judgment one of the Hon’ble Judges, (K. M. Joseh, J.) held:- “116. ...",
    "yashwant84": "84. In terms of Section 17A, no Police Officer is permitted to conduct any enquiry or inquiry or conduct investigation into any offence done by a public servant where the offence alleged is relatable to any recommendation made or decision taken by the public servant in discharge of his public functions without previous approval, inter alia, of the authority competent to remove the public servant from his Office at the time when the offence was alleged to have been committed. In respect of the public servant, who is involved in this case, it is clause (c), which is applicable. ...",
    "karnani33": "33. The contention that prior approval of investigation, as mandated under Section 17A of Prevention of Corruption Act, has not been obtained and thus, the proceedings initiated against Respondent No. 1 stand vitiated, has no legal or factual basis. Section 17A merely contemplates that police officers shall not conduct any enquiry, inquiry or investigation into any offence alleged to have been committed by a public servant where the alleged offence is relatable to any recommendation made or decision taken in discharge of official functions or duties, without the previous approval of the ...",
    "kishore18": "18. The Parliament again inserted Section 17A in the PC Act, 1988 w.e.f. 26.07.2018. This provision has continued to remain in the statute book. It also provided for sanction before prosecution but without any classification of Government servants. All Government servants of whatever category, class, or level, are provided protection under Section 17A of the PC Act, 1988. The said provision is reproduced hereunder: 17A. ...",
    "thommandru19": "19. Hence, all these decisions do not mandate that a Preliminary Enquiry must be conducted before the registration of an FIR in corruption cases. An FIR will not stand vitiated because a Preliminary Enquiry has not been conducted. The decision in Managipet (supra) dealt specifically with a case of Disproportionate Assets. ...",
    "aman74": "This is because, it is difficult to form an opinion conclusively at the stage of reading a first information report that the public servant is either in or not in possession of property disproportionate to the known sources of income of his/her. It would all depend on what is ultimately unearthed after the investigation is complete. ...",
    "ram_singh": "In Bhajan Lals case this Court had found on facts that the SP had passed the order mechanically and in a very casual manner regardless of the settled principles of law. The provisions of Section 17 of the Act had not been complied with. As earlier noticed the SP while authorising the SHO to investigate had made only endorsement to the effect please register the case and investigate. The SP was shown to be not aware either of allegations or the nature of the offences and the pressure of work-load requiring investigation by an Inspector. ...",
    "mayawati": "From the perusal of those orders, we are also satisfied that there could not have been any material before this Court about the disproportionate assets case of the petitioner beyond the Taj Corridor Project case and there was no such question or issue about disproportionate assets of the petitioner. In view of the same, giving any direction to lodge FIR relating to disproportionate assets case did not arise. 22) We finally conclude that anything beyond the Taj Corridor matter was not the subject-matter of reference before the Taj Corridor Bench. ...",
    "lokayukta11": "11. The order passed by Superintendent of Police reads as follows: “KARNATAKA LOKAYUKTA NO: KLA/PW/SP/City.Dn./99-2000 Superintendent of Police City Division, M.S. Buildings, Dr. Ambedkar Veedhi, Bangalore-560 001. Dated: 12th June, 2000. M E M 0 Sub: Possession of Disproportionate Assets to the known source of income by Sri. B. Srinivasa, Engineer-in-chief, Rural Development Engineering Department-reg. Ref: Report of Sri. M.D. Khalander Presently working as police Inspector, Police Wing, City Division, Karnataka Lokayukta. I have gone through the report of Sri. Md. ...",
    "yunus23": "23. There is no dispute that though these officers are on deputation, they are otherwise of the requisite rank as contemplated by Section 17 of the Prevention of Corruption Act, 1988 and that other formalities under that Act are satisfied for entrustment of duties under the Prevention of Corruption Act, 1988. Question is whether these police officers of the State can be invested with powers of investigation under Section 17 of the Prevention of Corruption Act, 1988 by the State under its statutory powers traceable to the same section?”",
    "radhy42": "42. In Esso Fabs Private Limited vs. State of Haryana (supra), the Court again dealt with the question whether the State was justified in invoking Section 17(1) and 17(4) and dispensing with the inquiry under Section 5-A and held: “53. Section 17, no doubt, deals with special situations and exceptional circumstances covering cases of “urgency” and “unforeseen emergency”. ...",
}
WANT = {"sudhakar33": ["lower_court"], "sudhakar45": ["lower_court_rejected"], "naidu28": ["one_judge"], "naidu25": ["one_judge"]}
for k, v in EX.items():
    got = N.kinds(v)
    check(got == WANT.get(k, []), f"the owner's passage '{k}': {got} (expected {WANT.get(k, [])})")

# the switch
check(N.enabled() is False, "PASSAGE_NOTES is off by default")
for v, want in (("on", True), (' "ON" ', True), ("1", True), ("off", False), ("banana", False), ("", False)):
    os.environ["PASSAGE_NOTES"] = v
    check(N.enabled() is want, f"PASSAGE_NOTES={v!r}: {want}")
os.environ.pop("PASSAGE_NOTES")

# other voices and the cases that must NOT be flagged
check(N.kinds("It was submitted on behalf of the appellant that the order of the High Court is illegal and that the High Court erred in refusing bail. The respondent opposed the plea.") == ["lower_court", "submission"],
      "a submission that says 'the High Court erred' is the party's view: 'submission' and 'lower_court', not 'lower_court_rejected'")
check(N.kinds("It was contended that the notice was defective. We reject that contention: in our view the notice satisfies the proviso.") == [], "a passage that records a contention and then decides it (We reject ... in our view) has the Court's own voice: no note")
check(N.kinds("The learned counsel for the appellant submits that the sentence is excessive.") == ["submission"], "counsel submits: submission")
check(N.kinds("The appellants contend that the trial court failed to consider the documents.", passage_type="reasoning") == ["lower_court", "submission"] or N.kinds("The appellants contend that the trial court failed to consider the documents.", passage_type="reasoning") == ["submission"], "a contention about a trial court is a submission")
check(N.kinds("The facts are brief. The deceased was last seen with the accused on the night of 4th May.", passage_type="argument") == ["submission"], "the search service's own 'argument' tag counts when the text does not show the Court's voice")
check(N.kinds("We hold that the accused is entitled to bail. The arguments advanced are rejected.", passage_type="argument") == [], "the 'argument' tag is overridden by 'We hold'")
check(N.kinds("One day, when my father was away, my brother, encouraged by my mother, started beating me with a cricket bat. I lost consciousness.") == [], "'my brother' in a narrative is not a judge speaking")
check(N.kinds("I have gone through the report of the Inspector and I order that a case be registered.") == [], "an officer's order quoted in a judgment ('I have gone through ... I order') is not a judge's opinion")
check(N.kinds("I have had the benefit of reading the draft judgment of my learned Brother and I respectfully agree with him.") == ["one_judge"], "'my learned Brother', 'I respectfully agree': one judge")
check(N.kinds("The High Court has jurisdiction under Article 226 to issue a writ.") == [], "'the High Court' with no reporting verb is not a report of a holding")
check(N.kinds("The Trial Court acquitted the accused. The High Court reversed the acquittal and convicted him under Section 302.") == [], "the plain history of a case (acquitted, reversed) names no reporting verb of the list: no note")
check(N.kinds("The High Court held that the accused could not be convicted on the sole testimony of the injured witness.") == ["lower_court"], "'the High Court held': a lower court's holding")
check(N.kinds("") == [] and N.kinds(None) == [] and N.kinds("   ") == [], "empty text: no kinds, no error")

# notes
check(N.prompt_note([]) == "" and N.page_note([]) == "" and N.prompt_note(["nonsense"]) == "", "no kinds: no note")
pn = N.prompt_note(["lower_court"])
check(pn.startswith("\n[Note by code") and "lower court" in pn and pn.endswith("]"), f"the prompt note for a lower court's view ({pn!r})")
check("NOT the law laid down" in N.prompt_note(["lower_court_rejected"]), "the note for a rejected view says it is not the law laid down")
check("ONE judge" in N.prompt_note(["one_judge"]) and "whole bench" in N.prompt_note(["one_judge"]), "the note for one judge's opinion says whose it is")
check("submitted" in N.prompt_note(["submission"]), "the note for a submission says so")
check(N.prompt_note(["lower_court", "submission"]).count("[Note by code") == 1 and "Also," in N.prompt_note(["lower_court", "submission"]), "two voices make one note")
check("Note by code" in N.INSTRUCTION and "never present a lower court" in N.INSTRUCTION, "the instruction to the model")
check(N.page_note(["one_judge"]).startswith("This passage is one judge") and "Supreme Court" in N.page_note(["lower_court"]), "the page notes are plain sentences")

# the answer-side check
check(N.overstated("In Nara Chandrababu Naidu v. State of Andhra Pradesh (2024), the Supreme Court said Section 17A applies only to offences after the 2018 amendment.", ["one_judge"]) is True, "'the Supreme Court said' about a one-judge passage: overstated")
check(N.overstated("In Nara Chandrababu Naidu v. State of Andhra Pradesh (2024), one judge said Section 17A applies only to offences after the 2018 amendment.", ["one_judge"]) is False, "'one judge said': fine")
check(N.overstated("The Court said so.", ["lower_court_rejected"]) is False, "a lower court's view that this Court rejected can be described as the Court's finding")
check(N.overstated("In X v. Y the High Court held that the SP must wait for the FIR.", ["lower_court"]) is False, "'the High Court held' is the right description")
check(N.overstated("In X v. Y the passage describes a High Court's four-step procedure.", ["lower_court"]) is False, "'the passage describes a High Court's ...' is fine")
check(N.overstated("The Supreme Court in X v. Y held that the SP must wait for the FIR.", ["lower_court"]) is True, "'the Supreme Court held' about a lower court's passage: overstated")
check(N.overstated("", ["one_judge"]) is False and N.overstated("the Supreme Court held", []) is False and N.overstated(None, None) is False, "empty input: no error")
check(N.overstated("In Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr (2024), one judge of the Supreme Court said that Section 17A applies only to later offences.", ["one_judge"]) is False, "'one judge of the Supreme Court said' already says whose voice it is")
check(N.overstated("In State of Karnataka v. T.N. Sudhakar Reddy (2025), the Supreme Court noted that the High Court held the SP must wait for the FIR.", ["lower_court"]) is False, "'the Supreme Court noted that the High Court held' is an accurate description of a lower court's view")
check(N.overstated("In State of Karnataka v. T.N. Sudhakar Reddy (2025), the Supreme Court held that the High Court must first register the FIR.", ["lower_court"]) is True, "'the Supreme Court held that the High Court must ...' presents the lower court's procedure as the law")
check(N.overstated("The Court below held that the sanction was valid.", ["lower_court"]) is False, "'the Court below held' is a lower court")
check(N.overstated("In X v. Y the Supreme Court observed that the appellant submitted the order was void.", ["submission"]) is False, "a sentence that already says it was a submission")
check(N.overstated("In X v. Y the Court held that no sanction was needed.", ["submission"]) is True, "'the Court held' about a submission passage")
check(N.overstated("The Supreme Court in State of Karnataka v. T.N. Sudhakar Reddy (2025) rejected the idea that the SP must first direct registration of an FIR.", ["lower_court"]) is True, "'the Supreme Court rejected ...' about a passage that only reports the High Court's view")
check(N.overstated("In X v. Y the Supreme Court upheld the argument that no sanction was needed.", ["submission"]) is True, "'the Supreme Court upheld the argument' about a submission passage")
check(N.overstated("In X v. Y the Supreme Court dismissed the appeal and the High Court order stands.", ["lower_court"]) is False, "a disposition ('dismissed the appeal') is not a claim about the passage's voice")
check(N.overstated("In X v. Y the Supreme Court held that no sanction was needed.", ["lower_court_rejected"]) is False and N.overstated("In X v. Y the Supreme Court held that no sanction was needed.", []) is False, "no flagged voice: never overstated")

# the sentence around a name
t1 = "Section 17 sets out the ranks. In Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr (2024), one judge said Section 17A is prospective. In Lalita Kumari v. Government of U.P. (2013), the Supreme Court held that an FIR must be registered."
sp = (t1.index("Nara"), t1.index("Nara") + len("Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr"))
sp2 = (t1.index("Lalita"), t1.index("Lalita") + len("Lalita Kumari v. Government of U.P."))
w1 = N._sentence(t1, sp, [sp2])
check("one judge said" in w1 and "Lalita" not in w1 and "Section 17 sets out" not in w1, f"the window is the case's own sentence, not the next case's ({w1!r})")
check(N.overstated(w1, ["one_judge"]) is False, "the next sentence's 'the Supreme Court held' (about another case) does not count against this case")
t2 = "In Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr (2024), the Supreme Court said Section 17A is prospective; in Lalita Kumari v. Government of U.P. (2013), one judge said otherwise."
sp3 = (t2.index("Nara"), t2.index("Nara") + len("Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr"))
w2 = N._sentence(t2, sp3, [])
check("the Supreme Court said" in w2 and "Lalita" not in w2, f"a semicolon ends the clause ({w2!r})")
t3 = "The Supreme Court in State of Karnataka v. T.N. Sudhakar Reddy (2025) held that the SP can act only after the FIR."
sp4 = (t3.index("State of"), t3.index("Reddy") + 5)
check(N.overstated(N._sentence(t3, sp4, []), ["lower_court"]) is True, "the court named BEFORE the case ('The Supreme Court in X v. Y held') is read too")
t4 = "- Naidu (2024): the Supreme Court said Section 17A is prospective\n- Lalita Kumari (2013): one judge said otherwise"
sp5 = (t4.index("Naidu"), t4.index("Naidu") + 5)
check("Lalita" not in N._sentence(t4, sp5, []), "a new line ends the item")

# answer_notes: every mention is read; the first may be innocent and a later one not
cs_ = [{"case_name": "Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr", "passage_kinds": ["one_judge"]}]
def loc_(t, n):
    i = t.find(n)
    return (i, i + len(n)) if i >= 0 else None
tt = ("The Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr (2024) decision is a split one, and one judge wrote that Section 17A is prospective. "
      "Later in the answer: Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr (2024) is where the Supreme Court held that Section 17A is prospective.")
check(len(N.answer_notes(tt, cs_, loc_)) == 1, "a later mention that overstates is found even when the first mention is fine")
check(N.answer_notes("Nothing about the case.", cs_, loc_) == [] and N.answer_notes("", cs_, loc_) == [] and N.answer_notes(None, None, None) == [], "no mention, empty, None: no notice, no error")
check(N.answer_notes(tt, cs_, lambda t, n: 1 / 0) == [], "a broken locator: no notice, no error")

# the case's own name as the subject of the verb ('Naidu says that ...')
t5 = "Even if 17A approval was missing, Nara Chandrababu Naidu says that alone would not vitiate the case."
sp6 = (t5.index("Nara"), t5.index("Nara") + len("Nara Chandrababu Naidu"))
w6, tail6 = N._sentence(t5, sp6, [], with_tail=True)
check(tail6.startswith(" says that alone") and N.overstated(w6, ["one_judge"], tail6) is True, f"'<case> says that ...' about a one-judge passage ({tail6!r})")
check(N.overstated(w6, ["one_judge"]) is False, "without the tail the same sentence is not judged (the court is not named)")
t6 = "If an SP did authorise investigation, even informally, T.N. Sudhakar Reddy (2025) treats that as sufficient without a strict FIR-first sequence."
sp7 = (t6.index("T.N."), t6.index("Reddy") + 5)
w7, tail7 = N._sentence(t6, sp7, [], with_tail=True)
check(N.overstated(w7, ["lower_court"], tail7) is True, f"'<case> (2025) treats that as sufficient' about a lower court's passage ({tail7[:40]!r})")
check(N.overstated(w7, ["lower_court_rejected"], tail7) is False and N.overstated(w7, [], tail7) is False, "when this Court rejected the lower court's view, or the passage is the Court's own, nothing to warn about")
t7 = "Nara Chandrababu Naidu v. State of Andhra Pradesh (2024) (from a wider search, not independently verified) is a split decision, and one judge wrote that Section 17A is prospective."
sp8 = (0, len("Nara Chandrababu Naidu v. State of Andhra Pradesh"))
w8, tail8 = N._sentence(t7, sp8, [], with_tail=True)
check(N.overstated(w8, ["one_judge"], tail8) is False, "a sentence in which the case is not the subject of a deciding verb")
t8 = "In Nara Chandrababu Naidu v. State of Andhra Pradesh (2024) (from a wider search, not independently verified) the court also found that approval was not needed."
sp9 = (t8.index("Nara"), t8.index("Nara") + len("Nara Chandrababu Naidu v. State of Andhra Pradesh"))
w9, tail9 = N._sentence(t8, sp9, [], with_tail=True)
check(N.overstated(w9, ["one_judge"], tail9) is False, "the lower-case 'the court also found' after the label is not the Supreme Court speaking (and no name-subject verb follows directly)")
cs2 = [{"case_name": "Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr", "passage_kinds": ["one_judge"]}]
check(len(N.answer_notes("Even if 17A approval was missing, Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr says that alone would not vitiate the case.", cs2, loc_)) == 1, "answer_notes catches the name-as-subject form")

# feed_block end to end, with the search service replaced by canned results
os.environ["SCI_SEARCH_MODE"] = "feed"
NAMES = {"sudhakar33": "State of Karnataka v. T.N. Sudhakar Reddy", "naidu28": "Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr", "ram_singh": "State of Madhya Pradesh & Ors v. Shri Ram Singh",
         "yashwant84": "Yashwant Sinha & Ors v. Central Bureau of Investigation Through Its Director & Anr"}


def canned():
    return [{"rank": i, "doc": i, "case_name": NAMES[k], "date": "2024-01-16", "paragraph": str(i), "link": f"https://x/{i}.pdf", "link_kind": "open_bucket_pdf", "text": EX[k], "name_to_review": False, "citations": {},
             "passage_type": "reasoning"} for i, k in enumerate(NAMES, 1)]


T.search = lambda question, timeout=None, k=10, label="sci_search": {"results": canned(), "as_of": "2026-08-12"}
Q = "Does section 17 require authorisation of a police officer not below the rank of SP to register a case of disproportionate assets?"
T.reset()
with contextlib.redirect_stdout(io.StringIO()):
    off_block = T.feed_block(Q)
check("Note by code" not in off_block and N.INSTRUCTION not in off_block and off_block.startswith(T.FEED_INSTRUCTION), "PASSAGE_NOTES off: the block is exactly as before (no note, no extra instruction)")
check(all(c.get("passage_note") is None and c.get("passage_kinds") == [] for c in T._LOCAL.cases), "PASSAGE_NOTES off: the case list carries no note")
os.environ["PASSAGE_NOTES"] = "on"
T.reset()
with contextlib.redirect_stdout(io.StringIO()):
    on_block = T.feed_block(Q)
parts = on_block.split("[WIDER SEARCH")
by_name = {p.split("]")[0].split(":", 1)[1].strip().split(" (")[0]: p for p in parts[1:]}
check(on_block.count("[Note by code") == 2, f"PASSAGE_NOTES on: exactly two passages get a note ({on_block.count('[Note by code')})")
check("lower court" in by_name["State of Karnataka v. T.N. Sudhakar Reddy"] and "ONE judge" in by_name["Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr"], "the High Court's passage and the one-judge passage carry their notes")
check("Note by code" not in by_name["State of Madhya Pradesh & Ors v. Shri Ram Singh"] and "Note by code" not in by_name["Yashwant Sinha & Ors v. Central Bureau of Investigation Through Its Director & Anr"], "the Court's own passages carry none")
check(N.INSTRUCTION in on_block and on_block.startswith(T.FEED_INSTRUCTION), "the instruction to follow the notes follows the standard feed instruction")
cs = {c["case_name"]: c for c in T._LOCAL.cases}
check(cs["State of Karnataka v. T.N. Sudhakar Reddy"]["passage_kinds"] == ["lower_court"] and "lower court" in (cs["State of Karnataka v. T.N. Sudhakar Reddy"]["passage_note"] or "") and cs["State of Madhya Pradesh & Ors v. Shri Ram Singh"]["passage_note"] is None, "the case list the page shows carries the plain-language note")

# attach(): the answer calls a flagged passage "the Supreme Court"
ans_bad = ("In Nara Chandrababu Naidu v. State of Andhra Pradesh (2024), the Supreme Court said Section 17A applies only to offences after the 2018 amendment. "
           "In State of Karnataka v. T.N. Sudhakar Reddy (2025), the Supreme Court held that the SP can act only after the FIR is registered.")
ans_ok = ("In Nara Chandrababu Naidu v. State of Andhra Pradesh (2024), one judge said Section 17A applies only to offences after the 2018 amendment. "
          "In State of Karnataka v. T.N. Sudhakar Reddy (2025), the passage describes a High Court's four-step procedure.")
GC.reset_notes()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    res = T.attach(Q, {"state": "single_match", "response_text": ans_bad})
notes = GC.pop_notes()
nd = [n for n in notes if "Naidu" in n]
sr = [n for n in notes if "Sudhakar" in n]
check(len(notes) == 2 and len(nd) == 1 and "one judge" in nd[0].lower() and len(sr) == 1 and "lower court" in sr[0], f"an answer that calls the flagged passages 'the Supreme Court' gets two notices ({notes})")
check("PASSAGE_NOTE_FLAG" in buf.getvalue() and "the Supreme Court said" in res["response_text"], "a log line; the answer text itself is untouched (but for the labels)")
GC.reset_notes()
with contextlib.redirect_stdout(io.StringIO()):
    T.attach(Q, {"state": "single_match", "response_text": ans_ok})
check(GC.pop_notes() == [], "an answer that describes them correctly gets no notice")
os.environ["PASSAGE_NOTES"] = "off"
GC.reset_notes()
with contextlib.redirect_stdout(io.StringIO()):
    T.attach(Q, {"state": "single_match", "response_text": ans_bad})
check(GC.pop_notes() == [], "with the switch off no notice")
os.environ.pop("PASSAGE_NOTES")

# the lawyers' table
row = AT.build([], [], [], [{"case_name": "Nara Chandrababu Naidu v. State of Andhra Pradesh & Anr", "date": "2024-01-16", "paragraph": "28", "passage_note": N.page_note(["one_judge"])}], lambda n, y, c: {"source": "none", "note": None})["wider"][0]
check("Reading note: This passage is one judge" in (row["status"] or ""), f"the lawyers' table carries the reading note ({row['status']!r})")
row2 = AT.build([], [], [], [{"case_name": "X v. Y", "date": "2024-01-16", "paragraph": "1"}], lambda n, y, c: {"source": "none", "note": None})["wider"][0]
check("Reading note" not in (row2["status"] or ""), "no note, no change to the table")

# the page
app = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "recourse_app.py"), encoding="utf-8").read()
check('j.get("passage_note")' in app and "esc(j[\"passage_note\"])" in app, "the page shows the plain-language note under the passage")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
