# Eval harness: parallel file execution

The workflow currently launches four Python entry points. Each prints Hello World with its evaluator name and file path.

| GitHub Actions job | File, relative to eval-harness/ |
|---|---|
| Rules | graders/rules.py |
| Factcheck | graders/factcheck.py |
| LLM Judge | graders/judge.py |
| Pairwise | pairwise.py |

All four jobs are independent: there are no job dependencies, the matrix permits four concurrent jobs, and fail-fast is disabled. Actual start times depend on GitHub runner availability.

Run **Actions → Eval harness → Run workflow** after the workflow is merged into the default branch. Changes to the workflow or these evaluator paths also run it on pull requests, so execution can be verified before merging.

No inputs, AWS credentials, S3 files, model calls, or additional Python packages are needed for this execution check. The existing rule-grader modules and grade.py remain available for their original use.

Local commands, from eval-harness/:

```bash
python graders/rules.py
python graders/factcheck.py
python graders/judge.py
python pairwise.py
```

Replace the main() body in each entry point when its evaluation implementation is ready.

