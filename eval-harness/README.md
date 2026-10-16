# Deep Insight Eval Harness

**→ Back to [Main README](../README.md)** · **English** | [한국어](README.ko.md)

An automatic scorecard for Deep Insight. When you change code, prompts or
models, it answers two questions with numbers instead of "the report reads
better":

1. **Does core functionality still work?** → PASS / FAIL per run
2. **What got better or worse, and by how much?** → before/after table

This version grades with rules only: no model calls, so grading is free.
Checks that need a reader (an answer-key fact check, an LLM judge, a
pairwise judge) come in follow-up PRs.

## What it is

| Part | What it does |
|---|---|
| **Runner** `run_eval.py` | Sends a fixed analysis request to the deployed runtime, approves the plan review automatically (no human), and saves the report, citations, code-execution logs and token usage |
| **Grader** `grade.py` | Scores one run: files produced, numbers correct, cost, time → `scores.json` with PASS / FAIL |
| **Comparer** `compare.py` | Puts two versions side by side: mean ± std per metric and the difference |
| **Static checks** `pytest` | Seconds, no AWS: prompt templates render, model request fields are valid, and the graders really catch planted defects |

Example `compare.py` output:

```
                          baseline        opus55          Δ
printed value = citation  100.0%          100.0%          +0.0%p
recompute matches CSV     100.0%          100.0%          +0.0%p
cost                      $10.20          $8.50           -17% ▲ better
duration                  1920s           1680s           -12% ▲ better
```

## Folder layout

```
eval-harness/
├── run_eval.py, grade.py, compare.py    commands you run day to day
├── eval_runtime.py                      eval runtime setup
├── graders/       rule-based scoring modules and cost.py
├── config/        scenarios.yaml, pricing.yaml, runtime_configs.yaml,
│                  eval.env (git-ignored, local only)
├── tests/         pytest suite and fixtures
└── eval_results/  every run, grade and comparison (git-ignored)
```

Run every command from `eval-harness/`. Paths in `config/scenarios.yaml` are
relative to `eval-harness/`.

## How it runs: steps and files

```
config/scenarios.yaml + jungle-market CSV
        │
        ▼  1. run_eval.py            invoke the eval runtime, auto-approve plan review
eval_results/<tag>/<run>/            events.jsonl, run.json, usage.json, config.json, artifacts/
        │
        ▼  2. grade.py               (run_eval.py calls it after each run)
        │     graders/*.py           files, citations, recompute, report, cost   → scores.json
        ▼
scores.json  (core_pass: PASS / FAIL)
        │
        └─▶ 3. compare.py            tag vs tag table              → stdout or compare.md
```

| Step | Command | Reads | Writes | Paid |
|---|---|---|---|---|
| 1. Run | `run_eval.py --scenario <s> --tag <t>` | `config/scenarios.yaml`, the scenario's `upload` files (sent to S3), `config/eval.env` | `eval_results/<t>/<s>-<time>-<n>/`: `events.jsonl`, `run.json`, `usage.json`, `config.json`, `s3/`, `artifacts/` | Yes: the runtime (agents, Fargate) |
| 2. Grade | `grade.py <run_dir> --scenario <s>` (automatic after step 1) | `artifacts/`, the CSV, `config/pricing.yaml`, the scenario's `pass:` | `scores.json` | No |
| 3. Compare | `compare.py <tag> <tag> [--out compare.md]` | `*/scores.json`, `run.json`, `config.json` | the table | No |

## Datasets: two to develop on, one kept out

Every scenario in `config/scenarios.yaml` has a `split`:

| Split | Datasets | What it is for |
|---|---|---|
| `dev` | jungle_market, yummy_food | Prompts and pass thresholds are tuned on these |
| `test` | moon_market | Checked before a release only. Nothing is tuned against it, so a change that only fits the dev sets shows up here |

- **jungle_market** (`deep-insight-web/sample_data/jungle-market/`): two weeks
  of grocery orders in 8 cities with planted patterns a shallow analysis gets
  wrong (duplicate rows that change the top city, a Simpson's paradox on a
  coupon, a stockout, threshold bunching, a promotion halo).
- **yummy_food** (`managed-agentcore/data/yummy_food/<lang>/`): one month of
  daily ad performance, 4 media × 6 products. Nothing to clean; the traps are
  in aggregating ad metrics (a mean of the ROAS column picks the wrong top
  media, the highest-CTR media has the lowest ROAS, a doubled budget returns
  far less at the margin).
- **moon_market** (`managed-agentcore/data/moon_market/<lang>/`): two weeks of
  single-product grocery orders in 10 Seoul districts. Its scenarios copy the
  dev pass thresholds and are only ever re-set from dev results.

Test scenarios need `--allow-test` in `run_eval.py`, and `compare.py` reports
dev and test in separate sections. Look at test results to decide a release,
not to pick the next change: once you tune on them, they are a third dev set.

## Workflow

```bash
# 0. once: setup (below)
# 1. measure the current version → reference point
.venv/bin/python run_eval.py --scenario jungle_market --repeat 3 --tag baseline
# 2. change code / prompts / models, redeploy the runtime, measure again
.venv/bin/python run_eval.py --scenario jungle_market --repeat 3 --tag my-change
# 3. compare
.venv/bin/python compare.py eval_results/baseline eval_results/my-change
```

Before a release, run the same versions on the test set as well:

```bash
.venv/bin/python run_eval.py --scenario moon_market_kr --repeat 3 --tag my-change-test --allow-test
.venv/bin/python compare.py eval_results/baseline-test eval_results/my-change-test --split test
```

Each run costs real money (a few dollars for `jungle_market_simple`, more for
the full query) and takes 15–40 minutes, so start with
`jungle_market_simple` when you only need a smoke test.

## Setup

```bash
cd eval-harness
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python -r requirements.txt
```

The runner reads `RUNTIME_ARN`, `AWS_REGION` and `S3_BUCKET_NAME` from
`managed-agentcore/.env` (written by the deploy scripts), or take
`--runtime-arn`, `--region`, `--bucket`.

## Static checks (no AWS)

```bash
.venv/bin/python -m pytest -q
```

`test_no_legacy_human_stop_sequence` is an expected failure (`xfail`, strict)
documenting a known bug; it turns into an error once the bug is fixed, so the
marker gets removed with the fix.

## Scenarios

`config/scenarios.yaml` defines dataset × query pairs:

| Scenario | Split | Use |
|---|---|---|
| `jungle_market` | dev | Main benchmark: open growth-opportunity request (Korean) |
| `jungle_market_en` | dev | The same request in English |
| `jungle_market_simple` | dev | Cheap smoke test: totals, AOV, category share |
| `jungle_market_revision` | dev | Same as simple, but requests one plan revision first (tests `planner_revise`) |
| `yummy_food_kr` | dev | Ad performance by media, category and product, and 3 strategies to spend the ad budget better |
| `yummy_food_en` | dev | The same request on the English edition |
| `moon_market_kr` | test | The open growth-opportunity request on moon_market (needs `--allow-test`) |
| `moon_market_en` | test | The same in English (needs `--allow-test`) |

The runner uploads each scenario's `upload` files (the CSV and
`column_definitions.json`) to `s3://<bucket>/uploads/eval-<scenario>/`, where
the web app puts uploads, and passes that as the data directory, so the
dataset doesn't have to be in the runtime image.

Each scenario's `pass:` block sets its core_pass thresholds:

| Key | Meaning |
|---|---|
| `min_recompute` | calculations that must be re-derived from the CSV |
| `min_cited_checked` | "number [n]" pairs that must be compared |

They start at loose defaults and are set from real runs: half of the lowest
count in a normal baseline run.

## The eval runtime: don't run evals on the users' runtime

The web app runs on the AgentCore runtime `deep_insight_runtime_vpc`. Evals
run on a separate one, `deep_insight_eval_runtime`, so that switching models
or trying an image for an experiment never changes what users get, and eval
load never sits in the users' runtime.

| | Users' runtime | Eval runtime |
|---|---|---|
| Who calls it | the web app (and `02_invoke_agentcore_runtime_vpc.py`) | `run_eval.py` only |
| Models | `managed-agentcore/.env`, set at deploy | `eval_runtime.py set-models <preset>` (`config/runtime_configs.yaml`) |
| Image | `…deep_insight_runtime_vpc:latest`, moves with every deploy | pinned by digest; changes only with `set-image` |
| Shared | role, VPC, ECS cluster, ALB, Fargate task definition, S3 bucket | same |

Sessions can't cross between the two: every request to a Fargate container
carries its session id, and the code executor rejects a mismatch with 403 (the
fix for the 2026-02-22 cross-runtime incident in `docs/incidents/`). What is
still shared is capacity (Fargate tasks, ALB, Bedrock quotas), so keep long
eval batches away from busy hours.

**Set it up once** (needs the users' runtime deployed, `managed-agentcore/` phases 1-3):

```bash
.venv/bin/python eval_runtime.py create    # copies the users' runtime; ARN → config/eval.env (git-ignored)
.venv/bin/python eval_runtime.py status    # both runtimes: version, image, models
```

**Day to day**

```bash
# measure what users have now
.venv/bin/python eval_runtime.py set-image          # follow the users' current image
.venv/bin/python eval_runtime.py set-models users
.venv/bin/python run_eval.py --scenario jungle_market --repeat 5 --tag baseline-<date>

# try a model config without touching users
.venv/bin/python eval_runtime.py set-models sonnet45-workers
.venv/bin/python run_eval.py --scenario jungle_market --repeat 5 --tag sonnet45
.venv/bin/python eval_runtime.py set-models users

# try a candidate image before it reaches users: build and push it with its own tag, then
.venv/bin/python eval_runtime.py set-image <account>.dkr.ecr.<region>.amazonaws.com/<repo>:<candidate-tag>
```

`run_eval.py` uses `EVAL_RUNTIME_ARN` from `config/eval.env` and refuses the users'
runtime (`RUNTIME_ARN` in `managed-agentcore/.env`) unless given
`--allow-users-runtime`. Runtimes created after 2026-06-11 can't set
`requireServiceS3Endpoint`, so the eval runtime keeps AgentCore's default
there while the users' runtime has it on; S3 access goes through the same VPC
either way. `eval_runtime.py delete` removes it.

## Runs on the eval runtime

```bash
.venv/bin/python run_eval.py --scenario jungle_market --repeat 3 --tag baseline
# parallel batches under one tag: give each its own repeat numbers
.venv/bin/python run_eval.py --scenario jungle_market --repeat 2 --first-repeat 4 --tag baseline
```

Each run is saved to `eval_results/<tag>/<scenario>-<timestamp>-<n>/`:
`events.jsonl` (every streamed event), `run.json` (status, timings),
`usage.json`, `config.json` (git SHA + the runtime's model IDs), the
downloaded session under `s3/` (`artifacts/` links to its artifacts), and
`scores.json`.

- Plan reviews are answered by writing the S3 feedback file the runtime polls
  (the same mechanism as `02_invoke_agentcore_runtime_vpc.py`), so there is no
  human wait and no 300 s timeout. A scenario's `hitl` list sends scripted
  revision requests first.
- Token usage is summed from the `usage_metadata` events in the stream; it
  matches the runtime's own `token_usage.json`.
- Model IDs come from the **runtime's** environment, not the local checkout,
  so comparing model configs means redeploying (or one runtime per config).
- The runtime doesn't stream tool calls. `agent_calls` counts `usage_metadata`
  events (one per agent invocation), and code failures come from the
  executor's `debug/execution_*.json`.
- If the runtime doesn't report a session_id, the run fails as
  `session_unresolved` instead of grading "the newest session" in the bucket,
  which could be someone else's. `--allow-session-fallback` restores the guess
  for a bucket nobody else uses and records a warning.

## Comparing tags

```bash
.venv/bin/python compare.py eval_results/baseline eval_results/candidate --out compare.md
```

One table per scenario:

- **pass/fail metrics** (core_pass, required artifacts, Auditor pass) show the
  rate with a 95% Wilson interval: `67% [21–94%] (2/3)`.
- **other metrics** show mean ± std (n).
- **Δ** vs the first tag carries a 95% bootstrap interval, and ▲/▼ appears only
  with **at least 5 runs a side** and an interval that excludes 0. With 3 runs
  a bootstrap is too coarse to mean anything: a constant series resamples to
  itself, so (0, 0, 0) vs (1, 1, 1) gets a zero-width interval. Below 5 runs
  the delta and interval are printed without a flag; read them as a hint, and
  use `--repeat 5` before calling a change.
- **pass^k**: the chance that k runs in a row all pass, which says more about
  reliability than the average pass rate.
- A ⚠ line appears when runs under one tag mix git SHAs, runtime versions or
  model sets; split them into separate tags before comparing.

Also prints per-agent cost with the model each agent ran on.

## Grading a run

```bash
.venv/bin/python grade.py <run_dir> --scenario jungle_market
```

`<run_dir>` holds an `artifacts/` folder (as downloaded from
`s3://<bucket>/deep-insight/fargate_sessions/<session_id>/`). Writes
`<run_dir>/scores.json`. Exit code 0 = core pass.

### What is scored

| Metric | Meaning | Source |
|---|---|---|
| `all_required_ok` | report docx, citations.json, calculation_metadata.json, validation_report.txt exist and parse | `graders/artifacts.py` |
| `citation_value_match_rate` | citations.json value == calculation_metadata value | `graders/citations.py` |
| `recompute_match_rate`, `recompute_supported`, `recompute_unverified` | metadata values re-derived from the raw CSV with pandas. Formulas are read as arithmetic over aggregates (SUM/AVG/MEAN/MEDIAN/MIN/MAX/COUNT/STD/TOTAL) with filters (`=`, `==`, `!=`, `IS NULL`, `NOT NULL`, inside or after the aggregate), grouping (`GROUP BY`, `grouped by`, `by`, `col\|key`, weekday) and placeholders (`cat`, `X`, `'{}'`) resolved from the calculation's description. Names the agent made up (`cat_sales`, `daily_sum`) stay unsupported. A subset named only in the description, by one to three column values ("아마존×건강식품 조합 ROAS"), is tried too. When the description names no group, the value only has to match some group (`recompute_lenient`); if none matches, it is `recompute_unverified`, not wrong. A file with exact duplicate rows is also recomputed without them, since removing them is the correct analysis (`recompute_dedup`) | `graders/recompute.py` |
| `cited_value_match_rate`, `cited_value_checked` | the number printed right before `[n]` in the report equals citation n, and how many pairs were compared | `graders/report.py` |
| `broken_citation_refs` | `[n]` in the body with no citation n | `graders/report.py` |
| `citation_inside_number` | `[n]` inside a number, range or time (`$111,065 [2].13`, `10 [1]~15%`). The value check reads only the part before the marker, so this is checked on its own; fails core_pass (#141) | `graders/report.py` |
| `validator_false_verified`, `validator_false_alarm` | citations the Validator marked verified that the recomputation finds wrong, and needs_review ones it finds right (the Reporter leaves needs_review numbers out), over `validator_verified_checked` / `validator_needs_review_checked` | `graders/recompute.py` |
| `citation_coverage` | share of significant numbers (amounts, %, decimals) in the body that carry a citation. Approximate | `graders/report.py` |
| `audit_pass`, `audit_block_findings` | the Auditor's own verdict, when the version has an Auditor | `graders/audit.py` |
| `audit_missed`, `audit_missed_kinds` | the Auditor passed a report in which the graders above find what it exists to block: a cited value that differs, a broken `[n]`, `[n]` inside a number | `grade.py` |
| `code_exec_failed`, `code_exec_fail_causes` | agent code that failed in the Fargate sandbox, bucketed by cause (missing file, AttributeError, …) | `graders/executions.py` |
| `cost_usd`, `cache_hit_rate` | token usage × `config/pricing.yaml` | `graders/cost.py` |

`core_pass` is defined once, in `fail_reasons()` in `grade.py`. A check that
produced no result fails instead of passing: a grader error, too few
calculations recomputed, too few citations compared.

### Prices

`config/pricing.yaml` holds Bedrock on-demand prices per model family. Entries marked
`verified: true` were read from the AWS Pricing API for us-west-2 global
inference; `verified: false` entries are list prices not yet checked. `null`
prices are reported as `unpriced_tokens` instead of guessed.
