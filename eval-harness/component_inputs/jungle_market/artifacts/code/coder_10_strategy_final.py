
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np
import json

df = pd.read_pickle('./artifacts/cache/df_main.pkl')
cust_rfm = pd.read_csv('./artifacts/cache/customer_rfm.csv')
total_sales = df['line_total'].sum()

daily_avg = df.groupby('order_date')['line_total'].sum().mean()
next_month_baseline = daily_avg * 30
scale_factor = 30/14

# ============ Strategy 3 REDESIGN: 저조 요일(화/목) 타겟 프로모션으로 주문 빈도 증대 ============
# Rationale: dow_sales showed Tue/Thu lowest vs weekend highest. Use existing SAVE10-eligible returning
# customers as the lever: target them with a reminder/push specifically on low-demand weekdays to flatten demand
# and capture incremental orders during trough days (added orders at full AOV of returning customers), scaled to 30 days.

dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
dow_korean = {'Monday':'월','Tuesday':'화','Wednesday':'수','Thursday':'목','Friday':'금','Saturday':'토','Sunday':'일'}
df['dow'] = df['order_date'].dt.day_name()
dow_sales = df.groupby('dow')['line_total'].sum().reindex(dow_order)
dow_orders_count = df.groupby('dow')['order_id'].nunique().reindex(dow_order)
print("요일별 매출:\n", dow_sales)
print("요일별 주문수:\n", dow_orders_count)

# identify 2 lowest weekdays (excluding weekend, since weekend already peaks)
weekday_sales = dow_sales[['Monday','Tuesday','Wednesday','Thursday','Friday']]
low_weekdays = weekday_sales.sort_values().head(2).index.tolist()
low_weekday_orders = dow_orders_count[low_weekdays].sum()
low_weekday_sales_sum = dow_sales[low_weekdays].sum()
avg_weekend_order_rate = dow_orders_count[['Saturday','Sunday']].mean() # avg orders on weekend days
avg_low_weekday_order_rate = dow_orders_count[low_weekdays].mean()
gap_orders_per_day = avg_weekend_order_rate - avg_low_weekday_order_rate

aov_overall = df.groupby('order_id')['line_total'].sum().mean()

track_calculation("low_weekdays_orders", int(low_weekday_orders), f"저조 요일({','.join([dow_korean[d] for d in low_weekdays])}) 주문수(14일)",
                   "SUM(COUNT(order_id) GROUP BY dow) for 2 lowest weekdays", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["order_date","order_id"], importance="high")
track_calculation("gap_orders_per_day", gap_orders_per_day, "주말 대비 저조요일 평균 주문수 격차(일별)",
                   "MEAN(orders on weekend days) - MEAN(orders on low weekdays)", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["order_date","order_id","dow"], importance="high")
print(f"\n저조요일: {low_weekdays}, 주문수합계(14일,약2주):{low_weekday_orders}, 주말평균:{avg_weekend_order_rate:.1f}, 저조요일평균:{avg_low_weekday_order_rate:.1f}, 격차/일:{gap_orders_per_day:.1f}")

# assumption: targeted push notification + small weekday-only incentive closes a % of the weekday order-count gap,
# applied over ~8-9 occurrences of each low weekday in a 30-day month (approx 4.3 weeks)
weeks_per_month = 30/7
conservative_close_pct = 0.15
base_close_pct = 0.30
optimistic_close_pct = 0.50

s3_conservative = gap_orders_per_day * len(low_weekdays) * weeks_per_month * conservative_close_pct * aov_overall
s3_base = gap_orders_per_day * len(low_weekdays) * weeks_per_month * base_close_pct * aov_overall
s3_optimistic = gap_orders_per_day * len(low_weekdays) * weeks_per_month * optimistic_close_pct * aov_overall

track_calculation("s3_conservative_final", s3_conservative, "전략3(최종) 보수적 기대 매출 증분(30일 환산)",
                   "gap_orders_per_day * 2개저조요일 * 4.3주 * 15% 격차해소율 * AOV",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","order_id","line_total"], importance="high")
track_calculation("s3_base_final", s3_base, "전략3(최종) 기본 기대 매출 증분(30일 환산)",
                   "gap_orders_per_day * 2개저조요일 * 4.3주 * 30% 격차해소율 * AOV",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","order_id","line_total"], importance="high")
track_calculation("s3_optimistic_final", s3_optimistic, "전략3(최종) 낙관적 기대 매출 증분(30일 환산)",
                   "gap_orders_per_day * 2개저조요일 * 4.3주 * 50% 격차해소율 * AOV",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","order_id","line_total"], importance="high")
print(f"전략3(최종) 기대효과: 보수 ${s3_conservative:,.0f} / 기본 ${s3_base:,.0f} / 낙관 ${s3_optimistic:,.0f}")

# Recompute final totals: strategy1 (reactivation) + strategy2_v2 (cross-sell) + strategy3_final (weekday gap)
with open('./artifacts/calculation_metadata.json', encoding='utf-8') as f:
    meta = json.load(f)
calc_dict = {c['id']: c['value'] for c in meta['calculations']}

s1_conservative_val = calc_dict['s1_conservative']
s1_base_val = calc_dict['s1_base']
s1_optimistic_val = calc_dict['s1_optimistic']
s2_conservative_val = calc_dict['s2_conservative_v2']
s2_base_val = calc_dict['s2_base_v2']
s2_optimistic_val = calc_dict['s2_optimistic_v2']

total_conservative_final = s1_conservative_val + s2_conservative_val + s3_conservative
total_base_final = s1_base_val + s2_base_val + s3_base
total_optimistic_final = s1_optimistic_val + s2_optimistic_val + s3_optimistic
total_impact_pct_final = total_base_final / next_month_baseline

track_calculation("total_conservative_final", total_conservative_final, "3대 전략(최종) 통합 보수적 기대 매출 증분",
                   "s1_conservative + s2_conservative_v2 + s3_conservative_final", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")
track_calculation("total_base_final", total_base_final, "3대 전략(최종) 통합 기본 기대 매출 증분",
                   "s1_base + s2_base_v2 + s3_base_final", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")
track_calculation("total_optimistic_final", total_optimistic_final, "3대 전략(최종) 통합 낙관적 기대 매출 증분",
                   "s1_optimistic + s2_optimistic_v2 + s3_optimistic_final", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")
track_calculation("total_impact_pct_final", total_impact_pct_final, "3대 전략(최종) 기본 기대 매출 증분의 베이스라인 대비 비중",
                   "total_base_final / next_month_baseline", source_file="./artifacts/calculation_metadata.json",
                   source_columns=[], importance="high")

print(f"\n[최종 확정] 3대 전략 통합: 보수 ${total_conservative_final:,.0f} / 기본 ${total_base_final:,.0f} / 낙관 ${total_optimistic_final:,.0f}")
print(f"기본 시나리오 베이스라인(${next_month_baseline:,.0f}) 대비: {total_impact_pct_final:.1%}")

save_calculation_metadata()

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 전략3 재설계: 저조 요일 타겟 프로모션 (요일별 수요 평탄화)
- 요일별 매출 하위 2개 평일: {','.join([dow_korean[d] for d in low_weekdays])}요일 (14일 기준 주문 {int(low_weekday_orders)}건, 매출 ${low_weekday_sales_sum:,.2f})
- 주말 평균 일별 주문수 {avg_weekend_order_rate:.1f}건 vs 저조요일 평균 {avg_low_weekday_order_rate:.1f}건 (격차 {gap_orders_per_day:.1f}건/일)
- 가정: 저조요일 타겟 푸시+소액 인센티브로 보수 15%/기본 30%/낙관 50% 격차 해소, 월 4.3주 반영, AOV(${aov_overall:,.2f}) 적용
- 기대 매출 증분: 보수 ${s3_conservative:,.0f} / 기본 ${s3_base:,.0f} / 낙관 ${s3_optimistic:,.0f}

## [최종 확정] 3대 실행 전략 통합 기대 효과
1. 전략1 - 이탈위험 고객 재활성화: 보수 ${s1_conservative_val:,.0f} / 기본 ${s1_base_val:,.0f} / 낙관 ${s1_optimistic_val:,.0f}
2. 전략2 - 크로스셀/번들(품목수 확대): 보수 ${s2_conservative_val:,.0f} / 기본 ${s2_base_val:,.0f} / 낙관 ${s2_optimistic_val:,.0f}
3. 전략3 - 저조요일 수요 평탄화: 보수 ${s3_conservative:,.0f} / 기본 ${s3_base:,.0f} / 낙관 ${s3_optimistic:,.0f}
- 통합 기대 매출 증분: 보수 ${total_conservative_final:,.0f} / 기본 ${total_base_final:,.0f} / 낙관 ${total_optimistic_final:,.0f}
- 다음달 매출 베이스라인(${next_month_baseline:,.0f}) 대비 기본 시나리오 +{total_impact_pct_final:.1%}
""")
print("✅ Step10 완료")
