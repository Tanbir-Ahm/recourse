
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

check(
    not [m for m in get_ndps_override("what is even illegal under this law") if m.get("type") == "judgment"],
    "a question with no bail/search/confession keywords does NOT pull in any judgment -- triggers are real, not decorative",
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
