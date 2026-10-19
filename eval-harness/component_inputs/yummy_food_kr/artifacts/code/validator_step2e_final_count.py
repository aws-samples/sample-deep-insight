import pickle

with open('./artifacts/cache/verified.pkl', 'rb') as f:
    verified = pickle.load(f)

match_count = sum(1 for v in verified.values() if bool(v.get('match')))
print(f"Total verified-true: {match_count} / {len(verified)}")

# below_avg_media_cost -> note confirms media are 네이바, 아마존 (NOT 컬삼) - matches coder's self-correction insight
print("below_avg media check:", verified['below_avg_media_cost']['note'])
