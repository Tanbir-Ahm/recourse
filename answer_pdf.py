"""
answer_pdf.py -- "download this answer as a PDF".

WHY (2026-09-28): the DRAFT petition is one document for one situation. A person also wants the ANSWER itself -- what they
asked, what Recourse said, which laws and judgments it rested on -- as a file they can keep or show a lawyer, and, when
they asked several things, all of it in one document.

HOW IT WORKS
  1. When an answer is produced, a small RECORD of it is saved (record_from_result): the person's own words, the answer
     text exactly as generated, the statute sections and judgments the answer TEXT actually names (with the stored
     official text and the real links), and the hedged "other cases" list.
  2. build_answer_pdf turns one or several records into a PDF. No AI call, no network: the PDF is exactly what the
     person saw, it costs nothing, and it is instant.
  3. verify_pdf_completeness reads the finished PDF's text back and proves every paragraph of every answer is inside it.
     build_verified_pdf builds, verifies, and falls back to a plain layout if the check fails.

A "facts to bring to a lawyer" checklist is built ONLY from the answer's own "what's unclear" line (unclear_checklist) --
phrases already in the answer, never invented. If the answer had no such line, there is no checklist.

Pure Python + reportlab (+ PyMuPDF for the self-check, both already in requirements.txt). The bundled DejaVu Sans fonts
(fonts/, free licence) print rupee signs, arrows, curly quotes and so on that the default PDF font cannot.
"""
import datetime
import io
import logging
import os
import re
import secrets
import time
from xml.sax.saxutils import escape

logger = logging.getLogger("answer_pdf")

ANSWER_STATES = ("single_match", "conflicting_matches")
MAX_RECORDS = 10          # a conversation PDF shows the newest 10 answers
MAX_EXCERPTS = 2          # judgment excerpts per case
EXCERPT_CHARS = 1300
STATUTE_CHARS = 4000
# The line WhatsApp shows above a conflicting_matches answer (whatsapp_formatter.format_answer_for_whatsapp).
CONFLICT_OPENER = ("More than one legal provision applies here, and they don't all say the same thing -- "
                   "here's each one, rather than picking one for you:")
DISCLAIMER = ("Recourse gives general legal information to help you understand your situation. It is not legal advice "
              "and it is not a court document. Please show it to a lawyer, or to your nearest District Legal Services "
              "Authority (free legal aid), before you act on it.")

_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

_ACT_TOKENS = [
    ("BNSS", re.compile(r"\bBNSS\b|Bharatiya Nagarik Suraksha Sanhita", re.I)),
    ("BNS", re.compile(r"\bBNS\b|Bharatiya Nyaya Sanhita", re.I)),
    ("ITACT", re.compile(r"\bIT Act\b|Information Technology Act", re.I)),
    ("NIACT", re.compile(r"\bNI Act\b|Negotiable Instruments Act", re.I)),
]
_ACT_SHORT = {"BNS": "BNS", "BNSS": "BNSS", "ITACT": "IT Act", "NIACT": "NI Act"}
_ACT_LONG = {"BNS": "Bharatiya Nyaya Sanhita, 2023", "BNSS": "Bharatiya Nagarik Suraksha Sanhita, 2023",
             "ITACT": "Information Technology Act, 2000", "NIACT": "Negotiable Instruments Act, 1881"}


# ---------------------------------------------------------------------------------------------------------------------
# small text helpers
# ---------------------------------------------------------------------------------------------------------------------
def _strip_md(s: str) -> str:
    return re.sub(r"\*+", "", s or "")


def _norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


def _paragraphs(text: str) -> list:
    return [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _base(section) -> str:
    return str(section or "").split("(")[0].strip()


def _cap(s: str, n: int, marker: str) -> tuple:
    s = s or ""
    return (s, False) if len(s) <= n else (s[:n].rstrip() + marker, True)


# ---------------------------------------------------------------------------------------------------------------------
# 1. the "what's unclear" checklist
# ---------------------------------------------------------------------------------------------------------------------
# The answer-writing prompt asks the model to say "what key facts are still unclear"; it words that line in several ways,
# so a number of phrasings are recognised. "What's CLEAR" is deliberately NOT one of them (it means the opposite).
_UNCLEAR_PAT = re.compile(
    r"(?:what(?:'s|’s| is| remains)\s+(?:still\s+|yet\s+)?(?:unclear|unknown|missing)"
    r"|what\s+(?:isn['’]t|is not)\s+(?:yet\s+|still\s+)?clear"
    r"|(?:key |important |the )?facts?\s+(?:that\s+)?(?:are\s+|remain\s+)?(?:still\s+)?(?:unclear|unknown|missing)"
    r"|what\s+(?:i|we)(?:\s+still)?\s+(?:don['’]t|do not)\s+know"
    r"|what\s+(?:i|we)(?:['’]d|\s+would)\s+need\s+to\s+know)"
    r"(?:\s+(?:here|yet))?",
    re.I)
_BULLET_LINE = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s+(.*\S)\s*$")
_LEAD_PAT = re.compile(r"\b(?:depends? on facts like|depends? on|facts like|such as|including)\s+", re.I)
_DOC_PAT = re.compile(
    r"\bif you (?:have|can get|receive|received|got|were given|are given)\s+((?:the |a |an |your |any )?[^,.]{2,140}?),?\s+you can upload",
    re.I)


def _split_top_level(s: str) -> list:
    """Split on commas / semicolons / ' and whether' that are NOT inside brackets."""
    out, depth, cur = [], 0, []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if depth == 0 and ch in ",;":
            out.append("".join(cur))
            cur = []
        elif depth == 0 and re.match(r"\s+and\s+(?=whether\b)", s[i:], re.I):
            out.append("".join(cur))
            cur = []
            i += re.match(r"\s+and\s+", s[i:], re.I).end()
            continue
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def unclear_checklist(response_text: str) -> dict:
    """{'items': [...], 'documents': [...], 'from_answer': str} built ONLY from phrases already in the answer.
    items: the things the answer's own "What's unclear" line says it needs to know. documents: from its own
    "If you have X, you can upload it" line. from_answer: when the line could not be split safely, the answer's own
    sentence, quoted -- never guessed items."""
    empty = {"items": [], "documents": [], "from_answer": ""}
    try:
        text = _strip_md(response_text or "")
        docs = []
        dm = _DOC_PAT.search(text)
        if dm:
            d = re.sub(r"\s+", " ", dm.group(1)).strip()
            docs = [d[0].upper() + d[1:]] if d else []
        m = _UNCLEAR_PAT.search(text)
        if not m:
            return {**empty, "documents": docs}
        after = text[m.end():]
        # the "what's unclear" part written as a bullet list ("What's unclear:\n- a\n- b")
        block = re.match(r"[ :\t]*\n+(?P<b>(?:[ \t]*(?:[-•*]|\d+[.)])[ \t]+[^\n]+\n?)+)", after)
        if block:
            bl = [_BULLET_LINE.match(ln).group(1).strip(" .") for ln in block.group("b").split("\n") if _BULLET_LINE.match(ln)]
            bl = [b[0].upper() + b[1:] for b in bl if b]
            if 1 <= len(bl) <= 8 and all(3 <= len(b) <= 220 for b in bl):
                return {"items": bl, "documents": docs, "from_answer": ""}
        rest = after.lstrip(" :\n\t-–—")
        rest = re.split(r"\n\s*\n", rest, maxsplit=1)[0]
        rest = re.sub(r"\s+", " ", rest).strip()
        rest = re.sub(r"^(?:is|are)\s+", "", rest, flags=re.I)
        rest = re.split(r"\s+[—–]\s+|\s+--\s+", rest, maxsplit=1)[0]
        rest = re.split(r"(?<=[.?!])\s+(?=[A-Z])", rest, maxsplit=1)[0].strip().rstrip(".")
        if not rest:
            return {**empty, "documents": docs}
        sentence = rest
        core = rest
        lead = _LEAD_PAT.search(rest)
        if lead and "," not in rest[:lead.start()]:
            core = rest[lead.end():]
        items = []
        for part in _split_top_level(core):
            part = re.sub(r"^(?:and|or)\s+", "", part.strip(), flags=re.I).strip(" .")
            if part:
                items.append(part[0].upper() + part[1:])
        if not (1 <= len(items) <= 8) or any(len(i) < 3 or len(i) > 220 for i in items):
            return {"items": [], "documents": docs, "from_answer": sentence}
        return {"items": items, "documents": docs, "from_answer": ""}
    except Exception:
        return empty


# ---------------------------------------------------------------------------------------------------------------------
# 2. the record
# ---------------------------------------------------------------------------------------------------------------------
_SEC_HEAD = r"\b(?:sections?|secs?\.?)\s+(?:\d+[a-z]?(?:\(\w+\))*\s*(?:,|and|&|or|to|-|–)\s*)*"


def _statute_hits(text: str, num: str) -> list:
    """For each place the answer names section `num`, the act named right after it (or None)."""
    hits = []
    for m in re.finditer(_SEC_HEAD + re.escape(num) + r"(?!\d)", text or "", re.I):
        tail = text[m.end(): m.end() + 70]
        tail = re.sub(r"^(?:\s*\([^)]*\))*", "", tail)
        found = None
        for act, pat in _ACT_TOKENS:
            hm = pat.search(tail)
            if hm and (found is None or hm.start() < found[1]):
                found = (act, hm.start())
        hits.append(found[0] if found else None)
    return hits


def _statutes_named(text: str, matches: list) -> list:
    stat = [m for m in matches if isinstance(m, dict) and m.get("type") == "statute" and m.get("section_number") and m.get("act")]
    acts_for_num = {}
    for m in stat:
        acts_for_num.setdefault(_base(m["section_number"]), set()).add(str(m["act"]).upper())
    out, seen = [], set()
    for m in stat:
        act, num = str(m["act"]).upper(), _base(m["section_number"])
        if (act, num) in seen:
            continue
        hits = _statute_hits(text, num)
        ok = any(h == act for h in hits) or (any(h is None for h in hits) and len(acts_for_num[num]) == 1)
        if not ok:
            continue
        seen.add((act, num))
        body, truncated = _cap(m.get("text") or "", STATUTE_CHARS, " [the section continues in the Act]")
        cls = []
        for key in sorted((m.get("all_variants") or {}), key=lambda k: (len(k), k)):
            v = m["all_variants"][key] or {}
            cls.append({"label": key, "cognizable": v.get("cognizable"), "bailable": v.get("bailable"),
                        "max_years": v.get("max_years"), "life_or_death": bool(v.get("life_or_death"))})
        out.append({"act": act, "section_number": num, "text": body, "truncated": truncated, "classification": cls})
    return out


def _excerpt_label(pn) -> str:
    s = str(pn or "").strip()
    return f"paragraph {s}" if s.isdigit() else "excerpt"


def record_from_result(question: str, result, *, created_at=None, answer_id=None):
    """The saved record of one answer, or None when there is nothing to put in a PDF (not an answer state, or no text).
    JSON-serialisable. Never raises."""
    try:
        if not isinstance(result, dict) or result.get("state") not in ANSWER_STATES:
            return None
        text = result.get("response_text")
        if not isinstance(text, str) or not text.strip():
            return None
        matches = [m for m in (result.get("matches") or []) if isinstance(m, dict)]
        judgments = []
        for link in result.get("cited_judgment_links") or []:
            if not isinstance(link, dict) or not link.get("url"):
                continue
            excerpts, seen = [], set()
            for m in matches:
                if m.get("type") == "judgment" and m.get("case_name") == link.get("case_name") and m.get("text"):
                    key = _norm(m["text"])[:200]
                    if key in seen:
                        continue
                    seen.add(key)
                    body, _ = _cap(m["text"].strip(), EXCERPT_CHARS, " ...")
                    excerpts.append({"label": _excerpt_label(m.get("paragraph_number")), "text": body})
                    if len(excerpts) >= MAX_EXCERPTS:
                        break
            judgments.append({"case_name": link.get("case_name"), "url": link["url"],
                              "source_label": link.get("source_label") or "source link", "excerpts": excerpts})
        others = []
        for j in result.get("unverified_related_judgments") or []:
            if isinstance(j, dict) and j.get("case_name"):
                pn = str(j.get("paragraph_number") or "").strip()
                others.append({"case_name": j["case_name"], "url": j.get("ik_search_url"),
                               "paragraph_number": pn if pn.isdigit() else None,
                               "procedural_disposal": bool(j.get("procedural_disposal"))})
        return {
            "answer_id": answer_id or ("RA-" + secrets.token_hex(3).upper()),
            "created_at": float(created_at if created_at is not None else time.time()),
            "question": (question or "").strip(),
            "state": result["state"],
            "response_text": text,
            "conflict_note": result["state"] == "conflicting_matches",
            "statutes": _statutes_named(text, matches),
            "judgments": judgments,
            "other_cases": others,
        }
    except Exception:
        logger.exception("record_from_result failed")
        return None


# ---------------------------------------------------------------------------------------------------------------------
# 3. the PDF
# ---------------------------------------------------------------------------------------------------------------------
_fonts_ready = {"done": False, "ok": False}


def _register_fonts() -> bool:
    if _fonts_ready["done"]:
        return _fonts_ready["ok"]
    _fonts_ready["done"] = True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        for name, fname in (("DejaVu", "DejaVuSans.ttf"), ("DejaVu-Bold", "DejaVuSans-Bold.ttf"),
                            ("DejaVu-Italic", "DejaVuSans-Oblique.ttf"), ("DejaVu-BoldItalic", "DejaVuSans-BoldOblique.ttf")):
            pdfmetrics.registerFont(TTFont(name, os.path.join(_FONT_DIR, fname)))
        pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu-Italic", boldItalic="DejaVu-BoldItalic")
        _fonts_ready["ok"] = True
    except Exception:
        logger.exception("could not register the bundled fonts; falling back to Helvetica")
    return _fonts_ready["ok"]


def _md_inline(s: str) -> str:
    s = escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<i>\1</i>", s)
    return s.replace("*", "")


def _fmt_time(ts) -> str:
    return datetime.datetime.fromtimestamp(ts, tz=_IST).strftime("%d %b %Y, %H:%M IST")


def _yn(v, yes, no):
    return yes if v is True else no if v is False else "not stated"


def _years(c) -> str:
    if c.get("life_or_death"):
        return "life imprisonment or death"
    y = c.get("max_years")
    return f"up to {y} years" if y else "not stated"


def build_answer_pdf(records: list, plain: bool = False) -> bytes:
    """One PDF for one or several saved records (oldest first). plain=True is the no-frills layout used as a fallback."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    if not records:
        raise ValueError("no records")
    total_n = len(records)
    records = list(records)[-MAX_RECORDS:]
    multi = len(records) > 1
    fonts_ok = _register_fonts()
    base, bold, ital = ("DejaVu", "DejaVu-Bold", "DejaVu-Italic") if fonts_ok else ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique")
    INK, MUTED, ACCENT, PALE = colors.HexColor("#1B2430"), colors.HexColor("#5B6675"), colors.HexColor("#1F4E8C"), colors.HexColor("#F3F5F8")

    def S(name, **kw):
        d = dict(fontName=base, fontSize=10, leading=14.5, textColor=INK, alignment=TA_LEFT, spaceAfter=5)
        d.update(kw)
        return ParagraphStyle(name, **d)

    st = {
        "title": S("title", fontName=bold, fontSize=17, leading=22, spaceAfter=3),
        "meta": S("meta", fontSize=8.5, leading=12, textColor=MUTED, spaceAfter=8),
        "h2": S("h2", fontName=bold, fontSize=12, leading=16, textColor=ACCENT, spaceBefore=12, spaceAfter=4, keepWithNext=1),
        "h3": S("h3", fontName=bold, fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=2, keepWithNext=1),
        "body": S("body"),
        "bullet": S("bullet", leftIndent=14, bulletIndent=3, spaceAfter=3),
        "q": S("q", fontSize=10.5, leading=15, backColor=PALE, borderPadding=(6, 6, 6, 6), spaceBefore=4, spaceAfter=10),
        "note": S("note", fontName=ital, textColor=MUTED, fontSize=9.5),
        "small": S("small", fontSize=8.5, leading=12, textColor=MUTED),
        "src": S("src", fontSize=8.5, leading=12, backColor=PALE, borderPadding=(5, 5, 5, 5), spaceAfter=8),
        "url": S("url", fontSize=8.5, leading=12, textColor=ACCENT, wordWrap="CJK"),
        "check": S("check", leftIndent=16, firstLineIndent=-16, spaceAfter=3),
        "lines": S("lines", fontSize=10, leading=22),
    }

    def P(text, style="body", raw=False):
        return Paragraph(text if raw else escape(text), st[style])

    def answer_flowables(text):
        out = []
        for para in _paragraphs(text):
            if plain:
                out.append(P(_strip_md(para).replace("\n", " "), "body"))
                continue
            buf = []

            def flush():
                if buf:
                    out.append(Paragraph("<br/>".join(_md_inline(b) for b in buf), st["body"]))
                    buf.clear()

            for line in para.split("\n"):
                mm_ = re.match(r"^\s*[-•]\s+(.*)$", line)
                if mm_:
                    flush()
                    out.append(Paragraph(_md_inline(mm_.group(1)), st["bullet"], bulletText="•"))
                else:
                    buf.append(line)
            flush()
        return out

    def statute_flowables(s, used_in=None):
        head = f"Section {s['section_number']} of the {_ACT_SHORT.get(s['act'], s['act'])}"
        out = [P(head + (f" — {_ACT_LONG[s['act']]}" if s["act"] in _ACT_LONG else ""), "h3")]
        if used_in:
            out.append(P(used_in, "small"))
        if s.get("classification"):
            rows = [["Provision", "Cognizable?", "Bail", "Maximum punishment"]]
            for c in s["classification"]:
                rows.append([c["label"], _yn(c["cognizable"], "Cognizable", "Non-cognizable"),
                             _yn(c["bailable"], "Bailable", "Non-bailable"), _years(c)])
            tbl = Table(rows, hAlign="LEFT", colWidths=[24 * mm, 34 * mm, 30 * mm, 50 * mm])
            tbl.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), base), ("FONTNAME", (0, 0), (-1, 0), bold),
                                     ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("BACKGROUND", (0, 0), (-1, 0), PALE),
                                     ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D0DA")),
                                     ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            out += [tbl, Spacer(1, 4)]
        out.append(Paragraph(escape(s["text"]).replace("\n", "<br/>"), st["src"]))
        return out

    def judgment_flowables(j, used_in=None):
        out = [P(j["case_name"], "h3")]
        if used_in:
            out.append(P(used_in, "small"))
        out.append(P(f"Read the judgment ({j.get('source_label', 'source link')}):", "small"))
        out.append(Paragraph(f'<link href="{escape(j["url"], {chr(34): "&quot;"})}">{escape(j["url"])}</link>', st["url"]))
        for e in j.get("excerpts") or []:
            out.append(Paragraph(f"<i>{escape(e['label'])}:</i> " + escape(e["text"]).replace("\n", " "), st["src"]))
        return out

    story = []
    ids = ", ".join(r["answer_id"] for r in records)
    story.append(P("Your questions and the answers" if multi else "Your question and the answer", "title"))
    when = _fmt_time(time.time())
    meta = (f"Recourse · {len(records)} answers · generated {when}" if multi
            else f"Recourse · answer ID {records[0]['answer_id']} · generated {when}")
    if total_n > len(records):
        meta += f" · showing the newest {len(records)} of {total_n} questions"
    story.append(P(meta, "meta"))
    story.append(P(DISCLAIMER, "note"))
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#C9D0DA"), spaceBefore=6, spaceAfter=6))

    if multi:
        story.append(P("Contents", "h2"))
        for i, r in enumerate(records, 1):
            q = r["question"] if len(r["question"]) <= 95 else r["question"][:92].rstrip() + "..."
            story.append(P(f"Question {i} — {q}  ({r['answer_id']})", "small"))
        story.append(Spacer(1, 6))

    for i, r in enumerate(records, 1):
        story.append(P(f"Question {i}" if multi else "Your question", "h2"))
        if multi:
            story.append(P(f"Answer ID {r['answer_id']} · {_fmt_time(r['created_at'])}", "small"))
        story.append(P(r["question"] or "(no text)", "q"))
        story.append(P("Answer" if multi else "The answer", "h2" if not multi else "h3"))
        if r.get("conflict_note"):
            story.append(P(CONFLICT_OPENER, "note"))
        story += answer_flowables(r["response_text"])
        if not multi:
            cl = unclear_checklist(r["response_text"])
            if cl["items"] or cl["from_answer"] or cl["documents"]:
                story += _checklist_flowables([(cl, None)], P, st)

    if multi:
        merged = []
        for i, r in enumerate(records, 1):
            merged.append((unclear_checklist(r["response_text"]), i))
        story += _checklist_flowables(merged, P, st)

    # ---- sources (deduplicated across answers; each says which questions used it)
    stat_map, judg_map, other_map = {}, {}, {}
    for i, r in enumerate(records, 1):
        for s in r.get("statutes") or []:
            stat_map.setdefault((s["act"], s["section_number"]), [s, []])[1].append(i)
        for j in r.get("judgments") or []:
            judg_map.setdefault(j["case_name"], [j, []])[1].append(i)
        for o in r.get("other_cases") or []:
            other_map.setdefault(o["case_name"], [o, []])[1].append(i)

    def used(idx):
        return ("Used in: " + ", ".join(f"Question {n}" for n in idx)) if multi else None

    if stat_map or judg_map:
        story.append(P("Sources this answer relies on" if not multi else "Sources these answers rely on", "h2"))
        if stat_map:
            story.append(P("Laws (text copied from Recourse's stored copy of the Act)", "small"))
            for s, idx in stat_map.values():
                story += statute_flowables(s, used(idx))
        if judg_map:
            story.append(P("Judgments", "small"))
            for j, idx in judg_map.values():
                story += judgment_flowables(j, used(idx))
    if other_map:
        story.append(P("Other cases that might be relevant (not independently verified)", "h2"))
        story.append(P("These came up in a wider search. Nobody at Recourse has read and confirmed them - read the real "
                       "judgment yourself, or with a lawyer, before relying on it.", "note"))
        for o, idx in other_map.values():
            flag = " — may be a procedural/bail order, not a full judgment" if o.get("procedural_disposal") else ""
            para = f" — paragraph {o['paragraph_number']}" if o.get("paragraph_number") else ""
            story.append(P(o["case_name"] + para + flag + (f" ({used(idx)})" if multi else ""), "h3"))
            if o.get("url"):
                story.append(Paragraph(f'<link href="{escape(o["url"])}">{escape(o["url"])}</link>', st["url"]))

    # ---- how this was checked (states only what is true for THIS document)
    has_stat, has_cls = bool(stat_map), any(s[0].get("classification") for s in stat_map.values())
    story.append(P("How this was checked", "h2"))
    lines = ["The wording of each answer was written by an AI (Claude) from the sources listed here. Recourse checks the "
             "section numbers and court names in that wording against the sources automatically; it cannot check that an "
             "answer fits your particular facts."]
    if has_stat:
        lines.append("Statute text in the Sources section is copied from Recourse's stored copy of the law, not written by the AI.")
    if has_cls:
        lines.append("Cognizable / bailable / punishment facts come from a fixed table of the law, not from the AI, and each answer is checked against that table.")
    if judg_map:
        lines.append("Judgments listed under 'Judgments' come from Recourse's curated library of judgments; the link goes to the source so you can read them yourself.")
    if other_map:
        lines.append("Cases under 'Other cases' were NOT independently verified.")
    lines.append(f"Laws and judgments change. This document was generated on {when}.")
    for ln in lines:
        story.append(P("• " + ln, "check"))

    story.append(P("Notes for my lawyer", "h2"))
    for _ in range(4):
        story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#C9D0DA"), spaceBefore=14, spaceAfter=0))

    footer_left = ("Answer ID " + ids) if not multi else f"{len(records)} answers"

    class _Numbered(rl_canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            n = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self.setFont(base, 7.5)
                self.setFillColor(MUTED)
                self.drawString(18 * mm, 13 * mm, f"Recourse — information, not legal advice · {footer_left}")
                self.drawRightString(A4[0] - 18 * mm, 13 * mm, f"Page {self._pageNumber} of {n}")
                super().showPage()
            super().save()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=26 * mm,
                            title="Recourse — " + ("your questions and answers" if multi else "your question and answer"),
                            author="Recourse")
    doc.build(story, canvasmaker=_Numbered)
    return buf.getvalue()


def _checklist_flowables(entries, P, st):
    """entries: [(checklist_dict, question_number_or_None), ...] -> flowables for 'Facts to find out or bring to a lawyer'."""
    items, seen, docs, quotes = [], set(), [], []
    for cl, qn in entries:
        for it in cl["items"]:
            k = _norm(it)
            if k not in seen:
                seen.add(k)
                items.append((it, qn))
        for d in cl["documents"]:
            if _norm(d) not in {_norm(x[0]) for x in docs}:
                docs.append((d, qn))
        if cl["from_answer"]:
            quotes.append((cl["from_answer"], qn))
    if not (items or docs or quotes):
        return []
    out = [P("Facts to find out or bring to a lawyer", "h2"),
           P("Taken from what the answer itself said was unclear.", "small")]
    for it, qn in items:
        out.append(P("☐  " + it + (f"  (Question {qn})" if qn else ""), "check"))
    for q, qn in quotes:
        out.append(P("From the answer: " + q + (f"  (Question {qn})" if qn else ""), "check"))
    if docs:
        out.append(P("Documents to have ready:", "h3"))
        for d, qn in docs:
            out.append(P("☐  " + d + (f"  (Question {qn})" if qn else ""), "check"))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# 4. proving the PDF holds everything, and the safe build
# ---------------------------------------------------------------------------------------------------------------------
_FOOTER_CLIP_PT = 62   # the footer sits in the bottom ~50 pt; the page body ends above 73 pt


def verify_pdf_completeness(pdf_bytes: bytes, records: list) -> dict:
    """Reads the PDF's text back and checks every question and every paragraph of every answer is inside it (letters and
    digits only, so line breaks and styling cannot fool it; the footer is excluded so a paragraph that crosses a page
    break is still found). {'ok': True/False/None, 'checked': n, 'missing': [...]} -- ok is None when no PDF reader is
    available."""
    try:
        import fitz
    except Exception:
        return {"ok": None, "checked": 0, "missing": [], "reason": "no PDF reader available"}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for page in doc:
            r = page.rect
            parts.append(page.get_text("text", clip=fitz.Rect(0, 0, r.width, r.height - _FOOTER_CLIP_PT)))
        hay = _norm("\n".join(parts))
        expected = []
        for rec in list(records)[-MAX_RECORDS:]:
            if rec.get("question"):
                expected.append(rec["question"])
            expected += [_strip_md(p) for p in _paragraphs(rec["response_text"])]
        missing = [e for e in expected if _norm(e) and _norm(e) not in hay]
        return {"ok": not missing, "checked": len(expected), "missing": missing}
    except Exception as exc:
        return {"ok": None, "checked": 0, "missing": [], "reason": f"{type(exc).__name__}: {exc}"}


def build_verified_pdf(records: list) -> tuple:
    """(pdf_bytes, info). Builds the styled PDF, proves it is complete, and falls back to the plain layout if not.
    info = {'ok': bool, 'fallback': bool, ...}. On total failure returns (None, {'ok': False, 'fallback': ..., 'error': ...}).
    Never raises."""
    if not records:
        return None, {"ok": False, "fallback": False, "error": "no answers to include"}
    try:
        data = build_answer_pdf(records)
        v = verify_pdf_completeness(data, records)
        if v["ok"] is not False:
            return data, {"ok": v["ok"] is True, "fallback": False, "checked": v["checked"]}
        logger.warning("styled answer PDF failed its completeness check (%s missing); building the plain layout", len(v["missing"]))
    except Exception as exc:
        logger.exception("styled answer PDF failed")
        err = f"{type(exc).__name__}: {exc}"
    else:
        err = None
    try:
        data = build_answer_pdf(records, plain=True)
        v = verify_pdf_completeness(data, records)
        if v["ok"] is False:
            logger.error("plain answer PDF ALSO failed its completeness check; sending it anyway")
        return data, {"ok": v["ok"] is True, "fallback": True, "checked": v["checked"]}
    except Exception as exc2:
        logger.exception("plain answer PDF failed")
        return None, {"ok": False, "fallback": True, "error": err or f"{type(exc2).__name__}: {exc2}"}
