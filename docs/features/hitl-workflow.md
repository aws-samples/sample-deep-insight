# Human-in-the-Loop (HITL) Workflow

Human-in-the-Loop (HITL) allows users to review and steer the analysis plan before execution, giving control over the analysis direction.

## Overview

When enabled, the Planner agent generates an analysis plan and pauses for user review. Users can:

- **Approve** the plan to proceed with execution
- **Provide feedback** to revise the plan (up to 10 revisions by default)

This ensures the analysis aligns with user expectations before resource-intensive execution begins.

## Workflow

```
User Query
    ↓
Coordinator → Planner → PlanReviewer → Supervisor → Tool Agents
                 ↑            │
                 └────────────┘
              (revision loop)
```

1. **Coordinator** receives user query and routes to Planner
2. **Planner** generates detailed analysis plan
3. **PlanReviewer** displays plan and waits for user feedback
4. User **approves** → proceeds to Supervisor for execution
5. User **provides feedback** → returns to Planner for revision
6. Loop continues until approved or max revisions reached

## Implementation Differences

### Self-Hosted

Uses interactive terminal input:

```
============================================================
PLAN REVIEW (Revision 0/10)
============================================================

[Plan content displayed here]

============================================================

Please review the plan above.
  - Press Enter or type 'yes' to approve and proceed
  - Type your feedback to request revisions (10 revision(s) remaining)

Your response: _
```

- Direct `input()` prompt in terminal
- Synchronous blocking until user responds
- Best for local development and testing

### Managed AgentCore

Uses S3-based feedback mechanism for serverless environments:

```
Client                          Runtime (AgentCore)
  │                                    │
  │◄──── plan_review_request ─────────│  (SSE event with plan)
  │                                    │
  │      [User reviews plan]           │
  │                                    │
  │───── Upload feedback to S3 ───────►│  (s3://bucket/deep-insight/feedback/{request_id}.json)
  │                                    │
  │                                    │  (Runtime polls S3)
  │◄──── Continue execution ──────────│
```

**Feedback JSON format:**
```json
{
  "approved": true,
  "feedback": "optional revision notes",
  "timestamp": "2025-12-16T10:30:00"
}
```

**S3 path:** `s3://{S3_BUCKET_NAME}/deep-insight/feedback/{request_id}.json`

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_PLAN_REVISIONS` | `10` | Maximum plan revisions before auto-approval |
| `PLAN_FEEDBACK_TIMEOUT` | `300` | Timeout in seconds for feedback (managed only) |
| `PLAN_FEEDBACK_POLL_INTERVAL` | `3` | S3 polling interval in seconds (managed only) |
| `S3_BUCKET_NAME` | - | S3 bucket for feedback upload (managed only) |

### Setting in .env

```bash
# Self-hosted: self-hosted/.env
MAX_PLAN_REVISIONS=10

# Managed AgentCore: managed-agentcore/.env
MAX_PLAN_REVISIONS=10
PLAN_FEEDBACK_TIMEOUT=300
PLAN_FEEDBACK_POLL_INTERVAL=3
S3_BUCKET_NAME=your-bucket-name
```

## Auto-Approval Conditions

The plan is automatically approved when:

1. **Max revisions reached** - After 10 revisions (configurable)
2. **Timeout** - No feedback received within 300 seconds (managed only)
3. **Non-interactive mode** - EOFError detected (self-hosted only)

## User Interaction

### Approving a Plan

Any of these inputs approve the plan:
- Press `Enter` (empty input)
- Type `yes`, `y`, `approve`, `ok`, or `proceed`

### Requesting Revision

Type your feedback directly:

```
Your response: Please add monthly trend analysis and include competitor comparison
```

The Planner will regenerate the plan incorporating your feedback.

## Key Files

### Self-Hosted
- `self-hosted/src/graph/nodes.py` - `plan_reviewer_node()` function (line 232)
- `self-hosted/src/graph/builder.py` - Graph workflow with PlanReviewer node

### Managed AgentCore
- `managed-agentcore/src/graph/nodes.py` - `plan_reviewer_node()` with S3 polling (line 307)
- `managed-agentcore/02_invoke_agentcore_runtime_vpc.py` - Client-side feedback handling (line 177)
- `managed-agentcore/src/utils/s3_utils.py` - S3 feedback utilities

## Example Session

```
============================================================
PLAN REVIEW (Revision 0/10)
============================================================

# Sales Analysis Plan

## Phase 1: Data Loading and Exploration
- Load CSV data using pandas
- Examine data structure and types
- Identify key columns for analysis

## Phase 2: Sales Performance Analysis
- Calculate total sales by product category
- Analyze monthly sales trends
- Identify top-performing products

## Phase 3: Visualization
- Create bar charts for category comparison
- Generate time series plots for trends
- Build heatmaps for correlation analysis

## Phase 4: Report Generation
- Compile findings into DOCX report
- Include all visualizations
- Add executive summary

============================================================

Please review the plan above.
  - Press Enter or type 'yes' to approve and proceed
  - Type your feedback to request revisions (10 revision(s) remaining)

Your response: Add regional breakdown analysis

Revising plan based on user feedback (revision 1)...

============================================================
PLAN REVIEW (Revision 1/10)
============================================================

[Updated plan with regional breakdown analysis added]

Your response: yes

Plan approved! Proceeding with execution...
```

## Best Practices

1. **Be specific with feedback** - Clear instructions help the Planner generate better revisions
2. **Review early** - Catch issues before execution to save time and resources
3. **Use auto-approval wisely** - Set appropriate timeout values for your use case
4. **Monitor revisions** - If hitting max revisions frequently, consider improving initial prompts
