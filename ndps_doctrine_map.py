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

MOHANLAL -- THE SAME COLLISION PATTERN, A DIFFERENT CAUSE (2026-09-25)
----------------------------------------------------------------------
Union of India v Mohanlal, (2016) 3 SCC 379: a single-opinion judgment
(T.S. Thakur, CJI and Kurian Joseph, J., no dissent) -- but most of it
is a nationwide data-gathering exercise, with page after page of
state-by-state seizure/storage/destruction tables, each internally
numbered "1) ANDHRA PRADESH", "2) ASSAM", etc. up past 20. Checked
directly before trusting the automated chunk file (same discipline as
Tofan Singh, not repeated blindly): paragraph_number "20" in
pilot_chunks/union_of_india_v_mohanlal_chunks.json collided with item
#20 of that state list ("Ministry of Home Affairs NCB"), not the real
paragraph 20 ("To sum up we direct as under..."). A different root
cause than Tofan Singh's (plain sequential numbering inside a big data
table colliding with real paragraph numbers, not a quoted-judgment
opinion-detection failure) but the same practical risk -- citing
"paragraph 20" unmodified would have surfaced a meaningless data row
alongside the real holding. Fixed the same way: a manually constructed,
single-paragraph chunks/union_of_india_v_mohanlal_chunks.json (chunk_
method "manual_verified_extraction"), verified against the real source
text read in full before promotion. The pilot_chunks/ copy is
unchanged, for the same reason as Tofan Singh's.

VIJAYSINH CHANDUBHA JADEJA -- A THIRD, DIFFERENT CHUNKING FAILURE (2026-09-25)
----------------------------------------------------------------------
Vijaysinh Chandubha Jadeja v State of Gujarat, (2011) 1 SCC 609: a
clean, unanimous 5-judge Constitution Bench decision, no dissent, no
large data tables -- the simplest of the four judgments promoted so
far. Even so, checked directly before trusting the automated chunk
file, and found a third, distinct chunking failure: the pilot_chunks
file only has 10 chunks, with real paragraph detection stopping after
"9" and the entire rest of the judgment (23,733 chars, including the
actual paragraph 22 holding) dumped into one oversized leftover chunk
labelled "9". Root cause here is neither a false opinion-split (Tofan
Singh) nor a data-table collision (Mohanlal): this PDF extraction left
a bare page-number digit on its own line after every page break (e.g.
a stray "1" or "2"), which interrupted chunk_judgments.py's ascending-
paragraph-sequence detector partway through a genuinely simple,
correctly-numbered document. Fixed the same way as the other two: a
manually constructed, single-paragraph core chunk
(chunks/vijaysinh_chandubha_jadeja_v_state_of_gujarat_chunks.json,
chunk_method "manual_verified_extraction"), with the stray page-break
digits and a footnote-number artifact ("Poll14," -> "Poll,") cleaned
out of the stored text -- confirmed by direct comparison against the
real source, not assumed. Three different judgments promoted tonight,
three different root causes, the same fix each time: never trust
automated chunking to have handled a document correctly by default --
check the specific paragraph being cited actually appears clean and
whole before using it, every single promotion, not just the first one
where a problem was found.

NOOR AGA -- CHECKED, AND ACTUALLY FINE (2026-09-25)
----------------------------------------------------------------------
Noor Aga v State of Punjab, (2008) 16 SCC 417: checked the same way as
the three above before trusting it. This time the check came back
clean -- the document's own final "CONCLUSION" section (a genuine,
correctly-numbered 1-6 list) chunked correctly with real, resolvable
paragraph numbers; only the un-numbered main body ahead of it landed
in one big "preamble" bucket, which is fine since the conclusion list
is what's cited here. Used directly from the pilot chunk file (minus
the embedding field), no manual reconstruction needed. Recorded
deliberately, not just the failures: checking every citation before
trusting it does not mean assuming every document is broken -- it
means not assuming either way until actually looked at.

KARNAIL SINGH -- A CHUNKING FAILURE, AND AN EXTERNAL CLAIM THAT DIDN'T
HOLD UP UNDER CHECKING (2026-09-25)
----------------------------------------------------------------------
Karnail Singh v State of Haryana, (2009) 8 SCC 539, a Constitution
Bench: the pilot chunk file's paragraph detector found NO genuine
ascending sequence anywhere in this document at all (likely confused
by the many numbered case citations sprinkled through the text, e.g.
"4 (2004) 11 SCC 576") and fell back entirely to 14 fixed-size chunks,
none of them aligned to the judgment's real paragraph numbers. Fixed
the same way as the others: a manually constructed, single-paragraph
core chunk (paragraph 17, the real 4-point (a)-(d) conclusion), text
clean, no page-break artifacts this time.

Separately, the user was shown (by a third-party tool, pasted in) a
critique claiming the real holding was actually in "paragraph 35", not
17. Checked directly rather than accepted: the source PDF this project
actually uses (api.sci.gov.in/jonew/judis/35186.pdf) has only 18
paragraphs total, and paragraph 17 is the exact four-point conclusion
already cited -- confirmed a second way by fetching Indian Kanoon's own
copy of the same case directly (the very source the pasted critique
claimed to cite), which independently confirmed 18 paragraphs total
and the same paragraph 17 text verbatim. The "paragraph 35" claim did
not hold up on either source and was not used. Two smaller, genuinely
useful precision points FROM that same critique were incorporated into
the context_note anyway (the 72-hour detail added by the 2001
amendment; "may constitute sufficient compliance" as a more precise
phrase than "excused") -- a critique being wrong on its central claim
doesn't mean every point in it is worthless, but the central claim
itself was checked and rejected, not assumed correct because a tool
asserted it confidently with citations attached.

MUKESH SINGH / MOHAN LAL -- A CRITIQUE THAT WAS RIGHT, AND A PATTERN FOR AN
OVERRULED PRECEDENT (2026-09-25)
----------------------------------------------------------------------
While reviewing Mohan Lal v State of Punjab, (2018) 17 SCC 627 (the "the
informant and the investigator must not be the same person" case) for
promotion, the user was shown a second third-party critique -- this one
correct, unlike the Karnail Singh one. Checked independently before
accepting it (same discipline either way, not just when skeptical):
Mohan Lal was EXPRESSLY OVERRULED by a 5-judge Constitution Bench in
Mukesh Singh v State (Narcotic Branch of Delhi), (2020) 10 SCC 120,
confirmed via multiple independent sources and by reading Mukesh
Singh's actual operative paragraph 12 directly, not just the critique's
summary. Promoting Mohan Lal's old rule as if it were still current law
would have been a real, substantive error, not a stylistic one.

Sourced Mukesh Singh fresh (not part of the original 8-case pilot
batch) per the standing judgment-sourcing-policy -- user supplied the
real api.sci.gov.in link. Same paragraph-collision problem as every
other document tonight: this 107K-char, 62-page judgment quotes an
earlier precedent's own "paragraph 12" at length before reaching its
own real paragraph 12 conclusion -- fixed the same way, a manually
verified single-paragraph core chunk.

DESIGN PATTERN for an overruled case the user wants kept for context,
not as current law: two separate doctrine-map entries. Mukesh Singh
carries the general topical triggers (informant/investigator questions)
and states the current, correct rule. Mohan Lal carries ONLY a narrow
trigger keyed to the user naming that case specifically ("mohan lal"),
and its context_note is framed entirely around being overruled, in
capital letters, pointing back to Mukesh Singh -- structurally, Mohan
Lal's holding can never surface on its own without Mukesh Singh's
correct current-law context also being retrievable for the same
general question. Verified directly (not assumed): a general question
about the same-officer scenario returns only Mukesh Singh; naming
"Mohan Lal" specifically returns both, together.

STATE OF RAJASTHAN V PARMANAND -- ANOTHER CRITIQUE, MOSTLY RIGHT, ONE REAL
OMISSION CAUGHT (2026-09-25)
----------------------------------------------------------------------
A third critique, checked the same way as the other two (never accepted
on tone or confident-looking citations alone). This one's central
claims held up against direct re-reading of the already-in-hand source
text -- no new external fetch needed, the primary source was already
fully read. Two real, worthwhile corrections taken from it: (1) calling
paragraph 14 the "primary" ground overstated what the Court itself
said -- it presented paragraphs 14 and 15 as two independent breaches,
neither formally ranked above the other ("this... is AGAIN a breach...
ON THIS GROUND ALSO"), so the entry now describes them as two
independent problems, not primary/secondary. (2) A genuine omission:
the original summary left out that the Court explicitly declined to
say whether the result would differ if the accused had *voluntarily*
asked to be searched before the raiding-party officer -- what's
actually prohibited is the POLICE offering that as a third option, not
a person choosing it themselves. Confirmed present verbatim in the
source ("We are not expressing any opinion on the question whether if
the respondents had voluntarily expressed...") and now included in the
context_note. Chunk file itself had page-break artifacts around both
paragraphs (and paragraph 15 ran into the judge-signature block) but no
paragraph-number collision this time -- fixed with the same manual,
cleaned extraction as every other promotion, not because collision was
assumed, but because it was checked.

UNION OF INDIA V SHIV SHANKER KESARI -- THE FINAL CASE OF THIS BATCH,
CLEAN, AND A CRITIQUE THAT TURNED OUT TO BE A REWORDING, NOT A CORRECTION
(2026-09-25)
----------------------------------------------------------------------
Auto-chunking worked perfectly here -- all 15 paragraphs matched their
real numbers with no collision and no fallback, verified directly
against the raw source text before use. A pasted critique of the
analysis was checked the same way as the other three this batch; it
turned out to be a legitimate rewording, not a substantive fact-check
catch, but it did surface one real imprecision worth fixing: the
original analysis said the High Court's bail order was set aside because
it recorded "no finding at all on either twin condition." The judgment's
own case-specific application paragraph (paragraph 13) explicitly names
only ONE concrete defect -- the High Court gave no reason for its view
that the contraband wasn't from the accused's exclusive possession. The
broader point, that the High Court never properly engaged with EITHER of
Section 37's two conditions at all, is the Court's remand instruction
(paragraph 14, "afresh... keeping in view THE PARAMETERS of Section 37"
-- plural) and the appellant's own argument (paragraph 3), not a
separately stated paragraph-13 finding. The context_note below is
written to match that precision: it states what paragraph 7 and
paragraph 11 hold as general law (what "reasonable grounds" means, and
that a bail court is not conducting a mini-trial), without overstating
what the case-specific application paragraph itself says.
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
        "doctrine": "seized_drugs_must_be_sampled_before_a_magistrate_and_stored_securely",
        "case_key": "union_of_india_v_mohanlal",
        "paragraph_numbers": ["20"],
        "court": "Supreme Court of India",
        "triggers": [
            ("sample", "drug"), ("sample", "seized"), ("tested",),
            ("was it tested",), ("who tested",), ("magistrate", "sample"),
            ("chain of custody",), ("tampered",), ("switched", "drug"),
            ("how is evidence stored",), ("where is the drug kept",),
            ("storage", "seized"), ("disposal of drug",), ("destroyed", "drug"),
        ],
        "context_note": (
            "Union of India v Mohanlal, (2016) 3 SCC 379: this case is not a "
            "single person's appeal -- it is the Supreme Court's own nationwide "
            "supervisory inquiry (with a court-appointed Amicus Curiae gathering "
            "data from every state) into how seized drugs are actually sampled, "
            "stored, and disposed of after arrest. The Court held that samples of "
            "the seized drug must be drawn in the presence of, and certified by, "
            "a Magistrate -- there is no legal basis for sampling at the moment "
            "of seizure itself -- and that this must happen 'without undue "
            "delay' after seizure. It found, bluntly, that no state or central "
            "agency had actually built the secure double-locked storage the law "
            "requires (everyone was using ordinary police 'malkhana' rooms meant "
            "for all kinds of seized property), calling this 'a complete failure "
            "bordering criminal negligence', and that only 16% of drugs seized "
            "over a 10-year period had actually been disposed of. Less about any "
            "one person's guilt, more about the integrity of the evidence used "
            "against them -- if the Magistrate-supervised sampling procedure "
            "wasn't properly followed in a specific case, that is a real, "
            "Supreme-Court-backed point a defence can raise."
        ),
    },
    {
        "doctrine": "section_50_needs_genuine_not_merely_substantial_compliance",
        "case_key": "vijaysinh_chandubha_jadeja_v_state_of_gujarat",
        "paragraph_numbers": ["22"],
        "court": "Supreme Court of India (Constitution Bench)",
        "triggers": [
            ("substantial compliance",), ("kind of told me",), ("sort of told me",),
            ("vaguely told me", "search"), ("mentioned", "gazetted officer"),
            ("asked if i wanted", "search"), ("did they really tell",),
            ("was that enough",), ("good enough", "search"), ("is that compliance",),
        ],
        "context_note": (
            "Vijaysinh Chandubha Jadeja v State of Gujarat, (2011) 1 SCC 609, a "
            "5-judge Constitution Bench: closes a loophole some courts had opened "
            "after Baldev Singh -- a vague or half-hearted mention of the right to "
            "be searched before a Gazetted Officer or Magistrate is NOT enough. "
            "The Court expressly rejected the idea that 'substantial compliance' "
            "(e.g. an officer merely asking 'if you wish you may be searched in "
            "the presence of a gazetted officer or a Magistrate') satisfies "
            "Section 50 -- holding instead that informing the person of this "
            "right 'is mandatory and requires a strict compliance.' It also added "
            "a practical preference beyond what Baldev Singh said: where the Act "
            "gives the officer a choice between a Gazetted Officer and a "
            "Magistrate, the officer should, in the first instance, try to take "
            "the person before a Magistrate rather than a Gazetted Officer, since "
            "a Magistrate 'enjoys more confidence of the common man' and adds "
            "legitimacy to the search."
        ),
    },
    {
        "doctrine": "reverse_burden_is_valid_but_recovery_must_first_be_proven",
        "case_key": "noor_aga_v_state_of_punjab",
        "paragraph_numbers": ["1", "5"],
        "court": "Supreme Court of India",
        "triggers": [
            ("reverse burden",), ("burden of proof",), ("presumption of guilt",),
            ("innocent until proven",), ("do i have to prove",), ("prove i didn't",),
            ("prove innocence",), ("unlawful possession", "presume"),
            ("is that even constitutional",), ("can they just presume",),
        ],
        "context_note": (
            "Noor Aga v State of Punjab, (2008) 16 SCC 417: two things, read "
            "together. First, Sections 35 and 54 of the NDPS Act (the sections "
            "that let a court presume guilt/unlawful possession once certain "
            "facts are shown, shifting the burden onto the accused) are 'not "
            "ultra vires the Constitution' -- they are valid law, not something "
            "that can be challenged as unconstitutional on that basis alone. "
            "Second, and just as important: 'the fact of recovery has not been "
            "proved beyond all reasonable doubt which is required to be "
            "established before the doctrine of reverse burden is applied.' In "
            "other words, the reverse burden is a real, lawful tool, but it only "
            "switches on AFTER the prosecution has itself first proven, beyond "
            "reasonable doubt and following the proper legal procedure, that the "
            "drug was actually recovered from the accused -- it is never a "
            "shortcut that lets the prosecution skip proving the basic facts of "
            "the case in the first place. Here, real discrepancies in the "
            "evidence, an unfair investigation, and recovery not made 'as per "
            "the procedure established by law' meant that starting point was "
            "never established, so the conviction was set aside."
        ),
    },
    {
        "doctrine": "section_42_needs_the_paperwork_but_genuine_urgency_can_delay_it",
        "case_key": "karnail_singh_v_state_of_haryana",
        "paragraph_numbers": ["17"],
        "court": "Supreme Court of India (Constitution Bench)",
        "triggers": [
            ("did they record", "information"), ("wrote it down",),
            ("informed", "superior"), ("no warrant",), ("without a warrant",),
            ("acted on a tip",), ("acted on information",), ("section 42",),
            ("did they follow procedure",), ("proper procedure", "search"),
        ],
        "context_note": (
            "Karnail Singh v State of Haryana, (2009) 8 SCC 539, a Constitution "
            "Bench: resolves a conflict between two earlier rulings on Section 42 "
            "-- the power to enter, search, seize, and arrest WITHOUT a warrant, "
            "based on information the officer already had. Normally, compliance "
            "with Sections 42(1) and 42(2) -- recording that information in "
            "writing and sending a copy to the superior officer (72 hours, after "
            "the 2001 amendment) -- 'should normally precede the entry, search "
            "and seizure.' But where the information comes in during a genuinely "
            "urgent situation -- 'the question is one of urgency and expediency' "
            "-- and any delay risks the evidence being destroyed or the person "
            "escaping, the recording and reporting may reasonably be postponed "
            "and done as soon as practical afterward; a satisfactory explanation "
            "for that delay may constitute sufficient compliance. What is never "
            "acceptable, urgency or not: total non-compliance. If the officer "
            "never records the information and never informs a superior at all "
            "-- especially if they had the time to do so, e.g. while sitting at "
            "the police station -- that remains 'a clear violation of section "
            "42', full stop. This complements the tool's existing Section 43 "
            "(public-place seizure) and Section 50 (personal-search rights) "
            "coverage by adding the specific test for Section 42 procedural "
            "compliance."
        ),
    },
    {
        "doctrine": "informant_being_investigator_is_not_automatic_bias",
        "case_key": "mukesh_singh_v_state_narcotic_branch_of_delhi",
        "paragraph_numbers": ["12"],
        "court": "Supreme Court of India (Constitution Bench)",
        "triggers": [
            ("same officer", "investigat"), ("same police officer",),
            ("officer who caught", "investigat"), ("informant", "investigat"),
            ("complainant", "investigat"), ("arrested him", "investigat"),
            ("same person", "arrest", "investigat"), ("is that fair",),
            ("is that biased",), ("conflict of interest", "police"),
        ],
        "context_note": (
            "Mukesh Singh v State (Narcotic Branch of Delhi), (2020) 10 SCC 120, "
            "a 5-judge Constitution Bench: the same officer who reported/arrested "
            "someone also being the one who investigates is NOT, by itself, "
            "automatic proof of bias or unfairness. The Court held: 'merely "
            "because the informant is the investigator... the accused is not "
            "entitled to acquittal... The matter has to be decided on a case to "
            "case basis' -- meaning something more specific has to actually be "
            "shown (a real reason to think that particular officer was biased or "
            "acted unfairly), not just the dual role on its own. This is the "
            "current, controlling law -- it EXPRESSLY OVERRULED an earlier, "
            "stricter Supreme Court ruling (Mohan Lal v State of Punjab, 2018) "
            "that had treated the dual role as automatically fatal to the "
            "prosecution's case. If someone specifically asks about that older "
            "Mohan Lal case, see the separate, clearly-labelled entry for it "
            "below -- it is kept only as historical context, not as current law."
        ),
    },
    {
        "doctrine": "mohan_lal_historical_context_only_overruled",
        "case_key": "mohan_lal_v_state_of_punjab",
        "paragraph_numbers": ["25"],
        "court": "Supreme Court of India",
        "triggers": [
            ("mohan lal",),
        ],
        "context_note": (
            "OVERRULED -- NOT CURRENT LAW. Mohan Lal v State of Punjab, (2018) 17 "
            "SCC 627, once held that an informant also acting as the "
            "investigating officer automatically made the investigation unfair, "
            "entitling the accused to acquittal without needing to show any "
            "specific bias. A 5-judge Constitution Bench in Mukesh Singh v State "
            "(Narcotic Branch of Delhi), (2020) 10 SCC 120, EXPRESSLY OVERRULED "
            "this: 'A contrary decision of this Court in the case of Mohan Lal "
            "v. State of Punjab... and any other decision taking a contrary view "
            "... are not good law and they are specifically overruled.' Kept "
            "here only so the tool recognises the case by name and can correctly "
            "say it no longer reflects the law -- see the Mukesh Singh entry "
            "above for what actually applies today. Never cite Mohan Lal's own "
            "holding as current law."
        ),
    },
    {
        "doctrine": "section_50_right_must_be_told_individually_not_as_a_group",
        "case_key": "state_of_rajasthan_v_parmanand",
        "paragraph_numbers": ["14", "15"],
        "court": "Supreme Court of India",
        "triggers": [
            ("arrested together",), ("both of us", "search"), ("two of us", "search"),
            ("same notice",), ("one notice", "both"), ("group notice",),
            ("only one of us signed",), ("signed for both",), ("signed for me",),
            ("third option", "search"), ("offered", "raiding"),
        ],
        "context_note": (
            "State of Rajasthan v Parmanand, (2014) 5 SCC 345: two independent "
            "problems, both breaches of Section 50 on their own. First -- where "
            "more than one person is searched, EACH person must be individually "
            "told about their right to be searched before a Gazetted Officer or "
            "Magistrate; one shared notice for two people is not enough, even if "
            "one of them signs 'for' the other. The Court held the communication "
            "'has to be clear, unambiguous and individual' -- 'a joint "
            "communication of the right may not be clear or unequivocal... may "
            "create confusion... may result in diluting the right.' Second, "
            "separately -- an officer offering a third choice beyond the two the "
            "law actually allows (here, a member of the SAME raiding party, "
            "instead of only a Gazetted Officer or Magistrate) is also a breach, "
            "because that person isn't genuinely independent. Worth knowing: the "
            "Court left open whether it would be different if the person had "
            "*voluntarily* asked to be searched before that raiding-party "
            "member themselves -- what's not allowed is the officer offering it "
            "as an alternative. Also worth noting: Section 50 only applies when "
            "the PERSON is searched, not merely a bag or container someone is "
            "carrying -- but if both the bag and the person are searched (as "
            "here), the whole exercise falls under Section 50."
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
    {
        "doctrine": "reasonable_grounds_for_bail_means_more_than_a_plausible_story",
        "case_key": "union_of_india_v_shiv_shanker_kesari",
        "paragraph_numbers": ["7", "11"],
        "court": "Supreme Court of India",
        "triggers": [
            ("reasonable grounds",), ("prima facie",), ("substantial probable cause",),
            ("do they have to prove", "innocent"), ("does the judge have to", "innocent"),
            ("mini trial",), ("mini-trial",), ("find him not guilty", "bail"),
            ("declare", "innocent", "bail"), ("what counts as reasonable",),
            ("how strong", "grounds", "bail"), ("what does reasonable grounds mean",),
        ],
        "context_note": (
            "Union of India v Shiv Shanker Kesari, (2007) 7 SCC 798: explains what "
            "Section 37's first bail condition -- 'reasonable grounds for believing "
            "the accused is not guilty' -- actually requires. 'Reasonable grounds' "
            "means more than a prima facie (surface-level plausible) case; it "
            "requires 'substantial probable cause' -- real facts and circumstances "
            "sufficient in themselves to justify that satisfaction, not just an "
            "absence of an obviously weak case. At the same time, the bail court is "
            "NOT being asked to hold a mini-trial or pronounce a finding of 'not "
            "guilty' -- that satisfaction is for the limited purpose of deciding "
            "bail only, nothing more. In this case, the Supreme Court set aside a "
            "High Court bail grant because the High Court's own order gave no "
            "reason at all for its conclusion that the seized drugs weren't from "
            "the accused's exclusive possession, and sent the bail application back "
            "to be decided afresh applying Section 37 properly."
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
