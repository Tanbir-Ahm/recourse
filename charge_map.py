"""
charge_map.py -- "What else could he be charged with?": the sections the facts of a conversation may bring in, chosen by CODE (CHARGE_MAP, default off; owner's go 2026-11-09, "then step 3"; lawyers first; research repository FOLLOW_UPS 2ef).

Why. A lawyer's follow-up "what are the other sections my client can be charged with?" (staging, 9 Nov 2026) was answered with BNS 77 and three charge-framing sections of the BNSS: the search finds sections by their meaning, and a question about charges finds the procedure that
surrounds charging. The sections that matter for a person present at a rape (BNS 70(1) gang rape, the common-intention rule in 3(5), conspiracy 61(2), abetment 49) and for evidence deleted from a phone (238) were never in the material.

How. Candidates come from two places and are always labelled:
  1. a table of fact patterns (PATTERNS below): when the facts of the conversation match a pattern, its sections are candidates, each with a one-line reason. The table was written by Claude, from the BNS text in the library, and has NOT been read by a lawyer; it is
     a starting list, not the law. A pattern's sections that the library cannot resolve are dropped.
  2. a search by meaning on the facts, kept only where the section is an OFFENCE (it has a row in the BNSS First Schedule, so procedure sections cannot stand in for charges), at most three, labelled "found by meaning; check that it fits".
Each candidate carries the Schedule's row (cognizable, bailable, court) from offence_class.py. The engine hands the candidates' official text and rows to the answer model with a clause that says the list is not complete and asks it to say, for each, what the section requires, which facts may
match, what the prosecution would still have to show and what the defence can raise; the page shows the code-built table of the candidates under the answer. Nothing here says a person has committed or will be charged with anything.

Pure functions; the search is a parameter (a test passes a stub).
"""
import os
import re

import offence_class

MAX_CANDIDATES = 10
MAX_SEARCHED = 3

CHARGES_QUESTION = "What other sections can the client be charged with on these facts, and how can the defence meet each of them? Give me detailed explanations."

_SEX = re.compile(r"\b(?:rape[ds]?|raping|rapist\w*|gang[- ]?rape\w*|molest\w*|sexual\w*|outrag\w*\s+(?:the\s+|her\s+)?modesty|voyeur\w*|intimate|nude|naked|obscene|indecent|forced himself|assault\w*\s+(?:on\s+)?(?:her|a woman|the woman|the girl))\b", re.I)
_REC = re.compile(r"\b(?:record\w*|film\w*|video\w*|clip\w*|footage|photograph\w*|photo\w*|captur\w*|shot|camera|cctv)\b", re.I)
_SHARE = re.compile(r"\b(?:shar\w+|forward\w*|upload\w*|post\w*|circulat\w*|viral|widely|leak\w*|distribut\w*|transmit\w*|publish\w*|whatsapp\w*)\b", re.I)
_PRESENT = re.compile(r"\b(?:present|at the (?:spot|scene)|crime spot|accompan\w+|along with|together with|helped|held her|assist\w*|aid\w*|stood by|stand(?:ing)? guard|waited outside|drove|arrang\w+ the|(?:was|were) there|there when|watch\w*|co-?accused|prime accused|principal accused|main accused|with the accused|were with|was with)\b", re.I)
_DELETE = re.compile(r"\b(?:delet\w+|destroy\w*|erase\w*|wipe\w*|formatt\w+|tamper\w*|hid(?:den|e)?|hiding|disappear\w*|dispos\w+ of)\b", re.I)
_EVID = re.compile(r"\b(?:phone|video|clip|footage|evidence|data|record\w*|chat|message\w*|file\w*|memory card|mobile)\b", re.I)
_CRIME = re.compile(r"\b(?:accused|case|FIR|police|arrest\w*|offence|investigat\w*|crime|incident|victim|complain\w*|rape\w*|assault\w*|murder|charge\w*|evidence of)\b", re.I)
_THREAT = re.compile(r"\b(?:threat\w*|blackmail\w*|extort\w*|demand\w* (?:money|rs|rupees)|intimidat\w*)\b", re.I)
_CHEAT = re.compile(r"\b(?:cheat\w*|fraud\w*|forg\w+|fake|forged|bogus|duped|dishonest\w*|false document)\b", re.I)
_FORGE = re.compile(r"\b(?:forg\w+|fake|forged|bogus|false document|appointment letter|certificate|signature)\b", re.I)
_HURT = re.compile(r"\b(?:hit|beat|beaten|assault\w*|injur\w*|hurt|wound\w*|stabb\w*|struck|rods?|sticks?|knife|knives|weapons?)\b", re.I)
_WEAPON = re.compile(r"\b(?:rods?|sticks?|knife|knives|weapons?|iron|blades?|axes?|acid|guns?|pistols?|swords?|daggers?)\b", re.I)
_STALK = re.compile(r"\b(?:stalk\w*|follow\w*|keeps? (?:calling|messaging|texting)|sends? (?:her )?messages)\b", re.I)
_DOWRY = re.compile(r"\b(?:dowry|cruelty|harass\w* (?:by|for) (?:her )?(?:husband|in-laws)|in-laws)\b", re.I)
_HARBOUR = re.compile(r"\b(?:harbou?r\w*|shelter\w*|hid(?:e|ing) (?:the )?(?:accused|wanted|absconding)|absconding|wanted (?:man|person|accused)|gave (?:him )?a lift|lift to)\b", re.I)

# breach of trust: property was put in someone's hands and then misappropriated (word lists written by Claude, not read by a lawyer)
_CBT_STRONG = re.compile(r"\b(?:embezzl\w*|misappropriat\w*|siphon\w*|defalcat\w*|divert(?:ed|ing)?|own use|personal use|(?:did not|failed to|never|not) (?:account|return|returned|remit|hand over)\w*)\b", re.I)
_CBT_WEAK = re.compile(r"\b(?:sold|pocket\w*|transferred|withdr[ae]w\w*|used|kept|opened|received|collect\w*|took)\b", re.I)
_CBT_ENTRUST = re.compile(r"\b(?:entrusted|custody|on behalf of|in trust|trustee|executor|caretaker|treasurer|cashier|custodian|secretary|collections?|collected|stored|safekeeping|(?:received|held|collected)\b.{0,50}\b(?:to (?:buy|invest|deposit|remit)|for (?:safekeeping|investment)))\b", re.I)
_CBT_ROLE = re.compile(r"\b(?:bank|co-?operative|society|trust|trustee|company|firm|employer|cashier|accountant|accounts manager|clerk|treasurer|manager|director|partner|agent|broker|employee|servant|driver|custodian|secretary|supervisor|caretaker|executor|administrator|officer|official|guardian|warehouse|courier|office)\b", re.I)
_CBT_THING = re.compile(r"\b(?:rs\.?\s?[\d,]+|rupees|lakhs?|crores?|funds?|money|cash|deposits?|proceeds|premium|goods|property|amount|ornaments?|jewel\w*|gold|parcels?|stock|grain|shares|donations?|rent|collections?|advances?|fees?|sum)\b", re.I)


def _breach_of_trust(t):
    """Property was put in his hands (entrusted, in his custody, collected on behalf of another, or held for him by his role) and then misappropriated: a clear verb of misappropriation, or a plain verb (sold, took, transferred ...) together with a sign of entrustment, with a role and a thing."""
    return bool((_CBT_STRONG.search(t) or (_CBT_WEAK.search(t) and _CBT_ENTRUST.search(t))) and _CBT_ROLE.search(t) and _CBT_THING.search(t))


# a road accident: a vehicle, a collision, and a death or an injury (word lists written by Claude, not read by a lawyer); a deliberate killing with a vehicle is not a negligence case
_VEHICLE = re.compile(r"\b(?:trucks?|lorry|lorries|cars?|bus(?:es)?|tempos?|tractors?|trolley|scooters?|scooty|motorcycles?|motorbikes?|bikes?|auto-?rickshaws?|autos?|jeeps?|vans?|carriers?|suvs?|pick-?ups?|e-?rickshaws?|rickshaws?|ambulances?|minibus|trailers?|rollers?|taxis?|cabs?|vehicles?|tankers?|dumpers?|jcb|drivers?|driving|drove|driven|riding|rode)\b", re.I)
_COLLIDE = re.compile(r"\b(?:hit|knocked(?: down)?|ran over|run over|rammed|collided|collision|crashed|struck|crushed|mowed|overturned|skidded|reversed (?:into|over)|backed (?:into|over)|clipped|sideswiped|side-?swiped|ran into|rolled into|toppled|pinned|dashed|slammed|lost control|jumped a signal|thrown off|accident)\b", re.I)
_RT_DEATH = re.compile(r"\b(?:died|dies|death|dead|killed|fatal|fatally|succumbed|lost (?:his|her|their) life|crushed to death|did not survive|passed away|declared dead|dead on arrival|killing|on the spot)\b", re.I)
_RT_HURT = re.compile(r"\b(?:injur\w*|fractur\w*|hurt|wound\w*|hospitali[sz]ed|grievous|bleeding|head injuries|broke|broken|surgery|serious(?:ly)? (?:injur\w*|hurt))\b", re.I)
_DELIBERATE = re.compile(r"\b(?:deliberately|intentionally|on purpose|wilfully|willfully|murder\w*|with intent to kill)\b", re.I)


_ROAD_CUE = re.compile(r"\b(?:smashed|bumped|brushed|touched|fell under|under the wheels?|wheels?|brakes?|braking|speeding|(?:high |full |excessive )?speed|overtak\w*|handlebar|divider|highway|road|footpath|pavement|crossing|signal|junction|lane|bend|slope|reversing|backed|swerv\w*|tyre|bonnet|windshield|collid\w*)\b", re.I)
_ATTACK = re.compile(r"\b(?:hijack\w*|robber\w*|dacoit\w*|assault\w*|attack\w*|beat|beaten|stabb?\w*|shot|firing|fired|mob)\b", re.I)
_CLAIM = re.compile(r"\b(?:insurance|insurer|claims?|compensation|mact|premium|reimburse\w*)\b", re.I)


def _road_accident(t):
    """A vehicle, a sign of an accident (a collision verb or a road word), and no sign of a deliberate act, a weapon, an attack or a claim for compensation (the person is then not the one who drove)."""
    return bool(_VEHICLE.search(t) and (_COLLIDE.search(t) or _ROAD_CUE.search(t)) and not (_DELIBERATE.search(t) or _WEAPON.search(t) or _ATTACK.search(t) or _CLAIM.search(t)))


def _road_death(t):
    return _road_accident(t) and bool(_RT_DEATH.search(t))


def _road_hurt(t):
    return _road_accident(t) and bool(_RT_HURT.search(t)) and not _RT_DEATH.search(t)


# an ask sentence in which a lawyer asks which offences, charges or sections apply (the first answer then gets the table's sections too, as the button would give them)
_ASK_OFFENCES = re.compile(r"\b(?:(?:what|which)\s+(?:all\s+|other\s+|more\s+|likely\s+|possible\s+)*(?:offences?|offenses?|sections?|charges?|penal provisions?|provisions?)\b|(?:what|which)\s+(?:are|is|will be|would be)\s+the\s+(?:likely\s+|possible\s+)*(?:offences?|charges?|sections?)\b|charged\s+(?:with|under)|booked\s+under|liable\s+(?:for|under)|likely\s+to\s+face|(?:what|which)\s+offences?\s+does\b)", re.I)


def asks_offences(ask_text):
    """True when an ask sentence asks which offences, charges or sections apply ('What offences is he likely to face?'); False for questions about bail, arrest, the punishment of a named section and the like. Words, not understanding."""
    try:
        t = re.sub(r"\s+", " ", ask_text or "")
        if not _ASK_OFFENCES.search(t):
            return False
        return not re.search(r"\b(?:section|sec\.?|s\.)\s*\d", t, re.I)          # a named section ('which offences are covered by section 318?') is a question about that section
    except Exception:  # noqa: BLE001
        return False


# more than one person in the offence itself (the companion rule below); words written by Claude, not read by a lawyer. "and his wife" is left out on purpose (it is as often the victim's wife as the accused's).
_OTHERS = re.compile(r"\b(?:co-?accused|co-?conspirators?|accomplices?|associates?|gang|group of|others|(?:two|three|four|five|six|several|some|many) (?:men|persons|people|boys|girls|friends|accused|others|youths)|(?:along|together) with"
                     r"|and (?:(?:two|three|four|several|some) )?(?:of )?(?:his|her|their) (?:friends?|brothers?|cousins?|partners?|parents?|family|relatives?|helpers?|associates?|accomplices?|colleagues?|mother|father|sons?|men|in-laws)"
                     r"|with (?:his|her|their) (?:friends|brothers?|associates|accomplices|colleagues|cousins?|men))\b", re.I)
# the patterns where the offence itself can be shared by several persons; NOT evidence_deleted and harbouring, which are about what happens after the offence (abetment of the earlier offence needs help given in it)
COMPANION_PATTERNS = frozenset({"recording_sexual", "sharing_sexual", "threat_with_material", "cheating_forgery", "hurt_weapon", "stalking", "dowry_cruelty", "breach_of_trust"})
COMPANIONS = [
    ("BNS", "61", "Criminal conspiracy: an agreement between two or more persons to do an illegal act (the section's own words); the facts speak of more than one person, which does not by itself show an agreement."),
    ("BNS", "45", "Abetment is defined here: a person abets a thing who instigates it, engages with others in a conspiracy for it (an act or illegal omission must follow), or intentionally aids it by an act or illegal omission; the facts speak of more than one person."),
    ("BNS", "49", "Punishment of abetment where the act abetted is committed and no express provision is made for it (the definition is in section 45)."),
]

# (id, test(text) -> bool, [(act, section, why)])  -- written by Claude from the library's BNS text; not read by a lawyer
PATTERNS = [
    ("recording_sexual", lambda t: bool(_SEX.search(t) and _REC.search(t)),
     [("BNS", "77", "Voyeurism: captures, or disseminates, the image of a woman in a private act; the facts speak of a recording."),
      ("ITACT", "66E", "Capturing, publishing or transmitting the image of a private area without consent, under circumstances violating privacy.")]),
    ("sharing_sexual", lambda t: bool(_SEX.search(t) and _REC.search(t) and _SHARE.search(t)),
     [("ITACT", "67", "Publishing or transmitting obscene material in electronic form; the facts speak of a recording that was shared."),
      ("ITACT", "67A", "Publishing or transmitting material containing a sexually explicit act or conduct in electronic form; wider than the 'private area' of section 66E.")]),
    ("present_at_rape", lambda t: bool(re.search(r"\b(?:rape[ds]?|raping|rapist\w*|gang[- ]?rape\w*|forced himself)\b", t, re.I) and _PRESENT.search(t)),
     [("BNS", "70", "Gang rape: where a woman is raped by one or more persons constituting a group or acting in furtherance of a common intention, each of them is deemed to have committed gang rape; a person present at the spot may be alleged to be part of the group."),
      ("BNS", "3", "Sub-section (5) of section 3 is the common-intention rule (a criminal act done by several persons in furtherance of the common intention of all)."),
      ("BNS", "61", "Criminal conspiracy: an agreement to do an illegal act, which may be alleged from association with the principal accused."),
      ("BNS", "45", "Abetment is defined here: a person abets a thing who instigates it, engages with others in a conspiracy for it (an act or illegal omission must follow), or intentionally aids it by an act or illegal omission; a person who filmed or stood by may be alleged to have aided."),
      ("BNS", "49", "Punishment of abetment where the act abetted is committed and no express provision is made for it (the definition is in section 45).")]),
    ("evidence_deleted", lambda t: bool(_DELETE.search(t) and _EVID.search(t) and _CRIME.search(t)),
     [("BNS", "238", "Causing evidence of an offence to disappear, or giving false information, to screen the offender.")]),
    ("threat_with_material", lambda t: bool(_THREAT.search(t) and (_REC.search(t) or _SEX.search(t))),
     [("BNS", "351", "Criminal intimidation."), ("BNS", "308", "Extortion (a threat used to obtain property or a valuable thing).")]),
    ("cheating_forgery", lambda t: bool(_CHEAT.search(t) and _FORGE.search(t)),
     [("BNS", "318", "Cheating and dishonestly inducing delivery of property."), ("BNS", "336", "Forgery, in particular for the purpose of cheating."),
      ("BNS", "340", "Using as genuine a document known to be forged.")]),
    ("hurt_weapon", lambda t: bool(_HURT.search(t) and _WEAPON.search(t)),
     [("BNS", "115", "Voluntarily causing hurt."), ("BNS", "117", "Voluntarily causing grievous hurt, where the injury is grievous."), ("BNS", "118", "Voluntarily causing hurt or grievous hurt by dangerous weapons or means.")]),
    ("stalking", lambda t: bool(_STALK.search(t) and re.search(r"\b(?:woman|girl|daughter|her|she|wife)\b", t, re.I)),
     [("BNS", "78", "Stalking: following a woman and contacting, or attempting to contact, her repeatedly despite a clear indication of disinterest, or watching her use of electronic communication.")]),
    ("dowry_cruelty", lambda t: bool(_DOWRY.search(t)),
     [("BNS", "85", "Husband or his relative subjecting a married woman to cruelty (the Dowry Prohibition Act, 1961 is separate and on the Act shelf).")]),
    ("harbouring", lambda t: bool(_HARBOUR.search(t)),
     [("BNS", "249", "Harbouring an offender: the facts speak of help given to a wanted person."), ("BNS", "253", "Harbouring an offender (other cases).")]),
    ("breach_of_trust", _breach_of_trust,
     [("BNS", "316", "Criminal breach of trust: dishonestly misappropriating, or converting to one's own use, property one has been entrusted with. Sub-section (4) is for a clerk or servant, (5) for a public servant, banker, merchant, agent, broker or attorney; which one fits depends on his role and on what he was entrusted with.")]),
    ("road_accident_death", _road_death,
     [("BNS", "106", "Causing death by a rash or negligent act: sub-section (1) is the general offence; sub-section (2) is for a driver who causes death by rash and negligent driving of a vehicle and escapes without reporting it to a police officer or a Magistrate soon after the incident (a lawyer should confirm that sub-section (2) is in force for the date of the incident)."),
      ("BNS", "281", "Rash driving or riding on a public way, in a manner so rash or negligent as to endanger human life; it is commonly charged together with section 106.")]),
    ("road_accident_hurt", _road_hurt,
     [("BNS", "281", "Rash driving or riding on a public way, in a manner so rash or negligent as to endanger human life."),
      ("BNS", "125", "Doing an act so rashly or negligently as to endanger human life or the personal safety of others; sub-sections cover hurt and grievous hurt caused by such an act.")]),
]


def enabled():
    """CHARGE_MAP=on (default off); it needs CASE_FILE (the facts) to be on as well."""
    on = (os.environ.get("CHARGE_MAP") or "").strip().strip("\"'").strip().lower() in ("on", "true", "1", "yes")
    try:
        import case_file
        return on and case_file.enabled()
    except Exception:  # noqa: BLE001
        return False


def _row_info(act, section):
    if str(act).upper() != "BNS":
        return None
    rows = offence_class.rows_for(section)
    if not rows:
        return None
    return {"lines": [offence_class.line(r) for r in rows], "summary": [offence_class.summary(r) for r in rows], "page": rows[0].get("page")}


def _default_search(text):
    try:
        from semantic_retrieval import find_relevant_sections
        r = find_relevant_sections(text)
        return [m for m in (r.get("matches") or []) if isinstance(m, dict)]
    except Exception:  # noqa: BLE001
        return []


def candidates(facts_text, victim_minor=None, search=None, limit=MAX_CANDIDATES):
    """The sections the facts may bring in: [{'act', 'section', 'why', 'source': 'pattern'|'search', 'pattern', 'class': {lines, summary, page}|None}], patterns first, in the table's order, then at most MAX_SEARCHED more by meaning (BNS offences only, not already listed; they come on top of the limit).
    `facts_text` is the person's facts as one text. [] for no text. Never raises."""
    try:
        t = re.sub(r"\s+", " ", facts_text or "").strip()
        if not t:
            return []
        out, seen = [], set()

        def add(act, sec, why, source, pattern, cap):
            key = (str(act).upper(), re.sub(r"\(.*", "", str(sec)))
            if key in seen or len(out) >= cap:
                return
            seen.add(key)
            out.append({"act": act, "section": str(sec), "why": why, "source": source, "pattern": pattern, "class": _row_info(act, sec)})

        fired = set()
        for pid, test, secs in PATTERNS:
            try:
                hit = test(t)
            except Exception:  # noqa: BLE001
                hit = False
            if hit:
                fired.add(pid)
                for act, sec, why in secs:
                    add(act, sec, why, "pattern", pid, limit)
        if fired & COMPANION_PATTERNS and _OTHERS.search(t):          # several persons in the offence itself: conspiracy, the definition of abetment, its punishment
            for act, sec, why in COMPANIONS:
                add(act, sec, why, "pattern", "companion", limit)
        n = 0
        for m in (search or _default_search)(t):
            if n >= MAX_SEARCHED:
                break
            act, sec = str(m.get("act") or "").upper(), str(m.get("section_number") or "")
            if act == "BNS" and sec and offence_class.rows_for(sec) and (act, re.sub(r"\(.*", "", sec)) not in seen:
                add("BNS", sec, "Found by meaning from the facts; check that it fits.", "search", None, limit + MAX_SEARCHED)
                n += 1
        return out
    except Exception:  # noqa: BLE001
        return []
