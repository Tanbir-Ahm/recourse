
"""
Semantic retrieval, Phase 2: real embeddings with scores, layered on top
of (never replacing) the exact-lookup retrieval built in retrieval.py.

Purpose: answer "which section(s)/judgment paragraph(s) are plausibly
relevant to this open-ended question?" -- something exact lookup cannot
do, since it requires already knowing a section number or doctrine name.
This is the missing piece for a chat interface where a layman describes a
situation in plain words rather than citing a section.

CRITICAL DESIGN RULE, carried over from the whole session's architecture:
this module NEVER decides a compliance verdict and NEVER answers a legal
question directly. It only returns ranked candidates with similarity
scores. Whatever calls this is responsible for (a) checking the score
against SIMILARITY_THRESHOLD before trusting a match at all, and (b)
routing any accepted match through the SAME deterministic lookups already
built (retrieval.py's get_statute_section / get_judgment_doctrine,
BNS_SECTION_DATA, the check_* functions in main.py) -- never generating an
answer straight from the retrieved text.

Why a real threshold matters here specifically (not just in the abstract):
"Can police arrest me directly for rioting?" genuinely matches MULTIPLE
BNS sections with materially different answers (191(2)/191(3), cognizable
vs 193(1)/(2)/(3), non-cognizable, a different question about
compensation liability). A single best-match answer would silently pick
one and hide the conflict. This module is built to surface "multiple
strong matches with different answers" as its own explicit case, not
just "one match, trust it" or "no match, give up" -- the same
"MIXED cognizability" honesty already implemented in
check_cognizable_arrest_basis, just extended to open-ended questions.
"""

import json
import math
import os
import re
import logging
import numpy as np

logger = logging.getLogger("semantic_retrieval")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv should already be installed (main.py depends on it)

try:
    import voyageai
    _voyage_available = True
except ImportError:
    _voyage_available = False


def _resolve_voyage_api_key():
    """CONFIRMED REAL BUG (2026-09-05), found via the Streamlit Community
    Cloud deployment's own logs after the user reported the Lane B
    "related judgments" panel coming back genuinely empty: os.environ
    (what voyageai.Client() reads internally when constructed with no
    api_key argument) and Streamlit Cloud's own Secrets manager are TWO
    SEPARATE stores -- a key entered into the Cloud app's Secrets panel
    never reaches os.environ on its own. main.py / chat_assistant.py
    already learned this lesson for ANTHROPIC_API_KEY (both explicitly
    check st.secrets first) -- this module never got the same treatment,
    so voyageai.Client() silently constructed with no key at all on
    Cloud, and every semantic_search/rerank call failed and returned
    None with NO log line (unlike indiankanoon_client.py's loud "not
    found in environment" message), making this half of the same outage
    invisible. Checks os.environ first (the local-dev / .env path,
    unchanged), then falls back to st.secrets (the Cloud path)."""
    key = os.environ.get("VOYAGE_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("VOYAGE_API_KEY")
    except Exception:
        return None


MODEL = "voyage-law-2"
RERANK_MODEL = "rerank-2"
EMBEDDINGS_PATH = "embeddings/corpus_embeddings.json"


SIMILARITY_THRESHOLD = 0.40
#Threshold level put at 0.40 down from 0.75. 1 means identical , pointing in same direction. 

# If multiple matches clear the threshold but disagree on a key legal
# attribute (e.g. different cognizable/bailable status for statute
# matches), surface that conflict explicitly rather than picking the
# top-ranked one. This gap defines "materially different" for the
# purposes of flagging a conflict.



# CONFIRMED REAL BUG (2026-09-01), found via live testing on "police came
# to my house and arrested me directly saying that i stole a goat": BNS
# Section 303 (theft) never appeared in the answer at all, even though it
# scored 0.3619 -- comfortably above STATUTE_SIMILARITY_THRESHOLD (0.34).
# Root cause: semantic_search() ranks statute AND judgment chunks
# TOGETHER in one combined pool, sorted by raw score, THEN slices to the
# top TOP_MATCHES_TO_CONSIDER BEFORE find_relevant_sections() ever splits
# them by type and applies the (deliberately different) per-type
# thresholds. For this exact query, all top 10 combined-ranked results
# were judgment paragraphs (arrest-procedure judgments score consistently
# higher than statute text on arrest-flavoured questions) -- direct
# verification found 13 real statute candidates clearing 0.34, but the
# last of them only appears at rank 39 in the combined list, so 12 of 13
# (including Section 303 itself) were silently discarded before the
# threshold filter ever ran. The SAME bug independently affects
# interview_flow.py's offence-identification path (semantic_search() at
# line ~562 there), which also filters `type == "statute"` out of this
# same shared, prematurely-truncated pool.
# FIX: raised from 10 to 50. This is a pure widening of the candidate
# pool, not a threshold change -- STATUTE_SIMILARITY_THRESHOLD/
# JUDGMENT_SIMILARITY_THRESHOLD still do the actual relevance filtering
# downstream, so nothing that would have failed the threshold before can
# pass now. 50 comfortably covers the confirmed real case (last
# qualifying statute candidate at rank 39) with margin, at negligible
# cost -- the expensive step (the full corpus @ query-vector matrix
# multiply, computed once per query regardless of top_k) is unchanged;
# only the post-hoc argsort/slice grows, which is microseconds even at
# this corpus's full ~1595-chunk size.
TOP_MATCHES_TO_CONSIDER = 50

_corpus_cache = None


def _load_corpus_embeddings():
    global _corpus_cache
    if _corpus_cache is not None:
        return _corpus_cache
    if not os.path.exists(EMBEDDINGS_PATH):
        return None
    with open(EMBEDDINGS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    records = data["records"]
    # Precompute the embedding matrix once, since dot-product against a
    # numpy matrix is far faster than looping in Python per query.
    matrix = np.array([r["embedding"] for r in records])
    _corpus_cache = {"records": records, "matrix": matrix, "model": data.get("model")}
    return _corpus_cache


def semantic_search(query, top_k=TOP_MATCHES_TO_CONSIDER, _raise_errors=False):
    """Embeds `query` and returns the top_k closest corpus chunks by
    similarity score, each as a dict with the chunk's metadata plus a
    'score' field. Returns None if embeddings aren't available at all
    (no API key, no corpus_embeddings.json, or the voyageai package isn't
    installed) -- callers must treat None the same honest way every other
    "Cannot Determine" case in this project is treated, not as an error
    to hide.

    _raise_errors: debugging aid only, defaults to False (production
    behavior: swallow to None). Set True temporarily to see the real
    exception instead of a bare None if something unexpected breaks again.

    Does NOT apply SIMILARITY_THRESHOLD itself -- returns raw scored
    results so callers can inspect the full picture (e.g. to detect a
    genuine multi-match conflict) before deciding what to trust."""
    if not _voyage_available:
        return None
    corpus = _load_corpus_embeddings()
    if corpus is None:
        return None

    client = voyageai.Client(api_key=_resolve_voyage_api_key())
    try:
        query_embedding = client.embed([query], model=MODEL, input_type="query").embeddings[0]
    except Exception:
        if _raise_errors:
            raise
        # Network/API failure -- honest None, not a crash, not a guess.
        # Logged (not silently swallowed): a missing/invalid key produces
        # the exact same None a genuine network blip would, and this was
        # previously indistinguishable from either -- see
        # _resolve_voyage_api_key's docstring for the real 2026-09-05 case
        # this invisibility caused.
        logger.exception("semantic_search: Voyage embed call failed for query=%r", query[:200])
        return None

    query_vec = np.array(query_embedding)
    scores = corpus["matrix"] @ query_vec  # dot product; Voyage embeddings are pre-normalized
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        record = dict(corpus["records"][idx])
        record.pop("embedding", None)  # don't return the raw vector to callers
        record["score"] = float(scores[idx])
        results.append(record)
    return results


# ---------------------------------------------------------------------
# Lexical (BM25) search -- the "second way" to search the corpus.
#
# WHY (Lane B eval baseline, finding #1 + its "common thread", 2026-09-05):
# semantic_search alone ranks by MEANING. It is good at paraphrase but
# glosses over literal strings -- someone who types the exact phrase
# "look out circular" or "Section 66A" or a case name does not reliably
# get the judgment that contains those literal words, because the
# embedding of a framework-heavy landmark ("OM/LOC-framework validity",
# "Clause 8(j)") sits far from the plain description of the situation.
# Okapi BM25 -- classic keyword ranking, the way Ctrl-F would score a
# match -- is the complementary signal. Pure Python + numpy over the
# ~1.6K already-loaded corpus chunks: no new dependency (rank_bm25 /
# sklearn are not installed and requirements.txt is a fragile UTF-16
# file on Streamlit Cloud), no API, no network, sub-millisecond.
#
# This is a RECALL aid for Lane B's corpus candidate pool, fused with
# semantic_search in hybrid_search(). It is deliberately NOT wired into
# Lane A's find_relevant_sections (the verified answer path) -- that
# change would need its own eval_chat_answers run and ships separately.
# ---------------------------------------------------------------------

_LEX_TOKEN_RE = re.compile(r"[a-z0-9]+")
_BM25_K1 = 1.5
_BM25_B = 0.75
_RRF_K = 60  # Reciprocal Rank Fusion constant (the standard default)

_lexical_cache = None


def _lex_tokenize(text):
    return _LEX_TOKEN_RE.findall((text or "").lower())


def _build_lexical_index():
    """Build (once, cached) an inverted BM25 index over the same corpus
    chunk records semantic_search uses. Returns None when the embeddings
    file is absent -- the corpus records live in that same file."""
    global _lexical_cache
    if _lexical_cache is not None:
        return _lexical_cache
    corpus = _load_corpus_embeddings()
    if corpus is None:
        return None
    records = corpus["records"]
    doc_tokens = [_lex_tokenize(r.get("text", "")) for r in records]
    n_docs = len(doc_tokens)
    doc_len = np.array([len(t) for t in doc_tokens], dtype=float)
    avgdl = float(doc_len.mean()) if n_docs else 0.0

    postings = {}   # term -> list[(doc_idx, term_freq)]
    df = {}         # term -> document frequency
    for i, toks in enumerate(doc_tokens):
        counts = {}
        for t in toks:
            counts[t] = counts.get(t, 0) + 1
        for t, f in counts.items():
            postings.setdefault(t, []).append((i, f))
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log(1.0 + (n_docs - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    _lexical_cache = {
        "records": records, "postings": postings, "idf": idf,
        "doc_len": doc_len, "avgdl": avgdl or 1.0,
    }
    return _lexical_cache


def lexical_search(query, top_k=TOP_MATCHES_TO_CONSIDER):
    """Plain word-match (Okapi BM25) over the corpus chunk text -- the
    Ctrl-F half of hybrid_search. Catches literal phrases ("look out
    circular", "Section 66A", a case name) that meaning-only search
    glosses over. No embeddings, no API, no network.

    Returns the same {**record, 'score'} dict shape semantic_search
    returns, EXCEPT 'score' here is the raw BM25 score (a positive
    magnitude, NOT a cosine, NOT comparable across the two searches --
    hybrid_search fuses by RANK, not score, for exactly this reason).
    Returns [] (never None) when the corpus file is missing or the query
    carries no indexable term -- lexical search has no external
    dependency that can be 'unavailable' the way Voyage can."""
    idx = _build_lexical_index()
    if idx is None:
        return []
    q_terms = {t for t in _lex_tokenize(query) if t in idx["postings"]}
    if not q_terms:
        return []

    k1, b = _BM25_K1, _BM25_B
    doc_len, avgdl = idx["doc_len"], idx["avgdl"]
    scores = {}
    for t in q_terms:
        idf_t = idx["idf"][t]
        for doc_i, f in idx["postings"][t]:
            denom = f + k1 * (1.0 - b + b * doc_len[doc_i] / avgdl)
            scores[doc_i] = scores.get(doc_i, 0.0) + idf_t * (f * (k1 + 1.0)) / denom

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    out = []
    for doc_i, s in ranked:
        if s <= 0.0:
            break
        rec = dict(idx["records"][doc_i])
        rec.pop("embedding", None)
        rec["score"] = float(s)
        rec["lexical_score"] = float(s)
        out.append(rec)
    return out


def hybrid_search(query, top_k=TOP_MATCHES_TO_CONSIDER, *,
                  semantic_fn=None, lexical_fn=None):
    """Search the corpus BOTH ways -- by meaning (semantic_search) and by
    literal words (lexical_search) -- and fuse the two ranked lists with
    Reciprocal Rank Fusion (each list contributes 1/(RRF_K + rank); a
    doc near the top of BOTH lists wins). Rank-based fusion, so BM25's
    uncalibrated magnitude never competes with a cosine on raw scale.

    A RECALL aid, not a re-ranker: it widens the candidate pool so an
    exact phrase reaches the right judgment even when the meaning search
    drifts. Whatever consumes this still applies its own threshold /
    Voyage rerank downstream (Lane B's fetch_and_pin does).

    Degrades cleanly:
      - Voyage unavailable (semantic_search -> None): returns the lexical
        results alone -- strictly more robust than semantic_search, which
        returns None here.
      - both arms empty AND semantic was the None kind: returns None (the
        honest "corpus retrieval unavailable" signal callers already
        handle); both arms empty otherwise: returns [].

    Each record carries: 'score' (fused RRF score), 'semantic_score' /
    'lexical_score' (raw, when that arm retrieved it), and 'retrieval'
    ('hybrid' | 'semantic' | 'lexical')."""
    semantic_fn = semantic_fn or semantic_search
    lexical_fn = lexical_fn or lexical_search

    sem_raw = semantic_fn(query, top_k=top_k)
    lex = lexical_fn(query, top_k=top_k) or []
    sem = sem_raw or []
    if not sem and not lex:
        return None if sem_raw is None else []

    def _key(r):
        return r.get("chunk_id") or (r.get("case_name"), r.get("paragraph_number"),
                                     r.get("section_number"))

    fused = {}
    for rank, r in enumerate(sem):
        e = fused.setdefault(_key(r), {"record": dict(r), "rrf": 0.0})
        e["rrf"] += 1.0 / (_RRF_K + rank + 1)
        e["record"]["semantic_score"] = r.get("score")
    for rank, r in enumerate(lex):
        e = fused.get(_key(r))
        if e is None:
            e = fused.setdefault(_key(r), {"record": dict(r), "rrf": 0.0})
        e["rrf"] += 1.0 / (_RRF_K + rank + 1)
        e["record"]["lexical_score"] = r.get("score")

    out = []
    for e in sorted(fused.values(), key=lambda x: x["rrf"], reverse=True)[:top_k]:
        rec = e["record"]
        rec.pop("embedding", None)
        rec["score"] = e["rrf"]
        ss = rec.get("semantic_score")
        ls = rec.get("lexical_score")
        rec["retrieval"] = ("hybrid" if ss is not None and ls is not None
                            else "lexical" if ss is None else "semantic")
        out.append(rec)
    return out


def rerank(query, documents, top_k=None, _raise_errors=False):
    """Score `documents` (a list of strings) for relevance to `query`
    using Voyage's cross-encoder reranker, which reads the query and each
    document TOGETHER -- unlike semantic_search's separate-embedding
    cosine, which loses nuance on long, multi-part queries.

    Used by related_judgments.py (Lane B) to rank a pool of candidate
    judgments against the user's FULL situation, and to pin the on-point
    paragraphs within a fetched judgment.

    Returns a list of {"index": int, "score": float, "document": str},
    sorted best-first (length min(top_k, len(documents))), OR None if the
    reranker is unavailable (no voyageai, no API key, network failure) --
    callers must treat None as an honest "could not rank", the same as
    semantic_search returning None, and fall back rather than crash.

    A scoring function, not a generator: it invents nothing and cites
    nothing. Consistent with this project's one architectural principle.
    """
    if not _voyage_available:
        return None
    docs = [d for d in (documents or []) if isinstance(d, str) and d.strip()]
    if not query or not docs:
        return []

    try:
        client = voyageai.Client(api_key=_resolve_voyage_api_key())
        resp = client.rerank(query, docs, model=RERANK_MODEL, top_k=top_k)
    except Exception:
        if _raise_errors:
            raise
        logger.exception("rerank: Voyage rerank call failed for query=%r", (query or "")[:200])
        return None

    out = []
    for r in getattr(resp, "results", []) or []:
        out.append({
            "index": int(r.index),
            "score": float(r.relevance_score),
            "document": docs[int(r.index)],
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


"""
ADD near the top of semantic_retrieval.py, replacing the single
SIMILARITY_THRESHOLD constant with two separate ones.

WHY SPLIT (2026-08-28): a real user question -- "police came to my
house and arrested me saying that i stole a goat" -- failed to surface
BNS Section 303 (theft) at all. Confirmed real score: 0.3542, just
below the single shared threshold of 0.40. Investigating this revealed
the deeper problem: statute matching and judgment matching were being
held to the SAME threshold, despite being fundamentally different
kinds of evidence:

- Statute sections are a CLOSED, fully-known vocabulary -- all ~360
  BNS sections and ~530 BNSS sections are already embedded, already
  verified, already have deterministic compliance data in
  BNS_SECTION_DATA. A statute match either genuinely applies or it
  doesn't; there's little risk in being more permissive here, since
  the SET of possible statute matches is small and fully controlled.
- Judgment/doctrine matches pull from a fuzzier, more open precedent
  space (currently 12 judgments, growing). Being too permissive here
  risks surfacing a genuinely unrelated case merely because it shares
  vocabulary -- a different, real risk (see BNS_SECTION_DATA's own
  "conflicting_matches" logic, built for exactly this kind of danger).

Given this asymmetry, statutes get a LOWER (more permissive) threshold
than judgments. The specific values below were chosen by testing
against every real confirmed score available at time of writing (this
session's goat-theft/D.K.-Basu/Prabir-Purkayastha/Youth-Bar-Association
scores, plus the Aug 27 handoff's BNSS-43(5) and confirmed-noise-ceiling
numbers) -- see the accompanying test script's output for the full
comparison table. STATUTE_SIMILARITY_THRESHOLD=0.34 was the narrowest
value that fixed both known statute-retrieval failures (goat theft at
0.3542, a hypothetical near-BNSS-43(5)-adjacent statute score) without
crossing the confirmed noise ceiling (~0.339) -- this is a narrow
margin (0.001), acknowledged directly, not a comfortable buffer.
JUDGMENT_SIMILARITY_THRESHOLD is kept at the existing 0.40, UNCHANGED,
since no confirmed real judgment-matching failure has been found at
that threshold -- lowering it was never the actual problem, and doing
so anyway would add judgment-matching risk to solve a statute-matching
problem.

MUST be revisited if a real failure is later found on either side of
this split -- these are evidence-based starting points from a small
number of real data points, not a large-scale calibration.
"""

STATUTE_SIMILARITY_THRESHOLD = 0.34
JUDGMENT_SIMILARITY_THRESHOLD = 0.40

# conflicting_matches is only declared when the competing provisions are
# BOTH genuinely relevant: each must score at least CONFLICT_MIN_SCORE
# (a real, confident match -- not noise-level) AND be within
# CONFLICT_SCORE_MARGIN of the top statute match. A genuine "the law
# forks here" case (e.g. "can police arrest me for cheating" -> 318(2)
# no vs 318(4) yes) has the competing provisions scoring high and close
# together, usually as subsections of the same section. When the best
# statute match is only noise-level (~0.36, as for "stole a goat",
# where nothing aligns cleanly), there is no confident fork to surface
# -- fall through to single_match and let the answer explain from the
# (weak) statute set plus the judgment matches. See the long note in
# find_relevant_sections().
CONFLICT_SCORE_MARGIN = 0.03
CONFLICT_MIN_SCORE = 0.40

# How many match blocks actually reach the answer generator.
#
# WHY (2026-09-02): threshold filtering (0.34 statute / 0.40 judgment) is
# a deliberately low bar -- for a typical situation question ~18 blocks
# clear it, of which only a handful are genuinely on point and the rest
# are topic-adjacent noise. Confirmed real case: "police... arrested me...
# saying that i stole a goat" put 13 statute candidates over 0.34, the
# last at rank 39; feeding all of them let the model wander to a
# tangential procedural section instead of staying on BNS 303 (theft).
# The Phase 5 offence-keyword anchor worked around this by injecting one
# strong correct match; this is the actual fix -- rank what cleared the
# threshold and keep only the strongest.
#
# Two-stage, applied PER TYPE (statute and judgment capped separately, so
# a weaker-scoring but genuinely relevant judgment is never crowded out
# by statute chunks or vice versa), on the already-score-ordered list:
#   1. relative gap -- drop anything scoring more than MATCH_SCORE_GAP
#      below that type's top match (adapts: keeps all of a genuine
#      multi-section cluster, trims a lone strong match's noise tail).
#   2. absolute cap -- then keep at most MAX_*_MATCHES_FOR_PROMPT.
# The top match of each type is always kept. Both stages are strictly
# looser than the conflicting_matches gate (within CONFLICT_SCORE_MARGIN
# 0.03 of top AND >= CONFLICT_MIN_SCORE 0.40), so conflict detection sees
# every provision it did before -- see _conflict_state().
MATCH_SCORE_GAP = 0.08
MAX_STATUTE_MATCHES_FOR_PROMPT = 5
MAX_JUDGMENT_MATCHES_FOR_PROMPT = 4

# Kept for any external code that still imports the old combined name
# directly -- deliberately aliased to the MORE CONSERVATIVE (judgment)
# value, not the more permissive statute one, so nothing that isn't
# explicitly updated to use the split constants silently becomes more
# permissive by accident.
SIMILARITY_THRESHOLD = JUDGMENT_SIMILARITY_THRESHOLD

# Case names embedded in the shared corpus for the freeze / cheque-bounce
# document-upload domains (built for main.py's compliance checks, not this
# arrest/FIR chat -- chat_assistant.SCOPE_CLASSIFIER_PROMPT tells the
# scope classifier this chat's OWN case law does not cover them). They
# live in the same embeddings file only because it is shared, so a
# generic similarity hit against one of them is never real arrest/FIR
# case law and must not be treated as a "verified corpus" authority for
# this chat feature or Lane B.
#
# CONFIRMED REAL FAILURE (2026-09-04): "Rangappa v Sri Mohan" -- an NI
# Act S.139 cheque-presumption case -- scored 0.409 (just above
# JUDGMENT_SIMILARITY_THRESHOLD) against a question about cheating and
# criminal breach of trust in a partnership, purely on "loan"/"signature"
# vocabulary overlap, and was then quoted as "relevant judicial
# authority" in a drafted representation about an offence it has nothing
# to do with. A curated exclusion list, not a score-based fix, because
# the failure is categorical (wrong legal domain), not a matter of degree.
OUT_OF_CHAT_DOMAIN_CASE_NAMES = frozenset({
    "Rangappa v Sri Mohan",
    "Bir Singh v Mukesh Kumar",
    "Damodar S. Prabhu v Sayed Babalal H",
    "Kaveri Plastics v Mahdoom Bawa Bahrudeen Noorul",
    "Prakash Chimanlal Sheth v Jagruti Keyur Rajpopat",
    "Malabar Gold and Diamond Limited v Union of India",
    "Neelkanth Pharma Logistics Pvt. Ltd. v Union of India",
    "State of Maharashtra v Tapas D. Neogy",
    "Hiral P. Harsora v Kusum Narottamdas Harsora",
    "D. Velusamy v D. Patchaiammal",
    "Satish Chander Ahuja v Sneha Ahuja",
    "Indra Sarma v V.K.V. Sarma",
    "Prabha Tyagi v Kamlesh Devi",
    "S. Vanitha v Deputy Commissioner, Bengaluru Urban District",
})


# ---------------------------------------------------------------------
# REPLACE find_relevant_sections() with this version:
# ---------------------------------------------------------------------

CHEQUE_BOUNCE_CASE_NAMES = frozenset({
    "Rangappa v Sri Mohan",
    "Bir Singh v Mukesh Kumar",
    "Damodar S. Prabhu v Sayed Babalal H",
    "Kaveri Plastics v Mahdoom Bawa Bahrudeen Noorul",
    "Prakash Chimanlal Sheth v Jagruti Keyur Rajpopat",
})

FREEZE_CASE_NAMES = frozenset({
    "State of Maharashtra v Tapas D. Neogy",
    "Neelkanth Pharma Logistics Pvt. Ltd. v Union of India",
    "Malabar Gold and Diamond Limited v Union of India",
})

DOMESTIC_VIOLENCE_CASE_NAMES = frozenset({
    "Hiral P. Harsora v Kusum Narottamdas Harsora",
    "D. Velusamy v D. Patchaiammal",
    "Satish Chander Ahuja v Sneha Ahuja",
    "Indra Sarma v V.K.V. Sarma",
    "Prabha Tyagi v Kamlesh Devi",
    "S. Vanitha v Deputy Commissioner, Bengaluru Urban District",
})

# domain= value -> the subset of OUT_OF_CHAT_DOMAIN_CASE_NAMES that
# becomes admissible for that (and only that) inline answer path.
_DOMAIN_CARVE_OUT = {
    "cheque_bounce": CHEQUE_BOUNCE_CASE_NAMES,
    "freeze": FREEZE_CASE_NAMES,
    "domestic_violence": DOMESTIC_VIOLENCE_CASE_NAMES,
}


# ---------------------------------------------------------------------
# Named-section fast path: a question that names an exact section number
# and Act ("420 IPC", "Section 318 BNS", "IT Act 66C") gets that section's
# real text via a dictionary lookup, never a similarity score.
#
# CONFIRMED REAL FAILURE (2026-09-22): "What are the ingredients for 420
# IPC?" -- arguably the single most commonly cited section number in
# Indian criminal law -- returned "no_match". BNS Section 318 (cheating,
# IPC 420's current-law equivalent) is verified, present and correct in
# the corpus (chunk_id "statute:BNS:318"), but the query text "420 IPC"
# doesn't resemble the statute's own wording (which never contains the
# digits "420" -- it uses the new BNS number) closely enough to clear
# STATUTE_SIMILARITY_THRESHOLD, or even to rank in the top statute
# candidates at all. A user who names the exact section they mean has
# already done the disambiguation work; there is no case for routing
# that through a similarity score at all.
#
# Deliberately narrow: only fires when a number sits directly next to an
# explicit Act name. A bare "u/s 420" with no Act named is left to the
# existing semantic path -- the Act is genuinely ambiguous (IPC or BNS?)
# and guessing would be worse than not firing.
_SECTION_ACT_ALIASES = {
    "indian penal code": "IPC",
    "ipc": "IPC",
    "code of criminal procedure": "CrPC",
    "crpc": "CrPC",
    "bharatiya nyaya sanhita": "BNS",
    "bns": "BNS",
    "bharatiya nagarik suraksha sanhita": "BNSS",
    "bnss": "BNSS",
    "information technology act": "ITACT",
    "it act": "ITACT",
    "itact": "ITACT",
    "negotiable instruments act": "NIACT",
    "ni act": "NIACT",
    "niact": "NIACT",
}
# Old-code acts need statute_concordance to find the current BNS/BNSS
# section first; the rest (new-code, or untouched by the recodification)
# are looked up directly.
_OLD_CODE_ACTS = frozenset({"IPC", "CrPC"})

# Sorted longest-first purely so the regex engine tries a multi-word alias
# ("it act") before either of its component words could be mistaken for
# something else -- \b boundaries already make this collision-proof, this
# is just the clearer way to read the pattern.
_SECTION_ACT_PATTERN = "|".join(
    re.escape(a) for a in sorted(_SECTION_ACT_ALIASES, key=len, reverse=True))
_SECTION_NUM_PATTERN = r"\d{1,4}[A-Za-z]{0,2}(?:\(\d+\))?"
_SECTION_PREFIX_PATTERN = r"(?:under\s+section|u/s|section|sec\.?|s\.?)?\s*"

_NUM_THEN_ACT_RE = re.compile(
    rf"{_SECTION_PREFIX_PATTERN}(?P<num>{_SECTION_NUM_PATTERN})\s*"
    rf"(?:of\s+(?:the\s+)?)?(?P<act>{_SECTION_ACT_PATTERN})\b",
    re.IGNORECASE,
)
_ACT_THEN_NUM_RE = re.compile(
    rf"\b(?P<act>{_SECTION_ACT_PATTERN})\s*{_SECTION_PREFIX_PATTERN}(?P<num>{_SECTION_NUM_PATTERN})",
    re.IGNORECASE,
)


def _detect_named_section(query):
    """The (act, number) named directly in `query` -- e.g. ("IPC", "420")
    for "420 IPC", or ("ITACT", "66C") for "IT Act 66C" -- or None if no
    Act is named right next to a number. Tries "number then Act" before
    "Act then number" since that is the more common phrasing, but either
    order is recognised."""
    for pattern in (_NUM_THEN_ACT_RE, _ACT_THEN_NUM_RE):
        m = pattern.search(query)
        if m:
            act = _SECTION_ACT_ALIASES.get(m.group("act").lower())
            if act:
                return act, m.group("num")
    return None


def _named_section_exact_match(query):
    """A synthetic statute record, same shape find_relevant_sections
    expects from semantic_search, for a section the question names
    explicitly -- resolved by exact dictionary lookup
    (statute_concordance.to_new + retrieval.get_statute_section), never
    embeddings. Score 1.0: the user named the exact provision, there is
    nothing to estimate. None if no Act+number is named, the old-code
    section was repealed with no successor, or the resolved section
    simply isn't in this project's corpus.

    A genuine one-to-many old-to-new mapping (rare) only surfaces the
    first listed successor -- a documented simplification, not a hidden
    failure; the common case (like IPC 420 -> BNS 318) is one-to-one."""
    detected = _detect_named_section(query)
    if detected is None:
        return None
    act, number = detected

    if act in _OLD_CODE_ACTS:
        from statute_concordance import to_new
        mapped = to_new(act, number)
        if not mapped:
            return None  # repealed outright, or not in the concordance table
        new_act, new_number = mapped[0]["act"], mapped[0]["section"]
    else:
        new_act, new_number = act, number

    from retrieval import get_statute_section
    hit = get_statute_section(new_act, new_number)
    if hit is None:
        return None

    return {
        # chunk_id names the real source chunk (always the bare top-level
        # section -- see retrieval.get_statute_section's docstring on why
        # a chunk only ever exists at that granularity).
        "chunk_id": f"statute:{hit['act']}:{hit['section_number']}",
        "text": hit["text"],
        "type": "statute",
        "act": hit["act"],
        # section_number, by contrast, keeps whatever specificity we
        # actually resolved (e.g. "318(4)" for IPC 420, not the bare
        # "318"): unlike an ordinary semantic match, which can only ever
        # report the bare number and correctly leaves every subsection's
        # cognizable/bailable status "in play" (see the enrichment loop's
        # all_variants comment below), an old-code translation or a
        # user-typed subsection IS that specific -- collapsing it back to
        # the bare number would manufacture a false conflict between
        # subsections the question was never actually asking about.
        "section_number": new_number,
        "score": 1.0,
        "exact_section_lookup": True,
    }


def find_relevant_sections(query, domain=None):
    """Higher-level function for BOTH statute and judgment lookup: returns
    a dict describing what was found, in one of four honest states --
    'no_match' (nothing cleared its applicable threshold), 'single_match'
    (exactly one section family cleared the threshold and they agree),
    'conflicting_matches' (multiple STATUTE sections cleared the
    threshold with DIFFERENT cognizable/bailable status -- the "rioting"
    case), or 'unavailable' (embeddings aren't set up at all). Never
    silently picks one match to hide a conflict.

    CHANGED 2026-08-28: statute and judgment matches are now filtered
    against SEPARATE thresholds (STATUTE_SIMILARITY_THRESHOLD=0.34,
    JUDGMENT_SIMILARITY_THRESHOLD=0.40), not one shared value. See the
    module-level comment above these constants for the full confirmed
    real-failure writeup (goat theft, Section 303, scored 0.3542 --
    below the old shared 0.40 threshold, now correctly caught). This
    was a deliberate, evidence-based split, not a blanket threshold
    lowering -- judgment matching keeps its prior, more conservative
    value unchanged, since no real judgment-matching failure has been
    found to justify loosening it.

    CONFIRMED REAL BUG (2026-08-27): this function previously filtered
    to statute matches ONLY (discarding every judgment match, however
    highly ranked), despite its use as the single retrieval entry point
    for chat_assistant.py's open-ended chat feature. Confirmed real
    case: for "is theft a serious crime that lets police arrest me right
    away?", Arnesh Kumar v State of Bihar scored HIGHEST of all 15
    results (0.407, ahead of every statute match) but was completely
    invisible to the chat feature -- it could only ever discuss
    cognizability from bare statute text, never surface the actual
    arrest-procedure case law that was the single best match. Fixed to
    also return judgment matches clearing the threshold, as a separate
    'judgment_matches' field -- the existing statute-only conflict logic
    is untouched, since that's correctly scoped to a narrower, real
    concern (statutes disagreeing on cognizable/bailable status), not a
    general "should judgments be included" question.

    ADDED 2026-09-22: before any of the above, check whether the question
    names an exact section + Act (_named_section_exact_match) -- see that
    function's docstring for the confirmed real failure ("420 IPC"
    returning no_match) this closes. A hit there is exact, not similarity-
    scored, so it works even with embeddings down and is never crowded
    out by an unrelated, loosely-scoring semantic statute match."""
    exact_hit = _named_section_exact_match(query)

    results = semantic_search(query)
    lex_hits = lexical_search(query) or []

    if results is None:
        # Voyage down: fall back to lexical-only rather than the blanket
        # "unavailable" -- strictly more useful, still honest.
        if not lex_hits and exact_hit is None:
            return {"state": "unavailable"}
        results = []

    # The freeze/cheque cases are excluded from every chat/Lane-B judgment
    # match by default (OUT_OF_CHAT_DOMAIN_CASE_NAMES) so they never leak
    # into an arrest answer as vocabulary-overlap noise. domain="cheque_
    # bounce" / "freeze" are the callers that have already established the
    # question IS that kind of matter -- for each, and only that one, its
    # own carve-out of cases becomes admissible; the OTHER domain's cases
    # (and State of Maharashtra v Tapas D. Neogy for a cheque call, etc.)
    # stay excluded.
    _excluded_cases = OUT_OF_CHAT_DOMAIN_CASE_NAMES
    if domain in _DOMAIN_CARVE_OUT:
        _excluded_cases = OUT_OF_CHAT_DOMAIN_CASE_NAMES - _DOMAIN_CARVE_OUT[domain]

    if exact_hit is not None:
        # The user named the exact provision -- trust that identification
        # outright rather than filtering it through a similarity score,
        # and don't let an unrelated, loosely-scoring semantic statute
        # match manufacture a spurious "conflicting_matches" alongside it
        # (see CONFLICT_SCORE_MARGIN's goat-theft note above for exactly
        # that failure mode). Subsection-level conflicts WITHIN this same
        # section are still fully checked below, via all_variants.
        statute_matches = [exact_hit]
    else:
        statute_matches = [r for r in results if r["type"] == "statute" and r["score"] >= STATUTE_SIMILARITY_THRESHOLD]
    judgment_matches = [r for r in results if r["type"] == "judgment" and r["score"] >= JUDGMENT_SIMILARITY_THRESHOLD
                         and r.get("case_name") not in _excluded_cases]

    # Keep only the strongest blocks per type before anything downstream
    # (enrichment, conflict detection, prompt assembly) sees them -- see
    # the MATCH_SCORE_GAP / MAX_*_MATCHES_FOR_PROMPT note above.
    statute_matches = _cap_matches(statute_matches, MAX_STATUTE_MATCHES_FOR_PROMPT)
    judgment_matches = _cap_matches(judgment_matches, MAX_JUDGMENT_MATCHES_FOR_PROMPT)

    # --- LEXICAL BACKFILL (judgments only) ---------------------------------
    # A judgment BM25 pulled up on literal keyword overlap that meaning-
    # search ranked just below JUDGMENT_SIMILARITY_THRESHOLD. Admitted only
    # when BOTH signals agree it is relevant (RRF philosophy): it must be a
    # real -- if sub-floor -- cosine hit (>= _BACKFILL_MIN_SEMANTIC) AND a
    # strong lexical hit, AND share >= _MIN_SHARED_TERMS distinct meaningful
    # words with the question. One paragraph per distinct case; capped;
    # scored just under the floor so it sorts after every semantic match.
    # Runs after _cap_matches so it never touches the statute conflict
    # logic. A lexical-ONLY hit (case absent from the semantic top-50) is
    # NOT admitted here -- that is the noise class (NALSA on "union of
    # india", etc.); the curated doctrine anchors cover the cases that
    # genuinely need pure-keyword rescue.
    _seen_cases = {(m.get("case_name") or "").lower()
                   for m in statute_matches + judgment_matches if m.get("case_name")}
    _by_key = {_bkey(r): r for r in results}
    _top_lex = lex_hits[0]["score"] if lex_hits else 0.0
    _added = []
    for lx in lex_hits[:_LEXICAL_BACKFILL_SCAN]:
        if lx.get("type") != "judgment":
            continue
        cn = (lx.get("case_name") or "")
        if not cn or cn.lower() in _seen_cases or cn in _excluded_cases:
            continue
        if _top_lex and lx.get("score", 0.0) < _BACKFILL_MIN_LEXICAL_FRAC * _top_lex:
            continue
        if not _shares_enough_terms(query, lx.get("text", "")):
            continue
        sem_rec = _by_key.get(_bkey(lx))
        sem_score = (sem_rec or {}).get("score")
        if sem_score is None or sem_score < _BACKFILL_MIN_SEMANTIC:
            continue  # not also a real meaning hit -> skip (noise guard)
        rec = dict(sem_rec)
        rec["retrieval"] = "lexical"
        rec["lexical_score"] = lx.get("score")
        rec["semantic_score"] = sem_score
        rec["score"] = min(sem_score, JUDGMENT_SIMILARITY_THRESHOLD - 0.001)
        _added.append(rec)
        _seen_cases.add(cn.lower())
        if len(_added) >= _MAX_LEXICAL_BACKFILL:
            break
    if _added:
        logger.info("find_relevant_sections: lexical backfill added %d judgment(s): %s",
                    len(_added), [r.get("case_name") for r in _added])
        judgment_matches = judgment_matches + _added

    if not statute_matches and not judgment_matches:
        return {"state": "no_match", "results": results}

    # Pull each matched section's actual compliance data via the SAME
    # deterministic table used everywhere else in this project -- this
    # function's job ends at "which sections look relevant"; it does not
    # decide cognizability itself.
    try:
        from main import BNS_SECTION_DATA
    except ImportError:
        BNS_SECTION_DATA = {}
    try:
        from itact_section_data import ITACT_SECTION_DATA
    except ImportError:
        ITACT_SECTION_DATA = {}
    # act -> its structured compliance table. CONFIRMED REAL GAP
    # (2026-09-05, Phase 3b): this block used to read BNS_SECTION_DATA
    # unconditionally regardless of a match's own "act" field -- harmless
    # for BNSS matches (they simply have no First-Schedule entries, so
    # .get() always missed anyway) but a real silent data-loss risk for
    # an IT Act match reached via unaided semantic search (not through
    # chat_assistant.py's keyword-anchor/explicit-section paths, which
    # already attach their own all_variants): BNS_SECTION_DATA.get("66C")
    # is always None, so its real cognizable/bailable classification
    # would have been silently dropped rather than looked up in the
    # right table.
    _SECTION_DATA_BY_ACT = {"BNS": BNS_SECTION_DATA, "ITACT": ITACT_SECTION_DATA}

    enriched = []
    for m in statute_matches:
        sec_key = m["section_number"]
        section_table = _SECTION_DATA_BY_ACT.get((m.get("act") or "").upper(), BNS_SECTION_DATA)
        # CONFIRMED REAL BUG (2026-08-27): a direct .get(sec_key) only
        # finds an EXACT match. BNS_SECTION_DATA keys 239 of 436 entries
        # (55%) by subsection (e.g. "191(2)", "191(3)"), not the bare
        # top-level number semantic search always returns (statute
        # chunks are split at the top-level section boundary only, per
        # chunk_corpus.py). Confirmed real case: "191" has no bare-key
        # entry at all -- only "191(2)" and "191(3)" exist, both
        # cognizable. A direct .get("191") silently returned None,
        # meaning this section's real compliance data was never actually
        # checked for conflicts. Fixed by pulling every subsection
        # variant of the matched bare number and treating them as this
        # match's full data set, same as retrieval.py's exact-lookup
        # code already does for the equivalent problem elsewhere.
        exact = section_table.get(sec_key)
        subsection_variants = {
            k: v for k, v in section_table.items()
            if k == sec_key or k.startswith(f"{sec_key}(")
        }
        if exact is not None and sec_key not in subsection_variants:
            subsection_variants[sec_key] = exact
        enriched.append({**m, "section_data": exact, "all_variants": subsection_variants})

    # A conflict is only checked across statute matches, since it's
    # specifically about disagreeing cognizable/bailable classifications
    # -- a concept that doesn't apply to judgment paragraphs the same way.
    #
    # CONFIRMED REAL FAILURE (2026-09-01, live): "police... arrested me...
    # saying that i stole a goat" retrieved Section 303 (theft, cognizable,
    # score ~0.44) AND -- spuriously -- Section 318 (cheating, whose
    # 318(2)/(3) are non-cognizable, score ~0.36). Checking cognizability
    # across EVERY match above the 0.34 threshold made {True, False} and
    # forced conflicting_matches, so a straightforward theft question got
    # the "the law forks, here are the scenarios" treatment plus a
    # duplicate hardcoded closer from app.py's conflict branch. A genuine
    # fork (e.g. "can police arrest me for cheating" -> 318(2) no vs
    # 318(4) yes) has the competing provisions as SUBSECTIONS OF THE SAME
    # top match, both scoring high -- not a high-relevance section vs a
    # low-relevance noise match. So conflict detection now only considers
    # matches within CONFLICT_SCORE_MARGIN of the top statute match.
    state = _conflict_state(enriched)

    return {"state": state, "matches": enriched, "judgment_matches": judgment_matches}


# ---------------------------------------------------------------------
# Lexical backfill for the CHAT answer path (Lane A).
#
# WHY (2026-09-08): find_relevant_sections ranks judgments by MEANING and
# then filters at JUDGMENT_SIMILARITY_THRESHOLD (0.40). A long narrative
# question ("boundary dispute over an irrigation channel ... they broke
# our fence ... the police arrested my father on the neighbour's
# statement") pushes the genuinely on-point judgment's cosine below 0.40
# and it never reaches the answer -- the exact gap the hand-written
# doctrine anchors have been patching one scenario at a time. This adds
# BM25 (lexical_search) as a RECALL aid to the same function: a judgment
# chunk that shares real, literal keywords with the question is admitted
# even below the cosine floor, behind a keyword-overlap gate and clearly
# tagged retrieval="lexical". Statutes are left to the (already strong)
# offence-keyword + statute_doctrine_map paths -- this only backfills
# judgments, and only a couple, sorted after every real semantic match.
_LEXICAL_BACKFILL_SCAN = 10   # how far down the BM25 list to look
_MAX_LEXICAL_BACKFILL = 2     # how many below-floor judgments to admit (distinct cases)
_MIN_SHARED_TERMS = 3         # distinct meaningful query words the chunk must contain
_BACKFILL_MIN_SEMANTIC = 0.22 # floor: the chunk must still be in the semantic top-50 with
                              # SOME meaning relevance -- not zero (a lexical-only hit is
                              # the noise class and is rejected by the sem_rec-is-None guard)
_BACKFILL_MIN_LEXICAL_FRAC = 0.35  # ... and a strong lexical hit vs the top BM25 score

_BACKFILL_STOPWORDS = frozenset("""
a an the and or but if then than that this these those there here of to in on at by for with
from into over under about as is are was were be been being have has had do does did not no
my our your his her their its it we you they he she i me us them him them who whom whose which
what when where why how so such can could would should may might will shall must been ongoing
police station custody arrested arrest complaint file filed said told them father brother son
mother sister wife husband family last week night day time went came arrived men man house home
court courts case cases state states india union section sections law laws legal judgment
judgement order orders petition appeal accused person people matter matters right rights
""".split())


def _bkey(r):
    return r.get("chunk_id") or (r.get("case_name"), r.get("paragraph_number"),
                                 r.get("section_number"))


def _content_terms(text):
    """Meaningful words for the keyword-overlap gate: >=4-letter tokens
    that aren't stopwords, plus any bare section number."""
    out = set()
    for t in _lex_tokenize(text):
        if t.isdigit() and len(t) >= 2:
            out.add(t)
        elif len(t) >= 4 and t not in _BACKFILL_STOPWORDS:
            out.add(t)
    return out


def _shares_enough_terms(query, chunk_text, minimum=_MIN_SHARED_TERMS):
    q = _content_terms(query)
    if len(q) < minimum:
        return False
    return len(q & _content_terms(chunk_text)) >= minimum


def _cap_matches(matches, max_keep, gap=MATCH_SCORE_GAP):
    """Trim a score-ordered match list to the strongest blocks: first drop
    anything more than `gap` below the top score, then keep at most
    `max_keep`. The top match is always kept. Split out from
    find_relevant_sections so it can be unit-tested without embeddings.
    `matches` must already be sorted by descending 'score' (semantic_search
    guarantees this)."""
    if len(matches) <= 1:
        return matches
    top_score = matches[0]["score"]
    within_gap = [m for m in matches if top_score - m["score"] <= gap]
    return within_gap[:max_keep]


def _conflict_state(enriched):
    """'conflicting_matches' iff the confident, closely-ranked statute
    matches genuinely disagree on cognizability; 'single_match'
    otherwise (including the no-statute-matches case). Split out from
    find_relevant_sections so the gating can be unit-tested without
    embeddings. `enriched` is score-ordered; each item has 'score' and
    'all_variants'."""
    if not enriched:
        return "single_match"
    top_score = enriched[0]["score"]
    conflict_pool = [
        e for e in enriched
        if e["score"] >= CONFLICT_MIN_SCORE and top_score - e["score"] <= CONFLICT_SCORE_MARGIN
    ]
    all_cognizable_values = set()
    for e in conflict_pool:
        for variant_data in e["all_variants"].values():
            all_cognizable_values.add(variant_data.get("cognizable"))
    return "conflicting_matches" if len(all_cognizable_values) > 1 else "single_match"


if __name__ == "__main__":
    if not _voyage_available:
        print("voyageai not installed -- run: pip install voyageai")
    elif not os.path.exists(EMBEDDINGS_PATH):
        print(f"{EMBEDDINGS_PATH} not found -- run embed_corpus.py first (requires VOYAGE_API_KEY).")
    else:
        test_queries = [
            "Can police arrest me directly for rioting?",
            "How can I sue my neighbour for a property dispute?",
            "asdkjaslkdj random gibberish text",
        ]
        for q in test_queries:
            print(f"\n=== Query: {q!r} ===")
            result = find_relevant_sections(q)
            print(f"State: {result['state']}")
            if result["state"] in ("single_match", "conflicting_matches"):
                for m in result["matches"]:
                    print(f"  {m['section_number']} (score={m['score']:.3f}): {m['text'][:80]!r}")
                    
    