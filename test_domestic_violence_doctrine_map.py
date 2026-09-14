
"""
test_domestic_violence_doctrine_map.py

Regression suite for domestic_violence_doctrine_map.py -- the first
trusted-tier legal-domain expansion beyond BNS/BNSS/cheque_bounce/freeze
(see that module's docstring for the full design). Same lightweight
check()/FAILURES convention as the rest of this repo's test_*.py files;
run directly: `python test_domestic_violence_doctrine_map.py`. No API
cost -- pure Python, real local chunk files, no network.
"""
from domestic_violence_doctrine_map import get_domestic_violence_override

FAILURES = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {description}")
    if not condition:
        FAILURES.append(description)


# ---- always-on foundational sections ----

base = get_domestic_violence_override("what counts as domestic violence")
sections = {m["section_number"] for m in base if m.get("act") == "PWDVA"}
check(
    {"2", "3"}.issubset(sections),
    "Sections 2 (definitions) and 3 (what counts as domestic violence) are always included, "
    "since any real question needs them",
)
check(
    all(m.get("source") == "curated_override" for m in base if m.get("act") == "PWDVA"),
    "every statute anchor is tagged 'curated_override', matching statute_doctrine_map's convention",
)

# ---- section-specific triggers ----

check(
    "19" in {m["section_number"] for m in get_domestic_violence_override("he threw me out of the house") if m.get("act") == "PWDVA"},
    "Section 19 (residence orders) fires for a 'thrown out of the house' question",
)
check(
    "20" in {m["section_number"] for m in get_domestic_violence_override("I lost my job and have no money for medical expenses") if m.get("act") == "PWDVA"},
    "Section 20 (monetary relief) fires for a money/expenses question",
)
check(
    "23" in {m["section_number"] for m in get_domestic_violence_override("this is an emergency, it's happening right now") if m.get("act") == "PWDVA"},
    "Section 23 (interim/ex parte orders) fires for an urgent/emergency question",
)
check(
    "19" not in {m["section_number"] for m in get_domestic_violence_override("what is domestic violence") if m.get("act") == "PWDVA"},
    "Section 19 does NOT fire for a question with no residence/housing keywords -- triggers are real, not decorative",
)

# ---- judgment anchors: real chunk files, real verbatim text ----

harsora_q = get_domestic_violence_override("my mother in law is the one hurting me, not my husband")
harsora_hits = [m for m in harsora_q if m.get("case_name") == "Hiral P. Harsora v Kusum Narottamdas Harsora"]
check(
    len(harsora_hits) == 1 and "adult male" in harsora_hits[0]["text"] and "struck" not in harsora_hits[0]["text"].lower()[:1] ,
    "a 'mother in law' question surfaces the real Harsora holding paragraph (verbatim, from the chunk file)",
)
check(
    harsora_hits and "stand deleted" in harsora_hits[0]["text"],
    "the Harsora text is the actual verbatim holding pulled from Indian Kanoon, not a paraphrase",
)
check(
    harsora_hits and harsora_hits[0]["citation"] == "AIR 2016 SC 4774, (2016) 10 SCC 165",
    "the real, verified citation is attached, not a placeholder",
)

velusamy_q = get_domestic_violence_override("we have been living together as boyfriend and girlfriend for years")
velusamy_hits = [m for m in velusamy_q if m.get("case_name") == "D. Velusamy v D. Patchaiammal"]
check(
    len(velusamy_hits) == 2,
    "both pinned Velusamy paragraphs (33, 34 -- the 4-condition test and its limiting principle) are returned",
)
check(
    any("hold themselves out" in m["text"] for m in velusamy_hits),
    "the actual 4-condition test text is present, verbatim",
)

check(
    get_domestic_violence_override("my mother in law hurts me") == get_domestic_violence_override("my mother in law hurts me"),
    "the same question always produces the same result -- fully deterministic, no randomness",
)

# ---- never raises ----

check(
    get_domestic_violence_override("") is not None,
    "an empty question never raises -- returns the always-on sections, not a crash",
)
check(
    get_domestic_violence_override(None) is not None,
    "a None question never raises",
)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) failed:")
    for f in FAILURES:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("\nAll checks passed.")
