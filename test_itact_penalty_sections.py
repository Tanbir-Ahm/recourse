"""
test_itact_penalty_sections.py -- IT Act sections 72 and 72A in the library (2026-11-02, owner: "Fix the IT s.72 and s.72A library sections"): the library's chunks, their embeddings and the structured table carry the wording in force since
30 November 2023 (Act 18 of 2023: "liable to penalty", no imprisonment), taken from the text checked against India Code's PDF (act_shelf/it_act_2000.json); the answer guards no longer treat them as cognizable/bailable offences.  Offline and free.
Run: python -X utf8 test_itact_penalty_sections.py
"""
import difflib
import json
import os
import sys

import build_act_chunks as B

HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def jl(*p):
    with open(os.path.join(HERE, *p), encoding="utf-8") as fh:
        return json.load(fh)


lib = {c["section_number"]: c for c in jl("chunks", "information_technology_act_2000_chunks.json")}
shelf = {c["section_number"]: c for c in jl("act_shelf", "it_act_2000.json")}
for n, amount in (("72", "five lakh rupees"), ("72A", "twenty-five lakh rupees")):
    t = lib[n]["text"]
    check("liable to penalty which may extend to " + amount in t and "imprisonment" not in t and "punished" not in t, f"library s.{n}: 'liable to penalty ... {amount}', no imprisonment")
    a, b = B.norm_words(t), B.norm_words(shelf[n]["text"])
    check(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() == 1.0, f"library s.{n}: every word equals the text checked against India Code's PDF")
check(lib["72A"]["text"].startswith("72A. Penalty for disclosure of information in breach of lawful contract."), "library s.72A: the heading reads 'Penalty ...' as the PDF does")
check(sorted(lib) == ["66", "66B", "66C", "66D", "66E", "67", "67A", "67B", "72", "72A"], "library: the ten IT sections are all still there")
check("imprisonment" in lib["67"]["text"] and "imprisonment" in lib["66C"]["text"], "library: the other IT sections (67, 66C) still carry their imprisonment")

emb = {r["chunk_id"]: r for r in jl("embeddings", "corpus_embeddings.json")["records"]}
for n in ("72", "72A"):
    r = emb[f"statute:ITACT:{n}"]
    check(r["text"] == lib[n]["text"] and len(r["embedding"]) == 1024, f"embedding of s.{n}: made from the corrected text, 1024 numbers")
check(all(emb[f"statute:ITACT:{n}"]["text"] == lib[n]["text"] for n in lib), "embeddings: every IT chunk's embedded text equals its chunk text")

from itact_section_data import ITACT_SECTION_DATA as T  # noqa: E402

for n in ("72", "72A"):
    d = T[n]
    check(d["punishment_shape"] == "penalty_only" and d["max_years"] is None and d["cognizable"] is None and d["bailable"] is None, f"table s.{n}: penalty only, no years, no cognizable/bailable")
check(T["72"]["penalty_up_to"].startswith("5,00,000") and T["72A"]["penalty_up_to"].startswith("25,00,000"), "table: the amounts (five lakh, twenty-five lakh rupees)")
check(T["66C"]["cognizable"] is True and T["66C"]["max_years"] == 3, "table: the other sections are untouched (66C: three years, cognizable)")

import chat_assistant as CA  # noqa: E402
import semantic_retrieval as SR  # noqa: E402

v72 = {"72": T["72"]}
check(CA._find_cognizable_bailable_mismatches("Section 72 of the IT Act is cognizable and non-bailable.", v72) == [], "guard: a claim about section 72 raises no 'wrong cognizable/bailable' retry (there is no such fact to contradict; before, the table said non-cognizable and bailable and forced one)")
check(CA._find_cognizable_bailable_omissions("Section 72 is bailable.", v72) == [], "guard: nor an 'also say cognizable' prompt")
v66 = {"66": T["66"]}
check(len(CA._find_cognizable_bailable_mismatches("Section 66 of the IT Act is non-cognizable.", v66)) == 1, "guard: a wrong claim about an ordinary section (66) is still caught")
m72a = SR._enrich_statute_match({"act": "ITACT", "section_number": "72A", "type": "statute", "score": 0.6})
m66c = SR._enrich_statute_match({"act": "ITACT", "section_number": "66C", "type": "statute", "score": 0.6})
check(SR._conflict_state([m72a, m66c]) == "single_match", "conflict test: a penalty-only section next to a cognizable one is not a 'conflict' between sections")
text = CA.format_retrieved_text_for_prompt([dict(m72a, text=lib["72A"]["text"], score=0.6)])
check("a penalty only" in text and "cognizable=None" not in text and "max_years=None" not in text, "prompt: s.72A is given as 'a penalty only', not as 'cognizable=None, max_years=None'")
text66 = CA.format_retrieved_text_for_prompt([dict(m66c, text=lib["66C"]["text"], score=0.6)])
check("cognizable=True" in text66 and "max_years=3" in text66, "prompt: an ordinary IT section is rendered as before")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")
