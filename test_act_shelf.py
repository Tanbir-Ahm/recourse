"""
test_act_shelf.py -- the Act shelf at answer time (act_shelf.py; ACT_SHELF=on|off, default off; 2026-10-16, plan: STATUTE_COVERAGE_PLAN.md step 2).
The switch and its default; the shelf's integrity checks (a stale embedding, a missing file, an unchecked text, a bad pointer: that Act is simply not held); the sections a question names; the search (floor, number of
sections, cap, pointers, a failing embedding); the Directory's wording for a held Act; the pipeline end to end with a stub model (the prompt, the label, the Act-name checks and repairs, the notice, the log line); the
page, WhatsApp and the PDF label; and that with the switch off nothing is different. No network, no model, no cost: the question vectors are the stored vectors of chosen sections.
Run: python -X utf8 test_act_shelf.py
"""
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import types

import numpy as np

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
for _v in ("ACT_SHELF", "ACT_DIRECTORY", "REGISTER_HOOKS", "RESPONSE_STYLE", "SCOPE_GATE", "SCI_SEARCH_MODE", "ANCHORS", "GROUNDING_CHECKS"):
    os.environ.pop(_v, None)

import act_directory as AD
import act_shelf as S
import chat_assistant as CA

FAILURES = []
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "recourse_app.py")
KEYS = ["pc_act_1988", "pocso_act_2012", "uapa_1967", "pmla_2002", "sc_st_act_1989"]
COUNTS = {"pc_act_1988": 35, "pocso_act_2012": 47, "uapa_1967": 67, "pmla_2002": 81, "sc_st_act_1989": 26}
CODES = {"pc_act_1988": "PCACT", "pocso_act_2012": "POCSO", "uapa_1967": "UAPA", "pmla_2002": "PMLA", "sc_st_act_1989": "SCSTACT"}


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def boom(text):
    raise AssertionError("the test reached the real Voyage call")


S._embed_query = boom                     # every test injects its own embedding

LOADED = {a["key"]: a["loaded_on"] for a in json.load(open(os.path.join(S.SHELF_DIR, "manifest.json"), encoding="utf-8"))["acts"]}      # the day the shelf was last loaded: it changes with every reload
LOADED_LABEL = S.loaded_label(LOADED["pmla_2002"])
EMB = json.load(open(os.path.join(S.SHELF_DIR, "shelf_embeddings.json"), encoding="utf-8"))
VEC = {r["chunk_id"]: np.array(r["embedding"], dtype=float) for r in EMB["records"]}


def like(code, sec):
    """A question 'embedding' that is exactly the stored vector of one section: that section ranks first with a score of 1."""
    return lambda text: VEC[f"act:{code}:{sec}"]


ZERO = lambda text: np.zeros(1024)        # nothing is close to this


# ---------------------------------------------------------------- the switch
for v, want in ((None, "off"), ("", "off"), ("on", "on"), (' "ON" ', "on"), ("off", "off"), ("banana", "off"), ("1", "off")):
    if v is None:
        os.environ.pop("ACT_SHELF", None)
    else:
        os.environ["ACT_SHELF"] = v
    check(S.mode() == want and S.enabled() is (want == "on"), f"ACT_SHELF={v!r}: {want}")
os.environ.pop("ACT_SHELF", None)
r = S.search("Section 45 of the PMLA", [{"id": "pmla_2002"}], embed_fn=like("PMLA", "45"))
check(r["matches"] == [] and S.held_state([], [{"id": "pmla_2002"}]) == {} and S.available("pmla_2002") is False, "switch off (the default): no match, no held state, nothing available")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    off_matches = CA._act_shelf_matches("Section 45 of the PMLA", "Section 45 of the PMLA")
check(off_matches == [] and buf.getvalue() == "" and CA._shelf_held([], "Section 45 of the PMLA") is None, "switch off: chat_assistant gets no shelf match, prints nothing and finds no held Act")

# ---------------------------------------------------------------- the shelf itself
SH = S.load()
check(set(SH["acts"]) == set(KEYS) and all(SH["acts"][k]["ok"] for k in KEYS) and SH["problems"] == [], f"the shelf loads: five Acts, every check passed ({ {k: v['problems'] for k, v in SH['acts'].items() if v['problems']} })")
check(all(len(SH["acts"][k]["by_num"]) == COUNTS[k] for k in KEYS), "every section of every Act is reachable by number (omitted and repealed stubs too)")
check(all(len(SH["acts"][k]["ranked"]) == COUNTS[k] - n for k, n in (("pc_act_1988", 2), ("pocso_act_2012", 0), ("uapa_1967", 1), ("pmla_2002", 8), ("sc_st_act_1989", 0))), "omitted and repealed stubs are not searched by meaning")
check(all(SH["acts"][k]["code"] == CODES[k] for k in KEYS) and all(SH["acts"][k]["text_status"] == "machine_checked" for k in KEYS), "codes as expected; the status is machine_checked (nobody has read the text)")
check(S.display_names() == {"PCACT": "Prevention of Corruption Act, 1988", "POCSO": "POCSO Act", "UAPA": "UAPA", "PMLA": "PMLA", "SCSTACT": "SC/ST Act"}, "display names (for the label and the repaired citation)")
check(all(k in {a["id"] for a in AD.load()["acts"]} for k in KEYS), "every shelf Act is an Act of the Directory (same ids)")
check(S.loaded_label("2026-10-16") == "16 October 2026" and S.loaded_label("nonsense") == "" and S.loaded_label(None) == "", "the date label")


def shelf_copy():
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, "act_shelf")
    shutil.copytree(S.SHELF_DIR, dst)
    return tmp, dst


def edit_json(path, fn):
    data = json.load(open(path, encoding="utf-8"))
    fn(data)
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)


tmp, d = shelf_copy()
edit_json(os.path.join(d, "pmla_2002.json"), lambda data: data[2].__setitem__("text", data[2]["text"] + " An added word."))
sh2 = S.load(d, refresh=True)
check(not sh2["acts"]["pmla_2002"]["ok"] and "no fresh embedding" in sh2["acts"]["pmla_2002"]["problems"][0] and all(sh2["acts"][k]["ok"] for k in KEYS if k != "pmla_2002"),
      "a section whose text changed since it was embedded: that Act is not held (the others are)")
shutil.rmtree(tmp)
tmp, d = shelf_copy()
os.remove(os.path.join(d, "shelf_embeddings.json"))
sh2 = S.load(d, refresh=True)
check(not any(a["ok"] for a in sh2["acts"].values()) and sh2["problems"], "no embeddings file: nothing is held, and nothing raises")
shutil.rmtree(tmp)
tmp, d = shelf_copy()
edit_json(os.path.join(d, "shelf_embeddings.json"), lambda data: data.__setitem__("model", "some-other-model"))
sh2 = S.load(d, refresh=True)
check(not any(a["ok"] for a in sh2["acts"].values()), "embeddings made with another model: nothing is held (the vectors would not be comparable)")
shutil.rmtree(tmp)
for field, value, label in (("text_status", "unchecked", "a text that did not pass its PDF check"), ("loaded_on", None, "no load date"), ("sections_loaded", 3, "a section count that disagrees with the file")):
    tmp, d = shelf_copy()

    def mut(data, field=field, value=value):
        data["acts"][3][field] = value
    edit_json(os.path.join(d, "manifest.json"), mut)
    sh2 = S.load(d, refresh=True)
    check(not sh2["acts"]["pmla_2002"]["ok"] and sh2["acts"]["pmla_2002"]["problems"] and all(sh2["acts"][k]["ok"] for k in KEYS if k != "pmla_2002"), f"{label}: that Act is not held")
    shutil.rmtree(tmp)
tmp, d = shelf_copy()
edit_json(os.path.join(d, "manifest.json"), lambda data: data["acts"][4]["pointers"][0].__setitem__("sections", ["18", "999"]))
sh2 = S.load(d, refresh=True)
check(not sh2["acts"]["sc_st_act_1989"]["ok"] and "pointer" in sh2["acts"]["sc_st_act_1989"]["problems"][0], "a pointer to a section that is not in the Act: that Act is not held")
shutil.rmtree(tmp)
tmp, d = shelf_copy()
os.remove(os.path.join(d, "uapa_1967.json"))
sh2 = S.load(d, refresh=True)
check(not sh2["acts"]["uapa_1967"]["ok"] and all(sh2["acts"][k]["ok"] for k in KEYS if k != "uapa_1967"), "a missing section file: that Act is not held")
shutil.rmtree(tmp)
sh2 = S.load(os.path.join(tempfile.gettempdir(), "no_such_shelf_dir"), refresh=True)
check(sh2["acts"] == {} and len(sh2["problems"]) == 1, "a directory that does not exist: an empty shelf and one problem, no exception")
S.load(refresh=True)                      # back to the real one

os.environ["ACT_SHELF"] = "on"
check(S.available("pmla_2002") and S.available("sc_st_act_1989") and not S.available("tada_1987") and not S.available("nonsense") and S.loaded_on("pmla_2002") == LOADED["pmla_2002"], "with the switch on: the five Acts are available, TADA is not")

# ---------------------------------------------------------------- the sections a question names
ALL = KEYS
NS = lambda q, ids=ALL: S.named_sections(q, ids)  # noqa: E731
check(NS("What does section 45 of the PMLA say about bail?") == {"pmla_2002": ["45"]}, "'section 45 of the PMLA'")
check(NS("PMLA section 45 and 19: how do they work together?") == {"pmla_2002": ["45", "19"]}, "'PMLA section 45 and 19': both numbers")
check(NS("Explain sections 3 and 4 of POCSO.") == {"pocso_act_2012": ["3", "4"]}, "'sections 3 and 4 of POCSO'")
check(NS("Is the bar in Section 43D(2) of the UAPA absolute?") == {"uapa_1967": ["43D"]}, "'Section 43D(2) of the UAPA': the sub-section is dropped, the letter kept")
check(NS("Does s. 18A of the SC/ST Act override anticipatory bail?") == {"sc_st_act_1989": ["18A"]}, "'s. 18A of the SC/ST Act'")
check(NS("What is u/s 19 of the PC Act?") == {"pc_act_1988": ["19"]}, "'u/s 19 of the PC Act'")
check(NS("In a PMLA case, is section 45 applicable at the stage of anticipatory bail?") == {"pmla_2002": ["45"]}, "the Act's name before the number")
check(NS("Does section 438 CrPC apply in a PMLA case?") == {}, "'section 438 CrPC' is not the PMLA's, even with the PMLA in the sentence")
check(NS("What is section 3 of the BNS?") == {}, "'section 3 of the BNS' is not ours")
check(NS("Does section 482 of the PMLA allow quashing?") == {}, "a number the Act does not have is ignored")
check(NS("What happened to section 27 of the PMLA?") == {"pmla_2002": ["27"]}, "an omitted section is reachable by number")
check(NS("Does section 3 of POCSO or section 3 of the BNS apply here?") == {"pocso_act_2012": ["3"]}, "two Acts' section 3 in one sentence: each goes to the Act standing next to it")
check(NS("Compare section 3 of POCSO with section 10 of the PC Act.") == {"pocso_act_2012": ["3"], "pc_act_1988": ["10"]}, "two shelf Acts in one sentence")
check(NS("What is the punishment under section 45?") == {}, "a section number with no Act next to it is not ours")
check(NS("Section 45 of the PMLA", ["pocso_act_2012"]) == {}, "an Act that was not asked for is ignored")
check(NS("") == {} and NS(None) == {} and NS("section", ALL) == {}, "empty and odd input: nothing, no exception")

# ---------------------------------------------------------------- the search
r = S.search("a question", [{"id": "pmla_2002", "how": "named"}], embed_fn=like("PMLA", "45"))
ms = r["matches"]
check(len(ms) == S.TOP_K_ONE and ms[0]["section_number"] == "45" and ms[0]["score"] == 1.0 and ms[0]["retrieval"] == "meaning", f"one Act: five sections by meaning, the closest first ({[m['section_number'] for m in ms]})")
check([m["score"] for m in ms] == sorted((m["score"] for m in ms), reverse=True) and all(m["score"] >= S.FLOOR for m in ms), "...in falling order of score, none under the floor")
m0 = ms[0]
check(m0["type"] == "statute" and m0["act"] == "PMLA" and m0["act_key"] == "pmla_2002" and m0["act_display"] == "PMLA" and m0["source"] == "act_shelf" and m0["chunk_id"] == "act:PMLA:45" and m0["all_variants"] == {}
      and m0["shelf"]["loaded_on"] == LOADED["pmla_2002"] and m0["shelf"]["text_status"] == "machine_checked" and m0["shelf"]["source_url"].startswith("https://indiacode.gov.in/act/") and m0["text"].startswith("45. Offences to be cognizable and non-bailable."),
      "the match carries what the prompt, the page and the checks need (Act code and name, official text, source, load date, status)")
check(r["info"]["acts"] == ["pmla_2002"] and r["info"]["embed"] == "ok" and r["info"]["chars"] == sum(len(m["text"]) for m in ms), "the log information is there")
r = S.search("Compare section 45 of the PMLA with section 4 of POCSO", [{"id": "pmla_2002"}, {"id": "pocso_act_2012"}], embed_fn=like("PMLA", "45"))
by = {}
for m in r["matches"]:
    by.setdefault(m["act_key"], []).append(m)
check(set(by) == {"pmla_2002", "pocso_act_2012"} and all(len(v) <= S.TOP_K_TWO for v in by.values()), f"two shelf Acts: at most three sections of each ({ {k: len(v) for k, v in by.items()} })")
r = S.search("a question", [{"id": "pmla_2002"}, {"id": "pmla_2002"}, {"id": "tada_1987"}, "pocso_act_2012"], embed_fn=like("POCSO", "19"))
check([m["act_key"] for m in r["matches"]].count("pmla_2002") <= S.TOP_K_TWO and r["info"]["acts"] == ["pmla_2002", "pocso_act_2012"], "a repeated Act counts once; an Act with no shelf (TADA) is skipped; a bare id works")
check(S.search("q", [{"id": "tada_1987"}], embed_fn=like("PMLA", "45"))["matches"] == [] and S.search("q", [], embed_fn=like("PMLA", "45"))["matches"] == [] and S.search("q", None, embed_fn=like("PMLA", "45"))["matches"] == [],
      "an Act with no shelf, no Acts, None: nothing")
r = S.search("a question", [{"id": "pmla_2002"}], embed_fn=ZERO)
check(r["matches"] == [] and r["info"]["per_act"]["pmla_2002"]["below_floor"] == 73, "nothing close enough (all under the floor): nothing is handed over, and the log says how many were under it")
r = S.search("What does section 45 of the PMLA say?", [{"id": "pmla_2002"}], embed_fn=like("PMLA", "4"))
sec = [(m["section_number"], m["retrieval"]) for m in r["matches"]]
check(sec[0] == ("45", "named") and sec[1] == ("4", "meaning") and len(sec) == 5 and r["matches"][0]["score"] is None, f"a named section comes first, then the closest by meaning ({sec})")
r = S.search("What does section 45 of the PMLA say?", [{"id": "pmla_2002"}], embed_fn=ZERO)
check([m["section_number"] for m in r["matches"]] == ["45"], "a named section comes even when nothing is close by meaning")
r = S.search("What does section 45 of the PMLA say?", [{"id": "pmla_2002"}], embed_fn=like("PMLA", "45"))
check([m["section_number"] for m in r["matches"]].count("45") == 1 and len(r["matches"]) == 5, "a section named and also closest by meaning comes once")
r = S.search("Sections 2, 3, 4 and 5 of the PMLA", [{"id": "pmla_2002"}], embed_fn=ZERO)
check([m["section_number"] for m in r["matches"]] == ["2", "3", "4"], f"at most {S.MAX_NAMED} named sections")
r = S.search("Is anticipatory bail available to an accused under the SC/ST Atrocities Act?", [{"id": "sc_st_act_1989"}], embed_fn=ZERO)
check([(m["section_number"], m["retrieval"]) for m in r["matches"]] == [("18", "pointer"), ("18A", "pointer")], "the pointer: 'anticipatory bail' brings sections 18 and 18A of the SC/ST Act")
for q in ("Can I apply for pre-arrest bail in an SC/ST case?", "Does section 438 apply under the Atrocities Act?", "Can he get bail before arrest under the SC/ST Act?"):
    r = S.search(q, [{"id": "sc_st_act_1989"}], embed_fn=ZERO)
    check({m["section_number"] for m in r["matches"]} >= {"18", "18A"}, f"pointer: {q!r}")
r = S.search("Is anticipatory bail available to an accused under the UAPA?", [{"id": "uapa_1967"}], embed_fn=ZERO)
check(r["matches"] == [], "...and only for the Act whose manifest has it")
r = S.search("a question", [{"id": "pmla_2002"}], embed_fn=lambda t: (_ for _ in ()).throw(RuntimeError("Voyage is down")))
check(r["matches"] == [] and r["info"]["embed"].startswith("failed"), "the embedding fails: no meaning sections, no exception")
r = S.search("section 45 of the PMLA", [{"id": "pmla_2002"}], embed_fn=lambda t: (_ for _ in ()).throw(RuntimeError("Voyage is down")))
check([m["section_number"] for m in r["matches"]] == ["45"], "...but a named section still comes")

# every section, used as the question: always itself first, never more than five, never over the cap, never a stub
bad = []
for k in KEYS:
    for c in SH["acts"][k]["ranked"]:
        r = S.search("q", [{"id": k}], embed_fn=like(c["act"], c["section_number"]))
        ms = r["matches"]
        if not (ms and ms[0]["section_number"] == str(c["section_number"]) and len(ms) <= S.TOP_K_ONE and sum(len(m["text"]) for m in ms) <= max(S.MAX_CHARS, len(ms[0]["text"])) and not any(m["shelf"]["omitted"] for m in ms)):
            bad.append((k, c["section_number"]))
check(not bad, f"all {sum(len(SH['acts'][k]['ranked']) for k in KEYS)} sections as questions: itself first, at most five, within the cap, no stub ({bad[:5]})")
r = S.search("q", [{"id": "sc_st_act_1989"}], embed_fn=like("SCSTACT", "3"))
check(r["matches"][0]["section_number"] == "3" and len(r["matches"][0]["text"]) > 11000, "a long section (the SC/ST Act's section 3, 11,800 characters) comes whole when it is the closest")
r = S.search("q", [{"id": "sc_st_act_1989"}, {"id": "pmla_2002"}], embed_fn=like("SCSTACT", "3"))
check(all(m["text"] for m in r["matches"]) and r["matches"][0]["text"] == SH["acts"]["sc_st_act_1989"]["by_num"]["3"]["text"], "...and no section is ever cut")
r = S.search("q", [{"id": "sc_st_act_1989"}], embed_fn=like("SCSTACT", "3"))
check(r["matches"][0]["section_number"] == "3" and len(r["matches"][0]["text"]) > 11000 and r["info"]["chars"] <= S.MAX_CHARS, "the SC/ST Act's section 3 (the longest section on the shelf, about 11,800 characters) as the closest: the others share what the cap leaves")
t17a = next(m for m in S.search("q", [{"id": "pc_act_1988"}], embed_fn=like("PCACT", "17A"))["matches"] if m["section_number"] == "17A")["text"]
check(len(t17a) < 2500 and "STATE AMENDMENT" not in t17a and "Anti-Corruption Bureau" not in t17a and "State or Union Territory amendments of this section (Union Territory of Jammu and Kashmir" in t17a,
      "the PC Act's section 17A is the central text with a one-line note: the 8,500 characters of Jammu and Kashmir / Ladakh text that India Code prints inside it are set aside")

# held state
ms = S.search("q", [{"id": "pmla_2002"}], embed_fn=like("PMLA", "45"))["matches"]
check(S.shelf_ids(ms) == ["pmla_2002"] and S.shelf_ids(None) == [] and S.shelf_ids([{"source": "curated"}, "x", None]) == [], "shelf_ids")
hs = S.held_state(ms, [{"id": "pmla_2002"}, {"id": "pocso_act_2012"}, {"id": "tada_1987"}])
check(hs == {"pmla_2002": {"state": "used", "loaded_on": LOADED["pmla_2002"]}, "pocso_act_2012": {"state": "unused", "loaded_on": LOADED["pocso_act_2012"]}}, f"held_state: used / unused / absent for an Act with no shelf ({hs})")
os.environ.pop("ACT_SHELF")
check(S.held_state(ms, [{"id": "pmla_2002"}]) == {}, "held_state with the switch off: nothing")
os.environ["ACT_SHELF"] = "on"

# ---------------------------------------------------------------- the Directory's wording
PM = AD.detect("Can my brother get bail under the PMLA?")
check([a["id"] for a in PM] == ["pmla_2002"], "the Directory finds the PMLA")
plain = AD.notice(PM, "answer")
check(plain["text"].startswith("This question also names the Prevention of Money-laundering Act, 2002 (PMLA). Recourse does not hold the text of that Act, so the answer below does not rest on it. Official text on India Code: "
                               "Prevention of Money-laundering Act, 2002 (PMLA): https://indiacode.gov.in/items/") and "held" not in plain, "held=None: the notice is the one that existed before the shelf, word for word")
check(AD.notice(PM, "answer", held={}) == plain and AD.notice(PM, "answer", held={"pocso_act_2012": {"state": "used", "loaded_on": "2026-10-16"}}) == plain, "...also when no Act of the question is in held")
HU = {"pmla_2002": {"state": "used", "loaded_on": "2026-10-16"}}
HN = {"pmla_2002": {"state": "unused", "loaded_on": "2026-10-16"}}
n = AD.notice(PM, "answer", held=HU)
check("Recourse has loaded the official text of that Act from India Code (loaded 16 October 2026; not yet read by our reviewer). The answer below was written from the sections of that Act that our search found for this question; it may contain other provisions that bear on your question."
      in n["text"] and "does not hold" not in n["text"] and n["held"] == {"pmla_2002": "used"}, "used (answer): says the text is loaded, from India Code, with the date, not yet read by our reviewer")
check("does not hold" not in n["text"] and "Official text on India Code: Prevention of Money-laundering Act, 2002 (PMLA): https://indiacode.gov.in/items/" in n["text"] and "not yet read by our reviewer" in n["html"] and '<a href="https://indiacode.gov.in/items/' in n["html"],
      "used: no 'does not hold', the link is still there, the page text says it too")
n = AD.notice(PM, "answer", held=HN)
check("Recourse has loaded the official text of that Act, but the answer below does not rest on it." in n["text"] and "does not hold" not in n["text"], "unused (answer): loaded, but the answer does not rest on it")
n = AD.notice(PM, "refusal", held=HN)
check("loaded" not in n["text"] and "does not hold" not in n["text"] and n["text"].startswith("This question names the Prevention of Money-laundering Act, 2002 (PMLA). Official text"), "unused (refusal): no claim either way, the link only")
n = AD.notice(PM, "opened", held=HU)
check(n["text"].count("Recourse has not checked this area in depth") == 1 and "loaded the official text of that Act from India Code" in n["text"] and "please confirm what follows with a lawyer" in n["text"], "used (opened): the caution once, with the loaded sentence")
n = AD.notice(PM, "opened", held=HN)
check(n["text"].count("has not checked this area in depth") == 1 and "has loaded the official text" in n["text"], "unused (opened)")
MIX = AD.detect("My son is accused under the POCSO Act and the Juvenile Justice Act.")
check([a["id"] for a in MIX] == ["pocso_act_2012", "jj_act_2015"], f"two Acts found ({[a['id'] for a in MIX]})")
HM = {"pocso_act_2012": {"state": "used", "loaded_on": "2026-10-16"}}
n = AD.notice(MIX, "opened", held=HM)
check("Recourse has loaded the official text of the Protection of Children from Sexual Offences Act, 2012 (POCSO) from India Code" in n["text"] and "Recourse does not hold the text of the Juvenile Justice (Care and Protection of Children) Act, 2015"
      in n["text"] and n["text"].count("has not checked this area in depth") == 1 and n["held"] == {"pocso_act_2012": "used"}, "one Act held and one not: each is described, by name, and the caution comes once")
PB = AD.prompt_block(PM)
check(PB == AD.prompt_block(PM, held=None) == AD.prompt_block(PM, held={}) and "## Acts named in the question that are not in the material" in PB and "The text of that Act is not in the material above" in PB, "prompt_block with no held Act: the block that existed before, word for word")
pb = AD.prompt_block(PM, held=HU)
check("## Act text in the material" in pb and "not in the material above" not in pb and "A provision missing from the material does not mean that Act has none." in pb
      and "do not state any other section number, punishment, procedure or route of appeal of that Act from memory" in pb
      and 'Name each of them with the Act shown in its label (for example "Section 45 of the PMLA"), not as a BNS or BNSS section.' in pb, "prompt_block, text used: use only those sections, name the Act shown in the label, never conclude from a missing section")
pb = AD.prompt_block(PM, held=HN)
check("its text is loaded, but nothing close enough was found" in pb and "from memory" in pb and "not in the material above" not in pb, "prompt_block, text loaded but nothing found: say so in one sentence, nothing from memory")
pb = AD.prompt_block(MIX, held=HM)
check(pb.count("\n\n## ") == 2 and "## Act text in the material" in pb and "## Acts named in the question that are not in the material" in pb and "Juvenile Justice" in pb.split("## Acts named")[1], "prompt_block for two Acts: one block for each group")

# ---------------------------------------------------------------- the pipeline, end to end, with a stub model
sent = {}
REPLY = {"text": "Short answer."}


class _Msgs:
    def create(self, **kw):
        c = kw["messages"][0]["content"]
        sent["prompt"] = c if isinstance(c, str) else json.dumps(c)
        sent["calls"] = sent.get("calls", 0) + 1
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=REPLY["text"])], stop_reason="end_turn", usage=None)


CA.client = types.SimpleNamespace(messages=_Msgs())
CAT = {"v": ("in_scope", "arrest", None)}
CA.classify_scope = lambda q: CAT["v"]
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "no_match"}
CA._fetch_pilot_related_judgments = lambda *a, **k: []
import answer_cache
answer_cache.get_cached = lambda m: None
answer_cache.record_candidate = lambda *a, **k: None


def ask(question, embed, reply, category=("in_scope", "arrest", None), gate=None):
    CAT["v"] = category
    REPLY["text"] = reply
    sent.clear()
    if gate:
        os.environ["SCOPE_GATE"] = gate
    else:
        os.environ.pop("SCOPE_GATE", None)
    S._embed_query = embed
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            res = CA._answer_question_inner(question)
    finally:
        S._embed_query = boom
        os.environ.pop("SCOPE_GATE", None)
    return res, buf.getvalue()


Q_PM = "My brother was arrested by the ED. Can he get bail under section 45 of the PMLA?"
res, out = ask(Q_PM, like("PMLA", "45"), "Bail is restricted by twin conditions under Section 45 of the PMLA. Section 19 of the PMLA lets the ED arrest only for reasons it records in writing.")
p = sent.get("prompt", "")
check(res["state"] == "single_match" and any(m.get("source") == "act_shelf" for m in res["matches"]), "end to end: the question that names the PMLA reaches the answer with shelf sections")
check(not any(m.get("act") == "BNS" and m.get("section_number") == "45" for m in res["matches"]), "...and 'section 45 of the PMLA' no longer also pulls BNS section 45")
check("[PMLA Section 45, Section/Para 45]\n45. Offences to be cognizable and non-bailable." in p, "the prompt labels the section with the Act's name and gives the official text")
check("PCACT" not in p and "SCSTACT" not in p and "[PMLA Section" in p, "no internal code reaches the prompt")
check("## Act text in the material" in p and "## Acts named in the question that are not in the material" not in p, "the prompt carries the 'Act text in the material' block, not the 'not in the material' one")
check("## Hard rules (never break)" in p and "Use ONLY the legal information given below" in p, "the Hard rules block is still in the prompt, unchanged")
check("[Amendment notes printed with this section on India Code" in p and "Subs. by Act 20 of 2005, s. 7" in p and "w.e.f. 19-4-2018" in p, "the amendment notes India Code prints with a section go with it (who changed it, from when)")
check(res["response_text"].startswith("Bail is restricted by twin conditions under Section 45 of the PMLA."), "a good answer comes out unchanged")
n = res["act_notice"]
check(n["kind"] == "answer" and n["held"] == {"pmla_2002": "used"} and "has loaded the official text" in n["text"] and "does not hold" not in n["text"], f"the notice says the text was loaded and used ({n['text'][:120]})")
lines = [l for l in out.splitlines() if l.startswith("ACT_SHELF ")]
lj = json.loads(lines[0][len("ACT_SHELF "):]) if lines else {}
check(len(lines) == 1 and lj["acts"] == ["pmla_2002"] and lj["per_act"]["pmla_2002"]["named"] == ["45"] and len(lj["q"]) == 12 and Q_PM not in lines[0] and "twin" not in lines[0], "one ACT_SHELF log line: a hash of the question, the Act and the sections; never the question or the text")

res, out = ask(Q_PM, like("PMLA", "45"), "Section 45 restricts bail to the cases in which the court is satisfied that the accused is not guilty.")
check(res["response_text"].startswith("Section 45 of the PMLA restricts bail"), f"the Act's name is added by code after a bare 'Section 45' ({res['response_text'][:60]!r})")
check(sent["calls"] == 1, "...without a second paid call")
res, out = ask(Q_PM, like("PMLA", "45"), "Section 45 of the BNSS restricts bail to the cases in which the court is satisfied that the accused is not guilty.")
check(res["state"] == "single_match" and res["response_text"] is None and sent["calls"] == 2, "a section of the PMLA given another Act's name: the answer is not shown (checked twice, withheld)")

Q_PC = "A clerk wants a bribe to clear my file. What does section 7 of the PC Act say, and who must sanction a prosecution?"
res, out = ask(Q_PC, like("PCACT", "19"), "Section 7 of the Prevention of Corruption Act, 1988 makes taking an undue advantage an offence. Section 19 of the PC Act requires previous sanction.")
check("[Prevention of Corruption Act, 1988 Section 19, Section/Para 19]" in sent["prompt"] and "[Prevention of Corruption Act, 1988 Section 7, Section/Para 7]" in sent["prompt"], "the PC Act's sections are labelled with the Act's name")
check(res["response_text"].startswith("Section 7 of the Prevention of Corruption Act, 1988 makes") and sent["calls"] == 1, "both ways of naming the PC Act pass the Act-name check")
res, out = ask(Q_PC, like("PCACT", "19"), "Previous sanction is needed under Section 19 before a court takes cognizance.")
check("Section 19 of the Prevention of Corruption Act, 1988 before a court" in res["response_text"], f"a bare 'Section 19' is completed with the Act's full name ({res['response_text']!r})")
Q_SS = "He abused me by my caste name in public. Which section of the SC/ST Act applies?"
res, out = ask(Q_SS, like("SCSTACT", "3"), "Section 3 of the SC/ST Act covers this.")
check("[SC/ST Act Section 3, Section/Para 3]" in sent["prompt"] and res["response_text"] == "Section 3 of the SC/ST Act covers this." and sent["calls"] == 1, "SC/ST Act: label and name check")
res, out = ask(Q_SS, like("SCSTACT", "3"), "Section 3 of the Scheduled Castes and the Scheduled Tribes (Prevention of Atrocities) Act, 1989 covers this.")
check(sent["calls"] == 1 and res["response_text"].startswith("Section 3 of the Scheduled Castes"), "SC/ST Act: the full name passes")
res, out = ask(Q_SS, like("SCSTACT", "3"), "Section 3 covers this.")
check(res["response_text"] == "Section 3 of the SC/ST Act covers this.", f"SC/ST Act: a bare section is completed ({res['response_text']!r})")
Q_PO = "My son is accused under POCSO of touching a girl. What is section 7 of the POCSO Act and what does section 8 say?"
res, out = ask(Q_PO, like("POCSO", "7"), "Section 7 of the POCSO Act defines sexual assault and section 8 of the POCSO Act punishes it.")
check(sent["calls"] == 1 and "[POCSO Act Section 7, Section/Para 7]" in sent["prompt"], "POCSO: label and name check")
Q_UA = "Is bail possible under section 43D of the UAPA?"
res, out = ask(Q_UA, like("UAPA", "43D"), "Section 43D of the Unlawful Activities (Prevention) Act, 1967 restricts bail.")
check(sent["calls"] == 1 and "[UAPA Section 43D, Section/Para 43D]" in sent["prompt"], "UAPA: label, a lettered section, and the full name passes")

# other ways of writing an Act's name pass the check and are never completed again
for act, names in (("UAPA", ("UA(P) Act", "UA(P)A", "UAP Act")), ("PMLA", ("Money Laundering Act", "Money-laundering Act", "PML Act")), ("SCSTACT", ("SC/ST (PoA) Act", "S.C./S.T. Act", "SCST Act", "Atrocities Act")), ("PCACT", ("P.C. Act", "Prevention of Corruption Act")),
                   ("POCSO", ("POCSO", "Protection of Children from Sexual Offences (POCSO) Act"))):
    pat = CA._shelf_name_pattern(act)
    check(all(pat.search(f"Section 7 of the {n}") for n in names) and all(CA._add_missing_acts(f"Section 7 of the {n} applies.", ["7"], {"7": act}) == f"Section 7 of the {n} applies." for n in names), f"{act}: {', '.join(names)} are accepted as the Act's name and are not completed again")
check(not AD.detect("What does the UA(P) Act say about bail?") and not AD.detect("What does the SC/ST (PoA) Act say?"), "...but answer_names do not make the Directory detect anything (it does not know these spellings; adding them would be a Directory change for Mr. Advocate to approve)")

# a number given to one shelf Act is never completed with another Act's name
check(CA._add_missing_acts("Section 19 of the PMLA lets the ED arrest.", ["19"], {"19": "PCACT"}) == "Section 19 of the PMLA lets the ED arrest.", "a mention that already names the PMLA is not completed with the PC Act's name")
check(CA._add_missing_acts("Section 3 under the SC/ST Act applies.", ["3"], {"3": "PMLA"}) == "Section 3 under the SC/ST Act applies." and CA._add_missing_acts("Section 7, of POCSO, defines it.", ["7"], {"7": "PCACT"}) == "Section 7, of POCSO, defines it.",
      "...also 'under the SC/ST Act' and 'of POCSO'")
check(CA._add_missing_acts("Section 19 lets the ED arrest.", ["19"], {"19": "PMLA"}) == "Section 19 of the PMLA lets the ED arrest.", "a bare number is completed with the Act it was retrieved under")
res, out = ask(Q_PC, like("PCACT", "19"), "Section 19 of the PMLA requires previous sanction before a court takes cognizance.")
check(res["state"] == "single_match" and res["response_text"] is None and sent["calls"] == 2, "end to end: a PC Act section given another shelf Act's name: the answer is withheld after the second try, not garbled")

# a shelf Act and a BNSS section in one answer (the numbers collide: both have a section 19)
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "single_match", "matches": [{"type": "statute", "act": "BNSS", "section_number": "35", "text": "35. When police may arrest without warrant.", "source": "semantic", "all_variants": {}}], "judgment_matches": []}
res, out = ask(Q_PM, like("PMLA", "45"), "Section 35 of the BNSS lets the police arrest, but for money laundering Section 45 of the PMLA restricts bail.")
check(sent["calls"] == 1 and res["response_text"].startswith("Section 35 of the BNSS") and {m["act"] for m in res["matches"] if m.get("section_number")} >= {"BNSS", "PMLA"}, "library and shelf sections together: both Acts' names pass")
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "no_match"}

# nothing close enough
res, out = ask("Under the PMLA, what are the rules for adopting a child?", ZERO, "The material does not cover adoption.")
check(res["state"] == "no_match", "a question that names the PMLA but for which nothing on the shelf is close: no_match, as any question with nothing found")
res, out = ask("Under the PMLA, what are the rules for adopting a child?", ZERO, "The material does not cover adoption.", category=("adjacent_uncovered", "adoption", None), gate="open")
check(res["state"] == "no_match" and res["act_notice"]["held"] == {"pmla_2002": "unused"} and "does not hold" not in res["act_notice"]["text"], "...and its notice does not say the Act is not held")

# the topic bar open: a POCSO question
Q_OPEN = "My nephew was arrested under the POCSO Act. What happens at the trial?"
res, out = ask(Q_OPEN, like("POCSO", "35"), "The trial must be completed within a year under Section 35 of the POCSO Act.", category=("adjacent_uncovered", "A special law.", None), gate="open")
p = sent["prompt"]
check(res["state"] == "single_match" and res["act_notice"]["kind"] == "opened" and res["act_notice"]["held"] == {"pocso_act_2012": "used"} and res["act_notice"]["text"].count("has not checked this area in depth") == 1, "topic bar open: the notice is of kind 'opened', says the text is loaded, carries the caution once")
check("## Scope note -- this question is outside the criminal-procedure library" in p and "(for example TADA, the Prevention of Corruption Act, UAPA, or a civil, tax or company law)" in p and "(for example TADA, the Prevention of Corruption Act, POCSO, UAPA" not in p,
      "the scope note's examples of Acts that are not in the material no longer list POCSO when POCSO's text is in the material")
check(CA._open_topic_block("x") == "" and CA._OPEN_TOPIC_BLOCK.count("(for example TADA, the Prevention of Corruption Act, POCSO, UAPA, or a civil, tax or company law)") == 1, "the scope note itself is unchanged")
os.environ["SCOPE_GATE"] = "open"
CA._open_topic_start("q", "r")
check(CA._open_topic_block("q") == CA._OPEN_TOPIC_BLOCK and CA._open_topic_block("q", None) == CA._OPEN_TOPIC_BLOCK and CA._open_topic_block("q", []) == CA._OPEN_TOPIC_BLOCK, "the scope note without shelf text: byte for byte as before")
held_pc = S.search("q", [{"id": "pc_act_1988"}], embed_fn=like("PCACT", "19"))["matches"]
check("(for example TADA, POCSO, UAPA, or a civil, tax or company law)" in CA._open_topic_block("q", held_pc), "...and with PC Act text in the material, the PC Act leaves the examples")
os.environ.pop("SCOPE_GATE")
CA._open_topic_reset()

# a question about TADA: no shelf, the notice and the prompt are the Directory's own
res, out = ask("My brother was convicted by a TADA Designated Court. What can he argue in his appeal?", like("PMLA", "45"), "Short answer.", category=("adjacent_uncovered", "TADA", None), gate="open")
check(res["state"] in ("no_match", "single_match") and "act_notice" in res and "held" not in res["act_notice"] and "does not hold the text of that Act" in res["act_notice"]["text"] and "ACT_SHELF" not in out, "an Act with no shelf (TADA): the notice says Recourse does not hold it; no shelf log line")

# the switch off: nothing is different
os.environ.pop("ACT_SHELF")
res, out = ask(Q_PM, like("PMLA", "45"), "Short answer.")
check(res["state"] == "single_match" and not any(m.get("source") == "act_shelf" for m in res["matches"]) and "ACT_SHELF" not in out and res["act_notice"]["text"].startswith("This question also names the Prevention of Money-laundering Act, 2002 (PMLA). Recourse does not hold the text of that Act")
      and "held" not in res["act_notice"], "ACT_SHELF off: no shelf section, no shelf log line, the notice that existed before the shelf")
check(any(m.get("act") == "BNS" and m.get("section_number") == "45" for m in res["matches"]), "ACT_SHELF off: 'section 45 of the PMLA' still pulls BNS section 45, exactly as it did before the shelf existed")
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "single_match", "matches": [{"type": "statute", "act": "BNSS", "section_number": "35", "text": "35. When police may arrest without warrant.", "source": "semantic", "all_variants": {}}], "judgment_matches": []}
res, out = ask(Q_PM, like("PMLA", "45"), "Short answer.", category=("adjacent_uncovered", "x", None), gate="open")
check(res["state"] == "single_match" and "## Acts named in the question that are not in the material" in sent["prompt"] and "## Act text in the material" not in sent["prompt"] and "(for example TADA, the Prevention of Corruption Act, POCSO, UAPA, or a civil, tax or company law)" in sent["prompt"]
      and res["act_notice"]["kind"] == "opened" and "does not hold the text of that Act" in res["act_notice"]["text"] and "held" not in res["act_notice"], "ACT_SHELF off: an opened question gets the old block and the old scope note in its prompt, and the old notice")
CA._find_relevant_sections_for_turn = lambda cur, full, **kw: {"state": "no_match"}
os.environ["ACT_SHELF"] = "on"

# ---------------------------------------------------------------- the pieces around the search
BNS45 = {"act": "BNS", "section_number": "45", "text": "45. Abettor.", "source": "explicit_section_ref", "all_variants": {}}
BNS3 = dict(BNS45, section_number="3", text="3. General explanations.")
OTHER = {"act": "BNSS", "section_number": "45", "text": "x", "source": "semantic"}
drop = CA._drop_sections_claimed_by_shelf
q = "Can he get bail under section 45 of the PMLA?"
check(drop([BNS45], q, q) == [], "'section 45 of the PMLA' is not BNS 45: the explicit BNS match is dropped")
q = "What are sections 3 of POCSO and section 3 of the BNS?"
check(drop([BNS3], q, q) == [BNS3], "'section 3 of POCSO ... section 3 of the BNS': the number is also put next to the BNS, so the BNS match stays")
q = "What is section 45 of the BNS?"
check(drop([BNS45], q, q) == [BNS45], "a question that names no shelf Act: nothing dropped")
q = "Can he get bail under section 45 of the PMLA?"
check(drop([BNS45, OTHER], q, q) == [OTHER] and drop([], q, q) == [], "only the explicit-reference BNS match is dropped; others stay; an empty list is fine")
os.environ.pop("ACT_SHELF")
check(drop([BNS45], q, q) == [BNS45], "ACT_SHELF off: nothing is dropped, as before")
os.environ["ACT_SHELF"] = "on"
os.environ["ACT_DIRECTORY"] = "off"
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    S._embed_query = like("PMLA", "45")
    gone = CA._act_shelf_matches(Q_PM, Q_PM)
    S._embed_query = boom
check(gone == [] and buf.getvalue() == "" and drop([BNS45], q, q) == [BNS45], "ACT_DIRECTORY=off turns the shelf off too (the Directory is what finds the Act in the question)")
os.environ.pop("ACT_DIRECTORY")
# a follow-up message in a conversation: the Act came from the history, the sections are looked up for the current message
full = "Earlier the person said: my brother was arrested by the ED under the PMLA.\n\nNow the person says: can he get bail?"
cur = CA._extract_current_message(full)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    S._embed_query = like("PMLA", "45")
    got = CA._act_shelf_matches(full, cur)
    S._embed_query = boom
check(cur == "can he get bail?" and got and got[0]["section_number"] == "45" and got[0]["retrieval"] == "meaning" and "ACT_SHELF" in buf.getvalue(), f"a follow-up: the Act is found from the history, the sections are searched with the current message ({cur!r})")
# an Act found only by a phrase ('looks like it is about')
LK = "My uncle was called by the Enforcement Directorate about a money laundering case. What should he do?"
check([(a["id"], a["how"]) for a in AD.detect(LK)] == [("pmla_2002", "likely")], "a question that only looks like it is about the PMLA is found by phrase")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    S._embed_query = like("PMLA", "50")
    got = CA._act_shelf_matches(LK, LK)
    S._embed_query = boom
check(got and got[0]["section_number"] == "50", "...and gets the shelf's sections")
n = AD.notice(AD.detect(LK), "answer", held=HU)
check(n["text"].startswith("This question also looks like it is about the Prevention of Money-laundering Act, 2002 (PMLA). Recourse has loaded"), "...and the notice keeps its 'looks like it is about' wording")

# ---------------------------------------------------------------- the page, WhatsApp, the PDF
from streamlit.testing.v1 import AppTest
import whatsapp_formatter as WF
import answer_pdf as AP

SHELF_MS = S.search("q", [{"id": "pmla_2002"}], embed_fn=like("PMLA", "45"))["matches"]
NOTE = AD.notice(PM, "answer", held=HU)
STUB = {"v": None}


def stub(question, inline_domains=frozenset(), audience=None, channel=None):
    return STUB["v"]


CA.answer_question = stub


def page(result):
    STUB["v"] = result
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.text_area(key="text").set_value("Can my brother get bail under the PMLA?").run()
    [b for b in at.button if "Check my situation" in b.label][0].click().run()
    return at, [m.value for m in at.markdown]


at, vals = page({"state": "single_match", "response_text": "Bail is restricted by Section 45 of the PMLA.", "matches": SHELF_MS, "situation_detected": False, "act_notice": NOTE})
check(not at.exception and any("**PMLA Section 45**" in v for v in vals), f"page: 'Read the source' heads the section with the Act's name, not its code (exception={at.exception})")
check(any(f'<p class="r-foot">Official text from India Code, loaded {LOADED_LABEL}; not yet read by our reviewer' in v and "the whole Act on India Code" in v and "https://indiacode.gov.in/act/" in v for v in vals), "page: a line under it says where the text is from, when it was loaded and that no reviewer has read it, with a link")
check(any("shortened here" in v for v in vals), "page: a section longer than the excerpt says that it is shortened")
check(any("has loaded the official text of that Act from India Code" in v for v in vals) and not any("does not hold" in v for v in vals), "page: the notice above the answer")
at, vals = page({"state": "single_match", "response_text": "Bail is restricted by Section 3 of the Act.", "matches": [{"type": "statute", "act": "BNSS", "section_number": "3", "text": "3. Definitions.", "source": "semantic", "all_variants": {}}], "situation_detected": False})
check(not at.exception and any("**BNSS Section 3**" in v for v in vals) and not any("Official text from India Code" in v for v in vals), "page: a BNSS section is headed and shown as before, with no shelf caption")
msgs = WF.format_answer_for_whatsapp({"state": "single_match", "response_text": "Short answer.", "act_notice": NOTE, "matches": SHELF_MS})
check(msgs[0] == NOTE["text"] and "not yet read by our reviewer" in msgs[0], "WhatsApp: the notice is the first message")
check(AP._shelf_act_name("PCACT") == "Prevention of Corruption Act, 1988" and AP._shelf_act_name("SCSTACT") == "SC/ST Act" and AP._shelf_act_name("BNS") is None, "PDF: the heading uses the Act's name for a shelf Act and nothing for any other code")
import fitz
pc_ms = S.search("q", [{"id": "pc_act_1988"}], embed_fn=like("PCACT", "19"))["matches"]
rec = AP.record_from_result("Is sanction needed for a PC Act prosecution?", {"state": "single_match", "response_text": "Previous sanction is needed under Section 19 of the Prevention of Corruption Act, 1988 before a court takes cognizance.",
                                                                         "matches": pc_ms, "situation_detected": False})
pdf_bytes, pdf_report = AP.build_verified_pdf([rec])
pdf_txt = " ".join("\n".join(pg.get_text() for pg in fitz.open(stream=pdf_bytes, filetype="pdf")).split())
check([(x["act"], x["section_number"]) for x in rec["statutes"]] == [("PCACT", "19")] and pdf_report.get("ok") and "Section 19 of the Prevention of Corruption Act, 1988" in pdf_txt,
      "PDF of the answer: a shelf section is listed among the sources under the Act's name, and the completeness check passes")
check(CA._shelf_display("PMLA") == "PMLA" and CA._shelf_display("BNS") is None and CA._shelf_name_pattern("BNS") is None and CA._shelf_name_pattern("PMLA").search("the Prevention of Money-laundering Act, 2002"), "chat_assistant's lookups: shelf codes only")

# ---------------------------------------------------------------- the gold set stays frozen
import hashlib
gold = json.load(open(os.path.join(S.SHELF_DIR, "eval_questions.json"), encoding="utf-8"))
body = json.dumps(gold["questions"], sort_keys=True, ensure_ascii=False)
check(hashlib.sha256(body.encode("utf-8")).hexdigest() == gold["questions_sha256"] and gold["questions_sha256"].startswith("8fe6280a105d"), "the retrieval gold set is unchanged since it was frozen (committed before the first run)")
miss = [(q["id"], s) for q in gold["questions"] for s in q["expected"] + q["also_ok"] if s not in SH["acts"][q["act_key"]]["by_num"] or SH["acts"][q["act_key"]]["by_num"][s].get("omitted")]
check(not miss, f"every section the gold set expects exists on the shelf and is not a stub ({miss[:3]})")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
