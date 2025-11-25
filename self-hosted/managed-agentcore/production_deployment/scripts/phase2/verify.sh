#!/bin/bash
#
# Phase 2: Fargate Runtime Verification
# Verify all Phase 2 resources are created correctly
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
echo -e "${BLUE}Phase 2: Fargate Runtime Verification${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Load environment variables
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    echo "Please run ./scripts/phase2/deploy.sh first"
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

echo -e "${YELLOW}1. Checking ECR Repository...${NC}"
echo ""

check_resource \
    "ECR Repository exists" \
    "$ECR_REPOSITORY_NAME" \
    "aws ecr describe-repositories --repository-names $ECR_REPOSITORY_NAME --region $AWS_REGION"

# Check if Docker image exists in ECR
IMAGE_COUNT=$(aws ecr list-images \
    --repository-name "$ECR_REPOSITORY_NAME" \
    --region "$AWS_REGION" \
    --query 'length(imageIds)' \
    --output text 2>/dev/null || echo "0")

printf "  %-50s " "Docker images in repository"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$IMAGE_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ OK ($IMAGE_COUNT)${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ NONE${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

# Check latest tag exists
LATEST_TAG=$(aws ecr describe-images \
    --repository-name "$ECR_REPOSITORY_NAME" \
    --region "$AWS_REGION" \
    --query 'imageDetails[?imageTags!=null && contains(imageTags, `latest`)].imageTags' \
    --output text 2>/dev/null || echo "")

printf "  %-50s " "Latest tag exists"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ ! -z "$LATEST_TAG" ]; then
    echo -e "${GREEN}✓ OK${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ MISSING${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

echo ""
echo -e "${YELLOW}2. Checking ECS Cluster...${NC}"
echo ""

# Extract cluster name from ARN
CLUSTER_NAME=$(echo "$ECS_CLUSTER_ARN" | awk -F'/' '{print $NF}')

check_resource \
    "ECS Cluster exists" \
    "$CLUSTER_NAME" \
    "aws ecs describe-clusters --clusters $CLUSTER_NAME --region $AWS_REGION"

# Check cluster status
CLUSTER_STATUS=$(aws ecs describe-clusters \
    --clusters "$CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --query 'clusters[0].status' \
    --output text 2>/dev/null || echo "unknown")

printf "  %-50s " "ECS Cluster status"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$CLUSTER_STATUS" == "ACTIVE" ]; then
    echo -e "${GREEN}✓ $CLUSTER_STATUS${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ $CLUSTER_STATUS${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

# Check Container Insights (optional - not critical)
CONTAINER_INSIGHTS=$(aws ecs describe-clusters \
    --clusters "$CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --query 'clusters[0].settings[?name==`containerInsights`].value' \
    --output text 2>/dev/null || echo "disabled")

printf "  %-50s " "Container Insights"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$CONTAINER_INSIGHTS" == "enabled" ]; then
    echo -e "${GREEN}✓ Enabled${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${YELLOW}⚠ Disabled (optional)${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
fi

echo ""
echo -e "${YELLOW}3. Checking Task Definition...${NC}"
echo ""

# Extract task definition family and revision
TASK_FAMILY=$(echo "$TASK_DEFINITION_ARN" | awk -F'/' '{print $2}' | cut -d':' -f1)
TASK_REVISION=$(echo "$TASK_DEFINITION_ARN" | awk -F':' '{print $NF}')

check_resource \
    "Task Definition exists" \
    "$TASK_FAMILY" \
    "aws ecs describe-task-definition --task-definition $TASK_DEFINITION_ARN --region $AWS_REGION"

# Check task definition status
TASK_STATUS=$(aws ecs describe-task-definition \
    --task-definition "$TASK_DEFINITION_ARN" \
    --region "$AWS_REGION" \
    --query 'taskDefinition.status' \
    --output text 2>/dev/null || echo "unknown")

printf "  %-50s " "Task Definition status"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$TASK_STATUS" == "ACTIVE" ]; then
    echo -e "${GREEN}✓ $TASK_STATUS${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ $TASK_STATUS${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

# Check network mode
NETWORK_MODE=$(aws ecs describe-task-definition \
    --task-definition "$TASK_DEFINITION_ARN" \
    --region "$AWS_REGION" \
    --query 'taskDefinition.networkMode' \
    --output text 2>/dev/null || echo "unknown")

printf "  %-50s " "Network mode"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$NETWORK_MODE" == "awsvpc" ]; then
    echo -e "${GREEN}✓ $NETWORK_MODE${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ $NETWORK_MODE${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

# Check requires compatibilities
COMPATIBILITIES=$(aws ecs describe-task-definition \
    --task-definition "$TASK_DEFINITION_ARN" \
    --region "$AWS_REGION" \
    --query 'taskDefinition.requiresCompatibilities' \
    --output text 2>/dev/null || echo "unknown")

printf "  %-50s " "Requires compatibilities"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [[ "$COMPATIBILITIES" == *"FARGATE"* ]]; then
    echo -e "${GREEN}✓ FARGATE${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${RED}✗ $COMPATIBILITIES${NC}"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
fi

echo ""
echo -e "${YELLOW}4. Checking CloudWatch Logs...${NC}"
echo ""

check_resource \
    "CloudWatch Log Group exists" \
    "$LOG_GROUP_NAME" \
    "aws logs describe-log-groups --log-group-name-prefix $LOG_GROUP_NAME --region $AWS_REGION"

# Check log retention
LOG_RETENTION=$(aws logs describe-log-groups \
    --log-group-name-prefix "$LOG_GROUP_NAME" \
    --region "$AWS_REGION" \
    --query 'logGroups[0].retentionInDays' \
    --output text 2>/dev/null || echo "Never")

printf "  %-50s " "Log retention"
TOTAL_CHECKS=$((TOTAL_CHECKS + 1))

if [ "$LOG_RETENTION" != "None" ] && [ "$LOG_RETENTION" != "Never" ]; then
    echo -e "${GREEN}✓ $LOG_RETENTION days${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
else
    echo -e "${YELLOW}⚠ Never expire${NC}"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
fi

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
    echo "  1. Test Fargate task: ${YELLOW}./scripts/phase2/test-task.sh${NC}"
    echo "  2. Proceed to Phase 3: AgentCore Runtime deployment"
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
