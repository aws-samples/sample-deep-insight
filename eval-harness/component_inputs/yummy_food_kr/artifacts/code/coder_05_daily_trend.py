
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')
df['날짜'] = pd.to_datetime(df['날짜'])

# ===== 일별 추이 =====
daily = df.groupby('날짜').agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum'),
                                클릭수=('클릭수','sum'), 노출수=('노출수','sum'), 전환수=('전환수','sum')).reset_index()
daily['ROAS'] = (daily['매출액']/daily['광고비용']).round(2)
daily['CTR'] = (daily['클릭수']/daily['노출수']*100).round(2)
daily['전환율'] = (daily['전환수']/daily['클릭수']*100).round(2)

print("일별 ROAS 통계:")
print(f"최고: {daily['ROAS'].max()} ({daily.loc[daily['ROAS'].idxmax(),'날짜'].date()})")
print(f"최저: {daily['ROAS'].min()} ({daily.loc[daily['ROAS'].idxmin(),'날짜'].date()})")
print(f"표준편차: {daily['ROAS'].std():.3f}")

roas_max = round(daily['ROAS'].max(), 2)
roas_min = round(daily['ROAS'].min(), 2)
roas_std = round(daily['ROAS'].std(), 3)
roas_max_date = str(daily.loc[daily['ROAS'].idxmax(),'날짜'].date())
roas_min_date = str(daily.loc[daily['ROAS'].idxmin(),'날짜'].date())

track_calculation("daily_roas_max", roas_max, f"일별 ROAS 최고치 ({roas_max_date})", "MAX(일별 SUM(매출액)/SUM(광고비용))",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["날짜","매출액","광고비용"], importance="high")
track_calculation("daily_roas_min", roas_min, f"일별 ROAS 최저치 ({roas_min_date})", "MIN(일별 SUM(매출액)/SUM(광고비용))",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["날짜","매출액","광고비용"], importance="high")
track_calculation("daily_roas_std", roas_std, "일별 ROAS 표준편차(변동성)", "STD(일별 ROAS)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["날짜","매출액","광고비용"], importance="medium")

daily.to_csv('./artifacts/daily_trend.csv', index=False, encoding='utf-8-sig')

# 요일 패턴 (주말 vs 평일)
daily['요일'] = daily['날짜'].dt.dayofweek
daily['주말'] = daily['요일'].isin([5,6])
weekend_roas = round(daily[daily['주말']]['매출액'].sum()/daily[daily['주말']]['광고비용'].sum(), 2)
weekday_roas = round(daily[~daily['주말']]['매출액'].sum()/daily[~daily['주말']]['광고비용'].sum(), 2)
print(f"\n주말 ROAS: {weekend_roas}, 평일 ROAS: {weekday_roas}")

track_calculation("weekend_roas", weekend_roas, "주말(토,일) 통합 ROAS", "SUM(주말 매출액)/SUM(주말 광고비용)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["날짜","매출액","광고비용"], importance="high")
track_calculation("weekday_roas", weekday_roas, "평일 통합 ROAS", "SUM(평일 매출액)/SUM(평일 광고비용)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["날짜","매출액","광고비용"], importance="high")

save_calculation_metadata()

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 기간별(일별) 추이 분석
- 일별 ROAS 최고: {roas_max} ({roas_max_date}), 최저: {roas_min} ({roas_min_date})
- 일별 ROAS 표준편차: {roas_std}
- 주말 ROAS {weekend_roas} vs 평일 ROAS {weekday_roas}
""")
print("✅ Daily trend complete")
