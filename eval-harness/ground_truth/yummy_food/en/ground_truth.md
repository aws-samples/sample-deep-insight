# Yummy Food (en): Ground Truth

Answer key for `yummy-food-market.csv` (in `managed-agentcore/data/yummy_food/en/` and `self-hosted/data/yummy_food/en/`). Every number below is recomputed from the CSV. The file is kept out of those data directories on purpose: they ship to the runtime, and the agents must never read this sheet.

## Overview

| Metric | Value |
|---|---|
| Period | 2025-09-01 to 2025-09-30 (30 days) |
| Rows | 720 (4 media x 6 products x 30 days, one row each) |
| Impressions | 77,961,417 |
| Clicks | 1,401,947 |
| Conversions | 65,509 |
| Ad spend | KRW 388,296,000 (KRW 388.3M) |
| Revenue | KRW 1,316,606,500 (KRW 1,316.6M) |
| CTR | 1.8% |
| Conversion rate | 4.67% |
| ROAS | 3.39 (339%) |
| CPC | KRW 277 |
| Revenue per conversion | KRW 20,098 |

## Definitions used in every answer

- One row = one Date x Media x Product. Every combination appears exactly once: no duplicates, no missing rows, nothing to clean.
- Revenue is the revenue of the row's conversions (purchases after an ad click) only, in KRW. Ad Cost is in KRW.
- **CTR** = SUM(Clicks) / SUM(Impressions) x 100. **Conversion rate** = SUM(Conversions) / SUM(Clicks) x 100. **ROAS** = SUM(Revenue) / SUM(Ad Cost), a ratio (4.14 = 414%).
- **CPC** = SUM(Ad Cost) / SUM(Clicks). **Revenue per conversion** = SUM(Revenue) / SUM(Conversions).
- The CTR, CVR and ROAS columns are each row's own ratio, rounded to 2 decimals. A figure for several rows is recomputed from the summed counts, never averaged from these columns (see B1).
- Main Age Group / Main Gender are fixed per product: the same in every row of a product, whatever the media or date.

## Part A. Familiar patterns

**A1. Media**

| Media | Ad spend | Revenue | CTR | Conversion rate | ROAS | CPC | Fresh Food share of own revenue |
|---|---|---|---|---|---|---|---|
| Kuppang | KRW 161,615,000 | KRW 669,613,700 | 1.36% | 6.79% | 4.14 | KRW 342 | 33.72% |
| Neiba | KRW 107,925,000 | KRW 253,662,100 | 3.21% | 2.13% | 2.35 | KRW 189 | 33.63% |
| Amazon | KRW 68,450,000 | KRW 216,952,800 | 1.2% | 6.39% | 3.17 | KRW 347 | 32.72% |
| Kulsam | KRW 50,306,000 | KRW 176,377,900 | 1.8% | 5.35% | 3.51 | KRW 312 | 77.55% |

- Revenue ranking: Kuppang > Neiba > Amazon > Kulsam. Ad spend ranking: Kuppang > Neiba > Amazon > Kulsam.
- Kulsam gets 77.55% of its revenue from Fresh Food; the other media 32.72-33.72%.

**A2. Category**

| Category | Ad spend | Revenue | Revenue share | ROAS |
|---|---|---|---|---|
| Fresh Food | KRW 148,655,000 | KRW 518,837,300 | 39.41% | 3.49 |
| Convenience Food | KRW 139,179,000 | KRW 460,878,600 | 35.01% | 3.31 |
| Health Food | KRW 100,462,000 | KRW 336,890,600 | 25.59% | 3.35 |

Category ROAS values are close to each other; only the revenue share ranking is used as an answer.

**A3. Product**

| Product | Category | Revenue | Conversions | Revenue per conversion | ROAS | Main buyers |
|---|---|---|---|---|---|---|
| Premium Fruit | Fresh Food | KRW 250,464,300 | 5,607 | KRW 44,670 | 3.85 | 40s Female |
| Omega-3 | Health Food | KRW 177,071,600 | 4,572 | KRW 38,730 | 3.53 | 50s Female |
| Protein Bar | Health Food | KRW 159,819,000 | 6,591 | KRW 24,248 | 3.18 | 30s Female |
| Instant Rice Set | Convenience Food | KRW 239,992,100 | 12,709 | KRW 18,884 | 3.45 | 20s Male |
| Frozen Dumplings | Convenience Food | KRW 220,886,500 | 15,198 | KRW 14,534 | 3.17 | 30s Male |
| Salad Kit | Fresh Food | KRW 268,373,000 | 20,832 | KRW 12,883 | 3.21 | 30s Female |

- Highest revenue per conversion: **Premium Fruit**. Highest ROAS: **Premium Fruit** (3.85; next Omega-3 3.53). Other product ROAS values are close and not used as answers.

**A4. Weekday**

| Weekday | Average daily revenue |
|---|---|
| Saturday | KRW 53,814,175 |
| Sunday | KRW 49,638,950 |
| Tuesday | KRW 42,067,800 |
| Wednesday | KRW 41,243,575 |
| Thursday | KRW 40,886,425 |
| Monday | KRW 40,494,540 |
| Friday | KRW 40,365,575 |

- Saturday is highest, then Sunday; weekend days average 1.26x weekdays. Average daily spend is about the same on every day of the week (Monday to Friday KRW 12,558,000 to KRW 13,259,800; Saturday KRW 12,943,000, Sunday KRW 12,944,000): the weekend lift comes from a higher conversion rate. The five weekdays are close to each other and are not ranked.
- September 2025 has 5 Mondays and 5 Tuesdays and 4 of every other weekday. Ranked by total revenue instead of the daily average, the order is Saturday > Tuesday > Monday > Sunday; the question asks for the average.

## Part B. Patterns that need real analysis

Each item lists the answer a shallow analysis gives (naive) and the correct one.

### B1. Averaging the ROAS column picks the wrong top media

- Naive: mean of the ROAS column per media ranks **Amazon** first (5.74).
- Correct: SUM(Revenue) / SUM(Ad Cost) ranks **Kuppang** first (4.14); Amazon is 3rd (3.17).
- Why: Amazon runs Protein Bar, Omega-3 and Premium Fruit on a tiny budget (about KRW 60,000 a day) at a high ROAS; those rows count as much as its large rows in a plain mean, but carry little spend. Small-budget Amazon rows: spend KRW 5,389,000, ROAS 8.8; large-budget rows: spend KRW 63,061,000, ROAS 2.69.

| Media | ROAS (SUM/SUM, correct) | Mean of ROAS column (naive) |
|---|---|---|
| Kuppang | 4.14 | 4.45 |
| Kulsam | 3.51 | 3.1 |
| Amazon | 3.17 | 5.74 |
| Neiba | 2.35 | 2.35 |

- The questions fix the period to the whole month. Over 2025-09-16 to 09-30 alone, Kuppang (3.53) and Kulsam (3.50) are nearly tied, so a ranking for the second half has no single answer and is not asked.

### B2. The highest CTR has the lowest ROAS

- Naive: Neiba has the highest CTR, so it returns the most revenue per KRW spent; move budget to it.
- Correct: Neiba has the highest CTR but the lowest conversion rate and the lowest ROAS of the 4 media: CTR 3.21%, conversion rate 2.13%, ROAS 2.35.
- CTR ranking: Neiba > Kulsam > Kuppang > Amazon. Conversion rate ranking: Kuppang > Amazon > Kulsam > Neiba.
- Neiba also has the lowest CPC (KRW 189; the others KRW 312 to KRW 347): its clicks are cheap but convert least. Which media is "most efficient" depends on the metric, so the question asks for the ROAS rank.

### B3. Kuppang budget increase: diminishing returns

- Kuppang daily ad spend doubled from 2025-09-16; the other media kept the same daily spend all month.
- Naive: Kuppang has the highest ROAS (4.14), so the extra budget earns about that much.
- Correct: the extra Kuppang spend returned only KRW 1.67 per KRW 1, below the full-month ROAS of every other media; Kuppang's ROAS fell from 5.38 to 3.53 after the increase.
- Incremental ROAS = (Kuppang revenue after - before) / (Kuppang ad spend after - before); both windows are 15 days with 2 Saturdays and 2 Sundays each.

| Kuppang | Days | Ad spend | Revenue | ROAS | CTR | Conversion rate |
|---|---|---|---|---|---|---|
| Before | 2025-09-01 to 2025-09-15 | KRW 53,953,000 | KRW 290,025,900 | 5.38 | 1.5% | 7.48% |
| After | 2025-09-16 to 2025-09-30 | KRW 107,662,000 | KRW 379,587,800 | 3.53 | 1.28% | 6.35% |
| Increment | | KRW 53,709,000 | KRW 89,561,900 | **1.67** | | |

- Average daily spend: Kuppang KRW 3,596,867 → KRW 7,177,467; the other 3 media together KRW 7,542,133 → KRW 7,569,933 (unchanged).
- The lowest other-media ROAS is Neiba 2.35, still above 1.67. By product the increment ranges from 1.42 to 1.95, on weekdays only it is 1.57 and on weekends only 1.94; every split stays below Neiba's 2.35.
- Not determined by the data, so not scored: whether more Kuppang budget pays off (1.67 is above 1, but the file has no margins), and what the other media would return on extra spend (their spend never changed).

## Evaluation questions

Each question has exactly one correct answer. `Naive` is the wrong answer a shallow analysis gives.

| ID | Question | Correct answer | Naive (wrong) answer | Scoring |
|---|---|---|---|---|
| Q1 | Which media has the highest ROAS over the whole month (2025-09-01 to 09-30)? | Kuppang (4.14) | Amazon (5.74, mean of the ROAS column) | exact match |
| Q2 | Rank the 4 media by ROAS over the whole month (2025-09-01 to 09-30), highest first. | Kuppang > Kulsam > Amazon > Neiba | Amazon > Kuppang > Kulsam > Neiba (mean of the ROAS column) | exact match |
| Q3 | Which media has the highest CTR, and where does it rank among the 4 media by ROAS? | Neiba (CTR 3.21%); last of the 4 by ROAS (2.35), and also last by conversion rate (2.13%) | first: the highest CTR taken as the best return | exact match: Neiba, and 4th (last) by ROAS |
| Q4 | Did any media change its ad spend during the month? | Kuppang doubled its daily spend from 2025-09-16 (KRW 3,596,867 to KRW 7,177,467 a day on average) | no change | exact match |
| Q5 | What did the extra Kuppang spend after 2025-09-16 return (incremental ROAS vs 09-01 to 09-15), and is it above or below each other media's full-month ROAS? | 1.67 = (revenue after - before) / (spend after - before); below every other media's full-month ROAS (lowest: Neiba 2.35). Kuppang ROAS fell from 5.38 to 3.53 | about 4.14 (Kuppang's full-month ROAS), above every other media | full credit requires the incremental ROAS (about 1.67) and that it is below every other media's full-month ROAS. A split by product or by weekday/weekend (1.42 to 1.95) gets partial credit. A budget recommendation is not scored: the file has no margins, and the other media never changed their spend |
| Q6 | What are total revenue, total ad spend and overall ROAS? | KRW 1,316,606,500 / KRW 388,296,000 / 3.39 |  | exact match (ROAS may be written as a percent) |
| Q7 | Rank the media by revenue. | Kuppang > Neiba > Amazon > Kulsam |  | exact match |
| Q8 | Which media gets the largest share of its own revenue from Fresh Food? | Kulsam (77.55%) |  | exact match |
| Q9 | Rank the categories by revenue share. | Fresh Food (39.41%) > Convenience Food (35.01%) > Health Food (25.59%) |  | exact match |
| Q10 | Which product has the highest revenue per conversion? | Premium Fruit (KRW 44,670) |  | exact match |
| Q11 | Which product has the highest ROAS? | Premium Fruit (3.85) |  | exact match |
| Q12 | Which weekday has the highest average daily revenue (each date's SUM(Revenue), averaged over that weekday's dates)? | Saturday (then Sunday); weekend days average 1.26x weekdays |  | exact match |
| Q13 | Who are the main buyers of Omega-3? | 50s Female |  | exact match |
