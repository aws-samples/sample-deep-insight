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
with open('./artifacts/cache/verified_final.pkl', 'rb') as f:
    verified = pickle.load(f)
with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)
with open('./artifacts/cache/df_main_enriched.pkl', 'rb') as f:
    df = pickle.load(f)
rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
df['order_date'] = pd.to_datetime(df['order_date'])
df['day_of_week'] = df['order_date'].dt.day_name()
order_full['order_date'] = pd.to_datetime(order_full['order_date'])

by_id = {c['id']: c for c in priority_calcs}
def get(cid):
    return verified.get(cid)
def mark(cid, actual, expected=None):
    if expected is None:
        expected = by_id[cid]['value']
    m = same_value(expected, actual)
    verified[cid] = {'match': m, 'expected': expected, 'actual': actual}

total_sales = df['line_total'].sum()

# ---------- Fix: VIP(최우수) and 이탈/저가치 segment id name mismatch ----------
seg_name_fix = {
    'VIP_최우수': 'VIP(최우수)',
    '이탈_저가치': '이탈/저가치',
}
for suf, real_seg in seg_name_fix.items():
    seg_custs = rfm.loc[rfm['segment']==real_seg, 'customer_id']
    n_seg = len(seg_custs)
    seg_sales = order_full.loc[order_full['customer_id'].isin(seg_custs), 'order_value'].sum()

    cid = f'seg_customers_{suf}'
    if cid in by_id: mark(cid, n_seg)
    cid = f'seg_sales_{suf}'
    if cid in by_id: mark(cid, seg_sales)
    cid = f'seg_sales_share_{suf}'
    if cid in by_id: mark(cid, seg_sales/total_sales)
    cid = f'seg_customer_share_{suf}'
    if cid in by_id: mark(cid, n_seg/len(rfm))

# ---------- Fix: city New_York -> "New York" ----------
city_real = 'New York'
cid = 'city_sales_New_York'
if cid in by_id:
    mark(cid, df.loc[df['city']==city_real, 'line_total'].sum())
cid = 'city_aov_New_York'
if cid in by_id:
    mark(cid, order_full.loc[order_full['city']==city_real, 'order_value'].mean())

print("Fixed segment/city name mismatches")
done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
print(f"Cumulative: {done}/{len(verified)}, matched: {match_count}")

with open('./artifacts/cache/verified_final2.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("saved verified_final2.pkl")
