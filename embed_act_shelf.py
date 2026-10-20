"""
embed_act_shelf.py -- embeds the sections of the Act shelf (act_shelf/<key>.json, written by build_act_chunks.py) with voyage-law-2 into act_shelf/shelf_embeddings.json.  Written 2026-10-16.
A maintenance tool, never run by the site. Costs a few cents (about 84,000 tokens for the first five Acts) and logs what was billed.

Why a file of its own and not embeddings/corpus_embeddings.json: the shared file is searched for EVERY question, statutes and judgments together; putting a new Act in it would let its sections surface
for questions that have nothing to do with that Act, and a re-run of embed_corpus.py would treat the new chunk files as judgments (twice already a bug there). The shelf is searched only when a question
names the Act (act_shelf.py), and only that Act's sections are ranked.

Each record carries the sha256 of the text it was embedded from: if a section is reloaded and its text changes, its embedding is stale and the shelf (act_shelf.py) refuses to use it until it is re-embedded.
Omitted and repealed stubs are not embedded (they are still reachable by number).

Usage:  python embed_act_shelf.py [--only pc_act_1988] [--dry-run] [--force]
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SHELF = os.path.join(HERE, "act_shelf")
OUT = os.path.join(SHELF, "shelf_embeddings.json")
MODEL = "voyage-law-2"                 # the same model the site embeds questions with (semantic_retrieval.MODEL)
USD_PER_MILLION_TOKENS = 0.12          # voyage-law-2 list price; the real bill is what the free allowance and the account say


def text_sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def chunk_id(chunk):
    return f"act:{chunk['act']}:{chunk['section_number']}"


def load_chunks(only=None):
    with open(os.path.join(SHELF, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    out = []
    for a in manifest["acts"]:
        if only and a["key"] != only:
            continue
        path = os.path.join(SHELF, f"{a['key']}.json")
        if not os.path.exists(path):
            print(f"WARNING: {path} not found, skipping")
            continue
        with open(path, encoding="utf-8") as fh:
            out += [c for c in json.load(fh) if not c.get("omitted")]
    return out


def embed_texts(client, texts, tries=4):
    last = None
    for attempt in range(tries):
        try:
            r = client.embed(texts, model=MODEL, input_type="document")
            return r.embeddings, int(getattr(r, "total_tokens", 0) or 0)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"Voyage failed after {tries} tries: {type(last).__name__}: {str(last)[:200]}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-embed everything, not only new or changed sections")
    args = ap.parse_args(argv)
    chunks = load_chunks(args.only)
    existing = {}
    if os.path.exists(OUT) and not args.force:
        with open(OUT, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("model") != MODEL:
            raise SystemExit(f"{OUT} was made with {data.get('model')!r}, not {MODEL!r}: use --force")
        existing = {r["chunk_id"]: r for r in data["records"]}
    todo = [c for c in chunks if existing.get(chunk_id(c), {}).get("text_sha") != text_sha(c["text"])]
    est_tokens = int(sum(len(c["text"]) for c in todo) / 3.87)
    print(f"{len(chunks)} sections on the shelf, {len(todo)} to embed (new or changed), about {est_tokens:,} tokens, about ${est_tokens / 1e6 * USD_PER_MILLION_TOKENS:.4f} at list price")
    if args.dry_run or not todo:
        return 0
    if not os.environ.get("VOYAGE_API_KEY"):
        raise SystemExit("VOYAGE_API_KEY is not set")
    import voyageai
    from embed_corpus import build_token_aware_batches
    client = voyageai.Client()
    items = [{"text": c["text"], "chunk": c} for c in todo]
    batches, oversized = build_token_aware_batches(items)
    if oversized:
        raise SystemExit(f"{len(oversized)} section(s) are too long to embed: {[chunk_id(i['chunk']) for i in oversized]}")
    billed = 0
    records = dict(existing)
    for n, batch in enumerate(batches, 1):
        vectors, tokens = embed_texts(client, [i["text"] for i in batch])
        billed += tokens
        for i, v in zip(batch, vectors):
            c = i["chunk"]
            records[chunk_id(c)] = {"chunk_id": chunk_id(c), "act": c["act"], "act_key": c["act_key"], "section_number": c["section_number"], "title": c["title"], "text_sha": text_sha(c["text"]), "embedding": v}
        print(f"  batch {n}/{len(batches)}: {len(batch)} sections, {tokens:,} tokens billed")
        time.sleep(1)
    keep = {chunk_id(c) for c in load_chunks(None)}
    ordered = [records[k] for k in sorted(records) if k in keep]            # a section that has left the shelf leaves its embedding too
    prev_billed = 0
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            prev_billed = json.load(fh).get("tokens_billed_total", 0)
    total_billed = prev_billed + billed
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"model": MODEL, "written": datetime.date.today().isoformat(), "chunk_count": len(ordered), "tokens_billed_this_run": billed, "tokens_billed_total": total_billed,
                   "estimated_cost_usd_total": round(total_billed / 1e6 * USD_PER_MILLION_TOKENS, 4), "records": ordered}, fh)
    print(f"wrote {OUT}: {len(ordered)} records; this run {billed:,} tokens (about ${billed / 1e6 * USD_PER_MILLION_TOKENS:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
