"""
judgment_court_facts.py -- a single, human-verified "which court decided
this" fact for every real judgment in the whole corpus (chunks/*.json,
minus the 3 chunk files that are actually full statute text: BNS, BNSS,
and the IT Act).

WHY THIS EXISTS
---------------
Built 2026-09-15, the same day chat_assistant._find_court_misattributions
was added, after that check first shipped covering only the 13 judgment
anchors curated for the domestic_violence/cheque_bounce/freeze inline
domains -- a real, narrow scope, since those were the only ones a human
had explicitly recorded a court for. The much larger general arrest/FIR
corpus (used on nearly every ordinary question this tool answers) had NO
court-attribution protection at all. This file closes that gap: every
one of the corpus's 46 real judgments now has a verified court fact, not
just the 13 that happened to have a curated doctrine-map anchor.

HOW EACH FACT WAS VERIFIED (2026-09-15) -- in order of preference:
1. The judgment's own stored caption/preamble text (e.g. "IN THE HIGH
   COURT OF DELHI AT NEW DELHI" or "IN THE SUPREME COURT OF INDIA ...
   CRIMINAL APPELLATE JURISDICTION") -- the most direct evidence,
   available for most of the corpus's chunk files.
2. The judgment's own citation field, where the reporter format is
   court-specific and unambiguous: an "SCC" (Supreme Court Cases) or
   "SCC OnLine SC" citation, or a neutral citation prefixed "INSC"
   (the Supreme Court's own scheme), is ALWAYS a Supreme Court of India
   judgment -- no High Court is ever reported in SCC or cited INSC. A
   state High Court's own neutral-citation prefix (e.g. "KER" for
   Kerala, "BHC" for Bombay, "DHC" for Delhi) or an explicit "(X High
   Court, ...)" note already recorded in the citation field is equally
   reliable.
3. For a small remainder with neither a stored caption nor an
   unambiguous citation prefix (K.N. Mehra, Pyare Lal Bhargava),
   cross-checked against this project's own existing curated
   context_notes in judgment_doctrine_map.py, which already state "the
   Supreme Court held..." for both -- independently corroborating the
   citation-based inference rather than resting on it alone.

A case genuinely absent from this dict is simply never checked by
_find_court_misattributions -- see that function's docstring: no
guessing, no false positives from an unverified case.

SCOPE NOTE: this is a flat, hand-verified fact table, not a doctrine map
-- it carries no trigger logic and contributes no text to any answer by
itself. It exists purely as the ground truth
chat_assistant._known_case_courts() checks a generated answer against.
"""

# case_name (exactly as stored in that case's own chunks/*.json
# "case_name" field, and therefore exactly what a `matches` dict's
# case_name carries) -> the real court, human-verified 2026-09-15.
CASE_NAME_TO_COURT = {
    # ---- the 13 already curated in domestic_violence_doctrine_map.py /
    # cheque_bounce_doctrine_map.py / freeze_doctrine_map.py (each ALSO
    # carries its own "court" field, added the same day, as local
    # documentation for a curator reading that entry -- this file is the
    # single source of truth the actual check reads from) -----------------
    "Hiral P. Harsora v Kusum Narottamdas Harsora": "Supreme Court of India",
    "D. Velusamy v D. Patchaiammal": "Supreme Court of India",
    "Satish Chander Ahuja v Sneha Ahuja": "Supreme Court of India",
    "Indra Sarma v V.K.V. Sarma": "Supreme Court of India",
    "Prabha Tyagi v Kamlesh Devi": "Supreme Court of India",
    "S. Vanitha v Deputy Commissioner, Bengaluru Urban District": "Supreme Court of India",
    "Rangappa v Sri Mohan": "Supreme Court of India",
    "Bir Singh v Mukesh Kumar": "Supreme Court of India",
    "Prakash Chimanlal Sheth v Jagruti Keyur Rajpopat": "Supreme Court of India",
    "Damodar S. Prabhu v Sayed Babalal H": "Supreme Court of India",
    "State of Maharashtra v Tapas D. Neogy": "Supreme Court of India",
    "Malabar Gold and Diamond Limited v Union of India": "Delhi High Court",
    "Neelkanth Pharma Logistics Pvt. Ltd. v Union of India": "Delhi High Court",

    # ---- the 2 curated in ndps_doctrine_map.py (added 2026-09-25) --------
    "State of Punjab v Baldev Singh": "Supreme Court of India (Constitution Bench)",
    "Union of India v Md Nawaz Khan": "Supreme Court of India",
    "Tofan Singh v State of Tamil Nadu": "Supreme Court of India",
    "Union of India v Mohanlal": "Supreme Court of India",
    "Vijaysinh Chandubha Jadeja v State of Gujarat": "Supreme Court of India (Constitution Bench)",
    "Noor Aga v State of Punjab": "Supreme Court of India",

    # ---- the wider general arrest/FIR corpus (judgment_doctrine_map.py
    # and unanchored semantic-only judgments) -- verified 2026-09-15 -------
    "Arnesh Kumar v State of Bihar": "Supreme Court of India",
    "Bikramjit Singh v State of Punjab": "Supreme Court of India",
    "Deepa v S. Vijayalakshmi": "Madras High Court",  # citation: SCC OnLine Mad (MD) -- Madurai Bench
    "D.K. Basu v State of West Bengal": "Supreme Court of India",
    "Jatin Narendrabhai Sanghvi & Ors v State of Gujarat & Anr": "Gujarat High Court",
    "Johnson V.U. v State of Kerala": "Kerala High Court",
    "Kahkashan Kausar @ Sonam v State of Bihar": "Supreme Court of India",
    "Kaveri Plastics v Mahdoom Bawa Bahrudeen Noorul": "Supreme Court of India",
    "K.N. Mehra v State of Rajasthan": "Supreme Court of India",
    "L. Muruganantham v State of Tamil Nadu": "Supreme Court of India",
    "Lalita Kumari v Government of Uttar Pradesh": "Supreme Court of India",
    "Lata Singh v State of Uttar Pradesh": "Supreme Court of India",
    "Lokesh B.H v State of Karnataka": "Supreme Court of India",  # citation: 2026 INSC 784
    "M. Ravindran v Intelligence Officer, Directorate of Revenue Intelligence": "Supreme Court of India",
    "Mathai v State of Kerala": "Supreme Court of India",
    "Md. Ibrahim & Ors v State of Bihar & Anr": "Supreme Court of India",
    "National Legal Services Authority v Union of India": "Supreme Court of India",
    "Pankaj Bansal v Union of India": "Supreme Court of India",
    "Prabir Purkayastha v State (NCT of Delhi)": "Supreme Court of India",
    "Prakash Ranjan v State of Bihar": "Patna High Court",
    "Pyare Lal Bhargava v State of Rajasthan": "Supreme Court of India",
    "Rakesh Kumar Paul v State of Assam": "Supreme Court of India",
    "Rakhi Mitra and Anr v State of West Bengal": "Calcutta High Court",
    "Satender Kumar Antil v Central Bureau of Investigation (2026)": "Supreme Court of India",
    "Satishchandra Ratanlal Shah v State of Gujarat": "Supreme Court of India",
    "Shreya Singhal v Union of India": "Supreme Court of India",
    "Sri Manjunath M P v State of Karnataka": "Karnataka High Court",
    "T. Manikadan v State (NCT of Delhi) & Anr": "Delhi High Court",
    "Usha Chakraborty v State of West Bengal": "Supreme Court of India",
    "Vihaan Kumar v State of Haryana": "Supreme Court of India",
    "Vijay Kumar Ghai v State of West Bengal": "Supreme Court of India",
    "Viraj Chetan Shah v Union of India & Anr (& Connected Matters)": "Bombay High Court",
    "Youth Bar Association v Union of India": "Supreme Court of India",
}
