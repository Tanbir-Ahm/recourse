"""
section_rule.py -- the named-section rule (added 2026-10-19 after the owner's staging test of section 17 of the Prevention of Corruption Act).

Four real failures, one cause: the person NAMED a section and the answer did not stay on it.
  * "Can a disproportionate assets case under PC act be filed without section 17 approval?": the answer wrote about section 17A ("previous approval") instead of section 17.
  * "I am asking about section 17, NOT section 17 A": the answer left out the second proviso of section 17, the one that matters (an offence under clause (b) of section 13(1) needs the order of an officer not below
    a Superintendent of Police). The page also cut the section's text at 900 characters, and the second proviso is the last thing in it.
  * Turns 3 and 4 of the same conversation ("... section 17 order ..."): a bare "section 17" with no Act name next to it was tied to no Act, so section 17 of the Act was found only by meaning, and BNS section 17 (an
    unrelated provision) was put into the material as well (act_shelf.implied_sections fixes the first; chat_assistant._drop_sections_claimed_by_shelf the second).

What this module holds (pure code, no model, no network):
  * enabled(): SECTION_RULE=on|off, default ON. It acts only when ACT_SHELF is on and the question names (or, in a conversation about one shelf Act, bare-names) a section of a shelf Act, so with ACT_SHELF off,
    which is the default, nothing changes.
  * provisos(text): the provisos of a section's text, each on its own, from the official text.
  * provisos_covered(answer, count): whether the answer refers to the section's provisos one by one ("the first proviso", "the second proviso", or "provisos").
  * notes(answer, matches): under the answer, the whole official text of every section the person named (owner's choice of 2026-10-20: show the explanation and the official wording side by side, always); only the
    sentence above it changes when the answer never uses the number ('not_mentioned') or does not refer to the provisos one by one ('provisos'). It carries the official text only; it judges nothing.
The prompt clause that tells the model to stay on the named section is in act_directory.py (_prompt_named), outside the Hard rules block. The limits are stated in FOLLOW_UPS item 2ay: the check for provisos looks for the words ("the first proviso", "a further proviso"; it cannot read meaning), so it can show the provisos although the answer did cover them in other words, and it cannot tell a wrong description of a proviso from a right one.
"""
import os
import re

MAX_NOTES = 2                 # sections noted under one answer
OFFICIAL_CHARS = 8000         # the official text given under the answer for a named section: cut at a line end beyond this (all but the longest sections of the nine Acts are under it)

_NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def enabled():
    """SECTION_RULE=on|off, default on. Off turns the whole rule off (implied section numbers, the prompt clause, the notes and the page's always-shown section)."""
    return (os.environ.get("SECTION_RULE") or "on").strip().strip("\"'").strip().lower() not in ("off", "0", "false", "no")


# ----- the provisos of a section -------------------------------------------------------------------------------------------------------------------------------------------------------------

_START = re.compile(r"^[\[(\s]*Provided\b(?:\s+(?:further|also))?\s+that\b", re.I)
_END = re.compile(r"^(?:[\[(\s]*(?:Provided\b|Explanation\b|Illustrations?\b|Note\s*:)|\[Note\s*:|\(\d+[A-Za-z]{0,2}\)\s)", re.I)


def _clean(text):
    """A proviso without the bracket that only closes (or opens) an amended passage of the section: '... warrant:]' -> '... warrant:'. Brackets inside the text stay (they are India Code's own marks)."""
    t = re.sub(r"\s+", " ", text).strip()
    if t.endswith("]") and t.count("]") > t.count("["):
        t = t[:-1].rstrip()
    if t.startswith("[") and t.count("[") > t.count("]"):
        t = t[1:].lstrip()
    return t


def provisos(text):
    """The provisos of a section, in order, each as its own text: [str]. A proviso begins at a line that starts with 'Provided that' (or 'Provided further that', 'Provided also that') and runs to the next
    such line, an Explanation, an Illustration, a note line or the next sub-section marker such as '(2)'. The shelf's text keeps every proviso on a line of its own (155 of 158 'Provided that' in the nine Acts
    start a line; the other three are quoted words that another Act's section inserts)."""
    out, cur = [], None
    for line in (text or "").split("\n"):
        s = line.strip()
        if _START.match(s):
            if cur:
                out.append(cur)
            cur = [s]
        elif cur is not None and s:
            if _END.match(s):
                out.append(cur)
                cur = None
            else:
                cur.append(s)
    if cur:
        out.append(cur)
    return [p for p in (_clean(" ".join(c)) for c in out) if p]


_PROVISO_WORD = re.compile(r"\bprovisos?\b|\bprovided\s+(?:further\s+|also\s+)?that\b", re.I)
_PLURAL = re.compile(r"\bprovisos\b", re.I)
_ORDINAL = (                                                       # how an answer refers to the 1st, 2nd and 3rd proviso of a section
    re.compile(r"\b(?:first|1st|one|the|a|this)\s+proviso\b|\bprovided\s+that\b", re.I),
    re.compile(r"\b(?:second|2nd|further|another|additional|other)\s+proviso\b|\bprovided\s+further\s+that\b", re.I),
    re.compile(r"\b(?:third|3rd)\s+proviso\b", re.I),
)


def provisos_covered(answer, count):
    """True when the answer refers to the section's provisos one by one. A section with no proviso is always covered; with one, the word 'proviso' (or 'provided that') is enough; with two or more, the answer must say
    'provisos' in the plural or refer to the first, the second (and for a third) one: 'the first proviso', 'the second proviso', 'a further proviso'. The prompt asks the model to introduce each proviso that way
    (act_directory._prompt_named), so an answer that follows it passes.  A rough test by words: it cannot tell a right description from a wrong one, it shows the provisos for an answer that covered them without
    numbering them, and it cannot see an answer that numbers them and gets one wrong. Owner's four answers (2026-10-19): none passes (no 'first proviso' in any), which is right: none gave both provisos."""
    if count <= 0:
        return True
    a = answer or ""
    if _PLURAL.search(a):
        return True
    if count == 1:
        return bool(_PROVISO_WORD.search(a))
    return all(p.search(a) for p in _ORDINAL[:min(count, len(_ORDINAL))])


# ----- the notes ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _cut_lines(text, limit):
    """`text` cut at the last line end within `limit` characters; (text, True if it was cut)."""
    if len(text) <= limit:
        return text, False
    head = text[:limit]
    nl = head.rfind("\n")
    return (head[:nl] if nl > limit // 2 else head).rstrip(), True


def _words(n):
    return _NUMBER_WORDS.get(n, str(n))


def _cites(m, matches, num, act, asked_seen):
    """SECTION_XREF: the sections that the asked section `m` cites (act_shelf._add_cited put their numbers in m['cites'] and their text in `matches`), each as {'section','lead','texts','cut'}: the whole official text of
    the cited section, under one plain sentence that makes no claim about what it means.  A cited section that is itself one the person asked about has its own note and is not repeated.  [] when none."""
    out = []
    try:
        for cn in (m.get("cites") or [])[:2]:
            cn = str(cn).upper()
            if (m.get("act"), cn) in asked_seen:
                continue
            hit = next((x for x in matches or [] if isinstance(x, dict) and x.get("source") == "act_shelf" and x.get("act") == m.get("act") and str(x.get("section_number") or "").upper() == cn
                        and (x.get("text") or "").strip()), None)
            if hit is None:
                continue
            body, cut = _cut_lines(hit["text"].strip(), OFFICIAL_CHARS)
            out.append({"section": cn, "texts": [body], "cut": cut,
                        "lead": f"Section {num} of the {act} refers to section {cn} of the same Act. So that you can read what the reference points to, here is the official text of section {cn}, as loaded from India Code:"})
    except Exception:  # noqa: BLE001
        return []
    return out


def notes(answer, matches):
    """The official text of every section the person NAMED, for the page, under the answer (owner's choice of 2026-10-20: "show both side by side, always"):
    [{'act', 'section', 'kind': 'official'|'not_mentioned'|'provisos', 'lead', 'texts': [the section's whole official text], 'provisos': [str], 'cut': bool, 'loaded_on', 'source_url'}], at most MAX_NOTES, for the shelf
    sections with retrieval 'named', or 'implied' (a bare number taken for the one shelf Act of the conversation).  [] when the rule is off, when the answer is empty, and on any problem.
    The text is always the section as loaded from India Code, word for word, cut at a line end beyond OFFICIAL_CHARS (cut=True says so).  The kind only changes the sentence above it:
    'official' = the answer uses the section's number and refers to its provisos one by one (or it has none): the plain statement that this is the official wording the explanation rests on;
    'not_mentioned' = the answer never uses the number (section 17A is not section 17); 'provisos' = the section has provisos and the answer does not clearly set them out (provisos_covered; `provisos` lists them).
    With SECTION_XREF on, an item also carries 'cites' = [{'section','lead','texts','cut'}]: the sections of the same Act that the asked section cites by number (act_shelf.cited_sections), whole and word for word."""
    out = []
    try:
        if not enabled() or not (answer or "").strip():
            return out
        import act_shelf
        mentioned = act_shelf.section_numbers_in(answer)
        seen = set()
        asked = {(x.get("act"), str(x.get("section_number") or "").upper()) for x in matches or []
                 if isinstance(x, dict) and x.get("source") == "act_shelf" and x.get("retrieval") in ("named", "implied")}        # a cited section that was itself asked about has its own note
        for m in matches or []:
            if not (isinstance(m, dict) and m.get("source") == "act_shelf" and m.get("retrieval") in ("named", "implied") and (m.get("text") or "").strip()):
                continue
            num = str(m.get("section_number") or "").upper()
            key = (m.get("act"), num)
            sh = m.get("shelf") if isinstance(m.get("shelf"), dict) else {}
            if not num or key in seen or sh.get("omitted"):
                continue
            seen.add(key)
            if len(out) >= MAX_NOTES:
                break
            act = m.get("act_display") or m.get("act") or "the Act"
            body, cut = _cut_lines(m["text"].strip(), OFFICIAL_CHARS)
            ps = provisos(m["text"])
            item = {"act": act, "section": num, "loaded_on": sh.get("loaded_on"), "source_url": sh.get("source_url"), "texts": [body], "cut": cut, "provisos": ps}
            if num not in mentioned:
                item.update(kind="not_mentioned", lead=f"You asked about section {num} of the {act}. The answer above does not set that section out by its number, so here is its official text:")
            elif ps and not provisos_covered(answer, len(ps)):
                k = len(ps)
                item.update(kind="provisos", lead=(f"Section {num} of the {act} has {_words(k)} proviso{'s' if k > 1 else ''} (an exception or condition added to the section's main rule), at the end of the text below. "
                                                   f"The answer above does not clearly set {'it' if k == 1 else 'them'} out, so here is the whole section in the official words:"))
            else:
                item.update(kind="official", lead=f"The official text of section {num} of the {act}, which you asked about. The explanation above is a plain-language reading of this text; the wording below is the law as loaded from India Code:")
            cites = _cites(m, matches, num, act, asked)
            if cites:
                item["cites"] = cites
            out.append(item)
        return out
    except Exception:  # noqa: BLE001
        return []
