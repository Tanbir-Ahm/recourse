"""
cheque_bounce_doctrine_map.py  --  curated judgment anchors for the
Section 138 Negotiable Instruments Act (dishonour-of-cheque) domain.

WHY THIS IS SEPARATE FROM judgment_doctrine_map.py
--------------------------------------------------
judgment_doctrine_map.py is arrest/FIR-tuned: its trigger lists key off
"arrested", "summons", "notice to appear", etc., and resolve to Arnesh
Kumar / Prabir Purkayastha / Satender Antil.  A Section 138 cheque matter
uses the word "summons" too (a Magistrate issues a summons on a 138
complaint) -- so running the arrest doctrine map on a cheque question
wrongly anchors arrest-necessity case law.  This module is only ever
called from the cheque-bounce answer branch in chat_assistant, so its
triggers can be relaxed (scope is already "this is a 138 matter") without
any risk to the arrest path.

The five cheque-bounce judgments (Rangappa, Bir Singh, Prakash Chimanlal
Sheth, Damodar S. Prabhu, Kaveri Plastics) live in the shared corpus and
are listed in semantic_retrieval.OUT_OF_CHAT_DOMAIN_CASE_NAMES so they
never leak into an arrest answer as vocabulary-overlap noise (the
confirmed 2026-09-04 "Rangappa quoted in a partnership-cheating draft"
failure).  find_relevant_sections(query, domain="cheque_bounce") lifts
that exclusion for the cheque path only; this map then guarantees the
four load-bearing paragraphs reach the answer regardless of ranking.

Every entry resolves to real verbatim paragraph text via
retrieval.get_judgment_paragraphs -- no paragraph text is stored here.
Never raises: an unresolvable entry is logged and skipped.
"""

import logging

logger = logging.getLogger(__name__)

# Sentinel: this doctrine is relevant to ANY Section 138 question (the
# scope is already known to be cheque-bounce by the time this runs).
_ALWAYS = "__always__"

_MAX_PARAGRAPHS_PER_ENTRY = 2
_MAX_ANCHORED_PARAGRAPHS = 8


CHEQUE_BOUNCE_ANCHORS = [
    {
        "doctrine": "section_139_presumption_includes_the_debt_and_is_rebuttable",
        "case_key": "rangappa",
        "paragraph_numbers": ["14", "23"],
        "court": "Supreme Court of India",
        "triggers": _ALWAYS,
        "context_note": (
            "Rangappa v Sri Mohan: once the cheque and the signature are "
            "admitted, Section 139 of the Negotiable Instruments Act makes "
            "the court presume the cheque was for a legally enforceable debt "
            "or liability -- the presumption INCLUDES the existence of the "
            "debt, not just receipt of the cheque. It is rebuttable: the "
            "accused can raise a probable defence on a preponderance of "
            "probabilities (not beyond reasonable doubt), and can do so from "
            "the complainant's own evidence and the circumstances without "
            "stepping into the witness box."
        ),
    },
    {
        "doctrine": "a_signed_blank_or_security_cheque_still_attracts_the_presumption",
        "case_key": "bir_singh",
        "paragraph_numbers": ["40", "42"],
        "court": "Supreme Court of India",
        "triggers": [
            ("blank",), ("security",), ("empty cheque",), ("blank cheque",),
            ("signed cheque",), ("filled",), ("fill",), ("filled in",),
            ("wrote the amount",), ("wrote in",), ("put the amount",),
            ("did not sign the amount",), ("only signed",), ("gave him a cheque",),
            ("gave a cheque",), ("handed",), ("guarantee",),
        ],
        "context_note": (
            "Bir Singh v Mukesh Kumar: a cheque that was signed and handed "
            "over voluntarily -- even a blank one given as security -- still "
            "attracts the Section 139 presumption. The holder later filling "
            "in the amount is not an 'alteration' and does not by itself "
            "break the case, unless the drawer proves the cheque was signed "
            "or parted with under threat or coercion, or was stolen. Mutual "
            "trust at the time it was given does not defeat the presumption."
        ),
    },
    {
        "doctrine": "a_138_complaint_is_tried_where_the_payees_bank_branch_is",
        "case_key": "prakash_chimanlal_sheth",
        "paragraph_numbers": ["7", "8"],
        "court": "Supreme Court of India",
        "triggers": [
            ("court",), ("jurisdiction",), ("far",), ("another",), ("different",),
            ("hours",), ("travel",), ("outstation",), ("where", "file"),
            ("which court",), ("city",), ("district",), ("state",), ("distance",),
            ("away",), ("wrong court",), ("cannot travel",), ("far off",),
        ],
        "context_note": (
            "Prakash Chimanlal Sheth v Jagruti Keyur Rajpopat: after the "
            "2015 amendment, Section 142(2)(a) of the Negotiable Instruments "
            "Act fixes territorial jurisdiction for a Section 138 case at the "
            "court where the BRANCH OF THE BANK IN WHICH THE PAYEE (the "
            "complainant) MAINTAINS THE ACCOUNT is situated -- not where the "
            "drawer lives or banks. So a complaint filed far from the "
            "accused's home town can be perfectly valid."
        ),
    },
    {
        "doctrine": "a_138_case_can_be_compounded_settled_at_any_stage",
        "case_key": "damodar_s_prabhu",
        "paragraph_numbers": ["8", "6"],
        "court": "Supreme Court of India",
        "triggers": _ALWAYS,
        "context_note": (
            "Damodar S. Prabhu v Sayed Babalal H: a Section 138 offence is "
            "compoundable (Section 147 of the Negotiable Instruments Act, "
            "which overrides the CrPC scheme), and the Supreme Court has "
            "allowed the parties to settle and compound the case at any "
            "stage of the litigation -- the Court laid down a graded-cost "
            "scale to encourage early settlement rather than late."
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


def get_cheque_bounce_override(question: str) -> list:
    """Given a Section 138 cheque-bounce question, return curated judgment
    matches shaped like semantic_search's judgment matches so they merge
    straight into chat_assistant's retrieved-text pool:

        {case_name, citation, paragraph_number, text, context_note,
         type: "judgment", source: "curated_judgment_override"}

    Round-robin (every matched case gives its first paragraph before any
    case gives its second); deduped by (case_name, paragraph_number);
    capped at _MAX_ANCHORED_PARAGRAPHS. Never raises.
    """
    from retrieval import get_judgment_paragraphs

    q = (question or "").lower()

    per_doctrine = []
    for entry in CHEQUE_BOUNCE_ANCHORS:
        if not _matches(entry["triggers"], q):
            continue
        try:
            paras = get_judgment_paragraphs(entry["case_key"], entry["paragraph_numbers"])
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("cheque_bounce_doctrine_map: %s lookup failed: %s",
                           entry["case_key"], exc)
            continue
        if not paras:
            logger.warning("cheque_bounce_doctrine_map: %r -> no paragraphs for %r %r",
                           entry["doctrine"], entry["case_key"], entry["paragraph_numbers"])
            continue
        order = {str(pn): i for i, pn in enumerate(entry["paragraph_numbers"])}
        paras.sort(key=lambda pp: order.get(str(pp.get("paragraph_number")), 99))
        per_doctrine.append((entry, paras[:_MAX_PARAGRAPHS_PER_ENTRY]))

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
                "case_name": p.get("case_name"),
                "citation": p.get("citation"),
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
