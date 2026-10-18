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
with open('./artifacts/cache/verified_final2.pkl', 'rb') as f:
    verified = pickle.load(f)
with open('./artifacts/cache/order_full.pkl', 'rb') as f:
    order_full = pickle.load(f)

by_id = {c['id']: c for c in priority_calcs}
def get(cid):
    return verified.get(cid)
def mark(cid, actual, expected=None, note=None):
    if expected is None:
        expected = by_id[cid]['value']
    m = same_value(expected, actual)
    verified[cid] = {'match': m, 'expected': expected, 'actual': actual}
    if note:
        verified[cid]['note'] = note

order_full['order_date'] = pd.to_datetime(order_full['order_date'])
order_full['date_only'] = order_full['order_date'].dt.date
daily_orders = order_full.groupby(['date_only','day_of_week'])['order_id'].nunique().reset_index(name='n_orders')

# Reproducing Coder's apparent methodology: "합계 per weekend-day-type" labeled as "평균"
# weekend_sum_per_day_label = sum over the 2 occurrences of Sat + sum over 2 occurrences of Sun, divided by... 
# Actually 514.0 = mean(Sat)+mean(Sun) = 269.5+244.5 = 514.0 (sum of the two day-type means)
sat_mean = daily_orders[daily_orders['day_of_week']=='Saturday']['n_orders'].mean()
sun_mean = daily_orders[daily_orders['day_of_week']=='Sunday']['n_orders'].mean()
weekend_combined = sat_mean + sun_mean
print("weekend_combined (Sat_mean+Sun_mean):", weekend_combined)

tue_mean = daily_orders[daily_orders['day_of_week']=='Tuesday']['n_orders'].mean()
thu_mean = daily_orders[daily_orders['day_of_week']=='Thursday']['n_orders'].mean()
low_combined = tue_mean + thu_mean
print("low_combined (Tue_mean+Thu_mean):", low_combined)

gap = weekend_combined - low_combined
print("gap (combined):", gap)

# This matches 514.0, 364.5, gap 149.5 -- confirms Coder's "day-type-sum" methodology (quasi-mislabeled as "평균")
mark('gap_orders_per_day', gap, note="Coder 방법론: 주말 2개요일(토+일) 평균의 합 vs 저조요일 2개요일(화+목) 평균의 합으로 재현됨. 표현상 '평균 일별 주문수'라고 했으나 실제로는 요일평균의 합산(already x2) - 원 공식 'gap*2개저조요일*4.3주' 재검토 필요")

aov_overall = order_full['order_value'].mean()
for suf, rate in [('conservative',0.15), ('base',0.30), ('optimistic',0.50)]:
    cid = f's3_{suf}_final'
    # NOTE: formula says "gap_orders_per_day * 2개저조요일 * 4.3주 * rate * AOV"
    # but gap_orders_per_day here ALREADY represents a 2-day combined gap (149.5).
    # Testing formula AS LITERALLY WRITTEN (gap * 2 * 4.3 * rate * aov) vs gap already embedding the *2
    actual_literal = gap * 2 * 4.3 * rate * aov_overall
    actual_no_double = gap * 4.3 * rate * aov_overall
    print(cid, 'literal(gap*2*4.3*rate*aov)=', actual_literal, 'no_double(gap*4.3*rate*aov)=', actual_no_double, 'expected=', by_id[cid]['value'])

with open('./artifacts/cache/verified_final3.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("saved")
