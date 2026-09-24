"""
judgment_promotion_assistant.py

Cuts the human time needed to promote a pilot-tier judgment (pilot_tier_search.py's wider, only
identity-verified pool) into the fully-trusted core corpus (judgment_doctrine_map.py's curated
anchors) -- WITHOUT cutting the actual verification step. Built 2026-09-24 at the user's explicit
request, after promoting Jagrup Singh v State of Haryana by hand (reading all 8 pages cold) worked
but doesn't scale: the user asked for an innovative way to grow the corpus faster while keeping
the core idea -- nothing is ever cited as authority unless a person confirmed it actually says so
-- fully intact.

WHAT THIS DOES AND DOES NOT DO
-------------------------------
An LLM (Sonnet) reads the full judgment text and drafts three things: a one-paragraph plain-
English summary of the core holding, a claimed VERBATIM quote of the passage that supports it, and
some suggested trigger phrases a real user might type. None of that draft is trusted as-is:

1. _verify_quote_is_real() deterministically checks the claimed quote against the REAL source
   text (whitespace-normalised, since a scanned judgment PDF line-wraps irregularly) -- not the
   LLM's memory of the text, the actual text. A quote that isn't really there -- fabricated,
   misremembered, or subtly altered -- is rejected outright and the whole draft is flagged
   REJECTED. This is the same discipline as chat_assistant._find_ungrounded_sections: the LLM
   proposes, Python verifies, and a claim that fails verification is never shown as if it passed.

2. _independent_holding_candidates() is a SECOND, fully independent, non-LLM pass over the same
   text -- sliding-window + holding-marker keyword scoring, the exact technique
   judgment_corroboration.py already uses and already learned the hard way not to over-trust (see
   that module's own docstring on the Satish Chander Ahuja mistake, and independent_agreement_
   check's explicit warning: agreement is a narrowing aid for a human's 30 seconds, NEVER a
   verdict, and the candidate text itself must always be shown alongside any score, precisely
   because two passages can share almost every word and mean the opposite thing -- a rule stated
   with a "not" the word-count alone cannot see). Reused here as a second corroboration pass; it
   does not decide anything either.

3. What comes out is a REPORT, not a promotion. A person reads the summary, reads the ACTUAL
   quoted text (not just the LLM's characterisation of it), and only then decides by hand whether
   to promote -- copying the chunk file into chunks/ and writing the judgment_doctrine_map.py
   entry remain separate, deliberate, human-done steps, exactly as they were for Jagrup Singh. This
   module has no function that writes to either location -- it cannot promote anything on its own,
   by construction, not just by convention.

A rejected draft (unverifiable quote, or an API failure) is never silently dropped -- it's reported
honestly, with the reason, so a person reviewing a batch knows which cases still need a from-
scratch read (or simply aren't a clean fit for promotion right now) rather than assuming silence
means success.

Run standalone: python judgment_promotion_assistant.py
(drafts a report for every case in pilot_corpus/ that pilot_chunks/ also has chunks for)
"""
import json
import logging
import os
import re

logger = logging.getLogger("judgment_promotion_assistant")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from anthropic import Anthropic

_api_key = os.environ.get("ANTHROPIC_API_KEY")
client = Anthropic(api_key=_api_key) if _api_key else None

SONNET_MODEL = "claude-sonnet-5"

_DRAFT_PROMPT = """You are helping a person review whether a Supreme Court of India judgment is a clean fit to \
cite as legal authority. Read the full judgment text below and identify its ONE core holding most relevant to \
criminal law/procedure (the kind of point a layperson's arrest/FIR question might turn on).

Return ONLY a JSON object with exactly these keys, nothing else, no markdown fences:
{{
  "summary": "one plain-English paragraph describing what the court actually decided",
  "quote": "the EXACT text of the passage that supports this holding, copied character-for-character from the \
judgment below -- do not paraphrase, summarise, or fix apparent typos/OCR artifacts, copy it exactly as it appears",
  "suggested_triggers": ["a few short phrases a real person describing this situation might actually type"]
}}

If the judgment's excerpt only contains background facts (what a party alleged) and no real court holding, say so \
honestly in "summary" and leave "quote" as an empty string rather than inventing one.

The judgment:
{text}
"""


def _extract_text_from_response(response) -> str:
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


_WS_RE = re.compile(r"\s+")


def _normalise_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip()).lower()


def _verify_quote_is_real(quote: str, source_text: str) -> bool:
    """Deterministic grounding check: is `quote` actually present in `source_text`, allowing for
    the whitespace/line-wrap differences a scanned judgment PDF always has, but NOT allowing any
    other difference (a changed word, section number, or negation must fail this check). Empty
    quotes are never verified -- an honest "I couldn't find a clean holding" must never be silently
    treated as a pass."""
    quote_norm = _normalise_ws(quote)
    if not quote_norm:
        return False
    return quote_norm in _normalise_ws(source_text)


# Reused from judgment_corroboration.py's independent_vaquill_candidates -- same deterministic,
# no-LLM sliding-window + holding-marker scoring technique, applied here to the pilot judgment's
# own full text instead of a second independently-scraped copy (this tool has no second source to
# cross-check against; the value here is a SECOND, LLM-blind METHOD looking at the same text, not a
# second copy of the text).
_HOLDING_MARKERS = (
    "held:", "we hold", "we declare", "it is held", "we therefore", "we, therefore",
    "in view of the foregoing", "we answer", "we are of the view", "the appeal is allowed",
    "the appeal is dismissed", "stands deleted", "does not lay down",
    "has not correctly interpreted", "we conclude", "the conviction is altered",
    "cannot be sustained", "all the requirements", "the ingredients",
)
_WINDOW_SIZE = 400
_WINDOW_STRIDE = 200


def _independent_holding_candidates(text: str, max_candidates: int = 3) -> dict:
    """Independently (no LLM, no knowledge of any quote already drafted) surfaces the highest-
    scoring windows of `text` by counting holding-marker phrases. A corroboration SIGNAL only --
    see this module's docstring and judgment_corroboration.independent_agreement_check's own
    warning against treating agreement as a verdict. Never raises; returns {'candidates': []} for
    text with no marker language at all, honestly, rather than guessing."""
    text_norm = _normalise_ws(text)
    scored = []
    for start in range(0, max(1, len(text_norm) - _WINDOW_SIZE), _WINDOW_STRIDE):
        window = text_norm[start:start + _WINDOW_SIZE]
        score = sum(1 for m in _HOLDING_MARKERS if m in window)
        if score > 0:
            scored.append((score, start, window))

    scored.sort(key=lambda t: (-t[0], t[1]))
    candidates, taken_starts = [], []
    for score, start, window in scored:
        if any(abs(start - t) < _WINDOW_SIZE for t in taken_starts):
            continue
        taken_starts.append(start)
        candidates.append({"score": score, "text": window})
        if len(candidates) >= max_candidates:
            break
    return {"candidates": candidates}


def _locate_source_paragraphs(quote: str, chunks: list) -> list:
    """Given a quote already confirmed real (via _verify_quote_is_real against the full text),
    finds which chunk(s) actually contain it, so a promoted doctrine-map entry can cite real,
    resolvable paragraph_number values (the same labels retrieval.get_judgment_paragraphs reads).
    Returns [] honestly if no single chunk contains the quote whole (e.g. it straddles a chunk
    boundary) -- never guesses a paragraph number."""
    quote_norm = _normalise_ws(quote)
    if not quote_norm:
        return []
    found = []
    for c in chunks:
        if quote_norm in _normalise_ws(c.get("text", "")):
            found.append(c["paragraph_number"])
    return found


# ---------------------------------------------------------------------------
# THREE STRENGTHENINGS, added 2026-09-24 after the user asked the right hard question: quote-
# verification only proves a quote is REAL, not that it's the RIGHT passage, not that the summary
# fairly represents it, and not that the case is still good law. None of these three close that gap
# fully -- nothing here replaces a person actually reading the quote in context before promoting --
# but each removes one specific, real blind spot from the earlier version of this tool.
# ---------------------------------------------------------------------------


def _context_paragraphs(source_paragraph_numbers: list, chunks: list) -> dict:
    """Surfaces the chunk immediately BEFORE and AFTER the matched paragraph(s), by their plain
    position in `chunks` (chunks are stored in original judgment page order) -- purely mechanical,
    no LLM involved. CONFIRMED REAL GAP this closes: quote-verification alone never showed whether
    the very next sentence reverses or qualifies what the quote says (e.g. a court restating an old
    rule immediately before rejecting it) -- a reviewer needs to see the neighbours, not just the
    isolated quote, to catch that. Returns {'before': [...], 'after': [...]}, each a list of
    {paragraph_number, text} (empty, honestly, when the match is the very first/last chunk)."""
    if not source_paragraph_numbers:
        return {"before": [], "after": []}
    indices = [i for i, c in enumerate(chunks) if c["paragraph_number"] in source_paragraph_numbers]
    if not indices:
        return {"before": [], "after": []}
    first_idx, last_idx = min(indices), max(indices)
    before = [chunks[first_idx - 1]] if first_idx > 0 else []
    after = [chunks[last_idx + 1]] if last_idx < len(chunks) - 1 else []
    return {
        "before": [{"paragraph_number": c["paragraph_number"], "text": c["text"]} for c in before],
        "after": [{"paragraph_number": c["paragraph_number"], "text": c["text"]} for c in after],
    }


# Broader than _HOLDING_MARKERS above on purpose: that list is tuned for a sliding-window
# CORROBORATION scan across a whole judgment (some false negatives there are fine, since it's only
# ever a soft count). This one is checked against a SINGLE, ALREADY-CHOSEN quote, where a false
# negative is more costly -- CONFIRMED REAL FINDING: the narrower list matched 0 of 5 real,
# genuinely-good quotes from the actual first pilot batch (Anwarul Haq, Hori Lal, Nanda Gopalan,
# Prabhu, Pravat Chandra Mohanty all use ordinary appellate disposition language -- "rightly
# convicted", "essential ingredients", "no ground to interfere" -- that the narrower list never
# anticipated). Even broadened, this is still just a keyword list and WILL miss real holdings
# phrased unusually -- it is a soft flag for extra scrutiny, never a rejection on its own.
_QUOTE_HOLDING_MARKERS = _HOLDING_MARKERS + (
    "held that", "we find", "we do not find", "conviction is upheld", "conviction is set aside",
    "rightly convicted", "wrongly convicted", "essential ingredients", "in our view", "in our opinion",
    "we are satisfied", "we are not satisfied", "cannot be said", "cannot interfere",
    "no ground to interfere", "reduction in sentence", "conviction cannot", "leave to compound",
    "grant of leave", "is liable to be", "is not sustainable", "is sustainable",
)


def _quote_has_holding_language(quote: str) -> bool:
    """Does the verified quote itself contain ordinary disposition/holding language, as opposed to
    reading like pure narrative or background fact? A SOFT check only -- any fixed keyword list
    will miss real holdings phrased unusually (confirmed: even this broadened list would have
    missed some real quotes before broadening), so a False here means 'look more carefully', not
    'this is wrong'. Never used to auto-reject on its own."""
    q = _normalise_ws(quote)
    return any(m in q for m in _QUOTE_HOLDING_MARKERS)


def _detect_old_code_references(quote: str) -> list:
    """Mechanical only, via statute_concordance.scan_old_refs (already built and proven elsewhere
    this project) -- surfaces any old IPC/CrPC section the quote names and its real modern BNS/BNSS
    number, so a reviewer doesn't have to manually spot and look up each one (the way Jagrup Singh's
    IPC 300->BNS 101 / IPC 304->BNS 105 conversion was done by hand). This is DELIBERATELY NOT a
    "is this still good law" check -- citation_currency.py is explicit that whether a case has been
    overruled or distinguished is a human research question no code may decide; this only automates
    the separate, genuinely mechanical half (what is this section called now). Best-effort, not
    exhaustive: scan_old_refs only tags a number when the act name sits close to it in the text, so
    "Section 326 read with Section 34 IPC" resolves the 34 but not the 326 -- a known, pre-existing
    limitation of that module, not something this tool works around."""
    import statute_concordance
    try:
        return statute_concordance.scan_old_refs(quote)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("_detect_old_code_references failed: %s", exc)
        return []


def draft_promotion(case_name: str, citation: str, full_text: str, chunks: list) -> dict:
    """The main entry point. Produces a REPORT for a person to read -- never promotes anything
    itself (see this module's docstring). Always returns a dict with at least 'rejected' (bool);
    never raises, even on an API failure -- a failure is an honest rejected report with 'error'
    set, not a crashed batch."""
    if client is None:
        return {"case_name": case_name, "rejected": True, "error": "no Anthropic client configured (ANTHROPIC_API_KEY missing)"}

    try:
        response = client.messages.create(
            model=SONNET_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": _DRAFT_PROMPT.format(text=full_text)}],
        )
        raw = _extract_text_from_response(response).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        draft = json.loads(raw)
    except Exception as exc:
        logger.warning("draft_promotion: LLM call/parse failed for %r: %s", case_name, exc)
        return {"case_name": case_name, "rejected": True, "error": f"LLM draft failed: {exc}"}

    quote = draft.get("quote", "") or ""
    verified = _verify_quote_is_real(quote, full_text)
    source_paragraphs = _locate_source_paragraphs(quote, chunks) if verified else []
    independent = _independent_holding_candidates(full_text)
    context = _context_paragraphs(source_paragraphs, chunks)
    holding_language = _quote_has_holding_language(quote) if verified else False
    old_code_refs = _detect_old_code_references(quote) if verified else []

    return {
        "case_name": case_name,
        "citation": citation,
        "summary": draft.get("summary", ""),
        "quote": quote,
        "suggested_triggers": draft.get("suggested_triggers", []),
        "quote_verified_real": verified,
        "source_paragraph_numbers": source_paragraphs,
        "independent_corroboration": independent,
        "context": context,
        "holding_language_in_quote": holding_language,
        "old_code_references": old_code_refs,
        # SOFT flag: worth a closer look before trusting the summary, never an auto-reject on its
        # own -- see _quote_has_holding_language's docstring for why a keyword list can't safely
        # be a hard gate here.
        "needs_extra_scrutiny": verified and not holding_language,
        # REJECTED (hard) only when the quote itself could not be confirmed real, or resolved to no
        # chunk at all -- either way, not a clean, promotable draft without a person going back to
        # the source themselves.
        "rejected": (not verified) or (not source_paragraphs),
    }


# Cases already promoted into chunks/ + judgment_doctrine_map.py by hand (see that module's
# verified_note for each) -- kept here so a re-run of the batch doesn't waste an API call re-
# drafting a case someone already read in full and promoted. Update this set as more get promoted.
_ALREADY_PROMOTED_STEMS = {
    "jagrup_singh_v_state_of_haryana",
    "anwarul_haq_v_state_of_uttar_pradesh",
    "nanda_gopalan_v_state_of_kerala",
    "prabhu_v_state_of_madhya_pradesh",
    "pravat_chandra_mohanty_v_state_of_odisha",
}


def _run_all_pilot_cases():
    """Drafts a report for every pilot_corpus/*.json case that also has a matching pilot_chunks/
    file and isn't already promoted, prints a human-readable summary, and saves the full
    structured reports to judgment_promotion_drafts.json for review. Never touches chunks/ or
    judgment_doctrine_map.py."""
    import glob

    reports = []
    for corpus_path in sorted(glob.glob("pilot_corpus/*.json")):
        stem = os.path.basename(corpus_path)[: -len(".json")]
        if stem in _ALREADY_PROMOTED_STEMS:
            continue
        with open(corpus_path, encoding="utf-8") as f:
            corpus = json.load(f)
        chunks_path = f"pilot_chunks/{stem}_chunks.json"
        if not os.path.exists(chunks_path):
            logger.warning("_run_all_pilot_cases: no chunk file for %r, skipping", corpus_path)
            continue
        with open(chunks_path, encoding="utf-8") as f:
            chunks = json.load(f)

        print(f"\n{'=' * 70}\nDrafting: {corpus['case_name']}\n{'=' * 70}")
        report = draft_promotion(
            case_name=corpus["case_name"], citation=corpus.get("citation", ""),
            full_text=corpus["text"], chunks=chunks,
        )
        reports.append(report)

        if report["rejected"]:
            print(f"REJECTED -- {report.get('error', 'quote could not be verified against the real text')}")
        else:
            if report["needs_extra_scrutiny"]:
                print("WARNING: this quote does not contain ordinary holding/disposition language -- "
                      "it may be background facts or a recited argument, not the court's own final "
                      "ruling. Read the context below especially carefully.")
            print(f"Summary: {report['summary']}")
            print(f"Quote (VERIFIED real, in {report['source_paragraph_numbers']}):")
            print(f"  {report['quote']}")
            ctx = report["context"]
            if ctx["before"]:
                print(f"  [context before, {ctx['before'][0]['paragraph_number']}]: {ctx['before'][0]['text'][:300]}")
            if ctx["after"]:
                print(f"  [context after, {ctx['after'][0]['paragraph_number']}]: {ctx['after'][0]['text'][:300]}")
            if report["old_code_references"]:
                print(f"Old-code references detected (best-effort, not exhaustive): {report['old_code_references']}")
            print(f"Suggested triggers: {report['suggested_triggers']}")
            n = len(report["independent_corroboration"]["candidates"])
            print(f"Independent (non-LLM) corroboration pass found {n} candidate window(s) -- "
                  f"read them yourself before trusting the summary above.")

    with open("judgment_promotion_drafts.json", "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)
    print(f"\n\n{len(reports)} draft(s) written to judgment_promotion_drafts.json for review.")
    print("Nothing has been promoted. Review each draft against its real quoted text before deciding.")


if __name__ == "__main__":
    _run_all_pilot_cases()
