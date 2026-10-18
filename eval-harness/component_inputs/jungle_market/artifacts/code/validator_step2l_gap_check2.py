import pickle, pandas as pd, numpy as np

with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)
order_full['order_date'] = pd.to_datetime(order_full['order_date'])
order_full['date_only'] = order_full['order_date'].dt.date
daily_orders = order_full.groupby(['date_only','day_of_week'])['order_id'].nunique().reset_index(name='n_orders')

sat_mean = daily_orders[daily_orders['day_of_week']=='Saturday']['n_orders'].mean()
sun_mean = daily_orders[daily_orders['day_of_week']=='Sunday']['n_orders'].mean()
tue_mean = daily_orders[daily_orders['day_of_week']=='Tuesday']['n_orders'].mean()
thu_mean = daily_orders[daily_orders['day_of_week']=='Thursday']['n_orders'].mean()
gap = (sat_mean+sun_mean) - (tue_mean+thu_mean)
print("gap:", gap)

aov_rounded = 36.92
for rate, expected in [(0.15, 7095.922082835143), (0.30, 14191.844165670285), (0.50, 23653.073609450475)]:
    actual = gap * 2 * 4.3 * rate * aov_rounded
    print(rate, actual, 'expected', expected, 'diff%', abs(actual-expected)/expected*100)

# try with gap NOT doubled, but using 4.3 weeks * 2 (days) differently -- maybe gap_orders_per_day is actually
# per-single-low-day gap (74.75) and formula multiplies by "2개 저조요일" meaning count applies once more at daily rate
aov_exact = order_full['order_value'].mean()
gap_single = 74.75
for rate, expected in [(0.15, 7095.922082835143)]:
    actual = gap_single * 2 * 4.3 * rate * aov_exact
    print('single*2*4.3:', actual, 'vs', expected)
