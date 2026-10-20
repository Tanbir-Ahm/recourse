"""
web_chat.py  --  follow-up questions on the website (CHAT_MODE; owner's go 2026-10-17: "Website only, thread can
vanish on refresh, cap at 8 turns").

The engine (chat_assistant.answer_question) takes ONE question string. A follow-up is folded into that string in the
format the WhatsApp bot already uses (whatsapp_store.build_question_with_context), so the engine's own reading of it
applies unchanged: _extract_current_message() splits on "\\n\\nNow the person says: ", every keyword match and the
library search run on the CURRENT message, and only the scope check reads the earlier messages too.

What this module adds, and why:
  - Only the PERSON's earlier messages are folded in, never our earlier answers. The engine treats the whole question
    string as the person's words: the grounding check counts it as material (a case name found there passes), the
    register's question block says "the person's own question names a case", the Act Directory reads Acts from it.
    An earlier answer folded in would let a case or an Act that WE named pass as one the person named.
  - The first message (usually the situation) is always kept, then the last three; each is flattened to one line and
    shortened, so the marker cannot appear twice and the scope check is not swamped.
  - A follow-up rewrite: one short model call (Haiku) that turns "is it bailable?" into a standalone question, because
    the engine searches on the current message and a bare "is it bailable?" finds the wrong sections (it only widens to
    the full text when the narrow search finds nothing at all). The rewrite is checked by code before use: every
    number in it, and any case name, must appear in the person's own messages; otherwise it is dropped. The person's
    own words always go to the engine; the rewrite is added after them, labelled.
  - A message the rewrite judges to start a new matter goes to the engine alone (no earlier messages), unless it is a
    short message that leans on earlier words ("what about him?").

Switch CHAT_MODE: off (default; the page is exactly as before) | on (fold + rewrite) | fold (fold only, no rewrite call;
the safety valve if the rewrite misbehaves). The thread lives in the browser session only: a refresh starts afresh.
"""
import hashlib
import json
import logging
import os
import re

logger = logging.getLogger("web_chat")

MAX_TURNS = 8                    # questions in one conversation, the first included (owner, 2026-10-17)
EARLIER_KEPT = 3                 # besides the first message, the last N earlier messages are folded in
MAX_MSG_CHARS = 1500             # each earlier message, flattened, is cut to about this length
MAX_ANSWER_CHARS = 900           # the rewrite step sees each earlier answer cut to about this length
ANSWERS_SHOWN_TO_REWRITE = 2     # ... and only the last N answers
MAX_STANDALONE_CHARS = 600
REWRITE_TIMEOUT_S = 20

MARKER = "\n\nNow the person says: "         # must equal chat_assistant._CONTEXT_MARKER (a test checks it)
HEADER = "Earlier in this same conversation (the person's earlier messages only; your earlier answers are not repeated here):"
REWRITE_LEAD = "(Read with the earlier messages, this asks: "

NOT_FOLDED_STATES = ("unrelated",)           # small talk is not part of the matter
ANSWER_STATES = ("single_match", "conflicting_matches")


def mode():
    v = (os.environ.get("CHAT_MODE") or "").strip().strip("\"'").strip().lower()
    return v if v in ("on", "fold") else "off"


def enabled():
    return mode() != "off"


def can_ask(turns):
    return len(turns or []) < MAX_TURNS


def _flat(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _cut(text, n):
    """text shortened to about n characters at a sentence end (or a word), with an ellipsis; whole when short."""
    text = _flat(text)
    if len(text) <= n:
        return text
    head = text[:n]
    ends = [m.end() for m in re.finditer(r"[.?!](?=\s)", head)]
    cut = ends[-1] if ends and ends[-1] > n * 0.5 else (head.rfind(" ") if " " in head else n)
    return head[:cut].rstrip() + " ..."


def earlier_messages(turns):
    """The person's earlier messages to fold in: the first one, then the last EARLIER_KEPT, each flattened and cut. Turns the engine judged small talk are left out."""
    qs = [t.get("q") or "" for t in (turns or []) if (t.get("answer") or {}).get("state") not in NOT_FOLDED_STATES and (t.get("q") or "").strip()]
    if not qs:
        return []
    picked = [qs[0]] + qs[1:][-EARLIER_KEPT:]
    return [_cut(q, MAX_MSG_CHARS) for q in picked]


def fold(earlier, current):
    """The engine's question string: the earlier messages in WhatsApp's format, then the marker, then the current message. No earlier messages: the current message alone (exactly today's input)."""
    if not earlier:
        return current
    lines = [HEADER] + [f"- The person asked: {m}" for m in earlier]
    return "\n".join(lines) + MARKER + current


# ------------------------------------------------------------------ the follow-up rewrite
REWRITE_PROMPT = """You help a legal information website read a follow-up message in a conversation. You do NOT answer it.

Below are the person's earlier messages, a shortened copy of the website's earlier answers, and the person's NEW message.

Decide two things:
1. Is the new message a follow-up that depends on the earlier conversation (it refers back to something, for example "is it bailable?", "what about my brother?", "and if he does not appear?", "explain the second point"), or does it start a new, separate matter? When in doubt, treat it as a follow-up.
2. If it is a follow-up, rewrite it as ONE standalone question that a reader who has not seen the conversation would understand, by filling in what words such as "it", "that", "he", "this case" or "the second point" refer to.

Rules for the rewrite:
- Keep the person's own question and wording; only add the missing references, taken from the conversation.
- Add no fact, date, amount, name or legal conclusion that the conversation does not contain.
- Never put a section number, an article number or a case name in the rewrite, even if the earlier answers mention one: describe the offence or the topic in words instead (for example "the offence of taking a bribe", not a section number).
- Do not answer the question, and do not judge whether anything was lawful.
- At most two sentences.

Return ONLY a JSON object, no other text:
{{"follow_up": true or false, "standalone": "the rewritten question, or the new message unchanged if follow_up is false"}}

The person's earlier messages:
{earlier}

The website's earlier answers (shortened):
{answers}

The NEW message:
{current}"""

_NUM = re.compile(r"\d+")
_CASE_NAME = re.compile(r"\b[A-Z][\w.&'()-]*(?:\s+(?:of\s+)?[A-Z][\w.&'()-]*)*\s+(?:[vV][sS]?\.?|versus)\s+[A-Z]")
_REFERENCE_WORD = re.compile(r"\b(it|its|that|this|these|those|he|him|his|she|her|they|them|their|there|same|such|above|earlier|previous|second|first|point)\b", re.I)


def _leans_back(message):
    """A short message with a word that points back ("what about him?", "is that bailable?"): it cannot stand alone, whatever the model says."""
    words = _flat(message).split()
    return len(words) <= 10 and bool(_REFERENCE_WORD.search(message or ""))


def _guard(standalone, person_text):
    """'' when the rewrite may be used, else the reason it may not: every number in it, and any case name, must appear in the person's own messages."""
    own_nums = set(_NUM.findall(person_text or ""))
    extra = [n for n in _NUM.findall(standalone) if n not in own_nums]
    if extra:
        return "number_not_in_person_messages"
    own = _letters(person_text)
    for m in _CASE_NAME.finditer(standalone):
        words = _letters_words(m.group(0))            # e.g. ['was', 'bilal', 'ahmed', 'kaloo', 'v', 's']: a capitalised first word of the sentence is caught too, so any tail with a party word counts
        cut = words.index("v") if "v" in words else 0
        if not any("".join(words[i:]) in own for i in range(cut)):
            return "case_name_not_in_person_messages"
    return ""


_CONNECTOR = re.compile(r"\s+(?:[vV][sS]?\.?|versus)\s+")


def _letters_words(text):
    return [w for w in re.sub(r"[^a-z0-9 ]", "", _CONNECTOR.sub(" v ", text or "").lower()).split()]


def _letters(text):
    return "".join(_letters_words(text))


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
    if not isinstance(data, dict) or not isinstance(data.get("follow_up"), bool) or not isinstance(data.get("standalone"), str):
        return None
    return data


def _call_model(prompt, current_message):
    """One Haiku call through the engine's client. Returns (text, inr) or raises. Its cost is logged as a COST_CALL line labelled chat_rewrite and counts towards the daily budget."""
    import chat_assistant as CA
    if CA.client is None:
        raise RuntimeError("no model client")
    response = CA.client.messages.create(model=CA.HAIKU_MODEL, max_tokens=400, timeout=REWRITE_TIMEOUT_S,
                                         messages=[{"role": "user", "content": prompt}])
    inr = 0.0
    try:
        import cost_log
        cost_log.begin(current_message)         # so the COST_CALL line carries this message's hash, not the previous question's; answer_question begins its own record afterwards
        cost_log.note_anthropic("chat_rewrite", CA.HAIKU_MODEL, getattr(response, "usage", None))
        calls = getattr(cost_log._LOCAL, "calls", None) or []
        inr = sum(c.get("inr", 0.0) for c in calls)
    except Exception:  # noqa: BLE001
        pass
    return CA._extract_text_from_response(response), inr


def rewrite(turns, current, call=None):
    """Returns (outcome, standalone, inr). outcome: 'used' | 'unchanged' | 'new_topic' | 'dropped_guard:<why>' | 'failed' | 'off'. `call` replaces the model call in tests."""
    if mode() != "on":
        return "off", None, 0.0
    try:
        import cost_log
        if cost_log.budget_state() == "hard":
            return "off", None, 0.0               # the engine will refuse the question anyway; spend nothing
    except Exception:  # noqa: BLE001
        pass
    earlier = earlier_messages(turns)
    answers = [_cut((t.get("answer") or {}).get("response_text") or "", MAX_ANSWER_CHARS) for t in (turns or [])
               if (t.get("answer") or {}).get("state") in ANSWER_STATES and (t.get("answer") or {}).get("response_text")][-ANSWERS_SHOWN_TO_REWRITE:]
    prompt = REWRITE_PROMPT.format(earlier="\n".join(f"- {m}" for m in earlier) or "(none)",
                                   answers="\n".join(f"- {a}" for a in answers) or "(none)", current=_flat(current))
    try:
        raw, inr = (call or _call_model)(prompt, current)
    except Exception as exc:  # noqa: BLE001 -- fail-open: the follow-up goes as typed
        logger.warning("chat rewrite failed: %s", type(exc).__name__)
        return "failed", None, 0.0
    data = _parse(raw)
    if data is None:
        return "failed", None, inr
    standalone = _flat(data["standalone"])
    if not data["follow_up"]:
        return "new_topic", None, inr
    if not standalone or len(standalone) > MAX_STANDALONE_CHARS:
        return "failed", None, inr
    if standalone.lower().rstrip("?.! ") == _flat(current).lower().rstrip("?.! "):
        return "unchanged", None, inr
    why = _guard(standalone, " ".join([t.get("q") or "" for t in (turns or [])] + [current or ""]))
    if why:
        return "dropped_guard:" + why, None, inr
    return "used", standalone, inr


def question_for_engine(turns, current, call=None):
    """The string to hand answer_question for a follow-up, plus a record for the log. With no earlier turns: the message alone."""
    if not turns:
        return current, {"turn": 1, "rewrite": "first", "folded": 0, "rewrite_inr": 0.0}
    outcome, standalone, inr = rewrite(turns, current, call=call)
    earlier = earlier_messages(turns)
    if outcome == "new_topic" and not _leans_back(current):
        earlier = []
    message = current + "\n" + REWRITE_LEAD + standalone + ")" if outcome == "used" else current
    return fold(earlier, message), {"turn": len(turns) + 1, "rewrite": outcome, "folded": len(earlier), "rewrite_inr": round(inr, 4)}


def log_turn(question, info):
    """One CHAT_TURN line per question asked in chat mode. Never the text: 'q' is the same hash as the COST_QUESTION line's."""
    try:
        rec = {"q": hashlib.sha256((question or "").encode("utf-8")).hexdigest()[:12], "mode": mode(), "of": MAX_TURNS, **(info or {})}
        print("CHAT_TURN " + json.dumps(rec), flush=True)
    except Exception:  # noqa: BLE001
        pass
