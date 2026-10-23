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


def sources_worth_showing(matches, reply_text, cap=16):
    reply_lc = (reply_text or "").lower()

    def _label(m):
        return str(m.get("section_number") or m.get("paragraph_number") or "")

    pool = matches or []
    named = [m for m in pool if case_is_named(m, reply_lc)]
    if named:
        pool = named
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


def statute_excerpt(m):
    limit = SHELF_EXCERPT_CHARS if isinstance(m.get("shelf"), dict) else 900
    return clean_excerpt(m.get("text") or "")[:limit]


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
        statutes.append({"heading": f'{m.get("act_display") or m.get("act")} Section {m.get("section_number")}', "caption": cap["text"] if cap else None, "caption_url": cap["url"] if cap else None, "text": statute_excerpt(m)})
    judgments = sources_worth_showing([m for m in all_matches if m.get("case_name")], reply)
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
            excerpts.append({"paragraph": head if head.isdigit() else None, "text": clean_excerpt(m.get("text") or "")[:1100]})
        cases.append({"name": name, "citation": cite or None, "caveats": currency_notes(name), "excerpts": excerpts})
    return statutes, cases


def _s(v):
    return None if v is None else str(v)


def _strings(v):
    return [str(x) for x in v] if isinstance(v, list) else []


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
            sci = {"fed": fed, "as_of": _s(result.get("sci_as_of")), "items": [
                {"case_name": str(j.get("case_name") or ""), "link": _s(j.get("link")), "date": _s(j.get("date")), "paragraph": _s(j.get("paragraph")), "link_kind": _s(j.get("link_kind")), "register_note": _s(j.get("register_note")),
                 "passage_note": _s(j.get("passage_note")), "names_register_note": _s(j.get("names_register_note")), "excerpt": _s(j.get("excerpt"))} for j in result["sci_related_judgments"] if isinstance(j, dict)]}
        anchors = None
        if result.get("anchor_excerpts"):
            items = [a for a in result["anchor_excerpts"] if isinstance(a, dict)]
            anchors = {"unconfirmed": any(a.get("status") != "reviewer_confirmed" for a in items), "items": [
                {"case_name": str(a.get("case_name") or ""), "link": _s(a.get("link")), "year": _s(a.get("year")), "citation": _s(a.get("citation")),
                 "excerpts": [{"label": str(e.get("label") or ""), "paragraph": _s(e.get("paragraph")), "text": str(e.get("text") or ""), "note": _s(e.get("note"))} for e in (a.get("excerpts") or []) if isinstance(e, dict)]} for a in items]}
        unverified = [{"case_name": str(j.get("case_name") or ""), "url": _s(j.get("ik_search_url")), "paragraph": _s(j.get("paragraph_number")), "procedural": bool(j.get("procedural_disposal"))}
                      for j in (result.get("unverified_related_judgments") or []) if isinstance(j, dict)]
        return {
            "kind": "answer", "label": "Your situation", "conflicting": state == "conflicting_matches",
            "outside_scope_note": None if has_act else _s(result.get("outside_scope_note")),
            "answer_markdown": answer_md, "fallback_text": fallback, "copy_text": copy_text,
            "act_notice_html": act["html"] if has_act else None,
            "section_notes": section_notes(result.get("section_note")) if isinstance(result.get("section_note"), list) else [],
            "authorities": authorities, "statutes": statutes, "judgments": cases, "cited_links": cited, "register": register,
            "grounding_notes": _strings(result.get("grounding_notes")), "sci_related": sci, "anchors": anchors, "unverified": unverified,
        }
    except Exception:  # noqa: BLE001 -- the view is a convenience for the front end; the engine's own result is still sent
        logger.exception("answer view failed")
        return None
