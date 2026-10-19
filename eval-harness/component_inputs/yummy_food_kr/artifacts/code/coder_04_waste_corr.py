
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')
total_cost = df['광고비용'].sum()
total_rev = df['매출액'].sum()
overall_roas = round(total_rev/total_cost, 2)

# ===== 광고비 낭비 규모 정량화 =====
# 행 단위 ROAS가 전체 평균(3.39) 미달인 세그먼트의 광고비 합계
# 매체 단위로 평균 미달 매체 식별
media_agg = df.groupby('매체').agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
media_agg['ROAS'] = (media_agg['매출액']/media_agg['광고비용']).round(2)

below_avg_media = media_agg[media_agg['ROAS'] < overall_roas]
below_avg_cost = below_avg_media['광고비용'].sum()
below_avg_cost_share = round(below_avg_cost/total_cost*100, 2)
print(f"전체 평균 ROAS({overall_roas}) 미달 매체: {below_avg_media['매체'].tolist()}")
print(f"해당 매체 광고비 합계: {below_avg_cost:,}원 (전체의 {below_avg_cost_share}%)")

track_calculation("below_avg_media_cost", below_avg_cost, "전체 평균 ROAS 미달 매체(네이바,컬삼,아마존)의 광고비 합계", 
                   "SUM(광고비용) WHERE 매체별ROAS < 전체ROAS(3.39)",
                   source_file="./artifacts/media_agg.csv", source_columns=["매체","광고비용","ROAS"], importance="high")
track_calculation("below_avg_media_cost_share", below_avg_cost_share, "전체 평균 ROAS 미달 매체 광고비 비중(%)",
                   "SUM(광고비용 WHERE ROAS<3.39)/SUM(전체광고비용)*100",
                   source_file="./artifacts/media_agg.csv", source_columns=["매체","광고비용","ROAS"], importance="high")

# 네이바 단독 - 가장 낮은 ROAS, 손익분기 대비
naver = media_agg[media_agg['매체']=='네이바'].iloc[0]
naver_cost = naver['광고비용']
naver_roas = naver['ROAS']
# 네이바를 전체 평균 ROAS로 끌어올렸을 때 증분 매출
naver_potential_rev = naver_cost * overall_roas
naver_actual_rev = naver['매출액']
naver_rev_gap = round(naver_potential_rev - naver_actual_rev, 0)
print(f"\n네이바 광고비: {naver_cost:,}원, ROAS: {naver_roas}")
print(f"네이바가 전체평균 ROAS({overall_roas}) 수준이었다면 매출: {naver_potential_rev:,.0f}원 (실제 {naver_actual_rev:,.0f}원, 차이 {naver_rev_gap:,.0f}원)")

track_calculation("naver_rev_gap", naver_rev_gap, "네이바 매체가 전체 평균 ROAS(3.39) 수준이었을 경우의 매출 증분 추정치",
                   "(네이바 광고비 x 전체평균ROAS) - 네이바 실제매출",
                   source_file="./artifacts/media_agg.csv", source_columns=["매체","광고비용","매출액"], importance="high")

# ===== 상관관계 분석 =====
corr_df = df[['노출수','클릭수','전환수','광고비용','매출액','CTR','전환율','ROAS']].corr()
print("\n=== 주요 상관관계 ===")
print(f"CTR vs 전환율: {corr_df.loc['CTR','전환율']:.3f}")
print(f"광고비용 vs ROAS: {corr_df.loc['광고비용','ROAS']:.3f}")
print(f"CTR vs ROAS: {corr_df.loc['CTR','ROAS']:.3f}")
print(f"전환율 vs ROAS: {corr_df.loc['전환율','ROAS']:.3f}")

ctr_cvr_corr = round(corr_df.loc['CTR','전환율'], 3)
cost_roas_corr = round(corr_df.loc['광고비용','ROAS'], 3)
ctr_roas_corr = round(corr_df.loc['CTR','ROAS'], 3)
cvr_roas_corr = round(corr_df.loc['전환율','ROAS'], 3)

track_calculation("corr_ctr_cvr", ctr_cvr_corr, "CTR과 전환율 간 피어슨 상관계수", "CORR(CTR, 전환율)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["CTR","전환율"], importance="high")
track_calculation("corr_cost_roas", cost_roas_corr, "광고비용과 ROAS 간 피어슨 상관계수", "CORR(광고비용, ROAS)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["광고비용","ROAS"], importance="high")
track_calculation("corr_ctr_roas", ctr_roas_corr, "CTR과 ROAS 간 피어슨 상관계수", "CORR(CTR, ROAS)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["CTR","ROAS"], importance="high")
track_calculation("corr_cvr_roas", cvr_roas_corr, "전환율과 ROAS 간 피어슨 상관계수", "CORR(전환율, ROAS)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["전환율","ROAS"], importance="high")

# ===== 네이바 진단: 클릭은 많은데 전환이 안되는 유형 =====
naver_df = df[df['매체']=='네이바']
naver_ctr = round(naver_df['클릭수'].sum()/naver_df['노출수'].sum()*100, 2)
naver_cvr = round(naver_df['전환수'].sum()/naver_df['클릭수'].sum()*100, 2)
kupang_df = df[df['매체']=='쿠빵']
kupang_ctr = round(kupang_df['클릭수'].sum()/kupang_df['노출수'].sum()*100, 2)
kupang_cvr = round(kupang_df['전환수'].sum()/kupang_df['클릭수'].sum()*100, 2)
print(f"\n네이바: CTR {naver_ctr}% (최고) vs 전환율 {naver_cvr}% (최저)")
print(f"쿠빵: CTR {kupang_ctr}% vs 전환율 {kupang_cvr}% (최고)")

track_calculation("naver_ctr_vs_cvr_gap", round(naver_ctr - naver_cvr,2), "네이바 CTR과 전환율 격차(클릭은 높으나 전환이 낮은 패턴)",
                   "네이바 CTR(%) - 네이바 전환율(%)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["매체","CTR","전환율"], importance="high")

save_calculation_metadata()

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 광고비 낭비 규모 및 상관관계 분석
- 전체 평균 ROAS 미달 매체(네이바, 컬삼, 아마존) 광고비 합계: {below_avg_cost:,}원 ({below_avg_cost_share}%)
- 네이바가 전체 평균 ROAS 수준 달성 시 매출 증분 추정: {naver_rev_gap:,.0f}원
- CTR-전환율 상관계수: {ctr_cvr_corr} (음의 상관 → 클릭 많아도 전환 안 되는 매체 존재)
- 광고비용-ROAS 상관계수: {cost_roas_corr}
- 네이바: CTR {naver_ctr}%(최고) vs 전환율 {naver_cvr}%(최저) - 클릭은 유도되나 구매전환 안되는 전형적 낭비 패턴
- 쿠빵: CTR {kupang_ctr}% vs 전환율 {kupang_cvr}%(최고) - 효율적 전환 구조
""")
print("✅ Complete")
