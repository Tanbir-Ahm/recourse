"""
test_search_stem.py -- search_stem.py, the Porter stemmer behind the search page's word matching. Offline and free.
1. Porter's measure m (the examples of the 1980 paper) and the consonant rule for y;
2. the paper's own examples, step by step and in full (the final stems of the whole algorithm);
3. the legal words the search page depends on (punishment / punished / punishable, bribe / bribed / bribing, arrest / arrested ...), and the pairs that do NOT meet (police / policy, bail / bailable);
4. what is left alone: words with a digit, one- and two-letter words, anything that is not plain a-z, absurdly long runs;
5. the stems are the same in every call (cache), and stems() keeps order and length.
The stemmer was also compared, once, with two independent Porter implementations (NLTK's original-algorithm mode and the snowball 'porter') on 85,325 distinct words: the words of Recourse's own texts, other
English text on the machine, and 60,000 random root + suffix + suffix products that exercise every rule; there were no differences for any word of three or more letters (those libraries are not a dependency of the
project, so that comparison is not repeated here; the figures are in review_results/2026-10-23_export_and_search/RESULTS.md).
Run: python -X utf8 test_search_stem.py
"""
import sys

import search_stem as P

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ======================================================================================================================
# 1. the measure and the consonant rule
# ======================================================================================================================
for w, m in (("tr", 0), ("ee", 0), ("tree", 0), ("y", 0), ("by", 0), ("trouble", 1), ("oats", 1), ("trees", 1), ("ivy", 1), ("troubles", 2), ("private", 2), ("oaten", 2), ("orrery", 2)):
    check(P._measure(w) == m, f"the measure of '{w}' is {m} (Porter 1980)")
check([P._cons("toy", i) for i in range(3)] == [True, False, True], "y after a vowel is a consonant (toy: t o y)")
check([P._cons("syzygy", i) for i in range(6)] == [True, False, True, False, True, False], "y after a consonant is a vowel, y at the start is a consonant (syzygy)")
check(P._cvc("hop") and P._cvc("fil") and not P._cvc("snow") and not P._cvc("box") and not P._cvc("tray") and not P._cvc("ab"), "the cvc rule: not when the last letter is w, x or y, nor in a short stem")

# ======================================================================================================================
# 2. the examples of the paper, as the whole algorithm turns them out
# ======================================================================================================================
PAPER = {
    # step 1a
    "caresses": "caress", "ponies": "poni", "ties": "ti", "caress": "caress", "cats": "cat",
    # step 1b
    "feed": "feed", "agreed": "agre", "plastered": "plaster", "bled": "bled", "motoring": "motor", "sing": "sing",
    "conflated": "conflat", "troubled": "troubl", "sized": "size", "hopping": "hop", "tanned": "tan", "falling": "fall", "hissing": "hiss", "fizzed": "fizz", "failing": "fail", "filing": "file",
    # step 1c
    "happy": "happi", "sky": "sky",
    # step 2
    "relational": "relat", "conditional": "condit", "rational": "ration", "valenci": "valenc", "digitizer": "digit", "vileli": "vile", "vietnamization": "vietnam", "predication": "predic", "operator": "oper",
    "feudalism": "feudal", "decisiveness": "decis", "hopefulness": "hope", "callousness": "callous", "formaliti": "formal", "sensitiviti": "sensit",
    # step 3
    "triplicate": "triplic", "formative": "form", "formalize": "formal", "electriciti": "electr", "electrical": "electr", "hopeful": "hope", "goodness": "good",
    # step 4
    "revival": "reviv", "allowance": "allow", "inference": "infer", "airliner": "airlin", "gyroscopic": "gyroscop", "adjustable": "adjust", "defensible": "defens", "irritant": "irrit", "replacement": "replac",
    "adjustment": "adjust", "dependent": "depend", "adoption": "adopt", "communism": "commun", "activate": "activ", "effective": "effect", "bowdlerize": "bowdler", "homologous": "homolog",
    # step 5
    "probate": "probat", "rate": "rate", "cease": "ceas", "controll": "control", "roll": "roll",
}
bad = {w: (P.stem(w), want) for w, want in PAPER.items() if P.stem(w) != want}
check(not bad, f"the {len(PAPER)} examples of Porter's paper come out as published{'' if not bad else ': ' + str(bad)}")
check(P.stem("element") == "element" and P.stem("replacement") == "replac", "step 4 tries only the longest matching suffix: 'element' (m of 'el' is 1) is left alone, 'replacement' loses 'ement'")
check(P.stem("agreed") == "agre" and P.stem("agree") == "agre", "agreed and agree meet (steps 1b and 5a)")

# ======================================================================================================================
# 3. the words of the search page
# ======================================================================================================================
def same(*ws):
    return len({P.stem(w) for w in ws}) == 1


check(same("punish", "punished", "punishment", "punishable", "punishing", "punishes"), "punish / punished / punishment / punishable / punishing / punishes meet")
check(same("bribe", "bribed", "bribing", "bribes"), "bribe / bribed / bribing / bribes meet")
check(same("arrest", "arrested", "arresting", "arrests", "arrestable"), "arrest in all its usual forms")
check(same("murder", "murdered", "murderer", "murders"), "murder / murdered / murderer / murders meet")
check(same("offender", "offenders") and same("offence", "offences") and not same("offence", "offender"), "offence(s) and offender(s) are two stems, as they are two words")
check(same("abet", "abetted", "abetting", "abetment"), "abet / abetted / abetting / abetment meet")
check(same("compensation", "compensate", "compensated"), "compensation / compensate / compensated meet")
check(same("negligent", "negligence", "negligently"), "negligent / negligence / negligently meet")
check(same("imprison", "imprisoned", "imprisonment"), "imprison / imprisoned / imprisonment meet")
check(same("condition", "conditions", "conditional"), "condition / conditions / conditional meet")
check(same("victim", "victims") and same("warrant", "warrants"), "plain plurals meet")
check(not same("police", "policy"), "police and policy stay apart (polic / polici)")
check(not same("bail", "bailable") and P.stem("bailable") == "bailabl", "bail and bailable are two stems (the algorithm leaves 'bailable' whole); a query for 'bailable' finds 'bailable'")
check(not same("bribe", "bribery"), "bribe and bribery are two stems (a known limit of the algorithm, not hidden)")
check(P.stem("cognizable") != P.stem("cognisable"), "the two spellings cognizable / cognisable are two stems (a known limit of the algorithm, not hidden)")

# ======================================================================================================================
# 4. what is left alone
# ======================================================================================================================
for w in ("498a", "43d", "2023", "17", "section17", "bns2023", "a1b", "x2"):
    check(P.stem(w) == w, f"'{w}' (has a digit) is not changed")
for w in ("is", "as", "us", "it", "of", "s", "a", "ls", "ds", ""):
    check(P.stem(w) == w, f"'{w}' (no more than two letters) is not changed")
for w in ("café", "naïve", "धारा", "ünïcode"):
    check(P.stem(w) == w, f"'{w}' (not plain a-z) is not changed")
long_word = "a" * 41
check(P.stem(long_word) == long_word and P.stem("s" * 300) == "s" * 300, "a run of more than 40 letters is not a word and is not changed")
check(P.stem("Punishment") == "Punishment", "the caller lower-cases (search_service does); a capital letter is not a lower-case a-z word and is left alone")

# ======================================================================================================================
# 5. calls
# ======================================================================================================================
toks = ["the", "police", "arrested", "the", "accused", "without", "warrant", "498a"]
out = P.stems(toks)
check(len(out) == len(toks) and out[0] == "the" and out[1] == "polic" and out[2] == "arrest" and out[4] == "accus" and out[-1] == "498a", "stems() keeps the order and the length")
check(P.stems([]) == [] and P.stem("punishment") == P.stem("punishment") == "punish", "stems of nothing; the same answer on the second call (cache)")
check(isinstance(P.stem.cache_info().hits, int), "the stems are cached")

print()
print("FAILURES:", len(FAILURES))
for f in FAILURES:
    print("  -", f)
sys.exit(1 if FAILURES else 0)
