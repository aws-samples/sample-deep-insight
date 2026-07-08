# Design: Fargate container "zombie" cleanup (Tier 1 + Tier 2) — revised on the merged #107 baseline

- **Date:** 2026-07-08
- **Status:** Approved design (revised)
- **Baseline:** PR #107 is **MERGED** (merge commit `6e472a9`). This design *builds on* #107's post-merge behavior — it does not re-describe it.
- **Scope (files):**
  - `managed-agentcore/src/tools/global_fargate_coordinator.py` (Tier 1 + Tier 2)
  - `managed-agentcore/fargate-runtime/code_executor_server.py` (one line: `sys.exit(0)` → `os._exit(0)` in `auto_shutdown`)
- **Supersedes:** the pre-merge draft, which *assumed* #107 as an unmerged premise. This version was re-validated against the actual merged code.



## Baseline (post-#107, verified in code)

On a completion failure the merged system now does:

- **Container** `complete_session` (`code_executor_server.py` L167–207): sets `is_complete = True` only **after** a confirmed `upload_to_s3` (L201, after L197); returns `bool`; a failed upload leaves `is_complete=False`. `/session/complete` returns HTTP 500 on failure.
- **Controller** `complete_session`: retries the completion POST ×4; only calls `_cleanup_session` (ALB deregister + `ecs.stop_task`) after a confirmed HTTP 200; on exhaustion returns `{upload_completed: False}` **without** StopTask — the container is left alive.
- **Coordinator** `cleanup_session` (`global_fargate_coordinator.py` L374–420): gates teardown on `upload_completed`; on failure keeps IP + session + HTTP client and early-returns.
- **Container** `auto_shutdown` (boot + 1h, `code_executor_server.py` ~L881): `if not is_complete: complete_session()` (direct-to-S3 salvage), then `sys.exit(0)`.

So the "failed flow" (keep-alive → salvage → reclaim gap) now genuinely exists. **Two gaps remain**, which this design closes:

1. On the failure path the **ALB target + coordinator state (IP, session) leak** — nothing reclaims them (no reaper).
2. `auto_shutdown`'s `sys.exit(0)` runs in a **daemon thread**, so it raises `SystemExit` only in that thread and does **not** terminate the process — the Fargate task never self-terminates on the failure path (empirically verified). The salvage upload runs, but the task lingers until externally stopped.



## Changes



### Change 0 — `os._exit` in `auto_shutdown` (container)

`code_executor_server.py`, `auto_shutdown` (~L881): replace `sys.exit(0)` with `os._exit(0)` so the daemon-thread shutdown actually terminates the process (and the Fargate task) after the boot+1h salvage. `os._exit` is appropriate: the salvage upload has already run, all logs use `flush=True`, and the container has no critical atexit handlers. (This is the earlier commit `59dd18d`, now valid on the post-#107 baseline; re-applied on this branch.)

### Tier 1 — deregister the ALB target on the failure path (coordinator)

In `cleanup_session`'s upload-not-confirmed branch: `_deregister_from_alb(container_ip)` immediately. Safe because the salvage upload is a direct boto3→S3 call that does **not** use the ALB, so removing the target prevents a permanent zombie in the target group. Do **not** StopTask (the container must live to salvage). Record the orphan (see Tier 2) and keep the IP held.

### Tier 2 — orphan tracking + reclaim-on-allocate sweep (coordinator)

- `_orphaned_sessions` **dict — REVISED from the draft's in-place flag.** On the failure path, **move** the session record out of `_sessions` into `_orphaned_sessions[req_id] = {task_arn, container_ip, session_id, orphaned_at}` and **delete it from** `_sessions`. Keep the IP in `_used_container_ips` (the container still holds it).
  - **Why moved, not flagged:** if the orphan stayed in `_sessions`, `ensure_session` (L224: `if req_id in self._sessions: return self._reuse_existing_session()`) would try to **reuse** it on a same-`request_id` retry — but Tier 1 removed its ALB target, so reuse would target a deregistered/dying container. Moving it out makes `ensure_session` create a **fresh** session instead, and gives the sweep a clean worklist. (Surfaced by the "think-it-over" pass and the review workflow.)
- `_is_tasks_stopped(task_arns) -> set(stopped_arns)` **— REVISED: batched.** One `ecs.describe_tasks` call for up to 100 ARNs. Classify a task as stopped when `lastStatus == 'STOPPED'` **or** it is absent from the response (already gone). On any API error, treat all as **not** stopped (conservative — never reclaim while the container may still hold its IP).
- `_reclaim_stopped_orphans()`**.** Batch-check every `_orphaned_sessions` entry; for each stopped one, reclaim: `_deregister_from_alb` (idempotent) + drop IP from `_used_container_ips` + drop `_http_clients[req_id]` + delete from `_orphaned_sessions` + add `req_id` to `_cleaned_up_requests`. Best-effort; log each reclaim; never raise into the request path.
- **Hook.** `ensure_session()` calls `_reclaim_stopped_orphans()` at entry (once per request, before the reuse/create decision).



## Error handling & concurrency

- Sweep/helper are **best-effort** — never raise into the request path.
- **Conservative reclaim** on unknown task status (do not free a held IP while unsure the task is dead).
- **Lock-free safety:** the sweep only touches `_orphaned_sessions` whose task is `STOPPED`; active sessions live in `_sessions` and are `RUNNING`, so never eligible. A `list(...)` snapshot avoids "dict changed during iteration." No new race surface versus the existing lock-free code. A real concurrency fix (locking + background reaper) is Tier 3, out of scope.



## Known limitations (documented, not fixed here)

- **Salvage is best-effort:** `auto_shutdown` calls `complete_session()` then `os._exit(0)` unconditionally; a persistent S3 failure — or the task dying earlier (spot reclaim / OOM / crash) — still loses the report permanently. Inherent to ephemeral container storage.
- **Out-of-band recovery:** a successful salvage lands in S3 up to ~1h after the user already saw a failure — it protects the artifact, not the live request UX.
- **Absolute (not idle) 1h timer:** a failure early in a container's life leaves it alive up to ~57 min before the salvage retry and before the reclaim sweep can find it `STOPPED`. The single boot-relative timer *doubles as* the max-session-lifetime cap (`auto_shutdown` force-completes and exits **any** session still running at 1h), so it **cannot simply be shortened** — lowering the constant would force-terminate legitimate long analyses (up to 500 executions × ≤600 s each) mid-run. Reducing the salvage delay requires *decoupling* the two roles (see Out of scope), not changing the value.
- **Unbounded until next request:** with no subsequent request, orphans linger in memory (bounded by process lifetime). The ALB target is already removed by Tier 1, so the AWS-side zombie is gone regardless.



## Testing

No test framework (per `CLAUDE.md`); mock-based like #107. Stub the ECS client / `_is_tasks_stopped` and assert:

- `STOPPED` orphan → removed from `_orphaned_sessions` + `_used_container_ips` + `_http_clients`, added to `_cleaned_up_requests`, ALB deregister called.
- `RUNNING` orphan → untouched.
- `describe_tasks` error → nothing reclaimed.
- `ensure_session` for a same `request_id` after tagging → creates a **fresh** session (does not reuse the orphan).
- batched `describe_tasks` → a **single** call for N orphans.



## Observability

ERROR log when a session is orphaned; INFO on each reclaim. CloudWatch metric / leak cap: deferred (YAGNI).

## Out of scope

Tier 3 (background reaper thread, ALB↔task reconciliation for crash-orphans, singleton locking, metrics/cap). No further container changes beyond `os._exit`. **Decoupling the 1h timer** — making the lifetime cap idle-based (reset on execution activity) and adding a dedicated short post-failure salvage-retry loop, both container-side — is deferred to a separate PR. The full review-workflow transcript (25 findings; 2 pre-#107 criticals now resolved by the merge) lives in the session's workflow journal.