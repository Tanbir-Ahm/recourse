"""
ndps_doctrine_map.py -- curated statute + judgment anchors for the
Narcotic Drugs and Psychotropic Substances Act, 1985 (NDPS), the tool's
newest legal-domain expansion beyond BNS/BNSS arrest/FIR law, the
cheque-bounce/freeze bolt-ons, and the PWDVA domestic-violence domain
(see domestic_violence_doctrine_map.py -- this file follows that exact
architecture, deliberately).

WHY NDPS, AND WHY NOW (2026-09-25)
-----------------------------------
Chosen after a direct analysis of what the tool's deterministic backbone
did and didn't cover: arrest safeguards, cheating/civil-dispute-vs-crime,
theft, matrimonial cruelty, FIR quashing, default bail, hurt/assault,
cheque-bounce, bank-freeze, and domestic violence were all already
covered to some degree. NDPS was a genuine, complete gap -- and one of
the highest-frequency real arrest categories in India, where the law is
unusually harsh and confusing for a family: Section 37 flips the normal
presumption in favour of bail, and the whole punishment/bail picture
turns on whether the seized quantity is "small", in between, or
"commercial" -- exactly the kind of thing a panicking family gets wrong
without help.

WHY THIS IS SMALL ON PURPOSE
------------------------------
Same discipline as every other curated anchor in this project: every
section and every judgment paragraph here was pulled verbatim from
Indian Kanoon and read by a person before being added. This covers only
what a family would realistically need for a first real question after
an arrest -- what's actually prohibited (Section 8), the punishment
tiers for the two offence types people are most often arrested for
(cannabis under Section 20, "manufactured drugs" like heroin under
Section 21), the much lighter consumption offence (Section 27), the
bail test itself (Section 37), the search-and-seizure rights that
matter most at the moment of arrest (Sections 43 and 50), and what
"small"/"commercial" quantity even means (Section 2). It is NOT meant
to cover everything NDPS-related (e.g. psychotropic substances under
Section 22, funding/harbouring under Section 27A, forfeiture of
property, or the special-court procedure are all out of scope for
now) -- see memory or a future session for growing this the same way
PWDVA grew a second batch of sections after a real gap was found.

Two judgments, both fully verified:
- State of Punjab v Baldev Singh, (1999) 6 SCC 172, a Constitution
  Bench: compliance with Section 50 (informing a person of their right
  to be searched before a Gazetted Officer or Magistrate) is not
  something the Court will call flatly "mandatory or directory" in so
  many words, but failure to do it renders the recovered contraband
  suspect and can make the conviction itself unsustainable.
- Union of India v Md Nawaz Khan, (2021) 10 SCC 100: states and applies
  the Section 37 "twin conditions" bail test. Deliberately included even
  though it is a bail-DENIAL case (the Supreme Court set aside a High
  Court's bail grant here) -- an honest picture of how strict this test
  really is matters more than only showing favourable outcomes.

SOURCING METHOD NOTE (both judgments)
---------------------------------------
Both were fetched from Indian Kanoon, which marks each real paragraph
with its own numeric id (id="p_N") but does not print that number as
visible text the way an official SC PDF does -- so chunk_judgments.py's
usual text-pattern paragraph detector cannot see them directly. Each
judgment's real paragraphs were extracted by that id structure instead,
re-prefixed with their own real number ("N. ...") to match the shape an
official PDF would have, and only THEN run through the normal
chunk_judgments.py pipeline -- so the resulting chunk files are
identical in shape and handling to every officially-PDF-sourced
judgment already in this corpus, just built from a different (still
primary, still verbatim) source. Baldev Singh's real paragraph 55 was
unusually long (15,500+ chars, a discursive Constitution Bench
paragraph working through Income Tax Act and Canadian/English case-law
comparisons before its own 10-point conclusions list) -- far too large
for a single chat citation. It was split, at the natural sentence "On
the basis of the reasoning and discussion above, the following
conclusions arise:", into paragraph 55 (the discursive reasoning, not
cited here) and a new paragraph 56 (the conclusions list itself, what
this domain actually cites) -- every paragraph originally numbered 56
or higher shifted up by one to keep the sequence genuinely ascending.
See corpus/state_of_punjab_v_baldev_singh.json's own notes field for
the same explanation, kept alongside the source record.

Like PWDVA, there is no shared get_statute_section() table for NDPS, so
verbatim section text is stored directly here. Judgment paragraphs are
NOT stored here; they resolve via retrieval.get_judgment_paragraphs
(auto-registered from chunks/ at import), same as every other judgment
anchor in this project. Both case_keys use the FULL filename stem
("state_of_punjab_v_baldev_singh", "union_of_india_v_md_nawaz_khan"),
not the naive post-"_v_" split -- the same "State/Union of X v Y"
registration trap already documented on the Ram Kishan and Haidarali
Kalubhai entries in judgment_doctrine_map.py, checked directly against
retrieval._JUDGMENT_CHUNK_FILES before use here, not assumed.

STATUTE TEXT CROSS-CHECKED AGAINST A GOVERNMENT SOURCE (2026-09-25)
----------------------------------------------------------------------
All 8 sections above were originally sourced from Indian Kanoon (a
private, widely-used legal database, not a government site) -- raised
by the user as a real gap, since the two judgments above got a more
careful sourcing pass than the statute text did. Closed the same day:
downloaded the actual Government of India bare-act PDF from
dor.gov.in/files/acts_files/Narcotic-Drugs-and-Psychotropic-Substances-
Act-1985_0.pdf (Department of Revenue, Ministry of Finance -- the
indiacode.nic.in copy itself blocked automated access, both directly
and via WebFetch, with a 403/timeout) and located each of Sections 2
(small/commercial quantity), 8, 20, 21, 27, 37, 43, and 50 in it
directly. Every one matches what is stored here word for word, clause
for clause, number for number -- zero discrepancies found. (That PDF's
own OCR text is noisy -- e.g. "PoPPy", "aPplication", "riSorous" --
but the underlying legal text is identical to the clean version
already stored in this file, which is what matters.) Section 2's
actual gram/kilogram thresholds remain outside the Act itself, set by
a separate Central Government notification, exactly as already noted
in that section's context_note above -- this cross-check confirms the
Act's OWN text says so, not a threshold table this file was missing.

TOFAN SINGH -- A NEW CHUNKING FAILURE MODE FOUND ON PROMOTION (2026-09-25)
----------------------------------------------------------------------
Tofan Singh v State of Tamil Nadu, (2021) 4 SCC 1: read in full BEFORE
promotion, including Indira Banerjee, J.'s full dissent (not just the
majority's conclusion) at the user's explicit request -- summarized in
this entry's own context_note below (the dissent's substance, not just
that it existed). Promoting it also surfaced a real, confirmed
limitation of chunk_judgments.py distinct
from every prior one documented in this project: this 308-page
judgment quotes ENTIRE other judgments' judge-signed passages inline
(including Baldev Singh's own "conclusions arise" list, word for word)
-- not just a paragraph or two, the way the project's known "quoted
paragraph retains its original number" collision usually looks. Those
inline judge signatures ("Nariman", "Bobde", "Kaul", "Chelameswar" --
names from an UNRELATED case, K.S. Puttaswamy, quoted for its privacy
discussion) fooled chunk_judgments.py's opinion-splitter into detecting
6 "opinions" in a document that genuinely has only 2 (Nariman for the
majority, Banerjee dissenting) -- which then cascaded into paragraph-
number collisions severe enough that automated chunking could not be
trusted to correctly resolve "paragraph 155" for this document at all
(it returned two DIFFERENT wrong paragraph-155 chunks, both from
Banerjee's opinion, and the real Nariman paragraph 155 ended up merged
into a giant fixed-size chunk mislabeled "57"). Confirmed by direct
inspection of pilot_chunks/tofan_singh_v_state_of_tamil_nadu_chunks.json
against the real, character-position-verified source text -- not
assumed. Fixed for THIS promotion by manually constructing
chunks/tofan_singh_v_state_of_tamil_nadu_chunks.json with a single,
hand-verified paragraph 155 (chunk_method "manual_verified_extraction",
confirmed to appear exactly once in Nariman's real, correctly-bounded
opinion text). The pilot_chunks/ copy is left as-is, still usable for
the wider pilot-tier semantic search where an occasional mislabeled
paragraph number matters less -- this fix only applies to the trusted
core citation. Improving chunk_judgments.py's opinion-detection to
generally resist quoted judge-signature blocks is a real, separate
piece of future work, not done here.
"""
import logging

logger = logging.getLogger(__name__)

_ALWAYS = "__always__"
_MAX_JUDGMENT_PARAGRAPHS_PER_ENTRY = 2
_MAX_ANCHORED_JUDGMENT_PARAGRAPHS = 4


# ---------------------------------------------------------------------------
# Statute anchors -- verbatim NDPS Act text, pulled via Indian Kanoon
# (indiankanoon.org/doc/496325, 961083, 363765, 1727139 [Sec 8], 1566465,
# 919170, 1374738) and read by a person before being added here, 2026-09-25.
# ---------------------------------------------------------------------------

_NDPS_STATUTE_ANCHORS = [
    {
        "section_number": "2",
        "triggers": [
            ("small quantity",), ("commercial quantity",), ("intermediate quantity",),
            ("how much", "quantity"), ("what counts as", "quantity"),
            ("how is quantity", "decided"), ("grams",), ("kilogram",),
            ("weight", "drug"), ("weight", "narcotic"),
        ],
        "text": (
            "2. Definitions. In this Act, unless the context otherwise requires -- "
            "\"small quantity\" means any quantity lesser than the quantity specified "
            "by the Central Government by notification in the Official Gazette; "
            "\"commercial quantity\" means any quantity greater than the quantity "
            "specified by the Central Government by notification in the Official "
            "Gazette."
        ),
        "context_note": (
            "This Act itself does not print the actual gram/kilogram numbers -- "
            "those are set separately, drug by drug, in a Central Government "
            "notification (not the Act's own text), and a lawyer or the case "
            "paperwork itself is the reliable way to find the exact threshold for "
            "the specific substance involved. What matters for now: a quantity "
            "below the 'small quantity' line, a quantity between that and "
            "'commercial quantity', and a quantity at or above 'commercial "
            "quantity' are punished very differently under Sections 20/21 below, "
            "and Section 37's harsh bail rule below only applies at the "
            "'commercial quantity' level (plus a few other offences named there)."
        ),
    },
    {
        "section_number": "8",
        "triggers": _ALWAYS,
        "text": (
            "8. Prohibition of certain operations. No person shall -- (a) cultivate "
            "any coca plant or gather any portion of coca plant; or (b) cultivate "
            "the opium poppy or any cannabis plant; or (c) produce, manufacture, "
            "possess, sell, purchase, transport, warehouse, use, consume, import "
            "inter-State, export inter-State, import into India, export from India "
            "or tranship any narcotic drug or psychotropic substance, except for "
            "medical or scientific purposes and in the manner and to the extent "
            "provided by the provisions of this Act or the rules or orders made "
            "thereunder..."
        ),
        "context_note": (
            "This is the general prohibition everything else in the Act builds on "
            "-- it is what makes cultivating, producing, possessing, selling, "
            "transporting or consuming a narcotic drug or psychotropic substance an "
            "offence in the first place (subject to the medical/scientific "
            "exception). Sections 20/21/27 below set the actual punishment, which "
            "depends heavily on which substance and how much of it."
        ),
    },
    {
        "section_number": "20",
        "triggers": [
            ("ganja",), ("charas",), ("cannabis",), ("marijuana",), ("weed",),
            ("hashish",), ("bhang",), ("cannabis plant",),
        ],
        "text": (
            "20. Punishment for contravention in relation to cannabis plant and "
            "cannabis. Whoever, in contravention of any provisions of this Act or "
            "any rule or order made or condition of licence granted thereunder, "
            "(a) cultivates any cannabis plant; or (b) produces, manufactures, "
            "possesses, sells, purchases, transports, imports inter-State, exports "
            "inter-State or uses cannabis, shall be punishable -- (i) where such "
            "contravention relates to clause (a) with rigorous imprisonment for a "
            "term which may extend to ten years and shall also be liable to fine "
            "which may extend to one lakh rupees; (ii) where such contravention "
            "relates to sub-clause (b), -- (A) and involves small quantity, with "
            "rigorous imprisonment for a term which may extend to one year, or with "
            "fine, which may extend to ten thousand rupees, or with both; (B) and "
            "involves quantity lesser than commercial quantity but greater than "
            "small quantity, with rigorous imprisonment for a term which may extend "
            "to ten years and with fine which may extend to one lakh rupees; (C) "
            "and involves commercial quantity, with rigorous imprisonment for a "
            "term which shall not be less than ten years but which may extend to "
            "twenty years and shall also be liable to fine which shall not be less "
            "than one lakh rupees but which may extend to two lakh rupees: "
            "Provided that the court may, for reasons to be recorded in the "
            "judgment, impose a fine exceeding two lakh rupees."
        ),
        "context_note": (
            "Cannabis (ganja, charas/hashish) is one of the two most common NDPS "
            "arrest categories. The punishment jumps sharply with quantity -- from "
            "up to 1 year for a small quantity, to up to 10 years for a mid-range "
            "quantity, to a MINIMUM of 10 years (up to 20) for a commercial "
            "quantity. Note bhang is treated differently under this Act's own "
            "definition of 'cannabis' -- whether a specific seized substance counts "
            "is a real, fact-specific question a lawyer needs to look at."
        ),
    },
    {
        "section_number": "21",
        "triggers": [
            ("heroin",), ("smack",), ("brown sugar",), ("opium",), ("morphine",),
            ("cocaine",), ("manufactured drug",), ("diacetylmorphine",),
        ],
        "text": (
            "21. Punishment for contravention in relation to manufactured drugs "
            "and preparations. Whoever, in contravention of any provision of this "
            "Act or any rule or order made or condition of licence granted "
            "thereunder, manufactures, possesses, sells, purchases, transports, "
            "imports inter-State, exports inter-State or uses any manufactured "
            "drug or any preparation containing any manufactured drug shall be "
            "punishable, -- (a) where the contravention involves small quantity, "
            "with rigorous imprisonment for a term which may extend to one year, "
            "or with fine which may extend to ten thousand rupees, or with both; "
            "(b) where the contravention involves quantity, lesser than commercial "
            "quantity but greater than small quantity, with rigorous imprisonment "
            "for a term which may extend to ten years and with fine which may "
            "extend to one lakh rupees; (c) where the contravention involves "
            "commercial quantity, with rigorous imprisonment for a term which "
            "shall not be less than ten years but which may extend to twenty years "
            "and shall also be liable to fine which shall not be less than one "
            "lakh rupees but which may extend to two lakh rupees: Provided that "
            "the court may, for reasons to be recorded in the judgment, impose a "
            "fine exceeding two lakh rupees."
        ),
        "context_note": (
            "This is the section that applies to heroin, morphine, cocaine and "
            "similar 'manufactured drugs' -- the other most common NDPS arrest "
            "category, with the same three quantity tiers and the same sharp jump "
            "at 'commercial quantity' (a MINIMUM of 10 years, up to 20) as "
            "cannabis under Section 20 above."
        ),
    },
    {
        "section_number": "27",
        "triggers": [
            ("just for myself",), ("personal use",), ("own use",), ("consume",),
            ("consumption",), ("was using it",), ("only used it",), ("smoked it",),
            ("for consumption",), ("i use", "myself"),
        ],
        "text": (
            "27. Punishment for consumption of any narcotic drug or psychotropic "
            "substance. Whoever, consumes any narcotic drug or psychotropic "
            "substance shall be punishable, -- (a) where the narcotic drug or "
            "psychotropic substance consumed is cocaine, morphine, diacetylmorphine "
            "or any other narcotic drug or any psychotropic substance as may be "
            "specified in this behalf by the Central Government by notification in "
            "the Official Gazette, with rigorous imprisonment for a term which may "
            "extend to one year, or with fine which may extend to twenty thousand "
            "rupees; or with both; and (b) where the narcotic drug or psychotropic "
            "substance consumed is other than those specified in or under clause "
            "(a), with imprisonment for a term which may extend to six months, or "
            "with fine which may extend to ten thousand rupees or with both."
        ),
        "context_note": (
            "Consumption for one's own use is a genuinely different, much lighter "
            "offence than possession, sale, or transport under Sections 20/21 "
            "above -- up to 1 year (for cocaine/heroin/morphine-type drugs) or up "
            "to 6 months (for others), regardless of quantity, rather than the "
            "quantity-tiered years-long sentences those sections carry. Whether "
            "the actual facts support 'consumption' rather than 'possession' is "
            "exactly the kind of question a lawyer needs to look at closely -- "
            "prosecutors do not always accept a consumption explanation at face "
            "value."
        ),
    },
    {
        "section_number": "37",
        "triggers": [
            ("bail",), ("get out on bail",), ("released",), ("out of jail",),
            ("out of custody",), ("apply for bail",), ("bail application",),
            ("can he get bail",), ("can she get bail",), ("will they get bail",),
        ],
        "text": (
            "37. Offences to be cognizable and non-bailable. (1) Notwithstanding "
            "anything contained in the Code of Criminal Procedure, 1973 -- (a) "
            "every offence punishable under this Act shall be cognizable; (b) no "
            "person accused of an offence punishable for offences under section 19 "
            "or section 24 or section 27A and also for offences involving "
            "commercial quantity shall be released on bail or on his own bond "
            "unless -- (i) the Public Prosecutor has been given an opportunity to "
            "oppose the application for such release, and (ii) where the Public "
            "Prosecutor opposes the application, the court is satisfied that there "
            "are reasonable grounds for believing that he is not guilty of such "
            "offence and that he is not likely to commit any offence while on "
            "bail. (2) The limitations on granting of bail specified in clause (b) "
            "of sub-section (1) are in addition to the limitations under the Code "
            "of Criminal Procedure, 1973 or any other law for the time being in "
            "force, on granting of bail."
        ),
        "context_note": (
            "This is the single most important section for a family asking about "
            "bail -- it flips the normal rule. It only applies to a narrow set of "
            "offences (financing/harbouring, repeat offences, and, most commonly, "
            "any offence involving a 'commercial quantity' -- see Section 2 above) "
            "-- but where it applies, the court cannot grant bail unless it is "
            "actually satisfied there are reasonable grounds to believe the "
            "accused is not guilty AND not likely to reoffend while out on bail -- "
            "the opposite of the usual presumption in favour of bail. See Union of "
            "India v Md Nawaz Khan below for how the Supreme Court actually applies "
            "this test."
        ),
    },
    {
        "section_number": "43",
        "triggers": [
            ("caught",), ("stopped me",), ("stopped him",), ("stopped her",),
            ("public place",), ("bus stand",), ("railway station",), ("checkpost",),
            ("check post",), ("naka",), ("random check",), ("on the street",),
            ("in the market",), ("at the station",),
        ],
        "text": (
            "43. Power of seizure and arrest in public place. Any officer of any "
            "of the departments mentioned in section 42 may -- (a) seize in any "
            "public place or in transit, any narcotic drug or psychotropic "
            "substance or controlled substance in respect of which he has reason "
            "to believe an offence punishable under this Act has been committed, "
            "and, along with such drug or substance, any animal or conveyance or "
            "article liable to confiscation under this Act, any document or other "
            "article which he has reason to believe may furnish evidence of the "
            "commission of an offence punishable under this Act...; (b) detain and "
            "search any person whom he has reason to believe to have committed an "
            "offence punishable under this Act, and if such person has any "
            "narcotic drug or psychotropic substance or controlled substance in "
            "his possession and such possession appears to him to be unlawful, "
            "arrest him and any other person in his company. Explanation.-- For "
            "the purposes of this section, the expression \"public place\" "
            "includes any public conveyance, hotel, shop, or other place intended "
            "for use by, or accessible to, the public."
        ),
        "context_note": (
            "This is the section that usually applies when someone is stopped and "
            "arrested somewhere open to the public (a street, market, bus stand, "
            "station, shop, etc.) rather than in a private home. It is a separate "
            "and somewhat lighter-touch power than a search based on prior, "
            "recorded information -- but the Section 50 right below (being taken "
            "to a Gazetted Officer or Magistrate before a personal search, if you "
            "ask for it) still applies."
        ),
    },
    {
        "section_number": "50",
        "triggers": [
            ("searched me",), ("search me",), ("frisk",), ("pat down",),
            ("personal search",), ("right to be searched",), ("gazetted officer",),
            ("magistrate", "search"), ("didn't tell me", "search"),
            ("did they have to tell", "search"), ("witness", "search"),
            ("search my body",), ("checked my pockets",),
        ],
        "text": (
            "50. Conditions under which search of persons shall be conducted. (1) "
            "When any officer duly authorised under section 42 is about to search "
            "any person under the provisions of section 41, section 42 or section "
            "43, he shall, if such person so requires, take such person without "
            "unnecessary delay to the nearest Gazetted Officer of any of the "
            "departments mentioned in section 42 or to the nearest Magistrate. (2) "
            "If such requisition is made, the officer may detain the person until "
            "he can bring him before the Gazetted Officer or the Magistrate "
            "referred to in sub-section (1). (3) The Gazetted Officer or the "
            "Magistrate before whom any such person is brought shall, if he sees "
            "no reasonable ground for search, forthwith discharge the person but "
            "otherwise shall direct that search be made. (4) No female shall be "
            "searched by anyone excepting a female. (5) When an officer duly "
            "authorised under section 42 has reason to believe that it is not "
            "possible to take the person to be searched to the nearest Gazetted "
            "Officer or Magistrate without the possibility of the person to be "
            "searched parting with possession of any narcotic drug or "
            "psychotropic substance, or controlled substance or article or "
            "document, he may, instead of taking such person to the nearest "
            "Gazetted Officer or Magistrate, proceed to search the person as "
            "provided under section 100 of the Code of Criminal Procedure, 1973. "
            "(6) After a search is conducted under sub-section (5), the officer "
            "shall record the reasons for such belief which necessitated such "
            "search and within seventy-two hours send a copy thereof to his "
            "immediate official superior."
        ),
        "context_note": (
            "This only applies to a PERSONAL search (frisking a person's body) -- "
            "not to a search of a bag, vehicle, or premises. If a person asks for "
            "it, the officer must take them to a nearby Gazetted Officer or "
            "Magistrate to decide whether the search should even happen -- a real, "
            "actionable right at the moment of search, not just paperwork. It does "
            "not have to be offered in writing; being told about it out loud is "
            "enough (see State of Punjab v Baldev Singh below), but not being told "
            "about it at all is a serious problem for the prosecution's case -- "
            "see the same judgment for exactly what that does and doesn't do to a "
            "conviction."
        ),
    },
]


# ---------------------------------------------------------------------------
# Judgment anchors -- only fully-verified, pinned holdings. See module
# docstring for why this stays intentionally short.
# ---------------------------------------------------------------------------

_NDPS_JUDGMENT_ANCHORS = [
    {
        "doctrine": "failure_to_inform_the_section_50_right_can_make_the_conviction_unsustainable",
        "case_key": "state_of_punjab_v_baldev_singh",
        "paragraph_numbers": ["56"],
        "court": "Supreme Court of India (Constitution Bench)",
        "triggers": [
            ("didn't tell me", "search"), ("did they have to tell", "search"),
            ("never told me", "gazetted"), ("never told me", "magistrate"),
            ("wasn't told", "right"), ("wasn't informed", "search"),
            ("did they have to inform",), ("right to be searched",),
            ("gazetted officer",), ("what if they didn't", "search"),
        ],
        "context_note": (
            "State of Punjab v Baldev Singh, (1999) 6 SCC 172, a Constitution "
            "Bench: it is 'imperative' for the officer to inform a person, before "
            "a personal search, of their right under Section 50 to be taken to the "
            "nearest Gazetted Officer or Magistrate -- and this can be told orally, "
            "it does not have to be in writing. The Court deliberately did not "
            "label Section 50 'mandatory' or 'directory' in so many words, but "
            "held that failing to inform the person of this right 'may render the "
            "recovery of the contraband suspect and the conviction and sentence "
            "of an accused bad and unsustainable in law' -- and that an illicit "
            "article seized in a search that violated Section 50 cannot, by "
            "itself, be used as proof of unlawful possession."
        ),
    },
    {
        "doctrine": "section_37_twin_conditions_bail_test",
        "case_key": "union_of_india_v_md_nawaz_khan",
        "paragraph_numbers": ["19", "20", "24"],
        "court": "Supreme Court of India",
        "triggers": [
            ("bail",), ("get out on bail",), ("released",), ("out of jail",),
            ("out of custody",), ("apply for bail",), ("bail application",),
            ("can he get bail",), ("can she get bail",), ("will they get bail",),
        ],
        "context_note": (
            "Union of India v Md Nawaz Khan, (2021) 10 SCC 100: spells out the "
            "Section 37 'twin conditions' the Public Prosecutor and the court must "
            "both apply before bail can be granted for a commercial-quantity (or "
            "similarly serious) NDPS offence -- there must be reasonable grounds "
            "to believe (a) the accused is not guilty of the offence, and (b) the "
            "accused is not likely to commit any offence while on bail. The Court "
            "clarified 'reasonable grounds' is a genuinely stringent standard -- "
            "more than a prima facie look, though still short of actually deciding "
            "guilt or innocence at the bail stage. Worth knowing: this is a case "
            "where the Supreme Court SET ASIDE a High Court's decision to grant "
            "bail, for glossing over this test -- an honest sign of how strictly "
            "it is actually applied, not just a favourable example."
        ),
    },
    {
        "doctrine": "section_67_statement_cannot_be_used_as_a_confession",
        "case_key": "tofan_singh_v_state_of_tamil_nadu",
        "paragraph_numbers": ["155"],
        "court": "Supreme Court of India",
        "triggers": [
            ("made a statement", "ncb"), ("made a statement", "narcotics"),
            ("told the officer",), ("signed a statement",), ("gave a statement",),
            ("confession",), ("confessed",), ("section 67",), ("statement", "used against"),
            ("can they use what he said",), ("can they use what she said",),
            ("used against him in court",), ("used against her in court",),
        ],
        "context_note": (
            "Tofan Singh v State of Tamil Nadu, (2021) 4 SCC 1: a statement made "
            "to an NDPS enforcement officer during investigation cannot be used as "
            "a confession to convict the accused. By a 2:1 majority (R.F. Nariman, "
            "J. and Navin Sinha, J.; Indira Banerjee, J. dissenting), the Court "
            "held that officers empowered under Section 53 of the NDPS Act count "
            "as 'police officers' for the purpose of Section 25 of the Evidence "
            "Act, so any confessional statement made to them is barred the same "
            "way a confession to an ordinary police officer would be -- and a "
            "statement recorded under Section 67 of the NDPS Act specifically "
            "'cannot be used as a confessional statement in the trial of an "
            "offence under the NDPS Act.' This is the current, binding law, "
            "followed since 2021 -- worth knowing that it was genuinely, "
            "substantively contested (not a technicality the dissent raised): "
            "Banerjee, J.'s dissent argued three existing Constitution Bench "
            "rulings already set the real test (whether the officer can file a "
            "formal Section 173 CrPC police report, which NDPS officers cannot), "
            "and that a 3-judge bench could not properly revisit what three "
            "5-judge Constitution Benches had settled -- a real disagreement, "
            "not a weak one, though it did not carry the day."
        ),
    },
]


def _matches(triggers, question_lower: str) -> bool:
    if triggers == _ALWAYS:
        return True
    for group in triggers:
        if all(word in question_lower for word in group):
            return True
    return False


def get_ndps_override(question: str) -> list:
    """Given an NDPS question, returns curated statute sections AND
    judgment paragraphs (shaped for format_retrieved_text_for_prompt /
    generate_grounded_response), combining the two anchor lists above.
    Never raises -- an unresolvable judgment entry is logged and
    skipped, same discipline as every other curated override in this
    project."""
    from retrieval import get_judgment_paragraphs

    q = (question or "").lower()
    results = []

    for entry in _NDPS_STATUTE_ANCHORS:
        if not _matches(entry["triggers"], q):
            continue
        results.append({
            "act": "NDPS",
            "section_number": entry["section_number"],
            "text": entry["text"],
            "context_note": entry["context_note"],
            "source": "curated_override",
        })

    judgment_count = 0
    for entry in _NDPS_JUDGMENT_ANCHORS:
        if judgment_count >= _MAX_ANCHORED_JUDGMENT_PARAGRAPHS:
            break
        if not _matches(entry["triggers"], q):
            continue
        try:
            paras = get_judgment_paragraphs(entry["case_key"], entry["paragraph_numbers"])
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("ndps_doctrine_map: %s lookup failed: %s", entry["case_key"], exc)
            continue
        if not paras:
            logger.warning("ndps_doctrine_map: %r -> no paragraphs for %r %r",
                           entry["doctrine"], entry["case_key"], entry["paragraph_numbers"])
            continue
        for p in paras[:_MAX_JUDGMENT_PARAGRAPHS_PER_ENTRY]:
            results.append({
                "case_name": p.get("case_name"),
                "citation": p.get("citation"),
                "paragraph_number": p.get("paragraph_number"),
                "opinion_author": p.get("opinion_author"),
                "text": p.get("text"),
                "context_note": entry["context_note"],
                "type": "judgment",
                "source": "curated_judgment_override",
            })
            judgment_count += 1

    return results
