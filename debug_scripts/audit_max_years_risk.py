
import json

with open('bns_final_merged_table.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for field_name in ["life_or_death", "max_years"]:
    print(f"=== Checking field: {field_name} ===")
    total_multi = 0
    agree = 0
    disagree = 0
    disagree_examples = []

    for section, entry in data.items():
        if not entry.get("needs_review"):
            continue
        top_level = entry.get(field_name)
        if top_level == "contingent":
            continue  # already correctly caught by existing string check

        conditions = entry.get("all_conditions")
        has_multiple = entry.get("has_multiple_conditions")
        if not has_multiple or not conditions:
            continue

        total_multi += 1
        condition_values = set()
        contingent_inside = False
        for cond in conditions:
            v = cond.get(field_name)
            if v == "contingent":
                contingent_inside = True
            condition_values.add(v)

        if contingent_inside:
            disagree += 1
            if len(disagree_examples) < 10:
                disagree_examples.append({
                    "section": section, "top_level": top_level,
                    "condition_values": list(condition_values),
                    "reason": "contingent string inside a condition"
                })
            continue

        if len(condition_values) == 1 and next(iter(condition_values)) == top_level:
            agree += 1
        else:
            disagree += 1
            if len(disagree_examples) < 10:
                disagree_examples.append({
                    "section": section, "top_level": top_level,
                    "condition_values": list(condition_values),
                    "reason": "disagreement"
                })

    print(f"  Entries with has_multiple_conditions=True and clean top-level: {total_multi}")
    print(f"  Agree (safe): {agree}")
    print(f"  DISAGREE (risk): {disagree}")
    for ex in disagree_examples:
        print(f"    {ex}")
    print()

# Also check: how many needs_manual_review-shape entries (max_years=None,
# life_or_death not "contingent") exist, to confirm the "falls through to
# has_variable=True, safe by accident" claim
print("=== needs_manual_review shape check ===")
count = 0
examples = []
for section, entry in data.items():
    if entry.get("punishment_shape") == "needs_manual_review" and entry.get("max_years") is None:
        lod = entry.get("life_or_death")
        if lod != "contingent":
            count += 1
            if len(examples) < 5:
                examples.append({"section": section, "life_or_death": lod, "max_years": entry.get("max_years"), "max_months": entry.get("max_months")})
print(f"Count: {count}")
for ex in examples:
    print(f"  {ex}")
    
