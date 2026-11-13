
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')

# 전략3 재계산: 더 보수적인 가정 (쿠빵과 격차의 20%만 개선, 클릭수도 동반 20% 축소 가정은 생략-보수적으로 전환율만)
naver_df = df[df['매체']=='네이바']
naver_click = naver_df['클릭수'].sum()
naver_conv = naver_df['전환수'].sum()
naver_cvr = round(naver_conv/naver_click*100, 2)
kupang_df = df[df['매체']=='쿠빵']
kupang_cvr = round(kupang_df['전환수'].sum()/kupang_df['클릭수'].sum()*100, 2)

# 격차의 20%만 보수적으로 개선 (랜딩페이지/타겟팅 최적화의 현실적 효과)
improve_ratio = 0.20
target_cvr = round(naver_cvr + (kupang_cvr - naver_cvr)*improve_ratio, 2)
additional_conv = round(naver_click * (target_cvr - naver_cvr) / 100, 0)
naver_aov = round(naver_df['매출액'].sum() / naver_conv, 0)
additional_rev = round(additional_conv * naver_aov, 0)
naver_rev = naver_df['매출액'].sum()
rev_increase_pct = round(additional_rev/naver_rev*100, 1)

print(f"=== 전략3 재계산(보수적 20% 격차개선) ===")
print(f"목표 전환율: {target_cvr}%")
print(f"추가 전환수: {additional_conv:,.0f}건")
print(f"기대 증분매출: {additional_rev:,.0f}원 (네이바 현재 매출 대비 {rev_increase_pct}%)")

track_calculation("strategy3_target_cvr", target_cvr, "전략3: 네이바 목표 전환율(쿠빵과 격차 20% 보수적 개선 가정)",
                   "네이바전환율 + (쿠빵전환율-네이바전환율)*0.2",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["매체","전환수","클릭수"], importance="high")
track_calculation("strategy3_additional_conv", additional_conv, "전략3: 전환율 개선 시 추가 전환수",
                   "네이바클릭수 x (목표전환율-현재전환율)/100",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["매체","클릭수"], importance="high")
track_calculation("strategy3_additional_rev", additional_rev, "전략3: 네이바 전환율 개선 시 기대 증분매출(보수적 시나리오)",
                   "추가전환수 x 네이바AOV", source_file="/app/data/yummy-food-market.csv",
                   source_columns=["매체","전환수","클릭수","매출액"], importance="high")
track_calculation("strategy3_rev_increase_pct", rev_increase_pct, "전략3: 네이바 매출 대비 증분매출 비율(%)",
                   "증분매출/네이바현재매출*100", source_file="/app/data/yummy-food-market.csv",
                   source_columns=["매체","매출액"], importance="high")

save_calculation_metadata()
print("✅ Strategy3 recalculated with conservative assumption")
