# Deep Insight: Self-Hosted vs Managed AgentCore

> Detailed comparison between deployment options

**→ [Self-Hosted README](../../../self-hosted/README.md)** | **→ [Managed AgentCore README](../../README.md)**

---

## Quick Comparison

| | Self-Hosted | Managed AgentCore |
|---|-------------|-------------------|
| **Setup Time** | ~10 minutes | ~45 minutes |
| **Agent Hosting** | Local/EC2 | Bedrock AgentCore Runtime |
| **Code Execution** | Local Python | AWS Fargate (Custom Code Interpreter) |
| **Network** | Your choice | 100% Private VPC |
| **Best For** | Development, Testing | Production, Enterprise |

---

## Detailed Comparison

### Setup & Prerequisites

| | Self-Hosted | Managed AgentCore |
|---|-------------|-------------------|
| Setup Time | ~10 minutes | ~45 minutes |
| Prerequisites | Python 3.12+, UV | AWS CLI v2, Docker, jq, UV, Python 3.12+ |
| Configuration | `.env` file | CloudFormation + `.env` (auto-generated) |
| Deployment Method | `uv run python main.py` | 4-phase deployment (CloudFormation + Scripts) |

### Infrastructure

| | Self-Hosted | Managed AgentCore |
|---|-------------|-------------------|
| Agent Runtime | Local machine or EC2 | Bedrock AgentCore Runtime (VPC mode) |
| Code Execution | Local Python process | Custom Code Interpreter (ECR + ALB + Fargate) |
| Container Management | None | ECS Fargate with auto-scaling |
| Load Balancing | None | Internal Application Load Balancer |

### Network & Security

| | Self-Hosted | Managed AgentCore |
|---|-------------|-------------------|
| Network Mode | Your choice (public/private) | 100% Private VPC |
| Internet Access | Required for Bedrock API | VPC Endpoints (no public internet) |
| Data Isolation | Depends on your setup | Complete VPC isolation |
| VPC Endpoints | N/A | Bedrock, ECR (3), S3, CloudWatch Logs |
| Security Groups | N/A | 4 groups with least-privilege rules |

### Operations & Monitoring

| | Self-Hosted | Managed AgentCore |
|---|-------------|-------------------|
| Scaling | Manual | AgentCore Runtime MicroVM + Auto-scaling Fargate |
| Monitoring | Custom implementation | CloudWatch + OpenTelemetry built-in |
| Log Management | Local/Custom | CloudWatch Logs with per-invocation streams |
| Artifact Storage | Local filesystem | S3 bucket |

### Cost Considerations

| | Self-Hosted | Managed AgentCore |
|---|-------------|-------------------|
| Infrastructure Cost | EC2 or local only | VPC Endpoints (~$36/mo) + ALB (~$20/mo) + Fargate (pay-per-use) |
| Bedrock API | Same | Same |
| Estimated Monthly* | $0 (local) or EC2 cost | ~$56-93/month base + Fargate usage |

*Estimated costs for 24/7 operation, excluding Bedrock API usage.

---

## When to Choose Each Option

### Choose Self-Hosted When:

- ✅ **Rapid Development** - Iterating quickly on agents, prompts, or workflows
- ✅ **Testing & PoC** - Validating concepts before production deployment
- ✅ **Cost Sensitivity** - Minimizing infrastructure costs during development
- ✅ **Simple Setup** - Getting started quickly without AWS infrastructure
- ✅ **Local Data** - Working with data that doesn't need VPC isolation

### Choose Managed AgentCore When:

- ✅ **Production Workloads** - Running enterprise-grade agent workflows
- ✅ **Data Security** - Requiring 100% private network with no public internet
- ✅ **Compliance** - Meeting enterprise security and compliance requirements
- ✅ **Scalability** - Needing auto-scaling for concurrent requests
- ✅ **Observability** - Requiring built-in monitoring with CloudWatch/OpenTelemetry
- ✅ **Long-Running Tasks** - Processing large files or complex workflows

---

## Feature Availability

| Feature | Self-Hosted | Managed AgentCore |
|---------|:-----------:|:-----------------:|
| Multi-Agent Workflow | ✅ | ✅ |
| Coder Agent | ✅ | ✅ |
| Validator Agent | ✅ | ✅ |
| Reporter Agent | ✅ | ✅ |
| Tracker Agent | ✅ | ✅ |
| DOCX Report Generation | ✅ | ✅ |
| Chart Generation | ✅ | ✅ |
| Large File Processing (1GB+) | ⚠️ Memory limited | ✅ |
| Custom Docker Image | ❌ | ✅ |
| VPC Private Mode | ❌ | ✅ |
| Auto-scaling | ❌ | ✅ |
| Built-in Observability | ❌ | ✅ |

---

## Migration Path

### Self-Hosted → Managed AgentCore

1. Development complete on self-hosted
2. Deploy managed-agentcore infrastructure (Phase 1-2)
3. Configure environment (Phase 3)
4. Create runtime and test (Phase 4)

> **Note**: Core agent logic (graph, prompts, workflow) is shared. Tool implementations differ slightly - self-hosted uses local Python execution while managed-agentcore uses Custom Code Interpreter tool for Fargate-based execution.

### Key Differences in Code

| Component | Self-Hosted | Managed AgentCore |
|-----------|-------------|-------------------|
| Entry Point | `main.py` | `01_create_agentcore_runtime_vpc.py` |
| Code Execution Tool | Local Python tool | Custom Code Interpreter tool (Fargate) |
| Session Management | In-memory | Cookie-based (ALB) |
| Artifact Storage | Local `./artifacts/` | S3 bucket |

---

## Project Structure Comparison

### Self-Hosted

```
self-hosted/
├── main.py                  # 🚀 Entry point
├── src/                     # 🤖 Agent source code
│   ├── graph/               # Workflow definitions
│   ├── tools/               # Agent tools (local execution)
│   ├── prompts/             # System prompts
│   └── utils/               # Utilities
├── app/                     # 🖥️ Streamlit web interface
├── setup/                   # Environment setup (pyproject.toml)
├── data/                    # 📂 Input data files
└── artifacts/               # 📄 Output reports (local)
```

### Managed AgentCore

```
managed-agentcore/
├── 01_create_agentcore_runtime_vpc.py  # 🚀 Runtime creation
├── 02_invoke_agentcore_runtime_vpc.py  # Runtime testing
├── 03_download_artifacts.py            # Download from S3
│
├── src/                                # 🤖 Agent source code
│   ├── graph/                          # Workflow definitions
│   ├── tools/                          # Agent tools (Fargate execution)
│   ├── prompts/                        # System prompts
│   └── utils/                          # Utilities
│
├── fargate-runtime/                    # 🐳 Custom Code Interpreter
│   ├── code_executor_server.py         # HTTP server for code execution
│   ├── Dockerfile                      # Container image
│   └── requirements.txt                # Python dependencies
│
├── production_deployment/              # 🏗️ Infrastructure as Code
│   ├── cloudformation/                 # CloudFormation templates
│   ├── scripts/                        # Phase 1-4 deployment scripts
│   └── docs/                           # Deployment documentation
│
└── data/                               # 📂 Input data files
```

### Key Structural Differences

| Component | Self-Hosted | Managed AgentCore |
|-----------|-------------|-------------------|
| Entry Point | `main.py` | `01_create_agentcore_runtime_vpc.py` |
| Code Executor | `src/tools/` (local) | `fargate-runtime/` (container) |
| Infrastructure | None | `production_deployment/cloudformation/` |
| Deployment Scripts | `setup/` | `production_deployment/scripts/` |
| Web Interface | `app/` (Streamlit) | N/A (API-based) |
| Artifacts | `artifacts/` (local) | S3 bucket |

---

## Architecture Diagrams

### Self-Hosted

```
User → main.py → Strands Agent → Local Python Executor
                      ↓
              Amazon Bedrock API
```

### Managed AgentCore

```
User → AgentCore Runtime (VPC) → Internal ALB → Fargate Containers
              ↓                                        ↓
       Amazon Bedrock              Custom Code Interpreter
       (VPC Endpoint)              (Python/Bash execution)
```

---

**→ [Self-Hosted README](../../../self-hosted/README.md)** | **→ [Managed AgentCore README](../../README.md)**
