"""section_checks.py -- two checks on a finished answer, by code (SECTION_CHECKS = off | log | warn; default follows GROUNDING_CHECKS: log or warn; added 2026-11-12 after a staging answer about the Motor Vehicles Act).

  1. SECTION GLOSS. A sentence that attributes something to ONE section ("Section 182(1) penalises a person who ... obtains a licence by fraud or misrepresentation") is checked against that section's own text. A word of the
     sentence that the section does not contain, but another statute section among the material does, was probably borrowed from that other section ('fraud or misrepresentation' is in section 19(1)(e), not in section 182).
     Only such BORROWED words are reported: a paraphrase ('penalises' for 'punishable') appears nowhere in the material and is left alone, a word from the person's own question is left alone, and a word that is common in the
     statutes (more than 4% of the sections of the shelf and the library's Acts that we hold) is left alone. A sentence that names two different sections is not checked, and so is one that does not begin "Section N (of the Act) <verb>" (a sentence about a case, a risk or a ground names a section and says other things). The check says that the word is not in the section; it does not say the answer is wrong.
  2. ARGUMENT FROM ABSENCE. A sentence outside 'Gaps and checks' that reasons from what the material does not contain ("no section in the material penalises X, so X should not be treated as an offence"). The material is what
     the search brought, not the whole law; absence from it is a gap to report, never an argument (the prompt says so since 2026-11-12; this finds the sentence that does it anyway).
Both are pure functions with no model and no network. Both swallow their own errors. A notice only withdraws trust; it never says what the law is.
"""
import json
import os
import re

import grounding_checks

_WORD = re.compile(r"[a-z]{5,}")                 # a word of the answer that may be reported
_WORD4 = re.compile(r"[a-z]{4,}")                # the words of a section it is compared with (a shorter limit, so 'cease' in the section matches 'ceases' in the answer)
_SEC = re.compile(r"\b(?:sections?|sec\.|ss?\.)\s*(\d{1,3}[A-Z]{0,2})(?:\s*\(\s*\w+\s*\))*", re.I)
_DESCRIBES = re.compile(r"^\W*(?:under\s+)?(?:sections?|sec\.|ss?\.)\s*\d{1,3}[A-Za-z]{0,2}(?:\s*\(\s*\w+\s*\))*(?:\s+(?:of|in)\s+(?:the\s+)?[A-Z][\w ,.'()-]{2,80}?)?\s*,?\s+(?:also\s+|further\s+|itself\s+)?(?:penalis|punish|provid|requir|allow|permit|let|state|say|make|bar|appl|cover|defin|impos|empower|prohibit|criminalis|prescrib|authoris|enabl|entitl|oblig|direct|declar|creat|treat|mak|set|lay|give|grant|restrict|exempt|exclud|includ|extend|specif)\w*\b", re.I)    # the sentence begins "Section N (of the Act) <verb>": it says what the section itself says
_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z0-9\"“(\[])|\n+")
COMMON_DF = 0.04
_DISCOURSE = frozenset("support show shown indic appli appear cover requir provid state includ contain establish prove allow permit specifi describ refer relat depend consid determin ground applic mention follow impos result cause arise concern appli cite name make give take list note say mean hold held bring caus remain".split())    # stems of the words an answer is written WITH ("supports", "shown", "applies"): never a sign of a borrowed concept
MIN_BORROWED = 2                  # a sentence is reported only when TWO or more of its words come from the same other section ('fraud' and 'misrepresentation' from section 19(1)(e)): one borrowed word is as often a paraphrase
_DF = {}


def mode():
    v = (os.environ.get("SECTION_CHECKS") or "").strip().strip("\"'").strip().lower()
    if v in ("off", "log", "warn"):
        return v
    return "warn" if grounding_checks.mode() in ("warn", "enforce") else ("off" if grounding_checks.mode() == "off" else "log")


def _stem(w):
    try:
        import search_stem
        return search_stem.stem(w)
    except Exception:  # noqa: BLE001
        return re.sub(r"(ing|ed|es|s)$", "", w)


def _words(text):
    return {_stem(w) for w in _WORD4.findall((text or "").lower())}


def _df_table():
    """{stem: share of the shelf's sections whose text has it}; built once from act_shelf/*.json (cheap: 1,253 sections)."""
    if _DF:
        return _DF
    try:
        import glob
        here = os.path.dirname(os.path.abspath(__file__))
        n, counts = 0, {}
        for f in glob.glob(os.path.join(here, "act_shelf", "*.json")):
            try:
                data = json.load(open(f, encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(data, list) or not data or not isinstance(data[0], dict) or "section_number" not in data[0]:
                continue
            for c in data:
                if c.get("omitted"):
                    continue
                n += 1
                for w in _words(c.get("text")):
                    counts[w] = counts.get(w, 0) + 1
        _DF.update({w: c / max(n, 1) for w, c in counts.items()})
        _DF["__n__"] = n
    except Exception:  # noqa: BLE001
        pass
    return _DF


def _act_names(m):
    names = {str(m.get("act") or "").lower(), str(m.get("act_display") or "").lower(), str(m.get("act_key") or "").lower().replace("_", " ")}
    d = str(m.get("act_display") or "")
    if d:
        names.add(re.sub(r",?\s*\d{4}$", "", d).lower())
    return {n for n in names if n}


def _resolve(sentence, num, statutes):
    """The material's section `num` that the sentence means: the one whose Act the sentence names; else the only one; None when it is ambiguous."""
    base = re.sub(r"[A-Z]*$", lambda m: m.group(0), num).upper()
    cands = [m for m in statutes if str(m.get("section_number") or "").upper().split("(")[0] == base]
    if not cands:
        return None
    low = sentence.lower()
    named = [m for m in cands if any(n and n in low for n in _act_names(m))]
    if len(named) == 1:
        return named[0]
    return cands[0] if len(cands) == 1 and not named else None


_CLASSIFICATION_SENT = re.compile(r"\bPart\s+II\b|\bFirst\s+Schedule\b|\bclassif(?:ied|ication|ies)\b|\bSchedule\b", re.I)    # a sentence that says how the Schedule classifies an offence describes the Schedule, not the section
_CASE_CUT = re.compile(r"\s*(?:;|[,]\s+(?:and\s+|while\s+|but\s+)?(?:the\s+)?(?:Supreme\s+Court|High\s+Court)\b|\s+—\s+|\s+\(\s*(?:para|paras|paragraph)\b)", re.I)    # a ';', a dash, or ", the Supreme Court ..." : the sentence turns to a case


def clause_about_section(sent):
    """The part of a sentence that says what the SECTION says: up to the first ';' and before the place where the sentence turns to a court or a case ("Section 47 requires X; the Supreme Court in Prabir held that grounds must be furnished" is two statements)."""
    m = _CASE_CUT.search(sent or "")
    return (sent[:m.start()] if m else (sent or "")).strip()


def classification_text(material):
    """The code-built classification blocks inside the answer model's material (Part II lines, the First Schedule's rows): the words the answer takes from them are not borrowed from another section."""
    try:
        parts = re.findall(r"\n## Classification of [^\n]*\n.*?(?=\n\n## |\Z)", material or "", flags=re.S)
        return "\n".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def section_gloss(answer, matches, question="", extra=""):
    """[{'act', 'section', 'words': [...], 'sentence'}] for the sentences that attribute a word to a section whose text lacks it while another section of the material has it. [] when none (the usual case). `extra`: text the program itself
    put in the material (classification_text), whose words are treated like the person's own."""
    try:
        statutes = [m for m in matches or [] if isinstance(m, dict) and m.get("type") in (None, "statute") and not m.get("case_name") and m.get("text") and m.get("section_number") not in (None, "")]
        if not statutes or not answer:
            return []
        df = _df_table()
        qwords = _words(question) | _words(extra)
        body = re.split(r"\*\*\s*Gaps and checks\s*\*\*", answer, maxsplit=1)[0]
        out, seen = [], set()
        for sent in _SPLIT.split(body):
            if _CLASSIFICATION_SENT.search(sent):
                continue
            sent = clause_about_section(sent)
            nums = {re.sub(r"\s+", "", n).upper() for n in _SEC.findall(sent)}
            if len(nums) != 1 or not _DESCRIBES.match(sent.strip()):
                continue
            num = next(iter(nums))
            target = _resolve(sent, num, statutes)
            if target is None:
                continue
            ttext = _words((target.get("title") or "") + " " + target["text"])
            others = {}
            for m in statutes:
                if m is target or (m.get("act"), m.get("section_number")) == (target.get("act"), target.get("section_number")):
                    continue
                for w in _words(m["text"]):
                    others.setdefault(w, f"{m.get('act')} {m.get('section_number')}")
            groups = {}
            for raw in _WORD.findall(sent.lower()):
                st = _stem(raw)
                if st in ttext or st in qwords or st in _DISCOURSE or st not in others or df.get(st, 0) > COMMON_DF:
                    continue
                if raw not in groups.setdefault(others[st], []):
                    groups[others[st]].append(raw)
            for src, ws in groups.items():
                if len(ws) >= MIN_BORROWED:
                    key = (target.get("act"), target.get("section"), tuple(ws))
                    if key not in seen:
                        seen.add(key)
                        out.append({"act": target.get("act"), "section": str(target.get("section_number")), "words": ws[:4], "borrowed_from": [src], "sentence": sent.strip()[:240]})
        return out
    except Exception:  # noqa: BLE001
        return []


_ABSENT = re.compile(r"\b(?:no|not|nothing|neither)\b[^.;]{0,140}?\b(?:in the material|shown in the material|before me|the material (?:does not|doesn't) (?:show|contain|include|hold)|not (?:shown|included) in the material)\b|\bthe material (?:does not|doesn't) (?:show|contain|include|hold)\b[^.;]{0,140}", re.I)
_CONCLUDE = re.compile(r"(?:,|;)\s*so\b|\btherefore\b|\bhence\b|\bshould not be\b|\bcannot be (?:treated|charged|pressed|said)\b|\bis not an offence\b|\bno offence\b|\bdoes not (?:apply|arise)\b|\bshould not apply\b", re.I)


_REPORTS_GAP = re.compile(r"\bcannot be (?:stated|determined|verified|fixed|assessed|said|confirmed)\b|\bcan(?:not|'t) (?:state|say|determine|verify)\b|\b(?:be|been|is) stated\b", re.I)    # a sentence that says what it cannot state is reporting the gap


def absence_arguments(answer):
    """[sentence, ...] before 'Gaps and checks' that reason from what the material does not contain. A sentence that only reports the gap ('The material does not show X') has no conclusion word and is left alone."""
    try:
        body = re.split(r"\*\*\s*Gaps and checks\s*\*\*", answer or "", maxsplit=1)[0]
        out = []
        for sent in _SPLIT.split(body):
            if _ABSENT.search(sent) and _CONCLUDE.search(sent) and not _REPORTS_GAP.search(sent) and len(sent.split()) >= 8:
                out.append(sent.strip()[:300])
        return out
    except Exception:  # noqa: BLE001
        return []


def notices(gloss, absent):
    out = []
    for g in gloss:
        words = ", ".join(f"“{w}”" for w in g["words"])
        out.append(f"This answer describes section {g['section']} ({g['act']}) in words ({words}) that are not in that section's text; they appear in {', '.join(g['borrowed_from'])}. Please read section {g['section']} itself before relying on that description.")
    if absent:
        out.append("A sentence in this answer reasons from what our sources do not contain. The sources are what the search brought, not the whole law: the absence of a provision from them does not show that none exists. Check the full Act before relying on that point.")
    return out


def log_line(question_hash, gloss, absent):
    print("SECTION_CHECKS " + json.dumps({"q": question_hash, "gloss": [{k: g[k] for k in ("act", "section", "words", "borrowed_from")} for g in gloss], "absence_sentences": len(absent)}), flush=True)
