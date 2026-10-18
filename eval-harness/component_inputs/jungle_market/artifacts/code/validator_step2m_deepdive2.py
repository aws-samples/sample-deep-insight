import pickle, pandas as pd, numpy as np

with open('./artifacts/cache/df_main_enriched.pkl', 'rb') as f:
    df = pickle.load(f)
with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)
rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
df['order_date'] = pd.to_datetime(df['order_date'])
order_full['order_date'] = pd.to_datetime(order_full['order_date'])

# ---- avg_repurchase_interval: try using order-level dates distinct, maybe only first/last (not all pairwise diffs) ----
cust_freq = df.groupby('customer_id')['order_id'].nunique()
multi = cust_freq[cust_freq>=2].index
# approach A: mean of ALL consecutive diffs (done before) = 3.9677
diffsA = []
for cust in multi:
    dates = sorted(df.loc[df['customer_id']==cust, 'order_date'].unique())
    d = pd.Series(dates)
    diffsA.extend(d.diff().dropna().dt.days.tolist())
print("approach A (all consecutive diffs) mean:", np.mean(diffsA), "n=", len(diffsA))

# approach B: (last-first)/(n_orders-1) per customer, then mean across customers
diffsB = []
for cust in multi:
    dates = sorted(df.loc[df['customer_id']==cust, 'order_date'].unique())
    n = len(dates)
    if n>=2:
        span = (dates[-1]-dates[0]).days
        diffsB.append(span/(n-1))
print("approach B (span/(n-1) per customer, then mean) mean:", np.mean(diffsB), "n=", len(diffsB))

# approach C: use order_full (dedup by order, which should be same as df unique dates per order)
print("expected: 3.557017543859649")

# ---- aov_returning_no_promo: maybe "no_promo" means promo_code is NaN OR '' for the whole order (not first linerow) ----
order_promo_any = df.groupby('order_id')['promo_code'].apply(lambda s: s.notna().any())
order_full_b = order_full.merge(order_promo_any.rename('has_promo'), on='order_id')
returning = order_full_b[order_full_b['customer_type']=='Returning']
aov_ret_nopromo_v2 = returning.loc[returning['has_promo']==False, 'order_value'].mean()
print("aov_returning_no_promo (has_promo any-line logic):", aov_ret_nopromo_v2, " expected 37.96567674764502")

# check SAVE10 aov with any-line logic too
order_promo_first = df.groupby('order_id')['promo_code'].first()
print("Any mismatch between first() and any() promo assignment?", (order_promo_first.isna() != (~order_promo_any)).sum())
