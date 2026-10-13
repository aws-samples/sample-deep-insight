# Deep Insight Ops — Deployment Guide

> Job tracking, email notifications, and admin dashboard for Deep Insight Web.

**Last Updated**: 2026-03

---

## Overview

Deep Insight Ops adds operational monitoring to the Web UI:

- **Job Tracking** — DynamoDB records every analysis job (status, tokens, duration)
- **Email Notifications** — SNS sends completion/failure emails to admins
- **Admin Dashboard** — Web-based dashboard with Cognito authentication
- **Agent Trace & Files** — per job: the order agents ran in, each agent's response, tool calls with their code and output, generated images and files, report re-download

All Ops resources are optional — the Web UI works normally without them.

### How a job's status and trace are recorded

```
Web UI /analyze ──► DynamoDB: Start
     │ payload: prompt, data_directory, job_id
     ▼
AgentCore Runtime
     ├─ after each agent invocation, and at the end:
     │    s3://…/deep-insight/traces/{job_id}/events.jsonl  ◄── dashboard reads the trace
     └─ at the end (success, error, client disconnect):
          s3://…/fargate_sessions/{session_id}/output/token_usage.json, job_status.json
                                                     │ S3 event
                                                     ▼
                         Lambda: update job by job_id ──► Success / Failed + SNS
EventBridge (15 min) ──► Lambda: Start with no sign of life ──► Failed
```

- **Trace**: the runtime records every agent event before the response stream's event filter, so tool calls (generated code, execution output) are included even though they are never streamed to the browser. It is keyed by `job_id`, which the dashboard knows from the start, and re-uploaded after each agent invocation: a running job shows the agents finished so far, and a runtime that dies mid-run still leaves the trace up to its last finished agent. Plan reviews (HITL) are recorded with the plan shown and the user's answer (approved / revision requested with feedback / auto-approved).
- **Status**: the runtime reports the final status itself, so a job settles even if the browser connection drops mid-run. Three writers record status (runtime via the Lambda, the web server on stream errors, the stale-job sweep); **Success is final**: none of them replaces a Success with Failed.
- **Stale jobs**: the runtime re-uploads the trace at least every 5 minutes while it runs, so the trace's last-modified time is a heartbeat. The sweep marks a job Failed when its trace hasn't changed for 30 minutes (Lambda env `STALE_HEARTBEAT_MINUTES`), or, for jobs without a trace (older runtimes), 120 minutes after it started (`STALE_JOB_MINUTES`). Long runs with several plan revisions and HITL waits keep their heartbeat and stay running.

**References**:
- [Planning Documents](../../docs/features/ops-dashboard/plan/) — business requirements, research, technical approach, implementation plan
- [Admin Authentication](../../docs/features/ops-dashboard/admin-authentication.md) — Cognito JWT auth flow, cookie security, route protection
- [Language Switching](../../docs/features/ops-dashboard/language-switching.md) — Korean/English i18n for admin dashboard pages

---

## Prerequisites

| Requirement | Details | Check |
|-------------|---------|-------|
| Managed AgentCore | Phase 1-3 deployed | `cat ../managed-agentcore/.env` |
| Deep Insight Web | `deploy.sh` already run | ALB DNS responds to `/health` |
| AWS CLI | Configured with admin permissions | `aws sts get-caller-identity` |

---

## Deploy

### Step 1: Deploy Ops infrastructure

```bash
cd deep-insight-web

# Provide admin email(s) for SNS notifications and Cognito accounts
bash ops/deploy_ops.sh admin1@example.com admin2@example.com
```

This creates:

| Resource | Name |
|----------|------|
| DynamoDB Table | `deep-insight-jobs` (PAY_PER_REQUEST, 2 GSIs) |
| SNS Topic | `deep-insight-job-notifications` |
| SNS Subscriptions | One per admin email |
| Lambda IAM Role | `deep-insight-ops-lambda-role` |
| Lambda Function | `deep-insight-job-complete` (Python 3.12) |
| S3 Event Notifications | `job_status.json` and `token_usage.json` uploads trigger Lambda |
| EventBridge Rule | `deep-insight-stale-job-sweep` (every 15 min, marks unreported jobs Failed) |
| Cognito User Pool | `deep-insight-ops-admins` (no self-signup, min 12 char password) |
| Cognito App Client | `deep-insight-ops-web` (no client secret) |
| Cognito Admin Users | One per admin email (temporary password sent via email) |
| Web Task Role Policy | DynamoDB + SNS permissions, S3 read on `deep-insight/traces/*` (agent trace) |
| ECS Task Definition | `DYNAMODB_TABLE_NAME`, `SNS_TOPIC_ARN`, `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID` env vars added |

### Step 2: Redeploy Web UI

```bash
# Rebuilds Docker image (includes ops/ module) and updates ECS service
bash deploy.sh
```

> `deploy.sh` preserves env vars added by `deploy_ops.sh`.

### Step 2b: Update the AgentCore Runtime

The agent trace and the runtime-reported job status need the runtime from the same commit. Recommended order: `deploy_ops.sh` (Lambda), `deploy.sh` (web), then the runtime. Any other order is safe too: a failed run never writes `token_usage.json`, which Lambdas from before this change read as success, and a runtime from before this change is still handled through `token_usage.json`.

```bash
cd ../managed-agentcore
uv run 01_create_agentcore_runtime_vpc.py  # updates the existing runtime
```

Until the runtime is updated, jobs are still tracked through `token_usage.json` as before, without a trace.

### Step 3: Wait for ECS service stability

```bash
aws ecs wait services-stable \
  --cluster deep-insight-cluster-prod \
  --services deep-insight-web-service \
  --region us-west-2
```

### Step 4: Verify

```bash
# Check DynamoDB table exists
aws dynamodb describe-table --table-name deep-insight-jobs \
  --region us-west-2 --query "Table.TableStatus"

# Check Lambda function exists
aws lambda get-function --function-name deep-insight-job-complete \
  --region us-west-2 --query "Configuration.FunctionArn"

# Check S3 event notification
aws s3api get-bucket-notification-configuration \
  --bucket <YOUR_BUCKET> --region us-west-2 \
  --query "LambdaFunctionConfigurations[?starts_with(Id, 'deep-insight-job-')].Id"  # job-complete, job-status

# Check ECS task definition has Ops env vars
aws ecs describe-task-definition --task-definition deep-insight-web-task \
  --region us-west-2 \
  --query "taskDefinition.containerDefinitions[0].environment[?name=='DYNAMODB_TABLE_NAME']"
```

---

## Getting Started

### Confirm SNS Subscription

Each admin receives a confirmation email from AWS. **Click the link** to activate notifications.

<img src="img/sns_notification.png" alt="SNS Subscription Confirmation Email" width="600"/>

After clicking, you should see the confirmation page:

<img src="img/sns_notification_confirm.png" alt="SNS Subscription Confirmed" width="500"/>

### Admin Login

Each admin also receives a Cognito email with a temporary password.

<img src="img/cognito_temp_password.png" alt="Cognito Temporary Password Email" width="600"/>

Navigate to `https://<ALB_DNS>/admin/login` and enter your email and temporary password.

<img src="img/admin_login.png" alt="Admin Login Page" width="600"/>

On first login, you are prompted to set a new permanent password (minimum 12 characters).

<img src="img/ask_new_password.png" alt="Set New Password" width="600"/>

### Dashboard Walkthrough

After login, the dashboard shows all analysis jobs with status, duration, tokens, and cache hit rate. Auto-refreshes every 30 seconds.

<img src="img/admin_job_list_page.png" alt="Admin Jobs Dashboard" width="700"/>

Click a row to open the job in a side panel (the URL gets `?job=<id>`, so the link opens it again; Esc closes it). Drag its left edge to resize it, and the divider between the tree and the detail to resize the halves. It has two tabs and a report download button:

- **Trace**: left half, the agents in run order: Coordinator, Planner, plan reviews (HITL, with the user's decision and feedback), and the Supervisor with each sub-agent it ran. The Supervisor's own work between agents shows as `Supervisor → Coder`, `Supervisor → Tracker`, … rows. Each row has a timeline bar, latency and tokens. Right half, the selected agent: its input, its output, then its process as a waterfall (one row per response or tool call: offset from the agent's start, status, duration and a bar on the agent's timeline; a filter for failed calls; the selected row opens below with input / output tabs), and metadata. A running job refreshes every 15 seconds and marks the running agents.
- **Files**: input data, result documents (report first), generated images, and every generated file.

Jobs that ran before the runtime recorded traces show files only; jobs from before agent inputs were recorded show "not recorded" as the input.

---

## Test

Run an analysis job from the Web UI to verify the full pipeline:

1. **Submit** an analysis query via the Web UI
2. **Check dashboard** — job appears with status `Start`
3. **Wait for completion** — status changes to `Success`, token stats populate
4. **Check email** — admins receive a completion notification

<img src="img/email_sns_notification.png" alt="SNS Job Completion Email" width="600"/>

```bash
# Or verify via CLI
aws dynamodb scan --table-name deep-insight-jobs \
  --region us-west-2 --query "Items[].{job_id:job_id.S,status:status.S}" \
  --output table
```

---

## Maintenance

### Redeploy

```bash
cd deep-insight-web

# Update Lambda code only (no email args = skip subscription/user creation)
bash ops/deploy_ops.sh

# Redeploy Web UI (preserves Ops env vars)
bash deploy.sh
```

### Add Subscribers

```bash
# New subscriber receives a confirmation email
aws sns subscribe \
  --topic-arn arn:aws:sns:us-west-2:<ACCOUNT_ID>:deep-insight-job-notifications \
  --protocol email \
  --endpoint new-admin@example.com

# List current subscribers
aws sns list-subscriptions-by-topic \
  --topic-arn arn:aws:sns:us-west-2:<ACCOUNT_ID>:deep-insight-job-notifications \
  --query "Subscriptions[].{Endpoint:Endpoint,Status:SubscriptionArn}" \
  --output table
```

### Add Admin Users

```bash
# Create a new Cognito admin (temporary password sent via email)
aws cognito-idp admin-create-user \
  --user-pool-id <USER_POOL_ID> \
  --username new-admin@example.com \
  --user-attributes Name=email,Value=new-admin@example.com Name=email_verified,Value=true \
  --region us-west-2
```

---

## Cleanup

```bash
cd deep-insight-web

# Remove all Ops resources (DynamoDB, SNS, Lambda, IAM, S3 event, Cognito)
bash ops/deploy_ops.sh cleanup
```

> ECS task definition env vars (DYNAMODB_TABLE_NAME, SNS_TOPIC_ARN) remain but are harmless — `job_tracker.py` skips writes when the table does not exist.

---

## Troubleshooting

### Lambda not triggering

```bash
# Check S3 event notification exists
aws s3api get-bucket-notification-configuration \
  --bucket <YOUR_BUCKET> --region us-west-2

# Check Lambda logs
aws logs tail /aws/lambda/deep-insight-job-complete --region us-west-2 --since 1h
```

### DynamoDB record stuck in "Start"

The runtime uploads `job_status.json` when the run ends, and the Lambda updates the job by `job_id`. A job left in `Start` means the runtime stopped without reporting, or runs an older version; the stale job sweep marks it Failed once its trace stops updating for `STALE_HEARTBEAT_MINUTES` (or `STALE_JOB_MINUTES` after start, without a trace).

```bash
# Check what the runtime uploaded (job_status.json, token_usage.json) and the trace
aws s3 ls s3://<YOUR_BUCKET>/deep-insight/fargate_sessions/<SESSION_ID>/output/
aws s3 ls s3://<YOUR_BUCKET>/deep-insight/traces/<JOB_ID>/

# Check the sweep schedule exists
aws events describe-rule --name deep-insight-stale-job-sweep --region us-west-2
```

Runtimes older than `job_status.json` report through `token_usage.json` and need the session_id linked by the web server, which only happens if the browser stayed connected until `workflow_complete`:

```bash
# Check if session_id was linked to job record
aws dynamodb query --table-name deep-insight-jobs \
  --index-name SessionIdIndex \
  --key-condition-expression "session_id = :sid" \
  --expression-attribute-values '{":sid":{"S":"<SESSION_ID>"}}' \
  --region us-west-2
```

### No email notifications

1. Check SNS subscription is confirmed (not `PendingConfirmation`)
2. Check spam/junk folder
3. Verify Lambda has SNS publish permission

```bash
aws sns list-subscriptions-by-topic \
  --topic-arn arn:aws:sns:us-west-2:<ACCOUNT_ID>:deep-insight-job-notifications \
  --query "Subscriptions[].{Endpoint:Endpoint,Arn:SubscriptionArn}" \
  --output table
```

### Login returns "Auth service unavailable"

Check ECS container logs for Cognito/JWT errors:

```bash
aws logs tail /ecs/deep-insight-web --region us-west-2 --since 15m
```

Common causes:
- `COGNITO_USER_POOL_ID` or `COGNITO_CLIENT_ID` env vars missing — rerun `deploy.sh`
- `cryptography` package not installed — check `requirements.txt`
