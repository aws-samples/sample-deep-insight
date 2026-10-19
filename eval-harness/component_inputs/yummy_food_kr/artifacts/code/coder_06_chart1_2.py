
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
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
total_cost = df['광고비용'].sum()
total_rev = df['매출액'].sum()
overall_roas = round(total_rev/total_cost, 2)

# ===== Chart 1: 매체별 광고비 vs ROAS (dual-axis) =====
media_agg = df.groupby('매체').agg(광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
media_agg['ROAS'] = (media_agg['매출액']/media_agg['광고비용']).round(2)
media_agg = media_agg.sort_values('광고비용', ascending=False)

fig, ax1 = plt.subplots(figsize=(9.6, 6), dpi=200)
x = np.arange(len(media_agg))
bars = ax1.bar(x, media_agg['광고비용']/1e6, color='#6699cc', label='광고비용(백만원)', width=0.5)
ax1.set_xticks(x)
ax1.set_xticklabels(media_agg['매체'])
ax1.set_ylabel('광고비용(백만원)', fontweight='bold')
ax1.set_ylim(top=media_agg['광고비용'].max()/1e6*1.18)
for b, v in zip(bars, media_agg['광고비용']/1e6):
    ax1.annotate(f'{v:.0f}M', (b.get_x()+b.get_width()/2, b.get_height()), xytext=(0,4),
                 textcoords='offset points', ha='center', va='bottom', color='#000000', fontweight='bold')

ax2 = ax1.twinx()
ax2.plot(x, media_agg['ROAS'], color='#cc3333', marker='o', linewidth=2.5, markersize=8, label='ROAS')
ax2.axhline(overall_roas, color='#333333', linestyle='--', linewidth=1.2)
ax2.text(len(x)-1+0.15, overall_roas, f'전체평균 {overall_roas}', color='#333333', fontweight='bold', va='center')
for xi, v in zip(x, media_agg['ROAS']):
    ax2.annotate(f'{v}', (xi, v), xytext=(0,12), textcoords='offset points', ha='center',
                 color='#cc3333', fontweight='bold', bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='none', alpha=0.8))
ax2.set_ylabel('ROAS (배)', fontweight='bold')
ax2.set_ylim(0, media_agg['ROAS'].max()*1.3)

fig.legend(loc='upper center', bbox_to_anchor=(0.5, 1.02), ncol=2, frameon=False)
plt.title('매체별 광고비 투입 규모 vs ROAS', fontweight='bold', pad=30)
plt.tight_layout()
plt.subplots_adjust(top=0.85)
plt.savefig('./artifacts/chart1_media_cost_vs_roas.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart1_media_cost_vs_roas.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart1")

# ===== Chart 2: 카테고리별 CTR·전환율·ROAS 비교 =====
cat_agg = df.groupby('카테고리').agg(노출수=('노출수','sum'), 클릭수=('클릭수','sum'),
                                       전환수=('전환수','sum'), 광고비용=('광고비용','sum'), 매출액=('매출액','sum')).reset_index()
cat_agg['CTR'] = (cat_agg['클릭수']/cat_agg['노출수']*100).round(2)
cat_agg['전환율'] = (cat_agg['전환수']/cat_agg['클릭수']*100).round(2)
cat_agg['ROAS'] = (cat_agg['매출액']/cat_agg['광고비용']).round(2)
cat_agg = cat_agg.sort_values('ROAS', ascending=False)

fig, axes = plt.subplots(1, 3, figsize=(9.6, 4.0), dpi=200)
metrics = [('CTR', '#6699cc', '%'), ('전환율', '#66aa66', '%'), ('ROAS', '#cc9933', '배')]
for ax, (metric, color, unit) in zip(axes, metrics):
    vals = cat_agg[metric].values
    bars = ax.bar(cat_agg['카테고리'], vals, color=color)
    ax.set_title(metric, fontweight='bold')
    ax.set_ylim(top=vals.max()*1.18)
    for b, v in zip(bars, vals):
        ax.annotate(f'{v}{unit}', (b.get_x()+b.get_width()/2, b.get_height()), xytext=(0,4),
                    textcoords='offset points', ha='center', va='bottom', color='#000000', fontweight='bold')
    ax.tick_params(axis='x', rotation=0)

plt.suptitle('카테고리별 CTR·전환율·ROAS 비교', fontweight='bold')
plt.tight_layout(pad=1.5)
plt.subplots_adjust(top=0.82, wspace=0.4)
plt.savefig('./artifacts/chart2_category_metrics.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart2_category_metrics.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart2")

print("Chart1,2 done")
