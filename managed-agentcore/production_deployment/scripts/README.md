# Deployment Scripts - Quick Reference

This directory contains all automation scripts for deploying Deep Insight infrastructure.

---

## 🎯 Script Relationship

```
┌─────────────────────────────────────────────────────────────┐
│         Option 1: Automated (deploy_phase1_phase2.sh)      │
│                                                             │
│  ./deploy_phase1_phase2.sh prod us-east-1                 │
│         │                                                    │
│         ├─→ Auto-detect AZs for your account               │
│         ├─→ calls phase1/deploy.sh (with AZ params)       │
│         └─→ calls phase2/deploy.sh                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   Option 2: Manual                          │
│                                                             │
│  1. cd phase1 && ./verify_agentcore_azs.sh us-east-1      │
│     → Shows: AvailabilityZone1=us-east-1a                 │
│              AvailabilityZone2=us-east-1c                 │
│                                                             │
│  2. ./deploy.sh prod \                                     │
│       --parameter-overrides \                              │
│         AvailabilityZone1=us-east-1a \                    │
│         AvailabilityZone2=us-east-1c                      │
│                                                             │
│  3. cd ../phase2 && ./deploy.sh prod                      │
│                                                             │
│  4. cd ../phase3 && ./setup_env.sh                        │
└─────────────────────────────────────────────────────────────┘

Key Point: deploy_phase1_phase2.sh is a WRAPPER that calls the same
           phase1/deploy.sh and phase2/deploy.sh scripts.
           Phase 3 (setup_env.sh) must be run separately.
           Use whichever approach fits your workflow!
```

---

## 📂 Script Overview

| Script | Purpose | Usage |
|--------|---------|-------|
| **deploy_phase1_phase2.sh** | 🚀 Deploy Phase 1 + 2 (auto-detect AZs) | `./deploy_phase1_phase2.sh prod us-east-1` |
| **phase1/verify_agentcore_azs.sh** | 🔍 Verify supported AZs for Phase 1 | `cd phase1 && ./verify_agentcore_azs.sh us-east-1` |
| **phase1/deploy.sh** | Phase 1: Infrastructure | `cd phase1 && ./deploy.sh prod` |
| **phase1/verify.sh** | Verify Phase 1 resources | `cd phase1 && ./verify.sh prod` |
| **phase1/cleanup.sh** | Delete Phase 1 resources | `cd phase1 && ./cleanup.sh prod` |
| **phase2/deploy.sh** | Phase 2: Fargate Runtime | `cd phase2 && ./deploy.sh prod` |
| **phase2/verify.sh** | Verify Phase 2 resources | `cd phase2 && ./verify.sh prod` |
| **phase2/cleanup.sh** | Delete Phase 2 resources | `cd phase2 && ./cleanup.sh prod` |
| **phase3/01_extract_env_vars_from_cf.sh** | Phase 3: Generate .env from CFN | `cd phase3 && ./01_extract_env_vars_from_cf.sh prod us-west-2` |
| **phase3/02_create_uv_env.sh** | Phase 3: Setup UV environment | `cd phase3 && ./02_create_uv_env.sh deep-insight` |
| **phase3/03_patch_dockerignore.sh** | Phase 3: Patch toolkit template | `cd phase3 && ./03_patch_dockerignore.sh` |
| **01_create_agentcore_runtime_vpc.py** | Phase 4: Create AgentCore Runtime | `uv run 01_create_agentcore_runtime_vpc.py` |
| **02_invoke_agentcore_runtime_vpc.py** | Phase 4: Test runtime invocation | `uv run 02_invoke_agentcore_runtime_vpc.py` |
| **03_download_artifacts.py** | Phase 4: Download S3 artifacts | `uv run 03_download_artifacts.py [session_id]` |
| **phase4/verify.sh** | Phase 4: Verify runtime status | `cd phase4 && ./verify.sh` |
| **phase4/cleanup.sh** | Phase 4: Delete runtime | `cd phase4 && ./cleanup.sh prod` |

---

## 🚀 deploy_phase1_phase2.sh - Deploy Phase 1 + Phase 2

**Purpose**: Automatically verify AZs and deploy both CloudFormation phases to any region/account.

**Syntax**:
```bash
./deploy_phase1_phase2.sh <environment> <region>
```

**Parameters**:
- `environment` - Environment name: `dev`, `staging`, `prod`
- `region` - AWS region: `us-east-1`, `us-west-2`, etc.

**Examples**:
```bash
# Deploy to us-east-1
./deploy_phase1_phase2.sh prod us-east-1

# Deploy to us-west-2
./deploy_phase1_phase2.sh prod us-west-2

# Deploy to eu-west-1
./deploy_phase1_phase2.sh staging eu-west-1
```

**What it does**:
1. ✅ Verifies AWS credentials
2. ✅ Checks if region supports AgentCore VPC mode
3. ✅ Automatically finds supported AZ names in YOUR account
4. ✅ Shows deployment plan and asks for confirmation
5. ✅ Calls phase1/deploy.sh with correct AZ parameters
6. ✅ Calls phase2/deploy.sh
7. ✅ Runs verification after each phase

**When to use**:
- ✅ First-time deployment to a new region
- ✅ Deploying to a new AWS account
- ✅ You want automatic AZ detection
- ✅ You want to deploy both CloudFormation phases together

**Note**: This is a wrapper script. Phase 3 (setup_env.sh) must be run separately.

---

## 🔍 phase1/verify_agentcore_azs.sh - AZ Verification

**Purpose**: Check which AZ names in your account map to supported AgentCore VPC AZ IDs for Phase 1 deployment.

**Syntax**:
```bash
cd phase1
./verify_agentcore_azs.sh [region]
```

**Parameters**:
- `region` - (Optional) AWS region (default: `us-east-1`)

**Examples**:
```bash
# Verify AZs for us-east-1
cd phase1
./verify_agentcore_azs.sh us-east-1

# Verify AZs for us-west-2
cd phase1
./verify_agentcore_azs.sh us-west-2
```

**Output Example**:
```
✅ us-east-1a → use1-az4 (SUPPORTED)
❌ us-east-1b → use1-az6 (NOT SUPPORTED)
✅ us-east-1c → use1-az1 (SUPPORTED)
✅ us-east-1d → use1-az2 (SUPPORTED)

Use these AZ names for CloudFormation deployment:
  AvailabilityZone1=us-east-1a
  AvailabilityZone2=us-east-1c
```

**When to use**:
- ✅ Before deploying Phase 1 to a new account
- ✅ Before deploying Phase 1 to a new region
- ✅ When you want to see all AZ mappings for your account
- ✅ When debugging Phase 1 AZ-related deployment failures
- ✅ Before running manual deployment (Option 2)

---

## 📦 Phase 1 Scripts

### phase1/deploy.sh

**Purpose**: Deploy Phase 1 infrastructure (VPC, Security Groups, VPC Endpoints, ALB, IAM).

**Syntax**:
```bash
cd phase1
./deploy.sh <environment> [options]
```

**Options**:
- `--region <region>` - AWS region (default: from AWS CLI config)
- `--parameter-overrides Key=Value ...` - Override CloudFormation parameters

**Examples**:
```bash
# Deploy with defaults
./deploy.sh prod

# Deploy to specific region with custom AZs
./deploy.sh prod \
  --region us-west-2 \
  --parameter-overrides \
    AvailabilityZone1=us-west-2a \
    AvailabilityZone2=us-west-2b
```

### phase1/verify.sh

**Purpose**: Verify Phase 1 resources are correctly deployed.

**Syntax**:
```bash
cd phase1
./verify.sh <environment> [region]
```

**What it checks**:
- VPC and Subnets
- Security Groups
- VPC Endpoints
- ALB and Target Group
- IAM Roles

### phase1/cleanup.sh

**Purpose**: Delete all Phase 1 CloudFormation stacks and resources.

**⚠️ WARNING**: This will delete ALL Phase 1 infrastructure!

**Syntax**:
```bash
cd phase1
./cleanup.sh <environment> [region]
```

---

## 🐳 Phase 2 Scripts

### phase2/deploy.sh

**Purpose**: Deploy Phase 2 infrastructure (ECR, Docker image, ECS Cluster, Task Definition).

**Syntax**:
```bash
cd phase2
./deploy.sh <environment> [options]
```

**Options**:
- `--region <region>` - AWS region (default: from AWS CLI config)
- `--stage <1|2|all>` - Deployment stage (default: `all`)
  - Stage 1: ECR only
  - Stage 2: Docker build + push + Full stack

**Examples**:
```bash
# Full deployment (all stages)
./deploy.sh prod

# ECR only (Stage 1)
./deploy.sh prod --stage 1

# Docker + ECS only (Stage 2) - assumes ECR exists
./deploy.sh prod --stage 2
```

### phase2/verify.sh

**Purpose**: Verify Phase 2 resources are correctly deployed.

**Syntax**:
```bash
cd phase2
./verify.sh <environment> [region]
```

**What it checks**:
- ECR repository
- Docker image
- ECS cluster
- Task definition

### phase2/cleanup.sh

**Purpose**: Delete all Phase 2 CloudFormation stacks and resources.

**⚠️ WARNING**: This will delete ECR images and ECS cluster!

**Syntax**:
```bash
cd phase2
./cleanup.sh <environment> [region]
```

---

## 📋 Phase 3 Scripts

### phase3/01_extract_env_vars_from_cf.sh

**Purpose**: Generate `.env` file from CloudFormation stack outputs (Phase 1 & 2).

**Syntax**:
```bash
cd phase3
./01_extract_env_vars_from_cf.sh <environment> <region>
```

**Parameters**:
- `environment` - Environment name (dev, staging, prod)
- `region` - AWS region where stacks are deployed (e.g., us-east-1, us-west-2, eu-west-1)

**Examples**:
```bash
# Extract from us-west-2 production stacks
./01_extract_env_vars_from_cf.sh prod us-west-2

# Extract from us-east-1 production stacks
./01_extract_env_vars_from_cf.sh prod us-east-1

# Extract from eu-west-1 development stacks
./01_extract_env_vars_from_cf.sh dev eu-west-1
```

**What it does**:
- Reads Phase 1 CloudFormation stack outputs (VPC, Subnets, Security Groups, ALB, IAM)
- Reads Phase 2 CloudFormation stack outputs (ECR, ECS, Task Definition)
- Generates `.env` file in project root with 35+ environment variables
- Used by Python scripts (create_agentcore_runtime_vpc.py, invoke_agentcore_runtime_vpc.py)

**Output**: `/home/ubuntu/Self-Study-Generative-AI/lab/20_deep_insight/.env`

**When to use**:
- After deploying Phase 1 and Phase 2
- When CloudFormation stack outputs change
- Before creating AgentCore Runtime

**Important**: Always specify the same region where you deployed your CloudFormation stacks!

**Supported Regions**:
The region parameter accepts any valid AWS region code. Common examples:
- **US**: `us-east-1`, `us-east-2`, `us-west-2`
- **Europe**: `eu-west-1`, `eu-central-1`
- **Asia Pacific**: `ap-south-1`, `ap-southeast-1`, `ap-southeast-2`, `ap-northeast-1`

**Region Mismatch Error**:
If you see "Phase 1 stack not found" or "DELETE_FAILED" errors, verify:
1. You're using the correct region parameter
2. The stacks exist in that region: `aws cloudformation list-stacks --region us-west-2`
3. Your AWS CLI default region matches or you override it

---

## 🤖 Phase 4 Scripts

Phase 4 manages the AgentCore Runtime lifecycle: creation, testing, verification, and cleanup.

### 01_create_agentcore_runtime_vpc.py

**Purpose**: Create AgentCore Runtime in VPC Private mode with all configuration from `.env`.

**Location**: Project root (`/home/ubuntu/Self-Study-Generative-AI/lab/20_deep_insight/`)

**Syntax**:
```bash
# From project root
uv run 01_create_agentcore_runtime_vpc.py
```

**Prerequisites**:
- ✅ Phase 1 deployed (VPC, ALB, IAM)
- ✅ Phase 2 deployed (ECR, ECS, Fargate)
- ✅ Phase 3 completed (`.env` generated, UV environment setup)

**What it does**:
1. Loads 35+ environment variables from `.env` file
2. Validates AWS credentials and region
3. Checks Phase 1 and Phase 2 resources exist
4. Creates AgentCore Runtime with VPC configuration:
   - Runtime Name: `deep_insight_runtime_vpc-{random}`
   - Network Mode: VPC (private subnets)
   - Fargate Integration: ECS cluster, task definition, container name
   - Observability: OTEL configuration for per-invocation logs
5. Saves Runtime ARN to `.env` file (RUNTIME_ARN)
6. Displays Runtime details (ID, ARN, status, network config)

**Configuration** (loaded from `.env`):
- **AWS**: Region, Account ID
- **VPC**: Subnet IDs, Security Group IDs
- **Fargate**: Cluster, Task Definition, Container Name
- **ALB**: DNS, Target Group ARN
- **Bedrock**: Model ID
- **OTEL**: 6 observability variables

**Output**:
```bash
✅ AgentCore Runtime Created Successfully!

Runtime ID:       deep_insight_runtime_vpc-abc123XYZ
Runtime ARN:      arn:aws:bedrock:us-east-1:123456789012:agent-runtime/deep_insight_runtime_vpc-abc123XYZ
Status:           READY
Network Mode:     VPC
Region:           us-east-1

Fargate Configuration:
  Cluster:        deep-insight-cluster-prod
  Task Definition: deep-insight-fargate-task-prod
  Container:      fargate-runtime
  Subnets:        subnet-xxx, subnet-yyy
  Security Groups: sg-xxx

Updated .env file:
  RUNTIME_ARN=arn:aws:bedrock:us-east-1:123456789012:agent-runtime/deep_insight_runtime_vpc-abc123XYZ
```

**Execution time**: ~2-3 minutes

**When to use**:
- First-time runtime creation after Phase 3
- Recreating runtime with different configuration
- After runtime deletion (for testing)

**Troubleshooting**:
- **Error: `.env` file not found** → Run `phase3/01_extract_env_vars_from_cf.sh prod`
- **Error: VPC resources not found** → Verify Phase 1 deployed successfully
- **Error: ECS cluster not found** → Verify Phase 2 deployed successfully
- **Error: IAM permissions denied** → Check Phase 1 IAM roles have correct policies

---

### 02_invoke_agentcore_runtime_vpc.py

**Purpose**: Test AgentCore Runtime by running a data analysis task with streaming output.

**Location**: Project root (`/home/ubuntu/Self-Study-Generative-AI/lab/20_deep_insight/`)

**Syntax**:
```bash
# From project root
uv run 02_invoke_agentcore_runtime_vpc.py
```

**Prerequisites**:
- ✅ Phase 4 runtime created (`01_create_agentcore_runtime_vpc.py`)
- ✅ `RUNTIME_ARN` exists in `.env` file
- ✅ Input data file exists: `./data/Dat-fresh-food-claude.csv`

**What it does**:
1. Loads Runtime ARN from `.env` file
2. Sends a data analysis prompt to the runtime:
   - Default: "Calculate total sales from CSV file (no PDF report)"
   - Expected runtime: 2-5 minutes
3. Processes streaming response in real-time
4. Displays agent workflow progress:
   - Coder Agent: Python code generation and execution
   - Validator Agent: Result verification and citation
   - Reporter Agent: PDF report generation (if requested)
5. Shows final results and artifacts

**Example prompts** (edit in script):
```python
# Quick test (2-5 min) - Default
PROMPT = "./data/Dat-fresh-food-claude.csv 파일의 총 매출액 계산해줘. PDF 보고서는 만들지 마."

# With chart and PDF (15-20 min)
PROMPT = "./data/Dat-fresh-food-claude.csv 파일의 총 매출액을 계산하고 차트 1개와 PDF 보고서를 생성해줘"

# Full analysis with PDF (20-25 min)
PROMPT = "./data/Dat-fresh-food-claude.csv 파일을 분석해서 총 매출액을 계산하고, 카테고리별 매출 비중도 함께 보여줘. 그리고 pdf 로 보고서 생성해줘"
```

**Output**:
```bash
🚀 Invoking AgentCore Runtime
   Runtime ARN: arn:aws:bedrock:us-east-1:123456789012:agent-runtime/deep_insight_runtime_vpc-abc123XYZ
   Region: us-east-1
   Prompt: ./data/Dat-fresh-food-claude.csv 파일의 총 매출액 계산해줘...

📡 Streaming response...

[Agent workflow progress shown in real-time]
- Coder Agent: Generating Python code
- Coder Agent: Executing code on Fargate
- Validator Agent: Verifying results
- Reporter Agent: Generating PDF (if requested)

✅ Analysis Complete!
   Total Sales: ₩157,685,452
   Artifacts: s3://bucket-name/deep-insight/fargate_sessions/2025-11-08-12-34-56/
```

**Execution time**: 2-25 minutes (depends on prompt complexity)

**When to use**:
- Testing runtime after creation
- End-to-end workflow validation
- Debugging multi-agent workflow
- Performance testing

**Troubleshooting**:
- **Error: RUNTIME_ARN not set** → Run `01_create_agentcore_runtime_vpc.py` first
- **Error: Runtime not found** → Check runtime exists: `aws bedrock-agentcore-control get-agent-runtime --runtime-identifier <runtime-id>`
- **Error: Fargate task failed** → Check CloudWatch logs: `/aws/bedrock-agentcore/runtimes/<runtime-id>`
- **Timeout**: Increase prompt complexity gradually to isolate issues

---

### 03_download_artifacts.py

**Purpose**: Download analysis artifacts (charts, PDFs, reports) from S3 to local `artifacts/` folder.

**Location**: Project root (`/home/ubuntu/Self-Study-Generative-AI/lab/20_deep_insight/`)

**Syntax**:
```bash
# Download latest session
uv run 03_download_artifacts.py

# Download specific session
uv run 03_download_artifacts.py 2025-11-08-12-34-56
```

**Prerequisites**:
- ✅ At least one successful runtime invocation (`02_invoke_agentcore_runtime_vpc.py`)
- ✅ S3 bucket configured in `.env` (S3_BUCKET_NAME)
- ✅ AWS credentials with S3 read permissions

**What it does**:
1. Lists all available sessions in S3 (`s3://bucket/deep-insight/fargate_sessions/`)
2. Downloads the most recent session (or specified session) to local folder
3. Organizes artifacts into subdirectories:
   ```
   artifacts/
   ├── {session_id}/
   │   ├── artifacts/     # Generated files (charts, PDFs, reports)
   │   ├── data/          # Data files (CSV, input files)
   │   └── debug/         # Debug info (execution logs, session status)
   ```
4. Displays download progress and summary

**Output**:
```bash
📦 Available sessions:
   1. 2025-11-08-12-34-56 (latest)
   2. 2025-11-07-10-20-30
   3. 2025-11-06-15-45-12

📦 Downloading session: 2025-11-08-12-34-56
   S3: s3://bucket-name/deep-insight/fargate_sessions/2025-11-08-12-34-56/
   Local: ./artifacts/2025-11-08-12-34-56

✅ Downloaded 12 files (24.5 MB)
   artifacts/: 5 files (PDF report, charts)
   data/: 3 files (CSV input)
   debug/: 4 files (execution logs)

📂 View artifacts:
   open artifacts/2025-11-08-12-34-56/artifacts/
```

**Local folder structure**:
```
artifacts/
├── 2025-11-08-12-34-56/
│   ├── artifacts/
│   │   ├── sales_report.pdf
│   │   ├── sales_chart.png
│   │   └── category_breakdown.png
│   ├── data/
│   │   └── Dat-fresh-food-claude.csv
│   └── debug/
│       ├── execution_log.txt
│       └── session_status.json
```

**When to use**:
- After successful runtime invocation
- Reviewing generated reports and charts
- Debugging failed executions (check debug/ folder)
- Archiving analysis results locally

**Troubleshooting**:
- **Error: No sessions found** → Run `02_invoke_agentcore_runtime_vpc.py` first
- **Error: S3 access denied** → Check IAM permissions for S3 bucket
- **Error: Session not found** → Verify session ID exists in S3

---

### phase4/verify.sh

**Purpose**: Verify AgentCore Runtime is in READY state and properly configured.

**Syntax**:
```bash
cd production_deployment/scripts/phase4
./verify.sh
```

**Prerequisites**:
- ✅ Runtime created (`01_create_agentcore_runtime_vpc.py`)
- ✅ `RUNTIME_ARN` in `.env` file

**What it checks**:
1. Runtime exists and is accessible
2. Runtime status is READY (not CREATING, FAILED, DELETING)
3. Network configuration (VPC mode, subnets, security groups)
4. Fargate configuration (cluster, task definition, container)
5. CloudWatch log groups exist
6. OTEL observability enabled

**Output**:
```bash
✅ AgentCore Runtime Verification

Runtime Status:
  ID:              deep_insight_runtime_vpc-abc123XYZ
  Status:          READY ✅
  Network Mode:    VPC
  Created:         2025-11-08 12:00:00

Network Configuration:
  Subnets:         subnet-xxx, subnet-yyy ✅
  Security Groups: sg-xxx ✅

Fargate Configuration:
  Cluster:         deep-insight-cluster-prod ✅
  Task Definition: deep-insight-fargate-task-prod ✅
  Container:       fargate-runtime ✅

CloudWatch Logs:
  Log Group:       /aws/bedrock-agentcore/runtimes/deep_insight_runtime_vpc-abc123XYZ ✅
  Streams:         3 invocation log streams

Observability:
  OTEL Enabled:    Yes ✅
  Per-Invocation:  Yes ✅

✅ All checks passed!
```

**When to use**:
- After runtime creation
- Debugging runtime issues
- Before running invocations
- Periodic health checks

---

### phase4/cleanup.sh

**Purpose**: Delete AgentCore Runtime and optionally clean up CloudWatch logs.

**Syntax**:
```bash
cd production_deployment/scripts/phase4
./cleanup.sh prod
```

**What it deletes**:
1. AgentCore Runtime instance
2. Runtime configuration
3. RUNTIME_ARN from `.env` file
4. (Optional) CloudWatch log groups

**Confirmation prompt**:
```bash
⚠️  WARNING: This will delete the following:
   - AgentCore Runtime: deep_insight_runtime_vpc-abc123XYZ
   - CloudWatch logs: /aws/bedrock-agentcore/runtimes/deep_insight_runtime_vpc-abc123XYZ
   - RUNTIME_ARN from .env file

Do you want to continue? (yes/no):
```

**Output**:
```bash
🗑️  Deleting AgentCore Runtime...
   Runtime ID: deep_insight_runtime_vpc-abc123XYZ

✅ Runtime deleted successfully

🗑️  Cleaning up CloudWatch logs...
✅ Log groups deleted

📝 Updated .env file (removed RUNTIME_ARN)

✅ Phase 4 cleanup complete!

To recreate runtime:
  uv run 01_create_agentcore_runtime_vpc.py
```

**When to use**:
- Testing runtime creation/deletion cycles
- Decommissioning the system
- Cleaning up after testing
- Before Phase 2/1 cleanup (must delete runtime first)

**⚠️ Data Loss**:
- All runtime invocation logs permanently deleted
- Cannot recover after deletion
- Must recreate runtime to run new invocations

**Execution time**: ~1-2 minutes

---

## 🎯 Common Workflows

### First-Time Deployment (Automated)

```bash
# Phase 1 + 2: Deploy CloudFormation Infrastructure
cd production_deployment/scripts
./deploy_phase1_phase2.sh prod us-east-1

# Phase 3: Environment Preparation
cd phase3
./01_extract_env_vars_from_cf.sh prod us-west-2  # Generate .env (specify your region!)
./02_create_uv_env.sh deep-insight               # Setup UV + dependencies
./03_patch_dockerignore.sh                       # Patch toolkit template

# Phase 4: Runtime Creation and Testing
cd ../../../                               # Back to project root
uv run 01_create_agentcore_runtime_vpc.py  # Create runtime
uv run 02_invoke_agentcore_runtime_vpc.py  # Test runtime
uv run 03_download_artifacts.py            # Download results

# Phase 4: Verification
cd production_deployment/scripts/phase4
./verify.sh                                # Verify runtime status
```

### First-Time Deployment (Manual)

```bash
# 1. Verify AZs
cd production_deployment/scripts/phase1
./verify_agentcore_azs.sh us-east-1

# 2. Deploy Phase 1
./deploy.sh prod \
  --parameter-overrides \
    AvailabilityZone1=us-east-1a \
    AvailabilityZone2=us-east-1c

# 3. Verify Phase 1
./verify.sh prod

# 4. Deploy Phase 2
cd ../phase2
./deploy.sh prod

# 5. Verify Phase 2
./verify.sh prod

# 6. Setup environment (Phase 3)
cd ../phase3
./01_extract_env_vars_from_cf.sh prod us-east-1  # Use your deployment region
./02_create_uv_env.sh deep-insight
./03_patch_dockerignore.sh

# 7. Create Runtime (Phase 4)
cd ../../../
uv run 01_create_agentcore_runtime_vpc.py

# 8. Test Runtime (Phase 4)
uv run 02_invoke_agentcore_runtime_vpc.py
uv run 03_download_artifacts.py

# 9. Verify Runtime (Phase 4)
cd production_deployment/scripts/phase4
./verify.sh
```

### Multi-Region Deployment

```bash
# Deploy to us-west-2
cd production_deployment/scripts
./deploy_phase1_phase2.sh prod us-west-2

# Setup environment for new region (Phase 3)
cd phase3
./01_extract_env_vars_from_cf.sh prod us-west-2  # Specify us-west-2 for new region
./02_create_uv_env.sh deep-insight
./03_patch_dockerignore.sh

# Create and test Runtime in new region (Phase 4)
cd ../../../
uv run 01_create_agentcore_runtime_vpc.py
uv run 02_invoke_agentcore_runtime_vpc.py
```

### Multi-Account Deployment

```bash
# 1. Switch to target account
aws configure --profile production
export AWS_PROFILE=production

# 2. Verify account
aws sts get-caller-identity

# 3. Deploy (auto-detects AZs for this account)
cd production_deployment/scripts
./deploy_phase1_phase2.sh prod us-east-1

# 4. Setup environment (Phase 3)
cd phase3
./01_extract_env_vars_from_cf.sh prod us-east-1  # Specify region
./02_create_uv_env.sh deep-insight
./03_patch_dockerignore.sh

# 5. Create and test Runtime (Phase 4)
cd ../../../
uv run 01_create_agentcore_runtime_vpc.py
uv run 02_invoke_agentcore_runtime_vpc.py
```

### Update Existing Deployment

```bash
# Update Phase 1 only
cd production_deployment/scripts/phase1
./deploy.sh prod

# Update Phase 2 only (rebuild Docker image)
cd ../phase2
./deploy.sh prod --stage 2
```

### Complete Cleanup

**⚠️ IMPORTANT**: Cleanup must be done in **reverse order** (Phase 4 → 3 → 2 → 1)

```bash
# Step 1: Delete AgentCore Runtime (Phase 4)
cd production_deployment/scripts/phase4
./cleanup.sh prod

# Step 2: Clean Phase 3 Environment (manual)
cd ../phase3
# Remove UV environment
rm -rf .venv
rm -f uv.lock

# Remove symlinks from project root
cd ../../../
rm -f .venv pyproject.toml uv.lock

# Remove .env file (contains sensitive data)
rm -f .env

# Step 3: Delete Phase 2 (Fargate Runtime)
cd production_deployment/scripts/phase2
./cleanup.sh prod

# Step 4: Delete Phase 1 (VPC Infrastructure)
cd ../phase1
./cleanup.sh prod
```

---

## 🗑️ Detailed Cleanup Guide

### Phase 4 Cleanup: AgentCore Runtime

**Script**: `phase4/cleanup.sh`

**What it deletes**:
- AgentCore Runtime instance
- Runtime configuration
- Associated CloudWatch log streams

**Manual verification**:
```bash
# List all runtimes (should be empty after cleanup)
aws bedrock-agentcore-control list-agent-runtimes

# Check CloudWatch log groups (runtime logs may persist)
aws logs describe-log-groups \
  --log-group-name-prefix "/aws/bedrock-agentcore/runtimes"
```

**⚠️ Data Loss**:
- All runtime invocation logs will be deleted
- Cannot be recovered after deletion

---

### Phase 3 Cleanup: Environment Preparation

**No automated script** - Manual cleanup required

**What to delete**:
1. **UV Virtual Environment**:
   ```bash
   cd production_deployment/scripts/phase3
   rm -rf .venv
   rm -f uv.lock
   ```

2. **Symlinks from Project Root**:
   ```bash
   cd /home/ubuntu/Self-Study-Generative-AI/lab/20_deep_insight
   rm -f .venv
   rm -f pyproject.toml
   rm -f uv.lock
   ```

3. **Environment Variables File**:
   ```bash
   # Contains sensitive AWS resource IDs
   rm -f .env
   ```

4. **Backup Files** (optional):
   ```bash
   rm -f .env.backup
   rm -f pyproject.toml.backup
   ```

5. **Jupyter Kernel** (optional):
   ```bash
   jupyter kernelspec remove -f deep-insight
   ```

**What to keep**:
- `pyproject.toml` (in phase3/ directory - source of truth)
- `install_korean_font.sh`
- All numbered scripts (01_, 02_, 03_)

**Verification**:
```bash
# Check no symlinks remain
ls -la /home/ubuntu/Self-Study-Generative-AI/lab/20_deep_insight/ | grep -- '->'

# Check no .env file
ls -la .env

# Check Jupyter kernels
jupyter kernelspec list
```

---

### Phase 2 Cleanup: Fargate Runtime

**Script**: `phase2/cleanup.sh`

**What it deletes**:
- ECS Cluster (`deep-insight-cluster-prod`)
- ECS Task Definition (`deep-insight-fargate-task-prod`)
- ECR Repository (`deep-insight-ecr-prod`)
- **All Docker images in ECR** (⚠️ cannot be recovered)
- CloudWatch Log Groups for ECS tasks
- CloudFormation Stack (`deep-insight-phase2-prod`)

**Before running cleanup**:
```bash
# Check running ECS tasks (should stop them first)
aws ecs list-tasks \
  --cluster deep-insight-cluster-prod \
  --region us-east-1

# Stop all running tasks
aws ecs list-tasks \
  --cluster deep-insight-cluster-prod \
  --query 'taskArns[]' \
  --output text | xargs -I {} aws ecs stop-task \
  --cluster deep-insight-cluster-prod \
  --task {}

# Check ECR images (will be deleted)
aws ecr list-images \
  --repository-name deep-insight-ecr-prod \
  --region us-east-1
```

**Execution**:
```bash
cd production_deployment/scripts/phase2
./cleanup.sh prod us-east-1
```

**Verification**:
```bash
# Stack should be deleted
aws cloudformation describe-stacks \
  --stack-name deep-insight-phase2-prod \
  --region us-east-1
# Expected: Stack does not exist

# ECR repository should be deleted
aws ecr describe-repositories \
  --repository-names deep-insight-ecr-prod \
  --region us-east-1
# Expected: RepositoryNotFoundException

# ECS cluster should be deleted
aws ecs describe-clusters \
  --clusters deep-insight-cluster-prod \
  --region us-east-1
# Expected: Cluster not found
```

**⚠️ Data Loss**:
- All Docker images (must rebuild from source)
- ECS task execution logs
- Cannot rollback to previous image versions

---

### Phase 1 Cleanup: VPC Infrastructure

**Script**: `phase1/cleanup.sh`

**What it deletes**:
- VPC (`DeepInsightVPC`)
- 2 Public Subnets + 2 Private Subnets
- 4 Security Groups (AgentCore, ALB, Fargate, VPC Endpoints)
- Internal Application Load Balancer
- ALB Target Group
- 6 VPC Endpoints (Bedrock, ECR, S3, CloudWatch Logs)
- NAT Gateway (⚠️ releases Elastic IP)
- Internet Gateway
- Route Tables
- 2 IAM Roles (TaskRole, ExecutionRole) + Policies
- CloudFormation Stack (`deep-insight-phase1-prod`)

**Before running cleanup**:
```bash
# Check if any resources are still in use
# 1. Check ALB target health (should deregister targets first)
aws elbv2 describe-target-health \
  --target-group-arn <target-group-arn>

# 2. Check running tasks using the VPC
aws ecs list-tasks \
  --cluster deep-insight-cluster-prod

# 3. Check VPC Endpoint connections
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=<vpc-id>"
```

**Execution**:
```bash
cd production_deployment/scripts/phase1
./cleanup.sh prod us-east-1
```

**Common Issues**:

1. **Network Interfaces in use**:
   ```bash
   # Error: Network interface is currently in use

   # Find and delete ENIs manually
   aws ec2 describe-network-interfaces \
     --filters "Name=vpc-id,Values=<vpc-id>" \
     --query 'NetworkInterfaces[*].[NetworkInterfaceId,Status,Description]'

   # Delete detached ENIs
   aws ec2 delete-network-interface \
     --network-interface-id <eni-id>
   ```

2. **NAT Gateway deletion delay**:
   ```bash
   # NAT Gateway takes 5-10 minutes to delete
   # CloudFormation will wait automatically
   # If stuck, check NAT Gateway status:
   aws ec2 describe-nat-gateways \
     --filter "Name=vpc-id,Values=<vpc-id>"
   ```

3. **IAM Roles in use**:
   ```bash
   # Error: Role is in use by ECS tasks

   # Must delete Phase 2 first (ECS tasks/task definitions)
   # Then retry Phase 1 cleanup
   ```

**Verification**:
```bash
# Stack should be deleted
aws cloudformation describe-stacks \
  --stack-name deep-insight-phase1-prod \
  --region us-east-1
# Expected: Stack does not exist

# VPC should be deleted
aws ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=DeepInsightVPC-prod"
# Expected: Empty list

# NAT Gateway should be deleted
aws ec2 describe-nat-gateways \
  --filter "Name=tag:Environment,Values=prod"
# Expected: State = deleted

# IAM roles should be deleted
aws iam get-role --role-name DeepInsightTaskRole-prod
aws iam get-role --role-name DeepInsightExecutionRole-prod
# Expected: NoSuchEntity errors
```

**⚠️ Data Loss**:
- All network configuration
- ALB DNS name (external references will break)
- NAT Gateway Elastic IP released
- VPC Endpoint DNS names invalidated

**💰 Cost Savings After Cleanup**:
- NAT Gateway: ~$32/month saved
- VPC Endpoints: ~$36/month saved
- ALB: ~$16/month saved
- **Total**: ~$84/month saved

---

## 🔄 Cleanup Order Enforcement

**Why reverse order matters**:

```
Phase 4 (Runtime) → Phase 3 (Environment) → Phase 2 (Fargate) → Phase 1 (VPC)
     ↓                    ↓                      ↓                   ↓
 Uses Runtime      Uses Fargate           Uses VPC              Base Infrastructure
 Created in Phase 3  Created in Phase 2   Created in Phase 1
```

**Dependencies**:
- Phase 4 Runtime **depends on** Phase 2 ECS Tasks
- Phase 2 ECS Tasks **depend on** Phase 1 VPC/ALB/IAM
- Phase 1 resources **cannot be deleted** while Phase 2/4 exist

**If you delete out of order**:
```bash
# ❌ Wrong: Delete Phase 1 before Phase 2
./phase1/cleanup.sh prod
# Error: Network interfaces in use (ECS tasks)
# Error: IAM roles in use (task definitions)
# Error: Security groups in use (ALB targets)

# ✅ Correct: Delete in reverse order
./phase4/cleanup.sh prod  # Runtime first
./phase2/cleanup.sh prod  # Then Fargate
./phase1/cleanup.sh prod  # Finally VPC
```

---

## 🧪 Partial Cleanup Scenarios

### Cleanup Runtime Only (Keep Infrastructure)

```bash
# Delete runtime but keep VPC/Fargate for quick redeployment
cd production_deployment/scripts/phase4
./cleanup.sh prod

# Later: Recreate runtime quickly
cd ../../../
uv run 01_create_agentcore_runtime_vpc.py
```

**Use case**: Testing different runtime configurations

---

### Cleanup Runtime + Fargate (Keep VPC)

```bash
# Delete runtime and Fargate, keep VPC infrastructure
cd production_deployment/scripts/phase4
./cleanup.sh prod

cd ../phase2
./cleanup.sh prod

# Later: Redeploy Fargate with new Docker image
./deploy.sh prod
```

**Use case**: Major code changes requiring new Docker image

---

### Complete Cleanup (All Phases)

```bash
# Full teardown - use automation script
cd production_deployment/scripts

# Delete Phase 4
cd phase4
./cleanup.sh prod

# Clean Phase 3 (manual)
cd ../phase3
rm -rf .venv
cd ../../../
rm -f .venv pyproject.toml uv.lock .env

# Delete Phase 2
cd production_deployment/scripts/phase2
./cleanup.sh prod

# Delete Phase 1
cd ../phase1
./cleanup.sh prod

# Verify all resources deleted
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[?contains(StackName, `deep-insight`)].StackName'
# Expected: Empty list
```

**Use case**: Decommissioning the entire system

---

## 🔧 Environment Variables

After Phase 2 deployment, run `./phase2/setup_env.sh` to generate `.env` file with:

**Phase 1 Outputs (19 variables)**:
- VPC IDs and Subnet IDs
- Security Group IDs
- ALB DNS and Target Group ARN
- IAM Role ARNs
- VPC Endpoint IDs

**Phase 2 Outputs (8 variables)**:
- ECR Repository URI
- ECS Cluster Name
- Task Definition ARN
- Container Name
- CloudWatch Log Group

**Static Configuration (8 variables)**:
- AWS Region and Account ID
- Bedrock Model ID
- OTEL configuration (6 variables)

**Total**: 35+ environment variables

---

## 📚 Additional Documentation

- **Main README**: `../README.md`
- **Multi-Region Guide**: `../docs/MULTI_REGION_DEPLOYMENT.md`
- **AZ Documentation**: `../docs/bedrock_agentcore_vpc_regions.md`
- **CloudFormation Guide**: `../docs/CLOUDFORMATION_GUIDE.md`

---

## ⚠️ Important Notes

### Before Deploying

1. ✅ Always run `verify_agentcore_azs.sh` for new regions/accounts
2. ✅ Verify AWS credentials: `aws sts get-caller-identity`
3. ✅ Check region supports AgentCore VPC (9 regions only)
4. ✅ Ensure unique S3 bucket names

### During Deployment

1. ⏱️ Phase 1 takes ~30-40 minutes
2. ⏱️ Phase 2 takes ~15-20 minutes (Docker build can be slow)
3. 💰 NAT Gateway and VPC Endpoints incur costs (~$68/month)
4. 📝 Save CloudFormation stack names and outputs

### After Deployment

1. ✅ Always run verification scripts
2. ✅ Run `setup_env.sh` to generate `.env` file
3. ✅ Test with `invoke_agentcore_runtime_vpc.py`
4. 📝 Document AZ mappings for the account
