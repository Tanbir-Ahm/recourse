"""
test_full_ni_it.py -- the whole Negotiable Instruments Act, 1881 and Information Technology Act, 2000 on the Act shelf (2026-10-31): the data, the repairs made from India Code's PDF, the Directory entries (detect=false) and the
search page (a section the library does not hold comes from the shelf; where both hold it the library's card stays).  Offline and free.  Run: python -X utf8 test_full_ni_it.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["ACT_SHELF"] = "on"                      # the search page reads the shelf only when the switch is on
FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def jl(*p):
    with open(os.path.join(HERE, *p), encoding="utf-8") as fh:
        return json.load(fh)


man = {a["key"]: a for a in jl("act_shelf", "manifest.json")["acts"]}
ni = {c["section_number"]: c for c in jl("act_shelf", "ni_act_1881.json")}
it = {c["section_number"]: c for c in jl("act_shelf", "it_act_2000.json")}
check(len(ni) == 155 and man["ni_act_1881"]["text_status"] == "machine_checked" and man["ni_act_1881"]["code"] == "NIACTFULL", "NI Act: 155 sections, machine_checked, code NIACTFULL (not the library's NIACT)")
check(len(it) == 125 and man["it_act_2000"]["text_status"] == "machine_checked" and man["it_act_2000"]["code"] == "ITACTFULL", "IT Act: 125 sections, machine_checked, code ITACTFULL (not the library's ITACT)")
check(sorted(k for k, c in ni.items() if c["omitted"]) == ["2"], "NI Act: only section 2 is omitted (repealed)")
check(sorted(k for k, c in it.items() if c["omitted"]) == sorted(["20", "49", "50", "51", "52", "52A", "52B", "52C", "53", "54", "56", "66A", "91", "92", "93", "94"]), "IT Act: 16 omitted sections, including 66A")
check("Dishonour of cheque for insufficiency" in ni["138"]["title"] and "142A" in ni and "143A" in ni and "148" in ni, "NI Act: sections 138, 142A, 143A and 148 are there")
check(ni["135"]["text"].split("\n")[1].startswith("Where a promissory note"), "NI s.135: the lost first letter ('here' for 'Where') is back")
check("non-payment" in ni["103"]["text"] and "non-acceptance" in ni["108"]["text"], "NI ss.103 and 108: the lost hyphens are back")
check(ni["133"]["title"].endswith("entitled to all.") and "Drawee" in ni["7"]["title"] and "On presentment" in ni["21"]["title"], "NI ss.7, 21 and 133: titles carry the words of the PDF's headings")
check("imprisonment" not in it["68"]["text"] and "penalty which may extend to twenty-five lakh rupees" in it["68"]["text"], "IT s.68(2): the amended text (penalty up to twenty-five lakh rupees), not the old imprisonment text")
check(it["66A"]["omitted"] and "Omitted by the Jan Vishwas" in it["66A"]["text"] and "grossly offensive" not in it["66A"]["text"] and "struck down" in it["66A"]["footnotes"], "IT s.66A: the struck-down wording is not on the shelf; the omission line and India Code's footnote are")
check(it["72A"]["title"].startswith("Penalty for disclosure") and it["48"]["title"].startswith("Establishment of Appellate Tribunal"), "IT ss.72A and 48: titles follow the PDF's headings")
check("authenticating an electronic record by means of electronic signature;" in it["2"]["text"] and "authenticating an electronic record by means of digital signature" not in it["2"]["text"], "IT s.2: 'electronic signature' where the database kept 'digital signature' in that clause (other definitions still say 'digital signature', as the PDF does)")
check("addition" in it["1"]["text"] and "a ddition" not in it["1"]["text"] and "sub-section (1) of Section 70B" in it["2"]["text"], "IT ss.1 and 2: the spacing and hyphen slips are repaired")
check(all("STATE AMENDMENT" not in c["text"].upper() for c in list(ni.values()) + list(it.values())), "no State-amendment text inside a section")

d = {a["id"]: a for a in jl("acts_directory.json")["acts"]}
check(d["ni_act_1881"]["detect"] is True and d["it_act_2000"]["detect"] is True, "Directory: both entries have detect=true since 2026-11-02 (owner: 'Switch NI and IT detection on')")
check(d["ni_act_1881"]["status"]["reviewed"] is None and d["it_act_2000"]["status"]["reviewed"] is None, "Directory: neither status line is marked reviewed")

import act_directory  # noqa: E402
import act_shelf  # noqa: E402
import search_service as S  # noqa: E402

check([x["id"] for x in act_directory.detect("What does section 138 of the Negotiable Instruments Act say?")] == ["ni_act_1881"] and [x["id"] for x in act_directory.detect("Is section 66 of the Information Technology Act bailable?")] == ["it_act_2000"], "a question that names either Act is tied to the shelf copy (detection on)")
sh = act_shelf.load(refresh=True)
check(sh["acts"]["ni_act_1881"]["ok"] and sh["acts"]["it_act_2000"]["ok"], "shelf: both Acts load with fresh embeddings")

# search page: a section the library does not hold comes from the shelf; both held -> the library's card only
shelf = {k: v for k, v in sh["acts"].items() if v.get("ok")}
card = S._full_act_section(shelf, "NIACT", "9")
check(card is not None and card["act"] == "NIACTFULL" and card["held"] == "shelf" and card["section"] == "9", "search page: NI section 9 (not among the library's 19) is taken from the shelf")
check(S._full_act_section(shelf, "ITACT", "68")["act"] == "ITACTFULL" and S._full_act_section(shelf, "ITACT", "9999") is None, "search page: IT section 68 from the shelf; an absent number gives nothing")
res = S.search("section 9 negotiable instruments act", embed_fn=lambda t: [0.0] * 1024)
prov = [p for p in res["provisions"] if p["section"] == "9"]
check(prov and prov[0]["act"] == "NIACTFULL" and not any("is not one of the" in n for n in res["notes"]), "search page: 'section 9 NI Act' now shows the section and no 'not one of the 19 sections' note")
res = S.search("section 138 negotiable instruments act", embed_fn=lambda t: [0.0] * 1024)
acts138 = [p["act"] for p in res["provisions"] if p["section"] == "138"]
check(acts138 == ["NIACT"], f"search page: section 138 (held by both) shows the library's card only ({acts138})")
dd = S._drop_shelf_duplicates([{"act": "NIACT", "section": "138"}, {"act": "NIACTFULL", "section": "138"}, {"act": "NIACTFULL", "section": "139"}, {"act": "PCACT", "section": "17"}])
check([(p["act"], p["section"]) for p in dd] == [("NIACT", "138"), ("NIACTFULL", "139"), ("PCACT", "17")], "duplicate dropping: only a shelf copy of a section the library also shows is dropped")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")
