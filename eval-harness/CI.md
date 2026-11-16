# Eval harness: GitHub Actions → AgentCore Runtime

The four Actions jobs invoke the existing **evaluation** AgentCore Runtime independently. The evaluator files execute inside that Runtime container; the GitHub runner only installs the invocation client and calls the Runtime API.

| Actions job | Runtime payload `evaluator` | File inside the runtime, relative to `/app/eval-harness/` |
|---|---|---|
| Rules | rules | graders/rules.py |
| Factcheck | factcheck | graders/factcheck.py |
| LLM Judge | judge | graders/judge.py |
| Pairwise | pairwise | graders/pairwise.py |

All four scripts currently print Hello World. They do not analyze CSVs, evaluate reports, call models, or compare baselines yet. The matrix has no job dependencies, allows four concurrent jobs, and disables fail-fast. Actual scheduling depends on GitHub runner availability.

## Runtime code

- `runtime.py`: AgentCore entry point. Selects one of the four fixed paths, runs it with Python with a 30-second timeout, and returns stdout, exit code, request/session IDs, timestamps, script SHA-256 and deployed code revision. Payloads without `evaluator` retain the existing analysis entry point.
- `Dockerfile`: layers the wrapper and four scripts over the existing managed-agentcore image. Deploy this image to the evaluation Runtime only, using `eval_runtime.py set-image <image-uri@sha256:digest>`.
- `invoke_runtime.py`: calls the Runtime and checks the returned request ID, evaluator, path, file hash, successful exit and Hello World output. A stale deployed script or failed execution fails the Actions job. The response is stored as an Actions artifact for each evaluator.

Changing an evaluator requires rebuilding and redeploying the evaluation Runtime before checking that change in Actions. This workflow invokes the deployed image; it does not deploy images itself. The users' Runtime stays on its own image.

## Authentication and execution

The GitHub environment `eval-harness` supplies `EVAL_RUNTIME_ARN` and `EVAL_AWS_ROLE_ARN`. Region is `us-west-2`. AWS credentials are obtained through GitHub OIDC; no long-lived AWS keys are stored in GitHub. The caller role can invoke only the evaluation Runtime and its DEFAULT endpoint.

The environment requires approval by `glossyyoon` before AWS access. Deployment branch rules currently permit `codex/eval-harness-parallel-20261116`, PR #160's merge ref, and `main`. Fork pull requests are skipped. Review code before approving a run because the approved runner receives the role's temporary credentials.

Changes to this workflow or its runtime/evaluator paths trigger a pull-request run. After merging into the default branch, **Actions → Eval harness → Run workflow** also starts the four jobs. Approve the `eval-harness` environment when prompted, then inspect each job's Runtime result and downloadable artifact.

For a local call with AWS credentials and a deployed image:

```bash
python invoke_runtime.py --evaluator rules --runtime-arn <eval-runtime-arn>
```

Direct file commands such as `python graders/rules.py` still work locally, but do not verify the Actions-to-Runtime connection. Replace each file's `main()` body when its evaluator implementation is ready.
