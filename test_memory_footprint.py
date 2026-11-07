"""
test_memory_footprint.py -- the engine's memory trims of 2026-11-07 (FOLLOW_UPS 2dq in the research repository): PyMuPDF is imported where it is used (main.py), the per-record vector lists of the corpus
embeddings are released once the matrix is built (semantic_retrieval), and the page refuses uploads over 10 MB (.streamlit/config.toml). Each check also proves that what it trimmed still works.
Offline and free (no model, no network; the embedding call is replaced). Run: python -X utf8 test_memory_footprint.py
"""
import json
import os
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def child(code, **env):
    e = {k: v for k, v in os.environ.items() if k not in ("KEEP_RECORD_VECTORS",)}
    e.update(env)
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=HERE, env=e, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "", p.stderr[-300:]


# 1. PyMuPDF is not loaded by the engine, the page or the WhatsApp bot's imports ...
rc, out, err = child("import sys, warnings; warnings.filterwarnings('ignore'); import chat_assistant, recourse_app; print('fitz' in sys.modules or 'pymupdf' in sys.modules)")
check(rc == 0 and out == "False", f"importing chat_assistant and recourse_app does not load PyMuPDF (about 100 MB): got {out!r} {err if rc else ''}")
rc, out, err = child("import sys, warnings; warnings.filterwarnings('ignore'); import whatsapp_bot; print('fitz' in sys.modules or 'pymupdf' in sys.modules)")
check(rc == 0 and out == "False", f"importing whatsapp_bot does not load PyMuPDF: got {out!r} {err if rc else ''}")
rc, out, err = child("import sys, warnings; warnings.filterwarnings('ignore'); import api.main; import api.engine_adapter; print('fitz' in sys.modules or 'pymupdf' in sys.modules)")
check(rc == 0 and out == "False", f"importing the API service does not load PyMuPDF: got {out!r} {err if rc else ''}")

# 2. ... and the function that needs it still works, loading it on the first call
import main as M
pdfs = sorted(f for f in os.listdir(HERE) if f.startswith("Sample_") and f.endswith(".pdf"))
check(bool(pdfs), "a sample PDF is in the repository to test with")
txt = M.extract_text_from_pdf(os.path.join(HERE, pdfs[0])) if pdfs else ""
check(len(txt.strip()) > 50, f"main.extract_text_from_pdf still reads a PDF ({len(txt)} characters)")
check("fitz" in sys.modules, "the first PDF read loads PyMuPDF (so it is loaded on demand)")
src = open(os.path.join(HERE, "main.py"), encoding="utf-8").read()
check(not src.startswith("import fitz") and "\nimport fitz\n" not in src.split("def extract_text_from_pdf")[0], "main.py no longer imports PyMuPDF at module level")

# 3. the corpus embeddings: records without their vector lists, the same matrix, the same scores
import numpy as np
import semantic_retrieval as sr
sr._corpus_cache = None
corpus = sr._load_corpus_embeddings()
check(corpus is not None and len(corpus["records"]) > 1000, f"the corpus loads ({len(corpus['records']) if corpus else 0} records)")
check(not any("embedding" in r for r in corpus["records"]), "the records no longer carry their own copy of the vector")
raw = json.load(open(sr.EMBEDDINGS_PATH, encoding="utf-8"))
expect = np.array([r["embedding"] for r in raw["records"]])
check(corpus["matrix"].shape == expect.shape and corpus["matrix"].dtype == expect.dtype and np.array_equal(corpus["matrix"], expect), "the matrix is exactly what building it from the file gives")
check(all({k: v for k, v in r.items()} == {k: v for k, v in rr.items() if k != "embedding"} for r, rr in zip(corpus["records"], raw["records"])), "every other field of every record is unchanged")

# semantic_search: same ranking and scores as computed straight from the file's vectors; no vector in the results
rng = np.random.default_rng(7)
qv = rng.normal(size=expect.shape[1]); qv = qv / np.linalg.norm(qv)


class FakeClient:
    def __init__(self, *a, **k):
        pass

    def embed(self, texts, model=None, input_type=None):
        return types.SimpleNamespace(embeddings=[qv.tolist()], total_tokens=3)


sr.voyageai = types.SimpleNamespace(Client=FakeClient)
sr._voyage_available = True
res = sr.semantic_search("anything", top_k=20)
scores = expect @ qv
top = np.argsort(scores)[::-1][:20]
check(res is not None and len(res) == 20 and [round(r["score"], 12) for r in res] == [round(float(scores[i]), 12) for i in top], "semantic_search returns the same 20 chunks with the same scores as the file's own vectors give")
check(all("embedding" not in r for r in res), "no result carries a vector")

# 4. the way back: KEEP_RECORD_VECTORS=on keeps the lists
rc, out, err = child("import warnings; warnings.filterwarnings('ignore'); import semantic_retrieval as s; c = s._load_corpus_embeddings(); print(all('embedding' in r for r in c['records']))", KEEP_RECORD_VECTORS="on")
check(rc == 0 and out == "True", f"KEEP_RECORD_VECTORS=on keeps the lists (the way back): got {out!r} {err if rc else ''}")

# 5. the upload cap
try:
    import tomllib
    cfg = tomllib.load(open(os.path.join(HERE, ".streamlit", "config.toml"), "rb"))
    cap = cfg.get("server", {}).get("maxUploadSize")
except Exception as exc:  # noqa: BLE001
    cap = repr(exc)
import recourse_upload
check(isinstance(cap, int) and recourse_upload._MAX_BYTES // (1024 * 1024) <= cap <= 20, f"the page's upload cap (maxUploadSize = {cap} MB) is at least the page's own 8 MB limit and far below Streamlit's default of 200")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
