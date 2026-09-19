# CASE-command usage log -- test plan

Feature: every `CASE` interaction on WhatsApp leaves exactly one row in the `case_events` table
(state database, on the Railway volume), so the feature can be measured. Also adds a gentle
"did you mean `CASE:`?" reply when someone forgets the colon.

## Definition of done
1. Every path below writes exactly one row with the right event name.
2. Logging can never break or slow a reply (fail-open) -- proven by forcing the logger to crash.
3. Reports never show a phone number; a typed query is stored truncated to 80 characters.
4. The hint only fires on "CASE <name> v <name>" -- never on an ordinary question containing "case".
5. Nothing that worked before is broken (all `test_*.py` suites pass).
6. The live trace below matches, row for row, on the real number.

## Automated checks
- `test_case_events.py` -- 29 checks, temp databases, mocked network (written before the code).
- All other `test_*.py` suites (regression).
- `acceptance_case_lookup.py` -- real index + real Vaquill data, now also checks the log.

## Live trace (run on the real number after deploy)
Send these from ONE phone, in order. Then read production back (read-only) and compare.

| # | You send | Expected reply | Expected new log rows |
|---|---|---|---|
| 1 | `CASE:` | usage help | `usage_help` |
| 2 | `CASE: Zzzz Qqqq Wwww` | "couldn't find" | `search_no_match` |
| 3 | `CASE: Arnesh Kumar v State of Bihar` | PDF | `exact_auto_send`, `doc_delivered` (pdf, cached = per state) |
| 4 | same again | PDF, much faster | `exact_auto_send`, `doc_delivered` (cached = yes) |
| 5 | `CASE: Arnesh Kumar v State of Bihar word` | Word file | `exact_auto_send`, `doc_delivered` (docx) |
| 6 | `CASE: Singh` | numbered menu | `menu_exact` |
| 7 | `2` | file for option 2 | `pick_ok`, `doc_delivered` |
| 8 | `CASE: Lata Singh v State of Bihar` | "closest matches" menu | `menu_fuzzy` |
| 9 | `9` | "reply with a number from 1 to N" | `pick_invalid` |
| 10 | `CASE Gayatri Balasamy v ISG Novasoft Technologies` | "Did you mean ... CASE: ..." | `case_hint` |
| 11 | `Can police arrest me without notice for a 3 year offence?` | normal Recourse answer | NO CASE row |

Pass = every expected row is present, in order, and nothing extra. Any mismatch is a FAIL and is
reported as such.

## Not covered by this plan (stated honestly)
- Rate-limit and failure rows are proven by the automated tests only; forcing them live would
  mean hitting the daily cap or breaking the data source in production.
- The 30-50 second first-fetch time depends on the Vaquill server and is only measured, not
  guaranteed.
