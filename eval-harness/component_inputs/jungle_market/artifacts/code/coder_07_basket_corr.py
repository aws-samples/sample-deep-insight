
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np
from itertools import combinations
from collections import Counter
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

# Basket analysis: co-purchase pairs
order_products = df.groupby('order_id')['product_name'].apply(lambda x: sorted(set(x))).reset_index()
order_products['n_items'] = order_products['product_name'].apply(len)
print("주문당 고유상품수 분포:\n", order_products['n_items'].describe())

multi_item_orders = order_products[order_products['n_items'] >= 2]
n_multi = len(multi_item_orders)
n_total_orders = len(order_products)
multi_item_share = n_multi / n_total_orders
track_calculation("multi_item_order_share", multi_item_share, "2개 이상 상품을 구매한 주문 비중",
                   "COUNT(orders WHERE n_items>=2) / COUNT(orders)", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["order_id","product_name"], importance="high")
print(f"\n2개 이상 상품 주문 비중: {multi_item_share:.2%} ({n_multi}/{n_total_orders})")

pair_counter = Counter()
for items in multi_item_orders['product_name']:
    for pair in combinations(items, 2):
        pair_counter[pair] += 1

top_pairs = pair_counter.most_common(10)
print("\n상위 동시구매 조합 TOP10:")
for pair, cnt in top_pairs:
    print(pair, cnt)
    pair_name = f"{pair[0]}_{pair[1]}".replace(' ','_').replace('(','').replace(')','')
    track_calculation(f"basket_pair_{pair_name}", cnt, f"동시구매 조합 - {pair[0]} + {pair[1]}",
                       "COUNT(orders containing both products)", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["order_id","product_name"], importance="high")

save_calculation_metadata()

# Correlation analysis - numeric features at order level
order_level = df.groupby('order_id').agg(
    order_value=('line_total','sum'), n_items=('product_id','nunique'),
    total_qty=('quantity','sum'), total_discount=('discount','sum'), order_hour=('order_hour','first')
).reset_index()

corr_cols = ['order_value','n_items','total_qty','total_discount','order_hour']
corr_matrix = order_level[corr_cols].corr()
print("\n상관관계 매트릭스:\n", corr_matrix)

corr_labels_kr = {'order_value':'주문금액','n_items':'상품종류수','total_qty':'총수량','total_discount':'할인액','order_hour':'주문시간'}

# track key correlations
key_corr_value_nitems = corr_matrix.loc['order_value','n_items']
track_calculation("corr_value_nitems", key_corr_value_nitems, "주문금액과 상품종류수의 상관계수",
                   "CORR(order_value, n_items)", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["order_id","line_total","product_id"], importance="high")

save_calculation_metadata()

# Chart: 상관관계 히트맵
fig, ax = plt.subplots(figsize=(9.6, 6), dpi=200)
labels_list = [corr_labels_kr[c] for c in corr_cols]
im = ax.imshow(corr_matrix.values, cmap='RdYlGn', vmin=-1, vmax=1)
ax.set_xticks(range(len(corr_cols)))
ax.set_xticklabels(labels_list, rotation=45, ha='right')
ax.set_yticks(range(len(corr_cols)))
ax.set_yticklabels(labels_list)
for i in range(len(corr_cols)):
    for j in range(len(corr_cols)):
        ax.text(j, i, f'{corr_matrix.values[i,j]:.2f}', ha='center', va='center', color='#000000')
ax.set_title('주요 변수 상관관계 히트맵', fontweight='bold')
cbar = plt.colorbar(im, ax=ax)
cbar.set_label('상관계수')
plt.tight_layout()
plt.savefig('./artifacts/chart6_correlation_heatmap.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart6_correlation_heatmap.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart6_correlation_heatmap.png")

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 장바구니(동시구매) 분석
- 2개 이상 상품 구매 주문 비중: {multi_item_share:.1%} ({n_multi}/{n_total_orders}건)
- 최다 동시구매 조합 TOP3:
""")
    for pair, cnt in top_pairs[:3]:
        f.write(f"  - {pair[0]} + {pair[1]}: {cnt}건\n")
    f.write(f"""
## 상관관계 분석
- 주문금액과 상품종류수 상관계수: {key_corr_value_nitems:.2f} (상품 종류를 늘릴수록 주문금액 증가 경향)
- 차트: chart6_correlation_heatmap.png
""")
print("✅ Step7 완료")
