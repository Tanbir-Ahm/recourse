# Act shelf: how well does the search find the right section? (2026-10-16)

Read this before trusting any number below. The questions and the "right" sections were chosen by Claude (an AI), not by a lawyer; the run involved no answer-writing model, so it says where the search puts a section, nothing about the answers built on it.

## What was measured

- `eval_questions.json`: 75 questions, 15 per Act (PC Act, POCSO, UAPA, PMLA, SC/ST Act), half in lay wording and half in lawyers' wording. For each, Claude wrote the section(s) it judged to answer the question (`expected`) and other sections that would be a reasonable first look (`also_ok`), from the Act's own section list and text. The file was committed (`da6817a`, hash `8fe6280a105d…`) before any retrieval number existed; `eval_act_shelf.py` refuses to run if it has changed since.
- `eval_offtopic_questions.json`: 10 questions that name a shelf Act and ask for something it does not contain (committed before any score was read), to see what "nothing relevant" scores.
- The questions are embedded with voyage-law-2 as queries (as the site does) and ranked, within the question's own Act, against the section embeddings. Billed: about 2,000 tokens (a fraction of a cent). Raw results: `EVAL_RESULTS.json` (every question, rank, top-5 sections and scores).

## Results (semantic search within the Act, 75 questions)

| | first place | top 3 | top 5 | top 8 |
|---|---|---|---|---|
| the section Claude marked as the answer | 73% | 89% | 95% | 96% |
| that section or a reasonable first look (`also_ok`) | 80% | 92% | 99% | 99% |

By Act (top 5, strict): POCSO 15 of 15, PC Act 14, PMLA 14, SC/ST 14, UAPA 14. Lay wording 91%, lawyers' wording 98%. A plain keyword (BM25) ranking was worse (top 5: 80%), and fusing the two did not beat meaning alone (93%), so the shelf uses meaning alone.

**With 75 questions this can show a large problem, not rank two close methods.** The four questions whose marked section missed the top 5:

- SS02 "Is anticipatory bail available to an accused under the SC/ST Atrocities Act?" (right: s.18, which says only "Section 438 of the Code not to apply"). The statute never uses the words "anticipatory bail"; the search put it 9th of 26. This is the most litigated question about this Act, so the shelf adds a small deterministic pointer for it (see "What the numbers decided"). That pointer was added after seeing this miss, so the result for this question is not independent evidence.
- PC11 (agent who collects a bribe: marked s.12, found 7A/7/8, all reasonable), UA07 (seizure of property: marked s.25, found 24A/26, reasonable) and PM11 (which court tries the offence: marked s.43, found s.44 first, which also answers it). Counted as hits in the second row.

## What the numbers decided

1. **Search by meaning alone, ranked within the Act, top 5** (top 3 per Act when a question draws two Acts).
2. **No high score threshold.** Scores inside one Act are compressed: the marked section often scores 0.35 to 0.45 and the wrong first place 0.40 to 0.50. Keeping only sections scoring 0.42 or more would have found the marked section for 58 of 75 questions instead of 71 (at a floor of 0.30).
3. **A floor of 0.22**, under which nothing is handed over. The first draft of this note said 0.30: every one of the 75 gold questions clears it (the lowest best-score is 0.330). A second look, at eight short follow-up questions written after the gold run ("Is anticipatory bail available under the UAPA / the PMLA / in a POCSO case ...?", not frozen, not part of the numbers above), showed the right section as the closest one at only 0.236 (PMLA s.45), 0.244 (POCSO s.31) and 0.277 (UAPA s.43D): a floor of 0.30 would have handed over nothing for them. Of the 10 off-topic probes, 6 score 0.172 to 0.211 (nothing handed over at 0.22), 4 score 0.267 to 0.380 and pull in sections that do not bear on the question (short title, definitions, repeal and saving, and in one case the long punishments section of the SC/ST Act). The floor is a judgement call from about 18 questions, not a measured optimum; it matters only for short questions with few matching words.
4. **A cap of 14,000 characters in all** (a few sections are long: SC/ST s.3 is 11,800 characters, PC s.17A 10,200, PMLA s.2 11,000). The top 5 had a median of 8,500 characters (about 2,200 tokens) and a maximum of 24,500; a quarter of the questions would exceed 16,000. Run on the 29 questions the Directory detects, caps of 18,000 and 14,000 handed the marked section over equally often (28 of 29), 12,000 and 10,000 less often (27): 14,000 was chosen, which keeps the largest payload near 3,600 tokens.
5. **Pointers for vocabulary gaps** (`manifest.json`, per Act): a short list of everyday phrases mapped to the sections they mean, applied only when the question contains the phrase. One entry so far (SC/ST: anticipatory bail, section 438).

## Two things that matter more than these numbers

- **The shelf is only searched when the Act Directory spots the Act in the question** (its name or one of its listed phrases). Of these 75 questions, which were written to test the search and often leave the Act unnamed, the Directory would have spotted the right Act in 29 (39%): PC Act 4 of 15, POCSO 5, UAPA 6, SC/ST 7, PMLA 7. Real questions that do not name the Act get no shelf text, exactly as today.
- **Searching the shelf for every question does not work.** Tried: the best shelf score across all 245 sections, for the 75 gold questions and for the 182 other questions in the research repository (arrest, bail, FIR and similar, which have nothing to do with these five Acts). The best of those 182 scored up to 0.47 against the shelf (a question about section 498A scored 0.47 against SC/ST s.18A); a threshold of 0.50 has no false hits among the 182 but finds only 45 of the 75 gold questions and none of the 11 real narrative questions the Directory ties to these Acts. Not built.

## After the wiring: the whole path on the same 75 questions (offline, stored question vectors, no cost)

`act_shelf.search` run as the site would run it (the Directory spots the Act first; then named sections, pointers, the closest five): the Directory found the right Act for 29 of the 75; for those 29 the marked section was handed over 28 times and a reasonable first look the 29th (PM11: s.44 instead of s.43). Counting all 75, **the marked section reached the answer model for 28 (37%)**; for the other 46 nothing from the shelf is handed over (the Act is not named), exactly as today. Sections handed over per question that draws the Act: 4.9 on average, 5 at most; characters (with the 14,000 cap): median 6,700, largest 13,800 (about 3,600 tokens). The pointer for anticipatory bail is in this run, so SS02 is no longer independent evidence.
