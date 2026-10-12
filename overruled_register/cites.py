"""Reporter citations of Supreme Court judgments, normalised to comparable keys.

    "(2010) 11 SCC 441"        -> scc:2010:11:441
    "AIR 1990 SC 1403"         -> air:1990:1403      (also "1990 AIR 1403" and the citator's "1990 SC 1403")
    "1992 Supp (1) SCC 335"     -> scc:1992:s1:335
    "[2019] 5 S.C.R. 569"      -> scr:2019:5:569     (old style "1966 SCR 209" -> scr:1966::209; "2001 Supp(1) SCR 598" -> scr:2001:s1:598)
    "2017 INSC 447"            -> insc:2017:447
    "(2015) 3 SCALE 28"        -> scale:2015:3:28
    "JT 1999 (6) SC 89"        -> jt:1999:6:89

High Court reports are not read; SCC OnLine numbers are kept only for the Supreme Court (sconline:2023:1308). A key identifies a reported page, so two different judgments printed on the same page
(AIR often does this) share a key; callers treat a key match as strong but not unique evidence.
"""
import re

def _roman(s):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50}
    total = 0
    for i, ch in enumerate(s.upper()):
        v = vals[ch]
        total += -v if i + 1 < len(s) and vals[s.upper()[i + 1]] > v else v
    return total


_Y = r"((?:19|20)\d\d)"
_SCR = r"S\.?\s*C\.?\s*R\.?"
_SUP = r"Supp?l?\.?"
_AIR = r"A\.?\s*I\.?\s*R\.?"

# (regex, key builder). Longer, more specific forms first; overlaps are resolved in find_cites (earliest, then longest, wins).
_PATTERNS = [
    # --- SCC
    (rf"\(\s*{_Y}\s*\)\s*(\d{{1,3}})\s*SCC\s*(\d{{1,4}})\b", lambda g: f"scc:{g[0]}:{g[1]}:{g[2]}"),                       # (2010) 11 SCC 441
    (rf"\b{_Y}\s*\(\s*(\d{{1,3}})\s*\)\s*SCC\s*(\d{{1,4}})\b", lambda g: f"scc:{g[0]}:{g[1]}:{g[2]}"),                       # 1996 (2) SCC 1
    (rf"\b{_Y}\s*SCC\s*\(\s*(\d{{1,3}})\s*\)\s*(\d{{1,4}})\b", lambda g: f"scc:{g[0]}:{g[1]}:{g[2]}"),                       # 1995 SCC (2) 560
    (rf"\(?\s*{_Y}\s*\)?\s*\(?\s*{_SUP}\s*\)?\s*\(?\s*(\d{{1,2}})\s*\)?\s*SCC\s*(\d{{1,4}})\b", lambda g: f"scc:{g[0]}:s{g[1]}:{g[2]}"),  # (1992) Supp 1 SCC 335; 1992 Supp (1) SCC 335
    (rf"\(\s*{_Y}\s*\)\s*(\d{{1,2}})\s*{_SUP}\s*SCC\s*(\d{{1,4}})\b", lambda g: f"scc:{g[0]}:s{g[1]}:{g[2]}"),                  # (1993) 4 Suppl. SCC 693
    (rf"\b{_Y}\s*SCC\s*{_SUP}\s*\(\s*(\d{{1,2}})\s*\)\s*(\d{{1,4}})\b", lambda g: f"scc:{g[0]}:s{g[1]}:{g[2]}"),                # 1995 SCC Supl. (3) 541
    (rf"\b{_Y}\s*\(\s*{_SUP}\s*\)\s*SCC\s*(\d{{1,4}})\b", lambda g: f"scc:{g[0]}:s:{g[1]}"),                                     # 1987 (Supp.) SCC 295
    (rf"\(\s*{_Y}\s*\)\s*(\d{{1,3}})\s*SCC\s*\(\s*Cri\s*\)\s*(\d{{1,4}})\b", lambda g: f"scccri:{g[0]}:{g[1]}:{g[2]}"),       # (1994) 3 SCC (Cri) 569
    (rf"\b{_Y}\s*SCC\s*\(\s*Cri\s*\)\s*(\d{{1,4}})\b", lambda g: f"scccri:{g[0]}::{g[1]}"),                                       # 1995 SCC (Cri) 1
    (rf"\(?\s*{_Y}\s*\)?\s*SCC\s*On\s*Line\s*SC\s*(\d{{1,6}})\b", lambda g: f"sconline:{g[0]}:{g[1]}"),                          # 2023 SCC OnLine SC 1308
    # --- AIR (Supreme Court only)
    (rf"\b{_AIR}\s*\(?\s*{_Y}\s*\)?\s*\(?\s*SC\s*\)?\s*(\d{{1,4}})\b", lambda g: f"air:{g[0]}:{g[1]}"),                         # AIR 1990 SC 1403; AIR (1968) SC 1012
    (rf"\b{_Y}\s*{_AIR}\s*(?:\(\s*SC\s*\)\s*|SC\s*)?(\d{{1,4}})\b", lambda g: f"air:{g[0]}:{g[1]}"),                              # 1990 AIR 1403
    (rf"\b{_Y}\s+SC\s*(\d{{1,4}})\b", lambda g: f"air:{g[0]}:{g[1]}"),                                                                # citator style: 1980 SC 898
    # --- SCR
    (rf"\[\s*{_Y}\s*\]\s*(\d{{1,3}})\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}:{g[1]}:{g[2]}"),                          # [2019] 5 S.C.R. 569
    (rf"\[\s*{_Y}\s*\]\s*(\d{{1,3}})\s*{_SUP}\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}:s{g[1]}:{g[2]}"),                # [1992] 1 Suppl. SCR 764
    (rf"\[\s*{_Y}\s*\]\s*{_SUP}\s*\(?\s*(\d{{1,2}})\s*\)?\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}:s{g[1]}:{g[2]}"),    # [2001] Supp (1) SCR 598
    (rf"\[\s*{_Y}\s*\]\s*{_SUP}\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}:s:{g[1]}"),                                      # [1976] Suppl. SCR 172
    (rf"\[\s*{_Y}\s*\]\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}::{g[1]}"),                                                  # [1953] S.C.R. 476 (the early reports have no volume)
    (rf"\(\s*{_Y}\s*\)\s*(\d{{1,3}})\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}:{g[1]}:{g[2]}"),                          # (1955) 1 SCR 1083
    (rf"\b{_Y}\s*\(\s*(\d{{1,3}})\s*\)\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}:{g[1]}:{g[2]}"),                        # 1964 (5) SCR 89
    (rf"\b{_Y}\s*{_SUP}\s*\(\s*(\d{{1,2}})\s*\)\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}:s{g[1]}:{g[2]}"),             # 2001 Supp(1) SCR 598
    (rf"\b{_Y}\s*{_SCR}\s*\(\s*(\d{{1,3}})\s*\)\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}:{g[1]}:{g[2]}"),                        # 1978 SCR (2) 621
    (rf"\b{_Y}\s*{_SCR}\s*(\d{{1,4}})\b", lambda g: f"scr:{g[0]}::{g[1]}"),                                                           # 1966 SCR 209
    # --- others
    (rf"\b{_Y}\s*\(\s*([IVXL]{{1,5}})\s*\)\s*SCALE\s*(\d{{1,4}})\b", lambda g: f"scale:{g[0]}:{_roman(g[1])}:{g[2]}"),                  # 2006(XI) SCALE 440
    (rf"\b{_Y}\s*SCALE\s*\(\s*(\d{{1,3}})\s*\)\s*(\d{{1,4}})\b", lambda g: f"scale:{g[0]}:{g[1]}:{g[2]}"),                       # 1996 SCALE (5) 267
    (rf"\b{_Y}\s*\(\s*(\d{{1,3}})\s*\)\s*SCALE\s*(\d{{1,4}})\b", lambda g: f"scale:{g[0]}:{g[1]}:{g[2]}"),                        # 2012 (4) SCALE 272
    (rf"\(\s*{_Y}\s*\)\s*(\d{{1,3}})\s*SCALE\s*(\d{{1,4}})\b", lambda g: f"scale:{g[0]}:{g[1]}:{g[2]}"),                           # (2015) 3 SCALE 28
    (rf"\bJT\s*\(?\s*{_Y}\s*\)?\s*\(\s*(?:Supp?l?\.?\s*)?(\d{{1,2}})\s*\)\s*(?:SC\s*)?(\d{{1,4}})\b", lambda g: f"jt:{g[0]}:{g[1]}:{g[2]}"),   # JT 1999 (6) SC 89; JT (2010) 12 SC 287
    (rf"\bJT\s*\(\s*{_Y}\s*\)\s*(\d{{1,2}})\s*SC\s*(\d{{1,4}})\b", lambda g: f"jt:{g[0]}:{g[1]}:{g[2]}"),                                # JT (2010) 12 SC 287
    (rf"\b{_Y}\s*\(\s*(\d{{1,2}})\s*\)\s*JT\s*(\d{{1,4}})\b", lambda g: f"jt:{g[0]}:{g[1]}:{g[2]}"),                               # 2021(10) JT 58
    (rf"\b{_Y}\s*INSC\s*(\d{{1,4}})\b", lambda g: f"insc:{g[0]}:{g[1]}"),                                                             # 2017 INSC 447
]
_COMPILED = [(re.compile(rx, re.I), build) for rx, build in _PATTERNS]


_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")      # stray control characters from the PDF text ("S.C.R. \x08 907"); not whitespace to \s, so they broke citations


def find_cites(text):
    """[(key, start, end)] for every reported citation in text, in order of appearance. Where two patterns overlap, the earlier start wins, then
    the longer match. Stray control characters are read as spaces (one for one, so positions do not move)."""
    text = _CONTROL.sub(" ", text)
    found = []
    for rx, build in _COMPILED:
        for m in rx.finditer(text):
            found.append((build(m.groups()), m.start(), m.end()))
    found.sort(key=lambda x: (x[1], -(x[2] - x[1])))
    out, last_end = [], -1
    for key, s, e in found:
        if s < last_end:
            continue
        out.append((key, s, e))
        last_end = e
    return out


def cite_keys(text):
    """The distinct keys in text, in order of first appearance."""
    seen, out = set(), []
    for key, _, _ in find_cites(text):
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def norm_cite(s):
    """The key of a single citation string, or None if none is recognised."""
    ks = cite_keys(s)
    return ks[0] if ks else None


def parse_key(key):
    """('scc', 2010, '11', 441) from 'scc:2010:11:441'."""
    parts = key.split(":")
    if parts[0] in ("air", "insc", "sconline"):
        return parts[0], int(parts[1]), "", int(parts[2])
    return parts[0], int(parts[1]), parts[2], int(parts[3])


def key_variants(key):
    """Keys that denote the same page. Old SCR headers print no volume ("1966 SCR 209") or only "Supp" where the bucket prints one ("[1966] 3 S.C.R. 209",
    "[1976] 1 Suppl. SCR 172"), so an SCR key with a volume also stands for the volume-less and unnumbered-supplement forms."""
    kind, year, series, page = parse_key(key)
    if kind == "scr" and series not in ("", "s"):
        return {key, f"scr:{year}::{page}", f"scr:{year}:s:{page}"}
    return {key}


def keys_match(a, b):
    """Equal keys, or the same SCR page where one side gives no volume (or only 'Supp') and the other a volume."""
    if a == b:
        return True
    ka, kb = parse_key(a), parse_key(b)
    return ka[0] == "scr" == kb[0] and ka[1] == kb[1] and ka[3] == kb[3] and bool({ka[2], kb[2]} & {"", "s"})
