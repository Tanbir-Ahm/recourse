"""
judgment_corroboration.py

Automated, deterministic corroboration checks for a curated judgment
anchor -- run BEFORE a person is asked for final sign-off, not instead
of it. Design agreed with the user 2026-09-14, built directly in
response to a real gap: while sourcing PWDVA's judgment anchors, an AI
reading a judgment alone twice picked a plausible-looking but WRONG
passage before finding the real holding (confirmed while sourcing
Satish Chander Ahuja) -- a mistake that could easily have shipped
unnoticed. Neither check here lets an AI decide what a judgment means;
both are plain, deterministic text/count operations whose only job is
to make a human's final check faster and more confident, not to
replace it.

TWO INDEPENDENT CHECKS
----------------------
1. cross_source_check() -- does an INDEPENDENTLY SCRAPED copy of the
   SAME judgment (vaquill_search.py's local pool, built by a different
   organization with a different pipeline than Indian Kanoon) also
   contain the exact holding text? This catches a misquote or
   transcription slip -- it does NOT catch picking the wrong paragraph
   as "the holding", since a wrong-but-real quote would still be found
   verbatim in both copies.

2. citation_corroboration_check() -- do OTHER REAL, LATER documents
   that cite this case (found via Indian Kanoon's own search API,
   using the `headline` snippet field it already returns for free --
   no extra per-document fetch cost) independently describe the SAME
   holding when discussing it? THIS is the check that would have
   caught the Ahuja mistake: a citing document discussing the case for
   a different point produces a headline that does NOT match, while
   ones actually discussing the real holding do.

Neither check can ever mark something "verified" or "correct" on its
own -- they only ever report a corroboration COUNT for a person to
weigh, alongside the actual quoted evidence so the person can read it
themselves rather than trust a number. Zero corroboration is reported
honestly as "0 found", never treated as proof of an error (a very new
or obscure judgment may simply not be cited anywhere yet).
"""
import logging

logger = logging.getLogger(__name__)

_MAX_CITING_DOCS_TO_SCAN = 20


def _normalise(text: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = text.replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalise_for_fingerprint(text: str) -> str:
    """Like _normalise, but also strips common punctuation (commas,
    periods, quotes) before comparing two independently-scraped copies
    of the same judgment -- CONFIRMED REAL ISSUE (found by this
    module's own test suite): two real, correct copies of the same
    sentence can differ trivially in a comma or a quote mark purely from
    each organization's own scraping/OCR pipeline, which must never be
    mistaken for the holding text genuinely being absent."""
    import re
    text = _normalise(text)
    return re.sub(r"[,.\"'‘’“”]", "", text)


def _phrase_group_matches(text_lower: str, groups: list) -> bool:
    """A 'group' is a tuple of words that must ALL appear (in any order,
    anywhere in the text) for that group to count as a match -- same
    trigger-group convention already used throughout this project's
    doctrine maps, reused here for consistency."""
    for group in groups:
        if all(word.lower() in text_lower for word in group):
            return True
    return False


def cross_source_check(case_title_contains: str, holding_text: str, vaquill_db_path: str = None) -> dict:
    """Checks vaquill_search.py's local pool for an independently-scraped
    copy of the same judgment and confirms the holding text (or a
    substantial chunk of it) appears there too.

    Returns {'checked': bool, 'found_in_vaquill': bool | None,
             'vaquill_case_id': str | None}. 'found_in_vaquill' is None
    (not False) when no matching case was found in the local pool at
    all -- that's "we don't have an independent copy to check against",
    never "confirmed absent"."""
    import sqlite3
    import vaquill_search

    db_path = vaquill_db_path or vaquill_search.DB_PATH
    try:
        conn = sqlite3.connect(db_path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("cross_source_check: could not open %r: %s", db_path, exc)
        return {"checked": False, "found_in_vaquill": None, "vaquill_case_id": None}

    try:
        row = conn.execute(
            "SELECT case_id, full_text FROM fts WHERE title LIKE ?",
            (f"%{case_title_contains}%",),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {"checked": True, "found_in_vaquill": None, "vaquill_case_id": None}

    case_id, full_text = row
    # A meaningful chunk, not the whole (possibly long) holding -- the
    # first ~12 words are almost always enough to be a distinctive
    # fingerprint without being thrown off by minor whitespace/OCR
    # differences between the two independently-scraped copies.
    words = (holding_text or "").split()
    fingerprint = " ".join(words[:12])
    found = _normalise_for_fingerprint(fingerprint) in _normalise_for_fingerprint(full_text)
    return {"checked": True, "found_in_vaquill": found, "vaquill_case_id": case_id}


def citation_corroboration_check(case_name: str, key_phrase_groups: list, max_docs: int = _MAX_CITING_DOCS_TO_SCAN) -> dict:
    """Searches Indian Kanoon for other real documents mentioning
    `case_name`, and counts how many DISTINCT ones (by document id) have
    a headline snippet matching at least one group in
    `key_phrase_groups` -- i.e., independently describe the same
    holding when citing this case. Uses the search API's own free
    `headline` field (no extra per-document fetch, no extra cost beyond
    the one search call).

    Returns {'checked': bool, 'documents_scanned': int,
             'corroborating_documents': [{'title', 'court', 'matched_headline'}]}.
    Never raises -- a search failure returns checked=False with an
    empty list, not an exception."""
    import indiankanoon_client as ik

    try:
        result = ik.search(case_name)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("citation_corroboration_check: IK search failed for %r: %s", case_name, exc)
        return {"checked": False, "documents_scanned": 0, "corroborating_documents": []}

    docs = (result or {}).get("docs", [])[:max_docs]
    corroborating = []
    seen_tids = set()
    for d in docs:
        tid = d.get("tid")
        if tid in seen_tids:
            continue
        seen_tids.add(tid)
        headline = d.get("headline") or ""
        if _phrase_group_matches(_normalise(headline), key_phrase_groups):
            corroborating.append({
                "title": d.get("title"),
                "court": d.get("docsource"),
                "matched_headline": _normalise(headline)[:300],
            })

    return {
        "checked": True,
        "documents_scanned": len(seen_tids),
        "corroborating_documents": corroborating,
    }


# ---------------------------------------------------------------------------
# STRENGTHENED independent-extraction check, added 2026-09-14 after the user
# pointed out cross_source_check only confirms a quote is REAL, not that it
# is the RIGHT paragraph -- exactly the Ahuja mistake it was originally
# pitched (imprecisely) as catching. This is the honest fix: independently
# surface candidate holding passages from VAQUILL'S OWN text, using
# deterministic structural + keyword scoring that never looks at what was
# already picked from Indian Kanoon, then check whether the two agree.
# Real, not cosmetic, independence: a wrong IK pick would not automatically
# make Vaquill's independently-highest-scoring window agree with it.
# ---------------------------------------------------------------------------

_HOLDING_MARKERS = (
    "we hold", "we declare", "it is held", "we therefore", "we, therefore",
    "in view of the foregoing", "we answer", "we are of the view",
    "the appeal is allowed", "the appeal is dismissed", "stands deleted",
    "does not lay down", "has not correctly interpreted", "we conclude",
)
_WINDOW_SIZE = 400
_WINDOW_STRIDE = 200


def _score_window(window_lower: str, doctrine_keywords: list) -> int:
    score = sum(1 for m in _HOLDING_MARKERS if m in window_lower)
    score += sum(1 for kw in doctrine_keywords if kw.lower() in window_lower)
    return score


def independent_vaquill_candidates(case_title_contains: str, doctrine_keywords: list,
                                    max_candidates: int = 3, vaquill_db_path: str = None) -> dict:
    """Slides a fixed-size window across Vaquill's OWN full text (never
    looking at any paragraph already picked from Indian Kanoon) and scores
    each window by how many disposal/holding-style phrases AND
    doctrine-specific keywords it contains. Returns the top-scoring,
    non-overlapping windows -- an independently-derived guess at where the
    real holding sits, for comparison against whatever was picked from the
    other source. Deterministic, no LLM call -- Python decides via keyword
    counting, exactly the same kind of rule this project already trusts
    elsewhere (e.g. ik_triage's own disposal-marker scan)."""
    import sqlite3
    import vaquill_search

    db_path = vaquill_db_path or vaquill_search.DB_PATH
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT case_id, full_text FROM fts WHERE title LIKE ?", (f"%{case_title_contains}%",)
        ).fetchone()
        conn.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("independent_vaquill_candidates: could not query %r: %s", db_path, exc)
        return {"checked": False, "candidates": []}

    if row is None:
        return {"checked": True, "candidates": [], "vaquill_case_id": None}

    case_id, full_text = row
    text_norm = _normalise(full_text)
    scored = []
    for start in range(0, max(1, len(text_norm) - _WINDOW_SIZE), _WINDOW_STRIDE):
        window = text_norm[start:start + _WINDOW_SIZE]
        s = _score_window(window, doctrine_keywords)
        if s > 0:
            scored.append((s, start, window))

    # Collapse overlapping/adjacent high-scorers into one candidate each,
    # keeping the highest-scoring window per local peak rather than
    # returning near-duplicate overlapping windows.
    scored.sort(key=lambda t: (-t[0], t[1]))
    candidates, taken_starts = [], []
    for s, start, window in scored:
        if any(abs(start - t) < _WINDOW_SIZE for t in taken_starts):
            continue
        taken_starts.append(start)
        candidates.append({"score": s, "text": window})
        if len(candidates) >= max_candidates:
            break

    return {"checked": True, "candidates": candidates, "vaquill_case_id": case_id}


def independent_agreement_check(case_title_contains: str, holding_text: str, doctrine_keywords: list,
                                 min_shared_words: int = 5) -> dict:
    """Compares the ORIGINAL pick (from Indian Kanoon) against candidates
    independently surfaced from Vaquill's own text (see
    independent_vaquill_candidates -- computed with NO knowledge of
    holding_text).

    CONFIRMED REAL LIMITATION, found testing this against Satish Chander
    Ahuja (the actual case that caused the original mistake) -- a much
    deeper one than expected: an overruling judgment quotes the OLD,
    now-rejected rule almost verbatim right before rejecting it, and the
    correct rule is often stated as a direct NEGATION using nearly the
    SAME words ("shared household CANNOT be read to mean X" vs the old
    rule's "shared household would ONLY mean X"). Confirmed live: both
    the real holding and the rejected old rule matched this function's
    best-matching-rank at rank 1 -- plain word-overlap matching cannot
    tell a sentence apart from its own negation, since "not" is a single
    word buried among a dozen shared ones. This is a genuine limit of
    any non-semantic (keyword/word-overlap) check, not a bug to patch
    away -- and it is NOT this project's job to reach for an LLM to
    settle it, since that would be exactly the "AI decides what the law
    means" step this whole architecture refuses to take.

    CONSEQUENCE FOR HOW THIS RESULT MUST BE USED: 'best_matching_rank'
    is a genuinely useful signal for NARROWING a 40,000-character
    judgment down to a handful of short, independently-surfaced
    candidate passages worth a person's 30 seconds -- it is NOT a
    verdict, and must never be shown or treated as "agrees == safe to
    skip reading". The review UI built from this always shows the
    candidate text itself alongside the rank, precisely so a human can
    catch exactly this kind of negation flip that the number alone
    cannot."""
    result = independent_vaquill_candidates(case_title_contains, doctrine_keywords)
    if not result["checked"]:
        return {"checked": False, "best_matching_rank": None, "candidates": []}

    holding_words = _normalise_for_fingerprint(holding_text).split()
    best_rank = None
    if len(holding_words) >= min_shared_words:
        for rank, candidate in enumerate(result["candidates"], start=1):
            candidate_norm = _normalise_for_fingerprint(candidate["text"])
            for i in range(len(holding_words) - min_shared_words + 1):
                fragment = " ".join(holding_words[i:i + min_shared_words])
                if fragment in candidate_norm:
                    best_rank = rank
                    break
            if best_rank is not None:
                break

    return {"checked": True, "best_matching_rank": best_rank, "candidates": result["candidates"]}


def full_corroboration_report(case_title_contains: str, case_name_for_search: str,
                               holding_text: str, key_phrase_groups: list,
                               doctrine_keywords: list = None) -> dict:
    """Runs all checks and returns one combined, human-readable report
    -- the thing actually meant to be shown to a person before they
    sign off on a new anchor, per the review process agreed 2026-09-14."""
    cross = cross_source_check(case_title_contains, holding_text)
    citation = citation_corroboration_check(case_name_for_search, key_phrase_groups)
    report = {"cross_source": cross, "citation_corroboration": citation}
    if doctrine_keywords:
        report["independent_agreement"] = independent_agreement_check(
            case_title_contains, holding_text, doctrine_keywords
        )
    return report
