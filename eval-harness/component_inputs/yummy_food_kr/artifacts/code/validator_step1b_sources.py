import pickle, os
from collections import Counter

with open('./artifacts/cache/priority_calcs.pkl', 'rb') as f:
    priority_calcs = pickle.load(f)

src_counter = Counter(c.get('source_file') for c in priority_calcs)
for src, cnt in src_counter.items():
    print(f"{cnt:3d}  {src}")

# print ids for calcs with no clear source_file or unusual ones
no_src = [c['id'] for c in priority_calcs if not c.get('source_file')]
print(f"\nNo source_file: {len(no_src)} -> {no_src[:10]}")
