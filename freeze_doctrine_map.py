"""
freeze_doctrine_map.py  --  curated judgment anchors for the bank-
account freeze / attachment domain (BNSS Sections 106 and 107, formerly
Section 102 CrPC).

WHY THIS IS SEPARATE FROM judgment_doctrine_map.py
--------------------------------------------------
Same reason as cheque_bounce_doctrine_map.py: judgment_doctrine_map is
arrest/FIR-tuned and a freeze narrative shares vocabulary ("police",
"investigation", "custody" of funds, "no notice") that would wrongly
fire the arrest-safeguard anchors. This module is only ever called from
the freeze answer branch in chat_assistant (_answer_inline_domain), so
its triggers can be relaxed -- scope is already "this is a bank-freeze
matter".

The three freeze judgments (State of Maharashtra v Tapas D. Neogy,
Neelkanth Pharma Logistics v Union of India, Malabar Gold and Diamond
Ltd v Union of India) live in the shared corpus and are listed in
semantic_retrieval.OUT_OF_CHAT_DOMAIN_CASE_NAMES so they never leak into
an arrest answer as vocabulary-overlap noise.
find_relevant_sections(query, domain="freeze") lifts that exclusion for
the freeze path only; this map then guarantees the load-bearing
paragraphs reach the answer regardless of ranking.

Every entry resolves to real verbatim paragraph text via
retrieval.get_judgment_paragraphs -- no paragraph text is stored here.
Never raises: an unresolvable entry is logged and skipped.
"""

import logging

logger = logging.getLogger(__name__)

# Sentinel: this doctrine is relevant to ANY bank-freeze question (scope
# is already known to be a freeze matter by the time this runs).
_ALWAYS = "__always__"

_MAX_PARAGRAPHS_PER_ENTRY = 2
_MAX_ANCHORED_PARAGRAPHS = 8


FREEZE_ANCHORS = [
    {
        "doctrine": "a_bank_account_is_property_the_police_may_freeze_but_only_under_investigation",
        "case_key": "tapas_d_neogy",
        "paragraph_numbers": ["fallback_11", "fallback_5"],
        "court": "Supreme Court of India",
        "triggers": _ALWAYS,
        "context_note": (
            "State of Maharashtra v Tapas D. Neogy: a bank account is "
            "'property', and the police CAN issue a direction to a bank "
            "prohibiting operation of an account (the power now sits in "
            "BNSS Section 106/107, formerly Section 102 CrPC) -- so a "
            "freeze is not automatically illegal. But the two "
            "preconditions must be met: it must be property, and there "
            "must be a suspicion of an offence in relation to THAT "
            "property."
        ),
    },
    {
        "doctrine": "attachment_of_a_bank_account_runs_through_the_magistrate_under_bnss_107",
        "case_key": "malabar_gold",
        "paragraph_numbers": ["fallback_17", "fallback_16"],
        "court": "Delhi High Court",
        "triggers": _ALWAYS,
        "context_note": (
            "Malabar Gold and Diamond Ltd v Union of India: BNSS Section "
            "106 (seizure) can be done by a police officer with an "
            "ex-post-facto report to the Magistrate; BNSS Section 107 "
            "(attachment / debit-freeze of a bank account, aimed at "
            "securing proceeds of crime) can be effected ONLY on the "
            "order of the jurisdictional Magistrate, who hears the "
            "parties (or passes an interim order where notice would "
            "defeat the purpose). A police email to the bank is not a "
            "Section 107 order."
        ),
    },
    {
        "doctrine": "blanket_freeze_of_the_whole_account_is_disproportionate_lien_the_traceable_sum",
        "case_key": "neelkanth_pharma_logistics",
        "paragraph_numbers": ["17", "27"],
        "court": "Delhi High Court",
        "triggers": _ALWAYS,
        "context_note": (
            "Neelkanth Pharma Logistics v Union of India: where the "
            "investigating agency has identified a SPECIFIC sum said to "
            "be tainted, freezing the ENTIRE account is disproportionate "
            "and arbitrary -- especially where the account-holder is "
            "neither an accused nor a suspect and may be an unwitting "
            "recipient. Marking a lien on the identifiable disputed "
            "amount 'should be the first and foremost option'; the rest "
            "of the account should be released. The agency must also "
            "record reasons."
        ),
    },
    {
        "doctrine": "a_bare_ncrp_complaint_number_or_bank_email_is_not_a_lawful_basis_to_debit_freeze",
        "case_key": "malabar_gold",
        "paragraph_numbers": ["fallback_21", "fallback_8"],
        "court": "Delhi High Court",
        "triggers": [
            ("ncrp",), ("cybercrime portal",), ("cyber crime portal",),
            ("complaint number",), ("acknowledgement number",), ("acknowledgment number",),
            ("helpline",), ("1930",), ("i4c",), ("email",), ("e-mail",), ("letter",),
            ("bank froze",), ("bank blocked",), ("bank has frozen",), ("bank frozen",),
            ("without any order",), ("no order",), ("no court order",),
            ("no notice",), ("without notice",), ("no fir",), ("without an fir",),
            ("customer",), ("someone who paid me",), ("payment i received",),
            ("upi",), ("received money",), ("unilateral",),
        ],
        "context_note": (
            "Malabar Gold and Diamond Ltd v Union of India: a bank / "
            "intermediary may put the DISPUTED AMOUNT on lien on the "
            "strength of an NCRP / cybercrime-helpline complaint "
            "acknowledgement number -- but it CANNOT debit-freeze the "
            "whole account on that basis; only the investigating agency, "
            "acting under BNSS Section 107, can. Merely that the person "
            "who paid you may have committed an offence is not, by "
            "itself, a lawful basis to freeze your account, and you are "
            "at least entitled to be told the reasons."
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


def get_freeze_override(question: str) -> list:
    """Given a bank-freeze question, return curated judgment matches
    shaped like semantic_search's judgment matches so they merge straight
    into chat_assistant's retrieved-text pool:

        {case_name, citation, paragraph_number, text, context_note,
         type: "judgment", source: "curated_judgment_override"}

    Round-robin (every matched case gives its first paragraph before any
    case gives its second); deduped by (case_name, paragraph_number);
    capped at _MAX_ANCHORED_PARAGRAPHS. Never raises.
    """
    from retrieval import get_judgment_paragraphs

    q = (question or "").lower()

    per_doctrine = []
    for entry in FREEZE_ANCHORS:
        if not _matches(entry["triggers"], q):
            continue
        try:
            paras = get_judgment_paragraphs(entry["case_key"], entry["paragraph_numbers"])
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("freeze_doctrine_map: %s lookup failed: %s", entry["case_key"], exc)
            continue
        if not paras:
            logger.warning("freeze_doctrine_map: %r -> no paragraphs for %r %r",
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
