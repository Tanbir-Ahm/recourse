
"""
Embed the entire sourced corpus (BNS/BNSS statute sections + judgment
paragraphs) using Voyage AI's voyage-law-2 model, and save the resulting
vectors to disk as a single JSON file.

This is a ONE-TIME job, not something that runs on every query. Re-run it
only when the corpus itself changes (new sections, new judgments, or a
chunking fix that changes chunk boundaries).

Why voyage-law-2 specifically: trained on statutes, case law, and court
documents -- confirmed via Voyage AI's own published benchmarks to
outperform general-purpose embedding models on legal retrieval tasks by a
meaningful margin, which matters here since the entire corpus IS legal
text (BNS/BNSS sections, Supreme Court and High Court judgments).

Design principle: embeddings are used ONLY for retrieval -- finding which
section(s)/paragraph(s) are plausibly relevant to a query, WITH a real,
checkable similarity score. Nothing about how a compliance verdict gets
decided changes. The deterministic BNS_SECTION_DATA lookups and check_*
functions built earlier this session are completely untouched; this layer
only decides WHERE to look, never WHAT the answer is.

Cost note: the full corpus here is ~1,410 chunks, ~390K tokens total --
comfortably inside Voyage's free tier allocation for voyage-law-2 (50M
tokens), so this one-time embed costs nothing in practice.
"""

import json
import os
import glob
import time

try:
    import voyageai
    from voyageai.error import (
        AuthenticationError,
        InvalidRequestError,
        MalformedRequestError,
        RateLimitError,
    )
except ImportError:
    raise SystemExit(
        "voyageai package not installed. Run: pip install voyageai"
    )

# Errors worth retrying (transient: rate limits, server hiccups, network
# blips) vs. errors that will NEVER succeed no matter how many times you
# retry (bad key, malformed request, access denied). Retrying the second
# category 3 times with exponential backoff just wastes time and delays
# a clear error message.
_NON_RETRYABLE = (AuthenticationError, InvalidRequestError, MalformedRequestError)

# main.py loads .env via python-dotenv when Streamlit secrets aren't
# available; this script always runs standalone from the command line, so
# it always needs the .env loading step -- there's no st.secrets fallback
# here. Without this, VOYAGE_API_KEY sitting in .env never reaches
# os.environ, and voyageai.Client() silently constructs with api_key=None
# rather than failing immediately. Load .env explicitly and fail fast
# instead.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv should already be installed (main.py depends on it)

MODEL = "voyage-law-2"
OUTPUT_PATH = "embeddings/corpus_embeddings.json"

# RESTRATEGIZED AGAIN 2026-08-27, this time using REAL numbers returned
# by the API itself, not estimates or general tier documentation:
#
# 1. A HARD per-request cap of 120,000 tokens for voyage-law-2 -- this is
#    a request-size limit, not a rate limit, confirmed directly by the
#    API's own error message when a 500-chunk batch (~123,814 real
#    tokens) was rejected: "The max allowed tokens per submitted batch is
#    120000." No batch can ever exceed this, regardless of rate-limit
#    tier or payment status.
#
# 2. A PROJECT-SPECIFIC TPM limit of 3,000,000 tokens/minute for
#    voyage-law-2 specifically -- confirmed directly by the API's own
#    rate-limit error, which is meaningfully lower than the general
#    "Tier 1: 8,000,000 TPM" figure found in Voyage's own published
#    documentation for voyage-3.5. Per-model and per-project limits can
#    differ from general tier documentation; the real, binding number is
#    whatever the API itself reports when actually queried, not what
#    general docs imply.
#
# Given #1, batching MUST be token-volume-aware (not a fixed chunk
# count) -- confirmed real case: a fixed BATCH_SIZE=500 produced a batch
# at ~124K real tokens, since judgment paragraphs vary hugely in length
# (confirmed earlier: from a few dozen chars up to the ~98K-char BNSS 531
# outlier). A fixed count cannot reliably stay under a hard token
# ceiling when chunk sizes vary this much.
MAX_TOKENS_PER_BATCH = 100000  # solid margin under the confirmed 120,000 hard cap
CHARS_PER_TOKEN_ESTIMATE = 3.87  # confirmed real ratio from this corpus's actual API response
                                    # (validated to within 0.12% against the real token count
                                    # the API reported for the same 500-chunk sample)

# At the confirmed 3,000,000 TPM limit for this model/project, and with
# each batch now capped at 100,000 tokens, roughly 30 such batches could
# run in a single minute before approaching the TPM ceiling -- this
# corpus (a handful of batches total) stays far under that regardless of
# pacing. Kept as a minimal courtesy pause, not rate-limit avoidance.
SECONDS_BETWEEN_REQUESTS = 2

# Confirmed real case: BNSS section 531 (Repeal and Savings) is ~98,000
# characters (~24,500 estimated tokens, well under the 120,000 hard cap
# on its own, but still larger than voyage-law-2's own 16K token context
# length -- these are two separate ceilings). This is a genuine chunking
# edge case: section 531 is the LAST numbered BNSS section, and
# everything after it in the source PDF (unnumbered attached
# forms/schedules -- warrants, notices, blank templates -- plus the
# government publisher's colophon) has no section-number boundary of its
# own, so it all got swept into the same chunk as section 531's real
# text. This is skipped and reported (not embedded, not silently
# truncated) because it exceeds the MODEL's context window, not because
# of the per-request or per-minute token limits. Fixing the chunker
# itself to split this properly is separate, real, follow-up work, not
# something to solve inside an embedding script.
MAX_CHARS_PER_SINGLE_CHUNK = 40000  # ~10K tokens; conservatively under voyage-law-2's 16K context limit


def load_statute_chunks():
    """Returns a list of (chunk_id, text, metadata) for every BNS/BNSS
    statute section chunk."""
    items = []
    for act, path in [
        ("BNS", "chunks/bharatiya_nyaya_sanhita_2023_chunks.json"),
        ("BNSS", "chunks/bharatiya_nagarik_suraksha_sanhita_2023_chunks.json"),
        ("ITACT", "chunks/information_technology_act_2000_chunks.json"),
        ("NIACT", "chunks/negotiable_instruments_act_1881_chunks.json"),
    ]:
        if not os.path.exists(path):
            print(f"WARNING: {path} not found, skipping {act}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
        for c in chunks:
            chunk_id = f"statute:{act}:{c['section_number']}"
            items.append({
                "chunk_id": chunk_id,
                "text": c["text"],
                "type": "statute",
                "act": act,
                "section_number": c["section_number"],
            })
    return items


def load_judgment_chunks():
    """Returns a list of (chunk_id, text, metadata) for every judgment
    paragraph chunk, across every *_chunks.json file except the two
    statute ones.

    NOTE: skip_files is compared by basename (os.path.basename), not full
    path string, since glob.glob can return backslash-separated paths on
    Windows which would silently fail to match a forward-slash string."""
    items = []
    skip_basenames = {
        "bharatiya_nyaya_sanhita_2023_chunks.json",
        "bharatiya_nagarik_suraksha_sanhita_2023_chunks.json",
        # CONFIRMED REAL BUG (2026-09-05, Phase 3b): adding "ITACT" to
        # load_statute_chunks()'s act/path list without ALSO excluding
        # this file here meant it got loaded a SECOND time by this
        # function's catch-all glob and embedded as bogus "judgment"
        # records (no case_name/paragraph_number fields, so those built
        # a garbage chunk_id and metadata) -- caught by reconciling the
        # printed judgment-chunk count against a direct file recount
        # before trusting the embed run, not by inspection alone.
        "information_technology_act_2000_chunks.json",
        # SAME BUG, REPEATED (2026-09-18): adding "NIACT" to
        # load_statute_chunks() without this line produced 12 bogus
        # "judgment:unknown:N:N" records -- caught the same way, by
        # actually querying find_relevant_sections() after embedding and
        # noticing a judgment match with an identical score to a real
        # NIACT statute match, not by the embed run completing cleanly.
        "negotiable_instruments_act_1881_chunks.json",
    }
    for path in sorted(glob.glob("chunks/*.json")):
        if os.path.basename(path) in skip_basenames:
            continue
        with open(path, "r", encoding="utf-8") as f:
            chunks = json.load(f)
        if not chunks:
            continue
        for i, c in enumerate(chunks):
            case_name = c.get("case_name", "unknown")
            para_num = c.get("paragraph_number", str(i))
            author = c.get("opinion_author")
            author_part = f":{author}" if author else ""
            chunk_id = f"judgment:{case_name}:{para_num}{author_part}:{i}"
            items.append({
                "chunk_id": chunk_id,
                "text": c["text"],
                "type": "judgment",
                "case_name": case_name,
                "citation": c.get("citation"),
                "paragraph_number": para_num,
                "opinion_author": author,
                "source_url": c.get("source_url"),
            })
    return items


def build_token_aware_batches(items):
    """Groups items into batches that stay under MAX_TOKENS_PER_BATCH
    (estimated via CHARS_PER_TOKEN_ESTIMATE), rather than a fixed chunk
    count. Confirmed real necessity: a fixed count of 500 chunks/batch
    produced one batch at ~123,814 real tokens (per the API's own count),
    exceeding voyage-law-2's confirmed hard 120,000-token-per-request
    ceiling -- chunk sizes vary too much across this corpus for a fixed
    count to reliably stay under a hard token ceiling.

    Returns (batches, oversized_items) -- oversized_items are chunks too
    large to embed regardless of batching. These are reported, not
    silently dropped or truncated."""
    batches = []
    oversized_items = []
    current_batch = []
    current_tokens = 0

    for item in items:
        estimated_tokens = len(item["text"]) / CHARS_PER_TOKEN_ESTIMATE
        if len(item["text"]) > MAX_CHARS_PER_SINGLE_CHUNK:
            oversized_items.append(item)
            continue
        if current_batch and current_tokens + estimated_tokens > MAX_TOKENS_PER_BATCH:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        current_batch.append(item)
        current_tokens += estimated_tokens

    if current_batch:
        batches.append(current_batch)

    return batches, oversized_items


def embed_batch(client, texts, model=MODEL, max_retries=5):
    """Embeds a batch of texts as documents (input_type='document')."""
    for attempt in range(max_retries):
        try:
            result = client.embed(texts, model=model, input_type="document")
            return result.embeddings
        except _NON_RETRYABLE as e:
            raise SystemExit(
                f"Voyage API rejected the request and retrying will not help: {e}\n"
                "Check that VOYAGE_API_KEY in your .env file is a real key from "
                "https://dash.voyageai.com (not the placeholder text), and that "
                "your account is active."
            )
        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            print(f"  Rate limited: {e}")
            print(f"  Waiting 65s for the rate-limit window to clear (attempt {attempt + 1}/{max_retries})...")
            time.sleep(65)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            print(f"  Embed batch failed ({e}), retrying in {wait}s...")
            time.sleep(wait)


def load_checkpoint():
    """If OUTPUT_PATH already exists from a previous partial run,
    returns the set of chunk_ids already embedded, so a resumed run can
    skip them."""
    if not os.path.exists(OUTPUT_PATH):
        return set(), []
    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    existing_records = data.get("records", [])
    existing_ids = {r["chunk_id"] for r in existing_records}
    return existing_ids, existing_records


def save_checkpoint(embedded_records):
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "model": MODEL,
            "chunk_count": len(embedded_records),
            "records": embedded_records,
        }, f)


def main():
    if not os.environ.get("VOYAGE_API_KEY"):
        raise SystemExit(
            "VOYAGE_API_KEY not found in environment. Confirm it's set in "
            "your .env file (VOYAGE_API_KEY=your-key, no quotes, no spaces "
            "around the =) and that this script is being run from the "
            "project's root folder, where .env actually lives."
        )

    client = voyageai.Client()

    print("Verifying Voyage API key with a test call...")
    embed_batch(client, ["test"])
    print("API key verified.\n")

    statute_items = load_statute_chunks()
    judgment_items = load_judgment_chunks()
    all_items = statute_items + judgment_items

    print(f"Loaded {len(statute_items)} statute chunks, {len(judgment_items)} judgment chunks")
    print(f"Total: {len(all_items)} chunks to embed")

    already_embedded_ids, embedded_records = load_checkpoint()
    if already_embedded_ids:
        print(f"Found existing progress: {len(already_embedded_ids)} chunks already embedded -- resuming.\n")
        all_items = [item for item in all_items if item["chunk_id"] not in already_embedded_ids]
        print(f"{len(all_items)} chunks remaining to embed.\n")

    batches, oversized_items = build_token_aware_batches(all_items)
    print(f"Grouped into {len(batches)} batches (max ~{MAX_TOKENS_PER_BATCH} estimated tokens each)")
    if oversized_items:
        print(f"\nWARNING: {len(oversized_items)} chunk(s) are too large to embed and will be SKIPPED, not truncated:")
        for item in oversized_items:
            label = item.get("section_number") or item.get("paragraph_number")
            print(f"  - {item['chunk_id']} ({len(item['text'])} chars, ~{len(item['text'])//CHARS_PER_TOKEN_ESTIMATE:.0f} est. tokens)")
        print("These likely need a chunking fix (see comments in this file) before they can be embedded.\n")

    if not batches:
        print("Nothing left to embed -- already complete.")
        return

    for batch_num, batch in enumerate(batches):
        texts = [item["text"] for item in batch]
        batch_tokens = sum(len(t) for t in texts) / CHARS_PER_TOKEN_ESTIMATE
        print(f"Embedding batch {batch_num + 1}/{len(batches)} ({len(batch)} chunks, ~{batch_tokens:.0f} est. tokens)...")
        vectors = embed_batch(client, texts)
        for item, vector in zip(batch, vectors):
            record = dict(item)
            record["embedding"] = vector
            embedded_records.append(record)

        save_checkpoint(embedded_records)

        is_last_batch = (batch_num == len(batches) - 1)
        if not is_last_batch:
            print(f"  Waiting {SECONDS_BETWEEN_REQUESTS}s before next batch...")
            time.sleep(SECONDS_BETWEEN_REQUESTS)

    print(f"\nWrote {len(embedded_records)} embedded chunks to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
    
