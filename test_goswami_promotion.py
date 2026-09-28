"""
test_goswami_promotion.py -- promotes the non-bailable-warrant guidance of Inder Mohan Goswami v State of
Uttaranchal ((2007) 12 SCC 1, Supreme Court, 9 Oct 2007) from the pilot tier into the fully-verified core corpus,
through the SAME judgment_doctrine_map.py mechanism used for Jagrup Singh. Written BEFORE the promotion.

WHY (2026-09-28): a real WhatsApp question, "When can a court issue a non-bailable warrant?", was answered by the
model paraphrasing a hedged pilot-tier case, and the answer left out the Court's strongest protection for an accused
person (no non-bailable warrant unless a heinous crime AND a feared risk of tampering or absconding). The core doctrine
map had no warrant entry at all. The user approved anchoring exactly this guidance, keeping the pilot copy, and NOT
anchoring the civil-dispute/cheating holdings (already covered by four verified core cases).

The judgment has no numbered paragraphs, so its chunks are fixed-size pieces labelled fallback_N (the tool's own
labels, not the Court's) -- the same situation as Jagrup Singh. The guidance sits in pieces 26 and 27.

Fully offline and free. Run: python -X utf8 test_goswami_promotion.py
"""
import importlib
import json
import os
import re
import sys
from unittest.mock import patch

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


SLUG = "inder_mohan_goswami_and_anr_v_state_of_uttaranchal_and_ors"
CORE = f"chunks/{SLUG}_chunks.json"
PILOT = f"pilot_chunks/{SLUG}_chunks.json"
CASE_NAME = "Inder Mohan Goswami and Anr. v State of Uttaranchal and Ors."
GOV_LINK = "https://api.sci.gov.in/jonew/judis/29628.pdf"


def squash(s):
    return re.sub(r"\s+", " ", s)


# ---------------------------------------------------------------- 1. the core chunk file
check(os.path.exists(CORE), f"{CORE} exists (promoted out of pilot_chunks/, which retrieval's registry does not scan)")
core = json.load(open(CORE, encoding="utf-8")) if os.path.exists(CORE) else []
pilot = json.load(open(PILOT, encoding="utf-8"))
check(len(core) == 28 == len(pilot), f"all 28 pieces carried over -- core {len(core)}, pilot {len(pilot)}")
check(all("embedding" not in c and "topic" not in c for c in core),
      "core chunk files carry neither embeddings nor a pilot 'topic' tag (same as every other core file)")
check(core and all(c.get("source_url") == GOV_LINK for c in core), "every piece keeps the real api.sci.gov.in link")
check(core and [c["text"] for c in core] == [c["text"] for c in pilot], "the text of every piece is byte-identical to the pilot copy -- nothing edited")
check(core and all(c["case_name"] == CASE_NAME and c["citation"] == "(2007) 12 SCC 1" for c in core), "case name and citation carried through")

# ---------------------------------------------------------------- 2. the pilot copy is KEPT (user's decision, 2026-09-28)
check(os.path.exists(PILOT) and all(len(c.get("embedding") or []) == 1024 for c in pilot),
      "the pilot copy is kept, with its embeddings, so Goswami stays findable by meaning on cheating/civil-dispute questions")

# ---------------------------------------------------------------- 3. real text resolves via retrieval
import retrieval
importlib.reload(retrieval)
check("inder_mohan_goswami_and_anr" in retrieval._JUDGMENT_CHUNK_FILES, "auto-registered under the 'stem before _v_' convention")
paras = retrieval.get_judgment_paragraphs("inder_mohan_goswami_and_anr", ["fallback_26", "fallback_27"]) or []
check([p["paragraph_number"] for p in paras] == ["fallback_26", "fallback_27"], f"both chosen pieces resolve -- got {[p['paragraph_number'] for p in paras]}")
combined = squash(" ".join(p["text"] for p in paras))
SIX = [
    "the courts have to be extremely careful before issuing non-bailable warrants",
    "Non-bailable warrant should be issued to bring a person to court when summons of bailable warrants would be unlikely to have the desired result",
    "the summon or the bailable warrants should be preferred",
    "should never be issued without proper scrutiny of facts and complete application of mind",
    "In complaint cases, at the first instance, the court should direct serving of the summons",
    "unless an accused is charged with the commission of an offence of a heinous crime and it is feared that he is likely to tamper or destroy the evidence or is likely to evade the process of law, issuance of non-bailable warrants should be avoided",
]
# piece 25 (not anchored) holds the 'extremely careful' sentence's opening, so the first is checked across 25+26+27
all_text = squash(" ".join(p["text"] for p in (retrieval.get_judgment_paragraphs("inder_mohan_goswami_and_anr", ["fallback_25", "fallback_26", "fallback_27"]) or [])))
for s in SIX:
    check(s in all_text, f"the Court's own sentence is genuinely in the resolved text -- {s[:70]!r}...")
check("heinous crime" in combined and "third instance" in combined,
      "the two anchored pieces together carry the heinous-crime rule and the 3-step complaint-case sequence")
check(all(p.get("source_url") == GOV_LINK for p in paras), "get_judgment_paragraphs now carries the real source link on every piece it returns")

# ---------------------------------------------------------------- 4. the doctrine map entry
import judgment_doctrine_map as jdm
importlib.reload(jdm)

ON_POINT = [
    "When can a court issue a non-bailable warrant?",
    "The magistrate issued a non bailable warrant against my brother in a cheque case",
    "Court sent a bailable warrant, what do I do?",
    "I missed a hearing and now there is a warrant against me",
    "he did not appear in court and the court issued a warrant",
    "Can a court issue NBW without sending a summons first?",
    "The court skipped the summons and directly issued a warrant",
]
OFF_POINT = [
    "Do police need a warrant to arrest me?",
    "Police arrested my son without any warrant, is that legal?",
    "Police came to search my house with a search warrant",
    "Is theft a bailable offence?",
    "My bank account was frozen and I can't access my salary.",
    "The court gave me a summons for a cheque bounce case",
    "Can I get anticipatory bail?",
]
KEY = "non_bailable_warrant_summons_first_then_bailable_then_nbw"
check(KEY in jdm.JUDGMENT_DOCTRINE_MAP, f"the doctrine entry {KEY!r} exists")
for q in ON_POINT:
    check(KEY in jdm.match_judgment_doctrine(q), f"fires on -- {q!r}")
for q in OFF_POINT:
    check(KEY not in jdm.match_judgment_doctrine(q), f"does NOT fire on -- {q!r}")

entry = jdm.JUDGMENT_DOCTRINE_MAP.get(KEY, {})
check(entry.get("case_key") == "inder_mohan_goswami_and_anr" and entry.get("paragraph_numbers") == ["fallback_26", "fallback_27"],
      "the entry points at exactly pieces 26 then 27 of Goswami")
note = squash(entry.get("context_note", "")).lower()
for needle in ("complaint cases", "straight-jacket", "heinous crime", "personal liberty"):
    check(needle in note, f"the context note carries {needle!r}")
check("guidance to trial courts" in note and "does not by itself make any particular warrant invalid" in note,
      "the note says this is guidance to trial courts, not a rule that invalidates a particular warrant")
check(entry.get("verified_note"), "a verified_note records how the anchor was checked")

# ---------------------------------------------------------------- 5. what the answer engine actually receives
out = [o for o in jdm.get_judgment_doctrine_override(ON_POINT[0]) if o.get("case_name") == CASE_NAME]
check(len(out) == 2 and [o["paragraph_number"] for o in out] == ["fallback_26", "fallback_27"], f"the override returns both pieces in order -- got {len(out)}")
if out:
    check(all(o["source"] == "curated_judgment_override" for o in out), "tagged as a curated (full-authority) override, not the pilot hedge")
    check(all(o.get("source_url") == GOV_LINK for o in out), "each override match carries the real government link")
    check("heinous crime" in squash(out[1]["text"]), "the heinous-crime rule reaches the model")

# ---------------------------------------------------------------- 6. court fact
import judgment_court_facts as jcf
check(jcf.CASE_NAME_TO_COURT.get(CASE_NAME) == "Supreme Court of India", "the court fact is recorded (header of the PDF: SUPREME COURT OF INDIA)")

# ---------------------------------------------------------------- 7. no double citation with the pilot list
import chat_assistant as ca
FAKE_PILOT_HIT = {"case_name": CASE_NAME, "source_url": GOV_LINK, "chunk_method": "fixed_size_fallback",
                  "paragraph_number": "fallback_9", "citation": "(2007) 12 SCC 1", "text": "x"}
with patch("pilot_tier_search.search_pilot_tier", return_value=[FAKE_PILOT_HIT]):
    check(ca._fetch_pilot_related_judgments(ON_POINT[0], exclude_case_names={CASE_NAME}) == [],
          "once Goswami is a verified match on the warrant question it is left out of the hedged pilot list")
    check([x["case_name"] for x in ca._fetch_pilot_related_judgments("Can a cheating FIR be quashed in a civil dispute?", exclude_case_names=set())] == [CASE_NAME],
          "on a question where it is NOT a verified match it still appears in the pilot list (the reason the pilot copy is kept)")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
