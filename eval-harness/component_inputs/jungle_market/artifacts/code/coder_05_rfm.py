
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
max_date = df['order_date'].max()

# RFM per customer (order-level aggregation first)
order_level = df.groupby(['customer_id','order_id']).agg(order_date=('order_date','first'), order_value=('line_total','sum')).reset_index()

cust_rfm = order_level.groupby('customer_id').agg(
    recency_days=('order_date', lambda x: (max_date - x.max()).days),
    frequency=('order_id', 'nunique'),
    monetary=('order_value', 'sum')
).reset_index()

print(cust_rfm.describe().to_string())

# RFM scoring using quantiles (1-4 scale, 4=best)
cust_rfm['R_score'] = pd.qcut(cust_rfm['recency_days'].rank(method='first'), 4, labels=[4,3,2,1]).astype(int)
cust_rfm['F_score'] = pd.qcut(cust_rfm['frequency'].rank(method='first'), 4, labels=[1,2,3,4]).astype(int)
cust_rfm['M_score'] = pd.qcut(cust_rfm['monetary'].rank(method='first'), 4, labels=[1,2,3,4]).astype(int)
cust_rfm['RFM_score'] = cust_rfm['R_score'] + cust_rfm['F_score'] + cust_rfm['M_score']

def segment_label(row):
    if row['RFM_score'] >= 10:
        return 'VIP(최우수)'
    elif row['RFM_score'] >= 8:
        return '우수고객'
    elif row['RFM_score'] >= 6:
        return '일반고객'
    elif row['RFM_score'] >= 4:
        return '이탈위험'
    else:
        return '이탈/저가치'

cust_rfm['segment'] = cust_rfm.apply(segment_label, axis=1)

seg_summary = cust_rfm.groupby('segment').agg(
    customers=('customer_id','count'),
    total_monetary=('monetary','sum'),
    avg_monetary=('monetary','mean'),
    avg_frequency=('frequency','mean'),
    avg_recency=('recency_days','mean')
).sort_values('total_monetary', ascending=False)
seg_summary['customer_share'] = seg_summary['customers'] / cust_rfm.shape[0]
seg_summary['sales_share'] = seg_summary['total_monetary'] / total_sales
print(seg_summary.to_string())

for seg, row in seg_summary.iterrows():
    seg_id = seg.replace('(','_').replace(')','').replace('/','_')
    track_calculation(f"seg_customers_{seg_id}", row['customers'], f"RFM 세그먼트 고객수 - {seg}",
                       "COUNT(customer_id) GROUP BY RFM segment", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["customer_id","order_date","order_id","line_total"], importance="high")
    track_calculation(f"seg_sales_{seg_id}", row['total_monetary'], f"RFM 세그먼트 매출 - {seg}",
                       "SUM(order monetary) GROUP BY RFM segment", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["customer_id","order_date","order_id","line_total"], importance="high")
    track_calculation(f"seg_sales_share_{seg_id}", row['sales_share'], f"RFM 세그먼트 매출 비중 - {seg}",
                       "seg_sales / total_sales", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["customer_id","order_date","order_id","line_total"], importance="high")
    track_calculation(f"seg_customer_share_{seg_id}", row['customer_share'], f"RFM 세그먼트 고객 비중 - {seg}",
                       "seg_customers / total_customers", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["customer_id"], importance="high")
    track_calculation(f"seg_avg_monetary_{seg_id}", row['avg_monetary'], f"RFM 세그먼트 1인당 평균 매출 - {seg}",
                       "AVG(monetary) GROUP BY RFM segment", source_file="./artifacts/cache/df_main.pkl",
                       source_columns=["customer_id","order_date","order_id","line_total"], importance="high")

# customer value concentration: top 10% / 20%
cust_rfm_sorted = cust_rfm.sort_values('monetary', ascending=False).reset_index(drop=True)
n_cust = len(cust_rfm_sorted)
top10pct_n = max(1, int(np.ceil(n_cust*0.1)))
top20pct_n = max(1, int(np.ceil(n_cust*0.2)))
top10pct_sales_share = cust_rfm_sorted.head(top10pct_n)['monetary'].sum() / total_sales
top20pct_sales_share = cust_rfm_sorted.head(top20pct_n)['monetary'].sum() / total_sales
track_calculation("top10pct_cust_sales_share", top10pct_sales_share, "상위 10% 고객의 매출 집중도",
                   f"SUM(monetary) top {top10pct_n} customers / total_sales", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["customer_id","line_total"], importance="high")
track_calculation("top20pct_cust_sales_share", top20pct_sales_share, "상위 20% 고객의 매출 집중도",
                   f"SUM(monetary) top {top20pct_n} customers / total_sales", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["customer_id","line_total"], importance="high")
print(f"\n상위10%({top10pct_n}명) 매출집중도: {top10pct_sales_share:.2%}")
print(f"상위20%({top20pct_n}명) 매출집중도: {top20pct_sales_share:.2%}")

# repeat purchase rate: customers with frequency >= 2
repeat_customers = (cust_rfm['frequency'] >= 2).sum()
repeat_rate = repeat_customers / n_cust
track_calculation("repeat_customers", repeat_customers, "재구매 고객 수(주문 2회 이상)", "COUNT(customer_id WHERE frequency>=2)",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_id","order_id"], importance="high")
track_calculation("repeat_rate", repeat_rate, "재구매율(고객 기준)", "repeat_customers / total_customers",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_id","order_id"], importance="high")
print(f"재구매 고객수: {repeat_customers}, 재구매율: {repeat_rate:.2%}")

# churn risk: recency > 7 days (half the period) among returning-capable customers
churn_risk_customers = (cust_rfm['recency_days'] > 7).sum()
churn_risk_rate = churn_risk_customers / n_cust
track_calculation("churn_risk_customers", churn_risk_customers, "이탈 위험 고객 수(최근 구매 7일 초과)",
                   "COUNT(customer_id WHERE recency_days>7)", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["customer_id","order_date"], importance="high")
track_calculation("churn_risk_rate", churn_risk_rate, "이탈 위험 고객 비율", "churn_risk_customers / total_customers",
                   source_file="./artifacts/cache/df_main.pkl", source_columns=["customer_id","order_date"], importance="high")
print(f"이탈위험고객(7일 이상 미구매): {churn_risk_customers}명 ({churn_risk_rate:.2%})")

# average repurchase interval days (for customers with freq>=2)
multi_order_dates = order_level.sort_values(['customer_id','order_date']).groupby('customer_id')['order_date'].apply(lambda x: x.diff().dt.days.dropna())
avg_repurchase_interval = multi_order_dates.explode().dropna().mean() if len(multi_order_dates)>0 else np.nan
# flatten properly
intervals = []
for cid, grp in order_level.sort_values(['customer_id','order_date']).groupby('customer_id'):
    d = grp['order_date'].diff().dt.days.dropna().tolist()
    intervals.extend(d)
avg_repurchase_interval = np.mean(intervals) if intervals else np.nan
track_calculation("avg_repurchase_interval", avg_repurchase_interval, "평균 재구매 간격(일)",
                   "MEAN(order_date diff) for customers with multiple orders", source_file="./artifacts/cache/df_main.pkl",
                   source_columns=["customer_id","order_date"], importance="high")
print(f"평균 재구매 간격: {avg_repurchase_interval:.2f}일")

save_calculation_metadata()
cust_rfm.to_csv('./artifacts/cache/customer_rfm.csv', index=False)
print("Cached customer_rfm.csv")

# Chart 3: RFM 세그먼트별 규모 및 매출 비중
fig, axes = plt.subplots(1, 2, figsize=(9.6, 4.5), dpi=200)
seg_order = seg_summary.index.tolist()
colors = plt.cm.Set2(np.linspace(0,1,len(seg_order)))

ax = axes[0]
bars = ax.barh(seg_order[::-1], seg_summary.loc[seg_order,'customers'].values[::-1], color=colors[::-1])
for bar, val, share in zip(bars, seg_summary.loc[seg_order,'customers'].values[::-1], seg_summary.loc[seg_order,'customer_share'].values[::-1]):
    ax.text(bar.get_width(), bar.get_y()+bar.get_height()/2, f' {val}명({share:.0%})', va='center', ha='left', fontsize=10)
ax.set_xlim(0, seg_summary['customers'].max()*1.35)
ax.set_title('세그먼트별 고객 수', fontweight='bold')
ax.set_xlabel('고객 수')

ax = axes[1]
bars = ax.barh(seg_order[::-1], seg_summary.loc[seg_order,'total_monetary'].values[::-1], color=colors[::-1])
for bar, val, share in zip(bars, seg_summary.loc[seg_order,'total_monetary'].values[::-1], seg_summary.loc[seg_order,'sales_share'].values[::-1]):
    ax.text(bar.get_width(), bar.get_y()+bar.get_height()/2, f' ${val:,.0f}({share:.0%})', va='center', ha='left', fontsize=10)
ax.set_xlim(0, seg_summary['total_monetary'].max()*1.4)
ax.set_title('세그먼트별 매출 비중', fontweight='bold')
ax.set_xlabel('매출 (USD)')

plt.tight_layout()
plt.savefig('./artifacts/chart3_rfm_segments.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart3_rfm_segments.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart3_rfm_segments.png")

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## RFM 고객 세그먼트 분석
- 전체 고객: {n_cust}명
""")
    for seg, row in seg_summary.iterrows():
        f.write(f"- {seg}: {int(row['customers'])}명({row['customer_share']:.1%}), 매출 ${row['total_monetary']:,.2f}({row['sales_share']:.1%}), 1인평균 ${row['avg_monetary']:,.2f}, 평균 Recency {row['avg_recency']:.1f}일\n")
    f.write(f"""- 상위 10% 고객 매출 집중도: {top10pct_sales_share:.1%}
- 상위 20% 고객 매출 집중도: {top20pct_sales_share:.1%}
- 재구매 고객수(2회 이상 주문): {repeat_customers}명, 재구매율: {repeat_rate:.1%}
- 이탈 위험 고객(7일 이상 미구매): {churn_risk_customers}명({churn_risk_rate:.1%})
- 평균 재구매 간격: {avg_repurchase_interval:.1f}일
- 차트: chart3_rfm_segments.png
""")
print("✅ Step5 완료")
