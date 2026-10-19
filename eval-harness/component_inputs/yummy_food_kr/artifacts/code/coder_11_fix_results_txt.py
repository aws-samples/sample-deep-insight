
import re

path = './artifacts/all_results.txt'
with open(path, encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    "전체 평균 ROAS 미달 매체(네이바, 컬삼, 아마존) 광고비 합계: 176,375,000원 (45.42%)",
    "전체 평균 ROAS(3.39) 미달 매체(네이바 ROAS 2.35, 아마존 ROAS 3.17) 광고비 합계: 176,375,000원 (전체의 45.42%)"
)

# 오래된(비보수적) 전략3 수치 블록 제거하고 최신 보수적 수치로 교체
content = content.replace(
    """### 전략3: 네이바 전환율 개선(CTR-CVR 미스매치 해소)
- 현재 전환율 2.13% → 목표 4.46%
- AOV: 20,850원
- 기대 증분매출: 277,263,300원
""",
    """### 전략3: 네이바 전환율 개선(CTR-CVR 미스매치 해소, 보수적 가정: 쿠빵과의 격차 20%만 개선)
- 현재 전환율 2.13% → 목표 3.06%
- AOV: 20,850원
- 기대 증분매출: 110,671,800원 (네이바 현재 매출 대비 43.6%)
"""
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("수정 완료")
print(content)
