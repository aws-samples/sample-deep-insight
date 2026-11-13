
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')
total_cost = df['광고비용'].sum()
total_rev = df['매출액'].sum()
overall_roas = round(total_rev/total_cost, 2)

# ===== 전략 1: 네이바 예산 축소 → 쿠빵/아마존x건강식품 재배분 시나리오 =====
media_agg = df.groupby('매체').agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
media_agg['ROAS'] = (media_agg['매출액']/media_agg['광고비용']).round(2)

naver_cost = media_agg[media_agg['매체']=='네이바']['광고비용'].values[0]
naver_roas = media_agg[media_agg['매체']=='네이바']['ROAS'].values[0]
kupang_roas = media_agg[media_agg['매체']=='쿠빵']['ROAS'].values[0]

# 네이바 예산 30% 축소 시나리오
cut_ratio = 0.30
naver_cut_amount = round(naver_cost * cut_ratio, 0)
lost_rev_naver = round(naver_cut_amount * naver_roas, 0)
# 쿠빵으로 재배분했을 때 기대 매출
realloc_rev_kupang = round(naver_cut_amount * kupang_roas, 0)
net_rev_gain = round(realloc_rev_kupang - lost_rev_naver, 0)

print(f"=== 전략1 시나리오: 네이바 예산 {cut_ratio*100:.0f}% 축소 → 쿠빵 재배분 ===")
print(f"네이바 광고비: {naver_cost:,}원, ROAS: {naver_roas}")
print(f"축소 금액: {naver_cut_amount:,.0f}원")
print(f"네이바에서 잃는 매출: {lost_rev_naver:,.0f}원")
print(f"쿠빵 재배분 시 기대 매출: {realloc_rev_kupang:,.0f}원")
print(f"순 매출 증분: {net_rev_gain:,.0f}원")

track_calculation("strategy1_naver_cut_amount", naver_cut_amount, "전략1: 네이바 예산 30% 축소 금액",
                   "네이바 총광고비 x 0.30", source_file="./artifacts/media_agg.csv",
                   source_columns=["매체","광고비용"], importance="high")
track_calculation("strategy1_net_rev_gain", net_rev_gain, "전략1: 네이바→쿠빵 예산 재배분 시 순매출 증분 추정",
                   "(축소금액 x 쿠빵ROAS) - (축소금액 x 네이바ROAS)",
                   source_file="./artifacts/media_agg.csv", source_columns=["매체","광고비용","ROAS"], importance="high")

# ===== 전략 2: 아마존x건강식품 조합 확대 시나리오 =====
cross_agg = df.groupby(['매체','카테고리']).agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
cross_agg['ROAS'] = (cross_agg['매출액']/cross_agg['광고비용']).round(2)
amazon_health = cross_agg[(cross_agg['매체']=='아마존') & (cross_agg['카테고리']=='건강식품')].iloc[0]
amazon_health_cost = amazon_health['광고비용']
amazon_health_roas = amazon_health['ROAS']

# 아마존x건강식품 예산 50% 증액 시나리오 (한계수익 보수적으로 70% 반영 가정)
increase_amount = round(amazon_health_cost * 0.5, 0)
conservative_roas = round(amazon_health_roas * 0.7, 2)  # 한계ROAS 보수적 할인
expected_incremental_rev = round(increase_amount * conservative_roas, 0)

print(f"\n=== 전략2 시나리오: 아마존x건강식품 예산 50% 증액 ===")
print(f"현재 광고비: {amazon_health_cost:,}원, ROAS: {amazon_health_roas}")
print(f"증액 금액: {increase_amount:,.0f}원")
print(f"보수적 한계ROAS(70% 할인 적용): {conservative_roas}")
print(f"기대 증분 매출: {expected_incremental_rev:,.0f}원")

track_calculation("strategy2_amazon_health_roas", amazon_health_roas, "아마존x건강식품 조합의 ROAS",
                   "SUM(매출액)/SUM(광고비용) WHERE 매체=아마존, 카테고리=건강식품",
                   source_file="./artifacts/cross_media_category.csv", source_columns=["매체","카테고리","매출액","광고비용"], importance="high")
track_calculation("strategy2_increase_amount", increase_amount, "전략2: 아마존x건강식품 예산 50% 증액 금액",
                   "아마존x건강식품 광고비 x 0.5", source_file="./artifacts/cross_media_category.csv",
                   source_columns=["매체","카테고리","광고비용"], importance="high")
track_calculation("strategy2_conservative_roas", conservative_roas, "전략2: 보수적 한계ROAS(원래ROAS의 70% 적용)",
                   "아마존x건강식품ROAS x 0.7", source_file="./artifacts/cross_media_category.csv",
                   source_columns=["매체","카테고리","매출액","광고비용"], importance="high")
track_calculation("strategy2_expected_rev", expected_incremental_rev, "전략2: 예산 증액 시 기대 증분매출(보수적 시나리오)",
                   "증액금액 x 보수적한계ROAS", source_file="./artifacts/cross_media_category.csv",
                   source_columns=["매체","카테고리","매출액","광고비용"], importance="high")

# ===== 전략 3: 네이바 CTR 쏠림(랜딩/타겟팅 최적화)으로 전환율 개선 시나리오 =====
naver_df = df[df['매체']=='네이바']
naver_click = naver_df['클릭수'].sum()
naver_conv = naver_df['전환수'].sum()
naver_cvr = round(naver_conv/naver_click*100, 2)
# 전환율을 쿠빵 수준(6.79%)까지 절반만 개선(보수적) 시나리오
kupang_df = df[df['매체']=='쿠빵']
kupang_cvr = round(kupang_df['전환수'].sum()/kupang_df['클릭수'].sum()*100, 2)
target_cvr = round(naver_cvr + (kupang_cvr - naver_cvr)*0.5, 2)  # 절반만 개선
additional_conv = round(naver_click * (target_cvr - naver_cvr) / 100, 0)
naver_aov = round(naver_df['매출액'].sum() / naver_conv, 0)  # 평균 전환당 매출
additional_rev = round(additional_conv * naver_aov, 0)

print(f"\n=== 전략3 시나리오: 네이바 전환율 개선(랜딩/타겟팅 최적화) ===")
print(f"네이바 현재 전환율: {naver_cvr}%, 목표(쿠빵과 격차 50% 개선): {target_cvr}%")
print(f"네이바 전환당 평균매출(AOV): {naver_aov:,.0f}원")
print(f"추가 전환수: {additional_conv:,.0f}건")
print(f"기대 증분 매출: {additional_rev:,.0f}원")

track_calculation("strategy3_naver_cvr", naver_cvr, "네이바 현재 전환율(%)", "SUM(전환수)/SUM(클릭수)*100 WHERE 매체=네이바",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["매체","전환수","클릭수"], importance="high")
track_calculation("strategy3_target_cvr", target_cvr, "전략3: 네이바 목표 전환율(쿠빵과 격차 50% 개선 가정)",
                   "네이바전환율 + (쿠빵전환율-네이바전환율)*0.5",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["매체","전환수","클릭수"], importance="high")
track_calculation("strategy3_naver_aov", naver_aov, "네이바 전환당 평균 매출(AOV)", "SUM(매출액)/SUM(전환수) WHERE 매체=네이바",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["매체","매출액","전환수"], importance="high")
track_calculation("strategy3_additional_rev", additional_rev, "전략3: 네이바 전환율 개선 시 기대 증분매출",
                   "추가전환수 x 네이바AOV", source_file="/app/data/yummy-food-market.csv",
                   source_columns=["매체","전환수","클릭수","매출액"], importance="high")

save_calculation_metadata()

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 전략 시나리오 수치
### 전략1: 네이바 예산 축소 → 쿠빵 재배분
- 네이바 예산 30% 축소: {naver_cut_amount:,.0f}원
- 순 매출 증분 추정: {net_rev_gain:,.0f}원

### 전략2: 아마존x건강식품(ROAS {amazon_health_roas}) 조합 확대
- 50% 증액: {increase_amount:,.0f}원
- 보수적 한계ROAS: {conservative_roas}
- 기대 증분매출: {expected_incremental_rev:,.0f}원

### 전략3: 네이바 전환율 개선(CTR-CVR 미스매치 해소)
- 현재 전환율 {naver_cvr}% → 목표 {target_cvr}%
- AOV: {naver_aov:,.0f}원
- 기대 증분매출: {additional_rev:,.0f}원
""")
print("✅ Strategy scenarios complete")
