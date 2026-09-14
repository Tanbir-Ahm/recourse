"""
domestic_violence_doctrine_map.py -- curated statute + judgment anchors
for the Protection of Women from Domestic Violence Act, 2005 (PWDVA)
domain, the tool's first legal-domain expansion beyond BNS/BNSS
arrest/FIR law and the cheque-bounce/freeze bolt-ons (design discussed
and agreed with the user 2026-09-14; see memory/vaquill-search-pool.md
for how the wider, unverified candidate pool for this domain works
separately from this trusted tier).

WHY THIS EXISTS, AND WHY IT'S SMALL ON PURPOSE
-----------------------------------------------
This is the TRUSTED tier only -- every section and every judgment
paragraph here was pulled verbatim from Indian Kanoon and read by a
person before being added (same discipline as every other curated
anchor in this project: see cheque_bounce_doctrine_map.py /
statute_doctrine_map.py). It deliberately covers ONLY the small core of
PWDVA anyone would need to understand a first real question -- what
counts as domestic violence, who can apply, and the three main relief
types (protection/residence/monetary orders) -- plus four fully-
verified Supreme Court holdings (Hiral P. Harsora on who can be
proceeded against; D. Velusamy on when a live-in relationship counts;
Satish Chander Ahuja on the shared household not needing to be owned
by the husband; Indra Sarma on when a live-in relationship with an
already-married person does NOT qualify).
This is NOT meant to cover everything PWDVA-related -- for a genuinely
comprehensive answer, chat_assistant also surfaces a WIDER, honestly
UNVERIFIED pool of real judgments via vaquill_search.py, clearly
labelled as "read carefully, not independently verified" -- the two
tiers are deliberately kept separate, never merged into one confidence
level.

Unlike statute_doctrine_map.py (BNS/BNSS), there is no shared
get_statute_section() table for PWDVA, so the verbatim section text is
stored directly here rather than looked up -- same approach
cheque_bounce_doctrine_map.py already uses for its context notes.
Judgment paragraphs are NOT stored here; they resolve via
retrieval.get_judgment_paragraphs (auto-registered from chunks/ at
import, per memory/judgment-chunk-registry-drift.md), same as every
other judgment anchor in this project.
"""
import logging

logger = logging.getLogger(__name__)

_ALWAYS = "__always__"
_MAX_JUDGMENT_PARAGRAPHS_PER_ENTRY = 2
_MAX_ANCHORED_JUDGMENT_PARAGRAPHS = 4


# ---------------------------------------------------------------------------
# Statute anchors -- verbatim PWDVA text, pulled via Indian Kanoon
# (indiankanoon.org/doc/1413588, 406908, 1373165, 1860699, 1130386,
# 485875, 207919) and read by a person before being added here, 2026-09-14.
# ---------------------------------------------------------------------------

_PWDVA_STATUTE_ANCHORS = [
    {
        "section_number": "2",
        "triggers": _ALWAYS,
        "text": (
            "2. Definitions. In this Act, unless the context otherwise requires, "
            "(a) \"aggrieved person\" means any woman who is, or has been, in a "
            "domestic relationship with the respondent and who alleges to have "
            "been subjected to any act of domestic violence by the respondent; "
            "(f) \"domestic relationship\" means a relationship between two "
            "persons who live or have, at any point of time, lived together in "
            "a shared household, when they are related by consanguinity, "
            "marriage, or through a relationship in the nature of marriage, "
            "adoption or are family members living together as a joint family; "
            "(k) \"monetary relief\" means the compensation which the Magistrate "
            "may order the respondent to pay to the aggrieved person, at any "
            "stage during the hearing of an application seeking any relief "
            "under this Act, to meet the expenses incurred and the losses "
            "suffered by the aggrieved person as a result of the domestic "
            "violence; (o) \"protection order\" means an order made in terms of "
            "section 18; (p) \"residence order\" means an order granted in terms "
            "of sub-section (1) of section 19."
        ),
        "context_note": (
            "Who can bring a case: any woman in a 'domestic relationship' with "
            "the person accused -- this covers a wife, but also a mother, "
            "sister, daughter, or a woman in a live-in relationship living in "
            "the same household (see D. Velusamy below for exactly which "
            "live-in relationships qualify)."
        ),
    },
    {
        "section_number": "3",
        "triggers": _ALWAYS,
        "text": (
            "3. Definition of domestic violence. For the purposes of this Act, "
            "any act, omission or commission or conduct of the respondent shall "
            "constitute domestic violence in case it (a) harms or injures or "
            "endangers the health, safety, life, limb or well-being, whether "
            "mental or physical, of the aggrieved person or tends to do so and "
            "includes causing physical abuse, sexual abuse, verbal and "
            "emotional abuse and economic abuse; or (b) harasses, harms, "
            "injures or endangers the aggrieved person with a view to coerce "
            "her or any other person related to her to meet any unlawful "
            "demand for any dowry or other property or valuable security; or "
            "(c) has the effect of threatening the aggrieved person or any "
            "person related to her by any conduct mentioned in clause (a) or "
            "clause (b); or (d) otherwise injures or causes harm, whether "
            "physical or mental, to the aggrieved person."
        ),
        "context_note": (
            "Domestic violence under this Act is broader than physical "
            "assault -- it explicitly includes verbal/emotional abuse (insults, "
            "humiliation) and economic abuse (denying money, destroying "
            "property, blocking access to shared assets), not just physical "
            "or sexual abuse."
        ),
    },
    {
        "section_number": "12",
        "triggers": [
            ("file",), ("apply",), ("application",), ("complaint",),
            ("how do i", "magistrate"), ("approach", "magistrate"),
            ("go to", "court"), ("what do i do",), ("legal action",),
        ],
        "text": (
            "12. Application to Magistrate. (1) An aggrieved person or a "
            "Protection Officer or any other person on behalf of the aggrieved "
            "person may present an application to the Magistrate seeking one "
            "or more reliefs under this Act... (4) The Magistrate shall fix "
            "the first date of hearing, which shall not ordinarily be beyond "
            "three days from the date of receipt of the application by the "
            "Court. (5) The Magistrate shall endeavour to dispose of every "
            "application made under sub-section (1) within a period of sixty "
            "days from the date of its first hearing."
        ),
        "context_note": (
            "This is a real, time-bound legal process, not an informal "
            "complaint -- the law itself expects a first hearing within 3 days "
            "and a decision within 60 days."
        ),
    },
    {
        "section_number": "18",
        "triggers": [
            ("protect",), ("protection order",), ("stop him",), ("restrain",),
            ("keep him away",), ("stop contacting",), ("stop calling",),
        ],
        "text": (
            "18. Protection orders. The Magistrate may, after giving the "
            "aggrieved person and the respondent an opportunity of being "
            "heard and on being prima facie satisfied that domestic violence "
            "has taken place or is likely to take place, pass a protection "
            "order in favour of the aggrieved person and prohibit the "
            "respondent from (a) committing any act of domestic violence; "
            "(c) entering the place of employment of the aggrieved person...; "
            "(d) attempting to communicate in any form whatsoever...; "
            "(e) alienating any assets, operating bank lockers or bank "
            "accounts used or held or enjoyed by both the parties..."
        ),
        "context_note": None,
    },
    {
        "section_number": "19",
        "triggers": [
            ("house",), ("home",), ("residence",), ("throw",), ("thrown out",),
            ("leave the house",), ("shared household",), ("kicked out",),
            ("won't let me stay",), ("in laws house",), ("matrimonial home",),
        ],
        "text": (
            "19. Residence orders. (1) While disposing of an application under "
            "sub-section (1) of section 12, the Magistrate may, on being "
            "satisfied that domestic violence has taken place, pass a "
            "residence order (a) restraining the respondent from dispossessing "
            "or in any other manner disturbing the possession of the aggrieved "
            "person from the shared household, whether or not the respondent "
            "has a legal or equitable interest in the shared household; "
            "(b) directing the respondent to remove himself from the shared "
            "household... Provided that no order under clause (b) shall be "
            "passed against any person who is a woman."
        ),
        "context_note": (
            "The right to stay in the shared household does not depend on "
            "the RESPONDENT owning it (see the statute text above) -- and "
            "the Supreme Court in Satish Chander Ahuja v Sneha Ahuja "
            "confirmed 'shared household' is not limited to a house owned "
            "by, or belonging to the joint family of, the husband; a 2007 "
            "ruling that had read it that narrowly does not lay down "
            "correct law."
        ),
    },
    {
        "section_number": "20",
        "triggers": [
            ("money",), ("maintenance",), ("expenses",), ("medical",),
            ("financial",), ("compensation",), ("lost my job",), ("salary",),
            ("no income",), ("support myself",),
        ],
        "text": (
            "20. Monetary reliefs. (1) While disposing of an application under "
            "sub-section (1) of section 12, the Magistrate may direct the "
            "respondent to pay monetary relief to meet the expenses incurred "
            "and losses suffered by the aggrieved person and any child... such "
            "relief may include (a) the loss of earnings; (b) the medical "
            "expenses; (c) the loss caused due to the destruction, damage or "
            "removal of any property...; and (d) the maintenance for the "
            "aggrieved person as well as her children, if any, including an "
            "order under or in addition to an order of maintenance under "
            "section 125 of the Code of Criminal Procedure, 1973 or any other "
            "law for the time being in force."
        ),
        "context_note": None,
    },
    {
        "section_number": "23",
        "triggers": [
            ("immediate",), ("emergency",), ("urgent",), ("right now",),
            ("today",), ("tonight",), ("interim",), ("scared right now",),
        ],
        "text": (
            "23. Power to grant interim and ex parte orders. (1) In any "
            "proceeding before him under this Act, the Magistrate may pass "
            "such interim order as he deems just and proper. (2) If the "
            "Magistrate is satisfied that an application prima facie discloses "
            "that the respondent is committing, or has committed an act of "
            "domestic violence or that there is a likelihood that the "
            "respondent may commit an act of domestic violence, he may grant "
            "an ex parte order on the basis of the affidavit..."
        ),
        "context_note": (
            "An ex parte order means the Magistrate can act immediately, "
            "before the other side is even heard, if the situation looks "
            "urgent enough on the face of the application."
        ),
    },
]


# ---------------------------------------------------------------------------
# Judgment anchors -- only fully-verified, pinned holdings. See module
# docstring for why this stays intentionally short.
# ---------------------------------------------------------------------------

_PWDVA_JUDGMENT_ANCHORS = [
    {
        "doctrine": "respondent_is_not_limited_to_an_adult_male",
        "case_key": "hiral_p_harsora_v_kusum_narottamdas_harsora",
        "paragraph_numbers": ["46"],
        "triggers": [
            ("mother in law",), ("sister in law",), ("female relative",),
            ("she is not", "man"), ("not a man",), ("woman", "responsible"),
            ("his mother",), ("his sister",), ("women in the house"),
        ],
        "context_note": (
            "Hiral P. Harsora v Kusum Narottamdas Harsora (2016): the "
            "Supreme Court struck down the words \"adult male\" that used to "
            "limit who could be named as the person responsible for the "
            "violence -- a complaint can now be filed against a female "
            "relative (e.g. a mother-in-law or sister-in-law) too, not only "
            "a male."
        ),
    },
    {
        "doctrine": "when_a_live_in_relationship_counts_as_domestic",
        "case_key": "d_velusamy_v_d_patchaiammal",
        "paragraph_numbers": ["33", "34"],
        "triggers": [
            ("live in",), ("living together",), ("not married",),
            ("girlfriend",), ("partner",), ("live-in",), ("boyfriend",),
            ("relationship", "marriage"),
        ],
        "context_note": (
            "D. Velusamy v D. Patchaiammal (2010): not every live-in "
            "relationship qualifies. The Supreme Court requires the couple "
            "to have held themselves out to society as being like spouses, "
            "both been of legal age and otherwise free to marry, and to "
            "have voluntarily lived together for a significant period -- a "
            "casual or purely sexual arrangement does not qualify."
        ),
    },
    {
        "doctrine": "shared_household_is_not_limited_to_a_house_the_husband_owns",
        "case_key": "satish_chander_ahuja_v_sneha_ahuja",
        "paragraph_numbers": ["84"],
        "triggers": [
            ("papers",), ("rent agreement",), ("own the house",), ("ownership",),
            ("my name",), ("his name",), ("not on the papers",), ("belongs to",),
            ("in laws house",), ("father in law",), ("owned by",),
        ],
        "context_note": (
            "Satish Chander Ahuja v Sneha Ahuja (2020): 'shared household' "
            "is NOT limited to a house owned by, or belonging to the joint "
            "family of, the husband -- an earlier ruling (S.R. Batra v "
            "Taruna Batra, 2007) that read it that narrowly was held to "
            "not lay down correct law."
        ),
    },
    {
        # Sourced and reviewed 2026-09-14 via the "Judgment Review Docket"
        # artifact -- corroboration evidence (6/10 independent citing
        # courts confirm, incl. the Supreme Court itself in Harsora;
        # confirmed in an independent second copy; matches the top
        # independently-re-derived candidate) reviewed and approved by
        # the user before this entry was added. See
        # memory/judgment-corroboration-tool.md.
        "doctrine": "live_in_with_someone_already_married_does_not_qualify",
        "case_key": "indra_sarma_v_v_k_v_sarma",
        "paragraph_numbers": ["65"],
        "triggers": [
            ("married", "live in"), ("married", "living together"),
            ("married", "girlfriend"), ("married", "boyfriend"),
            ("already married",), ("he was married",), ("she was married",),
            ("knew he was married",), ("knew she was married",),
            ("his wife", "live in"), ("his wife", "living together"),
        ],
        "context_note": (
            "Indra Sarma v V.K.V. Sarma (2013): a live-in relationship "
            "does NOT count as a 'relationship in the nature of marriage' "
            "under this Act if the woman knew the man was already married "
            "to someone else -- the Supreme Court held such a relationship "
            "has none of the essential characteristics of a marriage, so "
            "it falls outside this Act's protection. This is narrower than, "
            "and does not override, D. Velusamy's general 4-part test above "
            "-- it addresses specifically the 'already married' situation."
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


def get_domestic_violence_override(question: str) -> list:
    """Given a domestic-violence question, returns curated statute
    sections AND judgment paragraphs (shaped for
    format_retrieved_text_for_prompt / generate_grounded_response),
    combining the two anchor lists above. Never raises -- an
    unresolvable judgment entry is logged and skipped, same discipline
    as cheque_bounce_doctrine_map.get_cheque_bounce_override."""
    from retrieval import get_judgment_paragraphs

    q = (question or "").lower()
    results = []

    for entry in _PWDVA_STATUTE_ANCHORS:
        if not _matches(entry["triggers"], q):
            continue
        results.append({
            "act": "PWDVA",
            "section_number": entry["section_number"],
            "text": entry["text"],
            "context_note": entry["context_note"],
            "source": "curated_override",
        })

    judgment_count = 0
    for entry in _PWDVA_JUDGMENT_ANCHORS:
        if judgment_count >= _MAX_ANCHORED_JUDGMENT_PARAGRAPHS:
            break
        if not _matches(entry["triggers"], q):
            continue
        try:
            paras = get_judgment_paragraphs(entry["case_key"], entry["paragraph_numbers"])
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("domestic_violence_doctrine_map: %s lookup failed: %s",
                           entry["case_key"], exc)
            continue
        if not paras:
            logger.warning("domestic_violence_doctrine_map: %r -> no paragraphs for %r %r",
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
