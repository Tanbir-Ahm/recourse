"""
act_directory.py -- the Act Directory: signposts for the Acts whose text Recourse does not hold (added 2026-10-17 on the owner's "Start step 1"; plan: STATUTE_COVERAGE_PLAN.md step 1 in the
research repository, FOLLOW_UPS item 2af). Data: acts_directory.json next to this file.

What it does, and nothing more
  * Code, never the model, spots an Act in the person's QUESTION: by name or alias ("PC Act", "POCSO", "Prevention of Corruption Act, 1988": how = 'named') or, for a few Acts, by a phrase that means nothing
    else in practice ("corruption case", "money laundering", "Juvenile Justice Board": how = 'likely'). Matching is on lower-case words with word boundaries, so "arms act" never matches inside another word.
    An ambiguous short form ("CPC", "HMA", "NIA", "IT Act", "EC Act") is never an alias: no match is better than a wrong one.
  * It returns one fixed notice: this question names / looks like it is about the X Act; Recourse does not hold its text; where to read it. When the topic bar was opened for the question the notice
    REPLACES the generic outside-scope notice (it carries the same caution), so a person never sees two.
  * Nothing legal is shown until a person has confirmed it. The 'status' and 'appeal' lines in the data are drafts and stay hidden until their 'reviewed' stamp is set
    (python act_directory.py confirm ID status|appeal --by NAME). A link is used only when 'url_checked' is set (python act_directory.py check-links --write, run where India Code opens, or
    python act_directory.py confirm ID link --by NAME); otherwise the notice points to the India Code home page and says to search for the Act's name.
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


def notice(acts, kind="answer", path=None):
    """The fixed notice for the Acts a question names, as plain text (WhatsApp) and as escaped HTML (the page): {'kind','acts':[ids],'text','html'}, or None.
    kind: 'opened' (the topic bar was opened for this question: carries the generic caution too), 'answer' (an ordinary answer that also names the Act), 'refusal' (the question was turned away)."""
    try:
        if not acts or kind not in KINDS:
            return None
        d = load(path)
        many = len(acts) > 1
        esc = lambda s: _html.escape(s, quote=True)  # noqa: E731
        entries = [d["by_id"].get(a["id"]) or {} for a in acts]
        subject, holds = _subject(acts, kind), _holds(kind, many)
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
        text = " ".join([subject, holds] + extra + [link_text])
        html = " ".join([esc(subject), esc(holds)] + [esc(x) for x in extra] + [link_html])
        return {"kind": kind, "acts": [a["id"] for a in acts], "text": text, "html": html}
    except Exception:  # noqa: BLE001
        return None


def prompt_block(acts):
    """One short block for the answer prompt when the question names an Act that is not in the material ('' otherwise). It repeats the Hard rules for this case; it does not replace them."""
    try:
        if not acts:
            return ""
        many = len(acts) > 1
        names = _the_list([a["short"] for a in acts])
        verb = "names" if all(a.get("how") == "named" for a in acts) else "names or looks like it is about"
        it, them = ("those Acts", "them") if many else ("that Act", "it")
        return ("\n\n## Acts named in the question that are not in the material\n"
                f"The person's question {verb} the {names}. The text of {it} is not in the material above: do not state any section number, punishment, procedure or route of appeal of {it} "
                f"from memory, say in one sentence that the material does not contain {them}, and keep to what the material does show.\n")
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


def _title_of(body):
    m = re.search(r"<title[^>]*>(.*?)</title>", body or "", re.I | re.S)
    return _norm(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""


def _same_page(a, b):
    pa, pb = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    host = lambda h: (h or "").lower().replace("www.", "", 1)  # noqa: E731
    return host(pa.netloc) == host(pb.netloc) and pa.path.rstrip("/") == pb.path.rstrip("/")


def _try_url(url, entry, opener, timeout):
    """('ok'|'ok (name not confirmed)'|'failed', detail). A redirect to another page (for example a retired site sending everyone to its home page) is a failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; recourse-act-directory-check)"})
        with opener(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            final = resp.geturl() if hasattr(resp, "geturl") else url
            body = resp.read(200000).decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        return "failed", f"{type(exc).__name__}: {str(exc)[:80]}"
    if code != 200:
        return "failed", f"HTTP {code}"
    if not _same_page(url, final):
        return "failed", f"redirected to {final}"
    core = _norm(re.sub(r"^the\s+", "", entry.get("name") or "", flags=re.I))
    if core and core in _norm(re.sub(r"<[^>]+>", " ", body)):
        return "ok", "page names the Act"
    return "ok (name not confirmed)", "reachable; the page does not carry the Act's name in plain HTML (client-rendered?)"


def check_links(path=None, write=False, opener=None, timeout=15, today=None):
    """Opens each entry's url, then its url_alt. Returns [(id, status, detail, url_used)]. With write=True an OK link sets url_checked (an alternative that opens replaces a url that does not).
    Run it where India Code opens (the sandbox's network blocks it); a person's click on the link counts just as much (confirm ID link)."""
    path = path or DATA_PATH
    opener = opener or urllib.request.urlopen
    today = today or datetime.date.today().isoformat()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for e in data["acts"]:
        used, res = None, ("failed", "no url")
        for u in (e.get("url"), e.get("url_alt")):
            if not u:
                continue
            res = _try_url(u, e, opener, timeout)
            if res[0].startswith("ok"):
                used = u
                break
        out.append((e["id"], res[0], res[1], used))
        if write:
            if used:
                if used != e.get("url"):
                    e["url_alt"], e["url"] = e.get("url"), used
                e["url_checked"] = today + ("" if res[0] == "ok" else " (reachable only)")
            else:
                e["url_checked"] = None
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
        print(f"\n{len(rows) - len(bad)} of {len(rows)} links open" + (" (url_checked written)" if "--write" in args else " (nothing written; add --write)"))
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
