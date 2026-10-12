# Deep Insight Eval Harness

**→ Back to [Main README](../README.md)**

An automatic scorecard for Deep Insight. When you change code, prompts or
models, it answers two questions with numbers instead of "the report reads
better":

1. **Does core functionality still work?** → PASS / FAIL per run
2. **What got better or worse, and by how much?** → before/after table

## What it is

| Part | What it does |
|---|---|
| **Runner** `run_eval.py` | Sends a fixed analysis request to the deployed runtime, approves the plan review automatically (no human), and saves the report, citations, code-execution logs and token usage |
| **Grader** `grade.py` | Scores one run: files produced, numbers correct, cost, time → `scores.json` with PASS / FAIL |
| **Comparer** `compare.py` | Puts two versions side by side: mean ± std per metric and the difference |
| **Fact checker** `factcheck.py` | A model reads the report against the answer key: which facts are stated right, which wrong, which are about another period or subset (paid, on by default) |
| **LLM judge** `judge.py`, `pairwise.py` | Grades what numbers can't: did the report answer the request, and is it better than the baseline's? (paid, opt-in) |
| **Static checks** `pytest` | Seconds, no AWS: prompt templates render, model request fields are valid, and the graders really catch planted defects |

Example `compare.py` output:

```
                       baseline        opus55          Δ
printed value = citation  100.0%        100.0%          +0.0%p
core facts correct        100.0%        100.0%          +0.0%p
cost                      $10.20        $8.50           -17% ▲ better
duration                  1920s         1680s           -12% ▲ better
```

## Datasets: one to develop on, two kept out

The harness runs on **jungle_market** only (`deep-insight-web/sample_data/jungle-market/`):
two weeks of grocery orders in 8 cities with planted patterns a shallow
analysis gets wrong (duplicate rows that change the top city, a Simpson's
paradox on a coupon, a stockout, threshold bunching, a promotion halo). Its
answer sheet (`ground_truth.json` / `.md`, Q1-Q18) lets a person grade a report
without recomputing anything.

**moon_market and yummy_food are test sets.** They have no scenarios, answer
keys or gold cases here, and no prompt or threshold is tuned against them, so
a change that only fits jungle_market shows up when it is checked on them.

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

Each run costs real money (a few dollars for `jungle_market_simple`, more for
the full query) and takes 15–40 minutes, so start with
`jungle_market_simple` when you only need a smoke test.

On top of that, grading makes paid model calls: **the fact check runs by
default** whenever the scenario has an answer key (about $1 per report;
`--no-factcheck` skips it), and the LLM judge runs with `--judge` (about
$0.1–0.3 per report). The runner prints which paid checks are on, with the
model and region, before the first run.

## Fact check: report numbers against the answer key

The answer key (`answer_keys/`) holds facts computed from the dataset with
pandas: totals, city rankings, co-purchase counts, promotion effects. Checking
a report against it needs reading, not pattern matching: "Sydney가 매출 1위" is
wrong for the deduplicated file (Singapore is 1st) but right for 2026-03-10
alone, and only the sentence around it says which. `factcheck.py` splits the work so the model
reads and code does the arithmetic:

1. **Extract** (model, answers hidden). The model gets each fact's definition
   and scope, without its value, and lists every statement the report makes
   about it: exact quote, stated value, unit, and the period or filter the
   report gives. Hiding the answers keeps it from seeing what it expects.
2. **Compare** (code). The quote must occur in the report, the number must
   occur in the quote, and the value must equal the answer at the precision
   it was printed with: 12,481,923 is not 12,431,923, while 12,430,000 and
   1,243만 are. Rankings compare positions, relations compare directions.
3. **Adjudicate** (model, answers shown). Every mismatch and every case code
   can't settle (scope unclear, unit doubtful) goes back with the answer and
   the paragraph around the quote.

Each statement ends as `correct`, `wrong_confirmed` (code and the adjudicator
both say wrong, same scope), `out_of_scope` (another period or subset),
`needs_review` (they disagree, or only the model says wrong) or
`unverified_quote` (the quote isn't in the report; discarded).
**`wrong_confirmed` fails `core_pass`; `needs_review` doesn't** and is listed
in `scores.json` details for a person to read. `71.73%p` for a growth rate is
counted as `factcheck_unit_issues`, not as a wrong value.

```bash
.venv/bin/python factcheck_sanity.py --repeat 3      # is the fact checker right? (paid, ~$5 per repeat)
.venv/bin/python grade.py <run_dir> --scenario jungle_market   # fact check runs by default
.venv/bin/python grade.py <run_dir> --scenario jungle_market --no-factcheck   # no model calls
```

- **Trust, then use.** `factcheck_sanity.py` runs the checker on gold cases
  in `factcheck_cases/`: a real report whose errors were found by hand, the
  same report with the errors fixed, small planted errors, statements about
  another period or subset, and an instruction aimed at the evaluator. It
  reports wrong recall, false wrongs and stability over repeats, and fails
  below 100% recall or above 0 false wrongs. Re-run it whenever the prompts
  (`factcheck.PROMPT_VERSION`), the model in `judge.yaml` or an answer key
  change. **No jungle_market gold case exists yet**: it needs a real report
  whose errors a person found by hand (#133), so factcheck-v3 is not yet
  measured.
- **Same evaluator on both sides.** Results are cached in `factcheck.json`
  by report hash and `factcheck_version` (prompt version, model, effort,
  answer-key hash). `compare.py` warns when tags were checked by different
  versions; re-grade both with `grade.py` on the saved runs.
- About $1 per report with `global.openai.gpt-6-astra` at effort high.
- The prompts' examples use made-up names and numbers, so no dataset's answer
  reaches the evaluator through them.

## LLM judge: analysis quality

The graders above check that numbers are right. They can't see whether the
report answers the request: a report that only states total revenue correctly
passes all of them. The judge closes that gap. It runs on an **OpenAI model in
Amazon Bedrock** (Converse API, `judge.yaml`), a different family from the
Claude agents, so it isn't grading its own family's writing. The fact check
uses the same model.

**Region and model.** `judge.yaml` → `region: null` uses `JUDGE_REGION`, then
`EVAL_REGION` (`eval.env`), then your AWS default region. Before the first
call, the harness checks that the model can be called there (a free Bedrock
control-plane call) and stops with a message if not. The default,
`global.openai.gpt-6-astra`, is what we tested in us-west-2; in another region
check what your account has and set `model:` to it:

```bash
aws bedrock list-inference-profiles --region <region> --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'openai')].[inferenceProfileId,status]"
```

A different model changes `judge_version`, so old verdicts are re-judged, not
reused; run `judge_sanity.py` and `factcheck_sanity.py` on it before trusting
its scores.

**Pointwise** (`grade.py --judge`, `run_eval.py --judge`) reads the request,
the scenario's `requirements` (`scenarios.yaml`) and the report, and returns:

- each requirement as met / partial / missing → `judge_requirement_coverage`,
  `judge_requirements_missing` (**a missing requirement fails `core_pass`**)
- 1-5 scores with anchored definitions: `evidence_linkage` (claims tied to
  findings), `strategy_specificity` (target, steps, quantified effect,
  priority), `insight_depth` (beyond descriptive stats), `reasoning_soundness`
  (no overclaiming, data limits stated)

Left out on purpose: numeric accuracy (the graders and the fact check do it),
chart quality (the judge reads text only), length and formatting.

**Pairwise** (`pairwise.py`) is the main A/B signal: judges are better at
"which of these two" than at absolute scores. Each candidate report is
compared with a frozen baseline report, twice with the order swapped; a
verdict that flips with the order counts as a tie. Results show in
`compare.py`.

```bash
.venv/bin/python judge_sanity.py eval_results/baseline/<run> --scenario jungle_market  # does the judge fail what must fail?
.venv/bin/python grade.py eval_results/baseline/<run> --scenario jungle_market --judge
.venv/bin/python pairwise.py eval_results/baseline eval_results/baseline   # noise floor, expect ~50%
.venv/bin/python pairwise.py eval_results/baseline eval_results/my-change
```

- **Use enough pairs.** With 3 pairs a single pair moves the win rate by ±33
  points, so compare with `--pairs all` (3 × 3 = 9 pairs) or more before
  acting on it, and run baseline vs baseline first to see the noise.
- **Trust, then use.** `judge_sanity.py` feeds the judge a real report and
  variants with known answers (numbers only, strategies removed, a different
  question, empty, a prompt injection) and fails if it scores them wrong. The
  baseline-vs-baseline pairwise run shows how far from 50% noise alone moves
  the win rate.
- **Calibrate once with people.** `calibrate.py export` writes a blind label
  sheet (no judge scores in it); label 10-20 reports, then
  `calibrate.py score` prints agreement per criterion (exact, ±1, Spearman,
  bias). Re-check whenever the rubric or judge model changes.
- Judge results are cached (`judge.json`, `pairwise/`) by report hash and
  `judge_version`: `judge.PROMPT_VERSION`, a fingerprint of the system prompt,
  rubric and prompt templates, the judge model and effort, and the scenario's
  request and requirements. Changing any of them re-judges instead of reusing
  an old verdict; unchanged re-grading doesn't pay twice. A reply that breaks the schema
  is recorded as `judge_error`, never as a score.

## Langfuse: browse, compare and label in a UI

`langfuse_sync.py` publishes results to a Langfuse project through the public
REST API. **What it sends:** the request, the full report text, judge
justifications and per-agent usage. Run Langfuse in your own AWS account so
none of this leaves it: [deploy-langfuse-on-ecs-with-fargate](https://github.com/aws-samples/deploy-langfuse-on-ecs-with-fargate)
deploys a self-hosted Langfuse on ECS Fargate. A Langfuse Cloud host
(`*.cloud.langfuse.com`) is refused unless you pass `--allow-cloud`.

Give the harness **a Langfuse project of its own**. A re-sync deletes what the
tool created earlier for the same runs: superseded traces (unless they have
human labels) and the dataset run of each synced tag in `deep-insight-eval`,
which is rebuilt. In a shared project, a dataset or run with the same name
would be replaced.

| Eval harness | Langfuse |
|---|---|
| scenario (request, requirements, answer key, pass thresholds) | item in dataset `deep-insight-eval` |
| tag (`baseline`, `my-change`) | dataset run of the same name |
| one run | trace: input = request, output = the report text, metadata = git SHA, runtime version, model IDs |
| per-agent tokens, cost, time span | one generation per agent |
| `scores.json`, `judge.json` | trace scores; judge scores carry the judge's justification as the comment |
| pairwise win rate | score on the candidate's dataset run |
| human labels | annotation queue `deep-insight-calibration`, same score configs as the judge |

```bash
# eval-harness/langfuse.env (git-ignored): LANGFUSE_HOST (or LANGFUSE_BASE_URL), LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
.venv/bin/python langfuse_sync.py eval_results/baseline eval_results/my-change --dry-run   # count only
.venv/bin/python langfuse_sync.py eval_results/baseline eval_results/my-change --queue
.venv/bin/python calibrate.py langfuse     # judge vs labels entered in the annotation queue
```

Langfuse keeps one trace per dataset item per run, so each repeat is its own
item (`jungle_market #1`, `#2`, …). Every timestamp is the run's own time:
the UI finds a trace by the time of the score or run item you click. Trace
and score ids carry a hash of the run's content, so syncing unchanged results
is a no-op and changed results replace the old trace (kept, with a warning,
if it already has human labels). When labeling in the queue, hide the API
(judge) scores so labels stay blind.

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

`scenarios.yaml` defines dataset × query pairs, all on jungle_market:

| Scenario | Use |
|---|---|
| `jungle_market` | Main benchmark: open growth-opportunity request (Korean) |
| `jungle_market_en` | The same request in English |
| `jungle_market_simple` | Cheap smoke test: totals, AOV, category share |
| `jungle_market_revision` | Same as simple, but requests one plan revision first (tests `planner_revise`) |

The runner uploads each scenario's `upload` files (the CSV and
`column_definitions.json`) to `s3://<bucket>/uploads/eval-<scenario>/`, where
the web app puts uploads, and passes that as the data directory, so the
dataset doesn't have to be in the runtime image. The answer sheet next to the
CSV is never listed, so it can't reach the agents.

Each scenario's `pass:` block sets its core_pass thresholds:

| Key | Meaning |
|---|---|
| `required_facts` | answer-key facts that must be stated correctly (fact check) |
| `min_other_facts` | of the remaining answer-key facts, how many must be stated correctly |
| `min_recompute` | calculations that must be re-derived from the CSV |
| `min_cited_checked` | "number [n]" pairs that must be compared |

They start at loose defaults and are set from real runs: half of the lowest
count in a normal baseline run. Segment numbers depend on what each report
chose to analyze, so requiring a specific one would fail good reports; "at
least N of the rest" lets the report choose but still fails one that states
few numbers or gets most of them wrong.

## The eval runtime: don't run evals on the users' runtime

The web app runs on the AgentCore runtime `deep_insight_runtime_vpc`. Evals
run on a separate one, `deep_insight_eval_runtime`, so that switching models
or trying an image for an experiment never changes what users get, and eval
load never sits in the users' runtime.

| | Users' runtime | Eval runtime |
|---|---|---|
| Who calls it | the web app (and `02_invoke_agentcore_runtime_vpc.py`) | `run_eval.py` only |
| Models | `managed-agentcore/.env`, set at deploy | `eval_runtime.py set-models <preset>` (`runtime_configs.yaml`) |
| Image | `…deep_insight_runtime_vpc:latest`, moves with every deploy | pinned by digest; changes only with `set-image` |
| Shared | role, VPC, ECS cluster, ALB, Fargate task definition, S3 bucket | same |

Sessions can't cross between the two: every request to a Fargate container
carries its session id, and the code executor rejects a mismatch with 403 (the
fix for the 2026-02-22 cross-runtime incident in `docs/incidents/`). What is
still shared is capacity (Fargate tasks, ALB, Bedrock quotas), so keep long
eval batches away from busy hours.

**Set it up once** (needs the users' runtime deployed, `managed-agentcore/` phases 1-3):

```bash
.venv/bin/python eval_runtime.py create    # copies the users' runtime; ARN → eval.env (git-ignored)
.venv/bin/python eval_runtime.py status    # both runtimes: version, image, models
```

**Day to day**

```bash
# measure what users have now
.venv/bin/python eval_runtime.py set-image          # follow the users' current image
.venv/bin/python eval_runtime.py set-models users
.venv/bin/python run_eval.py --scenario jungle_market --repeat 5 --tag baseline-<date> --judge

# try a model config without touching users
.venv/bin/python eval_runtime.py set-models sonnet45-workers
.venv/bin/python run_eval.py --scenario jungle_market --repeat 5 --tag sonnet45 --judge
.venv/bin/python eval_runtime.py set-models users

# try a candidate image before it reaches users: build and push it with its own tag, then
.venv/bin/python eval_runtime.py set-image <account>.dkr.ecr.<region>.amazonaws.com/<repo>:<candidate-tag>
```

`run_eval.py` uses `EVAL_RUNTIME_ARN` from `eval.env` and refuses the users'
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
  model sets, or when the tags were graded by different fact-check or judge
  versions; split or re-grade them before comparing.

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
| `recompute_match_rate`, `recompute_supported`, `recompute_unverified` | metadata values re-derived from the raw CSV with pandas. Formulas are read as arithmetic over aggregates (SUM/AVG/MEAN/MEDIAN/MIN/MAX/COUNT/STD/TOTAL) with filters (`=`, `==`, `!=`, `IS NULL`, `NOT NULL`, inside or after the aggregate), grouping (`GROUP BY`, `grouped by`, `col\|key`, weekday) and placeholders (`cat`, `X`, `'{}'`) resolved from the calculation's description. Names the agent made up (`cat_sales`, `daily_sum`) stay unsupported. When the description names no group, the value only has to match some group (`recompute_lenient`); if none matches, it is `recompute_unverified`, not wrong. A file with exact duplicate rows is also recomputed without them, since removing them is the correct analysis (`recompute_dedup`) | `graders/recompute.py` |
| `cited_value_match_rate`, `cited_value_checked` | the number printed right before `[n]` in the report equals citation n, and how many pairs were compared | `graders/report.py` |
| `broken_citation_refs` | `[n]` in the body with no citation n | `graders/report.py` |
| `citation_coverage` | share of significant numbers (amounts, %, decimals) in the body that carry a citation. Approximate | `graders/report.py` |
| `required_facts_missing`, `other_facts_found` | answer-key facts stated correctly: the scenario's required ones, and how many of the rest | `factcheck.py` + `answer_keys/` |
| `factcheck_wrong_confirmed`, `factcheck_wrong_ids` | statements that contradict the answer key in the same scope, confirmed by code and the adjudicating model | `factcheck.py` |
| `factcheck_needs_review`, `factcheck_out_of_scope`, `factcheck_unit_issues`, `factcheck_unverified_quotes` | statements left for a person, about another period or subset, written with %p, or quoted wrongly by the model | `factcheck.py` |
| `audit_pass`, `audit_block_findings` | the Auditor's own verdict, when the version has an Auditor | `graders/audit.py` |
| `code_exec_failed`, `code_exec_fail_causes` | agent code that failed in the Fargate sandbox, bucketed by cause (missing file, AttributeError, …) | `graders/executions.py` |
| `cost_usd`, `cache_hit_rate` | token usage × `pricing.yaml` | `cost.py` |

`core_pass` is defined once, in `fail_reasons()` in `grade.py`. A check that
produced no result fails instead of passing: a grader error, `judge_error` or
`factcheck_error`, too few calculations recomputed, too few citations
compared. Only checks that were deliberately not run (the LLM judge without
`--judge`, the fact check with `--no-factcheck`) are skipped.

### Answer keys

`answer_keys/build_answer_key.py` computes facts from the dataset with
pandas. Regenerate after the dataset changes and review the values by hand;
jungle_market's facts agree with the dataset's own `ground_truth.json`
(checked 2026-10-12). Each fact has a `kind` (value, ranking or relation), a
`description` and a `scope` the fact checker reads without the answer, a
`unit`, the answer itself, and a `note` shown only when a statement is
adjudicated. Values are after removing the file's 111 exact duplicate rows
unless `scope` says otherwise. Numbers that depend on a report's own formulas
(opportunity scores, scenario uplifts) are left out: they have no dataset
answer.

### Prices

`pricing.yaml` holds Bedrock on-demand prices per model family. Entries marked
`verified: true` were read from the AWS Pricing API for us-west-2 global
inference; `verified: false` entries are list prices not yet checked. `null`
prices are reported as `unpriced_tokens` instead of guessed.
