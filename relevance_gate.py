"""
relevance_gate.py -- a floor under what the library hands the answer model (added 2026-10-31; owner's item 1: "Point 4 is filler ... BNSS s.249 ... has nothing to do with circumstantial evidence").

THE PROBLEM. The library search keeps the closest statute sections and judgments by cosine similarity with a fixed floor (0.34 for sections, 0.40 for judgments). For a question that the library cannot answer, the closest sections
still clear that floor: for "Can a person be convicted on circumstantial evidence alone? What must the prosecution prove?" BNSS 249 (the prosecutor's opening in a sessions trial), BNSS 244, BNS 230 and BNSS 259 scored 0.42 to 0.44,
higher than the sections that are right for "What is the punishment for theft?" (0.55). Handed over, they become filler that the answer then builds on.

THE GATE. One cross-encoder re-ranking call (Voyage rerank-2, which reads the question and each section together) scores the matches that survived the cosine floor and the cap; a section below RELEVANCE_FLOOR_STATUTE (default 0.45) and a
judgment below RELEVANCE_FLOOR_JUDGMENT (default 0.40) is left out. On 28 questions written by Claude with a known right section (`review_results/2026-10-31_relevance_gate/`): all 24 right sections that the search finds are kept at 0.45
(their lowest score is 0.466); of 46 matches for 18 questions the statutes cannot answer, 32 are removed. The floor was set on these same questions: it is a first setting, not a validated one.

SWITCH RELEVANCE_GATE = off | log | on, default OFF (nothing changes, no call). `log` scores and writes a RELEVANCE_GATE line but keeps everything; `on` also removes. A section the person NAMED ("section 420 IPC") is trusted and never gated.
If the re-ranker is unavailable, nothing is removed. If the gate removes EVERYTHING for a question, the answer is still written, from the wider search alone (chat_assistant._answer_from_wider_search_only), instead of ending as
"not enough to go on": the padding used to keep such a question answerable, and removing it must not turn the question into a refusal.
It does not say that what is kept is right, only that what is dropped scored low. No hallucination rate has been measured.
"""
import json
import os
import threading

DEFAULT_STATUTE_FLOOR = 0.45
DEFAULT_JUDGMENT_FLOOR = 0.40
_LOCAL = threading.local()


def _env(name, default=""):
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().strip("\"'").strip()
    return v if v else default


def mode():
    m = _env("RELEVANCE_GATE", "off").lower()
    return m if m in ("off", "log", "on") else "off"


def _floor(name, default):
    try:
        return max(0.0, min(0.9, float(_env(name, str(default)))))
    except ValueError:
        return default


def floors():
    return _floor("RELEVANCE_FLOOR_STATUTE", DEFAULT_STATUTE_FLOOR), _floor("RELEVANCE_FLOOR_JUDGMENT", DEFAULT_JUDGMENT_FLOOR)


def reset():
    """Forget what the gate did for the previous question (called at the start of answer_question)."""
    _LOCAL.emptied = False


def emptied():
    """True when, in this question, the gate in mode `on` removed every library match that had cleared the cosine floors."""
    return bool(getattr(_LOCAL, "emptied", False))


def _label(m):
    if m.get("type") == "judgment" or m.get("case_name"):
        return (m.get("case_name") or "")[:80]
    return f'{m.get("act") or "?"} {m.get("section_number") or ""}'.strip()


def apply(question, statute_matches, judgment_matches, statutes_trusted=False, rerank_fn=None):
    """(statute_matches, judgment_matches) after the gate. Never raises; on any problem returns the lists as they were."""
    try:
        m = mode()
        if m == "off":
            return statute_matches, judgment_matches
        pool = [("statute", x) for x in statute_matches if not statutes_trusted] + [("judgment", x) for x in judgment_matches]
        pool = [(k, x) for k, x in pool if (x.get("text") or "").strip()]
        if not pool or not (question or "").strip():
            return statute_matches, judgment_matches
        if rerank_fn is None:
            import semantic_retrieval
            rerank_fn = semantic_retrieval.rerank
        ranked = rerank_fn(question, [(x.get("text") or "")[:1500] for _k, x in pool])
        if ranked is None:                                            # no re-ranker: nothing is removed
            return statute_matches, judgment_matches
        score = {}
        for item in ranked:
            i = item.get("index") if isinstance(item, dict) else getattr(item, "index", None)
            s = item.get("score", item.get("relevance_score")) if isinstance(item, dict) else getattr(item, "relevance_score", None)
            if i is not None and s is not None:
                score[int(i)] = float(s)
        f_st, f_ju = floors()
        keep_ids, report = set(), []
        for i, (k, x) in enumerate(pool):
            s = score.get(i)
            ok = True if s is None else s >= (f_st if k == "statute" else f_ju)
            if ok:
                keep_ids.add(id(x))
            report.append({"kind": k, "item": _label(x), "rerank": None if s is None else round(s, 3), "cosine": round(float(x.get("score", 0.0)), 3), "kept": ok})
        print("RELEVANCE_GATE " + json.dumps({"mode": m, "floors": {"statute": f_st, "judgment": f_ju}, "items": report}), flush=True)
        if m == "log":
            return statute_matches, judgment_matches
        gated = {id(x) for _k, x in pool}
        new_s = [x for x in statute_matches if id(x) not in gated or id(x) in keep_ids]
        new_j = [x for x in judgment_matches if id(x) not in gated or id(x) in keep_ids]
        if not new_s and not new_j and (statute_matches or judgment_matches):
            _LOCAL.emptied = True
        return new_s, new_j
    except Exception:  # noqa: BLE001
        return statute_matches, judgment_matches
