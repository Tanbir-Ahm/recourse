"""
test_second_reader.py -- the automatic, blind, different-model second reader (second_reader.py).
Fully offline and free: a fake HTTP layer stands in for Gemini, so no network call and no key are ever used.
Run: python -X utf8 test_second_reader.py
"""
import json
import sys

import add_pilot_case as apc
import second_reader as sr

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


class Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def ok(obj, thought=False):
    parts = ([{"text": "hidden reasoning", "thought": True}] if thought else []) + [{"text": json.dumps(obj)}]
    return Resp(200, {"candidates": [{"content": {"parts": parts}}], "usageMetadata": {"promptTokenCount": 10}})


def scripted(*responses):
    """A fake requests.post that returns the given responses in order and records every call."""
    calls = []
    it = iter(responses)

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "prompt": json["contents"][0]["parts"][0]["text"]})
        return next(it)
    post.calls = calls
    return post


NOSLEEP = lambda s: None
KEY = "SECRET-KEY-VALUE-123"

# ---------------------------------------------------------------- 1. the model chain and retries
post = scripted(Resp(503), ok({"a": 1}))
parsed, model, usage = sr.call_gemini("hi", models=["m1", "m2"], api_key=KEY, post=post, sleep=NOSLEEP)
check(parsed == {"a": 1} and model == "m1" and len(post.calls) == 2, "a temporary 503 'high demand' is retried on the same model, then succeeds")
post = scripted(Resp(404), ok({"a": 2}))
parsed, model, _ = sr.call_gemini("hi", models=["gone", "m2"], api_key=KEY, post=post, sleep=NOSLEEP)
check(model == "m2" and len(post.calls) == 2, "a model that is gone (404, like 2.5 Flash live) is skipped at once -- no retry -- and the next one is used")
post = scripted(Resp(503), Resp(503), Resp(503), Resp(503))
try:
    sr.call_gemini("hi", models=["m1", "m2"], api_key=KEY, post=post, sleep=NOSLEEP)
    check(False, "an exhausted chain must raise ReaderUnavailable")
except sr.ReaderUnavailable as exc:
    check("HTTP 503" in str(exc) and KEY not in str(exc), "when nothing answers it raises ReaderUnavailable, saying why, and never contains the API key")
try:
    orig = sr._api_key
    sr._api_key = lambda: None
    sr.call_gemini("hi", post=scripted())
    check(False, "no key must raise ReaderUnavailable")
except sr.ReaderUnavailable as exc:
    check("GEMINI_API_KEY" in str(exc), "no key -> ReaderUnavailable (reported as NOT a pass), not a crash")
finally:
    sr._api_key = orig
post = scripted(ok({"a": 3}))
sr.call_gemini("hi", models=["m1"], api_key=KEY, post=post, sleep=NOSLEEP)
check(post.calls[0]["headers"].get("x-goog-api-key") == KEY and KEY not in post.calls[0]["url"],
      "the key travels in a header, never in the URL (URLs end up in logs)")
fenced = Resp(200, {"candidates": [{"content": {"parts": [{"text": "```json\n{\"z\": 9}\n```"}]}}]})
check(sr.call_gemini("hi", models=["m1"], api_key=KEY, post=scripted(fenced), sleep=NOSLEEP)[0] == {"z": 9},
      "an answer wrapped in a markdown code fence is still parsed")
check(sr.call_gemini("hi", models=["m1"], api_key=KEY, post=scripted(ok({"q": 1}, thought=True)), sleep=NOSLEEP)[0] == {"q": 1},
      "the model's hidden 'thinking' part is ignored, only its answer is read")
try:
    sr.call_gemini("hi", models=["m1", "m2"], api_key=KEY,
                   post=scripted(Resp(200, {"candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]}),
                                 Resp(200, {"candidates": [{"content": {"parts": [{"text": "still not json"}]}}]})), sleep=NOSLEEP)
    check(False, "unusable answers from every model must raise")
except sr.ReaderUnavailable as exc:
    check("unusable answer" in str(exc), "a model that returns non-JSON is treated as failed, not trusted")

# ---------------------------------------------------------------- 2. the reader is BLIND: it reads the text before it ever sees our claims
TEXT = ("The Court held as follows. In order to constitute an offence of cheating, the intention to deceive should be in "
        "existence at the time when the inducement was made. The Court then quoted: \"a mere failure to keep up promise "
        "subsequently cannot be presumed as an act leading to cheating\" from an earlier case. The appeal is dismissed.")
CLAIM_TEXTS = ["Cheating needs dishonest intent when the inducement was made.", "The appeal was allowed."]
QUOTES = ["In order to constitute an offence of cheating, the intention to deceive should be in existence at the time when the inducement was made.",
          "a mere failure to keep up promise subsequently cannot be presumed as an act leading to cheating"]
blind = {"key_points": [], "final_order": "appeal dismissed", "dissent": "none"}
comp = {"claims": [], "quotes": [], "missing_important_points": []}
post = scripted(ok(blind), ok(comp))
res = sr.run_second_reader(official_text=TEXT, claims=CLAIM_TEXTS, quotes=QUOTES, api_key=KEY, post=post, sleep=NOSLEEP, models=["m1"])
check(len(post.calls) == 2, "two calls: the blind reading, then the check")
check(CLAIM_TEXTS[0] not in post.calls[0]["prompt"] and CLAIM_TEXTS[1] not in post.calls[0]["prompt"] and TEXT in post.calls[0]["prompt"],
      "BLIND: the first call contains the judgment text and NONE of our claims")
check(CLAIM_TEXTS[0] in post.calls[1]["prompt"] and "1. Cheating needs" in post.calls[1]["prompt"] and "appeal dismissed" in post.calls[1]["prompt"],
      "the second call carries the numbered claims and the reader's own earlier reading")
check("Never answer SUPPORTED without a quote" in post.calls[1]["prompt"] and "NOT the Court's own holding" in post.calls[1]["prompt"],
      "the check prompt demands a quote for every verdict and tells the reader to separate the Court's words from quoted ones")

# ---------------------------------------------------------------- 3. audit: every quote the reader gives is checked by CODE
raw = {"models": ["m1", "m2"], "usage": [None, None], "blind": {"key_points": [
           {"point": "p1", "quote": "In order to constitute an offence of cheating, the intention to deceive should be in existence"},
           {"point": "p2", "quote": "A sentence that the reader made up entirely and that appears nowhere in the judgment."}],
       "final_order": "dismissed", "dissent": "none"},
       "compare": {"claims": [
           {"id": 1, "verdict": "SUPPORTED", "reason": "yes", "quote": "the intention to deceive should be in existence at the time when the inducement was made"},
           {"id": 2, "verdict": "NOT_SUPPORTED", "reason": "the appeal was dismissed", "quote": "The appeal is dismissed."}],
           "quotes": [{"id": 1, "whose_words": "court's own reasoning", "quoted_source": ""},
                      {"id": 2, "whose_words": "quotation of an earlier case, statute or counsel", "quoted_source": "an earlier case"}],
           "missing_important_points": [{"point": "an omitted exception", "quote": "This exact sentence is not in the judgment at all, really."}]}}
audit = sr.audit_result(raw, TEXT, CLAIM_TEXTS, QUOTES, check_fn=apc.check_quote)
check(audit["claims"][0]["trusted"] and audit["supported_verified"] == 1, "a SUPPORTED verdict backed by a quote that is really in the text is trusted")
check(not audit["claims"][1]["trusted"] and audit["flagged_claims"] == [2], "a NOT_SUPPORTED verdict is flagged for a person")
check(audit["quotes_not_courts_own"] == [2] and audit["quotes"][1]["quoted_source"] == "an earlier case",
      "a quote the reader says is the Court quoting someone else is flagged, with the source (the Alpic / Pratibha Rani slip)")
check(audit["blind_quotes_not_found"] == 1, "a quote the reader INVENTED in its own blind reading is counted as not found")
check(audit["missing_points"][0]["quote_status"] == "missing", "a 'missing point' resting on an invented quote is marked as such, not trusted")

raw2 = json.loads(json.dumps(raw))
raw2["compare"]["claims"][0]["quote"] = "This supporting sentence was invented by the reader and is not in the text at all."
a2 = sr.audit_result(raw2, TEXT, CLAIM_TEXTS, QUOTES, check_fn=apc.check_quote)
check(a2["claims"][0]["verdict"] == "UNVERIFIED" and not a2["claims"][0]["trusted"] and 1 in a2["flagged_claims"],
      "a SUPPORTED verdict resting on an INVENTED quote is downgraded to UNVERIFIED -- a made-up quote cannot make a claim pass")
raw3 = json.loads(json.dumps(raw))
raw3["compare"]["claims"] = raw3["compare"]["claims"][:1]
a3 = sr.audit_result(raw3, TEXT, CLAIM_TEXTS, QUOTES, check_fn=apc.check_quote)
check(a3["claims"][1]["verdict"] == "NO_ANSWER" and 2 in a3["flagged_claims"], "a claim the reader never answered is flagged, not silently passed")

stitched_ok = "In order to constitute an offence of cheating, the intention to deceive should be in existence ... a mere failure to keep up promise subsequently cannot be presumed as an act leading to cheating"
check(sr._qstatus(stitched_ok, TEXT, apc.check_quote) in ("exact", "cosmetic"), "a quote stitched from two real passages with '...' is checked piece by piece and passes")
stitched_bad = "In order to constitute an offence of cheating, the intention to deceive should be in existence ... and then a totally invented second piece that is nowhere in the judgment"
check(sr._qstatus(stitched_bad, TEXT, apc.check_quote) == "missing", "but one invented piece cannot hide behind a real one -- the worst piece decides")

rep = "\n".join(sr.format_report(audit))
check("FLAG claim 2" in rep and "FLAG quote 2" in rep and "MISSING from the summary" in rep and "never approves anything" in rep,
      "the report lists the flags and says plainly that the reader never approves anything")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("ALL PASSED")
