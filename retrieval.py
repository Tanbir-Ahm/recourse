
"""
Retrieval layer, Phase 1: exact lookup, not embeddings.

Two lookup functions:
  - get_statute_section(act, section_number): pulls a BNS/BNSS section's
    real text by its exact section number, from the already-sourced and
    chunked statute corpus.
  - get_judgment_paragraphs(case_key, paragraph_numbers): pulls specific
    paragraph(s) from a sourced judgment by exact paragraph number.

Neither uses embeddings or similarity search. Both are dictionary lookups
against pre-chunked corpus files, because main.py never needs "find me
something similar" -- it always cites an exact section number or an exact
doctrine it already knows the source of. See JUDGMENT_CITATION_MAP below
for the specific doctrine -> paragraph mappings, each individually verified
against the real chunked text before being added (not guessed).

This module has NO knowledge of compliance logic -- it only fetches real
source text. Whatever calls it (an LLM extraction step, or eventually a
compliance-check function wanting to show its source) is responsible for
reading and using that text. This keeps the deterministic-classification-
decides / LLM-only-extracts boundary intact: adding source text access
doesn't mean Python is inferring anything new from it.
"""

import json
import logging
import os


_STATUTE_CHUNK_FILES = {
    "BNS": "chunks/bharatiya_nyaya_sanhita_2023_chunks.json",
    "BNSS": "chunks/bharatiya_nagarik_suraksha_sanhita_2023_chunks.json",
    # Phase 3b, loc-transit-remand-plan: real IT Act criminal sections
    # (66, 66B-E, 67, 67A-B, 72, 72A). Section 66A is deliberately NOT
    # in this chunk file -- it was struck down as unconstitutional and
    # is handled by itact_section_status.py's dedicated override instead
    # of a "current text" lookup (see that module's docstring).
    "ITACT": "chunks/information_technology_act_2000_chunks.json",
    # Negotiable Instruments Act 1881: the 19 cheque-bounce sections (Section 138 domain),
    # sourced from India Code by build_ni_act_statute_chunks.py. Registered here so it is
    # never mistaken for a judgment file by _auto_register_judgment_chunks().
    "NIACT": "chunks/negotiable_instruments_act_1881_chunks.json",
}

_JUDGMENT_CHUNK_FILES = {
    "arnesh_kumar": "chunks/arnesh_kumar_v_state_of_bihar_chunks.json",
    "vihaan_kumar": "chunks/vihaan_kumar_v_state_of_haryana_chunks.json",
    "satender_kumar_antil_2026": "chunks/satender_kumar_antil_v_central_bureau_of_investigation_(2026)_chunks.json",
    "prabir_purkayastha": "chunks/prabir_purkayastha_v_state_(nct_of_delhi)_chunks.json",
    "dk_basu": "chunks/dk_basu_v_state_of_west_bengal_chunks.json",
    "nalsa": "chunks/national_legal_services_authority_v_union_of_india_chunks.json",
    "pankaj_bansal": "chunks/pankaj_bansal_v_union_of_india_chunks.json",
    "youth_bar_association": "chunks/youth_bar_association_v_union_of_india_chunks.json",
    "rakhi_mitra": "chunks/rakhi_mitra_and_anr_v_state_of_west_bengal_chunks.json",
    "sri_manjunath_mp": "chunks/sri_manjunath_m_p_v_state_of_karnataka_chunks.json",
    # ADDED 2026-09-01 (Project 2 currency-check discovery): these 8
    # case_keys are referenced by JUDGMENT_CITATION_MAP (freeze and
    # cheque-bounce domains) and their chunk files exist on disk, but
    # were NEVER registered here. CONFIRMED REAL BUG: get_judgment_doctrine()
    # silently returned None/empty for all 8 of these doctrine_keys --
    # no exception (main.py's _result() swallows exceptions around this
    # call, but there wasn't even one to swallow -- _load_judgment_chunks
    # just returned None for an unregistered case_key, and the "if
    # paragraphs:" check in _result() silently skipped attaching
    # source_paragraphs). Practical effect: every "Read the source"
    # expander for these 8 doctrines has been empty/absent in the app
    # this entire session, even though the compliance checks themselves
    # cite these cases correctly by name in their explanation text.
    "tapas_d_neogy": "chunks/state_of_maharashtra_v_tapas_d_neogy_chunks.json",
    "malabar_gold": "chunks/malabar_gold_and_diamond_limited_v_union_of_india_chunks.json",
    "neelkanth_pharma_logistics": "chunks/neelkanth_pharma_logistics_pvt_ltd_v_union_of_india_chunks.json",
    "rangappa": "chunks/rangappa_v_sri_mohan_chunks.json",
    "bir_singh": "chunks/bir_singh_v_mukesh_kumar_chunks.json",
    "damodar_s_prabhu": "chunks/damodar_s_prabhu_v_sayed_babalal_h_chunks.json",
    "kaveri_plastics": "chunks/kaveri_plastics_v_mahdoom_bawa_bahrudeen_noorul_chunks.json",
    "prakash_chimanlal_sheth": "chunks/prakash_chimanlal_sheth_v_jagruti_keyur_rajpopat_chunks.json",
}


def _auto_register_judgment_chunks():
    """Every non-statute *_chunks.json on disk should be reachable by
    get_judgment_paragraphs(). The hardcoded map above kept drifting out of
    sync with the corpus -- every seeding batch (2026-09-01, and again the
    09-05/09-06/09-08 batches) added chunk files that were never registered
    here, so get_judgment_doctrine() / any doctrine anchor pointing at them
    silently resolved to nothing (see the 2026-09-01 CONFIRMED REAL BUG
    note above -- it recurred). This scans chunks/ once at import and adds
    any unregistered judgment file under its '<stem before _v_>' key
    (matching the existing convention: arnesh_kumar_v_state_of_bihar ->
    'arnesh_kumar'), plus its full stem as an alias. Hardcoded entries are
    never overwritten -- a few of them key on the post-'_v_' half
    deliberately (e.g. 'tapas_d_neogy' from 'state_of_maharashtra_v_...').
    """
    import glob
    statute_basenames = {os.path.basename(p) for p in _STATUTE_CHUNK_FILES.values()}
    registered_paths = {os.path.normpath(p) for p in _JUDGMENT_CHUNK_FILES.values()}
    for path in glob.glob("chunks/*_chunks.json"):
        base = os.path.basename(path)
        if base in statute_basenames or os.path.normpath(path) in registered_paths:
            continue
        stem = base[: -len("_chunks.json")]
        key = stem.split("_v_")[0]
        for candidate in (key, stem):
            if candidate and candidate not in _JUDGMENT_CHUNK_FILES:
                _JUDGMENT_CHUNK_FILES[candidate] = path


try:
    _auto_register_judgment_chunks()
except Exception:  # never let a corpus-scan hiccup break import
    logging.getLogger("retrieval").exception("_auto_register_judgment_chunks failed")


_statute_cache = {}
_judgment_cache = {}


def _load_statute_chunks(act):
    if act not in _STATUTE_CHUNK_FILES:
        return None
    if act not in _statute_cache:
        path = _STATUTE_CHUNK_FILES[act]
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
        _statute_cache[act] = {c["section_number"]: c for c in chunks}
    return _statute_cache[act]


def _load_judgment_chunks(case_key):
    if case_key not in _JUDGMENT_CHUNK_FILES:
        return None
    if case_key not in _judgment_cache:
        path = _JUDGMENT_CHUNK_FILES[case_key]
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            _judgment_cache[case_key] = json.load(f)
    return _judgment_cache[case_key]


def get_statute_section(act, section_number):
    """Returns the real statute text for a section, keyed by BASE section
    number only (e.g. "106", not "106(2)") -- confirmed the chunker splits
    statutes at the top-level numbered-section boundary only, so a
    subsection-specific request returns the whole parent section's text,
    not just that subsection. Returns None if the act or section isn't
    found, never raises, so callers can treat a miss the same honest way
    the rest of this project treats "Cannot Determine" cases.

    act: "BNS" or "BNSS"
    section_number: e.g. "106", "106(2)" (subsection suffix is stripped
        automatically), "35"
    """
    chunks_by_section = _load_statute_chunks(act)
    if chunks_by_section is None:
        return None
    base = section_number.split("(")[0].strip()
    chunk = chunks_by_section.get(base)
    if chunk is None:
        return None
    return {
        "act": act,
        "section_number": base,
        "text": chunk["text"],
    }


def get_judgment_paragraphs(case_key, paragraph_numbers, opinion_author=None):
    """Returns the real text of specific paragraph(s) from a sourced
    judgment. paragraph_numbers can be a single string/int or a list, to
    support doctrines that span more than one paragraph (confirmed real
    case: Arnesh Kumar's directions span fallback_12 and fallback_13).

    opinion_author: only needed for multi-opinion documents (confirmed
    real case: Vihaan Kumar has two -- pass "ABHAY S. OKA" or
    "KOTISWAR SINGH" to disambiguate; for single-opinion documents, leave
    as None).

    Returns None if the case isn't found. Returns a list of paragraph
    dicts (possibly empty, if none of the requested numbers exist) rather
    than raising, for the same honest-miss reason as get_statute_section.
    """
    chunks = _load_judgment_chunks(case_key)
    if chunks is None:
        return None

    if isinstance(paragraph_numbers, (str, int)):
        paragraph_numbers = [paragraph_numbers]
    wanted = set(str(p) for p in paragraph_numbers)

    results = []
    for c in chunks:
        if str(c["paragraph_number"]) not in wanted:
            continue
        if opinion_author is not None and c.get("opinion_author") != opinion_author:
            continue
        results.append({
            "case_name": c["case_name"],
            "citation": c["citation"],
            "paragraph_number": c["paragraph_number"],
            "opinion_author": c.get("opinion_author"),
            "text": c["text"],
        })
    return results


# ---------------------------------------------------------------------------
# Judgment citation map: doctrine -> exact source location.
#
# Each entry below was individually verified against the real chunked text
# before being added here -- not guessed from the case name or a general
# sense of what the case is "about". This is what lets main.py's existing
# citation strings (e.g. "D.K. Basu safeguards", "Youth Bar Association
# guidelines (a)-(c)") resolve to real, checkable source text on demand.
#
# REQUIRED CHECK before adding any new entry: several sourced judgments
# contain genuine DUPLICATE paragraph numbers -- confirmed real cases
# include NALSA, Prabir Purkayastha, L. Muruganantham, Rakhi Mitra,
# Satender Kumar Antil 2026, Sri Manjunath M P, Prakash Ranjan, and even
# Vihaan Kumar's own Oka opinion (see judgment_qa.py's
# find_duplicate_paragraph_numbers docstring for the confirmed causes).
# Before mapping a doctrine to a paragraph number in one of these
# documents, run judgment_qa.py and confirm that specific number is NOT
# a duplicate for that document -- or if it is, confirm which occurrence
# is the document's own reasoning (not a quoted passage) before using it.
# get_judgment_paragraphs already handles an unverified duplicate safely
# (returns all matches rather than silently picking one), but a
# JUDGMENT_CITATION_MAP entry should point to a specific, human-checked
# occurrence, not rely on that fallback.
# ---------------------------------------------------------------------------

JUDGMENT_CITATION_MAP = {
    "arnesh_kumar_checklist": {
        "case_key": "arnesh_kumar",
        "paragraph_numbers": ["fallback_12", "fallback_13"],
        "opinion_author": None,
        "manual_override_text": (
            "All the State Governments to instruct its police officers not to automatically arrest "
            "when a case under Section 498-A of the IPC is registered but to satisfy themselves about "
            "the necessity for arrest under the parameters laid down above flowing from Section 41, "
            "Cr.PC;\n\n"
            "All police officers be provided with a check list containing specified sub-clauses under "
            "Section 41(1)(b)(ii);\n\n"
            "The police officer shall forward the check list duly filed and furnish the reasons and "
            "materials which necessitated the arrest, while forwarding/producing the accused before "
            "the Magistrate for further detention;\n\n"
            "The Magistrate while authorising detention of the accused shall peruse the report "
            "furnished by the police officer in terms aforesaid and only after recording its "
            "satisfaction, the Magistrate will authorise detention;\n\n"
            "The decision not to arrest an accused, be forwarded to the Magistrate within two weeks "
            "from the date of the institution of the case with a copy to the Magistrate which may be "
            "extended by the Superintendent of police of the district for the reasons to be recorded "
            "in writing;\n\n"
            "Notice of appearance in terms of Section 41A of Cr.PC be served on the accused within two "
            "weeks from the date of institution of the case, which may be extended by the "
            "Superintendent of Police of the District for the reasons to be recorded in writing;\n\n"
            "Failure to comply with the directions aforesaid shall apart from rendering the police "
            "officers concerned liable for departmental action, they shall also be liable to be "
            "punished for contempt of court to be instituted before High Court having territorial "
            "jurisdiction.\n\n"
            "We hasten to add that the directions aforesaid shall not only apply to the cases under "
            "Section 498-A of the I.P.C. or Section 4 of the Dowry Prohibition Act, the case in hand, "
            "but also such cases where offence is punishable with imprisonment for a term which may be "
            "less than seven years or which may extend to seven years; whether with or without fine."
        ),
        "verified_note": (
            "Confirmed: fallback_12 and fallback_13 are ~1500-char blind chunks (Arnesh Kumar's "
            "paragraph numbers did not survive PDF extraction -- see chunk_judgments.py notes), so the "
            "raw chunk boundaries include text before and after the actual checklist directions (the "
            "preceding paragraph on anticipatory bail volume, and the trailing instruction to circulate "
            "the judgment to Chief Secretaries). manual_override_text is a hand-trimmed exact excerpt of "
            "just the 7 checklist/timeline/consequence directions plus the 7-year applicability line, "
            "taken verbatim from the same source text -- no wording changed, only the surrounding "
            "context removed. This is the ONE entry in this map needing manual trimming; every other "
            "doctrine below has real paragraph-number boundaries and needs no override."
        ),
    },
    "dk_basu_safeguards": {
        "case_key": "dk_basu",
        "paragraph_numbers": ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
        "opinion_author": None,
        "verified_note": (
            "Confirmed: paragraphs 2-11 are the eleven numbered requirements "
            "(memo of arrest, witness attestation, right to inform family, "
            "medical exam, etc.), matching check_dk_basu_memo's checks "
            "one-to-one -- e.g. para 2 = witness-attested memo, para 5 = "
            "family/friend informed, paras 7-8 = medical examination. "
            "PROVENANCE (corrected 2026-09-01): the sourced text is the "
            "1 Aug 1997 monitoring order, which quotes these requirements "
            "VERBATIM from the substantive 18 Dec 1996 judgment, D.K. Basu "
            "v State of West Bengal, (1997) 1 SCC 416 -- the standard "
            "citation for these safeguards. Requirement wording is "
            "verbatim-faithful; the consequences passage in the sourced "
            "text is the 1997 bench's paraphrase. See the corpus record's "
            "'notes' field for the full account."
        ),
    },
    "vihaan_kumar_written_grounds": {
        "case_key": "vihaan_kumar",
        "paragraph_numbers": ["10"],
        "opinion_author": "ABHAY S. OKA",
        "verified_note": (
            "Confirmed: paragraph 10 (Oka, J.'s lead opinion) establishes "
            "the Article 22(1) written-grounds-of-arrest requirement, "
            "referencing Pankaj Bansal directly. opinion_author is required "
            "here since this document genuinely has two separate opinions "
            "(see chunk_judgments.py notes) and paragraph '10' only exists "
            "meaningfully within Oka's opinion."
        ),
    },
    "youth_bar_association_fir_copy_guidelines": {
        "case_key": "youth_bar_association",
        "paragraph_numbers": ["12"],
        "opinion_author": None,
        "verified_note": (
            "Confirmed: paragraph 12 contains the full lettered guideline "
            "list (a) through (k), including the accused's early-FIR-copy "
            "right (a)-(c) and the 24/48/72-hour online upload requirement "
            "(d), both cited by main.py's check_early_fir_copy_right and "
            "check_fir_uploaded_online functions."
        ),
    },
    
        "rakhi_mitra_arnesh_kumar_consequences": {
        # APPLYING/ILLUSTRATIVE PRECEDENT, NOT a rule-source -- this is a
        # Calcutta HC judgment restating and applying Arnesh Kumar's own
        # consequence rule, not creating new binding law. Per user framing
        # (2026-08-26): High Court judgments in this corpus mainly
        # reiterate/apply existing Supreme Court precedent. If ever
        # surfaced to a person, this should be presented as "here's how a
        # High Court applied the Arnesh Kumar consequence rule", clearly
        # subordinate to and never in place of the arnesh_kumar_checklist
        # entry above, which is the actual Supreme Court source.
        "case_key": "rakhi_mitra",
        "paragraph_numbers": ["18"],
        "opinion_author": None,
        "verified_note": (
            "Confirmed: paragraph 18 directly quotes and restates Arnesh Kumar paragraph 11's "
            "consequence rule (departmental action + contempt of court for non-compliance with the "
            "S.35(3)/S.41A notice requirement). This paragraph number is NOT one of Rakhi Mitra's own "
            "flagged duplicates (see judgment_qa.py's duplicate-paragraph check) -- confirmed unambiguous, "
            "single occurrence. NOTE: this document's own paragraph 11 (distinct from this doctrine) is a "
            "genuine duplicate -- do not confuse the two; paragraph 18 was chosen specifically because it "
            "carries no such ambiguity."
        ),
    },
    "sri_manjunath_arnesh_kumar_application": {
        # APPLYING/ILLUSTRATIVE PRECEDENT, NOT a rule-source -- same status
        # as rakhi_mitra_arnesh_kumar_consequences above. This Karnataka HC
        # judgment applies Arnesh Kumar's vague-allegation reasoning to
        # quash a specific S.498A-style proceeding; it does not create new
        # binding law. Subordinate to, never a substitute for, the
        # arnesh_kumar_checklist entry.
        "case_key": "sri_manjunath_mp",
        "paragraph_numbers": ["22", "27"],
        "opinion_author": None,
        "verified_note": (
            "Confirmed: paragraph 22 directly names and quotes Arnesh Kumar v State of Bihar "
            "(paragraphs 10, 11, 11.1-11.8). Paragraph 27 is the Court's own finding applying that "
            "doctrine to these specific facts ('baseless, general and sweeping allegations... abuse of "
            "process of law'), immediately followed by the formal quashing order at paragraph 28. Both "
            "22 and 27 confirmed NOT among this document's flagged duplicates (see judgment_qa.py) -- "
            "unambiguous, single occurrences each."
        ),
    },
    
    "tapas_d_neogy_bank_account_as_property": {
        "case_key": "tapas_d_neogy",
        "paragraph_numbers": ["fallback_4", "fallback_6"],
        "opinion_author": None,
        "verified_note": (
            "Confirmed via direct chunk inspection (2026-08-30): "
            "fallback_4 contains Section 102 CrPC's actual provisions as "
            "extracted and examined by the Court ('Coming now to the "
            "provisions of Section 102 of the Code of Criminal "
            "Procedure, the said provisions are extracted herein below "
            "in extenso'). fallback_6 contains the Court's own core "
            "reasoning on why a bank account qualifies as 'property' "
            "capable of seizure -- the money-becomes-unidentifiable-once-"
            "mixed analysis. Other fallback chunks in this document "
            "(fallback_7 through fallback_10) are the Court SURVEYING "
            "other courts' prior decisions before reaching its own "
            "conclusion -- useful context but not the holding itself, "
            "deliberately not cited here to keep the citation focused on "
            "the Court's own reasoning. Chunked via fixed_size_fallback "
            "since no genuine ascending paragraph-number sequence was "
            "found in this document -- confirmed via direct regex "
            "inspection, same limitation this corpus already accepts "
            "for Arnesh Kumar. judgment_qa.py flagged this document's "
            "caption/closing as unrecognised -- CONFIRMED FALSE POSITIVE "
            "(direct text check, 2026-08-30): both the opening and "
            "closing are genuine, complete, real judgment text; the QA "
            "tool's pattern-matching was calibrated against the "
            "PDF-extraction path's typical caption/closing format and "
            "does not yet recognise this document's real but "
            "differently-formatted caption/closing (sourced via the "
            "HTML/API path, not a downloaded PDF)."
        ),
    },
    "neelkanth_blanket_freeze_disproportionate": {
        "case_key": "neelkanth_pharma_logistics",
        "paragraph_numbers": ["11", "12"],
        "opinion_author": None,
        "verified_note": (
            "Confirmed via direct chunk inspection (2026-08-30): "
            "paragraph 11 states the core fact pattern (an account with "
            "a Rs. 93,50,05,208/- balance frozen entirely over an "
            "innocuous Rs. 200/- credit) and the Court's finding that "
            "there is nothing to suggest the petitioner is a suspect or "
            "accused. Paragraph 12 (FIRST occurrence -- see duplicate "
            "note below) is the Court's own direct holding that freezing "
            "the entire account, rather than preserving only the "
            "disputed Rs. 200/-, caused serious adverse financial "
            "consequences including dishonoured cheques and business "
            "disruption. IMPORTANT -- CONFIRMED REAL DUPLICATE "
            "(judgment_qa.py flagged this, verified by direct chunk "
            "comparison, 2026-08-30): paragraph '12' appears TWICE in "
            "this document's chunks. The SECOND occurrence "
            "('...doubtful if the amounts in question could be even "
            "recovered from the petitioners...proceeds of crime.') is "
            "NOT this Court's own reasoning -- it is the tail end of a "
            "quoted excerpt from Dr. Sajir v. Reserve Bank of India, "
            "2023 SCC OnLine Ker 9087, which this judgment quotes at "
            "length. Only the FIRST occurrence of paragraph 12 (this "
            "Court's own text) should be treated as Neelkanth's holding; "
            "retrieval.py's get_judgment_doctrine returns both "
            "occurrences by design (same honest-collision pattern used "
            "elsewhere in this project) -- any renderer surfacing this "
            "doctrine should make clear which fragment is being shown if "
            "both appear. SCOPE LIMITATION: this judgment does NOT "
            "engage with BNSS Sections 106/107's specific textual scheme "
            "(confirmed by direct text search) -- it argues purely from "
            "Article 21/proportionality principles, complementary to but "
            "distinct from Malabar Gold's BNSS-textual holding below."
        ),
    },
    "malabar_gold_section_106_107_textual_holding": {
        "case_key": "malabar_gold",
        "paragraph_numbers": ["fallback_22", "fallback_24"],
        "opinion_author": None,
        "verified_note": (
            "Confirmed via direct chunk inspection (2026-08-30): "
            "fallback_22 states that the Investigating Agency may "
            "proceed under Section 107 BNSS to debit-freeze or attach "
            "funds, framing this as the ONLY lawful route (as opposed to "
            "Section 106, which the Court holds is evidentiary-seizure-"
            "only). fallback_24 contains the Court's direct holding that "
            "'any blanket or disproportionate freezing of bank accounts' "
            "is impermissible absent the proper Section 107 procedure. "
            "OTHER RELEVANT CHUNKS NOT CITED HERE, noted for "
            "completeness: fallback_16, fallback_17, and fallback_19 "
            "also discuss the Section 106/107 distinction and reference "
            "Kartik Yogeshwar Chatur v. Union of India (Bombay HC, 2025 "
            "SCC OnLine Bom 4778, NOT independently sourced/verified in "
            "this corpus yet) -- fallback_16 and fallback_17 open with a "
            "quotation mark and appear to be quoting another source "
            "rather than this Court's own direct language, so were not "
            "selected as the primary citation. CONFIRMED DATA-QUALITY "
            "NOTE (2026-08-30): this document's fixed_size_fallback "
            "chunking has scattered a recurring Delhi HC digital-"
            "signature portal footer into multiple chunks throughout the "
            "document (confirmed at fallback_14, fallback_18, "
            "fallback_23) -- this appears to repeat multiple times "
            "within the source HTML, unlike the single-footer-per-page "
            "pattern this project's PDF-extraction pipeline already "
            "handles. Not a content-loss issue (the real holding text is "
            "fully intact in the chunks cited above), but worth knowing "
            "this footer-noise pattern exists for this HTML-sourced "
            "document specifically. judgment_qa.py flagged this "
            "document's caption/closing as unrecognised -- CONFIRMED "
            "FALSE POSITIVE (direct text check, 2026-08-30), same "
            "reasoning as Tapas D. Neogy's note above."
        ),
    },
    
    "rangappa_section_139_presumption_mandatory": {
        "case_key": "rangappa",
        "paragraph_numbers": ["14", "34"],
        "opinion_author": None,
        "verified_note": (
            "PARAGRAPH NUMBERS CONFIRMED 2026-09-01 (Project 2 backlog "
            "close-out) via direct chunk inspection of chunks/rangappa_v_"
            "sri_mohan_chunks.json: paragraph 14 states 'the presumption "
            "mandated by Section 139 of the Act does indeed include the "
            "existence of a legally enforceable debt or liability'; "
            "paragraph 34 states the rebuttal standard is 'preponderance "
            "of probabilities', not proof beyond reasonable doubt. Both "
            "confirmed as clean, unambiguous single chunks -- no "
            "duplicate-paragraph-number collision for either. NOTE: this "
            "chunk file also contains 'paragraphs' numbered 118, 138, 139 "
            "-- these are statute section numbers quoted within the "
            "judgment text, mis-parsed as paragraph markers by "
            "chunk_judgments.py's regex, not real paragraph numbers; "
            "confirmed not relevant here and not used."
        ),
    },
    "bir_singh_blank_cheque_and_informal_loan": {
        "case_key": "bir_singh",
        "paragraph_numbers": ["40"],
        "opinion_author": None,
        "verified_note": (
            "PARAGRAPH NUMBER CONFIRMED 2026-09-01 (Project 2 backlog "
            "close-out) via direct chunk inspection of chunks/bir_singh_v_"
            "mukesh_kumar_chunks.json: paragraph 40 states 'Even a blank "
            "cheque leaf, voluntarily signed and handed over by the "
            "accused, which is towards some payment, would attract "
            "presumption under Section 139... in the absence of any "
            "cogent evidence to show that the cheque was not issued in "
            "discharge of a debt.' Confirmed as a clean, unambiguous "
            "single chunk -- no duplicate-paragraph-number collision. "
            "CORRECTION (2026-09-01): this verified_note previously still "
            "restated the retracted 'informal/friendly loan does not "
            "defeat the presumption' claim as a 'Vital holding confirmed' "
            "-- despite HANDOFF_PROJECT2.md and main.py's own "
            "explain_debt_presumption_status docstring already stating "
            "this claim was found wrong and retracted (the 'friendly "
            "loan' phrase appears only in Bir Singh's facts recitation, "
            "never as a Court holding). This was a documentation-only "
            "inconsistency, not a live bug -- get_judgment_doctrine only "
            "ever returns paragraph text, never this verified_note field, "
            "to callers, so the stale claim never reached the app or any "
            "user-facing output. Removed here for consistency; this "
            "doctrine_key now documents only the real, confirmed "
            "blank-cheque holding."
        ),
    },
    "damodar_prabhu_compounding_cost_scheme": {
        "case_key": "damodar_s_prabhu",
        "paragraph_numbers": ["15"],
        "opinion_author": None,
        "verified_note": (
            "PARAGRAPH NUMBER CONFIRMED 2026-09-01 (Project 2 backlog "
            "close-out) via direct chunk inspection of chunks/damodar_s_"
            "prabhu_v_sayed_babalal_h_chunks.json: paragraph 15 IS 'THE "
            "GUIDELINES' section itself and states the exact operative "
            "figures -- (b) 10% of the cheque amount if compounding is "
            "sought before the Magistrate after the first/second hearing; "
            "(c) 15% before the Sessions Court or High Court; (d) 20% "
            "before the Supreme Court -- confirming the 10/15/20% figures "
            "compute_settlement_cost_incentive needs precisely, not just "
            "approximately. Confirmed as a clean, unambiguous single "
            "chunk (2798 chars) -- no duplicate-paragraph-number "
            "collision (note: this chunk file separately contains a "
            "spurious 'paragraph 147' -- a Section 147 statute reference "
            "mis-parsed as a paragraph marker, and a genuine duplicate "
            "'12' -- neither is paragraph 15, not relevant here)."
        ),
    },
    "kaveri_plastics_amount_specifically_demanded": {
        "case_key": "kaveri_plastics",
        "paragraph_numbers": ["5"],
        "opinion_author": None,
        "verified_note": (
            "CORRECTION (2026-09-01, Project 2 discovery), then RESOLVED "
            "same day: the previous version of this entry claimed "
            "paragraph_numbers=['14'], with a verified_note asserting "
            "paragraph 14 was 'SPECIFICALLY CONFIRMED via direct "
            "reading.' That was WRONG -- the real Suman Sethi quote ('We "
            "have to ascertain the meaning of the words the said amount "
            "of money...') sits at paragraph 5.2.1, not 14, per direct "
            "text search of corpus/kaveri_plastics_v_mahdoom_bawa_"
            "bahrudeen_noorul.json. This document's decimal-style "
            "numbering (4.1, 5.2, 5.2.1, 6.3...) was never captured as "
            "separate chunks by chunk_judgments.py's regex -- but "
            "confirmed via direct chunk inspection that the text WASN'T "
            "lost: chunks/kaveri_plastics_v_mahdoom_bawa_bahrudeen_"
            "noorul_chunks.json's paragraph '5' chunk (2798+ chars, "
            "spanning the whole Section 138 'said amount' analysis from "
            "5. through immediately before 6.) contains the full 5.2.1 "
            "text verbatim, including the exact Suman Sethi quote. Fixed "
            "by citing the coarser but real and complete paragraph '5', "
            "not by re-chunking. TRADEOFF, stated plainly: paragraph 5 is "
            "a large chunk (~17,000 chars) covering more than just the "
            "5.2.1 holding -- a renderer showing this will show the "
            "surrounding analysis too, not an isolated quote. This is "
            "honest and complete, just coarser-grained than the other "
            "entries in this map. A future re-chunk with decimal-aware "
            "paragraph boundaries (not done here) could tighten this to "
            "just 5.2.1 -- not required for this citation to be usable "
            "and accurate now. IMPORTANT -- CONFIRMED REAL DUPLICATE, same "
            "honest-collision pattern as Neelkanth's paragraph 12 above: "
            "paragraph '5' appears TWICE in this chunk file. The FIRST "
            "occurrence (119 chars, 'That you the noticees assured my "
            "client that the aforesaid cheque shall be honoured on "
            "presentation') is from the quoted DEMAND NOTICE text in the "
            "facts recitation, NOT the Court's own reasoning -- do not "
            "cite this one. Only the SECOND occurrence (16912 chars, "
            "opening 'Having gathered the compass of the controversy...') "
            "is the Court's own analysis and contains the real Suman "
            "Sethi quote. get_judgment_doctrine returns both by design; "
            "any renderer surfacing this doctrine must make clear which "
            "fragment is being shown, or use only the second."
        ),
    },
    "prakash_chimanlal_sheth_jurisdiction": {
        "case_key": "prakash_chimanlal_sheth",
        "paragraph_numbers": ["7", "8"],
        "opinion_author": None,
        "verified_note": (
            "PARAGRAPH NUMBERS CONFIRMED 2026-09-01 (Project 2 backlog "
            "close-out) via direct chunk inspection of chunks/prakash_"
            "chimanlal_sheth_v_jagruti_keyur_rajpopat_chunks.json: "
            "paragraph 7 states the Section 142(2)(a) rule itself (a "
            "complaint must be tried 'only by a Court within whose local "
            "jurisdiction... the branch of the bank where the payee... "
            "maintains the account, is situated'); paragraph 8 applies it "
            "to this case's own facts (complaint properly filed at "
            "Mangalore, where the appellant's account was held). Both "
            "confirmed as clean, unambiguous single chunks -- no "
            "duplicate-paragraph-number collision for either."
        ),
    },
}



def get_judgment_doctrine(doctrine_key):
    """Convenience wrapper: resolves a doctrine key from
    JUDGMENT_CITATION_MAP directly to its real source text, so callers
    don't need to know the underlying case_key/paragraph_numbers/
    opinion_author details. Returns None if the doctrine key isn't mapped.

    If the map entry has a manual_override_text (confirmed real need: only
    arnesh_kumar_checklist, whose blind fallback chunks include irrelevant
    surrounding text), that hand-trimmed excerpt is returned instead of the
    raw chunk lookup -- still the case's own real words, just without the
    extra context a human wouldn't want repeated on every check."""
    entry = JUDGMENT_CITATION_MAP.get(doctrine_key)
    if entry is None:
        return None

    if "manual_override_text" in entry:
        chunks = get_judgment_paragraphs(entry["case_key"], entry["paragraph_numbers"], opinion_author=entry["opinion_author"])
        case_name = chunks[0]["case_name"] if chunks else None
        citation = chunks[0]["citation"] if chunks else None
        return [{
            "case_name": case_name,
            "citation": citation,
            "paragraph_number": "checklist (excerpted)",
            "opinion_author": None,
            "text": entry["manual_override_text"],
        }]

    return get_judgment_paragraphs(
        entry["case_key"],
        entry["paragraph_numbers"],
        opinion_author=entry["opinion_author"],
    )


if __name__ == "__main__":
    print("=== Statute lookup test ===")
    r = get_statute_section("BNSS", "106(2)")
    print(f"BNSS 106(2) -> base section 106, {len(r['text']) if r else 0} chars" if r else "NOT FOUND")

    print("\n=== Judgment doctrine lookup test ===")
    for key in JUDGMENT_CITATION_MAP:
        result = get_judgment_doctrine(key)
        total_chars = sum(len(p["text"]) for p in result) if result else 0
        print(f"{key}: {len(result) if result else 0} paragraph(s), {total_chars} chars")
        
