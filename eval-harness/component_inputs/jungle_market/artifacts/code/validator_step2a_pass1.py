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
print(f"Loaded {len(priority_calcs)} calcs")

with open('./artifacts/cache/df_main.pkl', 'rb') as f:
    df = pickle.load(f)
print("df_main columns:", list(df.columns))
rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
print("rfm columns:", list(rfm.columns))

df['order_date'] = pd.to_datetime(df['order_date'])
df['day_of_week'] = df['order_date'].dt.day_name()
# order-level aggregation (order_value = sum of line_total per order, n_items = count of lines per order)
order_agg = df.groupby('order_id').agg(
    order_value=('line_total', 'sum'),
    n_items=('line_total', 'count'),
).reset_index()
# merge attributes (take first occurrence per order for dims)
order_dims = df.groupby('order_id').agg(
    customer_id=('customer_id', 'first'),
    order_date=('order_date', 'first'),
    city=('city', 'first'),
    country=('country', 'first'),
    channel=('channel', 'first'),
    promo_code=('promo_code', 'first'),
    gender=('gender', 'first'),
    age_group=('age_group', 'first'),
    customer_type=('customer_type', 'first'),
    day_of_week=('day_of_week', 'first'),
    order_hour=('order_hour', 'first'),
).reset_index()
order_full = order_agg.merge(order_dims, on='order_id')

verified = {}
notes = {}

def mark(calc_id, actual, expected, note=''):
    m = same_value(expected, actual)
    verified[calc_id] = {'match': m, 'expected': expected, 'actual': actual}
    if note:
        notes[calc_id] = note

for calc in priority_calcs:
    cid = calc['id']
    expected = calc['value']
    formula = (calc.get('formula') or '').strip()
    src = calc.get('source_file', '')
    cols = calc.get('source_columns') or []

    try:
        # ---- simple SUM ----
        m = re.fullmatch(r'SUM\(([^()]+)\)', formula)
        if m and 'GROUP BY' not in formula:
            col = m.group(1)
            if src.endswith('df_main.pkl') and col in df.columns:
                actual = df[col].sum()
                mark(cid, actual, expected)
                continue

        # ---- COUNT(DISTINCT col) ----
        m = re.fullmatch(r'COUNT\(DISTINCT ([^()]+)\)', formula)
        if m:
            col = m.group(1)
            if src.endswith('df_main.pkl') and col in df.columns:
                actual = df[col].nunique()
                mark(cid, actual, expected)
                continue

        # ---- MEAN(col) ----
        m = re.fullmatch(r'MEAN\(([^()]+)\)', formula)
        if m:
            col = m.group(1)
            if col == 'order_value' and src.endswith('df_main.pkl'):
                actual = order_full['order_value'].mean()
                mark(cid, actual, expected)
                continue
            if col in df.columns and src.endswith('df_main.pkl'):
                actual = df[col].mean()
                mark(cid, actual, expected)
                continue

        # fallback: not handled in this pass
        verified[cid] = {'match': None, 'expected': expected, 'actual': None, 'note': f'deferred: {formula}'}
    except Exception as ex:
        verified[cid] = {'match': None, 'expected': expected, 'actual': None, 'note': f'error: {ex}'}

done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
print(f"Pass1 processed: {done}/{len(verified)}, matched: {match_count}")

import pickle as pkl
with open('./artifacts/cache/verified_pass1.pkl', 'wb') as f:
    pkl.dump(verified, f)
with open('./artifacts/cache/order_full.pkl', 'wb') as f:
    pkl.dump(order_full, f)
print("📦 Cached verified_pass1.pkl, order_full.pkl")
