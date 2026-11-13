import pickle, json, re, pandas as pd, numpy as np

with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)
with open('./artifacts/cache/df_main_enriched.pkl', 'rb') as f:
    df = pickle.load(f)
rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
df['order_date'] = pd.to_datetime(df['order_date'])
df['day_of_week'] = df['order_date'].dt.day_name()
order_full['order_date'] = pd.to_datetime(order_full['order_date'])
order_full['date_only'] = order_full['order_date'].dt.date

# ---- investigate gap_orders_per_day: expected 149.5 ----
daily_orders = order_full.groupby(['date_only','day_of_week'])['order_id'].nunique().reset_index(name='n_orders')
print(daily_orders.groupby('day_of_week')['n_orders'].agg(['mean','count']))

weekend = daily_orders[daily_orders['day_of_week'].isin(['Saturday','Sunday'])]
low2 = daily_orders[daily_orders['day_of_week'].isin(['Tuesday','Thursday'])]
print("weekend avg:", weekend['n_orders'].mean(), "n_days:", len(weekend))
print("low2 avg:", low2['n_orders'].mean(), "n_days:", len(low2))
print("gap simple:", weekend['n_orders'].mean() - low2['n_orders'].mean())

# all days average orders/day
all_avg = daily_orders['n_orders'].mean()
print("all days avg:", all_avg)

# Maybe "weekend" means Fri+Sat+Sun or just comparing total orders not avg?
# try weekday groups all
print(daily_orders.groupby('day_of_week')['n_orders'].mean().sort_values())
