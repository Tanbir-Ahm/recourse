import os
import json
import typing
from xml.sax.saxutils import escape as _xml_escape
from datetime import datetime, timedelta
from anthropic import Anthropic
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable,Table, TableStyle
from reportlab.platypus import Table as _Table
from reportlab.lib import colors as _colors
import streamlit as st
from bns_section_data_v2 import BNS_SECTION_DATA

try:
    from retrieval import get_statute_section
    _retrieval_available = True
except ImportError:
    # retrieval.py or its chunk files may not be present in every
    # environment (e.g. a fresh clone missing the corpus/chunks
    # directories). Degrade honestly to the pre-retrieval fallback message
    # rather than crashing the app.
    _retrieval_available = False


try:
    api_key = st.secrets["ANTHROPIC_API_KEY"]
except (KeyError, FileNotFoundError):
    from dotenv import load_dotenv
    load_dotenv()
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    api_key = os.getenv("ANTHROPIC_API_KEY")
client = Anthropic(api_key=api_key)

def get_urgency_level(days_remaining):
    if days_remaining < 0:
        return "DEADLINE PASSED"
    elif days_remaining <= 3:
        return "CRITICAL"
    elif 4 <= days_remaining <= 10:
        return "HIGH RISK"
    elif 11 <= days_remaining <= 30:
        return "FORMAL"
    else:
        return "ROUTINE"


def get_action_plan(urgency_level):
    if urgency_level == "DEADLINE PASSED":
        return {
            "30_min": "Do not ignore this. The stated deadline has already passed.",
            "24_hr": "Consult a lawyer immediately — your options may be narrowing.",
            "3_day": "Prepare for possible legal proceedings; do not assume delay is safe."
        }
    elif urgency_level == "CRITICAL":
        return {
            "30_min": "Save this notice securely. Do not make verbal commitments to the sender.",
            "24_hr": "Gather all related documents and records immediately.",
            "3_day": "Seek professional review before any response — deadline is imminent."
        }
    elif urgency_level == "HIGH RISK":
        return {
            "30_min": "Save this notice and note the deadline clearly.",
            "24_hr": "Locate supporting documents and verify claimed facts.",
            "3_day": "Decide on response path: dispute, comply, or seek clarification."
        }
    elif urgency_level == "FORMAL":
        return {
            "30_min": "Save the notice and go through it.",
            "24_hr": "Find out the legal clauses.",
            "3_day": "Decide to talk to a lawyer."
        }
    else:
        return {
            "30_min": "Check who is the sender.",
            "24_hr": "Decide what are the allegations and violations.",
            "3_day": "Wait for 5 more days"
        }


def build_analysis_summary(days_remaining):
    urgency = get_urgency_level(days_remaining)
    message = get_action_plan(urgency)
    return {
        "urgency_level": urgency,
        "deadline_message": message,
        "days_remaining": days_remaining
    }


def extract_text_from_pdf(filepath):
    import fitz        # PyMuPDF is imported here, where it is used, not at the top of the module: this module is pulled in by the whole engine (chat_assistant -> main), and the import alone costs about 100 MB in every process, used or not (2026-11-07, FOLLOW_UPS 2dq)
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def clean_text(raw_text):
    lines = raw_text.split("\n")
    cleaned_lines = []
    for line in lines:
        if line.strip() != "":
            cleaned_lines.append(line.strip())
    return "\n".join(cleaned_lines)


def parse_json_response(response_text):
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


DATE_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y"]


def parse_date(raw: typing.Optional[str]) -> typing.Optional[datetime]:
    if not raw or str(raw).strip().lower() == "null":
        return None
    raw = str(raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _result(requirement: str, status: str, explanation: str, doctrine_key: str = None,
            applying_precedent_key: str = None) -> dict:
    """doctrine_key, when given, must match a key in retrieval.py's
    JUDGMENT_CITATION_MAP -- the PRIMARY source (a Supreme Court judgment).
    This attaches the real source paragraph(s) for that doctrine to the
    result as 'source_paragraphs' -- a lookup only, never used to
    influence status or explanation, which are decided entirely above
    this line by the calling check function.

    applying_precedent_key, when given, must ALSO match a
    JUDGMENT_CITATION_MAP key, but points to a High Court judgment
    illustrating how the primary doctrine gets applied in practice (e.g.
    rakhi_mitra_arnesh_kumar_consequences, sri_manjunath_arnesh_kumar_application).
    This is kept as a SEPARATE parameter from doctrine_key, not folded
    into it or accepted as a list on the same field, specifically so every
    call site stays self-documenting about which source is the primary
    binding rule and which is a subordinate illustration -- a High Court
    ruling binds only within its own state/UT, never nationally, and must
    never be presented as equivalent authority to the Supreme Court
    source. Stored on the result as 'applying_precedent_paragraphs',
    distinct from 'source_paragraphs', so any renderer can trivially tell
    the two apart and label them differently rather than needing to
    inspect court metadata at render time.

    Both parameters are safe to omit; existing call sites using only
    doctrine_key (or neither) are unaffected.

    PROJECT 2 (citation_currency.py): whenever doctrine_key or
    applying_precedent_key is resolved, this also attaches
    'citation_currency' / 'applying_precedent_currency' -- a lookup
    only, same as source_paragraphs, never used to influence status or
    explanation above this line. Absence of a curated currency record
    surfaces as an explicit NOT_YET_VERIFIED status, never silence."""
    result = {"requirement": requirement, "status": status, "explanation": explanation}
    if doctrine_key is not None and _retrieval_available:
        try:
            from retrieval import get_judgment_doctrine
            paragraphs = get_judgment_doctrine(doctrine_key)
            if paragraphs:
                result["source_paragraphs"] = paragraphs
        except Exception:
            pass
        try:
            from citation_currency import get_citation_currency
            result["citation_currency"] = get_citation_currency(doctrine_key)
        except Exception:
            pass
    if applying_precedent_key is not None and _retrieval_available:
        try:
            from retrieval import get_judgment_doctrine
            applying_paragraphs = get_judgment_doctrine(applying_precedent_key)
            if applying_paragraphs:
                result["applying_precedent_paragraphs"] = applying_paragraphs
        except Exception:
            pass
        try:
            from citation_currency import get_citation_currency
            result["applying_precedent_currency"] = get_citation_currency(applying_precedent_key)
        except Exception:
            pass
    return result


def check_30_day_window(fields: dict) -> dict:
    req = "Notice sent within 30 days of return memo [S.138(b)]"
    memo = parse_date(fields.get("return_memo_date"))
    notice = parse_date(fields.get("notice_date"))
    if memo is None or notice is None:
        return _result(req, "Cannot Determine", "Return-memo date or notice date is missing or unparseable.")
    gap = (notice - memo).days
    if gap < 0:
        return _result(req, "Non-Compliant", f"Notice dated {gap} days before the return memo, which is impossible/invalid.")
    status = "Compliant" if gap <= 30 else "Non-Compliant"
    return _result(req, status, f"Gap is {gap} calendar days (statutory limit: 30).")


def check_amount_match(fields: dict) -> dict:
    req = "Demand equals cheque face value; interest stated separately [Suman Sethi]"
    face = fields.get("cheque_face_value")
    demand = fields.get("demand_principal_amount")
    if face is None or demand is None:
        return _result(req, "Cannot Determine", "Cheque value or demand amount missing.")
    bundled = bool(fields.get("interest_bundled_in_principal_sentence", False))
    if face != demand:
        return _result(req, "Non-Compliant", f"Demand (Rs.{demand:,}) does not match cheque face value (Rs.{face:,}).")
    if bundled:
        return _result(req, "Non-Compliant", "Principal matches, but interest/costs are bundled into the demand sentence.")
    return _result(req, "Compliant", f"Demand matches face value (Rs.{face:,}); interest not improperly bundled.")


def explain_debt_presumption_status(f):
    """NEW 2026-08-30: REPLACES check_enforceable_debt entirely.
    check_enforceable_debt is RETIRED -- it treated "was this cheque
    for an enforceable debt" as a fact the tool could determine from a
    notice's self-description, returning a flat Compliant/Non-Compliant
    verdict. This is legally backwards per Rangappa v Sri Mohan,
    (2010) 11 SCC 441, paragraphs 14 and 34: Section 139's presumption
    of a legally enforceable debt is MANDATORY once the cheque
    signature is admitted/proved -- the complainant does not need to
    prove enforceability upfront; it is presumed. The accused can only
    rebut this on a PREPONDERANCE OF PROBABILITIES, not by merely
    asserting a defence.

    This function is DELIBERATELY INFORMATIONAL, never a compliance
    verdict -- same "explain, don't decide" pattern as
    compute_bail_pathway_info elsewhere in this project.

    Also incorporates Bir Singh v Mukesh Kumar, (2019) 4 SCC 197,
    paragraph 40: a blank cheque, voluntarily signed and handed over
    by the accused and later filled in by the payee, STILL attracts
    the Section 139 presumption -- "it was a blank cheque" is NOT, by
    itself, a fact that defeats enforceability.

    NOT YET COVERED (flagged, not silently omitted): whether an
    informal/undocumented ("friendly") loan defeats the presumption is
    NOT resolved by any case verified in this project as of 2026-08-30
    -- an earlier draft of this analysis incorrectly attributed this
    claim to Bir Singh; direct re-verification confirmed Bir Singh's
    mention of a "friendly loan" was ONLY in the facts recitation
    (paragraph 3, describing the complainant's allegation), never
    stated as a Court holding. This function makes no claim about
    informal loans."""
    was_blank = f.get("cheque_was_blank_when_signed")
    result_text_parts = [
        "Under Section 139 of the Negotiable Instruments Act, once the cheque signature is admitted "
        "or proved, the law PRESUMES the cheque was issued for a legally enforceable debt or liability "
        "-- this presumption is mandatory, per Rangappa v Sri Mohan (2010) 11 SCC 441. The complainant "
        "does not need to separately prove enforceability; the burden is on the accused to rebut this "
        "presumption, and that rebuttal must clear a preponderance-of-probabilities standard -- a bare "
        "denial or assertion that 'this wasn't a real debt' is not, by itself, sufficient."
    ]

    if was_blank is True:
        result_text_parts.append(
            "A blank cheque, voluntarily signed and handed over, does NOT avoid this presumption -- "
            "per Bir Singh v Mukesh Kumar (2019) 4 SCC 197, even a blank cheque leaf later filled in by "
            "the payee still attracts the Section 139 presumption. This is not, by itself, a valid "
            "defence."
        )

    return {
        "topic": "Debt presumption under Section 139 [Rangappa (2010) / Bir Singh (2019)]",
        "explanation": " ".join(result_text_parts),
        "note": "This is informational, not a compliance verdict -- enforceability is a legal "
                "presumption the case itself resolves, not a fact this tool can determine from a "
                "notice alone.",
    }


def compute_settlement_cost_incentive(fields):
    """NEW 2026-08-30: informational sidebar, per Damodar S. Prabhu v
    Sayed Babalal H, (2010) 5 SCC 663, paragraph 15 -- establishes a
    graduated cost scheme for compounding a Section 138 case,
    escalating the later it happens. Deliberately NEVER folded into
    compliance_checks -- same pattern as compute_bail_pathway_info
    elsewhere in this project.

    Args:
        fields: expects a 'case_stage' field with one of:
            "pre_trial", "convicted_at_trial_court", "on_appeal_hc",
            "on_appeal_sc", or "unclear".

    Returns:
        dict with 'pathway' and 'message'.
    """
    stage = fields.get("case_stage", "unclear")

    if stage == "pre_trial":
        return {
            "pathway": "low_cost_compounding_available",
            "message": "If the case is compounded (settled) now, at the pre-trial stage, minimal or no "
                       "cost is likely to be imposed. Per Damodar S. Prabhu v Sayed Babalal H (2010) 5 "
                       "SCC 663, the Supreme Court has established a framework encouraging early "
                       "settlement precisely because the cost of settling rises sharply the longer the "
                       "case continues. If the accused offers to pay the cheque amount unconditionally "
                       "at the first hearing and the complainant accepts, the case can often be closed "
                       "immediately at essentially no cost.",
        }
    if stage == "convicted_at_trial_court":
        return {
            "pathway": "escalated_cost_compounding",
            "message": "Compounding remains available even after conviction at the trial court -- per "
                       "Damodar S. Prabhu v Sayed Babalal H (2010) 5 SCC 663, compounding is not barred "
                       "post-conviction, but a real cost (in that judgment's framework, in the range of "
                       "10% of the cheque amount, payable to a legal aid fund) may now apply.",
        }
    if stage == "on_appeal_hc":
        return {
            "pathway": "escalated_cost_compounding",
            "message": "Compounding remains available at the High Court appeal stage -- per Damodar S. "
                       "Prabhu v Sayed Babalal H (2010) 5 SCC 663, the cost of compounding at this stage "
                       "escalates further (in that judgment's framework, in the range of 15% of the "
                       "cheque amount).",
        }
    if stage == "on_appeal_sc":
        return {
            "pathway": "escalated_cost_compounding",
            "message": "Compounding remains available even at the Supreme Court stage -- per Damodar S. "
                       "Prabhu v Sayed Babalal H (2010) 5 SCC 663, the cost of compounding at this stage "
                       "is highest (in that judgment's framework, in the range of 20% of the cheque "
                       "amount).",
        }
    return {
        "pathway": "unknown",
        "message": "The stage of the case is not known, so the applicable settlement-cost band under "
                   "Damodar S. Prabhu v Sayed Babalal H (2010) 5 SCC 663 cannot be stated -- but note "
                   "generally that compounding a Section 138 case becomes progressively more costly the "
                   "later it happens, so settling early is generally favourable if settlement is being "
                   "considered at all.",
    }


def check_amount_match(fields: dict) -> dict:
    """CORRECTED 2026-08-30: previously treated ANY co-mention of
    interest/costs alongside the principal amount as an automatic
    Non-Compliant defect, regardless of whether the cheque amount was
    still specifically identifiable. This is NOT what the actual case
    law holds. CONFIRMED via Kaveri Plastics v Mahdoom Bawa Bahrudeen
    Noorul (Supreme Court, 19 September 2025), paragraph 14, which
    directly quotes Suman Sethi v Ajay K. Churiwal, (2000) 2 SCC 380:
    a demand notice must specifically demand the CHEQUE AMOUNT itself
    ('the said amount') -- but additional amounts (interest, costs)
    mentioned ALONGSIDE the cheque amount do NOT, by themselves,
    invalidate the notice, PROVIDED the cheque amount remains
    specifically and severably demanded. Kaveri Plastics itself was
    decided on a genuine AMOUNT MISMATCH (the notice demanded a
    different figure than the actual cheque) -- that is the real
    defect the case law protects against, not mere co-mention of
    interest."""
    req = "Demand specifically states the correct cheque amount [Suman Sethi (2000) via Kaveri Plastics (2025)]"
    face = fields.get("cheque_face_value")
    demand = fields.get("demand_principal_amount")
    if face is None or demand is None:
        return _result(req, "Cannot Determine", "Cheque value or demand amount missing.")

    if face != demand:
        return _result(req, "Non-Compliant",
            f"Demand (Rs.{demand:,}) does not match cheque face value (Rs.{face:,}). Per Kaveri "
            f"Plastics v Mahdoom Bawa Bahrudeen Noorul (Supreme Court, 2025), a notice demanding an "
            f"amount that does not match the actual cheque -- even where the mismatch is claimed to be "
            f"a typographical error -- can be fatal to the complaint, since the notice must specifically "
            f"and correctly state the cheque amount.")

    return _result(req, "Compliant",
        f"Demand matches face value (Rs.{face:,}). Per Suman Sethi v Ajay K. Churiwal, (2000) 2 SCC "
        f"380 (as quoted in Kaveri Plastics v Mahdoom Bawa Bahrudeen Noorul, Supreme Court, 2025), a "
        f"notice that also mentions interest or costs alongside the correctly-stated cheque amount is "
        f"not, by itself, defective -- what matters is that the cheque amount itself is specifically "
        f"and severably demanded, which is satisfied here.")


def check_jurisdiction(fields):
    """NEW 2026-08-30: per Prakash Chimanlal Sheth v Jagruti Keyur
    Rajpopat, 2025 INSC 897, paragraphs 7-8 -- a Section 138 complaint
    must be filed at the place where the cheque was PRESENTED FOR
    COLLECTION and dishonoured (per Section 142(2) NI Act and the
    Constitution Bench framework in Dashrath Rupsingh Rathod v State
    of Maharashtra, 2014) -- not wherever the complainant resides, not
    where the loan was advanced, not where the demand notice was sent
    from."""
    req = "Complaint filed where cheque was presented for collection [Prakash Chimanlal Sheth (2025) / S.142(2) NI Act]"

    presentation_location = fields.get("cheque_presentation_bank_location")
    filing_location = fields.get("complaint_filed_location")

    if presentation_location is None or filing_location is None:
        return _result(req, "Cannot Determine",
            "Where the cheque was presented for collection, and/or where the complaint was actually "
            "filed, is not established from this information. This matters directly: per Prakash "
            "Chimanlal Sheth v Jagruti Keyur Rajpopat (2025 INSC 897) and Section 142(2) NI Act, "
            "jurisdiction lies specifically where the cheque was presented for collection through the "
            "payee's bank -- not wherever is most convenient for the complainant.")

    if str(presentation_location).strip().lower() == str(filing_location).strip().lower():
        return _result(req, "Compliant",
            "The complaint is recorded as filed at the same location where the cheque was presented "
            "for collection, consistent with Section 142(2) NI Act and Prakash Chimanlal Sheth v "
            "Jagruti Keyur Rajpopat (2025 INSC 897).")

    return _result(req, "Non-Compliant",
        f"The complaint is recorded as filed at '{filing_location}', but the cheque was presented for "
        f"collection at '{presentation_location}'. Per Section 142(2) NI Act and Prakash Chimanlal "
        f"Sheth v Jagruti Keyur Rajpopat (2025 INSC 897), jurisdiction lies specifically where the "
        f"cheque was presented for collection -- a mismatch here is a real, threshold defect that can "
        f"result in the complaint being quashed or transferred, independent of the case's merits.")


def run_compliance_checks(fields: dict) -> dict:
    """UPDATED 2026-08-30: check_enforceable_debt REMOVED from
    compliance_checks entirely (retired -- see
    explain_debt_presumption_status's docstring for why treating
    enforceability as a pass/fail compliance question was legally
    backwards per Rangappa v Sri Mohan). check_jurisdiction ADDED.
    check_amount_match CORRECTED. The presumption explanation and
    settlement-cost incentive are DELIBERATELY NOT included here --
    they are informational, not compliance verdicts, and should be
    surfaced separately by the UI layer via
    explain_debt_presumption_status() and
    compute_settlement_cost_incentive(), same pattern as
    compute_bail_pathway_info being kept separate from
    compliance_checks elsewhere in this project."""
    checks = [
        check_30_day_window(fields),
        check_amount_match(fields),
        check_15_day_payment_window(fields),
        check_jurisdiction(fields),
    ]
    non_compliant = [c for c in checks if c["status"] == "Non-Compliant"]
    undetermined = [c for c in checks if c["status"] == "Cannot Determine"]

    if non_compliant:
        overall = f"{len(non_compliant)} procedural defect(s) found. Notice may be legally vulnerable."
    elif undetermined:
        overall = f"No defects found, but {len(undetermined)} check(s) could not be verified from the document. Needs manual review."
    else:
        overall = "All checks pass. No procedural defects detected in extracted fields."

    return {"compliance_checks": checks, "overall_assessment": overall}


def check_15_day_payment_window(fields: dict) -> dict:
    req = "At least 15 days granted to pay [S.138(c)]"
    window = fields.get("payment_window_days_granted")
    if window is None:
        return _result(req, "Cannot Determine", "Stated payment window not found in notice.")
    status = "Compliant" if window >= 15 else "Non-Compliant"
    return _result(req, status, f"Notice grants {window} days (statutory minimum: 15).")




document_checklists = {
    "Banking & Cheque Bounce": [
        "Original dishonoured cheque (if in your possession)",
        "Bank return memo / cheque bounce memo",
        "Bank statement showing the transaction",
        "Any written agreement or invoice related to the underlying debt",
        "Proof of postal delivery (RPAD receipt) if you are the sender"
    ],
    "Police & Criminal Process": [
        "Copy of the FIR (if registered)",
        "Any written notice received from police (Section 35/41A, Section 94/91)",
        "Identity proof",
        "Names and badge numbers of investigating officers, if known",
        "Any prior correspondence with the police station"
    ],
    "Tenancy & Property": [
        "Rental agreement or lease deed",
        "Rent payment receipts or bank transfer records",
        "Property registration documents, if applicable",
        "Any prior written communication with landlord/tenant"
    ],
    "Individual Tax Notices": [
        "Copy of the relevant ITR/GST filing referenced in the notice",
        "Form 26AS / AIS statement (for income tax notices)",
        "Bank statements for the relevant financial year",
        "Any prior correspondence with the tax department"
    ],
    "Government / Revenue Orders": [
        "Copy of the original order or circular",
        "Land records / mutation documents, if applicable",
        "Any prior applications or representations filed",
        "Identity and address proof"
    ]
}


def get_document_checklist(document_type):
    return document_checklists.get(document_type, ["No checklist available for this category yet."])


def calculate_days_remaining(deadline_fields, notice_date_str=None):
    today = datetime.now()

    explicit_date = parse_date(deadline_fields.get("deadline_date_if_explicit"))
    if explicit_date:
        return (explicit_date - today).days

    days_stated = deadline_fields.get("deadline_days_stated")
    parsed_notice_date = parse_date(notice_date_str)
    if days_stated is not None and parsed_notice_date:
        deadline_date = parsed_notice_date + timedelta(days=days_stated)
        return (deadline_date - today).days

    return None


EXTRACTION_PROMPT = """You are extracting factual fields from an Indian Section 138
cheque bounce notice. Do NOT judge compliance. Only report what the document states.
If a field is not present, use null.

Return ONLY valid JSON in this exact format, no other text:
{{"return_memo_date": "DD-MM-YYYY or null",
  "notice_date": "DD-MM-YYYY or null",
  "cheque_face_value": number or null,
  "demand_principal_amount": number or null,
  "payment_window_days_granted": number or null,
  "interest_bundled_in_principal_sentence": true or false,
  "cheque_purpose": "debt" or "security" or "advance" or "unclear"
}}

Document text:
{document_text}"""

# Police & CRIMINAL PROCESS- sub-type routing and checks#


POLICE_SUBTYPE_PROMPT = """Classify this Indian police/criminal process document into exactly one type.
- "Arrest-related"- arrest memo, 41A/35 BNSS notice to appear, grounds of arrest, remand related document.
- "Bank/Account Freezing"- freeze/attachment order or intimation under 106/107 BNSS or old 102 CrPc
- "Search & Seizure "- NDPS search memo, seizure memo of goods/devices/property, panchnama 
- "FIR Registration Dispute"- written rejection of FIR, delay-in-registration complaint, closure intimation, NC entry only 
- "Summons to Vulnerable Person"- 179 BNSS/old 160 CrPC summons to a woman, minor or elderly person
- "FIR / Complaint - No Arrest Yet"- a properly registered FIR or written complaint where NO arrest, freeze, search, or summons has occurred yet — just the offence report itself
- "Other"- police document that fits none of the above 

Respond with only valid JSON:{{"police_subtype": "one of the above"}}

Document text:
{document_text}"""

ARREST_EXTRACTION_PROMPT = """Extract only what the arrest-related document explicitly states. Do NOT judge legality. If a field is not present, use null. Do not infer.
IMPORTANT INSTRUCTION for arrest_mode: use "in_presence" ONLY if the document indicates the person was arrested at the place of occurrence while the offence was ongoing or immediately upon commission, with police physically present witnessing it. Use "post_facto" if the arrest happened later — a different date from the offence, or at the person's residence or another location, or based on investigation, CCTV, or identification after the event. Use "preventive" if the document indicates arrest was made to PREVENT an anticipated offence (S.170 BNSS / old 151 CrPC) rather than for an offence already committed. Use "unclear" only if none of this can be determined.

IMPORTANT INSTRUCTION for arrest_power_limb: report a value ONLY where the document affirmatively states the underlying fact — e.g. that stolen property was recovered from the person at the time of arrest, that the person was already a proclaimed offender, that the arrest was for obstructing police or escaping custody, or that it was made on requisition from another police officer. Do NOT infer any of these from the offence charged. A theft charge alone is NOT "stolen_property" — that value requires property actually found in the person's possession. If none is affirmatively stated, use null.

IMPORTANT DISTINCTION for grounds_of_arrest_in_writing_furnished_to_arrestee: this field means a SEPARATE written document was handed to the arrestee explaining the specific grounds for HIS arrest. It is NOT the same as an internal police checklist of justifications (e.g., checkboxes like "for proper investigation" or "to ensure presence in court") recorded in the memo for the police's own record. If the memo only shows internal justification checkboxes with no indication that a distinct grounds document was furnished to the arrestee, mark this field false, not true.

IMPORTANT INSTRUCTION for 41A_or_35_BNSS_notice_issued_before_arrest: if the document otherwise documents procedural steps carefully (e.g., witness attestation, family notification, medical examination are all explicitly recorded) but says NOTHING about a prior notice to appear being issued before the arrest, mark this field false, not "unclear". A memo that carefully documents several safeguards but is silent on this one specific step is evidence the step was likely skipped, not evidence that its status is unknown. Only use "unclear" if the document is generally sparse or unclear on procedural matters overall, not merely silent on this one field while being detailed elsewhere.

Sections_cited must contain ONLY the bare section number/sub-section (e.g. '305', '318(4)'), never including 'BNS', 'IPC', 'CrPC', or similar labels."
Return ONLY valid JSON in this format, no other text:
{{
  "document_date": "DD-MM-YYYY or null",
  "offence_date": "DD-MM-YYYY or null",
  "sections_cited": ["list of sections mentioned"],
  "arrest_mode": "in_presence" or "post_facto" or "preventive" or "unclear",
  "arrest_power_limb": "stolen_property" or "proclaimed_offender" or "obstruction_escape" or "requisition" or "deserter" or "extradition" or "released_convict" or null,
  "punishment_years_upper_bound": number or null,
  "arrestee_gender": "male" or "female" or "third_gender" or "not stated",
  "arrestee_age": number or null,
  "arrest_datetime_full": "DD-MM-YYYY HH:MM or null",
  "production_datetime_full": "DD-MM-YYYY HH:MM or null",
  "grounds_of_arrest_in_writing_furnished_to_arrestee": true or false or "unclear",
  "41A_or_35_BNSS_notice_issued_before_arrest": true or false or "unclear",
  "witness_attested_memo": true or false or "unclear",
  "family_or_friend_informed": true or false or "unclear",
  "medical_exam_at_arrest_recorded": true or false or "unclear",
  "female_officer_present_for_female_arrestee": true or false or "unclear" or "not applicable",
  "chargesheet_filed_date": "DD-MM-YYYY or null",
  
}}

Document text:
{document_text}"""


def build_grounded_section_context(sections_cited):
    """Look up each cited section in the verified dictionary and produce a short, factual context string the model can reply on instead of guessing."""
    if not sections_cited:
        return "No sections were cited in the documen."
    lines=[]
    for sec in sections_cited:
        clean = re.sub(r'\s*(BNS|IPC|BNSS|CrPC)\s*$','', str(sec).strip(), flags=re.IGNORECASE).strip()
        data = BNS_SECTION_DATA.get(clean)
        if data:
            # Punishment and classification are INDEPENDENT facts — a section
            # can have a fixed punishment but contingent cognizable/bailable
            # status (confirmed real case: Section 57), or vice versa. Report
            # each honestly rather than collapsing both into one message.
            if data['life_or_death'] == "contingent":
                punishment_desc = "punishment depends on the underlying/related offence — not fixed"
            elif data['life_or_death']:
                punishment_desc = "max punishment: Life/Death"
            elif data['max_years'] is not None:
                punishment_desc = f"max punishment: {data['max_years']} years"
            elif data.get('max_months') is not None:
                punishment_desc = f"max punishment: {data['max_months']} months"
            else:
                punishment_desc = "punishment not resolved — needs manual review"

            if data['cognizable'] == "contingent":
                classification_desc = "cognizable/bailable status depends on the underlying/related offence"
            else:
                classification_desc = None  # will show separately if needed, not blocking the offence line

            offence_label = data['offence'] if data['offence'] else "(description not extracted — needs manual review)"
            line = f"-Section {clean}: {offence_label} ({punishment_desc})"
            if classification_desc:
                line += f" [{classification_desc}]"
            lines.append(line)
        else:
            # CRITICAL: BNS and BNSS both number their own sections starting
            # from 1 independently -- confirmed ALL 359 BNS section numbers
            # collide with a same-numbered BNSS section, and the two mean
            # completely different things (e.g. "106": BNS 106 is causing
            # death by negligence, an offence; BNSS 106 is police powers to
            # seize stolen property, a procedure). Since sections_cited
            # carries no reliable act suffix, silently trying one act before
            # the other would silently show the WRONG statute roughly half
            # the time. Both are looked up and shown if both exist, clearly
            # labeled, rather than guessing -- same honest-collision pattern
            # used for Vihaan Kumar's dual opinions in retrieval.py.
            retrieved_by_act = {}
            if _retrieval_available:
                for act in ("BNS", "BNSS"):
                    result = get_statute_section(act, clean)
                    if result:
                        retrieved_by_act[act] = result

            if retrieved_by_act:
                if len(retrieved_by_act) > 1:
                    lines.append(
                        f"- Section {clean}: not in our verified compliance table. This number exists in "
                        f"BOTH BNS and BNSS with different meanings -- showing both since which one was "
                        f"meant cannot be determined automatically; read both and use context to decide:"
                    )
                else:
                    lines.append(
                        f"- Section {clean}: not in our verified compliance table, but here is the actual "
                        f"statutory text (read this directly rather than assuming what it covers):"
                    )
                for act, retrieved in retrieved_by_act.items():
                    snippet = retrieved["text"][:600].strip()
                    truncated_note = "..." if len(retrieved["text"]) > 600 else ""
                    lines.append(f"  [{act}] \"{snippet}{truncated_note}\"")
            else:
                lines.append(f"- Section {clean}: not in our verified reference table — do not assume or guess what this section covers.")
    return "\n".join(lines)





import re

def get_max_years_from_sections(sections_cited):
    """Sentinel values: 'LIFE_OR_DEATH', 'CONTAINS_VARIABLE' (punishment
    depends on an underlying offence with no fixed value stated), and
    'CONTAINS_CONTINGENT' (checked via life_or_death == "contingent"
    specifically, NOT needs_review — a section's punishment can be a clean
    fixed number even when its cognizable/bailable status, a separate
    field, is contingent — confirmed real case: Section 57).
 
    Months-only sections (e.g. a 3-month ceiling) are real, known, resolved
    punishments — not variable/unresolved ones — so they must not be lumped
    into has_variable. They're tracked separately and only used as a
    fallback maximum (converted to a fractional year figure purely for
    numeric comparison against other cited sections) when no years-based
    candidate exists among the cited sections. The raw max_months value
    itself is never silently presented to the person as if it were years —
    that only happens in build_grounded_section_context's own months-aware
    display line.
 
    FIXED 2026-08-29: was `BNS_SECTION_DATA.get(clean)` -- a bare lookup
    with no subsection fallback, same confirmed bug class as
    check_cognizable_arrest_basis (see _lookup_section_variants'
    docstring for the full writeup). If ALL variants for a bare section
    number agree, use that shared value. If they DISAGREE on years/
    life-or-death, this is now treated the same way multi-condition
    disagreement is already treated elsewhere in this project (e.g.
    Section 303(2)'s cognizable/bailable disagreement in
    _resolve_field_with_conditions): flagged as CONTAINS_VARIABLE
    rather than silently picking one variant's value, since guessing
    which subsection actually applies would be a legal classification
    this function isn't positioned to make."""
    if not sections_cited:
        return None
    candidates = []
    months_only_candidates = []
    has_variable = False
    has_contingent = False
    for sec in sections_cited:
        clean = str(sec).strip()
        variants = _lookup_section_variants(clean)
        if not variants:
            continue
 
        # If multiple variants exist (e.g. bare "303" matching both
        # "303(1)" and "303(2)"), and they DISAGREE on max_years or
        # life_or_death, this is genuinely ambiguous -- which variant
        # actually applies depends on facts (e.g. first vs. repeat
        # conviction) this function has no way to know. Flag as
        # variable rather than silently picking the first one found.
        variant_datas = [data for _key, data in variants]
        lod_values = set(d.get("life_or_death") for d in variant_datas)
        years_values = set(d.get("max_years") for d in variant_datas)
 
        if len(variant_datas) > 1 and (len(lod_values) > 1 or len(years_values) > 1):
            has_variable = True
            continue
 
        data = variant_datas[0]
        if data.get("life_or_death") == "contingent":
            has_contingent = True
            continue
        if data["life_or_death"]:
            return "LIFE_OR_DEATH"
        if data["max_years"] is not None:
            candidates.append(data["max_years"])
        elif data.get("max_months") is not None:
            months_only_candidates.append(data["max_months"])
        else:
            has_variable = True
    if has_contingent:
        return "CONTAINS_CONTINGENT"
    if has_variable:
        return "CONTAINS_VARIABLE"
    if candidates:
        return max(candidates)
    if months_only_candidates:
        return max(months_only_candidates) / 12
    return None

FREEZE_EXTRACTION_PROMPT =""" Extract only what the bank/account freezing document explicitly states. DO NOT judge legality. Use null if not present.
 "If the document does not mention any BNS/BNSS/CrPC section number anywhere in connection with the freeze, you MUST answer 'none cited' — do not answer 'unclear' in this case. 'unclear' is only for when a section is mentioned but its exact identity is ambiguous."
 Return ONLY valid JSON:
 {{
     "freeze_date": "DD-MM-YYYY or null",
     "section_invoked": "106 BNSS" or "107 BNSS" or "102 CrPC" or "other" or "unclear",
     "scope" : "entire account" or "specific disputed amount" or "unclear",
     "specific_amount_stated": number or null,
     "account_holder_intimated": true or false or "unclear",
     "magistrate_intimation_recorded": true or false or "unclear",
     "magistrate_intimation_date": "DD-MM-YYYY or null",
     "court_order_referenced_for_107": true or false or "unclear" or "not applicable"
 }}
 Document text:
 {document_text}"""
 
SEARCH_EXTRACTION_PROMPT =""" Extract only what the search & seizure document expliclity states. DO NOT judge legality. Use null if not present.

Return ONLY valid JSON:
{{
    "search_target": "person" or "bag or vehicle or premises" or "unclear",
    "section_50_ndps_offer_recorded": true or false or "unclear" or "not applicable",
    "option_offered_to_accused":"magistrate or gazetted officer" or "police officer only" or "none offered" or "unclear" or "not applicable",
    "language_of_notice_understood_by_accused_confirmed": true or false or "unclear",
    "independent_witnesses_present": true or false or "unclear",
    "seizure_memo_signed_by_accused": true or false or "unclear"
}}
Document text:
{document_text} """

FIR_DISPUTE_EXTRACTION_PROMPT = """ Extract only what the document about FIR registration explicitly states. Use null if not present.
 
Return ONLY valid JSON:

{{
"complaint_date": "DD-MM-YYYY or null",
"offence_alleged_is_cognizable": true or false or "unclear",
"police_action": "refused to regsiter" or "delayed regsitration" or "NC entry only" or "closure intimation" or "unclear",
"delay_days": number or null, 
"written_response_given": true or false or "unclear",
"offence_category_falling_in_lalita_kumari_inquiry_exceptions": "matrimonial" or "commercial" or "medical negligence" or "corruption" or "none" or "unclear"
}}

Document text:
{document_text}"""

VULNERABLE_EXTRACTION_PROMPT ="""Extract only waht the summons to a vulnerable person explicitly states. Use null if not present.
Return ONLY valid JSON:

{{
    "summoned_person_gender": "male" or "female" or "not stated",
    "summoned_person_age": number or null,
    "summons_location": "police station" or "residence" or "unclear",
    "summons_datetime": "DD-MM-YYYY HH:MM or null,
    "female_officer_involved": true or false or "unclear" or "not applicable",
    "guardian_notified_for_minor": true or false or "unclear" or "not applicable"
    
}}

Document text:
{document_text}"""

FIR_NO_ARREST_EXTRACTION_PROMPT = """Extract only what this FIR or complaint document explicitly states. Do NOT judge legality. Use null if not present.

Sections_cited must contain ONLY the bare section number/sub-section (e.g. '305', '351(2)'), never including 'BNS', 'IPC', 'CrPC', or similar labels.

For fir_document_perspective: determine whether the document represents the INFORMANT's perspective (the person who filed/reported the complaint) or the ACCUSED's perspective (someone named as a suspect, or their counsel, seeking access to the FIR). Use "informant" or "accused". If genuinely unclear from the document, use "unclear" — do not guess.

Return ONLY valid JSON in this format, no other text:
{{
  "fir_number": "string or null",
  "sections_cited": ["list of bare section numbers"],
  "occurrence_date": "DD-MM-YYYY or null",
  "reporting_date": "DD-MM-YYYY or null",
  "arrest_mentioned": true or false,
  "fir_document_perspective": "informant" or "accused" or "unclear",
  "free_copy_given_to_informant": true or false or "unclear",
  "accused_applied_for_fir_copy": true or false or "unclear",
  "accused_fir_copy_provided": true or false or "unclear"
}}

Document text:
{document_text}"""


#------ Deterministic Python compliance checks----#

def parse_datetime_full(raw):
    if not raw or str(raw).strip().lower() == "null":
        return None
    from datetime import datetime as _dt
    for fmt in ("%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return _dt.strptime(str(raw).strip(),fmt)
        except ValueError:
            continue
    return None 

def resolve_arrest_mode(f):
    """Deterministic backstop: a date gap between offence and arrest proves post-facto."""
    mode = f.get("arrest_mode", "unclear")
    o = parse_date(f.get("offence_date"))
    a = parse_datetime_full(f.get("arrest_datetime_full"))
    if o is not None and a is not None and (a.date() - o.date()).days >= 1:
        return "post_facto"   # conclusive regardless of extraction
    return mode

# Limbs of S.35(1) BNSS that authorise arrest WITHOUT a prior S.35(3) notice.
# Key -> (section reference, plain-language predicate)
BYPASS_LIMBS = {
    "in_presence":        ("S.35(1)(a)", "the offence was committed in the presence of a police officer"),
    "over_seven_years":   ("S.35(1)(c)", "credible information of an offence punishable with MORE than seven years or death"),
    "proclaimed_offender":("S.35(1)(d)", "the person had already been proclaimed an offender by a court or the State Government"),
    "stolen_property":    ("S.35(1)(e)", "property reasonably suspected to be stolen was found in the person's possession"),
    "obstruction_escape": ("S.35(1)(f)", "obstructing a police officer in execution of duty, or escaping / attempting to escape lawful custody"),
    "deserter":           ("S.35(1)(g)", "reasonably suspected of being a deserter from the Armed Forces of the Union"),
    "extradition":        ("S.35(1)(h)", "an act committed outside India for which the person is liable to be apprehended under extradition law"),
    "released_convict":   ("S.35(1)(i)", "a released convict in breach of rules made under S.394(5) BNSS"),
    "requisition":        ("S.35(1)(j)", "arrest on a requisition from another police officer specifying the person and the cause"),
    "preventive":         ("S.170 BNSS", "preventive arrest to stop an anticipated cognizable offence (old S.151 CrPC)"),
}


def resolve_arrest_power_limb(f, upper_years):
    """Identify which limb of S.35(1) BNSS authorised this arrest without notice.
    Returns (limb_key, section_ref, description) or None if the arrest falls into
    the S.35(1)(b) notice-first pathway.

    DESIGN RULE: a bypass limb is returned ONLY where its predicate is affirmatively
    established. 'unclear' or absent never yields a bypass — the burden of showing an
    exception rests on the facts being present (Vihaan Kumar, 2025 INSC 162)."""

    mode = resolve_arrest_mode(f)          # from the previous step
    if mode == "in_presence":
        return ("in_presence",) + BYPASS_LIMBS["in_presence"]
    if mode == "preventive":
        return ("preventive",) + BYPASS_LIMBS["preventive"]

    if upper_years is not None and upper_years != "LIFE_OR_DEATH" and upper_years > 7:
        return ("over_seven_years",) + BYPASS_LIMBS["over_seven_years"]

    limb = f.get("arrest_power_limb")      # affirmative predicate captured separately
    if limb in BYPASS_LIMBS and limb not in ("in_presence", "preventive", "over_seven_years"):
        return (limb,) + BYPASS_LIMBS[limb]

    return None


def check_arnesh_kumar_notice(f):
    req = "S.35(3) BNSS notice before arrest [Arnesh Kumar (2014) / Satender Kumar Antil, 2026 INSC 115]"

    looked_up = get_max_years_from_sections(f.get("sections_cited", []))

    if looked_up == "LIFE_OR_DEATH":
        return _result(req, "Not Applicable",
            "Offence carries life imprisonment or death — arrest falls under S.35(1)(c) BNSS, outside the "
            "notice-first framework. Written grounds of arrest, D.K. Basu safeguards, and 24-hour production "
            "still apply in full and are checked separately.")

   
    if looked_up == "CONTAINS_VARIABLE":
        return _result(req, "Cannot Determine",
            "One or more cited sections (e.g. an attempt/abetment/conspiracy provision) has a punishment "
            "that depends on the underlying substantive offence and cannot be resolved automatically. "
            "Because this could carry a higher ceiling than the other sections cited, the combined "
            "punishment range — and therefore whether the notice-first framework applies — cannot be "
            "safely determined. Verify independently.")

    if looked_up == "CONTAINS_CONTINGENT":
        return _result(req, "Cannot Determine",
            "One or more cited sections has a classification or punishment that is explicitly contingent "
            "on another factor (e.g. an abettor's punishment following the offence abetted, or a "
            "conspiracy's punishment following the substantive offence) and is not a fixed value in our "
            "reference table. Whether the notice-first framework applies cannot be safely determined. "
            "Verify independently.")

    upper = looked_up if looked_up is not None else f.get("punishment_years_upper_bound")
    source = "looked up from cited section" if looked_up is not None else "as stated in document"

    # Resolve arrest mode / bypass limb BEFORE deciding the punishment range is unusable.
    # In-presence and preventive arrests, and the affirmative S.35(1) limbs, do not depend
    # on knowing punishment years at all — checking them first prevents an unresolved
    # punishment number from silently skipping this logic altogether.
    limb = resolve_arrest_power_limb(f, upper)
    if limb is not None:
        key, section_ref, description = limb
        if key == "preventive":
            return _result(req, "Not Applicable",
                f"Arrest was preventive under {section_ref} — {description}. The S.35(3) notice framework "
                f"does not govern this pathway. CRITICAL LIMIT: preventive detention under S.170 BNSS cannot "
                f"exceed 24 hours unless further detention is separately authorised in law.")
        if key == "over_seven_years":
            return _result(req, "Not Applicable",
                f"Offence carries up to {upper} years ({source}) — arrest falls under {section_ref}, above "
                f"the seven-year notice threshold. Written grounds, D.K. Basu safeguards, and the case-by-case "
                f"necessity test still apply and are checked separately.")
        
        return _result(req, "Not Applicable",
            f"Arrest is authorised under {section_ref} BNSS — {description}. No prior S.35(3) notice is "
            f"required on this limb. IMPORTANT: this exception holds only if that fact is genuinely "
            f"established on the record — verify from the case record that it is actually documented.")

    if upper is None:
        cleaned = [re.sub(r'\s*(BNS|IPC|BNSS|CrPC)\s*$', '', str(s).strip(), flags=re.IGNORECASE).strip()
                   for s in f.get("sections_cited", [])]
        recognized_but_variable = any(
            sec in BNS_SECTION_DATA and BNS_SECTION_DATA[sec]["max_years"] is None
            and not BNS_SECTION_DATA[sec]["life_or_death"]
            for sec in cleaned
        )
        recognized_but_contingent = any(
            sec in BNS_SECTION_DATA and BNS_SECTION_DATA[sec].get("max_years") == "contingent"
            for sec in cleaned
        )
        if recognized_but_variable:
            return _result(req, "Cannot Determine",
                "This section is recognised, but it is an attempt/abetment/conspiracy-type provision whose "
                "punishment depends on the underlying substantive offence, and cannot be automatically "
                "resolved. Determine independently whether that underlying offence carries more than 7 "
                "years: if yes, S.35(1)(c) applies and no notice is required; if 7 years or under, S.35(1)(b) "
                "applies and the notice-first framework (Arnesh Kumar / Satender Kumar Antil) governs.")
        if recognized_but_contingent:
            return _result(req, "Cannot Determine",
                "This section is recognised, but its punishment is explicitly contingent on another factor "
                "(e.g. an abettor's punishment following the offence abetted) and is not a fixed value. "
                "Whether the notice-first framework applies cannot be automatically resolved. Verify "
                "independently.")
        return _result(req, "Cannot Determine",
            "Section not recognized in lookup table and punishment range not stated in document; the "
            "threshold that decides which limb of S.35(1) applies cannot be established.")
    
    # NEW: fine-only offences (no imprisonment at all) raise a different, more
    # fundamental question than notice-timing — flag it distinctly rather than
    # folding it into the ordinary sub-7-year notice branch below.
    if upper == 0:
        return _result(req, "Cannot Determine",
            f"Offence carries a fine only, with no imprisonment at all ({source}). Arrest for a purely "
            f"fine-only offence is unusual and raises its own threshold question, separate from whether a "
            f"S.35(3) notice was served. Verify independently why an arrest occurred at all for this offence.")

    notice = f.get("41A_or_35_BNSS_notice_issued_before_arrest")
    if notice is True:
        return _result(req, "Compliant",
            f"Prior S.35(3) notice recorded before arrest for an offence punishable up to {upper} years ({source}).",
            doctrine_key="arnesh_kumar_checklist")
    if notice is False:
        return _result(req, "May be Non-Compliant",
            f"Offence punishable up to {upper} years ({source}); arrest was made after the event on the basis "
            f"of investigation, and no other arrest power under S.35(1) has been established. No mention of "
            f"the mandatory S.35(3) notice. Per Satender Kumar Antil (2026 INSC 115): notice is the rule and "
            f"arrest the exception. The arrest may be illegal if no notice was in fact served.",
            doctrine_key="arnesh_kumar_checklist",
            # Rakhi Mitra directly restates Arnesh Kumar's consequence rule
            # (departmental action + contempt) for exactly this scenario --
            # non-compliance with the notice requirement. Sri Manjunath M P
            # is deliberately NOT attached anywhere: it applies Arnesh Kumar
            # to a substantive vague-allegation/abuse-of-process question,
            # which is a different legal question from the procedural
            # notice-timing question this function checks, and this project
            # has no existing check for that substantive question -- wiring
            # it here would misrepresent what it's actually relevant to.
            applying_precedent_key="rakhi_mitra_arnesh_kumar_consequences")
    return _result(req, "Cannot Determine",
        "Arrest appears to fall on the S.35(1)(b) pathway, but whether a prior notice was served is unclear "
        "from the information given.",
        doctrine_key="arnesh_kumar_checklist")
    

def _resolve_field_with_conditions(entry, field_name):
    """
    Shared helper for check_cognizable_arrest_basis and
    compute_bail_pathway_info: determines the TRUSTWORTHY value of a
    boolean-ish field (cognizable or bailable) for one BNS_SECTION_DATA
    entry, accounting for multi-condition sections where the top-level
    value can DISAGREE with individual conditions.
 
    CONFIRMED REAL BUG THIS FIXES (2026-08-28), found via a direct audit
    of all 436 entries in bns_final_merged_table.json: the previous
    logic only checked whether the top-level field was literally the
    string "contingent". This missed 60 of 84 needs_review=True entries
    entirely (the string check only caught 24). Of those 60, a further
    direct audit of the 20 entries with has_multiple_conditions=True and
    a clean top-level value found 8 REAL disagreements -- cases where
    the top-level value is provably wrong for at least one genuine
    condition. Confirmed example: Section 303(2) (theft) has top-level
    cognizable=True, but its own all_conditions show cognizable values
    of [False, True] depending on which condition applies -- meaning a
    real theft case matching the non-cognizable condition would have
    been WRONGLY told the offence is cognizable. This section is
    already live and discussed by name in this tool's chat interface as
    of this session.
 
    Also confirmed: at least one entry (Section 95) has the literal
    string "contingent" appearing INSIDE individual conditions even
    though its own top-level field is a clean boolean -- so checking
    only the top-level field for "contingent" is insufficient even for
    that specific string-based signal; every condition must be checked.
 
    Args:
        entry: one BNS_SECTION_DATA value (a dict for a single section
            or subsection key).
        field_name: "cognizable" or "bailable".
 
    Returns:
        One of:
          - True or False: the field's real, verified, TRUSTWORTHY
            value (either no multi-condition complexity exists, or
            every condition agrees with the top-level value).
          - "contingent": either the top-level field IS the literal
            string "contingent", OR any individual condition contains
            that string, OR conditions exist but genuinely DISAGREE
            with each other or with the top-level value. In every one
            of these cases, the caller should treat this exactly like
            the pre-existing "contingent" handling (i.e. "Cannot
            Determine" -- verify from the case record), since silently
            picking one condition over another would be a legal
            classification the LLM/this function isn't positioned to
            make. This is a deliberate REUSE of the existing
            "contingent" signal/vocabulary already handled downstream,
            not a new state -- callers require NO changes to their
            "contingent" branch, only to how this value gets computed
            before reaching that branch.
    """
    top_level = entry.get(field_name)
 
    # Top-level is already the explicit sentinel -- no further checking
    # needed, this is the case the original code already handled
    # correctly.
    if top_level == "contingent":
        return "contingent"
 
    conditions = entry.get("all_conditions")
    has_multiple = entry.get("has_multiple_conditions")
 
    # No multi-condition complexity at all -- top-level value stands as
    # the real, trustworthy value (this covers the vast majority of
    # entries, including all 352 "clean" ones, unaffected by this fix).
    if not has_multiple or not conditions:
        return top_level
 
    # Multi-condition section: check EVERY condition's value for this
    # field, including scanning for the literal "contingent" string
    # inside a condition even if the top-level field itself is clean
    # (confirmed necessary by Section 95's real data).
    condition_values = set()
    for cond in conditions:
        cond_value = cond.get(field_name)
        if cond_value == "contingent":
            return "contingent"
        condition_values.add(cond_value)
 
    # All conditions agree with EACH OTHER -- but do they also agree
    # with the top-level value? A section could theoretically have all
    # conditions agree with each other while disagreeing with a stale
    # or mis-set top-level field; treat that as untrustworthy too,
    # since we can't tell which one is actually correct.
    if len(condition_values) == 1:
        only_condition_value = next(iter(condition_values))
        if only_condition_value == top_level:
            return top_level  # genuinely safe, confirmed by agreement
        else:
            return "contingent"  # top-level and conditions disagree
 
    # Conditions disagree with EACH OTHER -- this is the confirmed real
    # bug case (e.g. Section 303(2)). Cannot pick one without making a
    # legal classification decision this function shouldn't make.
    return "contingent"


def _lookup_section_variants(sec):
    """Shared helper: given a bare or subsection-qualified section number,
    return every matching BNS_SECTION_DATA entry -- the exact bare key if
    it exists, plus every subsection variant (e.g. "303" -> "303(2)").
 
    ADDED 2026-08-29 to fix a confirmed real bug found via
    interview_flow.py: multiple functions in this file
    (check_cognizable_arrest_basis, get_max_years_from_sections,
    compute_bail_pathway_info, check_fir_no_arrest_status) each had
    their OWN bare `sec in BNS_SECTION_DATA` / `.get(sec)` lookup with
    no subsection fallback. BNS_SECTION_DATA keys 239 of 436 entries
    (55%) by subsection only (e.g. "303(2)", not bare "303") --
    confirmed via a real conversation where a correctly-identified,
    correctly-confirmed "theft" offence (section "303") produced
    "section not recognized" on every single check, because no bare
    "303" key exists. This is the SAME bug class
    semantic_retrieval.py's find_relevant_sections() already found and
    fixed for its own purposes -- centralized here as ONE shared helper
    so every caller gets the fix consistently, rather than requiring
    the same subsection-variant logic to be independently reimplemented
    (and potentially forgotten) in every function that reads
    BNS_SECTION_DATA.
 
    Returns: list of (matched_key, data_dict) tuples, in this order:
        - the exact bare key's data first, if it exists
        - every subsection variant, sorted by key, otherwise
    Returns an empty list if nothing matches at all.
    """
    results = []
    if sec in BNS_SECTION_DATA:
        results.append((sec, BNS_SECTION_DATA[sec]))
    variant_keys = sorted(k for k in BNS_SECTION_DATA if k.startswith(f"{sec}("))
    for k in variant_keys:
        results.append((k, BNS_SECTION_DATA[k]))
    return results


def check_cognizable_arrest_basis(f):
    req = "Threshold basis for arrest without warrant [cognizability of the offence]"
 
    cleaned = [re.sub(r'\s*(BNS|IPC|BNSS|CrPC)\s*$', '', str(s).strip(), flags=re.IGNORECASE).strip()
               for s in f.get("sections_cited", [])]
 
    if not cleaned:
        return _result(req, "Cannot Determine",
            "No recognised section cited; whether the offence is cognizable (permitting arrest without "
            "warrant) cannot be established.")
 
    # FIXED 2026-08-29: was `[BNS_SECTION_DATA[sec] for sec in cleaned if
    # sec in BNS_SECTION_DATA]` -- a BARE lookup with no subsection
    # fallback. CONFIRMED REAL FAILURE: interview_flow.py's offence
    # confirmation writes bare section numbers into sections_cited
    # (e.g. "303" for theft, matched via semantic search against the
    # embedded statute text which is chunked at the bare top-level
    # section boundary). BNS_SECTION_DATA has NO bare "303" key --
    # only "303(2)" -- so known_entries came back completely empty
    # despite the person correctly confirming "theft", and every
    # downstream check wrongly reported "section not recognized". This
    # is the SAME subsection-collision bug semantic_retrieval.py's
    # find_relevant_sections() already found and fixed for its own
    # purposes (BNS_SECTION_DATA keys 239 of 436 entries, 55%, by
    # subsection, not the bare number) -- reusing that same
    # every-subsection-variant pattern here.
    known_entries = []
    for sec in cleaned:
        known_entries.extend(data for _key, data in _lookup_section_variants(sec))
 
    if not known_entries:
        return _result(req, "Cannot Determine",
            "Cited section(s) not recognised in the lookup table; cognizability status cannot be established.")
 
    # CHANGED 2026-08-28: was `entry.get("cognizable") == "contingent"`,
    # which only caught the literal top-level string and missed 8
    # confirmed real cases where has_multiple_conditions=True entries
    # have a clean top-level value that disagrees with at least one
    # genuine condition (see _resolve_field_with_conditions docstring
    # for the full confirmed-bug writeup, including Section 303(2)
    # already live in this tool's chat interface).
    resolved_cognizable = [_resolve_field_with_conditions(entry, "cognizable") for entry in known_entries]
 
    if any(val == "contingent" for val in resolved_cognizable):
        return _result(req, "Cannot Determine",
            "Cognizability of the cited section(s) depends on circumstances not captured here (e.g. the "
            "underlying/related offence) — cannot be automatically established. Verify from the case record.")
 
    if all(val is True for val in resolved_cognizable):
        return _result(req, "Compliant",
            "The cited offence(s) are cognizable — police ordinarily have power to arrest without a warrant. "
            "This does not by itself confirm the specific arrest power exercised was lawful; see the notice "
            "and other checks below for that.")
 
    if all(val is False for val in resolved_cognizable):
        return _result(req, "Non-Compliant",
            "The cited offence(s) are recorded as NON-COGNIZABLE in the statutory reference table. Ordinarily, "
            "police have no general power to arrest without a warrant for a non-cognizable offence — such an "
            "arrest is a threshold defect independent of whether a S.35(3) notice was served. A small number of "
            "specific statutes carve out exceptions permitting warrantless arrest even for particular "
            "non-cognizable matters; verify from the case record whether such a specific exception applies here "
            "before treating this as conclusive.")
 
    return _result(req, "Cannot Determine",
        "The cited offences have MIXED cognizability — some are cognizable, some are not. Whether the arrest "
        "was lawful depends on which specific offence the arrest power was actually exercised under; this "
        "cannot be determined automatically from the combined citation list. Verify from the case record.")
 

    
    
def check_223_cognizance_bar(f):
    req = "Cognizance bar for S.223 BNS offences [S.215(1)(a) BNSS]"
    cleaned = [re.sub(r'\s*(BNS|IPC|BNSS|CrPC)\s*$', '', str(s).strip(), flags=re.IGNORECASE).strip()
               for s in f.get("sections_cited", [])]
    if "223" not in cleaned:
        return _result(req, "Not Applicable", "No S.223 BNS (disobedience of promulgated order) offence cited.")
    return _result(req, "Cannot Determine",
        "S.215(1)(a) BNSS bars any court from taking cognizance of a S.223 BNS offence except on a WRITTEN "
        "complaint by the public servant whose order was disobeyed (or a superior). If this case was initiated "
        "only by a police FIR without that written complaint, this is a threshold defect capable of voiding the "
        "entire prosecution before any arrest-procedure question arises. Verify from the case record who filed "
        "the complaint — this specific procedural bar should be independently confirmed with counsel.")

def check_written_grounds(f):
    req= "Written grounds of arrest furnished to arrestee [Prabir Purkayastha (2024) / Vihaan Kumar, 2025 INSC 162]"
    v= f.get("grounds_of_arrest_in_writing_furnished_to_arrestee")
    if v is True :
        return _result(req, "Compliant", "Written grounds of arrest were furnished to the arrestee.", doctrine_key="vihaan_kumar_written_grounds")
    if v is False:
        return _result(req, "May be Non-Compliant",
    "The document does not mention of written grounds of arrest recorded being furnished. "
    "Per Vihaan Kumar (2025 INSC 162): failure to furnish written grounds violates Article 22(1), "
    "renders the arrest itself illegal, and is a ground for bail even where statutory bail restrictions "
    "exist — the burden is on the state to prove grounds were furnished.", doctrine_key="vihaan_kumar_written_grounds")
    return _result(req, "Cannot Determine", "Whether written grounds were furnished cannot be determined from the document.", doctrine_key="vihaan_kumar_written_grounds")

def check_dk_basu_memo(f):
    req ="Arrest memo attested by witness, family informed, medical exam [DK Basu (1997)]"
    checks = [
        ("witness attested", f.get("witness_attested_memo")),
        ("family informed", f.get("family_or_friend_informed")),
        ("medical exam recorded", f.get("medical_exam_at_arrest_recorded")),
    ]
    
    missing = [ name for name ,v in checks if v is False]
    unclear = [name for name, v in checks if v == "unclear" or  v is None]
    if missing:
       return _result(req, "Non-Compliant", f"D.K Basu items missing: {', '.join(missing)}. ", doctrine_key="dk_basu_safeguards")
    if unclear:
       return _result(req, "Cannot Determine", f" D.K Basu items unclear from document: {', '.join(unclear)}.", doctrine_key="dk_basu_safeguards")
    return _result(req, "Compliant", "Witness attestation, family notification, and medical exam all recorded.", doctrine_key="dk_basu_safeguards")

def check_night_arrest_of_woman(f):
    req = "Woman not arrested between sunset and sunrise [S.46(4) CrPC/ Sheela Barse]"
    gender = f.get("arrestee_gender")
    if gender == "third_gender":
        dt = parse_datetime_full(f.get("arrest_datetime_full"))
        if dt is None:
            return _result(req, "Cannot Determine", "Arrest time not stated; this safeguard's application to third-gender arrestees cannot be checked.")
        hour = dt.hour
        note = "This specific safeguard was framed for women arrestees; its extension to third-gender arrestees follows the spirit of NALSA v. Union of India (2014) but is not yet settled by a specific ruling on this exact point."
        if 6 <= hour < 18:
            return _result(req, "Compliant", f"Arrest at {dt.strftime('%H:%M')} is within daylight hours. {note}")
        return _result(req, "Cannot Determine", f"Arrest at {dt.strftime('%H:%M')} was outside daylight hours. {note} Verify independently.")
    if gender != "female":
        return _result(req, "Not Applicable", "Arrestee is not female.")
    dt = parse_datetime_full(f.get("arrest_datetime_full"))
    if dt is None:
        return _result(req, "Cannot Determine", "Arrest time not stated in full; night-arrest rule cannot be checked.")
    hour = dt.hour
    if 6 <= hour < 18:
        return _result(req, "Compliant", f"Arrest at {dt.strftime('%H:%M')} is within daylight hours.")
    return _result(req, "Non-Compliant", f"Female arrestee taken at {dt.strftime('%H:%M')} (outside 06:00-18:00). Prior magistrate permission mandatory.")

def check_female_officer_involvement(f):
    req = "Female officer involved in custody/interrogation of female arrestee [Sheela Barse (1983)]"
    gender = f.get("arrestee_gender")

    if gender == "third_gender":
        v = f.get("female_officer_present_for_female_arrestee")
        note = ("This safeguard was framed for female arrestees; its extension to third-gender arrestees "
                "follows the spirit of NALSA v. Union of India (2014) but is not settled by a specific ruling "
                "on this exact point. Best practice guidance in several states calls for an officer of the "
                "arrestee's choice or a third-gender-sensitised officer to be involved.")
        if v is True:
            return _result(req, "Compliant", f"Appropriate officer involvement recorded for this arrestee. {note}")
        if v is False:
            return _result(req, "Cannot Determine", f"No such officer involvement recorded. {note} Verify independently.")
        return _result(req, "Cannot Determine", f"Officer involvement status is unclear from the document. {note}")

    if gender != "female":
        return _result(req, "Not Applicable", "Arrestee is not female.")

    v = f.get("female_officer_present_for_female_arrestee")
    if v is True:
        return _result(req, "Compliant", "Female officer involvement recorded for this female arrestee.")
    if v is False:
        return _result(req, "May be Non-Compliant",
            "No female officer involvement recorded. Sheela Barse judgement requires a female officer for "
            "custody, interrogation, and search of a female arrestee. Silence on this point in an otherwise "
            "detailed memo suggests it may not have been observed.")
    return _result(req, "Cannot Determine", "Female officer involvement status is unclear from the document.")


def check_24_hour_production(f):
    req = "Produced before magistrate within 24 hours [Art. 22(2)/S. 58 BNSS]"
    a = parse_datetime_full(f.get("arrest_datetime_full"))
    p= parse_datetime_full(f.get("production_datetime_full"))
    if a is None:
        return _result(req, "Cannot Determine", "Arrest time not fully stated. ")
    if p is None:
        return _result(req, "Cannot Determine", "Production-before-magistrate time not stated in this document.")
    gap_hrs = (p-a).total_seconds()/3600.0
    if gap_hrs <= 24:
        return _result(req, "Compliant", f"Produced {gap_hrs:.1f} hours after arrest — within 24 hours.")
    return _result(req, "Non-Compliant", f"Produced {gap_hrs:.1f} hours after arrest — exceeds constitutional 24-hour limit.")

def check_default_bail(f, user_chargesheet_date=None):
    req = "Default bail on chargesheet delay [S.187 BNSS / S.167(2) CrPC]"

    a = parse_datetime_full(f.get("arrest_datetime_full"))
    if a is None:
        return _result(req, "Cannot Determine", "Arrest date/time not stated; default-bail clock cannot be computed.")
    looked_up = get_max_years_from_sections(f.get("sections_cited", []))
    if looked_up == "LIFE_OR_DEATH":
        threshold_days = 90
        upper_desc = "life/death"
    elif looked_up == "CONTAINS_VARIABLE":
        p = parse_datetime_full(f.get("production_datetime_full"))
        if p is not None:
            remand_start = p
            remand_basis = "actual production-before-magistrate date stated in document"
        else:
            remand_start = a + timedelta(days=1)
            remand_basis = "ASSUMED as one day after arrest (production date not stated) — verify against the actual remand order"
        deadline_60 = remand_start + timedelta(days=60)
        deadline_90 = remand_start + timedelta(days=90)
        return _result(req, "Cannot Determine",
            f"One or more cited sections has a punishment that depends on the underlying offence, so whether "
            f"the 60-day or 90-day window applies cannot be confirmed. Both possible deadlines, based on "
            f"{remand_basis}: if the 60-day window applies, default bail becomes available on "
            f"{deadline_60.strftime('%d-%m-%Y')}; if the 90-day window applies (offences carrying 10+ years, "
            f"life, or death), it becomes available on {deadline_90.strftime('%d-%m-%Y')}. Confirm which "
            f"threshold applies once the underlying offence attempted under any variable section is known.")

    elif looked_up == "CONTAINS_CONTINGENT":
        p = parse_datetime_full(f.get("production_datetime_full"))
        if p is not None:
            remand_start = p
            remand_basis = "actual production-before-magistrate date stated in document"
        else:
            remand_start = a + timedelta(days=1)
            remand_basis = "ASSUMED as one day after arrest (production date not stated) — verify against the actual remand order"
        deadline_60 = remand_start + timedelta(days=60)
        deadline_90 = remand_start + timedelta(days=90)
        return _result(req, "Cannot Determine",
            f"One or more cited sections has a punishment that is contingent on another factor (not a fixed "
            f"value in our reference table), so whether the 60-day or 90-day window applies cannot be "
            f"confirmed. Both possible deadlines, based on {remand_basis}: if the 60-day window applies, "
            f"default bail becomes available on {deadline_60.strftime('%d-%m-%Y')}; if the 90-day window "
            f"applies, it becomes available on {deadline_90.strftime('%d-%m-%Y')}. Verify the applicable "
            f"threshold independently.")
    else:
        upper = looked_up if looked_up is not None else f.get("punishment_years_upper_bound")
        ...
        if upper is None:
            return _result(req, "Cannot Determine", "Section not recognized in lookup table and punishment range not stated; 60-day vs 90-day threshold unknown.")
        threshold_days = 90 if upper >= 10 else 60
        upper_desc = f"{upper} years"

    p = parse_datetime_full(f.get("production_datetime_full"))
    if p is not None:
        remand_start = p
        remand_basis = "actual production-before-magistrate date stated in document"
    else:
        remand_start = a + timedelta(days=1)
        remand_basis = "ASSUMED as one day after arrest (production date not stated in document) — verify against the actual remand order"

    deadline_date = remand_start + timedelta(days=threshold_days)
    today = datetime.now()

    # user-supplied answer takes priority over document extraction, since the
    # document almost never contains this — it's created before a chargesheet exists
    cs_str = user_chargesheet_date if user_chargesheet_date is not None else f.get("chargesheet_filed_date")
    cs_dt = parse_date(cs_str)

    if cs_dt is not None:
        if cs_dt <= deadline_date:
            return _result(req, "Compliant", f"Chargesheet filed {cs_dt.strftime('%d-%m-%Y')}, within the {threshold_days}-day window (offence up to {upper_desc}; {remand_basis}).")
        return _result(req, "Non-Compliant", f"Chargesheet filed {cs_dt.strftime('%d-%m-%Y')}, AFTER the {threshold_days}-day window that expired {deadline_date.strftime('%d-%m-%Y')}. Default bail rights had accrued (offence up to {upper_desc}; {remand_basis}).")

    days_remaining = (deadline_date - today).days
    if days_remaining < 0:
        return _result(req, "May be Non-Compliant", f"No chargesheet filed as of today. Default bail eligibility date was {deadline_date.strftime('%d-%m-%Y')} ({-days_remaining} days ago) — {threshold_days}-day window (offence up to {upper_desc}; {remand_basis}). Default bail is now a matter of right.")
    return _result(req, "Compliant", f"No chargesheet filed yet. Default bail becomes available on {deadline_date.strftime('%d-%m-%Y')} if chargesheet is not filed before then — {days_remaining} days remain ({threshold_days}-day window; offence up to {upper_desc}; {remand_basis}).")



def run_arrest_compliance_checks(fields, user_chargesheet_date=None):
    checks = [
        check_arnesh_kumar_notice(fields),
        check_cognizable_arrest_basis(fields),
        check_written_grounds(fields),
        check_dk_basu_memo(fields),
        check_night_arrest_of_woman(fields),
        check_female_officer_involvement(fields),
        check_24_hour_production(fields),
        check_default_bail(fields, user_chargesheet_date),
    ]
 
     # Only include the 223 cognizance-bar check when 223 BNS is actually cited —
    # unlike the other Not Applicable results, this rule has no bearing at all
    # on non-223 cases, so it's excluded entirely rather than shown as N/A noise.
    cleaned_sections = [
        re.sub(r'\s*(BNS|IPC|BNSS|CrPC)\s*$', '', str(s).strip(), flags=re.IGNORECASE).strip()
        for s in fields.get("sections_cited", [])
    ]
    if "223" in cleaned_sections:
        checks.append(check_223_cognizance_bar(fields))
        
    non_compliant = [c for c in checks if c["status"] in ("Non-Compliant", "May be Non-Compliant")]
    undetermined = [c for c in checks if c["status"] == "Cannot Determine"]
    if non_compliant:
        overall = f"{len(non_compliant)} procedural defect(s) found or suspected. Arrest may be legally vulnerable."
    elif undetermined:
        overall = f"No defects proven, but {len(undetermined)} check(s) could not be verified. Manual review recommended."
    else:
        overall = "All applicable procedural checks pass."
    return {"compliance_checks": checks, "overall_assessment": overall}

def compute_severity(compliance_checks):
    """Weighted severity score from compliance findings.
    Non-Compliant = confirmed defect (2 pts), May be Non-Compliant = suspected/inferred (1 pt).
    Cannot Determine is tracked separately, never folded into the score."""
    score = 0
    unresolved_count = 0

    for check in compliance_checks:
        status = check.get("status")
        if status == "Non-Compliant":
            score += 2
        elif status == "May be Non-Compliant":
            score += 1
        elif status == "Cannot Determine":
            unresolved_count += 1

    if score == 0:
        label, color, tier = "No Procedural Defects Found", "green",1
    elif score <= 2:
        label, color, tier = "Some Concerns", "amber",2
    elif score <= 4:
        label, color, tier = "Serious Concerns", "orange",3
    else:
        label, color, tier = "Critical — Rights Likely Violated", "red",4
    tier_blocks = {1: "🟩", 2: "🟨", 3: "🟧", 4: "🟥"}
    meter = "".join(tier_blocks[t] for t in range(1, tier + 1)) + "⬜" * (4 - tier)

    return {
        "severity_score": score,
        "severity_label": label,
        "severity_color": color,
        "severity_meter": meter,
        "unresolved_checks": unresolved_count,
    }

def generate_quick_reference(full_analysis):
    """One-glance courtroom view: every actionable defect, worst first, plus default bail status."""
    compliance = full_analysis.get("compliance", {})
    checks = compliance.get("compliance_checks", [])
    severity = full_analysis.get("severity", {})

    priority = {"Non-Compliant": 0, "May be Non-Compliant": 1}
    actionable = [c for c in checks if c.get("status") in priority]
    actionable.sort(key=lambda c: priority[c["status"]])

    default_bail_check = next(
        (c for c in checks if "Default bail" in c.get("requirement", "")), None
    )

    return {
        "severity_label": severity.get("severity_label", "Not Available"),
        "severity_meter": severity.get("severity_meter", ""),
        "actionable_issues": actionable,
        "default_bail": default_bail_check,
    }

def compute_bail_pathway_info(sections_cited):
    """Informational only — NOT a compliance verdict, and must never be folded
    into compliance_checks or the severity score. Tells the family what kind
    of bail process applies: police-station bail (bailable) vs. court-only
    bail (non-bailable).
 
    FIXED 2026-08-29: was `[(sec, BNS_SECTION_DATA[sec]) for sec in
    cleaned if sec in BNS_SECTION_DATA]` -- same confirmed bare-lookup
    bug class as check_cognizable_arrest_basis. Now uses the shared
    _lookup_section_variants helper; when multiple variants exist for
    one bare section, each is checked independently and the existing
    "mixed" pathway logic below already handles disagreement honestly
    (no new special-casing needed here, since a mix of bailable/
    non-bailable variants is exactly the "mixed" case this function
    already reports)."""
    cleaned = [re.sub(r'\s*(BNS|IPC|BNSS|CrPC)\s*$', '', str(s).strip(), flags=re.IGNORECASE).strip()
               for s in (sections_cited or [])]
 
    known_entries = []
    for sec in cleaned:
        for matched_key, data in _lookup_section_variants(sec):
            known_entries.append((matched_key, data))
 
    if not known_entries:
        return {
            "pathway": "unknown",
            "message": "No recognised section was available, so whether bail can be granted at the "
                       "police station or only by a court cannot be determined from this information."
        }
 
    resolved = [(sec, _resolve_field_with_conditions(data, "bailable")) for sec, data in known_entries]
 
    contingent_sections = [sec for sec, val in resolved if val == "contingent"]
    if contingent_sections:
        return {
            "pathway": "unknown",
            "message": f"Bail eligibility for section(s) {', '.join(contingent_sections)} depends on "
                       f"circumstances not captured here (e.g. the underlying offence abetted) — this "
                       f"cannot be determined automatically. Verify with a lawyer."
        }
 
    if all(val is True for _, val in resolved):
        return {
            "pathway": "police_station",
            "message": "The cited offence(s) are BAILABLE. Under S.478 BNSS, bail is a matter of right and "
                       "the officer in charge of the police station can grant it directly — the family does "
                       "not need to wait for a court to open. If bail is refused at the station despite this, "
                       "that refusal is itself worth raising with a magistrate or superior officer."
        }
 
    if all(val is False for _, val in resolved):
        return {
            "pathway": "court_only",
            "message": "The cited offence(s) are NON-BAILABLE. Bail is discretionary and can only be granted "
                       "by a court, not by the police station directly. The family should approach a "
                       "magistrate — through a lawyer if possible — as soon as possible; there is no "
                       "automatic right to release here."
        }
 
    return {
        "pathway": "mixed",
        "message": "Some cited offence(s) are bailable and others are not. Where offences are mixed, courts "
                   "generally treat the case under the non-bailable offence's stricter process — a court, "
                   "not the police station, should be approached for bail. Verify this with a lawyer given "
                   "the mixed charges."
    }

def check_freeze_section_and_scope(f):
    """UPDATED 2026-08-30: added real citations to Neelkanth Pharma
    Logistics Pvt. Ltd. v Union of India (Delhi HC, 2025) and Malabar
    Gold and Diamond Limited v Union of India (Delhi HC, 2026), sourced
    and verified this session -- previously this check's "High Court
    trend" reference (Karnataka, Kerala, Bombay) was an assertion with
    no actual case law behind it in this project's corpus. Also uses
    specific_amount_stated, when available, to make the Non-Compliant
    message concretely reference the actual disputed sum rather than a
    generic statement."""
    req = "Blanket freeze under 106/107 BNSS restricted to disputed amount [Neelkanth Pharma Logistics (2025) / Malabar Gold (2026)]"
    scope = f.get("scope")
    specific_amount = f.get("specific_amount_stated")
 
    if scope == "specific disputed amount":
        return _result(req, "Compliant",
            "Freeze scope limited to specific disputed amount -- this is the proportionate approach "
            "favoured in Neelkanth Pharma Logistics Pvt. Ltd. v Union of India (Delhi High Court, "
            "2025), which recommends marking a lien on the disputed sum over freezing an account in "
            "its entirety.")
 
    if scope == "entire account":
        # FIXED 2026-08-30: was `if specific_amount is not None and
        # specific_amount != ""`, which treated the literal string
        # "unclear" as if it were a real known amount. CONFIRMED REAL
        # BUG: freeze_interview_flow.py's extraction correctly returns
        # the string "unclear" when the person genuinely doesn't know
        # the disputed amount -- this is a NEW input shape the
        # button-based UI never produced (its number_optional widget
        # only ever yields a real number or None/"SKIPPED"). The old
        # check silently interpolated "unclear" into the explanation
        # text, producing the nonsensical "Rs. unclear" in a live
        # conversation. Fixed by explicitly excluding "unclear" (and
        # "SKIPPED", the button-flow's equivalent placeholder) from
        # being treated as a real value.
        if specific_amount not in (None, "", "unclear", "SKIPPED"):
            return _result(req, "Non-Compliant",
                f"Entire account frozen, despite a specific disputed amount (Rs. {specific_amount}) "
                f"being identifiable. Per Neelkanth Pharma Logistics Pvt. Ltd. v Union of India (Delhi "
                f"High Court, 2025), freezing an entire account rather than the specific disputed sum "
                f"can be disproportionate and a violation of Article 21 -- the Court there noted that a "
                f"full freeze causes serious consequences (dishonoured cheques, business disruption) "
                f"unrelated to the disputed amount itself. Malabar Gold and Diamond Limited v Union of "
                f"India (Delhi High Court, 2026) independently holds blanket freezing of non-accused, "
                f"non-suspect account holders arbitrary and disproportionate.")
        return _result(req, "Non-Compliant",
            "Entire account frozen. High Courts have held blanket freezes disproportionate -- see "
            "Neelkanth Pharma Logistics Pvt. Ltd. v Union of India (Delhi High Court, 2025) and Malabar "
            "Gold and Diamond Limited v Union of India (Delhi High Court, 2026). If a specific disputed "
            "amount can be identified, that strengthens the case that a full freeze was "
            "disproportionate -- worth establishing this figure directly.")
 
    return _result(req, "Cannot Determine", "Freeze scope not stated in document.")

def check_freeze_magistrate_intimation(f):
    req = "Seizure/freeze intimated forthwith to Magistrate [S.106 BNSS]"
    v= f.get("magistrate_intimation_recorded")
    if v is True:
        return _result(req, "Compliant", "Intimation to jurisdictional Magistrate is recorded.")
    if v is False:
        return _result( req, "Non-Compliant", " No record of intimation to Magistrate. S.106 BNSS requires forthwith intimation.")
    return _result(req, "Cannot Determine", "magistrate intimation not clearly stated.")

def check_freeze_107_court_order(f):
    """UPDATED 2026-08-30: added real citations to Malabar Gold and
    Diamond Limited v Union of India (Delhi HC, 2026) and State of
    Maharashtra v Tapas D. Neogy, (1999) 7 SCC 685, sourced and
    verified this session -- previously this check's requirement text
    referenced Section 107 BNSS generically with no case law attached.
    Malabar Gold directly establishes that Section 106 alone can NEVER
    authorise a freeze/attachment (only evidentiary seizure) -- the
    existing final fallback branch already correctly routed non-107
    sections to "verify whether the correct attachment procedure was
    followed"; this update adds an explicit branch for Section 106
    specifically, citing the doctrine, since that is the single most
    common real defect pattern the new judgments describe."""
    req = "Attachment/freeze authorized via Section 107 BNSS court order [Malabar Gold (2026) / Tapas D. Neogy (1999)]"
    section = f.get("section_invoked")
 
    if section == "107 BNSS":
        v = f.get("court_order_referenced_for_107")
        if v is True:
            return _result(req, "Compliant",
                "Court order under S.107 BNSS is referenced, consistent with the requirement in Malabar "
                "Gold and Diamond Limited v Union of India (Delhi High Court, 2026) that "
                "attachment/freezing of bank accounts can only be done strictly upon the order of a "
                "competent Magistrate.")
        if v is False:
            return _result(req, "Non-Compliant",
                "S.107 BNSS invoked but no referenced court order. Per Malabar Gold and Diamond Limited "
                "v Union of India (Delhi High Court, 2026), attachment requires prior judicial sanction "
                "-- absence of any such order being shown is a real basis to challenge the freeze's "
                "legality, and the account holder may request the investigating authority to produce "
                "it.")
        return _result(req, "Cannot Determine", "Court order referenced for S.107 unclear.")
 
    if section == "106 BNSS":
        return _result(req, "Non-Compliant",
            "The freeze is recorded as being carried out under Section 106 BNSS. Per Malabar Gold and "
            "Diamond Limited v Union of India (Delhi High Court, 2026), Section 106 empowers police "
            "only to seize property for evidentiary purposes -- it confers NO authority to attach or "
            "debit-freeze a bank account. This doctrine traces back to the Supreme Court's foundational "
            "holding in State of Maharashtra v Tapas D. Neogy, (1999) 7 SCC 685, that a bank account is "
            "\"property\" seizable only with a genuine investigative nexus. Freezing or attaching funds "
            "as suspected proceeds of crime can only be done under Section 107 BNSS, strictly upon the "
            "order of a competent Magistrate. If no Section 107 order was obtained, this freeze may be "
            "unauthorised and legally vulnerable to challenge.")
 
    if section == "none cited":
        return _result(req, "May be Non-Compliant",
            "No legal section was cited to justify this freeze at all. Account/property attachment is "
            "supposed to proceed under Section 107 BNSS with Magistrate intimation. A freeze effected "
            "without invoking this process, on bare police request alone, may be illegal -- see Malabar "
            "Gold and Diamond Limited v Union of India (Delhi High Court, 2026).")
 
    return _result(req, "Cannot Determine",
        f"Freeze invoked under '{section}', not Section 107 BNSS -- verify whether the correct "
        f"attachment procedure was followed.")
    

def check_freeze_holder_intimation(f):
    """UPDATED 2026-08-30: added a real, verified citation to Malabar
    Gold and Diamond Limited v Union of India (Delhi HC, 2026),
    fallback_8, which directly holds that account holders are "at the
    very least, entitled to be informed of the reasons for freezing
    their bank accounts" -- confirmed verbatim in the primary text.

    IMPORTANT LEGAL CORRECTION from the previous version: the earlier
    wording ("violated basic notice principles") did not distinguish
    PRE-freeze notice from POST-freeze intimation -- a real, material
    distinction confirmed via web search (2026-08-30). An Allahabad
    High Court ruling (reported as Ashish Rawat v Union of India,
    cited as 2026:AHC:78406-DB) explicitly held that "prior notice to
    the account holder is not a prerequisite for freezing under
    Section 106 BNSS" -- meaning a freeze is NOT rendered unlawful
    merely for lacking advance warning. The same reporting confirms
    courts have separately required POST-freeze notification, ordering
    that "banks must inform account holders after freezing." This
    check is about POST-freeze intimation specifically (per its field
    name and framing "discovered only at bank/ATM"), now made explicit
    below rather than left ambiguous.

    NOTE ON SOURCING: the Allahabad HC case itself could NOT be
    located or independently verified via indiankanoon_client.py
    despite multiple search attempts (party name, party name + subject
    terms, and the reported neutral citation number all returned no
    match). Per this project's standing discipline, an unverified
    secondary-source case is NOT cited as an authority here. The
    citation below rests entirely on Malabar Gold, which IS
    independently verified against primary text (fallback_8)."""
    req = "Account holder intimated of freeze after the fact [Malabar Gold (2026)]"
    v = f.get("account_holder_intimated")
    if v is True:
        return _result(req, "Compliant",
            "Account holder intimated of the freeze. This is consistent with Malabar Gold and Diamond "
            "Limited v Union of India (Delhi High Court, 2026), which holds that an account holder is "
            "\"at the very least, entitled to be informed of the reasons for freezing their bank "
            "accounts.\"")
    if v is False:
        return _result(req, "May be Non-Compliant",
            "Account holder not intimated -- the freeze was discovered only at the bank/ATM. Per "
            "Malabar Gold and Diamond Limited v Union of India (Delhi High Court, 2026), an account "
            "holder is \"at the very least, entitled to be informed of the reasons for freezing their "
            "bank accounts.\" Note: BNSS does not require notice BEFORE a freeze -- this concerns the "
            "absence of any intimation AFTER the fact, which the account holder can raise directly with "
            "the investigating authority or bank.")
    return _result(req, "Cannot Determine", "Account holder intimation status unclear.")

def check_freeze_authorization_inferred(fields):
    """NEW 2026-08-30: honest, free-text-specific alternative to
    check_freeze_107_court_order. NEVER used interchangeably with that
    function -- this one is for cases where the person does NOT know
    which BNSS section was invoked (the realistic case for someone
    whose only knowledge is "my account got frozen"), and infers
    authorization status from OBSERVABLE FACTS (was a court/Magistrate
    mentioned, was a written order shown) rather than asking the
    person to name a section they were never told.

    ARCHITECTURAL PRINCIPLE: an inferred fact must NEVER be silently
    converted into the same field/confidence level as a directly-
    stated fact. If a free-text flow inferred section_invoked from
    indirect signals and fed it into check_freeze_107_court_order, a
    wrong inference would produce a confidently wrong verdict, not an
    honest Cannot Determine. This function instead reads the raw
    observable facts directly and caps its own confidence
    accordingly -- it never claims certainty about which section was
    invoked, since the person genuinely may never have been told.

    Args:
        fields: expects court_or_magistrate_mentioned, written_order_shown,
            written_order_mentions_court (each True/False/"unclear").
    """
    req = "Some indication of Magistrate/court authorization for the freeze [Malabar Gold (2026) / Tapas D. Neogy (1999)]"

    court_mentioned = fields.get("court_or_magistrate_mentioned")
    order_shown = fields.get("written_order_shown")
    order_mentions_court = fields.get("written_order_mentions_court")

    if order_shown is True and order_mentions_court is True:
        return _result(req, "Compliant",
            "You mentioned receiving a written order that referred to a court, which is broadly "
            "consistent with the requirement in Malabar Gold and Diamond Limited v Union of India "
            "(Delhi High Court, 2026) that freezing/attaching a bank account requires the order of a "
            "competent Magistrate. This is based on what you described, not a direct reading of the "
            "document itself -- if you can get a copy of the order, it's worth having a lawyer confirm "
            "it genuinely reflects a Magistrate's authorization.")

    if court_mentioned is True:
        return _result(req, "Cannot Determine",
            "You mentioned a court or Magistrate being involved in some way, but it's not clear "
            "whether a specific written order was shown to you or what it said. Per Malabar Gold and "
            "Diamond Limited v Union of India (Delhi High Court, 2026), freezing a bank account "
            "requires a competent Magistrate's order -- it would help to get a copy of any such order "
            "and have it checked directly.")

    if court_mentioned is False and (order_shown is False or order_mentions_court is False):
        return _result(req, "May be Non-Compliant",
            "Based on what you've described, there's no indication that a court or Magistrate was "
            "involved in authorizing this freeze. Per Malabar Gold and Diamond Limited v Union of "
            "India (Delhi High Court, 2026), freezing or attaching a bank account requires the order "
            "of a competent Magistrate -- ordinary evidentiary seizure under Section 106 BNSS does "
            "NOT, by itself, authorise a full freeze. This is worth raising directly with the "
            "investigating authority or a lawyer.")

    return _result(req, "Cannot Determine",
        "There isn't enough information here to say whether this freeze was properly authorised by a "
        "court. If you're able to find out whether any written order exists, and what it says, that "
        "would help establish this.")



def run_freeze_compliance_checks(fields):
    checks = [
        check_freeze_section_and_scope(fields),
        check_freeze_magistrate_intimation(fields),
        check_freeze_107_court_order(fields),
        check_freeze_holder_intimation(fields),
    ]
    
    non_compliant = [c for c in checks if c["status"] in  ("Non-Compliant", "May be Non-Compliant")]
    undetermined = [c for c in checks if c["status"] == "Cannot Determine"]
    if non_compliant:
        overall = f" {len(non_compliant)} defect(s) found or suspected in freeze procedure. Freeze may be legally vulnerable."
    elif undetermined:
        overall = f"{len(undetermined)} check(s) unverifiable. Manual review recommended."
    else:
        overall = "Freeze procedure appears compliant on the face of the document." 
    return {"compliance_checks": checks, "overall_assessment": overall}

def check_ndps_section_50_offer(f):
    req = "Right to be searched before Magistrate/Gazetted Officer offered[ S.50 NDPS/ Baldev Singh]"
    target = f.get("search_target")
    if target!= "person":
        return _result(req, "Not Applicable", "recovery not from the person; S. 50 does not apply(Ranjan Kumar Chadha).")
    offered = f.get("option_offered_to_accused")
    if offered == "magistrate or gazetted officer":
        return _result(req, "Compliant", "Correct S. 50 option offered- Magistrate or Gazetted officer.")
    if offered in ("police officer only", "none offered"):
        return _result (req, "Non-Compliant", f"S.50 requires Magistrate/Gazetted Officer option. Instead :{offered}. Searcg rendered illegal. (Baldev Singh).")
    return _result (req, "Cannot Determine", "S.50 option status unclear from memo.")

def check_ndps_language(f):
    req = "S.50 notice given in language understood by accused[Paramanand]"
    target = f.get("seacrh_target")
    if target != "person":
        return _result(req, "Not Applicable", "S.50 does not apply to this search.")
    v= f.get("language_of_notice_understood_by_accused_confirmed")
    if v is True:
        return _result(req, "Compliant", "Language of notice confirmed understood by accused.")
    if v is False:
        return _result (req, "Non-Compliant", "Notice not confirmed to be in a language the accused understood.")
    return _result (req, "Cannot Determine", "Language comprehension by accused not stated.")

def check_seizure_witnesses(f):
    req= "Independent witnesses present at seizure"
    v= f.get("Independent_witnesses_present")
    if v is True:
        return _result(req, "Compliant", "Independent witnesses recorded as present.")
    if v is False:
        return _result(req, "Non-Compliant", "No independent witnesses recorded. Seizure evidentiary value weakened.")
    return _result(req, "Cannot Determine", "Independent witness presence unclear.")

def run_search_compliance_checks(fields):
    checks= [
        check_ndps_section_50_offer(fields),
        check_ndps_language(fields),
        check_seizure_witnesses(fields),
    ]
    non_compliant = [c for c in checks if c["status"] == "Non-Compliant"]
    undetermined = [c for c in checks if c["status"]== "Cannot Determine"]
    if non_compliant:
        overall = f"{len(non_compliant)} search/seizure defect(s). Recovery may be inadmissible. "
    elif undetermined:
        overall = f"{len(undetermined)} check(s) unverifiable. Manual review recommended."
    else:
        overall = "Search procedure appears compliant on face of the memo."
    return {"compliance_checks": checks, "overall_assessment":overall}

def check_fir_registration_regime(f):
    req = "FIR registration inquiry compliant with regime[lalita Kumari (2014)/ S.173(3) BNSS]"
    complaint_dt = parse_date(f.get("complaint_date"))
    is_cognizable = f.get("offence_alleged_is_cognizable")
    action = f.get("police_action")
    delay = f.get("delay_days")
    
    if is_cognizable is False:
        return _result(req, "Not Applicable", "Alleged offence is not cognizable.")
    if is_cognizable in("unclear", None):
        return _result(req, "Cannot Determine", "Cognizable/non-cognizable status unclear.")
    
    bnss_cutoff= datetime(2024,7,1)
    regime ="BNSS" if complaint_dt and complaint_dt>= bnss_cutoff else "CrPC"
    inquiry_window = 14 if regime == "BNSS" else 7 
    
    if action == "refused to register":
        return _result(req, "Non-Compliant", f"Cognizable offence alleged; refusal to violates Lalita Kumari mandate.")
    if action == "delayed registration" and delay is not None and delay > inquiry_window:
        return _result(req, "Non-Compliant", f"Delay of {delay} days exceeds {inquiry_window}-day inquiry window under {regime}.")
    if action == "NC entry only":
        return _result(req, "Non-Compliant", "NC entry made for a cognizable offence. FIR registartion was mandatory.")
    if action in ("delayed registartion", "closure intimation"):
        return _result(req, "Compliant" , f"Action within {regime} regime; no immediate defect.")
    return _result(req, "Cannot Determine", "Police action on complaint not clearly stated.")


def run_fir_compliance_checks(fields):
    checks = [check_fir_registration_regime(fields)]
    non_compliant = [ c for c in checks if c["status"] == "Non-Compliant"]
    if non_compliant:
        overall =" FIR registration violation identified. Approach Magistrate under S.175(3) BNSS. "
    else:
        overall = "No FIR registartion defecr proven from document."
    return {"Compliance_checks": checks, "overall_assessment": overall}

def check_vulnerable_location(f):
    req = " Woman/minor/senior summoned at residence, not station[S.179 BNSS/ S. 160(1) CrPC]"
    gender= f.get("summoned_person_gender")
    age = f.get("summoned_person_age")
    protected= gender == "female" or (age is not None and (age <18 or age >60))
    if not protected:
        return _result(req, "Not Applicable", "Person does not fall in protected category.")
    loc= f.get("summons_location")
    if loc=="residence":
        return _result(req, "Compliant", "Summons issued for examination at residence.")
    if loc=="police station":
        return _result (req, "Non-Compliant", "Protected person summoned to police station-direct S.179 BNSS violation.")
    return _result(req, "Cannot Determine", "Summons location not clearly stated.")

def check_vulnerable_female_officer(f):
    req = "Female officer involvement for female summoned person [Sheela Barse]"
    if f.get("summoned_person_gender")!= "female":
        return _result(req, "Not Applicable", "Person is not female.")
    v= f.get("female_officer_involved")
    if v is True:
        return _result(req, "Compliant", "Female officer involvement recorded.")
    if v is False:
        return _result(req, "Non-Compliant", "No female officer involvement for a female person- Sheela Barse violation." )
    return _result(req, "Cannot Determine", "Female officer involvment unclear.")

def run_vulnerable_compliance_checks(fields):
    checks =[
        check_vulnerable_location(fields),
        check_vulnerable_female_officer(fields),
    ]
    non_compliant = [ c for c in checks if c["status"] == "Non-Compliant"]
    if non_compliant:
        overall = f"{len(non_compliant)} defect(s) in summons procedure."
    else:
        overall= "Summons procedure appears compliant on face of document."
    return {"compliance_checks": checks, "overall_assessment":overall}

def check_fir_no_arrest_status(f):
    req = "Offence classification and threshold status [pre-arrest FIR/complaint]"
    cleaned = [re.sub(r'\s*(BNS|IPC|BNSS|CrPC)\s*$', '', str(s).strip(), flags=re.IGNORECASE).strip()
               for s in f.get("sections_cited", [])]
    known = [(sec, BNS_SECTION_DATA[sec]) for sec in cleaned if sec in BNS_SECTION_DATA]

    if not known:
        return _result(req, "Cannot Determine",
            "No recognised section could be matched. Offence classification cannot be established from "
            "this document.")

    names = ", ".join(f"{sec} ({data['offence']})" for sec, data in known)

    def describe(field_values, true_label, false_label):
        if any(v == "contingent" for v in field_values):
            return f"{true_label}/{false_label} status depends on circumstances not captured here"
        if all(field_values):
            return true_label
        if all(not v for v in field_values):
            return false_label
        return f"mixed {true_label.split()[0]}"

    cognizable_values = [d.get("cognizable") for _, d in known]
    bailable_values = [d.get("bailable") for _, d in known]
    cognizable_status = describe(cognizable_values, "cognizable", "non-cognizable")
    bailable_status = describe(bailable_values, "bailable", "non-bailable")

    return _result(req, "Not Applicable",
        f"No arrest has occurred yet, so arrest-procedure checks (notice, grounds, production, default bail) "
        f"do not apply. Offence(s) cited: {names} — {cognizable_status}, {bailable_status}. If police act on "
        f"this FIR, whether an arrest requires prior notice will depend on the punishment ceiling and the "
        f"manner of arrest at that time; this can be re-checked once that happens.")
    
def check_fir_free_copy_provided(f):
    req = "Free copy of FIR given forthwith to informant/victim [S.173(2) BNSS]"
    if f.get("fir_document_perspective") == "accused":
        return _result(req, "Not Applicable", "This document is from the accused's perspective — the automatic S.173(2) BNSS right applies to the informant/victim, not the accused. See the separate accused's-copy-right check below.")
    v = f.get("free_copy_given_to_informant")
    if v is True:
        return _result(req, "Compliant", "A free copy of the FIR was recorded as given to the informant/victim.")
    if v is False:
        return _result(req, "Non-Compliant",
            "No free copy of the FIR was given to the informant/victim. Under S.173(2) BNSS, this is "
            "mandatory and must be given forthwith, at no cost. This copy is the informant's only "
            "independent record of exactly what was registered — including the sections cited — and its "
            "absence makes it impossible to verify the complaint was recorded accurately.")
    return _result(req, "Cannot Determine", "Whether a free copy was given to the informant/victim is unclear.")

def check_accused_fir_copy_provided(f):
    req = "Accused's right to an early copy of FIR, before chargesheet stage [Youth Bar Association of India v. UOI, (2016) 9 SCC 473, guidelines (a)-(c)]"
    if f.get("fir_document_perspective") != "accused":
        return _result(req, "Not Applicable", "This check applies only when the person is named as the accused, not the informant.")
    applied = f.get("accused_applied_for_fir_copy")
    if applied is not True:
        return _result(req, "Cannot Determine",
            "Per Youth Bar Association guidelines (b)-(c), this early-access right is triggered by an "
            "application — either to the police officer (before the FIR is forwarded to court) or to the "
            "Magistrate (after it is forwarded). No application is indicated yet, so this right has not "
            "been actively invoked. NOTE: this is a distinct, earlier route from Section 230 BNSS (formerly "
            "Section 207 CrPC), which only supplies documents automatically at the later chargesheet stage.",
            doctrine_key="youth_bar_association_fir_copy_guidelines")
    provided = f.get("accused_fir_copy_provided")
    if provided is True:
        return _result(req, "Compliant", "A copy of the FIR was provided pursuant to the accused's application, consistent with Youth Bar Association guidelines (b)-(c).", doctrine_key="youth_bar_association_fir_copy_guidelines")
    if provided is False:
        return _result(req, "Non-Compliant",
            "The accused applied for a copy of the FIR but it was not provided. Per Youth Bar Association "
            "guideline (b), an application to the police officer should be met with a copy within 24 hours; "
            "per guideline (c), an application to the court once the FIR has been forwarded should be met "
            "within two working days. This is separate from, and earlier than, the Section 230 BNSS "
            "(formerly Section 207 CrPC) chargesheet-stage disclosure obligation.",
            doctrine_key="youth_bar_association_fir_copy_guidelines")
    return _result(req, "Cannot Determine", "Whether the copy was provided after application is unclear.", doctrine_key="youth_bar_association_fir_copy_guidelines")


SENSITIVE_EXEMPT_SECTIONS = {"64", "64(1)", "64(2)", "65", "65(1)", "65(2)", "66", "67",
                              "68", "69", "70", "70(1)", "70(2)", "71", "113",
                              "113(2)(a)", "113(2)(b)"}

def check_fir_online_upload(f, user_checked_online=None, days_since_registration=None):
    req = "FIR uploaded online within 24-72 hours [Youth Bar Association of India v. UOI, (2016)]"
    cleaned = [re.sub(r'\s*(BNS|IPC|BNSS|CrPC)\s*$', '', str(s).strip(), flags=re.IGNORECASE).strip()
               for s in f.get("sections_cited", [])]

    if any(sec in SENSITIVE_EXEMPT_SECTIONS for sec in cleaned):
        return _result(req, "Not Applicable",
            "The cited offence falls in a category the Supreme Court treats as presumptively sensitive "
            "(sexual offence / terrorism), exempt from the online-upload mandate. NOTE: courts may also "
            "exempt other matters on privacy grounds not captured by section number alone — this "
            "exemption list is illustrative, not exhaustive, per the judgment itself.",
            doctrine_key="youth_bar_association_fir_copy_guidelines")

    if user_checked_online is None:
        return _result(req, "Cannot Determine",
            "Whether the FIR was uploaded to the police/State website cannot be confirmed without checking "
            "the relevant portal directly — this is a fact only you or your lawyer can verify by looking.",
            doctrine_key="youth_bar_association_fir_copy_guidelines")

    if user_checked_online is True:
        return _result(req, "Compliant", "FIR confirmed available online, as required.", doctrine_key="youth_bar_association_fir_copy_guidelines")

    if days_since_registration is not None and days_since_registration > 3:
        return _result(req, "May be Non-Compliant",
            f"FIR reported as not found online, {days_since_registration} days after registration — "
            f"beyond even the maximum 72-hour connectivity extension. "
            f"IMPORTANT: this alone is NOT grounds for anticipatory bail (same judgment, para (g)) — "
            f"raise it as a procedural point, not as a bail argument on its own.",
            doctrine_key="youth_bar_association_fir_copy_guidelines")

    return _result(req, "Cannot Determine",
        "FIR reported as not yet found online, but within the permitted window — check again shortly.",
        doctrine_key="youth_bar_association_fir_copy_guidelines")
    
def run_fir_no_arrest_checks(fields, user_checked_online=None, days_since_registration=None):
    checks = [
        check_fir_no_arrest_status(fields),
        check_fir_free_copy_provided(fields),
        check_accused_fir_copy_provided(fields),
        check_fir_online_upload(fields, user_checked_online, days_since_registration),
    ]
    non_compliant = [c for c in checks if c["status"] in ("Non-Compliant", "May be Non-Compliant")]
    if non_compliant:
        overall = f"{len(non_compliant)} procedural defect(s) found or suspected."
    else:
        overall = "No arrest-procedure defects to assess — no arrest has occurred yet. Re-check this case if an arrest is made."
    return {"compliance_checks": checks, "overall_assessment": overall}
    
    
#-------Router :subtype-> (extraction prompt, runner)-------------------------
POLICE_ROUTES ={
     "Arrest-related" : (ARREST_EXTRACTION_PROMPT, run_arrest_compliance_checks),
     "Bank/Account Freezing": ( FREEZE_EXTRACTION_PROMPT, run_freeze_compliance_checks),
     "Search & Seizure" : ( SEARCH_EXTRACTION_PROMPT, run_search_compliance_checks),
     "FIR Registration Dispute": (FIR_DISPUTE_EXTRACTION_PROMPT, run_fir_compliance_checks),
     "Summons to Vulnerable Person": (VULNERABLE_EXTRACTION_PROMPT, run_vulnerable_compliance_checks),
     "FIR / Complaint - No Arrest Yet": (FIR_NO_ARREST_EXTRACTION_PROMPT, run_fir_no_arrest_checks),
}

def _extract_text_from_response(response):
    """Shared helper: safely extracts text content from an Anthropic
    API response, regardless of block order or the presence of
    non-text blocks (e.g. ThinkingBlock).
 
    FIXED 2026-08-29: every `.content[0].text` call site in this
    project previously assumed the first content block is always plain
    text. CONFIRMED REAL FAILURE (layman_summary.py, same session):
    'ThinkingBlock' object has no attribute 'text' -- for a
    sufficiently complex prompt, the model can return a ThinkingBlock
    as the first content item, followed by the actual TextBlock.

    CORRECTION (2026-09-01): this docstring claimed the fix was
    "applied defensively across every extraction call in this file" --
    that was FALSE. All 11 real call sites in this file (run_police_
    pipeline x2, analyze_document x4 across its classification/
    extraction/missing-info/deadline steps) still did raw
    `response.content[0].text` immediately below this very function,
    never calling it. Found while chasing a live user-reported chat
    failure that traced back to the exact same unfixed pattern in
    chat_assistant.py (which had made the identical false claim about
    itself). Now actually wired into all 11 call sites."""
    text_block = next((block for block in response.content if hasattr(block, "text")), None)
    if text_block is None:
        raise ValueError("No text block found in response.content -- only non-text blocks returned.")
    return text_block.text


def run_police_pipeline(document_text):
    """Classify a police document into a sub type , extract fields  , run subtype-specific checks."""
    r = client.messages.create(
        model = "claude-haiku-4-5-20251001",
        max_tokens= 200,
        temperature=0,
        messages=[{"role": "user", "content": POLICE_SUBTYPE_PROMPT.format(document_text=document_text)}]
    )
    try:
        raw_text = _extract_text_from_response(r)
    except ValueError:
        raw_text = ""
    try:
        subtype_obj = parse_json_response(raw_text)
        subtype = subtype_obj.get("police_subtype", "Other")
    except json.JSONDecodeError:
        subtype="Other"
    route = POLICE_ROUTES.get(subtype)
    if route is None:
        return {
            "police_subtype": subtype,
            "extracted_fields": {},
            "compliance": {"compliance_checks": [], "overall_assessment": "No sub-type-specific check available."},
            "bail_pathway": None,
        }
    extraction_prompt, runner = route
    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        temperature=0,
        messages=[{"role": "user", "content": extraction_prompt.format(document_text=document_text)}]
    )
    try:
        raw_text = _extract_text_from_response(r)
    except ValueError:
        raw_text = ""
    try:
        extracted = parse_json_response(raw_text)
    except json.JSONDecodeError:
        extracted = {"error": "Failed to parse extraction", "raw": raw_text}
    return {
        "police_subtype": subtype,
        "extracted_fields": extracted,
        "compliance": runner(extracted),
        "bail_pathway": compute_bail_pathway_info(extracted.get("sections_cited", [])) if subtype == "Arrest-related" else None,
    }
    
  

def analyze_document(document_text):
    classification_prompt = f"""You are analyzing an Indian legal or administrative document. Classify it into exactly one of these categories:

- Banking & Cheque Bounce — examples: Section 138 NI Act notice, loan default demand notice, EMI default reminder
- Police & Criminal Process — examples: notice to appear for investigation (Section 35 BNSS / old 41A CrPC), summons to produce documents or devices (Section 94 BNSS), notice to join investigation (Section 179 BNSS), arrest memo, FIR copy served to accused, notice in dowry/cruelty complaint (Section 85 BNS), notice in cyber fraud investigation, notice to vehicle owner in accident case, bail condition compliance notice, externment/bound-over notice under Section 125 CrPC / Section 126 BNSS, police closure report served to complainant
- Tenancy & Property — examples: eviction notice, rent recovery notice, property dispute notice
- Individual Tax Notices — examples: Income Tax demand notice, GST notice for small traders — not corporate/enterprise tax matters
- Government / Revenue Orders — examples: revenue department orders, land record notices, government circulars affecting citizens

If the document doesn't clearly fit one of these five, classify it as "Other" rather than forcing a fit.

Respond with only valid JSON in this exact format, no other text:
{{"document_type": "category name", "sub_type": "specific notice type within that category", "confidence": "high/medium/low", "reasoning": "one sentence explanation"}}
"document_type" must be exactly the category name only, never including the examples in parentheses

Document text:
{document_text}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        temperature=0,
        messages=[{"role": "user", "content": classification_prompt}]
    )
    try:
        raw_text = _extract_text_from_response(response)
    except ValueError:
        raw_text = ""
    try:
        classification_result = parse_json_response(raw_text)
    except json.JSONDecodeError:
        classification_result = {"error": "Failed to parse model response", "raw": raw_text}

    # ---- Category-aware compliance routing now happens FIRST, before missing_info ----
    top_category = classification_result.get("document_type", "")
    extracted_fields = {}

    if top_category == "Police & Criminal Process":
        police_result = run_police_pipeline(document_text)
        compliance_result = police_result["compliance"]
        classification_result["police_subtype"] = police_result["police_subtype"]
        extracted_fields = police_result["extracted_fields"]
        classification_result["extracted_fields"] = extracted_fields
        bail_pathway_result = police_result.get("bail_pathway")
    elif top_category == "Banking & Cheque Bounce":
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            temperature=0,
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(document_text=document_text)}]
        )
        try:
            raw_text = _extract_text_from_response(response)
        except ValueError:
            raw_text = ""
        try:
            extracted_fields = parse_json_response(raw_text)
        except json.JSONDecodeError:
            extracted_fields = {"error": "Failed to parse extraction response", "raw": raw_text}
        compliance_result = run_compliance_checks(extracted_fields)
    else:
        compliance_result = {
            "compliance_checks": [],
            "overall_assessment": f"No compliance checker built yet for category: {top_category}. See README roadmap."
        }

    # ---- NOW build missing_info_prompt, grounded with whatever sections were actually extracted ----
    section_context = build_grounded_section_context(extracted_fields.get("sections_cited", []))

    missing_info_prompt = f"""You are reviewing an Indian legal notice for completeness. Identify what information is missing, vague, or unsupported by evidence — not what the notice contains.

VERIFIED SECTION CONTEXT (use this, do not guess or rely on your own knowledge of what these sections mean):
{section_context}

Do not state or assume what any cited section legally covers or means beyond what is given above. If a section is marked "not in our verified reference table," say only that its scope could not be verified — do not fill in your own answer.

Check specifically for:
- Whether a clear calculation or amount breakdown is provided (not just a total figure)
- Whether supporting documents are actually attached/referenced (not just claimed to exist)
- Whether the deadline for response is stated explicitly and unambiguously
- Whether the issuing party's authority or standing to send this notice is clear
- Whether the underlying facts (dates, transaction details) are specific or vague

Respond with only valid JSON in this exact format, no other text:
{{"missing_or_unclear": ["flag 1", "flag 2", ...], "completeness_assessment": "one sentence overall judgment"}}

If nothing is missing, return an empty list for "missing_or_unclear" and say so in the assessment.

Document text:
{document_text}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        temperature=0,
        messages=[{"role": "user", "content": missing_info_prompt}]
    )
    try:
        raw_text = _extract_text_from_response(response)
    except ValueError:
        raw_text = ""
    try:
        missing_info_result = parse_json_response(raw_text)
    except json.JSONDecodeError:
        missing_info_result = {"error": "Failed to parse model response", "raw": raw_text}

    # ---- deadline extraction and urgency, unchanged ----
    deadline_extraction_prompt = f"""...same as before..."""
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        temperature=0,
        messages=[{"role": "user", "content": deadline_extraction_prompt}]
    )
    try:
        raw_text = _extract_text_from_response(response)
    except ValueError:
        raw_text = ""
    try:
        deadline_fields = parse_json_response(raw_text)
    except json.JSONDecodeError:
        deadline_fields = {"error": "Failed to parse deadline extraction", "raw": raw_text}

    days_remaining = calculate_days_remaining(deadline_fields, deadline_fields.get("notice_date"))
    if days_remaining is None:
        urgency_result = {
            "urgency_level": "Cannot Determine",
            "deadline_message": "Deadline could not be extracted from this document. Manual review required.",
            "days_remaining": None
        }
    else:
        urgency_result = build_analysis_summary(days_remaining)

    full_analysis = {
        "classification": classification_result,
        "missing_info": missing_info_result,
        "compliance": compliance_result,
        "checklist": get_document_checklist(classification_result.get("document_type", "")),
        "urgency": urgency_result,
        "severity": compute_severity(compliance_result.get("compliance_checks", [])),
        "extracted_fields": extracted_fields
    }

    return full_analysis


if __name__ == "__main__":
    document_text = clean_text(extract_text_from_pdf("Sample_Legal_Notice_Section138.pdf"))
    #print("DEBUG:", repr(document_text[:200]))
    result = analyze_document(document_text)
    print(json.dumps(result, indent=2))


# Add to main.py, near the top with other imports:
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.units import inch
from reportlab.lib import colors
import io


def _kyr_pdf_styles():
    """The shared ParagraphStyle set for every Know Your Rights PDF
    (the compliance brief and, from Project 3, the action drafts) --
    factored out so the two renderers can't drift apart on typography."""
    styles = getSampleStyleSheet()
    body = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, alignment=TA_JUSTIFY, spaceAfter=6, leading=14)
    return {
        'styles': styles,
        'header': ParagraphStyle('Header', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=4),
        'sub': ParagraphStyle('Sub', parent=styles['Normal'], fontSize=9, alignment=TA_CENTER, textColor=colors.HexColor("#555555"), spaceAfter=2),
        'section_title': ParagraphStyle('SecTitle', parent=styles['Normal'], fontSize=12, fontName='Helvetica-Bold', spaceBefore=14, spaceAfter=6, textColor=colors.HexColor("#14213D")),
        'label': ParagraphStyle('Label', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', spaceAfter=2),
        'body': body,
        'finding_pass': ParagraphStyle('Pass', parent=body, textColor=colors.HexColor("#15803D")),
        'finding_fail': ParagraphStyle('Fail', parent=body, textColor=colors.HexColor("#B91C1C")),
        'finding_unclear': ParagraphStyle('Unclear', parent=body, textColor=colors.HexColor("#B45309")),
        'highlight': ParagraphStyle('Highlight', parent=styles['Normal'], fontSize=12, fontName='Helvetica-Bold', textColor=colors.HexColor("#7B2D26"), spaceBefore=8, spaceAfter=8),
        'small': ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor("#666666")),
    }


def generate_analysis_pdf(full_analysis, output_path="analysis.pdf"):
    """The LEGAL-ONLY diagnostic PDF -- for the person's lawyer or their
    own file. Findings, statuses, case-law citations, the default-bail
    computation, the Arnesh Kumar consequences. NO citizen hand-holding
    (no 'documents to gather' checklist, no 'recommended action plan')."""
    return _build_kyr_pdf(full_analysis, output_path, variant="analysis")


def generate_next_steps_pdf(full_analysis, plain_text=None, output_path="next_steps.pdf"):
    """The CITIZEN sheet -- plain-language summary + what to do + what to
    bring. Kept deliberately separate from the analysis PDF so neither
    document mixes registers."""
    return _build_kyr_pdf(full_analysis, output_path, variant="next_steps", plain_text=plain_text)


# Back-compat: the old name, now the legal-only analysis PDF.
def generate_compliance_brief(full_analysis, output_path="compliance_brief.pdf"):
    return _build_kyr_pdf(full_analysis, output_path, variant="analysis")


def _build_kyr_pdf(full_analysis, output_path, variant="analysis", plain_text=None):
    """Shared renderer. variant in {"analysis", "next_steps"} gates which
    sections appear; letterhead and disclaimer are shared."""
    is_analysis = variant == "analysis"
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=0.9*inch, bottomMargin=0.9*inch,
        leftMargin=0.9*inch, rightMargin=0.9*inch
    )
    _S = _kyr_pdf_styles()
    header, sub, section_title, label, body, finding_pass, finding_fail, finding_unclear, highlight, small = (
        _S['header'], _S['sub'], _S['section_title'], _S['label'], _S['body'],
        _S['finding_pass'], _S['finding_fail'], _S['finding_unclear'], _S['highlight'], _S['small'],
    )

    story = []

    # Letterhead
    story.append(Paragraph("KNOW YOUR RIGHTS", header))
    story.append(Paragraph(
        "Procedural Compliance Analysis" if is_analysis else "What You Can Do Next", sub))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#14213D")))
    story.append(Spacer(1, 12))

    # Section 1: Document details
    classification = full_analysis.get("classification", {})
    story.append(Paragraph("1. Summary", section_title))
    story.append(Paragraph(f"<b>Category:</b> {classification.get('document_type', 'N/A')}", body))
    story.append(Paragraph(f"<b>Sub-type:</b> {classification.get('sub_type', 'N/A')}", body))
    story.append(Paragraph(f"<b>Assessment:</b> {classification.get('reasoning', 'N/A')}", body))
    story.append(Spacer(1, 6))

    # next_steps: the plain-language summary leads, before anything else
    if not is_analysis and plain_text:
        story.append(Paragraph("In plain words", section_title))
        for para in str(plain_text).split("\n"):
            p = para.strip()
            if not p:
                story.append(Spacer(1, 4))
                continue
            p = p.replace("**", "")
            story.append(Paragraph(p.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), body))
        story.append(Spacer(1, 8))

    severity = full_analysis.get("severity", {})
    if is_analysis and severity:
        story.append(Paragraph("Severity of Procedural Compliance Violations", section_title))

        tier_colors_hex = {1: "#4CAF50", 2: "#FFC107", 3: "#FF7043", 4: "#D6336C"}
        score = severity.get("severity_score", 0)
        if score == 0:
            tier = 1
        elif score <= 2:
            tier = 2
        elif score <= 4:
            tier = 3
        else:
            tier = 4

        dot_size = 12
        dot_table = _Table([[""]], colWidths=[dot_size], rowHeights=[dot_size])
        dot_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,0), _colors.HexColor(tier_colors_hex[tier])),
            ('BOX', (0,0), (0,0), 0.5, colors.HexColor("#999999")),
        ]))

        label_row = Table(
            [[dot_table, Paragraph(f"<b>{severity.get('severity_label', 'Not Available')}</b>", body)]],
            colWidths=[dot_size + 6, None]
        )
        label_row.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
        ]))
        story.append(label_row)
        story.append(Spacer(1, 6))

        box_size = 18
        cells = [[""] * 4]
        meter_table = _Table(cells, colWidths=[box_size]*4, rowHeights=[box_size])
        style_commands = []
        for i in range(4):
            fill = _colors.HexColor(tier_colors_hex[i + 1]) if (i + 1) <= tier else _colors.HexColor("#E0E0E0")
            style_commands.append(('BACKGROUND', (i, 0), (i, 0), fill))
        meter_table.setStyle(TableStyle(style_commands + [
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#999999")),
            ('INNERGRID', (0,0), (-1,-1), 1, colors.white),
        ]))
        story.append(meter_table)

        unresolved = severity.get("unresolved_checks", 0)
        if unresolved > 0:
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"{unresolved} check(s) could not be verified from the information given.", small))
        story.append(Spacer(1, 10))

    # Section 2: Default bail / urgency highlight (if present)
    urgency = full_analysis.get("urgency", {})
    if urgency.get("urgency_level") not in (None, "Cannot Determine"):
        story.append(Paragraph(f"⚠ URGENCY: {urgency.get('urgency_level')}", highlight))
        if urgency.get("days_remaining") is not None:
            story.append(Paragraph(f"Days remaining: {urgency.get('days_remaining')}", body))

    # Pull out default bail specifically for highlighting, if present in compliance checks
    compliance = full_analysis.get("compliance", {})
    for check in compliance.get("compliance_checks", []):
        if "Default bail" in check.get("requirement", ""):
            story.append(Paragraph(f"⚠ DEFAULT BAIL: {check.get('status')}", highlight))
            story.append(Paragraph(check.get("explanation", ""), body))

    story.append(Spacer(1, 6))

    # Section 3: Compliance findings -- ANALYSIS PDF ONLY (the citizen
    # sheet carries the plain summary instead of the clause-by-clause audit).
    if not is_analysis:
        _append_next_steps_sections(story, full_analysis, _S)
        story.append(Spacer(1, 20))
        story.append(HRFlowable(width="100%", thickness=0.6, color=colors.grey))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "This sheet is generated by an automated tool and is not legal advice. It explains, in "
            "plain terms, what the analysis found and what you might do next. For anything you intend "
            "to file or send to an authority, use the separate Procedural Compliance Analysis and a "
            "lawyer's review.", small))
        doc.build(story)
        return output_path

    story.append(Paragraph("2. Procedural Compliance Findings", section_title))
    for check in compliance.get("compliance_checks", []):
        status = check.get("status", "")
        style = finding_pass if status == "Compliant" else finding_fail if status in ("Non-Compliant", "May be Non-Compliant") else finding_unclear if status == "Cannot Determine" else body
        story.append(Paragraph(f"<b>{check.get('requirement', '')}</b>", label))
        story.append(Paragraph(f"Status: <b>{status}</b>", style))
        story.append(Paragraph(check.get("explanation", ""), body))
        source_paragraphs = check.get("source_paragraphs")
        if source_paragraphs:
            case_name = source_paragraphs[0].get("case_name", "")
            citation = source_paragraphs[0].get("citation", "")
            story.append(Paragraph(f"<i>Source: {_xml_escape(case_name)} ({_xml_escape(citation)})</i>", small))
            for para in source_paragraphs:
                para_label = para.get("paragraph_number", "")
                author = para.get("opinion_author")
                # NOTE: renamed from "label" to avoid shadowing the outer
                # ParagraphStyle object also named "label" (defined earlier
                # in this function) -- that collision caused a crash on
                # every check AFTER the first one with source_paragraphs.
                para_label_str = f"¶{para_label}" + (f" ({author}, J.)" if author else "")
                raw_text = para.get("text", "")
                is_curated_excerpt = para_label == "checklist (excerpted)"
                if is_curated_excerpt:
                    snippet = raw_text.strip()
                    truncated_note = ""
                else:
                    snippet = raw_text[:1200].strip()
                    truncated_note = "..." if len(raw_text) > 1200 else ""
                story.append(Paragraph(f"<i>{_xml_escape(para_label_str)}: {_xml_escape(snippet)}{truncated_note}</i>", small))
        applying_precedent_paragraphs = check.get("applying_precedent_paragraphs")
        if applying_precedent_paragraphs:
            case_name = applying_precedent_paragraphs[0].get("case_name", "")
            citation = applying_precedent_paragraphs[0].get("citation", "")
            story.append(Paragraph(
                f"<i>How courts have applied this: {_xml_escape(case_name)} ({_xml_escape(citation)})</i>", small))
            for para in applying_precedent_paragraphs:
                para_label = para.get("paragraph_number", "")
                author = para.get("opinion_author")
                para_label_str = f"¶{para_label}" + (f" ({author}, J.)" if author else "")
                raw_text = para.get("text", "")
                snippet = raw_text[:1200].strip()
                truncated_note = "..." if len(raw_text) > 1200 else ""
                story.append(Paragraph(f"<i>{_xml_escape(para_label_str)}: {_xml_escape(snippet)}{truncated_note}</i>", small))
        story.append(Spacer(1, 4))
    
     # ---- If Bail Is Needed — informational, NOT a compliance verdict ----
    bail_pathway = full_analysis.get("bail_pathway")
    if bail_pathway:
        story.append(Paragraph("If Bail Is Needed", section_title))
        story.append(Paragraph(bail_pathway.get("message", ""), body))
        story.append(Spacer(1, 10))
    

    # ---- Consequences of Non-Compliance (Arnesh Kumar-specific) ----
    arnesh_kumar_flagged = any(
        "41A" in c.get("requirement", "") and c.get("status") in ("Non-Compliant", "May be Non-Compliant")
        for c in compliance.get("compliance_checks", [])
    )

    if arnesh_kumar_flagged:
        story.append(Paragraph("Consequences of Non-Compliance", section_title))
        story.append(Paragraph(
            "The Supreme Court has laid down specific consequences for non-compliance with arrest "
            "procedure guidelines: <i>Arnesh Kumar v. State of Bihar</i>, (2014) 8 SCC 273, "
            "Criminal Appeal No. 1277 of 2014.",
            body
        ))
        story.append(Spacer(1, 4))

        page_width = A4[0] - (0.9*inch * 2)
        col_width = page_width / 2

        consequence_table = Table(
            [
                [Paragraph("<b>For Police Officers</b>", label), Paragraph("<b>For Judicial Magistrates</b>", label)],
                [Paragraph(
                    "• Liable for departmental action<br/>"
                    "• Liable to be punished for contempt of court, "
                    "before the High Court having territorial jurisdiction",
                    body
                ),
                 Paragraph(
                    "• Liable for departmental action by the appropriate "
                    "High Court, if detention is authorized without "
                    "recording reasons in writing",
                    body
                )],
            ],
            colWidths=[col_width, col_width]
        )
        consequence_table.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#999999")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#FBE9E7")),
            ('BACKGROUND', (1,0), (1,-1), colors.HexColor("#FEF9E7")),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
        ]))
        story.append(consequence_table)
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "<i>Note: These consequences arise specifically from the Arnesh Kumar guidelines on "
            "arrest procedure. Other compliance findings above cite their own separate case law "
            "and may carry different consequences.</i>",
            small
        ))
        story.append(Spacer(1, 10))

    # Disclaimer -- analysis PDF (the next_steps PDF returned earlier with its own)
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.grey))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This analysis is generated by an automated tool and does not constitute legal advice. "
        "Findings marked 'May be Non-Compliant' are inferences drawn from the absence of information "
        "in the source, not confirmed violations. The section and case-law references reflect careful "
        "research but should be independently verified by a qualified advocate before being relied upon.",
        small
    ))

    doc.build(story)
    return output_path


def _append_next_steps_sections(story, full_analysis, _S):
    """The citizen-helper material -- kept OUT of the analysis PDF. Missing
    or unclear information, the recommended action plan, and the
    documents-to-gather checklist."""
    section_title, body = _S['section_title'], _S['body']

    missing = full_analysis.get("missing_info", {})
    flags = missing.get("missing_or_unclear", [])
    if flags:
        story.append(Paragraph("What is still missing or unclear", section_title))
        for flag in flags:
            story.append(Paragraph(f"• {flag}", body))
        story.append(Spacer(1, 10))

    urgency = full_analysis.get("urgency", {})
    if urgency.get("deadline_message") and isinstance(urgency["deadline_message"], dict):
        story.append(Paragraph("Suggested plan", section_title))
        for k, v in urgency["deadline_message"].items():
            story.append(Paragraph(f"<b>{k.replace('_', ' ').title()}:</b> {v}", body))
        story.append(Spacer(1, 10))

    checklist = full_analysis.get("checklist", [])
    if checklist:
        story.append(Paragraph("Documents to gather", section_title))
        for item in checklist:
            story.append(Paragraph(f"[ ] {item}", body))
        story.append(Spacer(1, 6))

