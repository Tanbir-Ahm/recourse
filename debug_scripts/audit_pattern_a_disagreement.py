import json

with open('bns_final_merged_table.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

pattern_a_total = 0
pattern_a_agree = 0
pattern_a_disagree = 0
disagree_examples = []

pattern_b_total = 0  # needs_manual_review shape, max_years None

for section, entry in data.items():
    if not entry.get("needs_review"):
        continue

    cog = entry.get("cognizable")
    bail = entry.get("bailable")

    # Skip ones already caught by the "contingent" string check
    if cog == "contingent" or bail == "contingent":
        continue

    if entry.get("has_multiple_conditions") and entry.get("all_conditions"):
        pattern_a_total += 1
        conditions = entry["all_conditions"]
        cog_values = set(c.get("cognizable") for c in conditions)
        bail_values = set(c.get("bailable") for c in conditions)

        if len(cog_values) == 1 and len(bail_values) == 1:
            pattern_a_agree += 1
        else:
            pattern_a_disagree += 1
            if len(disagree_examples) < 10:
                disagree_examples.append({
                    "section": section,
                    "top_level_cognizable": cog,
                    "top_level_bailable": bail,
                    "condition_cognizable_values": list(cog_values),
                    "condition_bailable_values": list(bail_values),
                })

    if entry.get("punishment_shape") == "needs_manual_review" and entry.get("max_years") is None:
        pattern_b_total += 1

print(f"Pattern A (has_multiple_conditions=True, clean top-level cog/bail): {pattern_a_total}")
print(f"  Conditions AGREE with top-level (safe, like '105'): {pattern_a_agree}")
print(f"  Conditions DISAGREE with top-level (REAL silent bug risk): {pattern_a_disagree}")
print()
print("Disagreement examples (top-level value would be WRONG for at least one real condition):")
for ex in disagree_examples:
    print(f"  {ex}")
print()
print(f"Pattern B (needs_manual_review shape, max_years=None): {pattern_b_total}")

