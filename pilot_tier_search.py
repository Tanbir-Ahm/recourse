"""
pilot_tier_search.py -- search over the WIDER, less-reviewed judgment pool (currently the 9
hand-verified hurt/assault cases in pilot_chunks/), kept deliberately separate from Recourse's
46-case core corpus (semantic_retrieval.py / embeddings/corpus_embeddings.json).

WHY SEPARATE (2026-09-23): the core 46 were each individually read by a person before being
trusted. This pool's cases were only automatically identity-checked (the real party names/date
were confirmed inside the file) and hand-found via the Court's own search -- a lighter review, not
the same standard. Mixing the two into one search would let this newer, less-reviewed material
silently carry the same weight as the core library. So this stays its own search, its own
(stricter) similarity bar, and its own unmissable label on every result -- the same separation
already used for the domestic-violence Vaquill pool, applied here with real embeddings instead of
keyword matching.

STATUS: standalone and proven in isolation (test_pilot_tier_search.py). This module has NO
connection to chat_assistant.py or the live WhatsApp/website answer path -- wiring it in is a
separate, deliberate step, not done by this file.
"""
import glob
import json
import math
import os

import semantic_retrieval

# Stricter than the core corpus's JUDGMENT_SIMILARITY_THRESHOLD (0.40): this pool has had less
# individual review, so it should take a closer match before being surfaced at all.
PILOT_TIER_SIMILARITY_THRESHOLD = 0.50

MAX_RESULTS = 3


def load_pilot_pool(chunk_dir: str) -> list:
    """All chunks from every *_chunks.json file in chunk_dir, each tagged with a stable chunk_id."""
    pool = []
    for path in sorted(glob.glob(os.path.join(chunk_dir, "*_chunks.json"))):
        chunks = json.load(open(path, encoding="utf-8"))
        for i, c in enumerate(chunks):
            pool.append({**c, "chunk_id": f"{os.path.basename(path)}:{i}"})
    return pool


def _embed_one(text: str) -> list:
    """A single real embedding call (Voyage's voyage-law-2, the same model the core corpus uses).
    Tests replace this with a synthetic stand-in -- never a real API call in a test."""
    import voyageai
    client = voyageai.Client()
    return client.embed([text], model="voyage-law-2", input_type="query").embeddings[0]


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _similarity(question: str, chunk: dict) -> float:
    """Real similarity between a question and a chunk. Tests replace this with a deterministic
    stand-in so no test run makes a real embedding call."""
    return _cosine(_embed_one(question), chunk["embedding"])


def search_pilot_tier(question: str, pool: list = None, chunk_dir: str = "pilot_chunks") -> list:
    """The wider-tier matches for a free-text question, above PILOT_TIER_SIMILARITY_THRESHOLD,
    best first, capped at MAX_RESULTS. Never raises on an empty/no-match pool -- returns []."""
    if pool is None:
        pool = load_pilot_pool(chunk_dir)
    scored = []
    for chunk in pool:
        score = _similarity(question, chunk)
        if score >= PILOT_TIER_SIMILARITY_THRESHOLD:
            scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    # at most one chunk per case, the best-scoring one, so a single long judgment can't crowd out
    # every other case in the result list
    seen_cases, out = set(), []
    for score, chunk in scored:
        if chunk["case_name"] in seen_cases:
            continue
        seen_cases.add(chunk["case_name"])
        out.append({**chunk, "score": score})
        if len(out) >= MAX_RESULTS:
            break
    return out


_NUMERIC_PARAGRAPH = lambda v: isinstance(v, str) and v.strip().isdigit()


def format_pilot_result(chunk: dict) -> str:
    """Case identification + (a real paragraph number, ONLY if this chunk genuinely has one) +
    the verified source link + an unmissable 'wider tier, not the core library' label. Deliberately
    does NOT include the chunk's own text -- describing what a passage says, grounded in the real
    text, is chat_assistant.py's phrasing job (a later, separate step), not this module's."""
    bits = [chunk["case_name"]]
    if chunk.get("citation"):
        bits.append(f"({chunk['citation']})")
    if chunk.get("chunk_method") == "paragraph_number" and _NUMERIC_PARAGRAPH(chunk.get("paragraph_number")):
        bits.append(f"-- paragraph {chunk['paragraph_number']}")
    lines = [" ".join(bits), f"Source (Supreme Court of India, not independently verified against the "
             f"official record): {chunk['source_url']}",
             "This case discussed a similar question -- it is not a conclusion about your own situation."]
    return "\n".join(lines)


if __name__ == "__main__":
    pool = load_pilot_pool("pilot_chunks")
    print(f"Loaded {len(pool)} chunks across {len({c['case_name'] for c in pool})} cases.")
