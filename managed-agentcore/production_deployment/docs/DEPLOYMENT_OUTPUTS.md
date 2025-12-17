# Deployment Outputs Reference

> What each deployment step creates

**→ Back to [Main README](../../README.md)**

> ⚠️ **Security Note:** The `.env` file contains sensitive AWS resource IDs. Do not commit it to git. It is already in `.gitignore`.

---

## 📊 Overview

| Phase | Script | Creates |
|-------|--------|---------|
| 1+2 | `deploy_phase1_phase2.sh` | CloudFormation stacks, VPC, ALB, ECR, ECS |
| 3 | `01_extract_env_vars_from_cf.sh` | `.env` file |
| 3 | `02_create_uv_env.sh` | `.venv/`, `uv.lock`, symlinks |
| 3 | `03_patch_dockerignore.sh` | Patches toolkit template |
| 4 | `01_create_agentcore_runtime_vpc.py` | AgentCore Runtime, updates `.env` |
| 4 | `02_invoke_agentcore_runtime_vpc.py` | S3 artifacts, CloudWatch logs |
| 4 | `03_download_artifacts.py` | `artifacts/` folder |

---

## 🏗️ Phase 1: VPC Infrastructure

**Script:** `deploy_phase1_phase2.sh` or `phase1/deploy.sh`

### AWS Resources Created

| Resource | Name Pattern | Description |
|----------|--------------|-------------|
| CloudFormation Stack | `deep-insight-infrastructure-{env}` | Parent stack |
| VPC | `deep-insight-vpc-{env}` | 10.0.0.0/16 |
| Private Subnets (2) | `deep-insight-private-{az}` | For Fargate tasks |
| Public Subnets (2) | `deep-insight-public-{az}` | For NAT Gateway |
| Security Groups (4) | `deep-insight-sg-*` | AgentCore, ALB, Fargate, VPC Endpoints |
| Internal ALB | `deep-insight-alb-{env}` | Routes to Fargate |
| Target Group | `deep-insight-tg-{env}` | Health checks |
| VPC Endpoints (6) | - | Bedrock, ECR (3), S3, CloudWatch Logs |
| NAT Gateway | - | Outbound internet (optional) |
| IAM Roles (2) | `deep-insight-task-role-{env}` | Task Role, Execution Role |
| S3 Bucket | `deep-insight-{env}-{account}-{region}` | Artifacts storage |

---

## 🐳 Phase 2: Fargate Runtime

**Script:** `deploy_phase1_phase2.sh` or `phase2/deploy.sh`

### AWS Resources Created

| Resource | Name Pattern | Description |
|----------|--------------|-------------|
| CloudFormation Stack | `deep-insight-fargate-{env}` | Fargate stack |
| ECR Repository | `deep-insight-fargate-{env}` | Docker images |
| Docker Image | `deep-insight-fargate-{env}:latest` | Python 3.12 + dependencies |
| ECS Cluster | `deep-insight-cluster-{env}` | Fargate cluster |
| Task Definition | `deep-insight-task-{env}` | 2 vCPU, 4 GB RAM |
| CloudWatch Log Group | `/ecs/deep-insight-{env}` | Container logs |

---

## 📋 Phase 3: Environment Preparation

### 01_extract_env_vars_from_cf.sh

**Creates:** `managed-agentcore/.env`

**Total: 45 variables** (42 from Phase 3 + 3 from Phase 4)

| Category | Count | Variables |
|----------|-------|-----------|
| OTEL Configuration | 6 | `OTEL_PYTHON_DISTRO`, `OTEL_PYTHON_CONFIGURATOR`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_EXPORTER_OTLP_LOGS_HEADERS`, `OTEL_RESOURCE_ATTRIBUTES`, `AGENT_OBSERVABILITY_ENABLED` |
| AWS Configuration | 2 | `AWS_REGION`, `AWS_ACCOUNT_ID` |
| Bedrock Models | 8 | `DEFAULT_MODEL_ID`, `COORDINATOR_MODEL_ID`, `PLANNER_MODEL_ID`, `SUPERVISOR_MODEL_ID`, `CODER_MODEL_ID`, `VALIDATOR_MODEL_ID`, `REPORTER_MODEL_ID`, `TRACKER_MODEL_ID` |
| Phase 1: VPC | 5 | `VPC_ID`, `PRIVATE_SUBNET_1_ID`, `PRIVATE_SUBNET_2_ID`, `PUBLIC_SUBNET_1_ID`, `PUBLIC_SUBNET_2_ID` |
| Phase 1: Security Groups | 4 | `SG_AGENTCORE_ID`, `SG_ALB_ID`, `SG_FARGATE_ID`, `SG_VPCE_ID` |
| Phase 1: ALB | 3 | `ALB_ARN`, `ALB_DNS`, `ALB_TARGET_GROUP_ARN` |
| Phase 1: IAM | 2 | `TASK_EXECUTION_ROLE_ARN`, `TASK_ROLE_ARN` |
| Phase 2: ECR | 2 | `ECR_REPOSITORY_URI`, `ECR_REPOSITORY_NAME` |
| Phase 2: ECS | 4 | `ECS_CLUSTER_ARN`, `ECS_CLUSTER_NAME`, `TASK_DEFINITION_ARN`, `TASK_DEFINITION_FAMILY` |
| Phase 2: Logs | 1 | `LOG_GROUP_NAME` |
| Phase 2: Network | 3 | `FARGATE_SUBNET_IDS`, `FARGATE_SECURITY_GROUP_IDS`, `FARGATE_ASSIGN_PUBLIC_IP` |
| Phase 2: Container | 1 | `CONTAINER_NAME` |
| S3 | 1 | `S3_BUCKET_NAME` |
| Phase 4: Runtime | 3 | `RUNTIME_NAME`, `RUNTIME_ARN`, `RUNTIME_ID` (added by `01_create_agentcore_runtime_vpc.py`) |

```bash
# ============================================================
# AWS OpenTelemetry Configuration (6 vars)
# ============================================================
OTEL_PYTHON_DISTRO=aws_distro
OTEL_PYTHON_CONFIGURATOR=aws_configurator
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_LOGS_HEADERS=x-aws-log-group=bedrock-agentcore-observability,x-aws-log-stream=custom-spans,x-aws-metric-namespace=AgentCore
OTEL_RESOURCE_ATTRIBUTES=service.name=deep-insight-runtime
AGENT_OBSERVABILITY_ENABLED=true

# ============================================================
# AWS Configuration (2 vars)
# ============================================================
AWS_REGION=us-west-2
AWS_ACCOUNT_ID=123456789012

# ============================================================
# Bedrock Model Configuration (8 vars)
# ============================================================
DEFAULT_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
COORDINATOR_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
PLANNER_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
SUPERVISOR_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
CODER_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
VALIDATOR_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
REPORTER_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
TRACKER_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0

# ============================================================
# Phase 1: Infrastructure Outputs (14 vars)
# ============================================================
VPC_ID=vpc-xxx
PRIVATE_SUBNET_1_ID=subnet-xxx
PRIVATE_SUBNET_2_ID=subnet-xxx
PUBLIC_SUBNET_1_ID=subnet-xxx
PUBLIC_SUBNET_2_ID=subnet-xxx

SG_AGENTCORE_ID=sg-xxx
SG_ALB_ID=sg-xxx
SG_FARGATE_ID=sg-xxx
SG_VPCE_ID=sg-xxx

ALB_ARN=arn:aws:elasticloadbalancing:...
ALB_DNS=internal-deep-insight-alb-{env}-xxx.{region}.elb.amazonaws.com
ALB_TARGET_GROUP_ARN=arn:aws:elasticloadbalancing:...

TASK_EXECUTION_ROLE_ARN=arn:aws:iam::...
TASK_ROLE_ARN=arn:aws:iam::...

# ============================================================
# Phase 2: Fargate Runtime Outputs (11 vars)
# ============================================================
ECR_REPOSITORY_URI=123456789012.dkr.ecr.{region}.amazonaws.com/deep-insight-fargate-runtime-{env}
ECR_REPOSITORY_NAME=deep-insight-fargate-runtime-{env}
ECS_CLUSTER_ARN=arn:aws:ecs:...
ECS_CLUSTER_NAME=deep-insight-cluster-{env}
TASK_DEFINITION_ARN=arn:aws:ecs:...
TASK_DEFINITION_FAMILY=deep-insight-fargate-task-{env}
LOG_GROUP_NAME=/ecs/deep-insight-fargate-{env}

FARGATE_SUBNET_IDS=subnet-xxx,subnet-xxx
FARGATE_SECURITY_GROUP_IDS=sg-xxx
FARGATE_ASSIGN_PUBLIC_IP=DISABLED

CONTAINER_NAME=fargate-runtime

# ============================================================
# S3 Configuration (1 var)
# ============================================================
S3_BUCKET_NAME=deep-insight-logs-{region}-{account}

# ============================================================
# Phase 4: AgentCore Runtime (3 vars) - Added by 01_create_agentcore_runtime_vpc.py
# ============================================================
RUNTIME_NAME=deep_insight_runtime_vpc
RUNTIME_ARN=arn:aws:bedrock-agentcore:{region}:{account}:runtime/deep_insight_runtime_vpc-{random}
RUNTIME_ID=deep_insight_runtime_vpc-{random}
```

### 02_create_uv_env.sh

**Creates:**

| File/Folder | Location | Description |
|-------------|----------|-------------|
| `.venv/` | `phase3/.venv/` | UV virtual environment |
| `uv.lock` | `phase3/uv.lock` | Dependency lock file |
| `.venv` symlink | `managed-agentcore/.venv` | Points to phase3/.venv |
| `pyproject.toml` symlink | `managed-agentcore/pyproject.toml` | Points to phase3/pyproject.toml |

### 03_patch_dockerignore.sh

**Modifies:** Toolkit template to include `src/prompts/` in Docker builds

---

## 🤖 Phase 4: AgentCore Runtime

### 01_create_agentcore_runtime_vpc.py

**Creates:**

| Resource | Description |
|----------|-------------|
| AgentCore Runtime | `deep_insight_runtime_vpc-{random}` |
| CloudWatch Log Group | `/aws/bedrock-agentcore/runtimes/{runtime-name}-DEFAULT` |

**Updates:** `.env` file with `RUNTIME_ARN`

```bash
RUNTIME_ARN=arn:aws:bedrock:us-west-2:123456789012:agent-runtime/deep_insight_runtime_vpc-abc123
```

### 02_invoke_agentcore_runtime_vpc.py

**Creates:**

| Location | Description |
|----------|-------------|
| S3: `s3://{bucket}/deep-insight/fargate_sessions/{session-id}/` | Session artifacts |
| S3: `.../artifacts/` | Charts, reports |
| S3: `.../data/` | Input data copy |
| S3: `.../debug/` | Execution logs |
| CloudWatch Logs | Per-invocation log stream |

### 03_download_artifacts.py

**Creates:**

```
managed-agentcore/
└── artifacts/
    └── {session-id}/
        ├── artifacts/    # Charts, PDFs, reports
        ├── data/         # Input data
        └── debug/        # Execution logs
```

---

## 🗑️ Cleanup: What Gets Deleted

| Phase | Script | Deletes |
|-------|--------|---------|
| 4 | `phase4/cleanup.sh` | AgentCore Runtime, CloudWatch logs, `RUNTIME_ARN` from `.env` |
| 3 | (manual) | `.venv/`, symlinks, `.env` |
| 2 | `phase2/cleanup.sh` | ECR images, ECS cluster, Task Definition |
| 1 | `phase1/cleanup.sh` | VPC, ALB, Security Groups, IAM Roles, S3 bucket |

---

## 📁 Final Project Structure

After all phases complete:

```
managed-agentcore/
├── .env                    # Created by Phase 3
├── .venv → phase3/.venv    # Symlink created by Phase 3
├── pyproject.toml → ...    # Symlink created by Phase 3
├── artifacts/              # Created by 03_download_artifacts.py
│   └── {session-id}/
└── production_deployment/
    └── scripts/
        └── phase3/
            ├── .venv/      # Created by Phase 3
            └── uv.lock     # Created by Phase 3
```

---

**→ Back to [Main README](../../README.md)**
