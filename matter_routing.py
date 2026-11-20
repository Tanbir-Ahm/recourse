"""
matter_routing.py -- which path answers a question asked inside a matter that has documents (MATTER_ROUTING_PLAN.md; owner's go 2026-11-20: "go ahead with auto routing, legal path when unsure").

Three routes:
  file   the answer lives in the person's documents ("what are the sections charged here?", "when was he arrested?"): the quick documents-only answer (no law, pages cited, cheap).
  law    everything else: the legal path exactly as it is today (law-only questions, law on the facts, chained questions, small talk, anything unsure).
  draft  a request to draft a document ("draft a bail petition"): drafting is not available, so a plain notice says so and what can be done instead (no model, no cost).

The rules, in order (first match wins):
  1. A draft request: a drafting verb (draft, prepare, write, make, compose, frame; Hinglish "kar do / bana do / likh do") asked of the tool, with a document noun near it (petition, application, notice, reply, complaint,
     affidavit, submissions ...). A question ABOUT drafting ("how is a quashing petition drafted?", "what should a bail petition contain?") is not a request: it goes to law.
  2. Any LAW signal -> law. Signals: a word or phrase that asks for the law or a judgment on it (entitled, valid, legal, bailable, punishment, chances, should we, can he, explain, what is a ..., under the BNSS, a section
     number asked about, an Act's name, a deadline "within 90 days", a case name "X v. Y" ...). One signal is enough: when in doubt, the legal path.
  3. A FILE signal and no law signal -> file. File signals: a document word (chargesheet, FIR, remand order, page, Doc 2 ...), a pointing word (here, in the file, according to ...), a past-tense question about what
     happened ("when was he arrested?", "who conducted the TIP?"), or a question about a person in the case ("who is the investigating officer?").
  4. Nothing -> law.
Pure functions; no model, no network. A route is a decision about COST and SHAPE only: the legal path is never weakened, and the file path never states law.
"""
import os
import re

ROUTES = ("file", "law", "draft")


def mode():
    """MATTER_ROUTING = off (default: today's behaviour) | shadow (decide and log, change nothing) | on (act on the decision)."""
    v = (os.environ.get("MATTER_ROUTING") or "off").strip().strip("\"'").strip().lower()
    return v if v in ("off", "shadow", "on") else "off"


def _norm(q):
    q = (q or "").lower().replace("’", "'").replace("‘", "'")
    q = re.sub(r"[‐-―]", "-", q)
    return " ".join(q.split())


# ------------------------------------------------------------------ 1. draft requests
_DOC_NOUNS = r"(?:petition|application|plaint|notice|reply|response|complaint|affidavit|writ|written submissions|submissions|synopsis|memo(?:randum)?|appeal|revision|representation|vakalatnama|letter|draft)"
_DRAFT_VERB = r"(?:draft|prepare|write|make|compose|frame|create|generate)"
_TEACHING = re.compile(r"\bhow (?:to|is|are|do|does|should|can|would)\b|\bwhat (?:should|must|does|do|goes|go)\b|\bexplain\b|\bcontents? of\b|\bformat of\b|\bstructure of\b")
_DRAFT_REQ = re.compile(r"(?:^|\b(?:please|kindly|can you|could you|would you|will you|pls|and|then|me)\s+)" + _DRAFT_VERB + r"\b(?:\s+\S+){0,6}?\s+" + _DOC_NOUNS + r"s?\b")
_DRAFT_HINGLISH = re.compile(_DOC_NOUNS + r"s?\b(?:\s+\S+){0,3}?\s+(?:draft|likh|bana|taiyar)\s+(?:kar|kr|de)\s*(?:do|de|dijiye|dena)?\b")


_DRAFT_WANT = re.compile(r"\b(?:i need|i want|we need|we want|give me|send me|need|want)\s+(?:a|an)\s+(?:draft (?:of (?:a |an )?)?)?(?:\S+\s+){0,3}?" + _DOC_NOUNS + r"s?\b")


def is_draft_request(q):
    n = _norm(q)
    if _TEACHING.search(n):
        return False
    return bool(_DRAFT_REQ.search(n) or _DRAFT_HINGLISH.search(n) or _DRAFT_WANT.search(n))


# ------------------------------------------------------------------ 2. law signals
_LAW_WORDS = [
    ("judgement", r"\b(?:entitled|entitlement|legal(?:ly)?|illegal(?:ly)?|lawful(?:ly)?|unlawful(?:ly)?|valid(?:ity)?|invalid|void|liable|liability|permissible|allowed|possible|proper(?:ly)?|correct(?:ly)?|justified|defective|mandatory|compulsory|necessary)\b"),
    ("offence_class", r"\b(?:bailable|non-bailable|cognizable|cognisable|non-cognizable|compoundable|non-compoundable|triable|punishable|punishment|sentence|saza|sazaa|imprisonment|fine of)\b"),
    ("evidence_value", r"\b(?:admissible|admissibility|evidentiary|evidential|probative|weak|weaker|strong|stronger|strength|merits?|chances?|likely|prospects?)\b"),
    ("advice", r"\b(?:should (?:we|i|he|she|they|the)|shall (?:we|i)|can (?:we|i|he|she|they|the|a|an|police|my|our|accused|magistrate|court|this|it)|could (?:we|i|he|she|they|the|a|police|it)|"
               r"would (?:it|he|she|the|this|that)|will (?:it|he|she|the|this|that)|may (?:we|i|he|she|the)|must (?:we|i|he|she|the|a)|what happens|what can we|what should|best|strategy|advise|advice|recommend)\b"),
    ("argument", r"\b(?:argue for|argue that|our (?:best |strongest )?arguments?|(?:best|strongest|possible|good) arguments?|grounds? (?:for|to|can|we|of bail|for bail)|plead|parity|challenge|quash(?:ing)?|"
                 r"defen[cs]e (?:can|should|may)|help (?:the|us|our|my) (?:defen[cs]e|client|case|accused))\b"),
    ("explain", r"\b(?:explain|meaning|means|define|definition|difference|differ|distinguish|compare|interpret|interpretation)\b"),
    ("law_word", r"\b(?:law|laws|legal position|position|statute|statutory|provision|provisions|provide|provides|rule|rules|precedent|judgment of|ruling|held in|limitation|deadline|default bail|right to|rights?|accrue[sd]?|kanoon|kanun|jamanat|apply|applies|applicable|relevant|affect|affects|effect)\b"),
    ("limits", r"\b(?:maximum|minimum|max|min|how long can|period of|time limit|within \d+ days|more than \d+ days|less than \d+ days|beyond \d+ days|\d+ days? (?:limit|rule|period))\b"),
    ("definition", r"^(?:what is|what's|what are) (?:a|an) |\bwhat is meant by\b"),
    ("act_named", r"\b(?:bns|bnss|bsa|ipc|crpc|cr\.p\.c|bharatiya|sanhita|adhiniyam|evidence act|penal code|constitution|article \d+|ndps|pocso|uapa|pmla|it act|ni act|the act)\b"),
    ("section_asked", r"\b(?:what (?:is|does|do) (?:section|s\.|sec\.?)\s*\d+|(?:section|sec\.?|s\.)\s*\d+[a-z]?(?:\s*\(\d+\))?\s+(?:of|says|say|provides|provide|mean)|explain section)\b"),
    ("sections_for", r"\b(?:which|what) (?:are the )?(?:sections?|offences?|provisions?) (?:for|apply|applies|cover|covers|deal|deals|would|will|can)\b"),
    ("court_tries", r"\b(?:which court (?:tries|try|will try|can try|has jurisdiction)|jurisdiction|tried by|trial court for)\b"),
    ("case_named", r"\b\w+ (?:v\.|vs\.?|versus) \w+|\bcase of\b|\bin re\b"),
    ("was_it_right", r"\b(?:was|is) (?:it|that|this) (?:right|correct|fair|proper)\b|\bwas (?:it|that) (?:wrong|bad)\b"),
    ("fault", r"\b(?:wrong|wrongly|wrongful|violat\w*|breach\w*|lapses?|irregular\w*|illegality|flaws?|loopholes?|defects?|mistakes?|delayed|delay|belated|late|prompt(?:ly)?|complete|incomplete|sufficient|insufficient|enough)\b"),
    ("offence_made_out", r"\b(?:made out|disclos\w* (?:an |any |the )?offen[cs]e|prima facie|ingredients?|elements of|attract\w*|constitute\w*)\b"),
    ("time_rule", r"\bwithin (?:\d+ (?:hours?|days?|months?)|(?:the )?(?:time|period|limit))\b|\b(?:in|on) time\b|\btime-?barred\b"),
    ("courts_and_precedent", r"\b(?:supreme court|high court|apex court|landmark|precedents?|judgments?|judgements?|case law|ratio|held|holds|holding|overruled|good law)\b"),
]
_LAW_RES = [(name, re.compile(rx)) for name, rx in _LAW_WORDS]


_NAMED_IN = re.compile(r"\b(?:in|per)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z.]+)+")       # "what happened in Arnesh Kumar?": a capitalised name after "in" is most often a judgment; read on the question as typed


def law_signals(q):
    n = _norm(q)
    out = [name for name, rx in _LAW_RES if rx.search(n)]
    if _NAMED_IN.search(q or ""):
        out.append("named_in")
    return out


# ------------------------------------------------------------------ 3. file signals
_FILE_WORDS = [
    ("document", r"\b(?:charge ?-?sheets?|final report|f\.?i\.?r\.?s?|remand(?: order)?|bail order|order(?:s)? (?:dated|of|passed)|the order|memo|seizure list|statements?|letter|report|reports|documents?|papers?|file|files|"
                 r"annexure|case diary|diary|record|records|deposition|page|pages|doc \d+|para(?:graph)? \d+|uploaded|attached)\b"),
    ("pointing", r"\b(?:here|in this case|in the case|this case|these documents|the material|mentioned|stated|recorded|according to|as per|written|shown|say about|says about|say on|says on)\b"),
    ("summary", r"\b(?:summari[sz]e|summary|timeline|chronology|list (?:all|the|of)|give me (?:the|a|all)|show me|read (?:the|this)|tell me (?:the|what|who|when|where))\b"),
    ("past_event", r"^(?:when|where|who|whom|what|which|how many|how much|why|did|was|were|has|had|is|are)\b.*\b(?:was|were|did|had|has been|have been|got|came|went|took|gave|"
                   r"\w{3,}ed)\b"),
    ("case_actor", r"^(?:who|when|where|what|which|how many|how much|is|did|does|has|was)\b.*\b(?:accused|co-accused|complainant|informant|victim|witness(?:es)?|investigating officer|i\.?o\.?|magistrate|judge|counsel|"
                   r"police station|my client|the client|he|she|his|her)\b"),
    ("hinglish", r"\b(?:kab|kaun|kahan|kitne din|kis din|kya likha|mein kya)\b"),
]
_FILE_RES = [(name, re.compile(rx)) for name, rx in _FILE_WORDS]


def file_signals(q):
    n = _norm(q)
    return [name for name, rx in _FILE_RES if rx.search(n)]


_STRONG_FILE = ("document", "pointing", "summary", "hinglish")
_CHARGES_ASKED = re.compile(r"\b(?:sections?|charges?|offen[cs]es?) (?:(?:are|were|is|has been|have been) )?(?:charged|applied|invoked|registered|mentioned|listed|in the (?:chargesheet|fir|charge ?sheet)|lagi|lage)\b|"
                            r"\b(?:what|which) (?:are )?(?:the )?charges\b|\bcharged (?:with|under)\b")


def lookup_like(question, fs=None):
    """Did the question ALSO ask what the documents say? Used only to offer 'Answer from my documents only' under a legal answer; it never changes the route (the routing rules above are what the frozen set
    measured). A document word, a pointing word, a summary request, or 'the sections charged'; not the weaker past-tense or person signals."""
    fs = file_signals(question) if fs is None else fs
    return bool(set(fs) & set(_STRONG_FILE) or _CHARGES_ASKED.search(_norm(question)))


def route(question, has_documents=True):
    """{'route': 'file' | 'law' | 'draft', 'why': the rule that decided, 'law_signals': [...], 'file_signals': [...], 'lookup_like': bool}. lookup_like = the question had file signals (used to offer
    'answer from my documents only' under a legal answer). A matter with no documents always takes the legal path."""
    ls, fs = law_signals(question), file_signals(question)
    base = {"law_signals": ls, "file_signals": fs, "lookup_like": lookup_like(question, fs)}
    if not has_documents:
        return {**base, "route": "law", "why": "no_documents"}
    if is_draft_request(question):
        return {**base, "route": "draft", "why": "draft_request"}
    if ls:
        return {**base, "route": "law", "why": "law_signal"}
    if fs:
        return {**base, "route": "file", "why": "file_signal"}
    return {**base, "route": "law", "why": "unsure"}
