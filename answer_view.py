"""
answer_view.py -- the engine's result as PRESENTATION DATA, for the new front end (WEBSITE_DESIGN 17; built 2026-10-23).
The Streamlit page (recourse_app.render_answer) decides what an answer shows: which sources are worth listing, how a section is shown, which notes appear and in what order, how the answer's bold labels become headings, what the Copy button copies. The new
front end must show exactly the same things, and must not re-implement that logic in a second language, so the logic lives here as plain Python that returns plain data (no HTML, no Streamlit): the API adds the result of build() to every reply as `view`, and the
front end only draws it. The helper functions below are copies of the page's own (recourse_app.py) taken on 2026-10-23; test_answer_view.py takes the page's functions out of its source and checks that both give the same output on the same inputs, so the
two cannot drift apart unnoticed. (A later cleanup can make the page import this module and delete its copies.)
Every text field is PLAIN TEXT (the front end escapes it) except the ones named *_html, which the engine itself wrote already escaped (act_notice.html) and which the front end sanitises again. build() never raises: it returns None for anything it cannot read.
"""
import html as _html
import logging
import re as _re

import refusal_text

logger = logging.getLogger("answer_view")
ANSWER_STATES = ("single_match", "conflicting_matches")
SHELF_EXCERPT_CHARS = 16000
LIBRARY_FULL_CHARS = 8000          # a BNS / BNSS / IT / NI section of the library is shown whole up to this length (988 library sections: 98% are under 4,700 characters, 10 are over 6,000). Until 2026-11-09 it was cut at 900, which hid
                                   # Explanation 1 of BNS 77 and sub-section (1)(b) of BNSS 35 in a staging answer that rested on both


# ------------------------------------------------------------------ copies of the page's helpers (recourse_app.py)
_LEAD_LABEL = _re.compile(r"(?m)^(\s{0,3})(\*\*[^*\n]{2,48}?\*\*)(:?)(?:[ \t]+|\n(?!\n))(?=\S)")
_WHOLE_LINE_BOLD = _re.compile(r"(?m)^(\s{0,4}(?:\d{1,2}[.)]\s+|[-*]\s+)?)\*\*([^*\n]+?)\*\*")
_CAP_AFTER_HEADING = _re.compile(r"(?m)^(\s{0,3}\*\*[^*\n]{2,90}\*\*:?\n\n)([a-z])")
_V3_HEADING_THEN_TEXT = _re.compile(r"(?m)^(\*\*[^*\n]{2,90}\*\*)[ \t]*\n(?!\n)")
_COPY_EMPH = _re.compile(r"(?<![\w*])(\*{1,2})(?=\S)(.+?)(?<=\S)\1(?![\w*])")
_PAGE_CRUFT = _re.compile(r"^\s*(?:\x0c\s*)?(?:page\s+\d+\s+of\s+\d+|\d{1,4}|\d+\s*\|\s*p\s*a\s*g\s*e)\s*$", _re.I)
_CASE_GENERIC_PARTY = ("state of", "state ", "union of india", "union of", "govt", "government", "central bureau of investigation", "cbi", "directorate of", "intelligence officer", "commissioner of", "n.c.t", "nct", "u.p.", "govt. of", "republic of")


def tame_sentence_bold(md, v3_label_max=0):
    def repl(m):
        prefix, inner = m.group(1), m.group(2)
        if "**" in inner:
            return m.group(0)
        if v3_label_max and m.string[m.end():m.end() + 1] in ("", "\n") and len(inner) <= v3_label_max and not inner.rstrip().endswith((".", "!")):
            return m.group(0)
        head, sep, tail = inner.partition(":")
        if sep and len(head) <= 48 and tail.strip():
            return f"{prefix}**{head.strip()}:** {tail.strip()}"
        if len(inner) <= 48 and not inner.rstrip().endswith((".", "!", "?")):
            return m.group(0)
        return f"{prefix}{inner}"
    return _WHOLE_LINE_BOLD.sub(repl, md)


def promote_answer_labels(md, audience=""):
    if not md:
        return md
    v3_max = {"layman": 48, "lawyer": 90}.get(audience, 0)
    md = tame_sentence_bold(md, v3_label_max=v3_max)
    if v3_max:
        md = _V3_HEADING_THEN_TEXT.sub(lambda m: m.group(1) + "\n\n", md)
    md = _LEAD_LABEL.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}\n\n", md)
    return _CAP_AFTER_HEADING.sub(lambda m: m.group(1) + m.group(2).upper(), md)


def plain_for_copy(md):
    try:
        t = _re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", md or "")
        for _ in range(2):
            t = _COPY_EMPH.sub(lambda m: m.group(2), t)
        return t.strip()
    except Exception:  # noqa: BLE001
        return (md or "").strip()


def clean_excerpt(text):
    if not text:
        return ""
    text = _html.unescape(text)
    out = []
    for line in text.replace("\x0c", "\n").split("\n"):
        line = _re.sub(r"</?[a-zA-Z][^>]*>", "", line)
        line = _re.sub(r"^\s+", "", line.rstrip())
        line = _re.sub(r"\s{2,}", " ", line)
        if _PAGE_CRUFT.match(line):
            continue
        out.append(line)
    cleaned = "\n".join(out)
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def case_is_named(m, reply_lc):
    cn = (m.get("case_name") or "").lower()
    if not cn:
        return False
    parts = [p.strip() for p in cn.split(" v ") if p.strip()]
    for p in parts:
        if any(p.startswith(g) for g in _CASE_GENERIC_PARTY):
            continue
        core = p.split("(")[0].split(",")[0].strip()
        if len(core) >= 4 and core in reply_lc:
            return True
    return False


_PARTY_HEAD = _re.compile(r"^(?:the |sri |shri |smt\.? |smti\.? |dr\.? |mr\.? |mrs\.? |ms\.? |m/s\.? |messrs\.? )+")
_PARTY_TAIL = _re.compile(r"\s*(?:,|&|\band\b)\s*(?:anr|ors|another|others)\b.*$")
_PARTY_NOISE = frozenset("represented through versus inspector police secretary".split())


def sci_named(case_name, reply_lc):
    """True when the answer NAMES a wider-search case. The stored form is 'Samar Chiring v. The State of Assam'; the answer writes 'Samar Chiring' or 'Gurmit Singh', so each party is reduced to its distinctive words
    (honorifics, 'and Anr', one-letter initials and generic parties such as the State or the Union dropped) and a case is named when ALL the distinctive words of one party stand in the answer as whole words. A party the State
    or the Union alone never counts. Never raises; False when in doubt (an unused-looking case is only moved to a collapsed list, never hidden)."""
    try:
        name = _re.sub(r"\(.*?\)", " ", str(case_name or "")).lower()
        reply_lc = str(reply_lc or "").lower()
        for party in _re.split(r"\s+(?:v\.?|vs\.?|versus)\s+", name):
            p = _re.sub(r"\s+", " ", party).strip(" .,")
            for _ in range(2):
                p = _PARTY_HEAD.sub("", p)
            p = _PARTY_TAIL.sub("", p).strip(" .,")
            if not p or any(p.startswith(g) for g in _CASE_GENERIC_PARTY):
                continue
            first = p.split(",")[0]
            words = [w for w in _re.findall(r"[a-z]+", first) if len(w) >= 3 and w not in _PARTY_NOISE]
            seen, dist = set(), []
            for w in words:
                if w not in seen:
                    seen.add(w)
                    dist.append(w)
            dist = dist[:4]
            if len(dist) >= 1 and sum(len(w) for w in dist) >= 6 and all(_re.search(r"\b" + _re.escape(w) + r"\b", reply_lc) for w in dist):
                return True
        return False
    except Exception:  # noqa: BLE001
        return False


def sources_worth_showing(matches, reply_text, cap=16, strict=False):
    """The judgments to show under 'the sections and judgments this answer rests on': those the reply names; when it names none, every one handed over (the layman's box, which keeps its sources even when the answer
    does not name a case), or, with `strict` (the lawyers' note, 2026-11-02: 'Arnesh Kumar' was listed under two answers about anticipatory bail that never named it), none."""
    reply_lc = (reply_text or "").lower()

    def _label(m):
        return str(m.get("section_number") or m.get("paragraph_number") or "")

    pool = matches or []
    named = [m for m in pool if case_is_named(m, reply_lc)]
    if named:
        pool = named
    elif strict:
        pool = []
    else:
        pool = sorted(pool, key=lambda m: 0 if str(m.get("source") or "").startswith("curated") else 1)
    picked, seen = [], set()
    for m in pool:
        key = (m.get("case_name") or "BNS/BNSS", _label(m))
        if key in seen:
            continue
        seen.add(key)
        picked.append(m)
        if len(picked) >= cap:
            break
    return picked


CITED_SUBSECTION_CHARS = 900          # each sub-section the answer cites that lies beyond the plain excerpt is shown up to this many characters
_SUB_MARK = _re.compile(r"(?m)^\((\d+[A-Za-z]?)\)")


def cited_subsections(reply, number):
    """The sub-sections of section `number` that `reply` cites as 'Section 483(3)' or 's. 483(3)' (a list of strings like '3'; [] when it cites the section only)."""
    try:
        n = _re.escape(str(number).split("(")[0].strip())
        out = []
        for m in _re.finditer(r"(?:sections?|sec\.|ss?\.)\s*" + n + r"\s*\(\s*(\d+[A-Za-z]?)\s*\)", reply or "", _re.I):
            if m.group(1) not in out:
                out.append(m.group(1))
        return out
    except Exception:  # noqa: BLE001
        return []


def _window_on(text, question, limit, skip_heading=True):
    """The stretch of `text` that holds the question's words (passage_window.py, PASSAGE_WINDOW on by default) or None: switch off, no question, nothing matches, the window is the head, or any failure."""
    try:
        import passage_window
        if not question or not passage_window.enabled():
            return None
        shown, info = passage_window.window(text, question, limit, skip_heading=skip_heading)
        return shown if shown and not info.get("error") and (info.get("moved") or info.get("heading")) else None
    except Exception:  # noqa: BLE001
        return None


def judgment_excerpt(text, question="", limit=1100):
    """The excerpt of a reviewed-library judgment as 'the sections and judgments this answer rests on' shows it: with the question, the window of `limit` characters that holds its words (heading skipped, '...' at the cut
    ends); else the first `limit` characters, as before."""
    t = clean_excerpt(text or "")
    if len(t) <= limit and not question:
        return t
    w = _window_on(t, question, limit)
    return w if w else t[:limit]


def _head_has_words(head, question):
    try:
        import passage_window
        return passage_window.has_words(head, question)
    except Exception:  # noqa: BLE001
        return True


def _opening(text):
    """The section's opening for a long section's cut view: up to 300 characters of whole words (the old first LINE was a wrapped line of the source, about 80 characters: 'Any police officer may without an order from a Magistrate and without a ...')."""
    flat = text[:300]
    if len(text) > 300 and " " in flat:
        flat = flat[:flat.rfind(" ")]
    return flat


def statute_excerpt(m, reply="", question=""):
    """The text of a statute section as 'the sections and judgments this answer rests on' shows it: a shelf section whole (up to 16,000 characters), any other statute whole up to LIBRARY_FULL_CHARS (8,000; it was cut at 900 until 2026-11-09). NEW (2026-11-03, owner's A): when the answer cites a
    sub-section that the cut leaves out (both anticipatory-bail answers rested on BNSS 483(3), and the box stopped inside the provisos of 483(1)), the section's first line is shown, then a gap marked '...', then each
    cited sub-section (up to CITED_SUBSECTION_CHARS each). Without such a citation, or when the cited sub-section is inside the plain excerpt, the excerpt is what it always was."""
    limit = SHELF_EXCERPT_CHARS if isinstance(m.get("shelf"), dict) else LIBRARY_FULL_CHARS
    text = clean_excerpt(m.get("text") or "")
    plain = text[:limit]
    if len(text) <= limit:
        return plain
    if question and not isinstance(m.get("shelf"), dict) and not (reply and cited_subsections(reply, m.get("section_number"))) and not _head_has_words(plain, question):
        # PASSAGE_WINDOW: the section's first line, a marked gap and the stretch that holds the question's words, ONLY when the first 900 characters hold none of them (a statute's opening states the rule, so it is kept
        # whenever it holds a word of the question; a sub-section the answer cites by number keeps the older rule below)
        first = _opening(text)
        w = _window_on(text[len(first):].lstrip(), question, max(limit - len(first) - 20, 300), skip_heading=False)
        if w and w.startswith("... "):
            return first + " ...\n\n[...]\n\n" + w[4:].rstrip()
    if not reply:
        return plain
    try:
        marks = [(x.start(), x.group(1)) for x in _SUB_MARK.finditer(text)]
        parts = []
        for sub in cited_subsections(reply, m.get("section_number")):
            for i, (pos, label) in enumerate(marks):
                if label.lower() != sub.lower():
                    continue
                end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
                if end <= limit:                                   # already inside the plain excerpt
                    break
                block = text[pos:end].rstrip()
                parts.append(block[:CITED_SUBSECTION_CHARS] + (" ..." if len(block) > CITED_SUBSECTION_CHARS else ""))
                break
        if not parts:
            return plain
        return _opening(text) + " ...\n\n[...]\n\n" + "\n\n".join(parts)
    except Exception:  # noqa: BLE001
        return plain


# ------------------------------------------------------------------ data builders (what the page draws with Streamlit calls, as data)
def _loaded_label(value):
    try:
        from act_shelf import loaded_label
        return loaded_label(value) or ""
    except Exception:  # noqa: BLE001
        return ""


def shelf_caption(m):
    """{'text', 'url'} for a section of the Act shelf (where its text comes from and that no reviewer has read it), else None."""
    sh = m.get("shelf") if isinstance(m, dict) else None
    if not isinstance(sh, dict):
        return None
    when = _loaded_label(sh.get("loaded_on"))
    bits = ["Official text from India Code" + (f", loaded {when}" if when else "") + "; not yet read by our reviewer"]
    if len(clean_excerpt(m.get("text") or "")) > SHELF_EXCERPT_CHARS:
        bits.append("shortened here")
    return {"text": "; ".join(bits), "url": sh.get("source_url") or None}


def currency_notes(case_name):
    """The legal-currency notes the page shows under a cited judgment (citation_currency), as plain strings."""
    if not case_name:
        return []
    try:
        from citation_currency import get_citation_currency_for_case_name
        out = []
        for rec in get_citation_currency_for_case_name(case_name):
            note = rec.get("plain_note") or rec.get("note") or rec.get("summary")
            if note:
                out.append(str(note))
        return out
    except Exception:  # noqa: BLE001
        return []


def section_notes(items):
    """SECTION_RULE / SECTION_XREF: for each section of a shelf Act the person named: a lead sentence, the section's whole text, cited sections' text, and the caption."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        try:
            when = _loaded_label(it.get("loaded_on"))
            bits = ["Official text from India Code" + (f", loaded {when}" if when else "") + "; not yet read by our reviewer"]
            if it.get("cut"):
                bits.append("shortened here; the whole section is under “Read the source” below")
            out.append({
                "lead": str(it.get("lead") or ""),
                "texts": _strings(it.get("texts")),
                "cites": [{"lead": str(c.get("lead") or ""), "texts": _strings(c.get("texts"))} for c in (it.get("cites") if isinstance(it.get("cites"), list) else []) if isinstance(c, dict)],
                "caption": "; ".join(bits),
                "url": it.get("source_url") or None,
            })
        except Exception:  # noqa: BLE001
            logger.exception("section note view failed")
    return out


def _statute_referenced(m, reply_lc):
    if str(m.get("source") or "").startswith("curated"):
        return True
    if m.get("source") == "act_shelf" and m.get("retrieval") in ("named", "implied", "cited"):
        try:
            import section_rule
            if section_rule.enabled():
                return True
        except Exception:  # noqa: BLE001
            pass
    sn = str(m.get("section_number") or "")
    return bool(sn) and (f"section {sn}".lower() in reply_lc or f"section {sn.split('(')[0]}".lower() in reply_lc)


def _sources(result, reply):
    reply_lc = (reply or "").lower()
    all_matches = [m for m in (result.get("matches") or []) if isinstance(m, dict)]
    statutes, seen = [], set()
    for m in all_matches:
        if not m.get("section_number") or m.get("case_name"):
            continue
        if not _statute_referenced(m, reply_lc):
            continue
        k = (m.get("act"), m.get("section_number"))
        if k in seen:
            continue
        seen.add(k)
        cap = shelf_caption(m)
        statutes.append({"heading": f'{m.get("act_display") or m.get("act")} Section {m.get("section_number")}', "caption": cap["text"] if cap else None, "caption_url": cap["url"] if cap else None, "text": statute_excerpt(m, reply, str(result.get("question_asked") or ""))})
    judgments = sources_worth_showing([m for m in all_matches if m.get("case_name")], reply, strict=(result.get("audience") == "lawyer"))
    by_case, order = {}, []
    for m in judgments:
        k = (m.get("case_name"), m.get("citation"))
        if k not in by_case:
            by_case[k] = []
            order.append(k)
        by_case[k].append(m)
    cases = []
    for name, cite in order:
        excerpts = []
        for m in by_case[(name, cite)]:
            head = str(m.get("paragraph_number") or "").split("_")[0]
            excerpts.append({"paragraph": head if head.isdigit() else None, "text": judgment_excerpt(m.get("text") or "", str(result.get("question_asked") or ""))})
        cases.append({"name": name, "citation": cite or None, "caveats": currency_notes(name), "excerpts": excerpts})
    return statutes, cases


UNVERIFIED_EXCERPT_CHARS = 1200       # what the answer model was shown of such a passage (chat_assistant._PILOT_CONTEXT_MAX_CHARS_PER_CHUNK)


def _unverified_excerpt(j, reply_lc):
    """The passage of a case in the 'Other real court cases' list, only when the answer NAMES the case (2026-11-02: a staging answer quoted words of Sibbia and cited Sushila para 102 while the file showed only their names, so a reader could not
    check them). The same first UNVERIFIED_EXCERPT_CHARS characters the answer model was given, cleaned; None when the case is not named, the passage is missing or on any error."""
    try:
        raw = str(j.get("text") or "")
        if not raw.strip() or not case_is_named(j, reply_lc):
            return None
        view = str(j.get("model_view") or "")                       # PASSAGE_WINDOW: the stretch of the passage the answer model was shown (chat_assistant._pool_view): the box shows the same words
        if view.strip():
            t = clean_excerpt(view)
            return t or None
        t = clean_excerpt(raw[:UNVERIFIED_EXCERPT_CHARS])
        return (t + " ...") if t and len(raw) > UNVERIFIED_EXCERPT_CHARS else (t or None)
    except Exception:  # noqa: BLE001
        return None


def _unverified_note(j, reply_lc):
    """For a pool passage that is shown (the answer names the case): one sentence when it is a law reporter's headnote, not the Court's own words (passage_notes.is_headnote); else None."""
    try:
        import passage_notes
        raw = str(j.get("text") or "")
        if raw.strip() and case_is_named(j, reply_lc) and (passage_notes.is_headnote(raw[:UNVERIFIED_EXCERPT_CHARS]) or passage_notes.is_headnote(str(j.get("model_view") or ""))):
            return passage_notes.HEADNOTE_PAGE
        return None
    except Exception:  # noqa: BLE001
        return None


def _s(v):
    return None if v is None else str(v)


def _strings(v):
    return [str(x) for x in v] if isinstance(v, list) else []


ASK_CHECK_LABELS = {"answered": "answered", "material_lacks": "the material does not show it", "not_found": "not found in the note"}


def _ask_check(v):
    """ANSWER_SHAPE's checklist for the page: {'items': [{'ask', 'status', 'label', 'heading'}], 'answered', 'total'} or None (answer_shape.checklist, built by code)."""
    try:
        if not isinstance(v, dict) or not isinstance(v.get("items"), list) or not v["items"]:
            return None
        items = [{"ask": str(i.get("ask") or ""), "status": str(i.get("status") or ""), "label": ASK_CHECK_LABELS.get(str(i.get("status")), ""), "heading": _s(i.get("heading"))} for i in v["items"] if isinstance(i, dict)]
        return {"items": items, "answered": int(v.get("answered") or 0), "total": int(v.get("total") or len(items))}
    except Exception:  # noqa: BLE001
        return None


CHARGE_TABLE_NOTE = "Chosen by a program from the facts in your case file (a table of fact patterns written by Recourse and a search by meaning). The list is not complete and has not been read by a lawyer. The classification is the BNSS First Schedule's own wording, extracted from the Gazette PDF by a program. Nothing here says anyone will be charged."


def _charge_table(v):
    """CHARGE_MAP's table for the page: {'note', 'items': [{'section', 'why', 'how', 'class_lines', 'summary'}]} or None (charge_map.candidates, stored with the answer)."""
    try:
        if not isinstance(v, list) or not v:
            return None
        items = []
        for c in v:
            if not isinstance(c, dict):
                continue
            act = "IT Act" if str(c.get("act")).upper() == "ITACT" else str(c.get("act") or "")
            cl = c.get("class") if isinstance(c.get("class"), dict) else {}
            items.append({"section": f"{act} section {c.get('section')}", "why": str(c.get("why") or ""), "how": "chosen from the facts by a table of patterns" if c.get("source") == "pattern" else "found by a search by meaning",
                          "class_lines": [str(x) for x in (cl.get("lines") or [])], "summary": [str(x) for x in (cl.get("summary") or []) if x]})
        return {"note": CHARGE_TABLE_NOTE, "items": items} if items else None
    except Exception:  # noqa: BLE001
        return None


def build(result):
    """The presentation data for one engine result, or None. For an answer: the pieces in the order the page draws them. For anything else: the shared refusal wording plus the notes the page shows under it."""
    try:
        if not isinstance(result, dict):
            return None
        state = result.get("state")
        if state not in ANSWER_STATES:
            n = refusal_text.notice(result)
            if n is None:
                return None
            act = result.get("act_notice")
            return {"kind": "notice", "notice": n, "act_notice_html": act.get("html") if isinstance(act, dict) and act.get("html") else None,
                    "register_notes": _strings(result.get("register_notes")) + _strings(result.get("register_possible"))}
        reply = result.get("response_text") if isinstance(result.get("response_text"), str) else ""
        act = result.get("act_notice") if isinstance(result.get("act_notice"), dict) else None
        has_act = bool(act and act.get("html"))
        matches = [m for m in (result.get("matches") or []) if isinstance(m, dict)]
        if reply:
            answer_md, fallback, copy_text = promote_answer_labels(reply, result.get("audience") or ""), None, plain_for_copy(reply)
        else:
            t = ((matches[0] if matches else {}).get("text") or "").strip()[:800]
            answer_md, fallback, copy_text = None, t, "Here is what the law says on this:\n\n" + t
        authorities = None
        if result.get("audience") == "lawyer" and isinstance(result.get("authorities"), dict):
            try:
                import authorities_table
                tables = [{"heading": h, "markdown": md} for h, md in authorities_table.render_markdown(result["authorities"])]
                a = result["authorities"]
                note = authorities_table.TABLE_NOTE if (a.get("library") or a.get("wider") or a.get("anchors")) else None
                authorities = {"tables": tables, "note": note}
            except Exception:  # noqa: BLE001
                logger.exception("authorities view failed")
        statutes, cases = _sources(result, reply)
        cited = None if result.get("audience") == "lawyer" else [{"case_name": str(c.get("case_name") or ""), "url": str(c.get("url") or ""), "source_label": str(c.get("source_label") or "source link")} for c in (result.get("cited_judgment_links") or []) if isinstance(c, dict)]
        reg_notes, reg_possible = _strings(result.get("register_notes")), _strings(result.get("register_possible"))
        register = {"notes": reg_notes, "possible": reg_possible, "not_checked": _s(result.get("register_not_checked"))} if (reg_notes or reg_possible or result.get("register_not_checked")) else None
        sci = None
        if result.get("sci_related_judgments"):
            fed = bool(result.get("sci_fed"))
            import sci_search_tier as _SCI
            rel = [j for j in result["sci_related_judgments"] if isinstance(j, dict)]
            by_court = result.get("sci_as_of_by_court") if isinstance(result.get("sci_as_of_by_court"), dict) else None
            sci = {"fed": fed, "as_of": _s(result.get("sci_as_of")), "as_of_by_court": {str(k): str(v) for k, v in by_court.items() if v} if by_court else None,
                   "scope": _SCI.scope_phrase(_SCI.courts_of(rel)), "court_tags": _SCI.mixed(rel), "items": [
                {"case_name": str(j.get("case_name") or ""), "link": _s(j.get("link")), "date": _s(j.get("date")), "paragraph": _s(j.get("paragraph")), "link_kind": _s(j.get("link_kind")), "court": _SCI.court_of(j),
                 "register_note": _s(j.get("register_note")), "passage_note": _s(j.get("passage_note")), "names_register_note": _s(j.get("names_register_note")), "excerpt": _s(j.get("excerpt")),
                 "used": sci_named(j.get("case_name"), reply.lower())} for j in rel]}
        anchors = None
        if result.get("anchor_excerpts"):
            items = [a for a in result["anchor_excerpts"] if isinstance(a, dict)]
            anchors = {"unconfirmed": any(a.get("status") != "reviewer_confirmed" for a in items), "items": [
                {"case_name": str(a.get("case_name") or ""), "link": _s(a.get("link")), "year": _s(a.get("year")), "citation": _s(a.get("citation")),
                 "excerpts": [{"label": str(e.get("label") or ""), "paragraph": _s(e.get("paragraph")), "text": str(e.get("text") or ""), "note": _s(e.get("note"))} for e in (a.get("excerpts") or []) if isinstance(e, dict)]} for a in items]}
        reply_lc_u = str(result.get("response_text") or "").lower()
        unverified = [{"case_name": str(j.get("case_name") or ""), "url": _s(j.get("ik_search_url")), "paragraph": _s(j.get("paragraph_number")), "procedural": bool(j.get("procedural_disposal")),
                       "excerpt": _unverified_excerpt(j, reply_lc_u), "note": _unverified_note(j, reply_lc_u)}
                      for j in (result.get("unverified_related_judgments") or []) if isinstance(j, dict)]
        return {
            "kind": "answer", "label": "Your situation", "conflicting": state == "conflicting_matches",
            "outside_scope_note": None if has_act else _s(result.get("outside_scope_note")),
            "answer_markdown": answer_md, "fallback_text": fallback, "copy_text": copy_text,
            "act_notice_html": act["html"] if has_act else None,
            "section_notes": section_notes(result.get("section_note")) if isinstance(result.get("section_note"), list) else [],
            "authorities": authorities, "statutes": statutes, "judgments": cases, "cited_links": cited, "register": register,
            "grounding_notes": _strings(result.get("grounding_notes")), "sci_related": sci, "anchors": anchors, "unverified": unverified,
            "ask_check": _ask_check(result.get("ask_check")),
            "charge_table": _charge_table(result.get("charge_candidates")),
        }
    except Exception:  # noqa: BLE001 -- the view is a convenience for the front end; the engine's own result is still sent
        logger.exception("answer view failed")
        return None
