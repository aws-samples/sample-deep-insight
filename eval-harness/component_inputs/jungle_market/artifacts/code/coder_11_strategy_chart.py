
import sys
sys.path.insert(0, './artifacts/code')
from coder_analysis_utils import track_calculation, save_calculation_metadata

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json

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

with open('./artifacts/calculation_metadata.json', encoding='utf-8') as f:
    meta = json.load(f)
calc_dict = {c['id']: c['value'] for c in meta['calculations']}

strategies = ['전략1\n이탈고객 재활성화', '전략2\n크로스셀/번들', '전략3\n저조요일 평탄화']
conservative = [calc_dict['s1_conservative'], calc_dict['s2_conservative_v2'], calc_dict['s3_conservative_final']]
base = [calc_dict['s1_base'], calc_dict['s2_base_v2'], calc_dict['s3_base_final']]
optimistic = [calc_dict['s1_optimistic'], calc_dict['s2_optimistic_v2'], calc_dict['s3_optimistic_final']]

x = np.arange(len(strategies))
width = 0.25

fig, ax = plt.subplots(figsize=(9.6, 6), dpi=200)
bars1 = ax.bar(x - width, conservative, width, label='보수적', color='#A8DADC')
bars2 = ax.bar(x, base, width, label='기본', color='#2E86AB')
bars3 = ax.bar(x + width, optimistic, width, label='낙관적', color='#1D3557')

for bars in [bars1, bars2, bars3]:
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f'${h:,.0f}', (bar.get_x()+bar.get_width()/2, h), xytext=(0,4),
                    textcoords='offset points', ha='center', va='bottom', fontsize=10)

ax.set_xticks(x)
ax.set_xticklabels(strategies)
ax.set_ylabel('기대 매출 증분 (USD, 30일 환산)')
ax.set_title('실행 전략별 기대 매출 증분 시나리오 비교', fontweight='bold')
ax.set_ylim(top=max(optimistic)*1.2)
ax.legend(loc='upper left', bbox_to_anchor=(1.02,1))
plt.subplots_adjust(right=0.78)
plt.tight_layout()
plt.savefig('./artifacts/chart7_strategy_impact.png', bbox_inches='tight', dpi=200)
plt.savefig('./artifacts/chart7_strategy_impact.svg', bbox_inches='tight')
plt.close()
print("📊 Saved chart7_strategy_impact.png")

print("Total files in artifacts:")
import os
for f in sorted(os.listdir('./artifacts')):
    print(f)

with open('./artifacts/all_results.txt', 'a', encoding='utf-8') as f:
    f.write(f"""
## 차트 목록
- chart1_daily_trend.png: 일별 매출 추이 및 추세선
- chart2_category_sales.png: 카테고리별 매출 기여도
- chart2b_top_products_pareto.png: 상위 15개 상품 매출(파레토)
- chart3_rfm_segments.png: RFM 세그먼트별 고객수/매출비중
- chart4_dow_hour_heatmap.png: 요일x시간대 매출 히트맵
- chart5_discount_analysis.png: 할인율 구간별 매출/건수
- chart6_correlation_heatmap.png: 주요 변수 상관관계 히트맵
- chart7_strategy_impact.png: 실행전략별 기대매출증분 시나리오 비교
""")
print("✅ Step11(차트) 완료")
