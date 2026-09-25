
"""
test_ndps_doctrine_map.py

Regression suite for ndps_doctrine_map.py -- the NDPS (Narcotic Drugs
and Psychotropic Substances Act, 1985) domain, built the same way as
domestic_violence_doctrine_map.py (see that module's test for the
template this follows). Same lightweight check()/FAILURES convention as
the rest of this repo's test_*.py files; run directly:
`python -X utf8 test_ndps_doctrine_map.py`. No API cost -- pure Python,
real local chunk files, no network.
"""
from ndps_doctrine_map import get_ndps_override

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- always-on foundational section ----

base = get_ndps_override("what is even illegal under this law")
sections = {m["section_number"] for m in base if m.get("act") == "NDPS"}
check(
    "8" in sections,
    "Section 8 (general prohibition) is always included, since any real question needs it",
)
check(
    all(m.get("source") == "curated_override" for m in base if m.get("act") == "NDPS"),
    "every statute anchor is tagged 'curated_override', matching the other domains' convention",
)

# ---- section-specific triggers ----

check(
    "37" in {m["section_number"] for m in get_ndps_override("can he get bail") if m.get("act") == "NDPS"},
    "Section 37 (bail) fires for a bail question",
)
check(
    "50" in {m["section_number"] for m in get_ndps_override("they never told me I could ask for a gazetted officer") if m.get("act") == "NDPS"},
    "Section 50 (search rights) fires for a 'right to be searched before a gazetted officer' question",
)
check(
    "20" in {m["section_number"] for m in get_ndps_override("they found ganja on him") if m.get("act") == "NDPS"},
    "Section 20 (cannabis) fires for a ganja question",
)
check(
    "21" in {m["section_number"] for m in get_ndps_override("he was caught with heroin") if m.get("act") == "NDPS"},
    "Section 21 (manufactured drugs) fires for a heroin question",
)
check(
    "27" in {m["section_number"] for m in get_ndps_override("it was just for personal use") if m.get("act") == "NDPS"},
    "Section 27 (consumption) fires for a personal-use question",
)
check(
    "43" in {m["section_number"] for m in get_ndps_override("they stopped him at a checkpost") if m.get("act") == "NDPS"},
    "Section 43 (seizure/arrest in public place) fires for a checkpost question",
)
check(
    "2" in {m["section_number"] for m in get_ndps_override("what counts as a commercial quantity") if m.get("act") == "NDPS"},
    "Section 2 (quantity definitions) fires for a 'what is commercial quantity' question",
)
check(
    "37" not in {m["section_number"] for m in get_ndps_override("what is even illegal under this law") if m.get("act") == "NDPS"},
    "Section 37 does NOT fire for a question with no bail keywords -- triggers are real, not decorative",
)

_ALWAYS_ON_COUNT = len({m["section_number"] for m in get_ndps_override("what is even illegal under this law") if m.get("act") == "NDPS"})
check(
    _ALWAYS_ON_COUNT == 1,
    f"only Section 8 is always-on (expected 1, got {_ALWAYS_ON_COUNT})",
)

# ---- judgment anchors: real chunk files, real verbatim text ----

baldev_q = get_ndps_override("the police never told me about my right to be searched before a gazetted officer")
baldev_hits = [m for m in baldev_q if m.get("case_name") == "State of Punjab v Baldev Singh"]
check(
    len(baldev_hits) == 1,
    f"a 'never told me about my right' question surfaces the real Baldev Singh holding paragraph -- got {len(baldev_hits)}",
)
if baldev_hits:
    text_norm = " ".join(baldev_hits[0]["text"].split()).lower()
    check(
        "conclusions arise" in text_norm and "imperative for him to inform" in text_norm,
        "the real Baldev Singh conclusions text (verbatim, from the chunk file) is present",
    )
    check(
        "bad and unsustainable in law" in text_norm,
        "the actual consequence for non-compliance (conviction bad and unsustainable) is present, not paraphrased",
    )
    check(
        baldev_hits[0]["citation"] == "(1999) 6 SCC 172",
        "the real, verified Baldev Singh citation is attached, not a placeholder",
    )

nawaz_q = get_ndps_override("will he get bail, they say there's a commercial quantity involved")
nawaz_hits = [m for m in nawaz_q if m.get("case_name") == "Union of India v Md Nawaz Khan"]
check(
    len(nawaz_hits) == 2,  # _MAX_JUDGMENT_PARAGRAPHS_PER_ENTRY caps this entry's 3 real paragraphs at 2
    f"the Md Nawaz Khan entry surfaces paragraphs, capped at the per-entry max -- got {len(nawaz_hits)}",
)
if nawaz_hits:
    combined = " ".join(" ".join(m["text"].split()).lower() for m in nawaz_hits)
    check(
        "reasonable grounds to believe" in combined,
        "the real twin-conditions bail test text (verbatim, from the chunk file) is present",
    )
    check(
        all(m["citation"] == "(2021) 10 SCC 100" for m in nawaz_hits),
        "the real, verified Md Nawaz Khan citation is attached to every returned paragraph",
    )

tofan_q = get_ndps_override("my brother made a statement to the NCB officer, can they use it against him in court?")
tofan_hits = [m for m in tofan_q if m.get("case_name") == "Tofan Singh v State of Tamil Nadu"]
check(
    len(tofan_hits) == 1,
    f"a 'statement used against him' question surfaces the real Tofan Singh holding paragraph -- got {len(tofan_hits)}",
)
if tofan_hits:
    text_norm = " ".join(tofan_hits[0]["text"].split()).lower()
    check(
        "we answer the reference by stating" in text_norm and "police officers" in text_norm,
        "the real Tofan Singh conclusions text (verbatim, manually-verified extraction) is present",
    )
    check(
        "cannot be used as a confessional statement" in text_norm,
        "the actual holding (section 67 statement barred as a confession) is present, not paraphrased",
    )
    check(
        tofan_hits[0]["citation"] == "(2021) 4 SCC 1",
        "the real, verified Tofan Singh citation is attached, not a placeholder",
    )
    check(
        tofan_hits[0]["opinion_author"] == "R.F. Nariman",
        "correctly attributed to the majority opinion (Nariman, J.), not the dissent (Banerjee, J.) -- "
        "regression guard for the chunking bug found on promotion, where automated chunking could not "
        "reliably tell the two opinions' paragraph 155s apart",
    )

mohanlal_q = get_ndps_override("was the sample of the drug tested and certified before a magistrate?")
mohanlal_hits = [m for m in mohanlal_q if m.get("case_name") == "Union of India v Mohanlal"]
check(
    len(mohanlal_hits) == 1,
    f"a 'was the sample tested before a magistrate' question surfaces the real Mohanlal holding paragraph -- got {len(mohanlal_hits)}",
)
if mohanlal_hits:
    text_norm = " ".join(mohanlal_hits[0]["text"].split()).lower()
    check(
        "to sum up we direct as under" in text_norm and "section 52a" in text_norm,
        "the real Mohanlal directions text (verbatim, manually-verified extraction) is present",
    )
    check(
        "andhra pradesh" not in text_norm and "ministry of home affairs" not in text_norm,
        "regression guard for the chunking bug found on promotion: the real paragraph 20 (the "
        "directions) must never be confused with the unrelated state-data-table row also numbered "
        "20 ('Ministry of Home Affairs NCB')",
    )
    check(
        mohanlal_hits[0]["citation"] == "(2016) 3 SCC 379",
        "the real, verified Mohanlal citation is attached, not a placeholder",
    )

jadeja_q = get_ndps_override("the officer just vaguely told me I could be searched by a gazetted officer, was that enough?")
jadeja_hits = [m for m in jadeja_q if m.get("case_name") == "Vijaysinh Chandubha Jadeja v State of Gujarat"]
check(
    len(jadeja_hits) == 1,
    f"a 'was that enough' question surfaces the real Jadeja holding paragraph -- got {len(jadeja_hits)}",
)
if jadeja_hits:
    text_norm = " ".join(jadeja_hits[0]["text"].split()).lower()
    check(
        "mandatory and requires a strict compliance" in text_norm,
        "the real Jadeja holding text (verbatim, manually-verified extraction) is present",
    )
    check(
        "substantial compliance" in text_norm and "more confidence of the common man" in text_norm,
        "both the rejection of 'substantial compliance' and the Magistrate-preference guidance are present",
    )
    check(
        # regression guard for the chunking bug found on promotion: the extraction must not
        # contain a bare page-number digit landing mid-sentence (e.g. "exercise the 2 right")
        "exercise the 2 right" not in text_norm and "poll14" not in text_norm,
        "no stray page-break digit or footnote-number artifact survived into the stored text",
    )
    check(
        jadeja_hits[0]["citation"] == "(2011) 1 SCC 609",
        "the real, verified Jadeja citation is attached, not a placeholder",
    )

noor_aga_q = get_ndps_override("can they just presume he's guilty because drugs were found, isn't that unconstitutional?")
noor_aga_hits = [m for m in noor_aga_q if m.get("case_name") == "Noor Aga v State of Punjab"]
check(
    len(noor_aga_hits) == 2,
    f"a reverse-burden question surfaces both real Noor Aga holding paragraphs -- got {len(noor_aga_hits)}",
)
if noor_aga_hits:
    combined = " ".join(" ".join(m["text"].split()).lower() for m in noor_aga_hits)
    check(
        "not ultra vires the" in combined,
        "the constitutionality holding (paragraph 1, verbatim) is present",
    )
    check(
        "fact of recovery has not been proved beyond all reasonable doubt" in combined,
        "the recovery-must-be-proven-first holding (paragraph 5, verbatim) is present",
    )
    check(
        all(m["citation"] == "(2008) 16 SCC 417" for m in noor_aga_hits),
        "the real, verified Noor Aga citation is attached to both paragraphs",
    )

karnail_q = get_ndps_override("the police acted on a tip without a warrant, did they follow proper procedure?")
karnail_hits = [m for m in karnail_q if m.get("case_name") == "Karnail Singh v State of Haryana"]
check(
    len(karnail_hits) == 1,
    f"a 'no warrant, proper procedure' question surfaces the real Karnail Singh holding paragraph -- got {len(karnail_hits)}",
)
if karnail_hits:
    text_norm = " ".join(karnail_hits[0]["text"].split()).lower()
    check(
        "should normally precede the entry, search and seizure" in text_norm,
        "the real Karnail Singh conclusion text (verbatim, manually-verified extraction) is present",
    )
    check(
        "clear violation of section 42" in text_norm,
        "the total-non-compliance holding is present, not paraphrased",
    )
    check(
        # regression guard for the pasted-but-unverified external critique claiming this was
        # "paragraph 35" -- checked directly against 2 independent sources (the real source PDF
        # and Indian Kanoon's own copy), both confirm this judgment has only 18 paragraphs total
        karnail_hits[0]["paragraph_number"] == "17",
        f"cited paragraph is the real, twice-verified 17, not an unverified external claim of "
        f"'35' -- got {karnail_hits[0]['paragraph_number']!r}",
    )
    check(
        karnail_hits[0]["citation"] == "(2009) 8 SCC 539",
        "the real, verified Karnail Singh citation is attached, not a placeholder",
    )

# ---- Mukesh Singh (current law) / Mohan Lal (overruled, historical context only) ----

general_q = get_ndps_override("the same officer who arrested him is also investigating, is that fair?")
general_names = {m.get("case_name") for m in general_q if m.get("type") == "judgment"}
check(
    "Mukesh Singh v State (Narcotic Branch of Delhi)" in general_names,
    f"a general 'same officer investigating' question surfaces Mukesh Singh (current law) -- got {general_names}",
)
check(
    "Mohan Lal v State of Punjab" not in general_names,
    "the SAME general question does NOT surface Mohan Lal -- its overruled holding must never appear "
    "without the user specifically naming that case, so it's never mistaken for current law",
)

mukesh_hits = [m for m in general_q if m.get("case_name") == "Mukesh Singh v State (Narcotic Branch of Delhi)"]
check(len(mukesh_hits) == 1, f"exactly one Mukesh Singh paragraph returned -- got {len(mukesh_hits)}")
if mukesh_hits:
    text_norm = " ".join(mukesh_hits[0]["text"].split()).lower()
    check(
        "not good law and they are specifically overruled" in text_norm,
        "the real Mukesh Singh conclusion text (verbatim, manually-verified extraction) is present",
    )
    check(
        "case to case basis" in text_norm,
        "the actual current-law standard (case-by-case, not automatic bias) is present, not paraphrased",
    )
    check(
        mukesh_hits[0]["citation"] == "(2020) 10 SCC 120",
        "the real, verified Mukesh Singh citation is attached, not a placeholder",
    )

named_q = get_ndps_override("is Mohan Lal still good law for informant being the investigator?")
named_names = {m.get("case_name") for m in named_q if m.get("type") == "judgment"}
check(
    {"Mukesh Singh v State (Narcotic Branch of Delhi)", "Mohan Lal v State of Punjab"}.issubset(named_names),
    f"naming Mohan Lal specifically surfaces BOTH cases together, never Mohan Lal alone -- got {named_names}",
)
mohan_lal_hits2 = [m for m in named_q if m.get("case_name") == "Mohan Lal v State of Punjab"]
if mohan_lal_hits2:
    text_norm = " ".join(mohan_lal_hits2[0]["text"].split()).lower()
    check(
        "informant and the investigator must not be the same person" in text_norm,
        "the real Mohan Lal holding text (verbatim, manually-verified extraction) is present",
    )
    check(
        mohan_lal_hits2[0]["citation"] == "(2018) 17 SCC 627",
        "the real, verified Mohan Lal citation is attached, not a placeholder",
    )
    # the OVERRULED framing lives in context_note, not the verbatim judgment text itself
    ctx_norm = mohan_lal_hits2[0]["context_note"].lower()
    check(
        "overruled" in ctx_norm and "not current law" in ctx_norm,
        "the Mohan Lal entry's context_note explicitly and unmissably flags it as overruled",
    )

parmanand_q = get_ndps_override("we were arrested together and only one of us signed the search notice")
parmanand_hits = [m for m in parmanand_q if m.get("case_name") == "State of Rajasthan v Parmanand"]
check(
    len(parmanand_hits) == 2,
    f"a 'signed for both of us' question surfaces both real Parmanand holding paragraphs -- got {len(parmanand_hits)}",
)
if parmanand_hits:
    combined = " ".join(" ".join(m["text"].split()).lower() for m in parmanand_hits)
    check(
        "clear, unambiguous and individual" in combined,
        "the individual-communication holding (paragraph 14, verbatim) is present",
    )
    check(
        "third option" in combined and "could not have given a third option" in combined,
        "the third-option holding (paragraph 15, verbatim) is present",
    )
    check(
        # regression guard for a real omission an external critique caught: the Court's own
        # caveat that a VOLUNTARY request to be searched by the raiding-party officer is a
        # different question from the police OFFERING it -- must survive in the stored text
        "voluntarily expressed" in combined,
        "the voluntary-request caveat (found missing by review, now included) is present",
    )
    check(
        all(m["citation"] == "(2014) 5 SCC 345" for m in parmanand_hits),
        "the real, verified Parmanand citation is attached to both paragraphs",
    )

check(
    not [m for m in get_ndps_override("what is even illegal under this law") if m.get("type") == "judgment"],
    "a question with no bail/search/confession keywords does NOT pull in any judgment -- triggers are real, not decorative",
)

# ---- Union of India v Shiv Shanker Kesari ----

kesari_hits = [
    m for m in get_ndps_override(
        "does the judge basically have to declare him innocent to give bail, and what counts as reasonable grounds anyway"
    )
    if m.get("type") == "judgment" and m.get("case_name") == "Union of India v Shiv Shanker Kesari"
]
check(
    {m["paragraph_number"] for m in kesari_hits} == {"7", "11"},
    "Shiv Shanker Kesari fires both anchored paragraphs (7 and 11) on a realistic combined question",
)
check(
    all(m["case_name"] == "Union of India v Shiv Shanker Kesari" for m in kesari_hits),
    "both paragraphs are correctly attributed to Shiv Shanker Kesari",
)
kesari_combined = " ".join(m["text"] for m in kesari_hits)
check(
    "substantial probable cause" in kesari_combined,
    "paragraph 7's 'reasonable grounds' definition is present",
)
check(
    "not called upon to record a" in kesari_combined and "finding of not guilty" in kesari_combined,
    "paragraph 11's 'not a mini-trial' holding is present",
)
check(
    all(m["citation"] == "(2007) 7 SCC 798" for m in kesari_hits),
    "the real, verified Shiv Shanker Kesari citation is attached to both paragraphs",
)
check(
    not [
        m for m in get_ndps_override("can he get bail") if m.get("type") == "judgment"
        and m["case_name"] == "Union of India v Shiv Shanker Kesari"
    ],
    "a bare bail question without 'reasonable grounds'/'prima facie'/mini-trial wording does NOT fire Kesari "
    "(that stays Nawaz Khan's twin-conditions entry, per the deliberate division of labour between the two)",
)

check(
    get_ndps_override("can he get bail") == get_ndps_override("can he get bail"),
    "the same question always produces the same result -- fully deterministic, no randomness",
)

# ---- never raises ----

check(
    get_ndps_override("") is not None,
    "an empty question never raises",
)
check(
    get_ndps_override(None) is not None,
    "a None question never raises",
)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
