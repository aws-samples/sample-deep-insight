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
with open('./artifacts/cache/verified_pass4b.pkl', 'rb') as f:
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
next_month_baseline = by_id['next_month_baseline']['value']  # already verified previously

# ---------- s2 (v1): coffee-only orders, oat milk price ----------
coffee_orders = set(df.loc[df['product_name']=='Ground Coffee','order_id'])
oatmilk_orders = set(df.loc[df['product_name']=='Oat Milk','order_id'])
coffee_only = coffee_orders - oatmilk_orders
if get('s2_coffee_only_orders') and get('s2_coffee_only_orders')['match'] is None:
    mark('s2_coffee_only_orders', len(coffee_only))

oat_milk_price = df.loc[df['product_name']=='Oat Milk','unit_price'].mean()
if get('s2_oat_milk_price') and get('s2_oat_milk_price')['match'] is None:
    mark('s2_oat_milk_price', oat_milk_price)

# pasta trio partial: Pasta Sauce, Spaghetti, Parmesan Cheese -- orders with 1 or 2 of the trio but not all 3
trio = ['Pasta Sauce','Spaghetti','Parmesan Cheese']
trio_orders = {p: set(df.loc[df['product_name']==p,'order_id']) for p in trio}
all_orders_union = trio_orders[trio[0]] | trio_orders[trio[1]] | trio_orders[trio[2]]
def count_trio(o):
    return sum(o in trio_orders[p] for p in trio)
partial = [o for o in all_orders_union if count_trio(o) in (1,2)]
if get('s2_pasta_partial_orders') and get('s2_pasta_partial_orders')['match'] is None:
    mark('s2_pasta_partial_orders', len(partial))

coffee_only_n = len(coffee_only)
for suf, rate in [('conservative',0.10), ('base',0.20), ('optimistic',0.35)]:
    cid = f's2_{suf}'
    if cid in by_id and get(cid) and get(cid)['match'] is None:
        actual = coffee_only_n * (30/14) * rate * oat_milk_price * 0.9
        mark(cid, actual)

# ---------- s3 (v1): low hours ----------
hour_sales = df.groupby('order_hour')['line_total'].sum().sort_values()
low_hours = hour_sales.head(6).index.tolist()
low_hours_mask = df['order_hour'].isin(low_hours)
s3_low_sales = df.loc[low_hours_mask, 'line_total'].sum()
s3_low_orders = df.loc[low_hours_mask, 'order_id'].nunique()
if get('s3_low_hours_sales') and get('s3_low_hours_sales')['match'] is None:
    mark('s3_low_hours_sales', s3_low_sales)
if get('s3_low_hours_orders') and get('s3_low_hours_orders')['match'] is None:
    mark('s3_low_hours_orders', s3_low_orders)

aov_overall = order_full['order_value'].mean()
for suf, rate in [('conservative',0.08), ('base',0.15), ('optimistic',0.25)]:
    cid = f's3_{suf}'
    if cid in by_id and get(cid) and get(cid)['match'] is None:
        actual = s3_low_orders * (30/14) * rate * aov_overall
        mark(cid, actual)

# ---------- total_base_impact / total_impact_pct (v1 combo) ----------
if get('total_base_impact') and get('total_base_impact')['match'] is None:
    actual = by_id['s1_base']['value'] + by_id['s2_base']['value'] + by_id['s3_base']['value']
    mark('total_base_impact', actual)
if get('total_impact_pct') and get('total_impact_pct')['match'] is None:
    actual = by_id['total_base_impact']['value'] / next_month_baseline
    mark('total_impact_pct', actual)

print("Pass5a (s2/s3 v1 + totals v1) done")
done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
print(f"Cumulative processed: {done}/{len(verified)}, matched: {match_count}")

with open('./artifacts/cache/verified_pass5a.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("saved")
