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
with open('./artifacts/cache/verified_final3.pkl', 'rb') as f:
    verified = pickle.load(f)
with open('./artifacts/cache/df_main_enriched.pkl', 'rb') as f:
    df = pickle.load(f)

by_id = {c['id']: c for c in priority_calcs}
def mark(cid, actual, note=None):
    expected = by_id[cid]['value']
    m = same_value(expected, actual)
    verified[cid] = {'match': m, 'expected': expected, 'actual': actual}
    if note:
        verified[cid]['note'] = note

# s2_v2 confirmed matching
target_orders_14d = 1115
avg_value_per_item = df['line_total'].sum() / len(df)
for cid, rate in [('s2_conservative_v2',0.15), ('s2_base_v2',0.25), ('s2_optimistic_v2',0.40)]:
    actual = target_orders_14d * (30/14) * rate * 1 * avg_value_per_item
    mark(cid, actual)

# s3_v1 (coffee bundle) & s3_final (gap) marked with note (approx/needs_review) already in verified_final3
# but let's finalize: s3_conservative_final etc currently are literal-match False (diff 0.34%) -> keep as needs_review with note
for cid in ['s3_conservative_final','s3_base_final','s3_optimistic_final']:
    if verified.get(cid, {}).get('match') is not True:
        verified[cid]['note'] = (verified[cid].get('note','') + 
            " | 로직(gap_orders_per_day=149.5 '요일평균의 합' 방식 * 2 * 4.3주 * rate * AOV) 재현시 기대값과 0.34% 차이 - AOV 소수점 처리 차이로 추정, needs_review")
    verified[cid]['match'] = False

# non-reproducible items: avg_repurchase_interval, aov_returning_no_promo, aov_uplift_per_order, s3_*_v2 (SAVE10)
for cid in ['avg_repurchase_interval']:
    verified[cid]['note'] = "재구매 간격 계산 방법(전체 연속쌍 평균 vs span/n-1) 모두 재현 실패 - 다른 중앙값/가중평균 방식 사용 추정, needs_review"
    verified[cid]['match'] = False
for cid in ['aov_returning_no_promo','aov_uplift_per_order']:
    verified[cid]['note'] = "promo_code 매칭 로직(first vs any, order_id 기준) 재현 실패 - needs_review"
    verified[cid]['match'] = False
for cid in ['s3_conservative_v2','s3_base_v2','s3_optimistic_v2']:
    verified[cid]['note'] = "상위 aov_uplift_per_order 값 재현 불일치로 연쇄 영향 - needs_review (단, 원본 결과값도 0으로 처리되어 전략3(v2)는 최종 전략에 미사용됨)"
    verified[cid]['match'] = False

done = sum(1 for v in verified.values() if v['match'] is not None)
match_count = sum(1 for v in verified.values() if v['match'])
needs_review = sum(1 for v in verified.values() if v['match'] is False)
print(f"FINAL: processed {done}/{len(verified)}, matched: {match_count}, needs_review: {needs_review}")

remaining_none = [k for k,v in verified.items() if v['match'] is None]
print("Still unresolved (None):", remaining_none)

with open('./artifacts/cache/verified_complete.pkl', 'wb') as f:
    pickle.dump(verified, f)
print("saved verified_complete.pkl")
