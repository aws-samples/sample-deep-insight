# Incident: Supervisor ConverseStream Stall — IncompleteRead After Successful Analysis

**Date**: 2026-03-17
**Severity**: Medium
**Affected**: Web UI → AgentCore Runtime streaming (managed deployment)
**Status**: Resolved — Coder prompt violation fixed (Fix 6 + Fix 8, 2026-03-20). Bedrock stall not reproduced. Stream keepalive and other resilience fixes still pending.

---

## Executive Summary

A complex analysis job failed on 2026-03-17 when the Supervisor agent's Bedrock `ConverseStream` call stalled silently for 15 minutes, triggering AgentCore's idle timeout. The Reporter agent was never invoked. Two root causes were identified:

1. **Bedrock API stall** (primary) — A cross-region `ConverseStream` call to us-east-2 accepted the request but returned zero bytes for 15 minutes. Not reproduced in 3 subsequent re-runs.

2. **Coder agent prompt violation** (contributing) — The Coder attempted DOCX generation (Reporter's job), bloating its context to ~36 tool calls. This was caused by the full plan leaking to the Coder through `shared_state["messages"]`, contradicting the system prompt prohibition.

**Resolution:**
- **Fix 5** (Done): Bedrock model invocation logging enabled for future diagnosis
- **Fix 6** (Done): Filtered `{FULL_PLAN}` per agent in system prompts — insufficient alone, plan still leaked through user messages
- **Fix 8** (Done): Single-channel plan distribution — removed full plan from user messages; plan flows only via system prompts. Verified in 2 consecutive runs: Coder violations eliminated, 25% fewer total tokens

**Remaining:** Fix 1 (stream keepalive), Fix 2 (TTFT logging), Fix 4 (Bedrock read_timeout), Fix 7 (tool-level guardrails) — resilience improvements, not blockers

---

## Summary

A complex analysis job (`3c784714`) completed all 7 analysis steps, 7 charts, and 19/19 validation checks successfully, then failed before DOCX report generation could begin. The Supervisor agent's `ConverseStream` call to Bedrock Sonnet stalled for ~15 minutes with zero response, causing the AgentCore→Web UI SSE stream to go idle and the web UI to receive `IncompleteRead(0 bytes read)`.

The Reporter agent was never invoked. The Supervisor was still deciding to call it when the Bedrock API went silent.

## Timeline (UTC)

| Time | Event |
|------|-------|
| 05:52:25 | Web UI receives analyze request, invokes AgentCore |
| 05:52:51 | Runtime starts: Coordinator → Planner |
| 05:53:29 | Plan generated (Sonnet) |
| 05:54:22 | User approves plan (HITL) |
| 05:54:22 | Supervisor starts, dispatches Coder agent |
| 05:54:52 | Fargate container created, data synced |
| 05:56:16–06:04:08 | Coder executes 7 analysis steps + 7 charts (32 executions, all successful) |
| 06:05:02 | Validator passes 19/19 checks |
| 06:05:07 | Supervisor's tool call: `pip show python-docx` → 200 OK (execution #36) |
| 06:05:10 | **Supervisor makes `ConverseStream` call** to Sonnet (CloudTrail: `requestID=dbbd73c4`, routed to **us-east-2**) |
| 06:05:10 | **Last activity — 15 min silence begins** |
| 06:05:10–06:20:04 | CloudTrail: **zero** Bedrock API calls |
| 06:05:10–06:20:04 | OTel observability: **zero** events |
| 06:05:10–06:20:04 | AgentCore runtime logs: **zero** entries |
| 06:05:10–06:20:04 | Fargate container: only health checks, no `/execute` requests |
| 06:20:04 | `WARNING:strands.multiagent.graph:remaining_task_count=<1> \| cancelling remaining tasks` |
| 06:20:04 | Web UI: `ERROR: IncompleteRead(0 bytes read)` |
| 06:20:04 | Job marked as failed, SNS notification sent |

## Root Cause

### Primary: Supervisor's Bedrock ConverseStream call stalled silently

The Supervisor agent received the `pip show python-docx` tool result at 06:05:07 and made its next `ConverseStream` call at **06:05:10** to decide what to do next (call the Reporter tool). This call **never returned**.

CloudTrail evidence:

| Field | Value |
|-------|-------|
| EventName | `ConverseStream` |
| Time | 06:05:10 UTC |
| Model | `global.anthropic.claude-sonnet-4-6` |
| inferenceRegion | **us-east-2** (cross-region routing) |
| maxTokens | 64,000 |
| requestID | `dbbd73c4-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| Error | (none) |
| Source IP | 10.0.x.x (AgentCore runtime in VPC) |

After this call, CloudTrail records **zero** Bedrock API calls until the job was cancelled at 06:20:04. The `ConverseStream` request was accepted by Bedrock but the response stream never materialized.

The Reporter agent was never invoked. This was the **Coder agent's** `ConverseStream` call — see "Coder Prompt Violation" section below.

### Contributing: Coder agent prompt violation — attempted DOCX generation

The Coder agent's prompt explicitly prohibits DOCX creation:

> `CRITICAL: You must NEVER create .docx, .pdf, or any report/document files.` (coder.md line 11)
> `⛔ NEVER create .docx or .pdf files (Reporter agent's responsibility)` (coder.md line 180)

Despite this, the Coder:
1. **Ran validation** directly (writing and executing `validator_verify.py`) instead of returning control to the Supervisor to dispatch the Validator agent
2. **Declared intent to create DOCX**: LLM output text "모든 수치가 100% 검증되었습니다. 이제 최종 DOCX 보고서를 작성합니다." ("All numbers verified 100%. Now creating the final DOCX report.")
3. **Prepared for DOCX creation**: Called `pip show python-docx` to check if the library is installed

**Evidence (OTel span at 06:05:07, scope=botocore.bedrock-runtime):**
```json
{"content": [
  {"text": "모든 수치가 100% 검증되었습니다. 이제 최종 DOCX 보고서를 작성합니다."},
  {"toolUse": {"name": "custom_interpreter_bash_tool",
               "input": {"cmd": "pip show python-docx 2>/dev/null | head -3 || pip install python-docx -q"}}}
]}
```

**What we cannot confirm:** Whether the stalled `ConverseStream` call (06:05:10) was actually generating DOCX code — the Bedrock response never arrived, so we don't know what the LLM was producing. The Coder declared intent and took a preparatory step, but the actual DOCX code generation cannot be proven.

**Impact of the violation:** By running analysis, charts, validation, AND attempting DOCX generation in one continuous session, the Coder accumulated ~36 tool calls of conversation context (~12K+ tokens). This bloated context may have contributed to the `ConverseStream` stall — a smaller, focused context (as designed) would have been less likely to trigger the issue.

### Contributing: No stream keepalive mechanism

The streaming architecture has no heartbeat/keepalive when the underlying LLM call produces no events:

```
agentcore_runtime.py → StreamableGraph.stream_async() → polls event_queue every 5ms
                                                          ↑
                                                     queue is EMPTY because
                                                     Supervisor's Bedrock call
                                                     sends nothing
```

The `stream_async()` poll loop runs correctly (tools execute in separate threads via `asyncio.to_thread()`, so the main event loop is NOT blocked), but yields nothing because the queue is empty.

### Contributing: AgentCore idleRuntimeSessionTimeout = 900s

The runtime's `lifecycleConfiguration.idleRuntimeSessionTimeout` is set to 900 seconds (15 minutes), which exactly matches the gap duration. The AgentCore service interpreted the idle SSE stream as an idle session and terminated it.

## CloudWatch Log Analysis

Searched all 4 log groups across a 48-hour window:

| Log Group | Socket/Timeout/Error matches |
|-----------|------------------------------|
| `/ecs/deep-insight-web` | 0 |
| `/aws/bedrock-agentcore/runtimes/...-DEFAULT` | 0 |
| `/ecs/deep-insight-fargate-prod` | 0 (only health checks during gap) |
| `bedrock-agentcore-observability` | 0 (only OTel spans, no errors) |

The only error logged anywhere:
```
[06:20:04] ERROR:__main__:AgentCore invocation error: An error occurred while reading
from response stream: ('Connection broken: IncompleteRead(0 bytes read)',
IncompleteRead(0 bytes read))
```

## CloudTrail Analysis

All Bedrock API calls in the 06:04–06:21 window:

| Time | Event | Model | Cross-Region |
|------|-------|-------|-------------|
| 06:04:11 | ConverseStream | Sonnet | — |
| 06:04:15 | ConverseStream | Sonnet | — |
| 06:05:05 | ConverseStream | Sonnet | — |
| 06:05:10 | ConverseStream | Sonnet | **us-east-2** |
| 06:06–06:20 | **(none)** | — | — |

The 06:05:10 call was the last. It was cross-region routed to us-east-2. No error was returned. No subsequent Bedrock calls were made for 15 minutes.

## Architecture Context

### Event flow (working correctly when events exist)

```
Supervisor tool call (worker thread via asyncio.to_thread)
  → asyncio.run() creates new event loop on worker thread
    → agent.stream_async() → Bedrock ConverseStream API
      → streaming tokens → _convert_to_agentcore_event()
        → put_event() into global deque (thread-safe)

Main event loop (NOT blocked):
  → StreamableGraph.stream_async() polls deque every 5ms
    → agentcore_runtime.py yields if type in STREAM_EVENT_TYPES
      → BedrockAgentCoreApp → SSE to web UI
```

### Why the main event loop is NOT blocked

Strands SDK `PythonAgentTool.stream()` dispatches sync tool functions via `asyncio.to_thread()` (confirmed in `strands/tools/tools.py:226`). The tool's `asyncio.run()` creates a separate event loop on the worker thread. The main event loop remains free to poll the event queue — and free to emit keepalives if implemented.

### Why events don't flow

Events don't flow because they don't exist. The Bedrock `ConverseStream` API accepted the request but sent zero response bytes. The event plumbing is correct; the upstream source is silent.

## Fixes

### Fix 1: Stream keepalive (recommended, immediate)

Add a keepalive producer in `agentcore_runtime.py` that emits an empty `agent_text_stream` event every 60 seconds when no real events are yielded. Since the main event loop is not blocked, this works regardless of what's happening in tool threads.

**Location**: `agentcore_runtime.py` lines 665-676 (streaming loop)
**Approach**: Two concurrent `asyncio` producers feeding a merged queue — one reads graph events, one emits keepalives. The main loop consumes from the queue.

### Fix 2: Bedrock call duration logging (observability)

Add timing around LLM calls to detect stalled Bedrock connections. Log elapsed time between `ConverseStream` request and first streaming token. Alert when TTFT exceeds a threshold (e.g., 120s).

**Location**: `src/utils/strands_sdk_utils.py` — `_retry_agent_streaming()` and `process_streaming_response_yield()`

### Fix 3: Increase idleRuntimeSessionTimeout (investigate)

Current: 900s. Available via `UpdateAgentRuntime` API → `lifecycleConfiguration.idleRuntimeSessionTimeout`. Increasing may help as a safety net, but does not address the underlying stalled Bedrock connection.

### Fix 4: Add Bedrock call timeout (defense in depth)

Add a `read_timeout` to the Bedrock client config used by the Supervisor/Reporter agents so that stalled `ConverseStream` calls fail fast (e.g., 300s) instead of hanging for 15 minutes. Combined with the existing retry logic, this would allow the system to retry instead of silently dying.

### Fix 5: Enable Bedrock model invocation logging (applied 2026-03-17)

**Status: Done**

Model invocation logging was not enabled at the time of the incident, so we could not see the actual prompt/response for the stalled `ConverseStream` call. This has now been enabled.

**What was created:**

| Resource | Value |
|----------|-------|
| IAM Role | `bedrock-invocation-logging-role` |
| CloudWatch Log Group | `/aws/bedrock/model-invocation-logs` (30-day retention) |
| S3 (full prompts/responses) | `s3://<S3_BUCKET>/bedrock-invocation-logs/` |
| Text data delivery | Enabled |
| Image/embedding delivery | Disabled |

**How to use for future incidents:**

```bash
# Check CloudWatch for metadata (latency, tokens, errors)
aws logs filter-log-events \
  --log-group-name "/aws/bedrock/model-invocation-logs" \
  --region us-west-2 \
  --start-time <epoch_ms> --end-time <epoch_ms> \
  --filter-pattern "ConverseStream"

# Check S3 for full prompt/response text (large payloads delivered here)
aws s3 ls s3://<S3_BUCKET>/bedrock-invocation-logs/ --recursive
```

**Note:** This logs every Bedrock call in the account/region (us-west-2), not just Deep Insight. CloudWatch retention is set to 30 days to manage costs.

## Impact

- 1 failed job (all analysis work lost despite successful completion)
- ~28 minutes of compute time wasted (Fargate container + AgentCore runtime)
- Bedrock token costs for Coder/Validator/Supervisor were consumed but produced no final report

## Lessons Learned

1. **Long-running SSE streams need keepalives.** Any architecture where an upstream API call can go silent for minutes needs a heartbeat mechanism to prevent intermediate proxies/services from killing the connection.
2. **Silent failures are the worst failures.** Zero errors in any log group made this hard to diagnose. The Bedrock API stall produced no exception, no timeout, no socket error — just silence.
3. **Observe the gap, not the error.** The `IncompleteRead` error was a symptom. The real signal was the 15-minute gap between the last event (06:05:07) and the cancellation (06:20:04) — visible only by correlating logs across all 4 CloudWatch log groups.
4. **Cross-region routing adds risk.** The stalled call was routed to us-east-2 via global inference. Cross-region Bedrock calls may have different latency/reliability characteristics. Consider monitoring TTFT by inference region.
5. **CloudTrail reveals what logs cannot.** Runtime logs, OTel spans, and CloudWatch all showed nothing during the gap. Only CloudTrail confirmed that the Bedrock API call was made at 06:05:10 and that no subsequent calls followed — proving the stall was in the Bedrock response, not in the application.
6. **Agent prompt violations compound infrastructure failures.** The Coder doing validation + DOCX prep (violating its prompt) bloated its conversation context to ~36 tool calls. If the agent hierarchy had been followed (Coder → Supervisor → Validator → Supervisor → Reporter), each agent would have had a smaller, focused context, reducing the risk of a stalled Bedrock call. Prompt adherence is not just about correctness — it's a reliability concern.

## Next Steps (scheduled 2026-03-18) — Updated 2026-03-20

| Item | Status |
|------|--------|
| Re-run the same job | **Done** — 3 re-runs completed. Bedrock stall not reproduced. |
| Strengthen Coder prompt | **Done** — Fix 6 (system prompt filtering) + Fix 8 (single-channel plan distribution). Verified in 2 consecutive clean runs. |
| Apply stream keepalive (Fix 1) | Pending — resilience improvement, not a blocker |

---

## Follow-Up: Re-Run Results (2026-03-20)

### Re-Run Summary

Job `4c86fb44` was submitted on 2026-03-20 at 01:12:30 UTC using the same dataset (Moon Market KR fresh food sales) and a similar query. The job **completed successfully** in ~28 minutes.

| Phase | Time (UTC) | Duration | Status |
|-------|-----------|----------|--------|
| Request → Plan | 01:12:30 → 01:13:29 | ~1 min | Plan generated |
| HITL Approval | 01:13:39 | — | Approved |
| Coder (analysis) | 01:15:46 → 01:26:43 | ~11 min | 7 analysis steps, 8 charts |
| Validator | 01:27:11 → 01:31:51 | ~5 min | **15/15 PASS** (100%) |
| Reporter (DOCX) | 01:33:49 → 01:39:25 | ~5.5 min | 8 report sections, 76 total executions |
| S3 Upload + Cleanup | 01:40:17 → 01:40:39 | ~22 sec | Fargate container deleted |
| **Total** | 01:12:30 → 01:40:39 | **~28 min** | **SUCCESS** |

**Bedrock stall did NOT reproduce.** 59 ConverseStream calls were made with no gaps longer than 227 seconds (which was confirmed as Fargate code execution time, not a Bedrock stall). Cross-region routing included both ap-southeast-4 and us-east-2 — both responded normally.

**Agent hierarchy worked correctly at the Supervisor level.** The Supervisor properly dispatched Coder → Validator → Reporter in sequence. The Reporter agent generated `final_report.docx`, `final_report_with_citations.docx` (37 citations, 15 unique, 8 embedded images), and `비즈니스_성장_기회_발굴_전략_보고서.docx`.

### Invocation Log Analysis

Bedrock model invocation logging (Fix 5, enabled 2026-03-17) captured 59 entries for this job. Large prompts (>~30K tokens) were offloaded to S3 (`inputBodyS3Path`), with only metadata in CloudWatch. This confirmed:

- All Bedrock calls received responses — no silent stalls
- The `input: 358 chars` entries in CloudWatch are S3 pointers, not small prompts
- Actual Coder context grew from 31K chars (call #4) to 130K chars (call #51)

### Critical Finding: Coder Prompt Violation Persists

**The Coder violated its DOCX prohibition again in this run — identically to the incident.**

S3-offloaded invocation logs (`/bedrock-invocation-logs/large/`) reveal the Coder's conversation at msg[23]–msg[28]:

| msg | Coder Action | Violation |
|-----|-------------|-----------|
| msg[23] | Wrote + ran `validator_verification.py` | YES — Validator's job |
| msg[25] | "모든 지표 100% 검증 통과! 이제 Reporter 단계로 최종 DOCX 보고서를 생성합니다." + `pip install python-docx` | YES — Reporter's job |
| msg[27] | Wrote + ran `reporter_docx.py` (926 lines, 47KB) | YES — Reporter's job |
| msg[28] | **Succeeded**: `비즈니스_성장_기회_발굴_전략_보고서.docx` (840KB) | — |

The job succeeded because: (1) Bedrock didn't stall this time, and (2) the Supervisor still dispatched the real Validator and Reporter agents afterward, whose outputs overwrote the Coder's rogue artifacts.

### Root Cause: Why the Coder Prompt Prohibition Fails

Investigation of the actual Bedrock invocation payloads (system prompt + messages) reveals a **structural conflict** between the prohibition and the injected plan.

**The FULL_PLAN contains all 3 agent steps — including the Reporter's DOCX task.**

The Coder's system prompt (`coder.md` line 4: `FULL_PLAN: {FULL_PLAN}`) injects the complete plan generated by the Planner, which includes:

> ### 3. Reporter: 비즈니스 성장 전략 종합 보고서 작성
> - [ ] 전문적인 비즈니스 보고서 형식의 **DOCX 파일 생성**

This "create DOCX" task instruction appears **twice** in the Coder's context:
1. In the **system prompt** (via `FULL_PLAN` template variable)
2. In the **first user message** (plan repeated verbatim)

The prohibition ("CRITICAL: You must NEVER create .docx") occupies ~3 sentences across 362 lines (<1% of prompt). The "create DOCX" task is a concrete, actionable checklist item that the LLM is trained to complete.

**Contributing factors:**

| Factor | Detail |
|--------|--------|
| Prohibition is <1% of prompt | 3 sentences across 14K chars — easily drowned out |
| "Create DOCX" is a visible task | Plan checkboxes (`- [ ]`) read as actionable work |
| Task completion pressure | Success criteria: "All Coder tasks from FULL_PLAN executed" |
| Context length decay | By msg[25] (~43K tokens), the prohibition is far from attention window |
| Concrete > abstract | "Create DOCX file" (task) overrides "NEVER create DOCX" (constraint) |

**The prompt-level prohibition approach is fundamentally insufficient.** No amount of "CRITICAL" or "NEVER" wording reliably overrides a visible task instruction at 30K+ tokens distance.

### Updated Fix Recommendations

#### Fix 6: Filter FULL_PLAN per agent (system prompt only — insufficient alone)

**Status: Done** (2026-03-20) — but **insufficient**: see "Second Re-Run (2026-03-20)" below

Only inject the agent-relevant steps into each agent's system prompt — not the full plan. The Coder no longer sees the Reporter's "create DOCX" task. Other agents' steps are replaced with `(handled by X agent)` to preserve workflow awareness without exposing task details.

**What was changed:**

| File | Change |
|------|--------|
| `src/prompts/template.py` | Added `filter_plan_for_agent(full_plan, agent_name)` — splits plan by `### N. AgentName:` headers, keeps only the matching agent's tasks, replaces others with `(handled by X agent)` |
| `src/tools/coder_agent_custom_interpreter_tool.py` | `FULL_PLAN` filtered to Coder-only before injection |
| `src/tools/validator_agent_custom_interpreter_tool.py` | `FULL_PLAN` filtered to Validator-only before injection |
| `src/tools/reporter_agent_custom_interpreter_tool.py` | `FULL_PLAN` filtered to Reporter-only before injection |
| `src/tools/tracker_agent_tool.py` | No change — Tracker needs full plan to track all agents |

**Effect on Coder's system prompt:**

Before (5 `docx` mentions — 1 task instruction + 4 prohibitions):
```
### 3. Reporter: 비즈니스 성장 전략 종합 보고서 작성
- [ ] 전문적인 비즈니스 보고서 형식의 DOCX 파일 생성   ← Coder saw this
```

After (4 `docx` mentions — 0 task instructions + 4 prohibitions):
```
### 3. Reporter: 비즈니스 성장 전략 종합 보고서 작성
(handled by Reporter agent)
```

#### Fix 7: Tool-level guardrail for file types (defense in depth)

Add a check in `custom_interpreter_write_and_execute_tool` and `custom_interpreter_bash_tool` that rejects execution when the Coder agent attempts to:
- Write files matching `*.docx` or `*.pdf`
- Run `pip install python-docx`
- Write files with `reporter` in the filename

This catches violations even if the LLM ignores prompt instructions.

#### Previously recommended fixes (still valid)

| Fix | Purpose | Status |
|-----|---------|--------|
| Fix 1: Stream keepalive | Heartbeat every 60s to prevent idle timeout | Pending |
| Fix 2: Bedrock call duration logging | TTFT monitoring | Pending |
| Fix 3: Increase idleRuntimeSessionTimeout | Safety net | Investigate |
| Fix 4: Bedrock call timeout (`read_timeout`) | Fail fast on stalls | Pending |
| Fix 5: Model invocation logging | Full prompt/response capture | **Done** (2026-03-17) |
| Fix 6: Filter FULL_PLAN per agent (system prompt) | Remove cross-agent task visibility in system prompt | **Done** (2026-03-20) — insufficient alone |
| Fix 7: Tool-level guardrail for file types | Block Coder from writing .docx | Pending (defense in depth) |
| Fix 8: Single-channel plan distribution | Remove full plan from user messages; plan flows only via system prompt | **Done** (2026-03-20) — **resolved the violation** |

---

## Follow-Up: Second Re-Run Results (2026-03-20, Fix 6 Verification)

### Re-Run Summary

Job `18dfc6c1` was submitted on 2026-03-20 at 05:01:29 UTC with Fix 6 deployed (runtime redeployed at 04:52:48 UTC, confirmed READY at 04:53:02 UTC). The job **completed successfully** in ~28 minutes — but **Fix 6 did not prevent the Coder's DOCX violation**.

| Phase | Time (UTC) | Duration | Executions | Status |
|-------|-----------|----------|------------|--------|
| Coordinator | 05:01:29–05:01:32 | 3s | — | Routed to Planner |
| Planner | 05:01:32–05:02:09 | 37s | — | Plan generated (Sonnet) |
| HITL Approval | 05:02:15 | 6s (3 polls) | — | Approved |
| Coder | 05:02:39–05:16:35 | ~14 min | 31 | **Violated prompt** — see below |
| Tracker (1st) | 05:16:46 | 11s | — | Progress updated |
| Validator | 05:16:09–05:21:01 | ~5 min | 28 | 20/20 PASS (100%) |
| Tracker (2nd) | 05:21:09 | 27s | — | Progress updated |
| Reporter | 05:22:33–05:28:37 | ~6 min | 28 | DOCX generated |
| Tracker (3rd) | 05:28:47 | 26s | — | Progress updated |
| S3 Upload + Cleanup | 05:29:28–05:29:48 | 20s | — | Fargate container deleted |
| **Total** | 05:01:29–05:29:48 | **~28 min** | 87 | **SUCCESS** |

**Tokens**: 1.84M total (985K regular input, 584K cache read, 47K cache write, 115K output)

**Bedrock stall did NOT reproduce.** No gaps longer than normal Fargate execution time.

### Coder Prompt Violation: Identical to Previous Runs

The Coder violated its prompt in the **exact same pattern** as the original incident and the first re-run, despite Fix 6 filtering the `{FULL_PLAN}` template in the system prompt:

| Exec # | Coder Action | Violation |
|--------|-------------|-----------|
| 24–25 | Wrote + ran `validator_check.py` (failed) | YES — Validator's job |
| 26–27 | Wrote + ran `validator_save.py` → 25/25 PASS, 15 citations | YES — Validator's job |
| 28 | `pip show python-docx` + `pip show Pillow` | YES — DOCX prep |
| 29–30 | Wrote + ran `reporter_create_report.py` (831 lines, 37KB) | YES — Reporter's job |
| 30 | Created `비즈니스_성장기회_발굴_보고서.docx` (1.3MB) | YES — Reporter's job |
| 31 | `ls -la ./artifacts/*.docx` (verified creation) | — |

The job succeeded because the Supervisor still dispatched the real Validator and Reporter agents afterward, whose outputs overwrote the Coder's rogue artifacts.

### Root Cause: Why Fix 6 Was Insufficient

Fix 6 filtered the `{FULL_PLAN}` template variable injected into agent **system prompts**. However, the full plan reaches the Coder through a **second, unfiltered channel**: the user message constructed from `shared_state["messages"]`.

#### Actual runtime evidence (Bedrock model invocation logs, job `18dfc6c1`)

The Supervisor's first `ConverseStream` call (05:02:15 UTC) was captured via Bedrock model invocation logging. The actual input sent to Bedrock:

**System prompt** (9,851 chars): The `supervisor.md` template — contains role, behavior, instructions, tool guidance, workflow rules. **No plan.** The Supervisor's system prompt has no `{FULL_PLAN}` template variable, so the plan is not in the system prompt.

**User message** (4,781 chars): Built at `nodes.py:474`. Contains the **full plan TWICE** with zero filtering:

```
[PART 1: messages[-1] = Planner's raw output, 2,364 chars]
# Plan
## thought
사용자가 데이터 기반 비즈니스 성장 기회 발굴을 요청했습니다...
워크플로우: **Coder → Validator → Reporter**
## steps
### 1. Coder: 고객·매출 데이터 종합 분석 및 성장 기회 발굴
- [ ] 데이터 탐색 ...
- [ ] 고객 세그먼트 분석 ...
### 2. Validator: 핵심 수치 검증 ...
### 3. Reporter: 비즈니스 성장 전략 종합 보고서 작성
- [ ] 전문적인 비즈니스 보고서 형식의 DOCX 파일 생성    ← FULL PLAN, all 3 agents

[PART 2: FULL_PLAN_FORMAT = same plan again in <full_plan> tags, 2,366 chars]
<full_plan>
# Plan
... (identical content repeated)
### 3. Reporter: ... DOCX 파일 생성                      ← same plan, AGAIN
</full_plan>
*Please consider this to select the next step.*

[PART 3: clues = empty at this point]
```

The user's original request (`request_prompt`: "데이터에서 비즈니스 성장 기회를 발굴해줘...") is **absent** from the user message — it was overwritten by the Planner's output at `nodes.py:293`.

This same `shared_state["messages"]` (containing the full plan) is later read by the Coder tool at line 123 of `coder_agent_custom_interpreter_tool.py`, where it becomes the Coder's user message — delivering the unfiltered plan with Reporter's "create DOCX" task directly to the Coder agent.

#### Data flow analysis (code trace)

**Step 1: Planner stores plan in TWO shared state keys (line 293–294 of `nodes.py`)**

```python
# After Planner completes:
shared_state['messages'] = [get_message_from_string(role="user", string=response["text"], imgs=[])]
shared_state['full_plan'] = response["text"]
```

Both `shared_state["messages"]` and `shared_state["full_plan"]` contain the **same content** — the Planner's raw output, which is the full plan with all 3 agent sections (Coder, Validator, Reporter including "create DOCX").

**Step 2: Supervisor constructs its user message with the full plan TWICE (line 473–474)**

```python
clues, full_plan, messages = shared_state.get("clues", ""), shared_state.get("full_plan", ""), shared_state["messages"]
message_text = '\n\n'.join([messages[-1]["content"][-1]["text"], FULL_PLAN_FORMAT.format(full_plan), clues])
```

The Supervisor's input message contains:
1. `messages[-1]` — the Planner's raw output (the plan, unfiltered)
2. `FULL_PLAN_FORMAT.format(full_plan)` — the plan again in `<full_plan>` tags (unfiltered)

**Step 3: Coder reads shared state and constructs its user message (lines 86–87, 123 of `coder_agent_custom_interpreter_tool.py`)**

```python
request_prompt, full_plan = shared_state.get("request_prompt", ""), shared_state.get("full_plan", "")
clues, messages = shared_state.get("clues", ""), shared_state.get("messages", [])

# Fix 6 filters the system prompt correctly:
coder_plan = filter_plan_for_agent(full_plan, "coder")  # ✅ Filtered
system_prompts = apply_prompt_template(prompt_name="coder", prompt_context={"FULL_PLAN": coder_plan})

# But the user message is built from messages[-1], which is the Planner's unfiltered output:
message = '\n\n'.join([messages[-1]["content"][-1]["text"], clues])  # ❌ Contains full plan
```

#### Two-channel architecture flaw

The plan flows to the Coder through **two independent channels**:

```
shared_state["full_plan"]                    shared_state["messages"]
(Planner's raw output)                       (Planner's raw output as user message)
        │                                            │
        ▼                                            ▼
filter_plan_for_agent("coder")               messages[-1]["content"][-1]["text"]
        │                                            │
        ▼                                            ▼
SYSTEM PROMPT: {FULL_PLAN}                   USER MESSAGE: message variable
(Filtered — Coder sees only                  (UNFILTERED — Coder sees all 3
its own tasks) ✅                             agent sections including Reporter's
                                              "create DOCX" task) ❌
```

Fix 6 patched Channel 1 (system prompt) but left Channel 2 (user message) unfiltered. The Coder's system prompt says `(handled by Reporter agent)` for the Reporter section, but the user message contains the full plan text with `### 3. Reporter: ... DOCX 파일 생성`.

**The LLM follows the concrete task instruction in the user message over the abstract prohibition in the system prompt.** This is the same "concrete > abstract" dynamic identified in the first re-run analysis, but the mechanism is different — it's not plan visibility in the system prompt (Fix 6 addressed that), it's plan visibility in the user message (a separate channel).

#### Clues accumulation: a third plan leak vector

Examination of the actual clues content at each stage (from Bedrock model invocation logs) reveals how plan information propagates through the clues mechanism:

**Stage 1: Supervisor → Coder (05:02:39 UTC)**

```
clues = ""  (empty — no prior agents have run)
```

No leak risk at this stage. The Coder's first invocation receives empty clues.

**Stage 2: Supervisor → Tracker (after Coder, 05:16:46 UTC)**

```
clues = "Here is clues from coder:\n<clues>\n{Coder's 2,434-char summary}\n</clues>"
```

Contains analysis results, key findings, segment stats. No plan text.

**Stage 3: Supervisor → Validator (after Tracker, ~05:16:50 UTC)**

The Tracker's output is an **updated copy of the full plan** with `[x]` checkmarks — including the Reporter section:

```
clues = [coder clues] +
  "Here is updated tracking status:\n<tracking_clues>\n
  # Plan
  ...
  ### 1. Coder: ... [x] all tasks
  ### 2. Validator: ... [ ] all tasks
  ### 3. Reporter: 비즈니스 성장 기회 발굴 종합 보고서 작성
  - [ ] DOCX 보고서 생성: 한국어 전문 보고서로 작성    ← FULL PLAN IN CLUES
  \n</tracking_clues>"
```

**The Tracker's output embeds the full plan (with Reporter's DOCX task) into clues**, which is then passed to all subsequent agents. This is a **third leak vector** — separate from both the system prompt (Channel 1) and `shared_state["messages"]` (Channel 2).

**Impact assessment:** This third vector does NOT affect the Coder's DOCX violation, because the Tracker runs *after* the Coder. The Coder receives empty clues on its first (and typically only) invocation. However, if the Supervisor were to call the Coder a second time (e.g., to fix errors), the Coder would receive clues containing the full plan from the Tracker's output.

For the Validator and Reporter agents, the clues vector is not a concern — they are supposed to know about the full workflow. But it is worth noting as a general architectural observation: **the Tracker broadcasts the full plan into clues**, which undermines per-agent plan filtering for any agent called after the first Tracker update.

### Updated Fix Recommendations

#### Fix 8: Single-channel plan distribution (architectural fix)

**Status: Done** (2026-03-20)

Remove the full plan from user messages entirely. The plan flows to each agent through **one controlled channel only** — the system prompt, where `filter_plan_for_agent()` already applies per-agent filtering.

**What was changed:**

| File | Change |
|------|--------|
| `src/prompts/supervisor.md` | Added `FULL_PLAN: {FULL_PLAN}` to frontmatter; added `<full_plan>{FULL_PLAN}</full_plan>` in instructions section — Supervisor now receives the full plan via system prompt |
| `src/graph/nodes.py:464–480` | Moved shared state read before agent creation; passed `{"FULL_PLAN": full_plan}` to supervisor prompt context; replaced user message with `request_prompt` + clues only (removed `FULL_PLAN_FORMAT`) |
| `src/graph/nodes.py:293` | Changed `shared_state['messages']` from storing `response["text"]` (the full plan) to storing `shared_state.get("request_prompt", "")` (the user's original request) — prevents plan from leaking to downstream agents |

**Architectural principle:** Each agent receives its plan **only** via its system prompt `{FULL_PLAN}` template, which is filtered per agent by `filter_plan_for_agent()`. User messages carry only the task context (user request, clues from prior agents) — never the plan itself.

**Effect on channels:**

```
Before (two channels, one unfiltered):
  System prompt {FULL_PLAN}: filtered ✅
  User message messages[-1]: UNFILTERED ❌

After (single channel, filtered):
  System prompt {FULL_PLAN}: filtered ✅
  User message: user request + clues only (no plan) ✅
```

#### Fix 7: Tool-level guardrail for file types (defense in depth)

**Status: Pending** (still valid, complementary to Fix 8)

Even with Fix 8, the Coder might infer DOCX generation from context (installed packages, analysis workflow patterns). Fix 7 adds a hard block at the tool execution layer as defense in depth.

### Lessons Learned (Updated)

7. **Prompts have multiple input channels.** An LLM agent's behavior is shaped by both its system prompt AND user messages. Filtering one channel (system prompt) while leaving another (user message) unfiltered creates a contradiction that the LLM resolves by following the more concrete instruction. Prompt hygiene must be applied consistently across all channels.
8. **Shared state is a broadcast medium.** When `shared_state["messages"]` is written by one agent (Planner) and read by all downstream agents (Supervisor, Coder, Validator, Reporter), any information in it — including the full plan — leaks to all consumers. Shared state keys that carry plan information must be filtered at the point of consumption, or the plan must be removed from shared state messages entirely.
9. **Fix the prompt before adding guardrails.** The prompt is the primary instruction that drives agent behavior and tool usage. Tool-level guardrails (Fix 7) are defense in depth, but the correct first step is ensuring the prompt itself is consistent and contradiction-free across all channels (Fix 8). A well-instructed agent shouldn't need guardrails for normal operation.

---

## Follow-Up: Third Re-Run Results (2026-03-20, Fix 8 Verification)

### Re-Run Summary

Job `bc403566` was submitted on 2026-03-20 at 08:18:49 UTC with Fix 8 deployed (runtime redeployed at ~08:10 UTC). The job **completed successfully** and **Fix 8 eliminated the Coder's DOCX violation**.

| Phase | Time (UTC) | Duration | Executions | Status |
|-------|-----------|----------|------------|--------|
| Coordinator | 08:18:49–08:18:53 | 4s | — | Routed to Planner |
| Planner | 08:18:53–08:19:42 | 49s | — | Plan generated (Sonnet) |
| HITL Approval | 08:19:48 | 6s (3 polls) | — | Approved |
| Coder | 08:22:54–08:32:01 | ~9 min | 25 | **No violations** |
| Tracker (1st) | 08:32:21 | 38s | — | Progress updated |
| Validator | 08:33:52–08:36:59 | ~3 min | — | Verified |
| Tracker (2nd) | 08:37:25 | 34s | — | Progress updated |
| Reporter | 08:38:51–08:46:34 | ~8 min | — | DOCX generated |
| Tracker (3rd) | 08:46:34 | — | — | Progress updated |
| S3 Upload + Cleanup | — | — | — | Fargate container deleted |
| **Total** | 08:18:49–08:46:34 | **~28 min** | — | **SUCCESS** |

**Tokens**: 1.37M total (774K regular input, 416K cache read, 80K cache write, 102K output)

### Fix 8 Verification: Coder DOCX Violation Eliminated

The Coder completed with **25 executions** and produced only its expected outputs:

- 9 charts (.png)
- `all_results.txt`
- `calculation_metadata.json`
- Code files: `coder_01_explore.py` through `coder_09_results.py`

**No violations observed:**
- No `validator_check.py` or `validator_save.py` (Validator's job)
- No `pip show python-docx` or `pip install python-docx` (DOCX prep)
- No `reporter_create_report.py` (Reporter's job)
- No `.docx` files created by the Coder
- The Coder's `ls -la ./artifacts/` output at exec #25 confirmed: only `.png`, `.json`, `.txt` files

The Supervisor correctly dispatched Coder → Tracker → Validator → Tracker → Reporter → Tracker in sequence.

### Comparison: Fix 6 (failed) vs Fix 8 (succeeded)

| Metric | Fix 6 only (job `18dfc6c1`) | **Fix 8 (job `bc403566`)** |
|--------|---------------------------|--------------------------|
| **Coder violations** | validator + pip show + 831-line DOCX | **None** |
| Coder executions | 31 | **25 (−19%)** |
| Coder tokens | 720K | **397K (−45%)** |
| Total tokens | 1.84M | **1.37M (−25%)** |
| Total duration | ~28 min | ~28 min |
| Coder produced `.docx` | YES (1.3MB) | **NO** |

The 45% reduction in Coder tokens and 25% reduction in total tokens are direct results of eliminating the Coder's wasted work (validation + DOCX generation that was subsequently overwritten by the real Validator and Reporter).

### Cache Hit Ratio Analysis

Moving the full plan from user message to system prompt affected caching behavior. The system prompt is stable across multi-turn tool calls and benefits from Bedrock's prompt caching, while user messages change every turn and cannot be cached.

**Supervisor cache comparison:**

| Metric | Fix 6 (plan in user msg) | Fix 8 (plan in system prompt) | Change |
|--------|------------------------|-------------------------------|--------|
| Regular Input | 98,578 | 184,965 | +88% |
| Cache Read | 9,837 | 30,124 | **+206%** |
| Cache Write | 13,116 | 22,593 | +72% |
| **Cache Hit Ratio** | **9.1%** | **14.0%** | **+4.9pp** |

The Supervisor's cache hit ratio improved from 9.1% → 14.0% because the plan is now in the system prompt (cached across all multi-turn tool calls) instead of the user message (changes every turn, not cacheable). The Supervisor used more total tokens (+88% regular input) because it now orchestrates the full workflow without the Coder doing redundant work, but more of those tokens hit cache at 90% discount.

**Overall cache comparison:**

| Metric | Fix 6 | Fix 8 | Change |
|--------|-------|-------|--------|
| Total tokens | 1.84M | 1.37M | −25% |
| Cache Read | 584K | 416K | −29% |
| Cache Read ratio | 37.2% | 35.0% | −2.2pp |

The overall cache read ratio decreased slightly (37.2% → 35.0%) because the Coder — which had the highest absolute cache read in the previous run (144K from its bloated 31-execution session) — now uses fewer tokens overall. The **net cost impact is strongly positive**: 25% fewer total tokens with similar cache efficiency means significantly lower Bedrock costs.

### Updated Fix Status

| Fix | Purpose | Status |
|-----|---------|--------|
| Fix 1: Stream keepalive | Heartbeat every 60s to prevent idle timeout | Pending |
| Fix 2: Bedrock call duration logging | TTFT monitoring | Pending |
| Fix 3: Increase idleRuntimeSessionTimeout | Safety net | Investigate |
| Fix 4: Bedrock call timeout (`read_timeout`) | Fail fast on stalls | Pending |
| Fix 5: Model invocation logging | Full prompt/response capture | **Done** (2026-03-17) |
| Fix 6: Filter FULL_PLAN per agent (system prompt) | Remove cross-agent task visibility in system prompt | **Done** (2026-03-20) — insufficient alone |
| Fix 7: Tool-level guardrail for file types | Block Coder from writing .docx | Pending (defense in depth) |
| Fix 8: Single-channel plan distribution | Remove full plan from user messages; plan flows only via system prompt | **Done** (2026-03-20) — **resolved the Coder DOCX violation** |
