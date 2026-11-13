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
with open('./artifacts/cache/verified_pass4a.pkl', 'rb') as f:
    verified = pickle.load(f)
with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)
with open('./artifacts/cache/df_main_enriched.pkl', 'rb') as f:
    df = pickle.load(f)
rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
df['order_date'] = pd.to_datetime(df['order_date'])
order_full['order_date'] = pd.to_datetime(order_full['order_date'])

print("order_full columns:", list(order_full.columns))

by_id = {c['id']: c for c in priority_calcs}
def get(cid):
    return verified.get(cid)
def mark(cid, actual, expected=None):
    if expected is None:
        expected = by_id[cid]['value']
    m = same_value(expected, actual)
    verified[cid] = {'match': m, 'expected': expected, 'actual': actual}

# ---------- Strategy 1 ----------
seg_target = rfm[rfm['segment'].isin(['이탈위험','이탈/저가치'])]
s1_target = len(seg_target)
aov_returning = order_full.loc[order_full['customer_type']=='Returning','order_value'].mean()
for suf, rate in [('conservative',0.08), ('base',0.15), ('optimistic',0.25)]:
    cid = f's1_{suf}'
    if cid in by_id and get(cid) and get(cid)['match'] is None:
        actual = s1_target * rate * aov_returning
        mark(cid, actual)

# ---------- target_orders_14d, avg_value_per_item, vip_avg_items ----------
order_seg = order_full.merge(rfm[['customer_id','segment']], on='customer_id', how='left')
target_seg_orders = order_seg[order_seg['segment'].isin(['우수고객','일반고객'])]
n_target_orders_14d = len(target_seg_orders)
if 'target_orders_14d' in by_id and get('target_orders_14d') and get('target_orders_14d')['match'] is None:
    mark('target_orders_14d', n_target_orders_14d)

total_sales = df['line_total'].sum()
n_items_total = len(df)
avg_value_per_item = total_sales / n_items_total
if 'avg_value_per_item' in by_id and get('avg_value_per_item') and get('avg_value_per_item')['match'] is None:
    mark('avg_value_per_item', avg_value_per_item)

vip_custs = rfm.loc[rfm['segment']=='VIP(최우수)','customer_id']
vip_orders = order_full[order_full['customer_id'].isin(vip_custs)]
if 'vip_avg_items' in by_id and get('vip_avg_items') and get('vip_avg_items')['match'] is None:
    mark('vip_avg_items', vip_orders['n_items'].mean())

print("Pass4b (strategy groundwork) done")
done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
print(f"Cumulative processed: {done}/{len(verified)}, matched: {match_count}")

with open('./artifacts/cache/verified_pass4b.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("📦 saved verified_pass4b.pkl")

remaining_strategy = [k for k in by_id if k.startswith(('s1_','s2_','s3_','total_')) and verified.get(k,{}).get('match') is None]
print("Remaining strategy ids:", remaining_strategy)
for r in remaining_strategy:
    print(r, '=>', by_id[r]['value'], '|', by_id[r]['formula'])
