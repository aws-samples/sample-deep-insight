# Data Validation — Files Changed and Created

A file-by-file inventory of the citation/data-validation system, across both
deployments (`self-hosted/`, `managed-agentcore/`).

**Source commits**
- `77cae05` — Citation integrity: deterministic Resolver + independent Auditor + contiguous renumber (self-hosted + managed)
- `8a0d665` — Data validation pipeline + chart quality refinements

**Recorded**: 2026-05-28

---

## Summary

- Both deployments are kept in **parity**: every `src/prompts/` and `src/tools/`
  change ships to both `self-hosted/` and `managed-agentcore/`.
- `77cae05` touched **31 files** (~2,344 insertions, ~180 deletions).
- `8a0d665` touched **5 files** (~454 insertions, ~221 deletions).
- Two genuinely new files added per deployment: the **`auditor.md`** system
  prompt and the **Auditor agent tool wrapper**. Everything else is targeted
  modification of pre-existing files.

---

## Prompts (`src/prompts/`)

### NEW

| File | self-hosted | managed-agentcore | Purpose |
|---|---|---|---|
| `auditor.md` | NEW (521 lines) | NEW (521 lines) | Auditor agent system prompt. DeepTRACE 4-type classification (A/B/C/D), embedded `audit_engine` code executed via `write_and_execute_tool`, value-tolerance matching (`tol_abs=0.05`), verdict emission (PASS / RETRY / NEEDS_REVIEW). |

### MODIFIED

Δ values are total lines changed (insertions + deletions) as reported by
`git show --stat`, summed across the two commits.

| File | self-hosted Δ | managed Δ | What changed |
|---|---|---|---|
| `reporter.md` | 319 (`77cae05`) + 108 (`8a0d665`) | 267 (`77cae05`) + 108 (`8a0d665`) | (1) `resolve_body_citations(doc)` — deterministic Resolver: pre-strip every `[N]` the LLM wrote, then re-insert markers from `citations.json` (verified entries only) within tolerance. (2) Chart-safe text edits via `w:t` node mutation (avoids the `Run.text` setter that wipes `<w:drawing>`). (3) Contiguous renumber driven by actual body markers (no orphan/gap). (4) LAST-occurrence reference-section split (TOC-safe on docs whose TOC contains the reference-section title). (5) Clean-version `_strip_markers` with stray-space removal. (6) Tolerance floor raised `0.01` → `0.05`. (7) Earlier chart-quality refinements from `8a0d665`. |
| `validator.md` | 51 | 46 | `needs_review` escalation discipline; dedup via `aliases`; verify-all-high (the `[:20]` cap was removed); citation metadata schema with `calculation_id` cross-link to `calculation_metadata.json`. |
| `coder.md` | 36 (`77cae05`) + 118 (`8a0d665`) | 36 (`77cae05`) + 118 (`8a0d665`) | Importance discipline (`high` / `medium` / `low`); `calculation_metadata` schema with `formula` and `source_file`; alignment language: "Validator verifies ALL high (no cap)"; chart-quality refinements from `8a0d665`. |
| `supervisor.md` | 114 | 114 | Auditor orchestration: when to invoke, what to pass; retry-loop semantics on Type B/C; agent inventory expanded to include the Auditor. |
| `planner.md` | 35 | 35 | Auditor task injected into the plan checklist (e.g. `4. Auditor: 최종 보고서 인용 감사 / 감사 결과 verdict 발행`). |

### TRIVIAL CLEANUP

Vestigial top-of-prefix `{CURRENT_TIME}` removed to keep the Bedrock
prompt-cache prefix stable across runs.

| File (both deployments) | Δ |
|---|---|
| `coordinator.md`, `planner_revise.md`, `reporter_pdf.md`, `toy_agent.md`, `tracker.md` | −1 line each |

---

## Tools (`src/tools/`)

### NEW

| File | Deployment | Lines | Purpose |
|---|---|---|---|
| `auditor_agent_tool.py` | `self-hosted/` | 179 | Strands SDK `@tool` wrapper for the Auditor. Loads the `auditor` system prompt, reads `AUDITOR_MODEL_ID` from env, enables Bedrock prompt caching (`prompt_cache_info=(True, "default")`, `tool_cache=True`), wires the local `write_and_execute_tool` for `audit_engine.py` execution. |
| `auditor_agent_custom_interpreter_tool.py` | `managed-agentcore/` | 196 | Functionally identical wrapper for the managed deployment. Differences: wraps execution in an OpenTelemetry span, calls `get_global_session().ensure_session()` to keep a Fargate session warm, uses `custom_interpreter_write_and_execute_tool` (HTTP into the Fargate code-executor) instead of the local executor. |

---

## Graph & Runtime

| File | Deployment(s) | Δ | What changed |
|---|---|---|---|
| `src/graph/nodes.py` | both | 3 each | Auditor tool registered in the Supervisor node's tool list so the Supervisor can invoke it during execution. |

---

## Environment Variables (`.env.example`)

| File | Δ | What was added |
|---|---|---|
| `self-hosted/.env.example` | 13 | `AUDITOR_MODEL_ID=...` plus per-agent model-ID alignment cleanup. |
| `managed-agentcore/.env.example` | 1 | `AUDITOR_MODEL_ID=global.anthropic.claude-sonnet-4-6` |

The Auditor runs on the same Sonnet tier as the Supervisor by default; override
in your local `.env` to change tier.

---

## Build / Hygiene

| File | Δ | Purpose |
|---|---|---|
| `self-hosted/setup/uv.lock` | 16 | Lockfile drift from dependency resolution (`strands-agents` and related). |
| `.gitignore` (root) | 4 | Explicit pin for the `citation-marker-misuse.md` PoC document (kept locally in a staging directory). It references customer-data filenames, S3 paths, and MD5 hashes; never committed (defense in depth on top of the broader `under_development/` rule). |
| `self-hosted/.gitignore` | 4 | Excludes `artifacts_*/` (per-run outputs) and a customer-sample dataset directory under `data/`. |

---

## Documentation (`docs/features/data-validation/`)

This folder was established as the canonical home for citation / data-validation
documentation.

| File | Status | Purpose |
|---|---|---|
| `citation-validation-explained.md` | Promoted from a staging directory | Beginner's guide. Definitions, DeepTRACE taxonomy, worked example (one number end-to-end through Coder → Validator → Reporter → Resolver → Auditor), ASCII diagrams. |
| `citation-coverage-research.md` | Promoted from a staging directory | Research note on post-hoc vs generation-time citation; the basis for the deterministic Resolver design. |
| `files-changed.md` | NEW (this file) | File-by-file record of what was changed and created. |

The original PoC document `citation-marker-misuse.md` was **deliberately kept
in a staging directory** (gitignored): it contains
customer-data references — dataset filenames, S3 paths, MD5 hashes, specific
cited values — and is kept locally as a historical record only, never committed.

`docs/features/improve-chart-visibility/README.md` was the doc updated by
`8a0d665` (chart-quality side of that commit) — it lives in its own feature
folder.

---

## Predecessors (context only)

The two commits above (`77cae05`, `8a0d665`) are the explicit "data validation"
commits. The following earlier commits laid foundations but are not enumerated
file-by-file in this record:

- `ca09054` — Validator immutability + Reporter `needs_review` handling + chart polish
- `e94391c` — FIX: Reporter audit regex double-escape + Coder pie-chart small-wedge rule
- `21ad5ea` — FIX: Preserve chart images in `final_report.docx` by using `w:t` element targeting
- `55eb15c` — ADD: Chart visibility initiative (vector embed, anti-clip rules)

Run `git log --oneline` for full history.
