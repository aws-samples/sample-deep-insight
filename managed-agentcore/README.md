# Deep Insight: Multi-Agent Data Analysis System

> AWS Bedrock AgentCore Runtime으로 구현한 자동화된 데이터 분석 시스템

---

## 🎯 Overview

CSV 데이터를 분석하여 인사이트를 추출하고 PDF 보고서를 자동 생성하는 Multi-Agent 시스템입니다.

**핵심 기능**:
- 📊 자동화된 데이터 분석 및 계산 (Coder Agent)
- ✅ 결과 검증 및 인용 생성 (Validator Agent)
- 📄 PDF 보고서 자동 생성 (Reporter Agent)
- 🔒 VPC Private 모드 완전 지원

**기술 스택**:
- AWS Bedrock AgentCore Runtime (VPC Private Mode)
- AWS Fargate (Dynamic Code Execution)
- Strands Agent Multi-Agent Workflow
- CloudFormation Infrastructure as Code

---

## 🚀 Quick Start

### Production Deployment

Four-phase deployment:
1. **Phase 1**: VPC Infrastructure (CloudFormation)
2. **Phase 2**: Fargate Runtime (CloudFormation + Docker)
3. **Phase 3**: Environment Preparation (UV, Dependencies, Config)
4. **Phase 4**: AgentCore Runtime (Creation, Verification, Cleanup)

**Quick commands**:
```bash
# Phase 1 + 2: Infrastructure (Automated)
cd production_deployment/scripts
./deploy_phase1_phase2.sh prod us-west-2

# Phase 3: Environment Setup
cd phase3
./01_extract_env_vars_from_cf.sh prod us-west-2  # Specify your deployment region
./02_create_uv_env.sh deep-insight
./03_patch_dockerignore.sh

# Phase 4: Runtime Creation and Testing
cd ../../../
uv run 01_create_agentcore_runtime_vpc.py  # Create runtime
uv run 02_invoke_agentcore_runtime_vpc.py  # Test runtime
uv run 03_download_artifacts.py            # Download results

# Phase 4: Verification
cd production_deployment/scripts/phase4
./verify.sh
```

---

## 🗑️ Cleanup

### Complete Cleanup (All Phases)

**Single command** to delete all resources in the correct order:

```bash
cd production_deployment/scripts
./cleanup_all.sh prod us-west-2
```

This will delete:
- Phase 4: AgentCore Runtime + CloudWatch logs
- Phase 3: UV environment, .env file, symlinks
- Phase 2: ECS cluster, ECR repository, Docker images
- Phase 1: VPC, subnets, security groups, ALB, IAM roles
- S3 buckets (templates + session data)

**⚠️ WARNING**: You must type "DELETE" to confirm. This action is irreversible!

### Manual Cleanup (Individual Phases)

If you need to clean up specific phases:

```bash
# Phase 4: Delete Runtime only (region REQUIRED)
cd production_deployment/scripts/phase4
./cleanup.sh prod --region us-west-2

# Phase 2: Delete Fargate resources (region REQUIRED)
cd production_deployment/scripts/phase2
./cleanup.sh prod --region us-west-2

# Phase 1: Delete VPC infrastructure (region REQUIRED)
cd production_deployment/scripts/phase1
./cleanup.sh prod --region us-west-2
```

**Important**: Always delete in reverse order (4 → 3 → 2 → 1)

For detailed cleanup instructions, see: [`production_deployment/scripts/README.md#cleanup`](production_deployment/scripts/README.md#-cleanup-order-enforcement)

---

## 📁 Project Structure

```
.
├── production_deployment/       # 🏗️ Production Deployment (All Phases)
│   ├── README.md                # Main deployment guide
│   ├── cloudformation/          # CloudFormation templates
│   ├── scripts/                 # Deployment & verification scripts
│   │   ├── deploy_phase1_phase2.sh  # Automated Phase 1 + 2
│   │   ├── cleanup_all.sh       # 🗑️ Complete cleanup (all phases)
│   │   ├── phase1/              # VPC Infrastructure
│   │   │   ├── deploy.sh
│   │   │   ├── verify.sh
│   │   │   └── cleanup.sh
│   │   ├── phase2/              # Fargate Runtime
│   │   │   ├── deploy.sh
│   │   │   ├── verify.sh
│   │   │   └── cleanup.sh
│   │   ├── phase3/              # Environment Preparation
│   │   │   ├── 01_extract_env_vars_from_cf.sh
│   │   │   ├── 02_create_uv_env.sh
│   │   │   ├── 03_patch_dockerignore.sh
│   │   │   └── pyproject.toml (+ .venv, uv.lock)
│   │   └── phase4/              # Runtime Management
│   │       ├── verify.sh
│   │       └── cleanup.sh
│   └── docs/                    # Detailed documentation
│       ├── MULTI_REGION_DEPLOYMENT.md
│       ├── bedrock_agentcore_vpc_regions.md
│       └── CLOUDFORMATION_GUIDE.md
│
├── src/                         # 🤖 Agent Source Code
│   ├── graph/                   # LangGraph workflow definitions
│   ├── tools/                   # Fargate integration tools
│   ├── prompts/                 # Agent prompts
│   └── utils/                   # Utilities
│
├── fargate-runtime/             # 🐳 Fargate Container Code
│   ├── dynamic_executor_v2.py   # Code execution server
│   ├── Dockerfile               # Container image
│   └── requirements.txt         # Python dependencies
│
├── 01_create_agentcore_runtime_vpc.py  # Phase 4: Runtime creation
├── 02_invoke_agentcore_runtime_vpc.py  # Phase 4: Runtime testing
├── 03_download_artifacts.py             # Phase 4: Download S3 artifacts
│
├── .venv → production_deployment/scripts/phase3/.venv  # Symlink
├── pyproject.toml → production_deployment/scripts/phase3/pyproject.toml  # Symlink
│
└── README.md                    # This file
```

---

## 📚 Documentation

### Deployment Guides
- **[production_deployment/README.md](production_deployment/README.md)** - Complete deployment guide
- **[production_deployment/scripts/README.md](production_deployment/scripts/README.md)** - All scripts reference
- **[production_deployment/docs/MULTI_REGION_DEPLOYMENT.md](production_deployment/docs/MULTI_REGION_DEPLOYMENT.md)** - Multi-region & multi-account deployment

### Technical Guides
- **[production_deployment/docs/bedrock_agentcore_vpc_regions.md](production_deployment/docs/bedrock_agentcore_vpc_regions.md)** - Supported regions & AZ IDs
- **[production_deployment/docs/CLOUDFORMATION_GUIDE.md](production_deployment/docs/CLOUDFORMATION_GUIDE.md)** - CloudFormation details


---

## 📊 Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────┐
│  User (Bedrock AgentCore API)                           │
└────────────────┬────────────────────────────────────────┘
                 │ invoke_runtime()
                 ▼
┌─────────────────────────────────────────────────────────┐
│  AgentCore Runtime (VPC Private)                        │
│  ┌───────────────────────────────────────────────┐      │
│  │ Coordinator (Strands Agent)                       │      │
│  │  - Coder Agent → Validator Agent → Reporter  │      │
│  │  - Multi-Agent Workflow Orchestration         │      │
│  └───────────────────────────────────────────────┘      │
└────────────────┬────────────────────────────────────────┘
                 │ HTTP (Private)
                 ▼
┌─────────────────────────────────────────────────────────┐
│  Internal ALB (Private Subnets)                         │
│  - Target Group (Fargate Tasks)                         │
│  - Health Checks & Routing                              │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│  Fargate Containers (Private Subnets)                   │
│  - Python Code Execution (Dynamic)                      │
│  - Session Management (Cookie-based)                    │
│  - Matplotlib, Pandas, Data Processing                  │
└─────────────────────────────────────────────────────────┘
```

### Network Architecture

**100% Private Network** - No public internet access required:
- VPC Endpoints for AWS services (Bedrock, ECR, S3, CloudWatch Logs)
- NAT Gateway optional (VPC Endpoints handle all traffic)
- Private subnets for Fargate tasks
- Internal ALB for container routing

---

## 🔑 Key Features

### Phase 1: Infrastructure
- **VPC**: 10.0.0.0/16 with Multi-AZ deployment
- **Security Groups**: 4 groups with least-privilege rules
- **VPC Endpoints**: 6 endpoints for private AWS service access
- **Internal ALB**: Private load balancer for Fargate containers
- **IAM Roles**: Task Role + Execution Role with minimal permissions

### Phase 2: Fargate Runtime
- **ECR Repository**: Private container registry
- **Docker Image**: Python 3.12 + Korean font support
- **ECS Cluster**: Fargate-based compute
- **Task Definition**: 2 vCPU, 4 GB RAM, auto-scaling ready

### Phase 3: Environment Preparation
- **UV Environment**: Python 3.12 + all dependencies
- **Korean Font Support**: Nanum fonts for PDF generation
- **PDF Tools**: Pandoc, TeXLive, XeTeX
- **Toolkit Patch**: Include prompts in Docker builds
- **Symlinks**: Enable `uv run` from project root

### Phase 4: AgentCore Runtime
- **Runtime Creation**: Automated VPC runtime deployment (01_create_agentcore_runtime_vpc.py)
- **Runtime Testing**: End-to-end workflow testing with streaming output (02_invoke_agentcore_runtime_vpc.py)
- **Artifact Management**: S3 artifact download and organization (03_download_artifacts.py)
- **VPC Private Mode**: Native Runtime.launch() support with private network
- **Multi-Agent Workflow**: Coordinator-based orchestration (Coder, Validator, Reporter)
- **Dynamic Execution**: On-demand Fargate container creation and management
- **Observability**: Per-invocation CloudWatch log streams with OTEL integration
- **Verification**: Runtime health and status checks (verify.sh)
- **Cleanup**: Runtime deletion and resource cleanup (cleanup.sh)

---

## 🌍 Multi-Region Support

Supports deployment to **9 AWS regions**:
- 🇺🇸 US East (N. Virginia, Ohio), US West (Oregon)
- 🌏 Asia Pacific (Mumbai, Singapore, Sydney, Tokyo)
- 🇪🇺 Europe (Ireland, Frankfurt)

**Important**: AZ names are account-specific. Always verify AZ mappings before deploying to new accounts/regions.

**→ [docs/MULTI_REGION_DEPLOYMENT.md](production_deployment/docs/MULTI_REGION_DEPLOYMENT.md)**

---


## 📝 License

MIT License

---

**Version**: 3.0.0
**Status**: ✅ Production Ready
**Last Updated**: 2025-11-08
