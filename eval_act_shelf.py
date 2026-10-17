"""
eval_act_shelf.py -- measures how well a search of the Act shelf finds the right section, on the gold set act_shelf/eval_questions.json.  Written 2026-10-16.
A maintenance tool, never run by the site. It embeds the questions with voyage-law-2 (input_type="query", exactly as the site does), ranks the sections of the question's own Act by cosine
similarity against act_shelf/shelf_embeddings.json, and reports where the expected section came out. It also reports a plain keyword (BM25) ranking and the two fused (reciprocal rank fusion),
so that a decision to keep the shelf's search to the one signal is made on a number.

What the numbers are and are not: the gold set is Claude's (AI-marked, written before the first run, committed first), not a lawyer's list; 75 questions are enough to see a large problem, not to
rank two close methods; nothing here involves the answer-writing model. It says how often the search puts the section a reader would want in the first few places, nothing about answers.

Usage:  python eval_act_shelf.py [--cache FILE] [--out FILE]      (needs VOYAGE_API_KEY unless the cache already holds the question vectors)
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SHELF = os.path.join(HERE, "act_shelf")
MODEL = "voyage-law-2"
_TOKEN = re.compile(r"[a-z0-9]+")
K_LIST = (1, 3, 5, 8)
RRF_K = 60


def text_sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def load_shelf():
    """-> {act_key: [chunk, ...]} for the non-omitted sections, each chunk with its embedding attached; refuses a stale or missing embedding."""
    with open(os.path.join(SHELF, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(os.path.join(SHELF, "shelf_embeddings.json"), encoding="utf-8") as fh:
        emb = json.load(fh)
    if emb.get("model") != MODEL:
        raise SystemExit(f"shelf embeddings were made with {emb.get('model')!r}, not {MODEL!r}")
    by_id = {r["chunk_id"]: r for r in emb["records"]}
    out = {}
    for a in manifest["acts"]:
        with open(os.path.join(SHELF, f"{a['key']}.json"), encoding="utf-8") as fh:
            chunks = [c for c in json.load(fh) if not c.get("omitted")]
        for c in chunks:
            r = by_id.get(f"act:{c['act']}:{c['section_number']}")
            if r is None or r["text_sha"] != text_sha(c["text"]):
                raise SystemExit(f"stale or missing embedding for {c['act']} s.{c['section_number']}")
            c["_vec"] = np.array(r["embedding"], dtype=float)
        out[a["key"]] = chunks
    return out


def embed_questions(questions, cache_path):
    """-> ({id: vector}, tokens_billed). Question vectors are cached by (id, sha of the question text) so that analysis can be repeated without paying again."""
    cache = {}
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)
    need = [q for q in questions if cache.get(q["id"], {}).get("sha") != text_sha(q["q"])]
    billed = 0
    if need:
        if not os.environ.get("VOYAGE_API_KEY"):
            raise SystemExit("VOYAGE_API_KEY is not set and the cache does not hold every question")
        import voyageai
        client = voyageai.Client()
        for i in range(0, len(need), 64):
            batch = need[i:i + 64]
            r = client.embed([q["q"] for q in batch], model=MODEL, input_type="query")
            billed += int(getattr(r, "total_tokens", 0) or 0)
            for q, v in zip(batch, r.embeddings):
                cache[q["id"]] = {"sha": text_sha(q["q"]), "vec": v}
        if cache_path:
            with open(cache_path, "w", encoding="utf-8") as fh:
                json.dump(cache, fh)
    return {q["id"]: np.array(cache[q["id"]]["vec"], dtype=float) for q in questions}, billed


def bm25_scores(query, docs, k1=1.5, b=0.75):
    toks = [_TOKEN.findall((d or "").lower()) for d in docs]
    n = len(toks)
    avgdl = sum(len(t) for t in toks) / max(n, 1)
    df = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    scores = []
    q = _TOKEN.findall(query.lower())
    for t in toks:
        tf = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avgdl))
        scores.append(s)
    return np.array(scores)


def ranks_from(scores):
    order = np.argsort(-scores, kind="stable")
    rank = np.empty(len(scores), dtype=int)
    rank[order] = np.arange(1, len(scores) + 1)
    return order, rank


def first_rank(chunks, rank, wanted):
    hits = [int(rank[i]) for i, c in enumerate(chunks) if c["section_number"] in wanted]
    return min(hits) if hits else None


def evaluate(gold, shelf, qvecs):
    rows = []
    for q in gold["questions"]:
        chunks = shelf[q["act_key"]]
        mat = np.vstack([c["_vec"] for c in chunks])
        sem = mat @ qvecs[q["id"]]
        lex = bm25_scores(q["q"], [c["text"] for c in chunks])
        _, r_sem = ranks_from(sem)
        _, r_lex = ranks_from(lex)
        fused = 1.0 / (RRF_K + r_sem) + 1.0 / (RRF_K + r_lex)
        order_f, r_fus = ranks_from(fused)
        strict, lenient = set(q["expected"]), set(q["expected"]) | set(q["also_ok"])
        order_s = np.argsort(-sem, kind="stable")
        exp_idx = [i for i, c in enumerate(chunks) if c["section_number"] in strict]
        rows.append({
            "id": q["id"], "act_key": q["act_key"], "kind": q["kind"], "hard": q["hard"], "q": q["q"], "expected": q["expected"], "also_ok": q["also_ok"],
            "rank_sem": first_rank(chunks, r_sem, strict), "rank_sem_lenient": first_rank(chunks, r_sem, lenient),
            "rank_lex": first_rank(chunks, r_lex, strict), "rank_lex_lenient": first_rank(chunks, r_lex, lenient),
            "rank_fused": first_rank(chunks, r_fus, strict), "rank_fused_lenient": first_rank(chunks, r_fus, lenient),
            "top5_sem": [chunks[i]["section_number"] for i in order_s[:5]],
            "top5_scores": [round(float(sem[i]), 4) for i in order_s[:5]],
            "expected_score": round(float(max(sem[i] for i in exp_idx)), 4),
            "n_sections": len(chunks),
        })
    return rows


def summarize(rows, key):
    n = len(rows)
    out = {"n": n}
    for k in K_LIST:
        out[f"hit@{k}"] = round(sum(1 for r in rows if r[key] is not None and r[key] <= k) / n, 3) if n else None
    out["mrr"] = round(sum(1.0 / r[key] for r in rows if r[key]) / n, 3) if n else None
    return out


def threshold_table(rows, thresholds, ks):
    """For a cut (score >= t, at most k sections): how many questions get the strict expected section, and how many sections are handed over on average."""
    out = []
    for t in thresholds:
        for k in ks:
            got, handed = 0, 0
            for r in rows:
                kept = [(s, sec) for s, sec in zip(r["top5_scores"], r["top5_sem"]) if s >= t][:k]
                handed += len(kept)
                if any(sec in r["expected"] for _, sec in kept):
                    got += 1
            out.append({"threshold": t, "k": k, "found": got, "of": len(rows), "avg_sections_returned": round(handed / len(rows), 2)})
    return out


def offtopic_scores(path, shelf, cache_path):
    """Best within-Act score for questions that name a shelf Act but ask for something it does not contain (act_shelf/eval_offtopic_questions.json): what 'nothing relevant' looks like. -> (rows, tokens billed)."""
    if not os.path.exists(path):
        return [], 0
    with open(path, encoding="utf-8") as fh:
        probes = json.load(fh)
    body = json.dumps(probes["questions"], sort_keys=True, ensure_ascii=False)
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != probes["questions_sha256"]:
        raise SystemExit("the off-topic probes were changed after they were frozen")
    vecs, billed = embed_questions(probes["questions"], cache_path)
    rows = []
    for q in probes["questions"]:
        chunks = shelf[q["act_key"]]
        sem = np.vstack([c["_vec"] for c in chunks]) @ vecs[q["id"]]
        order = np.argsort(-sem, kind="stable")[:3]
        rows.append({"id": q["id"], "act_key": q["act_key"], "q": q["q"], "top3": [chunks[i]["section_number"] for i in order], "top3_scores": [round(float(sem[i]), 4) for i in order]})
    return rows, billed


def whole_path(gold):
    """For the questions whose Act the manifest marks "whole_act": the REAL search (act_shelf.search, ACT_SHELF=on for this call only) with an embedding function that fails if it is ever called.
    A very short Act is handed over in full, so the question is whether every section the gold set expects (strict and also_ok) is in what is handed over, and that no Voyage call was made.
    This checks the delivery, not whether the answer model uses the right section. -> rows (empty when no gold question is about a whole Act)."""
    import act_shelf
    with open(os.path.join(SHELF, "manifest.json"), encoding="utf-8") as fh:
        whole_keys = {a["key"] for a in json.load(fh)["acts"] if a.get("whole_act")}
    rows = []
    before = os.environ.get("ACT_SHELF")
    os.environ["ACT_SHELF"] = "on"
    try:
        def _no_voyage(_text):
            raise AssertionError("a whole Act must not need a question vector")
        for q in gold["questions"]:
            if q["act_key"] not in whole_keys:
                continue
            res = act_shelf.search(q["q"], [{"id": q["act_key"]}], embed_fn=_no_voyage)
            got = [m["section_number"] for m in res["matches"]]
            want = [str(x).upper() for x in q["expected"]]
            ok_also = [str(x).upper() for x in q.get("also_ok", [])]
            rows.append({"id": q["id"], "act_key": q["act_key"], "delivered": got, "expected_in": all(w in [g.upper() for g in got] for w in want),
                         "also_ok_in": all(w in [g.upper() for g in got] for w in ok_also), "chars": res["info"]["chars"], "embed": res["info"]["embed"], "error": res["info"].get("error")})
    finally:
        if before is None:
            os.environ.pop("ACT_SHELF", None)
        else:
            os.environ["ACT_SHELF"] = before
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default=os.path.join(SHELF, "eval_questions.json"))
    ap.add_argument("--offtopic", default=os.path.join(SHELF, "eval_offtopic_questions.json"))
    ap.add_argument("--cache", default=None, help="file that keeps the question vectors, so the analysis can be repeated for free")
    ap.add_argument("--out", default=os.path.join(SHELF, "EVAL_RESULTS.json"))
    args = ap.parse_args(argv)
    with open(args.gold, encoding="utf-8") as fh:
        gold = json.load(fh)
    body = json.dumps(gold["questions"], sort_keys=True, ensure_ascii=False)
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != gold["questions_sha256"]:
        raise SystemExit("the gold set was changed after it was frozen (questions_sha256 does not match)")
    shelf = load_shelf()
    qvecs, billed = embed_questions(gold["questions"], args.cache)
    rows = evaluate(gold, shelf, qvecs)
    off_rows, off_billed = offtopic_scores(args.offtopic, shelf, args.cache)
    billed += off_billed
    methods = {"semantic": "rank_sem", "keyword_bm25": "rank_lex", "fused_rrf": "rank_fused"}
    result = {"run_on": datetime.date.today().isoformat(), "model": MODEL, "questions_sha256": gold["questions_sha256"], "question_tokens_billed_this_run": billed,
              "note": f"AI-marked gold set (Claude's, written and committed before this run); {len(gold['questions'])} questions; measures where the search puts the expected section, not answer quality.",
              "overall": {m: summarize(rows, k) for m, k in methods.items()},
              "overall_lenient": {m: summarize(rows, k + "_lenient") for m, k in methods.items()},
              "by_act": {a: {m: summarize([r for r in rows if r["act_key"] == a], k) for m, k in methods.items()} for a in sorted({r["act_key"] for r in rows})},
              "by_kind": {kd: {m: summarize([r for r in rows if r["kind"] == kd], k) for m, k in methods.items()} for kd in ("layman", "lawyer")},
              "by_hard": {str(h): {m: summarize([r for r in rows if r["hard"] == h], k) for m, k in methods.items()} for h in (False, True)},
              "thresholds": threshold_table(rows, [0.30, 0.34, 0.38, 0.42, 0.46, 0.50], (3, 5)),
              "offtopic": off_rows,
              "whole_path": whole_path(gold),
              "rows": rows}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    print(f"gold {gold['questions_sha256'][:12]}; question tokens billed this run: {billed}")
    for name, block in (("strict", result["overall"]), ("lenient (also_ok counts)", result["overall_lenient"])):
        print(f"\n{name}")
        for m, s in block.items():
            print(f"  {m:13s} n={s['n']}  " + "  ".join(f"top{k}={s[f'hit@{k}']:.2f}" for k in K_LIST) + f"  mrr={s['mrr']:.2f}")
    print("\nsemantic, by Act (strict)")
    for a, b in result["by_act"].items():
        s = b["semantic"]
        print(f"  {a:16s} " + "  ".join(f"top{k}={s[f'hit@{k}']:.2f}" for k in K_LIST) + f"  mrr={s['mrr']:.2f}")
    print("\nsemantic, by kind / hard (strict)")
    for kd, b in result["by_kind"].items():
        s = b["semantic"]
        if s["n"]:
            print(f"  {kd:8s} n={s['n']} " + "  ".join(f"top{k}={s[f'hit@{k}']:.2f}" for k in K_LIST))
    for h, b in result["by_hard"].items():
        s = b["semantic"]
        if s["n"]:
            print(f"  hard={h:5s} n={s['n']} " + "  ".join(f"top{k}={s[f'hit@{k}']:.2f}" for k in K_LIST))
    if off_rows:
        tops = sorted(r["top3_scores"][0] for r in off_rows)
        print("\noff-topic probes (a shelf Act named, something it does not contain asked): best within-Act score " + ", ".join(f"{t:.3f}" for t in tops))
        gold_tops = sorted(r["top5_scores"][0] for r in rows)
        print(f"  for comparison, the best score on the {len(rows)} gold questions: lowest {gold_tops[0]:.3f}, 10th lowest {gold_tops[9]:.3f}, median {gold_tops[len(gold_tops) // 2]:.3f}")
    if result["whole_path"]:
        wp = result["whole_path"]
        print(f"\nwhole-Act delivery (the real search; the Act is handed over in full, no question vector): {sum(1 for r in wp if r['expected_in'])} of {len(wp)} have the expected section(s) among those handed over, "
              f"{sum(1 for r in wp if r['also_ok_in'])} of {len(wp)} the also-ok ones as well; embedding calls: {sum(1 for r in wp if r['embed'] != 'not needed')}; errors: {sum(1 for r in wp if r['error'])}")
        for r in wp:
            if not (r["expected_in"] and r["also_ok_in"]) or r["error"] or r["embed"] != "not needed":
                print(f"  PROBLEM {r['id']}: {r}")
    print("\nmisses (semantic, expected not in the top 5)")
    for r in rows:
        if r["rank_sem"] is None or r["rank_sem"] > 5:
            print(f"  {r['id']} expected {r['expected']} came {r['rank_sem']} of {r['n_sections']}; top5 {r['top5_sem']} ({r['top5_scores'][0]}); {r['q'][:80]}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
