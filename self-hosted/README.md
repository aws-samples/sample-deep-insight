# Deep Insight: Self-Hosted Version

> Full control deployment with complete code access - run locally or in your own infrastructure

**Last Updated**: 2025-12-10

---

## 🎯 Overview

Self-hosted deployment option for Deep Insight - run agents locally or on your own infrastructure with full customization control. For the complete project overview, deployment comparison, and contribution guidelines, see the [root README](../README.md).

- **Full Control**: Complete code access to agents, prompts, and workflows
- **Rapid Iteration**: No rebuild required during development
- **Simple Setup**: Get started in ~10 minutes

---

## 🚀 Quick Start

### Tested Environments

macOS, Ubuntu, Amazon Linux

### Prerequisites

| Tool | Version | Check Command |
|------|---------|---------------|
| Python | 3.12+ | `python3 --version` |
| AWS CLI | v2.x | `aws --version` |

### Setup & Run

```bash
# 1. Clone repository
git clone https://github.com/aws-samples/sample-deep-insight.git
cd sample-deep-insight/self-hosted

# 2. Create environment
cd setup/ && ./create-uv-env.sh deep-insight 3.12 && cd ..

# 3. Configure AWS credentials (https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html)
aws configure

# 4. Copy environment file
cp .env.example .env

# 5. Run analysis
uv run python main.py --user_query "Analyze from sales and marketing perspectives, generate charts and extract insights. The analysis target is the './data/moon_market/kr/' directory. moon-market-fresh-food-sales.csv is the data file, and column_definitions.json contains column descriptions."
```

---

## 📊 Architecture

### Three-Tier Agent Hierarchy

```
User Query + Data Files (CSV, JSON)
    ↓
┌─────────────────────────────────────────────────────────┐
│  COORDINATOR (Entry Point)                              │
│  - Handles initial requests                             │
│  - Routes simple queries directly                       │
│  - Hands off complex tasks to Planner                   │
│  - Model: Claude Sonnet 4 (no reasoning)                │
└────────────────┬────────────────────────────────────────┘
                 ↓ (if complex)
┌─────────────────────────────────────────────────────────┐
│  PLANNER (Strategic Thinking)                           │
│  - Analyzes task complexity                             │
│  - Creates detailed execution plan                      │
│  - Model: Claude Sonnet 4 (reasoning enabled)           │
└────────────────┬────────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────────────────────────┐
│  SUPERVISOR (Task Orchestrator)                         │
│  - Delegates to specialized tool agents                 │
│  - Monitors progress and coordinates workflow           │
│  - Aggregates results                                   │
│  - Model: Claude Sonnet 4 (prompt caching)              │
└────────────────┬────────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────────────────────────┐
│  TOOL AGENTS                                            │
│  - Coder: Python/Bash execution for data analysis       │
│  - Reporter: Report formatting and DOCX generation      │
│  - Validator: Quality validation and verification       │
│  - Tracker: Progress monitoring                         │
└─────────────────────────────────────────────────────────┘
```

---

## ✨ Key Features

### Full Customization
- 🎨 **Complete Code Access** - Modify agents, prompts, and workflows directly
- 🧠 **Flexible Model Selection** - Choose different Claude models for each agent via `.env` configuration
- 🛠️ **Extensible Agents** - Add new agents or modify existing ones to fit your requirements

### Development Experience
- ⚡ **Rapid Iteration** - No rebuild required, changes take effect immediately
- 🔧 **Local Execution** - Run and debug agents on your local machine
- 📝 **Prompt Engineering** - System prompts stored as markdown files in `src/prompts/`

### Production Ready
- 📊 **Token Tracking** - Monitor input/output tokens and cache reads/writes per agent
- 🔄 **Streaming Responses** - Real-time event streaming for responsive UX
- 📄 **DOCX Reports** - Automatic editable Word document generation

### Multi-Agent Workflow
- 🤖 **Hierarchical Orchestration** - Coordinator → Planner → Supervisor architecture handles complex tasks automatically
- 🔀 **Smart Routing** - Simple queries handled directly, complex tasks delegated to specialized agents
- 📈 **Parallel Execution** - Tool agents work concurrently for faster results
- 🔍 **Built-in Validation** - Automatic result verification and citation generation

> 📖 **[Compare with Managed AgentCore →](../managed-agentcore/production_deployment/docs/DEPLOYMENT_COMPARISON.md)** When to choose each option

---

## 📁 Project Structure

```
.
├── main.py                  # CLI entry point (local mode)
├── web/                     # Web server (AWS deployment mode)
│   ├── app.py               # FastAPI server with SSE streaming
│   ├── event_adapter.py     # Engine event → SSE event adapter
│   └── hitl.py              # Human-in-the-loop plan review
├── infra/                   # AWS CDK infrastructure
│   ├── app.py               # CDK app entry point
│   ├── cdk.json             # CDK config (region, instance_type, etc.)
│   └── stacks/              # CloudFront + ALB + EC2 + Cognito
├── src/
│   ├── graph/               # Multi-agent workflow definitions
│   │   ├── builder.py       # Graph construction with Strands SDK
│   │   └── nodes.py         # Agent node implementations
│   ├── tools/               # Tool agent implementations
│   │   ├── coder_agent_tool.py
│   │   ├── reporter_agent_tool.py
│   │   ├── validator_agent_tool.py
│   │   └── tracker_agent_tool.py
│   ├── prompts/             # System prompts (*.md files)
│   └── utils/               # Utilities (event queue, strands utils)
├── setup/                   # Environment setup
│   ├── create-uv-env.sh
│   └── pyproject.toml
├── data/                    # Sample CSV data files
└── skills/                  # Skill templates
```

---

## 🔧 Use Your Own Data

### Directory Structure

Add your data files under the `data/` directory:

```
data/
└── your_project/
    ├── your_data.csv              # Your data file
    └── column_definitions.json    # Column descriptions (optional)
```

### Column Definitions (Optional)

Create `column_definitions.json` to help the agent understand your data:

```json
{
  "columns": {
    "date": "Transaction date in YYYY-MM-DD format",
    "product_name": "Name of the product sold",
    "quantity": "Number of units sold",
    "revenue": "Total revenue in USD"
  }
}
```

### Run Analysis

Your prompt should include:
1. **Analysis perspective**: What angle to analyze (e.g., sales, marketing, operations)
2. **Data path**: Full path to your CSV and JSON files

```bash
uv run python main.py --user_query "Analyze from sales and marketing perspectives, generate charts and extract insights. The analysis target is './data/your_project/' directory. your_data.csv is the data file, and column_definitions.json contains column descriptions."
```

> 📖 **[Prompt writing guide (Korean) →](https://www.linkedin.com/pulse/%EB%8D%B0%EC%9D%B4%ED%84%B0-%EB%B6%84%EC%84%9D-%EB%A6%AC%ED%8F%AC%ED%8A%B8-2-3%EC%9D%BC%EC%97%90%EC%84%9C-15%EB%B6%84%EC%9C%BC%EB%A1%9C-agentic-ai-%EC%8B%A4%EC%A0%84-%EC%9C%A0%EC%8A%A4%EC%BC%80%EC%9D%B4%EC%8A%A4-gonsoo-moon-nhlac/)** How to write effective analysis prompts

---

## 🔧 Change Agent Model IDs

Each agent can use a different Bedrock model. Configure model IDs in `.env`:

```bash
# Default model for all agents
DEFAULT_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0

# Use faster model for simple routing tasks
COORDINATOR_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0

# Use most capable model for complex planning
PLANNER_MODEL_ID=global.anthropic.claude-opus-4-5-20251101-v1:0

# Other agents
CODER_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0
VALIDATOR_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0
REPORTER_MODEL_ID=global.anthropic.claude-sonnet-4-5-20250929-v1:0
```

### Available Models

| Model | Model ID | Use Case |
|-------|----------|----------|
| Claude Opus 4.5 | `global.anthropic.claude-opus-4-5-20251101-v1:0` | Highest capability |
| Claude Sonnet 4.5 | `global.anthropic.claude-sonnet-4-5-20250929-v1:0` | Higher capability |
| Claude Sonnet 4 | `global.anthropic.claude-sonnet-4-20250514-v1:0` | Balanced |
| Claude Haiku 4.5 | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | Fast, lower cost |

> **Finding other models**: Use `aws bedrock list-foundation-models --query "modelSummaries[?providerName=='Anthropic'].[modelId,modelName]" --output table` or see [Amazon Bedrock Model IDs](https://docs.aws.amazon.com/bedrock/latest/userguide/model-ids.html)

Changes take effect immediately (no rebuild required).

---

## 🌐 Web Deployment (AWS)

Deploy to AWS and access via browser. Architecture: `Browser → CloudFront → ALB → EC2 (FastAPI)`.

### Prerequisites

- AWS CDK CLI **2.1107.0+** (`npm install -g aws-cdk@latest`)
- Python 3.12+, Node.js 18+, AWS CLI v2

### Deploy

```bash
# 1. Configure — set your email, origin_verify_secret auto-generates on first deploy
cd self-hosted/infra
# Edit cdk.json: set "admin_email" to your email

# 2. Infrastructure
pip install -r requirements.txt
cdk bootstrap aws://ACCOUNT_ID/REGION
cdk deploy --all
# → Note the outputs: CloudFrontURL, Ec2InstanceId, OriginVerifySecret, etc.

# 3. App code → EC2
cd ../..  # back to sample-deep-insight/
COPYFILE_DISABLE=1 tar czf /tmp/deep-insight-deploy.tar.gz \
  --exclude='__pycache__' --exclude='.venv' --exclude='*.pyc' \
  --exclude='artifacts/*.png' --exclude='artifacts/*.docx' --exclude='artifacts/*.txt' \
  --exclude='artifacts/*.json' --exclude='data/uploads/*' \
  --exclude='infra/cdk.out' --exclude='setup/.venv' \
  --exclude='setup/install-tl-*' --exclude='._*' \
  --exclude='.git' --exclude='*.backup' \
  self-hosted/ deep-insight-web/

aws s3 cp /tmp/deep-insight-deploy.tar.gz \
  s3://cdk-hnb659fds-assets-ACCOUNT_ID-REGION/deploy/deep-insight-deploy.tar.gz

aws ssm send-command --instance-ids EC2_INSTANCE_ID \
  --document-name AWS-RunShellScript \
  --parameters '{"commands":[
    "aws s3 cp s3://cdk-hnb659fds-assets-ACCOUNT_ID-REGION/deploy/deep-insight-deploy.tar.gz /tmp/deploy.tar.gz --region REGION",
    "tar xzf /tmp/deploy.tar.gz -C /opt/deep-insight/",
    "export PATH=/root/.local/bin:$PATH && cd /opt/deep-insight/self-hosted/setup && uv sync"
  ]}' --region REGION

# 4. .env.deploy — fill CDK output values, then start service
#    (see .env.deploy template below)
#    systemctl restart deep-insight

# 5. Open CloudFrontURL in browser
```

### .env.deploy template

Create on EC2 at `/opt/deep-insight/self-hosted/.env.deploy` with CDK output values:

```
ORIGIN_VERIFY_SECRET=<OriginVerifySecret output>
COGNITO_DOMAIN=<CognitoDomainURL output>
COGNITO_CLIENT_ID=<AppClientId output>
COGNITO_REDIRECT_URI=<CloudFrontURL output>/auth/callback
COGNITO_USER_POOL_ID=<UserPoolId output>
WEB_PORT=8080
AWS_REGION=<your region>
AWS_DEFAULT_REGION=<your region>
MAX_PLAN_REVISIONS=10
DEFAULT_MODEL_ID=us.anthropic.claude-sonnet-4-6
COORDINATOR_MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
PLANNER_MODEL_ID=us.anthropic.claude-sonnet-4-6
SUPERVISOR_MODEL_ID=us.anthropic.claude-sonnet-4-6
CODER_MODEL_ID=us.anthropic.claude-sonnet-4-6
VALIDATOR_MODEL_ID=us.anthropic.claude-sonnet-4-6
REPORTER_MODEL_ID=us.anthropic.claude-sonnet-4-6
TRACKER_MODEL_ID=us.anthropic.claude-sonnet-4-6
```

> Model ID prefix: `us.anthropic.*` for us-east-1/us-west-2, `global.anthropic.*` for cross-region. Check available IDs: `aws bedrock list-inference-profiles --region REGION`

### Redeploy (code only)

```bash
# Package + upload (same as step 3), then:
aws ssm send-command --instance-ids EC2_INSTANCE_ID \
  --document-name AWS-RunShellScript \
  --parameters '{"commands":[
    "aws s3 cp s3://cdk-hnb659fds-assets-ACCOUNT_ID-REGION/deploy/deep-insight-deploy.tar.gz /tmp/deploy.tar.gz --region REGION",
    "tar xzf /tmp/deploy.tar.gz -C /opt/deep-insight/",
    "systemctl restart deep-insight"
  ]}' --region REGION
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `schema version mismatch` | `npm install -g aws-cdk@latest` (need CDK CLI 2.1107.0+) |
| `model identifier is invalid` | Check model ID with `aws bedrock list-inference-profiles` |
| Logo missing | Ensure tar excludes `artifacts/*.png` not `*.png` |
| `Reports not available yet` | Check EC2 logs: `journalctl -u deep-insight --since "10 min ago"` |

### Cost (~$176/month)

EC2 t3.xlarge ~$120 + NAT Gateway ~$35 + ALB ~$20 + CloudFront ~$1

---

## 🛠️ Modify Agent Prompts

System prompts are stored as markdown files in `src/prompts/`:

```
src/prompts/
├── coordinator.md    # Entry point agent
├── planner.md        # Planning agent
├── supervisor.md     # Task orchestration
├── coder.md          # Code execution
├── reporter.md       # Report generation
└── validator.md      # Result validation
```

Edit these files to customize agent behavior. Changes take effect immediately (no rebuild required).

---

## 📝 License

MIT License - see the [LICENSE](../LICENSE) file for details.

---

> 📖 For contributing guidelines, acknowledgments, and full project documentation, see the [root README](../README.md).