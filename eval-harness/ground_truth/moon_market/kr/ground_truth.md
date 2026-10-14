# Moon Market (kr): Ground Truth

Answer key for `moon-market-fresh-food-sales.csv` (in `managed-agentcore/data/moon_market/kr/`; the same file is in `self-hosted/data/moon_market/kr/` and `deep-insight-web/sample_data/moon-market-kr/kr-moon-market-fresh-food-sales.csv`). Every number below is recomputed from the CSV. The sheet is kept out of those directories on purpose: they reach the agents, which must never read it.

## Overview

| Metric | Value |
|---|---|
| Period | 2025-05-01 (Thu) to 2025-05-14 (Wed), 14 days |
| Public holidays | 2025-05-05 (Mon), 2025-05-06 (Tue) |
| Rows = orders | 1,144 |
| Revenue | 22,787,840원 (2,279만 원) |
| AOV | 19,919원 |
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
| Top category by revenue | 과일/견과/쌀 (5,823,180원, 25.55%); next 건강식품 (5,355,980원) |
| District with the most orders | 송파구 (215); next 마포구 (132) |
| District with the most revenue | 송파구 (4,073,680원); next 서초구 (2,860,460원) |
| Product with the most orders | 김치찌개키트 (74); next 백미 (62) |
| Age group with the highest 간편식/밀키트/샐러드 share of its revenue | 20대 (27.34%; next 30대 12.05%) |
| Age group with the highest 건강식품 share of its revenue | 60대 (49.58%; next 30대 21.54%) |
| Revenue share by gender | F 53.13%, M 46.87% |

**Category revenue**

| Category | Revenue | Share |
|---|---|---|
| 과일/견과/쌀 | 5,823,180원 | 25.55% |
| 건강식품 | 5,355,980원 | 23.5% |
| 간편식/밀키트/샐러드 | 2,803,800원 | 12.3% |
| 정육/가공육/달걀 | 2,626,140원 | 11.52% |
| 커피/차 | 2,038,200원 | 8.94% |
| 베이커리 | 1,959,620원 | 8.6% |
| 유제품 | 1,389,120원 | 6.1% |
| 채소 | 791,800원 | 3.47% |

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

### B2. 서초구's top AOV is three gift orders

- Naive: 서초구 customers spend the most per order across the board.
- Correct: 서초구's top AOV comes from 3 한우선물세트 orders (Qty 3, 390,000원 each) placed on the holidays for 어버이날 (05-08); they are the only 한우선물세트 sales. Without them 서초구's AOV ranks 7 of 10, and its median order is like the others.
- 서초구: 96 orders, revenue 2,860,460원, AOV 29,796원 (next 영등포구 21,326원), median 13,950원 (all orders: 12,900원).
- The 3 한우선물세트 orders: 1,170,000원 = 40.9% of 서초구 revenue. Without them: AOV 18,177원, rank 7 of 10.

| Date | Qty | Amount | Gender | Age Group |
|---|---|---|---|---|
| 2025-05-05 | 3 | 390,000원 | M | 50대 |
| 2025-05-05 | 3 | 390,000원 | F | 40대 |
| 2025-05-06 | 3 | 390,000원 | F | 50대 |

### B3. Weekend AOV is lower only because of the discount

- Naive: weekend customers buy smaller baskets (lower AOV).
- Correct: weekend baskets are the same size (units per order and gross AOV match weekdays); the lower AOV is WEEKEND20's 20% discount on every weekend order.

| Orders | Net AOV | Gross AOV | Units per order |
|---|---|---|---|
| Weekend | 15,915원 | 19,894원 | 1.9 |
| Weekday | 19,986원 | 19,986원 | 1.88 |

## Evaluation questions

Each question has exactly one correct answer. `Naive` is the wrong answer a shallow analysis gives.

| ID | Question | Correct answer | Naive (wrong) answer | Scoring |
|---|---|---|---|---|
| Q1 | Which weekday has the most orders per day? | On the dates that are not holidays: Saturday and Sunday (91.5 and 91.0 orders/day vs about 60 on weekdays). Monday and Tuesday look busiest only because 2025-05-05 and 05-06 are public holidays, the two busiest dates (149 and 150 orders) | Monday / Tuesday (averaged over all dates) | full credit requires naming the holidays as the reason Monday and Tuesday look busiest |
| Q2 | Which two dates have the most orders? | 2025-05-05 and 2025-05-06 (public holidays) |  | exact match |
| Q3 | Which district has the highest AOV, and why? | 서초구 (29,796원), because of 3 한우선물세트 orders of 390,000원 each (the only 한우선물세트 sales, placed on the holidays) = 40.9% of its revenue; without them its AOV is 18,177원, rank 7 of 10 | 서초구 customers spend more per order across the board | full credit requires the 3 한우선물세트 orders as the reason |
| Q4 | Do weekend orders hold smaller baskets than weekday orders? | No: units per order 1.9 vs 1.88 and gross AOV 19,894원 vs 19,986원 are the same; the lower net AOV (15,915원 vs 19,986원) is WEEKEND20's 20% discount | Yes, weekend AOV is lower | full credit requires the 20% WEEKEND20 discount as the reason |
| Q5 | What are total revenue, number of orders and AOV? | 22,787,840원 / 1,144 / 19,919원 |  | exact match |
| Q6 | What share of orders used a promotion code? | 31.91% (365 orders, all WEEKEND20 = every weekend order) |  | exact match |
| Q7 | Which category has the highest revenue? | 과일/견과/쌀 (5,823,180원, 25.55%) |  | exact match |
| Q8 | Which district has the most orders? | 송파구 (215 orders; next 마포구 132) |  | exact match |
| Q9 | Which product has the most orders? | 김치찌개키트 (74 orders; next 백미 62) |  | exact match |
| Q10 | Which age group spends the largest share of its revenue on 간편식/밀키트/샐러드? | 20대 (27.34%; next 30대 12.05%) |  | exact match |
| Q11 | Which age group spends the largest share of its revenue on 건강식품? | 60대 (49.58%; next 30대 21.54%) |  | exact match |
| Q12 | What share of revenue comes from female customers? | 53.13% |  | exact match |
