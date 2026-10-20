"""
test_act_directory.py -- the Act Directory (act_directory.py, acts_directory.json; 2026-10-16, plan: STATUTE_COVERAGE_PLAN.md step 1): signposts for the Acts whose text Recourse does not hold.
Data integrity; detection (named and phrase matches, 12+ natural questions for each of the five priority Acts, 3 for every other Act, and controls that must stay silent); the notice
(three kinds, link and review gating, escaping); the reviewer's stamps and the link check; chat_assistant._attach_act_notice and the prompt block; the page and WhatsApp.
No network, no model, no cost. Run: python -X utf8 test_act_directory.py
"""
import copy
import json
import os
import re
import sys
import tempfile
import types
import urllib.error

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ.pop("ACT_DIRECTORY", None)
os.environ.pop("REGISTER_HOOKS", None)
os.environ.pop("RESPONSE_STYLE", None)
os.environ.pop("SCOPE_GATE", None)

import act_directory as AD
import chat_assistant as CA
import whatsapp_formatter as WF

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "recourse_app.py")


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def ids(q):
    return [a["id"] for a in AD.detect(q)]


D = AD.load()
RAW = D["raw"]
ACTS = RAW["acts"]
PRIORITY = [a["id"] for a in ACTS if a.get("priority") == 1]

# ---------------------------------------------------------------- data integrity
check(RAW.get("schema") == 1 and len(ACTS) == 34, f"the directory holds 34 Acts ({len(ACTS)})")
check(len({a["id"] for a in ACTS}) == len(ACTS), "every id is unique")
check(PRIORITY == ["pc_act_1988", "pocso_act_2012", "uapa_1967", "pmla_2002", "sc_st_act_1989"], f"the five priority Acts are the ones the owner accepted ({PRIORITY})")
check(all(a.get("name") and a.get("short") and a.get("act_no") and a.get("aliases") for a in ACTS), "every entry has a name, a short name, an Act number and at least one alias")
check(all(a["pack"] == "none" for a in ACTS), "every entry says the library holds none of its text")
seen = {}
for a in ACTS:
    for x in [AD._norm(s) for s in a["aliases"] + a["phrases"]]:
        seen.setdefault(x, []).append(a["id"])
check(not {k: v for k, v in seen.items() if len(v) > 1}, "no alias or phrase belongs to two Acts")
check(all(len(k) >= 3 for k in seen), "no alias or phrase is shorter than three characters")
check(not ({"act", "the act", "code", "section", "court", "cpc", "hma", "nia", "it act", "ec act", "pc", "ed"} & set(seen)), "no ambiguous short form is an alias")
UUID_RE = re.compile(r"^https://indiacode\.gov\.in/items/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
check(all(UUID_RE.match(a["url"] or "") for a in ACTS), "every link is an indiacode.gov.in item link (the old-style www.indiacode.nic.in handles mean something else on the new system and are gone)")
check(all(not a.get("url_alt") for a in ACTS), "no alternative link is kept")
check(all(re.match(r"^\d{4}-\d{2}-\d{2} \(machine: India Code's own record matches on title, number and year\)$", a.get("url_checked") or "") for a in ACTS),
      "every link was checked by the machine against India Code's own record (title, Act number and year)")
check(all(isinstance(a.get("indiacode"), dict) and a["indiacode"].get("uuid") == UUID_RE.match(a["url"]).group(1) and a["indiacode"].get("title") and a["indiacode"].get("kind") in ("act", "repealed-stub")
          and f'{a["indiacode"]["act_number"]} of {a["indiacode"]["act_year"]}' == a["act_no"] and isinstance(a["indiacode"].get("repealed"), bool) for a in ACTS), "every entry carries India Code's own facts for its record, equal to the entry")
check(sorted(a["id"] for a in ACTS if a["indiacode"]["repealed"]) == ["crpc_1973", "evidence_act_1872", "income_tax_act_1961", "ipc_1860", "tada_1987"],
      "India Code itself lists exactly these five as repealed: the TADA (Act 30 of 2001), the IPC (45 of 2023), the CrPC (46 of 2023), the Evidence Act (47 of 2023) and the 1961 Income-tax Act (30 of 2025)")
check({a["id"]: a["indiacode"]["repealed_by"] for a in ACTS if a["indiacode"]["repealed"]} == {"tada_1987": "Act 30 of 2001", "ipc_1860": "Act 45 of 2023", "crpc_1973": "Act 46 of 2023", "evidence_act_1872": "Act 47 of 2023", "income_tax_act_1961": "Act 30 of 2025"},
      "and by which Act, as India Code's own record says")
check(all(a["status"]["text"] and a["status"]["reviewed"] is None for a in ACTS), "every status line is a draft with no reviewer stamp")
check(all(a["appeal"]["reviewed"] is None for a in ACTS) and sorted(a["id"] for a in ACTS if a["appeal"]["text"]) == ["nia_act_2008", "pc_act_1988", "pmla_2002", "pocso_act_2012", "sc_st_act_1989", "tada_1987", "uapa_1967"],
      "seven appeal-route drafts (the five priority Acts, TADA and the NIA Act), none confirmed")
check([a["id"] for a in ACTS if a["detect"] is False] == ["ipc_1860", "crpc_1973"], "the two repealed codes the concordance already handles are not detected (a notice would be noise)")
check(all(a["status"]["confidence"] in ("certain", "likely", "guessing") for a in ACTS), "every status draft carries the drafter's confidence")
check(all((a["status"].get("evidence") or "").strip() for a in ACTS) and all((a["appeal"].get("evidence") or "").strip() for a in ACTS if a["appeal"]["text"]) and all(a["appeal"]["confidence"] in ("certain", "likely") for a in ACTS if a["appeal"]["text"]),
      "every drafted line says what it rests on (what was read on India Code, and what is only recollection)")
check(all(("recollection" in a["status"]["evidence"] or "could not be read" in a["status"]["evidence"] or "not checked" in a["status"]["evidence"]) for a in ACTS if a["status"]["confidence"] == "likely")
      and all(a["status"]["evidence"].startswith(("India Code", "Section")) or "India Code" in a["status"]["evidence"] for a in ACTS if a["status"]["confidence"] == "certain"),
      "a 'likely' status line names what is recollection; a 'certain' one cites India Code")
# the status line must agree with India Code's own record (the guard against a drafting slip like 'eight years' for a section that says 'two')
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}


def ic_date(s):
    m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", (s or "").strip())
    if m:
        return (int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", (s or "").strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


bad_rep = [a["id"] for a in ACTS if (a["indiacode"]["repealed"] and not a["status"]["text"].startswith(("Repealed by", "No longer in force"))) or (not a["indiacode"]["repealed"] and not a["status"]["text"].startswith("In force"))]
check(not bad_rep, f"every status line agrees with India Code on 'repealed' or 'in force' ({bad_rep})")
bad_date, n_dates = [], 0
for a in ACTS:
    m = re.match(r"^In force since (\d{1,2}) (%s) (\d{4})" % "|".join(MONTHS), a["status"]["text"])
    if m:
        n_dates += 1
        if ic_date(a["indiacode"].get("enforced")) != (int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))):
            bad_date.append((a["id"], m.group(0), a["indiacode"].get("enforced")))
check(n_dates >= 15 and not bad_date, f"every 'In force since <date>' equals the enforcement date India Code gives ({n_dates} checked; mismatches {bad_date})")

# ---------------------------------------------------------------- detection: named and phrase matches
PC = [
    "Can a case under the Prevention of Corruption Act, 1988 be quashed by the High Court?",
    "My father, a government clerk, is accused under Section 7 of the PC Act. Is bail possible?",
    "What is the punishment under the P.C. Act for taking a bribe?",
    "Is sanction needed before prosecuting a public servant under the Prevention Of Corruption Act?",
    "pc act 1988 section 13 criminal misconduct meaning",
    "Section 17A of the Prevention of Corruption (Amendment) Act, 2018 asks for approval before an inquiry, right?",
    "The Anti Corruption Bureau registered a case against my brother. Can he get anticipatory bail?",
    "A police officer demanded a bribe from me to release my son. What can I do?",
    "He was caught accepting a bribe. What happens next?",
    "I am facing a corruption case as a village revenue officer.",
    "A disproportionate assets case was filed against my uncle, an engineer, by the vigilance department.",
    "Does my corruption trial have to finish within a fixed time?",
    "What are the bribery charges against a public servant who took money?",
    "He took a bribe of Rs 5000. Is that a bailable offence?",
]
POCSO = [
    "Is anticipatory bail available in a POCSO case?",
    "My son is accused under the POCSO Act. What is the first step?",
    "pocso act section 29 presumption",
    "Under the Protection of Children from Sexual Offences Act, can the accused get bail?",
    "Which court tries offences under the Protection of Children from Sexual Offences Act, 2012?",
    "Can a POCSO case be quashed after a compromise?",
    "A POCSO FIR was filed against our teacher; what happens now?",
    "Is the consent of a 17 year old relevant under POCSO?",
    "What is the age limit under Pocso?",
    "A Pocso complaint has been filed against my brother, can he be arrested immediately?",
    "Is a child sexual abuse case tried by a special court?",
    "The police registered a case on sexual offences against children. What are the accused's rights?",
]
UAPA = [
    "Can bail be granted under UAPA?",
    "My brother was arrested under the Unlawful Activities (Prevention) Act. What are his rights?",
    "UAPA section 43D(5) bail test",
    "How long can police custody last under the Unlawful Activities Prevention Act?",
    "uapa case anticipatory bail",
    "Is a UAPA FIR registered against my cousin for a social media post valid?",
    "Which court hears UAPA appeals?",
    "Is the chargesheet in a U.A.P.A. case due in 90 days?",
    "Under the Unlawful Activities (Prevention) Amendment Act, 2019 an individual can be declared a terrorist, right?",
    "What does the Unlawful Activities Prevention Act say about membership of a banned organisation?",
    "My father was booked under UAPA and the BNS. Will he get bail?",
    "Who investigates a UAPA offence?",
]
PMLA = [
    "Can the ED arrest me under PMLA without a notice?",
    "PMLA section 45 twin conditions for bail",
    "I am summoned under the Prevention of Money Laundering Act. Do I have to appear?",
    "pmla case anticipatory bail",
    "The Enforcement Directorate attached my house. What can I do?",
    "Is a money laundering case possible without a scheduled offence?",
    "Under the PML Act, can property be attached before trial?",
    "What is the maximum punishment under the Prevention of Money-laundering Act, 2002?",
    "My husband was arrested in a money laundering case; what are his rights?",
    "ED summons in a PMLA matter: can I take a lawyer along?",
    "Are PMLA offences cognizable?",
    "What is the Adjudicating Authority under PMLA?",
]
SCST = [
    "Is anticipatory bail barred under the SC/ST Act?",
    "A case under the SC ST Act was filed against my brother. What now?",
    "What does the Atrocities Act say about arrest without a preliminary enquiry?",
    "Scheduled Castes and the Scheduled Tribes (Prevention of Atrocities) Act, 1989 section 18A meaning",
    "Can a false SC/ST case be quashed?",
    "Which court hears cases under the Prevention of Atrocities Act?",
    "sc/st act bail rules for the accused",
    "Is caste abuse in a private place covered by the SC-ST Act?",
    "My neighbour filed an Atrocities Act case against me over a land dispute",
    "The Scheduled Castes and Scheduled Tribes (Prevention of Atrocities) Act: who investigates, the DSP?",
    "Section 3(1)(r) of the SC/ST Act",
    "What are the exclusive special courts under the SC/ST (Prevention of Atrocities) Act?",
]
PC += ["He is an engineer and was caught in an anti-corruption trap in 2019 under the Prevention of Corruption Act."]
SCST += ["After a fight over a drain, our neighbour filed a case saying my father abused him by caste inside the neighbour's own house.", "Is a caste slur said in anger enough for a case?"]
for aid, qs in (("pc_act_1988", PC), ("pocso_act_2012", POCSO), ("uapa_1967", UAPA), ("pmla_2002", PMLA), ("sc_st_act_1989", SCST)):
    wrong = [q for q in qs if aid not in ids(q)]
    check(len(qs) >= 12 and not wrong, f"{aid}: {len(qs)} natural questions, all found ({wrong[:2]})")

OTHERS = {
    "tada_1987": ["My brother was convicted by a TADA Designated Court. Can he appeal?", "tada case pending since 1993, what can be done", "Is the Terrorist and Disruptive Activities (Prevention) Act still in force?"],
    "nia_act_2008": ["Can the state police continue after the NIA Act transfer?", "What does the National Investigation Agency Act say about special courts?", "NIA Act section 21 appeal"],
    "arms_act_1959": ["He was caught with a country-made pistol. Which section of the Arms Act applies?", "Is a case under the Arms Act bailable?", "arms act licence expired, is carrying a gun an offence?"],
    "dowry_prohibition_act_1961": ["Is giving dowry also an offence under the Dowry Prohibition Act?", "A Dowry Act complaint was filed against my family.", "dowry prohibition act section 3 punishment", "My in-laws keep up a dowry demand of 5 lakhs. What can I do?"],
    "jj_act_2015": ["My son is 16 and was produced before the Juvenile Justice Board. What now?", "Can a child in conflict with law be tried as an adult under the JJ Act?", "Juvenile Justice Act bail for a minor"],
    "mv_act_1988": ["Drunk driving challan: is it bailable?", "Which section of the Motor Vehicles Act punishes driving without a licence?", "MV Act accident claim time limit"],
    "customs_act_1962": ["Customs officers seized my gold at the airport under the Customs Act. What can I do?", "customs act section 135 smuggling", "Is arrest under the Customs Act bailable?"],
    "cgst_act_2017": ["I was arrested under the CGST Act for fake invoices.", "cgst act section 132 punishment", "Can the CGST officer arrest without a warrant under the Central Goods and Services Tax Act?"],
    "essential_commodities_act_1955": ["He was booked under the Essential Commodities Act for stocking rice.", "essential commodities act bail", "Which court tries Essential Commodities Act cases?"],
    "itpa_1956": ["A case under the Immoral Traffic Prevention Act was registered against the hotel owner.", "ITPA section 3 brothel", "Suppression of Immoral Traffic in Women and Girls Act, old name?"],
    "posh_act_2013": ["Our Internal Complaints Committee is not formed. What does the POSH Act say?", "posh act complaint time limit", "Sexual Harassment of Women at Workplace Act applies to a college?"],
    "senior_citizens_act_2007": ["My in-laws filed a case under the Senior Citizens Act to evict me.", "senior citizens act maintenance tribunal order", "Maintenance and Welfare of Parents and Senior Citizens Act appeal"],
    "evidence_act_1872": ["Is a confession to a police officer admissible under the Indian Evidence Act?", "evidence act section 27 recovery", "Which provision of the Evidence Act covers dying declarations?"],
    "bsa_2023": ["Which section of the Bharatiya Sakshya Adhiniyam replaces Section 65B?", "bharatiya sakshya adhiniyam electronic evidence certificate", "Is Section 63 of the BSA 2023 certificate mandatory?", "Is a certificate under Section 63 BSA needed for CCTV footage?"],
    "cpc_1908": ["Which order of the Code of Civil Procedure deals with temporary injunction?", "code of civil procedure section 9", "Can the Code of Civil Procedure be applied in a family court?"],
    "contract_act_1872": ["Is a verbal agreement valid under the Indian Contract Act?", "contract act section 73 damages", "Void agreement under the Contract Act: examples?"],
    "tpa_1882": ["Is an unregistered gift deed valid under the Transfer of Property Act?", "transfer of property act section 54 sale", "Section 106 of the Transfer of Property Act notice period"],
    "hma_1955": ["Can I get a divorce under the Hindu Marriage Act after one year?", "hindu marriage act section 13B mutual consent", "Is a second marriage void under the Hindu Marriage Act?"],
    "hsa_1956": ["Do daughters get a share under the Hindu Succession Act?", "hindu succession act section 8 rules", "Hindu Succession Act coparcenary 2005 amendment"],
    "income_tax_act_1961": ["Notice under the Income Tax Act section 148, what to do?", "income-tax act section 276C offence", "Can the Income Tax Act be used to freeze my account?"],
    "companies_act_2013": ["Director disqualification under the Companies Act?", "companies act section 447 fraud punishment", "Can the Companies Act be used against a private company director for cheating?"],
    "consumer_protection_act_2019": ["I want to file a complaint in the consumer court for a defective phone.", "consumer protection act e-commerce rules", "Which consumer forum has jurisdiction for Rs 30 lakh?"],
    "limitation_act_1963": ["Limitation Act: is a claim for a loan barred after three years?", "limitation act section 5 condonation", "How does the Limitation Act treat acknowledgment of a debt?"],
    "child_marriage_act_2006": ["Can a child marriage be stopped by a court order before the wedding?", "Prohibition of Child Marriage Act, who can file a complaint?", "my cousin was married off at 16, is it a child marriage and voidable?", "child marriage prohibition officer powers"],
    "pcr_act_1955": ["Protection of Civil Rights Act section 7 punishment", "He was stopped from entering the temple, a case of practice of untouchability?", "PCR Act and SC ST Act, which applies?", "untouchability offences act, old name"],
    "pdpp_act_1984": ["A bus was burned during the bandh, which law is used: the Prevention of Damage to Public Property Act?", "pdpp act bail rules", "Damage to Public Property Act section 3 punishment", "He was arrested for damage to public property during the protest"],
    "muslim_women_act_2019": ["Muslim Women (Protection of Rights on Marriage) Act, 2019 section 4 punishment", "My husband said triple talaq on WhatsApp, what can I do?", "Is bail possible in a triple talaq case?", "talaq e biddat complaint by the wife"],
}
check(len(OTHERS) == 27 and set(OTHERS) | set(PRIORITY) == {a["id"] for a in ACTS if a["detect"]}, "the test set covers every detected Act")
bad = {a: [q for q in qs if a not in ids(q)] for a, qs in OTHERS.items()}
check(not any(bad.values()), f"3 natural questions for each of the other 27 Acts are all found ({ {k: v for k, v in bad.items() if v} })")

# how a match was made
check(AD.detect("My father is accused under the PC Act") == [{"id": "pc_act_1988", "short": "Prevention of Corruption Act, 1988", "how": "named"}], "a name gives how='named'")
check(AD.detect("I am facing a corruption case")[0]["how"] == "likely", "a phrase gives how='likely'")
check([a["how"] for a in AD.detect("corruption case and the POCSO Act")] == ["named", "likely"] and ids("corruption case and the POCSO Act") == ["pocso_act_2012", "pc_act_1988"], "a named Act comes before a likely one")
check(ids("He was arrested under UAPA and PMLA") == ["uapa_1967", "pmla_2002"] and ids("PMLA then UAPA") == ["pmla_2002", "uapa_1967"], "two named Acts come in the order the question names them")
check(len(AD.detect("UAPA, PMLA, POCSO and the TADA Act")) == AD.MAX_ACTS == 2, "never more than two Acts")
check(ids("Is the PC Act different from the pc act?") == ["pc_act_1988"], "the same Act twice is one Act")

# silence: no match is better than a wrong one
CONTROLS = [
    "Can the police arrest me for cheating without a warrant?",
    "What is the punishment for theft under BNS Section 303?",
    "My husband was arrested at night without a warrant. Is that legal?",
    "How long can the police keep me in custody before producing me before a magistrate?",
    "Can I get anticipatory bail under Section 482 of the BNSS?",
    "The police did not give me a copy of the FIR. What should I do?",
    "I was arrested for possession of ganja under the NDPS Act. What is Section 37?",
    "My cheque bounced and the bank gave a memo. What is the notice period under Section 138?",
    "Someone made a fake profile of me online. Is that Section 66D of the IT Act?",
    "My husband beats me. Can I get a protection order and stay in the shared household?",
    "My bank account was frozen by the police under Section 106 of the BNSS. What can I do?",
    "A senior colleague touched me inappropriately and he has been arrested.",
    "I was arrested under Section 420 of the IPC. Is that now Section 318 of the BNS?",
    "Section 438 of the CrPC is now which section?",
    "Police registered an FIR under the Indian Penal Code against my brother in 2019.",
    "Can a magistrate order further investigation after a chargesheet?",
    "He was carrying arms actually for a ceremony, nothing else.",
    "What is the difference between bailable and non-bailable offences?",
    "Is a confession before a police officer admissible?",
    "My neighbour threatens me. Can I file a complaint for criminal intimidation?",
    "A teacher touched my minor daughter inappropriately at school.",
    "Someone pointed a gun at me and threatened to kill me.",
    "The CPC says nothing about this.",
    "My HMA claim is pending.",
    "Nia filed a complaint at the police station.",
    "My divorce petition is pending in the family court and my husband wants maintenance.",
    "My husband divorced me and now refuses to pay maintenance under Section 144 of the BNSS.",
    "A mob damaged my private shop during the riot. Can I claim compensation?",
    "He was arrested for mischief after breaking a neighbour's wall.",
    "My sister got married at 19 against our wishes and we want to file a missing person complaint.",
    "I was refused entry to a private club and I want to know my rights.",
    "The IT Act says nothing about this.",
    "What is the EC Act?",
    "My PC acts up every day.",
    "Can the police take my phone during an investigation?",
    "What are my rights if I am summoned for questioning?",
    "How do I file a zero FIR?",
    "Is house arrest possible instead of custody?",
    "",
    None,
    123,
]
fired = {q: ids(q) for q in CONTROLS if isinstance(q, str) and ids(q)}
check(not fired, f"controls stay silent ({fired})")
check(AD.detect(None) == [] and AD.detect("") == [] and AD.detect(123) == [] and AD.detect("   ") == [], "bad input gives []")
check(ids("He was booked under Section 420 of the Indian Penal Code and Section 438 of the Code of Criminal Procedure") == [], "IPC and CrPC are directory entries but are never detected")

# the switch
os.environ["ACT_DIRECTORY"] = "off"
check(AD.detect("A POCSO case") == [] and AD.mode() == "off", "ACT_DIRECTORY=off: nothing is detected")
os.environ["ACT_DIRECTORY"] = ' "OFF" '
check(AD.detect("A POCSO case") == [], "quotation marks and capitals around the value are ignored")
os.environ["ACT_DIRECTORY"] = "names"
check(ids("A POCSO case") == ["pocso_act_2012"] and ids("I am facing a corruption case") == [], "ACT_DIRECTORY=names: names match, phrases do not")
os.environ["ACT_DIRECTORY"] = "banana"
check(AD.mode() == "on" and ids("I am facing a corruption case") == ["pc_act_1988"], "anything else means on")
os.environ.pop("ACT_DIRECTORY")

# a broken or missing file leaves the site as it was
check(AD.detect("A POCSO case", path="/nonexistent/acts.json") == [] and AD.load("/nonexistent/acts.json")["acts"] == [], "a missing data file gives no match and no error")
with tempfile.TemporaryDirectory() as tmp:
    bad_path = os.path.join(tmp, "bad.json")
    open(bad_path, "w").write("{not json")
    check(AD.detect("A POCSO case", path=bad_path) == [], "a broken data file gives no match and no error")

# ---------------------------------------------------------------- the notice
named = AD.detect("My father is accused under the PC Act")
likely = AD.detect("I am facing a corruption case")
n_open, n_ans, n_ref = AD.notice(named, "opened"), AD.notice(named, "answer"), AD.notice(named, "refusal")
check(n_open["text"].startswith("This question names the Prevention of Corruption Act, 1988. Recourse has not checked this area in depth and does not hold the text of that Act, so what follows rests only on what we could find; "
                                "please confirm it with a lawyer who handles this area before you rely on it."), "opened: names the Act and carries the same caution as the generic notice")
check(n_ans["text"].startswith("This question also names the Prevention of Corruption Act, 1988. Recourse does not hold the text of that Act, so the answer below does not rest on it."), "answer: an ordinary answer that also names the Act")
check(n_ref["text"].startswith("This question names the Prevention of Corruption Act, 1988. Recourse does not hold the text of that Act. Official text on India Code: "), "refusal: short")
check(AD.notice(likely, "opened")["text"].startswith("This question looks like it is about the Prevention of Corruption Act, 1988."), "a phrase match says 'looks like it is about', never 'names'")
check(AD.notice(likely, "answer")["text"].startswith("This question looks like it is about the Prevention of Corruption Act, 1988."), "the same for an ordinary answer, with no stray 'also' (staging 2026-10-17)")
two = AD.detect("corruption case and the POCSO Act")
check(AD.notice(two, "opened")["text"].startswith("This question names the Protection of Children from Sexual Offences Act, 2012 (POCSO) and looks like it is about the Prevention of Corruption Act, 1988. "
                                                   "Recourse has not checked this area in depth and does not hold the text of those Acts,"), "two Acts of different kinds: both said, plural wording")
check(AD.notice([], "answer") is None and AD.notice(named, "bogus") is None and AD.notice(None, "answer") is None, "no Act, or a wrong kind, gives no notice")
check(all("good law" not in n["text"].lower() for n in (n_open, n_ans, n_ref)), "the notice never says anything is good law")
check(n_open["acts"] == ["pc_act_1988"] and n_open["kind"] == "opened", "the notice carries the ids and the kind")

# the link: every link has been checked against India Code's own record, so the notice gives the Act's own link; an unchecked link falls back to the India Code home page
PCE = next(a for a in ACTS if a["id"] == "pc_act_1988")
POE = next(a for a in ACTS if a["id"] == "pocso_act_2012")
check(f"Official text on India Code: Prevention of Corruption Act, 1988: {PCE['url']}." in n_open["text"] and "search for the Act's name" not in n_open["text"], "checked link: the Act's own link, as text")
check(f'<a href="{PCE["url"]}">Prevention of Corruption Act, 1988</a>' in n_open["html"] and 'href="https://indiacode.gov.in/"' not in n_open["html"], "checked link: the Act's own link, as an anchor")
# status and appeal drafts are never shown
check(PCE["status"]["text"] not in n_open["text"] + n_open["html"] and PCE["appeal"]["text"] not in n_open["text"] + n_open["html"], "the draft status and appeal lines are not shown")

with tempfile.TemporaryDirectory() as tmp:
    unchecked = copy.deepcopy(RAW)
    for a in unchecked["acts"]:
        a["url_checked"] = None
    pu = os.path.join(tmp, "unchecked.json")
    json.dump(unchecked, open(pu, "w", encoding="utf-8"))
    AD.load(pu, refresh=True)
    un = AD.notice(AD.detect("the PC Act", pu), "opened", pu)
    check("indiacode.gov.in/" in un["text"] and "search for the Act's name" in un["text"] and PCE["url"] not in un["text"], "unchecked link: the home page, 'search for the Act's name', no Act link")
    check('<a href="https://indiacode.gov.in/">India Code</a>' in un["html"] and PCE["url"] not in un["html"], "unchecked link: one anchor on the home page in the HTML too")

    p = os.path.join(tmp, "acts.json")
    data = copy.deepcopy(unchecked)
    for a in data["acts"]:
        if a["id"] == "pc_act_1988":
            a["url_checked"] = "2026-10-20 (Mr. Advocate)"
            a["status"]["reviewed"] = {"by": "Mr. Advocate", "on": "2026-10-20"}
        if a["id"] == "pocso_act_2012":
            a["url_checked"] = "2026-10-20"
            a["appeal"]["reviewed"] = {"by": "Mr. Advocate", "on": "2026-10-20"}
    json.dump(data, open(p, "w", encoding="utf-8"))
    AD.load(p, refresh=True)
    one = AD.notice(AD.detect("the PC Act", p), "refusal", p)
    check(f"Official text on India Code: Prevention of Corruption Act, 1988: {PCE['url']}." in one["text"]
          and f'<a href="{PCE["url"]}">Prevention of Corruption Act, 1988</a>' in one["html"], "checked link: the Act's own link, as text and as an anchor")
    check(PCE["status"]["text"] in one["text"] and PCE["appeal"]["text"] not in one["text"], "a confirmed status line is shown, an unconfirmed appeal line is not")
    both = AD.notice(AD.detect("the PC Act and the POCSO Act", p), "refusal", p)
    check(f"Prevention of Corruption Act, 1988: {PCE['status']['text']}" in both["text"] and f"Protection of Children from Sexual Offences Act, 2012 (POCSO): {POE['appeal']['text']}" in both["text"],
          "with two Acts each confirmed line is prefixed with its Act")
    check(f"Official text on India Code: Prevention of Corruption Act, 1988: {PCE['url']}; Protection of Children from Sexual Offences Act, 2012 (POCSO): {POE['url']}." in both["text"],
          "two checked links are both given")
    mixed = AD.notice(AD.detect("the PC Act and the UAPA", p), "refusal", p)
    check("search for each Act's name" in mixed["text"] and PCE["url"] not in mixed["text"], "if any link is unchecked the notice falls back to the home page for all (never a half-verified list)")
    # escaping
    data2 = copy.deepcopy(RAW)
    for a in data2["acts"]:
        if a["id"] == "pc_act_1988":
            a["short"] = 'Corruption <script>alert(1)</script> Act'
            a["url"] = 'https://example.org/"onmouseover="x'
            a["url_checked"] = "2026-10-20"
            a["status"]["text"] = "In force <b>bold</b>"
            a["status"]["reviewed"] = {"by": "x", "on": "y"}
    p2 = os.path.join(tmp, "acts2.json")
    json.dump(data2, open(p2, "w", encoding="utf-8"))
    esc_n = AD.notice(AD.detect("the PC Act", p2), "refusal", p2)
    check("<script>" not in esc_n["html"] and "&lt;script&gt;" in esc_n["html"] and "<b>" not in esc_n["html"] and '"onmouseover' not in esc_n["html"] and "&quot;onmouseover" in esc_n["html"],
          "the HTML is escaped: names, status lines and links")
    AD.load(p, refresh=True)

# ---------------------------------------------------------------- the prompt block
blk = AD.prompt_block(named)
check(blk.startswith("\n\n## Acts named in the question that are not in the material\n") and "names the Prevention of Corruption Act, 1988" in blk and "do not state any section number, punishment, procedure or route of appeal of that Act from memory" in blk,
      "the prompt block names the Act and repeats the rule")
check("names or looks like it is about the Prevention of Corruption Act, 1988" in AD.prompt_block(likely) and "of those Acts" in AD.prompt_block(two) and AD.prompt_block([]) == "", "likely and plural wording; nothing when no Act is named")

# ---------------------------------------------------------------- the reviewer's stamps and the link check
with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "acts.json")
    json.dump(RAW, open(p, "w", encoding="utf-8"), indent=2)
    e = AD.confirm("pc_act_1988", "status", "Mr. Advocate", "2026-10-20", p)
    check(e["status"]["reviewed"] == {"by": "Mr. Advocate", "on": "2026-10-20"}, "confirm status records who and when")
    on_disk = json.load(open(p, encoding="utf-8"))
    check(next(a for a in on_disk["acts"] if a["id"] == "pc_act_1988")["status"]["reviewed"]["by"] == "Mr. Advocate" and next(a for a in on_disk["acts"] if a["id"] == "pocso_act_2012")["status"]["reviewed"] is None,
          "only that entry changed on disk")
    e = AD.confirm("pc_act_1988", "link", "Mr. Advocate", "2026-10-20", p)
    check(e["url_checked"] == "2026-10-20 (Mr. Advocate)", "confirm link sets url_checked")
    for args, why in ((("nope", "status", "x"), "an unknown id"), (("pc_act_1988", "colour", "x"), "an unknown field"), (("pc_act_1988", "status", ""), "no reviewer name"), (("arms_act_1959", "appeal", "x"), "an empty draft")):
        try:
            AD.confirm(*args, path=p)
            check(False, f"confirm refuses {why}")
        except (ValueError, KeyError):
            check(True, f"confirm refuses {why}")


class _Resp:
    def __init__(self, url, body, status=200):
        self._url, self._body, self.status = url, body, status

    def geturl(self):
        return self._url

    def read(self, n=-1):
        return self._body if isinstance(self._body, bytes) else self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_opener(table):
    seen = []

    def opener(req, timeout=15):
        url = req.full_url
        seen.append(url)
        r = table.get(url)
        if r is None:
            raise OSError("unreachable")
        if isinstance(r, Exception):
            raise r
        return r(url) if callable(r) else r
    opener.seen = seen
    return opener


def rec(uuid, title, number=None, year=None, collection="ACT", state="CENTRAL", repealed="false", handle="123456789/1", kind="item", withdrawn=False, in_archive=True, enacted=None, enforced=None):
    """An India Code item as the data API returns it (the fields the check reads)."""
    md = {"dc.title": [{"value": title}]}
    for k, v in (("dc.identifier.act_number", number), ("dc.date.act_year", year), ("dc.identifier.collection", collection), ("dc.identifier.state_name", state), ("dc.identifier.repealed", repealed),
                 ("dc.date.enact_date", enacted), ("dc.date.enforcement_date", enforced)):
        if v is not None:
            md[k] = [{"value": str(v)}]
    return {"uuid": uuid, "name": title, "handle": handle, "type": kind, "withdrawn": withdrawn, "inArchive": in_archive, "metadata": md}


def api(uuid):
    return f"{AD.IC_API}/core/items/{uuid}"


def j(obj):
    return json.dumps(obj)


U = {k: f"{n:08x}-0000-4000-8000-{n:012x}" for k, n in (("pc", 1), ("cg", 2), ("ua", 3), ("pm", 4), ("td", 5), ("po", 6))}
PCX = {"id": "pc_act_1988", "name": "The Prevention of Corruption Act, 1988", "act_no": "49 of 1988"}
PC_REC = rec(U["pc"], "The Prevention of Corruption Act, 1988", 49, 1988, handle="123456789/496166", enacted="1988-09-09", enforced="09-09-1988")

# --- the link forms that can be checked
check(AD._ic_ref("https://indiacode.gov.in/items/" + U["pc"]) == ("uuid", U["pc"]) and AD._ic_ref("https://indiacode.gov.in/act/" + U["pc"] + "/sections") == ("uuid", U["pc"])
      and AD._ic_ref("https://indiacode.gov.in/handle/123456789/496166") == ("handle", "123456789/496166") and AD._ic_ref("https://indiacode.gov.in/items/" + U["pc"].upper()) == ("uuid", U["pc"]),
      "a link is checked by the record it names: items/<uuid>, act/<uuid> or handle/123456789/<n> on indiacode.gov.in")
check(all(AD._ic_ref(u) is None for u in ("https://www.indiacode.nic.in/handle/123456789/1558", "https://indiacode.gov.in/", "https://indiacode.gov.in/collections/" + U["pc"], "https://example.org/items/" + U["pc"],
                                          "https://indiacode.gov.in/items/not-a-uuid", "", None)),
      "the old-style host, the home page, a collection, another site and a malformed id are not checkable links")

# --- identity: the record must BE this Act
def ident(entry, item):
    return AD._ic_identity(entry, item)[0]


check(ident(PCX, PC_REC) == "ok", "identity: the Act's own central record is ok")
info = AD._ic_identity(PCX, PC_REC)[2]
check(info == {"kind": "act", "title": "The Prevention of Corruption Act, 1988", "act_number": "49", "act_year": "1988", "uuid": U["pc"], "handle": "123456789/496166", "repealed": False, "repealed_by": None,
               "enacted": "1988-09-09", "enforced": "09-09-1988"}, "identity: the facts kept are India Code's own, dates in its own words")
check(AD._ic_identity(PCX, rec(U["pc"], "The Prevention of Corruption Act, 1988", 49, 1988))[2]["enforced"] is None, "identity: a record with no enforcement date keeps None, not an invention")
check(ident(PCX, rec(U["pc"], "The Prevention of Corruption Act, 1988", 49, 1988, state="Rajasthan")) == "failed", "identity: a state's version of the same Act is not this Act")
check(ident(PCX, rec(U["pc"], "The Prevention of Corruption (Amendment) Act, 2018", 49, 1988, collection="ACT_AMENDMENT", state=None)) == "failed", "identity: an amendment Act's record (it carries the parent's number and year) is not this Act")
check(ident(PCX, rec(U["pc"], "The Prevention of Corruption Act, 1988", 49, 1988, kind="collection")) == "failed" and ident(PCX, [1, 2]) == "failed" and ident(PCX, None) == "failed", "identity: a collection, a list or nothing is not an Act")
check(ident(PCX, rec(U["pc"], "The Prevention of Corruption Act, 1988", 49, 1988, withdrawn=True)) == "failed" and ident(PCX, rec(U["pc"], "The Prevention of Corruption Act, 1988", 49, 1988, in_archive=False)) == "failed", "identity: a withdrawn or unarchived record is not ok")
check(ident(PCX, rec(U["pc"], "The Prevention of Corruption Act, 1988", 50, 1988)) == "failed" and ident(PCX, rec(U["pc"], "The Prevention of Corruption Act, 1988", 49, 1989)) == "failed", "identity: the Act number and the year must both equal the entry's")
check(ident(PCX, rec(U["pc"], "The Prevention of Corruption Act, 1947", 49, 1988)) == "failed" and ident(dict(PCX, name="The Prevention of Corruption Act, 1947"), PC_REC) == "failed", "identity: the year inside the name must agree when both sides carry one")
check(ident(PCX, rec(U["pc"], "The Protection of Children from Sexual Offences Act, 2012", 32, 2012)) == "failed", "identity: another Act is not this Act")
check(ident(dict(PCX, act_no="not a number"), PC_REC) == "failed" and ident({"name": "x"}, PC_REC) == "failed", "identity: an entry with no usable Act number cannot be confirmed")
PMX = {"name": "The Prevention of Money-laundering Act, 2002", "act_no": "15 of 2003"}
check(ident(PMX, rec(U["pm"], "The Prevention of Money-Laundering Act, 2002", 15, 2003)) == "ok", "identity: capital letters and hyphens do not matter; an Act named for 2002 but numbered 15 of 2003 is ok")
JJX = {"name": "The Juvenile Justice (Care and Protection of Children) Act, 2015", "act_no": "2 of 2016"}
check(ident(JJX, rec(U["po"], "The Juvenile Justice (Care and Protection of Children) Act, 2015.", 2, 2016)) == "ok", "identity: India Code's trailing full stop does not matter")
TDX = {"name": "The Terrorist and Disruptive Activities (Prevention) Act, 1987", "act_no": "28 of 1987"}
stub_td = rec(U["td"], "The Terrorist and Disruptive Activities (Prevention) Act, 1987, 28 of 1987 (Rep., Act 30 of 2001)", collection=None, state=None, repealed=None)
st_, _d, info_td = AD._ic_identity(TDX, stub_td)
check(st_ == "ok" and info_td["kind"] == "repealed-stub" and info_td["repealed"] is True and info_td["repealed_by"] == "Act 30 of 2001" and info_td["act_number"] == "28" and info_td["act_year"] == "1987",
      "identity: a repealed Act's archive entry ('Name, N of YEAR (Rep., Act X of Y)') is ok and says which Act repealed it")
CRX = {"name": "The Code of Criminal Procedure, 1973", "act_no": "2 of 1974"}
check(ident(CRX, rec(U["ua"], "The Code of Criminal Procedure 1973, 02 of 1974 (Rep., Act 46 of 2023)", collection=None, state=None, repealed=None)) == "ok", "identity: no comma before the number and a leading zero are read correctly")
IPX = {"name": "The Indian Penal Code, 1860", "act_no": "45 of 1860"}
check(ident(IPX, rec(U["ua"], "The Indian Penal Code, 45 of 1860 (Rep., Act 45 of 2023)", collection=None, state=None, repealed=None)) == "ok", "identity: a name without a year on India Code's side matches the entry's name with one")
check(ident(IPX, rec(U["ua"], "The Indian Penal Code Amendment Act, 1872, 19 of 1872 (Rep., 1 of 1938)", collection=None, state=None, repealed=None)) == "failed", "identity: an amendment Act's archive entry is not the Act")
check(ident(IPX, rec(U["ua"], "Some Notice", collection="NOTIFICATION", state="CENTRAL")) == "failed", "identity: a notification is not an Act")

# --- one link: ok, failed (definitely not this Act) or unreachable (says nothing)
PCE_ = dict(PCX, url="x")
for desc, table_, want in (
    ("the right record", {api(U["pc"]): _Resp(api(U["pc"]), j(PC_REC))}, "ok"),
    ("a record that does not exist (404)", {api(U["pc"]): urllib.error.HTTPError(api(U["pc"]), 404, "Not Found", {}, None)}, "failed"),
    ("a 404 answered without an exception", {api(U["pc"]): _Resp(api(U["pc"]), "{}", 404)}, "failed"),
    ("a server error (503)", {api(U["pc"]): urllib.error.HTTPError(api(U["pc"]), 503, "Unavailable", {}, None)}, "unreachable"),
    ("a refusal (403, for example the sandbox's network policy)", {api(U["pc"]): urllib.error.HTTPError(api(U["pc"]), 403, "Forbidden", {}, None)}, "unreachable"),
    ("no connection", {}, "unreachable"),
    ("an answer that is not JSON", {api(U["pc"]): _Resp(api(U["pc"]), "<html>maintenance</html>")}, "unreachable"),
    ("another Act's record", {api(U["pc"]): _Resp(api(U["pc"]), j(rec(U["pc"], "The Arms Act, 1959", 54, 1959)))}, "failed"),
):
    st_, detail_, _ = AD._try_url("https://indiacode.gov.in/items/" + U["pc"], PCE_, make_opener(table_), 5)
    check(st_ == want, f"one link, {desc}: {want} ({st_}: {detail_[:60]})")
op_ = make_opener({f"{AD.IC_API}/pid/find?id=123456789/496166": _Resp(f"{AD.IC_API}/core/items/{U['pc']}", j(PC_REC))})
check(AD._try_url("https://indiacode.gov.in/handle/123456789/496166", PCE_, op_, 5)[0] == "ok" and op_.seen == [f"{AD.IC_API}/pid/find?id=123456789/496166"], "one link, a handle: resolved through the data API's handle lookup")
check(AD._try_url("https://www.indiacode.nic.in/handle/123456789/1558", PCE_, make_opener({}), 5)[0] == "failed", "one link, the old-style host: failed without any request")

# --- the whole directory: what is written, and what is never written
with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "acts.json")
    small = copy.deepcopy(RAW)
    small["acts"] = [a for a in small["acts"] if a["id"] in ("pc_act_1988", "cgst_act_2017", "uapa_1967", "pmla_2002", "tada_1987")]
    by_ = {a["id"]: a for a in small["acts"]}
    by_["pc_act_1988"].update(url="https://indiacode.gov.in/items/" + U["pc"], url_alt=None, url_checked=None)
    by_["cgst_act_2017"].update(url="https://indiacode.gov.in/items/" + U["cg"], url_alt="https://indiacode.gov.in/handle/123456789/111", url_checked=None)
    by_["uapa_1967"].update(url="https://indiacode.gov.in/items/" + U["ua"], url_alt=None, url_checked="2026-10-01 (Mr. Advocate)", indiacode={"title": "stale"})
    by_["pmla_2002"].update(url="https://indiacode.gov.in/items/" + U["pm"], url_alt=None, url_checked="2026-10-01 (machine: earlier)", indiacode={"title": "earlier"})
    by_["tada_1987"].update(url="https://indiacode.gov.in/items/" + U["td"], url_alt=None, url_checked=None)
    json.dump(small, open(p, "w", encoding="utf-8"), indent=2)
    before = open(p, encoding="utf-8").read()
    cg_rec = rec(U["cg"], "The Central Goods and Services Tax Act, 2017", 12, 2017, handle="123456789/496310")
    table = {
        api(U["pc"]): _Resp(api(U["pc"]), j(PC_REC)),
        api(U["cg"]): urllib.error.HTTPError(api(U["cg"]), 404, "Not Found", {}, None),
        f"{AD.IC_API}/pid/find?id=123456789/111": _Resp(f"{AD.IC_API}/core/items/{U['cg']}", j(cg_rec)),
        api(U["ua"]): _Resp(api(U["ua"]), j(rec(U["ua"], "The Arms Act, 1959", 54, 1959))),
        # pmla: no entry in the table -> no connection
        api(U["td"]): _Resp(api(U["td"]), j(stub_td)),
    }
    rows = AD.check_links(p, write=False, opener=make_opener(table), today="2026-10-20")
    res = {r[0]: r for r in rows}
    check({k: v[1] for k, v in res.items()} == {"pc_act_1988": "ok", "cgst_act_2017": "ok", "uapa_1967": "failed", "pmla_2002": "unreachable", "tada_1987": "ok"}, f"check-links: {({k: v[1] for k, v in res.items()})}")
    check(res["cgst_act_2017"][3] == "https://indiacode.gov.in/handle/123456789/111", "check-links: a record that is not there falls back to url_alt")
    check(open(p, encoding="utf-8").read() == before, "check-links without --write changes nothing")
    AD.check_links(p, write=True, opener=make_opener(table), today="2026-10-20")
    after = {a["id"]: a for a in json.load(open(p, encoding="utf-8"))["acts"]}
    note = "2026-10-20 (machine: India Code's own record matches on title, number and year)"
    check(after["pc_act_1988"]["url_checked"] == note and after["pc_act_1988"]["indiacode"] == dict(info, verified_on="2026-10-20"), "check-links --write: an ok link is stamped, with India Code's own facts and the date")
    check(after["cgst_act_2017"]["url"] == "https://indiacode.gov.in/handle/123456789/111" and after["cgst_act_2017"]["url_alt"] == "https://indiacode.gov.in/items/" + U["cg"] and after["cgst_act_2017"]["url_checked"] == note,
          "check-links --write: the working alternative is promoted")
    check(after["uapa_1967"]["url_checked"] is None and "indiacode" not in after["uapa_1967"], "check-links --write: a link that is definitely another Act loses its stamp (even a person's) and its stale facts")
    check(after["pmla_2002"]["url_checked"] == "2026-10-01 (machine: earlier)" and after["pmla_2002"]["indiacode"] == {"title": "earlier"}, "check-links --write: a link that could not be reached changes NOTHING (a dead connection never un-checks a link)")
    check(after["tada_1987"]["indiacode"]["kind"] == "repealed-stub" and after["tada_1987"]["indiacode"]["repealed_by"] == "Act 30 of 2001" and after["tada_1987"]["indiacode"]["repealed"] is True, "check-links --write: a repealed Act's facts are kept")
    check(after["tada_1987"]["status"] == by_["tada_1987"]["status"] and after["pc_act_1988"]["aliases"] == by_["pc_act_1988"]["aliases"], "check-links --write touches nothing but links and facts")

# ---------------------------------------------------------------- chat_assistant: the notice is attached, the log and the prompt carry the Act
Q_PC = "My father is accused under the PC Act. His lawyer says the trial can be stayed. Is that right?"
Q_PLAIN = "Can the police arrest me for cheating without a warrant?"
CA._open_topic_reset()
r = CA._attach_act_notice({"state": "single_match", "response_text": "x"}, question=Q_PC)
check(r["act_notice"]["kind"] == "answer" and r["act_notice"]["acts"] == ["pc_act_1988"], "an ordinary answer to a question that names the Act: kind 'answer'")
CA._open_topic_start(Q_PC, "reason")
r = CA._attach_act_notice({"state": "single_match", "response_text": "x"}, question=Q_PC)
check(r["act_notice"]["kind"] == "opened", "an answer to a question the topic bar was opened for: kind 'opened'")
r = CA._attach_act_notice({"state": "conflicting_matches"}, question=Q_PC)
check(r["act_notice"]["kind"] == "opened", "conflicting_matches counts as an answer")
CA._open_topic_reset()
for st_ in CA._REFUSAL_NOTE_STATES:
    r = CA._attach_act_notice({"state": st_}, question=Q_PC)
    check(r.get("act_notice", {}).get("kind") == "refusal", f"{st_}: kind 'refusal'")
for st_ in ("unrelated", "budget_paused", "error", None):
    r = CA._attach_act_notice({"state": st_}, question=Q_PC)
    check("act_notice" not in r, f"{st_}: left alone")
check("act_notice" not in CA._attach_act_notice({"state": "single_match"}, question=Q_PLAIN), "a question that names no such Act: nothing is added")
check("act_notice" not in CA._attach_act_notice({"state": "single_match"}, question="") and "act_notice" not in CA._attach_act_notice({"state": "single_match"}), "no question: nothing is added")
check(CA._attach_act_notice("not a dict", question=Q_PC) == "not a dict" and CA._attach_act_notice(None, question=Q_PC) is None, "bad input does not raise")
os.environ["ACT_DIRECTORY"] = "off"
check("act_notice" not in CA._attach_act_notice({"state": "single_match"}, question=Q_PC) and CA._acts_named(Q_PC) == [], "ACT_DIRECTORY=off: nothing is added")
os.environ.pop("ACT_DIRECTORY")

_core = CA._answer_question_core
try:
    CA._answer_question_core = lambda question, inline_domains=frozenset(): {"state": "adjacent_uncovered", "reasoning": "A special law."}
    out = CA._answer_question_inner("My brother was convicted by a TADA Designated Court.")
    check(out["state"] == "adjacent_uncovered" and out["act_notice"]["kind"] == "refusal" and out["act_notice"]["acts"] == ["tada_1987"], "_answer_question_inner: a refusal carries the Act notice")
    CA._answer_question_core = lambda question, inline_domains=frozenset(): {"state": "adjacent_uncovered", "reasoning": "A civil suit."}
    check(CA._answer_question_inner("My landlord won't return my deposit.") == {"state": "adjacent_uncovered", "reasoning": "A civil suit."}, "_answer_question_inner: a refusal about a question that names no such Act is unchanged")
finally:
    CA._answer_question_core = _core

# the prompt
sent = {}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Short answer.")], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
CA._open_topic_reset()
txt = CA.generate_grounded_response(Q_PC, "[BNSS Section 482]\nText.", matches=[])
check(txt and "## Acts named in the question that are not in the material" in sent["prompt"] and "names the Prevention of Corruption Act, 1988" in sent["prompt"]
      and sent["prompt"].index("Text.") < sent["prompt"].index("## Acts named in the question"), "the prompt gets the block, after the library material, for an ordinary question that names the Act")
check("## Hard rules (never break)" in sent["prompt"] and "Use ONLY the legal information given below" in sent["prompt"], "the Hard rules block is still in the prompt, unchanged")
sent.clear()
txt = CA.generate_grounded_response(Q_PLAIN, "[BNSS Section 35]\nText.", matches=[])
check(txt and "## Acts named in the question" not in sent["prompt"], "a question that names no such Act: the prompt is as before")
os.environ["ACT_DIRECTORY"] = "off"
sent.clear()
txt = CA.generate_grounded_response(Q_PC, "[BNSS Section 482]\nText.", matches=[])
check(txt and "## Acts named in the question" not in sent["prompt"], "ACT_DIRECTORY=off: the prompt is as before")
os.environ.pop("ACT_DIRECTORY")

# ---------------------------------------------------------------- WhatsApp
NOTE_OPEN = AD.notice(AD.detect(Q_PC), "opened")
NOTE_REF = AD.notice(AD.detect("My brother was convicted by a TADA Designated Court."), "refusal")
GENERIC = CA.OUTSIDE_SCOPE_NOTE
msgs = WF.format_answer_for_whatsapp({"state": "single_match", "response_text": "Short answer.\n\nMore.", "outside_scope_note": GENERIC, "act_notice": NOTE_OPEN})
check(msgs[0] == NOTE_OPEN["text"] and GENERIC not in msgs, "WhatsApp: the Act notice is the first message and REPLACES the generic notice (one notice, not two)")
msgs = WF.format_answer_for_whatsapp({"state": "single_match", "response_text": "Short answer.", "outside_scope_note": GENERIC})
check(msgs[0] == GENERIC, "WhatsApp: with no Act notice the generic notice is as before")
msgs = WF.format_answer_for_whatsapp({"state": "adjacent_uncovered", "reasoning": "A TADA appeal.", "act_notice": NOTE_REF})
check(len(msgs) == 3 and msgs[1] == NOTE_REF["text"] and msgs[2] == WF._CONSULT_LINE, "WhatsApp: a refusal gets the Act notice before the closing 'consult a lawyer' line")
msgs = WF.format_answer_for_whatsapp({"state": "adjacent_uncovered", "reasoning": "x", "act_notice": NOTE_REF, "register_notes": ["Case X was overruled."]})
check(len(msgs) == 4 and msgs[1] == NOTE_REF["text"] and msgs[2].startswith("*Currency notes*") and msgs[3] == WF._CONSULT_LINE, "WhatsApp: the Act notice comes first, then the currency notes, then the closing line")
check(WF.format_answer_for_whatsapp({"state": "unrelated", "act_notice": NOTE_REF}) == WF.format_answer_for_whatsapp({"state": "unrelated"}), "WhatsApp: 'unrelated' never shows it")
check(WF.format_answer_for_whatsapp({"state": "adjacent_uncovered", "reasoning": "x"}) == ["This looks like it's related to law, but it's outside what I can confidently answer right now.\n\nx", WF._CONSULT_LINE],
      "WhatsApp: a refusal without an Act notice is exactly as before")

# ---------------------------------------------------------------- the page
from streamlit.testing.v1 import AppTest

SEEN = {}


def stub(question, inline_domains=frozenset(), audience=None, channel=None):
    m = os.environ.get("TEST_MODE")
    if m == "opened_with_act":
        return {"state": "single_match", "response_text": "Short answer.", "matches": [], "situation_detected": False, "outside_scope_note": GENERIC, "act_notice": NOTE_OPEN}
    if m == "opened_plain":
        return {"state": "single_match", "response_text": "Short answer.", "matches": [], "situation_detected": False, "outside_scope_note": GENERIC}
    if m == "answer_with_act":
        return {"state": "single_match", "response_text": "Short answer.", "matches": [], "situation_detected": False, "act_notice": AD.notice(AD.detect(Q_PC), "answer")}
    if m == "refusal_with_act":
        return {"state": "adjacent_uncovered", "reasoning": "A TADA appeal.", "act_notice": NOTE_REF}
    if m == "refusal_plain":
        return {"state": "adjacent_uncovered", "reasoning": "A civil suit."}
    return {"state": "single_match", "response_text": "Short answer.", "matches": [], "situation_detected": False}


CA.answer_question = stub


def md_values(at):
    return [m.value for m in at.markdown]


def ask(mode):
    os.environ["TEST_MODE"] = mode
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.text_area(key="text").set_value("My father is accused under the PC Act").run()
    [b for b in at.button if "Check my situation" in b.label][0].click().run()
    return at


at = ask("opened_with_act")
vals = md_values(at)
check(not at.exception and any(f'<a href="{PCE["url"]}">Prevention of Corruption Act, 1988</a>' in v and "names the Prevention of Corruption Act, 1988" in v for v in vals), f"page: the Act notice is shown with the Act's own link (exception={at.exception})")
check(not any("has not checked in depth (Recourse is built around" in v for v in vals), "page: the generic notice is NOT shown next to it (one notice, not two)")
at = ask("opened_plain")
vals = md_values(at)
check(not at.exception and any("has not checked in depth (Recourse is built around" in v for v in vals) and not any("This question names" in v for v in vals), "page: with no Act notice the generic notice is shown, as before")
at = ask("answer_with_act")
vals = md_values(at)
check(not at.exception and any("This question also names the Prevention of Corruption Act, 1988." in v for v in vals), "page: an ordinary answer that names the Act shows the notice")
at = ask("refusal_with_act")
vals = md_values(at)
check(not at.exception and any("Recourse can't help with this one" in v for v in vals) and any("names the Terrorist and Disruptive Activities (Prevention) Act, 1987 (TADA)" in v and f'<a href="{next(a for a in ACTS if a["id"] == "tada_1987")["url"]}">' in v for v in vals),
      "page: the refusal is still shown, with the Act notice under it")
at = ask("refusal_plain")
vals = md_values(at)
check(not at.exception and any("Recourse can't help with this one" in v for v in vals) and not any("This question names" in v for v in vals), "page: a refusal without an Act notice is unchanged")
at = ask("answered")
vals = md_values(at)
check(not at.exception and not any("This question" in v and "names" in v for v in vals), "page: an ordinary answer is unchanged")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
