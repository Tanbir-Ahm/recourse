"""
case_file.py -- the CASE FILE of a conversation: what the person has told us, in their own words, kept where they can see it and edit it (owner's go 2026-11-09: "the follow-up should carry all the major details of the main question ... more like a
claude artifact of today where we can edit the artifact"; research repository FOLLOW_UPS 2ee).

Why. A follow-up used to reach the engine as the bare new message plus up to four of the earlier messages, and the engine SEARCHED only on the bare message: "what are the other sections my client can be charged with" found BNSS 236, 234, 244, 353
and 237 (framing and discharge of charges) and no offence section, with 11,000 tokens of material against 26,000 for the first answer (staging, 2026-11-09). The facts did travel as text; the search power did not.

What it is. For each conversation, a short list of FACTS, each one a sentence the person typed (copied word for word, never rewritten by a model; a sentence that is a question or a request is not a fact), plus facts the person adds or edits by hand and
answers they tap (the victim's age). The person sees the list beside the conversation and can change, add or remove any line; a line they edit is theirs by definition. A tapped answer cannot be re-worded, only removed (its text is fixed, so a word
cannot be slipped into it).

How the engine uses it (switch CASE_FILE, default off):
  * the facts are folded into the engine's question as "what the person has told us" (their words), the person's earlier QUESTIONS stay as before;
  * a follow-up is SEARCHED on the new message plus the facts (a separate search text; the question string, which the engine treats as the person's words for the grounding checks, the register and the Act Directory, stays theirs);
  * the sections and library judgments the earlier answers relied on are offered again (carry_forward.py), never our conclusions as facts.

Second switch AGE_CARD (default off; needs CASE_FILE): a conversation that mentions a sexual offence and does not say whether the victim is under 18 gets a card under the answer asking it. The answer to the card is a fact of the file. Only a
tapped "under 18" (or the person's own clear words) hands the POCSO Act to the answer model; a guess by the Act-detection model that a question "looks like" POCSO no longer does.

Pure functions, no model, no network, no database. The API (api/chat_service.py, api/routers/chats.py) stores the dict as chats.case_file.
"""
import hashlib
import os
import re
import uuid

MAX_FACTS = 30
MAX_FACT_CHARS = 500
FOLD_FACT_CHARS = 2500            # all facts together, as folded into the engine's question
HINT_CHARS = 600                  # the facts as a search text
ASKS_KEPT = 3                     # the person's earlier questions folded in besides the facts
ASK_CHARS = 300

FACTS_HEADER = "What the person has told us in this conversation (their own words, as they have edited them; these are not our answers and are not checked against any record):"

AGE_KEY = "victim_age"
AGE_VALUES = {"minor": "The victim is under 18 years old.", "adult": "The victim is 18 years old or more.", "unknown": "The person does not know the victim's age."}
AGE_LABELS = {"minor": "Under 18", "adult": "18 or over", "unknown": "Don't know"}


def _on(name):
    return (os.environ.get(name) or "").strip().strip("\"'").strip().lower() in ("on", "true", "1", "yes")


def enabled():
    """CASE_FILE=on (default off)."""
    return _on("CASE_FILE")


def age_card_enabled():
    """AGE_CARD=on (default off); it needs CASE_FILE."""
    return enabled() and _on("AGE_CARD")


# ------------------------------------------------------------------ the file
def new_file():
    return {"v": 1, "facts": [], "removed": []}


def _flat(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _norm(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _h(text):
    return hashlib.sha1(_norm(text).encode("utf-8")).hexdigest()[:12]


def _clean_file(cf):
    out = new_file()
    if isinstance(cf, dict):
        for f in cf.get("facts") or []:
            if isinstance(f, dict) and isinstance(f.get("text"), str) and f["text"].strip():
                keep = {k: f[k] for k in ("id", "text", "kind", "key", "value", "h") if k in f}
                keep.setdefault("id", uuid.uuid4().hex[:10])
                keep.setdefault("kind", "typed")
                out["facts"].append(keep)
        out["removed"] = [str(x) for x in (cf.get("removed") or []) if isinstance(x, str)][-200:]
    return out


# ------------------------------------------------------------------ sentences: facts and asks
_ASK_START = re.compile(
    r"^(?:(?:please|kindly|also|and|but|now|so|then|okay|ok)\s+)*(?:what|which|who|whom|whose|when|where|why|how|can|could|should|would|will|shall|is|are|was|were|do|does|did|has|have|had|may|might|"
    r"tell|explain|give|advise|list|suggest|draft|help|state|describe|analy[sz]e|compare|summari[sz]e|show|provide|mention|elaborate|clarify|check|find|identify|discuss|outline|prepare|write)\b", re.I)


_BOUND = re.compile(r"([.?!।][\"')\]”’]?)(\s+)")


def _split_block(block):
    """The sentences of one line of text. A full stop is a boundary whatever the next letter's case (people type in lower case), unless the word before it is an abbreviation or an initial (passage_window's list: Mr., Dr., Vs., No., S. ...)."""
    try:
        import passage_window
        abbr = passage_window._ABBR
    except Exception:  # noqa: BLE001
        abbr = None
    spans, start = [], 0
    for m in _BOUND.finditer(block):
        if abbr is not None and m.group(1)[0] == "." and abbr.search(block[max(0, m.start(1) - 14):m.start(1) + 1]):
            continue
        spans.append(block[start:m.end(1)])
        start = m.end(2)
    spans.append(block[start:])
    return [_flat(x) for x in spans if _flat(x)]


def _sentences(text):
    out = []
    for block in re.split(r"\n+", text or ""):
        block = _flat(block)
        if block:
            out.extend(_split_block(block))
    return out


def is_ask(sentence):
    s = _flat(sentence)
    return s.endswith("?") or bool(_ASK_START.match(s))


def split_message(message):
    """-> (facts, asks): the statement sentences and the question/request sentences of one message, each copied word for word."""
    facts, asks = [], []
    for s in _sentences(message):
        if is_ask(s):
            asks.append(s)
        elif len(s.split()) >= 4 and len(s) >= 15:
            facts.append(s[:MAX_FACT_CHARS].rstrip())
    return facts, asks


def asks_of(messages):
    """The person's earlier questions, the first message's first, then the last ASKS_KEPT of the rest, each cut. `messages`: their earlier messages in order."""
    allasks = []
    for m in messages or []:
        allasks.extend(split_message(m)[1])
    if not allasks:
        return []
    picked = [allasks[0]] + allasks[1:][-ASKS_KEPT:]
    out = []
    for a in picked:
        out.append(a if len(a) <= ASK_CHARS else a[:ASK_CHARS].rsplit(" ", 1)[0].rstrip(" ,;") + " ...")
    return out


def add_from_message(cf, message):
    """A copy of the file with the statement sentences of `message` added: the ones not already in it and not removed by the person (a sentence the person deleted, or edited, stays gone/edited)."""
    cf = _clean_file(cf)
    seen = {_h(f["text"]) for f in cf["facts"]} | {f["h"] for f in cf["facts"] if f.get("h")} | set(cf["removed"])
    facts, _ = split_message(message)
    for s in facts:
        if len(cf["facts"]) >= MAX_FACTS:
            break
        h = _h(s)
        if h in seen:
            continue
        seen.add(h)
        cf["facts"].append({"id": uuid.uuid4().hex[:10], "text": s, "kind": "typed", "h": h})
    return cf


_ID_OK = re.compile(r"^[A-Za-z0-9]{6,16}$")


def apply_edit(cf, items):
    """The person's edit of the list: `items` is the whole list as they now see it, [{'id': str|None, 'text': str}] in order. A known id keeps its fact (its text changes if they changed it: the fact becomes 'edited'); an unknown or missing id
    is a new fact they wrote ('added'); a fact missing from the list is removed (a typed one is remembered as removed so it is not taken from their messages again). A tapped answer keeps its fixed text. Returns a new file."""
    cf = _clean_file(cf)
    by_id = {f["id"]: f for f in cf["facts"]}
    out, kept_ids, seen_texts = [], set(), set()
    for it in (items or [])[:MAX_FACTS * 2]:
        if not isinstance(it, dict):
            continue
        fid = it.get("id") if isinstance(it.get("id"), str) else None
        old = by_id.get(fid) if fid else None
        if old is not None:
            kept_ids.add(fid)
            if old.get("kind") == "button":
                out.append(old)
                continue
            text = _flat(it.get("text"))[:MAX_FACT_CHARS].rstrip()
            if not text:
                kept_ids.discard(fid)          # emptied: removed
                continue
            if _norm(text) != _norm(old["text"]):
                old = {**old, "text": text, "kind": "edited"}
            if _norm(old["text"]) in seen_texts:
                continue
            seen_texts.add(_norm(old["text"]))
            out.append(old)
        else:
            text = _flat(it.get("text"))[:MAX_FACT_CHARS].rstrip()
            if not text or _norm(text) in seen_texts:
                continue
            seen_texts.add(_norm(text))
            nid = fid if (fid and _ID_OK.match(fid) and fid not in by_id and fid not in {o["id"] for o in out}) else uuid.uuid4().hex[:10]       # the page names a line it has just written, so a repeated save of the same line is not a second line
            out.append({"id": nid, "text": text, "kind": "added", "h": _h(text)})
    removed = list(cf["removed"])
    for f in cf["facts"]:
        if f["id"] not in kept_ids and f.get("kind") != "button":
            for h in (f.get("h"), _h(f["text"])):
                if h and h not in removed:
                    removed.append(h)
    return {"v": 1, "facts": out[:MAX_FACTS], "removed": removed[-200:]}


def set_answer(cf, key, value):
    """Record a tapped answer (only AGE_KEY with minor / adult / unknown): replaces an earlier answer to the same card. Returns a new file; raises ValueError for anything else."""
    if key != AGE_KEY or value not in AGE_VALUES:
        raise ValueError("unknown answer")
    cf = _clean_file(cf)
    cf["facts"] = [f for f in cf["facts"] if f.get("key") != key]
    cf["facts"].append({"id": uuid.uuid4().hex[:10], "text": AGE_VALUES[value], "kind": "button", "key": key, "value": value})
    return cf


def answer_of(cf, key=AGE_KEY):
    for f in (cf or {}).get("facts") or []:
        if isinstance(f, dict) and f.get("key") == key:
            return f.get("value")
    return None


def victim_minor(cf):
    """True when the person tapped 'under 18'; False when they tapped 'adult'; None otherwise (not asked, or 'don't know')."""
    v = answer_of(cf)
    return True if v == "minor" else (False if v == "adult" else None)


def fact_texts(cf):
    return [f["text"] for f in (cf or {}).get("facts") or [] if isinstance(f, dict) and f.get("text")]


def fold_lines(cf):
    """The lines that carry the facts into the engine's question (one line each; the marker can never appear inside a fact because a fact is one flattened sentence). [] for an empty file."""
    lines, used = [], 0
    for t in fact_texts(cf):
        t = _flat(t)
        if used + len(t) > FOLD_FACT_CHARS:
            break
        used += len(t)
        lines.append(f"- {t}")
    return ([FACTS_HEADER] + lines) if lines else []


def search_hint(cf, limit=HINT_CHARS):
    """The facts as a search text (typed, edited and added ones; a tapped answer is not a search word), cut at a sentence."""
    texts = [t for f in (cf or {}).get("facts") or [] if isinstance(f, dict) and f.get("kind") != "button" for t in [f.get("text")] if t]
    out = ""
    for t in texts:
        t = _flat(t)
        if len(out) + len(t) + 1 > limit:
            break
        out = (out + " " + t).strip()
    return out


# ------------------------------------------------------------------ the age card
SEXUAL = re.compile(
    r"\b(?:rape[ds]?|raping|rapist|gang[- ]?rape\w*|molest\w*|sexual(?:ly)?\s+(?:assault\w*|harass\w*|abus\w*|offence\w*|offense\w*|exploit\w*|intercourse|act|acts|violence|misconduct)|"
    r"outrag\w*\s+(?:the\s+|her\s+)?modesty|voyeur\w*|indecent\s+(?:assault|exposure|act)|sex\s+crime\w*|eve[- ]?teas\w*|groped|groping|"
    r"(?:nude|naked|obscene|intimate|sexual)\s+(?:video|videos|image|images|photo|photos|picture|pictures|clip|clips)|sexual\s+molest\w*|(?:376|354|509)\b)", re.I)
CASE_CONTEXT = re.compile(
    r"\b(?:my client|my (?:son|brother|husband|father|friend|relative|nephew|cousin|uncle)|we represent|(?:was|were|been|got|is|are) (?:arrested|booked|charged|detained|in custody|accused)|has been (?:arrested|booked|charged|detained)|"
    r"booked|(?:an )?FIR (?:has|was|is|under|for)|chargesheet (?:has|was|is)|in custody|under (?:section|sec\.?) \d+|charged (?:with|under)|accused of)\b", re.I)
ADULT_CONTEXT = re.compile(r"\b(?:colleague|co-?worker|workplace|office|employer|employee|boss|wife|husband|marital|adult|gym|live-?in)\b", re.I)
MINOR_SIGNAL = re.compile(
    r"(?:\bpocso\b|protection of children from sexual|"
    r"\b(?:minor|child|underage|under[- ]age)\s+(?:girl|boy|victim|complainant|prosecutrix|survivor)\b|"
    r"\bvictim\s+(?:is|was|being)\s+(?:a\s+)?(?:minor|child|under|below)\b|"
    r"\b(?:girl|boy|child|victim|prosecutrix)\b[^.?!]{0,40}\b(?:aged|age of|of age)\s*(?:[0-9]|1[0-7])\b|"
    r"\b(?:[0-9]|1[0-7])[- ]?year[- ]?old\s+(?:girl|boy|child|victim|minor)\b|"
    r"\b(?:under|below)[- ]?(?:18|eighteen)\b[^.?!]{0,40}\b(?:victim|girl|boy|child)\b|\b(?:victim|girl|boy|child)\b[^.?!]{0,40}\b(?:under|below)[- ]?(?:18|eighteen)\b|"
    r"\b(?:school ?girl|school ?boy|schoolgirl|schoolboy)\b)", re.I)


def sexual_offence_words(text):
    return bool(SEXUAL.search(text or ""))


def minor_signal(text):
    """True when the person's own words clearly say the VICTIM is a child (a number near the word 'client' or 'accused' does not count)."""
    return bool(MINOR_SIGNAL.search(text or ""))


def card_for(cf, person_text):
    """The age card, or None. Shown when the conversation's words mention a sexual offence in a case (not a bare definition question), the person's words do not already say the victim is a child, and the file holds no answer to the card yet.
    `person_text` is everything the person has typed in this conversation. Needs AGE_CARD on."""
    try:
        if not age_card_enabled() or answer_of(cf) is not None:
            return None
        text = " ".join([person_text or ""] + fact_texts(cf))
        if not (sexual_offence_words(text) and CASE_CONTEXT.search(text)) or minor_signal(text) or ADULT_CONTEXT.search(text):
            return None
        return {"key": AGE_KEY, "title": "One fact changes this answer a lot", "text": "Was the victim under 18 years old?",
                "why": "If the victim was under 18, a special law, the Protection of Children from Sexual Offences Act (POCSO), applies. Tell us and we will look at it. We will not assume either way.",
                "options": [{"value": v, "label": AGE_LABELS[v]} for v in ("minor", "adult", "unknown")]}
    except Exception:  # noqa: BLE001
        return None
