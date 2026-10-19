
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')
cust_rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
total_sales = df['line_total'].sum()
n_customers = df['customer_id'].nunique()

daily_avg = df.groupby('order_date')['line_total'].sum().mean()
next_month_baseline = daily_avg * 30
scale_factor = 30/14

# ============ Revised Strategy 2: VIP/우수고객 대상 상품종류 확장(Cross-sell) + 번들 ============
# Insight: order_value vs n_items corr = 0.82 -> encouraging customers to add 1 more item type raises order value substantially
# Target: 우수고객+일반고객 세그먼트의 평균 n_items를 VIP 수준으로 끌어올리는 "add-on" 프로모션(장바구니 추가 유도, 번들 추천)
order_level = df.groupby('order_id').agg(customer_id=('customer_id','first'), n_items=('product_id','nunique'),
                                           order_value=('line_total','sum')).reset_index()
order_level = order_level.merge(cust_rfm[['customer_id','segment']], on='customer_id', how='left')

seg_avg_items = order_level.groupby('segment')['n_items'].mean().sort_values(ascending=False)
seg_avg_value = order_level.groupby('segment')['order_value'].mean()
print("세그먼트별 평균 품목수:\n", seg_avg_items)
print("세그먼트별 평균 주문액:\n", seg_avg_value)

vip_avg_items = seg_avg_items.get('VIP(최우수)', seg_avg_items.max())
target_segs = ['우수고객','일반고객']
target_orders = order_level[order_level['segment'].isin(target_segs)]
n_target_orders_14d = len(target_orders)
avg_value_per_item = order_level['order_value'].sum() / order_level['n_items'].sum()  # proxy $/item

track_calculation("vip_avg_items", vip_avg_items, "VIP 세그먼트 평균 주문당 품목수", "MEAN(n_items) WHERE segment='VIP(최우수)'",
                   source_file="./artifacts/cache/customer_rfm.csv", source_columns=["segment","order_id","product_id"], importance="high")
track_calculation("target_orders_14d", n_target_orders_14d, "전략2 타깃(우수고객+일반고객) 주문수(14일)",
                   "COUNT(order_id WHERE segment IN ('우수고객','일반고객'))",
                   source_file="./artifacts/cache/customer_rfm.csv", source_columns=["segment","order_id"], importance="high")
track_calculation("avg_value_per_item", avg_value_per_item, "품목당 평균 매출(proxy)", "SUM(order_value)/SUM(n_items)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","line_total","product_id"], importance="high")
print(f"\nVIP평균품목수:{vip_avg_items:.2f}, 타깃주문수(14일):{n_target_orders_14d}, 품목당평균매출:{avg_value_per_item:.2f}")

# assume cross-sell/bundle nudge (e.g., "add 1 more item for free shipping/discount") gets a % of target orders to add +1 item
conservative_adopt = 0.15
base_adopt = 0.25
optimistic_adopt = 0.40
items_added = 1  # +1 item per adopting order

s2_conservative = n_target_orders_14d * scale_factor * conservative_adopt * items_added * avg_value_per_item
s2_base = n_target_orders_14d * scale_factor * base_adopt * items_added * avg_value_per_item
s2_optimistic = n_target_orders_14d * scale_factor * optimistic_adopt * items_added * avg_value_per_item

track_calculation("s2_conservative_v2", s2_conservative, "전략2(수정) 보수적 기대 매출 증분(30일 환산)",
                   "target_orders_14d * (30/14) * 15% 채택률 * 1개 추가품목 * 품목당평균매출",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","segment","product_id","line_total"], importance="high")
track_calculation("s2_base_v2", s2_base, "전략2(수정) 기본 기대 매출 증분(30일 환산)",
                   "target_orders_14d * (30/14) * 25% 채택률 * 1개 추가품목 * 품목당평균매출",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","segment","product_id","line_total"], importance="high")
track_calculation("s2_optimistic_v2", s2_optimistic, "전략2(수정) 낙관적 기대 매출 증분(30일 환산)",
                   "target_orders_14d * (30/14) * 40% 채택률 * 1개 추가품목 * 품목당평균매출",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","segment","product_id","line_total"], importance="high")
print(f"전략2(수정) 기대효과: 보수 ${s2_conservative:,.0f} / 기본 ${s2_base:,.0f} / 낙관 ${s2_optimistic:,.0f}")

# ============ Revised Strategy 3: SAVE10 쿠폰 확대 (Returning 고객 대상, 현재 저조 활용) ============
# SAVE10 used in how many returning-customer orders currently?
returning_orders = df[df['customer_type']=='Returning']['order_id'].nunique()
save10_orders = df[df['promo_code']=='SAVE10']['order_id'].nunique()
save10_usage_rate = save10_orders / returning_orders
aov_save10 = df[df['promo_code']=='SAVE10'].groupby('order_id')['line_total'].sum().mean()
aov_returning_no_promo = df[(df['customer_type']=='Returning') & (df['promo_code'].isna())].groupby('order_id')['line_total'].sum().mean()

track_calculation("save10_usage_rate", save10_usage_rate, "재구매 고객 중 SAVE10 쿠폰 사용률",
                   "COUNT(order_id WHERE promo_code='SAVE10') / COUNT(order_id WHERE customer_type='Returning')",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","customer_type","order_id"], importance="high")
track_calculation("aov_save10", aov_save10, "SAVE10 쿠폰 사용 주문 AOV", "MEAN(order_value) WHERE promo_code='SAVE10'",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","order_id","line_total"], importance="high")
track_calculation("aov_returning_no_promo", aov_returning_no_promo, "프로모션 미사용 재구매고객 AOV",
                   "MEAN(order_value) WHERE customer_type='Returning' AND promo_code IS NULL",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","customer_type","order_id","line_total"], importance="high")
print(f"\nSAVE10 사용률:{save10_usage_rate:.2%}, SAVE10 AOV:{aov_save10:.2f}, 미사용 재구매AOV:{aov_returning_no_promo:.2f}")

# non-SAVE10 returning orders (opportunity to target with coupon to drive higher AOV + frequency)
non_save10_returning_orders = returning_orders - save10_orders
aov_uplift_per_order = aov_save10 - aov_returning_no_promo  # incremental AOV when using coupon (basket enlargement effect)

conservative_target_pct = 0.10
base_target_pct = 0.20
optimistic_target_pct = 0.35

s3_conservative = non_save10_returning_orders * scale_factor * conservative_target_pct * max(aov_uplift_per_order, 0)
s3_base = non_save10_returning_orders * scale_factor * base_target_pct * max(aov_uplift_per_order, 0)
s3_optimistic = non_save10_returning_orders * scale_factor * optimistic_target_pct * max(aov_uplift_per_order, 0)

track_calculation("non_save10_returning_orders", non_save10_returning_orders, "SAVE10 미사용 재구매고객 주문수(14일)",
                   "returning_orders - save10_orders", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["promo_code","customer_type","order_id"], importance="high")
track_calculation("aov_uplift_per_order", aov_uplift_per_order, "SAVE10 사용시 AOV 증분", "aov_save10 - aov_returning_no_promo",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","order_id","line_total"], importance="high")
track_calculation("s3_conservative_v2", s3_conservative, "전략3(수정) 보수적 기대 매출 증분(30일 환산)",
                   "non_save10_returning_orders * (30/14) * 10% 타기팅율 * aov_uplift_per_order",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","customer_type","order_id","line_total"], importance="high")
track_calculation("s3_base_v2", s3_base, "전략3(수정) 기본 기대 매출 증분(30일 환산)",
                   "non_save10_returning_orders * (30/14) * 20% 타기팅율 * aov_uplift_per_order",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","customer_type","order_id","line_total"], importance="high")
track_calculation("s3_optimistic_v2", s3_optimistic, "전략3(수정) 낙관적 기대 매출 증분(30일 환산)",
                   "non_save10_returning_orders * (30/14) * 35% 타기팅율 * aov_uplift_per_order",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","customer_type","order_id","line_total"], importance="high")
print(f"전략3(수정) 기대효과: 보수 ${s3_conservative:,.0f} / 기본 ${s3_base:,.0f} / 낙관 ${s3_optimistic:,.0f}")

# recompute totals using strategy1(original) + strategy2_v2 + strategy3_v2
# load strategy1 values from existing metadata
import json
with open('./artifacts/calculation_metadata.json', encoding='utf-8') as f:
    meta = json.load(f)
calc_dict = {c['id']: c['value'] for c in meta['calculations']}
s1_base_val = calc_dict.get('s1_base', 0)
s1_conservative_val = calc_dict.get('s1_conservative', 0)
s1_optimistic_val = calc_dict.get('s1_optimistic', 0)

total_base_v2 = s1_base_val + s2_base + s3_base
total_conservative_v2 = s1_conservative_val + s2_conservative + s3_conservative
total_optimistic_v2 = s1_optimistic_val + s2_optimistic + s3_optimistic
total_impact_pct_v2 = total_base_v2 / next_month_baseline

track_calculation("total_base_v2", total_base_v2, "3대 전략(최종) 통합 기본 기대 매출 증분",
                   "s1_base + s2_base_v2 + s3_base_v2", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")
track_calculation("total_conservative_v2", total_conservative_v2, "3대 전략(최종) 통합 보수적 기대 매출 증분",
                   "s1_conservative + s2_conservative_v2 + s3_conservative_v2", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")
track_calculation("total_optimistic_v2", total_optimistic_v2, "3대 전략(최종) 통합 낙관적 기대 매출 증분",
                   "s1_optimistic + s2_optimistic_v2 + s3_optimistic_v2", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")
track_calculation("total_impact_pct_v2", total_impact_pct_v2, "3대 전략(최종) 기본 기대 매출 증분의 베이스라인 대비 비중",
                   "total_base_v2 / next_month_baseline", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")

print(f"\n[최종] 3대 전략 통합 기대효과: 보수 ${total_conservative_v2:,.0f} / 기본 ${total_base_v2:,.0f} / 낙관 ${total_optimistic_v2:,.0f}")
print(f"기본 시나리오 베이스라인 대비: {total_impact_pct_v2:.1%}")

save_calculation_metadata()

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 전략 재산정 (더 높은 임팩트 기회로 보강)

### 전략2(최종): 크로스셀/번들로 품목수 확대 (우수고객+일반고객 타깃)
- 핵심 근거: 주문금액-품목수 상관계수 0.82 (품목 추가가 주문액 증대에 강하게 연결)
- VIP세그먼트 평균 품목수 {vip_avg_items:.2f}개 vs 타깃세그먼트는 더 낮음 -> 격차만큼 추가구매 유도 여지
- 타깃: 우수고객+일반고객 주문 {n_target_orders_14d}건(14일), 품목당평균매출 ${avg_value_per_item:,.2f}
- 가정: "1개 더 담으면 할인/무료배송" 넛지로 보수 15%/기본 25%/낙관 40% 주문이 +1품목 추가, 30일 환산
- 기대 매출 증분: 보수 ${s2_conservative:,.0f} / 기본 ${s2_base:,.0f} / 낙관 ${s2_optimistic:,.0f}

### 전략3(최종): SAVE10 쿠폰 타겟 확대 (재구매 고객 대상)
- 현재 재구매 고객의 SAVE10 사용률: {save10_usage_rate:.1%} (낮은 활용도)
- SAVE10 사용 주문 AOV ${aov_save10:,.2f} vs 미사용 재구매고객 AOV ${aov_returning_no_promo:,.2f} (증분 ${aov_uplift_per_order:,.2f})
- 타깃: SAVE10 미사용 재구매 고객 주문 {non_save10_returning_orders}건(14일)
- 가정: 타겟 쿠폰 발송으로 보수 10%/기본 20%/낙관 35% 고객이 쿠폰 사용 전환, 30일 환산
- 기대 매출 증분: 보수 ${s3_conservative:,.0f} / 기본 ${s3_base:,.0f} / 낙관 ${s3_optimistic:,.0f}

### 3대 전략(최종) 통합 기대 효과
- 전략1(재활성화) + 전략2(크로스셀) + 전략3(쿠폰확대)
- 통합 기대 매출 증분: 보수 ${total_conservative_v2:,.0f} / 기본 ${total_base_v2:,.0f} / 낙관 ${total_optimistic_v2:,.0f}
- 다음달 매출 베이스라인(${next_month_baseline:,.0f}) 대비 기본 시나리오 +{total_impact_pct_v2:.1%}
""")
print("✅ Step9 완료")
