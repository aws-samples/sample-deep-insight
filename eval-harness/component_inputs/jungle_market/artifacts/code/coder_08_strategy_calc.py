
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')
cust_rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
total_sales = df['line_total'].sum()
n_customers = df['customer_id'].nunique()
max_date = df['order_date'].max()

daily_avg = df.groupby('order_date')['line_total'].sum().mean()
next_month_baseline = daily_avg * 30

# ============ Strategy 1: 이탈위험/일반 고객 재활성화 (VIP 유지 + 재구매 유도) ============
# Target: '이탈위험' + '일반고객' segments -> re-engagement campaign (push notif + reminder email with small incentive)
churn_seg = cust_rfm[cust_rfm['segment'].isin(['이탈위험','이탈/저가치'])]
n_churn_target = len(churn_seg)
avg_monetary_churn = churn_seg['monetary'].mean()

# assumption: campaign re-activates X% of these customers into placing 1 additional order at avg AOV of 'returning' customers in next 30 days
aov_returning = df[df['customer_type']=='Returning'].groupby('order_id')['line_total'].sum().mean()

conservative_reactivation_rate = 0.08
base_reactivation_rate = 0.15
optimistic_reactivation_rate = 0.25

s1_conservative = n_churn_target * conservative_reactivation_rate * aov_returning
s1_base = n_churn_target * base_reactivation_rate * aov_returning
s1_optimistic = n_churn_target * optimistic_reactivation_rate * aov_returning

track_calculation("s1_target_customers", n_churn_target, "전략1 타깃 고객수(이탈위험+이탈저가치 세그먼트)",
                   "COUNT(customer_id WHERE segment IN ('이탈위험','이탈/저가치'))",
                   source_file="./artifacts/cache/customer_rfm.csv", source_columns=["segment","customer_id"], importance="high")
track_calculation("s1_conservative", s1_conservative, "전략1 보수적 기대 매출 증분",
                   "target_customers * 8% 재활성화율 * AOV(재구매고객)",
                   source_file="./artifacts/cache/customer_rfm.csv", source_columns=["segment","customer_id"], importance="high")
track_calculation("s1_base", s1_base, "전략1 기본 기대 매출 증분",
                   "target_customers * 15% 재활성화율 * AOV(재구매고객)",
                   source_file="./artifacts/cache/customer_rfm.csv", source_columns=["segment","customer_id"], importance="high")
track_calculation("s1_optimistic", s1_optimistic, "전략1 낙관적 기대 매출 증분",
                   "target_customers * 25% 재활성화율 * AOV(재구매고객)",
                   source_file="./artifacts/cache/customer_rfm.csv", source_columns=["segment","customer_id"], importance="high")
print(f"전략1 타깃: {n_churn_target}명, AOV(재구매):{aov_returning:.2f}")
print(f"전략1 기대효과: 보수 ${s1_conservative:,.0f} / 기본 ${s1_base:,.0f} / 낙관 ${s1_optimistic:,.0f}")

# ============ Strategy 2: 번들/크로스셀 프로모션 (Ground Coffee + Oat Milk 등 TOP 조합) ============
# baseline: orders containing Ground Coffee but NOT Oat Milk -> upsell potential
coffee_orders = set(df[df['product_name']=='Ground Coffee']['order_id'])
oatmilk_orders = set(df[df['product_name']=='Oat Milk']['order_id'])
coffee_only_orders = coffee_orders - oatmilk_orders
n_coffee_only = len(coffee_only_orders)
oat_milk_price = df[df['product_name']=='Oat Milk']['unit_price'].mean()

# also check pasta trio: Spaghetti + Pasta Sauce + Parmesan Cheese
spaghetti_orders = set(df[df['product_name']=='Spaghetti']['order_id'])
saucespag_orders = set(df[df['product_name']=='Pasta Sauce']['order_id'])
parm_orders = set(df[df['product_name']=='Parmesan Cheese']['order_id'])
pasta_partial = (spaghetti_orders | saucespag_orders | parm_orders) - (spaghetti_orders & saucespag_orders & parm_orders)
n_pasta_partial = len(pasta_partial)

track_calculation("s2_coffee_only_orders", n_coffee_only, "전략2 커피 구매했지만 오트밀크 미구매 주문수(업셀 대상)",
                   "COUNT(orders with Ground Coffee but not Oat Milk)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","product_name"], importance="high")
track_calculation("s2_oat_milk_price", oat_milk_price, "오트밀크 평균 단가", "MEAN(unit_price) WHERE product_name='Oat Milk'",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["product_name","unit_price"], importance="high")
track_calculation("s2_pasta_partial_orders", n_pasta_partial, "전략2 파스타 트리오 중 일부만 구매한 주문수(번들 대상)",
                   "COUNT(orders with partial pasta trio)", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["order_id","product_name"], importance="high")

# assume bundle promo converts a % of coffee-only orders to add oat milk at full/discounted price next month
# scale to monthly: current 14-day period -> project to 30 days (x30/14)
scale_factor = 30/14
conservative_conv = 0.10
base_conv = 0.20
optimistic_conv = 0.35

s2_conservative = n_coffee_only * scale_factor * conservative_conv * oat_milk_price * 0.9  # 10% bundle discount assumed
s2_base = n_coffee_only * scale_factor * base_conv * oat_milk_price * 0.9
s2_optimistic = n_coffee_only * scale_factor * optimistic_conv * oat_milk_price * 0.9

track_calculation("s2_conservative", s2_conservative, "전략2 보수적 기대 매출 증분(30일 환산)",
                   "coffee_only_orders * (30/14) * 10% 전환율 * oat_milk_price * 0.9(번들할인반영)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","product_name","unit_price"], importance="high")
track_calculation("s2_base", s2_base, "전략2 기본 기대 매출 증분(30일 환산)",
                   "coffee_only_orders * (30/14) * 20% 전환율 * oat_milk_price * 0.9(번들할인반영)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","product_name","unit_price"], importance="high")
track_calculation("s2_optimistic", s2_optimistic, "전략2 낙관적 기대 매출 증분(30일 환산)",
                   "coffee_only_orders * (30/14) * 35% 전환율 * oat_milk_price * 0.9(번들할인반영)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_id","product_name","unit_price"], importance="high")
print(f"\n전략2 타깃(커피only): {n_coffee_only}건, 오트밀크 평균단가:{oat_milk_price:.2f}")
print(f"전략2 기대효과: 보수 ${s2_conservative:,.0f} / 기본 ${s2_base:,.0f} / 낙관 ${s2_optimistic:,.0f}")

# ============ Strategy 3: 피크타임 운영 최적화 + 저조시간 프로모션 (요일x시간대 기반) ============
# Target: boost off-peak hours & weekday troughs with targeted push/promo while ensuring peak-hour fulfillment efficiency
hour_sales = df.groupby('order_hour')['line_total'].sum()
low_hours = hour_sales.sort_values().head(6).index.tolist()  # 6 lowest hours
low_hours_sales = hour_sales.loc[low_hours].sum()
low_hours_orders = df[df['order_hour'].isin(low_hours)]['order_id'].nunique()

track_calculation("s3_low_hours_sales", low_hours_sales, "저조 시간대(하위 6개 시간) 매출 합계",
                   "SUM(line_total) WHERE order_hour IN low_hours", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["order_hour","line_total"], importance="high")
track_calculation("s3_low_hours_orders", low_hours_orders, "저조 시간대 주문수",
                   "COUNT(DISTINCT order_id) WHERE order_hour IN low_hours", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["order_hour","order_id"], importance="high")

# assume targeted off-peak promo (time-limited discount/push notification) lifts off-peak order volume by X%,
# scaled to 30 days, at current AOV
aov_overall = df.groupby('order_id')['line_total'].sum().mean()
conservative_lift = 0.08
base_lift = 0.15
optimistic_lift = 0.25

s3_conservative = low_hours_orders * scale_factor * conservative_lift * aov_overall
s3_base = low_hours_orders * scale_factor * base_lift * aov_overall
s3_optimistic = low_hours_orders * scale_factor * optimistic_lift * aov_overall

track_calculation("s3_conservative", s3_conservative, "전략3 보수적 기대 매출 증분(30일 환산)",
                   "low_hours_orders * (30/14) * 8% 주문증가율 * AOV",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_hour","order_id","line_total"], importance="high")
track_calculation("s3_base", s3_base, "전략3 기본 기대 매출 증분(30일 환산)",
                   "low_hours_orders * (30/14) * 15% 주문증가율 * AOV",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_hour","order_id","line_total"], importance="high")
track_calculation("s3_optimistic", s3_optimistic, "전략3 낙관적 기대 매출 증분(30일 환산)",
                   "low_hours_orders * (30/14) * 25% 주문증가율 * AOV",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_hour","order_id","line_total"], importance="high")
print(f"\n전략3 저조시간({low_hours}) 매출:{low_hours_sales:,.2f}, 주문수:{low_hours_orders}")
print(f"전략3 기대효과: 보수 ${s3_conservative:,.0f} / 기본 ${s3_base:,.0f} / 낙관 ${s3_optimistic:,.0f}")

# Total combined impact (base scenario) vs baseline
total_base_impact = s1_base + s2_base + s3_base
total_impact_pct_of_baseline = total_base_impact / next_month_baseline
track_calculation("total_base_impact", total_base_impact, "3대 전략 통합 기본 기대 매출 증분",
                   "s1_base + s2_base + s3_base", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")
track_calculation("total_impact_pct", total_impact_pct_of_baseline, "3대 전략 통합 기대 매출 증분이 베이스라인 대비 비중",
                   "total_base_impact / next_month_baseline", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")
print(f"\n3대 전략 통합(기본) 기대효과: ${total_base_impact:,.0f} (베이스라인 대비 {total_impact_pct_of_baseline:.1%})")

save_calculation_metadata()

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 실행 전략별 기대 효과 산출 (다음달 30일 환산, 현재 14일 데이터 기반)

### 전략1: 이탈위험/저가치 고객 재활성화 캠페인
- 타깃: 이탈위험+이탈/저가치 세그먼트 {n_churn_target}명 (최근 7일 이상 미구매 또는 저가치)
- 가정: 재활성화 캠페인(알림/리마인드+소액 인센티브)으로 보수 8%/기본 15%/낙관 25% 고객이 재구매고객 평균 AOV(${aov_returning:,.2f})로 1회 추가 주문
- 기대 매출 증분: 보수 ${s1_conservative:,.0f} / 기본 ${s1_base:,.0f} / 낙관 ${s1_optimistic:,.0f}

### 전략2: 번들/크로스셀 프로모션 (Ground Coffee + Oat Milk 등)
- 타깃: 커피 구매했지만 오트밀크 미구매 주문 {n_coffee_only}건(14일 기준), 파스타 트리오 부분구매 {n_pasta_partial}건
- 가정: 번들 프로모션(10% 할인)으로 보수 10%/기본 20%/낙관 35%가 오트밀크(평균 단가 ${oat_milk_price:,.2f}) 추가 구매, 30일 환산(x{scale_factor:.2f})
- 기대 매출 증분: 보수 ${s2_conservative:,.0f} / 기본 ${s2_base:,.0f} / 낙관 ${s2_optimistic:,.0f}

### 전략3: 저조 시간대 타깃 프로모션 + 피크타임 운영 효율화
- 타깃: 매출 하위 6개 시간대 주문 {low_hours_orders}건(14일 기준), 매출 ${low_hours_sales:,.2f}
- 가정: 저조시간 타깃 푸시/프로모션으로 보수 8%/기본 15%/낙관 25% 주문량 증가, 전체 평균 AOV(${aov_overall:,.2f}) 적용, 30일 환산
- 기대 매출 증분: 보수 ${s3_conservative:,.0f} / 기본 ${s3_base:,.0f} / 낙관 ${s3_optimistic:,.0f}

### 3대 전략 통합 기본(Base) 시나리오 기대 효과
- 합계: ${total_base_impact:,.0f} (다음달 매출 베이스라인 대비 +{total_impact_pct_of_baseline:.1%})
""")
print("✅ Step8 완료")
