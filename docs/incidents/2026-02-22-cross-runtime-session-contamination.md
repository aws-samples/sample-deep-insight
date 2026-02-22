# Incident: Cross-Runtime Session Contamination via ALB Failover

**Date**: 2026-02-22
**Severity**: High
**Affected**: Managed AgentCore (Fargate container sessions)
**Status**: Fixed and deployed

---

## Summary

Two concurrent AgentCore runtime invocations shared the same Fargate container due to ALB sticky session failover. One runtime's cleanup (`POST /session/complete`) killed the other's active session, causing all subsequent code executions to fail with HTTP 400.

## Timeline (UTC)

| Time | Event |
|------|-------|
| 06:35 | Runtime A starts, creates container at <IP-A> |
| 07:05 | Runtime B starts, creates container at <IP-B> |
| ~07:10 | Container <IP-A> (Runtime A) becomes unhealthy |
| 07:10-07:19 | ALB silently reroutes Runtime A's requests to container <IP-B> |
| 07:19:30 | Runtime B completes execution 81 (last successful) |
| 07:22:08 | Runtime A sends executions 82-84 to Runtime B's container |
| 07:23:16 | Runtime A completes workflow, sends `POST /session/complete` through ALB |
| 07:23:16 | ALB routes the request to container <IP-B> (Runtime B's container) |
| 07:23:21 | Container <IP-B> marks `is_complete=True`, uploads to S3 |
| 07:23:33 | Runtime B tries execution 82 -> HTTP 400 "Session is already complete" |
| 07:23:33-07:39:13 | All Runtime B executions fail with HTTP 400 |

## Root Cause

Three contributing factors:

1. **No session-level authentication on container HTTP endpoints.** The `/session/complete` and `/execute` endpoints accepted requests from any source without verifying the session ID. Any request routed through the ALB could kill any session.

2. **ALB sticky session failover is silent.** When a sticky session target becomes unhealthy, the ALB routes requests to another healthy target without returning errors to the client. The caller has no way to detect the misrouting.

3. **Runtime continued operating on an unhealthy container.** When the coordinator detected its container was unhealthy via ALB health check, it logged warnings but continued sending requests. These requests were silently routed to a different container.

## Fixes Applied

### Fix 1: Session ID Validation (Primary Fix)

**Files**: `fargate-runtime/code_executor_server.py`, `src/tools/fargate_container_controller.py`

The client now sends `session_id` in every `/execute` and `/session/complete` request. The container rejects requests where the session ID doesn't match with HTTP 403.

- Container `/execute`: validates `session_id` field, returns 403 on mismatch
- Container `/session/complete`: validates `session_id` field, returns 403 on mismatch
- Client `execute_code()`: includes `session_id` in request body
- Client `complete_session()`: includes `session_id` in request body

The `session_id` field is optional for backward compatibility. Missing `session_id` is allowed; only mismatches are rejected.

### Fix 2: Health Check Reflects Session State

**File**: `fargate-runtime/code_executor_server.py`

The `/health` endpoint now returns HTTP 503 when `is_complete=True`. Previously it always returned 200 regardless of session state, keeping completed containers as valid ALB targets indefinitely.

The ALB health check Matcher (`HttpCode: 200`) treats 503 as unhealthy. After `UnhealthyThresholdCount` (3) consecutive 503 responses at 30-second intervals, the ALB stops routing traffic to the completed container.

### Fix 3: Error Message Includes Container Response

**File**: `src/tools/fargate_container_controller.py`

Non-200 responses from the container now include the actual error message in the exception. Previously, the error only showed the HTTP status code (e.g., "HTTP 400"), discarding the container's error detail.

Before: `FIXED CONTAINER NOT RESPONDING FAILED: HTTP 400 - TERMINATING ENTIRE WORKFLOW`
After: `FIXED CONTAINER NOT RESPONDING FAILED: HTTP 400 - Session is already complete - TERMINATING ENTIRE WORKFLOW`

### Fix 4 (No Code Change): Unhealthy Container Warning

Issue #2 (runtime continues on unhealthy container) is protected by Fix #1. When ALB misroutes requests to the wrong container, the container rejects them with 403. No additional code change needed — the existing warning-only behavior is correct for transient ALB health check flaps.

## Verification

Deployed to production on 2026-02-22. Test invocation completed successfully:
- Container health returns 503 after session completion (confirmed in logs)
- Session completion with matching session ID succeeds (HTTP 200)
- No cross-contamination observed

## Lessons Learned

1. **ALB sticky sessions are not a substitute for application-level session identity.** Sticky cookies can fail over silently, routing requests to unintended targets. Always validate session ownership at the application layer.

2. **Shared infrastructure (ALB) between concurrent sessions needs isolation guarantees.** Multiple runtimes sharing an ALB target group can interact through cookie failover in ways that are invisible to the caller.

3. **"Warning-only" for infrastructure anomalies delays detection.** The runtime logged 15+ warnings about an unhealthy container but continued operating, allowing the cross-contamination to occur. Warnings should have actionable follow-up, even if the action is "proceed with caution because Fix #1 provides a safety net."
