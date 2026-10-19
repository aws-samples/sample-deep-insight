
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

# ===== Chart 5: 매체x카테고리 ROAS 히트맵 =====
cross_agg = df.groupby(['매체','카테고리']).agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
cross_agg['ROAS'] = (cross_agg['매출액']/cross_agg['광고비용']).round(2)
pivot = cross_agg.pivot(index='매체', columns='카테고리', values='ROAS')
# order rows by overall ROAS desc, cols by category order
media_order = df.groupby('매체').apply(lambda g: g['매출액'].sum()/g['광고비용'].sum(), include_groups=False).sort_values(ascending=False).index
pivot = pivot.loc[media_order]

fig, ax = plt.subplots(figsize=(9.6, max(5, 0.3*len(pivot))), dpi=200)
cmap = plt.cm.RdYlGn.copy()
im = ax.imshow(pivot.values, cmap=cmap, aspect='auto', vmin=pivot.values.min()*0.8, vmax=pivot.values.max()*1.05)
ax.set_xticks(range(len(pivot.columns))); ax.set_xticklabels(pivot.columns)
ax.set_yticks(range(len(pivot.index))); ax.set_yticklabels(pivot.index)
for i in range(len(pivot.index)):
    for j in range(len(pivot.columns)):
        v = pivot.values[i,j]
        ax.text(j, i, f'{v:.2f}', ha='center', va='center', color='#000000', fontweight='bold', fontsize=13)
cbar = fig.colorbar(im, ax=ax, shrink=0.8)
cbar.set_label('ROAS (배)', fontweight='bold')
ax.set_title('매체 x 카테고리 ROAS 히트맵', fontweight='bold')
plt.tight_layout()
plt.savefig('./artifacts/chart5_media_category_heatmap.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart5_media_category_heatmap.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart5")

# ===== Chart 6: 일별 ROAS 추이 라인차트 =====
df2 = df.copy()
df2['날짜'] = pd.to_datetime(df2['날짜'])
daily = df2.groupby('날짜').agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
daily['ROAS'] = (daily['매출액']/daily['광고비용']).round(2)
overall_roas = round(df['매출액'].sum()/df['광고비용'].sum(), 2)

fig, ax = plt.subplots(figsize=(9.6, 6.0), dpi=200)
ax.plot(daily['날짜'], daily['ROAS'], color='#3366cc', marker='o', markersize=4, linewidth=1.8)
ax.axhline(overall_roas, color='#333333', linestyle='--', linewidth=1.2)
ax.text(daily['날짜'].iloc[-1], overall_roas, f' 전체평균 {overall_roas}', color='#333333', fontweight='bold', va='bottom')

# annotate max/min
max_idx = daily['ROAS'].idxmax(); min_idx = daily['ROAS'].idxmin()
ax.annotate(f"최고 {daily.loc[max_idx,'ROAS']}", (daily.loc[max_idx,'날짜'], daily.loc[max_idx,'ROAS']),
            xytext=(0,10), textcoords='offset points', ha='center', color='#cc3333', fontweight='bold')
ax.annotate(f"최저 {daily.loc[min_idx,'ROAS']}", (daily.loc[min_idx,'날짜'], daily.loc[min_idx,'ROAS']),
            xytext=(0,-15), textcoords='offset points', ha='center', color='#cc3333', fontweight='bold')
# first/last
ax.annotate(f"{daily['ROAS'].iloc[0]}", (daily['날짜'].iloc[0], daily['ROAS'].iloc[0]), xytext=(0,8),
            textcoords='offset points', ha='left', color='#3366cc', fontweight='bold')
ax.annotate(f"{daily['ROAS'].iloc[-1]}", (daily['날짜'].iloc[-1], daily['ROAS'].iloc[-1]), xytext=(0,8),
            textcoords='offset points', ha='right', color='#3366cc', fontweight='bold')

ymin, ymax = daily['ROAS'].min(), daily['ROAS'].max()
margin = (ymax-ymin)*0.15
ax.set_ylim(ymin-margin, ymax+margin*1.3)
ax.set_xlabel('날짜', fontweight='bold')
ax.set_ylabel('ROAS (배)', fontweight='bold')
ax.set_title('일별 ROAS 추이 (2025년 9월)', fontweight='bold')
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig('./artifacts/chart6_daily_roas_trend.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart6_daily_roas_trend.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart6")
print("Chart5,6 done")
