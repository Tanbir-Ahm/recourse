"""
judgment_doctrine_map.py

The judgment-law counterpart of statute_doctrine_map.py.

WHY THIS EXISTS (2026-09-08):
The chat answer engine (chat_assistant.answer_question) gets its case law
ONLY from semantic_retrieval.find_relevant_sections -> semantic_search,
filtered against JUDGMENT_SIMILARITY_THRESHOLD (0.40). For a long,
narrative, multi-issue question -- the kind a frightened person actually
types -- voyage-law-2 similarity is weak: a real user query about being
"arrested for cheating and breach of trust" in a "trading partnership"
with "signatures I never signed" scored EVERY genuinely-relevant judgment
(Vijay Kumar Ghai, Usha Chakraborty, Satishchandra Ratanlal Shah on
civil-dispute-dressed-as-crime; Prabir Purkayastha / Arnesh Kumar on the
arrest itself) at ~0.25-0.33, well under 0.40 -- while a cheque-bounce
case (Rangappa) scored 0.407 on "loan"/"signature" vocabulary overlap and
had to be suppressed by name (see semantic_retrieval.OUT_OF_CHAT_DOMAIN_
CASE_NAMES). Net effect: the answer surfaced NO judgment at all, even
though the corpus holds exactly the right cases.

statute_doctrine_map.py already solves this class of gap for STATUTE
sections. This module does the same for JUDGMENTS: keyword-triggered,
hand-verified doctrine -> specific paragraph(s) of a specific judgment,
resolved through retrieval.get_judgment_paragraphs (real text, never
hardcoded here). Same "all words in a trigger group must appear somewhere
in the message" matching as statute_doctrine_map / doctrine_matcher.

SCOPE: this only feeds the chat answer's retrieved-text pool. It does not
touch main.py's compliance checks or Lane B's related-judgments panel
(which has its own doctrine-anchor mechanism).

EVERY paragraph reference below was read in the actual chunk file before
being added -- the slugs (e.g. "36_civil_dispute_vs_cheating") are the
chunker's own paragraph_number values for these seeded judgments.
"""

import logging

logger = logging.getLogger("judgment_doctrine_map")

# Caps to keep a multi-trigger query (arrest + cheating + FIR-refusal) from
# flooding the prompt. Paragraphs are gathered round-robin -- one per matched
# doctrine first, then second paragraphs -- so every relevant CASE gets in
# before any case gets a second paragraph. Entries earlier in the map win
# ties. Per-entry cap keeps one talkative doctrine from crowding out others.
_MAX_ANCHORED_PARAGRAPHS = 8
_MAX_PARAGRAPHS_PER_ENTRY = 2


# "An arrest has actually happened" -- the SAME list the statute post-arrest
# anchors use (statute_doctrine_map._ARREST_HAPPENED), kept in sync by hand
# because the two maps must not drift (a real recurring bug: the statute
# BNSS 47/35/58 blocks fired for "picked up by the police" but the judgment
# Prabir/Arnesh/Satender anchors did not, so the model named Prabir from
# memory with no excerpt on the page).
_ARREST_HAPPENED = [
    ("arrested",), ("was arrested",), ("been arrested",), ("got arrested",),
    ("arrested me",), ("have arrested me",), ("arrested my",), ("arrested our",),
    ("arrested him",), ("arrested her",), ("police arrested",),
    ("picked up by the police",), ("picked up by police",), ("picked me up",),
    ("picked him up",), ("picked her up",), ("picked up two days",),
    ("took me in",), ("took him in",), ("took me away",), ("took him away",),
    ("detained me",), ("detained him",), ("taken into custody",),
    ("taken to custody",), ("in the lock-up",), ("in the lockup",),
    ("in lock-up",), ("in lockup",), ("in police custody",), ("police custody",),
    ("in judicial custody",), ("in custody",), ("still in custody",),
    ("held in custody",), ("remanded",),
    ("arrested", "days"), ("custody", "days"), ("lock-up", "days"),
    ("lockup", "days"), ("detained", "days"),
]

# Pre-arrest: no arrest yet, but a notice to appear / summons / fear of an
# imminent arrest. Arnesh Kumar and Satender Kumar Antil ("notice is the
# rule, arrest the exception") apply here too -- so their anchors fire for
# both. NOT used by the grounds-of-arrest / custodial / 24-hour anchors.
_ARREST_FEARED_OR_NOTICE = [
    ("notice to appear",), ("41a notice",), ("35(3) notice",),
    ("summons",), ("summoned",), ("called to the station",),
    ("calling me to the station",), ("keep calling me",), ("asked to come to the station",),
    ("asked me to come to the police station",), ("told to appear",),
    ("might arrest",), ("going to arrest",), ("about to arrest",),
    ("threatening to arrest",), ("afraid", "arrest"), ("fear", "arrest"),
    ("scared", "arrest"), ("anticipatory",), ("before", "arrest"),
]


# Order matters: for someone already in custody the arrest-safeguard
# doctrines are the most urgent, so they come first and win the cap.
JUDGMENT_DOCTRINE_MAP = {
    # ---- the arrest itself ---------------------------------------------
    "grounds_of_arrest_must_be_furnished_in_writing": {
        "case_key": "prabir_purkayastha",
        "paragraph_numbers": ["30", "49"],
        "opinion_author": None,
        "trigger_groups": _ARREST_HAPPENED + [
            ("grounds", "arrest"), ("not told", "why"), ("nobody told", "why"),
            ("didn't tell", "why"), ("no reason", "arrest"),
            ("not shown", "documents"), ("haven't shown", "documents"),
            ("not shown", "grounds"), ("without", "notice"), ("no notice",),
        ],
        "context_note": (
            "In Prabir Purkayastha v State (NCT of Delhi) 2024 INSC 414 the "
            "Supreme Court held that the grounds of arrest must be "
            "communicated to the arrested person IN WRITING, that there is a "
            "real difference between the 'reasons for arrest' (formal, "
            "common to every arrest) and the 'grounds of arrest' (the "
            "specific facts and material that led to THIS arrest), and that "
            "an arrest memo which does not convey the grounds does not "
            "satisfy the requirement. Where the written grounds were not "
            "furnished before remand, the arrest and the remand were "
            "declared invalid and the accused was ordered released. The "
            "same principle was laid down for Article 22(1) generally in "
            "Pankaj Bansal v Union of India (2023) and reiterated in Vihaan "
            "Kumar v State of Haryana (2025)."
        ),
        "verified_note": (
            "Paras 30 (communicate grounds in writing) and 49 ('reasons' vs "
            "'grounds' distinction) read verbatim in "
            "chunks/prabir_purkayastha_v_state_(nct_of_delhi)_chunks.json. "
            "Added 2026-09-08."
        ),
    },
    "arrest_must_be_necessary_not_automatic": {
        "case_key": "arnesh_kumar",
        "paragraph_numbers": ["fallback_8", "fallback_10"],
        "opinion_author": None,
        # Arnesh Kumar is the safeguard for EVERY arrest for an offence up
        # to 7 years -- fire it whenever an arrest has actually happened,
        # not only for a hard-coded list of offence words. The context_note
        # is self-limiting ("for an offence punishable with up to seven
        # years"), so it does no harm on a genuinely serious-offence
        # answer.
        "trigger_groups": _ARREST_HAPPENED + _ARREST_FEARED_OR_NOTICE + [
            ("directly arrested",), ("arrested", "straight away"),
            ("without", "notice"), ("no notice",), ("not necessary", "arrest"),
            ("automatically", "arrest"), ("came to my house", "arrested"),
            ("came to our house", "arrested"),
        ],
        "context_note": (
            "In Arnesh Kumar v State of Bihar (2014) 8 SCC 273 the Supreme "
            "Court held that for an offence punishable with up to seven "
            "years (this covers most property offences, cheating, criminal "
            "breach of trust, kidnapping under BNS 137(2), and hurt) the "
            "police may not arrest automatically: they must first be "
            "satisfied, on the parameters in Section 41 CrPC (now Section 35 "
            "BNSS), that arrest is NECESSARY -- to prevent a further "
            "offence, for proper investigation, to prevent tampering with "
            "evidence or intimidation of witnesses, or to secure the "
            "person's attendance -- and must record those reasons in "
            "writing. The Magistrate authorising detention must "
            "independently record satisfaction that the arrest was "
            "necessary before allowing further custody."
        ),
        "verified_note": (
            "fallback_8 (necessity conditions) and fallback_10 (Magistrate's "
            "recorded satisfaction) read verbatim in "
            "chunks/arnesh_kumar_v_state_of_bihar_chunks.json. The narrower "
            "7-direction checklist (fallback_12/13) is separately mapped as "
            "'arnesh_kumar_checklist' in retrieval.JUDGMENT_CITATION_MAP. "
            "Added 2026-09-08."
        ),
    },
    "notice_is_the_rule_arrest_is_the_exception_bnss": {
        "case_key": "satender_kumar_antil_2026",
        "paragraph_numbers": ["31", "33"],
        "opinion_author": None,
        "trigger_groups": _ARREST_HAPPENED + _ARREST_FEARED_OR_NOTICE + [
            ("arrested", "directly"), ("without", "notice"), ("no notice",),
            ("not necessary", "arrest"), ("35(3)",), ("41a",), ("41-a",),
            ("came to my house", "arrested"), ("straight to arrest",),
            ("should have got a notice",), ("without any notice",),
        ],
        "context_note": (
            "In Satender Kumar Antil v CBI, 2026 INSC 115 (order dated "
            "15 January 2026) the Supreme Court, interpreting the new "
            "Bharatiya Nagarik Suraksha Sanhita, held plainly that for an "
            "offence punishable with imprisonment up to seven years a NOTICE "
            "under Section 35(3) of the BNSS is the RULE and an arrest under "
            "Section 35(6) is the EXCEPTION. Its conclusions: an arrest is a "
            "statutory discretion, never mandatory; the officer must ask "
            "whether arrest is a necessity before making it; even where the "
            "Section 35(1)(b) conditions exist, the arrest must not be made "
            "unless it is 'absolutely warranted'; and the power to arrest "
            "after a notice has issued is 'not a matter of routine, but an "
            "exception'. This is the current-code restatement of Arnesh "
            "Kumar."
        ),
        "verified_note": (
            "Paras 31 and 33 (the court's own holding and its lettered "
            "conclusions) read verbatim in chunks/satender_kumar_antil_v_"
            "central_bureau_of_investigation_(2026)_chunks.json; both are "
            "x1 (paras 24 and 32 in this file are duplicated because it "
            "quotes the 2022 Satender Kumar Antil and Arnesh Kumar inline -- "
            "deliberately not used). Citation 2026 INSC 115. case_key is "
            "'satender_kumar_antil_2026' -- the hardcoded key in "
            "retrieval._JUDGMENT_CHUNK_FILES (auto-register skips a file "
            "already registered under any key). Added 2026-09-08."
        ),
    },
    "twenty_four_hour_production_and_custodial_safeguards": {
        "case_key": "dk_basu",
        "paragraph_numbers": ["2", "5", "7"],
        "opinion_author": None,
        "trigger_groups": [
            ("beaten", "custody"), ("beaten", "lockup"), ("beaten", "lock-up"),
            ("beat", "custody"), ("hit", "custody"), ("slapped", "lockup"),
            ("tortur", "custody"), ("handcuff",), ("kept awake",),
            ("arrested", "medical"), ("arrested", "doctor"),
            ("arrested", "injured"), ("arrest memo",), ("no memo",),
            # family not told about the arrest / where he is held
            ("not told", "which police station"), ("which police station", "taken"),
            ("don't know", "which police station"), ("dont know", "which station"),
            ("not told", "where he"), ("not told", "where they took"),
            ("not informed", "arrest"), ("nobody told us", "arrest"),
            ("nobody informed us",), ("no one told us", "where"),
            ("don't know where", "held"), ("dont know where", "held"),
            ("where he is being held",), ("where he has been taken",),
            ("family", "not informed"), ("without", "us being told"),
        ],
        "context_note": (
            "The D.K. Basu v State of West Bengal (1997) 1 SCC 416 "
            "safeguards require, among other things, an arrest memo attested "
            "by a witness and countersigned by the arrestee (para 2), that a "
            "relative or friend be informed of the arrest and the place of "
            "custody (para 5), and that the arrestee be medically examined "
            "at the time of arrest with injuries recorded (paras 7-8). "
            "Breach of these is a serious matter to place before the "
            "Magistrate at the first production, and can found a claim for "
            "compensation."
        ),
        "verified_note": (
            "Paras 2/5/7 read verbatim in "
            "chunks/dk_basu_v_state_of_west_bengal_chunks.json; they map "
            "one-to-one to check_dk_basu_memo (see "
            "retrieval.JUDGMENT_CITATION_MAP 'dk_basu_safeguards'). "
            "Added 2026-09-08."
        ),
    },
    "consequence_of_arresting_without_the_notice_or_recorded_reasons": {
        "case_key": "rakhi_mitra",
        "paragraph_numbers": ["18", "21"],
        "opinion_author": None,
        "trigger_groups": [
            ("arrested", "before"), ("arrested", "without", "notice"),
            ("no notice", "arrest"), ("didn't give", "notice"),
            ("straight away", "arrested"), ("same night", "arrested"),
            ("same day", "arrested"), ("directly arrested",),
            ("didn't record", "reasons"), ("no reasons", "recorded"),
            ("arrested", "before", "show"), ("arrested", "couldn't", "show"),
            ("arrest", "not necessary"), ("should have", "notice"),
        ],
        "context_note": (
            "In Rakhi Mitra v State of West Bengal, 2025:CHC-AS:1826 the "
            "Calcutta High Court held that where the police arrest a person "
            "for an offence punishable with up to seven years WITHOUT first "
            "serving a Section 35(3) BNSS (formerly Section 41-A CrPC) "
            "notice and without recording why the arrest was necessary, the "
            "arrest violates the mandate of Arnesh Kumar and Satender Kumar "
            "Antil. The consequences it identified: the officer is liable "
            "to departmental action and to be proceeded against for "
            "contempt of court; and, on the facts before it, the Court "
            "quashed the criminal proceedings against the petitioners for "
            "that non-compliance. A person arrested this way can put the "
            "non-service of notice and the absence of recorded reasons "
            "before the Magistrate at the first production."
        ),
        "verified_note": (
            "Para 18 (the Arnesh Kumar consequences holding) and para 21 "
            "(non-compliance found on the case diary) read verbatim in "
            "chunks/rakhi_mitra_and_anr_v_state_of_west_bengal_chunks.json; "
            "both x1 (paras 8/27/29 in this file are duplicated because it "
            "quotes Arnesh Kumar / Satender Kumar Antil inline -- not "
            "used). Citation 2025:CHC-AS:1826. Added 2026-09-08."
        ),
    },
    # ---- right to marry a partner of one's own choice ----------------
    "adult_free_to_marry_of_choice_false_kidnapping_case": {
        "case_key": "lata_singh",
        "paragraph_numbers": [
            "major_free_to_marry_no_offence_made_out",
            "false_criminal_case_is_abuse_of_process",
            "right_of_a_major_to_marry_of_choice_and_police_protection_direction",
        ],
        "opinion_author": None,
        "trigger_groups": [
            ("kidnap", "wife"), ("kidnap", "my wife"), ("kidnap", "my own wife"),
            ("kidnapping", "wife"), ("kidnapped", "wife"),
            ("kidnap", "adult"), ("kidnapping", "adult"), ("kidnapped", "adult"),
            ("kidnap", "she is a major"), ("kidnap", "major"),
            ("married", "against", "wishes"), ("marriage", "against", "family"),
            ("marriage", "against", "wishes"),
            ("inter-caste", "marriage"), ("inter caste", "marriage"),
            ("inter-religious", "marriage"), ("different caste", "marriage"),
            ("her family", "kidnap"), ("her family", "complaint", "married"),
            ("she came with me", "own"), ("came with me", "willingly"),
            ("left with me", "voluntarily"), ("her own free will",),
            ("she", "told the police", "voluntarily"),
            ("honour killing",), ("honor killing",),
            ("366",), ("366a",), ("368",),
            ("elopement",), ("eloped",),
        ],
        "context_note": (
            "In Lata Singh v State of Uttar Pradesh, (2006) 5 SCC 475 the "
            "petitioner's brothers -- furious that she had married outside "
            "her caste -- lodged a false kidnapping report against her "
            "husband and his relatives, several of whom were arrested and "
            "jailed. The Supreme Court held: an adult woman is a major and "
            "is 'free to marry anyone she likes or live with anyone she "
            "likes'; there is no bar to an inter-caste marriage; and on "
            "those facts 'we cannot see what offence was committed by the "
            "petitioner, her husband or her husband's relatives'. It "
            "quashed the entire criminal case as 'an abuse of the process "
            "of the Court' brought only because she married outside her "
            "caste, and directed the police across the country to protect "
            "such couples from harassment, threats and violence and to "
            "proceed instead against those who harass them. The right of "
            "two consenting adults to marry a partner of their own choice "
            "has since been affirmed as part of Article 21 (Shafin Jahan v "
            "Asokan K.M.; Shakti Vahini v Union of India)."
        ),
        "verified_note": (
            "Slugs 'major_free_to_marry_no_offence_made_out', "
            "'false_criminal_case_is_abuse_of_process' and "
            "'right_of_a_major_to_marry_of_choice_and_police_protection_"
            "direction' seeded + verbatim-verified from IK doc 1364215 "
            "(seed_lata_singh.py) 2026-09-08 into "
            "chunks/lata_singh_v_state_of_uttar_pradesh_chunks.json; "
            "embedded into corpus_embeddings.json the same day. Citation "
            "(2006) 5 SCC 475."
        ),
    },
    # ---- civil / commercial dispute given a criminal colour --------------
    "civil_dispute_criminalised_as_cheating_or_cbt": {
        "case_key": "vijay_kumar_ghai",
        "paragraph_numbers": ["36_civil_dispute_vs_cheating"],
        "opinion_author": None,
        "trigger_groups": [
            ("cheating", "partnership"), ("cheating", "partner"),
            ("cheating", "business"), ("cheating", "firm"),
            ("cheating", "loan"), ("cheating", "joint"),
            ("cheating", "cousin"), ("cheating", "commercial"),
            ("cheating", "contract"), ("cheating", "money", "dispute"),
            ("breach of trust", "partnership"), ("breach of trust", "partner"),
            ("breach of trust", "business"), ("breach of trust", "firm"),
            ("breach of trust", "loan"), ("breach of trust", "joint"),
            ("breach of trust", "contract"), ("breach of trust", "money"),
            ("420", "partnership"), ("406", "partnership"),
            ("cheating", "owed"), ("cheating", "repay"),
            ("false", "fir", "business dispute"),
            ("civil dispute", "criminal"), ("civil matter", "fir"),
        ],
        "context_note": (
            "In Vijay Kumar Ghai v State of West Bengal (2022) 7 SCC 124 the "
            "Supreme Court quashed an FIR alleging cheating (Section 420 "
            "IPC) and criminal breach of trust (Section 405) arising from a "
            "business/investment dispute, holding that the ingredients of "
            "those offences were simply not made out on the complaint's own "
            "averments and that a commercial dispute had been given the "
            "colour of a criminal offence. The relevance here: a partnership "
            "or loan dispute does not become 'cheating' or 'criminal breach "
            "of trust' just because money is owed or a deal went wrong -- "
            "the police and eventually the court must find dishonest "
            "intention and the specific ingredients of each offence, and "
            "where they are absent the criminal proceeding is liable to be "
            "quashed by the High Court under Section 528 BNSS (Section 482 "
            "CrPC). This is context, not a verdict on any particular case."
        ),
        "verified_note": (
            "Para slug '36_civil_dispute_vs_cheating' read verbatim in "
            "chunks/vijay_kumar_ghai_v_state_of_west_bengal_chunks.json "
            "(the file's single chunk). Citation (2022) 7 SCC 124 per the "
            "chunk's citation field. Added 2026-09-08."
        ),
    },
    "breach_of_contract_is_not_criminal_breach_of_trust": {
        "case_key": "satishchandra_ratanlal_shah",
        "paragraph_numbers": ["13_breach_of_trust_ingredients", "15_caution_against_criminalizing_civil_disputes"],
        "opinion_author": None,
        "trigger_groups": [
            ("breach of trust", "contract"), ("breach of trust", "business"),
            ("breach of trust", "partner"), ("breach of trust", "firm"),
            ("breach of trust", "loan"), ("breach of trust", "deal"),
            ("406", "contract"), ("406", "business"),
            ("misappropriat", "partner"), ("misappropriat", "business"),
            ("entrust", "partner"), ("entrust", "business"),
            ("criminal breach of trust", "money"),
        ],
        "context_note": (
            "In Satishchandra Ratanlal Shah v State of Gujarat (2019) 9 SCC "
            "148 the Supreme Court held that criminal breach of trust "
            "(Section 405/406 IPC; now Section 316 BNS) requires that "
            "property was actually ENTRUSTED to the accused and then "
            "dishonestly misappropriated -- a failure to repay a debt or "
            "honour a contract, without entrustment and dishonest "
            "misappropriation, is a civil wrong, not this offence. The "
            "Court repeated its consistent caution against criminalising "
            "civil disputes such as breach of contractual obligations."
        ),
        "verified_note": (
            "Para slugs '13_breach_of_trust_ingredients' and "
            "'15_caution_against_criminalizing_civil_disputes' read "
            "verbatim in chunks/satishchandra_ratanlal_shah_v_state_of_"
            "gujarat_chunks.json. Added 2026-09-08."
        ),
    },
    "cheating_needs_dishonest_intent_from_the_outset": {
        "case_key": "satishchandra_ratanlal_shah",
        "paragraph_numbers": ["14_cheating_vs_breach_of_contract"],
        "opinion_author": None,
        "trigger_groups": [
            ("cheating", "loan"), ("cheating", "contract"),
            ("cheating", "promise"), ("cheating", "repay"),
            ("cheating", "deal"), ("cheating", "agreement"),
            ("cheated", "loan"), ("cheated", "business"),
            ("420", "contract"), ("defraud", "contract"),
        ],
        "context_note": (
            "On the distinction between a mere breach of contract and the "
            "offence of cheating, the Supreme Court in Satishchandra "
            "Ratanlal Shah held that it turns on the intention at the time "
            "of the inducement: cheating requires that the accused had a "
            "fraudulent or dishonest intention AT THE OUTSET, when the other "
            "person was induced to part with property or act. A later "
            "failure to perform, or a business loss, does not by itself "
            "show that earlier dishonest intention and is not cheating."
        ),
        "verified_note": (
            "Para slug '14_cheating_vs_breach_of_contract' read verbatim in "
            "the same chunk file. Added 2026-09-08."
        ),
    },
    "fir_quashing_ingredients_not_made_out": {
        "case_key": "usha_chakraborty",
        "paragraph_numbers": [
            "breach_of_trust_406_bare_retention_insufficient",
            "cheating_420_deception_chain_not_explained",
            "civil_dispute_can_coexist_with_genuine_crime_converse_test",
        ],
        "opinion_author": None,
        "trigger_groups": [
            ("fir", "cheating", "business"), ("fir", "breach of trust", "business"),
            ("false", "cheating", "partner"), ("false", "cheating", "loan"),
            ("cheating", "breach of trust", "dispute"),
            ("arrested", "cheating", "breach of trust"),
            ("quash", "cheating"), ("quash", "fir", "business"),
        ],
        "context_note": (
            "In Usha Chakraborty v State of West Bengal (2023) the Supreme "
            "Court, quashing an FIR that had bundled cheating, criminal "
            "breach of trust and forgery charges out of a property/family "
            "dispute, went through each offence and held that the FIR did "
            "not spell out the essential ingredients of any of them -- for "
            "criminal breach of trust, bare retention of property is not "
            "enough without entrustment and dishonest misappropriation; for "
            "cheating, the FIR must explain the chain of deception. It also "
            "applied the Paramjeet Batra test: a dispute that is "
            "essentially civil should not be allowed to be pursued as a "
            "crime, though a genuine offence embedded in a civil dispute "
            "can still be investigated."
        ),
        "verified_note": (
            "Para slugs read verbatim in chunks/usha_chakraborty_v_state_of_"
            "west_bengal_chunks.json (11-chunk file). Added 2026-09-08."
        ),
    },
    "bhajan_lal_seven_categories_for_quashing_an_fir": {
        # The standalone State of Haryana v Bhajan Lal judgment is NOT a
        # separate file in this corpus; its seven categories are captured
        # verbatim (with the "AIR 1992 SC 604" marker in the text) inside
        # the Usha Chakraborty chunk, which is where this anchor points.
        "case_key": "usha_chakraborty",
        "paragraph_numbers": ["bhajan_lal_categories_fir_quashing"],
        "opinion_author": None,
        # the chunk lives in the Usha Chakraborty file but its content is
        # the Bhajan Lal test verbatim -- show it under the real source.
        "display_case_name": "State of Haryana v Bhajan Lal",
        "display_citation": "1992 Supp (1) SCC 335 (AIR 1992 SC 604) — as set out in Usha Chakraborty v State of West Bengal",
        "trigger_groups": [
            ("false fir",), ("false case",), ("false complaint",),
            ("fake fir",), ("fabricated", "fir"), ("fabricated", "case"),
            ("quash",), ("quashing",), ("get the fir quashed",),
            ("528 bnss",), ("482 crpc",), ("482 cr.p.c",),
            ("malicious", "prosecution"), ("maliciously", "fir"),
            ("false", "fir", "against me"), ("false", "case", "against me"),
            ("wreak", "vengeance"), ("personal grudge",), ("ulterior motive",),
            ("settle", "score"), ("harass", "false"), ("frame me",), ("framed me",),
            ("civil dispute", "criminal case"), ("civil matter", "criminal case"),
            ("no offence", "made out"), ("does not", "disclose", "offence"),
            # a boundary / land / water / property dispute turned into a
            # criminal case, esp. where the police acted on one side's story
            ("boundary dispute", "arrested"), ("boundary dispute", "fir"),
            ("boundary dispute", "police"), ("boundary dispute", "complaint"),
            ("land dispute", "arrested"), ("land dispute", "fir"),
            ("property dispute", "arrested"), ("property dispute", "fir"),
            ("water", "dispute", "arrested"), ("irrigation", "arrested"),
            ("dispute", "arrested", "neighbour"), ("dispute", "arrested", "neighbor"),
            ("only", "neighbour's statement"), ("only", "neighbor's statement"),
            ("based only on", "statement"), ("one-sided", "statement"),
            ("other party's", "version"), ("arrested", "wrong", "party"),
            # a retaliatory / cross-complaint: we complained first, then the
            # other side filed a case and the police acted on THAT
            ("counter-complaint",), ("counter complaint",), ("counter-complained",),
            ("counter complained",), ("counter-case",), ("counter case",),
            ("cross-case",), ("cross case",), ("cross fir",), ("cross-fir",),
            ("cross-complaint",), ("cross complaint",),
            ("we filed a complaint", "he"), ("we filed first",),
            ("after we complained",), ("when we objected",),
            ("then he", "filed a case"), ("then he", "complained"),
            ("retaliat",), ("in retaliation",),
            # a complaint that on its own facts cannot amount to the offence
            # charged -- Bhajan Lal category 1
            ("kidnap", "my wife"), ("kidnap", "my own wife"),
            ("kidnapping", "wife"), ("kidnapping", "adult"),
            ("kidnap", "adult"), ("kidnapped", "adult"),
            ("married", "against", "wishes"), ("marriage", "against", "family"),
            ("she is an adult", "police"), ("she is a major",),
            ("came with me", "on her own"), ("came with me", "willingly"),
            ("left with me", "voluntarily"), ("her own free will",),
            ("she", "told the police", "voluntarily"),
            ("consenting adult",), ("she consented", "police"),
            ("her family", "complaint", "kidnap"),
        ],
        "context_note": (
            "The High Court's power to quash an FIR or a criminal "
            "proceeding (Section 528 of the BNSS, formerly Section 482 CrPC) "
            "is governed by the seven categories laid down by the Supreme "
            "Court in State of Haryana v Bhajan Lal, 1992 Supp (1) SCC 335 "
            "(AIR 1992 SC 604). In summary, a proceeding may be quashed "
            "where: (1) the allegations, taken at face value, do not make "
            "out any offence; (2)/(3)/(4) the allegations or the material "
            "collected do not disclose a cognizable offence, or disclose "
            "only a non-cognizable one for which no order of a Magistrate "
            "was obtained; (5) the allegations are so absurd and inherently "
            "improbable that no prudent person could find sufficient ground "
            "to proceed; (6) there is an express legal bar to the "
            "proceeding, or a specific, efficacious alternative remedy; or "
            "(7) the proceeding is manifestly attended with mala fides or "
            "is maliciously instituted with an ulterior motive to wreak "
            "vengeance out of a private grudge. The Court also cautioned "
            "that this power is to be exercised sparingly and not to stifle "
            "a legitimate prosecution.\n\n"
            "Category 1 is the one most often engaged where the complaint, "
            "on its own facts, cannot amount to the offence charged, and "
            "category 7 where a private dispute is being pursued as a crime "
            "to pressure the other side. Examples: a 'kidnapping' complaint "
            "by a woman's family when she is an ADULT (kidnapping from "
            "lawful guardianship under BNS Section 137 covers only a child "
            "or a person of unsound mind, and a major's parents are not her "
            "'lawful guardian'); and a boundary / land / irrigation-channel "
            "dispute where one side gets the other arrested on its own "
            "one-sided version -- the criminal machinery is not the forum "
            "for deciding who owns or may use the land or water (BNSS "
            "Sections 164/166 before an Executive Magistrate is), and the "
            "police should not take sides in what is essentially a civil "
            "dispute. Courts have repeatedly cautioned against giving a "
            "civil dispute 'the cloak of a criminal offence'."
        ),
        "verified_note": (
            "The seven categories are quoted verbatim in the chunk slug "
            "'bhajan_lal_categories_fir_quashing' (x1) of "
            "chunks/usha_chakraborty_v_state_of_west_bengal_chunks.json -- "
            "the chunk text itself carries the 'AIR 1992 SC 604' source "
            "marker. Bhajan Lal has no standalone chunk file in this corpus; "
            "get_judgment_doctrine_override attributes the paragraph to "
            "Usha Chakraborty (the containing judgment) with its citation, "
            "and this context_note names Bhajan Lal as the source of the "
            "test. Added 2026-09-08 on user request."
        ),
    },
    "property_dispute_dressed_as_forgery_or_cheating": {
        "case_key": "md_ibrahim",
        "paragraph_numbers": [
            "civil_dispute_criminal_cloak_caution",
            "forgery_false_document_ownership_claim",
        ],
        "opinion_author": None,
        "trigger_groups": [
            ("forgery", "property"), ("forged", "property"),
            ("forgery", "land"), ("forged", "land"),
            ("forgery", "sale deed"), ("forged", "sale deed"),
            ("forgery", "document", "dispute"),
            ("false document", "property"), ("false document", "land"),
            ("forged", "signature", "property"), ("forged", "signature", "land"),
            ("forgery", "ancestral"), ("cheating", "ancestral"),
            ("fir", "property dispute"), ("fir", "land dispute"),
            ("arrested", "property dispute"), ("arrested", "land dispute"),
            ("civil", "property", "criminal"),
            # power of attorney / sale deed / will forgery in a land dispute
            # -- always paired with a forgery/criminal/arrest signal so a
            # plain "how do I register a power of attorney" never fires this
            ("power of attorney", "forged"), ("power of attorney", "fake"),
            ("power of attorney", "signature"), ("power of attorney", "forgery"),
            ("power of attorney", "arrested"), ("power of attorney", "fir"),
            ("power of attorney", "complaint"), ("power of attorney", "not", "sign"),
            ("gpa", "forged"), ("gpa", "signature"), ("gpa", "arrested"),
            ("sale deed", "forged"), ("sale deed", "signature", "recognise"),
            ("sale deed", "not", "signed"),
            ("will", "forged"), ("forged", "will"),
            ("forgery", "will"), ("forgery", "power of attorney"),
            ("signature", "none of us recognise"), ("signature", "we don't recognise"),
            ("signature", "not", "father"), ("date", "hospitalised"),
            ("authorised him to sell",), ("authorized him to sell",),
            ("impersonat", "owner"), ("falsely", "authorised"),
        ],
        "context_note": (
            "In Md. Ibrahim v State of Bihar (2009) 8 SCC 751 the Supreme "
            "Court set aside a criminal case arising from a land dispute, "
            "warning against the growing tendency to give a civil dispute "
            "the 'cloak of a criminal offence' to apply pressure. On "
            "forgery it drew a fundamental distinction: a person who "
            "executes a document CLAIMING the property is his own -- even "
            "if that claim is wrong or disputed -- does not thereby make a "
            "'false document'; that is a civil title dispute. BUT a person "
            "who executes a document 'by impersonating the owner or falsely "
            "claiming to be authorised or empowered by the owner' DOES make "
            "a false document -- so a power of attorney or sale deed that "
            "carries a signature the owner did not make, or falsely says a "
            "(here, deceased or hospitalised) owner authorised the sale, can "
            "amount to forgery. The genuineness of the signature and the "
            "authority are questions of fact for the investigation and the "
            "court."
        ),
        "verified_note": (
            "Para slugs 'civil_dispute_criminal_cloak_caution' and "
            "'forgery_false_document_ownership_claim' read verbatim in "
            "chunks/md_ibrahim_v_state_of_bihar_chunks.json. Citation "
            "(2009) 8 SCC 751. Added 2026-09-08."
        ),
    },
    "criminal_machinery_is_not_for_a_civil_land_or_water_dispute": {
        "case_key": "md_ibrahim",
        "paragraph_numbers": ["civil_dispute_criminal_cloak_caution"],
        "opinion_author": None,
        "trigger_groups": [
            ("boundary dispute",), ("land dispute",),
            ("irrigation", "channel"), ("irrigation", "dispute"),
            ("shared", "channel"), ("water", "channel"),
            ("dispute", "neighbour", "farm"), ("dispute", "neighbor", "farm"),
            ("dispute", "fence"), ("broke", "our fence"), ("broke down", "fence"),
            ("dispute", "field"), ("dispute", "agricultural"),
            ("possession", "dispute", "arrested"),
            ("civil dispute", "arrested"), ("civil matter", "police"),
            ("right of way", "dispute"), ("easement", "dispute"),
        ],
        "context_note": (
            "In Md. Ibrahim v State of Bihar (2009) 8 SCC 751 the Supreme "
            "Court warned against 'the growing tendency of complainants "
            "attempting to give the cloak of a criminal offence to matters "
            "which are essentially and purely civil in nature', usually to "
            "apply pressure on the other side. Where the real dispute is "
            "about the ownership, boundary, possession, or right to use a "
            "piece of land or a water/irrigation channel, that is for the "
            "civil court, or -- where there is a threat to the peace -- for "
            "an Executive Magistrate under BNSS Sections 164 (land/water "
            "possession) and 166 (right of user of land or water). The "
            "police should not take one party's side and treat a civil "
            "dispute as a crime; and an arrest made on only the other "
            "party's version, without independent material, is open to "
            "challenge."
        ),
        "verified_note": (
            "Slug 'civil_dispute_criminal_cloak_caution' read verbatim in "
            "chunks/md_ibrahim_v_state_of_bihar_chunks.json (x1). Citation "
            "(2009) 8 SCC 751. Separate from the forgery-specific Md. "
            "Ibrahim entry above so a boundary/water dispute with no "
            "forgery claim does not also pull the forged-document "
            "paragraph. Added 2026-09-08."
        ),
    },
    # ---- theft: dishonest intention is the ingredient -----------------
    "theft_requires_dishonest_intention": {
        "case_key": "kn_mehra",
        "paragraph_numbers": ["essential_ingredients"],
        "opinion_author": None,
        "trigger_groups": [
            ("theft", "intention"), ("theft", "dishonest"),
            ("stole", "intention"), ("stole", "dishonest"),
            ("theft", "consent"), ("stole", "consent"),
            ("arrested", "theft", "dispute"),
            ("theft", "did not intend"), ("theft", "no intention"),
            ("borrowed", "theft"), ("permission", "theft"),
        ],
        "context_note": (
            "In K.N. Mehra v State of Rajasthan, AIR 1957 SC 369 the Supreme "
            "Court set out the two essential ingredients of theft: (1) the "
            "movable property was moved out of a person's possession WITHOUT "
            "their consent, and (2) the moving was done WITH A DISHONEST "
            "INTENTION at that time. Both must be present. If the person had "
            "consent (express or implied) to take the thing, or genuinely "
            "had no dishonest intention when they took it, the offence of "
            "theft is not made out."
        ),
        "verified_note": (
            "Slug 'essential_ingredients' read verbatim in "
            "chunks/kn_mehra_v_state_of_rajasthan_chunks.json (single "
            "chunk). Citation AIR 1957 SC 369. Added 2026-09-08."
        ),
    },
    "temporary_taking_can_still_be_theft": {
        "case_key": "pyare_lal_bhargava",
        "paragraph_numbers": ["theft_temporary_deprivation"],
        "opinion_author": None,
        "trigger_groups": [
            ("theft", "returned"), ("theft", "gave back"),
            ("theft", "brought back"), ("stole", "returned"),
            ("stole", "gave it back"), ("took", "returned", "theft"),
            ("temporarily", "theft"), ("temporary", "theft"),
            ("borrowed", "theft"), ("meant to return",),
        ],
        "context_note": (
            "In Pyare Lal Bhargava v State of Rajasthan, AIR 1963 SC 1094 "
            "the Supreme Court held that theft does not require permanent "
            "deprivation -- a temporary taking or dispossession is enough, "
            "even where the person intended to return the property later, "
            "because depriving the owner of possession for any period is "
            "'wrongful loss'. So 'I was going to give it back' is not, by "
            "itself, a defence to theft; the questions remain consent and "
            "dishonest intention at the time of taking."
        ),
        "verified_note": (
            "Slug 'theft_temporary_deprivation' read verbatim in "
            "chunks/pyare_lal_bhargava_v_state_of_rajasthan_chunks.json. "
            "Citation AIR 1963 SC 1094. Added 2026-09-08."
        ),
    },
    # ---- cruelty / dowry harassment: over-implication of relatives ----
    "over_implication_of_husbands_relatives_in_cruelty_cases": {
        "case_key": "kahkashan_kausar_sonam",
        "paragraph_numbers": ["18_synthesis", "17_subba_rao_quote"],
        "opinion_author": None,
        "trigger_groups": [
            ("498a", "relatives"), ("498a", "in-laws"), ("498a", "family"),
            ("498a", "parents"), ("498a", "sister"), ("498a", "brother"),
            ("cruelty", "relatives"), ("cruelty", "in-laws"),
            ("cruelty", "husband", "family"),
            ("dowry", "case", "relatives"), ("dowry", "case", "in-laws"),
            ("dowry", "harassment", "relatives"),
            ("85", "relatives"), ("85", "in-laws"),
            ("false", "dowry", "case"), ("false", "498a"),
            ("wife", "case", "my parents"), ("wife", "case", "my family"),
            ("named", "all", "family"), ("distant relative", "dowry"),
        ],
        "context_note": (
            "In Kahkashan Kausar @ Sonam v State of Bihar (2022) 6 SCC 599 "
            "the Supreme Court quashed a Section 498A IPC (cruelty; now "
            "Section 85 BNS) case against the husband's relatives, noting a "
            "consistent line of authority expressing concern about the "
            "'misuse of Section 498A' and the 'tendency of implicating "
            "relatives of the husband in matrimonial disputes' with general "
            "and omnibus allegations. Where the complaint makes only vague, "
            "non-specific allegations against a relative -- no distinct role, "
            "no specific instance of cruelty attributed to that person -- the "
            "proceedings against that relative are liable to be quashed. "
            "This does not dilute a genuine, specific cruelty allegation "
            "against the husband or a named relative."
        ),
        "verified_note": (
            "Slugs '18_synthesis' (the court's own synthesis of the "
            "authorities) and '17_subba_rao_quote' (the K. Subba Rao / "
            "quoted caution) read verbatim in "
            "chunks/kahkashan_kausar_sonam_v_state_of_bihar_chunks.json. "
            "Citation (2022) 6 SCC 599. Added 2026-09-08."
        ),
    },
    # ---- FIR not registered -------------------------------------------
    "fir_registration_is_mandatory_lalita_kumari": {
        "case_key": "lalita_kumari",
        "paragraph_numbers": [
            "111_i_ii_registration_mandatory_no_preliminary_inquiry",
            "111_iv_v_duty_to_register_and_scope_of_preliminary_inquiry",
        ],
        "opinion_author": None,
        "trigger_groups": [
            ("won't register",), ("wont register",), ("will not register",),
            ("not registering",), ("didn't register",), ("did not register",),
            ("refuse", "register"), ("refusing", "register"), ("refused", "register"),
            ("refuse", "fir"), ("refusing", "fir"), ("refused", "fir"),
            ("won't", "fir"), ("not lodge",), ("won't lodge",),
            ("refusing", "complaint"), ("won't take", "complaint"),
            ("no fir",), ("zero fir",), ("fir", "not", "registered"),
        ],
        "context_note": (
            "In Lalita Kumari v Government of Uttar Pradesh (2014) 2 SCC 1 a "
            "Constitution Bench held that registration of an FIR under "
            "Section 154 CrPC (now Section 173 BNSS) is MANDATORY once the "
            "information discloses a cognizable offence, and the officer has "
            "no discretion to hold a preliminary inquiry into whether the "
            "information is true. A preliminary inquiry is permissible only "
            "in a narrow set of categories -- matrimonial/family disputes, "
            "commercial offences, medical negligence, corruption, and cases "
            "with abnormal unexplained delay -- and even then only to check "
            "whether the information discloses a cognizable offence, not its "
            "veracity, and it must be closed within a fixed period. Action "
            "lies against an officer who does not register a cognizable "
            "offence."
        ),
        "verified_note": (
            "Para slugs read verbatim in "
            "chunks/lalita_kumari_v_government_of_uttar_pradesh_chunks.json "
            "(seeded 2026-09-08, para 111 holding directions). Added "
            "2026-09-08 alongside statute_doctrine_map's BNSS 173/175 "
            "entries."
        ),
    },
    # ---- default bail ------------------------------------------------
    "default_bail_is_an_indefeasible_right": {
        "case_key": "m_ravindran",
        "paragraph_numbers": ["18_1_filing_the_application_is_availing_the_right"],
        "opinion_author": None,
        "trigger_groups": [
            ("chargesheet", "days"), ("charge sheet", "days"),
            ("no chargesheet",), ("haven't filed", "chargesheet"),
            ("hasn't filed", "chargesheet"), ("not filed", "chargesheet"),
            ("default bail",), ("statutory bail",),
            ("60 days", "custody"), ("90 days", "custody"),
            ("still", "investigating", "custody"),
        ],
        "context_note": (
            "In M. Ravindran v Intelligence Officer, DRI (2021) 2 SCC 485 "
            "and Bikramjit Singh v State of Punjab (2020) 10 SCC 616 the "
            "Supreme Court held that the right to default bail -- release on "
            "bail when the chargesheet is not filed within 60 or 90 days -- "
            "is not a mere statutory right but part of the fundamental right "
            "under Article 21, and it becomes indefeasible the moment the "
            "accused files an application for it after the period expires "
            "and is prepared to furnish bail. Filing the application is "
            "'availing' the right; it cannot be defeated by the prosecution "
            "then filing the chargesheet or seeking an extension."
        ),
        "verified_note": (
            "M. Ravindran para '18_1_filing_the_application_is_availing_the_"
            "right' and (context) Bikramjit Singh para "
            "'29_default_bail_is_a_fundamental_right_under_article_21' read "
            "verbatim in their chunk files. Added 2026-09-08."
        ),
    },
    # ---- grievous hurt / dangerous weapon: non-recovery of weapon, what counts as "dangerous" ----
    "weapon_not_recovered_does_not_defeat_conviction": {
        "case_key": "anwarul_haq",
        "paragraph_numbers": ["2"],
        "opinion_author": None,
        "trigger_groups": [
            ("knife", "not recovered"), ("weapon", "not recovered"), ("weapon", "never found"),
            ("knife", "never found"), ("weapon", "never recovered"), ("knife", "not found"),
            ("stabbed", "weapon not recovered"), ("dangerous weapon", "not proven"),
            ("was it a dangerous weapon",), ("eyewitness", "weapon not recovered"),
            ("conviction", "weapon not found"), ("stabbing", "no weapon recovered"),
            ("knife attack", "no weapon"), ("police never found", "knife"),
            ("police never found", "weapon"), ("nature of the instrument",),
        ],
        "context_note": (
            "PROMOTED 2026-09-24 from the pilot pool to this fully-verified corpus, after "
            "independent review found the tool's own draft accurate but incomplete -- see "
            "verified_note. In Anwarul Haq v State of Uttar Pradesh, (2005) the Supreme Court "
            "upheld a conviction under Section 324 of the IPC (voluntarily causing hurt by a "
            "dangerous weapon, now BNS Section 118) for a knife attack, holding that the knife "
            "never being recovered during investigation does NOT by itself discredit eyewitness "
            "testimony describing its use, especially when the medical evidence of the injuries "
            "corroborates it. On what makes something a 'dangerous weapon': the expression 'an "
            "instrument... likely to cause death' should be construed with reference to the "
            "NATURE of the instrument, not the manner of its use. The Court also declined to "
            "consider a 'this wasn't proven to be a dangerous weapon' argument raised for the "
            "first time on appeal, since it was never raised before the trial court or High "
            "Court."
        ),
        "verified_note": (
            "Read in full (all 3 pages, pilot_corpus/anwarul_haq_v_state_of_uttar_pradesh.json) at "
            "the user's request, reviewing judgment_promotion_assistant.py's draft for this case. "
            "The tool's own verified quote (the non-recovery-of-weapon passage) checked out "
            "accurately, but independent review found the draft had missed a second, genuinely "
            "useful sentence in the SAME chunk -- the 'nature of the instrument, not manner of "
            "use' test -- so both are included here rather than just the one the tool selected. "
            "paragraph_number '2' is the chunker's label, not a real numbered judgment paragraph "
            "-- this 2005 judgment has no real paragraph numbering; the chunker's heuristic "
            "latched onto the doctor's own injury list ('1.', '2.') instead. The label still "
            "resolves correctly via get_judgment_paragraphs, confirmed by test. Both target "
            "sentences read verbatim in "
            "chunks/anwarul_haq_v_state_of_uttar_pradesh_chunks.json. Citation: Appeal (Crl.) "
            "625-626 of 2005. IPC 324 -> BNS 118 confirmed via "
            "statute_concordance.to_new('IPC','324') and cross-checked against BNS 118's real "
            "text (retrieval.get_statute_section) -- the wording is near-identical, a direct "
            "renumbering, not a substantive change."
        ),
    },
    "compromise_cannot_compound_grievous_hurt_but_can_reduce_sentence": {
        "case_key": "nanda_gopalan",
        "paragraph_numbers": ["fallback_4"],
        "opinion_author": None,
        "trigger_groups": [
            ("compromise", "324"), ("compromise", "326"), ("settled", "grievous hurt"),
            ("compromise", "grievous hurt"), ("compound", "324"), ("compound", "326"),
            ("settle", "assault case"), ("settle", "grievous hurt"),
            ("drop the case", "compromise"), ("withdraw the case", "compromise"),
            ("victim", "wants to withdraw", "grievous hurt"),
            ("reduce", "sentence", "compromise"), ("made up", "reduce", "punishment"),
            ("relative", "settled", "assault"), ("we settled", "punishment"),
        ],
        "context_note": (
            "In Nanda Gopalan v State of Kerala, (2015) the Supreme Court held that offences under "
            "Sections 324 and 326 of the IPC (now BNS Sections 118(1) and 118(2)) are "
            "NON-COMPOUNDABLE -- a private compromise between the parties cannot make the case go "
            "away, since Section 320 of the CrPC (now Section 359 of the BNSS) exhaustively lists "
            "which offences may be compounded and by whom, with no scope for a court to add to that "
            "list on its own. However, a genuine compromise -- especially between close relatives -- "
            "CAN still be taken into account to reduce the sentence actually imposed, even though "
            "the conviction itself must stand. This case independently reaffirmed, quoting them "
            "verbatim, two other holdings already in this tool's sources: Mathai v State of Kerala's "
            "'dangerous weapon' test, and Anwarul Haq v State of Uttar Pradesh's rule that the "
            "'was this a dangerous weapon' argument must be raised at trial, not for the first time "
            "on appeal."
        ),
        "verified_note": (
            "Read in full (all 11 pages, pilot_corpus/nanda_gopalan_v_state_of_kerala.json) at the "
            "user's request, reviewing judgment_promotion_assistant.py's draft. The draft's quote "
            "and summary checked out fully accurate on independent review -- unlike Anwarul Haq, "
            "nothing important was found missing, so this is promoted with the single quote "
            "originally drafted. Notably well-corroborated: the judgment itself quotes Mathai v "
            "State of Kerala's paragraphs 16-17 and Anwarul Haq's paragraphs 11-14 verbatim, "
            "independently reaffirming both as good law as of 2015. Quote reads verbatim in "
            "chunks/nanda_gopalan_v_state_of_kerala_chunks.json. Citation: Criminal Appeal No. 714 "
            "of 2015 (arising out of SLP (Crl.) No. 431 of 2015). IPC 324 -> BNS 118(1), IPC 326 -> "
            "BNS 118(2), both confirmed via statute_concordance.to_new(), both direct renumberings "
            "with no substantive change flagged."
        ),
    },
    "what_makes_a_weapon_dangerous_for_grievous_hurt": {
        "case_key": "prabhu",
        "paragraph_numbers": ["13"],
        "opinion_author": None,
        "trigger_groups": [
            ("dangerous weapon", "stick"), ("dangerous weapon", "lathi"),
            ("dangerous weapon", "grievous hurt"), ("is a stick", "dangerous weapon"),
            ("does a stick count", "weapon"), ("what counts as", "dangerous weapon"),
            ("326", "dangerous weapon"), ("weapon used", "grievous hurt"),
            ("hit with a stick", "326"), ("beaten with", "lathi"),
            ("only knives", "dangerous weapon"), ("deadly weapon",),
        ],
        "context_note": (
            "In Prabhu v State of Madhya Pradesh, (2008) the Supreme Court set out the real test "
            "for what makes a weapon 'dangerous' under Section 326 of the IPC (now BNS Section "
            "118(2), voluntarily causing grievous hurt by dangerous weapons or means): there is NO "
            "fixed or earmarked category of 'dangerous weapon' -- whether an object (a stick, a "
            "lathi, anything) qualifies depends entirely on the facts of the case, including "
            "factors like the weapon's size and sharpness and how the injury was actually caused. "
            "The essential ingredients to attract this offence are: (1) hurt was voluntarily "
            "caused; (2) the hurt qualifies as grievous hurt; and (3) it was caused by a weapon or "
            "means that is genuinely dangerous on the facts. This directly follows and cites Mathai "
            "v State of Kerala's own reasoning on the same point."
        ),
        "verified_note": (
            "Read in full (all 8 pages, pilot_corpus/prabhu_v_state_of_madhya_pradesh.json) at the "
            "user's request. The draft's quote and summary checked out fully accurate -- promoted "
            "with the single quote as originally drafted, same as Nanda Gopalan. Same judge (Dr. "
            "Arijit Pasayat) as Anwarul Haq; this judgment explicitly names Mathai v State of "
            "Kerala as the source of its reasoning, a further independent corroboration of "
            "Mathai's continued good-law status. Note (not added to this entry, a different topic): "
            "Prabhu's own individual liability turned on a common-intention point -- the "
            "prosecution failed to prove he shared his co-accused's intention to kill, only "
            "knowledge that grievous hurt was likely, similar in spirit to Ram Kishan's fact "
            "pattern (not yet promoted). Quote reads verbatim in "
            "chunks/prabhu_v_state_of_madhya_pradesh_chunks.json. Citation: Criminal Appeal No. "
            "1956 of 2008. IPC 326 -> BNS 118(2), IPC 34 -> BNS 3(5), both confirmed via "
            "statute_concordance.to_new(), no substantive change flagged for either."
        ),
    },
    "compounding_not_automatic_for_custodial_or_public_office_offences": {
        "case_key": "pravat_chandra_mohanty",
        "paragraph_numbers": ["30"],
        "opinion_author": None,
        "trigger_groups": [
            ("police", "compound", "324"), ("police", "compensation", "compound"),
            ("custody", "compound"), ("custodial", "compound"),
            ("officer", "offering", "compensation", "settle"),
            ("compound", "public servant"), ("compound", "abuse of power"),
            ("settle", "case", "police officer"), ("compensation", "drop the case", "police"),
            ("court", "let", "settled", "compound"), ("leave to compound",),
        ],
        "context_note": (
            "In Pravat Chandra Mohanty v State of Odisha, (2021) two police officers had beaten a "
            "man to death in custody; convicted under Section 324 IPC (now BNS Section 118(2)), "
            "they later offered compensation and sought to have the offence compounded (settled) "
            "under Section 320 of the CrPC (now Section 359 of the BNSS). The Supreme Court "
            "REFUSED, holding that the grant of leave to compound under Section 320(5) is not "
            "automatic or mechanical just because the accused and the victim's family agree -- the "
            "Court has a clear duty to independently weigh the nature of the offence and its "
            "effect on society first. Custodial violence by a public servant is exactly the kind "
            "of grave, public-interest offence this applies to: 'when the protector of people and "
            "society himself... adopts brutality... it is a matter of great public concern' -- an "
            "abuse of public office is not simply a private dispute the parties can settle away."
        ),
        "verified_note": (
            "Read in full (all 35 pages, pilot_corpus/pravat_chandra_mohanty_v_state_of_odisha."
            "json) at the user's request. The draft's central factual claim -- that this is a "
            "genuine custodial-death case, not an embellishment -- was independently confirmed "
            "(paragraph 14's quoted FIR, and paragraphs 36/40's own description of the accused as "
            "the police-station in-charge and a Senior Inspector). The draft's quote and summary "
            "checked out fully accurate; promoted with the single quote as originally drafted. "
            "NOTE: this case also reduces the sentence (1 year to 6 months) citing the settlement "
            "as a mitigating factor even after refusing to compound (paragraphs 41-43) -- "
            "deliberately NOT added as a second paragraph here, since that exact point is already "
            "covered by the Nanda Gopalan v State of Kerala entry promoted the same session; citing "
            "it again here would be redundant, not additive. Quote reads verbatim in "
            "chunks/pravat_chandra_mohanty_v_state_of_odisha_chunks.json. Citation: Criminal Appeal "
            "No. 125 of 2021. IPC 324 -> BNS 118(2) confirmed via statute_concordance.to_new(), no "
            "substantive change flagged."
        ),
    },
    "fir_ante_timing_delay_not_automatically_fatal": {
        "case_key": "hori_lal",
        "paragraph_numbers": ["fallback_3", "fallback_5"],
        "opinion_author": None,
        "trigger_groups": [
            ("fir", "sent late", "magistrate"), ("fir", "delay", "magistrate"),
            ("special report", "late"), ("ante-timed", "fir"), ("ante timed", "fir"),
            ("fir", "reached", "magistrate", "late"), ("delay", "reaching", "magistrate"),
            ("fir", "day late"), ("crime number", "not mentioned"),
            ("part of a group", "responsible"), ("part of the group", "held responsible"),
            ("standing with a group", "attacked"), ("common object",),
            ("unlawful assembly",), ("didn't do anything myself", "group"),
            ("group", "attacked someone", "held responsible"),
        ],
        "context_note": (
            "In Hori Lal & Anr. v State of Uttar Pradesh, (2006) the Supreme Court addressed two "
            "separate points that come up often in group-violence cases. First, on FIR timing: a "
            "delay in the special report reaching the Magistrate (here, one day) does not by "
            "itself invalidate the prosecution's case -- the Court will weigh it against the "
            "practical circumstances (distance travelled, urgency of medical help, the magnitude "
            "of the incident) rather than treat any delay as automatically fatal; similarly, not "
            "mentioning the crime number on every ancillary document (like a doctor's letter) is "
            "not significant if it's recorded in the inquest/panchnama. Second, on group liability "
            "under Section 149 of the IPC (now BNS Section 190, 'common object' of an unlawful "
            "assembly, defined in IPC Section 141 / now BNS Section 189): a person can be held "
            "liable for an offence committed by another member of the same assembly if they "
            "shared the assembly's common object -- either because the offence was committed in "
            "direct furtherance of that shared purpose, or because it was something the members "
            "knew was likely to happen in pursuing it. Whether someone actually shared the common "
            "object is judged from their own acts, conduct, and the surrounding circumstances, not "
            "just their presence."
        ),
        "verified_note": (
            "Read in full (all 7 pages, pilot_corpus/hori_lal_v_state_of_uttar_pradesh.json) at the "
            "user's request. The tool's own draft (fallback_3, the FIR-timing quote) checked out "
            "accurate -- it had been flagged 'needs extra scrutiny' by the holding-language check "
            "only because the real sentence ('we do not think that...') doesn't match any of the "
            "tool's keyword markers, a confirmed false alarm in the CHECK, not a problem with the "
            "quote. Independent review of the full judgment found a second, genuinely separate "
            "passage (fallback_5) the tool's draft did not select -- the Court's own explanation of "
            "the Section 149 'common object' test -- added here since it answers a different real "
            "question than the FIR point. Both paragraphs read verbatim in "
            "chunks/hori_lal_v_state_of_uttar_pradesh_chunks.json. Citation: Appeal (Crl.) 97 of "
            "2000. IPC 149 -> BNS 190, IPC 141 -> BNS 189, both confirmed via "
            "statute_concordance.to_new(), no substantive change flagged for either."
        ),
    },
    "mere_presence_and_circumstantial_evidence_insufficient_for_murder": {
        "case_key": "sakharam",
        "paragraph_numbers": ["fallback_3", "fallback_4"],
        "opinion_author": None,
        "trigger_groups": [
            ("present", "circumstantial", "murder"), ("was there", "no other evidence", "murder"),
            ("present at the scene", "charged with murder"), ("no direct evidence", "murder"),
            ("no motive", "circumstantial"), ("no motive shown", "murder"),
            ("alibi", "rejected", "guilty"), ("alibi", "didn't hold up"),
            ("defence", "failed", "evidence against"), ("plea", "failed", "look guilty"),
            ("suicide theory", "rejected"), ("juvenile", "circumstantial evidence"),
            ("minor", "presumption of innocence"), ("accused was a minor", "circumstantial"),
        ],
        "context_note": (
            "In Sakharam v State of Madhya Pradesh, (1992) the Supreme Court ACQUITTED an accused "
            "whose murder conviction rested entirely on circumstantial evidence, setting out several "
            "distinct, still-relevant principles. First: being present at the scene when a death "
            "occurred is not, by itself, enough to convict someone of causing it -- 'this "
            "circumstance alone is not sufficient to conclude that it was the appellant who fired "
            "the gun-shot and he did so with the intention of killing the deceased.' Second: absence "
            "of a proven motive is a genuine 'plus-point' for the accused specifically in a "
            "circumstantial-evidence case (though it matters less where the evidence is otherwise "
            "overwhelming). Third, and often misunderstood: if the accused's own defence (an alibi, "
            "a suicide theory) fails at trial, that failure is NOT itself evidence of guilt -- 'that "
            "cannot be taken as a circumstance against him... no adverse inference can be drawn "
            "against the appellant' -- the prosecution still has to prove its own case beyond "
            "reasonable doubt on its own evidence. Fourth: where the accused is a minor, "
            "circumstantial evidence must 'unmistakably' prove guilt to displace the presumption of "
            "juvenile innocence -- the specific Act cited (the Children Act, 1960) has since been "
            "superseded by later juvenile justice legislation, but the underlying principle (a "
            "stricter proof standard where youth is relevant) is the reusable point, not that "
            "specific old citation."
        ),
        "verified_note": (
            "Read in full (all 4 pages, pilot_corpus/sakharam_v_state_of_madhya_pradesh.json) at "
            "the user's request. The tool's own verified quote (fallback_3) checked out accurate, "
            "AND on independent review that same chunk turned out to already contain two more real, "
            "separate holdings the draft's quote and summary hadn't surfaced directly -- the "
            "absence-of-motive point and, notably, the failed-defence-plea point (a real, commonly "
            "relevant worry: 'does a rejected alibi make me look guilty'). A fourth point "
            "(juvenile-innocence) lives in a different chunk (fallback_4), added as a second "
            "paragraph, with an explicit caution in this note about the cited Act being outdated -- "
            "the LLM's own draft never mentioned the Act's age, this was caught only by reading the "
            "full case and checking the citation. Both paragraphs read verbatim in "
            "chunks/sakharam_v_state_of_madhya_pradesh_chunks.json. Citation: Criminal Appeal No. "
            "370 of 1980. IPC 302 -> BNS 103 (change flagged -- BNS 103 restructures murder into "
            "subsections rather than a single provision; not relied on directly in this entry's "
            "quoted text, so not further verified here)."
        ),
    },
    "altering_conviction_on_appeal_is_not_material_prejudice": {
        # NOT "ram_kishan": the case is "State of Uttar Pradesh v Ram Kishan" (state listed
        # first), so retrieval.py's auto-registration key (stem.split("_v_")[0]) is
        # "state_of_uttar_pradesh", not the more distinctive second party -- confirmed by a real
        # test failure before this was caught. The FULL stem is used here, not that shorter key,
        # to avoid ever colliding with a different "State of Uttar Pradesh v ..." case promoted later.
        "case_key": "state_of_uttar_pradesh_v_ram_kishan",
        "paragraph_numbers": ["fallback_7", "fallback_8"],
        "opinion_author": None,
        "trigger_groups": [
            ("change the charge", "without telling"), ("convict", "alone", "grievous hurt"),
            ("charged", "murder", "convict", "grievous hurt"), ("material prejudice",),
            ("alter", "conviction", "appeal"), ("different offence", "same trial"),
            ("group attack", "only shouted"), ("didn't touch", "guilty"),
            ("instigated", "guilty", "same"), ("shouted", "beat", "stabbing"),
            ("only encouraged", "attacked"), ("common intention", "role"),
            ("restrained", "guilty", "stabbing"), ("held him", "guilty"),
        ],
        "context_note": (
            "In State of Uttar Pradesh v Ram Kishan, [1976] 3 S.C.R. 379, several co-accused in a "
            "group assault were originally charged with murder (IPC 302/149, now BNS 103/190) but "
            "the Supreme Court convicted them individually based on their ACTUAL role, not a "
            "blanket verdict. Two points from this: First, on 'material prejudice' -- converting a "
            "conviction from murder to a lesser offence (grievous hurt, IPC 326/34, now BNS "
            "118(2)/3(5)) on appeal does NOT, by itself, unfairly prejudice the accused, where the "
            "underlying facts the accused had to meet at trial are the same either way. Second, and "
            "just as important: the Court looked at what EACH accused actually did. Two accused who "
            "physically restrained the victim while another stabbed him were held to share the "
            "intention to cause grievous hurt (BNS 118(2)/3(5)). But the accused who only verbally "
            "instigated the attack ('beat him') and never touched anyone was held NOT to share that "
            "intention -- only simple assault (IPC 323/109, now BNS 115(2)/49). Shouting "
            "encouragement and physically restraining someone are not automatically treated the "
            "same, even within the same group incident."
        ),
        "verified_note": (
            "Read in full (all 8 pages, pilot_corpus/state_of_uttar_pradesh_v_ram_kishan.json) at "
            "the user's request -- this is the case that originally exposed the pilot-tier-to-prose "
            "gap (the first live Q1 test this session): its summary claimed a material-prejudice "
            "holding, but the tool's verified quote (fallback_5, the generic 'slow to interfere in "
            "an appeal against acquittal' standard) never actually contained it. Found the real "
            "sentence on independent review -- and found it is literally SPLIT by the chunker "
            "across fallback_7 and fallback_8 ('...no prejudice is caused to the accused by "
            "alteration of the conviction to section 326/34' ends one chunk; 'although they had "
            "been originally charged under section 302/149... which they had to meet in the trial' "
            "continues in the next). fallback_7 also holds a genuinely separate, case-specific "
            "holding neither tool draft surfaced: the individual-liability-by-role finding. "
            "judgment_doctrine_map's own round-robin caps each entry at 2 paragraphs "
            "(_MAX_PARAGRAPHS_PER_ENTRY), so fallback_5 (the generic quote) was dropped in favour "
            "of these two case-specific ones. Both read verbatim, in order, in "
            "chunks/state_of_uttar_pradesh_v_ram_kishan_chunks.json. Citation: Criminal Appeal No. "
            "253 of 1971. IPC 302 -> BNS 103, IPC 307 -> BNS 109 (both change-flagged by "
            "statute_concordance -- not relied on directly in the quoted text, so not further "
            "verified here); IPC 149 -> BNS 190, IPC 326 -> BNS 118(2), IPC 34 -> BNS 3(5), IPC 323 "
            "-> BNS 115(2), IPC 109 -> BNS 49, all confirmed unchanged."
        ),
    },
    # ---- counterfeiting currency: not limited to Indian notes -------------
    # NOT a hurt/assault case -- kept in its own section, deliberately separate from the
    # hurt/assault entries above. See verified_note for why this case was moved here at all.
    "counterfeiting_currency_covers_foreign_notes_too": {
        "case_key": "mathai_verghese",
        "paragraph_numbers": ["fallback_2"],
        "opinion_author": None,
        "trigger_groups": [
            ("fake", "dollar", "notes"), ("counterfeit", "currency"), ("counterfeit", "notes"),
            ("fake currency",), ("fake notes",), ("forged currency", "foreign"),
            ("counterfeit", "foreign currency"), ("fake", "foreign notes"),
            ("counterfeit", "dollar bill"), ("489a",), ("489c",),
            ("only indian currency", "counterfeit"), ("law cover", "foreign currency"),
        ],
        "context_note": (
            "In Mathai Verghese v State of Kerala, [1987] 1 S.C.R. 317, the Supreme Court held "
            "that India's counterfeiting-currency law is NOT limited to Indian rupee notes -- "
            "Section 489A of the IPC (counterfeiting a currency note or bank note, now BNS Section "
            "178) and Section 489C (possessing a forged currency note knowing it to be forged, "
            "intending to use it as genuine, now BNS Section 180) cover the currency notes of ANY "
            "country. A High Court had held that counterfeiting or possessing counterfeit American "
            "dollar notes was not an offence under Indian law because the sections only named "
            "'currency notes' without saying 'Indian currency notes' -- the Supreme Court reversed "
            "this, holding the expression 'currency note' is 'large enough in its amplitude to "
            "cover the currency notes of any country', and that it 'would, therefore, in any case, "
            "be an offence to counterfeit a dollar bill or to be in possession of a counterfeit "
            "dollar bill.'"
        ),
        "verified_note": (
            "PROMOTED 2026-09-25 out of the hurt/assault pilot pool, at the user's explicit "
            "instruction, after discovering (via a full independent read, the case the automated "
            "promotion tool could never verify a quote for across two separate runs) that this "
            "case has NOTHING to do with hurt or assault -- it's about counterfeiting currency, "
            "entirely different subject matter. It was almost certainly pulled into that pool by "
            "mistake, due to its similar-sounding name to Mathai v State of Kerala (2005) 3 SCC "
            "260, an unrelated, already-trusted case already in this corpus (different citation, "
            "different year, different holding -- confirmed by reading both). This explains the "
            "tool's repeated rejection: its drafting prompt asks for a holding 'relevant to "
            "criminal law/procedure... the kind of point a layperson's arrest/FIR question might "
            "turn on', which this case doesn't naturally offer, so the AI likely strained for a fit "
            "and misquoted each time. Read in full (all 9 pages, formerly pilot_corpus/mathai_"
            "verghese_v_state_of_kerala.json, now deleted -- the case is preserved only here, in "
            "the promoted core corpus). Quote reads verbatim in chunks/mathai_verghese_v_state_of_"
            "kerala_chunks.json. Citation [1987] 1 S.C.R. 317. IPC 489A -> BNS 178 confirmed via "
            "statute_concordance.to_new(); IPC 489C -> BNS 180 confirmed by matching the exact "
            "wording quoted inside this judgment against BNS 180's real text -- "
            "statute_concordance's own table has a gap for 489C (returns None), a known limitation "
            "of that tool, not verified here via its automated lookup."
        ),
    },
    # ---- accidental death / rash driving: 304A vs 304 Part II vs 302 ----
    "rash_or_negligent_act_causing_death_is_not_culpable_homicide": {
        "case_key": "state_of_gujarat_v_haidarali_kalubhai",
        "paragraph_numbers": ["fallback_4", "fallback_5"],
        "opinion_author": None,
        "trigger_groups": [
            ("accident", "died"), ("accident", "death"), ("accidentally", "died"),
            ("accidentally", "killed"), ("lost control", "vehicle"),
            ("lost control", "died"), ("rash driving",), ("negligent driving",),
            ("rash and negligent",), ("charged with murder", "accident"),
            ("charged", "302", "accident"), ("wasn't intentional", "died"),
            ("didn't mean to kill",), ("didn't intend to kill",),
            ("304a",), ("304 part ii",), ("culpable homicide", "accident"),
            ("vehicle", "hit", "died"), ("truck", "hit", "died"),
            ("car accident", "died"), ("run over", "died"),
        ],
        "context_note": (
            "In State of Gujarat v Haidarali Kalubhai, 1976 AIR 1012 / [1976] 3 S.C.R. 303, the "
            "Supreme Court explained the line between a genuine accident and a crime when a death "
            "happens without anyone meaning to kill. The accused lost control of a truck he was "
            "driving at speed and struck a cot, fatally injuring the person resting on it. He was "
            "originally convicted of culpable homicide (old IPC Section 304 Part II, now BNS Section "
            "105); the High Court reduced this to the lesser offence of causing death by a rash or "
            "negligent act (old IPC Section 304A, now BNS Section 106(1)), and the Supreme Court "
            "upheld that. The Court held that Section 304A 'carves out a specific offence where "
            "death is caused by doing a rash or negligent act' and 'by its own definition totally "
            "excludes the ingredients of' culpable homicide (old IPC Sections 299/300, now BNS "
            "Sections 100/101) -- what separates the two is intent or knowledge: 'when intent or "
            "knowledge is the direct motivating force of the act complained of', the graver charge "
            "of culpable homicide applies instead. On the facts, 'the tangential track of the "
            "speeding truck coming in contact with the corner of the steel cot... would not reveal "
            "the accused['s] intention or any deliberate act with the requisite knowledge', and the "
            "facts fit 'more reasonably with the theory of loss of control by the accused of the "
            "vehicle in high speed'. Worth flagging: BNS 106 is not identical to old IPC 304A -- BNS "
            "106(2) adds a specific hit-and-run aggravation (fleeing the scene without reporting to "
            "police, up to 10 years) that IPC 304A did not have; that provision plays no part in this "
            "case, since the accused here did not flee."
        ),
        "verified_note": (
            "The key sentence -- 'Section 304A by its own definition totally excludes the "
            "ingredients of section 299 or section 300 IPC' -- is split by the fixed-size chunk "
            "boundary exactly across fallback_4/fallback_5 (the same class of chunk-boundary "
            "sentence-split confirmed earlier on the Ram Kishan entry above); both are cited "
            "together so the model sees the complete sentence, not just its second half. "
            "PROMOTED 2026-09-25, the first case not sourced from the original 9-case pilot pool -- "
            "found via a scratch exploration of api.sci.gov.in's sequential JUDIS numbering scheme "
            "(ID 5735, adjacent to Ram Kishan's ID 5725), read in full before any decision was made "
            "to build with it, and approved by the user for a NEW domain (accidental death / rash "
            "driving) rather than being forced into hurt/assault. Fetched directly from "
            "https://api.sci.gov.in/jonew/judis/5735.pdf via PyMuPDF; per-page JUDIS.NIC.IN / "
            "SUPREME COURT OF INDIA / 'Page N of 5' footer stamps and bare SCR volume page numbers "
            "(304-308, an artifact of pagination, not paragraph markers) stripped before chunking. "
            "This is a 1976 judgment with no modern numbered-paragraph structure, so it chunked via "
            "the fixed-size fallback (5 chunks, fallback_1..fallback_5), same as Arnesh Kumar and "
            "Mathai Verghese. Both quotes above -- the 304A/culpable-homicide test and its "
            "application to these facts -- sit together in fallback_5; verified verbatim against "
            "chunks/state_of_gujarat_v_haidarali_kalubhai_chunks.json. case_key is the FULL stem "
            "'state_of_gujarat_v_haidarali_kalubhai', not the naive post-split 'state_of_gujarat' -- "
            "this filename hits the exact same 'State of X v Y' registration trap documented on the "
            "Ram Kishan entry above (retrieval.py's auto-registration keys 'State of X v Y' files on "
            "the state's name unless disambiguated), confirmed safe by direct inspection of "
            "retrieval._JUDGMENT_CHUNK_FILES before use, not assumed. Citation 1976 AIR 1012, "
            "[1976] 3 S.C.R. 303 as printed on the judgment itself. IPC 299 -> BNS 100, IPC 300 -> "
            "BNS 101, IPC 304 -> BNS 105, IPC 304A -> BNS 106 all confirmed via "
            "statute_concordance.to_new('IPC', n) (no gaps for these sections); BNS 106's actual "
            "text read via retrieval.get_statute_section to confirm the sub-section split (106(1) "
            "rash/negligent act, 106(2) hit-and-run) and surface the hit-and-run caveat above."
        ),
    },
    # ---- murder vs. culpable homicide: sudden fight, no premeditation ----
    "sudden_fight_no_premeditation_reduces_murder_to_culpable_homicide": {
        "case_key": "jagrup_singh",
        "paragraph_numbers": ["fallback_2", "fallback_8"],
        "opinion_author": None,
        "trigger_groups": [
            ("sudden fight",), ("sudden quarrel",), ("sudden scuffle",),
            ("heat of the moment", "died"), ("heat of the moment", "death"),
            ("heat of passion",), ("without premeditation",), ("no premeditation",),
            ("without any premeditation",), ("not premeditated",),
            ("single blow", "died"), ("single blow", "death"),
            ("one blow", "died"), ("solitary blow",),
            ("hit him once",), ("hit her once",),
            ("struck him once",), ("struck her once",),
            ("no weapon", "sudden", "died"), ("no weapon", "quarrel", "died"),
            ("unplanned", "fight", "died"), ("spur of the moment", "died"),
            ("no intention to kill", "sudden"), ("exception 4",),
        ],
        "context_note": (
            "PROMOTED 2026-09-24 from the pilot (wider, not-independently-reviewed) judgment pool "
            "to this fully-verified corpus, after being personally read in full and confirmed -- see "
            "verified_note below for what that review found. In Jagrup Singh v State of Haryana, "
            "1981 AIR 1552 / [1981] 3 S.C.R. 839, the Supreme Court reduced a murder conviction to "
            "culpable homicide not amounting to murder where the accused struck a single blow with "
            "the blunt side of a farm tool, in a sudden fight at a wedding, with no prior "
            "premeditation and no clearly established motive. It held that where an act causing "
            "death happens 'in the heat of the moment, without pre-meditation and in a sudden "
            "fight', and the accused did not take undue advantage of the situation or act in a "
            "cruel or unusual manner, the case falls under Exception 4 to murder (BNS Section 101 -- "
            "then IPC Section 300) -- the offence is culpable homicide not amounting to murder (BNS "
            "Section 105, verified via statute_concordance.to_new('IPC','304') -- then IPC Section "
            "304 Part II), not murder. The Court was equally clear this is NOT an automatic rule: it "
            "expressly rejected the idea that a single blow on a vital part of the body always "
            "reduces the offence -- the real intention must still be gathered from the weapon used, "
            "the part of the body struck, the force used, and the surrounding circumstances of each "
            "case."
        ),
        "verified_note": (
            "Read in full (all 8 pages, pilot_corpus/jagrup_singh_v_state_of_haryana.json) at the "
            "user's request, after a live chat answer had described this case (hedged, via the "
            "pilot-tier mechanism) as dealing with whether a sudden, unpremeditated blow falls under "
            "the sudden-fight exception. Confirmed: it does, and the description was accurate. "
            "Paragraph slugs 'fallback_2' (the headnote's own HELD summary, containing 'all the "
            "requirements of Exception 4') and 'fallback_8' (the Court's final operative order, "
            "containing the actual alteration of the conviction from s.302 to s.304 Part II) read "
            "verbatim in chunks/jagrup_singh_v_state_of_haryana_chunks.json -- promoted from "
            "pilot_chunks/ of the same name (embedding field stripped; the embeddings that made this "
            "case findable at all live separately, unaffected). Citation [1981] 3 S.C.R. 839. Added "
            "2026-09-24."
        ),
    },
    "default_bail_oral_application_enough_and_courts_duty": {
        "case_key": "rakesh_kumar_paul",
        "paragraph_numbers": [
            "40_written_or_oral_application_for_default_bail_is_of_no_consequence",
            "44_court_has_a_duty_to_apprise_the_accused_of_the_right",
        ],
        "opinion_author": None,
        "trigger_groups": [
            ("chargesheet", "days"), ("charge sheet", "days"),
            ("no chargesheet",), ("haven't filed", "chargesheet"),
            ("hasn't filed", "chargesheet"), ("not filed", "chargesheet"),
            ("default bail",), ("statutory bail",),
            ("60 days", "custody"), ("90 days", "custody"),
            ("ninety days",), ("sixty days",),
            ("no lawyer", "chargesheet"), ("cannot afford", "lawyer", "custody"),
        ],
        "context_note": (
            "In Rakesh Kumar Paul v State of Assam (2017) 15 SCC 67 the "
            "Supreme Court held that in matters of personal liberty the "
            "court must not be technical: whether the accused makes a "
            "WRITTEN application for default bail or only an ORAL one is of "
            "no consequence, and once the time limit has passed without a "
            "chargesheet the accused need only indicate they are ready to "
            "furnish bail. It also held it is the DUTY of the court, on "
            "coming to know that an accused before it is entitled to default "
            "bail, to inform them of that indefeasible right. (The case also "
            "held that 'imprisonment for not less than ten years' means the "
            "offence must carry a minimum of ten years for the 90-day limit "
            "to apply -- otherwise the limit is 60 days.)"
        ),
        "verified_note": (
            "Slugs '40_written_or_oral_application_for_default_bail_is_of_no_"
            "consequence' and '44_court_has_a_duty_to_apprise_the_accused_of_"
            "the_right' read verbatim in "
            "chunks/rakesh_kumar_paul_v_state_of_assam_chunks.json. Citation "
            "(2017) 15 SCC 67. Added 2026-09-08. Complements the M. Ravindran "
            "entry above; section-order sort + total cap keep the pair from "
            "flooding a default-bail answer."
        ),
    },
}


def match_judgment_doctrine(question: str) -> list:
    """Return the keys of JUDGMENT_DOCTRINE_MAP entries whose trigger groups
    match `question`. Same logic as statute_doctrine_map.match_statute_
    doctrine: a group matches if ALL its words appear anywhere in the
    lower-cased question."""
    if not question or not question.strip():
        return []
    q = question.lower()
    matched = []
    for key, entry in JUDGMENT_DOCTRINE_MAP.items():
        for group in entry["trigger_groups"]:
            if all(word in q for word in group):
                matched.append(key)
                logger.info("judgment_doctrine_map: matched %r on group=%r", key, group)
                break
    return matched


def get_judgment_doctrine_override(question: str) -> list:
    """Main entry point for chat_assistant. Given the user's message,
    resolve every matching doctrine to real judgment-paragraph text and
    return a list of match dicts shaped like semantic_search's judgment
    matches, so they merge straight into the same retrieved-text pool:

        {case_name, citation, paragraph_number, text, context_note,
         source: "curated_judgment_override"}

    Deduped by (case_name, paragraph_number); capped at
    _MAX_ANCHORED_PARAGRAPHS total. Never raises: a doctrine whose chunk
    file or paragraph cannot be resolved is logged and skipped.
    """
    from retrieval import get_judgment_paragraphs

    # Resolve each matched doctrine to an ordered list of its paragraphs.
    per_doctrine = []
    for key in match_judgment_doctrine(question):
        entry = JUDGMENT_DOCTRINE_MAP[key]
        paras = get_judgment_paragraphs(
            entry["case_key"], entry["paragraph_numbers"],
            opinion_author=entry.get("opinion_author"),
        )
        if not paras:
            logger.warning(
                "judgment_doctrine_map: %r -> get_judgment_paragraphs(%r, %r) "
                "returned nothing; skipping", key, entry["case_key"],
                entry["paragraph_numbers"],
            )
            continue
        order = {str(pn): i for i, pn in enumerate(entry["paragraph_numbers"])}
        paras.sort(key=lambda pp: order.get(str(pp.get("paragraph_number")), 99))
        per_doctrine.append((entry, paras[:_MAX_PARAGRAPHS_PER_ENTRY]))

    # Round-robin: every matched case contributes its first paragraph before
    # any case contributes its second.
    results, seen = [], set()
    for rank in range(_MAX_PARAGRAPHS_PER_ENTRY):
        for entry, paras in per_doctrine:
            if rank >= len(paras):
                continue
            p = paras[rank]
            sig = (p.get("case_name"), str(p.get("paragraph_number")))
            if sig in seen:
                continue
            seen.add(sig)
            results.append({
                "case_name": entry.get("display_case_name") or p.get("case_name"),
                "citation": entry.get("display_citation") or p.get("citation"),
                "paragraph_number": p.get("paragraph_number"),
                "opinion_author": p.get("opinion_author"),
                "text": p.get("text"),
                "context_note": entry["context_note"],
                "type": "judgment",
                "source": "curated_judgment_override",
            })
            if len(results) >= _MAX_ANCHORED_PARAGRAPHS:
                return results
    return results
