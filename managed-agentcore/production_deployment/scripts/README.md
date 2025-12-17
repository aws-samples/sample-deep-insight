# Deployment Scripts Reference

> Quick reference for all deployment and cleanup scripts

**→ Back to [Main README](../../README.md)**

---

## 📋 Prerequisites

```bash
# AWS CLI v2
aws --version   # aws-cli/2.x.x required

# jq (JSON processor)
jq --version    # Required for parsing CloudFormation outputs

# Install if missing (Ubuntu/Debian)
sudo apt-get update && sudo apt-get install -y jq
```

---

## 📂 Script Overview

| Script | Purpose |
|--------|---------|
| `deploy_phase1_phase2.sh` | Deploy Phase 1 + 2 (auto-detect AZs) |
| `cleanup_all.sh` | Delete all resources (Phase 4 → 1) |
| `phase1/deploy.sh` | Deploy VPC infrastructure |
| `phase1/verify.sh` | Verify Phase 1 resources |
| `phase1/verify_agentcore_azs.sh` | Check supported AZs |
| `phase1/cleanup.sh` | Delete Phase 1 resources |
| `phase2/deploy.sh` | Deploy Fargate runtime |
| `phase2/verify.sh` | Verify Phase 2 resources |
| `phase2/cleanup.sh` | Delete Phase 2 resources |
| `phase3/01_extract_env_vars_from_cf.sh` | Generate .env from CloudFormation |
| `phase3/02_create_uv_env.sh` | Setup UV environment |
| `phase3/03_patch_dockerignore.sh` | Patch toolkit template |
| `phase4/cleanup.sh` | Delete AgentCore runtime |

---

## 🚀 deploy_phase1_phase2.sh

Automated deployment of Phase 1 + 2 with AZ auto-detection.

```bash
./deploy_phase1_phase2.sh <environment> <region>
```

**Examples:**
```bash
./deploy_phase1_phase2.sh prod us-west-2
./deploy_phase1_phase2.sh dev us-east-1
```

---

## 🗑️ cleanup_all.sh

Delete all resources in correct order (Phase 4 → 3 → 2 → 1).

```bash
./cleanup_all.sh <environment> <region>
```

**Example:**
```bash
./cleanup_all.sh prod us-west-2
```

---

## 📦 Phase 1 Scripts

### deploy.sh

```bash
cd phase1
./deploy.sh <environment> [options]
```

**Options:**
- `--region <region>` - AWS region
- `--parameter-overrides Key=Value` - Override CloudFormation parameters

**Example:**
```bash
./deploy.sh prod --region us-west-2
```

### verify_agentcore_azs.sh

Check which AZs support AgentCore VPC mode in your account.

```bash
cd phase1
./verify_agentcore_azs.sh <region>
```

### verify.sh / cleanup.sh

```bash
cd phase1
./verify.sh <environment> --region <region>
./cleanup.sh <environment> --region <region>
```

---

## 🐳 Phase 2 Scripts

### deploy.sh

```bash
cd phase2
./deploy.sh <environment> [options]
```

**Options:**
- `--region <region>` - AWS region
- `--stage <1|2|all>` - Deployment stage
  - `1`: ECR only
  - `2`: Docker build + ECS
  - `all`: Full deployment (default)

**Examples:**
```bash
./deploy.sh prod                    # Full deployment
./deploy.sh prod --stage 2          # Rebuild Docker image only
```

### verify.sh / cleanup.sh

```bash
cd phase2
./verify.sh <environment> --region <region>
./cleanup.sh <environment> --region <region>
```

---

## 📋 Phase 3 Scripts

### 01_extract_env_vars_from_cf.sh

Generate `.env` file from CloudFormation outputs.

```bash
cd phase3
./01_extract_env_vars_from_cf.sh <environment> <region>
```

**Example:**
```bash
./01_extract_env_vars_from_cf.sh prod us-west-2
```

### 02_create_uv_env.sh

Setup UV virtual environment.

```bash
cd phase3
./02_create_uv_env.sh <env-name>
```

**Example:**
```bash
./02_create_uv_env.sh deep-insight
```

### 03_patch_dockerignore.sh

Patch toolkit template to include prompts in Docker builds.

```bash
cd phase3
./03_patch_dockerignore.sh
```

---

## 🤖 Phase 4 Scripts

Phase 4 uses Python scripts from the project root:

```bash
uv run 01_create_agentcore_runtime_vpc.py  # Create runtime
uv run 02_invoke_agentcore_runtime_vpc.py  # Test runtime
uv run 03_download_artifacts.py            # Download results
```

### cleanup.sh

```bash
cd phase4
./cleanup.sh <environment> --region <region>
```

---

## 🛠️ Troubleshooting

### "Unsupported Availability Zone"

Run `./phase1/verify_agentcore_azs.sh <region>` and use only SUPPORTED AZs.

### "Stack not found" in Phase 3

Verify you're using the correct region where stacks were deployed:
```bash
aws cloudformation list-stacks --region <region>
```

### "Network interface in use" during cleanup

Delete in reverse order: Phase 4 → 3 → 2 → 1. If stuck, wait for ENIs to release (~6 hours after AgentCore runtime deletion).

### Docker build fails in Phase 2

Run `./phase3/03_patch_dockerignore.sh` before Phase 2 deployment.

### "Invalid type for parameter" during deployment

**Symptom:**
```
Invalid type for parameter [0], value: OrderedDict([('ParameterKey', 'Environment'), ...
```

**Cause:** Outdated AWS CLI version.

**Solution:** Update AWS CLI:
```bash
# Check current version
aws --version

# Update AWS CLI (Linux)
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install --update

# Verify update
aws --version
```

---

**→ Back to [Main README](../../README.md)**
