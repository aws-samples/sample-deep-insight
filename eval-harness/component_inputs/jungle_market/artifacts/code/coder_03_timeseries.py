
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

daily = df.groupby('order_date')['line_total'].sum().sort_index()
print(daily)

df['week'] = np.where(df['order_date'] <= pd.Timestamp('2026-03-08'), 'Week1(3/2-3/8)', 'Week2(3/9-3/15)')
week_sales = df.groupby('week')['line_total'].sum()
wow_growth = (week_sales['Week2(3/9-3/15)'] - week_sales['Week1(3/2-3/8)']) / week_sales['Week1(3/2-3/8)']
track_calculation("week1_sales", week_sales['Week1(3/2-3/8)'], "1주차(3/2-3/8) 매출", "SUM(line_total) WHERE week='Week1'",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","line_total"], importance="high")
track_calculation("week2_sales", week_sales['Week2(3/9-3/15)'], "2주차(3/9-3/15) 매출", "SUM(line_total) WHERE week='Week2'",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","line_total"], importance="high")
track_calculation("wow_growth", wow_growth, "주차 대비 매출 성장률(WoW)", "(week2_sales-week1_sales)/week1_sales",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","line_total"], importance="high")
print(f"1주차: {week_sales['Week1(3/2-3/8)']:,.2f}, 2주차: {week_sales['Week2(3/9-3/15)']:,.2f}, WoW성장률: {wow_growth:.2%}")

daily_avg = daily.mean()
days_count = daily.shape[0]
next_month_baseline = daily_avg * 30
track_calculation("daily_avg_sales", daily_avg, "일평균 매출", "MEAN(daily SUM(line_total))",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","line_total"], importance="high")
track_calculation("next_month_baseline", next_month_baseline, "다음달 매출 베이스라인 추정(일평균x30일)", "daily_avg_sales * 30",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","line_total"], importance="high")
print(f"일평균매출: {daily_avg:,.2f}, 기간일수:{days_count}, 다음달 베이스라인(30일 추정): {next_month_baseline:,.2f}")

df['dow'] = df['order_date'].dt.day_name()
dow_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
dow_sales = df.groupby('dow')['line_total'].sum().reindex(dow_order)
dow_korean = {'Monday':'월','Tuesday':'화','Wednesday':'수','Thursday':'목','Friday':'금','Saturday':'토','Sunday':'일'}
for d,v in dow_sales.items():
    track_calculation(f"dow_sales_{d}", v, f"요일별 매출 - {dow_korean[d]}요일", "SUM(line_total) GROUP BY day_of_week",
                       source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","line_total"], importance="high")
print(dow_sales)

peak_dow = dow_sales.idxmax()
track_calculation("peak_dow", peak_dow, "매출 최고 요일", "ARGMAX(SUM(line_total) GROUP BY day_of_week)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_date","line_total"], importance="high")

hour_sales = df.groupby('order_hour')['line_total'].sum().sort_index()
peak_hour = hour_sales.idxmax()
track_calculation("peak_hour", int(peak_hour), "매출 최고 시간대", "ARGMAX(SUM(line_total) GROUP BY order_hour)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_hour","line_total"], importance="high")
track_calculation("peak_hour_sales", hour_sales.max(), "최고 시간대 매출", "MAX(SUM(line_total) GROUP BY order_hour)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["order_hour","line_total"], importance="high")
print(hour_sales)

save_calculation_metadata()

fig, ax = plt.subplots(figsize=(9.6, 6), dpi=200)
x_num = np.arange(len(daily))
ax.plot(daily.index, daily.values, marker='o', color='#2E86AB', linewidth=2, label='일별 매출')
z = np.polyfit(x_num, daily.values, 1)
trend = np.poly1d(z)(x_num)
ax.plot(daily.index, trend, linestyle='--', color='#E63946', linewidth=2, label='추세선')
for i, (idx, val) in enumerate(daily.items()):
    if i == 0:
        ax.annotate(f'{val:,.0f}', (idx, val), xytext=(0,8), textcoords='offset points', ha='left', color='#2E86AB')
    elif i == len(daily)-1:
        ax.annotate(f'{val:,.0f}', (idx, val), xytext=(0,8), textcoords='offset points', ha='right', color='#2E86AB')
    elif val == daily.max() or val == daily.min():
        ax.annotate(f'{val:,.0f}', (idx, val), xytext=(0,8), textcoords='offset points', ha='center', color='#2E86AB')
ax.set_title('일별 매출 추이 및 추세선 (2026-03-02 ~ 2026-03-15)', fontweight='bold')
ax.set_xlabel('날짜')
ax.set_ylabel('매출 (USD)')
ymin, ymax = daily.min(), daily.max()
margin = (ymax-ymin)*0.15
ax.set_ylim(ymin-margin, ymax+margin)
plt.xticks(rotation=45)
ax.legend(loc='upper left', bbox_to_anchor=(1.02,1))
plt.subplots_adjust(right=0.78)
plt.tight_layout()
plt.savefig('./artifacts/chart1_daily_trend.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart1_daily_trend.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart1_daily_trend.png")

pivot = df.pivot_table(index='dow', columns='order_hour', values='line_total', aggfunc='sum', fill_value=0).reindex(dow_order)
pivot.index = [dow_korean[d] for d in pivot.index]
fig, ax = plt.subplots(figsize=(11, 5), dpi=200)
im = ax.imshow(pivot.values, cmap='RdYlGn', aspect='auto')
ax.set_xticks(range(len(pivot.columns)))
ax.set_xticklabels(pivot.columns, fontsize=9)
ax.set_yticks(range(len(pivot.index)))
ax.set_yticklabels(pivot.index)
ax.set_xlabel('주문 시간(시)')
ax.set_ylabel('요일')
ax.set_title('요일 x 시간대별 매출 히트맵 (USD)', fontweight='bold')
cbar = plt.colorbar(im, ax=ax)
cbar.set_label('매출 (USD)')
plt.tight_layout()
plt.savefig('./artifacts/chart4_dow_hour_heatmap.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart4_dow_hour_heatmap.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart4_dow_hour_heatmap.png")

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 시계열 분석
- 1주차(3/2-3/8) 매출: ${week_sales['Week1(3/2-3/8)']:,.2f}
- 2주차(3/9-3/15) 매출: ${week_sales['Week2(3/9-3/15)']:,.2f}
- 주차 대비 성장률(WoW): {wow_growth:+.2%}
- 일평균 매출: ${daily_avg:,.2f} (관측 {days_count}일 기준)
- 다음달(30일) 매출 베이스라인 추정(현재 트렌드 유지 가정): ${next_month_baseline:,.2f}
- 매출 최고 요일: {dow_korean[peak_dow]}요일 (${dow_sales[peak_dow]:,.2f})
- 매출 최고 시간대: {peak_hour}시 (${hour_sales.max():,.2f})
- 차트: chart1_daily_trend.png, chart4_dow_hour_heatmap.png
""")
print("✅ Step3 완료")
