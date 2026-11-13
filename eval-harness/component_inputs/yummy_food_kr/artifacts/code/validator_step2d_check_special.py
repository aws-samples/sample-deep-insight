import pickle

with open('./artifacts/cache/verified.pkl', 'rb') as f:
    verified = pickle.load(f)

# find the one not counted as match=True nor False nor None
others = [(cid, v) for cid, v in verified.items() if v.get('match') not in (True, False, None)]
print("Others:", others)

print(verified['below_avg_media_cost'])
