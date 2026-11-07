"""
shelf_companions.py -- SHELF_COMPANIONS=on|off (default ON; written 2026-11-07 after the owner's question "can an arrest in a disproportionate assets case be made without an enquiry?").

The answer to that question rested on sections 13 and 17 of the Prevention of Corruption Act and never mentioned section 17A, whose heading is "Enquiry or Inquiry or investigation of offences relatable to
recommendations made or decision taken by public servant ...": the section about the previous approval that an enquiry or investigation of that kind needs. Checked afterwards (2026-11-07): on this checkout the search by meaning
DOES rank 17A second for that question, so it probably reached the model and the model did not use it; the first claim, that the search missed it, was not established. This module therefore does two things: it guarantees
that the pair 17 / 17A is in the material whenever the question is about an enquiry or investigation (the meaning search's cap or a different index could drop 17A), and it marks them, so that section_rule shows the
official text of one the answer never mentions.

What it does (pure code, no model, no network): when the question uses a word for an enquiry, inquiry, investigation, approval, sanction or permission, and the Act shelf already handed over a section of the Prevention of
Corruption Act, sections 17 and 17A of that Act are added to the material as 'companion' sections (whichever of the two is not there already), with their whole official text from the shelf; both are marked
m["companion"] = True (section_rule.notes shows the official text of a marked section that the answer does not mention). Nothing says that 17A
applies to the person's facts: whether it does is a question for a lawyer, and the prompt's rule about letter-different sections (17 and 17A) tells the model to keep them apart and say how they differ.
It acts only when ACT_SHELF is on (it is called from chat_assistant._companion_shelf_matches, which runs only then). Fail-open: any problem gives no companions and the question goes through as without it.
Not tried with the answer model.  The list of rules is the whole of what it knows: do not grow it into a general "related sections" table without a measurement on questions it has not seen.
"""
import json
import os
import re

RULES = [
    {"id": "pca_enquiry",
     "act_key": "pc_act_1988",
     "when": re.compile(r"\b(?:en|in)quir(?:y|ies|ed|e|ing)\b|\binvestigat\w*|\bapprov\w*|\bsanction\w*|\bpermission\b|\bauthori[sz]\w*", re.I),
     "add": ["17", "17A"]},
]
MAX_ADDED = 2


def enabled():
    return (os.environ.get("SHELF_COMPANIONS") or "on").strip().strip("\"'").strip().lower() not in ("off", "0", "false", "no")


def add(question, matches):
    """The companion sections for `question` (the person's current message) as shelf statute matches (retrieval 'companion'), [] when there is none. `matches` is what the shelf already handed over."""
    try:
        if not enabled() or not (question or "").strip():
            return []
        import act_shelf
        if not act_shelf.enabled():
            return []
        shelf = act_shelf.load()
        out = []
        for rule in RULES:
            have = {(m.get("act_key"), str(m.get("section_number") or "").upper()) for m in matches or [] if isinstance(m, dict) and m.get("source") == "act_shelf"}
            if not any(k == rule["act_key"] for k, _ in have) or not rule["when"].search(question):
                continue
            st = (shelf.get("acts") or {}).get(rule["act_key"])
            if not st or not st.get("ok"):
                continue
            for m in matches or []:                                   # the ones already there are marked too
                if isinstance(m, dict) and m.get("source") == "act_shelf" and m.get("act_key") == rule["act_key"] and str(m.get("section_number") or "").upper() in [n.upper() for n in rule["add"]]:
                    m["companion"] = True
            for num in rule["add"]:
                if len(out) >= MAX_ADDED or (rule["act_key"], num.upper()) in have:
                    continue
                c = st["by_num"].get(num.upper())
                if not c or c.get("omitted"):
                    continue
                m = act_shelf._match(st, c, "companion", None)
                m["companion"] = True
                out.append(m)
        if out:
            print("SHELF_COMPANIONS " + json.dumps({"added": [f"{m['act']} s.{m['section_number']}" for m in out]}), flush=True)
        return out
    except Exception:  # noqa: BLE001
        return []
