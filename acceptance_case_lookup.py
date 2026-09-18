"""Real-world acceptance test for the WhatsApp CASE: feature.

Unlike test_case_lookup.py (fake data), this uses the REAL shipped title index
and the REAL Vaquill dataset over the network. Only the WhatsApp send is
captured instead of sent, and state is written to a throwaway DB.
Takes a few minutes (a real fetch is ~20-50s). Run: python -X utf8 acceptance_case_lookup.py
"""
import io, os, re, sys, tempfile, time

import case_lookup
import whatsapp_bot

case_lookup.STATE_PATH = os.path.join(tempfile.mkdtemp(), "state.db")
sent, docs = [], []
whatsapp_bot.send_whatsapp_message = lambda p, m, *a, **k: sent.append(m) or True
whatsapp_bot.send_whatsapp_document = lambda p, url, fn, caption=None: docs.append((url, fn, caption)) or True
whatsapp_bot.WHATSAPP_PUBLIC_BASE_URL = "https://example.test"

fails = []
def check(ok, msg):
    print(("[PASS] " if ok else "[FAIL] ") + msg)
    if not ok: fails.append(msg)

def say(phone, text):
    sent.clear()
    out = whatsapp_bot.handle_incoming_message(phone, text)
    return " ".join(out) if isinstance(out, list) else str(out)

def latest(store):
    return max(store.values(), key=lambda e: e[1])[0]

def pdf_text(b):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(b)).pages)

# 1. Real search: landmark cases resolve to the right judgment
for q, must in [("Arnesh Kumar v State of Bihar", "ARNESH"), ("D.K. Basu", "BASU"),
                ("Maneka Gandhi", "MANEKA"), ("Lalita Kumari", "LALITA")]:
    r = case_lookup.search_cases_detailed(q)
    check(bool(r["cases"]) and must in r["cases"][0]["title"].upper(), f"real index finds '{q}'")

# 2. Honest failures
out = say("9001", "CASE: Zxqvw Plmokn Qwerty")
check(not docs and "doesn't mean it doesn't exist" in out, "nonsense name -> honest 'not found', no file")
out = say("9001", "CASE: ")
check(not docs, "empty command sends no file")
out = say("9001", 'CASE: " OR 1=1 -- ) AND (')
check(not docs, "hostile punctuation doesn't crash or send a file")
out = say("9001", "case of bail after 14 days arrest?")
check(not docs and "found these" not in out.lower(), "a normal question starting with 'case' is NOT treated as a command")

# 3. Full real flow: command -> (menu ->) file, with real fetch
docs.clear()
t = time.time()
out = say("9002", "CASE: Arnesh Kumar v State of Bihar")
print(f"      first request took {time.time()-t:.0f}s")
if not docs:  # got a menu instead; pick the first option
    out = say("9002", "1")
check(len(docs) == 1 and docs[0][1].lower().endswith(".pdf"), "PDF delivered for Arnesh Kumar")
pdf = latest(whatsapp_bot._PENDING_PDFS) if whatsapp_bot._PENDING_PDFS else b""
check(pdf[:4] == b"%PDF" and len(pdf) > 10_000, f"PDF is real ({len(pdf)//1024} KB)")
txt = pdf_text(pdf)
if txt is None:
    print("[SKIP] pypdf not installed -- open the PDF yourself; checks below skipped")
else:
    check("ARNESH" in txt.upper() and "41" in txt, "PDF text contains the case name and Section 41")
    check("NOT been independently verified" in " ".join(txt.split()), "disclaimer is embedded in the file itself")
    check(not re.search(r"[ऀ-෿]", txt), "no Hindi/other-language junk in the English PDF")

# 4. Word format + cache speed
docs.clear()
t = time.time()
out = say("9003", "CASE: Arnesh Kumar v State of Bihar word")
if not docs: out = say("9003", "1")
dt = time.time() - t
check(len(docs) == 1 and docs[0][1].lower().endswith(".docx"), "Word file delivered")
check(dt < 8, f"second request served from cache fast ({dt:.1f}s)")
dx = latest(whatsapp_bot._PENDING_DOCX) if whatsapp_bot._PENDING_DOCX else b""
check(dx[:2] == b"PK" and len(dx) > 10_000, "Word file is a real .docx")

# 5. Rate limit
case_lookup.SEARCH_DAILY_LIMIT = 2
say("9004", "CASE: Maneka Gandhi"); say("9004", "CASE: Maneka Gandhi")
out = say("9004", "CASE: Maneka Gandhi")
check("limit" in out.lower() or "today" in out.lower(), "3rd search over the daily cap is politely refused")

print("\n" + ("ALL ACCEPTANCE CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
