# Jungle Market: Ground Truth

Answer key for `jungle-market-sales.csv`. Every number below is recomputed from the CSV. Revenue figures use `line_total` after removing exact duplicate rows unless stated otherwise.

## Overview

| Metric | Value |
|---|---|
| Period | 2026-03-02 to 2026-03-15 |
| Rows (raw / after dedup) | 15,680 / 15,569 |
| Orders | 2,987 |
| Customers | 1,847 |
| Revenue | $110,270.26 |
| AOV | $36.92 |
| Lines per order | 5.21 |

## Definitions used in every answer

- Remove exact duplicate rows first (see B1). All numbers below are after dedup unless marked naive.
- **Revenue** = sum of line_total (net, after discounts). **AOV** = revenue / distinct order_id (net).
- **Gross order value** = sum of unit_price * quantity (before discounts). Used only where stated (B4).
- **Units/day** = sum of quantity / number of days in the window.
- **Lift** of A and B = P(A and B) / (P(A) * P(B)), computed at order level.

## Promotion rules (exactly how the data was generated)

- At most one promo_code per order; codes never stack.
- **SAVE10**: coupon used only by Returning customers (0 SAVE10 orders from New customers); 10% off every row of the order.
- **WELCOME10**: applied automatically to every order of a New customer with gross value >= $50; $10 off the order, split across its rows.
- **PASTA30**: 30% off Spaghetti rows on 2026-03-09 to 2026-03-11, applied automatically only when the order has no SAVE10 or WELCOME10 code.

## Part A. Familiar patterns

| # | Question | Answer |
|---|---|---|
| A1 | Which city has the highest Bakery revenue share? | Paris (13%) |
| A2 | Which city has the highest cheese revenue share? | Paris (14%) |
| A3 | Which city has the highest Ready Meals share? | Tokyo (20%) |
| A4 | Which city has the fewest items per order? | Tokyo (3.54) |
| A5 | Which city has the highest Plant-based share? | Berlin (15%) |
| A6 | Which city has the highest net AOV? | New York ($50.78) |
| A7 | Which city has the highest App share? | Seoul (82%) |
| A8 | Busiest / quietest weekday? | Saturday / Tuesday (weekend is 1.31x weekdays) |

**A9. Co-purchase**

- Pair bought together in the most orders: **Ground Coffee + Oat Milk** (477 orders; runner-up Pasta Sauce + Spaghetti with 266).
- Strongest bundle by lift: **Spaghetti + Pasta Sauce + Parmesan Cheese** (the top 3 pairs by lift are all pairs within this 3-product set).
- Exactly 7 pairs (with at least 30 orders) have lift above 2, all of them planted; the highest other pair is Granola Bars + Orange Juice (lift 1.84).

| Rule | Orders | Support | Confidence | Lift |
|---|---|---|---|---|
| Spaghetti → Pasta Sauce | 266 | 8.91% | 58% | 4.71 |
| Pasta Sauce + Spaghetti → Parmesan Cheese | 195 | 6.53% | 73% | 6.37 |
| Baguette → Butter | 140 | 4.69% | 51% | 2.98 |
| Sourdough Bread → Butter | 143 | 4.79% | 50% | 2.88 |
| Cereal → Whole Milk | 188 | 6.29% | 63% | 3.5 |
| Ground Coffee → Oat Milk | 477 | 15.97% | 68% | 3.34 |
| Oat Milk → Ground Coffee | 477 | 15.97% | 78% | 3.34 |

## Part B. Patterns that need real analysis

Each item lists the answer a shallow analysis would give (naive) and the correct one.

### B1. Duplicate rows change the top city

- 111 rows are exact duplicates: every row of Sydney on 2026-03-10 (15 orders) was loaded twice.
- Naive: top revenue city = **Sydney** ($17,053.67).
- Correct: after dedup the top city is **Singapore** ($16,645.52); Sydney is $16,258.80.

### B2. SAVE10 and Simpson's paradox

- Metric: **net AOV** = mean over orders of sum(line_total), i.e. after the 10% discount. Compared groups: orders with promo_code SAVE10 vs orders with no promo_code.
- Naive: all cities pooled, SAVE10 orders have net AOV $33.96 (580 orders) vs no-promo $35.79 (2071 orders), so SAVE10 looks like it lowers basket value.
- Correct: within every city SAVE10 orders have a HIGHER AOV; SAVE10 is concentrated in low-AOV cities (Tokyo, Seoul).
- Note: on gross AOV (before discount) SAVE10 orders are higher overall too, so the paradox exists only on net AOV (gross AOV $37.74 vs $35.79).

| City | SAVE10 share | SAVE10 net AOV | No-promo net AOV |
|---|---|---|---|
| London | 8% | $45.31 | $35.38 |
| New York | 6% | $71.62 | $48.01 |
| Berlin | 6% | $51.93 | $34.19 |
| Paris | 9% | $44.17 | $35.26 |
| Tokyo | 53% | $26.73 | $23.40 |
| Seoul | 50% | $30.26 | $24.79 |
| Singapore | 6% | $48.74 | $37.97 |
| Sydney | 7% | $46.58 | $39.29 |

### B3. Berlin Oat Milk stockout drags down coffee

- Naive: a weekend dip in Berlin demand.
- Correct: Oat Milk was out of stock in Berlin (0 units sold on both dates). Ground Coffee is usually bought together with Oat Milk, so those customers skipped coffee too. The coffee rate per 100 orders fell versus the following weekend in Berlin, while other cities' coffee rate on the same dates stayed at their following-weekend level.
- Comparison: the stockout dates are a Saturday and Sunday; the baseline is the same weekdays one week later. Coffee is measured per 100 orders, so differences in order volume do not affect the comparison.

| Group | Dates | Coffee orders / orders | Coffee per 100 orders |
|---|---|---|---|
| Berlin | 2026-03-07 / 2026-03-08 (stockout) | 7 / 63 | 11.11 |
| Berlin | 2026-03-14 / 2026-03-15 (following weekend) | 16 / 59 | 27.12 |
| Berlin | all non-stockout dates | 77 / 271 | 28.41 |
| Other 7 cities | 2026-03-07 / 2026-03-08 | 109 / 456 | 23.9 |
| Other 7 cities | 2026-03-14 / 2026-03-15 | 104 / 450 | 23.11 |

- Oat Milk sold in Berlin on the stockout dates: 0 units.
- Berlin coffee rate is 59% lower than on the following weekend. The Berlin sample on the stockout dates is small (63 orders), so the cause is established by the 0 Oat Milk units and the co-purchase rule, not by the size of the drop alone.

### B4. WELCOME10 threshold bunching

- Rule: WELCOME10: new customers get $10 off when gross order value >= $50. Applied automatically; every eligible order has the code (0 eligible orders without it).
- Metric: gross order value = sum of unit_price * quantity (before the $10 discount).
- Naive: nothing unusual: new and returning customers have about the same average order value (gross AOV $39.40 vs returning $38.17).
- Correct: new-customer orders pile up just above $50 (the WELCOME10 threshold) and almost none fall just below it: customers top up the basket to get the discount. 110 of 390 new-customer orders (28%) have gross $50-55, only 4 have $45-50.
- Scoring: full credit: $50-55 gross with the WELCOME10 $50 threshold as the reason. Partial credit: $40-45 net (the same orders after the $10 discount) with the threshold as the reason.

| Range | New-customer orders by gross | by net (line_total) |
|---|---|---|
| $0-30 | 172 | 172 |
| $30-35 | 12 | 12 |
| $35-40 | 11 | 11 |
| $40-45 | 8 | 118 |
| $45-50 | 4 | 31 |
| $50-55 | 110 | 13 |
| $55-60 | 27 | 12 |
| $60-65 | 13 | 4 |
| $65-70 | 12 | 7 |
| $70+ | 21 | 10 |

### B5. PASTA30 halo and post-promo dip

- PASTA30: 30% off Spaghetti, 2026-03-09 to 2026-03-11. Windows: before 2026-03-02 to 2026-03-08, after 2026-03-12 to 2026-03-14.
- Naive: only Spaghetti sales went up.
- Correct: non-discounted Pasta Sauce and Parmesan Cheese rose too (halo), and Spaghetti fell below the pre-promo level for 3 days afterwards (pantry loading).
- Units: units/day = sum of quantity / number of days, over ALL rows of the product. During the promo this includes Spaghetti rows that did not get PASTA30 because the order used SAVE10 or WELCOME10. (52 of 205 Spaghetti rows in the promo window have no PASTA30).

| Product | Units/day before | Promo | After | Promo vs before | After vs before |
|---|---|---|---|---|---|
| Spaghetti | 37.29 | 156.67 | 20.67 | 4.2x | 0.55x |
| Pasta Sauce | 30.71 | 67.0 | 26.0 | 2.18x | 0.85x |
| Parmesan Cheese | 28.57 | 64.0 | 19.0 | 2.24x | 0.67x |

### B6. Late-night orders are the biggest baskets

- Naive: late-night orders are small snack runs.
- Correct: late night has the highest AOV, driven by customers aged 55+ ordering on Web. Share of 55+ in late-night orders: 41% (vs 17% overall); Web share: 60%.

| Hour band | Orders | AOV | Lines/order |
|---|---|---|---|
| Morning (06-11) | 872 | $35.61 | 5.09 |
| Afternoon (12-17) | 833 | $36.07 | 5.1 |
| Evening (18-21) | 877 | $35.64 | 4.99 |
| Late night (22-05) | 405 | $44.24 | 6.2 |

## Evaluation questions

Each question has exactly one correct answer. `Naive` is the wrong answer a shallow analysis gives.

| ID | Question | Correct answer | Naive (wrong) answer | Scoring |
|---|---|---|---|---|
| Q1 | Which city has the highest total revenue? | Singapore ($16,645.52) | Sydney ($17,053.67, duplicates not removed) | exact match |
| Q2 | How many exact duplicate rows are there, and where do they come from? | 111 rows: all rows of Sydney on 2026-03-10 | no duplicates | exact match |
| Q3 | Which product pair appears together in the most orders? | Ground Coffee + Oat Milk (477 orders) |  | exact match |
| Q4 | Which three products form the strongest bundle (highest lift)? | Spaghetti + Pasta Sauce + Parmesan Cheese |  | exact match |
| Q5 | Within each city, do SAVE10 orders have a higher or lower net AOV (mean of the order's sum of line_total) than orders with no promo code? | Higher in all 8 cities | Lower (all cities pooled: $33.96 vs $35.79) | full credit only for 'higher in every city' with the explanation that SAVE10 is concentrated in low-AOV Tokyo and Seoul |
| Q6 | Why did Ground Coffee sales drop in Berlin on 2026-03-07 and 2026-03-08? | Oat Milk was out of stock in Berlin on those dates (0 units); coffee is co-purchased with Oat Milk. Coffee orders per 100 Berlin orders: 11.11 (7/63) vs 27.12 (16/59) on the following weekend | a weekend dip in Berlin demand | full credit requires naming the Oat Milk stockout as the cause |
| Q7 | In which $5 range of gross order value do new-customer orders concentrate, and why? | $50-55 gross (110 of 390 orders); customers top up to reach the WELCOME10 $50 threshold | no concentration; new customers look like returning customers | full credit: $50-55 gross with the WELCOME10 $50 threshold as the reason. Partial credit: $40-45 net (the same orders after the $10 discount) with the threshold as the reason. |
| Q8 | During PASTA30 (2026-03-09 to 03-11), did Pasta Sauce and Parmesan Cheese (not discounted) sell more units per day than in the week before? | Yes: Pasta Sauce 2.18x and Parmesan Cheese 2.24x units/day vs the week before | No, only Spaghetti went up | exact match |
| Q9 | How did Spaghetti sell in the 3 days after PASTA30 compared with the week before? | Lower: 0.55x units/day (pantry loading) | back to normal | exact match |
| Q10 | Which hour band (by order_hour: 06-11, 12-17, 18-21, 22-05) has the highest net AOV? | Late night 22:00-05:59 ($44.24), driven by customers aged 55+ on Web | not late night (assumed to be small snack orders) | exact match |
| Q11 | Which city has the highest Bakery revenue share? | Paris (13%) |  | exact match |
| Q12 | Which city has the highest cheese revenue share? | Paris (14%) |  | exact match |
| Q13 | Which city has the highest Ready Meals revenue share? | Tokyo (20%) |  | exact match |
| Q14 | Which city has the fewest items (lines) per order? | Tokyo (3.54) |  | exact match |
| Q15 | Which city has the highest Plant-based revenue share? | Berlin (15%) |  | exact match |
| Q16 | Which city has the highest net AOV? | New York ($50.78) |  | exact match |
| Q17 | Which city has the highest share of App orders? | Seoul (82%) |  | exact match |
| Q18 | Which weekday has the most orders on average, and which the fewest? | Most: Saturday, fewest: Tuesday |  | exact match |
