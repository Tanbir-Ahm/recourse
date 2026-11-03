"""
statute_widen.py -- STATUTE_WIDEN=off|log|on (default off; written 2026-11-03 on the owner's "Yes, measure the misses and fix the common ones"; research repository FOLLOW_UPS item 2dg).

THE MISS IT CLOSES. The library search keeps a section only if it is within 0.08 of the best section's cosine score AND among the first five. A section that the question is plainly about is often just outside that:
on the 65 development questions it was ranked 3rd to 7th by cosine and was cut by the 0.08 rule or the cap of five (BNSS 187 for "kept at the police station more than 24 hours", BNSS 483, BNSS 250, BNS 189, BNSS 359), while a
cross-encoder that reads the question and the section TOGETHER scored it 0.62 to 0.78. On the 48 frozen questions 9 of the 11 missed BNS/BNSS sections were ranked 15th or better by cosine. Nothing here makes the closest
sections any less likely to arrive: it only ADDS.

WHAT IT DOES. After the usual selection, take the closest `STATUTE_WIDEN_POOL` (default 10) statute sections by cosine that cleared the usual floor (0.34) and were not selected; score them once with the Voyage re-ranker
(rerank-2, the model the relevance gate uses); add at most `STATUTE_WIDEN_MAX` (default 2) of them, in cosine order, whose re-ranker score is at least `STATUTE_WIDEN_FLOOR` (default 0.55). The added sections are marked
retrieval 'widened'. The conflict state is computed BEFORE they are added, so a question never changes between single and conflicting matches because of them.

WHAT IT DOES NOT DO. It does not find a section whose wording shares nothing with the question's (quashing an FIR is BNSS 528, "Saving of inherent powers of the High Court"; that section ranked 83rd and 119th): that is the
far-miss class, not touched here. It does not say the added section is right: a neighbour in the same chapter can pass the floor (BNS 192, 193, 195 beside 191). It costs one re-rank call per question (a few thousand tokens).
The settings were chosen on the 65 development questions and the 48 frozen questions together (on the development questions alone every floor from 0.50 to 0.60 recovers the same 5 of 9; the frozen narrative questions score lower with the
cross-encoder and 0.55 recovers 4 of 11 where 0.60 recovers 2 and 0.50 no more than 0.55); a third set of 36 questions, written after the floor was fixed, is the only unseen test. A section the person NAMED is trusted and
nothing is added. If the re-ranker is unavailable nothing is added. No hallucination rate has been measured.

SWITCH: STATUTE_WIDEN = off (default; nothing changes, no call) | log (scores and writes a STATUTE_WIDEN line, adds nothing) | on.
"""
import hashlib
import json
import os


def _env(name, default=""):
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().strip("\"'").strip()
    return v if v else default


def mode():
    m = _env("STATUTE_WIDEN", "off").lower()
    return m if m in ("off", "log", "on") else "off"


def _num(name, default, lo, hi, cast=float):
    try:
        return max(lo, min(hi, cast(_env(name, str(default)))))
    except ValueError:
        return default


def settings():
    """(pool, max_added, floor) from the environment; out-of-range values are pulled back into a sane range."""
    return (_num("STATUTE_WIDEN_POOL", 10, 3, 30, int), _num("STATUTE_WIDEN_MAX", 2, 0, 5, int), _num("STATUTE_WIDEN_FLOOR", 0.55, 0.3, 0.95))


def _key(m):
    return ((m.get("act") or "").upper(), str(m.get("section_number") or "").upper())


def widen(question, results, kept, statute_floor=0.34, rerank_fn=None):
    """([added statute matches], info) for `question`. `results` is the search's full list (best first), `kept` the statute matches already selected. Never raises; ([], info) on any problem or when off."""
    info = {"mode": mode(), "pool": 0, "added": [], "rerank": "skipped"}
    try:
        if info["mode"] == "off" or not (question or "").strip():
            return [], info
        pool_n, max_add, floor = settings()
        if max_add <= 0:
            return [], info
        # the pool counts the closest sections by cosine whether or not they were kept: a kept one is one of the `pool_n`, not an extra place
        top = []
        for r in results or []:
            if isinstance(r, dict) and r.get("type") == "statute" and (r.get("text") or "").strip() and float(r.get("score") or 0) >= statute_floor:
                top.append(r)
            if len(top) >= pool_n:
                break
        have = {_key(m) for m in kept or []}
        cand = [r for r in top if _key(r) not in have]
        info["pool"] = len(cand)
        if not cand:
            return [], info
        if rerank_fn is None:
            import semantic_retrieval
            rerank_fn = semantic_retrieval.rerank
        ranked = rerank_fn(question, [(r.get("text") or "")[:1500] for r in cand])
        if ranked is None:
            info["rerank"] = "unavailable"
            return [], info
        info["rerank"] = "ok"
        scores = {}
        for it in ranked:
            idx = it.get("index") if isinstance(it, dict) else getattr(it, "index", None)
            sc = it.get("score", it.get("relevance_score")) if isinstance(it, dict) else getattr(it, "relevance_score", None)
            if idx is not None and sc is not None:
                scores[int(idx)] = float(sc)
        added = []
        for i, r in enumerate(cand):                                   # cosine order; the re-ranker only decides whether a section is allowed in
            sc = scores.get(i)
            if sc is None or sc < floor:
                continue
            m = dict(r)
            m["retrieval"] = "widened"
            m["widen_rerank"] = round(sc, 4)
            added.append(m)
            if len(added) >= max_add:
                break
        info["added"] = [{"act": m.get("act"), "sec": str(m.get("section_number")), "cos": round(float(m.get("score") or 0), 3), "rr": m["widen_rerank"]} for m in added]
        info["floor"] = floor
        return (added if info["mode"] == "on" else []), info
    except Exception as exc:  # noqa: BLE001 -- never lets a failure here touch an answer
        info["error"] = repr(exc)[:120]
        return [], info


def log(question, info):
    """One STATUTE_WIDEN line per question when the switch is on or log and something was scored."""
    try:
        if info.get("mode") in ("log", "on") and info.get("pool"):
            q = hashlib.sha1((question or "").encode("utf-8", "ignore")).hexdigest()[:12]
            print("STATUTE_WIDEN " + json.dumps({"q": q, **info}, ensure_ascii=False), flush=True)
    except Exception:  # noqa: BLE001
        pass
