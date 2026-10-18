
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

plt.rcParams['font.family'] = ['NanumGothic']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['svg.fonttype'] = 'path'
plt.rcParams.update({
    'font.size': 12, 'axes.titlesize': 16, 'axes.labelsize': 12,
    'xtick.labelsize': 11, 'ytick.labelsize': 11, 'legend.fontsize': 12,
    'figure.titlesize': 18,
    'text.color': '#000000', 'axes.labelcolor': '#000000', 'axes.edgecolor': '#000000',
    'axes.titlecolor': '#000000', 'xtick.color': '#000000', 'ytick.color': '#000000',
    'axes.labelweight': 'bold', 'axes.titleweight': 'bold', 'figure.titleweight': 'bold',
    'font.weight': 'bold',
})

df = pd.read_pickle('./artifacts/cache/df_main.pkl')

total_sales = df['line_total'].sum()

# Category analysis
cat_sales = df.groupby('category')['line_total'].sum().sort_values(ascending=False)
cat_qty = df.groupby('category')['quantity'].sum()
cat_share = cat_sales / total_sales

for cat in cat_sales.index:
    track_calculation(f"cat_sales_{cat.replace(' ','_').replace('&','and')}", cat_sales[cat], f"카테고리별 매출 - {cat}",
                       "SUM(line_total) GROUP BY category", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["category","line_total"], importance="high")

print(cat_sales)
print("\n카테고리 비중:\n", cat_share)

# Pareto: top 20% products by sales
prod_sales = df.groupby(['product_id','product_name'])['line_total'].sum().sort_values(ascending=False).reset_index()
n_products = len(prod_sales)
top20_n = max(1, int(np.ceil(n_products * 0.2)))
top20_sales = prod_sales.head(top20_n)['line_total'].sum()
top20_share = top20_sales / total_sales
track_calculation("top20_product_share", top20_share, "상위 20% 상품의 매출 비중(파레토)",
                   f"SUM(line_total) top {top20_n} products / SUM(line_total) all",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["product_id","line_total"], importance="high")
print(f"\n상품수:{n_products}, 상위20%({top20_n}개) 매출비중: {top20_share:.2%}")

# Top 10 products
top10 = prod_sales.head(10)
for i, row in top10.iterrows():
    track_calculation(f"top_product_{row['product_id']}", row['line_total'], f"상위 상품 매출 - {row['product_name']}",
                       "SUM(line_total) GROUP BY product_id", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["product_id","line_total"], importance="high")
print(top10.to_string())

# Bottom performers (lowest sales among products with at least some sales)
bottom5 = prod_sales.tail(5)
print("\n하위 5개 상품:\n", bottom5.to_string())

save_calculation_metadata()

# Chart 2: 카테고리별 매출 기여도 (horizontal bar sorted desc)
fig, ax = plt.subplots(figsize=(9.6, max(4, 0.4*len(cat_sales))), dpi=200)
colors = plt.cm.viridis(np.linspace(0.2, 0.85, len(cat_sales)))
bars = ax.barh(cat_sales.index[::-1], cat_sales.values[::-1], color=colors[::-1])
for bar, val, share in zip(bars, cat_sales.values[::-1], cat_share.values[::-1]):
    ax.text(bar.get_width(), bar.get_y()+bar.get_height()/2, f' ${val:,.0f} ({share:.1%})',
            va='center', ha='left', color='#000000')
ax.set_xlim(0, cat_sales.max()*1.3)
ax.set_title('카테고리별 매출 기여도', fontweight='bold')
ax.set_xlabel('매출 (USD)')
ax.set_ylabel('카테고리')
plt.tight_layout()
plt.savefig('./artifacts/chart2_category_sales.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart2_category_sales.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart2_category_sales.png")

# Top 15 product pareto chart
top15 = prod_sales.head(15).copy()
top15['label'] = top15['product_name']
top15 = top15.sort_values('line_total', ascending=True)
cum_share = (prod_sales.head(15)['line_total'].cumsum() / total_sales * 100)

fig, ax1 = plt.subplots(figsize=(9.6, max(5, 0.4*15)), dpi=200)
bars = ax1.barh(top15['label'], top15['line_total'], color='#2E86AB')
for bar, val in zip(bars, top15['line_total']):
    ax1.text(bar.get_width(), bar.get_y()+bar.get_height()/2, f' ${val:,.0f}', va='center', ha='left', color='#000000')
ax1.set_xlim(0, top15['line_total'].max()*1.3)
ax1.set_title('상위 15개 상품 매출 (파레토)', fontweight='bold')
ax1.set_xlabel('매출 (USD)')
ax1.set_ylabel('상품명')
plt.tight_layout()
plt.savefig('./artifacts/chart2b_top_products_pareto.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart2b_top_products_pareto.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart2b_top_products_pareto.png")

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 카테고리/상품 분석
- 카테고리별 매출 1위: {cat_sales.index[0]} (${cat_sales.iloc[0]:,.2f}, 비중 {cat_share.iloc[0]:.1%})
- 카테고리별 매출 2위: {cat_sales.index[1]} (${cat_sales.iloc[1]:,.2f}, 비중 {cat_share.iloc[1]:.1%})
- 카테고리별 매출 3위: {cat_sales.index[2]} (${cat_sales.iloc[2]:,.2f}, 비중 {cat_share.iloc[2]:.1%})
- 총 상품 수: {n_products}개, 상위 20%({top20_n}개) 상품이 매출의 {top20_share:.1%} 차지 (파레토 법칙 확인)
- 매출 1위 상품: {top10.iloc[0]['product_name']} (${top10.iloc[0]['line_total']:,.2f})
- 차트: chart2_category_sales.png, chart2b_top_products_pareto.png
""")
print("✅ Step4 완료")
