# Jungle Market: the evaluation dataset

**→ Back to [Eval Harness README](../README.md)**

Jungle Market is the dataset the eval harness runs on. It is a fictional
online grocery delivery service in 8 cities, two weeks of orders, with
patterns planted on purpose. Some are familiar and a report should simply find
them. Others give a wrong answer to a shallow analysis and the right one only
to a careful one. Every pattern has one correct answer, computed from the CSV,
so a report can be graded without recomputing anything.

It replaced moon_market as the development set because moon_market had three
gaps: it was Korea-specific, every transaction held a single product (no
basket analysis), and there was no answer key. moon_market is now kept out as
a test set (see the README).

## Files

| File | What it is | Sent to the agents? |
|---|---|---|
| `deep-insight-web/sample_data/jungle-market/jungle-market-sales.csv` | The data: 15,680 rows | Yes |
| `deep-insight-web/sample_data/jungle-market/column_definitions.json` | Column descriptions, including the exact promotion rules | Yes |
| `deep-insight-web/sample_data/jungle-market/ground_truth.md` | Answer sheet for people: patterns, naive vs correct answers, Q1-Q18 | **No** |
| `deep-insight-web/sample_data/jungle-market/ground_truth.json` | The same answers, machine-readable | **No** |
| `eval-harness/answer_keys/jungle_market.json` | 44 facts the fact checker (`graders/factcheck.py`) compares reports against | **No** |
| `eval-harness/answer_keys/build_answer_key.py` | Builds the answer key from the CSV with pandas | No |

`config/scenarios.yaml` lists only the CSV and `column_definitions.json` under
`upload`, so the answers never reach the runtime. Keep it that way: do not put
the `ground_truth` files or the answer key in an upload list, a prompt or a
scenario `query`.

## The data

- **Period:** 2026-03-02 (Mon) to 2026-03-15 (Sun), 14 days
- **Size:** 15,680 rows (111 of them exact duplicates), 2,987 orders, 1,847 customers
- **Cities:** London, New York, Berlin, Paris, Tokyo, Seoul, Singapore, Sydney (amounts in USD)
- **Grain:** one row = one product in one order. An order spans several rows
  (5.2 on average), so co-purchase analysis is possible.
- **Columns:** `order_id, order_date, order_hour, customer_id, customer_type,
  gender, age_group, city, country, channel, product_id, product_name,
  category, unit_price, quantity, discount, line_total, promo_code`. See
  `column_definitions.json`.

**Definitions used by every answer**

- Remove exact duplicate rows first. All answers are after dedup unless marked naive or raw.
- Revenue = sum of `line_total` (net, after discounts). AOV = revenue / distinct `order_id` (net).
- Gross order value = sum of `unit_price * quantity` (before discounts). Used only where stated (Q7).
- Units/day = sum of `quantity` / number of days in the window.
- Lift of A and B = P(A and B) / (P(A) * P(B)), at order level.

**Promotion rules** (also in `column_definitions.json`)

- At most one `promo_code` per order; codes never stack.
- `SAVE10`: Returning customers only; 10% off every row of the order.
- `WELCOME10`: applied automatically to every New customer order with gross value >= $50; $10 off, split across rows.
- `PASTA30`: 30% off Spaghetti rows on 2026-03-09 to 03-11, only when the order has no other code.

## What is planted

**Part A: familiar patterns.** A report should find these. They make the
report read as plausible, and missing them is a sign the analysis was thin.

| Pattern | Answer |
|---|---|
| Highest Bakery and cheese revenue share | Paris |
| Highest Ready Meals share, fewest items per order | Tokyo |
| Highest Plant-based share | Berlin |
| Highest net AOV | New York |
| Highest App share | Seoul |
| Busiest / quietest weekday | Saturday / Tuesday |
| Co-purchase | Ground Coffee + Oat Milk (most orders together), Spaghetti + Pasta Sauce + Parmesan Cheese (strongest bundle), Bread → Butter, Cereal → Whole Milk |

**Part B: patterns that need real analysis.** Each has a naive answer that a
shallow analysis gives, and a correct one.

| # | Pattern | Naive (wrong) | Correct |
|---|---|---|---|
| B1 | Duplicate rows | Top revenue city is Sydney | All 111 rows of Sydney on 2026-03-10 were loaded twice. After dedup, Singapore is first |
| B2 | Simpson's paradox on SAVE10 | SAVE10 orders have a lower net AOV ($33.96 vs $35.79) | Within every city SAVE10 orders are higher. SAVE10 is concentrated in low-AOV Tokyo and Seoul |
| B3 | Berlin Oat Milk stockout | A weekend dip in Berlin demand | Oat Milk sold 0 units on 03-07/08. Coffee is bought with Oat Milk, so coffee fell too (11.1 vs 27.1 per 100 orders on the next weekend) |
| B4 | WELCOME10 threshold | New customers look like returning ones | 110 of 390 new-customer orders sit at $50-55 gross, just above the $10-off threshold |
| B5 | PASTA30 halo and dip | Only Spaghetti went up | Pasta Sauce (2.18x) and Parmesan (2.24x) rose too, and Spaghetti fell to 0.55x in the 3 days after |
| B6 | Late-night orders | Small snack orders | Late night (22-05) has the highest net AOV ($44.24), driven by customers aged 55+ on Web |

Full numbers, tables and the reasoning behind each answer are in
`ground_truth.md`.

## Two answer sources, one set of numbers

| | `ground_truth.json` / `.md` | `answer_keys/jungle_market.json` |
|---|---|---|
| Used by | a person grading a report | `graders/factcheck.py` (automated) |
| Shape | 18 questions with a correct answer, a naive answer and a scoring rule | 44 facts: value, ranking or relation, each with a scope |
| Answers | "did the report find the pattern and explain it" | "is each number the report states right" |

The two agree (checked 2026-10-12; `ground_truth.json` rounds shares to whole
percents). Which answer-key facts cover each question:

| Question | Answer-key facts |
|---|---|
| Overview | `total_revenue`, `order_count`, `customer_count`, `avg_order_value`, `lines_per_order` |
| Q1 top revenue city | `city_revenue_ranking`, `top_city_revenue`, `sydney_revenue` |
| Q2 duplicate rows | `duplicate_row_count` |
| Q3 most frequent pair | `coffee_oat_milk_orders` |
| Q4 strongest bundle | `spaghetti_pasta_sauce_orders`, `spaghetti_pasta_sauce_lift`, `pasta_bundle_parmesan_confidence_pct` |
| Q5 SAVE10 | `save10_vs_no_promo_aov_within_city`, `save10_net_aov_pooled`, `no_promo_net_aov_pooled`, `save10_share_tokyo_pct` |
| Q6 Berlin stockout | `berlin_oat_milk_units_stockout`, `berlin_coffee_per_100_orders_stockout`, `berlin_coffee_per_100_orders_next_weekend` |
| Q7 WELCOME10 | `new_orders_gross_50_55`, `new_customer_order_count` |
| Q8, Q9 PASTA30 | `spaghetti_promo_lift_x`, `pasta_sauce_promo_lift_x`, `parmesan_promo_lift_x`, `spaghetti_post_promo_x` |
| Q10 late night | `hour_band_aov_ranking`, `late_night_aov`, `late_night_age55_share_pct` |
| Q11-Q17 city profiles | `city_*_ranking` and `top_city_*` per metric (bakery, cheese, ready meals, lines per order, plant-based, AOV, app share) |
| Q18 weekdays | `weekday_order_ranking` |

## How to evaluate

### 1. Automated: run and grade

```bash
cd eval-harness
.venv/bin/python run_eval.py --scenario jungle_market --repeat 3 --tag baseline
.venv/bin/python grade.py <run_dir> --scenario jungle_market      # re-grade a saved run
```

| Scenario | Request | What to expect from the report |
|---|---|---|
| `jungle_market` | Open growth request (Korean) | Part A patterns, ideally some of Part B, and 3 strategies |
| `jungle_market_en` | The same in English | Same |
| `jungle_market_simple` | Totals, AOV, category share | Overview facts only; Part B is not asked |
| `jungle_market_revision` | Simple + one plan revision (add city revenue) | Overview facts plus a city ranking (Q1) |

The fact check reads every number the report states and labels it against
the answer key. For this dataset it matters most in two places:

- A statement about another period or subset is `out_of_scope`, not wrong.
  "Paris is the top city" is wrong for the whole period (Paris is 4th) but
  right for 2026-03-10 alone, so it is out of scope if the report says it is
  about that day.
- The duplicate rows are a loading error, not another scope. A figure that
  counts them twice is wrong even when the report says it kept them (Sydney
  first, $111,065.13 total revenue). Only a sentence that names the raw file
  as a contrast to the deduplicated result ("before removing duplicates,
  Sydney looks first") is true.
- `wrong_confirmed` fails `core_pass`. So a report that states the naive
  answer as its result fails.

`core_pass` thresholds for each scenario are in `config/scenarios.yaml` under `pass:`.
For the open scenarios only `total_revenue` is required for now. These are
loose defaults and should be set from the first baseline runs.

The automated graders check numbers. They do not check whether a report
*explains* a pattern (for example, that coffee fell *because of* the
stockout). Use the LLM judge (`--judge`) or the manual grading below for
that.

### 2. Manual: grade a report with Q1-Q18

Use this when comparing versions by hand, or to build gold cases for
`sanity/factcheck_sanity.py` (the first one is `sanity/factcheck_cases/jungle_market.yaml`).

1. Open the report and `ground_truth.md` side by side. Don't recompute anything:
   every answer is in the table at the end of `ground_truth.md`.
2. For each question the report addresses, give one label:

   | Label | When |
   |---|---|
   | `correct` | Matches the correct answer and meets the scoring rule |
   | `partial` | Meets the partial-credit rule (only Q7 has one: $40-45 **net** with the threshold as the reason) |
   | `naive` | States the naive answer (for example Sydney first, SAVE10 lowers AOV) |
   | `wrong` | Any other wrong answer |
   | `not_addressed` | The report does not cover it |

3. Apply the scoring rule where the question has one. Otherwise an answer must
   match exactly (same city, same direction, same range):
   - **Q5:** `correct` only with "higher in every city" *and* the reason (SAVE10 concentrated in Tokyo and Seoul).
   - **Q6:** `correct` only if the Oat Milk stockout is named as the cause.
   - **Q7:** full credit for $50-55 gross with the WELCOME10 threshold as the reason. Partial credit for $40-45 net with the same reason.
4. Numbers: accept the rounding the report printed ($16,645.52, $16,646, $16.6K
   are all right). A different metric is not right: a gross AOV where net AOV
   is asked is `wrong` unless the report labels it as gross.
5. `not_addressed` is not `wrong`. The open request does not ask every
   question, so compare versions on `correct` and `naive` counts, not on
   coverage alone. For Part B, `naive` is the important number: it means the
   report fell into the trap.

### What counts as falling into a trap

| Trap | Signs in a report |
|---|---|
| B1 duplicates | Ranks Sydney first, or totals that include the 111 duplicate rows ($111,065.13 revenue instead of $110,270.26) |
| B2 Simpson | Recommends dropping SAVE10 because it "lowers basket value" |
| B3 stockout | Explains the Berlin coffee drop by demand, weather or the weekend |
| B4 threshold | Reads the new-customer order values as normal spending |
| B5 halo | Judges PASTA30 on Spaghetti alone, or misses the post-promo dip |
| B6 late night | Treats late night as a low-value time slot |

## If the dataset changes

The dataset is fixed, and the generator is not in the repository. If the CSV
ever changes, all of these must change together:

1. `ground_truth.json` / `.md`: recompute every answer from the new CSV.
2. `answer_keys/jungle_market.json`: run `answer_keys/build_answer_key.py`, then check its values against `ground_truth.json` by hand.
3. Hard-coded counts: "111 duplicate rows" and "15,680 rows" appear in
   `build_answer_key.py`, the README and this file.
4. Re-run `sanity/factcheck_sanity.py` and `sanity/judge_sanity.py`, and re-grade the
   baseline runs. A new answer key changes `factcheck_version`, so old fact
   checks are not reused.
