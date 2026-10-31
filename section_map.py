"""
section_map.py -- which section of the Bharatiya Sakshya Adhiniyam, 2023 (BSA) now carries each section of the Indian Evidence Act, 1872 (EA).  Built 2026-10-31 (owner's decision: "a section map (s.106 to s.109, s.27 to the proviso of s.23(2), and so on)").

How it is made (by program, from the two texts on the Act shelf; nobody has read the result).  Both Acts are loaded from India Code (act_shelf/bsa_2023.json, act_shelf/evidence_act_1872.json).  Each paragraph of an EA section is compared with every paragraph of the BSA:
the words are lower-cased, a few terms are put into their new names ("Indian Evidence Act" -> "Bharatiya Sakshya Adhiniyam", "Indian Penal Code" -> "Bharatiya Nyaya Sanhita" and so on), and the share of the EA paragraph's three-word runs that the BSA paragraph also holds
decides the match.  A section's pairs are the BSA sections that carry at least MIN_SHARE of its words.  The best match is also described by the opening words of the BSA paragraph, so a section that moved INTO a sub-section or a proviso (EA 27 -> the proviso of BSA 23(2)) says so.

What the map is NOT: a statement that the two sections mean the same.  The BSA re-enacted the EA with changes (section 63 on electronic records, the new section 63 certificate form, section 23's proviso, section 120's presumption, the oath for electronic evidence and so on); a high share means the WORDS are
mostly the same, a low share that they are not.  Every pair is `machine_built_not_reviewed` until Mr. Advocate has read it (sheet `acts/SECTION_MAP_SHEET.docx`); the page and the prompt say "reported to correspond ... not yet read by our reviewer".

Usage:  python section_map.py [--out act_shelf/section_map_ea_bsa.json]
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHELF = os.path.join(HERE, "act_shelf")
MIN_SHARE = 0.20           # a BSA section is listed for an EA section when it holds at least this share of the EA section's three-word runs
PAR_MIN = 0.20            # a paragraph counts as carried over when this share of its three-word runs is found in one BSA paragraph
SAME = 0.90                # at or above this the wording is (nearly) the same
REWORDED = 0.55            # between this and SAME: reworded or partly changed; under it: only some of the section survives
SUBS = [
    (r"indian evidence act,? 1872", "bharatiya sakshya adhiniyam 2023"), (r"indian evidence act", "bharatiya sakshya adhiniyam"), (r"evidence act", "bharatiya sakshya adhiniyam"),
    (r"this act", "this adhiniyam"), (r"indian penal code(?: \(45 of 1860\))?", "bharatiya nyaya sanhita 2023"), (r"code of criminal procedure,? 1973(?: \(2 of 1974\))?", "bharatiya nagarik suraksha sanhita 2023"),
    (r"code of criminal procedure,? 1898", "bharatiya nagarik suraksha sanhita 2023"), (r"code of civil procedure,? 1908(?: \(5 of 1908\))?", "code of civil procedure 1908"),
    (r"police-officer", "police officer"), (r"\bwhilst\b", "while"), (r"hand-writing", "handwriting"), (r"\bsuch\b", "such"),
]


def words(text):
    t = text.lower()
    for pat, rep in SUBS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"[–—\-]+", " ", t)
    return re.findall(r"[a-z0-9]+", t)


def grams(ws, n=3):
    return set(zip(*[ws[i:] for i in range(n)])) if len(ws) >= n else {tuple(ws)} if ws else set()


def paragraphs(chunk):
    body = chunk["text"].split("\n")[1:]                      # drop the 'N. Title' line
    out = [p.strip() for p in body if p.strip() and p.strip() != "[State amendments printed here by India Code are not part of the central Act and are not loaded.]"]
    return out


def load(name):
    with open(os.path.join(SHELF, name), encoding="utf-8") as fh:
        return json.load(fh)


def subsection_of(bsa_par, sec, k):
    """For a paragraph that is a proviso, explanation, exception or illustration, the sub-section it hangs from ('(2)'): the nearest earlier paragraph of the section that opens with '(1)', '(2)' ...; '' for a paragraph that is itself a sub-section or the whole section."""
    if not re.match(r"^(provided|explanation|exception|illustration|\*)", bsa_par[(sec, k)], re.I):
        m = re.match(r"^\((\d+[A-Za-z]?)\)", bsa_par[(sec, k)])
        return "(%s)" % m.group(1) if m else ""
    for j in range(k - 1, -1, -1):
        m = re.match(r"^\((\d+[A-Za-z]?)\)", bsa_par.get((sec, j), ""))
        if m:
            return "(%s)" % m.group(1)
    return ""


def build(ea_chunks, bsa_chunks, built_on=None):
    index = {}                                                # gram -> set of (bsa section, paragraph number)
    bsa_par = {}                                              # (section, k) -> paragraph text
    for c in bsa_chunks:
        for k, p in enumerate(paragraphs(c)):
            bsa_par[(c["section_number"], k)] = p
            for g in grams(words(p)):
                index.setdefault(g, set()).add((c["section_number"], k))
    pairs = []
    for c in ea_chunks:
        pars = paragraphs(c)
        n_total = sum(max(1, len(words(p))) for p in pars)
        by_sec, best_par = {}, {}
        for p in pars:
            ws = words(p)
            if len(ws) < 4:
                continue
            g = grams(ws)
            score = {}
            for gram in g:
                for key in index.get(gram, ()):
                    score[key] = score.get(key, 0) + 1
            if not score:
                continue
            key, hits = max(score.items(), key=lambda kv: kv[1])
            share = hits / len(g)
            if share >= PAR_MIN:
                by_sec[key[0]] = by_sec.get(key[0], 0.0) + share * len(ws)
                if share > best_par.get(key[0], (0, None))[0]:
                    best_par[key[0]] = (share, key[1])
        heading_words = words(c["title"])
        out = []
        for sec, weight in by_sec.items():
            sh = round(min(1.0, weight / n_total), 3)
            if sh >= MIN_SHARE:
                k = best_par[sec][1]
                out.append({"section": sec, "share": sh, "bsa_part": bsa_par[(sec, k)][:90], "bsa_subsection": subsection_of(bsa_par, sec, k)})
        out.sort(key=lambda d: -d["share"])
        omitted = bool(c.get("omitted")) or c["section_number"] == "2"
        if omitted:
            kind = "repealed_in_ea"
        elif not out:
            kind = "no_counterpart_found"
        elif len(out) > 1 and out[1]["share"] >= 0.25:
            kind = "split_or_merged"
        elif out[0]["share"] >= SAME:
            kind = "same_wording"
        elif out[0]["share"] >= REWORDED:
            kind = "reworded"
        else:
            kind = "partly_carried"
        pairs.append({"ea": c["section_number"], "ea_title": c["title"], "bsa": out[:4], "kind": kind})
    return {"schema": 1, "built_on": built_on or datetime.date.today().isoformat(), "status": "machine_built_not_reviewed",
            "about": "Which section of the Bharatiya Sakshya Adhiniyam, 2023 carries each section of the Indian Evidence Act, 1872, by shared wording. Built by program (section_map.py); not read by a person; NOT a statement that the sections mean the same.",
            "share_means": "the share of the Evidence Act section's three-word runs that the Adhiniyam paragraph also holds, after the Act's own new names are put in", "pairs": pairs}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(SHELF, "section_map_ea_bsa.json"))
    a = ap.parse_args(argv)
    m = build(load("evidence_act_1872.json"), load("bsa_2023.json"))
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    kinds = {}
    for p in m["pairs"]:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print("wrote", a.out, kinds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
