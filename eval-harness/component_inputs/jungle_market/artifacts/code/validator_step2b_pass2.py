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
with open('./artifacts/cache/verified_pass1.pkl', 'rb') as f:
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

# helper: build id -> (group_col_value) mapping from id naming convention
# patterns observed: city_sales_<City>, city_aov_<City>, dow_sales_<Day>, promo_sales_<code>,
# top_product_<PID>, seg_customer_share_<seg>, seg_customers_<seg>, seg_sales_<seg>,
# seg_sales_share_<seg>, basket_pair_<p1>_<p2>

total_sales = df['line_total'].sum()
total_customers = df['customer_id'].nunique()

# Precompute order-level with RFM segment merged
order_seg = order_full.merge(rfm[['customer_id', 'segment']], on='customer_id', how='left')

for cid, calc in by_id.items():
    if verified.get(cid, {}).get('match') is not None:
        continue
    expected = calc['value']
    formula = (calc.get('formula') or '').strip()
    src = calc.get('source_file', '')
    actual = None
    note = None
    try:
        # city_sales_<City>
        if cid.startswith('city_sales_'):
            city = cid[len('city_sales_'):]
            actual = df.loc[df['city'] == city, 'line_total'].sum()
        elif cid.startswith('city_aov_'):
            city = cid[len('city_aov_'):]
            actual = order_full.loc[order_full['city'] == city, 'order_value'].mean()
        elif cid.startswith('dow_sales_'):
            day = cid[len('dow_sales_'):]
            actual = df.loc[df['day_of_week'] == day, 'line_total'].sum()
        elif cid.startswith('dow_orders_') or cid.startswith('dow_norders_'):
            day = cid.split('_')[-1]
            actual = order_full.loc[order_full['day_of_week'] == day, 'order_id'].nunique()
        elif cid.startswith('promo_sales_'):
            code = cid[len('promo_sales_'):]
            if code == 'none':
                actual = df.loc[df['promo_code'].isna() | (df['promo_code'] == '') | (df['promo_code'].astype(str).str.lower()=='none'), 'line_total'].sum()
            else:
                actual = df.loc[df['promo_code'] == code, 'line_total'].sum()
        elif cid.startswith('top_product_'):
            pid = cid[len('top_product_'):]
            actual = df.loc[df['product_id'] == pid, 'line_total'].sum()
        elif cid.startswith('channel_sales_'):
            ch = cid[len('channel_sales_'):]
            actual = df.loc[df['channel'] == ch, 'line_total'].sum()
        elif cid.startswith('category_sales_'):
            cat = cid[len('category_sales_'):]
            actual = df.loc[df['category'] == cat, 'line_total'].sum()
        elif cid.startswith('age_sales_') or cid.startswith('age_group_sales_'):
            ag = cid.split('_')[-1]
            actual = df.loc[df['age_group'] == ag, 'line_total'].sum()
        elif cid.startswith('gender_sales_'):
            g = cid[len('gender_sales_'):]
            actual = df.loc[df['gender'] == g, 'line_total'].sum()
        elif cid.startswith('seg_customers_'):
            seg = cid[len('seg_customers_'):]
            actual = (rfm['segment'] == seg).sum()
        elif cid.startswith('seg_sales_share_'):
            seg = cid[len('seg_sales_share_'):]
            seg_custs = rfm.loc[rfm['segment'] == seg, 'customer_id']
            seg_sales = order_full.loc[order_full['customer_id'].isin(seg_custs), 'order_value'].sum()
            actual = seg_sales / total_sales
        elif cid.startswith('seg_sales_'):
            seg = cid[len('seg_sales_'):]
            seg_custs = rfm.loc[rfm['segment'] == seg, 'customer_id']
            actual = order_full.loc[order_full['customer_id'].isin(seg_custs), 'order_value'].sum()
        elif cid.startswith('seg_customer_share_'):
            seg = cid[len('seg_customer_share_'):]
            actual = (rfm['segment'] == seg).sum() / len(rfm)
        elif cid.startswith('seg_aov_'):
            seg = cid[len('seg_aov_'):]
            seg_custs = rfm.loc[rfm['segment'] == seg, 'customer_id']
            actual = order_full.loc[order_full['customer_id'].isin(seg_custs), 'order_value'].mean()
        elif cid.startswith('basket_pair_'):
            rest = cid[len('basket_pair_'):]
            # product names use underscores for spaces; try to match against unique product_name set
            prod_names = df['product_name'].unique()
            # find split point: try all possible splits matching known product names
            found = None
            parts = rest.split('_')
            for i in range(1, len(parts)):
                p1 = ' '.join(parts[:i])
                p2 = ' '.join(parts[i:])
                if p1 in prod_names and p2 in prod_names:
                    found = (p1, p2)
                    break
            if found:
                p1, p2 = found
                orders_p1 = set(df.loc[df['product_name'] == p1, 'order_id'])
                orders_p2 = set(df.loc[df['product_name'] == p2, 'order_id'])
                actual = len(orders_p1 & orders_p2)
            else:
                note = f'could not parse product pair from {rest}'
        else:
            note = f'no pattern matched (id={cid})'
    except Exception as ex:
        note = f'error: {ex}'

    if actual is not None:
        m = same_value(expected, actual)
        verified[cid] = {'match': m, 'expected': expected, 'actual': actual}
    else:
        verified[cid] = {'match': None, 'expected': expected, 'actual': None, 'note': note}

done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
print(f"Cumulative processed: {done}/{len(verified)}, matched: {match_count}")

with open('./artifacts/cache/verified_pass2.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("📦 Cached verified_pass2.pkl")

# print remaining unmatched ids for next pass
remaining = [k for k, v in verified.items() if v['match'] is None]
print(f"Remaining ({len(remaining)}):")
for r in remaining[:60]:
    print(' -', r)
