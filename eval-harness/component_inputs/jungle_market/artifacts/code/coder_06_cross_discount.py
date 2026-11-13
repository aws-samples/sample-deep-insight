
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

# order-level dataframe with customer attributes
order_level = df.groupby('order_id').agg(
    customer_id=('customer_id','first'), gender=('gender','first'), age_group=('age_group','first'),
    city=('city','first'), country=('country','first'), channel=('channel','first'),
    customer_type=('customer_type','first'), order_value=('line_total','sum')
).reset_index()

n_orders = order_level.shape[0]

# City analysis
city_sales = df.groupby('city')['line_total'].sum().sort_values(ascending=False)
city_aov = order_level.groupby('city')['order_value'].mean().reindex(city_sales.index)
for city in city_sales.index:
    track_calculation(f"city_sales_{city.replace(' ','_')}", city_sales[city], f"도시별 매출 - {city}",
                       "SUM(line_total) GROUP BY city", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["city","line_total"], importance="high")
    track_calculation(f"city_aov_{city.replace(' ','_')}", city_aov[city], f"도시별 AOV - {city}",
                       "MEAN(order_value) GROUP BY city", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["city","order_id","line_total"], importance="high")
print("도시별 매출:\n", city_sales)
print("\n도시별 AOV:\n", city_aov)

# Age x Gender cross
age_gender_aov = order_level.groupby(['age_group','gender'])['order_value'].mean().unstack()
age_gender_sales = order_level.groupby(['age_group','gender'])['order_value'].sum().unstack()
print("\n연령x성별 AOV:\n", age_gender_aov)
print("\n연령x성별 매출:\n", age_gender_sales)

# find highest AOV sub-segment
flat_aov = order_level.groupby(['age_group','gender'])['order_value'].mean()
best_seg = flat_aov.idxmax()
track_calculation("best_age_gender_aov_value", flat_aov.max(), f"최고 AOV 연령x성별 세그먼트 - {best_seg[0]}/{best_seg[1]}",
                   "MAX(MEAN(order_value) GROUP BY age_group,gender)", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["age_group","gender","order_id","line_total"], importance="high")
print(f"\n최고 AOV 세그먼트: {best_seg}, AOV={flat_aov.max():.2f}")

# channel analysis
channel_sales = df.groupby('channel')['line_total'].sum()
channel_orders = order_level.groupby('channel')['order_id'].nunique()
channel_aov = order_level.groupby('channel')['order_value'].mean()
channel_customers = df.groupby('channel')['customer_id'].nunique()
for ch in channel_sales.index:
    track_calculation(f"channel_sales_{ch}", channel_sales[ch], f"채널별 매출 - {ch}",
                       "SUM(line_total) GROUP BY channel", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["channel","line_total"], importance="high")
    track_calculation(f"channel_aov_{ch}", channel_aov[ch], f"채널별 AOV - {ch}",
                       "MEAN(order_value) GROUP BY channel", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["channel","order_id","line_total"], importance="high")
print("\n채널별 매출:\n", channel_sales)
print("채널별 AOV:\n", channel_aov)
print("채널별 주문수:\n", channel_orders)

# promo analysis
df['has_promo'] = df['promo_code'].notna()
promo_sales = df.groupby(df['promo_code'].fillna('없음'))['line_total'].sum().sort_values(ascending=False)
promo_orders = df.groupby(df['promo_code'].fillna('없음'))['order_id'].nunique()
promo_discount = df.groupby(df['promo_code'].fillna('없음'))['discount'].sum()
print("\n프로모코드별 매출:\n", promo_sales)
print("프로모코드별 할인액:\n", promo_discount)

for pc in promo_sales.index:
    pc_id = pc if pc!='없음' else 'none'
    track_calculation(f"promo_sales_{pc_id}", promo_sales[pc], f"프로모션별 매출 - {pc}",
                       "SUM(line_total) GROUP BY promo_code", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["promo_code","line_total"], importance="high")

# AOV with vs without promo
order_promo = df.groupby('order_id').agg(order_value=('line_total','sum'), has_promo=('has_promo','max')).reset_index()
aov_promo = order_promo.groupby('has_promo')['order_value'].mean()
track_calculation("aov_with_promo", aov_promo.get(True,0), "프로모션 적용 주문 AOV", "MEAN(order_value) WHERE has_promo=True",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","order_id","line_total"], importance="high")
track_calculation("aov_without_promo", aov_promo.get(False,0), "프로모션 미적용 주문 AOV", "MEAN(order_value) WHERE has_promo=False",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["promo_code","order_id","line_total"], importance="high")
print("\n프로모션 적용여부별 AOV:\n", aov_promo)

# discount rate per row & sales relationship -> bucket discount pct
df['discount_pct'] = np.where(df['unit_price']*df['quantity']>0, df['discount']/(df['unit_price']*df['quantity']), 0)
bins = [-0.001, 0, 0.05, 0.10, 0.15, 0.20, 1.0]
labels = ['0%','0-5%','5-10%','10-15%','15-20%','20%+']
df['discount_bucket'] = pd.cut(df['discount_pct'], bins=bins, labels=labels)
disc_bucket_sales = df.groupby('discount_bucket')['line_total'].sum()
disc_bucket_rows = df.groupby('discount_bucket').size()
disc_bucket_avg_qty = df.groupby('discount_bucket')['quantity'].mean()
print("\n할인구간별 매출:\n", disc_bucket_sales)
print("할인구간별 건수:\n", disc_bucket_rows)
print("할인구간별 평균구매수량:\n", disc_bucket_avg_qty)

for b in disc_bucket_sales.index:
    track_calculation(f"discbucket_sales_{b}", disc_bucket_sales[b], f"할인율 구간별 매출 - {b}",
                       "SUM(line_total) GROUP BY discount_pct bucket", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["discount","unit_price","quantity","line_total"], importance="high")

save_calculation_metadata()

# Chart: 할인율 구간별 매출/건수
fig, ax1 = plt.subplots(figsize=(9.6, 6), dpi=200)
colors_bar = '#2E86AB'
bars = ax1.bar(disc_bucket_sales.index.astype(str), disc_bucket_sales.values, color=colors_bar, label='매출(USD)')
ax1.set_ylabel('매출 (USD)', color=colors_bar)
ax1.set_xlabel('할인율 구간')
for bar, val in zip(bars, disc_bucket_sales.values):
    ax1.annotate(f'{val:,.0f}', (bar.get_x()+bar.get_width()/2, bar.get_height()), xytext=(0,4), textcoords='offset points', ha='center', va='bottom', color='#000000')
ax1.set_ylim(top=disc_bucket_sales.max()*1.18)

ax2 = ax1.twinx()
ax2.plot(disc_bucket_sales.index.astype(str), disc_bucket_rows.values, color='#E63946', marker='o', linewidth=2, label='거래건수')
ax2.set_ylabel('거래 건수', color='#E63946')
for x, val in zip(disc_bucket_sales.index.astype(str), disc_bucket_rows.values):
    ax2.annotate(f'{val}', (x, val), xytext=(0,12), textcoords='offset points', ha='center',
                 bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='none', alpha=0.8), color='#E63946')

ax1.set_title('할인율 구간별 매출 및 거래건수', fontweight='bold')
fig.legend(loc='upper center', bbox_to_anchor=(0.5, 1.02), ncol=2, frameon=False)
plt.tight_layout()
plt.savefig('./artifacts/chart5_discount_analysis.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart5_discount_analysis.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart5_discount_analysis.png")

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 지역/속성별 교차 분석
- 매출 1위 도시: {city_sales.index[0]} (${city_sales.iloc[0]:,.2f}), AOV ${city_aov[city_sales.index[0]]:,.2f}
- AOV 최고 도시: {city_aov.idxmax()} (${city_aov.max():,.2f})
- 최고 AOV 연령x성별 세그먼트: {best_seg[0]}/{best_seg[1]} (AOV ${flat_aov.max():,.2f})

## 채널 분석
- App 매출: ${channel_sales.get('App',0):,.2f}, AOV ${channel_aov.get('App',0):,.2f}
- Web 매출: ${channel_sales.get('Web',0):,.2f}, AOV ${channel_aov.get('Web',0):,.2f}

## 프로모션 분석
- 프로모션 미적용 매출: ${promo_sales.get('없음',0):,.2f}
- SAVE10 매출: ${promo_sales.get('SAVE10',0):,.2f}
- WELCOME10 매출: ${promo_sales.get('WELCOME10',0):,.2f}
- PASTA30 매출: ${promo_sales.get('PASTA30',0):,.2f}
- 프로모션 적용 주문 AOV: ${aov_promo.get(True,0):,.2f} vs 미적용 AOV: ${aov_promo.get(False,0):,.2f}

## 할인율 구간별 분석
""")
    for b in disc_bucket_sales.index:
        f.write(f"- {b}: 매출 ${disc_bucket_sales[b]:,.2f}, 건수 {disc_bucket_rows[b]}건, 평균구매수량 {disc_bucket_avg_qty[b]:.2f}\n")
    f.write("- 차트: chart5_discount_analysis.png\n")
print("✅ Step6 완료")
