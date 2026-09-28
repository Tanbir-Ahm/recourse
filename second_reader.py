"""
second_reader.py -- an automatic, BLIND, different-model second reader for a judgment summary.

WHY: every real mistake caught while adding pilot cases was about MEANING, not wording (a statistic
credited to the wrong commission; a fact named as the reason for a ruling when it wasn't; two "key
quotes" that were the Court quoting other cases). A word-for-word quote check can't catch those; a second
reader can. This is the automatic version of what the person building Recourse does by hand with ChatGPT.

HOW: (1) the reader reads the OFFICIAL text alone, before seeing our summary, and lists its own key points
with exact quotes and whose words they are; (2) it then checks our numbered claims and numbered quotes against
the text; (3) CODE checks every quote the reader returns against the official text -- a verdict resting on a
quote that isn't really there is marked UNVERIFIED, so an invented quote can't pass. The reader is a different
model family from the one that wrote the summary (Gemini's free tier), which is the point: it doesn't share
the same blind spots.

WHAT IT NEVER DOES: approve anything, rewrite the summary, or state what the law is. It produces FLAGS for a
person to read. If no model answers (free-tier throttling, retired models), that is reported as "reader
unavailable -- NOT a pass", never as a pass.

Only public judgment text and our own claims are ever sent -- Google's free tier may use content to improve
its products, so nothing private (no user conversations) may ever be passed to this module.
"""
import json
import os
import re
import time

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Checked against the live API 2026-09-28: models that are LISTED are not always usable (2.5 Flash returned
# 404 "no longer available to new users"), and the free tier answers 503 "high demand" from time to time --
# hence a chain, and retries, rather than one hard-coded model.
MODEL_CHAIN = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_TRIES_PER_MODEL = 2
BACKOFF_SECONDS = (2.0, 6.0)
COURT_OWN = "court's own reasoning"


class ReaderUnavailable(Exception):
    """No model in the chain produced a usable answer. Reported as NOT a pass."""


def _api_key():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return os.environ.get("GEMINI_API_KEY")


def _parse_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    return json.loads(t)


def call_gemini(prompt: str, *, models=None, api_key=None, post=None, sleep=time.sleep, timeout=240):
    """Returns (parsed_json, model_used, usage). Retries transient errors, skips models that are gone,
    falls through the chain, raises ReaderUnavailable if nothing works. The key is sent in a header and is
    never included in any message or error."""
    key = api_key or _api_key()
    if not key:
        raise ReaderUnavailable("no GEMINI_API_KEY in the environment/.env")
    post = post or requests.post
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    errors = []
    for model in (models or MODEL_CHAIN):
        for attempt in range(MAX_TRIES_PER_MODEL):
            try:
                r = post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=timeout)
            except requests.RequestException as exc:
                errors.append(f"{model}: {type(exc).__name__}")
                sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            if r.status_code == 200:
                data = r.json()
                try:
                    parts = data["candidates"][0]["content"]["parts"]
                    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                    return _parse_json(text), model, data.get("usageMetadata")
                except (KeyError, IndexError, ValueError, TypeError):
                    errors.append(f"{model}: unusable answer")
                    break
            errors.append(f"{model}: HTTP {r.status_code}")
            if r.status_code in RETRY_STATUS:
                sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            break
    raise ReaderUnavailable("; ".join(errors[-8:]))


BLIND_PROMPT = """You are reading a Supreme Court of India judgment. Use ONLY the text between the markers. Do not use anything you remember about this case.

Return JSON only, with exactly these keys:
{{
  "parties": "...",
  "bench_and_author": "...",
  "dissent": "none, or describe it",
  "final_order": "what the Court finally ordered",
  "key_points": [
    {{"point": "one sentence", "quote": "exact copy of the sentence(s) in the text that support it",
      "whose_words": "{court_own} | quotation of an earlier case, statute or counsel",
      "quoted_source": "name of the case/statute/person being quoted, else empty"}}
  ],
  "exceptions_or_counterpoints": [ {{"point": "...", "quote": "exact copy"}} ]
}}
Give the 5 to 8 most important key_points. Every quote must be copied exactly, character for character, from the text; never paraphrase inside a quote.

=== JUDGMENT TEXT ===
{text}
=== END OF JUDGMENT TEXT ==="""

COMPARE_PROMPT = """Below are: a judgment text; a summary someone else wrote, as numbered CLAIMS; numbered QUOTES they intend to rely on; and your own earlier reading. Assume the claims may contain mistakes. Check each claim against the judgment text ONLY.

Return JSON only:
{{
  "claims": [ {{"id": 1, "verdict": "SUPPORTED | NOT_SUPPORTED | MISLEADING", "reason": "one sentence",
               "quote": "exact copy of the sentence in the text that decides it"}} ],
  "quotes": [ {{"id": 1, "found_in_text": true, "whose_words": "{court_own} | quotation of an earlier case, statute or counsel",
               "quoted_source": "who is being quoted, else empty", "evidence": "exact copy of nearby words that show this"}} ],
  "missing_important_points": [ {{"point": "...", "quote": "exact copy"}} ]
}}
Rules:
- SUPPORTED only if a sentence in the text says it. Never answer SUPPORTED without a quote.
- MISLEADING if it is partly right but wrongly attributed, overstated, or leaves out a condition that changes its meaning.
- NOT_SUPPORTED if the text does not say it or says the opposite.
- A sentence the Court is quoting from another case, statute or counsel is NOT the Court's own holding -- say so.
- Every quote you give must be an exact copy from the text.

=== JUDGMENT TEXT ===
{text}
=== CLAIMS ===
{claims}
=== QUOTES ===
{quotes}
=== YOUR EARLIER READING (may be incomplete) ===
{blind}
=== END ==="""


def _numbered(items) -> str:
    return "\n".join(f"{i}. {s}" for i, s in enumerate(items, 1)) or "(none)"


def run_second_reader(*, official_text, claims, quotes=(), models=None, api_key=None, post=None, sleep=time.sleep) -> dict:
    """Two calls: the blind reading, then the claim-by-claim check. Raises ReaderUnavailable if either fails."""
    blind, m1, u1 = call_gemini(BLIND_PROMPT.format(text=official_text, court_own=COURT_OWN),
                                models=models, api_key=api_key, post=post, sleep=sleep)
    comp, m2, u2 = call_gemini(
        COMPARE_PROMPT.format(text=official_text, claims=_numbered(claims), quotes=_numbered(quotes),
                              blind=json.dumps(blind, ensure_ascii=False), court_own=COURT_OWN),
        models=models, api_key=api_key, post=post, sleep=sleep)
    return {"models": [m1, m2], "usage": [u1, u2], "blind": blind, "compare": comp}


def _qstatus(quote, text, check_fn) -> str:
    """Status of a reader-supplied quote. A quote stitched together with '...' is checked piece by piece
    (the reader often joins two nearby passages); only pieces long enough to mean something are counted,
    and the WORST piece decides -- so one invented piece can't hide behind a real one."""
    if not isinstance(quote, str) or not quote.strip():
        return "none"
    pieces = [p for p in re.split(r"\.{3,}|…", quote) if sum(ch.isalnum() for ch in p) >= 20]
    if not pieces:
        return "too_short"
    rank = {"exact": 0, "cosmetic": 1, "too_short": 2, "missing": 3}
    worst = "exact"
    for p in pieces:
        st = check_fn(p.strip(), text)["status"]
        if rank.get(st, 3) > rank[worst]:
            worst = st
    return worst


def audit_result(result: dict, official_text: str, claims, quotes=(), check_fn=None) -> dict:
    """Turns the reader's raw answer into flags -- checking every quote it gave against the official text so a
    made-up quote can't back up a verdict."""
    if check_fn is None:
        from add_pilot_case import check_quote as check_fn
    comp = result.get("compare") or {}
    blind = result.get("blind") or {}
    by_id = {c.get("id"): c for c in comp.get("claims", []) if isinstance(c, dict)}
    claim_rows, flagged = [], []
    for i, claim in enumerate(claims, 1):
        c = by_id.get(i)
        if not c:
            claim_rows.append({"id": i, "claim": claim, "verdict": "NO_ANSWER", "reason": "the reader did not answer this claim",
                               "quote": "", "quote_status": "none", "trusted": False})
            flagged.append(i)
            continue
        verdict = str(c.get("verdict", "")).upper().strip()
        qs = _qstatus(c.get("quote"), official_text, check_fn)
        trusted = verdict == "SUPPORTED" and qs in ("exact", "cosmetic")
        if verdict == "SUPPORTED" and not trusted:
            verdict = "UNVERIFIED"
            c = {**c, "reason": (c.get("reason") or "") + " [the reader's supporting quote is not in the official text]"}
        claim_rows.append({"id": i, "claim": claim, "verdict": verdict, "reason": c.get("reason", ""),
                           "quote": c.get("quote", ""), "quote_status": qs, "trusted": trusted})
        if not trusted:
            flagged.append(i)
    qmap = {q.get("id"): q for q in comp.get("quotes", []) if isinstance(q, dict)}
    quote_rows, quote_flags = [], []
    for i, q in enumerate(quotes, 1):
        r = qmap.get(i, {})
        whose = str(r.get("whose_words", "")).strip()
        own = whose.lower().startswith("court")
        quote_rows.append({"id": i, "quote": q, "whose_words": whose or "no answer", "quoted_source": r.get("quoted_source", ""),
                           "evidence": r.get("evidence", ""), "court_own": own})
        if not own:
            quote_flags.append(i)
    missing = []
    for m in comp.get("missing_important_points", []) or []:
        if isinstance(m, dict) and m.get("point"):
            missing.append({"point": m["point"], "quote": m.get("quote", ""), "quote_status": _qstatus(m.get("quote"), official_text, check_fn)})
    blind_points = [p for p in (blind.get("key_points") or []) if isinstance(p, dict)]
    unverifiable = sum(1 for p in blind_points if _qstatus(p.get("quote"), official_text, check_fn) not in ("exact", "cosmetic"))
    return {"models": result.get("models"), "claims": claim_rows, "flagged_claims": flagged,
            "supported_verified": sum(1 for r in claim_rows if r["trusted"]), "claims_total": len(claims),
            "quotes": quote_rows, "quotes_not_courts_own": quote_flags, "missing_points": missing,
            "blind_points": len(blind_points), "blind_quotes_not_found": unverifiable,
            "blind_final_order": blind.get("final_order", ""), "blind_dissent": blind.get("dissent", "")}


def format_report(audit: dict) -> list:
    lines = [f"Second reader (blind, different model: {', '.join(sorted(set(m for m in audit['models'] if m)))}):",
             f"  Claims confirmed with a quote that is really in the text: {audit['supported_verified']} of {audit['claims_total']}"]
    for r in audit["claims"]:
        if not r["trusted"]:
            lines.append(f"  FLAG claim {r['id']} [{r['verdict']}]: {r['claim'][:110]}")
            lines.append(f"       reader says: {r['reason'][:200]}")
            if r["quote"]:
                lines.append(f"       its quote ({r['quote_status']}): \"{r['quote'][:160]}\"")
    for r in audit["quotes"]:
        if not r["court_own"]:
            lines.append(f"  FLAG quote {r['id']}: these are NOT the Court's own words ({r['whose_words']}"
                         + (f": {r['quoted_source']}" if r["quoted_source"] else "") + f") -- \"{r['quote'][:90]}...\"")
    for m in audit["missing_points"]:
        lines.append(f"  MISSING from the summary ({m['quote_status']} quote): {m['point'][:180]}")
    lines.append(f"  Its own blind reading: {audit['blind_points']} key points, {audit['blind_quotes_not_found']} with a quote NOT found in the text; "
                 f"dissent: {str(audit['blind_dissent'])[:60]}")
    lines.append("  These are flags for a person to read; the reader never approves anything.")
    return lines
