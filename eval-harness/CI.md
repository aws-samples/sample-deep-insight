# Eval harness: sequential evaluators in GitHub Actions

## Intended flow

```text
Code pushed to a branch
  → GitHub Actions starts
  → Invoke the evaluation AgentCore Runtime once
  → Wait for successful analysis completion
  → Download that run's reports, citations, execution logs and usage
  → Rules → Factcheck → LLM Judge → Pairwise (on the GitHub runner)
  → Upload evaluation results
```

This is supported by GitHub Actions: steps in one job execute in order, and
subsequent steps normally run only after earlier steps succeed. If Runtime
execution is moved to a separate job later, the evaluation job can use `needs`
to wait for it and download the artifacts it uploaded.

A Runtime callback that starts a new workflow is unnecessary for this design.
The original Actions job can keep the Runtime invocation stream open until
completion, then continue with its next step. For a long asynchronous run,
that step can instead poll a durable status record until it reaches success or
failure; accepting a request is not a completion signal.

## Implemented now

Runtime integration is **deferred**. The current workflow is an evaluator
entry-point smoke check, not a Runtime-to-Actions integration test.

- `push` to any branch starts the workflow; tags do not. Manual
  `workflow_dispatch` is also available. There is no additional `pull_request`
  trigger, avoiding duplicate runs for a branch with an open PR.
- One Ubuntu job checks out the pushed commit and sets up Python 3.12.
- Four ordinary steps run the checked-out scripts on the GitHub runner:

| Order | Actions step | Command | Log |
|---|---|---|---|
| 1 | Rules | `python graders/rules.py` | `results/rules.log` |
| 2 | Factcheck | `python graders/factcheck.py` | `results/factcheck.log` |
| 3 | LLM Judge | `python graders/judge.py` | `results/judge.log` |
| 4 | Pairwise | `python graders/pairwise.py` | `results/pairwise.log` |

All four scripts currently print Hello World. They do not read analysis
artifacts, evaluate reports, call models or compare baselines yet. No matrix,
background process, AWS login or Runtime invocation is used. Python's standard
library is sufficient for these entry points, so no dependency install is
needed yet.

Each evaluator has a one-minute step timeout. The explicit Bash shell enables
`pipefail`, so a failed Python command is not hidden by `tee`. A failed or timed
out evaluator stops the remaining evaluator steps; logs from the steps that
ran are uploaded with `if: always()` as the `eval-evaluator-logs` artifact.
These are script logs, not grading scores. Revisit timeouts and dependencies
when implementing the real evaluators.

## Deferred Runtime connection

Insert the following work before the Rules step, at the comment in
`.github/workflows/eval-harness.yml`:

1. Obtain AWS credentials through OIDC and the protected `eval-harness`
   environment, then invoke the **analysis** entry point on the evaluation
   Runtime once. Do not invoke the old batch evaluator dispatcher, which would
   run the same evaluators again inside the container.
2. Wait for an explicit successful terminal event (`workflow_complete` in the
   current analysis stream) and validate the run/session ID. Stop on a failed,
   incomplete or timed out run; HTTP 200 alone is insufficient.
3. Fetch only that session's artifacts and write a manifest containing the
   run/session ID, S3 location, deployed Runtime version/image and code revision.
   All four evaluators must consume that same run's files.
4. Pass the local artifact directory or manifest to each evaluator, implement
   their grading logic, and retain the manifest and scores as Actions artifacts.

`run_eval.py` already contains analysis invocation, automatic plan-review
feedback, completion-event handling and S3 download logic. It also calls
`grade.py` automatically; separate generation/download from grading before
using it as the upstream stage here. The existing invocation-only OIDC role
will also need appropriately scoped permissions for any chosen S3 feedback,
upload and download operations. Those changes are deferred with the connection.

A code push updates the scripts checked out by Actions. It does **not** rebuild
or redeploy an AgentCore Runtime image. If analysis code changes are to be
measured, deploy the matching evaluation image before invoking it and record
its revision separately from the Actions checkout revision.

The old `runtime.py`, `Dockerfile` and `invoke_runtime.py` remain available for
the previously deployed Runtime-side Hello World dispatcher. The new Actions
workflow does not call them. Their earlier AWS execution results do not verify
the newly proposed Runtime → Actions handoff. No Runtime redeploy, AWS invocation
or end-to-end handoff validation is part of this change.

## References

- [GitHub Actions workflow syntax: steps and job dependencies](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [Events that trigger workflows: push](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push)
