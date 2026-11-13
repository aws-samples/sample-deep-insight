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
with open('./artifacts/cache/verified_pass5a.pkl', 'rb') as f:
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

next_month_baseline = by_id['next_month_baseline']['value']

# ---------- s3_v2: SAVE10 targeting (returning customers) ----------
order_promo = df.groupby('order_id')['promo_code'].first()
order_full2 = order_full.merge(order_promo.rename('promo'), on='order_id')
returning_orders = order_full2[order_full2['customer_type']=='Returning']
save10_orders_mask = returning_orders['promo']=='SAVE10'
n_save10_orders = save10_orders_mask.sum()
n_returning_orders = len(returning_orders)
if 'save10_usage_rate' in by_id and get('save10_usage_rate') and get('save10_usage_rate')['match'] is None:
    mark('save10_usage_rate', n_save10_orders/n_returning_orders)

aov_save10 = returning_orders.loc[save10_orders_mask,'order_value'].mean()
if get('aov_save10') and get('aov_save10')['match'] is None:
    mark('aov_save10', aov_save10)

no_promo_mask = returning_orders['promo'].isna()
aov_returning_no_promo = returning_orders.loc[no_promo_mask,'order_value'].mean()
if get('aov_returning_no_promo') and get('aov_returning_no_promo')['match'] is None:
    mark('aov_returning_no_promo', aov_returning_no_promo)

non_save10_returning_orders = n_returning_orders - n_save10_orders
if get('non_save10_returning_orders') and get('non_save10_returning_orders')['match'] is None:
    mark('non_save10_returning_orders', non_save10_returning_orders)

aov_uplift = aov_save10 - aov_returning_no_promo
if get('aov_uplift_per_order') and get('aov_uplift_per_order')['match'] is None:
    mark('aov_uplift_per_order', aov_uplift)

for suf, rate in [('conservative',0.10), ('base',0.20), ('optimistic',0.35)]:
    cid = f's3_{suf}_v2'
    if cid in by_id and get(cid) and get(cid)['match'] is None:
        actual = non_save10_returning_orders * (30/14) * rate * aov_uplift
        mark(cid, actual)

# ---------- totals v2 ----------
s1_base = by_id['s1_base']['value']; s1_cons = by_id['s1_conservative']['value']; s1_opt = by_id['s1_optimistic']['value']
s2v2_base = by_id['s2_base_v2']['value']; s2v2_cons = by_id['s2_conservative_v2']['value']; s2v2_opt = by_id['s2_optimistic_v2']['value']
s3v2_base = by_id['s3_base_v2']['value']; s3v2_cons = by_id['s3_conservative_v2']['value']; s3v2_opt = by_id['s3_optimistic_v2']['value']

if get('total_base_v2') and get('total_base_v2')['match'] is None:
    mark('total_base_v2', s1_base + s2v2_base + s3v2_base)
if get('total_conservative_v2') and get('total_conservative_v2')['match'] is None:
    mark('total_conservative_v2', s1_cons + s2v2_cons + s3v2_cons)
if get('total_optimistic_v2') and get('total_optimistic_v2')['match'] is None:
    mark('total_optimistic_v2', s1_opt + s2v2_opt + s3v2_opt)
if get('total_impact_pct_v2') and get('total_impact_pct_v2')['match'] is None:
    mark('total_impact_pct_v2', by_id['total_base_v2']['value'] / next_month_baseline)

# ---------- s3_final: weekday demand flattening (화,목 vs weekend) ----------
# low weekdays = Tuesday, Thursday
low_days = ['Tuesday','Thursday']
low_orders_df = order_full[order_full['day_of_week'].isin(low_days)]
low_weekdays_orders = len(low_orders_df)
if 'low_weekdays_orders' in by_id and get('low_weekdays_orders') and get('low_weekdays_orders')['match'] is None:
    mark('low_weekdays_orders', low_weekdays_orders)

# weekend = Saturday, Sunday; need orders per day counts to get averages
order_full['date_only'] = order_full['order_date'].dt.date
daily_orders = order_full.groupby(['date_only','day_of_week'])['order_id'].nunique().reset_index(name='n_orders')
weekend_days = daily_orders[daily_orders['day_of_week'].isin(['Saturday','Sunday'])]
low_days_daily = daily_orders[daily_orders['day_of_week'].isin(low_days)]
weekend_avg = weekend_days['n_orders'].mean()
low_avg = low_days_daily['n_orders'].mean()
gap_orders_per_day = weekend_avg - low_avg
if 'gap_orders_per_day' in by_id and get('gap_orders_per_day') and get('gap_orders_per_day')['match'] is None:
    mark('gap_orders_per_day', gap_orders_per_day)

aov_overall = order_full['order_value'].mean()
for suf, rate in [('conservative',0.15), ('base',0.30), ('optimistic',0.50)]:
    cid = f's3_{suf}_final'
    if cid in by_id and get(cid) and get(cid)['match'] is None:
        actual = gap_orders_per_day * 2 * 4.3 * rate * aov_overall
        mark(cid, actual)

# ---------- totals final ----------
s2v2_cons = by_id['s2_conservative_v2']['value']; s2v2_base = by_id['s2_base_v2']['value']; s2v2_opt = by_id['s2_optimistic_v2']['value']
s3f_cons = by_id['s3_conservative_final']['value']; s3f_base = by_id['s3_base_final']['value']; s3f_opt = by_id['s3_optimistic_final']['value']

if get('total_conservative_final') and get('total_conservative_final')['match'] is None:
    mark('total_conservative_final', s1_cons + s2v2_cons + s3f_cons)
if get('total_base_final') and get('total_base_final')['match'] is None:
    mark('total_base_final', s1_base + s2v2_base + s3f_base)
if get('total_optimistic_final') and get('total_optimistic_final')['match'] is None:
    mark('total_optimistic_final', s1_opt + s2v2_opt + s3f_opt)
if get('total_impact_pct_final') and get('total_impact_pct_final')['match'] is None:
    mark('total_impact_pct_final', by_id['total_base_final']['value'] / next_month_baseline)

print("Pass5b (s3_v2/s3_final + totals) done")
done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
print(f"Cumulative processed: {done}/{len(verified)}, matched: {match_count}")

remaining = [k for k,v in verified.items() if v['match'] is None]
print("Remaining:", remaining)
not_matched = [k for k,v in verified.items() if v['match'] is False]
print("NOT matched (needs_review):", not_matched)
for k in not_matched:
    print(' -', k, 'expected=', verified[k]['expected'], 'actual=', verified[k]['actual'])

with open('./artifacts/cache/verified_final.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("saved verified_final.pkl")
