# Multi-Region and Multi-Account Deployment Guide

**Last Updated**: 2025-11-08
**Purpose**: Deploy Deep Insight infrastructure to different AWS regions and accounts

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Key Concepts](#key-concepts)
3. [Pre-Deployment Verification](#pre-deployment-verification)
4. [Deployment Workflow](#deployment-workflow)
5. [Region-Specific Configurations](#region-specific-configurations)
6. [Account-Specific Considerations](#account-specific-considerations)
7. [Troubleshooting](#troubleshooting)

---

## 🎯 Overview

This guide explains how to deploy the Deep Insight CloudFormation stacks across:
- **Different AWS Regions** (9 supported regions)
- **Different AWS Accounts** (development, staging, production)

### Why This Guide Exists

**Critical Issue**: Availability Zone (AZ) names like `us-east-1a` are **account-specific**. The same AZ name maps to different physical datacenters in different AWS accounts.

**Example**:
```
Account A:  us-east-1a → use1-az4 ✅ Supported by AgentCore
Account B:  us-east-1a → use1-az6 ❌ NOT supported by AgentCore
```

Using the same hardcoded AZ name across accounts will cause failures.

---

## 🔑 Key Concepts

### Availability Zone IDs vs Names

| Concept | Consistency | Example | Usage |
|---------|-------------|---------|-------|
| **AZ ID** | Globally consistent | `use1-az1` | Same across all AWS accounts |
| **AZ Name** | Account-specific | `us-east-1a` | Varies per AWS account |

**AgentCore VPC Requirement**: Only specific AZ IDs are supported per region.

### Supported Regions and AZ IDs

| Region | Region Code | Supported AZ IDs |
|--------|------------|------------------|
| US East (N. Virginia) | `us-east-1` | `use1-az1`, `use1-az2`, `use1-az4` |
| US East (Ohio) | `us-east-2` | `use2-az1`, `use2-az2`, `use2-az3` |
| US West (Oregon) | `us-west-2` | `usw2-az1`, `usw2-az2`, `usw2-az3` |
| Asia Pacific (Mumbai) | `ap-south-1` | `aps1-az1`, `aps1-az2`, `aps1-az3` |
| Asia Pacific (Singapore) | `ap-southeast-1` | `apse1-az1`, `apse1-az2`, `apse1-az3` |
| Asia Pacific (Sydney) | `ap-southeast-2` | `apse2-az1`, `apse2-az2`, `apse2-az3` |
| Asia Pacific (Tokyo) | `ap-northeast-1` | `apne1-az1`, `apne1-az2`, `apne1-az4` |
| Europe (Ireland) | `eu-west-1` | `euw1-az1`, `euw1-az2`, `euw1-az3` |
| Europe (Frankfurt) | `eu-central-1` | `euc1-az1`, `euc1-az2`, `euc1-az3` |

**See also**: `bedrock_agentcore_vpc_regions.md` for detailed AZ documentation.

---

## ✅ Pre-Deployment Verification

### Step 1: Run AZ Verification Script

**Before deploying to ANY account or region**, verify which AZ names in that account map to supported AZ IDs.

```bash
# Navigate to phase1 directory
cd production_deployment/scripts/phase1

# Run verification for your target region
./verify_agentcore_azs.sh us-east-1
```

**Example Output**:
```
================================================================
AgentCore VPC - Availability Zone Verification Tool
================================================================

Region: us-east-1

✅ Region 'us-east-1' supports AgentCore VPC mode

Supported AZ IDs for us-east-1: use1-az1 use1-az2 use1-az4

================================================================
Checking YOUR account's AZ name mapping...
================================================================

✅ us-east-1a → use1-az4 (SUPPORTED)
❌ us-east-1b → use1-az6 (NOT SUPPORTED)
✅ us-east-1c → use1-az1 (SUPPORTED)
✅ us-east-1d → use1-az2 (SUPPORTED)

================================================================
Summary for YOUR AWS Account in us-east-1
================================================================

✅ Found 3 supported AZ(s) in your account

Use these AZ names for CloudFormation deployment:

  AvailabilityZone1=us-east-1a
  AvailabilityZone2=us-east-1c

================================================================
CloudFormation Deployment Command
================================================================

Deploy Phase 1 with the verified AZs:

  cd production_deployment/scripts/phase1
  ./deploy.sh prod \
    --region us-east-1 \
    --parameter-overrides \
      AvailabilityZone1=us-east-1a \
      AvailabilityZone2=us-east-1c
```

### Step 2: Document Your Account's AZ Mapping

Create a reference document for each account:

```bash
# Production Account (738490718699, us-east-1)
AvailabilityZone1=us-east-1a  # use1-az4 ✅
AvailabilityZone2=us-east-1c  # use1-az1 ✅

# Development Account (057716757052, us-east-1)
AvailabilityZone1=us-east-1a  # use1-az2 ✅
AvailabilityZone2=us-east-1b  # use1-az1 ✅
```

**Note**: Same AZ name (`us-east-1a`) maps to different AZ IDs in different accounts!

---

## 🚀 Deployment Workflow

### Option A: Automated Deployment (Recommended)

Use the automated deployment script that handles AZ verification and deployment in one command:

```bash
cd production_deployment/scripts

# Deploy Phase 1 + Phase 2 (auto-detects supported AZs)
./deploy_phase1_phase2.sh prod us-west-2
```

**What the script does**:
1. ✅ Verifies AWS credentials and account
2. ✅ Checks if region supports AgentCore VPC mode
3. ✅ Automatically finds supported AZ names in YOUR account
4. ✅ Shows deployment plan and asks for confirmation
5. ✅ Calls phase1/deploy.sh with correct AZ parameters
6. ✅ Calls phase2/deploy.sh
7. ✅ Runs verification after each phase

**Example Session**:
```
$ ./deploy_phase1_phase2.sh prod us-west-2

================================================================
Deep Insight - Automated Multi-Region Deployment
================================================================

Environment: prod
Region:      us-west-2

Step 1: Verifying AWS credentials...
  ✅ AWS Account ID: 738490718699
  ✅ Default Region: us-east-1

Step 2: Verifying Availability Zone support...
  ✅ Region 'us-west-2' supports AgentCore VPC mode
  Supported AZ IDs: usw2-az1 usw2-az2 usw2-az3

Step 3: Finding supported AZs in your account...
  ✅ us-west-2a → usw2-az1 (SUPPORTED)
  ✅ us-west-2b → usw2-az2 (SUPPORTED)
  ✅ us-west-2c → usw2-az3 (SUPPORTED)
  ⚠️  us-west-2d → usw2-az4 (not supported)

✅ Found 3 supported AZ(s)

Will use for deployment:
  AvailabilityZone1: us-west-2a
  AvailabilityZone2: us-west-2b

Step 4: Deployment confirmation

You are about to deploy Deep Insight infrastructure:
  Environment:         prod
  Region:              us-west-2
  AWS Account:         738490718699
  Availability Zone 1: us-west-2a
  Availability Zone 2: us-west-2b

This will deploy:
  ✅ Phase 1: VPC, Security Groups, VPC Endpoints, ALB, IAM (~30-40 min)
  ✅ Phase 2: ECR, Docker Image, ECS Cluster, Task Definition (~15-20 min)

Continue with deployment? (yes/no): yes

Step 5: Deploying Phase 1 (Infrastructure)
[CloudFormation deployment proceeds...]

Step 6: Deploying Phase 2 (Fargate Runtime)
[Docker build and deployment proceeds...]
```

### Option B: Manual Deployment

If you prefer manual control over each step:

#### 1. Verify AZ Support

```bash
# Example: Deploying to us-west-2
cd production_deployment/scripts/phase1
./verify_agentcore_azs.sh us-west-2
```

#### 2. Note the Verified AZ Names

From the script output, capture the AZ names for your deployment:
```
AvailabilityZone1=us-west-2a
AvailabilityZone2=us-west-2b
```

#### 3. Deploy Phase 1

```bash
cd scripts/phase1

# Deploy with explicit AZ parameters
./deploy.sh prod \
  --region us-west-2 \
  --parameter-overrides \
    AvailabilityZone1=us-west-2a \
    AvailabilityZone2=us-west-2b
```

#### 4. Continue with Phase 2 and 3

```bash
# Phase 2: Fargate Runtime
cd ../phase2
./deploy.sh prod --region us-west-2

# Phase 3: AgentCore Runtime
cd ../../
uv run create_agentcore_runtime_vpc.py
```

### Deploying to a New Account

#### Automated Approach (Recommended)

```bash
# 1. Switch to the target account
aws configure --profile production
export AWS_PROFILE=production

# 2. Verify account
aws sts get-caller-identity

# 3. Deploy Phase 1 + 2 (auto-detects AZs for THIS account)
cd production_deployment/scripts
./deploy_phase1_phase2.sh prod us-east-1

# The script will automatically find the correct AZ names
# for THIS account's AZ ID mappings!
```

#### Manual Approach

```bash
# 1. Configure AWS Credentials
aws configure --profile production
export AWS_PROFILE=production

# Verify
aws sts get-caller-identity

# 2. Verify AZs for This Account
# Each account has different AZ name → AZ ID mappings!
cd production_deployment/scripts/phase1
./verify_agentcore_azs.sh us-east-1

# 3. Deploy Phase 1 with Account-Specific AZ Names
# Use the AZ names from the verification output
./deploy.sh prod \
  --region us-east-1 \
  --parameter-overrides \
    AvailabilityZone1=<from_verification> \
    AvailabilityZone2=<from_verification>

# 4. Deploy Phase 2
cd ../phase2
./deploy.sh prod
```

---

## 🔧 Region-Specific Configurations

### VPC CIDR Considerations

If deploying to multiple regions in the same account, use **non-overlapping CIDR blocks**:

```bash
# us-east-1 (Production)
VpcCidr=10.0.0.0/16
PrivateSubnet1Cidr=10.0.1.0/24
PrivateSubnet2Cidr=10.0.2.0/24

# us-west-2 (DR/Backup)
VpcCidr=10.1.0.0/16
PrivateSubnet1Cidr=10.1.1.0/24
PrivateSubnet2Cidr=10.1.2.0/24
```

### ECR Repository Naming

ECR repositories are **region-specific**. Same name can be used across regions:

```bash
# Both regions can have:
ECR_REPO=deep-insight-fargate-runtime-prod

# But URIs will be different:
us-east-1: 738490718699.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod
us-west-2: 738490718699.dkr.ecr.us-west-2.amazonaws.com/deep-insight-fargate-runtime-prod
```

### S3 Bucket Naming

S3 bucket names are **globally unique**. Use region suffix:

```bash
# us-east-1
S3BucketName=bedrock-logs-prod-738490718699-us-east-1

# us-west-2
S3BucketName=bedrock-logs-prod-738490718699-us-west-2
```

---

## 🔐 Account-Specific Considerations

### IAM Role Names

IAM role names are **account-specific** but must be unique within an account.

For multiple environments in the same account:

```bash
# Development environment
TaskRoleName=deep-insight-task-role-dev
ExecutionRoleName=deep-insight-task-execution-role-dev

# Production environment (different account)
TaskRoleName=deep-insight-task-role-prod
ExecutionRoleName=deep-insight-task-execution-role-prod
```

### Cross-Account ECR Access

If using a centralized ECR repository in one account:

1. **ECR Repository Policy** (in central account):
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "AWS": "arn:aws:iam::TARGET_ACCOUNT_ID:root"
    },
    "Action": [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability"
    ]
  }]
}
```

2. **Task Execution Role** (in target account):
```yaml
# Add permission to assume role for ECR access
- Effect: Allow
  Action:
    - ecr:GetAuthorizationToken
    - ecr:BatchCheckLayerAvailability
    - ecr:GetDownloadUrlForLayer
    - ecr:BatchGetImage
  Resource: "*"
```

---

## 🛠️ Troubleshooting

### Error: "Unsupported Availability Zone"

**Symptom**:
```
CloudFormation Stack CREATE_FAILED
Error: The specified availability zone is not supported for AgentCore VPC mode
```

**Cause**: The AZ name you specified maps to an unsupported AZ ID in your account.

**Solution**:
1. Run the verification script: `cd phase1 && ./verify_agentcore_azs.sh <region>`
2. Use only the AZ names marked as "SUPPORTED"
3. Update your CloudFormation parameters

### Error: "AZ ID Mismatch Between Accounts"

**Symptom**: Deployment works in Account A but fails in Account B with same AZ names.

**Cause**: Same AZ name maps to different AZ IDs in different accounts.

**Example**:
```
Account A:  us-east-1a → use1-az4 ✅ Supported
Account B:  us-east-1a → use1-az6 ❌ NOT Supported
```

**Solution**:
- Never copy AZ names between accounts
- Always run verification script for each account
- Document account-specific AZ mappings

### Error: "VPC Endpoint Not Available"

**Symptom**: VPC Endpoint creation fails for bedrock-agentcore service.

**Cause**: Region does not support Bedrock AgentCore VPC mode.

**Solution**:
- Verify region is in the supported list (9 regions)
- See `bedrock_agentcore_vpc_regions.md` for complete list
- Choose a different region if needed

---

## 📚 Additional Resources

- **AZ Verification Script**: `scripts/phase1/verify_agentcore_azs.sh`
- **Region/AZ Documentation**: `docs/bedrock_agentcore_vpc_regions.md`
- **CloudFormation Parameters**: `cloudformation/phase1-main.yaml` (lines 19-58)
- **Deployment Scripts**: `scripts/phase1/deploy.sh`, `scripts/phase2/deploy.sh`

---

## ✅ Deployment Checklist

Before deploying to a new region or account:

- [ ] Run `phase1/verify_agentcore_azs.sh` for target region
- [ ] Document verified AZ names for the account
- [ ] Update VPC CIDR if deploying multiple regions
- [ ] Update S3 bucket name with region suffix
- [ ] Verify IAM role names don't conflict
- [ ] Test deployment in development environment first
- [ ] Update `.env` file with new region/account values
- [ ] Backup existing `.env` before changes

---

**Best Practice**: Always run the verification script before any deployment. Never assume AZ names from one account will work in another.
