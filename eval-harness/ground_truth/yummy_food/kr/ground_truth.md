# Yummy Food (kr): Ground Truth

Answer key for `yummy-food-market.csv` (in `managed-agentcore/data/yummy_food/kr/`; the same file is in `self-hosted/data/yummy_food/kr/` and `deep-insight-web/sample_data/yummyfood-kr/kr-yummy-food-market.csv`). Every number below is recomputed from the CSV. The file is kept out of those data directories on purpose: they ship to the runtime, and the agents must never read this sheet.

## Overview

| Metric | Value |
|---|---|
| Period | 2025-09-01 to 2025-09-30 (30 days) |
| Rows | 720 (4 media x 6 products x 30 days, one row each) |
| Impressions | 77,961,417 |
| Clicks | 1,401,947 |
| Conversions | 65,509 |
| Ad spend | 388,296,000원 (3.88억 원) |
| Revenue | 1,316,606,500원 (13.17억 원) |
| CTR | 1.8% |
| Conversion rate | 4.67% |
| ROAS | 3.39 (339%) |
| CPC | 277원 |
| Revenue per conversion | 20,098원 |

## Definitions used in every answer

- One row = one 날짜 x 매체 x 상품명. Every combination appears exactly once: no duplicates, no missing rows, nothing to clean.
- 매출액 is the revenue of the row's conversions (purchases after an ad click) only, in KRW. 광고비용 is in KRW.
- **CTR** = SUM(클릭수) / SUM(노출수) x 100. **Conversion rate** = SUM(전환수) / SUM(클릭수) x 100. **ROAS** = SUM(매출액) / SUM(광고비용), a ratio (4.14 = 414%).
- **CPC** = SUM(광고비용) / SUM(클릭수). **Revenue per conversion** = SUM(매출액) / SUM(전환수).
- The CTR, 전환율 and ROAS columns are each row's own ratio, rounded to 2 decimals. A figure for several rows is recomputed from the summed counts, never averaged from these columns (see B1).
- 주요구매연령 / 주요구매성별 are fixed per product: the same in every row of a product, whatever the media or date.

## Part A. Familiar patterns

**A1. Media**

| Media | Ad spend | Revenue | CTR | Conversion rate | ROAS | CPC | 신선식품 share of own revenue |
|---|---|---|---|---|---|---|---|
| 쿠빵 | 161,615,000원 | 669,613,700원 | 1.36% | 6.79% | 4.14 | 342원 | 33.72% |
| 네이바 | 107,925,000원 | 253,662,100원 | 3.21% | 2.13% | 2.35 | 189원 | 33.63% |
| 아마존 | 68,450,000원 | 216,952,800원 | 1.2% | 6.39% | 3.17 | 347원 | 32.72% |
| 컬삼 | 50,306,000원 | 176,377,900원 | 1.8% | 5.35% | 3.51 | 312원 | 77.55% |

- Revenue ranking: 쿠빵 > 네이바 > 아마존 > 컬삼. Ad spend ranking: 쿠빵 > 네이바 > 아마존 > 컬삼.
- 컬삼 gets 77.55% of its revenue from 신선식품; the other media 32.72-33.72%.

**A2. Category**

| Category | Ad spend | Revenue | Revenue share | ROAS |
|---|---|---|---|---|
| 신선식품 | 148,655,000원 | 518,837,300원 | 39.41% | 3.49 |
| 간편식 | 139,179,000원 | 460,878,600원 | 35.01% | 3.31 |
| 건강식품 | 100,462,000원 | 336,890,600원 | 25.59% | 3.35 |

Category ROAS values are close to each other; only the revenue share ranking is used as an answer.

**A3. Product**

| Product | Category | Revenue | Conversions | Revenue per conversion | ROAS | Main buyers |
|---|---|---|---|---|---|---|
| 프리미엄과일 | 신선식품 | 250,464,300원 | 5,607 | 44,670원 | 3.85 | 40대 여성 |
| 오메가3 | 건강식품 | 177,071,600원 | 4,572 | 38,730원 | 3.53 | 50대 여성 |
| 프로틴바 | 건강식품 | 159,819,000원 | 6,591 | 24,248원 | 3.18 | 30대 여성 |
| 즉석밥세트 | 간편식 | 239,992,100원 | 12,709 | 18,884원 | 3.45 | 20대 남성 |
| 냉동만두 | 간편식 | 220,886,500원 | 15,198 | 14,534원 | 3.17 | 30대 남성 |
| 샐러드키트 | 신선식품 | 268,373,000원 | 20,832 | 12,883원 | 3.21 | 30대 여성 |

- Highest revenue per conversion: **프리미엄과일**. Highest ROAS: **프리미엄과일** (3.85; next 오메가3 3.53). Other product ROAS values are close and not used as answers.

**A4. Weekday**

| Weekday | Average daily revenue |
|---|---|
| Saturday | 53,814,175원 |
| Sunday | 49,638,950원 |
| Tuesday | 42,067,800원 |
| Wednesday | 41,243,575원 |
| Thursday | 40,886,425원 |
| Monday | 40,494,540원 |
| Friday | 40,365,575원 |

- Saturday is highest, then Sunday; weekend days average 1.26x weekdays. Average daily spend is about the same on every day of the week (Monday to Friday 12,558,000원 to 13,259,800원; Saturday 12,943,000원, Sunday 12,944,000원): the weekend lift comes from a higher conversion rate. The five weekdays are close to each other and are not ranked.
- September 2025 has 5 Mondays and 5 Tuesdays and 4 of every other weekday. Ranked by total revenue instead of the daily average, the order is Saturday > Tuesday > Monday > Sunday; the question asks for the average.

## Part B. Patterns that need real analysis

Each item lists the answer a shallow analysis gives (naive) and the correct one.

### B1. Averaging the ROAS column picks the wrong top media

- Naive: mean of the ROAS column per media ranks **아마존** first (5.74).
- Correct: SUM(매출액) / SUM(광고비용) ranks **쿠빵** first (4.14); 아마존 is 3rd (3.17).
- Why: 아마존 runs 프로틴바, 오메가3 and 프리미엄과일 on a tiny budget (about 60,000원 a day) at a high ROAS; those rows count as much as its large rows in a plain mean, but carry little spend. Small-budget 아마존 rows: spend 5,389,000원, ROAS 8.8; large-budget rows: spend 63,061,000원, ROAS 2.69.

| Media | ROAS (SUM/SUM, correct) | Mean of ROAS column (naive) |
|---|---|---|
| 쿠빵 | 4.14 | 4.45 |
| 컬삼 | 3.51 | 3.1 |
| 아마존 | 3.17 | 5.74 |
| 네이바 | 2.35 | 2.35 |

- The questions fix the period to the whole month. Over 2025-09-16 to 09-30 alone, 쿠빵 (3.53) and 컬삼 (3.50) are nearly tied, so a ranking for the second half has no single answer and is not asked.

### B2. The highest CTR has the lowest ROAS

- Naive: 네이바 has the highest CTR, so it returns the most revenue per 원 spent; move budget to it.
- Correct: 네이바 has the highest CTR but the lowest conversion rate and the lowest ROAS of the 4 media: CTR 3.21%, conversion rate 2.13%, ROAS 2.35.
- CTR ranking: 네이바 > 컬삼 > 쿠빵 > 아마존. Conversion rate ranking: 쿠빵 > 아마존 > 컬삼 > 네이바.
- 네이바 also has the lowest CPC (189원; the others 312원 to 347원): its clicks are cheap but convert least. Which media is "most efficient" depends on the metric, so the question asks for the ROAS rank.

### B3. 쿠빵 budget increase: diminishing returns

- 쿠빵 daily ad spend doubled from 2025-09-16; the other media kept the same daily spend all month.
- Naive: 쿠빵 has the highest ROAS (4.14), so the extra budget earns about that much.
- Correct: the extra 쿠빵 spend returned only 1.67원 per 1원, below the full-month ROAS of every other media; 쿠빵's ROAS fell from 5.38 to 3.53 after the increase.
- Incremental ROAS = (쿠빵 revenue after - before) / (쿠빵 ad spend after - before); both windows are 15 days with 2 Saturdays and 2 Sundays each.

| 쿠빵 | Days | Ad spend | Revenue | ROAS | CTR | Conversion rate |
|---|---|---|---|---|---|---|
| Before | 2025-09-01 to 2025-09-15 | 53,953,000원 | 290,025,900원 | 5.38 | 1.5% | 7.48% |
| After | 2025-09-16 to 2025-09-30 | 107,662,000원 | 379,587,800원 | 3.53 | 1.28% | 6.35% |
| Increment | | 53,709,000원 | 89,561,900원 | **1.67** | | |

- Average daily spend: 쿠빵 3,596,867원 → 7,177,467원; the other 3 media together 7,542,133원 → 7,569,933원 (unchanged).
- The lowest other-media ROAS is 네이바 2.35, still above 1.67. By product the increment ranges from 1.42 to 1.95, on weekdays only it is 1.57 and on weekends only 1.94; every split stays below 네이바's 2.35.
- Not determined by the data, so not scored: whether more 쿠빵 budget pays off (1.67 is above 1, but the file has no margins), and what the other media would return on extra spend (their spend never changed).

## Evaluation questions

Each question has exactly one correct answer. `Naive` is the wrong answer a shallow analysis gives.

| ID | Question | Correct answer | Naive (wrong) answer | Scoring |
|---|---|---|---|---|
| Q1 | Which media has the highest ROAS over the whole month (2025-09-01 to 09-30)? | 쿠빵 (4.14) | 아마존 (5.74, mean of the ROAS column) | exact match |
| Q2 | Rank the 4 media by ROAS over the whole month (2025-09-01 to 09-30), highest first. | 쿠빵 > 컬삼 > 아마존 > 네이바 | 아마존 > 쿠빵 > 컬삼 > 네이바 (mean of the ROAS column) | exact match |
| Q3 | Which media has the highest CTR, and where does it rank among the 4 media by ROAS? | 네이바 (CTR 3.21%); last of the 4 by ROAS (2.35), and also last by conversion rate (2.13%) | first: the highest CTR taken as the best return | exact match: 네이바, and 4th (last) by ROAS |
| Q4 | Did any media change its ad spend during the month? | 쿠빵 doubled its daily spend from 2025-09-16 (3,596,867원 to 7,177,467원 a day on average) | no change | exact match |
| Q5 | What did the extra 쿠빵 spend after 2025-09-16 return (incremental ROAS vs 09-01 to 09-15), and is it above or below each other media's full-month ROAS? | 1.67 = (revenue after - before) / (spend after - before); below every other media's full-month ROAS (lowest: 네이바 2.35). 쿠빵 ROAS fell from 5.38 to 3.53 | about 4.14 (쿠빵's full-month ROAS), above every other media | full credit requires the incremental ROAS (about 1.67) and that it is below every other media's full-month ROAS. A split by product or by weekday/weekend (1.42 to 1.95) gets partial credit. A budget recommendation is not scored: the file has no margins, and the other media never changed their spend |
| Q6 | What are total revenue, total ad spend and overall ROAS? | 1,316,606,500원 / 388,296,000원 / 3.39 |  | exact match (ROAS may be written as a percent) |
| Q7 | Rank the media by revenue. | 쿠빵 > 네이바 > 아마존 > 컬삼 |  | exact match |
| Q8 | Which media gets the largest share of its own revenue from 신선식품? | 컬삼 (77.55%) |  | exact match |
| Q9 | Rank the categories by revenue share. | 신선식품 (39.41%) > 간편식 (35.01%) > 건강식품 (25.59%) |  | exact match |
| Q10 | Which product has the highest revenue per conversion? | 프리미엄과일 (44,670원) |  | exact match |
| Q11 | Which product has the highest ROAS? | 프리미엄과일 (3.85) |  | exact match |
| Q12 | Which weekday has the highest average daily revenue (each date's SUM(매출액), averaged over that weekday's dates)? | Saturday (then Sunday); weekend days average 1.26x weekdays |  | exact match |
| Q13 | Who are the main buyers of 오메가3? | 50대 여성 |  | exact match |
