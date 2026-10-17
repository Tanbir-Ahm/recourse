"""test_act_detect.py -- the second Act-detection pass (act_detect.py, ACT_DETECT): the switch, the word pass and its guards, the AI pass and the code checks on its reply, the cache and the log line in
chat_assistant._acts_named, and that NOTHING changes while ACT_DETECT is unset. Offline and free: no model, no network (the AI call is a stub). Run: python -X utf8 test_act_detect.py"""
import contextlib
import io
import json
import os
import sys

os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("VOYAGE_API_KEY", "dummy")
os.environ.pop("ACT_DETECT", None)
os.environ.pop("ACT_DIRECTORY", None)
import act_detect as AD
import act_directory as D

FAILURES = []
IDS = {e["id"] for e in D.load()["acts"] if e.get("detect") is not False}
ENTRIES = [{"id": e["id"], "short": e["short"]} for e in D.load()["acts"] if e.get("detect") is not False]


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def w(q):
    return sorted(h["id"] for h in AD.wide(q, IDS))


# ---------------------------------------------------------------- the switch
for val, want in ((None, "off"), ("", "off"), ("off", "off"), ("wide", "wide"), ("WIDE", "wide"), ('"ai"', "ai"), ("ai", "ai"), ("on", "off"), ("yes", "off")):
    if val is None:
        os.environ.pop("ACT_DETECT", None)
    else:
        os.environ["ACT_DETECT"] = val
    check(AD.mode() == want, f"ACT_DETECT={val!r} reads as {want!r} (got {AD.mode()!r})")
os.environ.pop("ACT_DETECT", None)
check(not AD.enabled(), "unset ACT_DETECT: the second pass is off")
check(AD.more("my son took a bribe", [], ENTRIES) == ([], {"mode": "off", "pass": "none", "inr": 0.0}), "off: more() does nothing at all")

# ---------------------------------------------------------------- the word pass: what it must find
os.environ["ACT_DETECT"] = "wide"
FOUND = [
    ("My son works as a clerk in a government office. He was arrested yesterday for taking money from a contractor.", "pc_act_1988", "the owner's own sentence, 2026-10-17: no Act named, no word 'bribe'"),
    ("The tehsildar took Rs 10,000 from us to sign our land papers", "pc_act_1988", "a role word the Directory's phrase list does not have"),
    ("A police constable demanded money to not file a case against me", "pc_act_1988", "'demanded money', not 'demanded a bribe'"),
    ("The officer is demanding a percentage to clear my bill", "pc_act_1988", "a percentage to clear a bill"),
    ("He had to pay a bribe at the RTO", "pc_act_1988", "a bare 'bribe' (the Directory holds only fixed forms such as 'taking a bribe')"),
    ("A government officer owns property far beyond his salary", "pc_act_1988", "assets beyond a public servant's salary"),
    ("A man touched my 12-year-old daughter's chest over her clothes", "pocso_act_2012", "a sexual act described against a child"),
    ("My brother is accused of terror funding", "uapa_1967", "terror funding"),
    ("ED froze my father's bank account last week", "pmla_2002", "the ED freezing an account (ED near froze)"),
    ("They abused my father by his caste name in front of the whole street", "sc_st_act_1989", "a caste insult in everyday words"),
    ("My in-laws keep demanding dowry of five lakhs", "dowry_prohibition_act_1961", "a dowry DEMAND"),
    ("Two years after the wedding my husband's family mention the dowry we gave", "dowry_prohibition_act_1961", "dowry that was GIVEN (the Act prohibits giving as well as demanding)"),
    ("My 16-year-old son was arrested for stealing a bike", "jj_act_2015", "a child accused of an ordinary offence"),
    ("Police found a country-made pistol in our store room", "arms_act_1959", "a firearm found by the police"),
    ("He was caught drunk driving on the highway", "mv_act_1988", "drunk driving"),
    # weakness 1 (2026-10-17): a private-sector word no longer blocks the Act when a public servant is named too
    ("I am a builder and the municipal officer asked me for Rs 50,000 to approve my plan", "pc_act_1988", "'builder' plus a municipal officer: the guard is lifted"),
    ("I own a shop and a police constable took Rs 2000 from me every month", "pc_act_1988", "'shop...' plus a constable: the guard is lifted"),
    # weakness 3: terrorism WITH a case context, and the Act's own terms
    ("My nephew was booked for terrorism and is in custody", "uapa_1967", "terrorism near 'booked' and 'custody'"),
    ("What is the punishment for giving money to a terrorist organisation?", "uapa_1967", "the Act's own term 'terrorist organisation'"),
    ("Can the Central Government declare an individual a terrorist?", "uapa_1967", "designation of an individual as a terrorist"),
    # weakness 2: the Enforcement Directorate WITH a cue
    ("The Enforcement Directorate attached my house last month", "pmla_2002", "the Directorate near 'attached'"),
    ("I got a summons from the Enforcement Directorate", "pmla_2002", "the Directorate near 'summons'"),
    # the Muslim Women (Protection of Rights on Marriage) Act, 2019 (added 2026-10-17)
    ("Mere shohar ne phone par teen talaq bol diya. Kya main police mein complaint kar sakti hoon?", "muslim_women_act_2019", "Hinglish: 'teen talaq'"),
    ("Last night in front of his brothers he said talaq, talaq, talaq and threw me out of the house.", "muslim_women_act_2019", "the word said three times in a row"),
    ("My husband sent me a voice message with the word talaq repeated three times. Can I file an FIR against him?", "muslim_women_act_2019", "talaq near 'three times'"),
    ("He wrote talak on a paper three times and handed it to my father.", "muslim_women_act_2019", "a different spelling of talaq"),
    ("My brother is in jail because his wife complained that he gave her talaq by SMS.", "muslim_women_act_2019", "talaq by SMS, with jail"),
    ("He sent a talaqnama on stamp paper through his lawyer saying I am divorced with immediate effect.", "muslim_women_act_2019", "talaqnama on stamp paper, immediate effect"),
    ("Is a Muslim husband liable if he gives oral talaq in anger in a single breath?", "muslim_women_act_2019", "'in a single breath' is instant"),
    ("My neighbour is Muslim and her husband said 'I divorce you' three times during an argument and then threw her out.", "muslim_women_act_2019", "no word talaq: a Muslim husband, 'I divorce you' three times"),
    ("My cousin's husband said 'you are divorced' thrice in front of the qazi. She is Muslim. Is that valid?", "muslim_women_act_2019", "no word talaq: 'thrice', a qazi, Muslim"),
    ("I am a Muslim woman. My husband left me after sending an email that says he divorces me immediately.", "muslim_women_act_2019", "no word talaq: a Muslim husband divorced by email"),
    ("What is the punishment under the Muslim Women Act for pronouncing talaq?", "muslim_women_act_2019", "the bare name of the Act near talaq"),
    ("talaq e bidat kya hai? kya ye ab crime hai?", "muslim_women_act_2019", "talaq-e-bidat spelling"),
    # the Prevention of Damage to Public Property Act, 1984 (added 2026-10-17)
    ("A state transport bus was burnt during the bandh and the police picked up my brother from the village.", "pdpp_act_1984", "a public bus burnt, with a bandh"),
    ("The FIR says my husband set a railway coach on fire at the rail roko protest.", "pdpp_act_1984", "'set ... on fire' with the thing inside the phrase"),
    ("During the farmers' agitation some people broke the windows of a government bus, and my uncle is named in the FIR.", "pdpp_act_1984", "windows of a government bus, agitation"),
    ("Some boys vandalised the tehsil office after the verdict and the police have arrested my cousin.", "pdpp_act_1984", "a public office vandalised, no protest word needed"),
    ("He is accused of throwing stones at a police station and a municipal office during the riot.", "pdpp_act_1984", "stones at a police station"),
    ("Is damage to government property during a dharna a non-bailable offence?", "pdpp_act_1984", "damage to government property"),
    ("Police booked thirty people for burning buses after the bandh call by the party.", "pdpp_act_1984", "a plain bus counts when there is a bandh"),
    ("Several buses of the state transport corporation were stoned and one was set ablaze during the shutdown.", "pdpp_act_1984", "passive: buses were stoned"),
    ("He was arrested for breaking the signal lights and barricades at the junction during the road blockade.", "pdpp_act_1984", "the public thing itself is the object"),
    ("He faces a 3-year sentence for breaking the lights of a public bus.", "pdpp_act_1984", "lights of a public bus, no protest word needed"),
]
for q, act, why in FOUND:
    check(act in w(q), f"word pass finds {act}: {why}  ({w(q)})")

# ---------------------------------------------------------------- the word pass: what it must NOT find (the workbook's own false-positive rules)
NOT_FOUND = [
    ("My employer took Rs 20,000 from my salary as penalty. Can I complain to the police?", "pc_act_1988", "a private employer is not the Prevention of Corruption Act"),
    ("My boss, a manager in a private company, asked me to pay a commission to get my pending bill cleared.", "pc_act_1988", "a private company is not the Prevention of Corruption Act"),
    ("A shopkeeper took money from me for a mobile phone and gave a fake bill", "pc_act_1988", "a shopkeeper is not a public servant"),
    ("My opponent bribed voters in the panchayat election", "pc_act_1988", "election bribery is a different offence"),
    ("My 10-year-old was hit by a car and the driver ran away", "pocso_act_2012", "a child in the question is not by itself POCSO"),
    ("My daughter is 20 years old and her colleague at work touched her inappropriately", "pocso_act_2012", "an adult is not POCSO (the workbook's age and workplace guard)"),
    ("A 15-year-old girl was sexually assaulted by her neighbour", "jj_act_2015", "a sexual offence against a child is POCSO's, not the Juvenile Justice Act's"),
    ("My wife filed a dowry harassment case under Section 498A and I was granted anticipatory bail", "dowry_prohibition_act_1961", "a dowry HARASSMENT case is BNS cruelty, not the Dowry Prohibition Act (the workbook's own warning)"),
    ("My daughter-in-law filed a case under section 85 and 86 BNS against my son over dowry harassment", "dowry_prohibition_act_1961", "the same, with the BNS sections named"),
    ("The police have registered an FIR against my father for rash driving causing a death", "mv_act_1988", "rash driving alone is a BNS offence, so it does not raise the Motor Vehicles Act"),
    ("Someone snatched my gold chain on the road. Which section applies and is it bailable?", None, "an ordinary BNS question raises no Act at all"),
    ("My sister was arrested at night with no woman police officer there. Is that allowed?", None, "an ordinary BNSS question raises no Act at all"),
    ("Can the police arrest me for cheating without a warrant?", None, "an ordinary arrest question raises no Act at all"),
    # weaknesses 1 to 3 (2026-10-17): the stricter rules still hold
    ("My boss in a private company asked me for a commission to clear my bill", "pc_act_1988", "a private payment with no public servant named stays blocked"),
    ("A candidate gave voters money before the election and the election officer took a bribe", "pc_act_1988", "the election guard still blocks even when a public servant is named"),
    ("What is terrorism and how do countries define it?", "uapa_1967", "a bare mention of terrorism, with no case, is not the Act"),
    ("The film is about terrorism and how it spreads", "uapa_1967", "the same"),
    ("The Enforcement Directorate has its headquarters in Delhi", "pmla_2002", "the name alone, with no cue word, is not the Act"),
    # near-misses for the Muslim Women Act: other talaq, other divorces, threats
    ("My husband sent me the first notice of talaq-e-hasan by registered post. Is the divorce complete after three months?", "muslim_women_act_2019", "talaq-e-hasan is not instantaneous"),
    ("Is talaq-e-hasan valid in India after the 2017 judgment? My husband gave the first notice by letter.", "muslim_women_act_2019", "the same, with a letter"),
    ("He said he will give me talaq if I speak to my parents on the phone again.", "muslim_women_act_2019", "a threat of talaq is not a pronouncement"),
    ("My husband threatened to give me talaq if I did not bring a car. I recorded the call and want to complain.", "muslim_women_act_2019", "a threat again"),
    ("My husband said talaq once during a fight and apologised the next day. Are we still married?", "muslim_women_act_2019", "one mention, nothing instant or delivered"),
    ("I am a Muslim man. My wife left home and I want a divorce. I have called her three times but she does not pick up the phone.", "muslim_women_act_2019", "'three times' near divorce but not a pronouncement"),
    ("My Christian husband divorced me by text message and I do not know what to do.", "muslim_women_act_2019", "no Muslim word, no talaq"),
    ("A Muslim couple divorced through khula and the wife wants to return the mehr. Is that required?", "muslim_women_act_2019", "khula is the wife's divorce"),
    ("Under the Muslim Women (Protection of Rights on Divorce) Act, 1986, can a divorced wife claim a lump sum from the husband?", "muslim_women_act_2019", "the 1986 Act is a different Act"),
    ("Can a Muslim woman file a case under the domestic violence act after talaq?", "muslim_women_act_2019", "talaq with no pronouncement detail"),
    # near-misses for the Public Property Act: private property, accidents, burn injuries, a place named only as where a complaint was made
    ("A mob damaged my shop during the riot. Can I claim compensation from the government?", "pdpp_act_1984", "a private shop"),
    ("My bus was damaged in a road accident and the insurer is refusing the claim.", "pdpp_act_1984", "an accident"),
    ("A government bus hit my father's scooter and damaged it. Who will pay for the repair?", "pdpp_act_1984", "the bus is the one that caused the damage"),
    ("My child suffered burn injuries and was admitted to a government hospital. Who pays for treatment?", "pdpp_act_1984", "a burn injury in a hospital is not arson of the hospital"),
    ("Someone smashed my phone and I went to the police station to file a complaint.", "pdpp_act_1984", "a police station named only as the place of the complaint"),
    ("He ransacked his wife's cupboard and was arrested after the family dispute reached the police station.", "pdpp_act_1984", "the same"),
    ("The roof of our government school building was damaged by heavy rain. Who is responsible for the repairs?", "pdpp_act_1984", "weather, not mischief"),
    ("I damaged a file belonging to a government office by mistake while it was with me. Can they file a case?", "pdpp_act_1984", "a file, not property, and no protest"),
    ("The traffic police broke the glass of my car to remove it from the no-parking zone. Can I complain?", "pdpp_act_1984", "the police are the ones who broke it"),
    ("A mob attacked my brother during the bandh and he was seriously injured. The accused are known. Which sections apply?", "pdpp_act_1984", "a mob and a bandh, but no public thing and no damage"),
    ("I was injured in stone pelting during the riot. Can I get compensation from the state?", "pdpp_act_1984", "stone pelting, but nothing public was damaged"),
]
for q, act, why in NOT_FOUND:
    got = w(q)
    check((got == [] if act is None else act not in got), f"word pass does NOT fire {act or 'anything'}: {why}  ({got})")

check(AD.wide("", IDS) == [] and AD.wide(None, IDS) == [], "word pass: empty or missing question gives nothing")
import time as _time
_t = _time.time()
for _long in ("talaq " * 4000, "the government bus damaged " * 2000, "set a government bus " * 2000, "alpha beta gamma delta " * 3000 + " bandh"):
    AD.wide(_long, IDS)
check(_time.time() - _t < 5.0, f"word pass: four 25,000-to-55,000-character inputs finish in under 5 seconds ({_time.time() - _t:.2f}s)")
check(all(h["id"] in {"pc_act_1988"} for h in AD.wide("he paid a bribe to the clerk", {"pc_act_1988"})), "word pass returns only Acts the caller allows")
check(AD.wide("he paid a bribe to the clerk", {"mv_act_1988"}) == [], "an Act the Directory cannot detect is never returned")
check(all(h["how"] == "likely" for h in AD.wide("he paid a bribe", IDS)), "every word-pass match is 'likely', never 'named'")

# ---------------------------------------------------------------- the AI pass
os.environ["ACT_DETECT"] = "ai"
Q_AI = "Can the court attach the property of a corrupt government officer?"


def stub(payload, seen=None):
    def call(prompt):
        if seen is not None:
            seen["prompt"] = prompt
        if isinstance(payload, Exception):
            raise payload
        return (payload if isinstance(payload, str) else json.dumps(payload)), 0.21
    return call


seen = {}
hits, inr = AD.ai(Q_AI, ENTRIES, call=stub({"acts": [{"id": "pc_act_1988", "quote": "a corrupt government officer"}]}, seen))
check(hits == [{"id": "pc_act_1988", "how": "likely", "why": "ai", "quote": "a corrupt government officer"}] and inr == 0.21, f"AI pass: a clean reply is used, with the words it quoted ({hits})")
check("- pc_act_1988: Prevention of Corruption Act, 1988." in seen["prompt"] and "bribery or corruption BY A PUBLIC SERVANT" in seen["prompt"], "the AI is given the Directory's ids with one line each")
check("A payment to a PRIVATE person" in seen["prompt"] and "An agency is not an Act" in seen["prompt"], "the workbook's false-positive rules are in the brief")
check(seen["prompt"].rstrip().endswith(Q_AI), "the question is the last thing in the brief")

for payload, why in (({"acts": [{"id": "pc_act_1988", "quote": "a corrupt municipal engineer"}]}, "a quote that is not in the question"),
                     ({"acts": [{"id": "pc_act_1988", "quote": "the"}]}, "a quote too short to mean anything"),
                     ({"acts": [{"id": "pc_act_1988"}]}, "no quote at all"),
                     ({"acts": [{"id": "benami_act_1988", "quote": "a corrupt government officer"}]}, "an Act that is not on the list"),
                     ({"acts": [{"id": "ipc_1860", "quote": "a corrupt government officer"}]}, "an Act the Directory may not detect"),
                     ("not json at all", "a reply that is not JSON"),
                     ({"acts": "pc_act_1988"}, "acts that is not a list"),
                     (RuntimeError("timeout"), "a failed call")):
    hits, _ = AD.ai(Q_AI, ENTRIES, call=stub(payload))
    check(hits == [], f"AI pass drops {why} ({hits})")

hits, _ = AD.ai(Q_AI, ENTRIES, call=stub({"acts": []}))
check(hits == [], "AI pass: an empty list is a fine answer")
hits, _ = AD.ai(Q_AI, ENTRIES, call=stub({"acts": [{"id": "pc_act_1988", "quote": "corrupt government officer"}, {"id": "cpc_1908", "quote": "attach the property"}, {"id": "hma_1955", "quote": "the court"}]}))
check(len(hits) == 2, f"AI pass: at most two Acts ({hits})")
hits, _ = AD.ai(Q_AI, ENTRIES, call=stub({"acts": [{"id": "pc_act_1988", "quote": "Corrupt  Government   Officer!"}]}))
check(len(hits) == 1, "AI pass: the quote is matched ignoring case, spacing and punctuation")
check(AD.ai("", ENTRIES, call=stub({"acts": []})) == ([], 0.0) and AD.ai(Q_AI, [], call=stub({"acts": []})) == ([], 0.0), "AI pass: no question or no Act list gives nothing, with no call")

import cost_log
_saved = cost_log.budget_state
cost_log.budget_state = lambda: "hard"
called = {"n": 0}


def counting(prompt):
    called["n"] += 1
    return json.dumps({"acts": []}), 0.0


check(AD.ai(Q_AI, ENTRIES, call=counting) == ([], 0.0) and called["n"] == 0, "daily budget at its hard line: the AI pass makes no call")
cost_log.budget_state = _saved

# ---------------------------------------------------------------- more(): which pass runs
hits, rec = AD.more("The tehsildar took Rs 10,000 from us to sign our land papers", [], ENTRIES, call=stub({"acts": [{"id": "hma_1955", "quote": "the tehsildar"}]}))
check(rec["pass"] == "wide" and [h["id"] for h in hits] == ["pc_act_1988"], f"more(): the word pass answers, so no AI call is made ({rec})")
hits, rec = AD.more(Q_AI, [], ENTRIES, call=stub({"acts": [{"id": "pc_act_1988", "quote": "a corrupt government officer"}]}))
check(rec["pass"] == "ai" and [h["id"] for h in hits] == ["pc_act_1988"] and rec["inr"] == 0.21, f"more(): the AI pass runs when the word pass finds nothing ({rec})")
hits, rec = AD.more("Is section 45 of the PMLA bailable?", [{"id": "pmla_2002"}], ENTRIES, call=stub({"acts": [{"id": "hma_1955", "quote": "section 45"}]}))
check(rec["pass"] in ("none", "wide") and all(h["id"] != "pmla_2002" for h in hits), f"more(): an Act the Directory already named is never repeated, and no AI call is made ({rec})")
os.environ["ACT_DETECT"] = "wide"
hits, rec = AD.more(Q_AI, [], ENTRIES, call=stub({"acts": [{"id": "pc_act_1988", "quote": "a corrupt government officer"}]}))
check(hits == [] and rec["pass"] == "none", f"ACT_DETECT=wide: the AI pass never runs ({rec})")

# ---------------------------------------------------------------- chat_assistant._acts_named
import chat_assistant as CA

os.environ.pop("ACT_DETECT", None)
CA._ACTS_CACHE.value = None
Q_OWNER = "My son works as a clerk in a government office. He was arrested yesterday for taking money from a contractor."
check(CA._acts_named(Q_OWNER) == [], "ACT_DETECT unset: the site behaves exactly as before (no Act for the owner's sentence)")
check(CA._acts_named("Is bail available under section 45 of the PMLA?") == [{"id": "pmla_2002", "short": "Prevention of Money-laundering Act, 2002 (PMLA)", "how": "named"}], "ACT_DETECT unset: a named Act is still found")

os.environ["ACT_DETECT"] = "wide"
CA._ACTS_CACHE.value = None
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    acts = CA._acts_named(Q_OWNER)
check(acts == [{"id": "pc_act_1988", "short": "Prevention of Corruption Act, 1988", "how": "likely"}], f"ACT_DETECT=wide: the owner's sentence reaches the Prevention of Corruption Act, as 'likely' ({acts})")
line = [l for l in buf.getvalue().splitlines() if l.startswith("ACT_DETECT ")]
rec = json.loads(line[0].split(" ", 1)[1]) if line else {}
check(rec.get("pass") == "wide" and rec.get("acts") == ["pc_act_1988"] and len(rec.get("q") or "") == 12 and "contractor" not in (line[0] if line else ""), f"one ACT_DETECT log line, with a hash and never the question ({line[:1]})")

calls = {"n": 0}
_real_more = AD.more


def counting_more(*a, **kw):
    calls["n"] += 1
    return _real_more(*a, **kw)


AD.more = counting_more
with contextlib.redirect_stdout(io.StringIO()):
    for _ in range(4):
        CA._acts_named(Q_OWNER)
check(calls["n"] == 0, "the result is remembered: six callers in one answer do not run the passes again")
with contextlib.redirect_stdout(io.StringIO()):
    CA._acts_named("A different question about a bribe at the RTO")
check(calls["n"] == 1, "a different question runs the passes again")
AD.more = _real_more

os.environ["ACT_DIRECTORY"] = "off"
CA._ACTS_CACHE.value = None
with contextlib.redirect_stdout(io.StringIO()):
    off = CA._acts_named(Q_OWNER)
check(off == [], "ACT_DIRECTORY=off switches the second pass off too (one switch still turns everything off)")
os.environ.pop("ACT_DIRECTORY", None)

CA._ACTS_CACHE.value = None
_broken = AD.wide
AD.wide = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
with contextlib.redirect_stdout(io.StringIO()):
    safe = CA._acts_named("He paid a bribe to the clerk")
check(safe == [], "a broken pass never breaks the answer: the Directory's own result is returned")
AD.wide = _broken

os.environ.pop("ACT_DETECT", None)
print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("all passed")
