"""
passage_window.py -- PASSAGE_WINDOW=on|off (default on; written 2026-11-09 on the owner's "Show the window around where the question's words are densest, snapped to sentence ends, with ... at both ends and a
skipped heading. This applies to both the page box and the model's text. Keep the head only when nothing matches. Do not show the unnecessary heading details in the response of the answers";
research repository FOLLOW_UPS item 2dz).

THE FAULT IT CLOSES (FOLLOW_UPS 2dy). A wider-search passage is a chunk of a judgment, up to a few thousand characters. The page showed its first 600 characters and the answer model its first 900, whatever
the question was. Papu Das (Gauhati High Court, 2024): the chunk opens with "BEFORE HONOURABLE MRS. JUSTICE ... ORDER ... Heard Mr. ..."; the sentences about giving a lift start at character 706, so the page showed
the heading and case numbers and stopped 127 characters before them.

WHAT IT DOES. window(text, question, limit) returns the stretch of the passage that the page or the model should read:
  1. a heading at the start (a court / bench / counsel / "PETITIONER: ... RESPONDENT: ..." / "ORDER dd.mm.yyyy" sentence, at most three of them, never all of the text) is skipped;
  2. the passage is cut into sentences (not after Mr., Dr., Vs., No., initials ...); of the windows that start at a sentence and run to about `limit` characters, the one holding the most DISTINCT words of the question
     is chosen (words are weighed: common legal words such as court, state, accused count a fifth); on a tie the earlier window wins;
  3. "... " is put in front when the window does not start at the beginning of the passage, " ..." behind when it does not reach the end; the words in between are the passage's own, copied exactly, nothing rewritten;
  4. when NO word of the question is in the passage, or the head already holds as many as any window, the head is shown (after the skipped heading), as before.
It never raises: on any failure the old cut (sci_search_tier._cut) is used. PASSAGE_WINDOW=off gives the old cut everywhere.
"""
import os
import re

HEAD_START = re.compile(r"^\W*(?:BEFORE\b|IN THE (?:SUPREME|HIGH) COURT|IN THE COURT OF|PETITIONER\s*:|APPELLANT\s*:|RESPONDENT\s*:|REPORTABLE|NON-?\s*REPORTABLE|CRIMINAL (?:APPELLATE|ORIGINAL|REVISIONAL) JURISDICTION|"
                        r"CIVIL APPELLATE|Page No\.?\s*#|THE GAUHATI HIGH COURT|GAUHATI HIGH COURT|HIGH COURT OF|JUDGMENT AND ORDER|JUDGMENT\s*&\s*ORDER|JUDGMENT\b|ORDER\b|CAV\b|PRESENT\s*:|CORAM\s*:|"
                        r"HON['’]?BLE|HONOURABLE|HONORABLE|Heard\b|Case No\.?\s*:|BENCH\s*:|DATE OF JUDGMENT|Dated\s*:|Date of order)", re.I)
_ABBR = re.compile(r"(?:(?<![A-Za-z])(?:Mr|Mrs|Ms|Messrs|Dr|Sri|Shri|Smt|Smti|Hon|Vs|v|No|Nos|Co|Ltd|Pvt|St|Jr|Sr|Cr|Crl|Art|Arts|Sec|Secs|Ss|Cl|Addl|Dy|Govt|Rs|etc|viz|Prof|Adv|Md|Mst|Kum|Ors|Anr|Dist|J|JJ|CJ|Ex|Sh|Cri|Pw|Pws|Dw|Dws)|(?<![A-Za-z])[A-Za-z])\.$", re.I)
_BOUND = re.compile(r"([.?!][\"')\]”’]?)(\s+)(?=[A-Z0-9\"“(\[‘'])")
STOP = frozenset("""the and with from that this these those what which when where whom whose have has had having been were was are will would could should shall might must can cannot does did doing done not nor
but for into onto over under after before about against between during through than then there here their them they our your yours his her hers its who why how also only just very more most such some other any each every
both either neither whether however though although because since until while once again further""".split())
COMMON = frozenset("court courts state case cases section sections order orders accused petitioner petitioners appeal appellant appellants respondent respondents police law legal judgment person persons offence offences held".split())


def enabled():
    return (os.environ.get("PASSAGE_WINDOW") or "on").strip().strip("\"'").strip().lower() not in ("off", "0", "false", "no")


def _norm(text):
    return re.sub(r"[ \t]+", " ", text or "").strip()


def _terms(question):
    """[(compiled regex, weight)] for the distinct content words of the question (a word is matched by its first five letters, as a stem)."""
    seen, out = set(), []
    for w in re.findall(r"[a-z]{4,}", (question or "").lower()):
        if w in STOP:
            continue
        key = w[:5]
        if key in seen:
            continue
        seen.add(key)
        out.append((re.compile(r"\b" + re.escape(key)), 0.2 if w in COMMON else 1.0))
    return out


def _sentences(t):
    """[(start, end)] spans covering t, split after . ? ! when the next word starts a sentence and the word before the stop is not an abbreviation or an initial."""
    spans, start = [], 0
    for m in _BOUND.finditer(t):
        before = t[max(0, m.start(1) - 14):m.start(1) + 1]
        if m.group(1)[0] == "." and _ABBR.search(before):
            continue
        spans.append((start, m.end(1)))
        start = m.end(2)
    spans.append((start, len(t)))
    return [(a, b) for a, b in spans if b > a]


def _is_heading(s):
    s = s.strip()
    if HEAD_START.match(s):
        return True
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 25 and sum(1 for c in letters if c.isupper()) / len(letters) >= 0.7


def _score(chunk, terms):
    s, hits = 0.0, 0
    for rx, w in terms:
        n = len(rx.findall(chunk))
        if n:
            s += w
            hits += min(n, 5)
    return s + 0.01 * hits


def _fit(t, a, limit, spans, k):
    """End position of the window that starts at sentence k (start a): whole sentences while they fit in `limit`; a first sentence longer than that is cut at a word."""
    end = spans[k][1]
    if end - a > limit:
        cut = t.rfind(" ", a, a + limit)
        return (cut if cut > a + limit * 0.5 else a + limit), True
    j = k + 1
    while j < len(spans) and spans[j][1] - a <= limit:
        end = spans[j][1]
        j += 1
    return end, False


def window(text, question, limit):
    """-> (shown text, {'moved': bool, 'heading': bool}). Never raises."""
    t = _norm(text)
    if not t:
        return "", {"moved": False, "heading": False}
    try:
        spans = _sentences(t)
        h = 0
        while h < len(spans) - 1 and h < 3 and _is_heading(t[spans[h][0]:spans[h][1]]):
            h += 1
        if h and len(t) - spans[h][0] < 80:
            h = 0                                                   # skipping the heading would leave almost nothing
        terms = _terms(question)
        a0 = spans[h][0]
        best_k, best = h, -1.0
        if terms:
            head_end, _ = _fit(t, a0, limit, spans, h)
            head_score = _score(t[a0:head_end], terms)
            best = head_score
            for k in range(h + 1, len(spans)):
                a = spans[k][0]
                end, _ = _fit(t, a, limit, spans, k)
                sc = _score(t[a:end], terms)
                if sc > best + 1e-9:
                    best, best_k = sc, k
            if best <= 0:
                best_k = h
        k = best_k
        a = spans[k][0]
        end, _hard = _fit(t, a, limit, spans, k)
        body = t[a:end].rstrip()
        out = ("... " if k > h else "") + body + (" ..." if end < len(t) else "")
        return out, {"moved": k > h, "heading": h > 0}
    except Exception:  # noqa: BLE001 -- never lets a failure here touch an answer
        return "", {"moved": False, "heading": False, "error": True}
