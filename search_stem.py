"""
search_stem.py

The Porter stemmer (M. F. Porter, "An algorithm for suffix stripping", Program 14(3), 1980), the original algorithm, written out here so that the search page needs no extra library.

WHAT IT IS FOR: the search page matches the words a person types against the words of a section. Without stemming "punishment" does not find a section that says "punished", nor "bribing" one that says "bribe". The stemmer cuts a
word to a stem (punishment, punished, punishable -> punish) and the index and the query are both cut the same way.

WHAT IT IS NOT: a dictionary. A stem is not always a word (ponies -> poni), and two words that the algorithm cuts to the same stem are not always related in meaning (the algorithm is blind to meaning). The search page uses the stem only to
decide that a section HOLDS a word in some usual form; the person reads the section and decides. Words with a digit in them (498A, 43D, 2023) are never changed, nor are words of one or two letters.

    stem("punishment") -> "punish"        stem("bribed") -> "bribe"        stem("498a") -> "498a"
"""

import functools
import re

_VOWELS = "aeiou"
_MAX_WORD = 40            # a longer run of letters is not a word; it is left as it is
_PLAIN = re.compile(r"[a-z]+")         # the only words that are cut: the rules above are written for lower-case a-z (a capital vowel would count as a consonant)


def _cons(w, i):
    """True when w[i] is a consonant: a letter other than a, e, i, o, u, and other than y after a consonant (Porter's definition)."""
    ch = w[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return True if i == 0 else not _cons(w, i - 1)
    return True


def _measure(stem):
    """Porter's m: how many times a run of vowels is followed by a run of consonants, [C](VC)^m[V]."""
    n, i, m = len(stem), 0, 0
    while i < n and _cons(stem, i):          # the optional leading consonants
        i += 1
    while i < n:
        while i < n and not _cons(stem, i):  # a run of vowels ...
            i += 1
        if i >= n:
            break
        m += 1                               # ... followed by a run of consonants: one VC
        while i < n and _cons(stem, i):
            i += 1
    return m


def _has_vowel(stem):
    return any(not _cons(stem, i) for i in range(len(stem)))


def _double_cons(w):
    return len(w) >= 2 and w[-1] == w[-2] and _cons(w, len(w) - 1)


def _cvc(w):
    """The stem ends consonant-vowel-consonant, the last consonant not w, x or y (Porter's *o)."""
    n = len(w)
    return n >= 3 and _cons(w, n - 1) and not _cons(w, n - 2) and _cons(w, n - 3) and w[-1] not in "wxy"


def _step1a(w):
    if w.endswith("sses"):
        return w[:-2]
    if w.endswith("ies"):
        return w[:-2]
    if w.endswith("ss"):
        return w
    if w.endswith("s"):
        return w[:-1]
    return w


def _step1b(w):
    if w.endswith("eed"):
        return w[:-1] if _measure(w[:-3]) > 0 else w
    for suffix in ("ed", "ing"):
        if w.endswith(suffix) and _has_vowel(w[:-len(suffix)]):
            w = w[:-len(suffix)]
            if w.endswith(("at", "bl", "iz")):
                return w + "e"
            if _double_cons(w) and w[-1] not in "lsz":
                return w[:-1]
            if _measure(w) == 1 and _cvc(w):
                return w + "e"
            return w
    return w


def _step1c(w):
    if w.endswith("y") and _has_vowel(w[:-1]):
        return w[:-1] + "i"
    return w


# (suffix, replacement); the rule with the longest matching suffix is the only one tried, and it applies only when the measure of what is left is over the step's limit (Porter 1980)
_STEP2 = (("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"),
          ("ization", "ize"), ("ation", "ate"), ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"))
_STEP3 = (("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", ""))
_STEP4 = ("al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize")


def _longest_first(rules):
    return sorted(rules, key=lambda r: -len(r[0]))


_STEP2 = _longest_first(_STEP2)
_STEP3 = _longest_first(_STEP3)
_STEP4 = sorted(_STEP4, key=lambda s: -len(s))


def _replace(w, rules, limit):
    for suffix, repl in rules:
        if w.endswith(suffix):
            stem = w[:-len(suffix)]
            return stem + repl if _measure(stem) > limit else w
    return w


def _step4(w):
    for suffix in _STEP4:
        if w.endswith(suffix):
            stem = w[:-len(suffix)]
            if suffix == "ion" and not stem.endswith(("s", "t")):
                return w
            return stem if _measure(stem) > 1 else w
    return w


def _step5(w):
    if w.endswith("e"):
        stem = w[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _cvc(stem)):
            w = stem
    if w.endswith("l") and _double_cons(w) and _measure(w[:-1]) > 1:
        w = w[:-1]
    return w


@functools.lru_cache(maxsize=65536)
def stem(word):
    """The Porter stem of a lower-case word. A word that is not only the letters a to z, or has one or two letters, or is absurdly long, comes back as it is."""
    if len(word) <= 2 or len(word) > _MAX_WORD or not _PLAIN.fullmatch(word):
        return word
    w = _step1c(_step1b(_step1a(word)))
    w = _replace(w, _STEP2, 0)
    w = _replace(w, _STEP3, 0)
    w = _step4(w)
    return _step5(w)


def stems(tokens):
    """The stems of a list of tokens, in order."""
    return [stem(t) for t in tokens]
