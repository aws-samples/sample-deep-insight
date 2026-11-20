# Eval harness: GitHub Actions → AgentCore Runtime

One Actions job invokes the existing **evaluation** AgentCore Runtime once. Within that invocation, the Runtime awaits each evaluator before starting the next: Rules → Factcheck → LLM Judge → Pairwise. The evaluator files execute inside that Runtime container; the GitHub runner only installs the invocation client and calls the Runtime API.

| Execution order | Evaluator in Runtime payload `evaluators` | File inside the runtime, relative to `/app/eval-harness/` |
|---|---|---|
| 1. Rules | rules | graders/rules.py |
| 2. Factcheck | factcheck | graders/factcheck.py |
| 3. LLM Judge | judge | graders/judge.py |
| 4. Pairwise | pairwise | graders/pairwise.py |

All four scripts currently print Hello World. They do not analyze CSVs, evaluate reports, call models, or compare baselines yet. There is no job matrix or concurrent evaluator execution. A script's nonzero exit or 30-second timeout is recorded and the remaining evaluators still run; any unsuccessful result fails the Actions job.

## Runtime code

- `runtime.py`: AgentCore entry point. Accepts `evaluators: ["rules", "factcheck", "judge", "pairwise"]` and a request ID, then runs all four fixed paths sequentially with Python and a 30-second timeout per script. Returns one `evaluation_complete` response containing the ordered `results`, each with stdout, stderr, exit code, shared request/session IDs, timestamps, script SHA-256 and deployed code revision. Payloads without `evaluators` retain the existing analysis entry point.
- `Dockerfile`: layers the wrapper and four scripts over the existing managed-agentcore image. Deploy this image to the evaluation Runtime only, using `eval_runtime.py set-image <image-uri@sha256:digest>`.
- `invoke_runtime.py`: calls the Runtime once with retries disabled and checks the shared request/session IDs, all four evaluator results in order, paths, file hashes, successful exits and Hello World outputs. A stale deployed script, missing or reordered result, or failed execution fails the Actions job. The combined response is stored as `results/evaluators.json` in the single `eval-runtime-results` Actions artifact.

Changing the runtime wrapper or an evaluator requires rebuilding and redeploying the evaluation Runtime before checking that change in Actions. In particular, the deployed image must support the `evaluators` batch payload. This workflow invokes the deployed image; it does not deploy images itself. The users' Runtime stays on its own image.

## Authentication and execution

The GitHub environment `eval-harness` supplies `EVAL_RUNTIME_ARN` and `EVAL_AWS_ROLE_ARN`. Region is `us-west-2`. AWS credentials are obtained through GitHub OIDC; no long-lived AWS keys are stored in GitHub. The caller role can invoke only the evaluation Runtime and its DEFAULT endpoint.

The environment requires approval by `glossyyoon` before AWS access. Deployment branch rules currently permit `codex/eval-harness-parallel-20261116`, PR #160's merge ref, and `main`. Fork pull requests are skipped. Review code before approving a run because the approved runner receives the role's temporary credentials.

Changes to this workflow or its runtime/evaluator paths trigger a pull-request run. After merging into the default branch, **Actions → Eval harness → Run workflow** also starts the single job. Approve the `eval-harness` environment when prompted, then inspect the combined Runtime result and downloadable artifact.

For a local call with AWS credentials and a deployed image:

```bash
python invoke_runtime.py --runtime-arn <eval-runtime-arn> --out results/evaluators.json
```

Direct file commands such as `python graders/rules.py` still work locally, but do not verify the Actions-to-Runtime connection. Replace each file's `main()` body when its evaluator implementation is ready.
