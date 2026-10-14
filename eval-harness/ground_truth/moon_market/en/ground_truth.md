# Moon Market (en): Ground Truth

Answer key for `moon-market-fresh-food-sales.csv` (in `managed-agentcore/data/moon_market/en/`; the same file is in `deep-insight-web/sample_data/moon-market-en/en-moon-market-fresh-food-sales.csv`). Every number below is recomputed from the CSV. The sheet is kept out of those directories on purpose: they reach the agents, which must never read it.

## Overview

| Metric | Value |
|---|---|
| Period | 2025-05-01 (Thu) to 2025-05-14 (Wed), 14 days |
| Public holidays | 2025-05-05 (Mon), 2025-05-06 (Tue) |
| Rows = orders | 1,144 |
| Revenue | KRW 22,787,840 (KRW 22.79M) |
| AOV | KRW 19,919 |
| Units | 2,166 |
| Units per order | 1.89 |
| Products / categories / districts | 24 / 8 / 10 |
| WEEKEND20 orders | 365 (31.91%) |

## Definitions used in every answer

- One row = one order of one product. There is no order id: number of orders = number of rows. Nothing to clean: no duplicates, no missing values.
- **Revenue** = SUM(Amount). Amount is list price x Qty x (1 - discount), after the discount. **AOV** = revenue / orders.
- **Gross** = list price x Qty: Amount / 0.8 for WEEKEND20 orders, Amount otherwise. Used only in B3.
- Each product has one fixed category, size and list price. WEEKEND20 (20% off) is applied to every Saturday and Sunday order and to nothing else; it is the only promotion code.
- Day types: **holiday** = 2025-05-05 and 05-06; **weekend** = Saturday and Sunday; **weekday** = the other Monday-Friday dates.

## Part A. Familiar patterns

| Pattern | Answer |
|---|---|
| Top category by revenue | Fruit/Nuts/Rice (KRW 5,823,180, 25.55%); next Health Supplements (KRW 5,355,980) |
| District with the most orders | Songpa-gu (215); next Mapo-gu (132) |
| District with the most revenue | Songpa-gu (KRW 4,073,680); next Seocho-gu (KRW 2,860,460) |
| Product with the most orders | Kimchi Stew Kit (74); next White Rice (62) |
| Age group with the highest Ready Meal/Meal Kit/Salad share of its revenue | 20s (27.34%; next 30s 12.05%) |
| Age group with the highest Health Supplements share of its revenue | 60s (49.58%; next 30s 21.54%) |
| Revenue share by gender | F 53.13%, M 46.87% |

**Category revenue**

| Category | Revenue | Share |
|---|---|---|
| Fruit/Nuts/Rice | KRW 5,823,180 | 25.55% |
| Health Supplements | KRW 5,355,980 | 23.5% |
| Ready Meal/Meal Kit/Salad | KRW 2,803,800 | 12.3% |
| Meat/Processed Meat/Egg | KRW 2,626,140 | 11.52% |
| Coffee/Tea | KRW 2,038,200 | 8.94% |
| Bakery | KRW 1,959,620 | 8.6% |
| Dairy | KRW 1,389,120 | 6.1% |
| Vegetables | KRW 791,800 | 3.47% |

Only the top category is used as an answer; some lower neighbours are within 10% of each other.

## Part B. Patterns that need real analysis

Each item lists the answer a shallow analysis gives (naive) and the correct one.

### B1. Holidays make Monday and Tuesday look busiest

- Naive: averaged by weekday name over all dates, Tuesday and Monday have the most orders per day.
- Correct: the two busiest dates are the public holidays 2025-05-05 (Mon) and 05-06 (Tue); on the other dates Saturday and Sunday are the busiest.

| Weekday | Orders/day, all dates (naive) | Orders/day, without the holidays |
|---|---|---|
| Saturday | 91.5 | 91.5 |
| Sunday | 91.0 | 91.0 |
| Tuesday | 106.5 | 63.0 |
| Friday | 60.0 | 60.0 |
| Thursday | 59.5 | 59.5 |
| Wednesday | 59.5 | 59.5 |
| Monday | 104.0 | 59.0 |

- Average orders per day: holiday 149.5, weekend 91.25, weekday 60.0.
- Busiest dates: 2025-05-06 (150), 2025-05-05 (149), 2025-05-11 (93).

### B2. Seocho-gu's top AOV is three gift orders

- Naive: Seocho-gu customers spend the most per order across the board.
- Correct: Seocho-gu's top AOV comes from 3 Hanwoo Beef Gift Set orders (Qty 3, KRW 390,000 each) placed on the holidays for Parents' Day (05-08); they are the only Hanwoo Beef Gift Set sales. Without them Seocho-gu's AOV ranks 7 of 10, and its median order is like the others.
- Seocho-gu: 96 orders, revenue KRW 2,860,460, AOV KRW 29,796 (next Yeongdeungpo-gu KRW 21,326), median KRW 13,950 (all orders: KRW 12,900).
- The 3 Hanwoo Beef Gift Set orders: KRW 1,170,000 = 40.9% of Seocho-gu revenue. Without them: AOV KRW 18,177, rank 7 of 10.

| Date | Qty | Amount | Gender | Age Group |
|---|---|---|---|---|
| 2025-05-05 | 3 | KRW 390,000 | M | 50s |
| 2025-05-05 | 3 | KRW 390,000 | F | 40s |
| 2025-05-06 | 3 | KRW 390,000 | F | 50s |

### B3. Weekend AOV is lower only because of the discount

- Naive: weekend customers buy smaller baskets (lower AOV).
- Correct: weekend baskets are the same size (units per order and gross AOV match weekdays); the lower AOV is WEEKEND20's 20% discount on every weekend order.

| Orders | Net AOV | Gross AOV | Units per order |
|---|---|---|---|
| Weekend | KRW 15,915 | KRW 19,894 | 1.9 |
| Weekday | KRW 19,986 | KRW 19,986 | 1.88 |

## Evaluation questions

Each question has exactly one correct answer. `Naive` is the wrong answer a shallow analysis gives.

| ID | Question | Correct answer | Naive (wrong) answer | Scoring |
|---|---|---|---|---|
| Q1 | Which weekday has the most orders per day? | On the dates that are not holidays: Saturday and Sunday (91.5 and 91.0 orders/day vs about 60 on weekdays). Monday and Tuesday look busiest only because 2025-05-05 and 05-06 are public holidays, the two busiest dates (149 and 150 orders) | Monday / Tuesday (averaged over all dates) | full credit requires naming the holidays as the reason Monday and Tuesday look busiest |
| Q2 | Which two dates have the most orders? | 2025-05-05 and 2025-05-06 (public holidays) |  | exact match |
| Q3 | Which district has the highest AOV, and why? | Seocho-gu (KRW 29,796), because of 3 Hanwoo Beef Gift Set orders of KRW 390,000 each (the only Hanwoo Beef Gift Set sales, placed on the holidays) = 40.9% of its revenue; without them its AOV is KRW 18,177, rank 7 of 10 | Seocho-gu customers spend more per order across the board | full credit requires the 3 Hanwoo Beef Gift Set orders as the reason |
| Q4 | Do weekend orders hold smaller baskets than weekday orders? | No: units per order 1.9 vs 1.88 and gross AOV KRW 19,894 vs KRW 19,986 are the same; the lower net AOV (KRW 15,915 vs KRW 19,986) is WEEKEND20's 20% discount | Yes, weekend AOV is lower | full credit requires the 20% WEEKEND20 discount as the reason |
| Q5 | What are total revenue, number of orders and AOV? | KRW 22,787,840 / 1,144 / KRW 19,919 |  | exact match |
| Q6 | What share of orders used a promotion code? | 31.91% (365 orders, all WEEKEND20 = every weekend order) |  | exact match |
| Q7 | Which category has the highest revenue? | Fruit/Nuts/Rice (KRW 5,823,180, 25.55%) |  | exact match |
| Q8 | Which district has the most orders? | Songpa-gu (215 orders; next Mapo-gu 132) |  | exact match |
| Q9 | Which product has the most orders? | Kimchi Stew Kit (74 orders; next White Rice 62) |  | exact match |
| Q10 | Which age group spends the largest share of its revenue on Ready Meal/Meal Kit/Salad? | 20s (27.34%; next 30s 12.05%) |  | exact match |
| Q11 | Which age group spends the largest share of its revenue on Health Supplements? | 60s (49.58%; next 30s 21.54%) |  | exact match |
| Q12 | What share of revenue comes from female customers? | 53.13% |  | exact match |
