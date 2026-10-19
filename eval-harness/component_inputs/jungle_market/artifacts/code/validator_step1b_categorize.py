import json

with open('./artifacts/cache/priority_calcs_dump.json', encoding='utf-8') as f:
    data = json.load(f)

# group formulas by pattern prefix to understand categories
from collections import Counter
import re

categories = Counter()
for d in data:
    fid = d['id']
    formula = d['formula'] or ''
    if formula.startswith('SUM(') and 'GROUP BY' not in formula and '/' not in formula:
        categories['simple_sum'] += 1
    elif formula.startswith('COUNT(DISTINCT'):
        categories['count_distinct'] += 1
    elif 'GROUP BY' in formula:
        categories['group_by'] += 1
    elif '/' in formula and 'GROUP BY' not in formula:
        categories['ratio'] += 1
    elif formula.startswith('MEAN('):
        categories['mean'] += 1
    else:
        categories['other'] += 1

print(categories)

# print ids in 'other' category to inspect manually
print("\n--- OTHER category ids & formulas ---")
for d in data:
    formula = d['formula'] or ''
    if not (formula.startswith('SUM(') and 'GROUP BY' not in formula and '/' not in formula) \
       and not formula.startswith('COUNT(DISTINCT') \
       and 'GROUP BY' not in formula \
       and not (('/' in formula) and 'GROUP BY' not in formula) \
       and not formula.startswith('MEAN('):
        print(d['id'], '::', formula, '::', d['source_file'])
