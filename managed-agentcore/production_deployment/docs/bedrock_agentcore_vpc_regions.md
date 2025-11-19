# AWS Bedrock AgentCore VPC Mode - Region & Availability Zone Guide

**Last Updated**: 2025-11-08  
**Source**: [AWS Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)

---

## 📍 Supported Regions (9 Total)

Amazon Bedrock AgentCore with VPC mode is available in **9 AWS Regions**:

### Americas (3)
- 🇺🇸 **US East (N. Virginia)** - `us-east-1`
- 🇺🇸 **US East (Ohio)** - `us-east-2`
- 🇺🇸 **US West (Oregon)** - `us-west-2`

### Asia Pacific (4)
- 🇮🇳 **Asia Pacific (Mumbai)** - `ap-south-1`
- 🇸🇬 **Asia Pacific (Singapore)** - `ap-southeast-1`
- 🇦🇺 **Asia Pacific (Sydney)** - `ap-southeast-2`
- 🇯🇵 **Asia Pacific (Tokyo)** - `ap-northeast-1`

### Europe (2)
- 🇮🇪 **Europe (Ireland)** - `eu-west-1`
- 🇩🇪 **Europe (Frankfurt)** - `eu-central-1`

---

## 🔍 Supported Availability Zones for VPC Mode

⚠️ **CRITICAL**: Only specific AZ IDs are supported per region. Using unsupported AZs will cause configuration failures.

| Region | Region Code | Supported AZ IDs | Count |
|--------|------------|------------------|-------|
| US East (N. Virginia) | `us-east-1` | `use1-az1`, `use1-az2`, `use1-az4` | 3 |
| US East (Ohio) | `us-east-2` | `use2-az1`, `use2-az2`, `use2-az3` | 3 |
| US West (Oregon) | `us-west-2` | `usw2-az1`, `usw2-az2`, `usw2-az3` | 3 |
| Asia Pacific (Mumbai) | `ap-south-1` | `aps1-az1`, `aps1-az2`, `aps1-az3` | 3 |
| Asia Pacific (Singapore) | `ap-southeast-1` | `apse1-az1`, `apse1-az2`, `apse1-az3` | 3 |
| Asia Pacific (Sydney) | `ap-southeast-2` | `apse2-az1`, `apse2-az2`, `apse2-az3` | 3 |
| Asia Pacific (Tokyo) | `ap-northeast-1` | `apne1-az1`, `apne1-az2`, `apne1-az4` | 3 |
| Europe (Ireland) | `eu-west-1` | `euw1-az1`, `euw1-az2`, `euw1-az3` | 3 |
| Europe (Frankfurt) | `eu-central-1` | `euc1-az1`, `euc1-az2`, `euc1-az3` | 3 |

---

## 🗺️ AZ ID to AZ Name Mapping

**Important**: AZ IDs (e.g., `use1-az1`) are **consistent across accounts**, while AZ names (e.g., `us-east-1a`) **vary per account**.

### How to Find Your AZ Names from AZ IDs

```bash
# List all AZs in a region with their IDs
aws ec2 describe-availability-zones --region us-east-1 \
  --query 'AvailabilityZones[*].{Name:ZoneName, ID:ZoneId}' \
  --output table

# Example output for us-east-1:
# ----------------------------------
# |  Name        |  ID            |
# ----------------------------------
# |  us-east-1a  |  use1-az1      |  ✅ Supported
# |  us-east-1b  |  use1-az2      |  ✅ Supported
# |  us-east-1c  |  use1-az5      |  ❌ NOT supported (use1-az5)
# |  us-east-1d  |  use1-az4      |  ✅ Supported
# ----------------------------------
```

**Note**: In the example above, `us-east-1c` maps to `use1-az5` which is **NOT** in the supported list. You must use AZs that map to `use1-az1`, `use1-az2`, or `use1-az4`.

---

## 🎯 Practical Deployment Guide

### Your Current Production Setup (us-east-1)

```bash
# Check your current subnet AZ IDs
aws ec2 describe-subnets \
  --subnet-ids subnet-018b0810d92f3fcdc subnet-0e2f3fa18969bf917 \
  --region us-east-1 \
  --query 'Subnets[*].{ID:SubnetId, AZ:AvailabilityZone, AZID:AvailabilityZoneId}' \
  --output table

# Expected output:
# subnet-018b0810d92f3fcdc | us-east-1a | use1-az1  ✅ Supported
# subnet-0e2f3fa18969bf917 | us-east-1b | use1-az2  ✅ Supported
```

✅ **Your production deployment is correct!** Both AZs are supported.

---

### Deploying to us-west-2

**Step 1: Identify Supported AZs**
```bash
# Get AZ mapping for us-west-2
aws ec2 describe-availability-zones --region us-west-2 \
  --query 'AvailabilityZones[*].{Name:ZoneName, ID:ZoneId}' \
  --output table
```

**Expected AZ IDs for us-west-2**:
- `usw2-az1` ✅ Supported
- `usw2-az2` ✅ Supported
- `usw2-az3` ✅ Supported
- `usw2-az4` ❌ NOT supported

**Step 2: Choose AZ Names That Map to Supported IDs**

```bash
# Example mapping (varies per account):
# us-west-2a → usw2-az1  ✅ Use this
# us-west-2b → usw2-az2  ✅ Use this
# us-west-2c → usw2-az3  ✅ Use this
# us-west-2d → usw2-az4  ❌ Don't use this
```

**Step 3: Update CloudFormation Parameters**

```bash
# Deploy with correct AZs for your account
./scripts/phase1/deploy.sh prod \
  --region us-west-2 \
  --parameter-overrides \
    AvailabilityZone1=us-west-2a \
    AvailabilityZone2=us-west-2b
```

---

## ⚠️ Common Pitfalls

### 1. Using Unsupported AZ IDs
**Problem**: CloudFormation deployment fails with "Unsupported Availability Zone"

**Example (us-east-1)**:
```
❌ use1-az3 - NOT supported (even if us-east-1c exists in your account)
❌ use1-az5 - NOT supported
❌ use1-az6 - NOT supported
✅ use1-az1, use1-az2, use1-az4 - Supported
```

**Solution**: Always check AZ ID mapping, not just AZ names.

### 2. Assuming AZ Names Are Consistent
**Problem**: `us-east-1a` might be `use1-az1` in Account A but `use1-az2` in Account B.

**Solution**: Use AWS CLI to get the exact mapping for your account.

### 3. Not Using Minimum 2 AZs
**Problem**: Single-AZ deployments fail high availability requirements.

**Solution**: Always configure at least 2 subnets in different supported AZs.

---

## 🔧 CloudFormation Template Updates

### Current Hardcoded Approach (Not Region-Agnostic)

```yaml
# phase1-main.yaml
Parameters:
  AvailabilityZone1:
    Type: AWS::EC2::AvailabilityZone::Name
    Default: us-east-1a  # ❌ Hardcoded, breaks in other regions
```

### Recommended: Dynamic AZ Selection

**Option A: Use Fn::GetAZs (Simple)**
```yaml
# In network.yaml
Resources:
  PrivateSubnet1:
    Type: AWS::EC2::Subnet
    Properties:
      AvailabilityZone: !Select [0, !GetAZs '']  # First available AZ
      # ⚠️ May select unsupported AZ!
```

**Option B: Parameter with Validation (Better)**
```yaml
Parameters:
  AvailabilityZone1:
    Type: AWS::EC2::AvailabilityZone::Name
    Description: |
      First Availability Zone (must be supported for AgentCore VPC)
      us-east-1: use1-az1, use1-az2, use1-az4
      us-west-2: usw2-az1, usw2-az2, usw2-az3
      See: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html
    # No default - forces user to specify correct AZ
```

**Option C: Mappings (Best for Multi-Region)**
```yaml
Mappings:
  RegionAZs:
    us-east-1:
      AZ1: us-east-1a  # Your account-specific mapping
      AZ2: us-east-1b
    us-west-2:
      AZ1: us-west-2a
      AZ2: us-west-2b
    eu-west-1:
      AZ1: eu-west-1a
      AZ2: eu-west-1b

Resources:
  PrivateSubnet1:
    Type: AWS::EC2::Subnet
    Properties:
      AvailabilityZone: !FindInMap [RegionAZs, !Ref 'AWS::Region', AZ1]
```

---

## 📊 Region Selection Criteria

### Choose Your Region Based On:

**1. Latency**
- Deploy in region closest to your users
- Use [CloudPing](https://www.cloudping.info/) to test latency

**2. Data Residency**
- EU customers: Use `eu-west-1` or `eu-central-1`
- Asia customers: Use `ap-southeast-1`, `ap-northeast-1`, etc.

**3. Cost**
- Pricing varies slightly by region
- US regions typically cheapest
- Check [AWS Pricing Calculator](https://calculator.aws/)

**4. Disaster Recovery**
- Use 2 regions for DR (e.g., `us-east-1` + `us-west-2`)
- Ensure both support AgentCore VPC mode

---

## 🔍 Verification Script

```bash
#!/bin/bash
# verify_agentcore_azs.sh - Verify your AZs are supported

REGION="${1:-us-east-1}"

echo "Checking AgentCore VPC supported AZs for region: $REGION"
echo ""

# Define supported AZ IDs per region
declare -A SUPPORTED_AZS
SUPPORTED_AZS[us-east-1]="use1-az1 use1-az2 use1-az4"
SUPPORTED_AZS[us-east-2]="use2-az1 use2-az2 use2-az3"
SUPPORTED_AZS[us-west-2]="usw2-az1 usw2-az2 usw2-az3"
SUPPORTED_AZS[ap-south-1]="aps1-az1 aps1-az2 aps1-az3"
SUPPORTED_AZS[ap-southeast-1]="apse1-az1 apse1-az2 apse1-az3"
SUPPORTED_AZS[ap-southeast-2]="apse2-az1 apse2-az2 apse2-az3"
SUPPORTED_AZS[ap-northeast-1]="apne1-az1 apne1-az2 apne1-az4"
SUPPORTED_AZS[eu-west-1]="euw1-az1 euw1-az2 euw1-az3"
SUPPORTED_AZS[eu-central-1]="euc1-az1 euc1-az2 euc1-az3"

# Get current AZs
aws ec2 describe-availability-zones --region "$REGION" \
  --query 'AvailabilityZones[*].[ZoneName,ZoneId]' \
  --output text | while read AZ_NAME AZ_ID; do
  
  # Check if AZ ID is supported
  if [[ " ${SUPPORTED_AZS[$REGION]} " =~ " $AZ_ID " ]]; then
    echo "✅ $AZ_NAME ($AZ_ID) - SUPPORTED"
  else
    echo "❌ $AZ_NAME ($AZ_ID) - NOT SUPPORTED"
  fi
done

echo ""
echo "Supported AZ IDs for $REGION: ${SUPPORTED_AZS[$REGION]}"
```

**Usage**:
```bash
cd production_deployment/scripts/phase1
chmod +x verify_agentcore_azs.sh
./verify_agentcore_azs.sh us-east-1
./verify_agentcore_azs.sh us-west-2
```

---

## 📝 Summary

**Key Takeaways**:

1. ✅ **9 regions** support Bedrock AgentCore VPC mode
2. ✅ Each region has **3 supported AZ IDs** (except us-east-1 and ap-northeast-1)
3. ⚠️ **AZ names vary per account** - always check AZ ID mapping
4. ❌ Using unsupported AZ IDs will **fail during deployment**
5. 📍 **Minimum 2 AZs** required for high availability

**For Production**:
- Always verify AZ IDs before deployment
- Use account-specific AZ name mappings
- Document your region/AZ choices
- Test in target region before production rollout

---

**References**:
- [AgentCore VPC Configuration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)
- [AgentCore Regions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html)
- [AWS Availability Zones](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-regions-availability-zones.html)

