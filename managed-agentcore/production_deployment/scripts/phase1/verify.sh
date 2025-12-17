#!/bin/bash
#
# Phase 1: Infrastructure Verification
# Verify all Phase 1 resources are created correctly
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Phase 1: Infrastructure Verification${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Load environment variables
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    echo "Please run ./scripts/phase1/deploy.sh first"
    exit 1
fi

source "$ENV_FILE"

# Verification counters
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0

check_resource() {
    local description=$1
    local resource_id=$2
    local check_command=$3

    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

    printf "  %-50s " "$description"

    if [ -z "$resource_id" ]; then
        echo -e "${RED}✗ MISSING${NC}"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
        return 1
    fi

    if eval "$check_command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ OK${NC}"
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
        return 0
    else
        echo -e "${RED}✗ FAILED${NC}"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
        return 1
    fi
}

echo -e "${YELLOW}1. Checking VPC and Network Resources...${NC}"
echo ""

check_resource \
    "VPC exists" \
    "$VPC_ID" \
    "aws ec2 describe-vpcs --vpc-ids $VPC_ID --region $AWS_REGION"

check_resource \
    "Private Subnet 1 exists" \
    "$PRIVATE_SUBNET_1_ID" \
    "aws ec2 describe-subnets --subnet-ids $PRIVATE_SUBNET_1_ID --region $AWS_REGION"

check_resource \
    "Private Subnet 2 exists" \
    "$PRIVATE_SUBNET_2_ID" \
    "aws ec2 describe-subnets --subnet-ids $PRIVATE_SUBNET_2_ID --region $AWS_REGION"

check_resource \
    "Public Subnet 1 exists" \
    "$PUBLIC_SUBNET_1_ID" \
    "aws ec2 describe-subnets --subnet-ids $PUBLIC_SUBNET_1_ID --region $AWS_REGION"

check_resource \
    "Public Subnet 2 exists" \
    "$PUBLIC_SUBNET_2_ID" \
    "aws ec2 describe-subnets --subnet-ids $PUBLIC_SUBNET_2_ID --region $AWS_REGION"

# Check NAT Gateway
NAT_GW_ID=$(aws ec2 describe-nat-gateways \
    --filter "Name=vpc-id,Values=$VPC_ID" "Name=state,Values=available" \
    --region "$AWS_REGION" \
    --query 'NatGateways[0].NatGatewayId' \
    --output text 2>/dev/null)

check_resource \
    "NAT Gateway available" \
    "$NAT_GW_ID" \
    "aws ec2 describe-nat-gateways --nat-gateway-ids $NAT_GW_ID --region $AWS_REGION"

# Check Internet Gateway
IGW_ID=$(aws ec2 describe-internet-gateways \
    --filters "Name=attachment.vpc-id,Values=$VPC_ID" \
    --region "$AWS_REGION" \
    --query 'InternetGateways[0].InternetGatewayId' \
    --output text 2>/dev/null)

check_resource \
    "Internet Gateway attached" \
    "$IGW_ID" \
    "aws ec2 describe-internet-gateways --internet-gateway-ids $IGW_ID --region $AWS_REGION"

echo ""
echo -e "${YELLOW}2. Checking Security Groups...${NC}"
echo ""

check_resource \
    "AgentCore Security Group" \
    "$SG_AGENTCORE_ID" \
    "aws ec2 describe-security-groups --group-ids $SG_AGENTCORE_ID --region $AWS_REGION"

check_resource \
    "ALB Security Group" \
    "$SG_ALB_ID" \
    "aws ec2 describe-security-groups --group-ids $SG_ALB_ID --region $AWS_REGION"

check_resource \
    "Fargate Security Group" \
    "$SG_FARGATE_ID" \
    "aws ec2 describe-security-groups --group-ids $SG_FARGATE_ID --region $AWS_REGION"

check_resource \
    "VPC Endpoint Security Group" \
    "$SG_VPCE_ID" \
    "aws ec2 describe-security-groups --group-ids $SG_VPCE_ID --region $AWS_REGION"

echo ""
echo -e "${YELLOW}3. Checking VPC Endpoints...${NC}"
echo ""

# Get all VPC Endpoints in the VPC
VPCE_IDS=$(aws ec2 describe-vpc-endpoints \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --region "$AWS_REGION" \
    --query 'VpcEndpoints[].VpcEndpointId' \
    --output text)

VPCE_COUNT=$(echo "$VPCE_IDS" | wc -w)

printf "  %-50s " "VPC Endpoints count (expected 7)"
if [ "$VPCE_COUNT" -eq 7 ]; then
    echo -e "${GREEN}✓ OK ($VPCE_COUNT)${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
elif [ "$VPCE_COUNT" -ge 6 ]; then
    echo -e "${GREEN}✓ OK ($VPCE_COUNT, sufficient)${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ FAILED ($VPCE_COUNT)${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

# Check each VPC Endpoint status
for VPCE_ID in $VPCE_IDS; do
    VPCE_STATE=$(aws ec2 describe-vpc-endpoints \
        --vpc-endpoint-ids "$VPCE_ID" \
        --region "$AWS_REGION" \
        --query 'VpcEndpoints[0].State' \
        --output text)

    SERVICE_NAME=$(aws ec2 describe-vpc-endpoints \
        --vpc-endpoint-ids "$VPCE_ID" \
        --region "$AWS_REGION" \
        --query 'VpcEndpoints[0].ServiceName' \
        --output text | sed 's/.*\.//')

    printf "  %-50s " "VPC Endpoint ($SERVICE_NAME)"
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

    if [ "$VPCE_STATE" == "available" ]; then
        echo -e "${GREEN}✓ $VPCE_STATE${NC}"
        PASSED_CHECKS=$((PASSED_CHECKS + 1))
    else
        echo -e "${YELLOW}⚠ $VPCE_STATE${NC}"
        FAILED_CHECKS=$((FAILED_CHECKS + 1))
    fi
done

echo ""
echo -e "${YELLOW}4. Checking Application Load Balancer...${NC}"
echo ""

ALB_STATE=$(aws elbv2 describe-load-balancers \
    --load-balancer-arns "$ALB_ARN" \
    --region "$AWS_REGION" \
    --query 'LoadBalancers[0].State.Code' \
    --output text 2>/dev/null || echo "unknown")

printf "  %-50s " "ALB State"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$ALB_STATE" == "active" ]; then
    echo -e "${GREEN}✓ $ALB_STATE${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ $ALB_STATE${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

# Check Target Group
TG_HEALTH_CHECK=$(aws elbv2 describe-target-groups \
    --target-group-arns "$ALB_TARGET_GROUP_ARN" \
    --region "$AWS_REGION" \
    --query 'TargetGroups[0].HealthCheckEnabled' \
    --output text 2>/dev/null || echo "false")

printf "  %-50s " "Target Group Health Check"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$TG_HEALTH_CHECK" == "True" ]; then
    echo -e "${GREEN}✓ Enabled${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ Disabled${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

# Check Sticky Sessions
STICKINESS=$(aws elbv2 describe-target-group-attributes \
    --target-group-arn "$ALB_TARGET_GROUP_ARN" \
    --region "$AWS_REGION" \
    --query 'Attributes[?Key==`stickiness.enabled`].Value' \
    --output text 2>/dev/null || echo "false")

printf "  %-50s " "Sticky Sessions"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$STICKINESS" == "true" ]; then
    echo -e "${GREEN}✓ Enabled${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ Disabled${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

echo ""
echo -e "${YELLOW}5. Checking IAM Roles...${NC}"
echo ""

# Extract role name from ARN
TASK_EXEC_ROLE_NAME=$(echo "$TASK_EXECUTION_ROLE_ARN" | awk -F'/' '{print $NF}')
TASK_ROLE_NAME=$(echo "$TASK_ROLE_ARN" | awk -F'/' '{print $NF}')

check_resource \
    "Task Execution Role" \
    "$TASK_EXEC_ROLE_NAME" \
    "aws iam get-role --role-name $TASK_EXEC_ROLE_NAME --region $AWS_REGION"

check_resource \
    "Task Role" \
    "$TASK_ROLE_NAME" \
    "aws iam get-role --role-name $TASK_ROLE_NAME --region $AWS_REGION"

# Summary
echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Verification Summary${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo "Total Checks:  $TOTAL_CHECKS"
echo -e "${GREEN}Passed:        $PASSED_CHECKS${NC}"

if [ $FAILED_CHECKS -gt 0 ]; then
    echo -e "${RED}Failed:        $FAILED_CHECKS${NC}"
fi

echo ""

# Final result
if [ $FAILED_CHECKS -eq 0 ]; then
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo -e "${YELLOW}Next Steps:${NC}"
    echo "  1. Proceed to Phase 2: ./scripts/phase2/1-deploy-infrastructure.sh"
    echo ""
    exit 0
else
    echo -e "${RED}============================================${NC}"
    echo -e "${RED}✗ Some checks failed${NC}"
    echo -e "${RED}============================================${NC}"
    echo ""
    echo "Please review the failed checks above and fix any issues."
    echo ""
    exit 1
fi
