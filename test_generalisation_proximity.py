"""test_generalisation_proximity.py -- the soft check "unsupported case generalisation" now flags a case only when the generalisation word ("illustrates", "shows that", "demonstrates", "establishes") is about that case
(same sentence as its name, or the next sentence when it points back). Live finding 2026-10-16: a long lawyer answer was retried (Rs 6.52 more) because such a word appeared somewhere else in the note. Offline and free.
Run: python -X utf8 test_generalisation_proximity.py"""
import sys

import chat_assistant as CA

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def mk(name, text):
    return {"case_name": name, "text": text}


FACTS = "The appellant alleged that a false complaint was lodged and he was arrested and remanded."   # no holding verb
M = [mk("Arnesh Kumar v. State of Bihar", FACTS), mk("Prabir Purkayastha v. State (NCT of Delhi)", FACTS), mk("Satender Kumar Antil v. Central Bureau of Investigation", FACTS)]
f = CA._find_unsupported_case_generalizations

# 1. the live false alarm: the word is about something else
live = ("In Arnesh Kumar v. State of Bihar the Court directed that the police must record reasons before arrest. "
        "In Prabir Purkayastha v. State (NCT of Delhi) the Court said the grounds must be given in writing. "
        "Satender Kumar Antil v. Central Bureau of Investigation (2026) concerned Section 35(1)(b). "
        "Taken together, the statutory text shows that the conditions are cumulative, and the Bench establishes nothing beyond the text.")
check(f(live, M) == [], "the word 'shows that' / 'establishes' in a closing sentence that names no case does not flag the cases named earlier")

# 2. the real thing is still caught: same sentence
check(f("Arnesh Kumar v. State of Bihar illustrates how courts scrutinise arrests.", M) == ["Arnesh Kumar v. State of Bihar"], "same sentence: flagged as before")
check(f("In Arnesh Kumar v. State of Bihar, the Court shows that police must justify every arrest.", M) == ["Arnesh Kumar v. State of Bihar"], "same sentence, 'shows that'")
check(f("The decision in Prabir Purkayastha v. State (NCT of Delhi) demonstrates a strict approach.", M) == ["Prabir Purkayastha v. State (NCT of Delhi)"], "same sentence, 'demonstrates'")

# 3. "v." does not split a sentence
check(f("Arnesh Kumar v. State of Bihar, decided in 2014, establishes the rule.", M) == ["Arnesh Kumar v. State of Bihar"], "'v.' does not cut the sentence between the party names")
check(f("In A.R. Antulay v. R.S. Nayak, which Satender Kumar Antil v. CBI follows, the Court shows that delay matters.", [mk("A.R. Antulay v. R.S. Nayak", FACTS)]) == ["A.R. Antulay v. R.S. Nayak"], "initials ('A.R.') do not split a sentence either")

# 4. the next sentence counts only when it points back
check(f("Arnesh Kumar v. State of Bihar is the leading case. This illustrates why reasons must be recorded.", M) == ["Arnesh Kumar v. State of Bihar"], "next sentence starting 'This' counts")
check(f("Arnesh Kumar v. State of Bihar is the leading case. Section 41A shows that notice comes first.", M) == [], "next sentence about something else does not count")
check(f("Arnesh Kumar v. State of Bihar is the leading case. It demonstrates the point.", M) == ["Arnesh Kumar v. State of Bihar"], "'It ...' counts")
check(f("Arnesh Kumar v. State of Bihar is the leading case. This illustrates what Prabir Purkayastha v. State (NCT of Delhi) later said.", M[:2]) == ["Prabir Purkayastha v. State (NCT of Delhi)"], "a next sentence that names another case is credited to that case (same sentence), not to the first")

# 5. lines and bullets
bul = "- Arnesh Kumar v. State of Bihar: reasons must be recorded.\n- The text of Section 35 shows that the notice is mandatory.\n"
check(f(bul, M) == [], "bullet lines are separate: a 'shows that' in another bullet does not flag the case")

# 6. unchanged behaviours
check(f("Arnesh Kumar v. State of Bihar illustrates the rule.", [mk("Arnesh Kumar v. State of Bihar", "The Court held that the police must record reasons.")]) == [], "an excerpt with holding language still protects the case")
check(f("Section 318 of the BNS covers cheating.", M) == [] and f("This illustrates a rule.", []) == [] and f("", M) == [] and f(None, M) == [], "empty and no-generalisation inputs are no-ops")
check(f("The Court in Arnesh Kumar illustrates the rule.", [mk("Arnesh Kumar v State of Bihar", FACTS)]) == ["Arnesh Kumar v State of Bihar"], "a short name in the sentence is matched (first party)")

# 7. the original confirmed bug (2026-09-04) is still reproduced
mur = [mk("L. Muruganantham v State of Tamil Nadu", "It is alleged that a false complaint was lodged and the appellant was arrested and remanded to judicial custody.")]
check(f("L. Muruganantham v State of Tamil Nadu is a useful precedent that illustrates how courts do scrutinise whether an arrest was properly justified.", mur) == ["L. Muruganantham v State of Tamil Nadu"], "the 2026-09-04 bug (L. Muruganantham) is still flagged")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
