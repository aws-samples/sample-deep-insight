import json, pickle, os

with open('./artifacts/calculation_metadata.json', 'r', encoding='utf-8') as f:
    metadata = json.load(f)

# Handle both formats
if isinstance(metadata, dict) and 'calculations' in metadata:
    calculations = metadata['calculations']
elif isinstance(metadata, dict):
    calculations = [{'id': k, **v} for k, v in metadata.items()]
else:
    calculations = metadata

print(f"Total calculations: {len(calculations)}")
print(f"Importance dist: {set(c.get('importance') for c in calculations)}")

def _dedup_key(c):
    val = c.get('value')
    try:
        val_key = round(float(val), 4)
    except (TypeError, ValueError):
        val_key = str(val)
    formula = (c.get('formula') or '').strip()
    cols = tuple(sorted(c.get('source_columns') or []))
    return (val_key, formula, cols)

seen = {}
order = []
for c in calculations:
    k = _dedup_key(c)
    if k in seen:
        seen[k].setdefault('aliases', []).append(c.get('id'))
    else:
        seen[k] = dict(c)
        order.append(k)
dedup_calcs = [seen[k] for k in order]
n_dup = len(calculations) - len(dedup_calcs)
print(f"Dedup: {len(calculations)} -> {len(dedup_calcs)} ({n_dup} duplicates merged into aliases)")

high = [c for c in dedup_calcs if c.get('importance') == 'high']
medium = [c for c in dedup_calcs if c.get('importance') == 'medium']
priority_calcs = high

print(f"High: {len(high)}, Medium: {len(medium)}, Selected: {len(priority_calcs)}")

os.makedirs('./artifacts/cache', exist_ok=True)
with open('./artifacts/cache/priority_calcs.pkl', 'wb') as f:
    pickle.dump(priority_calcs, f)
print("Cached: priority_calcs.pkl")
