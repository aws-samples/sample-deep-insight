# Deep Insight: Web UI

> Browser-based interface for data upload, analysis, HITL plan review, and report download

**Last Updated**: 2026-04

---

## Overview

Web UI for Deep Insight — a FastAPI server that connects to the Managed AgentCore backend and provides a browser-based experience for non-technical users. For the complete project overview and deployment comparison, see the [root README](../README.md).

- **Browser-Based**: Upload data, review plans, download reports — no CLI needed
- **Data Q&A**: Ask natural-language questions on the uploaded CSV — Text2SQL with editable, re-runnable SQL
- **Bilingual**: Korean / English language support
- **Secure**: Two deployment options — VPN CIDR or CloudFront + Cognito auth

<img src="../docs/features/web-ui/images/web-ui.png" alt="Deep Insight Web UI" width="600"/>

---

## Quick Start

### Prerequisites

| Requirement | Details | Check Command |
|-------------|---------|---------------|
| Managed AgentCore | Phase 1–3 deployed ([guide](../managed-agentcore/README.md)) | `cat ../managed-agentcore/.env` |
| Docker | 20.x+ | `docker --version` |

> **Important**: The Web UI requires a running Managed AgentCore deployment. The `managed-agentcore/.env` file must exist with `RUNTIME_ARN`, `AWS_REGION`, and `S3_BUCKET_NAME` configured.

### Deployment Options

Two deployment methods are available:

| | Option A: VPN CIDR | Option B: CloudFront + Cognito |
|---|---------------------|-------------------------------|
| **Script** | `deploy.sh` | `deploy-cloudfront.sh` |
| **Access** | VPN users only | Anyone with Cognito credentials |
| **ALB SG** | VPN CIDR inbound | CloudFront managed prefix list |
| **Auth** | Network-level (VPN) | Cognito User Pool (Lambda@Edge) |
| **HTTPS** | No (HTTP via VPN) | Yes (CloudFront terminates TLS) |
| **Best for** | Internal teams on VPN | External demos, customer PoCs |

### Option A: VPN CIDR (direct ALB)

```bash
cd deep-insight-web

# Deploy with VPN CIDR restriction
bash deploy.sh "<YOUR_VPN_CIDR>"

# Wait for service to stabilize
aws ecs wait services-stable \
  --cluster deep-insight-cluster-prod \
  --services deep-insight-web-service \
  --region us-west-2

# Clean up
bash deploy.sh cleanup
```

### Option B: CloudFront + Cognito (recommended)

```bash
cd deep-insight-web

# Deploy with CloudFront (ALB restricted to CloudFront prefix list only)
bash deploy-cloudfront.sh

# Wait for service to stabilize
aws ecs wait services-stable \
  --cluster deep-insight-cluster-prod \
  --services deep-insight-web-service \
  --region us-west-2

# (Optional) Add Cognito authentication
bash add-cognito-auth.sh <CLOUDFRONT_DISTRIBUTION_ID>

# Clean up (removes CloudFront, ALB, ECS, and all resources)
bash deploy-cloudfront.sh cleanup
```

> **Security**: `deploy-cloudfront.sh` uses the CloudFront managed prefix list (`pl-82a045eb`) instead of `0.0.0.0/0` for the ALB security group. This prevents DyePack/Epoxy auto-mitigation incidents.

> **Note**: Do NOT test during rolling deployment — the old ECS task gets killed mid-stream.

### What the deploy scripts do

Both scripts handle all infrastructure in a single run:

1. **ECR Repository** — Creates container registry
2. **Docker Build + Push** — Auto-detects platform (arm64/x86) and pushes to ECR
3. **Security Groups** — ALB SG (VPN CIDR *or* CloudFront prefix list), ECS SG, VPC endpoint rules
4. **ALB + Target Group + Listener** — Internet-facing ALB with 3600s idle timeout for long analysis sessions
5. **IAM Task Role** — Least-privilege permissions (S3 upload/feedback/artifacts, AgentCore invoke)
6. **CloudWatch Log Group** — Container logging
7. **ECS Task Definition** — Fargate (auto-detects ARM64 or X86_64), 1024 CPU / 2048 MB (Data Q&A runs pandas/matplotlib/DuckDB in-container)
8. **ECS Service** — Creates or updates with rolling deployment
9. **CloudFront** — *(Option B only)* Creates distribution with ALB origin

---

## Features

| Feature | Endpoint | Description |
|---------|----------|-------------|
| Health check | `GET /health` | ALB health check (status, runtime ARN, region, S3 bucket) |
| Static page | `GET /` | Serves `static/index.html` |
| File upload | `POST /upload` | Upload data file + optional column definitions to S3 |
| Analysis | `POST /analyze` | Invoke AgentCore Runtime, stream SSE events to browser |
| HITL review | `POST /feedback` | Submit plan approval/rejection (uploaded to S3) |
| Artifacts | `GET /artifacts/{session_id}` | List generated report files |
| Download | `GET /download/{session_id}/{filename}` | Download a report file |
| Column auto-gen | `POST /generate-column-definitions` | Generate `column_definitions.json` from CSV header + sample rows (Bedrock Claude) |
| Prompt auto-gen | `POST /generate-prompts` | Generate 3 sample analysis prompts from `column_definitions.json` |
| Data Q&A chat | `POST /chat` | DuckDB-backed Text2SQL chat with SSE streaming |
| Chat reset | `POST /chat/reset` | Clear chat history for a session |
| Chat suggestions | `POST /chat/suggestions` | Schema-heuristic starter questions |
| Dataset meta | `GET /chat/meta` | Row count, columns, types, descriptions |
| SQL re-run | `POST /sql/execute` | Execute user-edited SQL directly (no LLM) |

> For detailed feature specifications, see the [Development Plan](../docs/features/web-ui/03-development-plan.md).
>
> For Ops Admin (job tracking, notifications, dashboard), see the [Ops Deployment Guide](ops/README.md).

---

## Data Q&A

Conversational exploration on the uploaded CSV. Complements the long-form
analysis flow (`/analyze`, 15–30 min) with fast, iterative questions.

Enabled automatically after upload — a "Data Q&A" tab appears next to "Analysis"
at the top of the page.

### How it works

```
Upload CSV --> DuckDB in-memory table (read_csv_auto)
                    |
User question --> Strands Agent + Claude Sonnet 4.6
                    |
                    |-- query_sql(sql)                     -> table (SSE)
                    |-- create_chart(sql, matplotlib_code) -> PNG (SSE)
                    |-- describe_schema
                    v
             Answer streamed back with SQL block + table/chart
                    |
User edits SQL --> POST /sql/execute (re-run without LLM, ms latency)
```

### Highlights

- **Text2SQL with transparency**: Generated SQL is always shown in the chat bubble; collapsible by default
- **Inline SQL editor**: `▶ 실행` re-runs as-is, `✎ 편집` opens editor; no extra LLM call needed
- **Light-themed charts**: matplotlib with Korean font (NanumGothic), bold titles, click to zoom
- **Dynamic starter questions**: From schema heuristics — no LLM call on welcome load
- **Follow-up chips**: LLM inlines `[SUGGESTIONS]q1|q2|q3[/SUGGESTIONS]` at response end
- **Column-definitions aware**: Uses `column_definitions.json` (optional, auto-generated) in the system prompt for domain-accurate SQL
- **Insight-first Response Rules**: System prompt forces concrete numeric headlines and bans filler phrases ("경향이 있습니다" etc.)

### Prompt caching

System prompt + tool specs + conversation history are cached via Bedrock
ephemeral cache using `SystemContentBlock + cachePoint` and
`CacheConfig(strategy="auto")`. TTL is 5 minutes, which is a Bedrock
platform default (not configurable); this matches the typical inter-turn
gap in an interactive Q&A session.

Measured 5-turn session in production:

| Turn | total input | cache_read | hit% |
|---|---|---|---|
| 1 | 5,938 | 2,653 | 44.7% |
| 2 | 12,243 | 10,822 | 88.4% |
| 3 | 10,963 | 9,760 | 89.0% |
| 4 | 13,048 | 12,112 | 92.8% |
| 5 | 15,281 | 14,038 | 91.9% |

Per-turn input cost drops to ~10% on cache hits; session-level savings
typically 50%+ depending on conversation length (write premium grows with
history).

Toggle via env var: `ENABLE_PROMPT_CACHE=0` disables caching (useful for
local debugging).

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CHAT_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Chat agent LLM |
| `ENABLE_PROMPT_CACHE` | `1` | Set `0` to disable prompt caching |
| `WEB_UTILITY_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Column/prompt auto-generation utility |

### Observing prompt caching hits

```bash
# Live tail of per-turn usage metrics
aws logs tail /ecs/deep-insight-web --region us-west-2 --follow | grep "chat usage"
```

Each chat turn logs `input=… output=… cache_read=… cache_write=…` (values are
cumulative within a task; diff consecutive lines for per-turn deltas).

### Local development

Chat runs without S3 if `S3_BUCKET_NAME` is unset — uploaded CSVs go to
`/tmp/deep-insight-uploads/{upload_id}/` instead. Only Bedrock credentials
(`AWS_PROFILE` or env vars) are required.

```bash
cd deep-insight-web
pip install -r requirements.txt
export AWS_REGION=us-west-2    # CHAT_MODEL_ID uses global. profile
python app.py
# localhost:8080 → upload CSV → "Data Q&A" tab → ask
```

---

## Architecture

**Option A: VPN CIDR**

```
Browser --> ALB (VPN CIDR SG) --> ECS Fargate (FastAPI)
                                      |
                                      +-- AgentCore Runtime (SSE streaming)
                                      +-- S3 (upload / feedback / artifacts)
```

**Option B: CloudFront + Cognito**

```
Browser --> CloudFront (HTTPS) --> Lambda@Edge (Cognito auth)
                                       |
                                       v (authenticated)
                                  ALB (CF prefix list SG) --> ECS Fargate (FastAPI)
                                                                  |
                                                                  +-- AgentCore Runtime
                                                                  +-- S3
```

- **AgentCore Native Protocol**: `boto3.invoke_agent_runtime()` with SSE streaming
- **SSE keepalive**: Sends `: keepalive` comments every 30s to prevent proxy idle timeout
- **HITL flow**: `plan_review_request` SSE event -> browser modal -> `POST /feedback` -> S3 -> AgentCore polls
- **Data Q&A flow**: `/chat` invokes a Strands Agent (Claude Sonnet 4.6) with three tools — `describe_schema`, `query_sql`, `create_chart`. DuckDB runs in-container against the uploaded CSV; **AgentCore is not on this path**, so chat responses return in seconds rather than minutes.
- **Env vars**: Reuses `managed-agentcore/.env` (no separate `.env.example`)

---

## Troubleshooting

### `exec format error` in ECS tasks

The Docker image architecture doesn't match the Fargate runtime platform. The task definition uses ARM64 (Graviton2), so the image must be built on an arm64 host.

```bash
# Verify the image architecture
docker inspect deep-insight-web:latest --format '{{.Architecture}}'
# Expected: arm64
```

If you see `amd64`, rebuild with `--no-cache` to avoid stale cached layers:

```bash
docker build --no-cache -t deep-insight-web:latest .
```

### Container crashes at startup (exit code 255)

Check CloudWatch logs:

```bash
aws logs get-log-events --log-group-name /ecs/deep-insight-web \
  --log-stream-name "$(aws logs describe-log-streams \
    --log-group-name /ecs/deep-insight-web \
    --order-by LastEventTime --descending \
    --query 'logStreams[0].logStreamName' --output text \
    --region us-west-2)" \
  --region us-west-2 --query 'events[*].message' --output text
```

### ECS task cycling (starts, registers, then deregisters)

The service is likely failing health checks. Verify target health:

```bash
aws elbv2 describe-target-health \
  --target-group-arn "$(aws elbv2 describe-target-groups \
    --names deep-insight-web-tg \
    --query 'TargetGroups[0].TargetGroupArn' --output text \
    --region us-west-2)" \
  --region us-west-2
```

### Data Q&A: `AccessDeniedException: bedrock:InvokeModel` or `s3:ListBucket`

The task role's inline policy is out of sync — happens when `deploy-cloudfront.sh`
or `deploy.sh` adds new Sids but the role already existed (older script
versions only created policy on role creation).

Re-run the deploy script; it now always refreshes the inline policy:

```bash
bash deploy-cloudfront.sh   # or deploy.sh
```

Verify the policy contains the expected Sids:

```bash
aws iam get-role-policy \
  --role-name deep-insight-web-task-role \
  --policy-name deep-insight-web-task-policy \
  --query 'PolicyDocument.Statement[].Sid'
# Expected: ["S3Upload", "S3UploadsList", "S3Feedback",
#            "S3ArtifactsList", "S3ArtifactsGet",
#            "AgentCoreInvoke", "BedrockInvokeClaude"]
```

### Data Q&A: chart labels render as □□□

The container is missing Korean fonts. The Dockerfile installs `fontconfig +
fonts-nanum` before the `USER appuser` switch. If an older image was pushed
before this change, rebuild and redeploy:

```bash
bash deploy-cloudfront.sh   # or deploy.sh — forces new image build + push
```

Verify Nanum is present inside the container:

```bash
docker run --rm 603420654815.dkr.ecr.us-west-2.amazonaws.com/deep-insight-web:latest \
  fc-list | grep -i nanum
```
