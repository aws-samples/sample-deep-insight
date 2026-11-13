import pickle, json

with open('./artifacts/cache/priority_calcs.pkl', 'rb') as f:
    priority_calcs = pickle.load(f)

for c in priority_calcs:
    print(c['id'], '|', c.get('description'), '|', c.get('formula'), '|', c.get('value'), '|', c.get('source_file'))
