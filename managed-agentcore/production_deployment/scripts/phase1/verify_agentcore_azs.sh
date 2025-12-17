#!/bin/bash
# verify_agentcore_azs.sh - Verify your AZs are supported for Bedrock AgentCore VPC mode
# Usage: ./verify_agentcore_azs.sh [region]
# Example: ./verify_agentcore_azs.sh us-east-1

set -e

REGION="${1:-us-east-1}"

echo "================================================================"
echo "AgentCore VPC - Availability Zone Verification Tool"
echo "================================================================"
echo ""
echo "Region: $REGION"
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

# Check if region is supported
if [[ -z "${SUPPORTED_AZS[$REGION]}" ]]; then
    echo "❌ ERROR: Region '$REGION' does not support AgentCore VPC mode"
    echo ""
    echo "Supported regions:"
    echo "  - us-east-1, us-east-2, us-west-2"
    echo "  - ap-south-1, ap-southeast-1, ap-southeast-2, ap-northeast-1"
    echo "  - eu-west-1, eu-central-1"
    echo ""
    exit 1
fi

echo "✅ Region '$REGION' supports AgentCore VPC mode"
echo ""
echo "Supported AZ IDs for $REGION: ${SUPPORTED_AZS[$REGION]}"
echo ""
echo "================================================================"
echo "Checking YOUR account's AZ name mapping..."
echo "================================================================"
echo ""

# Get current AZs and check support
SUPPORTED_AZ_NAMES=()
UNSUPPORTED_AZ_NAMES=()

while IFS=$'\t' read -r AZ_NAME AZ_ID; do
    # Check if AZ ID is supported
    if [[ " ${SUPPORTED_AZS[$REGION]} " =~ " $AZ_ID " ]]; then
        echo "✅ $AZ_NAME → $AZ_ID (SUPPORTED)"
        SUPPORTED_AZ_NAMES+=("$AZ_NAME")
    else
        echo "❌ $AZ_NAME → $AZ_ID (NOT SUPPORTED)"
        UNSUPPORTED_AZ_NAMES+=("$AZ_NAME")
    fi
done < <(aws ec2 describe-availability-zones --region "$REGION" \
    --query 'AvailabilityZones[*].[ZoneName,ZoneId]' \
    --output text)

echo ""
echo "================================================================"
echo "Summary for YOUR AWS Account in $REGION"
echo "================================================================"
echo ""

if [ ${#SUPPORTED_AZ_NAMES[@]} -lt 2 ]; then
    echo "❌ ERROR: Found only ${#SUPPORTED_AZ_NAMES[@]} supported AZ(s)"
    echo "   AgentCore VPC requires at least 2 AZs in different supported zones"
    echo ""
    exit 1
fi

echo "✅ Found ${#SUPPORTED_AZ_NAMES[@]} supported AZ(s) in your account"
echo ""
echo "Use these AZ names for CloudFormation deployment:"
echo ""
echo "  AvailabilityZone1=${SUPPORTED_AZ_NAMES[0]}"
echo "  AvailabilityZone2=${SUPPORTED_AZ_NAMES[1]}"

if [ ${#SUPPORTED_AZ_NAMES[@]} -gt 2 ]; then
    echo ""
    echo "Additional supported AZs (optional):"
    for i in "${!SUPPORTED_AZ_NAMES[@]}"; do
        if [ $i -gt 1 ]; then
            echo "  - ${SUPPORTED_AZ_NAMES[$i]}"
        fi
    done
fi

echo ""
echo "================================================================"
echo "CloudFormation Deployment Command"
echo "================================================================"
echo ""
echo "Deploy Phase 1 with the verified AZs:"
echo ""
echo "  cd production_deployment/scripts/phase1"
echo "  ./deploy.sh prod \\"
echo "    --region $REGION \\"
echo "    --parameter-overrides \\"
echo "      AvailabilityZone1=${SUPPORTED_AZ_NAMES[0]} \\"
echo "      AvailabilityZone2=${SUPPORTED_AZ_NAMES[1]}"
echo ""

if [ ${#UNSUPPORTED_AZ_NAMES[@]} -gt 0 ]; then
    echo "================================================================"
    echo "⚠️  WARNING: Unsupported AZs in Your Account"
    echo "================================================================"
    echo ""
    echo "The following AZs exist but are NOT supported by AgentCore VPC:"
    for az in "${UNSUPPORTED_AZ_NAMES[@]}"; do
        echo "  ❌ $az"
    done
    echo ""
    echo "Do NOT use these AZ names in your CloudFormation parameters!"
    echo ""
fi

echo "================================================================"
echo "✅ Verification Complete"
echo "================================================================"
echo ""
echo "For more information, see:"
echo "  production_deployment/docs/bedrock_agentcore_vpc_regions.md"
echo ""
