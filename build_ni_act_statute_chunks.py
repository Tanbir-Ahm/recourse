"""
build_ni_act_statute_chunks.py -- sources the 19 cheque-bounce-relevant
Negotiable Instruments Act, 1881 sections from India Code's public data
API (indiacode.gov.in) and saves them in the SAME chunk shape
embed_corpus.py already expects for BNS/BNSS/IT Act
(chunks/*.json: list of {act_name, citation, section_number, text,
source_url, source_type}).

WHY THIS SOURCE, NOT A SINGLE PDF: the NI Act is from 1881 and has been
amended many times since (Chapter XVII in 1988, Section 142 in 2015,
Section 143A in 2018). A single scanned/gazette PDF risks being an
outdated snapshot -- confirmed for real during sourcing: a PDF found at
cdnbbsr.s3waas.gov.in was missing Section 143A entirely. India Code's
NEW system (indiacode.gov.in, migrated from the retired indiacode.nic.in)
catalogs the Act section-by-section as individual live records, each
carrying the CURRENT in-force text with inline amendment brackets
(e.g. "[a term which may be extended to two years]") -- confirmed by
inspecting Section 138's real API response.

WHY THE API AND NOT THE WEBSITE ITSELF: the site's front end is a
client-side Angular app (no server-rendered HTML for a plain fetch to
read); the same content is available as plain JSON from the underlying
public discovery API, which is what this script reads.

Only pulls the ONE central-government record set for this Act
(act_id AC_CEN_2_33_00042_00042_1523271998701) -- confirmed by
inspection there is a decoy record (a Chhattisgarh state-adoption entry
sharing the same title) that must be excluded.

Only the 19 sections the cheque_bounce domain actually uses are pulled,
matching this project's standing discipline (see PWDVA: 11 of ~30+
possible sections, not the whole Act) of sourcing only what a domain
uses, not a whole Act indiscriminately.
"""

import json
import os
import re
import time

import requests

API_URL = "https://indiacode.gov.in/server/api/discover/search/objects"
ACT_ID = "AC_CEN_2_33_00042_00042_1523271998701"
ACT_NAME = "Negotiable Instruments Act 1881"
CITATION = "Act No. 26 of 1881"
OUTPUT_PATH = os.path.join("chunks", "negotiable_instruments_act_1881_chunks.json")

TARGET_SECTIONS = {"6", "20", "30", "31", "87", "118", "138", "139", "140", "141", "142", "142A", "143", "143A", "144", "145", "146", "147", "148"}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# QA-confirmed typos in India Code's OWN database for Section 118, found
# 2026-09-18 by cross-checking against Indian Kanoon
# (https://indiankanoon.org/doc/517539/) and other independent secondary
# sources -- both clauses read correctly everywhere else. These are
# genuine data-entry errors in the primary source itself, not something
# introduced by this script's HTML cleaning. Corrected here (not by
# hand-editing the output JSON) so a re-run doesn't silently reintroduce
# them, and so the correction is documented rather than invisible.
_KNOWN_SOURCE_TYPOS = {
    "118": [
        ("naturity", "maturity"),
        ("instrutment", "instrument"),
    ],
}


def _apply_known_corrections(section_number: str, text: str) -> str:
    for wrong, right in _KNOWN_SOURCE_TYPOS.get(section_number, []):
        text = text.replace(wrong, right)
    return text


def _clean_html(raw_html: str) -> str:
    """Strips India Code's presentational HTML (span/hr/sup wrappers)
    down to plain, readable section text, converting <br/> and <hr/>
    into newlines so paragraph structure survives."""
    text = raw_html or ""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<hr[^>]*>", "\n", text)
    text = re.sub(r"<sup>(\d+)</sup>", r"", text)  # drop footnote-number markers
    text = re.sub(r"<[^>]+>", "", text)  # drop all remaining tags (span, etc.)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def fetch_all_records_for_act(act_id: str) -> list:
    """India Code's discover API is a full-text search, not a
    filter-by-id lookup -- searching for the act_id string itself
    reliably surfaces every record sharing it (confirmed: 158 records,
    2 pages at size=100). Pages through all of them."""
    records = []
    page = 0
    size = 100
    while True:
        resp = requests.get(
            API_URL,
            params={"query": act_id, "dsoType": "item", "size": size, "page": page},
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        sr = data["_embedded"]["searchResult"]
        objs = sr["_embedded"]["objects"]
        for o in objs:
            records.append(o["_embedded"]["indexableObject"])
        total_pages = sr["page"]["totalPages"]
        page += 1
        if page >= total_pages:
            break
        time.sleep(1)
    return records


def main():
    print(f"Fetching all India Code records sharing act_id {ACT_ID} ...")
    records = fetch_all_records_for_act(ACT_ID)
    print(f"Fetched {len(records)} total records (sections + schedules + decoys).")

    def meta(item, key):
        vals = item.get("metadata", {}).get(key)
        return vals[0]["value"] if vals else None

    chunks = []
    found_sections = set()
    for item in records:
        if meta(item, "dc.identifier.act_id") != ACT_ID:
            continue  # excludes the Chhattisgarh decoy and anything else
        if meta(item, "dc.identifier.collection") != "SECTION":
            continue
        sec_num = meta(item, "dc.identifier.section_number")
        if sec_num not in TARGET_SECTIONS:
            continue
        raw_html = meta(item, "dc.identifier.section_page_note")
        if not raw_html:
            print(f"  WARNING: section {sec_num} has no text, skipping")
            continue
        handle = item.get("handle")
        text = f"{sec_num}. {meta(item, 'dc.title')}\n{_clean_html(raw_html)}"
        text = _apply_known_corrections(sec_num, text)
        chunk = {
            "act_name": ACT_NAME,
            "citation": CITATION,
            "section_number": sec_num,
            "title": meta(item, "dc.title"),
            "text": text,
            "source_url": f"https://indiacode.gov.in/handle/{handle}",
            "source_type": "primary",
        }
        if sec_num in _KNOWN_SOURCE_TYPOS:
            chunk["qa_note"] = (
                "Source (India Code) had typos here, corrected against Indian "
                "Kanoon + a second independent source, 2026-09-18: "
                + "; ".join(f"'{w}' -> '{r}'" for w, r in _KNOWN_SOURCE_TYPOS[sec_num])
            )
        chunks.append(chunk)
        found_sections.add(sec_num)

    missing = TARGET_SECTIONS - found_sections
    if missing:
        print(f"WARNING: these target sections were NOT found: {sorted(missing)}")

    chunks.sort(key=lambda c: (len(c["section_number"]), c["section_number"]))

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(chunks)} of {len(TARGET_SECTIONS)} target sections to {OUTPUT_PATH}")
    for c in chunks:
        print(f"  Section {c['section_number']}: {c['title']} ({len(c['text'])} chars)")


if __name__ == "__main__":
    main()
