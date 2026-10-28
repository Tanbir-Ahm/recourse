"""test_name_match.py -- name_match.py: do two case names read as the same parties? Offline, free. Run: python -X utf8 test_name_match.py"""
import sys

import name_match as NM

FAILURES = []


def check(cond, msg):
    print(f"[{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def same(a, b):
    return NM.names_match(NM.parse_name(a), NM.parse_name(b))


# ---- names the court's list and a model write differently: SAME case
for a, b, why in [
    ("State of Bihar v. Rajendra Agrawalla", "STATE OF BIHAR versus SRI RA.IENDRA AGRAWALLA", "a scanned I for J and an honorific"),
    ("Kalika Tiwari v. State of Bihar", "KALIKA TIWARI AND ORS. ETC. versus STATE OF BIHAR", "'and Ors. etc.'"),
    ("Kalika Tiwari v. State of Bihar", "Kalika Tiwari , Uma Shankar Rai ,Vijay Bahadur Rai & Others v. State of Bihar", "one name out of a list of appellants"),
    ("Uma Shankar Rai v. State of Bihar", "Kalika Tiwari , Uma Shankar Rai ,Vijay Bahadur Rai & Others v. State of Bihar", "the middle name of the list"),
    ("Lalita Kumari v Government of Uttar Pradesh", "LALITA KUMARI versus GOVT. OF U.P. & ORS.", "Government/Govt, Uttar Pradesh/U.P."),
    ("Girija Prasad v. State of Madhya Pradesh", "GIRIJA PRASAD (DEAD) BY LRS. versus STATE OF MADHYA PRADESH", "(Dead) by LRs"),
    ("Pandurang v. The State of Hyderabad", "PANDURANG, TUKIA AND BHILLIA versus THE ST ATE OF HYDERABAD", "a space inside 'ST ATE'"),
    ("Prakash Chandra Yadav v. State of Bihar", "Prakash Chandra Yada v. State of Bihar & Ors", "a letter lost at the end of a long name"),
    ("State of Bihar v. Rajendra Agrawalla", "Rajendra Agrawalla v. State of Bihar", "parties given the other way round"),
    ("State v. Navjot Sandhu", "State (NCT of Delhi) v. Navjot Sandhu @ Afsan Guru", "a bracket read both ways, and an alias"),
    ("P. Ramachandra Rao v. State of Karnataka", "Ramachandra Rao v. State of Karnataka", "an initial left out of a long name"),
    ("Sikka Papers Limited v. National Insurance Company Limited", "SIKKA PAPERS LTD. versus NATIONAL INSURANCE CO. LTD. & ORS.", "Limited/Ltd, Company/Co"),
    ("Shri Abdul Karim v. The State of Karnataka & Ors", "ABDUL KARIM versus STATE OF KARNATAKA AND ORS.", "Shri and The"),
    ("Arun Kumar Yadav v. State of U.P.", "ARUN KUMAR YADAV versus STATE OF U.P. THRU DIST. JUDGE", "'thru ...' cut off"),
    ("Shranappa Mutyappa Halke v. State of Maharashtra", "Shranappa Mutyappa Halke v. STATE OF MAHARASHTRA(and connected appeals)", "'(and connected appeals)'"),
    ("Gottipulla Venkata Siva Subrayanam v. State of Andhra Pradesh", "GCTTIPULLA VENKATA SIVA SUBRAYANAM & ORS. versus STATE OF ANDHRA PRADESH & ANR.", "G scanned as GC"),
    ("M/s Sicagen India Ltd v. Mahindra Vadineni", "M/S. SICAGEN INDIA LTD. versus MAHINDRA VADINENI", "M/s"),
    ("Maqbool v. State of Andhra Pradesh", "Maqbool @ Zubir @ Shahnawaz & Anr v. State of A.P", "an alias list: the first name"),
]:
    check(same(a, b), f"same case: {why}  [{a} | {b}]")

# ---- different cases that look alike: NOT the same
for a, b, why in [
    ("Rakesh Kumar Singh v. State of Bihar", "Rajesh Kumar Singh v. State of Bihar", "one unrelated letter apart"),
    ("Ramesh Chandra v. State of Madhya Pradesh", "Ramesh Chandra Gupta v. State of Madhya Pradesh", "a longer lookalike first party"),
    ("K. Kumar v. State of Bihar", "S. Kumar v. State of Bihar", "different initials"),
    ("S. Kumar v. State of Bihar", "Kumar v. State of Bihar", "a bare surname does not stand for an initial plus surname"),
    ("Ramesh v. State of Bihar", "Ramesh v. State of Punjab", "same first party, a different State"),
    ("Union of India v. Mohanlal Likumal Punjabi", "BERGER PAINTS INDIA LTD. versus COMMISSIONER OF INCOME TAX, CALCUTTA", "nothing in common"),
    ("State of Maharashtra v. Manoj", "STATE OF MAHARASHTRA versus DNYANESHWAR LAXMAN RAO WANKHEDE", "same State, a different person"),
    ("Sushil Kumar v. State of Bihar", "Sushila Kumar v. State of Bihar", "eleven letters: no slip allowed (under 14)"),
    ("Ram and Sons v. State of Bihar", "Ram v. State of Bihar", "a name taken out of an 'and' that is part of one name needs to stand alone"),
    ("Kamal v. State of Tamil Nadu", "Kamal @ Poorikamal & Anr v. State of Tamil Nadu", "a five-letter name taken out of a list cannot stand alone"),
    ("State of Bihar v. Union of India", "State of Punjab v. Union of India", "a different State as first party"),
]:
    check(not same(a, b), f"different case: {why}  [{a} | {b}]")

# ---- the versus marker, the second party, short first parties
for a, b, want, why in [
    ("Dr. V. K. Saxena v. State of Uttar Pradesh", "DR. V. K. SAXENA versus STATE OF U.P.", True, "an initial 'V.' is not the versus marker"),
    ("V. Rajaram v. State of Karnataka", "V. RAJARAM versus STATE OF KARNATAKA", True, "the initial V is part of the name"),
    ("Rajaram v. State of Madhya Pradesh", "V. RAJARAM versus STATE REPRESENTED BY THE INSPECTOR OF POLICE", False, "a name with an initial is not a bare surname; and no State is shown to match"),
    ("Pandurang Chandrakant Mhatre v. State Rep. by the Inspector of Police, Srirangam Police Station, Trichy, Tamil Nadu", "PANDURANG CHANDRAKANT MHATRE versus STATE OF MAHARASHTRA", False, "'State rep. by ... Tamil Nadu' is not Maharashtra"),
    ("Pandurang Chandrakant Mhatre v. State Rep. by the Inspector of Police, Tamil Nadu", "PANDURANG CHANDRAKANT MHATRE versus STATE OF TAMIL NADU", True, "...but is Tamil Nadu"),
    ("Sidharth Vashisht v. State (Delhi Administration)", "SIDHARTHA VASHISHT @ MANU SHARMA versus STATE (NCT OF DELHI)", True, "Delhi Administration / NCT of Delhi share 'Delhi'"),
    ("Kamal v. State of Maharashtra", "KAMAL versus STATE (NCT OF DELHI)", False, "a one-word first party needs the second party to match"),
    ("Kumar v. State of Madhya Pradesh", "KUMAR versus STATE REPRESENTED BY INSPECTOR OF POLICE", False, "a one-word first party and a second party that shows no State"),
    ("Rajendra Prasad Agrawalla v. State of Bihar", "RAJENDRA PRASAD AGRAWALLA versus STATE", True, "a long first party with a bare 'State' as second party: nothing contradicts"),
    ("Rajendra Prasad Agrawalla v. Union of India", "RAJENDRA PRASAD AGRAWALLA versus STATE OF BIHAR", False, "Union of India is not a State"),
    ("Sanjay v. State of Delhi", "SANJAY @ KAKA versus THE STATE (NCT OF DELHI)", True, "a short first party whose second party does match is accepted"),
]:
    check(same(a, b) is want, f"{'same' if want else 'different'}: {why}  [{a} | {b}]")
for a, b, want, why in [
    ("State of Madhya Pradesh v. Mohd. Yunus", "STATE OF MADHYA PRADESH versus PEER MOHD.", False, "'Mohd' alone does not make two second parties the same person"),
    ("State of Rajasthan v. Sudha Singh", "STATE OF RAJASTHAN versus HARPHOOL SINGH", False, "'Singh' alone does not either"),
    ("State of U.P. v. Ajay Singh", "STATE OF U.P. versus AJAY KUMAR", False, "same given name, different particles"),
    ("State of U.P. v. Ajay Singh", "STATE OF U.P. versus AJAY SINGH & ORS.", True, "same given name, same particle"),
    ("State of Bihar v. Mohd. Yunus Ansari", "STATE OF BIHAR versus YUNUS ANSARI", True, "Mohd is a particle and may be missing on one side"),
    ("M.C.D v. State of Delhi", "M.C.D. versus STATE OF DELHI AND ANR.", True, "a body known by its letters (three or more) is matched on them"),
    ("C.B.I v. Rajendra Prasad Agrawalla", "CENTRAL BUREAU OF INVESTIGATION versus RAJENDRA PRASAD AGRAWALLA", False, "...but not expanded to its full name (nothing here knows what CBI stands for)"),
    ("A.B. v. State of Bihar", "A.B. versus STATE OF BIHAR", False, "two letters are no name"),
]:
    check(same(a, b) is want, f"{'same' if want else 'different'}: {why}  [{a} | {b}]")
check(NM.split_versus("Dr. V. K. Saxena v. State of U.P.")[0] == "Dr. V. K. Saxena" and NM.split_versus("Anil V. Bansal")[1] == "Bansal" and NM.split_versus("A V. K. Singh") == ["A V. K. Singh"], "split_versus: lowercase v first; a capital V. only when no initial follows")

# ---- parts
check(NM.parse_name("")[:2] == ([], []) and NM.parse_name(None)[:2] == ([], []), "empty input parses to nothing")
check(not NM.names_match(NM.parse_name(""), NM.parse_name("A v. B")) and not NM.names_match(NM.parse_name("A v. B"), NM.parse_name("")), "an empty name matches nothing")
check(NM.wdist("rajendra", "raiendra", 1) == 1 and NM.wdist("rajendra", "rakendra", 1) == 2, "a look-alike letter costs one, an unrelated one two")
check(NM.wdist("abcd", "abdc", 1) == 1, "two letters swapped cost one")
check(NM.wdist("abcdefgh", "zzzzzzzz", 2) == 3, "the limit is respected (limit + 1 when over)")
check([NM.allowance(n) for n in (5, 13, 14, 23, 24, 33, 34, 60)] == [0, 0, 1, 1, 2, 2, 3, 3], "the allowance grows with the length of the name")
check(NM.tok_eq("yadav", "yadav") and not NM.tok_eq("ramesh", "rakesh") and NM.tok_eq("subrayanam", "subrayanem") is False, "single words: equal, or a long word one SLIP apart (an unrelated letter is two)")
a = NM.parse_party("Girja Prasad (Dead) by Lrs")
check(any(s[2] == "girjaprasad" for s in a), f"'(Dead) by Lrs' is cut ({[s[2] for s in a]})")
b = NM.parse_party("State (NCT of Delhi)")
check({s[2] for s in b} >= {"state", "stationctdelhi"[:0] or "statenctdelhi"}, f"a bracket holding a name is read both ways ({[s[2] for s in b]})")
c = NM.parse_party("Kalika Tiwari, Uma Shankar Rai and Vijay Bahadur Rai")
check(len(c) == 4 and c[0][3] is False and all(s[3] for s in c[1:]), "a list of names gives the whole party first, then each name")
check(NM.parse_party("Union of India & Ors.")[0][2] == "unionindia", "'& Ors.' and 'of' are not part of the name")
check(NM.parse_party("State of Uttar Pradesh")[0][2] == NM.parse_party("State of U.P.")[0][2], "Uttar Pradesh and U.P. are written one way")
check(NM.names_match(NM.parse_name("Rajendra Prasad Agrawalla v. Quux"), NM.parse_name("Rajendra Prasad Agrawalla")) is True, "a title that is only one party matches on the first party (nothing to contradict the second)")
check(NM.names_match(NM.parse_name("Zorro v. Quux"), NM.parse_name("Zorro")) is False, "...but not for a short single-word first party, which names thousands of people")

for fn in ("parse_name", "parse_party"):
    for bad in (None, 5, "v.", " v. ", "((((", "\x00\x01", "A v. " + "B " * 500):
        try:
            getattr(NM, fn)(bad)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check(ok, f"{fn}({str(bad)[:12]!r}) does not raise")

print("\nALL PASSED" if not FAILURES else f"\n{len(FAILURES)} FAILED: {FAILURES}")
sys.exit(1 if FAILURES else 0)
