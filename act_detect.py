"""
act_detect.py -- a second pass at spotting WHICH ACT a question is about, for the Act Directory and the Act shelf (added 2026-10-17 on the owner's go; research repository FOLLOW_UPS item 2ak).

Why it exists. act_directory.detect() finds an Act only by its name, an alias, or one of a short list of fixed phrases. A real person does not write "taking a bribe": they write "my son works as a clerk in a
government office and was arrested for taking money from a contractor". That sentence named no Act, so the Prevention of Corruption Act was never handed to the answer model (owner's staging test,
2026-10-17). Measured on 75 test questions (five Acts, fifteen each; research `acts/trigger_workbook_eval.py`): the Directory alone finds the right Act for 29, the two passes here take it to 59.

Two passes, both OFF unless ACT_DETECT is set:
  ACT_DETECT = off (default, or unset)  nothing happens; act_directory behaves exactly as before.
  ACT_DETECT = wide                      the WORD pass: everyday wording and the Acts' own vocabulary, by regular expression. No model, no cost.
  ACT_DETECT = ai                        the word pass, and, only when it finds nothing, ONE short Haiku call that may pick an Act from the Directory's own list. Costs about Rs 0.2 a question [Likely].

Where the words come from:
  * the owner's trigger workbook (research `review_data/ruler/inputs/2026-10-12_trigger_workbook_with_spec_v2.xlsx`): Mr. Advocate's "Revised Trigger Map" and "False-Positive Audit", the owner's
    "Layperson Trigger Additions", and Machine Spec v2's N1/N2 anchors (`review_tools/machine_spec_v2.py`), which that workbook froze on 2026-10-12 after Mr. Advocate's regex audit.
  * the Acts' own distinctive vocabulary, derived from the shelf text of the five loaded Acts and kept only where the term is rare in the BNS/BNSS and in the other four Acts
    (`acts/trigger_workbook_eval.py --derive`), then pruned by hand.
Four changes were made to the workbook's anchors on purpose, each because the workbook's own false-positive rules require it; they are marked DEVIATION below.

What a match is and is not. A match here is a RANKING HINT, never a legal conclusion: it is reported with how='likely', so the page says "This question looks like it is about the X Act", exactly as a
phrase match already does. Nothing here says an Act applies to anyone's case. The model never chooses from its own knowledge: the AI pass may only return an id from the list the code gives it, must quote
the words of the question that made it choose, and the code throws the answer away if that quote is not in the question.

Public: mode(); wide(question, ids) -> [{'id','how','why'}]; ai(question, entries, call=None) -> ([{'id','how','why'}], inr); more(question, found, entries, call=None) -> ([hits], record).
Never raises into an answer: every function returns an empty result on bad input or any failure.
"""
import json
import logging
import os
import re

logger = logging.getLogger("act_detect")

AI_MODEL_MAX_TOKENS = 500
AI_TIMEOUT_S = 15
MAX_HITS = 2
FLAGS = re.I | re.S


def mode():
    """'off' (default), 'wide' or 'ai', from ACT_DETECT. Quotation marks around the value are ignored."""
    v = (os.environ.get("ACT_DETECT") or "").strip().strip("\"'").strip().lower()
    return v if v in ("wide", "ai") else "off"


def enabled():
    return mode() != "off"


def near(a, b, n=100):
    """a within n characters of b, in either order (the form Machine Spec v2 uses)."""
    return rf"(?:(?:{a}).{{0,{n}}}(?:{b})|(?:{b}).{{0,{n}}}(?:{a}))"


# ---------------------------------------------------------------------------------------------- the words
# 'about' is the one line the AI pass is given for the Act; 'wide' are the word-pass patterns; 'not_when' stops the word pass for that Act when the question also says this.
_ROLE = r"(?:public servant|government (?:officer|official|servant|employee|staff)|govt\.? (?:officer|official)|officer|official|clerk|inspector|constable|head constable|sub-?inspector|tehsildar|patwari|talathi|revenue officer|municipal (?:officer|official|clerk)|peon|babu|customs officer|excise officer|income[- ]tax officer|registrar|sub-?registrar|engineer|doctor at the government hospital|teacher at the government school)"
_PAY = r"(?:asked (?:me |us |him |her )?for|asking (?:me |us |him |her )?for|ask for|demand|demands|demanded|demanding|took|take|takes|taking|accept|accepts|accepted|accepting|received|receiving|paid|pay|paying|gave|give|giving|offered|offering|collect|collects|collected|collecting)"
_MONEY = r"(?:bribe|money|cash|rs\.?\s*\d|rupees|₹\s*\d|commission|percentage|per cent|percent|cut|gift|gifts|speed money|under the table|hafta)"
_OFFICIAL_WORK = r"(?:file|files|bill|bills|licen[cs]e|permit|tender|certificate|papers|paperwork|work|registration|mutation|transfer|pension|passport|ration card|no[- ]objection|noc|clearance|approval|sanction|case diary)"

# A word that makes a question about a PUBLIC servant (stricter than _ROLE: a bare "officer" or "clerk" can work in a private firm)
_PUBLIC_ROLE = r"\b(?:public servants?|govern?ment (?:officer|official|servant|employee|staff|clerk|hospital|school|doctor|teacher|department|office)|govt\.? (?:officer|official|servant|employee|staff|clerk|hospital|school|office)|sarkari|police(?:man|men|woman)?|constable|sub-?inspector|inspector|tehsildar|patwari|talathi|revenue (?:officer|department)|municipal|municipality|corporation officer|panchayat|customs officer|excise officer|income[- ]tax officer|registrar|sub-?registrar|babu|vigilance|anti[- ]corruption)\b"

ACTS = {
    # ---- the five Acts whose text is on the shelf ----
    "pc_act_1988": {
        "about": "bribery or corruption BY A PUBLIC SERVANT: a bribe or 'commission' demanded, offered or paid to get official work done, a trap by the anti-corruption bureau or vigilance, assets beyond a public servant's known income, or the sanction/approval needed before prosecuting an official.",
        "wide": [
            r"\bbrib\w+",                                                           # workbook N2 #1 (the Directory holds only "taking a bribe" and a few fixed forms)
            r"\billegal gratification\b", r"\bundue advantage\b",                   # the Act's own words
            r"\banti[- ]?corruption\b", r"\bvigilance (?:case|department|enquiry|inquiry|raid|trap|officer)\b",
            r"\btrap case\b", r"\bspecial judge\b", r"\bknown sources? of income\b", r"\bdisproportionate (?:assets|wealth)\b",
            near(_ROLE, _PAY + r"\s+(?:\w+\s+){0,3}?" + _MONEY, 90),                # workbook N2 #6, widened: more roles ("tehsildar", "constable") and more verb forms ("taking", "demanding")
            near(_ROLE, near(_OFFICIAL_WORK, _MONEY, 60), 90),                      # "to pass my file", "to clear my bill", "to move the file"
            near(r"\b(?:property|assets|wealth|house|land)\b", r"\b(?:far )?beyond (?:his|her|their) (?:known )?(?:salary|income|means)\b", 80),
        ],
        # the workbook's own guard, in two parts. Election bribery (a different offence) always stops the word pass.
        "not_when": r"\b(?:voter|voters|election|elections|poll|polling|candidate)\b",
        # A private-sector payment stops it too, UNLESS the question also names a public servant: "I am a builder and the municipal officer asked me for Rs 50,000" is this Act.
        "soft_not_when": r"\b(?:private (?:company|firm|sector|bank|hospital|school|college)|my boss|shopkeeper|landlord|builder|contractor asked me)\b",
        "lifted_by": _PUBLIC_ROLE,
    },
    "pocso_act_2012": {
        "about": "a SEXUAL offence against a child (anyone under 18): touching, assault, rape, harassment, showing or making pornography, and the special court, child-friendly procedure and mandatory reporting that go with it.",
        "wide": [
            r"\b(?:aggravated )?penetrative sexual assault\b", r"\bchild sexual abuse\b", r"\bsexual (?:assault|harassment) of a child\b",
            near(r"\b(?:touch\w*|molest\w*|sexual\w*|rape\w*|obscene|inappropriate\w*|indecent)\b",
                 r"\b(?:child|children|minor|daughter|son|girl|boy|student|under[- ]?(?:18|eighteen)|(?:[0-9]|1[0-7])[- ]?year[- ]?old)\b", 100),   # workbook N2
            near(r"\bpornograph\w+", r"\b(?:child|children|minor|daughter|son|girl|boy|under[- ]?(?:18|eighteen))\b", 80),
        ],
        "not_when": r"\b(?:1[89]|[2-9][0-9])[- ]?year[- ]?old\b|\baged\s*(?:1[89]|[2-9][0-9])\b|\b(?:adult|boss|employer|colleague|workplace)\b",   # workbook N2 exclusion
    },
    "uapa_1967": {
        "about": "the anti-terror law: a terrorist act, terrorist funding, membership of or support for a banned (terrorist) organisation, an association declared unlawful, and bail in such a case.",
        "wide": [
            # terrorism named WITH a case context (workbook N2: terror* near booked/arrested/accused/charged/FIR/bail/case); the bare word is not enough, a person asking what terrorism is does not need this Act
            near(r"\bterroris[mt]\w*", r"\b(?:booked|arrest\w*|accused|charged?|charges|chargesheet|FIR|bail|case|cases|trial|custody|detained|detention|under (?:section|the)|jail|police|court|NIA)\b", 80),
            r"\bterror (?:funding|financing|case|charge|act)\b", r"\banti[- ]terror (?:law|act|case)\b",
            r"\bunlawful association\b", r"\bdeclared unlawful\b", r"\bproceeds of terrorism\b", r"\bterrorist gang\b",
            r"\bterrorist (?:organi[sz]ations?|individuals?|list)\b",                       # the Act's own terms (schedule of terrorist organisations; designation of an individual): added because the stricter first pattern lost two questions that use them
            near(r"\b(?:declar\w+|designat\w+|notif\w+|list(?:ed)?)\b", r"\bterroris[mt]\w*", 60),   # "declare an individual a terrorist"
            near(r"\bbanned\b", r"\b(?:organi[sz]ation|outfit|group|association)\b", 40),
        ],
        "not_when": "",
    },
    "pmla_2002": {
        "about": "money laundering: the Enforcement Directorate (ED) attaching or freezing property, proceeds of crime, a summons or arrest by the ED, bail in a laundering case, and the duties of banks and other reporting entities.",
        "wide": [
            r"\bmoney[- ]launder\w+", r"\blaundering\b", r"\bproceeds of crime\b", r"\breporting entit\w+", r"\badjudicating authority\b", r"\bprovisional attachment\b",
            near(r"\benforcement directorate\b", r"\b(?:attach\w*|froze|frozen|freez\w*|arrest\w*|summon\w*|raid\w*|seiz\w*|notice|case|bail|questioned|ECIR|propert\w+|assets?|bank|account|investigat\w*|inquir\w*|enquir\w*|appear\w*|launder\w*)\b", 80),   # a cue is required (the workbook's own audit: the bare name also turns up in news talk)
            near(r"(?-i:\bED\b)", r"\b(?:attach\w*|froze|frozen|freez\w*|arrest\w*|summon\w*|raid\w*|seiz\w*|notice|case|bail|questioned)\b", 60),   # workbook N2; ED is case-sensitive so "ed" inside a word never matches
        ],
        "not_when": "",
    },
    "sc_st_act_1989": {
        "about": "an atrocity against a member of a Scheduled Caste or Scheduled Tribe: caste-based insult, humiliation or threat, and the special court, bail and anticipatory-bail rules of that Act.",
        "wide": [
            r"\bcaste[- ](?:name|abuse|slur|insult|based|discrimination|remark)\b", r"\bbecause of (?:my|his|her|their) caste\b",
            r"\b(?:dalit|adivasi)\b", r"\bscheduled (?:castes?|tribes?)\b", r"\bexclusive special court\b",
            near(r"\batrocit(?:y|ies)\b", r"\b(?:caste|tribe|tribal|dalit|adivasi|sc|st)\b", 100),
        ],
        "not_when": "",
    },
    # ---- Directory Acts with no shelf text: a hint only, so the person is told where to read the Act ----
    "dowry_prohibition_act_1961": {
        "about": "the Dowry Prohibition Act itself: giving, taking or demanding dowry as an offence under that Act (cruelty by a husband or his relatives is a different, BNS, offence).",
        "wide": [near(r"\bdowry\b", r"\b(?:demand\w*|given|giving|gave|taking|took|take|return\w*|agreement|articles)\b", 100)],   # DEVIATION: the workbook's N2 is a bare "dowry"; the audit's own rule is that dowry alone appears in BNS cruelty and dowry-death matters, so a demand/giving/taking context is required here
        "not_when": "",
    },
    "jj_act_2015": {
        "about": "a child (under 18) accused of an offence, or a child who needs care and protection: the Juvenile Justice Board, an observation home, and how a child's age is proved.",
        "wide": [
            r"\bjuvenile\b", r"\bjuvenile justice board\b", r"\bchild in conflict with law\b", r"\bchild in need of care and protection\b", r"\bobservation home\b", r"\bchild welfare committee\b",
            near(r"\b(?:proof of age|age determination|age of the (?:child|accused))\b", r"\b(?:child|minor|school certificate|aadhaar|birth certificate)\b", 100),
            near(r"\b(?:minor|(?:1[0-7]|[5-9])[- ]?year[- ]?old)\b", r"\b(?:arrest\w*|accused|custody|jail|remand|police station)\b", 60),
        ],
        "not_when": r"\b(?:sexual\w*|molest\w*|rape\w*|pornograph\w*)\b",   # workbook N2 exclusion: a sexual offence against a child is POCSO's
    },
    "arms_act_1959": {
        "about": "unlicensed firearms and ammunition: a gun, pistol, revolver, rifle, bullets or cartridges found, seized or carried without a licence.",
        "wide": [near(r"\b(?:gun|pistol|revolver|rifle|firearm|bullets?|cartridges?|ammunition)\b", r"\b(?:found|recovered|seized|caught|carrying|carried|licen[cs]e|unlicensed|possession|police)\b", 80)],
        "not_when": "",
    },
    "mv_act_1988": {
        "about": "motor-vehicle offences: drunk driving, dangerous driving, hit and run, driving without a licence or insurance.",
        "wide": [r"\bdrunk(?:en)? driving\b", r"\bdrink[- ]and[- ]driv\w+", r"\bhit[- ]and[- ]run\b", r"\bdangerous driving\b", r"\bdriving (?:without (?:a )?(?:valid )?(?:licen[cs]e|insurance)|under the influence|after drinking)\b"],
        # DEVIATION: the workbook's N2 also has a bare "rash (and negligent) driving"; rash driving is itself a BNS offence, so on its own it would put a Motor Vehicles Act notice on an ordinary BNS question
        "not_when": "",
    },
}

# The rest of the Directory's Acts: no word pass of their own (nothing in the workbook was measured for them), but the AI pass may choose them, so each needs its one line. 'wide' empty = never matched by code.
_ABOUT = {
    "tada_1987": "the repealed anti-terror law of 1987: a TADA case, a Designated Court, or an old conviction or appeal under TADA.",
    "nia_act_2008": "the National Investigation Agency: which cases the NIA takes over, its Special Courts, and appeals from them.",
    "customs_act_1962": "smuggling, customs duty evasion, goods seized at an airport, port or border, and confiscation or penalty by customs officers.",
    "cgst_act_2017": "GST offences: a fake invoice, wrongly claimed input tax credit, GST evasion, or arrest by GST officers.",
    "essential_commodities_act_1955": "hoarding, black-marketing or over-pricing of essential goods such as food grain, fuel or medicines.",
    "itpa_1956": "prostitution-related offences: a brothel, procuring or forcing a person into prostitution, or living on its earnings.",
    "posh_act_2013": "sexual harassment of a woman AT WORK handled by an Internal Committee (a civil complaint process, not a police case).",
    "senior_citizens_act_2007": "maintenance for parents and senior citizens, and the Tribunal that can order it or cancel a transfer of their property.",
    "evidence_act_1872": "the old law of evidence, for proceedings that still run under it (the Bharatiya Sakshya Adhiniyam replaced it in 2024).",
    "bsa_2023": "the current law of evidence: what can be proved and how, including electronic records and their certificate.",
    "cpc_1908": "how a CIVIL suit runs: filing, summons, written statement, interim orders, execution of a decree, appeals.",
    "contract_act_1872": "agreements: when a contract is binding, when it can be set aside, breach and damages.",
    "tpa_1882": "transfer of immovable property: sale, mortgage, lease, gift and the rights that go with them.",
    "hma_1955": "Hindu marriage and divorce: judicial separation, restitution, nullity, maintenance and custody within that Act.",
    "hsa_1956": "inheritance among Hindus: who takes a share of the property of a person who has died.",
    "income_tax_act_1961": "income tax: assessment, penalty, search and seizure by the tax department, and tax prosecution.",
    "companies_act_2013": "companies: fraud in company affairs, directors' liability, an SFIO investigation, filings and winding up.",
    "consumer_protection_act_2019": "a complaint by a consumer about a defective product or deficient service, before a Consumer Commission.",
    "limitation_act_1963": "the time limit for bringing a case to court, and when a delay can be condoned.",
    "child_marriage_act_2006": "a child marriage (a girl under 18 or a boy under 21 married): making it voidable, stopping it by court injunction, and the punishment of those who arrange or conduct it.",
    "pcr_act_1955": "the practice of untouchability: refusing a person entry to a temple, well, shop, hospital or public place, or other social disabilities, because of 'untouchability' (a different Act from the SC/ST Atrocities Act).",
    "pdpp_act_1984": "damage to public property: a bus, train, government building or other public property damaged or burned in a protest, riot or bandh, and the special bail rule for it.",
    "muslim_women_act_2019": "instant triple talaq (talaq-e-biddat): pronouncing talaq three times at once, which the Act makes void and punishable, with the wife's subsistence allowance and custody of her minor children.",
}
for _id, _about in _ABOUT.items():
    ACTS.setdefault(_id, {"about": _about, "wide": [], "not_when": ""})

_COMPILED = None


def _compiled():
    global _COMPILED
    if _COMPILED is None:
        out = {}
        for act_id, spec in ACTS.items():
            try:
                out[act_id] = {"wide": [re.compile(p, FLAGS) for p in spec["wide"]],
                               "not_when": re.compile(spec["not_when"], FLAGS) if spec.get("not_when") else None,
                               "soft_not_when": re.compile(spec["soft_not_when"], FLAGS) if spec.get("soft_not_when") else None,
                               "lifted_by": re.compile(spec["lifted_by"], FLAGS) if spec.get("lifted_by") else None}
            except re.error as exc:  # pragma: no cover -- a broken pattern must never break an answer
                logger.warning("act_detect: pattern for %s did not compile (%s); that Act is skipped", act_id, exc)
        _COMPILED = out
    return _COMPILED


def wide(question, ids=None):
    """The word pass: [{'id','how':'likely','why'}] for the Acts whose everyday wording or own vocabulary the question carries. `ids`: the Act ids the Directory knows and may be detected (others are dropped)."""
    try:
        if not isinstance(question, str) or not question.strip():
            return []
        hits = []
        for act_id, c in _compiled().items():
            if ids is not None and act_id not in ids:
                continue
            if c["not_when"] and c["not_when"].search(question):
                continue
            if c["soft_not_when"] and c["soft_not_when"].search(question) and not (c["lifted_by"] and c["lifted_by"].search(question)):
                continue
            for i, p in enumerate(c["wide"]):
                if p.search(question):
                    hits.append({"id": act_id, "how": "likely", "why": f"wide:{i}"})
                    break
        return hits
    except Exception as exc:  # noqa: BLE001 -- fail-open
        logger.warning("act_detect.wide failed: %s", type(exc).__name__)
        return []


# ---------------------------------------------------------------------------------------------- the AI pass
AI_PROMPT = """You route a question to the Indian Act it is about, for a legal information website. You do NOT answer the question and you do NOT say whether any law applies to anybody's case.

Below is the list of Acts the website can point a reader to. Choose the Act (at most two) that the question is about, if any. Choose none when the question is about ordinary criminal law (theft, hurt, cheating, forgery, arrest, FIR, bail, police procedure) with no special Act behind it, or when you are not reasonably sure.

Rules, from this website's own false-positive review:
- Choose ONLY from the list below, and return the id exactly as written.
- An agency is not an Act. The ED may act under more than one law; the police and the CBI act under many.
- A bare section number means nothing: the same number exists in many Acts.
- A payment to a PRIVATE person (an employer, a shopkeeper, a builder, a private company) is not the Prevention of Corruption Act. That Act is about a public servant.
- A child in the question is not by itself the POCSO Act: that Act is about SEXUAL offences against a child. A child accused of an ordinary offence is the Juvenile Justice Act.
- A caste mentioned in passing is not by itself the SC/ST Act, and a dowry mentioned in passing is not by itself the Dowry Prohibition Act.
- Terrorism, national security or a protest is not automatically the UAPA.
- When an everyday description plainly matches an Act even though the Act is not named (for example a government clerk taking money to pass a file: the Prevention of Corruption Act), choose that Act.

For each Act you choose, copy the exact words from the question that made you choose it. Copy them word for word from the question; do not paraphrase. If you cannot copy such words, do not choose that Act.

Return ONLY a JSON object, no other text:
{{"acts": [{{"id": "<id from the list>", "quote": "<words copied from the question>"}}]}}
An empty list is a good answer when nothing fits.

The Acts:
{acts}

The question:
{question}"""


def _norm(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _call_model(prompt):
    """One Haiku call through the engine's client. Returns (text, inr). The cost is added to the question's own COST_QUESTION record (cost_log.begin was called by answer_question; this must not reset it)."""
    import chat_assistant as CA
    if CA.client is None:
        raise RuntimeError("no model client")
    response = CA.client.messages.create(model=CA.HAIKU_MODEL, max_tokens=AI_MODEL_MAX_TOKENS, timeout=AI_TIMEOUT_S,
                                         messages=[{"role": "user", "content": prompt}])
    inr = 0.0
    try:
        import cost_log
        before = len(getattr(cost_log._LOCAL, "calls", None) or [])
        cost_log.note_anthropic("act_detect", CA.HAIKU_MODEL, getattr(response, "usage", None))
        calls = getattr(cost_log._LOCAL, "calls", None) or []
        inr = sum(c.get("inr", 0.0) for c in calls[before:])
    except Exception:  # noqa: BLE001
        pass
    return CA._extract_text_from_response(response), inr


def _parse(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            return None
    return data if isinstance(data, dict) and isinstance(data.get("acts"), list) else None


def ai(question, entries, call=None):
    """The AI pass: ([{'id','how':'likely','why'}], inr). `entries`: [{'id','short'}] the Acts the Directory may detect; their one-line descriptions come from ACTS above, or the short name alone.
    The reply is checked by code: the id must be one we offered, and the quoted words must really be in the question. Any failure returns ([], inr) and the site behaves as if the pass had not run."""
    inr = 0.0
    try:
        if not isinstance(question, str) or not question.strip() or not entries:
            return [], 0.0
        try:
            import cost_log
            if cost_log.budget_state() == "hard":
                return [], 0.0                      # the engine refuses the question anyway; spend nothing
        except Exception:  # noqa: BLE001
            pass
        known = {e["id"]: e for e in entries if isinstance(e, dict) and e.get("id")}
        lines = [f"- {i}: {known[i].get('short') or i}. " + (ACTS.get(i, {}).get("about") or "") for i in known]
        raw, inr = (call or _call_model)(AI_PROMPT.format(acts="\n".join(lines), question=question.strip()[:4000]))
        data = _parse(raw)
        if data is None:
            logger.warning("act_detect.ai: the reply could not be read")
            return [], inr
        out, qn = [], _norm(question)
        for item in data["acts"]:
            if not isinstance(item, dict):
                continue
            act_id, quote = item.get("id"), item.get("quote")
            if act_id not in known:
                continue                            # an Act we did not offer, or an invented id
            if not isinstance(quote, str) or len(_norm(quote)) < 6 or _norm(quote) not in qn:
                logger.warning("act_detect.ai: %s dropped, its quote is not in the question", act_id)
                continue                            # the words must be the person's own
            if not any(h["id"] == act_id for h in out):
                out.append({"id": act_id, "how": "likely", "why": "ai", "quote": quote.strip()[:200]})      # the quote is for the evaluation script; the log line (more()) never carries it
            if len(out) >= MAX_HITS:
                break
        return out, inr
    except Exception as exc:  # noqa: BLE001 -- fail-open
        logger.warning("act_detect.ai failed: %s", type(exc).__name__)
        return [], inr


def more(question, found, entries, call=None):
    """Both passes, for act_directory's result. Returns (extra hits not already found, record for the log). The AI pass runs only when nothing at all was found: it can add an Act, never correct one."""
    rec = {"mode": mode(), "pass": "none", "inr": 0.0}
    try:
        if not enabled() or not entries:
            return [], rec
        ids = {e["id"] for e in entries if isinstance(e, dict) and e.get("id")}
        have = {h["id"] for h in (found or []) if isinstance(h, dict) and h.get("id")}
        hits = [h for h in wide(question, ids) if h["id"] not in have]
        if hits:
            rec["pass"] = "wide"
        elif mode() == "ai" and not have:
            hits, inr = ai(question, entries, call=call)
            hits = [h for h in hits if h["id"] not in have]
            rec["pass"], rec["inr"] = ("ai" if hits else "ai_none"), round(inr, 4)
        rec["acts"] = [h["id"] for h in hits]
        rec["why"] = [h["why"] for h in hits]
        return hits, rec
    except Exception as exc:  # noqa: BLE001 -- fail-open
        logger.warning("act_detect.more failed: %s", type(exc).__name__)
        return [], rec
