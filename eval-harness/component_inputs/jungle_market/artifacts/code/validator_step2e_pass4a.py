import pickle, json, re, pandas as pd, numpy as np

def same_value(expected, actual):
    try:
        e, a = float(expected), float(actual)
    except (ValueError, TypeError):
        return str(expected) == str(actual)
    text = repr(float(e)) if isinstance(expected, float) else str(expected)
    decimals = len(text.split('.')[1].rstrip('0')) if '.' in text and 'e' not in text else 0
    return abs(e - a) <= max(0.5 * 10 ** -decimals, abs(a) * 1e-9)

with open('./artifacts/cache/priority_calcs.pkl', 'rb') as f:
    priority_calcs = pickle.load(f)
with open('./artifacts/cache/verified_pass3.pkl', 'rb') as f:
    verified = pickle.load(f)
with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)
with open('./artifacts/cache/df_main.pkl', 'rb') as f:
    df = pickle.load(f)
rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
df['order_date'] = pd.to_datetime(df['order_date'])
df['day_of_week'] = df['order_date'].dt.day_name()
order_full['order_date'] = pd.to_datetime(order_full['order_date'])

by_id = {c['id']: c for c in priority_calcs}
total_sales = df['line_total'].sum()
total_customers = df['customer_id'].nunique()

def get(cid):
    return verified.get(cid)
def mark(cid, actual, expected=None):
    if expected is None:
        expected = by_id[cid]['value']
    m = same_value(expected, actual)
    verified[cid] = {'match': m, 'expected': expected, 'actual': actual}
def mark_review(cid, actual, note):
    expected = by_id[cid]['value']
    verified[cid] = {'match': False, 'expected': expected, 'actual': actual, 'note': note}

# ---- category sales mapping (handle special chars) ----
cat_map = {
    'Beverages': 'Beverages',
    'Dairy_and_Eggs': 'Dairy & Eggs',
    'Pantry': 'Pantry',
    'Ready_Meals': 'Ready Meals',
    'Produce': 'Produce',
    'Plant-based': 'Plant-based',
    'Bakery': 'Bakery',
    'Snacks': 'Snacks',
    'Frozen': 'Frozen',
    'Household': 'Household',
}
for suf, real_cat in cat_map.items():
    cid = f'cat_sales_{suf}'
    if cid in by_id and get(cid) and get(cid)['match'] is None:
        actual = df.loc[df['category']==real_cat, 'line_total'].sum()
        mark(cid, actual)

# ---- seg_avg_monetary ----
seg_map = {
    'VIP_최우수': 'VIP(최우수)',
    '우수고객': '우수고객',
    '일반고객': '일반고객',
    '이탈위험': '이탈위험',
    '이탈_저가치': '이탈/저가치',
}
for suf, real_seg in seg_map.items():
    cid = f'seg_avg_monetary_{suf}'
    if cid in by_id and get(cid) and get(cid)['match'] is None:
        actual = rfm.loc[rfm['segment']==real_seg, 'monetary'].mean()
        mark(cid, actual)

# ---- discount buckets ----
# need discount rate per line: discount / (unit_price*quantity)
df['disc_rate'] = df['discount'] / (df['unit_price']*df['quantity'])
df['disc_rate'] = df['disc_rate'].fillna(0)
bucket_defs = {
    '0%': (df['disc_rate']==0),
    '10-15%': (df['disc_rate']>=0.10) & (df['disc_rate']<0.15),
    '15-20%': (df['disc_rate']>=0.15) & (df['disc_rate']<0.20),
    '20%+': (df['disc_rate']>=0.20),
}
for suf, mask in bucket_defs.items():
    cid = f'discbucket_sales_{suf}'
    if cid in by_id and get(cid) and get(cid)['match'] is None:
        actual = df.loc[mask, 'line_total'].sum()
        mark(cid, actual)

print("Pass4a (category/seg/discount) done")
done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
print(f"Cumulative processed: {done}/{len(verified)}, matched: {match_count}")

with open('./artifacts/cache/verified_pass4a.pkl', 'wb') as f:
    pickle.dump(verified, f)
with open('./artifacts/cache/df_main_enriched.pkl', 'wb') as f:
    pickle.dump(df, f)
print("📦 Cached verified_pass4a.pkl, df_main_enriched.pkl")
