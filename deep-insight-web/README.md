# Deep Insight: Web UI

> Browser-based interface for data upload, analysis, HITL plan review, and report download

**Last Updated**: 2026-02

---

## Overview

Web UI for Deep Insight — a FastAPI server that connects to the Managed AgentCore backend and provides a browser-based experience for non-technical users. For the complete project overview and deployment comparison, see the [root README](../README.md).

- **Browser-Based**: Upload data, review plans, download reports — no CLI needed
- **Bilingual**: Korean / English language support
- **Secure**: Internet-facing ALB restricted to VPN CIDR

<img src="../docs/front-end/images/web-ui.png" alt="Deep Insight Web UI" width="600"/>

---

## Quick Start

### Prerequisites

| Requirement | Details | Check Command |
|-------------|---------|---------------|
| Managed AgentCore | Phase 1–3 deployed ([guide](../managed-agentcore/README.md)) | `cat ../managed-agentcore/.env` |
| Docker | 20.x+ | `docker --version` |

> **Important**: The Web UI requires a running Managed AgentCore deployment. The `managed-agentcore/.env` file must exist with `RUNTIME_ARN`, `AWS_REGION`, and `S3_BUCKET_NAME` configured.

### Production Deployment

```bash
cd deep-insight-web

# Deploy (ECR, Docker build/push, ALB, ECS)
# VPN_CIDR restricts ALB access to your VPN's IP range (only users on the VPN can reach the Web UI)
# Usage: bash deploy.sh <VPN_CIDR>
# Example: bash deploy.sh "10.0.0.0/8"
bash deploy.sh "<YOUR_VPN_CIDR>"

# Wait for service to stabilize
aws ecs wait services-stable \
  --cluster deep-insight-cluster-prod \
  --services deep-insight-web-service \
  --region us-west-2

# Clean up all resources
bash deploy.sh cleanup
```

> **Note**: Do NOT test during rolling deployment — the old ECS task gets killed mid-stream.

### What `deploy.sh` Does

The script handles all infrastructure in a single run:

1. **ECR Repository** — Creates container registry
2. **Docker Build + Push** — Builds image natively (arm64 on Graviton, x86 on Intel) and pushes to ECR
3. **Security Groups** — ALB SG (VPN CIDR inbound on port 80), ECS SG, VPC endpoint rules
4. **ALB + Target Group + Listener** — Internet-facing ALB with 3600s idle timeout for long analysis sessions
5. **IAM Task Role** — Least-privilege permissions (S3 upload/feedback/artifacts, AgentCore invoke)
6. **CloudWatch Log Group** — Container logging
7. **ECS Task Definition** — Fargate ARM64 (Graviton2), 256 CPU / 512 MB
8. **ECS Service** — Creates or updates with rolling deployment

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

> For detailed feature specifications, see the [Development Plan](../docs/front-end/03-development-plan.md).

---

## Architecture

```
Browser ←─ SSE ──→ FastAPI (deep-insight-web)
                        │
                        ├── boto3.invoke_agent_runtime() ──→ AgentCore Runtime
                        │        (SSE streaming, 3600s timeout)
                        │
                        └── S3 ──→ File upload / HITL feedback / Report download
```

- **AgentCore Native Protocol**: `boto3.invoke_agent_runtime()` with SSE streaming
- **HITL flow**: `plan_review_request` SSE event → browser modal → `POST /feedback` → S3 → AgentCore polls
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
