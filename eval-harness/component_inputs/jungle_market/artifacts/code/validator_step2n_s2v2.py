import pickle, pandas as pd, numpy as np

with open('./artifacts/cache/df_main_enriched.pkl', 'rb') as f:
    df = pickle.load(f)
with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)
rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')

# s2_v2 formula: target_orders_14d * (30/14) * rate * 1개 추가품목 * 품목당평균매출
target_orders_14d = 1115  # verified
avg_value_per_item = df['line_total'].sum() / len(df)  # verified earlier
print("avg_value_per_item:", avg_value_per_item)

for rate, expected in [(0.15, 2538.382268564822), (0.25, 4230.637114274704), (0.40, 6769.019382839527)]:
    actual = target_orders_14d * (30/14) * rate * 1 * avg_value_per_item
    print(rate, actual, 'expected', expected, 'diff%', abs(actual-expected)/expected*100)
