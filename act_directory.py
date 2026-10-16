"""
act_directory.py -- the Act Directory: signposts for the Acts whose text Recourse does not hold (added 2026-10-16 on the owner's "Start step 1"; plan: STATUTE_COVERAGE_PLAN.md step 1 in the
research repository, FOLLOW_UPS item 2af). Data: acts_directory.json next to this file.

What it does, and nothing more
  * Code, never the model, spots an Act in the person's QUESTION: by name or alias ("PC Act", "POCSO", "Prevention of Corruption Act, 1988": how = 'named') or, for a few Acts, by a phrase that means nothing
    else in practice ("corruption case", "money laundering", "Juvenile Justice Board": how = 'likely'). Matching is on lower-case words with word boundaries, so "arms act" never matches inside another word.
    An ambiguous short form ("CPC", "HMA", "NIA", "IT Act", "EC Act") is never an alias: no match is better than a wrong one.
  * It returns one fixed notice: this question names / looks like it is about the X Act; Recourse does not hold its text; where to read it. When the topic bar was opened for the question the notice
    REPLACES the generic outside-scope notice (it carries the same caution), so a person never sees two.
  * Nothing legal is shown until a person has confirmed it. The 'status' and 'appeal' lines in the data are drafts and stay hidden until their 'reviewed' stamp is set
    (python act_directory.py confirm ID status|appeal --by NAME). A link is used only when 'url_checked' is set (python act_directory.py check-links --write, run where indiacode.gov.in opens:
    it asks India Code's own data API for the record the link points to and requires its title, Act number and year to equal the entry's; or python act_directory.py confirm ID link --by NAME);
    otherwise the notice points to the India Code home page and says to search for the Act's name.
  * ACT_DIRECTORY=off switches all of it off (no notice, no prompt line, no log field); ACT_DIRECTORY=names keeps only name matches. Unset means on. Quotation marks around the value are ignored.
  * Never raises into an answer: every public function returns an empty result on bad input or a missing data file.

Public: detect(question) -> [{'id','short','how'}] (at most MAX_ACTS); notice(acts, kind) -> {'kind','acts','text','html'} | None; prompt_block(acts) -> str; link_for(entry); check_links(); confirm().
"""
import datetime
import html as _html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(_HERE, "acts_directory.json")
FALLBACK_URL = "https://indiacode.gov.in/"
MAX_ACTS = 2
KINDS = ("opened", "answer", "refusal")
_STATE = {}


def mode():
    """'on' (default), 'names' (name matches only) or 'off', from ACT_DIRECTORY."""
    v = (os.environ.get("ACT_DIRECTORY") or "").strip().strip("\"'").strip().lower()
    return v if v in ("off", "names") else "on"


def _norm(text):
    """Lower-case words only: 'S.C./S.T. Act' -> 's c s t act'; 'SC/ST Act' -> 'sc st act'; 'Prevention of Corruption (Amendment) Act, 2018' -> 'prevention of corruption amendment act 2018'."""
    t = (text or "").lower().replace("’", "'")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _pattern(norm_phrase):
    return re.compile(r"(?<![a-z0-9])" + re.escape(norm_phrase) + r"(?![a-z0-9])")


def load(path=None, refresh=False):
    """The directory with compiled patterns, cached per path. A missing or broken file gives an empty directory (the site then behaves as it did before the directory existed)."""
    path = path or DATA_PATH
    st = _STATE.get(path)
    if st is not None and not refresh:
        return st
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {"acts": []}
    except Exception:  # noqa: BLE001 -- fail-open
        data = {"acts": []}
    acts = []
    for raw in data.get("acts") or []:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("short"):
            continue
        e = dict(raw)
        e["_alias_re"] = [_pattern(n) for n in (_norm(a) for a in e.get("aliases") or []) if n]
        e["_phrase_re"] = [_pattern(n) for n in (_norm(p) for p in e.get("phrases") or []) if n]
        acts.append(e)
    st = {"raw": data, "acts": acts, "by_id": {e["id"]: e for e in acts}, "fallback_url": data.get("fallback_url") or FALLBACK_URL}
    _STATE[path] = st
    return st


def _first_pos(patterns, q):
    best = None
    for p in patterns:
        m = p.search(q)
        if m and (best is None or m.start() < best):
            best = m.start()
    return best


def detect(question, path=None):
    """The Acts of the directory that the QUESTION names or clearly describes, named ones first, then by position: [{'id','short','how'}], at most MAX_ACTS. [] when off, on bad input or when nothing matches."""
    try:
        m = mode()
        if m == "off" or not isinstance(question, str) or not question.strip():
            return []
        d = load(path)
        q = _norm(question)
        hits = []
        for e in d["acts"]:
            if e.get("detect") is False:
                continue
            pos = _first_pos(e["_alias_re"], q)
            how = "named"
            if pos is None and m == "on":
                pos = _first_pos(e["_phrase_re"], q)
                how = "likely"
            if pos is not None:
                hits.append((0 if how == "named" else 1, pos, e["id"], how, e["short"]))
        hits.sort(key=lambda h: (h[0], h[1]))
        return [{"id": h[2], "short": h[4], "how": h[3]} for h in hits[:MAX_ACTS]]
    except Exception:  # noqa: BLE001
        return []


def link_for(entry, fallback=FALLBACK_URL):
    """(url, verified): the Act's own link only once url_checked is set, else the India Code home page."""
    if isinstance(entry, dict) and entry.get("url") and entry.get("url_checked"):
        return entry["url"], True
    return fallback, False


def _reviewed_text(entry, field):
    f = (entry or {}).get(field)
    if isinstance(f, dict) and f.get("reviewed") and (f.get("text") or "").strip():
        return f["text"].strip()
    return ""


def _the_list(names):
    return " and the ".join(names)


def _subject(acts, kind):
    named = [a["short"] for a in acts if a.get("how") == "named"]
    likely = [a["short"] for a in acts if a.get("how") != "named"]
    also = "also " if kind == "answer" else ""
    parts = []
    if named:
        parts.append(f"{also}names the {_the_list(named)}")
    if likely:
        parts.append(f"{'also ' if (kind == 'answer' and not named) else ''}looks like it is about the {_the_list(likely)}")
    return "This question " + " and ".join(parts) + "."


def _holds(kind, many):
    it, them = ("those Acts", "them") if many else ("that Act", "it")
    if kind == "opened":
        return (f"Recourse has not checked this area in depth and does not hold the text of {it}, so what follows rests only on what we could find; "
                "please confirm it with a lawyer who handles this area before you rely on it.")
    if kind == "answer":
        return f"Recourse does not hold the text of {it}, so the answer below does not rest on {them}."
    return f"Recourse does not hold the text of {it}."


def _label(iso):
    """'2026-10-16' -> '16 October 2026' ('' when it is not a date)."""
    try:
        d = datetime.date.fromisoformat(str(iso))
        return f"{d.day} {d.strftime('%B %Y')}"
    except Exception:  # noqa: BLE001
        return ""


def _split_held(acts, held):
    """The Acts of a question in three groups, by what act_shelf.held_state says about each: 'used' (the shelf's text of the Act reached the answer), 'unused' (the shelf holds the Act but nothing from it did),
    'plain' (no working shelf: the Directory's own wording, as before the shelf existed).  held=None puts every Act in 'plain'."""
    used, unused, plain = [], [], []
    for a in acts:
        h = (held or {}).get(a["id"])
        state = h.get("state") if isinstance(h, dict) else None
        (used if state == "used" else unused if state == "unused" else plain).append(a)
    return used, unused, plain


def _ref(group, whole):
    """How a group of Acts is referred to in a sentence about it: ('that Act'|'those Acts', 'it'|'them', 'it'|'they') when the group is all the Acts of the question, else by name."""
    many = len(group) > 1
    if whole:
        return ("those Acts", "them", "they") if many else ("that Act", "it", "it")
    names = "the " + _the_list([a["short"] for a in group])
    return (names, "them" if many else "it", "they" if many else "it")


def _stamp(group, held):
    dates = {(held.get(a["id"]) or {}).get("loaded_on") for a in group}
    when = _label(next(iter(dates))) if len(dates) == 1 else ""
    return (f"loaded {when}; " if when else "") + "not yet read by our reviewer"


def _held_sentences(acts, kind, held):
    """The sentences about whether Recourse holds each group's text, for a question whose Acts include at least one with a working shelf (see _split_held)."""
    used, unused, plain = _split_held(acts, held)
    whole = lambda g: len(g) == len(acts)  # noqa: E731
    out = []
    if used:
        it, them, they = _ref(used, whole(used))
        out.append(f"Recourse has loaded the official text of {it} from India Code ({_stamp(used, held)}). The answer below was written from the sections of {it} that our search found for this question; "
                   f"{they} may contain other provisions that bear on your question.")
    if unused and kind != "refusal":
        it, them, they = _ref(unused, whole(unused))
        out.append(f"Recourse has loaded the official text of {it}, but the answer below does not rest on {them}.")
    if plain:
        it, them, they = _ref(plain, whole(plain))
        out.append(f"Recourse does not hold the text of {it}, so the answer below does not rest on {them}." if kind != "refusal" else f"Recourse does not hold the text of {it}.")
    if kind == "opened":
        out.append("Recourse has not checked this area in depth; please confirm what follows with a lawyer who handles this area before you rely on it.")
    return out


def notice(acts, kind="answer", path=None, held=None):
    """The fixed notice for the Acts a question names, as plain text (WhatsApp) and as escaped HTML (the page): {'kind','acts':[ids],'text','html'}, or None.
    kind: 'opened' (the topic bar was opened for this question: carries the generic caution too), 'answer' (an ordinary answer that also names the Act), 'refusal' (the question was turned away).
    held (added 2026-10-16 with the Act shelf, act_shelf.held_state): {act id: {'state': 'used'|'unused', 'loaded_on': iso date}} for the Acts that have a working shelf.  None, or no Act of the question in it:
    exactly the notice that existed before the shelf ('does not hold the text').  An Act whose shelf text reached the answer is described as loaded from India Code and not yet read by our reviewer."""
    try:
        if not acts or kind not in KINDS:
            return None
        d = load(path)
        many = len(acts) > 1
        esc = lambda s: _html.escape(s, quote=True)  # noqa: E731
        entries = [d["by_id"].get(a["id"]) or {} for a in acts]
        subject = _subject(acts, kind)
        if held and any(a["id"] in held for a in acts):
            holds = " ".join(_held_sentences(acts, kind, held))
        else:
            holds = _holds(kind, many)
        extra = []                                                   # only what a person has confirmed
        for a, e in zip(acts, entries):
            for field in ("status", "appeal"):
                t = _reviewed_text(e, field)
                if t:
                    extra.append((f"{a['short']}: {t}" if many else t))
        links = [link_for(e, d["fallback_url"]) for e in entries]
        if all(v for _, v in links):
            link_text = "Official text on India Code: " + "; ".join(f"{a['short']}: {u}" for a, (u, _) in zip(acts, links)) + "."
            link_html = "Official text on India Code: " + "; ".join(f'<a href="{esc(u)}">{esc(a["short"])}</a>' for a, (u, _) in zip(acts, links)) + "."
        else:
            root = d["fallback_url"]
            which = "each Act's name" if many else "the Act's name"
            link_text = f"Official text: India Code, {root} (search for {which})."
            link_html = f'Official text: <a href="{esc(root)}">India Code</a> (indiacode.gov.in), searching for {which}.'
        text = " ".join([p for p in [subject, holds] + extra + [link_text] if p])
        html = " ".join([p for p in [esc(subject), esc(holds)] + [esc(x) for x in extra] + [link_html] if p])
        out = {"kind": kind, "acts": [a["id"] for a in acts], "text": text, "html": html}
        if held and any(a["id"] in held for a in acts):
            out["held"] = {a["id"]: held[a["id"]]["state"] for a in acts if a["id"] in held}
        return out
    except Exception:  # noqa: BLE001
        return None


def _verb(group):
    return "names" if all(a.get("how") == "named" for a in group) else "names or looks like it is about"


def _prompt_plain(group):
    many = len(group) > 1
    names = _the_list([a["short"] for a in group])
    it, them = ("those Acts", "them") if many else ("that Act", "it")
    return ("\n\n## Acts named in the question that are not in the material\n"
            f"The person's question {_verb(group)} the {names}. The text of {it} is not in the material above: do not state any section number, punishment, procedure or route of appeal of {it} "
            f"from memory, say in one sentence that the material does not contain {them}, and keep to what the material does show.\n")


def _prompt_used(group):
    names = _the_list([a["short"] for a in group])
    it = "those Acts" if len(group) > 1 else "that Act"
    return ("\n\n## Act text in the material\n"
            f"The person's question {_verb(group)} the {names}. The material above includes sections of {it}, each block labelled with the Act's name; the text is the official text as loaded from India Code. "
            f"Use only those sections for anything you say about {it}: do not state any other section number, punishment, procedure or route of appeal of {it} from memory. "
            f"Name each of them with the Act shown in its label (for example \"Section 45 of the PMLA\"), not as a BNS or BNSS section. "
            "The material shows only the sections our search found closest to the question, not the whole Act. If the question needs a provision that is not among them, say in one sentence that the material does not show it "
            f"and that the full text is on India Code. A provision missing from the material does not mean {it} {'have' if len(group) > 1 else 'has'} none. "
            "Where a section's words and the person's facts do not clearly match, say so instead of stretching the section.\n")


def _prompt_unused(group):
    names = _the_list([a["short"] for a in group])
    it = "those Acts" if len(group) > 1 else "that Act"
    return ("\n\n## Act named in the question: its text is loaded, but nothing close enough was found\n"
            f"The person's question {_verb(group)} the {names}. Recourse holds the text of {it}, but no section of it was close enough to this question to be given to you above: do not state any section number, "
            f"punishment, procedure or route of appeal of {it} from memory, say in one sentence that the material does not contain a provision of {it} on this point, and keep to what the material does show.\n")


def prompt_block(acts, held=None):
    """The blocks for the answer prompt when the question names an Act ('' otherwise). They repeat the Hard rules for this case; they do not replace them.  held (see notice): an Act whose shelf text reached the
    answer gets the block that says so and forbids going beyond the sections given; an Act the shelf holds but nothing of which reached the answer gets the block that says nothing close enough was found;
    every other Act gets the block that existed before the shelf, byte for byte."""
    try:
        if not acts:
            return ""
        used, unused, plain = _split_held(acts, held)
        return (_prompt_plain(plain) if plain else "") + (_prompt_used(used) if used else "") + (_prompt_unused(unused) if unused else "")
    except Exception:  # noqa: BLE001
        return ""


# ----- maintenance: the reviewer's stamps and the link check (not used while answering) -----------------------------------------------------------------------------------------------

def _save(data, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    _STATE.pop(path, None)


def confirm(act_id, field, by, on=None, path=None):
    """Records that a PERSON has confirmed one field of one entry: field 'status' or 'appeal' (the text must exist: an empty draft cannot be confirmed) or 'link' (sets url_checked). Never run on anyone's behalf."""
    path = path or DATA_PATH
    if field not in ("status", "appeal", "link"):
        raise ValueError("field must be status, appeal or link")
    if not (by or "").strip():
        raise ValueError("--by NAME is required: who confirmed it")
    on = on or datetime.date.today().isoformat()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    entry = next((e for e in data["acts"] if e.get("id") == act_id), None)
    if entry is None:
        raise KeyError(f"no Act with id {act_id!r}")
    if field == "link":
        if not entry.get("url"):
            raise ValueError("this entry has no url to confirm")
        entry["url_checked"] = f"{on} ({by.strip()})"
    else:
        f = entry.get(field) or {}
        if not (f.get("text") or "").strip():
            raise ValueError(f"the {field} line is empty: nothing to confirm")
        f["reviewed"] = {"by": by.strip(), "on": on}
        entry[field] = f
    _save(data, path)
    return entry


IC_API = "https://indiacode.gov.in/server/api"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# the archive entry of a repealed Act reads  'Name, N of YEAR (Rep., Act X of Y)'  (and sometimes has no comma before N)
_STUB = re.compile(r"^(?P<name>.+?)[\s,]+(?P<num>\d+)\s+of\s+(?P<year>\d{4})\s*(?:,?\s*\(\s*Rep\.?[\s,]*(?P<by>[^)]*?)\s*\))?\s*$", re.I)
_CHECK_NOTE = "machine: India Code's own record matches on title, number and year"


def _ic_ref(url):
    """('uuid', u) or ('handle', '123456789/N') for an indiacode.gov.in item link; None for anything else (another host, a collection page, the home page)."""
    p = urllib.parse.urlsplit(url or "")
    if (p.netloc or "").lower() not in ("indiacode.gov.in", "www.indiacode.gov.in"):
        return None
    parts = [s for s in p.path.split("/") if s]
    if len(parts) >= 2 and parts[0] in ("items", "act") and _UUID.fullmatch(parts[1].lower()):
        return "uuid", parts[1].lower()
    if len(parts) >= 3 and parts[0] == "handle" and parts[1].isdigit() and parts[2].isdigit():
        return "handle", f"{parts[1]}/{parts[2]}"
    return None


def _name_parts(text):
    """(words, year): lower-case words without a leading 'The' and without a trailing year, and that year or None. 'The Indian Penal Code, 1860' and India Code's 'The Indian Penal Code' are the same
    name (one has no year); 'Prevention of Corruption Act, 1947' and '... Act, 1988' are not."""
    k = _norm(re.sub(r"^\s*the\s+", "", text or "", flags=re.I))
    m = re.search(r"\s+(\d{4})$", k)
    return (k[:m.start()], m.group(1)) if m else (k, None)


def _same_name(a, b):
    (ka, ya), (kb, yb) = _name_parts(a), _name_parts(b)
    return ka == kb and (ya is None or yb is None or ya == yb)


def _ic_identity(entry, item):
    """('ok', detail, info) when India Code's own record IS this Act: a central, archived, not withdrawn item whose title and Act number and year equal the entry's.
    ('failed', reason, None) otherwise. A repealed Act's archive entry ('Name, N of YEAR (Rep., Act X of Y)') counts; a state's version of the same Act does not."""
    try:
        if not isinstance(item, dict) or item.get("type") != "item":
            return "failed", "the link is not an India Code item", None
        if item.get("withdrawn") or item.get("inArchive") is False:
            return "failed", "the record is withdrawn or not in the archive", None
        md = item.get("metadata") or {}
        first = lambda k: str(((md.get(k) or [{}])[0].get("value")) or "").strip()  # noqa: E731
        title = first("dc.title") or str(item.get("name") or "").strip()
        want = re.match(r"\s*(\d+)\s+of\s+(\d{4})", entry.get("act_no") or "")
        if not title or not want:
            return "failed", "no title on the record or no Act number in the directory to compare", None
        state = first("dc.identifier.state_name")
        if state and state.upper() != "CENTRAL":
            return "failed", f"the record belongs to {state}, not to the Centre", None
        name, num, year, by = title, first("dc.identifier.act_number"), first("dc.date.act_year"), None
        if first("dc.identifier.collection") == "ACT":
            kind = "act"
            rep = first("dc.identifier.repealed").lower()
            repealed = True if rep == "true" else (False if rep == "false" else None)
        else:
            m = _STUB.match(title)
            if not m:
                return "failed", f"the record is not an Act (title {title!r} does not read 'Name, N of YEAR')", None
            name, num, year, by = m.group("name"), m.group("num"), m.group("year"), (m.group("by") or "").strip() or None
            kind, repealed = ("repealed-stub", True) if by else ("record", None)
        if not _same_name(name, entry.get("name")):
            return "failed", f"India Code's title is {title!r}", None
        if (int(num), int(year)) != (int(want.group(1)), int(want.group(2))):
            return "failed", f"India Code's Act number is {num} of {year}", None
        info = {"kind": kind, "title": title, "act_number": str(int(num)), "act_year": str(int(year)), "uuid": item.get("uuid"), "handle": item.get("handle"), "repealed": repealed, "repealed_by": by,
                "enacted": first("dc.date.enact_date") or None, "enforced": first("dc.date.enforcement_date") or None}       # India Code's own words: formats differ ('09-09-1988', '1-7-2024', free text for the GST and consumer Acts)
        return "ok", f"India Code record {title!r} ({int(num)} of {int(year)})", info
    except Exception as exc:  # noqa: BLE001
        return "failed", f"could not compare: {type(exc).__name__}", None


def _try_url(url, entry, opener, timeout):
    """('ok'|'failed'|'unreachable', detail, info). 'ok' only when India Code's data API returns the record this link points to AND that record is this Act (title, number, year, central).
    'unreachable' (no connection, a refusal, a server error) says nothing about the link; a missing record or a different Act is 'failed'.
    Why the API and not the page: the site is a client-side app that answers HTTP 200 for any address, so 'the page opens' proves nothing (the old-style handles 123456789/1558 and /2036 open to a
    collection called 'Form' and to nothing)."""
    ref = _ic_ref(url)
    if ref is None:
        return "failed", "not an indiacode.gov.in item link (items/<id>, act/<id> or handle/123456789/<n>)", None
    api = f"{IC_API}/core/items/{ref[1]}" if ref[0] == "uuid" else f"{IC_API}/pid/find?id={urllib.parse.quote(ref[1], safe='/')}"
    try:
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0 (compatible; recourse-act-directory-check)", "Accept": "application/json"})
        with opener(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            body = resp.read(2000000).decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return ("failed", "no such record (HTTP 404)", None) if exc.code in (404, 410) else ("unreachable", f"HTTP {exc.code}", None)
    except Exception as exc:  # noqa: BLE001
        return "unreachable", f"{type(exc).__name__}: {str(exc)[:80]}", None
    if code in (404, 410):
        return "failed", f"no such record (HTTP {code})", None
    if code != 200:
        return "unreachable", f"HTTP {code}", None
    try:
        item = json.loads(body)
    except ValueError:
        return "unreachable", "the data API did not return JSON", None
    return _ic_identity(entry, item)


def check_links(path=None, write=False, opener=None, timeout=20, today=None):
    """Checks each entry's url, then its url_alt, against India Code's own record. Returns [(id, 'ok'|'failed'|'unreachable', detail, url_used)].
    With write=True: an ok link stamps url_checked and fills 'indiacode' (title, Act number and year, uuid, handle, repealed or not); an alternative that checks out replaces a url that does not;
    a link that is definitely wrong (no such record, or another Act) clears url_checked; a link that could not be reached (no connection) changes NOTHING.
    Run it where indiacode.gov.in is reachable. A person's click counts just as much (confirm ID link)."""
    path = path or DATA_PATH
    opener = opener or urllib.request.urlopen
    today = today or datetime.date.today().isoformat()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for e in data["acts"]:
        used, res = None, ("failed", "no url", None)
        for u in (e.get("url"), e.get("url_alt")):
            if not u:
                continue
            res = _try_url(u, e, opener, timeout)
            if res[0] == "ok":
                used = u
                break
        out.append((e["id"], res[0], res[1], used))
        if not write:
            continue
        if used:
            if used != e.get("url"):
                e["url_alt"], e["url"] = e.get("url"), used
            e["url_checked"] = f"{today} ({_CHECK_NOTE})"
            e["indiacode"] = dict(res[2], verified_on=today)
        elif res[0] == "failed":
            e["url_checked"] = None
            e.pop("indiacode", None)
    if write:
        _save(data, path)
    return out


def _main(argv):
    if not argv or argv[0] not in ("list", "check-links", "confirm"):
        print(__doc__.split("Public:")[0])
        print("usage: python act_directory.py list | check-links [--write] | confirm ID status|appeal|link --by NAME [--on DATE]")
        return 2
    args = argv[1:]
    opt = lambda name: (args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None)  # noqa: E731
    path = opt("--file")
    if argv[0] == "list":
        for e in load(path)["acts"]:
            print(f"{e['id']:34s} {e.get('act_no',''):>10s}  detect={e.get('detect', True)!s:5s}  link={'checked' if e.get('url_checked') else 'unchecked':9s}  "
                  f"status={'confirmed' if (e.get('status') or {}).get('reviewed') else 'draft':9s}  appeal={'confirmed' if (e.get('appeal') or {}).get('reviewed') else ('draft' if (e.get('appeal') or {}).get('text') else '-'):9s}")
        return 0
    if argv[0] == "check-links":
        rows = check_links(path, write="--write" in args)
        for i, st, detail, used in rows:
            print(f"{st:24s} {i:34s} {detail}")
        bad = [r for r in rows if not r[1].startswith("ok")]
        print(f"\n{len(rows) - len(bad)} of {len(rows)} links check out against India Code's own record" + (" (url_checked written)" if "--write" in args else " (nothing written; add --write)"))
        return 1 if bad else 0
    ids = [a for a in args if not a.startswith("--") and a not in (opt("--by"), opt("--on"), opt("--file"))]
    if len(ids) != 2:
        print("usage: python act_directory.py confirm ID status|appeal|link --by NAME [--on DATE]")
        return 2
    e = confirm(ids[0], ids[1], opt("--by"), opt("--on"), path)
    print("confirmed:", e["id"], ids[1])
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
