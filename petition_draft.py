"""
petition_draft.py

Turns a completed arrest-safeguard assessment (the fixed checklist, or an
uploaded arrest memo) into a draft High Court criminal petition -- cause
title, "IN THE MATTER OF" cascade, numbered SHOWETH paragraphs, GROUNDS,
PRAYER, INTERIM PRAYER, AFFIDAVIT, VERIFICATION and INDEX.

Everything is assembled deterministically. NO LLM. The tool supplies the
GROUNDS (one per safeguard the assessment marked "not followed"), the
matters-to-confirm paragraph, and the relief -- from the same findings
already shown to the person. Every fact the tool does not hold
(identities, FIR number, dates, addresses) is left as [ ___ ]. Every
judgment passage is flagged NOT INDEPENDENTLY VERIFIED unless it came
through as human-verified.

Public surface:
    from_checklist(question_text, evaluate_result, *, ...) -> str
    from_doc_check(question_text, doc_check_result, *, ...) -> str
    to_pdf(draft_text, output_path) -> output_path
"""

import re

# CIVIL-DISPUTE-DRESSED-AS-CRIMINAL case names: if the answer leaned on one
# of these, the petition should also ask for quashing, not just the arrest
# safeguards. Shared by recourse_app.py (website) and whatsapp_bot.py (the
# WhatsApp DRAFT command, added 2026-09-14) so one list decides both,
# rather than two copies drifting apart over time.
_CIVIL_DISPUTE_CASE_NAMES = ("Md. Ibrahim", "Bhajan Lal", "Vijay Kumar Ghai", "Usha Chakraborty",
                             "Satishchandra Ratanlal Shah")


def derive_draft_context(matches):
    """From a chat answer's `matches` list: (civil_dispute flag, offence
    BNS sections) -- the two pieces from_checklist()/from_doc_check() need
    beyond the checklist/doc-check result itself. civil_dispute=True means
    the answer leaned on the 'civil matter given criminal colour' line of
    cases."""
    matches = matches or []
    civil = any(any(c in (m.get("case_name") or "") for c in _CIVIL_DISPUTE_CASE_NAMES) for m in matches)
    secs, seen = [], set()
    for m in matches:
        sn = str(m.get("section_number") or "")
        act = str(m.get("act") or "")
        if sn and act.upper() == "BNS" and not m.get("case_name") and sn not in seen:
            seen.add(sn)
            secs.append(sn)
    return civil, secs[:4]


_NOT_VERIFIED = (
    "« The case-law statements above are from an automated search and are NOT "
    "INDEPENDENTLY VERIFIED. Read the judgment(s) named and confirm the holding with a "
    "lawyer before this ground is used. »"
)

def _header(note=""):
    base = (
        "RECOURSE -- DRAFT PETITION\n"
        "\n"
        "A starting point only. Complete every [ ___ ]. Check every ground against the\n"
        "record. The case citations in this draft are from an automated search -- check\n"
        "each one in the reported judgment, with a lawyer, before the draft is used or\n"
        "filed. This is not a filed document and is not legal advice.\n"
    )
    if note:
        base += "\n" + note.rstrip() + "\n"
    return base


_HEADER = _header(
    "Drafted in High Court form. Your advocate may instead move the same grounds as a\n"
    "bail application before the Court of Session, or as a representation at the next\n"
    "remand hearing -- the substance carries over."
)

_CLOSING_AVERMENTS = [
    "FOR THAT the continued custody causes irreparable prejudice to the arrested person "
    "and to those dependent on him, [ set out the specific hardship -- livelihood, "
    "dependants, health, education ], which no later order can undo.",
    "FOR THAT the Petitioner has not filed any other petition or application on the same "
    "cause of action before this Hon'ble Court or any other court or authority, and "
    "undertakes to disclose any such proceeding at once if it is instituted.",
    "FOR THAT unless the reliefs sought are granted the arrested person will continue to "
    "suffer detention contrary to law and the Petitioner will be left without remedy.",
    "FOR THAT the Petitioner craves leave to add to, alter or amend these grounds with "
    "the leave of this Hon'ble Court, and submits that this petition is made bona fide "
    "and in the interest of justice.",
]

_AFFIDAVIT_TEMPLATE = """AFFIDAVIT

I, [ deponent's name ], aged about [ __ ] years, [ relationship / role ], resident of
[ full address ], do solemnly affirm and state as follows:

1. I am the Petitioner / the person authorised by the Petitioner to affirm this
   affidavit, I am acquainted with the facts of the case, and I am competent to
   affirm it.

2. The statements in paragraphs 1 to {fact_para} of the accompanying petition are
   true to my own knowledge; the statements founded on the annexed records are
   believed by me to be true; and the grounds and submissions in paragraphs
   {first_ground} to {last_ground} are advanced on legal advice which I believe to
   be correct.

3. My contact number is [ ___ ] and my address for service is as stated above. I
   undertake to inform the Registry of this Hon'ble Court of any change during the
   pendency of these proceedings.


OATH / VERIFICATION

I affirm that the contents of this affidavit are true, that nothing material has
been concealed, and that no part of it is false.

Affirmed at [ place ] on this [ __ ] day of [ month ], 20[ __ ].

                                        _______________________________
                                        Signature of the Deponent

Identified by:                          Sworn before me:
_____________________                   _____________________
[ Advocate ]                            [ Oath Commissioner / Notary ]
"""

_INDEX_TEMPLATE = """INDEX

  Sl. No. | Particulars                                          | Page Nos.
  --------|------------------------------------------------------|----------
    1     | Criminal Petition                                    |  __ - __
    2     | Affidavit in support                                 |  __
    3     | ANNEXURE-I   : Copy of the First Information Report   |  __ - __
    4     | ANNEXURE-II  : Copy of the arrest memo [ if available]|  __ - __
    5     | ANNEXURE-III : Copy of the remand order dated [ ___ ] |  __ - __
    6     | ANNEXURE-IV  : Copy of the order rejecting bail       |  __ - __
    7     | [ further annexures as referred to in the petition ] |  __ - __

Filed by:  _______________________
           [ Advocate's name ]
           Counsel for the Petitioner
"""


# ---------------------------------------------------------------------------
# adapters -> a normalised list of grounds + a list of matters-to-confirm
# ---------------------------------------------------------------------------

def _sections_clause(offence_sections):
    if offence_sections:
        joined = ", ".join(str(s) for s in offence_sections)
        return f"Sections {joined} of the Bharatiya Nyaya Sanhita, 2023 -- confirm against the FIR"
    return "Sections [ ___ ] of the Bharatiya Nyaya Sanhita, 2023"


def from_checklist(question_text, evaluate_result, *, civil_dispute=False,
                   offence_sections=None):
    """evaluate_result: the dict returned by
    arrest_safeguard_checklist.evaluate()."""
    from arrest_safeguard_checklist import GROUND_LEADS

    rows = (evaluate_result or {}).get("rows", []) or []
    grounds, to_verify = [], []
    for r in rows:
        if r.get("bucket") == "bad":
            lead_title = GROUND_LEADS.get(r["id"], (r.get("question", ""), r.get("question", "")))
            grounds.append({
                "lead": lead_title[1],
                "finding": r.get("finding", ""),
                "section": r.get("section", ""),
                "cases": _split_cases(r.get("case", "")),
            })
        elif r.get("bucket") == "warn":
            title = GROUND_LEADS.get(r["id"], (r.get("question", ""),))[0]
            to_verify.append(f"{title}: {r.get('finding', '')}")

    band_label = (evaluate_result or {}).get("summary", {}).get("label", "")
    return _build(question_text, grounds, to_verify,
                  civil_dispute=civil_dispute, offence_sections=offence_sections,
                  band_label=band_label)


_DOC_REQ_TO_LEAD = [
    ("written grounds", "written_grounds"),
    ("grounds of arrest", "written_grounds"),
    ("notice before arrest", "notice_before_arrest"),
    ("35(3)", "notice_before_arrest"),
    ("41a", "notice_before_arrest"),
    ("family informed", "family_informed"),
    ("d.k basu", "family_informed"),
    ("d.k. basu", "family_informed"),
    ("medical", "medical_exam"),
    ("24 hour", "produced_24h"),
    ("magistrate within 24", "produced_24h"),
    ("night", "night_arrest_woman"),
    ("sunset", "night_arrest_woman"),
    ("female officer", "female_officer"),
    ("default bail", "default_bail"),
]


def from_doc_check(question_text, doc_check_result, *, civil_dispute=False,
                   offence_sections=None):
    """doc_check_result: the dict from recourse_upload.check_arrest_document
    (its 'checks' carry plain/status/bucket/explanation)."""
    from arrest_safeguard_checklist import GROUND_LEADS

    # recourse_upload buckets: bad = defect, warn = suspected defect,
    # unknown = "Cannot Determine". bad -> a ground; warn/unknown -> a
    # matter to confirm; ok/na -> not carried into the petition.
    checks = (doc_check_result or {}).get("checks", []) or []
    grounds, to_verify = [], []
    for c in checks:
        bucket = c.get("bucket")
        if bucket not in ("bad", "warn", "unknown"):
            continue
        text = (c.get("plain") or "").lower()
        sid = next((i for kw, i in _DOC_REQ_TO_LEAD if kw in text), None)
        lead_title = GROUND_LEADS.get(sid) if sid else None
        expl = (c.get("explanation") or "").strip()
        if bucket == "bad" and lead_title:
            grounds.append({
                "lead": lead_title[1],
                "finding": expl,
                "section": "",
                "cases": _extract_cases(expl),
            })
        elif lead_title:
            to_verify.append(f"{lead_title[0]}: {expl}")
        else:
            to_verify.append(f"{c.get('plain', 'A safeguard')}: {expl}")

    return _build(question_text, grounds, to_verify,
                  civil_dispute=civil_dispute, offence_sections=offence_sections,
                  band_label=(doc_check_result or {}).get("overall", ""))


def _split_cases(case_str):
    if not case_str:
        return []
    return [c.strip() for c in re.split(r";|\band\b", case_str) if c.strip()]


def _extract_cases(text):
    # "the Supreme Court in Vihaan Kumar held", "Per Arnesh Kumar (2014)"
    out = []
    for m in re.finditer(r"\b(?:in|per)\s+([A-Z][A-Za-z.\-]+(?:\s+[A-Z][A-Za-z.\-]+){0,3})", text):
        cand = m.group(1).strip(" .,")
        if len(cand) > 3 and cand not in out:
            out.append(cand)
    return out


# ---------------------------------------------------------------------------
# the builder
# ---------------------------------------------------------------------------

def _build(question_text, grounds, to_verify, *, civil_dispute, offence_sections,
           band_label):
    L = []
    add = L.append

    add(_HEADER)
    add("")
    add("DISTRICT: [ district ]")
    add("")
    add("IN THE HIGH COURT OF [ ___ ] AT [ ___ ]")
    add("[ Extraordinary Criminal / Constitutional Writ Jurisdiction -- retain the")
    add("  description your High Court's rules use ]")
    add("")
    add("CRIMINAL PETITION NO. ________ OF 20____")
    add("")
    add("Category: [ for the filing advocate ]      Code: [ for the filing advocate ]")
    add("")
    add("")
    add("To,")
    add("The Hon'ble the Chief Justice and Hon'ble Judges of the")
    add("High Court of [ ___ ] at [ ___ ].")
    add("")
    add("")

    # ---- IN THE MATTER OF cascade ----
    add("IN THE MATTER OF:")
    add("")
    relief_line = ("A petition under Article 226 of the Constitution of India read with "
                   "Section 528 of the Bharatiya Nagarik Suraksha Sanhita, 2023, for a "
                   "declaration that the arrest and continued custody of the person named "
                   "below are illegal and for his release")
    if civil_dispute:
        relief_line += (", and for quashing of the First Information Report described "
                        "below as an abuse of the process of law")
    add(relief_line + ".")
    add("")
    add("                              -AND-")
    add("")
    add("IN THE MATTER OF:")
    add("")
    add(f"First Information Report No. [ ___ ] dated [ ___ ], registered at Police Station")
    add(f"[ ___ ], District [ ___ ], under {_sections_clause(offence_sections)}; the arrest")
    add("of the said person on or about [ date / time ]; and his continued detention under")
    add("the remand order dated [ ___ ] passed by the Court of [ ___ ].")
    add("")
    add("                              -AND-")
    add("")
    add("IN THE MATTER OF:")
    add("")
    add("The arrest and continued custody of the said person in breach of Article 22(1)")
    add("and 22(2) of the Constitution of India and of the mandatory safeguards in the")
    add("Bharatiya Nagarik Suraksha Sanhita, 2023" +
        (", and the initiation of criminal proceedings upon a dispute that is, in"
         " substance, of a civil nature" if civil_dispute else "") + ".")
    add("")
    add("                              -AND-")
    add("")
    add("IN THE MATTER OF:")
    add("")
    add("[ full name ], aged about [ __ ] years, [ son / wife / etc. ] of [ ___ ],")
    add("resident of [ full address ],")
    add("        ... Petitioner")
    add("[ where the petition is moved by a relative because the detained person cannot")
    add("  himself approach this Court, add: \"the Petitioner is the [ relationship ] of")
    add("  the detained person and moves this Hon'ble Court as his next friend\" ]")
    add("")
    add("                            -Versus-")
    add("")
    add("1.  The State of [ ___ ], through the [ Public Prosecutor / Secretary, Home")
    add("    Department ], [ address ].")
    add("2.  The Superintendent of Police, [ district ], [ address ].")
    add("3.  The Officer-in-Charge, Police Station [ ___ ], [ address ].")
    add("4.  [ The Investigating Officer, by name and rank, if known ].")
    add("5.  [ The de facto complainant / informant, by name and address, if the FIR was")
    add("    lodged on a private complaint -- add as a respondent. ]")
    add("        ... Respondents")
    add("")
    add("")
    add("The humble petition of the Petitioner above-named")
    add("       MOST RESPECTFULLY SHOWETH:")
    add("")

    para = 0

    def numbered(text_lines):
        nonlocal para
        para += 1
        if isinstance(text_lines, str):
            text_lines = [text_lines]
        add(f"{para}.  {text_lines[0]}")
        for extra in text_lines[1:]:
            add(f"    {extra}")
        add("")

    numbered(
        "The Petitioner is [ identity and occupation ]. The person whose arrest is "
        "challenged is [ name ], the Petitioner's [ relationship ], aged about [ __ ] "
        "years, presently confined at [ jail / police custody ]. The Petitioner is "
        "competent to move this Court on his behalf and is directly aggrieved by the "
        "matters set out below.")

    q2 = ("This petition challenges the legality of the said person's arrest and "
          "continued custody and seeks his release")
    if civil_dispute:
        q2 += (", together with quashing of First Information Report No. [ ___ ] "
               "registered at Police Station [ ___ ],")
    q2 += " and interim protection pending disposal."
    numbered(q2)

    fact_para = para  # last non-ground para so far; background follows
    numbered([
        "[ BACKGROUND -- one numbered paragraph for each step, in sequence, each with "
        "its date and time. Begin from the account given below and complete every "
        "specific: ]",
        "",
        _seed_from_question(question_text),
        "",
        "[ continue: what was said at the time of arrest; who was present; what, if "
        "anything, was handed over in writing; when and how the family came to know; the "
        "date of first production before the Magistrate; the remand orders passed; any "
        "bail application moved and its outcome. ]",
    ])

    numbered([
        "A copy of the First Information Report is annexed and marked ANNEXURE-I. A copy "
        "of the arrest memo [ if furnished ] is annexed and marked ANNEXURE-II. A copy of "
        "the remand order dated [ ___ ] is annexed and marked ANNEXURE-III. A copy of the "
        "order [ if any ] rejecting bail is annexed and marked ANNEXURE-IV. [ Add further "
        "annexures -- medical report, notices, correspondence -- as referred to below. ]",
    ])
    fact_para = para

    # ---- GROUNDS ----
    add("GROUNDS")
    add("")
    add("    The Petitioner submits, without prejudice and in the alternative, as follows:")
    add("")
    first_ground = para + 1

    if grounds:
        for g in grounds:
            para += 1
            add(f"{para}.  FOR THAT {g['lead']}.")
            if g.get("section"):
                add(f"    This requirement is contained in {g['section']}.")
            for chunk in _wrap(g.get("finding", "")):
                add(f"    {chunk}")
            if g.get("cases"):
                add(f"    Reliance is placed on {', '.join(g['cases'])}.")
            add(f"    {_NOT_VERIFIED}")
            add("")
    else:
        para += 1
        add(f"{para}.  FOR THAT no specific procedural defect is asserted on the material "
            "available; this petition is made so that this Hon'ble Court may satisfy "
            "itself as to the legality of the arrest and the continued custody.")
        add("")

    if to_verify:
        para += 1
        add(f"{para}.  FOR THAT the following matters could not be confirmed from the "
            "information available and are stated for this Hon'ble Court's satisfaction; "
            "if the record bears any of them out, each is a further and independent "
            "ground:")
        for i, tv in enumerate(to_verify):
            add(f"    ({_roman_lower(i + 1)}) {_oneline(tv)}")
        add("    In particular, if the investigation is not complete and no report under "
            "Section 193 of the Bharatiya Nagarik Suraksha Sanhita has been filed within "
            "the period prescribed by Section 187, the arrested person is entitled to be "
            "released on statutory (default) bail, a right independent of any rejection "
            "of bail on merits (M. Ravindran v. Intelligence Officer, (2021) 2 SCC 485; "
            "Rakesh Kumar Paul v. State of Assam, (2017) 15 SCC 67).")
        add(f"    {_NOT_VERIFIED}")
        add("")

    if civil_dispute:
        para += 1
        add(f"{para}.  FOR THAT the dispute is, in substance, of a civil nature and the "
            "essential ingredients of the offences alleged are not made out on the face "
            "of the First Information Report. Criminal proceedings arising from what is "
            "essentially a civil dispute, and pursued to bring pressure on the accused, "
            "are an abuse of the process of law (Md. Ibrahim v. State of Bihar, (2009) 8 "
            "SCC 751; State of Haryana v. Bhajan Lal, 1992 Supp (1) SCC 335). This ground "
            "is to be retained only if the facts bear it out.")
        add(f"    {_NOT_VERIFIED}")
        add("")

    for av in _CLOSING_AVERMENTS:
        para += 1
        for j, chunk in enumerate(_wrap(av)):
            add((f"{para}.  " if j == 0 else "    ") + chunk)
        add("")
    last_ground = para

    # ---- PRAYER ----
    add("PRAYER")
    add("")
    add("In the premises aforesaid, the Petitioner respectfully prays that this Hon'ble")
    add("Court may graciously be pleased to:")
    add("")
    add(" i)   admit this petition;")
    add("")
    show_cause = ("call for the records of First Information Report No. [ ___ ] of Police "
                  "Station [ ___ ] and of the remand proceedings, and issue notice to the "
                  "Respondents to show cause why the arrest and continued custody of the "
                  "said person should not be declared illegal")
    if civil_dispute:
        show_cause += (" and why the said First Information Report and all proceedings "
                       "arising from it should not be quashed")
    add(" ii)  " + _oneline(show_cause) + ";")
    add("")
    grant = ("upon hearing the parties, declare the arrest and continued custody illegal "
             "and direct the release of the said person forthwith, or in the alternative "
             "enlarge him on bail on such terms as this Hon'ble Court thinks fit")
    if civil_dispute:
        grant += ("; and quash the said First Information Report and all proceedings "
                  "arising from it")
    add(" iii) " + _oneline(grant) + ";")
    add("")
    add(" iv)  pass such further or other order(s) as this Hon'ble Court may deem fit and")
    add("      proper in the circumstances of the case.")
    add("")
    add("                                -AND-")
    add("")
    add("INTERIM PRAYER")
    add("")
    add("Pending the hearing and final disposal of this petition, the Petitioner prays")
    add("that this Hon'ble Court may graciously be pleased to:")
    add("")
    add(" i)   stay all further coercive steps against the said person in connection with")
    add("      the said First Information Report;")
    add("")
    medical = any("medical" in (g.get("lead", "") + g.get("finding", "")).lower()
                  for g in grounds) or any("medical" in t.lower() for t in to_verify)
    if medical:
        add(" ii)  direct that the said person be produced before the jurisdictional")
        add("      Magistrate at the earliest date and be medically examined forthwith by")
        add("      a Government medical officer, with all injuries and their approximate")
        add("      time of causation recorded and the report placed on the record;")
    else:
        add(" ii)  direct that the said person be produced before the jurisdictional")
        add("      Magistrate at the earliest date;")
    add("")
    add(" iii) pass such further or other interim order(s) as this Hon'ble Court may deem")
    add("      fit and proper.")
    add("")
    add("And for this act of kindness, the Petitioner shall ever pray.")
    add("")
    add("")
    add("Place: [ ___ ]                          _______________________________")
    add("Date:  [ ___ ]                          Signature of the Petitioner")
    add("")
    add("                                       Through:")
    add("                                       _______________________________")
    add("                                       [ Advocate's name ]")
    add("                                       Counsel for the Petitioner")
    add("")
    add("")
    add(_AFFIDAVIT_TEMPLATE.format(
        fact_para=max(fact_para, 1),
        first_ground=first_ground,
        last_ground=max(last_ground, first_ground),
    ))
    add("")
    add(_INDEX_TEMPLATE)

    return "\n".join(L).rstrip() + "\n"


# ---------------------------------------------------------------------------
# small text helpers
# ---------------------------------------------------------------------------

def _seed_from_question(question_text):
    q = (question_text or "").strip()
    if not q:
        return "[ state, in sequence, what happened -- who was arrested, by whom, when and where. ]"
    q = re.sub(r"\s+", " ", q)
    return f'As stated by the Petitioner: "{q}"'


def _wrap(text, width=86):
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    out, line = [], ""
    for word in text.split(" "):
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def _oneline(text):
    return re.sub(r"\s+", " ", (text or "").strip())


def _roman_lower(n):
    numerals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for value, sym in numerals:
        while n >= value:
            out += sym
            n -= value
    return out or "i"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

_PDF_SUBST = {
    "«": "<<", "»": ">>",        # guillemets
    "—": "--", "–": "-",          # em / en dash
    "‘": "'", "’": "'",           # curly quotes
    "“": '"', "”": '"',
    "·": "-", "•": "-",           # middle dot / bullet
    "…": "...",
    " ": " ",
}


def _pdf_ascii(text):
    for a, b in _PDF_SUBST.items():
        text = text.replace(a, b)
    return text


def _strip_for_pdf(text):
    """The per-ground « NOT INDEPENDENTLY VERIFIED » note is useful in the
    editable box but repeats after every ground and reads as clutter in
    the finished PDF -- the one caution line in the header covers it.
    Drop those lines (and any orphaned « / »), collapse blank runs."""
    out = []
    for raw in _pdf_ascii(text or "").split("\n"):
        s = raw.strip()
        low = s.lower()
        if "independently verified" in low:
            continue
        if s in ("<<", ">>", "<< >>", ">>", "«", "»"):
            continue
        if low.startswith("<<") and low.endswith(">>") and "search" in low:
            continue
        out.append(raw)
    cleaned = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"


def to_pdf(draft_text, output_path="recourse_petition_draft.pdf"):
    """Render the (possibly edited) draft to a PDF. Its own renderer (not
    draft_layer's) so the letterhead is 'RECOURSE -- DRAFT PETITION', not
    'KNOW YOUR RIGHTS'. Typography is the shared KYR style set."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from main import _kyr_pdf_styles

    S = _kyr_pdf_styles()
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
    )

    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [
        Paragraph("RECOURSE &mdash; DRAFT PETITION", S["header"]),
        Spacer(1, 4),
        HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#14213D")),
        Spacer(1, 12),
    ]

    lines = _strip_for_pdf(draft_text).split("\n")
    # the first line of the body is the "RECOURSE -- DRAFT PETITION"
    # header text itself -- drop it, it is now the letterhead above
    if lines and "RECOURSE" in lines[0].upper() and "DRAFT" in lines[0].upper():
        lines = lines[1:]

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            story.append(Spacer(1, 6))
            continue
        letters = [ch for ch in line if ch.isalpha()]
        is_heading = (len(letters) >= 3 and all(ch.isupper() for ch in letters)
                      and not line.lstrip().startswith(("[", "-", "|")))
        story.append(Paragraph(esc(line), S["section_title"] if is_heading else S["body"]))

    story += [
        Spacer(1, 20),
        HRFlowable(width="100%", thickness=0.6, color=colors.grey),
        Spacer(1, 6),
        Paragraph(
            "This draft is generated by an automated tool and is not legal advice. It is a "
            "starting point to be checked and completed with a qualified advocate before it "
            "is signed, filed or sent. Points phrased as 'appears not to have' or 'not "
            "furnished' are drawn from the answers given, not confirmed findings.",
            S["small"],
        ),
    ]
    doc.build(story)
    return output_path


# ===========================================================================
# CHEQUE-BOUNCE / BANK-FREEZE petitions
#
# The person here is the Petitioner (not a detenu, so no next-friend note).
# There is no safeguard checklist for these -- the grounds come straight
# from the chat answer's curated authorities (each carries a case_name +
# context_note, which is a plain statement of the doctrine).
# ===========================================================================

_CIVIL_SPEC = {
    "cheque_bounce": {
        "title": "DRAFT PETITION -- SECTION 138 CHEQUE COMPLAINT",
        "header_note": ("This is drafted as a High Court petition to quash the complaint. "
                        "Quashing a Section 138 case at the summons stage is granted "
                        "sparingly -- your advocate may instead file these points as the "
                        "defence in the trial court, or seek exemption from personal "
                        "appearance. The substance carries over."),
        "contentions": [
            "there was no legally enforceable debt or liability for the amount for which "
            "the cheque was presented [ set out what, if anything, was owed, what was "
            "repaid and when, and how the figure on the cheque was arrived at ];",
            "the statutory presumption under Section 139 of the Negotiable Instruments Act "
            "is rebuttable and the Petitioner is in a position to rebut it on a "
            "preponderance of probabilities from the complainant's own case and the "
            "surrounding circumstances;",
            "[ if applicable ] the Court in which the complaint is filed lacks territorial "
            "jurisdiction, the payee's bank branch being situated at [ ___ ];",
            "the Petitioner is ready and willing to have the matter compounded / settled "
            "in accordance with law.",
        ],
        "enabling": ("Article 226 of the Constitution of India read with Section 528 of the "
                     "Bharatiya Nagarik Suraksha Sanhita, 2023"),
        "relief": ("for quashing of the complaint case described below, instituted under "
                   "Section 138 of the Negotiable Instruments Act, 1881, or in the "
                   "alternative for appropriate directions to secure a fair trial"),
        "matter2": ("Complaint Case No. [ ___ ] of 20[ __ ], pending before the Court of "
                    "[ ___ ], instituted under Section 138 of the Negotiable Instruments "
                    "Act, 1881, in respect of cheque No. [ ___ ] dated [ ___ ] for "
                    "Rs. [ ___ ] drawn on [ ___ ] Bank, and the summons issued to the "
                    "Petitioner therein dated [ ___ ]"),
        "matter3": ("the institution and continuation of the said complaint although there "
                    "was no legally enforceable debt or liability for the sum claimed, the "
                    "statutory presumption being rebuttable, and questions of territorial "
                    "jurisdiction and of the Petitioner's readiness to compound"),
        "respondents": [
            "1.  The State of [ ___ ], through the [ Public Prosecutor ], [ address ].",
            "2.  [ Name of the complainant ], son/daughter/spouse of [ ___ ], resident of "
            "[ address ] -- the complainant in the said case.",
        ],
        "para1": ("The Petitioner is [ identity and occupation ], resident of [ address ]. "
                  "The Petitioner has been summoned as the accused in the complaint case "
                  "described below and is directly aggrieved by it."),
        "para2_extra": "",
        "bg_hint": ("[ continue: the origin of the cheque -- whether it was given blank or as "
                    "security and for what sum; what was actually owed and what was repaid, "
                    "with dates; how and when the amount was filled in; the demand notice and "
                    "any reply; where the Petitioner's and the complainant's bank branches "
                    "are; and the Petitioner's willingness to settle. ]"),
        "annexures": [
            "A copy of the complaint / summons is annexed and marked ANNEXURE-I. A copy of "
            "the cheque and the return memo is annexed and marked ANNEXURE-II. A copy of "
            "the demand notice [ and any reply ] is annexed and marked ANNEXURE-III. [ Add "
            "proof of repayment and bank records as further annexures. ]",
        ],
        "prayer_grant": ("quash the said complaint case and all proceedings arising from "
                         "it; or in the alternative pass such directions as secure a fair "
                         "trial and the Petitioner's exemption from personal appearance for "
                         "routine dates"),
        "interim": [
            "stay all further proceedings in the said complaint case;",
            "dispense with the personal appearance of the Petitioner pending disposal;",
        ],
        "index_rows": [
            "    3     | ANNEXURE-I   : Copy of the complaint / summons        |  __ - __",
            "    4     | ANNEXURE-II  : Copy of the cheque and return memo     |  __ - __",
            "    5     | ANNEXURE-III : Copy of the demand notice [ & reply ]  |  __ - __",
            "    6     | [ further annexures -- repayment proof, bank records ]|  __ - __",
        ],
    },
    "freeze": {
        "title": "DRAFT PETITION -- BANK ACCOUNT FREEZE",
        "header_note": ("This is drafted as a High Court writ petition. The same relief is "
                        "often sought by an application before the jurisdictional "
                        "Magistrate under Section 107 of the BNSS -- your advocate will "
                        "advise which forum fits your facts. The substance carries over."),
        "contentions": [
            "the account was frozen without any order of the jurisdictional Magistrate "
            "under Section 107 of the Bharatiya Nagarik Suraksha Sanhita, a communication "
            "from the police or a bank to that effect not being such an order;",
            "the freeze extends to the whole account when only a specific sum of "
            "Rs. [ ___ ] is said to be in dispute, which is disproportionate and "
            "arbitrary; a lien on that identifiable sum is the appropriate measure and "
            "the balance ought to be released;",
            "the Petitioner is neither an accused nor a suspect in the matter under "
            "investigation and has received [ the credit in question ] in the ordinary "
            "course [ set out the transaction ];",
            "no reasons for the freeze have been recorded or communicated to the "
            "Petitioner, and the freeze impinges on the Petitioner's right to carry on "
            "trade and to livelihood.",
        ],
        "enabling": "Article 226 of the Constitution of India",
        "relief": ("for a direction to the Respondents to withdraw the freeze on the bank "
                   "account described below, or to confine any restriction to the specific "
                   "disputed amount and release the balance"),
        "matter2": ("the freezing / debit-freeze of Bank Account No. [ ___ ] maintained by "
                    "the Petitioner with [ ___ ] Bank, [ ___ ] Branch, effected on or about "
                    "[ ___ ] pursuant to a communication dated [ ___ ] from [ ___ ]"),
        "matter3": ("the freezing of the entire account without an order of the "
                    "jurisdictional Magistrate under Section 107 of the Bharatiya Nagarik "
                    "Suraksha Sanhita, and disproportionately to the sum said to be in "
                    "dispute, the Petitioner being neither an accused nor a suspect in the "
                    "matter under investigation"),
        "respondents": [
            "1.  The State of [ ___ ], through the [ Public Prosecutor / Secretary, Home "
            "Department ], [ address ].",
            "2.  The Superintendent of Police / the Officer-in-Charge, [ Cyber Crime ] "
            "Police Station, [ ___ ], [ address ].",
            "3.  [ Name ] Bank, through its Branch Manager, [ branch and address ].",
            "4.  [ The Indian Cyber Crime Coordination Centre / nodal officer, if the "
            "freeze originated from the cybercrime portal. ]",
        ],
        "para1": ("The Petitioner is [ identity and occupation ], resident of [ address ], "
                  "and maintains the bank account described below in the ordinary course of "
                  "[ his / its ] affairs. The Petitioner is directly aggrieved by the "
                  "freezing of that account."),
        "para2_extra": "",
        "bg_hint": ("[ continue: when and how the Petitioner learnt of the freeze; what the "
                    "bank stated as the reason; the specific sum said to be tainted and how "
                    "it entered the account; the total balance locked; whether any FIR or "
                    "notice has been served on the Petitioner; and the hardship caused. ]"),
        "annexures": [
            "A copy of the bank's intimation of the freeze [ if any ] is annexed and marked "
            "ANNEXURE-I. A copy of the account statement showing the balance and the "
            "disputed credit is annexed and marked ANNEXURE-II. [ Add any communication "
            "from the investigating agency and the Petitioner's representations as further "
            "annexures. ]",
        ],
        "prayer_grant": ("direct the Respondents to forthwith withdraw the freeze on the "
                         "said account; or in the alternative to confine the restriction to "
                         "the identified disputed amount of Rs. [ ___ ] and release the "
                         "balance to the Petitioner"),
        "interim": [
            "direct that the Petitioner be permitted to operate the said account save to "
            "the extent of the disputed sum of Rs. [ ___ ], pending disposal;",
        ],
        "index_rows": [
            "    3     | ANNEXURE-I   : Bank's intimation of the freeze       |  __ - __",
            "    4     | ANNEXURE-II  : Account statement (balance + credit)  |  __ - __",
            "    5     | [ further annexures -- agency communications, reps ] |  __ - __",
        ],
    },
}


_KEEP_CAPS = {
    "BNSS", "BNS", "CRPC", "CR.P.C", "FIR", "SCC", "INSC", "NI", "IPC", "AIR",
    "DEL", "PC", "UT", "UTS", "LEA", "LEAS", "NCRP", "I4C", "SC", "HC", "RBI",
    "OTP", "UPI", "SOP", "QR", "MOU", "PAN", "NALSA", "CJI", "NCT",
}


def _deemphasise(text):
    """The doctrine notes use ALL-CAPS for emphasis ('the presumption
    INCLUDES the debt'); that reads oddly in a petition. Lower-case any
    all-caps word that isn't a real abbreviation."""
    def repl(m):
        w = m.group(0)
        return w if w in _KEEP_CAPS else w.lower()
    return re.sub(r"\b[A-Z][A-Z]{2,}\b", repl, text)


def _grounds_from_answer(answer):
    """Each curated authority in the chat answer -> one entry. The
    context_note is a plain statement of the doctrine; the leading
    "CaseName: " is stripped and the case is cited explicitly instead."""
    out, seen = [], set()
    for m in (answer or {}).get("matches", []) or []:
        cn = (m.get("case_name") or "").strip()
        note = (m.get("context_note") or "").strip()
        if not cn or not note or cn in seen:
            continue
        seen.add(cn)
        body = _deemphasise(re.sub(r"^[^:]{1,80}:\s*", "", note))
        cite = (m.get("citation") or "").strip()
        out.append({
            "case": f"{cn} ({cite})" if cite else cn,
            "body": body,
        })
    return out


def _civil_petition(domain, question_text, answer):
    spec = _CIVIL_SPEC[domain]
    grounds = _grounds_from_answer(answer)
    out = []
    add = out.append

    add(_header(spec.get("header_note", "")))
    add("")
    add("DISTRICT: [ district ]")
    add("")
    add("IN THE HIGH COURT OF [ ___ ] AT [ ___ ]")
    add("[ Constitutional Writ / Extraordinary Criminal Jurisdiction -- retain the")
    add("  description your High Court's rules use ]")
    add("")
    add("CRIMINAL / WRIT PETITION NO. ________ OF 20____")
    add("")
    add("Category: [ for the filing advocate ]      Code: [ for the filing advocate ]")
    add("")
    add("")
    add("To,")
    add("The Hon'ble the Chief Justice and Hon'ble Judges of the")
    add("High Court of [ ___ ] at [ ___ ].")
    add("")
    add("")
    add("IN THE MATTER OF:")
    add("")
    for chunk in _wrap(f"A petition under {spec['enabling']}, {spec['relief']}."):
        add(chunk)
    add("")
    add("                              -AND-")
    add("")
    add("IN THE MATTER OF:")
    add("")
    for chunk in _wrap(spec["matter2"] + "."):
        add(chunk)
    add("")
    add("                              -AND-")
    add("")
    add("IN THE MATTER OF:")
    add("")
    for chunk in _wrap(spec["matter3"] + "."):
        add(chunk)
    add("")
    add("                              -AND-")
    add("")
    add("IN THE MATTER OF:")
    add("")
    add("[ full name ], aged about [ __ ] years, [ son / wife / etc. ] of [ ___ ],")
    add("resident of [ full address ],")
    add("        ... Petitioner")
    add("")
    add("                            -Versus-")
    add("")
    for r in spec["respondents"]:
        for chunk in _wrap(r, width=84):
            add(chunk if chunk.startswith(("1.", "2.", "3.", "4.", "5.")) else "    " + chunk)
    add("        ... Respondents")
    add("")
    add("")
    add("The humble petition of the Petitioner above-named")
    add("       MOST RESPECTFULLY SHOWETH:")
    add("")

    para = 0

    def numbered(lines):
        nonlocal para
        para += 1
        if isinstance(lines, str):
            lines = _wrap(lines)
        add(f"{para}.  {lines[0]}")
        for extra in lines[1:]:
            add(f"    {extra}")
        add("")

    numbered(spec["para1"])
    numbered(f"This petition challenges the said proceedings and seeks the relief set out "
             f"in the prayer below, together with interim protection pending disposal.")

    numbered([
        "[ BACKGROUND -- one numbered paragraph for each step, in sequence, each with its "
        "date. Begin from the account given below and complete every specific: ]",
        "",
        _seed_from_question(question_text),
        "",
        spec["bg_hint"],
    ])
    fact_para = para

    for a in spec["annexures"]:
        numbered(a)

    add("GROUNDS")
    add("")
    add("    The Petitioner submits, without prejudice and in the alternative, as follows:")
    add("")
    first_ground = para + 1

    for contention in spec.get("contentions", []):
        para += 1
        for j, chunk in enumerate(_wrap("FOR THAT " + contention)):
            add((f"{para}.  " if j == 0 else "    ") + chunk)
        add("")

    if grounds:
        para += 1
        add(f"{para}.  FOR THAT the legal position set out below supports the Petitioner "
            "and is relied on:")
        for g in grounds:
            add("")
            add(f"    As held in {g['case']}:")
            for chunk in _wrap(g["body"], width=82):
                add(f"        {chunk}")
            add("        [ the Petitioner's submission on the facts of this case: ___ ]")
        add("")
        add(f"    {_NOT_VERIFIED}")
        add("")

    for av in _CLOSING_AVERMENTS:
        para += 1
        av2 = av.replace("the continued custody causes", "the impugned action causes") \
                .replace("the arrested person and", "the Petitioner and") \
                .replace("the arrested person will continue to suffer detention contrary "
                         "to law", "the Petitioner will continue to suffer the impugned "
                         "action contrary to law")
        for j, chunk in enumerate(_wrap(av2)):
            add((f"{para}.  " if j == 0 else "    ") + chunk)
        add("")
    last_ground = para

    add("PRAYER")
    add("")
    add("In the premises aforesaid, the Petitioner respectfully prays that this Hon'ble")
    add("Court may graciously be pleased to:")
    add("")
    add(" i)   admit this petition;")
    add("")
    add(" ii)  call for the records of the proceedings described above and issue notice to")
    add("      the Respondents to show cause why the relief prayed for should not be granted;")
    add("")
    for k, chunk in enumerate(_wrap("upon hearing the parties, " + spec["prayer_grant"] + ";")):
        add((" iii) " if k == 0 else "      ") + chunk)
    add("")
    add(" iv)  pass such further or other order(s) as this Hon'ble Court may deem fit and")
    add("      proper in the circumstances of the case.")
    add("")
    add("                                -AND-")
    add("")
    add("INTERIM PRAYER")
    add("")
    add("Pending the hearing and final disposal of this petition, the Petitioner prays")
    add("that this Hon'ble Court may graciously be pleased to:")
    add("")
    n = 0
    for item in spec["interim"]:
        n += 1
        for k, chunk in enumerate(_wrap(item)):
            add((f" {_roman_lower(n)})".ljust(6) if k == 0 else "      ") + chunk)
    n += 1
    add(f" {_roman_lower(n)})".ljust(6) + "pass such further or other interim order(s) as this")
    add("      Hon'ble Court may deem fit and proper.")
    add("")
    add("And for this act of kindness, the Petitioner shall ever pray.")
    add("")
    add("")
    add("Place: [ ___ ]                          _______________________________")
    add("Date:  [ ___ ]                          Signature of the Petitioner")
    add("")
    add("                                       Through:")
    add("                                       _______________________________")
    add("                                       [ Advocate's name ]")
    add("                                       Counsel for the Petitioner")
    add("")
    add("")
    add(_AFFIDAVIT_TEMPLATE.format(
        fact_para=max(fact_para, 1),
        first_ground=first_ground,
        last_ground=max(last_ground, first_ground),
    ))
    add("")
    idx = ["INDEX", "",
           "  Sl. No. | Particulars                                          | Page Nos.",
           "  --------|------------------------------------------------------|----------",
           "    1     | Petition                                             |  __ - __",
           "    2     | Affidavit in support                                 |  __"]
    idx += spec["index_rows"]
    idx += ["", "Filed by:  _______________________",
            "           [ Advocate's name ]", "           Counsel for the Petitioner"]
    add("\n".join(idx))

    return "\n".join(out).rstrip() + "\n"


def from_cheque_answer(question_text, answer):
    return _civil_petition("cheque_bounce", question_text, answer)


def from_freeze_answer(question_text, answer):
    return _civil_petition("freeze", question_text, answer)
