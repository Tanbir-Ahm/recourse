"""
ea_bsa_map.py -- reads act_shelf/section_map_ea_bsa.json (built by section_map.py) and words the one fixed note that goes under a shelf section of the Indian Evidence Act, 1872 or of the Bharatiya Sakshya Adhiniyam, 2023
(2026-10-31; owner's decision on the answer-quality list).  The note reaches the answer model through the match's `context_note` (chat_assistant puts it under "[Important legal context for this section]").

What the note says, and no more:  the Evidence Act was repealed by the Adhiniyam, in force from 1 July 2024 (India Code's own record); which section of the other Act holds mostly the same words, by a program's count of shared
three-word runs; that nobody has read the pairing.  It never says the two sections mean the same, never says which Act governs a given case (the Adhiniyam's own repeal-and-savings section decides that, and it is not on
this note), and never says a case decided under one is good law under the other.  The share of words is shown in plain words, not as a number.

Fail-open: any problem (no map file, a section without an entry) gives '' and the section goes to the model exactly as before.
"""
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, "act_shelf", "section_map_ea_bsa.json")
EA_KEY, BSA_KEY = "evidence_act_1872", "bsa_2023"
_LOCK = threading.Lock()
_CACHE = {}

HOW = {                                                       # the start of the sentence, ending where the place is named
    "same_wording": "Nearly the same words as this section are found in",
    "reworded": "Much of this section's wording, with changes, is found in",
    "split_or_merged": "This section's wording is now spread over",
    "partly_carried": "Only part of this section's wording is found in",
}
MIN_REVERSE_SHARE = 0.30         # a BSA section is said to carry an Evidence Act section's wording only if it holds at least this share of it


def _load(path=None):
    p = os.path.abspath(path or MAP_PATH)
    with _LOCK:
        if p in _CACHE:
            return _CACHE[p]
        data = None
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
                data = None
        except Exception:  # noqa: BLE001 -- fail-open
            data = None
        fwd, rev = {}, {}
        for pr in (data or {}).get("pairs", []):
            try:
                ea = str(pr["ea"]).upper()
                fwd[ea] = pr
                for b in pr.get("bsa") or []:
                    if b.get("share", 0) >= MIN_REVERSE_SHARE:
                        rev.setdefault(str(b["section"]).upper(), []).append((ea, b))
            except Exception:  # noqa: BLE001
                continue
        _CACHE[p] = (fwd, rev)
        return _CACHE[p]


def _part(b):
    sub = b.get("bsa_subsection") or ""
    bp = (b.get("bsa_part") or "")
    prov = "the proviso to " if bp.lower().startswith("provided") else ""
    return f"{prov}section {b['section']}{sub}" if (prov and sub) else f"section {b['section']}{sub}"


def _ea_part(ea, pr):
    return f"section {ea} of the Indian Evidence Act"


def note_for(act_key, section_number, path=None):
    """The note for one shelf section of the Evidence Act or the Adhiniyam, '' for any other section or Act."""
    try:
        fwd, rev = _load(path)
        num = str(section_number).upper()
        if act_key == EA_KEY:
            pr = fwd.get(num)
            if not pr or pr.get("kind") == "repealed_in_ea":
                return ""
            head = ("The Indian Evidence Act, 1872 was repealed by the Bharatiya Sakshya Adhiniyam, 2023, which is in force from 1 July 2024 (India Code's record). ")
            if not pr.get("bsa") or pr.get("kind") == "no_counterpart_found":
                return head + ("No section of the Adhiniyam with similar wording was found by our program for this section; do not say the Adhiniyam carries it over, and do not say it was dropped: say only that no matching "
                               "section was found.")
            bs = [b for b in pr["bsa"] if b["share"] >= 0.25][:2] or pr["bsa"][:1]
            where = " and ".join(_part(b) for b in bs)
            how = HOW.get(pr.get("kind"), "Some of this section's wording is found in")
            return (head + f"{how} {where} of the Bharatiya Sakshya Adhiniyam, 2023. This pairing was made by a program comparing the "
                    "words of the two Acts; our reviewer has not read it. Name the Adhiniyam section only as 'the corresponding provision in the new Act, reportedly', and do not say the two mean the same unless "
                    "the passages given show it.")
        if act_key == BSA_KEY:
            rows = rev.get(num) or []
            head = "The Bharatiya Sakshya Adhiniyam, 2023 replaced the Indian Evidence Act, 1872 from 1 July 2024 (India Code's record). "
            if not rows:
                return ""
            nums = [ea for ea, _b in rows[:4]]
            eas = ("section %s" % nums[0]) if len(nums) == 1 else ("sections " + ", ".join(nums[:-1]) + " and " + nums[-1])
            return (head + f"Judgments and books written before then cite the old Act: this section holds much of the wording of {eas} of the Evidence Act. This pairing was made by a program comparing the words of the "
                    "two Acts; our reviewer has not read it. Say 'reportedly corresponds to' and do not say the two mean the same unless the passages given show it.")
    except Exception:  # noqa: BLE001 -- fail-open
        return ""
    return ""
