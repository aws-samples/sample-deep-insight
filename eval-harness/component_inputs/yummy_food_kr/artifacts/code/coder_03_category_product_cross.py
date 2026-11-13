
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np

df = pd.read_pickle('./artifacts/cache/df_main.pkl')

total_cost = df['광고비용'].sum()
total_rev = df['매출액'].sum()

# ===== 카테고리별 집계 =====
cat_agg = df.groupby('카테고리').agg(
    노출수=('노출수','sum'), 클릭수=('클릭수','sum'), 전환수=('전환수','sum'),
    광고비용=('광고비용','sum'), 매출액=('매출액','sum')
).reset_index()
cat_agg['CTR'] = (cat_agg['클릭수']/cat_agg['노출수']*100).round(2)
cat_agg['전환율'] = (cat_agg['전환수']/cat_agg['클릭수']*100).round(2)
cat_agg['ROAS'] = (cat_agg['매출액']/cat_agg['광고비용']).round(2)
cat_agg['CPA'] = (cat_agg['광고비용']/cat_agg['전환수']).round(1)
cat_agg['광고비점유율'] = (cat_agg['광고비용']/total_cost*100).round(2)
cat_agg['매출점유율'] = (cat_agg['매출액']/total_rev*100).round(2)
cat_agg = cat_agg.sort_values('ROAS', ascending=False)
print("=== 카테고리별 성과 ===")
print(cat_agg.to_string(index=False))

for _, row in cat_agg.iterrows():
    c = row['카테고리']
    track_calculation(f"cat_{c}_roas", row['ROAS'], f"{c} 카테고리 ROAS", "SUM(매출액)/SUM(광고비용) by 카테고리",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["카테고리","매출액","광고비용"], importance="high")
    track_calculation(f"cat_{c}_ctr", row['CTR'], f"{c} 카테고리 CTR(%)", "SUM(클릭수)/SUM(노출수)*100 by 카테고리",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["카테고리","클릭수","노출수"], importance="high")
    track_calculation(f"cat_{c}_cvr", row['전환율'], f"{c} 카테고리 전환율(%)", "SUM(전환수)/SUM(클릭수)*100 by 카테고리",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["카테고리","전환수","클릭수"], importance="high")
    track_calculation(f"cat_{c}_cost_share", row['광고비점유율'], f"{c} 카테고리 광고비 점유율(%)", "SUM(광고비용 by 카테고리)/SUM(전체 광고비용)*100",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["카테고리","광고비용"], importance="high")

cat_agg.to_csv('./artifacts/category_agg.csv', index=False, encoding='utf-8-sig')

# ===== 상품별 집계 =====
prod_agg = df.groupby(['상품명','카테고리']).agg(
    노출수=('노출수','sum'), 클릭수=('클릭수','sum'), 전환수=('전환수','sum'),
    광고비용=('광고비용','sum'), 매출액=('매출액','sum')
).reset_index()
prod_agg['CTR'] = (prod_agg['클릭수']/prod_agg['노출수']*100).round(2)
prod_agg['전환율'] = (prod_agg['전환수']/prod_agg['클릭수']*100).round(2)
prod_agg['ROAS'] = (prod_agg['매출액']/prod_agg['광고비용']).round(2)
prod_agg['CPA'] = (prod_agg['광고비용']/prod_agg['전환수']).round(1)
prod_agg['광고비점유율'] = (prod_agg['광고비용']/total_cost*100).round(2)
prod_agg = prod_agg.sort_values('ROAS', ascending=False)
print("\n=== 상품별 성과 (ROAS 내림차순) ===")
print(prod_agg.to_string(index=False))

for _, row in prod_agg.iterrows():
    p = row['상품명']
    track_calculation(f"prod_{p}_roas", row['ROAS'], f"{p} 상품 ROAS", "SUM(매출액)/SUM(광고비용) by 상품명",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["상품명","매출액","광고비용"], importance="high")
    track_calculation(f"prod_{p}_ctr", row['CTR'], f"{p} 상품 CTR(%)", "SUM(클릭수)/SUM(노출수)*100 by 상품명",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["상품명","클릭수","노출수"], importance="high")
    track_calculation(f"prod_{p}_cvr", row['전환율'], f"{p} 상품 전환율(%)", "SUM(전환수)/SUM(클릭수)*100 by 상품명",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["상품명","전환수","클릭수"], importance="high")
    track_calculation(f"prod_{p}_cost", row['광고비용'], f"{p} 상품 총 광고비용", "SUM(광고비용) by 상품명",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["상품명","광고비용"], importance="high")

prod_agg.to_csv('./artifacts/product_agg.csv', index=False, encoding='utf-8-sig')

# ===== 매체 x 카테고리 교차 =====
cross_agg = df.groupby(['매체','카테고리']).agg(
    광고비용=('광고비용','sum'), 매출액=('매출액','sum'),
    클릭수=('클릭수','sum'), 노출수=('노출수','sum'), 전환수=('전환수','sum')
).reset_index()
cross_agg['ROAS'] = (cross_agg['매출액']/cross_agg['광고비용']).round(2)
cross_agg['CTR'] = (cross_agg['클릭수']/cross_agg['노출수']*100).round(2)
cross_agg['전환율'] = (cross_agg['전환수']/cross_agg['클릭수']*100).round(2)
print("\n=== 매체x카테고리 교차 ROAS ===")
pivot_roas = cross_agg.pivot(index='매체', columns='카테고리', values='ROAS')
print(pivot_roas.to_string())

for _, row in cross_agg.iterrows():
    key = f"cross_{row['매체']}_{row['카테고리']}"
    track_calculation(f"{key}_roas", row['ROAS'], f"{row['매체']}x{row['카테고리']} 교차 ROAS", "SUM(매출액)/SUM(광고비용) by 매체,카테고리",
                       source_file="/app/data/yummy-food-market.csv", source_columns=["매체","카테고리","매출액","광고비용"], importance="high")

cross_agg.to_csv('./artifacts/cross_media_category.csv', index=False, encoding='utf-8-sig')
pivot_roas.to_csv('./artifacts/cross_pivot_roas.csv', encoding='utf-8-sig')

save_calculation_metadata()
print("\n✅ Saved category_agg.csv, product_agg.csv, cross_media_category.csv")
