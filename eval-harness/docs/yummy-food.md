# Yummy Food: the second development dataset

**→ Back to [Eval Harness README](../README.md)**

Yummy Food is the second dataset the eval harness is tuned on, next to
[Jungle Market](jungle-market.md). It is one month of daily ad performance for
a fictional food seller: 6 products advertised on 4 media. Jungle Market's
traps are in the data (duplicates, a stockout, a confounded coupon); Yummy
Food has nothing to clean, and its traps are in how ad metrics are
aggregated. A report that averages the ratio columns, or reads a high CTR as a
high return, gets the main answers wrong. Every pattern has one correct
answer, computed from the CSV.

It has a Korean (kr) and an English (en) edition with the same numbers;
`yummy_food_kr` and `yummy_food_en` are the scenarios. Both are in the `dev`
split, so prompts, the judge, the rubric and pass thresholds may be tuned on
them. moon_market is the test set (see the README).

## Files

| File | What it is | Sent to the agents? |
|---|---|---|
| `managed-agentcore/data/yummy_food/<lang>/yummy-food-market.csv` | The data: 720 rows | Yes |
| `managed-agentcore/data/yummy_food/<lang>/column_definitions.json` | Column descriptions, including how each ratio column is computed | Yes |
| `eval-harness/ground_truth/yummy_food/<lang>/ground_truth.md` | Answer sheet for people: patterns, naive vs correct answers, Q1-Q13 | **No** |
| `eval-harness/ground_truth/yummy_food/<lang>/ground_truth.json` | The same answers, machine-readable | **No** |
| `eval-harness/answer_keys/yummy_food_<lang>.json` | 38 facts the fact checker (`graders/factcheck.py`) compares reports against | **No** |
| `eval-harness/answer_keys/build_answer_key.py` | Builds the answer keys from the CSV with pandas (`yummy_food()`) | No |
| `eval-harness/sanity/factcheck_cases/yummy_food.yaml` | Gold cases for the fact checker (kr) | No |

The same files are in `self-hosted/data/yummy_food/<lang>/` and, for the web app's sample list, in `deep-insight-web/sample_data/yummyfood-<lang>/` (named `<lang>-yummy-food-market.csv`, `<lang>-yummy-food-column_definitions.json`). Only the CSV and
`column_definitions.json` are in the scenarios' `upload` lists.

## The data

- **Period:** 2025-09-01 to 2025-09-30, 30 days
- **Size:** 720 rows = 4 media × 6 products × 30 days, one row each; no duplicates, no missing rows
- **Media:** 쿠빵, 네이바, 아마존, 컬삼 (en: Kuppang, Neiba, Amazon, Kulsam). Amounts in KRW
- **Products:** 간편식 (즉석밥세트, 냉동만두), 건강식품 (프로틴바, 오메가3), 신선식품 (샐러드키트, 프리미엄과일)
- **Columns:** `날짜, 매체, 카테고리, 상품명, 노출수, 클릭수, 전환수, 광고비용, 매출액, CTR, 전환율, ROAS, 주요구매연령, 주요구매성별`
  (en: `Date, Media, Category, Product, Impressions, Clicks, Conversions, Ad Cost, Revenue, CTR, CVR, ROAS, Main Age Group, Main Gender`)
- **Totals:** ad spend 388,296,000원, revenue 1,316,606,500원, ROAS 3.39

**Definitions used by every answer**

- CTR = SUM(클릭수) / SUM(노출수). Conversion rate = SUM(전환수) / SUM(클릭수). ROAS = SUM(매출액) / SUM(광고비용), a ratio (4.14 = 414%).
- The CTR, 전환율 and ROAS columns are each row's own ratio. A figure for several rows is recomputed from the summed counts, never averaged from these columns.
- 매출액 is the revenue of the row's ad conversions only. There are no costs or margins, so whether a ROAS is profitable is not in the data.

## What is planted

**Part A: familiar patterns.**

| Pattern | Answer |
|---|---|
| Revenue by media | 쿠빵 > 네이바 > 아마존 > 컬삼 |
| Category revenue share | 신선식품 39.41% > 간편식 35.01% > 건강식품 25.59% |
| Media most reliant on 신선식품 | 컬삼 (77.55% of its own revenue; the others about 33%) |
| Highest ROAS and revenue per conversion by product | 프리미엄과일 (3.85, 44,670원) |
| Highest average daily revenue | Saturday, then Sunday; weekend days 1.26x weekdays, from a higher conversion rate, not more spend |

**Part B: patterns that need real analysis.**

| # | Pattern | Naive answer | Correct answer |
|---|---|---|---|
| B1 | Averaging the ROAS column | 아마존 has the highest ROAS (5.74, mean of the column) | SUM/SUM ranks 쿠빵 first (4.14) and 아마존 third (3.17). 아마존's tiny-budget rows (about 60,000원 a day, ROAS 8.8) weigh as much as its large ones in a plain mean |
| B2 | High CTR, low return | 네이바 has the highest CTR (3.21%), so move budget to it | 네이바 also has the lowest conversion rate (2.13%) and the lowest ROAS (2.35): cheap clicks that convert least |
| B3 | 쿠빵's doubled budget | The extra spend earns 쿠빵's full-month ROAS (4.14) | 쿠빵's daily spend doubled from 09-16; the extra spend returned 1.67원 per 1원, below every other media's full-month ROAS. 쿠빵's ROAS fell from 5.38 to 3.53 |

Not scored, because the data can't decide it: whether more 쿠빵 budget pays off
(no margins), and what the other media would return on more spend (their spend
never changed). A report that says so is right to.

Full numbers and the reasoning are in `ground_truth.md`.

## Two answer sources, one set of numbers

| | `ground_truth.json` / `.md` | `answer_keys/yummy_food_<lang>.json` |
|---|---|---|
| Used by | a person grading a report | `graders/factcheck.py` (automated) |
| Shape | 13 questions with a correct answer, a naive answer and a scoring rule | 38 facts: value or ranking, each with a scope |

The two agree (checked 2026-10-14). The en key is the kr key with names
translated. Which answer-key facts cover each question:

| Question | Answer-key facts |
|---|---|
| Overview | `total_impressions`, `total_clicks`, `total_conversions`, `row_count`, `overall_ctr_pct`, `overall_cvr_pct`, `revenue_per_conversion` |
| Q1, Q2 ROAS by media | `media_roas_ranking`, `media_roas_kuppang`, `media_roas_kulsam`, `media_roas_amazon`, `media_roas_neiba` |
| Q3 highest CTR | `media_ctr_ranking`, `media_cvr_ranking`, `media_ctr_pct_neiba`, `media_cvr_pct_neiba` |
| Q4 spend change | `kuppang_daily_spend_before`, `kuppang_daily_spend_after` |
| Q5 incremental ROAS | `kuppang_incremental_roas`, `kuppang_roas_before`, `kuppang_roas_after` |
| Q6 totals | `total_revenue`, `total_ad_spend`, `overall_roas` |
| Q7 revenue by media | `media_revenue_ranking`, `media_revenue_*` |
| Q8 신선식품 reliance | `top_media_fresh_food_share_pct` |
| Q9 category share | `category_revenue_ranking`, `category_revenue_share_pct_*` |
| Q10, Q11 top product | `top_product_revenue_per_conversion`, `top_product_roas` |
| Q12 weekday | `saturday_avg_daily_revenue`, `weekend_vs_weekday_daily_revenue_x` |
| Q13 main buyers of 오메가3 | none: a name, graded from the sheet |

## How to evaluate

```bash
cd eval-harness
.venv/bin/python run_eval.py --scenario yummy_food_kr --repeat 3 --tag baseline
.venv/bin/python grade.py <run_dir> --scenario yummy_food_kr      # re-grade a saved run
```

| Scenario | Request | What to expect from the report |
|---|---|---|
| `yummy_food_kr` | Ad performance by media, category and product; where spend is efficient or wasted; 3 strategies with priority and expected impact | Part A, ROAS by media computed SUM/SUM (B1), and ideally B2 and B3 |
| `yummy_food_en` | The same on the English edition | Same |

The request names CTR, conversion rate and ROAS but none of the traps.
`column_definitions.json` says that several rows combine as SUM ÷ SUM, so B1
tests whether the analysis follows the column definitions; B2 and B3 need
comparing metrics and looking at the daily series. For the fact check, the mean of the ROAS column is a different (wrong)
quantity, not another scope: "아마존 ROAS 5.74, 1위" is wrong. A sentence that
names the method as a contrast ("단순 평균하면 아마존이 1위처럼 보이지만")
is true, and figures for a named subset (the second half, weekends, 아마존's
small-budget rows) are out of scope.

`core_pass` thresholds are in `config/scenarios.yaml` under `pass:`; like
jungle_market's they are loose defaults until the first baseline runs.

To grade by hand, use the Q1-Q13 table at the end of `ground_truth.md` the way
[jungle-market.md](jungle-market.md#2-manual-grade-a-report-with-q1-q18)
describes. Only Q5 has partial credit: an incremental ROAS split by product or
by weekday/weekend (1.42 to 1.95).

### Gold cases

`sanity/factcheck_cases/yummy_food.yaml` measures the fact checker on this
data. Its report (`yummy_food_report_a.txt`) is written by hand from the
answer sheet and makes the B1 and B3 mistakes (`naive`); `corrected`,
`planted`, `scope_traps` and `injection` are built from it as for
jungle_market. It is not a real run: no Deep Insight report on the current
data existed when it was written. Add a `real` case from the first
`yummy_food_kr` baseline run, with its labels checked against the CSV.

### What counts as falling into a trap

| Trap | Signs in a report |
|---|---|
| B1 ROAS mean | Ranks 아마존 first by ROAS, or gives media ROAS of 5.74 / 4.45 / 3.10 |
| B2 CTR | Calls 네이바 the most efficient media, or moves budget to it for its CTR |
| B3 budget | Reads 쿠빵's full-month ROAS as the return on its extra spend, or misses that the spend changed |

## If the dataset changes

1. `ground_truth/yummy_food/<lang>/ground_truth.json` / `.md`: recompute every answer.
2. `answer_keys/yummy_food_<lang>.json`: run `answer_keys/build_answer_key.py`
   (its asserts stop it if a planted pattern disappeared), then check the
   values against `ground_truth.json` by hand.
3. `sanity/factcheck_cases/yummy_food_report_a.txt` and its labels.
4. Re-run `sanity/factcheck_sanity.py` and re-grade the baseline runs.
