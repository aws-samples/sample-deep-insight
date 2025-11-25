#!/bin/bash

#==============================================================================
# Environment Setup Script
#==============================================================================
# Automatically generates .env file from CloudFormation stack outputs
# Usage: ./01_extract_env_vars_from_cf.sh <environment> <region>
# Example: ./01_extract_env_vars_from_cf.sh prod us-west-2
#==============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT=${1:-prod}
REGION=${2:-""}
PROJECT_NAME="deep-insight"
PHASE1_STACK_NAME="${PROJECT_NAME}-infrastructure-${ENVIRONMENT}"
PHASE2_STACK_NAME="${PROJECT_NAME}-fargate-${ENVIRONMENT}"

# Region is REQUIRED to prevent accidental misconfigurations
if [ -z "$REGION" ]; then
    echo -e "${RED}Error: Region parameter is required${NC}"
    echo ""
    echo "Usage: $0 <environment> <region>"
    echo ""
    echo "Examples:"
    echo "  $0 prod us-east-1"
    echo "  $0 prod us-west-2"
    echo "  $0 dev us-east-1"
    echo ""
    echo "This is a safety measure to ensure .env is generated for the correct region."
    exit 1
fi

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Environment Setup - Auto-generate .env${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Region: ${REGION}${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROD_DEPLOY_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$PROD_DEPLOY_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# Verify PROJECT_ROOT is correct (should end with "20_deep_insight", not "production_deployment")
if [[ "$PROJECT_ROOT" == *"/production_deployment" ]]; then
    echo -e "${RED}✗ Error: PROJECT_ROOT calculation incorrect${NC}"
    echo "  PROJECT_ROOT: $PROJECT_ROOT"
    echo "  Expected to end with: 20_deep_insight"
    echo "  Please check script path calculation"
    exit 1
fi

# Set AWS region from parameter
AWS_REGION="$REGION"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)

if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo -e "${RED}✗ Failed to detect AWS Account ID${NC}"
    echo -e "${YELLOW}  Please ensure AWS CLI is configured${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Detected AWS Account: $AWS_ACCOUNT_ID"
echo -e "${GREEN}✓${NC} Detected AWS Region: $AWS_REGION"
echo ""

# Check if Phase 1 stack exists
echo -e "${YELLOW}Checking Phase 1 stack: $PHASE1_STACK_NAME${NC}"
PHASE1_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$PHASE1_STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$PHASE1_STATUS" = "NOT_FOUND" ]; then
    echo -e "${RED}✗ Phase 1 stack not found: $PHASE1_STACK_NAME${NC}"
    echo -e "${YELLOW}  Please deploy Phase 1 first: ./scripts/phase1/deploy.sh${NC}"
    exit 1
fi

if [[ ! "$PHASE1_STATUS" =~ ^(CREATE_COMPLETE|UPDATE_COMPLETE)$ ]]; then
    echo -e "${RED}✗ Phase 1 stack is not ready: $PHASE1_STATUS${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Phase 1 stack status: $PHASE1_STATUS"

# Check if Phase 2 stack exists
echo -e "${YELLOW}Checking Phase 2 stack: $PHASE2_STACK_NAME${NC}"
PHASE2_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$PHASE2_STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$PHASE2_STATUS" = "NOT_FOUND" ]; then
    echo -e "${YELLOW}⚠${NC} Phase 2 stack not found: $PHASE2_STACK_NAME"
    echo -e "${YELLOW}  .env will be generated with Phase 1 outputs only${NC}"
    PHASE2_DEPLOYED=false
else
    if [[ ! "$PHASE2_STATUS" =~ ^(CREATE_COMPLETE|UPDATE_COMPLETE)$ ]]; then
        echo -e "${YELLOW}⚠${NC} Phase 2 stack is not ready: $PHASE2_STATUS"
        PHASE2_DEPLOYED=false
    else
        echo -e "${GREEN}✓${NC} Phase 2 stack status: $PHASE2_STATUS"
        PHASE2_DEPLOYED=true
    fi
fi
echo ""

# Preserve existing RUNTIME_ARN if .env exists
EXISTING_RUNTIME_ARN=""
EXISTING_RUNTIME_NAME=""
EXISTING_RUNTIME_ID=""
if [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}Preserving existing Runtime configuration...${NC}"
    # Use tail -1 to get last occurrence (handles duplicates, prefers populated values)
    EXISTING_RUNTIME_ARN=$(grep "^RUNTIME_ARN=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2-)
    EXISTING_RUNTIME_NAME=$(grep "^RUNTIME_NAME=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2-)
    EXISTING_RUNTIME_ID=$(grep "^RUNTIME_ID=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d'=' -f2-)
    if [ -n "$EXISTING_RUNTIME_ARN" ]; then
        echo -e "${GREEN}✓${NC} Preserved RUNTIME_ARN: $EXISTING_RUNTIME_ARN"
    fi
fi
echo ""

# Read Phase 1 outputs
echo -e "${YELLOW}Reading Phase 1 CloudFormation outputs...${NC}"
PHASE1_OUTPUTS=$(aws cloudformation describe-stacks \
    --stack-name "$PHASE1_STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].Outputs' \
    --output json)

# Extract Phase 1 values
VPC_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="VpcId") | .OutputValue')
PRIVATE_SUBNET_1_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="PrivateSubnet1Id") | .OutputValue')
PRIVATE_SUBNET_2_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="PrivateSubnet2Id") | .OutputValue')
PUBLIC_SUBNET_1_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="PublicSubnet1Id") | .OutputValue')
PUBLIC_SUBNET_2_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="PublicSubnet2Id") | .OutputValue')
SG_AGENTCORE_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="AgentCoreSecurityGroupId") | .OutputValue')
SG_ALB_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="ALBSecurityGroupId") | .OutputValue')
SG_FARGATE_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="FargateSecurityGroupId") | .OutputValue')
SG_VPCE_ID=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="VPCEndpointSecurityGroupId") | .OutputValue')
ALB_ARN=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="ApplicationLoadBalancerArn") | .OutputValue')
ALB_DNS=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="ApplicationLoadBalancerDNS") | .OutputValue')
ALB_TARGET_GROUP_ARN=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="TargetGroupArn") | .OutputValue')
TASK_EXECUTION_ROLE_ARN=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="TaskExecutionRoleArn") | .OutputValue')
TASK_ROLE_ARN=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="TaskRoleArn") | .OutputValue')
S3_BUCKET_NAME=$(echo "$PHASE1_OUTPUTS" | jq -r '.[] | select(.OutputKey=="SessionDataBucketName") | .OutputValue')

PHASE1_COUNT=14
echo -e "${GREEN}✓${NC} Phase 1: $PHASE1_COUNT variables"

# Read Phase 2 outputs (if deployed)
PHASE2_COUNT=0
if [ "$PHASE2_DEPLOYED" = true ]; then
    echo -e "${YELLOW}Reading Phase 2 CloudFormation outputs...${NC}"
    PHASE2_OUTPUTS=$(aws cloudformation describe-stacks \
        --stack-name "$PHASE2_STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs' \
        --output json)

    ECR_REPOSITORY_URI=$(echo "$PHASE2_OUTPUTS" | jq -r '.[] | select(.OutputKey=="ECRRepositoryUri") | .OutputValue')
    ECR_REPOSITORY_NAME=$(echo "$PHASE2_OUTPUTS" | jq -r '.[] | select(.OutputKey=="ECRRepositoryName") | .OutputValue')
    ECS_CLUSTER_ARN=$(echo "$PHASE2_OUTPUTS" | jq -r '.[] | select(.OutputKey=="ECSClusterArn") | .OutputValue')
    ECS_CLUSTER_NAME=$(echo "$PHASE2_OUTPUTS" | jq -r '.[] | select(.OutputKey=="ECSClusterName") | .OutputValue')
    TASK_DEFINITION_ARN=$(echo "$PHASE2_OUTPUTS" | jq -r '.[] | select(.OutputKey=="TaskDefinitionArn") | .OutputValue')
    LOG_GROUP_NAME=$(echo "$PHASE2_OUTPUTS" | jq -r '.[] | select(.OutputKey=="LogGroupName") | .OutputValue')

    # Extract task family from ARN
    TASK_DEFINITION_FAMILY=$(echo "$TASK_DEFINITION_ARN" | awk -F'/' '{print $2}' | cut -d':' -f1)

    PHASE2_COUNT=8
    echo -e "${GREEN}✓${NC} Phase 2: $PHASE2_COUNT variables"
fi
echo ""

# Generate .env file
echo -e "${YELLOW}Generating .env file at project root...${NC}"

cat > "$ENV_FILE" <<EOF
# ============================================================
# AWS OpenTelemetry Configuration (for per-invocation log streams)
# ============================================================
OTEL_PYTHON_DISTRO=aws_distro
OTEL_PYTHON_CONFIGURATOR=aws_configurator
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_LOGS_HEADERS=x-aws-log-group=bedrock-agentcore-observability,x-aws-log-stream=custom-spans,x-aws-metric-namespace=AgentCore
OTEL_RESOURCE_ATTRIBUTES=service.name=deep-insight-runtime
AGENT_OBSERVABILITY_ENABLED=true

# ============================================================
# AWS Configuration
# ============================================================
AWS_REGION=$AWS_REGION
AWS_ACCOUNT_ID=$AWS_ACCOUNT_ID

# ============================================================
# Bedrock Model Configuration
# ============================================================
DEFAULT_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
COORDINATOR_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
PLANNER_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
SUPERVISOR_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
CODER_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
VALIDATOR_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
REPORTER_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0
TRACKER_MODEL_ID=global.anthropic.claude-sonnet-4-20250514-v1:0

# ============================================================
# Phase 1: Infrastructure Outputs
# ============================================================
VPC_ID=$VPC_ID
PRIVATE_SUBNET_1_ID=$PRIVATE_SUBNET_1_ID
PRIVATE_SUBNET_2_ID=$PRIVATE_SUBNET_2_ID
PUBLIC_SUBNET_1_ID=$PUBLIC_SUBNET_1_ID
PUBLIC_SUBNET_2_ID=$PUBLIC_SUBNET_2_ID

SG_AGENTCORE_ID=$SG_AGENTCORE_ID
SG_ALB_ID=$SG_ALB_ID
SG_FARGATE_ID=$SG_FARGATE_ID
SG_VPCE_ID=$SG_VPCE_ID

ALB_ARN=$ALB_ARN
ALB_DNS=$ALB_DNS
ALB_TARGET_GROUP_ARN=$ALB_TARGET_GROUP_ARN

TASK_EXECUTION_ROLE_ARN=$TASK_EXECUTION_ROLE_ARN
TASK_ROLE_ARN=$TASK_ROLE_ARN

EOF

# Add Phase 2 variables if deployed
if [ "$PHASE2_DEPLOYED" = true ]; then
    cat >> "$ENV_FILE" <<EOF
# ============================================================
# Phase 2: Fargate Runtime Outputs
# ============================================================
ECR_REPOSITORY_URI=$ECR_REPOSITORY_URI
ECR_REPOSITORY_NAME=$ECR_REPOSITORY_NAME
ECS_CLUSTER_ARN=$ECS_CLUSTER_ARN
ECS_CLUSTER_NAME=$ECS_CLUSTER_NAME
TASK_DEFINITION_ARN=$TASK_DEFINITION_ARN
TASK_DEFINITION_FAMILY=$TASK_DEFINITION_FAMILY
LOG_GROUP_NAME=$LOG_GROUP_NAME

# Fargate Network Configuration (for Runtime to launch containers)
FARGATE_SUBNET_IDS=$PRIVATE_SUBNET_1_ID,$PRIVATE_SUBNET_2_ID
FARGATE_SECURITY_GROUP_IDS=$SG_FARGATE_ID
FARGATE_ASSIGN_PUBLIC_IP=DISABLED

# Container Configuration
CONTAINER_NAME=fargate-runtime

EOF
else
    cat >> "$ENV_FILE" <<EOF
# ============================================================
# Phase 2: Fargate Runtime Outputs (Not deployed yet)
# ============================================================
# Run ./scripts/phase2/deploy.sh to deploy Phase 2

EOF
fi

# Add S3 bucket (from Phase 1 CloudFormation)
cat >> "$ENV_FILE" <<EOF
# ============================================================
# S3 Configuration
# ============================================================
S3_BUCKET_NAME=$S3_BUCKET_NAME
EOF

# Preserve existing Runtime configuration (if exists)
# Note: Phase 3 section is managed by 01_create_agentcore_runtime_vpc.py
if [ -n "$EXISTING_RUNTIME_ARN" ]; then
    cat >> "$ENV_FILE" <<EOF

# Phase 3: AgentCore Runtime (Preserved from previous deployment)
RUNTIME_NAME=$EXISTING_RUNTIME_NAME
RUNTIME_ARN=$EXISTING_RUNTIME_ARN
RUNTIME_ID=$EXISTING_RUNTIME_ID
EOF
fi

echo -e "${GREEN}✓${NC} Generated .env at: $ENV_FILE"
echo ""
echo -e "${BLUE}Project Root: ${NC}$PROJECT_ROOT"
echo -e "${BLUE}Environment file: ${NC}$ENV_FILE"
echo ""

# Summary
OTEL_COUNT=6
AWS_CONFIG_COUNT=3  # AWS_REGION + AWS_ACCOUNT_ID + BEDROCK_MODEL_ID
RUNTIME_COUNT=3
TOTAL_COUNT=$((OTEL_COUNT + AWS_CONFIG_COUNT + PHASE1_COUNT + PHASE2_COUNT + RUNTIME_COUNT + 1))

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}============================================${NC}"
echo -e "${GREEN}✓${NC} Total variables: $TOTAL_COUNT"
echo "  - OTEL: $OTEL_COUNT variables"
echo "  - AWS Config: $AWS_CONFIG_COUNT variables"
echo "  - Phase 1: $PHASE1_COUNT variables"
if [ "$PHASE2_DEPLOYED" = true ]; then
    echo "  - Phase 2: $PHASE2_COUNT variables"
else
    echo "  - Phase 2: Not deployed yet"
fi
echo "  - S3 Bucket: 1 variable (default: bedrock-logs-$AWS_ACCOUNT_ID)"
if [ -n "$EXISTING_RUNTIME_ARN" ]; then
    echo "  - Runtime: $RUNTIME_COUNT variables (preserved from existing .env)"
else
    echo "  - Runtime: $RUNTIME_COUNT variables (empty, to be populated)"
fi
echo ""

echo -e "${GREEN}✓${NC} Environment setup complete!"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
if [ "$PHASE2_DEPLOYED" = false ]; then
    echo "  1. Deploy Phase 2: cd production_deployment && ./scripts/phase2/deploy.sh"
    echo "  2. Deploy Phase 3: cd production_deployment && python 01_create_agentcore_runtime.py"
elif [ -z "$EXISTING_RUNTIME_ARN" ]; then
    echo "  1. Deploy Phase 3: cd production_deployment && python 01_create_agentcore_runtime.py"
    echo "  2. Test Runtime: cd production_deployment && python 03_invoke_agentcore_job_vpc.py"
else
    echo "  1. Test Runtime: cd production_deployment && python 03_invoke_agentcore_job_vpc.py"
fi
echo ""
