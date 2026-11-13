
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')

# ===== 전체 벤치마크 =====
total_impr = df['노출수'].sum()
total_click = df['클릭수'].sum()
total_conv = df['전환수'].sum()
total_cost = df['광고비용'].sum()
total_rev = df['매출액'].sum()

overall_ctr = round(total_click / total_impr * 100, 2)
overall_cvr = round(total_conv / total_click * 100, 2)
overall_roas = round(total_rev / total_cost, 2)
overall_cpc = round(total_cost / total_click, 1)
overall_cpa = round(total_cost / total_conv, 1)

print("=== 전체 벤치마크 (2025-09, 30일, 4매체x6상품) ===")
print(f"총 노출수: {total_impr:,}")
print(f"총 클릭수: {total_click:,}")
print(f"총 전환수: {total_conv:,}")
print(f"총 광고비: {total_cost:,}원")
print(f"총 매출: {total_rev:,}원")
print(f"전체 CTR: {overall_ctr}%")
print(f"전체 전환율: {overall_cvr}%")
print(f"전체 ROAS: {overall_roas}")
print(f"전체 CPC: {overall_cpc}원")
print(f"전체 CPA: {overall_cpa}원")

track_calculation("total_cost", total_cost, "전체 총 광고비용", "SUM(광고비용)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["광고비용"], importance="high")
track_calculation("total_rev", total_rev, "전체 총 매출액", "SUM(매출액)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["매출액"], importance="high")
track_calculation("overall_ctr", overall_ctr, "전체 통합 CTR(%)", "SUM(클릭수)/SUM(노출수)*100",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["클릭수","노출수"], importance="high")
track_calculation("overall_cvr", overall_cvr, "전체 통합 전환율(%)", "SUM(전환수)/SUM(클릭수)*100",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["전환수","클릭수"], importance="high")
track_calculation("overall_roas", overall_roas, "전체 통합 ROAS", "SUM(매출액)/SUM(광고비용)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["매출액","광고비용"], importance="high")
track_calculation("overall_cpc", overall_cpc, "전체 통합 CPC(원)", "SUM(광고비용)/SUM(클릭수)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["광고비용","클릭수"], importance="high")
track_calculation("overall_cpa", overall_cpa, "전체 통합 CPA(원)", "SUM(광고비용)/SUM(전환수)",
                   source_file="/app/data/yummy-food-market.csv", source_columns=["광고비용","전환수"], importance="high")

# ===== 매체별 집계 =====
media_agg = df.groupby('매체').agg(
    노출수=('노출수','sum'), 클릭수=('클릭수','sum'), 전환수=('전환수','sum'),
    광고비용=('광고비용','sum'), 매출액=('매출액','sum')
).reset_index()
media_agg['CTR'] = (media_agg['클릭수']/media_agg['노출수']*100).round(2)
media_agg['전환율'] = (media_agg['전환수']/media_agg['클릭수']*100).round(2)
media_agg['ROAS'] = (media_agg['매출액']/media_agg['광고비용']).round(2)
media_agg['CPA'] = (media_agg['광고비용']/media_agg['전환수']).round(1)
media_agg['광고비점유율'] = (media_agg['광고비용']/total_cost*100).round(2)
media_agg['매출점유율'] = (media_agg['매출액']/total_rev*100).round(2)
media_agg = media_agg.sort_values('ROAS', ascending=False)

print("\n=== 매체별 성과 ===")
print(media_agg.to_string(index=False))

for _, row in media_agg.iterrows():
    m = row['매체']
    track_calculation(f"media_{m}_roas", row['ROAS'], f"{m} 매체 ROAS", "SUM(매출액)/SUM(광고비용) by 매체",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["매체","매출액","광고비용"], importance="high")
    track_calculation(f"media_{m}_ctr", row['CTR'], f"{m} 매체 CTR(%)", "SUM(클릭수)/SUM(노출수)*100 by 매체",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["매체","클릭수","노출수"], importance="high")
    track_calculation(f"media_{m}_cvr", row['전환율'], f"{m} 매체 전환율(%)", "SUM(전환수)/SUM(클릭수)*100 by 매체",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["매체","전환수","클릭수"], importance="high")
    track_calculation(f"media_{m}_cost_share", row['광고비점유율'], f"{m} 매체 광고비 점유율(%)", "SUM(광고비용 by 매체)/SUM(전체 광고비용)*100",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["매체","광고비용"], importance="high")
    track_calculation(f"media_{m}_rev_share", row['매출점유율'], f"{m} 매체 매출 점유율(%)", "SUM(매출액 by 매체)/SUM(전체 매출액)*100",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["매체","매출액"], importance="high")
    track_calculation(f"media_{m}_cpa", row['CPA'], f"{m} 매체 CPA(원)", "SUM(광고비용)/SUM(전환수) by 매체",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["매체","광고비용","전환수"], importance="high")

media_agg.to_csv('./artifacts/media_agg.csv', index=False, encoding='utf-8-sig')
save_calculation_metadata()
print("\n✅ Saved media_agg.csv")
