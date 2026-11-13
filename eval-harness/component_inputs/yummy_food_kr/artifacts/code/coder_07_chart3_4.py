
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

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

# ===== Chart 3: 상품별 ROAS Top/Bottom 랭킹 (horizontal bar, 전체 6개) =====
prod_agg = df.groupby('상품명').agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
prod_agg['ROAS'] = (prod_agg['매출액']/prod_agg['광고비용']).round(2)
prod_agg = prod_agg.sort_values('ROAS', ascending=True)

fig, ax = plt.subplots(figsize=(9.6, max(4, 0.4*len(prod_agg))), dpi=200)
colors = ['#cc3333' if v < prod_agg['ROAS'].median() else '#3366cc' for v in prod_agg['ROAS']]
bars = ax.barh(prod_agg['상품명'], prod_agg['ROAS'], color=colors)
overall_roas = round(df['매출액'].sum()/df['광고비용'].sum(), 2)
ax.axvline(overall_roas, color='#333333', linestyle='--', linewidth=1.2)
ax.text(overall_roas, len(prod_agg)-0.3, f' 전체평균 {overall_roas}', color='#333333', fontweight='bold', va='center')
ax.set_xlim(0, prod_agg['ROAS'].max()*1.25)
for b, v in zip(bars, prod_agg['ROAS']):
    ax.annotate(f'{v}', (b.get_width(), b.get_y()+b.get_height()/2), xytext=(5,0),
                textcoords='offset points', ha='left', va='center', color='#000000', fontweight='bold')
ax.set_xlabel('ROAS (배)', fontweight='bold')
ax.set_title('상품별 ROAS 랭킹 (빨강: 평균 이하)', fontweight='bold')
plt.tight_layout()
plt.savefig('./artifacts/chart3_product_roas_ranking.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart3_product_roas_ranking.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart3")

# ===== Chart 4: 광고비 vs ROAS 산점도 (버블 크기=매출), 매체x카테고리 레벨 =====
cross_agg = df.groupby(['매체','카테고리']).agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
cross_agg['ROAS'] = (cross_agg['매출액']/cross_agg['광고비용']).round(2)
cross_agg['label'] = cross_agg['매체'] + '-' + cross_agg['카테고리']

fig, ax = plt.subplots(figsize=(9.6, 6.0), dpi=200)
sizes = cross_agg['매출액'] / cross_agg['매출액'].max() * 600
media_colors = {'쿠빵':'#cc3333', '네이바':'#33aa33', '아마존':'#3366cc', '컬삼':'#cc9933'}
colors = [media_colors[m] for m in cross_agg['매체']]
sc = ax.scatter(cross_agg['광고비용']/1e6, cross_agg['ROAS'], s=sizes, c=colors, alpha=0.7, edgecolors='black', linewidth=0.8)
overall_roas_v = round(df['매출액'].sum()/df['광고비용'].sum(), 2)
ax.axhline(overall_roas_v, color='#333333', linestyle='--', linewidth=1.2)
ax.text(0.98, overall_roas_v, f'전체평균 {overall_roas_v}', color='#333333', fontweight='bold',
        transform=ax.get_yaxis_transform(), ha='right', va='bottom')

from matplotlib.lines import Line2D
legend_elems = [Line2D([0],[0], marker='o', color='w', markerfacecolor=c, markersize=10, label=m) for m,c in media_colors.items()]
ax.legend(handles=legend_elems, loc='upper left', bbox_to_anchor=(1.02,1), title='매체')
plt.subplots_adjust(right=0.78)

# annotate top/bottom points
ymin, ymax = ax.get_ylim(); xmin, xmax = ax.get_xlim()
ymargin = (ymax-ymin)*0.06; xmargin=(xmax-xmin)*0.06
ax.set_ylim(ymin-ymargin, ymax+ymargin)
ax.set_xlim(xmin-xmargin, xmax+xmargin)

texts = []
top_label = cross_agg.sort_values('ROAS', ascending=False).head(2)
bottom_label = cross_agg.sort_values('ROAS', ascending=True).head(2)
for _, row in pd.concat([top_label, bottom_label]).iterrows():
    t = ax.annotate(row['label'], (row['광고비용']/1e6, row['ROAS']), xytext=(8,5), textcoords='offset points',
                     color='#000000', fontweight='bold', fontsize=10)
    texts.append(t)

ax.set_xlabel('광고비용(백만원)', fontweight='bold')
ax.set_ylabel('ROAS (배)', fontweight='bold')
ax.set_title('매체x카테고리 광고비 대비 ROAS (버블=매출규모)', fontweight='bold')
plt.tight_layout()
plt.savefig('./artifacts/chart4_cost_vs_roas_bubble.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart4_cost_vs_roas_bubble.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart4")
print("Chart3,4 done")
