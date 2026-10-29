"""
test_landmark_anchors.py -- the landmark case fix (2026-10-29): verbatim excerpts of Sharad Birdhichand Sarda (1984) and Hanumant (1952) for a question about conviction on circumstantial evidence
(excerpt_anchors.py, topic "circumstantial_evidence", switch LANDMARKS) and the calls in chat_assistant.py, sci_search_tier.py, authorities_table.py.
Fully offline and free: no model, no network. Run: python -X utf8 test_landmark_anchors.py

The trigger is tested on three sets of questions (all written by Claude, none by a lawyer; review_results/2026-10-29_landmark_circumstantial/ in the research repository has them with their hashes):
set 1 was frozen and committed BEFORE any pattern existed, set 2 was written to attack the patterns and the patterns were then tuned on it, set 3 was written afterwards and run once.
The expected misses and false fires below are the measured ones: if a pattern change moves them, this test says so and the numbers in that folder's RESULTS.md must be redone.
"""
import hashlib
import json
import os
import re
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


SETS = json.loads(r"""{
 "set1": {
  "sha256": "283f2143507aac761010654ef9b8c358f73852b4a35d84ae19bbe1123ee55eef",
  "pos": [
   "Can a person be convicted on circumstantial evidence alone? What must the prosecution prove?",
   "What are the conditions for a conviction based solely on circumstantial evidence?",
   "Explain the five golden principles for circumstantial evidence in a murder trial.",
   "What is the panchsheel of proof in circumstantial evidence cases?",
   "Sharad Birdhichand Sarda v. State of Maharashtra - what did the Supreme Court hold?",
   "When can a court convict where the case rests entirely on circumstantial evidence?",
   "In a case based on circumstantial evidence, must the chain of circumstances be complete?",
   "Grounds of appeal against a murder conviction resting only on circumstantial evidence",
   "Does the prosecution have to exclude every hypothesis of innocence when the evidence is circumstantial?",
   "The High Court upheld a conviction founded on circumstantial evidence. What should the special leave petition argue?",
   "What is the standard of proof for circumstantial evidence in a criminal case?",
   "Is a false defence an additional link in the chain of circumstantial evidence?",
   "What does 'may be' as against 'must be' mean in the law on circumstantial evidence?",
   "How does a criminal court assess circumstantial evidence?",
   "What is the test laid down in Hanumant v. State of Madhya Pradesh for circumstantial evidence?",
   "Can a conviction rest on circumstantial evidence when no motive is proved?",
   "Is a conviction safe if the prosecution case is based only on circumstantial evidence and one link in the chain is missing?",
   "What must the prosecution establish before a court can convict on the basis of circumstantial evidence in a dowry death case?",
   "There is no eyewitness in my brother's murder case. Can he still be convicted?",
   "The police have no direct evidence against me, only circumstances. Can I be convicted?",
   "Can someone go to jail only on the basis of circumstantial evidence?",
   "Can the court punish a person if nobody saw the crime happen?",
   "My husband was convicted of murder though no one saw him do it. Is that legal?",
   "The police say a chain of circumstances proves my son killed his wife. Is that enough to convict him?",
   "Is circumstantial evidence enough to prove murder?",
   "Can a person be sentenced without any direct evidence?",
   "Can I be found guilty on suspicion and circumstances alone?",
   "No one saw who committed the crime. What does the prosecution need to prove to convict someone?",
   "Is it legal to convict a person when there is only circumstantial evidence and no witnesses?",
   "The case against my father is based only on circumstantial evidence. How strong is it?",
   "Can circumstantial evidence be used to convict someone of rape?",
   "If the prosecution has only circumstantial evidence, who gets the benefit of the doubt?",
   "My uncle was arrested for murder but the police have no eyewitness and no confession. Can the court still convict him?",
   "Can the court convict an accused when the entire case is circumstantial?",
   "circumstantial evidence pe conviction ho sakta hai kya?",
   "can court convict on circumstancial evidence",
   "conviction on circumstantial evidance - what are the rules",
   "convicted without any direct evidence, only a circumstantial case. what are my options",
   "what is chain of evidence in a circumstantial case and why must it be complete for conviction",
   "Is suspicion, however strong, enough to convict an accused?",
   "In a murder trial where nobody saw the killing, how does the court decide guilt?",
   "Can the accused be acquitted if the circumstances are consistent with innocence as well as guilt?"
  ],
  "neg": [
   "How do I get bail in a murder case?",
   "What is the punishment for murder under the Bharatiya Nyaya Sanhita?",
   "Can the police arrest me without a warrant for cheating?",
   "My cheque bounced, what should I do?",
   "What are the stages of a sessions trial?",
   "What is the limitation for filing a criminal appeal against conviction?",
   "How long can the police keep me in custody before producing me before a magistrate?",
   "Can the police search my house without a warrant?",
   "Is the testimony of a single eyewitness enough to convict an accused?",
   "Can a conviction be based on the testimony of a child witness?",
   "Is electronic evidence admissible without a certificate?",
   "What is the evidentiary value of a first information report?",
   "Can the court draw an adverse inference from the accused's silence?",
   "Can a confession made to a police officer be used against the accused?",
   "What are the grounds for quashing an FIR?",
   "How can I challenge a sentence that I think is too harsh?",
   "What is default bail and when does it arise?",
   "My trial has been going on for 9 years and the prosecution keeps asking for time. Can the case be closed because of the delay?",
   "The accused was not produced before the magistrate within 24 hours. What follows?",
   "Can an FIR be registered against a public servant without sanction?",
   "In what circumstances can the police arrest without a warrant?",
   "Under what circumstances can a court grant anticipatory bail?",
   "What mitigating circumstances can reduce a death sentence to life imprisonment?",
   "The circumstances of my arrest were illegal. Can I claim compensation?",
   "Because of my financial circumstances I cannot pay the fine. What can I do?",
   "What special circumstances allow parole to a convict?",
   "In what circumstances is a confession treated as voluntary?",
   "Does the family's circumstances matter to the Juvenile Justice Board?",
   "Can adultery be proved by circumstantial evidence in a divorce case?",
   "Can a will be proved by circumstantial evidence in a civil suit about property?",
   "Can an insurance company reject my claim on the basis of circumstantial evidence?",
   "Is circumstantial evidence enough to prove cruelty in a divorce petition?",
   "Can negligence be proved by circumstantial evidence in a motor accident claim?",
   "There was no eyewitness to the accident. Can my family still claim compensation from the insurer?",
   "There is no witness to the loan I gave my friend. Can I file a recovery suit?",
   "Can a tenant be evicted on the basis of circumstantial evidence of subletting?",
   "What is the difference between a primary and a secondary document under the evidence law?",
   "Is a dying declaration enough to convict?",
   "What is the burden of proof on the accused under section 106 of the Evidence Act?",
   "What does 'beyond reasonable doubt' mean?",
   "Can a hostile witness's evidence be relied upon?",
   "Can the court rely on the evidence of an accomplice?",
   "How do I register a trademark?",
   "What are the notice period rules for terminating an employee?",
   "How can a landlord evict a tenant?",
   "What is the procedure to file for divorce by mutual consent?",
   "How is income tax calculated on rental income?",
   ""
  ],
  "ambiguous": [
   "Is last seen together enough to convict a person of murder?",
   "What is the difference between direct and circumstantial evidence?",
   "Is recovery of the weapon at the accused's instance enough for conviction?",
   "Can DNA evidence alone convict a person?",
   "What is the relevance of the accused's conduct after the crime?",
   "Can a person be convicted on the basis of a dying declaration alone?",
   "What happens if the prosecution fails to prove motive?",
   "Is it necessary for the prosecution to prove every link in its case?"
  ],
  "misses": [],
  "false_fires": [],
  "ambiguous_fires": [
   "What is the difference between direct and circumstantial evidence?"
  ]
 },
 "set2": {
  "sha256": "b2223d89faf15d66b8ab3000b1997cf0d771bcdc55c1f0aa8e1147c9ab5853e4",
  "pos": [
   "Is a conviction possible when the prosecution relies on a series of circumstances rather than any one direct proof?",
   "Our lawyer says the case against my brother is all inference and no witness. Can the court send him to prison?",
   "How many links in the chain must be proved before the court can say the accused is guilty?",
   "In Sharad Sarda the Supreme Court talked about 'must be' and not 'may be'. What does it mean for my case?",
   "What are the Sarda principles on proof?",
   "The prosecution has only shown a series of facts that together point to the accused. Is that enough for a conviction?",
   "My son was convicted on last seen together and a recovery. Can we get that set aside on the ground that the chain is incomplete?",
   "Can the accused be convicted if every fact proved is also consistent with someone else having done it?",
   "What did the Supreme Court say in the Sharad Birdhichand Sarda case about a false defence?",
   "Is the five-point test for circumstantial cases still followed by the courts?",
   "my father is accused in a murder, there is no eye witness only some circumstances, can court convict",
   "No CCTV, no witness - only the circumstances. Can the court still convict him?",
   "Is it true that courts cannot convict on mere suspicion even in heinous crimes?",
   "Can a person be convicted of murder if the weapon was never found and nobody saw it?",
   "What is the legal test for conviction when the police have only inferences and no direct proof?",
   "Kya circumstantial evidence se saza ho sakti hai?",
   "Ground of appeal: the trial court convicted on an incomplete chain of circumstances.",
   "Circumstantial evidence of cruelty in a section 498A case - can it support a conviction?",
   "Does the prosecution have to prove every circumstance beyond reasonable doubt when there is no direct evidence?",
   "Can a murder accused be acquitted because the evidence against him is circumstantial?",
   "What did the Supreme Court say about hypotheses consistent with innocence?",
   "Is it legal for a court to hang someone on circumstantial evidence?",
   "The judge convicted my husband based on motive, last seen and recovery together. Are these circumstances enough?",
   "Can a woman be held guilty of killing her husband when nobody saw it and only the circumstances point to her?",
   "Explain the principle that the accused must be and not merely may be guilty before a court can convict.",
   "Can I be sentenced if all the police have is that I was seen near the place earlier that day?"
  ],
  "neg": [
   "Circumstances in which the accused may be released on bail in a murder case",
   "Is there a chain of command in the police that decides an arrest?",
   "What is the chain of custody of seized drugs under the NDPS Act?",
   "Can a person be convicted for murder if a witness turned hostile?",
   "There's no direct evidence of the loan, only WhatsApp messages. Can I get my money back?",
   "Without any direct evidence of cruelty, can my wife get a divorce?",
   "The accused says the circumstances forced him to steal out of hunger. Is hunger a defence?",
   "My lawyer says the evidence is circumstantial in my husband's insurance claim after his death.",
   "What are the stages of a murder trial in a sessions court?",
   "Explain the Panchsheel agreement between India and China.",
   "What are the five principles of Panchsheel in foreign policy?",
   "What is the golden rule of interpretation of statutes?",
   "Is the testimony of the investigating officer alone enough for conviction?",
   "Is a confession alone enough to convict an accused?",
   "Can I be convicted for something I did under duress?",
   "Suspicion of theft: can the shopkeeper detain me?",
   "Can the police arrest me merely on suspicion?",
   "Is a conviction for cheque bounce possible without a legal notice?",
   "Can the court rely on the circumstances of the case to reduce my sentence?",
   "There was no witness when I signed the agreement. Is it valid?",
   "No eyewitness saw the accident but there is CCTV. Can I claim from the insurance company?",
   "Chain of events leading to the accident: who is liable under motor vehicle law?",
   "Which evidence is better, direct or circumstantial, for proving a breach of contract?",
   "Can an employer dismiss an employee on circumstantial evidence of theft in a domestic inquiry?",
   "Can the Income Tax department assess me on circumstantial evidence?",
   "What are the grounds for anticipatory bail in a murder case?",
   "Is the FIR itself enough evidence to convict?",
   "Can a juvenile be tried as an adult for murder?",
   "What happens to a case when the main witness dies before the trial ends?",
   "How long does a sessions trial for murder usually take?",
   "Can I get compensation if the accused is acquitted?",
   "What is the difference between culpable homicide and murder?",
   "Is the post-mortem report binding on the court?",
   "When is a death sentence confirmed by the High Court?"
  ],
  "ambiguous": [
   "Is it possible to prove murder without finding the body?",
   "Does the benefit of the doubt apply when two explanations are possible on the evidence?",
   "Does the Customs department need direct evidence for a seizure or is circumstantial evidence enough?",
   "Is a person guilty of contempt if nobody saw him break the court's order?",
   "What is the evidentiary value of an extra-judicial confession?"
  ],
  "misses": [
   "Can the accused be convicted if every fact proved is also consistent with someone else having done it?",
   "Can I be sentenced if all the police have is that I was seen near the place earlier that day?"
  ],
  "false_fires": [],
  "ambiguous_fires": [
   "Does the Customs department need direct evidence for a seizure or is circumstantial evidence enough?",
   "Is a person guilty of contempt if nobody saw him break the court's order?"
  ]
 },
 "set3": {
  "sha256": "397d0011c9c32bb0112b10d62a98cfe032d5b542b22ac8b7224960df4d5bc4cc",
  "pos": [
   "Can the court convict my brother of murder when there is nothing but circumstantial evidence against him?",
   "What does the prosecution have to prove if it has no direct evidence and is relying on circumstances?",
   "A man was found dead and the police arrested the neighbour because they had quarrelled. There is no eyewitness. Can he be convicted?",
   "Is it enough for conviction that all the circumstances point towards the accused?",
   "Which Supreme Court judgment lays down the principles for convicting on circumstantial evidence?",
   "What are the golden rules a court must follow in a circumstantial evidence case?",
   "The High Court confirmed the death sentence in a case based only on circumstantial evidence. Is that permissible?",
   "If the circumstances proved are consistent with both guilt and innocence, what must the court do?",
   "Can false statements by the accused complete the chain of circumstances against him?",
   "What does 'proved beyond reasonable doubt' mean when the case depends on circumstantial evidence?",
   "My cousin is in jail for rape and murder although no one saw anything. How can the conviction be challenged?",
   "Do all the circumstances relied on by the prosecution have to be proved independently?",
   "Can an accused be convicted on suspicion if the motive is strong?",
   "How does a court decide guilt where there is only circumstantial proof and no confession?",
   "Explain the five conditions for a conviction on circumstantial evidence.",
   "Can a person be hanged on the basis of circumstantial evidence?",
   "In a dowry death case there is no direct evidence of cruelty. Can circumstantial evidence convict the husband?",
   "Is the chain of circumstances test applicable to cases under the POCSO Act as well?",
   "What was decided in Sharad Birdhichand Sarda about the standard of proof?",
   "If one link in the chain of circumstances is missing, can the accused still be convicted?",
   "Can the benefit of doubt be given where the case rests on circumstances alone?",
   "Without any eyewitness, how can the prosecution prove who killed the victim?",
   "Can we appeal a life sentence given only on circumstantial evidence?",
   "Is there a rule that circumstantial evidence must exclude every other reasonable explanation?",
   "What did the Supreme Court say about convicting an accused on the basis of circumstances in a murder where nobody saw the accused with the victim?"
  ],
  "neg": [
   "How can I get my security deposit back from my landlord?",
   "What is the procedure to obtain a succession certificate?",
   "Can my employer terminate me without notice during probation?",
   "What documents are needed to register a sale deed?",
   "My neighbour is playing loud music at night. Which law applies?",
   "Can the police refuse to register my FIR?",
   "What is the punishment for criminal breach of trust?",
   "Is it compulsory to give a statement to the police during investigation?",
   "How do I get anticipatory bail in a cheating case?",
   "What are the rights of an arrested woman at night?",
   "Can the court transfer my case to another city?",
   "Is a sting operation recording admissible as evidence?",
   "What is the difference between bailable and non-bailable offences?",
   "How long can police detain me before charge sheet is filed?",
   "A witness has turned hostile. What can the prosecution do?",
   "Can an accused be convicted on the basis of a retracted confession?",
   "Is it necessary for the prosecution to examine all the witnesses it has cited?",
   "Is the evidence of a police informer admissible?",
   "How is a conviction under the NDPS Act appealed?",
   "Can I withdraw my complaint after the chargesheet is filed?",
   "What happens if the investigating officer is transferred in the middle of the trial?",
   "Are the circumstances of the offender relevant at the sentencing stage?",
   "The court has fixed the case for final arguments. What does that mean?",
   "What is the evidentiary value of a medical report in a rape case?",
   "In what circumstances can a will be challenged?",
   "Can an insurance claim be rejected because there was no witness to the fire?",
   "My landlord says there is no direct evidence that I paid the rent. Can he evict me?",
   "Is a chain of title important when buying a flat?",
   "My husband says we should divorce because of my circumstances. What are my rights?",
   "I was arrested on suspicion of theft and released the next day. Can I sue the police?"
  ],
  "ambiguous": [],
  "misses": [
   "If the circumstances proved are consistent with both guilt and innocence, what must the court do?",
   "Do all the circumstances relied on by the prosecution have to be proved independently?",
   "Can the benefit of doubt be given where the case rests on circumstances alone?"
  ],
  "false_fires": [],
  "ambiguous_fires": []
 }
}""")
TRIAL_SHA = {"v1": "04e111b41ac9af86e7c2b3460f6180bed65e87afb37230455a8f524c1df2e842", "v3": "9011db01d02712c1017d95d099d9b2f471dd64fb15f9e5993155b68b79cf1acd"}
Q_OWNER = "Can a person be convicted on circumstantial evidence alone? What must the prosecution prove?"
Q_DELAY = "My trial has been going on for 9 years and the prosecution keeps asking for time. Can the case be closed because of the delay?"
L = E.LABEL_UNCONFIRMED
for k in ("ANCHORS", "LANDMARKS", "RESPONSE_STYLE", "SCI_SEARCH_MODE"):
    os.environ.pop(k, None)

# --- the switches: both off by default, each its own
check(E.landmarks_mode() == "off" and E.mode() == "off" and E.selected(Q_OWNER) == [] and E.block(Q_OWNER) == "" and E.applies(Q_OWNER) is False, "off is the default: nothing is selected and the prompt gets nothing")
for v in ("on", ' "on" ', "'ON'", "1", "true", "yes"):
    os.environ["LANDMARKS"] = v
    check(E.landmarks_mode() == "on", f"LANDMARKS={v!r} switches the landmark topics on")
for v in ("off", "banana", ""):
    os.environ["LANDMARKS"] = v
    check(E.landmarks_mode() == "off", f"LANDMARKS={v!r} leaves them off")
os.environ["ANCHORS"] = "on"
os.environ.pop("LANDMARKS", None)
check(E.selected(Q_OWNER) == [] and E.active_topics(Q_OWNER) == [] and E.block(Q_OWNER) == "", "ANCHORS on (as in production) does NOT switch the landmark topic on: merging the code changes nothing there")
check(len(E.selected(Q_DELAY)) == 2, "ANCHORS on still gives the two trial-delay anchors for a delay question")
os.environ["LANDMARKS"] = "on"
os.environ.pop("ANCHORS", None)
check(E.selected(Q_DELAY) == [] and len(E.selected(Q_OWNER)) == 2, "LANDMARKS on alone: the landmark topic works and the trial-delay topic stays off")
os.environ["ANCHORS"] = "on"

# --- the data
lm = [a for a in E.load() if a["topic"] == "circumstantial_evidence"]
ids = [a["id"] for a in lm]
check(ids == ["circumstantial_evidence_sharad_sarda", "circumstantial_evidence_hanumant"], f"two landmark anchors, the controlling one first ({ids})")
check(all((a.get("check") or {}).get("all_found") and a["status"] == "machine_checked" and not a.get("confirmed_by") and a["link"].startswith("https://api.sci.gov.in/jonew/judis/") for a in lm), "each passed the check against the court's PDF, is machine_checked, is not marked as confirmed by anyone, and links to the court's own copy")
check(all(a["check"]["segments_checked"] == sum(len(e["segments"]) for e in a["excerpts"]) and len(a["check"]["sha256"]) == 64 for a in lm), "the check covered every segment")
check(all(a.get("verify_options") and a["check"].get("options") == a["verify_options"] and "No word was ignored" in a["check"]["method"] for a in lm), "the check record says what printed furniture it looked past (old printed report)")
sarda, han = lm
check(sarda["citation"] == "(1984) 4 SCC 116" and sarda["date"] == "1984-07-17" and "three judges" in sarda["bench_note"] and sarda["case_name"] == "Sharad Birdhichand Sarda v. State of Maharashtra", "Sharad Birdhichand Sarda: name, citation, date and bench as the reports give them")
check(han["citation"] == "AIR 1952 SC 343" and han["date"] == "1952-09-23" and han["bench_note"] is None, "Hanumant: AIR citation, the date from the judgment's own text, and no bench (the archive header is wrong)")
check(all(e.get("paragraph") and e.get("paragraph_source") for a in lm for e in a["excerpts"]), "every excerpt has a paragraph number and the source of that number (no number is shown without one)")
check(len(sarda["excerpts"]) == 4 and [e["paragraph"] for e in sarda["excerpts"]] == ["152 to 154", "151, 159 to 161", "163", "179 and 180"], "the four Sharad Birdhichand Sarda excerpts and their paragraphs")
check(len(sarda["also_in"]) >= 6 and all(r["name"] and r["must_contain"] for r in sarda["also_in"]), "later Supreme Court judgments that quote the passages with their paragraph numbers are recorded")
every = " ".join(E.excerpt_text(e).lower() for a in lm for e in a["excerpts"])
check("good law" not in every, "no excerpt says that a case is good law")

# --- which questions: the three sets
for key in ("set1", "set2", "set3"):
    s = SETS[key]
    fires = [q for q in s["pos"] if E._circumstantial(q)]
    wrong = [q for q in s["neg"] if E._circumstantial(q)]
    amb = [q for q in s["ambiguous"] if E._circumstantial(q)]
    check(sorted(q for q in s["pos"] if q not in fires) == sorted(s["misses"]), f"{key}: the positives the test misses are exactly the measured ones ({len(s['pos']) - len(fires)} of {len(s['pos'])})")
    check(sorted(wrong) == sorted(s["false_fires"]) and sorted(amb) == sorted(s["ambiguous_fires"]), f"{key}: the negatives it wrongly catches are exactly the measured ones ({len(wrong)} of {len(s['neg'])}); ambiguous questions that fire: {len(amb)}")
check(len(SETS["set1"]["misses"]) == 0 and len(SETS["set1"]["false_fires"]) == 0, "set 1 (frozen before the patterns): every positive caught, no negative caught")
check(E._circumstantial(Q_OWNER), "the owner's own question (the staging question that started this) is covered")
check(not E._circumstantial("") and not E._circumstantial(None), "an empty question is not")
# civil settings: the words alone are blocked, a conviction in the question lets them through, and the named case or the five golden principles always count
check(not E._circumstantial("Can adultery be proved by circumstantial evidence in a divorce case?") and not E._circumstantial("Can an insurance company reject my claim on circumstantial evidence?"), "circumstantial evidence in a divorce or an insurance claim is not this topic")
check(E._circumstantial("Can a contract killer be convicted on circumstantial evidence?"), "a civil word inside a criminal question does not block it (strong criminal word)")
check(E._circumstantial("What are the five golden principles?") and E._circumstantial("Sharad Birdhichand Sarda v. State of Maharashtra") and not E._circumstantial("Explain the Panchsheel agreement between India and China."), "the case by name and the five golden principles count; the Panchsheel treaty does not")

# --- the prompt block
b = E.block(Q_OWNER)
check(b.startswith("\n\n## Verbatim Supreme Court excerpts") and "These excerpts bear on a question about proving guilt by circumstantial evidence in a criminal case." in b and "Antulay" not in b and "Kartar" not in b, "the block opens with its own subject and carries nothing of the trial-delay topic")
for a in lm:
    for e in a["excerpts"]:
        for seg in e["segments"]:
            check(seg.strip() in b, f"segment is in the block word for word: {seg[:60]!r}")
check("[VERBATIM EXCERPTS -- Sharad Birdhichand Sarda v. State of Maharashtra (1984), (1984) 4 SCC 116, decided 17 July 1984, a Bench of three judges: Fazal Ali, Varadarajan and Mukharji JJ.]" in b, "the head names the case, the year, the citation, the date and the bench")
check("[VERBATIM EXCERPTS -- Hanumant v. The State of Madhya Pradesh (1952), AIR 1952 SC 343, decided 23 September 1952]" in b, "Hanumant's head, with no bench")
check("paragraphs 152 to 154 of the SCC report" in b and "paragraphs 151, 159 to 161 of the SCC report" in b and "paragraph 163 of the SCC report" in b and "paragraphs 179 and 180 of the SCC report" in b and "paragraph 10 of the AIR report" in b, "each excerpt's paragraph is shown with the report it belongs to")
check("Their legal reading has NOT yet been confirmed by our reviewer." in b and f"put the words {L} right after its name" in b and "never say that a case is good law" in b, "unconfirmed: the model is told to label the cases and not to call them good law")
check("say in your opening that it can, but only if every one of the Bench's five conditions is met" in b and "numbered list" in b and "Do not describe the five conditions as a statute." in b, "the guidance: answer yes-but in the opening and give the five conditions as a numbered list")
check("a false defence or a false explanation cannot make up for a missing link" in b and "entitled to the benefit of doubt" in b and "suspicion, however great, cannot take the place of legal proof" in b, "and the three further points the excerpts make")
check("state the rule from that judgment first, and use a case from a wider search only for what these excerpts do not say" in b, "the rule is stated from the landmark first and the wider-search cases are for the rest")
check("direct evidence, motive, last seen together, recovery of articles, dying declarations" in b, "the model is told what these excerpts do NOT cover")
check(len(b) < 9500, f"the block stays small ({len(b)} characters)")
check(len(E.fed()) == 2 and E.case_names() == ["Sharad Birdhichand Sarda v. State of Maharashtra", "Hanumant v. The State of Madhya Pradesh"], "block() remembers what it handed over")
check(E.block("Can the police arrest me for cheating?") == "" and E.fed() == [], "a question on another subject gets no block and the memory is cleared")
# guidance is built only from what was handed over
partial = [dict(sarda, excerpts=[sarda["excerpts"][2]])]                      # only the 'two views' excerpt
check(E._circumstantial_guidance(partial) == "", "no guidance when the excerpts handed over do not hold the five conditions")
only_conditions = [dict(sarda, excerpts=[sarda["excerpts"][0]])]
g = E._circumstantial_guidance(only_conditions)
check("numbered list" in g and "false defence" not in g and "benefit of doubt" not in g and "suspicion" not in g, "with only the five conditions handed over, only they are described")
# the styles: v1/v2 get a longer word allowance for this multi-part answer, v3 and WhatsApp keep their own limits
import answer_style as AS
os.environ["RESPONSE_STYLE"] = "v1"
check("This is a multi-part question (the rule, its five conditions, what the Court adds): up to about 400 words are allowed" in E.block(Q_OWNER), "v1: about 400 words are allowed for this multi-part answer")
os.environ["RESPONSE_STYLE"] = "v3"
check("up to about 400 words" not in E.block(Q_OWNER), "v3 keeps its own length rules")
AS._LOCAL.channel = "whatsapp"
os.environ["RESPONSE_STYLE"] = "v1"
check("up to about 400 words" not in E.block(Q_OWNER), "WhatsApp keeps its character limit")
AS._LOCAL.channel = None
os.environ.pop("RESPONSE_STYLE", None)

# --- both topics at once: two sections, each with its own words
Q_BOTH = "My murder trial rests on circumstantial evidence and has been going on for 9 years and the prosecution keeps asking for time. Can I be convicted and can the case be closed?"
bb = E.block(Q_BOTH)
check(E.active_topics(Q_BOTH) == ["trial_delay", "circumstantial_evidence"] and bb.count("## Verbatim Supreme Court excerpts") == 2 and "Antulay" in bb and "panchsheel" in bb and len(E.fed()) == 4, "a question on both subjects gets both sections, trial delay first")

# --- the live trial-delay prompt must not change by accident (these hashes were taken from the code as it was before this change; the two outputs were also compared byte for byte)
os.environ.pop("LANDMARKS", None)
for style, want in TRIAL_SHA.items():
    os.environ["RESPONSE_STYLE"] = style
    check(hashlib.sha256(E.block(Q_DELAY).encode("utf-8")).hexdigest() == want, f"the trial-delay block under {style} is byte for byte what production runs")
os.environ.pop("RESPONSE_STYLE", None)
os.environ["LANDMARKS"] = "on"

# --- labelling the finished answer
def _lab(ans, q=Q_OWNER):
    E.block(q)
    return E.attach(q, {"state": "single_match", "response_text": ans})["response_text"]


o1 = _lab("Yes. In Sharad Birdhichand Sarda v. State of Maharashtra (1984) the Supreme Court set out five conditions. The Court drew them from Hanumant v. The State of Madhya Pradesh (1952).")
check(o1.count(L) == 2 and "(1984) " + L in o1 and "(1952) " + L in o1, f"each landmark case gets the label once, after its year ({o1.count(L)})")
o2 = _lab("In *Sharad Birdhichand Sarda v. State of Maharashtra* (1984) the Court set out five conditions, taken from *Hanumant v. State of Madhya Pradesh* (1952).")
check(o2.count(L) == 2 and "(1984) " + L in o2 and "(1952) " + L in o2, "names in italics: the label goes after the closing mark and the year")
o3 = _lab("In Sharad Birdhi Chand Sarda v. State of Maharashtra (1984) 4 SCC 116, the Court held X.")
check(o3.count(L) == 1 and "4 SCC 116 " + L in o3, "the archive's spelling 'Birdhi Chand': label after the citation")
o4 = _lab("The Supreme Court in Sharad Sarda (1984) held X.")
check(o4 == "The Supreme Court in Sharad Sarda (1984) " + L + " held X.", "the short name 'Sharad Sarda' (an alias listed in the data) and a year")
o4b = _lab("Sharad Birdhichand Sarda v. State of Maharashtra (1984) set out five conditions. Later the Court in Sharad Sarda (1984) applied them.")
check(o4b.count(L) == 1 and "State of Maharashtra (1984) " + L in o4b and "Sharad Sarda (1984) held" not in o4b and o4b.endswith("Sharad Sarda (1984) applied them."), "a case named in full and then by its short name is labelled once, at the first mention")
o4c = _lab("The Court in Sharad Sarda (1984) held X, as in Sharad Birdhichand Sarda v. State of Maharashtra (1984).")
check(o4c.count(L) == 1 and o4c.index(L) < o4c.index("as in"), "a short name that comes first takes the label, not the full name that follows")
o4d = _lab("The Supreme Court in Sarda (1984) held X.")
check(L not in o4d and E.cases()[0]["label"] == L, "a bare surname is not found in the text (a known limit); the sources box under the answer still carries the label")
check(E.names_in("The Supreme Court in Sharad Sarda (1984) held X.").count("Sharad Sarda") >= 1, "the 'not checked' sentence is told the short name is an anchor case")
o5 = _lab("In Sharad Birdhichand Sarda v. State of Maharashtra, AIR 1984 SC 1622 the Court held X.")
check(o5.count(L) == 1 and "AIR 1984 SC 1622 " + L in o5, "an AIR citation after a comma: label after it")
check(_lab(o1) == o1, "labelling twice adds nothing")
# the cases and the page
cs = E.cases()
check(len(cs) == 2 and cs[0]["case_name"].startswith("Sharad Birdhichand Sarda") and cs[0]["paragraph"] == "151, 152 to 154, 159 to 161, 163, 179 and 180" and cs[0]["label"] == L and cs[0]["link"].endswith("/9517.pdf"), "the result lists the anchors with the paragraphs in order, the label and the court's link")
check(cs[1]["paragraph"] == "10 (AIR report)" and cs[1]["excerpts"][0]["paragraph"] == "10 (AIR report)" and cs[0]["excerpts"][0]["paragraph"] == "152 to 154", "a paragraph of another report says so (AIR); an SCC paragraph is the bare number as before")
table = AT.build([], [], [], [], lambda n, y, c: {"source": "not_checked", "note": "x"}, anchors=cs)
md = AT.render_markdown(table)
check(len(table["anchors"]) == 2 and "(1984) 4 SCC 116" in md[0][1] and "/9517.pdf" in md[0][1] and "AIR 1952 SC 343" in md[0][1], "the table of authorities lists both with citation and link")

# the PDF and Word export (the page's own view -> answer_export, which proves its files complete) carry both cases
import datetime
import io
import answer_export as X
import answer_view as V
import docx as _docx
import pymupdf
_res = E.attach(Q_OWNER, {"state": "single_match", "audience": "layman", "response_text": "**Short answer**\nYes, but only if every one of five conditions is met.", "matches": []})
_when = datetime.datetime(2026, 10, 29, 9, 30, tzinfo=datetime.timezone.utc)
_doc = X.build_document([{"question": Q_OWNER, "view": V.build(_res), "answer_id": "RA-LM0001", "created_at": _when, "audience": "layman"}], generated_at=_when)
_pdf, _ip = X.export(_doc, "pdf")
_dx, _ix = X.export(_doc, "docx")
_pt = " ".join(re.sub(r"\s+", " ", p.get_text()) for p in pymupdf.open(stream=_pdf, filetype="pdf")).lower()
_dt = re.sub(r"\s+", " ", " ".join(p.text for p in _docx.Document(io.BytesIO(_dx)).paragraphs)).lower()
_need = [X.H_ANCHORS + X.ANCHORS_UNCONFIRMED, "Sharad Birdhichand Sarda", "(1984) 4 SCC 116", "paragraph 152 to 154", "paragraph 151, 159 to 161", "Hanumant", "AIR 1952 SC 343", "paragraph 10 (AIR report)", "panchsheel",
         "https://api.sci.gov.in/jonew/judis/9517.pdf", "https://api.sci.gov.in/jonew/judis/1154.pdf"]
check(_ip["ok"] is True and _ix["ok"] is True and all(re.sub(r"\s+", " ", n).lower() in _pt for n in _need), "the PDF export carries both cases, their citations, paragraphs, links and the unconfirmed notice (and proves itself complete)")
check(all(re.sub(r"\s+", " ", n).lower() in _dt for n in _need), "the Word export carries the same")

# --- the wider search does not hand the same judgments over a second time (the index spells them differently)
os.environ.update(SCI_SEARCH_MODE="feed", SCI_SEARCH_URL="http://127.0.0.1:9", SCI_SEARCH_TOKEN="t")
SARDA_IDX = {"rank": 1, "doc": 9517, "case_name": "Sharad Birdhi Chand Sarda v. State of Maharashtra", "date": "1984-07-17", "paragraph": "153", "link": "https://api.sci.gov.in/jonew/judis/9517.pdf", "link_kind": "court_archive_pdf", "text": "A close analysis of this decision would show that the following conditions must be fulfilled.", "name_to_review": False, "citations": {}}
HAN_IDX = {"rank": 2, "doc": 1154, "case_name": "Hanumant v. The State of Madhya Pradesh.Raojibhaithe State of Madhya Pra", "date": "1952-01-23", "paragraph": "10", "link": "https://api.sci.gov.in/jonew/judis/1154.pdf", "link_kind": "court_archive_pdf", "text": "It is well to remember that in cases where the evidence is of a circumstantial nature.", "name_to_review": False, "citations": {}}
OTHER = {"rank": 3, "doc": 55555, "case_name": "Padman Bibhar v. State of Odisha", "date": "2025-05-21", "paragraph": "10", "link": "https://x/5.pdf", "link_kind": "open_bucket_pdf", "text": "the facts so proved should unerringly point towards the guilt of the accused.", "name_to_review": False, "citations": {}}
calls = []


def fake_search(q, timeout=None, k=10, label="x"):
    calls.append(q)
    return {"results": [SARDA_IDX, HAN_IDX, OTHER]}


T.search = fake_search
T.reset()
E.block(Q_OWNER)
fb = T.feed_block(Q_OWNER)
check("Sharad Birdhi Chand Sarda" not in fb and "Hanumant" not in fb and "Padman Bibhar" in fb, "landmarks on: the two judgments are not fed again from the wider search (found by their court-archive id, whatever the index calls them); other cases still are")
check(T._anchor_doc_ids(Q_OWNER) == {9517, 1154}, "the ids come from the anchors' links")
os.environ["LANDMARKS"] = "off"
T.reset()
fb2 = T.feed_block(Q_OWNER)
check("Sharad Birdhi Chand Sarda" in fb2 and "Hanumant" in fb2, "landmarks off: the wider search feeds them as before")
os.environ["LANDMARKS"] = "on"
os.environ.pop("SCI_SEARCH_MODE")

# --- the call in generate_grounded_response, and the answer cache
sent = {}


class _Msgs:
    def create(self, **kw):
        sent["prompt"] = kw["messages"][0]["content"] if isinstance(kw["messages"][0]["content"], str) else json.dumps(kw["messages"][0]["content"])
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Short answer.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
E.reset()
txt = CA.generate_grounded_response(Q_OWNER, "[BNSS Section 346]\nLibrary text.", matches=[])
check(txt and "Verbatim Supreme Court excerpts" in sent["prompt"] and "panchsheel" in sent["prompt"] and sent["prompt"].index("Library text.") < sent["prompt"].index("Verbatim Supreme Court excerpts"), "the excerpts are put into the prompt after the library text")
sent.clear()
txt = CA.generate_grounded_response("Can police arrest me for cheating?", "[BNSS Section 35]\nArrest text.", matches=[])
check(txt and "Verbatim Supreme Court excerpts" not in sent["prompt"], "a question on another subject: nothing added")
os.environ["LANDMARKS"] = "off"
sent.clear()
txt = CA.generate_grounded_response(Q_OWNER, "[BNSS Section 346]\nLibrary text.", matches=[])
check(txt and "Verbatim Supreme Court excerpts" not in sent["prompt"], "switch off: nothing added")
os.environ["LANDMARKS"] = "on"
check(E.applies(Q_OWNER) is True, "a question that gets excerpts is generated fresh, never from the answer cache (applies() is what the cache check reads)")

# --- the full path: labels and the list ride on the result
CA._answer_question_core = lambda q, inline_domains=frozenset(): (E.block(q), {"state": "single_match", "response_text": "Yes. The Supreme Court in Sharad Birdhichand Sarda v. State of Maharashtra (1984) said so."})[1]
out = CA._answer_question_inner(Q_OWNER)
check(L in out["response_text"] and len(out.get("anchor_excerpts") or []) == 2, "through answer_question's inner path the answer is labelled and lists the excerpts")
nc = CA._attach_register_notes({"state": "single_match", "response_text": "In Sharad Birdhichand Sarda v. State of Maharashtra (1984) the Court held X. In Ram Prasad v. State of Bihar (2001) it held Z."}).get("register_not_checked") or ""
check("Ram Prasad" in nc and "Sharad" not in nc, f"the 'not checked' sentence names only the case that is neither an anchor nor a source ({nc!r})")

# --- a confirmed anchor needs no label
conf = json.load(open(E._PATH, encoding="utf-8"))
for a in conf["anchors"]:
    if a["topic"] == "circumstantial_evidence":
        a["status"], a["confirmed_by"], a["confirmed_on"] = "reviewer_confirmed", "Mr. Advocate", "2026-11-01"
import tempfile
tmp = os.path.join(tempfile.mkdtemp(), "excerpt_anchors.json")
json.dump(conf, open(tmp, "w", encoding="utf-8"))
saved = E.load
E.load = lambda path=None: saved(tmp)
bc = E.block(Q_OWNER)
check("Our reviewer has confirmed them." in bc and "put the words" not in bc, "confirmed: no label instruction and the block says the reviewer confirmed them")
check(E.attach(Q_OWNER, {"state": "single_match", "response_text": "In Sharad Birdhichand Sarda v. State of Maharashtra (1984) the Court held X."})["response_text"].count(L) == 0, "confirmed: the answer text is not labelled")
E.load = saved

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
