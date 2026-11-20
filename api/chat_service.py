"""
api/chat_service.py -- one saved chat turn, start to finish (step A3.4; WEBSITE_DESIGN 5.1).
run_turn() is the job a signed-in question runs in an engine worker thread: it folds the person's EARLIER questions into the engine's input (web_chat.question_for_engine: only the person's own words, never our earlier answers), runs the
engine, then saves the question and the answer and settles the quota IN THE SAME THREAD, so a caller who disconnects half-way still gets their answer saved and their allowance counted exactly once.
A question the site answered counts as one use; a refusal (the topic bar, "not enough to go on", an unavailable model, a spending pause) is saved but costs nothing. A failure releases the unit and saves nothing.
A repeated Idempotency-Key returns the stored answer instead of asking again; the same key arriving while the first is still running is refused (409), so a retry never spends twice.
"""
import datetime
import logging
import re
import threading
from dataclasses import dataclass, field

from sqlalchemy import func, select

import carry_forward
import case_file as CF
import matter_files as MF
import law_on_hand as LOH
import matter_depth as MD
import matter_routing as MR
import web_chat

from . import engine_adapter, matter_docs, quota
from .db import models as M
from .db import session as dbs

logger = logging.getLogger("recourse.api")
ANSWER_STATES = ("single_match", "conflicting_matches")
TITLE_CHARS = 60
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,40}$")

_INFLIGHT = set()
_INFLIGHT_LOCK = threading.Lock()


def claim(chat_id, key):
    """True if this (chat, key) is not already running; the caller must unclaim() when it ends. In-process: the service runs as ONE replica (WEBSITE_DESIGN 9)."""
    with _INFLIGHT_LOCK:
        if (chat_id, key) in _INFLIGHT:
            return False
        _INFLIGHT.add((chat_id, key))
        return True


def unclaim(chat_id, key):
    with _INFLIGHT_LOCK:
        _INFLIGHT.discard((chat_id, key))


def matter_notes(db, chat):
    """The notes of the matter a chat is filed under, as the dict web_chat.matter_lines reads; None when it is not filed under one (or the matter is gone)."""
    if chat.matter_id is None:
        return None
    m = db.execute(select(M.Matter).where(M.Matter.id == chat.matter_id, M.Matter.user_id == chat.user_id)).scalar_one_or_none()
    if m is None:
        return None
    return {"title": m.title, "court": m.court, "case_number": m.case_number, "sections": m.sections, "stage": m.stage, "next_date": m.next_date.isoformat() if m.next_date else None, "facts": m.facts}


def matter_instructions(db, chat):
    """The standing instructions of the matter a chat is filed under (P0), or None."""
    if chat.matter_id is None:
        return None
    return db.execute(select(M.Matter.instructions).where(M.Matter.id == chat.matter_id, M.Matter.user_id == chat.user_id)).scalar_one_or_none()


FACT_LABELS = {"typed": "From your message", "edited": "You edited this", "added": "You added this", "button": "You tapped this"}


def case_file_view(cf, turns, audience=None):
    """What the page draws as the conversation's case file (case_file.py): the facts (id, text, kind, label, whether the text can be changed), what the earlier answers relied on (display only), and the age card when it is due. None when
    CASE_FILE is off. `turns`: [{'q', 'answer'}] of the saved conversation."""
    if not CF.enabled():
        return None
    cf = cf if isinstance(cf, dict) else CF.new_file()
    facts = [{"id": f["id"], "text": f["text"], "kind": f.get("kind", "typed"), "label": FACT_LABELS.get(f.get("kind", "typed"), ""), "editable": f.get("kind") != "button"} for f in cf.get("facts") or [] if isinstance(f, dict) and f.get("text")]
    try:
        relied = carry_forward.relied_on(turns)
    except Exception:  # noqa: BLE001
        relied = {"sections": [], "cases": []}
    person_text = " ".join(t.get("q") or "" for t in turns or [])
    import charge_map
    asked = any((t.get("q") or "").strip() == charge_map.CHARGES_QUESTION for t in turns or [])
    last = (turns or [])[-1] if turns else None
    shown = any((t.get("answer") or {}).get("charge_candidates") for t in turns or [])                 # the table already came with an answer (the person asked which offences apply): the button would give the same sections again
    offer = bool(charge_map.enabled() and audience == "lawyer" and facts and not asked and not shown and last and (last.get("answer") or {}).get("state") in ANSWER_STATES)
    return {"enabled": True, "facts": facts, "limit": CF.MAX_FACTS, "max_chars": CF.MAX_FACT_CHARS, "relied_on": relied, "card": CF.card_for(cf, person_text),
            "charges": {"offer": True, "text": "What else could he be charged with?", "note": "Sections the facts may bring in, chosen by a program from your case file; not complete and not read by a lawyer."} if offer else None}


def title_from(question):
    t = re.sub(r"\s+", " ", question or "").strip()
    if len(t) <= TITLE_CHARS:
        return t
    head = t[:TITLE_CHARS]
    return (head.rsplit(" ", 1)[0] if " " in head else head).rstrip(" ,;:") + " ..."


def turns_of(messages):
    """[{'q': the person's words, 'answer': the engine's stored result}] from a chat's messages in order. A question with no stored answer is left out."""
    turns, pending = [], None
    for m in messages:
        if m.role == "user":
            pending = m.content
        elif m.role == "assistant" and pending is not None:
            turns.append({"q": pending, "answer": m.result if isinstance(m.result, dict) else {}})
            pending = None
    return turns


def user_message_count(db, chat_id):
    return db.execute(select(func.count()).select_from(M.Message).where(M.Message.chat_id == chat_id, M.Message.role == "user")).scalar()


def stored_reply(db, chat_id, key, question):
    """-> ('none', None) | ('same', out) | ('reused', None) for an Idempotency-Key already used in this chat."""
    um = db.execute(select(M.Message).where(M.Message.chat_id == chat_id, M.Message.request_id == key, M.Message.role == "user")).scalars().first()
    if um is None:
        return "none", None
    if um.content != question:
        return "reused", None
    am = db.execute(select(M.Message).where(M.Message.chat_id == chat_id, M.Message.request_id == key, M.Message.role == "assistant")).scalars().first()
    if am is None:
        return "none", None
    return "same", {"result": am.result, "cost_inr": float(am.cost_inr) if am.cost_inr is not None else None, "elapsed_ms": None, "chat_id": str(chat_id), "message_id": str(am.id), "saved": True, "replayed": True}


@dataclass
class Turn:
    user_id: object
    chat_id: object
    audience: str
    question: str
    request_id: str
    event_id: object
    usage: dict
    turns: list = field(default_factory=list)
    matter: dict | None = None                  # the notes of the matter the chat is filed under (title, court, case_number, sections, stage, next_date, facts), read once when the question was accepted
    case_file: dict | None = None               # the chat's case file (case_file.py) as it was when the question was accepted; None when CASE_FILE is off
    intent: str | None = None                   # 'age_minor': the question is the person's tap on 'under 18' (the server wrote its words)
    matter_id: object = None                    # the matter the chat is filed under (MATTER_FILES: its documents are searched for each question, inside the worker thread)
    instructions: str | None = None             # the matter's standing instructions (MATTER_INSTRUCTIONS on); never folded into the question


def _style():
    try:
        import answer_style
        return answer_style.style()
    except Exception:  # noqa: BLE001
        return None


def _commit():
    import os
    return (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:12] or None


def _release_only(event_id):
    try:
        with dbs.session() as db:
            quota.release(db, event_id)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not release a use: %s", type(exc).__name__)


def run_turn(on_step, c):
    """The worker-thread job. Returns the engine's reply plus chat_id, message_id, saved, usage."""
    try:
        engine_q, info = web_chat.question_for_engine(c.turns, c.question, matter=c.matter, case_file=c.case_file)
        web_chat.log_turn(engine_q, info)
        ecf = web_chat.engine_case_file(c.case_file, info, c.turns, c.question, intent=c.intent, audience=c.audience) if c.case_file is not None or CF.enabled() else None
        dec = _route_decision(c)
        acting = bool(dec and dec["mode"] == "on")
        size = dec["size"] if acting else None
        if size == "draft":
            docs = None                                                   # a request to draft: drafting is not available; a fixed notice, no model, no cost (DRAFTING_PLAN.md section 10, D0)
            out = {"result": {"state": "draft_unavailable"}, "cost_inr": 0.0, "elapsed_ms": 0}
        elif size == "smalltalk":
            docs = None                                                   # thanks / hello: a fixed line, no model, no cost (matter_depth.py)
            out = {"result": {"state": "smalltalk"}, "cost_inr": 0.0, "elapsed_ms": 0}
        else:
            file_route = size in ("file", "explain")                      # the whole matter when it is short (matter_docs.for_question)
            docs = _matter_docs(c, file_route=file_route)
            out = engine_adapter.work(engine_q, c.audience, on_step, carried=info.get("carry") or None, case_file=ecf, matter_docs=docs,
                                      matter_instructions=c.instructions if c.instructions and MF.instructions_enabled() else None, matter_route="file" if (size == "file" and docs) else None,
                                      matter_depth=size if size in ("explain", "standard", "research") else None, matter_pins=dec.get("pins") if size in ("explain", "standard") else None)
            if docs:
                _check_documents(c, out, docs)
        if acting:
            _attach_route(out, dec)
    except BaseException:
        _release_only(c.event_id)
        unclaim(c.chat_id, c.request_id)
        raise
    try:
        return _save(c, out, info)
    finally:
        unclaim(c.chat_id, c.request_id)


ROUTE_INTENTS = {"with_law": "law", "documents_only": "file", "explain_sections": "law", "go_deeper": "research"}
ROUTE_LABELS = {"file": "From your documents only. This answer states no law.", "law": "Answered with the law and your documents.",
                "escaped": "This question needed the law, so it was answered with the law and your documents."}
_REF_OK = re.compile(r"(?:BNS|BNSS|BSA) \d{1,3}[A-Z]?(?:\(\d+\))?")


def routing_active():
    """Any of the matter switches that change how a question in a matter is answered: MATTER_ROUTING (on), MATTER_DEPTH (on) or LAW_ON_HAND."""
    return MR.mode() == "on" or MD.mode() == "on" or LOH.enabled()


def pins_for(c):
    """['BNS 309(4)', ...]: the sections of the matter to explain, chosen by CODE and never from model text: the list the last answer in the conversation gave (a documents-only answer's code-checked list, or an explain answer's
    own sections), else the sections the matter's documents give as charged on a labelled line. [] when neither."""
    refs = []
    try:
        last = ((c.turns or [])[-1].get("answer") if c.turns else None) or {}
        refs = list((((last.get("matter_route") or {}).get("offers") or {}).get("explain_sections")) or [])
        if not refs:
            refs = [x.get("ref") for x in ((last.get("law_on_hand") or {}).get("sections") or []) if isinstance(x, dict) and x.get("on_hand")]
        refs = [r for r in refs if isinstance(r, str) and _REF_OK.fullmatch(r)]
        if not refs:
            with dbs.session() as db:
                refs = matter_docs.charged_pins(db, c.user_id, c.matter_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pins: %s", type(exc).__name__)
        refs = []
    return list(dict.fromkeys(refs))[:LOH.MAX_ITEMS]


def _intent_size(intent):
    """The size a tapped button asks for."""
    dm = MD.mode() == "on"
    if intent == "documents_only":
        return "file"
    if intent == "go_deeper":
        return "research"
    if intent == "with_law":
        return "standard" if dm else "law"
    if intent == "explain_sections":
        return "explain" if LOH.enabled() else "law"
    return None


def _route_decision(c):
    """Which size of answer this question gets, for a chat filed under a matter that has documents; None when nothing applies (every switch off, no matter, no documents). {'size', 'route', 'why', 'mode', 'pins', ...}.
    'size' is file | explain | standard | research | draft | smalltalk, or 'law' (the full path as before: MATTER_ROUTING alone). MATTER_DEPTH (matter_depth.py) chooses among all sizes (unsure means standard); with it off,
    MATTER_ROUTING chooses between the file path and the full path as before, and LAW_ON_HAND alone adds the explain size. A tapped button decides by itself. Logged in every mode (counts and rule names, never the question)."""
    if c.matter_id is None or not MF.enabled():
        return None
    rm, dm, lh = MR.mode(), MD.mode(), LOH.enabled()
    if rm == "off" and dm == "off" and not lh:
        return None
    try:
        with dbs.session() as db:
            if not matter_docs.has_documents(db, c.user_id, c.matter_id):
                return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("routing: could not read the matter's documents: %s", type(exc).__name__)
        return None
    import json as _json
    pins = pins_for(c) if (dm != "off" or lh) else []
    router = MR.route(c.question, True)
    d = {"route": router["route"], "why": router["why"], "law_signals": router["law_signals"], "file_signals": router["file_signals"], "lookup_like": router["lookup_like"], "pins": pins, "size": None}
    plan = MD.plan(c.question, pins_available=bool(pins), has_documents=True) if (dm != "off" or lh) else None
    if c.intent in ROUTE_INTENTS:
        sz = _intent_size(c.intent)
        d.update(route=ROUTE_INTENTS[c.intent], why="tapped_" + c.intent, lookup_like=False, size=sz)
        if sz == "explain" and not pins and not LOH.refs_in_text(c.question, pins):
            d["size"] = "standard" if dm == "on" else "law"
        d["mode"] = "on" if (rm == "on" or dm == "on" or (lh and sz == "explain")) else "shadow"
    elif dm == "on":
        sz = plan["size"]
        if sz == "explain" and not lh:
            sz = "standard"                                                # the explain size needs LAW_ON_HAND: without it a question about sections takes the Standard size
        d.update(size=sz, why=plan["why"], mode="on")
    else:
        legacy = {"file": "file", "draft": "draft"}.get(router["route"], "law")
        d["size"], d["mode"] = legacy, ("on" if rm == "on" else "shadow")
        if lh and plan and plan["size"] == "explain" and pins:
            d.update(size="explain", why=plan["why"], mode="on")
        elif rm != "on":
            d["size"], d["mode"] = None, "shadow"
    d["plan_size"] = plan["size"] if plan else None
    print("MATTER_ROUTE " + _json.dumps({"mode": d["mode"], "route": d["route"], "why": d["why"], "law_signals": d["law_signals"], "file_signals": d["file_signals"], "depth_mode": dm, "size": d["size"], "plan": d["plan_size"], "pins": len(pins)}), flush=True)
    return d


def _attach_route(out, dec):
    """result['matter_route']: the path and size that actually answered, its label, and the one-tap other ways."""
    result = out.get("result") if isinstance(out.get("result"), dict) else None
    if result is None or result.get("state") in ("draft_unavailable", "smalltalk"):
        return
    answered = result.get("route")                                           # 'file' | 'explain' | None (the full path)
    answer = result.get("state") in ANSWER_STATES
    depth_on = MD.mode() == "on"
    size = (result.get("depth") or answered or "law") if (answered or result.get("depth")) else "law"
    escaped = (dec["size"] == "file" and answered != "file") or (dec["size"] == "explain" and answered != "explain")
    offers = {"with_law": bool(answered == "file" and answer),
              "documents_only": bool(answered is None and answer and not escaped and dec.get("lookup_like") and not dec["why"].startswith("tapped_") and not depth_on),
              "explain_sections": list(result.get("explain_sections") or []) if answered == "file" else [],
              "go_deeper": bool(depth_on and answer and size in ("file", "explain", "standard"))}
    if (size == "explain" or (depth_on and size in MD.LABELS)) and MD.LABELS.get(size):
        label = MD.LABELS[size]
    else:
        label = ROUTE_LABELS["escaped" if escaped else ("file" if answered == "file" else "law")]
    result["matter_route"] = {"route": "file" if answered == "file" else "law", "size": size, "decided": dec["route"], "why": dec["why"], "escaped": escaped, "label": label, "offers": offers}
    if escaped:
        print("MATTER_ROUTE_ESCAPED " + __import__("json").dumps({"why": dec["why"], "size": dec["size"]}), flush=True)


def last_exchange(chat):
    """(the person's last question, the stored result of the answer to it) of a chat, or (None, None)."""
    q, res = None, None
    for m in chat.messages:
        if m.role == "user":
            q, res = m.content, None
        elif m.role == "assistant":
            res = m.result if isinstance(m.result, dict) else {}
    return q, res


def route_intent_question(chat, intent):
    """The words of a tapped routing button, written by the server from the stored answer (never from the client): None when the button was not offered under the last answer."""
    if not (MF.enabled() and routing_active() and chat.matter_id):
        return None
    q, res = last_exchange(chat)
    offers = ((res or {}).get("matter_route") or {}).get("offers") or {}
    if intent in ("with_law", "documents_only", "go_deeper"):
        return q if (q and offers.get(intent)) else None
    if intent == "explain_sections":
        refs = [r for r in (offers.get("explain_sections") or []) if isinstance(r, str) and re.fullmatch(r"(?:BNS|BNSS|BSA) \d{1,3}[A-Z]?(?:\(\d+\))?", r)]
        return MF.explain_question(refs) or None
    return None


def _matter_docs(c, file_route=False):
    """MATTER_FILES on and the chat filed under a matter with documents: the passages that match the question (this matter's only), else None. The search text is the person's current message and their two previous
    messages (a follow-up such as 'and on page 3?' leans on them), never our answers. Fails open: the question is answered without the documents."""
    if c.matter_id is None or not MF.enabled():
        return None
    try:
        earlier = [t.get("q") or "" for t in (c.turns or []) if isinstance(t, dict)][-2:]
        text = " ".join(earlier + [c.question or ""])
        with dbs.session() as db:
            d = matter_docs.for_question(db, c.user_id, c.matter_id, text, file_route=file_route)
        if d:
            print("MATTER_DOCS " + __import__("json").dumps({"files": len(d["docs"]), "handed": len(d["chosen"]), "meaning": d.get("meaning"),
                                                              "chars": sum(len(p["text"]) for p in d["chosen"])}), flush=True)        # counts only: no names, no text
        return d
    except Exception as exc:  # noqa: BLE001
        logger.warning("matter documents could not be read for a question: %s", type(exc).__name__)
        print("MATTER_DOCS " + __import__("json").dumps({"error": type(exc).__name__}), flush=True)
        return None


def _check_documents(c, out, docs):
    """After the answer: every quotation the answer attributes to a document and a page is looked for on that page of the document's whole read text (matter_files.check_quotes); the passages handed over and the
    notes go into result['matter_files'] for the box under the answer. Never changes the answer's text; fails open."""
    result = out.get("result") if isinstance(out.get("result"), dict) else None
    if result is None:
        return
    try:
        with dbs.session() as db:
            full = matter_docs.full_text(db, c.user_id, c.matter_id)
        text = result.get("response_text") or ""
        checks = MF.check_quotes(text, full) if text else []
        meta = {str(k): {"name": v["name"], "unit": v["unit"], "unread": v["unread"]} for k, v in docs["docs"].items()}
        notes = MF.quote_notes(checks, meta)
        cited = sorted({int(m.group(1)) for m in MF._CITE.finditer(text)})
        handed = docs.get("file_chosen") if (result.get("route") == "file" and docs.get("file_chosen")) else docs["chosen"]
        result["matter_files"] = {"docs": meta, "handed": [{"doc": p["doc"], "loc": p["loc"], "loc_to": p["loc_to"], "text": p["text"]} for p in handed], "coverage": result.pop("coverage", None) or "",
                                  "cited_docs": cited, "quote_checks": [{k: (list(v) if isinstance(v, tuple) else v) for k, v in r.items()} for r in checks], "notes": notes + list(result.pop("matter_files_engine_notes", []) or [])}
        print("MATTER_QUOTES " + __import__("json").dumps({"checked": len(checks), **{v: sum(1 for r in checks if r["verdict"] == v) for v in ("ok", "other_page", "other_doc", "not_in_file", "unknown_doc", "skipped_short")},
                                                            "cited_docs": len(cited)}), flush=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("matter documents check failed: %s", type(exc).__name__)


def _save(c, out, info):
    result = out.get("result") if isinstance(out.get("result"), dict) else {}
    state = result.get("state")
    counted = state in ANSWER_STATES
    cost = out.get("cost_inr")
    message_id, saved, usage = None, False, dict(c.usage)
    try:
        with dbs.session() as db:
            chat = db.execute(select(M.Chat).where(M.Chat.id == c.chat_id, M.Chat.user_id == c.user_id).with_for_update()).scalar_one_or_none()
            if chat is not None:
                dup = db.execute(select(M.Message.id).where(M.Message.chat_id == c.chat_id, M.Message.request_id == c.request_id)).first()
                if dup is None:
                    last = db.execute(select(func.coalesce(func.max(M.Message.seq), 0)).where(M.Message.chat_id == c.chat_id)).scalar()
                    now = datetime.datetime.now(datetime.timezone.utc)
                    db.add(M.Message(chat_id=c.chat_id, role="user", seq=last + 1, content=c.question, request_id=c.request_id))
                    am = M.Message(chat_id=c.chat_id, role="assistant", seq=last + 2, content=result.get("response_text") or "", result=out.get("result"), state=state,
                                   request_id=c.request_id, cost_inr=cost, style=_style(), engine_commit=_commit())
                    db.add(am)
                    chat.updated_at = now
                    if not chat.title:
                        chat.title = title_from(c.question)
                    if CF.enabled() and c.intent is None and state != "unrelated":          # the sentences the person typed join the case file (a tap's own words are not facts; small talk is not part of the matter)
                        chat.case_file = CF.add_from_message(chat.case_file, c.question)
                    db.flush()
                    message_id, saved = am.id, True
            quota.settle(db, c.event_id, cost, message_id)
            if not counted or not saved:
                quota.release(db, c.event_id)
                usage["used"] = max(0, usage.get("used", 1) - 1)
            db.commit()
    except Exception as exc:  # noqa: BLE001 -- the answer was made and paid for: it is still returned, flagged as not saved
        logger.warning("could not save a chat turn: %s", type(exc).__name__)
        saved, message_id = False, None
        try:
            with dbs.session() as db:
                quota.settle(db, c.event_id, cost, None)
                if not counted:
                    quota.release(db, c.event_id)
                    usage["used"] = max(0, usage.get("used", 1) - 1)
                db.commit()
        except Exception as exc2:  # noqa: BLE001
            logger.warning("could not settle a use: %s", type(exc2).__name__)
    reply = {**out, "chat_id": str(c.chat_id), "message_id": str(message_id) if message_id else None, "saved": saved, "usage": usage, "turn": info.get("turn")}
    try:
        if CF.enabled() and saved:
            with dbs.session() as db:
                chat = db.execute(select(M.Chat).where(M.Chat.id == c.chat_id, M.Chat.user_id == c.user_id)).scalar_one_or_none()
                if chat is not None:
                    reply["case_file"] = case_file_view(chat.case_file, turns_of(chat.messages), chat.audience)
    except Exception as exc:  # noqa: BLE001 -- the answer is returned without the panel's data
        logger.warning("could not read the case file back: %s", type(exc).__name__)
    return reply
