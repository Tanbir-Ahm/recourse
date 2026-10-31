"""
evidence_companions.py -- EVIDENCE_COMPANIONS=off|on (default off; written 2026-10-31 on the owner's decision "load the Evidence Act and the BSA ... plus a section map ... and companion searches for circumstantial-evidence questions").

The problem (owner's critique of a staging answer on circumstantial evidence): the answer rested on the general rule and left out what a lawyer reaches for next -- the burden of proving a fact especially within the accused's knowledge
(section 106 of the Evidence Act, now section 109 of the Bharatiya Sakshya Adhiniyam), the recovery provision (section 27, now the proviso to section 23(2)), and the case-law doctrines that attach to them
(last seen together; a false explanation as an added link in the chain).  A search on the question's own words does not bring them; they have to be asked for.

What it does when the switch is on and the question is about proving guilt by circumstantial evidence (excerpt_anchors._circumstantial, the same question test as the LANDMARKS topic):
  1. shelf_matches(): the sections EA 106, 27 and 8 and BSA 109, 23 and 6 are handed over from the Act shelf (needs ACT_SHELF=on and the two Acts' shelf text), with the counterpart note of ea_bsa_map.py;
  2. extra_queries() / merge(): in feed mode (SCI_SEARCH_MODE=feed) the wider search is asked three more questions (last seen together; false explanation of the accused; recovery on a disclosure statement); the best result of
     each that is not already among the results is added after the third result, and counts as an ordinary wider-search passage in every way (label, filters, flags, register line).
Nothing here says a case is good law or that a doctrine applies on the person's facts; the passages and sections are handed over for the answer model to use under the same rules as every other passage.
Fail-open: any problem gives no companions and the question goes through exactly as without the switch.  Not tried with the answer model or the real index (the sandbox has neither).
"""
import json
import os

SHELF_SECTIONS = {
    "circumstantial": [("evidence_act_1872", "106"), ("bsa_2023", "109"), ("evidence_act_1872", "27"), ("bsa_2023", "23"), ("evidence_act_1872", "8"), ("bsa_2023", "6")],
}
QUERIES = {
    "circumstantial": [
        ("last_seen_together", "Conviction based on last seen together theory: accused last seen with the deceased shortly before death, burden on the accused to explain under section 106 of the Evidence Act"),
        ("false_explanation", "False explanation or false defence by the accused as an additional link in the chain of circumstances in a case of circumstantial evidence"),
        ("recovery", "Recovery of the weapon or articles on the disclosure statement of the accused: section 27 of the Evidence Act, information leading to discovery, admissibility and weight"),
    ],
}
MAX_PER_QUERY = 1


def mode():
    v = (os.environ.get("EVIDENCE_COMPANIONS") or "").strip().strip("\"'").lower()
    return "on" if v == "on" else "off"


def topic(question):
    """The companion topic of a question ('circumstantial') or None; None whenever the switch is off."""
    try:
        if mode() != "on" or not question:
            return None
        import excerpt_anchors
        return "circumstantial" if excerpt_anchors._circumstantial(question) else None
    except Exception:  # noqa: BLE001
        return None


def shelf_matches(question, already=()):
    """Shelf sections for the topic as statute matches (retrieval 'companion'); [] when the switch is off, the shelf is off, the question is on another subject, or any Act is not held. `already` is a list of
    chunk ids the question has anyway."""
    try:
        t = topic(question)
        if not t:
            return []
        import act_shelf
        if not act_shelf.enabled():
            return []
        shelf = act_shelf.load()
        out = []
        for key, num in SHELF_SECTIONS[t]:
            st = (shelf.get("acts") or {}).get(key)
            if not st or not st.get("ok"):
                return []                                           # all or none: half a pair (the old section without the new one) would mislead
            c = st["by_num"].get(num.upper())
            if not c or c.get("omitted"):
                return []
            cid = f"act:{c['act']}:{c['section_number']}"
            if cid in already:
                continue
            m = act_shelf._match(st, c, "companion", None)
            out.append(m)
        if out:
            print("EVIDENCE_COMPANIONS_SHELF " + json.dumps({"topic": t, "sections": [f"{m['act']} s.{m['section_number']}" for m in out]}), flush=True)
        return out
    except Exception:  # noqa: BLE001
        return []


def extra_queries(question):
    """[(tag, query)] for the wider search, [] when there are none."""
    t = topic(question)
    return list(QUERIES.get(t, [])) if t else []


def merge(found, question, search_fn, after=3):
    """The search service's answer `found` ({'results': [...]}) with the best new result of each companion query placed after the first `after` results.  `search_fn(query) -> answer dict or None`.
    Returns `found` unchanged on any problem or when there is nothing to add."""
    try:
        qs = extra_queries(question)
        if not qs or not isinstance(found, dict) or not isinstance(found.get("results"), list):
            return found
        have = {r.get("doc") for r in found["results"] if isinstance(r, dict)}
        added, log = [], []
        for tag, q in qs:
            ans = search_fn(q)
            if not ans or not isinstance(ans.get("results"), list):
                continue
            n = 0
            for r in ans["results"]:
                if not isinstance(r, dict) or not r.get("case_name") or r.get("name_to_review") or r.get("doc") in have:
                    continue
                r = dict(r)
                r["companion"] = tag
                added.append(r)
                have.add(r.get("doc"))
                log.append({"query": tag, "case": (r.get("case_name") or "")[:100], "para": r.get("paragraph")})
                n += 1
                if n >= MAX_PER_QUERY:
                    break
        if not added:
            return found
        out = dict(found)
        out["results"] = found["results"][:after] + added + found["results"][after:]
        print("EVIDENCE_COMPANIONS_SEARCH " + json.dumps({"added": log}), flush=True)
        return out
    except Exception:  # noqa: BLE001
        return found
