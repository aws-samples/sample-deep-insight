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
with open('./artifacts/cache/verified_pass2.pkl', 'rb') as f:
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

# n_items per order using product line count
order_items = df.groupby('order_id').size().rename('n_items_count')
order_full2 = order_full.merge(order_items, on='order_id', how='left')

# aov
if get('aov') and get('aov')['match'] is None:
    mark('aov', order_full['order_value'].mean())

# discount_rate
if get('discount_rate') and get('discount_rate')['match'] is None:
    actual = df['discount'].sum() / (df['unit_price']*df['quantity']).sum()
    mark('discount_rate', actual)

# new/returning shares (order-level, using customer_type dim)
if get('new_order_share') and get('new_order_share')['match'] is None:
    n_new = (order_full['customer_type']=='New').sum()
    n_total = len(order_full)
    mark('new_order_share', n_new/n_total)
if get('returning_order_share') and get('returning_order_share')['match'] is None:
    n_ret = (order_full['customer_type']=='Returning').sum()
    n_total = len(order_full)
    mark('returning_order_share', n_ret/n_total)
if get('new_sales_share') and get('new_sales_share')['match'] is None:
    s_new = df.loc[df['customer_type']=='New','line_total'].sum()
    mark('new_sales_share', s_new/total_sales)
if get('returning_sales_share') and get('returning_sales_share')['match'] is None:
    s_ret = df.loc[df['customer_type']=='Returning','line_total'].sum()
    mark('returning_sales_share', s_ret/total_sales)
if get('aov_new') and get('aov_new')['match'] is None:
    mark('aov_new', order_full.loc[order_full['customer_type']=='New','order_value'].mean())
if get('aov_returning') and get('aov_returning')['match'] is None:
    mark('aov_returning', order_full.loc[order_full['customer_type']=='Returning','order_value'].mean())

# week1/week2 sales: data spans 3/2~3/15 (14 days) -> week1 = first 7 days, week2 = next 7 days
min_date = df['order_date'].min()
df['days_from_start'] = (df['order_date'] - min_date).dt.days
if get('week1_sales') and get('week1_sales')['match'] is None:
    w1 = df.loc[df['days_from_start'] < 7, 'line_total'].sum()
    mark('week1_sales', w1)
if get('week2_sales') and get('week2_sales')['match'] is None:
    w2 = df.loc[(df['days_from_start'] >= 7) & (df['days_from_start'] < 14), 'line_total'].sum()
    mark('week2_sales', w2)
if get('wow_growth') and get('wow_growth')['match'] is None:
    w1 = df.loc[df['days_from_start'] < 7, 'line_total'].sum()
    w2 = df.loc[(df['days_from_start'] >= 7) & (df['days_from_start'] < 14), 'line_total'].sum()
    mark('wow_growth', (w2-w1)/w1)

# daily avg sales & next month baseline
daily_sales = df.groupby(df['order_date'].dt.date)['line_total'].sum()
if get('daily_avg_sales') and get('daily_avg_sales')['match'] is None:
    mark('daily_avg_sales', daily_sales.mean())
if get('next_month_baseline') and get('next_month_baseline')['match'] is None:
    mark('next_month_baseline', daily_sales.mean()*30)

# peak dow / peak hour
dow_sales = df.groupby('day_of_week')['line_total'].sum()
if get('peak_dow') and get('peak_dow')['match'] is None:
    mark('peak_dow', dow_sales.idxmax())
hour_sales = df.groupby('order_hour')['line_total'].sum()
if get('peak_hour') and get('peak_hour')['match'] is None:
    mark('peak_hour', hour_sales.idxmax())
if get('peak_hour_sales') and get('peak_hour_sales')['match'] is None:
    mark('peak_hour_sales', hour_sales.max())

# top20 product share: top 12 products (as noted in formula) over total
if get('top20_product_share') and get('top20_product_share')['match'] is None:
    prod_sales = df.groupby('product_id')['line_total'].sum().sort_values(ascending=False)
    top12 = prod_sales.head(12).sum()
    mark('top20_product_share', top12/total_sales)

# top10pct / top20pct customer sales share
cust_monetary = df.groupby('customer_id')['line_total'].sum().sort_values(ascending=False)
if get('top10pct_cust_sales_share') and get('top10pct_cust_sales_share')['match'] is None:
    top185 = cust_monetary.head(185).sum()
    mark('top10pct_cust_sales_share', top185/total_sales)
if get('top20pct_cust_sales_share') and get('top20pct_cust_sales_share')['match'] is None:
    top370 = cust_monetary.head(370).sum()
    mark('top20pct_cust_sales_share', top370/total_sales)

# repeat customers / rate (frequency = distinct order count per customer)
cust_freq = df.groupby('customer_id')['order_id'].nunique()
if get('repeat_customers') and get('repeat_customers')['match'] is None:
    rc = (cust_freq>=2).sum()
    mark('repeat_customers', rc)
if get('repeat_rate') and get('repeat_rate')['match'] is None:
    rc = (cust_freq>=2).sum()
    mark('repeat_rate', rc/total_customers)

# churn risk: recency_days > 7 computed from max date in dataset
max_date = df['order_date'].max()
cust_last = df.groupby('customer_id')['order_date'].max()
recency = (max_date - cust_last).dt.days
if get('churn_risk_customers') and get('churn_risk_customers')['match'] is None:
    cr = (recency>7).sum()
    mark('churn_risk_customers', cr)
if get('churn_risk_rate') and get('churn_risk_rate')['match'] is None:
    cr = (recency>7).sum()
    mark('churn_risk_rate', cr/total_customers)

# avg repurchase interval: for customers with >=2 orders, mean diff between consecutive order dates
if get('avg_repurchase_interval') and get('avg_repurchase_interval')['match'] is None:
    multi = cust_freq[cust_freq>=2].index
    diffs = []
    for cust in multi:
        dates = sorted(df.loc[df['customer_id']==cust, 'order_date'].unique())
        d = pd.Series(dates)
        dd = d.diff().dropna().dt.days
        diffs.extend(dd.tolist())
    actual = np.mean(diffs) if diffs else None
    if actual is not None:
        mark('avg_repurchase_interval', actual)

# best_age_gender_aov_value
if get('best_age_gender_aov_value') and get('best_age_gender_aov_value')['match'] is None:
    grp = order_full.groupby(['age_group','gender'])['order_value'].mean()
    mark('best_age_gender_aov_value', grp.max())

# channel aov
for ch in ['App','Web']:
    cid = f'channel_aov_{ch}'
    if get(cid) and get(cid)['match'] is None:
        mark(cid, order_full.loc[order_full['channel']==ch,'order_value'].mean())

# aov with/without promo
order_has_promo = df.groupby('order_id')['promo_code'].apply(lambda s: s.notna().any())
order_full3 = order_full.merge(order_has_promo.rename('has_promo'), on='order_id')
if get('aov_with_promo') and get('aov_with_promo')['match'] is None:
    mark('aov_with_promo', order_full3.loc[order_full3['has_promo']==True,'order_value'].mean())
if get('aov_without_promo') and get('aov_without_promo')['match'] is None:
    mark('aov_without_promo', order_full3.loc[order_full3['has_promo']==False,'order_value'].mean())

# multi item order share
if get('multi_item_order_share') and get('multi_item_order_share')['match'] is None:
    n_items = df.groupby('order_id').size()
    actual = (n_items>=2).sum() / len(n_items)
    mark('multi_item_order_share', actual)

# corr value nitems
if get('corr_value_nitems') and get('corr_value_nitems')['match'] is None:
    n_items = df.groupby('order_id').size().rename('n_items')
    merged = order_full[['order_id','order_value']].merge(n_items, on='order_id')
    actual = merged['order_value'].corr(merged['n_items'])
    mark('corr_value_nitems', actual)

# s1_target_customers: segment in ('이탈위험','이탈/저가치') -- check actual segment labels in rfm
seg_labels = rfm['segment'].unique().tolist()
if get('s1_target_customers') and get('s1_target_customers')['match'] is None:
    # try common variants
    candidates = [s for s in seg_labels if ('이탈위험' in s) or ('이탈' in s and ('저가치' in s))]
    actual = rfm['segment'].isin(candidates).sum()
    mark('s1_target_customers', actual)

done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
print(f"Cumulative processed: {done}/{len(verified)}, matched: {match_count}")
print("segment labels in rfm:", seg_labels)

with open('./artifacts/cache/verified_pass3.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("📦 Cached verified_pass3.pkl")

remaining = [k for k, v in verified.items() if v['match'] is None]
print(f"Remaining ({len(remaining)}):", remaining)
