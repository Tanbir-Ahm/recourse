"""
test_related_judgments.py

Coverage for related_judgments.py (Lane B) through Phase 1b:
  - situation decomposition (Anthropic client mocked)
  - anchor building + the answer-section anchor (real statute_concordance)
  - ik_query_builder.build_issue_query / semantic_retrieval.rerank
  - search_candidates / rank_candidates / get_related_judgments with every
    external call (IK search, local search, reranker, decomposition)
    injected -- nothing here touches the network.

Run: python test_related_judgments.py
"""

import datetime
import logging
import re
import sys
from unittest.mock import MagicMock, patch

import related_judgments as rj

# The failure-path cases below deliberately feed bad JSON / raise from the
# mocked client; related_judgments logs those at warning/exception level.
# Silence them so the test output stays readable -- the assertions, not
# the logs, are what verify the honest give-up behaviour.
logging.getLogger("related_judgments").setLevel(logging.CRITICAL)

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


def _fake_response(text):
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    return resp


# ---------------------------------------------------------------------------
# _hook_phrase_in_text -- the guard that throws away issues the user did
# not actually raise.
# ---------------------------------------------------------------------------
MSG = ("Last month police came to our house around 11pm and took my younger "
       "brother. His name was not in the FIR. They never told us why or showed "
       "any papers. It's been over two months now and no chargesheet.")

check(rj._hook_phrase_in_text("name was not in the FIR", MSG),
      "verbatim substring hook is accepted")
check(rj._hook_phrase_in_text("His name was not in the FIR", MSG),
      "case-insensitive substring hook is accepted")
check(rj._hook_phrase_in_text("no chargesheet", MSG),
      "short verbatim hook is accepted")
check(rj._hook_phrase_in_text("brother house police", MSG),
      "content-word bag match (reordered words) is accepted")
check(not rj._hook_phrase_in_text("he was beaten in custody", MSG),
      "a hook the user never said (custodial assault) is rejected")
check(not rj._hook_phrase_in_text("", MSG),
      "empty hook is rejected")
check(not rj._hook_phrase_in_text("the police station court case", MSG),
      "a hook that only overlaps on stopwords/filler is rejected")


# ---------------------------------------------------------------------------
# _parse_section_hook
# ---------------------------------------------------------------------------
check(rj._parse_section_hook("BNSS 35") == ("BNSS", "35"), "'BNSS 35' parses")
check(rj._parse_section_hook("BNS 318(4)") == ("BNS", "318"), "'BNS 318(4)' -> base number only")
check(rj._parse_section_hook("Section 187 BNSS") == ("BNSS", "187"), "'Section 187 BNSS' parses")
check(rj._parse_section_hook("Article 22(1)") is None, "'Article 22(1)' is not a BNS/BNSS section")
check(rj._parse_section_hook("D.K. Basu") is None, "'D.K. Basu' is not a section")
check(rj._parse_section_hook("") is None, "empty hook parses to None")


# ---------------------------------------------------------------------------
# extract_answer_sections
# ---------------------------------------------------------------------------
check(
    rj.extract_answer_sections("Section 303(2) covers theft; Section 35 of the BNSS applies; also Section 187.")
    == {"303", "35", "187"},
    "base section numbers pulled from an answer, subsection suffix stripped",
)
check(rj.extract_answer_sections("no section numbers here") == set(),
      "an answer with no sections -> empty set")


# ---------------------------------------------------------------------------
# build_anchors -- real concordance lookups, no LLM, no network.
# ---------------------------------------------------------------------------
profile = {
    "primary_grievance": "brother held without grounds",
    "procedural_stage": "arrested, pre-chargesheet, ~2 months",
    "issues": [
        {"issue": "grounds of arrest not communicated",
         "hook_phrase": "never told us why", "section_hooks": ["BNSS 47", "Article 22(1)"]},
        {"issue": "arrest of a person not named in the FIR",
         "hook_phrase": "name was not in the FIR", "section_hooks": ["BNSS 35"]},
        {"issue": "chargesheet not filed in time",
         "hook_phrase": "no chargesheet", "section_hooks": ["BNSS 187"]},
        {"issue": "some issue with no section",
         "hook_phrase": "took my younger brother", "section_hooks": []},
    ],
}
anchors = rj.build_anchors(profile)

check(len(anchors) == 4, "one anchor per issue")
a0, a1, a2, a3 = anchors

check(a0["new_sections"] == ["BNSS 47"], "BNSS 47 kept as the new-section label")
check("CrPC 50" in a0["old_sections"], "BNSS 47 -> CrPC 50 via concordance")
check(a0["doctrine_hooks"] == ["Article 22(1)"], "'Article 22(1)' kept as a doctrine hook, not a section")

check("CrPC 41" in a1["old_sections"], "BNSS 35 -> CrPC 41 via concordance")
check(a1["hook_phrase"] == "name was not in the FIR", "hook phrase carried onto the anchor")

check("CrPC 167" in a2["old_sections"], "BNSS 187 -> CrPC 167 (default bail) via concordance")

check(a3["new_sections"] == [] and a3["old_sections"] == [] and a3["doctrine_hooks"] == [],
      "an issue with no section hooks yields an anchor with empty lists (still searchable by phrase)")

check(rj.build_anchors(None) == [], "build_anchors(None) -> []")
check(rj.build_anchors({}) == [], "build_anchors({}) -> []")


# ---------------------------------------------------------------------------
# decompose_situation -- model mocked.
# ---------------------------------------------------------------------------
GOOD_JSON = """{
  "primary_grievance": "brother arrested and held without grounds",
  "procedural_stage": "arrested, pre-chargesheet, ~2 months",
  "issues": [
    {"issue": "grounds of arrest not communicated", "hook_phrase": "never told us why", "section_hooks": ["BNSS 47", "Article 22(1)"]},
    {"issue": "arrest of a person not named in the FIR", "hook_phrase": "name was not in the FIR", "section_hooks": ["BNSS 35"]},
    {"issue": "chargesheet not filed within the time limit", "hook_phrase": "no chargesheet", "section_hooks": ["BNSS 187"]}
  ]
}"""

with patch("related_judgments.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response(GOOD_JSON)]
    result = rj.decompose_situation(MSG)
    check(result is not None, "a clean multi-issue message decomposes")
    check(len(result["issues"]) == 3, "all three verified issues are kept")
    check(result["issues"][0]["issue"] == "grounds of arrest not communicated",
          "issue order is preserved (most important first)")
    check(result["primary_grievance"].startswith("brother"), "primary_grievance carried through")

# An issue whose hook_phrase is NOT in the user's message must be dropped.
HALLUCINATED_HOOK_JSON = """{
  "primary_grievance": "x", "procedural_stage": "y",
  "issues": [
    {"issue": "real issue", "hook_phrase": "name was not in the FIR", "section_hooks": []},
    {"issue": "invented issue", "hook_phrase": "he was tortured with electric shocks", "section_hooks": []}
  ]
}"""
with patch("related_judgments.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response(HALLUCINATED_HOOK_JSON)]
    result = rj.decompose_situation(MSG)
    check(result is not None and len(result["issues"]) == 1,
          "an issue with a hook the user never said is dropped; the real one survives")
    check(result["issues"][0]["issue"] == "real issue", "the surviving issue is the grounded one")

# More than MAX_ISSUES -> capped.
many = ", ".join(f'{{"issue": "i{n}", "hook_phrase": "police came to our house", "section_hooks": []}}'
                 for n in range(8))
with patch("related_judgments.client") as mock_client:
    mock_client.messages.create.side_effect = [
        _fake_response('{"primary_grievance":"x","procedural_stage":"y","issues":[' + many + ']}')
    ]
    result = rj.decompose_situation(MSG)
    check(result is not None and len(result["issues"]) == rj.MAX_ISSUES,
          f"issue list is capped at MAX_ISSUES ({rj.MAX_ISSUES})")

# Fenced JSON is tolerated.
with patch("related_judgments.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response("```json\n" + GOOD_JSON + "\n```")]
    result = rj.decompose_situation(MSG)
    check(result is not None and len(result["issues"]) == 3, "a ```json fenced response still parses")

# Unparseable response -> None (honest give-up).
with patch("related_judgments.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response("I couldn't work that out, sorry.")]
    check(rj.decompose_situation(MSG) is None, "an unparseable model response -> None")

# No issue survives -> None.
with patch("related_judgments.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response(
        '{"primary_grievance":"x","procedural_stage":"y","issues":['
        '{"issue":"a","hook_phrase":"words the user never wrote at all","section_hooks":[]}]}'
    )]
    check(rj.decompose_situation(MSG) is None, "if every issue's hook fails verification -> None")

# Model call itself raises -> None.
with patch("related_judgments.client") as mock_client:
    mock_client.messages.create.side_effect = RuntimeError("network down")
    check(rj.decompose_situation(MSG) is None, "a model-call exception -> None, not a crash")

# client is None -> None, no call attempted.
with patch("related_judgments.client", None):
    check(rj.decompose_situation(MSG) is None, "client unavailable -> None")

# Empty / whitespace message -> None.
with patch("related_judgments.client") as mock_client:
    mock_client.messages.create.side_effect = [_fake_response(GOOD_JSON)]
    check(rj.decompose_situation("   ") is None, "empty message -> None (no model call)")
    check(mock_client.messages.create.call_count == 0, "no model call made for an empty message")


# ---------------------------------------------------------------------------
# ik_query_builder.build_issue_query / build_issue_queries (no network)
# ---------------------------------------------------------------------------
from ik_query_builder import build_issue_query, build_issue_queries

_anchor = {
    "issue": "grounds of arrest not communicated",
    "hook_phrase": "They never told us why",
    "new_sections": ["BNSS 47"],
    "old_sections": ["CrPC 50"],
    "doctrine_hooks": ["Article 22(1)"],
}
q = build_issue_query(_anchor, fromdate="01-01-2015")
check(q.startswith('"never told us why"'),
      "the phrase query is the trimmed verbatim phrase ALONE (leading stopword 'They' dropped)")
check("50" not in q and "47" not in q and "Article" not in q,
      "the phrase query carries NO section numbers or doctrine names -- kept clean")
check("doctypes:highcourts" in q, "court filter appended (High Courts only by default)")
check("fromdate:01-01-2015" in q, "fromdate appended when given")

kw = build_issue_query(_anchor, include_phrase=False)
check('"never told us why"' not in kw, "the keyword query drops the verbatim phrase")
check(any(w in kw for w in ("grounds", "arrest", "communicated")),
      "the keyword query carries content words from the issue description")
_nums = re.findall(r"(?<!\d)\d{1,3}[A-Z]?(?!\d)", kw.split("doctypes:")[0])
check(len(_nums) <= 1, "the keyword query carries at most ONE section number")

qs = build_issue_queries(_anchor)
check(len(qs) == 2 and '"never told us why"' in qs[0] and '"never told us why"' not in qs[1],
      "a phrase query then a keyword query, in that order")

empty = {"issue": "arrest procedure generally", "hook_phrase": "", "new_sections": [],
         "old_sections": [], "doctrine_hooks": []}
eq = build_issue_query(empty)
check("arrest" in eq and "procedure" in eq and eq.strip() != "doctypes:highcourts",
      "a phrase-less anchor still produces a non-empty keyword query from the issue text")

# CONFIRMED REAL GAP FIX (2026-09-04): a compound accusation ("cheating and
# breach of trust") decomposes into ONE issue tagged with section_hooks for
# BOTH offences -- old_sections empty because to_old() can't map an
# already-old IPC hook further, so new_sections carries the raw hooks
# directly. Previously build_issue_query only ever used the first one
# (420, cheating), so no IK query ever ran for 406 (breach of trust).
_compound_anchor = {
    "issue": "arrest on allegation of cheating and breach of trust",
    "hook_phrase": "arrested for cheating and breach of trust",
    "new_sections": ["IPC 420", "IPC 406", "IPC 415"],
    "old_sections": [],
    "doctrine_hooks": [],
}
compound_qs = build_issue_queries(_compound_anchor)
broad_qs = [q for q in compound_qs if '"arrested for cheating' not in q]
check(any("420" in q for q in broad_qs) and any("406" in q for q in broad_qs),
      "IK search runs at least once anchored to EACH distinct named section "
      "(420 cheating AND 406 breach of trust), not just the first")

# old_sections and new_sections for the SAME hook (e.g. "BNSS 47" ->
# concordance -> "CrPC 50") must not be double-counted as two offences.
_same_provision_anchor = {
    "issue": "grounds of arrest not communicated",
    "hook_phrase": "",
    "new_sections": ["BNSS 47"],
    "old_sections": ["CrPC 50"],
    "doctrine_hooks": [],
}
same_prov_qs = build_issue_queries(_same_provision_anchor)
check(sum(1 for q in same_prov_qs if "50" in q.split("doctypes:")[0]) == 1,
      "old/new numbering for one real provision produces exactly one section-anchored query, not two")


# ---------------------------------------------------------------------------
# semantic_retrieval.rerank -- Voyage client mocked (no API cost)
# ---------------------------------------------------------------------------
import semantic_retrieval as sr


class _RerankResult:
    def __init__(self, index, score):
        self.index = index
        self.relevance_score = score


class _RerankResponse:
    def __init__(self, pairs):
        self.results = [_RerankResult(i, s) for i, s in pairs]


check(sr.rerank("q", []) == [], "rerank with no documents -> [] (not None)")
check(sr.rerank("", ["a", "b"]) == [], "rerank with empty query -> []")

with patch("semantic_retrieval._voyage_available", True), \
     patch("semantic_retrieval.voyageai") as mock_voyage:
    mock_voyage.Client.return_value.rerank.return_value = _RerankResponse([(2, 0.9), (0, 0.4)])
    out = sr.rerank("which case is about X", ["doc-a", "doc-b", "doc-c"], top_k=2)
    check([o["index"] for o in out] == [2, 0], "results returned best-first by score")
    check(out[0]["document"] == "doc-c", "index maps back to the right document string")
    check(out[0]["score"] == 0.9, "relevance_score carried through")

with patch("semantic_retrieval._voyage_available", True), \
     patch("semantic_retrieval.voyageai") as mock_voyage:
    mock_voyage.Client.return_value.rerank.side_effect = RuntimeError("voyage down")
    check(sr.rerank("q", ["a", "b"]) is None, "a reranker exception -> None (honest 'could not rank')")

with patch("semantic_retrieval._voyage_available", False):
    check(sr.rerank("q", ["a", "b"]) is None, "reranker unavailable -> None")


# ---------------------------------------------------------------------------
# Phase 1b: search_candidates / rank_candidates / get_related_judgments
# -- every external call injected, nothing hits the network.
# ---------------------------------------------------------------------------

def _ik_doc(tid, title, court="Delhi High Court", pubdate="2025-06-01", headline="a snippet"):
    return {"tid": tid, "title": title, "docsource": court,
            "publishdate": pubdate, "headline": headline}


def _corpus_rec(name, para, text, score=0.5):
    return {"type": "judgment", "chunk_id": f"judgment:{name}:{para}", "case_name": name,
            "paragraph_number": para, "text": text, "score": score,
            "source_url": f"https://indiankanoon.org/doc/{para}/"}


ANCHORS = [
    {"issue": "arrest of a person not named in the FIR", "hook_phrase": "name was not in the FIR",
     "new_sections": ["BNSS 35"], "old_sections": ["CrPC 41"], "doctrine_hooks": []},
    {"issue": "chargesheet not filed within the time limit", "hook_phrase": "no chargesheet",
     "new_sections": ["BNSS 187"], "old_sections": ["CrPC 167"], "doctrine_hooks": []},
]

# tid 500 comes back for a query mentioning "41" / the FIR phrase (issue 0),
# 501 too; a query mentioning "167" (issue 1) returns just 500. 502 is
# really a corpus case (Arnesh Kumar).
_IK_ISSUE0 = {"docs": [_ik_doc(500, "Ramesh v State"), _ik_doc(501, "Suresh v State"),
                       _ik_doc(502, "Arnesh Kumar vs State Of Bihar on 2 July, 2014",
                               court="Supreme Court of India")]}
_IK_ISSUE1 = {"docs": [_ik_doc(500, "Ramesh v State")]}


def _fake_ik_search_many(queries):
    """indiankanoon_client.search_many stand-in: {query: result}."""
    out = {}
    for q in queries:
        if "41" in q.split() or "not named" in q or "FIR" in q or "name was not in the FIR" in q:
            out[q] = _IK_ISSUE0
        else:
            out[q] = _IK_ISSUE1
    return out


def _fake_local_search(query):
    if "not named" in query or "FIR" in query:
        return [_corpus_rec("D.K. Basu v State of West Bengal", "35",
                            "The arrest safeguards apply regardless of whether the arrestee is named in the FIR.")]
    return []


def _fake_rerank(q, docs, top_k=None):
    # score by simple keyword overlap so the test is deterministic
    ql = set(re.findall(r"[a-z]+", q.lower()))
    out = []
    for i, d in enumerate(docs):
        dl = set(re.findall(r"[a-z]+", d.lower()))
        out.append({"index": i, "score": len(ql & dl) / (len(ql) + 1), "document": d})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


CORPUS_NAMES = ["Arnesh Kumar v State of Bihar", "D.K. Basu v State of West Bengal"]

pool = rj.search_candidates(ANCHORS, ik_search_many_fn=_fake_ik_search_many, local_search_fn=_fake_local_search)
by_tid = {c["raw"]["tid"]: c for c in pool if c["source"] == "indiankanoon"}
check(set(by_tid) == {500, 501, 502}, "IK hits pooled and deduped by tid across issues")
check(by_tid[500]["matched_issues"] == [0, 1], "a tid returned for two issues has both indices unioned")
check(by_tid[501]["matched_issues"] == [0], "a single-issue tid keeps just its index")
check(any(c["source"] == "corpus" for c in pool), "local corpus hit is pooled alongside IK hits")

ranked = rj.rank_candidates(pool, "police arrested him though his name was not in the FIR and no chargesheet",
                            rerank_fn=_fake_rerank, corpus_case_names=CORPUS_NAMES,
                            today=datetime.date(2026, 9, 3))
ranked_tids = [r["triage"]["tid"] for r in ranked if r["source"] == "indiankanoon"]
check(502 not in ranked_tids, "the IK hit that is really a corpus case (Arnesh Kumar) is dropped")
check(all(r["rerank_used"] for r in ranked), "rerank_used flag is True when a reranker was supplied")
check(ranked == sorted(ranked, key=lambda r: r["score"], reverse=True), "ranked list is sorted best-first")
c500 = next(r for r in ranked if r["source"] == "indiankanoon" and r["triage"]["tid"] == 500)
c501 = next(r for r in ranked if r["source"] == "indiankanoon" and r["triage"]["tid"] == 501)
check(c500["score"] > c501["score"], "the two-issue judgment outranks the one-issue judgment (cross-issue boost)")

degraded = rj.rank_candidates(pool, "q", rerank_fn=lambda *a, **k: None,
                              corpus_case_names=CORPUS_NAMES,
                              today=datetime.date(2026, 9, 3))
check(degraded and all(not r["rerank_used"] for r in degraded),
      "reranker returning None -> ranking still produces a list, marked not rerank_used")

# A corpus case the grounded answer NAMES is kept (not dropped) and flagged
ranked_named = rj.rank_candidates(
    pool, "arrest without warrant, no chargesheet",
    rerank_fn=_fake_rerank, corpus_case_names=CORPUS_NAMES,
    grounded_answer_text="The Supreme Court in D.K. Basu v State of West Bengal laid down safeguards.",
    today=datetime.date(2026, 9, 3),
)
dkb = [r for r in ranked_named if r["source"] == "corpus" and "Basu" in (r["triage"]["title"] or "")]
check(len(dkb) == 1, "a corpus case named in the grounded answer is KEPT, not dropped")
check(dkb[0]["triage"].get("cited_in_answer") is True,
      "and it is flagged cited_in_answer so the panel can say 'the judgment cited above'")


# ---- get_related_judgments: full flow, everything injected ----
def _fake_decompose(msg):
    return {"primary_grievance": "held without grounds", "procedural_stage": "pre-chargesheet",
            "issues": [
                {"issue": "arrest of a person not named in the FIR", "hook_phrase": "name was not in the FIR", "section_hooks": ["BNSS 35"]},
                {"issue": "chargesheet not filed within the time limit", "hook_phrase": "no chargesheet", "section_hooks": ["BNSS 187"]},
            ]}

res = rj.get_related_judgments(
    "arrested though his name was not in the FIR, and still no chargesheet after 2 months",
    grounded_answer_text="Section 35 of the BNSS governs arrest; Section 187 governs default bail.",
    write_bundle=False,
    # CONFIRMED REAL BUG (found by an independent cloud-session review, 2026-09-26): this call
    # used to omit pin/fetch_many_fn/clean_fn/gloss_fn entirely, so with pin=True (the default)
    # it fell through to REAL fetch_and_pin + REAL _default_gloss_fn -- a live, billable
    # Anthropic call (and a live IndianKanoon fetch, had a real INDIANKANOON_API_KEY been
    # present) on every "free" run. This call only asserts on status/candidates/anchors below,
    # none of which need pinning -- pin=False is the same escape hatch already used at the two
    # sibling calls further down this file, and is exactly what related_judgments.py's own
    # docstring says it's for ("stops after ranking, no IK-doc credits").
    pin=False,
    decompose_fn=_fake_decompose, ik_search_many_fn=_fake_ik_search_many,
    local_search_fn=_fake_local_search, rerank_fn=_fake_rerank,
    today=datetime.date(2026, 9, 3),
)
check(res["status"] == "ok", "get_related_judgments returns status 'ok' when candidates survive")
check(len(res["candidates"]) >= 1, "at least one candidate returned")
check(len(res["anchors"]) == 2, "one anchor per issue, no synthetic mega-anchor from the answer")
check(502 not in [c["triage"]["tid"] for c in res["candidates"] if c["source"] == "indiankanoon"],
      "corpus-case IK hit stays dropped through the full flow")

# answer-section parsing: act-qualified only, resolved via concordance
check(rj._answer_act_sections("Section 35 of the BNSS governs arrest; Section 187 BNSS covers default bail; Section 99 alone is ambiguous.")
      == [("BNSS", "35"), ("BNSS", "187")],
      "only ACT-qualified section references are pulled from the answer ('Section 99 alone' ignored)")
_old = rj.answer_old_sections("Section 35 of the BNSS governs arrest without warrant.")
check("CrPC 41" in _old and "IPC 97" not in _old,
      "'Section 35 of the BNSS' resolves to CrPC 41 only -- never IPC 97 (BNS 35 private defence)")

with patch.dict("os.environ", {"KYR_DISABLE_LIVE_JUDGMENTS": "1"}):
    r = rj.get_related_judgments("anything", decompose_fn=_fake_decompose)
    check(r["status"] == "disabled" and r["candidates"] == [], "kill switch -> status 'disabled', no work done")

r = rj.get_related_judgments("x", write_bundle=False, decompose_fn=lambda m: None)
check(r["status"] == "no_decomposition", "decomposition failure -> status 'no_decomposition', never a raise")

def _boom_ik_many(queries):
    raise RuntimeError("IK down")

r = rj.get_related_judgments(
    "arrested, name not in FIR", write_bundle=False, pin=False, decompose_fn=_fake_decompose,
    ik_search_many_fn=_boom_ik_many, local_search_fn=lambda q: [], rerank_fn=_fake_rerank,
    today=datetime.date(2026, 9, 3),
)
check(r["status"] in ("ok", "no_candidates"), "an IK exception is swallowed -- get_related_judgments still returns a dict")


# ---------------------------------------------------------------------------
# Phase 2: fetch_and_pin -- fetch / clean / rerank all injected.
# ---------------------------------------------------------------------------
check(rj._para_number("14. The Court held that...") == 14, "leading 'N.' paragraph number extracted")
check(rj._para_number("42) In this case") == 42, "leading 'N)' paragraph number extracted")
check(rj._para_number("No number here") is None, "no leading number -> None")

_HTML_500 = "<h2 class='doc_title'>Ramesh v State</h2>" + "".join(
    f"<p data-structure='{s}' id='p_{i}'>{i}. {txt}</p>"
    for i, (s, txt) in enumerate([
        ("Facts", "The petitioner was arrested at his home."),
        ("Analysis", "The petitioner was not named in the FIR and the arrest was challenged."),
        ("Conclusion", "Not being named in the FIR does not by itself bar an arrest, but the Section 41A safeguards still apply."),
    ], start=1)
)


def _fake_fetch_many(tids):
    # 500 -> real HTML; anything else -> empty doc -> "fetch fails" downstream
    return {str(t): ({"doc": _HTML_500} if str(t) == "500" else {"doc": ""}) for t in tids}


def _fake_clean(html):
    # crude parse of the fake HTML -> the ik_text_cleaner.clean_document shape
    import re as _re
    paras = []
    for m in _re.finditer(r"<p data-structure='([^']+)'[^>]*>(.*?)</p>", html):
        paras.append({"tag": "p", "structure": m.group(1), "text": m.group(2),
                      "has_citation": False, "citation_sentiments": []})
    return {"title": "Ramesh v State", "paragraphs": paras, "paragraph_count": len(paras)}


# Build a ranked list by hand: two IK candidates (500 fetchable, 501 not),
# one corpus candidate.
_r500 = {"source": "indiankanoon", "matched_issues": [0, 1], "queries": ["q"],
         "raw": _ik_doc(500, "Ramesh v State"), "score": 0.6, "rerank_score": 0.6, "rerank_used": True,
         "triage": {"tid": 500, "title": "Ramesh v State", "url": "u", "court_tier": "high_court",
                    "adverse_markers": [], "is_corpus_case": False}}
_r501 = {"source": "indiankanoon", "matched_issues": [0], "queries": ["q"],
         "raw": _ik_doc(501, "Suresh v State"), "score": 0.55, "rerank_score": 0.55, "rerank_used": True,
         "triage": {"tid": 501, "title": "Suresh v State", "url": "u", "court_tier": "high_court",
                    "adverse_markers": [], "is_corpus_case": False}}
_rc = {"source": "corpus", "matched_issues": [0], "queries": [], "record": {},
       "score": 0.5, "rerank_score": 0.5, "rerank_used": True,
       "triage": {"tid": None, "title": "D.K. Basu v State of West Bengal", "url": "u",
                  "court_tier": "supreme_court", "adverse_markers": [], "is_corpus_case": True}}

_r501_score_before = _r501["score"]
with patch("related_judgments._corpus_para_pool", lambda name: [
    {"text": "10. The arrestee may meet his lawyer during interrogation.", "structure": None, "para_number": 10},
]):
    pinned = rj.fetch_and_pin([_r500, _r501, _rc], "arrested though not named in the FIR, no chargesheet",
                              fetch_many_fn=_fake_fetch_many, clean_fn=_fake_clean, rerank_fn=_fake_rerank)

by_tid = {c["triage"]["tid"]: c for c in pinned}
check(by_tid[500].get("pinned"), "the fetchable IK candidate (500) has pinned paragraphs")
check(by_tid[500]["content_score"] is not None, "fetched candidate has a content_score")
check(any(p["para_number"] in (1, 2, 3) for p in by_tid[500]["pinned"]),
      "a pinned paragraph carries the judgment's own paragraph number")
check(by_tid[501].get("fetch_failed") is True, "the IK candidate whose fetch returned empty HTML is flagged fetch_failed")
check(by_tid[501]["pinned"] == [] and by_tid[501]["score"] < _r501_score_before,
      "a fetch-failed candidate is demoted and has no pinned paragraphs, but is still present")
corpus_c = next(c for c in pinned if c["source"] == "corpus")
check(corpus_c.get("pinned") and corpus_c["pinned"][0]["para_number"] == 10,
      "the corpus candidate is paragraph-pinned from its local chunk pool (no fetch)")

# structure bonus: the 'Conclusion' paragraph should be pinnable above a
# 'Facts' paragraph of similar raw relevance
concl = [p for p in by_tid[500]["pinned"] if p["structure"] == "Conclusion"]
check(concl, "the Conclusion-tagged paragraph is among those pinned (structure bonus applied)")

# ---------------------------------------------------------------------------
# Section-alignment correction (2026-09-04): a deterministic guard against
# the reranker scoring a lexically-similar but legally UNRELATED judgment
# higher than a genuinely on-point one. CONFIRMED REAL FAILURE: a Gujarat
# HC civil-service ACR dispute (0.885) outscored a real cheating/forgery
# judgment (0.56) for a cheating/breach-of-trust question -- the ACR case
# shared surface vocabulary ("shown", "documents", "delay") with the
# user's message but never engaged with the actual offence.
# ---------------------------------------------------------------------------
check(rj._anchor_bare_sections({"old_sections": ["IPC 420", "IPC 406"], "new_sections": ["BNS 318(4)"]})
      == {"420", "406", "318"},
      "_anchor_bare_sections unions bare numbers from both old and new numbering")
check(rj._mentions_section("The accused was charged under Section 420 IPC for cheating.", "420"),
      "'Section 420' is recognized as a real citation")
check(rj._mentions_section("He was booked under S.406 for breach of trust.", "406"),
      "'S.406' (abbreviated) is recognized as a real citation")
check(not rj._mentions_section("The hearing was listed on the 420th day of the term.", "420"),
      "a bare coincidental number with no section-citation marker is NOT treated as a citation")

_offtopic = {"source": "indiankanoon", "matched_issues": [0], "queries": ["q"],
             "raw": _ik_doc(600, "Unrelated Service Matter"), "score": 0.9, "rerank_score": 0.9,
             "rerank_used": True, "anchor_sections": ["420", "406"],
             "triage": {"tid": 600, "title": "Unrelated Service Matter", "url": "u", "court_tier": "high_court",
                        "adverse_markers": [], "is_corpus_case": False}}
_ontopic = {"source": "indiankanoon", "matched_issues": [0], "queries": ["q"],
            "raw": _ik_doc(601, "Real Cheating Case"), "score": 0.6, "rerank_score": 0.6,
            "rerank_used": True, "anchor_sections": ["420", "406"],
            "triage": {"tid": 601, "title": "Real Cheating Case", "url": "u", "court_tier": "high_court",
                       "adverse_markers": [], "is_corpus_case": False}}

_HTML_OFFTOPIC = "<h2 class='doc_title'>Unrelated Service Matter</h2>" + "".join(
    f"<p data-structure='{s}' id='p_{i}'>{i}. {txt}</p>"
    for i, (s, txt) in enumerate([
        ("Facts", "The petitioner's loan documents and signatures were part of the partnership dispute records."),
        ("Analysis", "The delay in the process cast doubt on the partnership and its forged accounting entries."),
    ], start=1)
)
_HTML_ONTOPIC = "<h2 class='doc_title'>Real Cheating Case</h2>" + "".join(
    f"<p data-structure='{s}' id='p_{i}'>{i}. {txt}</p>"
    for i, (s, txt) in enumerate([
        ("Facts", "The accused was charged under Section 420 IPC for cheating his business partner."),
        ("Analysis", "The Court examined whether Section 406 IPC criminal breach of trust was made out."),
    ], start=1)
)


def _fake_fetch_section_test(tids):
    html_by_tid = {"600": _HTML_OFFTOPIC, "601": _HTML_ONTOPIC}
    return {str(t): {"doc": html_by_tid.get(str(t), "")} for t in tids}


_section_test_msg = ("arrested for cheating and breach of trust over loan documents "
                      "and forged signatures in a partnership dispute")
pinned_section_test = rj.fetch_and_pin(
    [_offtopic, _ontopic], _section_test_msg,
    fetch_many_fn=_fake_fetch_section_test, clean_fn=_fake_clean, rerank_fn=_fake_rerank,
)
by_tid_sec = {c["triage"]["tid"]: c for c in pinned_section_test}
check(by_tid_sec[600]["section_alignment"] is False,
      "a candidate whose full fetched text mentions NONE of the issue's named sections is flagged misaligned")
check(by_tid_sec[601]["section_alignment"] is True,
      "a candidate whose full fetched text DOES cite one of the issue's named sections is flagged aligned")
check(by_tid_sec[601]["score"] > by_tid_sec[600]["score"],
      "REAL-SHAPED GAP FIX: the section-citing judgment now outranks the lexically-similar but "
      "legally unrelated one, reversing the confirmed real reranker mis-score")

# ---------------------------------------------------------------------------
# Document-finality correction (2026-09-04): a deterministic guard against
# a bail/interlocutory disposal being ranked, pinned, and (via the app's
# unverified-review confirm button) approved as if it were a judgment.
# CONFIRMED REAL FAILURE: "Attapuram Bharath Reddy vs The State Of
# Telangana" -- a bail application whose only content is a PetArg
# (petitioner's argument) praying to be "enlarged on bail" -- was ranked,
# fetched, and user-confirmed into related_judgments_approved.json.
# ---------------------------------------------------------------------------
_bail_order = {"source": "indiankanoon", "matched_issues": [0], "queries": ["q"],
               "raw": _ik_doc(700, "Attapuram Bharath Reddy vs State"), "score": 0.8, "rerank_score": 0.8,
               "rerank_used": True, "anchor_sections": [],
               "triage": {"tid": 700, "title": "Attapuram Bharath Reddy vs State", "url": "u",
                          "court_tier": "high_court", "adverse_markers": [], "is_corpus_case": False}}
_real_judgment = {"source": "indiankanoon", "matched_issues": [0], "queries": ["q"],
                   "raw": _ik_doc(701, "Genuine Arrest-Guidelines Case"), "score": 0.6, "rerank_score": 0.6,
                   "rerank_used": True, "anchor_sections": [],
                   "triage": {"tid": 701, "title": "Genuine Arrest-Guidelines Case", "url": "u",
                              "court_tier": "high_court", "adverse_markers": [], "is_corpus_case": False}}

# Real, verbatim shape of the confirmed Attapuram document: ONE paragraph,
# tagged PetArg by IK's own classifier, praying for bail -- no
# Analysis/Precedent/CDiscource/Issue/Conclusion tag anywhere.
_HTML_BAIL_ORDER = "<h2 class='doc_title'>Attapuram Bharath Reddy vs State</h2>" + (
    "<p data-structure='PetArg' id='p_1'>4. The learned counsel for the petitioner contends that the "
    "petitioner is innocent and has been falsely implicated. Hence, it is prayed that the petitioner "
    "be enlarged on bail.</p>"
)
# Arnesh-Kumar-SHAPED: genuinely discusses bail throughout (that IS its
# subject) but carries real Analysis + Conclusion structure -- must NOT be
# flagged, proving the conjunction protects real precedent.
_HTML_REAL_JUDGMENT = "<h2 class='doc_title'>Genuine Arrest-Guidelines Case</h2>" + "".join(
    f"<p data-structure='{s}' id='p_{i}'>{i}. {txt}</p>"
    for i, (s, txt) in enumerate([
        ("PetArg", "The petitioner submits the arrest and remand were made without due application of mind."),
        ("Analysis", "Section 41 CrPC and the safeguards against automatic arrest are examined in detail, "
                      "with reference to anticipatory bail and regular bail as meaningful remedies."),
        ("Conclusion", "We accordingly lay down the following guidelines to be followed in all arrests."),
    ], start=1)
)


def _fake_fetch_finality_test(tids):
    html_by_tid = {"700": _HTML_BAIL_ORDER, "701": _HTML_REAL_JUDGMENT}
    return {str(t): {"doc": html_by_tid.get(str(t), "")} for t in tids}


_finality_test_msg = "arrested at night without being told the grounds, family not informed"
pinned_finality_test = rj.fetch_and_pin(
    [_bail_order, _real_judgment], _finality_test_msg,
    fetch_many_fn=_fake_fetch_finality_test, clean_fn=_fake_clean, rerank_fn=_fake_rerank,
)
by_tid_fin = {c["triage"]["tid"]: c for c in pinned_finality_test}

check(by_tid_fin[700]["procedural_disposal"] is True,
      "REPRODUCES THE CONFIRMED CASE: the PetArg-only bail-order document is flagged procedural_disposal")
check(bool(by_tid_fin[700]["procedural_disposal_markers"]),
      "the flagged candidate carries the disposal marker(s) that triggered it")
check(by_tid_fin[701]["procedural_disposal"] is False,
      "REAL-SHAPED FIX: the Arnesh-Kumar-shaped judgment (bail discussed, but real Analysis/Conclusion "
      "structure present) is NOT flagged -- the conjunction protects genuine precedent")

check(by_tid_fin[700]["content_score"] < by_tid_fin[701]["content_score"],
      "the flagged bail order's content_score is demoted below the genuine judgment's, despite starting "
      "with a HIGHER raw rerank/headline score (0.8 vs 0.6)")
check(by_tid_fin[700]["score"] < by_tid_fin[701]["score"],
      "the demotion carries through to the final ranking score -- a bail order cannot outrank a real "
      "judgment on lexical similarity alone")

check(rj._display_worthy(by_tid_fin[700]) is False,
      "a procedural_disposal=True candidate is HARD-EXCLUDED from the fully-trusted for_display panel, "
      "regardless of its (already-demoted) content_score")

corpus_cand_for_finality = {"source": "corpus", "matched_issues": [0], "queries": [],
                            "triage": {"title": "Some Corpus Case", "cited_in_answer": False}}
check(rj._display_worthy({**corpus_cand_for_finality, "content_score": 0.9,
                          "procedural_disposal": None}) is True,
      "a corpus candidate (procedural_disposal always None, never checked) is unaffected by this gate")

# get_related_judgments with pin=True, everything injected
# CONFIRMED REAL BUG (found by an independent cloud-session review, 2026-09-25): this call site
# was the one exception among ~7 similar calls in this file that omitted gloss_fn -- pin=True
# means candidates genuinely carry pinned paragraphs, so gloss_and_verify's gloss_fn=None default
# fell through to a REAL Sonnet call. Silent because gloss_and_verify swallows gloss exceptions by
# design (tested elsewhere in this file) -- it never failed loudly, it just quietly cost money.
with patch("related_judgments._corpus_para_pool", lambda name: []):
    res2 = rj.get_related_judgments(
        "arrested though his name was not in the FIR, and still no chargesheet",
        grounded_answer_text="Section 35 of the BNSS governs arrest. Section 187 of the BNSS governs default bail.",
        write_bundle=False, pin=True,
        decompose_fn=_fake_decompose, ik_search_many_fn=_fake_ik_search_many,
        local_search_fn=_fake_local_search, rerank_fn=_fake_rerank,
        fetch_many_fn=_fake_fetch_many, clean_fn=_fake_clean, today=datetime.date(2026, 9, 3),
        gloss_fn=lambda situation, paras: "This case dealt with a similar arrest/default-bail situation.",
    )
check(res2["status"] == "ok", "pin=True full flow returns ok")
check(any("pinned" in c for c in res2["candidates"]), "candidates carry a 'pinned' field after pin=True")

res3 = rj.get_related_judgments(
    "arrested though his name was not in the FIR", write_bundle=False, pin=False,
    decompose_fn=_fake_decompose, ik_search_many_fn=_fake_ik_search_many,
    local_search_fn=_fake_local_search, rerank_fn=_fake_rerank, today=datetime.date(2026, 9, 3),
)
check(all(not c.get("pinned") for c in res3["candidates"]),
      "pin=False -> no paragraph fetching, no pinned paragraphs")


# ---------------------------------------------------------------------------
# Phase 3: the settled-doctrine whitelist gate (via get_related_judgments)
# Phase 4: the bounded gloss + its verification
# ---------------------------------------------------------------------------

# _verify_gloss -- the output gate
_PARA = "12. The right to be produced before a Magistrate within 24 hours under Section 57 is mandatory."
check(rj._verify_gloss("The court considered a delay in producing an arrested person and observed that the 24-hour rule is mandatory.", _PARA)
      is not None, "a clean descriptive one-sentence gloss passes")
check(rj._verify_gloss("Your arrest was illegal because you were not produced in time.", _PARA) is None,
      "a gloss with a verdict about the person ('your arrest was illegal') is rejected")
check(rj._verify_gloss("This is binding precedent that must be followed in your case.", _PARA) is None,
      "a gloss claiming 'binding' / 'must be followed' / 'your case' is rejected")
check(rj._verify_gloss("The court applied Section 167 to extend custody.", _PARA) is None,
      "a gloss citing Section 167, which is NOT in the paragraph, is rejected")
check(rj._verify_gloss("The court applied Section 57 to the facts.", _PARA) is not None,
      "a gloss citing Section 57, which IS in the paragraph, passes")
check(rj._verify_gloss("", _PARA) is None, "an empty gloss is rejected")


# gloss_and_verify -- gloss_fn injected
_cands = [
    {"source": "indiankanoon", "matched_issues": [0], "triage": {"tid": 1, "title": "X v State"},
     "pinned": [{"para_number": 12, "structure": "Section", "text": _PARA, "score": 0.6}]},
    {"source": "indiankanoon", "matched_issues": [0], "triage": {"tid": 2, "title": "Y v State"},
     "pinned": []},  # nothing pinned -> no gloss attempted
]
rj.gloss_and_verify(_cands, "not produced before a magistrate in time",
                    gloss_fn=lambda situation, paras: "The judgment dealt with a delayed production and the court observed the rule is mandatory.")
check(_cands[0]["gloss"] and "mandatory" in _cands[0]["gloss"], "a passing gloss is attached to the pinned candidate")
check(_cands[1]["gloss"] is None, "a candidate with no pinned paragraph gets gloss=None (no call)")

rj.gloss_and_verify(_cands, "situation", gloss_fn=lambda s, p: "This applies to you and your arrest was illegal.")
check(_cands[0]["gloss"] is None, "a gloss that fails verification is dropped (set to None), not shown")

rj.gloss_and_verify(_cands, "situation", gloss_fn=lambda s, p: (_ for _ in ()).throw(RuntimeError("model down")))
check(True, "a gloss_fn exception is swallowed -- gloss_and_verify does not raise")


# get_related_judgments: whitelist gate drives show_user + whether gloss runs
def _decompose_whitelisted(msg):
    return {"primary_grievance": "held without grounds", "procedural_stage": "pre-chargesheet",
            "issues": [
                {"issue": "arrest of a person not named in the FIR", "hook_phrase": "name was not in the FIR", "section_hooks": ["BNSS 35"]},
                {"issue": "chargesheet not filed within the time limit", "hook_phrase": "no chargesheet", "section_hooks": ["BNSS 187"]},
            ]}

def _decompose_not_whitelisted(msg):
    return {"primary_grievance": "account frozen", "procedural_stage": "unknown",
            "issues": [
                {"issue": "police froze the bank account", "hook_phrase": "bank account was frozen", "section_hooks": ["BNSS 107"]},
            ]}

_gloss_calls = []
def _tracking_gloss(situation, paras):
    _gloss_calls.append(1)
    return "The judgment dealt with a similar delay and the court made observations about it."

with patch("related_judgments._corpus_para_pool", lambda name: [
    {"text": "9. Article 22 of the Constitution reads thus: arrested shall be detained.", "structure": None, "para_number": 9},
]):
    wl_res = rj.get_related_judgments(
        "arrested though his name was not in the FIR and still no chargesheet after two months",
        write_bundle=False, pin=True, decompose_fn=_decompose_whitelisted,
        ik_search_many_fn=_fake_ik_search_many, local_search_fn=_fake_local_search,
        rerank_fn=_fake_rerank, fetch_many_fn=_fake_fetch_many, clean_fn=_fake_clean,
        gloss_fn=_tracking_gloss, today=datetime.date(2026, 9, 3),
    )
check(wl_res["show_user"] is True, "all-whitelisted issues -> show_user True")
check(wl_res["whitelist"]["covered"] is True, "whitelist report says covered")
check(len(_gloss_calls) >= 1, "the gloss runs on the whitelisted path")
check("for_display" in wl_res and len(wl_res["for_display"]) <= 5,
      "for_display is a capped subset of the ranked candidates")
check(all(rj._display_worthy(c) for c in wl_res["for_display"]),
      "every for_display candidate passes _display_worthy")

# _display_worthy: off-point gloss and low content are excluded
check(rj._display_worthy({"source": "corpus", "gloss": None, "content_score": 0.55,
                          "triage": {}}) is True,
      "a corpus candidate with a real content score is display-worthy")
check(rj._display_worthy({"source": "corpus", "gloss": None, "content_score": 0.30,
                          "triage": {}}) is False,
      "a corpus candidate whose only match is a weak stray paragraph is NOT shown")
check(rj._display_worthy({"source": "corpus", "gloss": None, "content_score": 0.30,
                          "triage": {"cited_in_answer": True}}) is True,
      "...unless the grounded answer named it -- then it always shows")
check(rj._display_worthy({"source": "indiankanoon", "gloss": "This one may not be closely on point.",
                          "content_score": 0.9}) is False,
      "an off-point gloss excludes a candidate from the panel even at a high score")
check(rj._display_worthy({"source": "indiankanoon", "gloss": "The court dealt with a similar delay.",
                          "content_score": 0.2}) is False,
      "a low content_score excludes an IK candidate from the panel")
check(rj._display_worthy({"source": "indiankanoon", "gloss": "The court dealt with a similar delay.",
                          "content_score": 0.55}) is True,
      "a genuine on-point IK candidate is display-worthy")

_gloss_calls.clear()
nb_res = rj.get_related_judgments(
    "the police froze my bank account without telling me", write_bundle=False, pin=False,
    decompose_fn=_decompose_not_whitelisted, ik_search_many_fn=_fake_ik_search_many,
    local_search_fn=lambda q: [], rerank_fn=_fake_rerank, gloss_fn=_tracking_gloss,
    today=datetime.date(2026, 9, 3),
)
check(nb_res["show_user"] is False, "a non-whitelisted issue -> show_user False (fully-trusted panel hidden)")
check(nb_res["whitelist"]["uncovered"] == ["police froze the bank account"],
      "the whitelist report names the issue that hid the panel")
check(len(_gloss_calls) == 0,
      "no gloss call here -- but because pin=False leaves every candidate without a content_score "
      "(nothing clears the glossable floor), NOT because show_user gates gloss anymore (see below)")
check(nb_res["for_display"] == [], "for_display stays empty when not whitelisted")
check(nb_res["status"] in ("ok", "no_candidates"),
      "the run still completes and a bundle would still be written for hand-curation")

# --- unverified-review path (2026-09-04, unfiltered per explicit user
# correction): a non-whitelisted (substantive offence) question must
# still surface EVERY ranked candidate for the user to judge themselves
# -- not just ones this tool's own scoring/gloss/alignment machinery
# considers "good enough". Two earlier, more cautious versions of this
# path (a stricter score floor, then a defect-only filter) were both
# built and both explicitly rejected by the user as still hiding things
# ("DO NOT HIDE... irrespective of your confidence"). This is the FINAL
# behavior: unverified_for_display == the full ranked list, unfiltered,
# whenever show_user is False.
def _decompose_theft_not_whitelisted(msg):
    # primary_grievance/issue text deliberately echo the fixture judgment's
    # own wording below -- get_related_judgments builds its paragraph-pin
    # query from THESE fields (profile + issue text), not the raw user
    # message, so the fake keyword-overlap reranker needs real overlap
    # with them specifically to produce a realistic content_score.
    return {"primary_grievance": "accused of stealing a laptop from the office",
            "procedural_stage": "unknown",
            "issues": [
                {"issue": "arrest on an allegation of stealing a laptop from the office",
                 "hook_phrase": "accused of stealing a laptop from the office",
                 "section_hooks": ["BNS 303"]},
            ]}


_HTML_THEFT_ONTOPIC = "<h2 class='doc_title'>Real Theft Case</h2>" + "".join(
    f"<p data-structure='{s}' id='p_{i}'>{i}. {txt}</p>"
    for i, (s, txt) in enumerate([
        ("Facts", "The accused was charged under Section 303 BNS for allegedly stealing a laptop from the office."),
        ("Analysis", "The Court examined whether the ingredients of theft under Section 303 were made out."),
    ], start=1)
)


def _fake_fetch_theft(tids):
    return {str(t): {"doc": _HTML_THEFT_ONTOPIC if str(t) == "702" else ""} for t in tids}


def _fake_ik_search_theft(queries):
    return {q: {"docs": [_ik_doc(702, "Real Theft Case")]} for q in queries}


_gloss_calls.clear()
theft_res = rj.get_related_judgments(
    "accused of stealing a laptop from the office and arrested without much explanation",
    write_bundle=False, pin=True,
    decompose_fn=_decompose_theft_not_whitelisted, ik_search_many_fn=_fake_ik_search_theft,
    local_search_fn=lambda q: [], rerank_fn=_fake_rerank, gloss_fn=_tracking_gloss,
    fetch_many_fn=_fake_fetch_theft, clean_fn=_fake_clean, today=datetime.date(2026, 9, 3),
)
check(theft_res["show_user"] is False, "a substantive-offence issue (theft) is not a whitelisted procedural doctrine")
check(theft_res["for_display"] == [], "the fully-trusted panel still stays empty when not whitelisted")
check(theft_res["unverified_for_display"] == theft_res["candidates"],
      "REAL-SHAPED FIX (final, per explicit user correction): unverified_for_display is the FULL "
      "ranked list, not a filtered subset -- nothing here is this tool's confidence judgment to make")
check(len(_gloss_calls) >= 1,
      "gloss still runs for a non-whitelisted question when something is genuinely glossable -- "
      "the gloss text itself is shown to the user, it just no longer GATES visibility")

# A second scenario, deliberately built to score LOW on pure text
# similarity (see _decompose_theft_weak_overlap below) -- confirms the
# unfiltered behavior holds even for a weak-scoring candidate, not just
# a strong one.
def _decompose_theft_weak_overlap(msg):
    # deliberately shares almost no vocabulary with _HTML_THEFT_ONTOPIC's
    # paragraphs, so the fake keyword-overlap reranker gives it a low
    # content_score even though the fetched text genuinely cites Section
    # 303 -- and deliberately avoids any settled_doctrine_whitelist
    # trigger words (family/notified, grounds, 24 hours, lawyer, medical,
    # bail) so this stays a non-whitelisted question.
    return {"primary_grievance": "workplace dispute that turned into a police complaint",
            "procedural_stage": "unknown",
            "issues": [
                {"issue": "arrest over a workplace dispute the accused denies any part in",
                 "hook_phrase": "workplace dispute that turned into a police complaint",
                 "section_hooks": ["BNS 303"]},
            ]}


weak_res = rj.get_related_judgments(
    "there was a workplace dispute that turned into a police complaint and an arrest",
    write_bundle=False, pin=True,
    decompose_fn=_decompose_theft_weak_overlap, ik_search_many_fn=_fake_ik_search_theft,
    local_search_fn=lambda q: [], rerank_fn=_fake_rerank, gloss_fn=_tracking_gloss,
    fetch_many_fn=_fake_fetch_theft, clean_fn=_fake_clean, today=datetime.date(2026, 9, 3),
)
weak_scores = [c.get("content_score") for c in weak_res["candidates"] if c["source"] == "indiankanoon"]
check(bool(weak_scores) and max(weak_scores) < rj._DISPLAY_CONTENT_FLOOR,
      f"sanity check on the test setup: the weak-overlap fixture really does score low ({weak_scores})")
check(weak_res["unverified_for_display"] == weak_res["candidates"],
      "a low-scoring candidate is included too -- unverified_for_display is never score-filtered")

# REGRESSION TEST (2026-09-05, Phase 3c, caught by LIVE testing on a real
# Section 66A question): unverified_for_display used to be gated on
# `show_user` alone (`[] if show_user else list(ranked)`). CONFIRMED REAL
# FAILURE: when every issue WAS whitelisted (show_user=True) but
# _display_worthy's score floor excluded every real candidate anyway,
# for_display AND unverified_for_display were BOTH forced empty -- the
# exact "this tool's own confidence hides real results" bug the 2026-09-04
# correction above was written to fix, reappearing in a narrower case the
# original fix didn't cover. The fix: gate on whether for_display actually
# ended up non-empty, not on show_user directly.
def _decompose_whitelisted_weak_overlap(msg):
    # section_hooks alone is enough to satisfy settled_doctrine_whitelist's
    # default_bail entry (BNSS 187 is in its "sections" set) regardless of
    # scoring -- deliberately paired with the SAME weak-overlap fixture as
    # _decompose_theft_weak_overlap above, so real candidates exist but
    # none clear the display-confidence floor.
    return {"primary_grievance": "workplace dispute that turned into a police complaint",
            "procedural_stage": "unknown",
            "issues": [
                {"issue": "chargesheet not filed within the time limit",
                 "hook_phrase": "workplace dispute that turned into a police complaint",
                 "section_hooks": ["BNSS 187"]},
            ]}


# Fix 4 (2026-09-06) gave default_bail a doctrine anchor, so every whitelist
# topic now injects a guaranteed-display anchor. This regression guard tests
# the OTHER path -- show_user True but for_display legitimately empty -- so
# anchor injection is suppressed here to keep that path reachable.
with patch("doctrine_anchors.anchor_candidates", lambda *a, **k: []):
    whitelisted_weak_res = rj.get_related_judgments(
        "there was a workplace dispute that turned into a police complaint and no chargesheet was filed for months",
        write_bundle=False, pin=True,
        decompose_fn=_decompose_whitelisted_weak_overlap, ik_search_many_fn=_fake_ik_search_theft,
        local_search_fn=lambda q: [], rerank_fn=_fake_rerank, gloss_fn=_tracking_gloss,
        fetch_many_fn=_fake_fetch_theft, clean_fn=_fake_clean, today=datetime.date(2026, 9, 3),
    )
check(whitelisted_weak_res["show_user"] is True,
      "sanity check on the test setup: this issue IS whitelisted (default_bail via the BNSS 187 section hook)")
check(whitelisted_weak_res["for_display"] == [],
      "sanity check on the test setup: nothing clears the display-confidence floor (weak-overlap fixture)")
check(whitelisted_weak_res["unverified_for_display"] == whitelisted_weak_res["candidates"],
      "CONFIRMED FIX: even though show_user is True, when for_display legitimately ends up empty "
      "(nothing scored high enough), the full ranked list still falls back to unverified_for_display "
      "-- gating on show_user alone used to leave the user with nothing at all in exactly this case")


# _dedupe_batch -- a batch order gives one IK doc per connected petition
_batch = [
    {"score": 0.8, "triage": {"title": "Mujeeb Rahman v State of Kerala", "court": "Kerala High Court", "publish_date": "2026-08-21"},
     "pinned": [{"text": "12. The right to be produced before a Magistrate within twenty-four hours is mandatory and absolute."}]},
    {"score": 0.79, "triage": {"title": "Rashad Muhammed v State of Kerala", "court": "Kerala High Court", "publish_date": "2026-08-21"},
     "pinned": [{"text": "12. The right to be produced before a Magistrate within twenty-four hours is mandatory and absolute."}]},
    {"score": 0.7, "triage": {"title": "Someone Else v State of Punjab", "court": "Punjab & Haryana High Court", "publish_date": "2025-03-01"},
     "pinned": [{"text": "4. A wholly different holding about default bail arithmetic."}]},
]
_dd = rj._dedupe_batch(_batch)
check(len(_dd) == 2, "a 3-row list with 2 batch-identical rows collapses to 2")
check(_dd[0]["triage"]["title"] == "Mujeeb Rahman v State of Kerala",
      "the higher-scored row of the batch pair is the one kept")
check(any(c["triage"]["court"].startswith("Punjab") for c in _dd),
      "a genuinely different judgment (different court/date/para) is NOT deduped away")


# ---------------------------------------------------------------------------
# Speedup: indiankanoon_client parallel helpers + prepare_related_judgments
# ---------------------------------------------------------------------------
import indiankanoon_client as ik

_calls = []
def _slow_search(q, page=0):
    import time as _t
    _calls.append(q); _t.sleep(0.05)
    if "boom" in q:
        raise RuntimeError("nope")
    return {"found": "1 of 1", "docs": [{"tid": abs(hash(q)) % 100000, "title": q}]}

with patch("indiankanoon_client.search", _slow_search), \
     patch("indiankanoon_client._check_api_key", lambda: None):
    import time as _t
    t0 = _t.time()
    out = ik.search_many(["q one", "q two", "q three", "q boom"])
    elapsed = _t.time() - t0
    check(set(out) == {"q one", "q two", "q three", "q boom"}, "search_many returns a result per query")
    check(out["q boom"] is None, "a query that errors maps to None, not a raise")
    check(all(isinstance(out[q], dict) for q in ("q one", "q two", "q three")),
          "the other queries return their dicts")
    check(elapsed < 0.18, f"4 x 50ms searches ran concurrently (took {elapsed:.2f}s, not ~0.2s serial)")

_dcalls = []
def _slow_doc(tid):
    import time as _t
    _dcalls.append(tid); _t.sleep(0.05)
    return {"doc": f"<html>{tid}</html>"}

with patch("indiankanoon_client.get_document", _slow_doc), \
     patch("indiankanoon_client._check_api_key", lambda: None):
    out = ik.get_documents([10, 11, 12, 10])  # dupe 10
    check(set(out) == {"10", "11", "12"}, "get_documents dedupes and keys by string id")
    check(out["11"]["doc"] == "<html>11</html>", "each doc comes back correctly")


# prepare_related_judgments: the free half, reusable via prepared=
prep = rj.prepare_related_judgments(
    "arrested though his name was not in the FIR, and no chargesheet after two months",
    decompose_fn=_decompose_whitelisted, local_search_fn=_fake_local_search,
    rerank_fn=_fake_rerank, today=datetime.date(2026, 9, 3),
)
check(prep is not None and "profile" in prep and "anchors" in prep,
      "prepare_related_judgments returns the profile + anchors (the free half)")
check(all(c["source"] == "corpus" for c in prep["corpus_ranked"]),
      "prepare_related_judgments' corpus_ranked holds only corpus candidates (no IK yet)")

_prep_decomp_calls = []
def _counting_decompose(msg):
    _prep_decomp_calls.append(1)
    return _decompose_whitelisted(msg)

with patch("related_judgments._corpus_para_pool", lambda name: [
    {"text": "9. Article 22 of the Constitution: arrested shall be detained only per procedure.", "structure": None, "para_number": 9}]):
    res_prep = rj.get_related_judgments(
        "arrested though his name was not in the FIR, and no chargesheet after two months",
        grounded_answer_text="Section 35 of the BNSS governs arrest. Section 187 governs default bail.",
        write_bundle=False, prepared=prep,
        decompose_fn=_counting_decompose,
        ik_search_many_fn=_fake_ik_search_many, rerank_fn=_fake_rerank,
        fetch_many_fn=_fake_fetch_many, clean_fn=_fake_clean, gloss_fn=lambda s, p: "The court considered a similar delay.",
        today=datetime.date(2026, 9, 3),
    )
check(len(_prep_decomp_calls) == 0,
      "get_related_judgments(prepared=...) does NOT re-run decomposition")
check(res_prep["status"] == "ok" and res_prep["profile"] is prep["profile"],
      "a prepared run reuses the profile and still completes")
check(any(c["source"] == "corpus" for c in res_prep["candidates"]),
      "the prepared corpus candidates are merged back into the final ranked list")


# ---------------------------------------------------------------------------
# authorities_from_result / authorities_from_matches -> draft_layer input
# ---------------------------------------------------------------------------
_res = {"for_display": [
    {"source": "corpus", "triage": {"title": "D.K. Basu v State of West Bengal",
        "citation": "(1997) 1 SCC 416", "court": "Supreme Court", "url": "https://indiankanoon.org/doc/235756/"},
     "pinned": [{"para_number": 8, "text": "The arrestee should be subjected to medical examination every 48 hours."}]},
    {"source": "indiankanoon", "triage": {"title": "Mujeeb Rahman v State of Kerala",
        "citation": "", "court": "Kerala High Court", "url": "https://indiankanoon.org/doc/999/"},
     "pinned": [{"para_number": 12, "text": "The right to be produced before a Magistrate within twenty-four hours is absolute."}]},
    {"source": "indiankanoon", "triage": {"title": "No Pins v State"}, "pinned": []},
]}
auths = rj.authorities_from_result(_res)
check(len(auths) == 2, "authorities_from_result: one entry per displayed candidate that has a pinned paragraph")
check(auths[0]["verified"] is True and auths[1]["verified"] is False,
      "corpus -> verified True, live Indian Kanoon -> verified False")
check(auths[0]["quote"].startswith("The arrestee should") and auths[0]["para_number"] == 8,
      "the pinned paragraph text is carried verbatim with its number")
check(auths[1]["url"] == "https://indiankanoon.org/doc/999/", "the live hit keeps its source link")

m_auths = rj.authorities_from_matches([
    {"case_name": "Vihaan Kumar v State of Haryana", "citation": "2025 INSC 162",
     "paragraph_number": 21, "text": "Non-compliance with Article 22(1) vitiates the arrest and the remand.",
     "type": "judgment", "source_url": "https://indiankanoon.org/doc/74708490/"},
    {"section_number": "303", "text": "Whoever commits theft...", "type": "statute"},  # not a judgment -> skipped
])
check(len(m_auths) == 1 and m_auths[0]["verified"] is True,
      "authorities_from_matches keeps only judgment matches, all verified (from the 22-case corpus)")
check(m_auths[0]["para_number"] == 21 and "vitiates the arrest" in m_auths[0]["quote"],
      "the corpus paragraph and its number come through")


# ---------------------------------------------------------------------------
# The user-approved store: record_approved / approved_candidates
# ---------------------------------------------------------------------------
import tempfile, os as _os, json as _json

_store = _os.path.join(tempfile.mkdtemp(), "approved.json")
_issues = [{"issue": "arrest of a person not produced before a magistrate within twenty-four hours"},
           {"issue": "denial of access to a lawyer during police custody"}]
_result_to_approve = {"for_display": [
    {"source": "indiankanoon",
     "triage": {"tid": 42, "title": "Mujeeb Rahman v State of Kerala", "court": "Kerala High Court",
                "url": "https://indiankanoon.org/doc/42/", "citation": ""},
     "pinned": [{"para_number": 12, "text": "The right to be produced before a Magistrate within twenty-four hours is absolute."}],
     "gloss": "Deals with delayed production before a magistrate."},
    {"source": "indiankanoon", "triage": {"tid": 43, "title": "No Pins"}, "pinned": []},  # skipped
]}

n = rj.record_approved("my brother was not produced before a magistrate in 24 hours and denied a lawyer",
                       _issues, _result_to_approve, path=_store)
check(n == 1, "record_approved stores one judgment (the one with a pinned paragraph)")
check(_os.path.exists(_store), "the approved store file is written")

# re-recording the same judgment does not duplicate it
n2 = rj.record_approved("another similar question about 24 hour production", _issues, _result_to_approve, path=_store)
check(n2 == 0 and len(_json.load(open(_store))) == 1, "recording the same tid again is a no-op")

# a new question whose issues overlap -> the approved judgment comes back, pre-pinned
prof = {"_question": "different wording",
        "issues": [{"issue": "person was not produced before the magistrate within 24 hours of arrest"}]}
got = rj.approved_candidates(prof, path=_store)
check(len(got) == 1 and got[0]["source"] == "approved", "an overlapping-issue question retrieves the approved judgment")
check(got[0]["pinned"] and got[0]["pinned"][0]["para_number"] == 12,
      "it comes back pre-pinned -- no Indian Kanoon call needed")
check(got[0]["triage"]["previously_approved"] is True, "flagged previously_approved")

# an unrelated question -> nothing
check(rj.approved_candidates({"issues": [{"issue": "my landlord filed an eviction suit"}]}, path=_store) == [],
      "an unrelated question retrieves nothing from the approved store")

# exact-question match works even with different issue phrasing
check(len(rj.approved_candidates(
    {"_question": "my brother was not produced before a magistrate in 24 hours and denied a lawyer",
     "issues": [{"issue": "completely different phrasing here"}]}, path=_store)) == 1,
    "the exact same question retrieves the approved judgment regardless of issue wording")

check(rj.approved_candidates({"issues": []}, path="/nonexistent/nope.json") == [],
      "a missing store file -> [], never a raise")


# ---------------------------------------------------------------------------
# REGRESSION (2026-09-05, caught via live user testing): the same real
# judgment reached the Lane B panel TWICE -- once as a fresh corpus hit
# (source='corpus') and once via the approved-store reuse cache
# (source='approved', tid also None there). The old dedup key in BOTH
# _merge_ranked and prepare_related_judgments' seed-merge was
# (source, tid-or-title) -- including source let the same judgment
# survive under two different keys ("Arnesh Kumar v State of Bihar"
# showed up once as "in our verified library" and once as "you kept
# this in a draft before"). Fixed via _judgment_identity(), which drops
# source from the key entirely.
# ---------------------------------------------------------------------------
_arnesh_corpus = {"source": "corpus", "score": 0.55,
                  "triage": {"tid": None, "title": "Arnesh Kumar v State of Bihar"}}
_arnesh_approved = {"source": "approved", "score": 0.6,
                    "triage": {"tid": None, "title": "Arnesh Kumar v State of Bihar",
                               "previously_approved": True}}
_other = {"source": "indiankanoon", "score": 0.5, "triage": {"tid": 999, "title": "Some Other Case"}}

merged = rj._merge_ranked([_arnesh_corpus, _other], [_arnesh_approved])
check(len(merged) == 2,
      "_merge_ranked collapses the same judgment found via corpus AND the approved store into one entry")
check(merged[0]["source"] == "corpus",
      "the fresh corpus entry wins over the 'you kept this in a draft before' framing (first list wins)")

_arnesh_approved_upper = {**_arnesh_approved,
                          "triage": {**_arnesh_approved["triage"], "title": "ARNESH KUMAR V STATE OF BIHAR"}}
check(len(rj._merge_ranked([_arnesh_corpus], [_arnesh_approved_upper])) == 1,
      "_merge_ranked's dedup is case-insensitive on title")

check(len(rj._merge_ranked(
    [{"source": "corpus", "score": 0.4, "triage": {"tid": 42, "title": "X v Y"}}],
    [{"source": "approved", "score": 0.9, "triage": {"tid": 42, "title": "X v Y (approved copy)"}}],
)) == 1, "_merge_ranked dedupes by tid even when the title string differs")

# the same bug also lived in prepare_related_judgments' own seed-vs-corpus
# merge (line ~1411) -- exercise that call site directly, with
# approved_candidates() stubbed so no real store file is touched.
_arnesh_seed = [{
    "source": "approved", "matched_issues": [0], "queries": [],
    "pinned": [{"para_number": 7, "structure": None, "text": "Arrest should be the last option."}],
    "gloss": None, "content_score": 0.6, "rerank_score": 0.6, "rerank_used": True,
    "_nudges": 0.0, "score": 0.6,
    "triage": {"tid": None, "title": "Arnesh Kumar v State of Bihar", "citation": "(2014) 8 SCC 273",
               "court": "Supreme Court", "court_tier": "high_court",
               "url": "https://indiankanoon.org/doc/2982624/", "publish_date": None,
               "is_corpus_case": False, "cited_in_answer": False, "adverse_markers": [],
               "previously_approved": True},
}]

with patch("related_judgments.approved_candidates", lambda profile: _arnesh_seed), \
     patch("related_judgments._corpus_case_names", lambda: set(CORPUS_NAMES)):
    prep2 = rj.prepare_related_judgments(
        "police want to arrest me without any justification, what are my rights",
        decompose_fn=_decompose_whitelisted,
        local_search_fn=lambda q: [_corpus_rec("Arnesh Kumar v State of Bihar", "7",
                                                "Arrest should be the last option.", score=0.7)],
        rerank_fn=_fake_rerank, today=datetime.date(2026, 9, 5),
    )
titles2 = [c["triage"]["title"] for c in prep2["corpus_ranked"]]
check(titles2.count("Arnesh Kumar v State of Bihar") == 1,
      "prepare_related_judgments' seed-merge no longer lets the same judgment in twice "
      "(fresh corpus hit + approved-store copy)")
check(prep2["corpus_ranked"][titles2.index("Arnesh Kumar v State of Bihar")]["source"] == "corpus",
      "the surviving entry is the fresh corpus hit, not the approved-store copy")


# ---------------------------------------------------------------------------
print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILED")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("RESULT: ALL TESTS PASSED")
