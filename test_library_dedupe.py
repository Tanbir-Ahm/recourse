"""test_library_dedupe.py -- a judgment the reviewed library already supplies for an answer is not handed over a second time as a "wider search" passage and is never labelled "(from a wider search, not independently
verified)" (FOLLOW_UPS 2cl/2cm: Pankaj Bansal was in the library AND came again from the wider search, so the answer called its own library case unverified while the table beside it said "No adverse later judgment found").
Fully offline and free: a function stands in for the search service. Run: python -X utf8 test_library_dedupe.py"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sci_search_tier as T

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def res(doc, name, date, text="Arrest is not to be made routinely.", para="9", court="Supreme Court of India"):
    return {"rank": doc, "doc": doc, "case_name": name, "date": date, "paragraph": para, "link": f"https://x.example/{doc}.pdf", "link_kind": "court_archive_pdf", "text": text,
            "name_to_review": False, "citations": {}, "court": court}


PANKAJ = res(1, "Pankaj Bansal v. Union of India & Ors.", "2023-10-03", "The grounds of arrest must be furnished in writing to the arrested person.")
ARNESH = res(2, "Arnesh Kumar v. State of Bihar", "2014-07-02", "Arrest is not to be made routinely.")
OTHER_YEAR = res(3, "Pankaj Bansal v. Union of India & Ors.", "1999-01-05", "A different decision of the same parties.")
LIB = [{"type": "judgment", "case_name": "Pankaj Bansal v Union of India", "citation": "2023 INSC 866", "paragraph_number": "29", "text": "x", "score": 0.5},
       {"type": "statute", "act": "BNSS", "section_number": "480", "text": "y"}]                                                     # a statute match has no case name


def feed(results, question="grounds of arrest in writing", exclude=None):
    found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": results}
    saved, saved_mode = T.search, os.environ.get("SCI_SEARCH_MODE")
    T.search = lambda *a, **k: found
    os.environ["SCI_SEARCH_MODE"] = "feed"
    os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
    out = io.StringIO()
    try:
        T.reset()
        with contextlib.redirect_stdout(out):
            block = T.feed_block(question, exclude_names=exclude) if exclude is not None else T.feed_block(question)
        return block, [c["case_name"] for c in T._LOCAL.cases], out.getvalue()
    finally:
        T.search = saved
        if saved_mode is None:
            os.environ.pop("SCI_SEARCH_MODE", None)
        else:
            os.environ["SCI_SEARCH_MODE"] = saved_mode


# ---- the helpers
check(T.library_keys(LIB) == [("Pankaj Bansal v Union of India", "2023")], "library_keys: judgments only, the year from the citation")
check(T.library_keys([{"case_name": "A v B", "citation": "(2014) 8 SCC 273"}, {"case_name": "C v D", "citation": "AIR 1978 SC 597"}, {"case_name": "E v F"}, {"case_name": "G v H", "year": 2005}, None, "x"])
      == [("A v B", "2014"), ("C v D", "1978"), ("E v F", None), ("G v H", "2005")], "library_keys: SCC and AIR citations, no citation, a year field; junk is skipped")
check(T.library_keys(None) == [] and T.library_keys([]) == [], "library_keys: nothing in, nothing out")
sk = T._library_skips(T.library_keys(LIB))
check(T.is_library_case("Pankaj Bansal v. Union of India & Ors.", "2023-10-03", sk), "the same case under the search service's longer name is recognised")
check(not T.is_library_case("Pankaj Bansal v. Union of India & Ors.", "1999-01-05", sk), "the same parties in another year are another decision")
check(T.is_library_case("Pankaj Bansal v. Union of India & Ors.", None, sk) and T.is_library_case("Pankaj Bansal v. Union of India & Ors.", "", sk), "no date on the wider-search side: the names decide")
check(not T.is_library_case("Arnesh Kumar v. State of Bihar", "2014-07-02", sk) and not T.is_library_case("Pankaj Kumar v. Union of India", "2023-01-01", sk), "a different case is not recognised")
check(not T.is_library_case("Pankaj Bansal v. Union of India", "2023-10-03", ()) and not T.is_library_case(None, None, sk), "no skips, or no name: never true")
check(T._library_skips(["A v B", ("C v D", 2014), "", None, ("", "2000")]) == (("A v B", None), ("C v D", "2014")), "_library_skips: strings and pairs, empties dropped, a stable tuple")

# ---- the feed
block0, cases0, _ = feed([PANKAJ, ARNESH])
check(cases0 == ["Pankaj Bansal v. Union of India & Ors.", "Arnesh Kumar v. State of Bihar"], "without exclusions the feed is what it was (both cases)")
block1, cases1, log1 = feed([PANKAJ, ARNESH], exclude=T.library_keys(LIB))
check(cases1 == ["Arnesh Kumar v. State of Bihar"], f"a library case is left out of the feed ({cases1})")
check("Pankaj Bansal" not in block1 and "Arnesh Kumar" in block1, "and out of the prompt text")
check('SCI_FEED_LIBRARY {"left_out": ["Pankaj Bansal v. Union of India & Ors."]}' in log1, "one log line names what was left out")
block2, cases2, _ = feed([PANKAJ, OTHER_YEAR, ARNESH], exclude=T.library_keys(LIB))
check([c for c in cases2] == ["Pankaj Bansal v. Union of India & Ors.", "Arnesh Kumar v. State of Bihar"] and "A different decision of the same parties" in block2, "another year's decision of the same parties stays in the feed")
block3, cases3, log3 = feed([PANKAJ], exclude=T.library_keys(LIB))
check(block3 == "" and cases3 == [] and "nothing usable" in log3, "when every wider-search case is already in the library the feed is empty (as it is when nothing came back)")
block4, cases4, _ = feed([PANKAJ, ARNESH], exclude=[])
check(cases4 == cases0 and block4 == block0, "an empty exclusion list changes nothing, byte for byte")
block5, _c, _l = feed([PANKAJ, ARNESH], exclude=[("Pankaj Bansal v Union of India", "2023")])
check("Pankaj Bansal" not in block5, "a (name, year) pair works as well as library_keys")

# ---- the cache is per question AND per exclusion
calls = []
found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": [PANKAJ, ARNESH]}
saved = T.search
T.search = lambda *a, **k: (calls.append(1), found)[1]
os.environ["SCI_SEARCH_MODE"] = "feed"
os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
try:
    with contextlib.redirect_stdout(io.StringIO()):
        T.reset()
        a = T.feed_block("q", exclude_names=T.library_keys(LIB))
        b = T.feed_block("q", exclude_names=T.library_keys(LIB))
        n_same = len(calls)
        c = T.feed_block("q")
        n_other = len(calls)
        d = T.feed_block("q")
        n_again = len(calls)
finally:
    T.search = saved
    os.environ.pop("SCI_SEARCH_MODE", None)
check(a == b and n_same == 1, "the retry loop's second call (same question, same library) is served from the cache: one search")
check(c != a and "Pankaj Bansal" in c and n_other == 2, "the same question with another library list is searched again (never served the wrong block)")
check(c == d and n_again == 2, "and that is cached in turn")

# ---- attach: belt and braces
found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": [PANKAJ, ARNESH]}
T.search = lambda *a, **k: found
os.environ["SCI_SEARCH_MODE"] = "feed"
os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
text = "Pankaj Bansal v. Union of India (2023) requires the grounds of arrest in writing. Arnesh Kumar v. State of Bihar (2014) warns against routine arrest."
try:
    with contextlib.redirect_stdout(io.StringIO()):
        T.reset()
        T.feed_block("q")                                                  # the prompt was built WITHOUT exclusions (as if the library match was added later)
        r = T.attach("q", {"state": "single_match", "response_text": text, "matches": LIB})
finally:
    T.search = saved
    os.environ.pop("SCI_SEARCH_MODE", None)
names = [c["case_name"] for c in r.get("sci_related_judgments") or []]
check(names == ["Arnesh Kumar v. State of Bihar"], f"attach: a library case is not in the page's wider-search list ({names})")
check(r["response_text"].count(T.LABEL) == 1 and r["response_text"].find(T.LABEL) > r["response_text"].find("Arnesh Kumar"), "attach: only the wider-search case is labelled; the library case is not")
check("Pankaj Bansal v. Union of India (2023) requires" in r["response_text"], "attach: the library case's sentence is untouched")

# a result with no library matches behaves as before
found = {"ok": True, "as_of": "2026-10-16", "index_commit": "abc", "results": [PANKAJ, ARNESH]}
T.search = lambda *a, **k: found
os.environ["SCI_SEARCH_MODE"] = "feed"
os.environ["SCI_SEARCH_URL"] = "http://127.0.0.1:9"
try:
    with contextlib.redirect_stdout(io.StringIO()):
        T.reset()
        T.feed_block("q")
        r2 = T.attach("q", {"state": "single_match", "response_text": text})
finally:
    T.search = saved
    os.environ.pop("SCI_SEARCH_MODE", None)
check(r2["response_text"].count(T.LABEL) == 2 and len(r2["sci_related_judgments"]) == 2, "attach: with no library matches both cases are wider-search cases, as before")

# ---- the engine's call site
import chat_assistant as CA

seen = {}
real = T.feed_block


def spy(question, exclude_names=None):
    seen["exclude"] = exclude_names
    return ""


T.feed_block = spy


class _Boom:                                                                # a client whose call fails after the prompt is built: only the call site is under test
    class messages:
        @staticmethod
        def create(*a, **k):
            raise RuntimeError("stop")


saved_client = CA.client
CA.client = _Boom()
try:
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            CA.generate_grounded_response("q", "material", matches=LIB)
        except Exception:  # noqa: BLE001
            pass
finally:
    T.feed_block = real
    CA.client = saved_client
check(seen.get("exclude") == [("Pankaj Bansal v Union of India", "2023")], f"generate_grounded_response hands feed_block the library cases of its own matches ({seen.get('exclude')})")

# ---- a generic second party ('Union of India') does not carry a label to another case that has the same respondent
# (found with real data on 2026-10-26: 'Pankaj Bansal v. Union of India' got the label of the wider-search case 'Vijay Madanlal Choudhary & Ors v. Union of India & Ors')
VMC = "Vijay Madanlal Choudhary & Ors v. Union of India & Ors"
TXT = "Pankaj Bansal v. Union of India (2023) held that the grounds of arrest must be furnished in writing."
check(T._locate(TXT, VMC, []) is None, "_locate: another case's respondent ('Union of India') is not a mention of the case")
check(T._locate("Pankaj Bansal v. Union of India & Ors.", "Pankaj Bansal v. Union of India & Ors.", []) is not None, "_locate: the case itself is still found by its full name")
sp = T._locate("Nikesh Shah v. Union of India held that x.", "Nikesh Tarachand Shah v. Union of India", [])
check(sp is not None, "_locate: a shortened first party (Nikesh Shah) still finds the case through its respondent")
sp = T._locate("In Vijai Madanlal Choudary v. Union of India the Court said x.", VMC, [])
check(sp is not None, "_locate: a misspelt first party still finds the case")
check(T._locate("Sadhwi Pragya v. State of Maharashtra said y.", "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", []) is not None, "_locate: a shortened first party with a 'State of' respondent")
check(T._locate("Ram Kumar v. State of Maharashtra said y.", "Sadhwi Pragyna Singh Thakur v. State of Maharashtra", []) is None, "_locate: a different case against the same State is not a mention of it")
check(T._first_party_agrees("Pankaj Bansal v. Union of India", 17, "Vijay Madanlal Choudhary & Ors") is False and T._first_party_agrees("Pankaj Bansal v. Union of India", 17, "Pankaj Bansal") is True and T._first_party_agrees("x v. Union of India", 5, "") is True, "_first_party_agrees")
out = T.label_fed_cases(TXT, [{"case_name": VMC}])
check(out == TXT, "label_fed_cases: the answer names another case against the Union of India: no label is added")
out2 = T.label_fed_cases(TXT + " Vijay Madanlal Choudhary v. Union of India is also relevant.", [{"case_name": VMC}])
check(out2.count(T.LABEL) == 1 and out2.find(T.LABEL) > out2.find("Vijay Madanlal"), "label_fed_cases: the case that is named gets its label, after its own name")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL PASSED")
