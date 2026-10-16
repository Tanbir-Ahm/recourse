"""
test_act_directory.py -- the Act Directory (act_directory.py, acts_directory.json; 2026-10-17, plan: STATUTE_COVERAGE_PLAN.md step 1): signposts for the Acts whose text Recourse does not hold.
Data integrity; detection (named and phrase matches, 12+ natural questions for each of the five priority Acts, 3 for every other Act, and controls that must stay silent); the notice
(three kinds, link and review gating, escaping); the reviewer's stamps and the link check; chat_assistant._attach_act_notice and the prompt block; the page and WhatsApp.
No network, no model, no cost. Run: python -X utf8 test_act_directory.py
"""
import copy
import json
import os
import sys
import tempfile
import types

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
check(RAW.get("schema") == 1 and len(ACTS) == 30, f"the directory holds 30 Acts ({len(ACTS)})")
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
check(all((a["url"] or "").startswith("https://") and ("indiacode.nic.in" in a["url"] or "indiacode.gov.in" in a["url"]) for a in ACTS), "every link is on India Code")
check(all(a.get("url_checked") is None for a in ACTS), "no link is marked checked yet (nothing could be opened from the build sandbox)")
check(all(a["status"]["text"] and a["status"]["reviewed"] is None for a in ACTS), "every status line is a draft with no reviewer stamp")
check(all(a["appeal"]["reviewed"] is None for a in ACTS) and sum(1 for a in ACTS if a["appeal"]["text"]) == 6, "six appeal-route drafts, none confirmed")
check([a["id"] for a in ACTS if a["detect"] is False] == ["ipc_1860", "crpc_1973"], "the two repealed codes the concordance already handles are not detected (a notice would be noise)")
check(all(a["status"]["confidence"] in ("certain", "likely", "guessing") for a in ACTS), "every status draft carries the drafter's confidence")

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
}
check(len(OTHERS) == 23 and set(OTHERS) | set(PRIORITY) == {a["id"] for a in ACTS if a["detect"]}, "the test set covers every detected Act")
bad = {a: [q for q in qs if a not in ids(q)] for a, qs in OTHERS.items()}
check(not any(bad.values()), f"3 natural questions for each of the other 23 Acts are all found ({ {k: v for k, v in bad.items() if v} })")

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
check(n_ref["text"].startswith("This question names the Prevention of Corruption Act, 1988. Recourse does not hold the text of that Act. Official text:"), "refusal: short")
check(AD.notice(likely, "opened")["text"].startswith("This question looks like it is about the Prevention of Corruption Act, 1988."), "a phrase match says 'looks like it is about', never 'names'")
check(AD.notice(likely, "answer")["text"].startswith("This question also looks like it is about the Prevention of Corruption Act, 1988."), "the same for an ordinary answer")
two = AD.detect("corruption case and the POCSO Act")
check(AD.notice(two, "opened")["text"].startswith("This question names the Protection of Children from Sexual Offences Act, 2012 (POCSO) and looks like it is about the Prevention of Corruption Act, 1988. "
                                                   "Recourse has not checked this area in depth and does not hold the text of those Acts,"), "two Acts of different kinds: both said, plural wording")
check(AD.notice([], "answer") is None and AD.notice(named, "bogus") is None and AD.notice(None, "answer") is None, "no Act, or a wrong kind, gives no notice")
check(all("good law" not in n["text"].lower() for n in (n_open, n_ans, n_ref)), "the notice never says anything is good law")
check(n_open["acts"] == ["pc_act_1988"] and n_open["kind"] == "opened", "the notice carries the ids and the kind")

# the link: the Act's own only once checked; otherwise the India Code home page
check("indiacode.gov.in/" in n_open["text"] and "search for the Act's name" in n_open["text"] and "indiacode.nic.in/handle" not in n_open["text"], "unchecked link: the home page, 'search for the Act's name', no Act link")
check('<a href="https://indiacode.gov.in/">India Code</a>' in n_open["html"] and "handle/123456789/1558" not in n_open["html"], "unchecked link: one anchor on the home page in the HTML too")
# status and appeal drafts are never shown
check("Amended by the Lokpal" not in n_open["text"] + n_open["html"] and "Special Judge" not in n_open["text"] + n_open["html"], "the draft status and appeal lines are not shown")

with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "acts.json")
    data = copy.deepcopy(RAW)
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
    check("Official text on India Code: Prevention of Corruption Act, 1988: https://www.indiacode.nic.in/handle/123456789/1558." in one["text"]
          and '<a href="https://www.indiacode.nic.in/handle/123456789/1558">Prevention of Corruption Act, 1988</a>' in one["html"], "checked link: the Act's own link, as text and as an anchor")
    check("Amended by the Lokpal and Lokayuktas Act, 2013" in one["text"] and "Special Judge" not in one["text"], "a confirmed status line is shown, an unconfirmed appeal line is not")
    both = AD.notice(AD.detect("the PC Act and the POCSO Act", p), "refusal", p)
    check("Prevention of Corruption Act, 1988: In force." in both["text"] and "Protection of Children from Sexual Offences Act, 2012 (POCSO): Appeals against a Special Court's judgment lie to the High Court" in both["text"],
          "with two Acts each confirmed line is prefixed with its Act")
    check("Official text on India Code: Prevention of Corruption Act, 1988: https://www.indiacode.nic.in/handle/123456789/1558; Protection of Children from Sexual Offences Act, 2012 (POCSO): https://www.indiacode.nic.in/handle/123456789/2079." in both["text"],
          "two checked links are both given")
    mixed = AD.notice(AD.detect("the PC Act and the UAPA", p), "refusal", p)
    check("search for each Act's name" in mixed["text"] and "handle/123456789/1558" not in mixed["text"], "if any link is unchecked the notice falls back to the home page for all (never a half-verified list)")
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
    for args, why in ((("nope", "status", "x"), "an unknown id"), (("pc_act_1988", "colour", "x"), "an unknown field"), (("pc_act_1988", "status", ""), "no reviewer name"), (("nia_act_2008", "appeal", "x"), "an empty draft")):
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
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_opener(table):
    def opener(req, timeout=15):
        url = req.full_url
        r = table.get(url)
        if r is None:
            raise OSError("unreachable")
        if isinstance(r, Exception):
            raise r
        return r(url) if callable(r) else r
    return opener


with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, "acts.json")
    small = copy.deepcopy(RAW)
    small["acts"] = [a for a in small["acts"] if a["id"] in ("pc_act_1988", "cgst_act_2017", "uapa_1967", "pmla_2002")]
    for a in small["acts"]:
        if a["id"] == "cgst_act_2017":
            a["url"], a["url_alt"] = "https://indiacode.gov.in/act/1f98f6d0-ec9d-42f0-bd50-dc34d25998e1", "https://www.indiacode.nic.in/handle/123456789/2250"
    json.dump(small, open(p, "w", encoding="utf-8"), indent=2)
    pc_url = next(a["url"] for a in small["acts"] if a["id"] == "pc_act_1988")
    cg_url, cg_alt = "https://indiacode.gov.in/act/1f98f6d0-ec9d-42f0-bd50-dc34d25998e1", "https://www.indiacode.nic.in/handle/123456789/2250"
    uapa_url = next(a["url"] for a in small["acts"] if a["id"] == "uapa_1967")
    pm_url = next(a["url"] for a in small["acts"] if a["id"] == "pmla_2002")
    table = {
        pc_url: _Resp(pc_url, "<html><title>India Code: Prevention of Corruption Act, 1988</title><body>Prevention of Corruption Act, 1988</body></html>"),
        cg_url: _Resp(cg_url, "<html><title>India Code</title><body><app-root></app-root></body></html>", 404),
        cg_alt: _Resp(cg_alt, "<html><title>India Code: Central Goods and Services Tax Act, 2017</title>The Central Goods and Services Tax Act, 2017</html>"),
        uapa_url: _Resp("https://www.indiacode.nic.in/", "<html>home</html>"),
        pm_url: _Resp(pm_url, "<html><title>India Code</title><app-root></app-root></html>"),
    }
    rows = AD.check_links(p, write=False, opener=make_opener(table), today="2026-10-20")
    res = {r[0]: r for r in rows}
    check(res["pc_act_1988"][1] == "ok" and res["pc_act_1988"][3] == pc_url, "check-links: a page that names the Act is ok")
    check(res["cgst_act_2017"][1] == "ok" and res["cgst_act_2017"][3] == cg_alt, "check-links: a 404 on the first url falls back to url_alt")
    check(res["uapa_1967"][1] == "failed" and "redirected" in res["uapa_1967"][2], "check-links: a redirect to another page (a retired site's home page) is a failure")
    check(res["pmla_2002"][1] == "ok (name not confirmed)", "check-links: a reachable client-rendered page is ok but says the name was not confirmed")
    check(json.load(open(p, encoding="utf-8"))["acts"][0]["url_checked"] is None, "check-links without --write changes nothing")
    AD.check_links(p, write=True, opener=make_opener(table), today="2026-10-20")
    after = {a["id"]: a for a in json.load(open(p, encoding="utf-8"))["acts"]}
    check(after["pc_act_1988"]["url_checked"] == "2026-10-20" and after["cgst_act_2017"]["url"] == cg_alt and after["cgst_act_2017"]["url_alt"] == cg_url and after["cgst_act_2017"]["url_checked"] == "2026-10-20"
          and after["pmla_2002"]["url_checked"] == "2026-10-20 (reachable only)" and after["uapa_1967"]["url_checked"] is None, "check-links --write: ok links stamped, the working alternative promoted, a failed link left unchecked")

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
check(not at.exception and any('<a href="https://indiacode.gov.in/">India Code</a>' in v and "names the Prevention of Corruption Act, 1988" in v for v in vals), f"page: the Act notice is shown with its link (exception={at.exception})")
check(not any("has not checked in depth (Recourse is built around" in v for v in vals), "page: the generic notice is NOT shown next to it (one notice, not two)")
at = ask("opened_plain")
vals = md_values(at)
check(not at.exception and any("has not checked in depth (Recourse is built around" in v for v in vals) and not any("This question names" in v for v in vals), "page: with no Act notice the generic notice is shown, as before")
at = ask("answer_with_act")
vals = md_values(at)
check(not at.exception and any("This question also names the Prevention of Corruption Act, 1988." in v for v in vals), "page: an ordinary answer that names the Act shows the notice")
at = ask("refusal_with_act")
vals = md_values(at)
check(not at.exception and any("Recourse can't help with this one" in v for v in vals) and any("names the Terrorist and Disruptive Activities (Prevention) Act, 1987 (TADA)" in v and '<a href="https://indiacode.gov.in/">' in v for v in vals),
      "page: the refusal is still shown, with the Act notice under it")
at = ask("refusal_plain")
vals = md_values(at)
check(not at.exception and any("Recourse can't help with this one" in v for v in vals) and not any("This question names" in v for v in vals), "page: a refusal without an Act notice is unchanged")
at = ask("answered")
vals = md_values(at)
check(not at.exception and not any("This question" in v and "names" in v for v in vals), "page: an ordinary answer is unchanged")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
