import pickle, pandas as pd, numpy as np

with open('./artifacts/cache/df_main_enriched.pkl', 'rb') as f:
    df = pickle.load(f)
with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)
rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
df['order_date'] = pd.to_datetime(df['order_date'])

failures = []

# Chart1: daily trend
daily = df.groupby(df['order_date'].dt.date)['line_total'].sum()
if daily.fillna(0).abs().sum() == 0:
    failures.append("chart1_daily_trend: all daily sales zero")
else:
    print("chart1 daily sales sum:", daily.sum(), "days:", len(daily))

# Chart2: category sales
cat_sales = df.groupby('category')['line_total'].sum()
if cat_sales.fillna(0).abs().sum() == 0:
    failures.append("chart2_category_sales: all zero")
else:
    print("chart2 category sales sum:", cat_sales.sum(), "n_categories:", len(cat_sales))

# Chart2b: top products pareto
prod_sales = df.groupby('product_id')['line_total'].sum().sort_values(ascending=False)
if prod_sales.fillna(0).abs().sum() == 0:
    failures.append("chart2b_top_products_pareto: all zero")
else:
    print("chart2b top products sum (all):", prod_sales.sum(), "n_products:", len(prod_sales))

# Chart3: RFM segments
seg_counts = rfm['segment'].value_counts()
if seg_counts.sum() == 0:
    failures.append("chart3_rfm_segments: zero customers")
else:
    print("chart3 segment counts:", seg_counts.to_dict(), "total:", seg_counts.sum(), "== n_customers:", len(rfm))

# Chart4: dow x hour heatmap
pivot = df.pivot_table(index=df['order_date'].dt.day_name(), columns='order_hour', values='line_total', aggfunc='sum', fill_value=0)
if pivot.to_numpy().sum() == 0:
    failures.append("chart4_dow_hour_heatmap: all zero")
else:
    print("chart4 heatmap sum:", pivot.to_numpy().sum(), "shape:", pivot.shape)

# Chart5: discount bucket analysis
df['disc_rate'] = (df['discount'] / (df['unit_price']*df['quantity'])).fillna(0)
bucket_sales = pd.cut(df['disc_rate'], bins=[-0.01,0,0.10,0.15,0.20,1.0], labels=['0%','0-10%','10-15%','15-20%','20%+'])
disc_grp = df.groupby(bucket_sales)['line_total'].sum()
if disc_grp.fillna(0).abs().sum() == 0:
    failures.append("chart5_discount_analysis: all zero")
else:
    print("chart5 discount bucket sales:", disc_grp.to_dict())

# Chart6: correlation heatmap (numeric vars)
numeric_cols = ['unit_price','quantity','discount','line_total','order_hour']
corr = df[numeric_cols].corr()
if corr.isna().all().all() or corr.to_numpy().sum() == 0:
    failures.append("chart6_correlation_heatmap: all NaN/zero")
else:
    print("chart6 correlation matrix sum (abs):", corr.abs().to_numpy().sum())

# Chart7: strategy impact -- values from calculation_metadata (already validated as a group)
import json
with open('./artifacts/calculation_metadata.json', encoding='utf-8') as f:
    meta = json.load(f)
calc_by_id = {c['id']: c['value'] for c in meta['calculations']}
strategy_vals = [calc_by_id.get(k) for k in ['total_conservative_final','total_base_final','total_optimistic_final']]
if sum(v for v in strategy_vals if v) == 0:
    failures.append("chart7_strategy_impact: all zero")
else:
    print("chart7 strategy totals:", strategy_vals)

print()
if failures:
    print("❌ Chart data sanity check FAILED:")
    for f_ in failures:
        print(" -", f_)
else:
    print("✅ Chart data sanity: all 7 charts have non-zero, well-formed underlying data")
