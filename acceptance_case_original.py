"""Real-data acceptance for the original-PDF path: the REAL index + the REAL open S3 bucket.
Landmark cases plus a random sample across all eras; reports how many resolve to a VERIFIED original file.
Run: python -X utf8 acceptance_case_original.py [sample_size]   (needs internet; a few minutes)"""
import collections
import random
import re
import sqlite3
import sys
import time

import case_lookup
import case_original

SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 40
LANDMARKS = ["Kesavananda Bharati v State of Kerala", "Maneka Gandhi v Union of India", "D.K. Basu v State of West Bengal",
             "Lalita Kumari v Government of Uttar Pradesh", "Rangappa v Sri Mohan", "Rakesh Kumar Paul v State of Assam",
             "Bir Singh v Mukesh Kumar", "Satender Kumar Antil v Central Bureau of Investigation", "Pankaj Bansal v Union of India",
             "Prabir Purkayastha v State NCT of Delhi", "Vihaan Kumar v State of Haryana", "Arnesh Kumar v State of Bihar",
             "Shreya Singhal v Union of India", "Hussainara Khatoon v Home Secretary", "Bachan Singh v State of Punjab"]

results = []   # (label, year, status, MB)


def run(label, case):
    t = time.time()
    r = case_original.get_original(case)
    mb = len(r.get("bytes", b"")) / 1048576
    yr = (case.get("decision_date") or "0000")[:4]
    results.append((label, yr, r["status"], mb, time.time() - t))
    print(f"  {r['status']:11} {mb:5.1f}MB {time.time()-t:4.1f}s  {yr}  {label[:60]}   [{case.get('citation')}]")


print("== landmark cases (searched by name, as a user would)")
for name in LANDMARKS:
    hits = case_lookup.search_cases_detailed(name)["cases"]
    if not hits:
        print("  (not in the index)", name); continue
    run(name, case_lookup.get_case(hits[0]["case_id"]))

print("\n== random sample across all years")
conn = sqlite3.connect(case_lookup.INDEX_PATH)
rows = conn.execute("select case_id, title, decision_date, citation from cases").fetchall()
random.seed(20)
by_decade = collections.defaultdict(list)
for r in rows:
    by_decade[(r[2] or "0000")[:3]].append(r)
per = max(1, SAMPLE // len(by_decade))
picked = [x for d in sorted(by_decade) for x in random.sample(by_decade[d], min(per, len(by_decade[d])))]
for cid, title, date, cit in picked:
    run(title, {"case_id": cid, "title": title, "citation": cit, "decision_date": date})

print("\n== SUMMARY")
allr = results
print("statuses:", dict(collections.Counter(r[2] for r in allr)))
ok = [r for r in allr if r[2] == "ok"]
print(f"verified original found: {len(ok)} of {len(allr)} ({100*len(ok)/len(allr):.0f}%)")
print("by decade (ok/total):", {d: f"{sum(1 for r in allr if r[1][:3]==d and r[2]=='ok')}/{sum(1 for r in allr if r[1][:3]==d)}" for d in sorted({r[1][:3] for r in allr})})
print("largest file:", f"{max((r[3] for r in ok), default=0):.1f} MB", "| median time:", f"{sorted(r[4] for r in allr)[len(allr)//2]:.1f}s")
bad = [r for r in allr if r[2] == "mismatch"]
print("MISMATCHES (file found but failed name verification -> safely refused):", [(b[0][:40], b[1]) for b in bad])
