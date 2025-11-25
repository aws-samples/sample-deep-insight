#!/bin/bash
#
# Phase 2: Fargate Runtime Deployment (Two-Stage CloudFormation)
# Stage 1: Create ECR Repository (CloudFormation)
# Stage 2: Build and push Docker image
# Stage 3: Deploy full stack with ECS (CloudFormation)
#
# Usage: ./scripts/phase2/deploy.sh <environment> --region <region> [options]
#   environment: dev, staging, prod (default: prod)
#   --region: AWS region (REQUIRED, e.g., us-east-1, us-west-2)
#   --stage: Deployment stage (optional: ecr, docker, stack, all)
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
ENVIRONMENT="${1:-prod}"
PROJECT_NAME="deep-insight"

# Parse command-line arguments
REGION=""
STAGE="all"
shift || true  # Remove first positional argument (ENVIRONMENT)

while [[ $# -gt 0 ]]; do
    case $1 in
        --region)
            REGION="$2"
            shift 2
            ;;
        --stage)
            STAGE="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Region is REQUIRED to prevent accidental deployments to wrong region
if [ -z "$REGION" ]; then
    echo -e "${RED}Error: --region parameter is required${NC}"
    echo ""
    echo "Usage: $0 <environment> --region <region> [options]"
    echo ""
    echo "Examples:"
    echo "  $0 prod --region us-east-1"
    echo "  $0 prod --region us-west-2"
    echo "  $0 prod --region us-east-1 --stage docker"
    echo ""
    echo "This is a safety measure to ensure deployment to the correct region."
    exit 1
fi

STACK_NAME="${PROJECT_NAME}-fargate-${ENVIRONMENT}"
TEMPLATE_FILE="$PROJECT_ROOT/cloudformation/phase2-fargate.yaml"
ENV_FILE="$PROJECT_ROOT/.env"
FARGATE_RUNTIME_DIR="$PROJECT_ROOT/../fargate-runtime"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Phase 2: Two-Stage Fargate Deployment${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo "Stack Name: $STACK_NAME"
echo "Stage: $STAGE"
echo ""

# ============================================
# Check Prerequisites
# ============================================
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Check Phase 1 .env file
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: Phase 1 .env file not found${NC}"
    echo "Please run ./scripts/phase1/deploy.sh first"
    exit 1
fi
echo -e "${GREEN}✓${NC} Phase 1 .env file found"

# Load Phase 1 environment variables
source "$ENV_FILE"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} AWS CLI configured"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker not found${NC}"
    echo "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker installed"

# Check fargate-runtime directory
if [ ! -d "$FARGATE_RUNTIME_DIR" ]; then
    echo -e "${RED}Error: Fargate runtime directory not found: $FARGATE_RUNTIME_DIR${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Fargate runtime directory found"

# Check CloudFormation template
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo -e "${RED}Error: CloudFormation template not found: $TEMPLATE_FILE${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} CloudFormation template found"

# Get AWS region and account
AWS_REGION="$REGION"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# ============================================
# STAGE 1: Deploy ECR Repository Only
# ============================================
echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}STAGE 1: Creating ECR Repository${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Create temp parameter file for Stage 1 (ECR only)
TEMP_PARAMS_FILE=$(mktemp)
cat > "$TEMP_PARAMS_FILE" <<EOF
[
  {
    "ParameterKey": "Environment",
    "ParameterValue": "$ENVIRONMENT"
  },
  {
    "ParameterKey": "ProjectName",
    "ParameterValue": "$PROJECT_NAME"
  },
  {
    "ParameterKey": "DeployECS",
    "ParameterValue": "false"
  },
  {
    "ParameterKey": "VpcId",
    "ParameterValue": "$VPC_ID"
  },
  {
    "ParameterKey": "PrivateSubnet1Id",
    "ParameterValue": "$PRIVATE_SUBNET_1_ID"
  },
  {
    "ParameterKey": "PrivateSubnet2Id",
    "ParameterValue": "$PRIVATE_SUBNET_2_ID"
  },
  {
    "ParameterKey": "FargateSecurityGroupId",
    "ParameterValue": "$SG_FARGATE_ID"
  },
  {
    "ParameterKey": "TaskExecutionRoleArn",
    "ParameterValue": "$TASK_EXECUTION_ROLE_ARN"
  },
  {
    "ParameterKey": "TaskRoleArn",
    "ParameterValue": "$TASK_ROLE_ARN"
  }
]
EOF

echo "Deploying CloudFormation stack (ECR only)..."
aws cloudformation deploy \
    --template-file "$TEMPLATE_FILE" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides file://"$TEMP_PARAMS_FILE" \
    --capabilities CAPABILITY_IAM \
    --region "$AWS_REGION" \
    --tags \
        Environment="$ENVIRONMENT" \
        Project="$PROJECT_NAME" \
        ManagedBy=CloudFormation \
    --no-fail-on-empty-changeset

rm -f "$TEMP_PARAMS_FILE"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} ECR Repository created via CloudFormation"
else
    echo -e "${RED}✗ Stage 1 deployment failed${NC}"
    exit 1
fi

# Get ECR URI from CloudFormation outputs
ECR_URI=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`ECRRepositoryUri`].OutputValue' \
    --output text)

ECR_REPO_NAME=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].Outputs[?OutputKey==`ECRRepositoryName`].OutputValue' \
    --output text)

echo ""
echo "ECR Repository URI: $ECR_URI"
echo "ECR Repository Name: $ECR_REPO_NAME"

# ============================================
# STAGE 2: Build and Push Docker Image
# ============================================
echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}STAGE 2: Building & Pushing Docker Image${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

cd "$FARGATE_RUNTIME_DIR"

IMAGE_TAG="v$(date +%Y%m%d-%H%M%S)"
DOCKER_IMAGE="$ECR_URI:$IMAGE_TAG"

echo "Building Docker image..."
echo "Image: $DOCKER_IMAGE"
echo "This may take 5-10 minutes (installing system packages + Python packages)"
echo ""

docker build --platform linux/arm64 -t "$DOCKER_IMAGE" -t "$ECR_URI:latest" .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Docker image built successfully"
else
    echo -e "${RED}✗ Docker build failed${NC}"
    exit 1
fi

# ECR login
echo ""
echo "Logging in to ECR..."
aws ecr get-login-password --region "$AWS_REGION" | \
    docker login --username AWS --password-stdin "${ECR_URI%%/*}"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ ECR login failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Logged in to ECR"

# Push images
echo ""
echo "Pushing Docker images to ECR..."
echo "  - $DOCKER_IMAGE"
docker push "$DOCKER_IMAGE"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Docker push failed (tagged)${NC}"
    exit 1
fi

echo "  - $ECR_URI:latest"
docker push "$ECR_URI:latest"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Docker push failed (latest)${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Docker images pushed successfully"

# ============================================
# STAGE 3: Deploy Full Stack with ECS
# ============================================
echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}STAGE 3: Deploying Full Stack (ECS)${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

cd "$PROJECT_ROOT"

# Create temp parameter file for Stage 3 (Full stack)
TEMP_PARAMS_FILE=$(mktemp)
cat > "$TEMP_PARAMS_FILE" <<EOF
[
  {
    "ParameterKey": "Environment",
    "ParameterValue": "$ENVIRONMENT"
  },
  {
    "ParameterKey": "ProjectName",
    "ParameterValue": "$PROJECT_NAME"
  },
  {
    "ParameterKey": "DeployECS",
    "ParameterValue": "true"
  },
  {
    "ParameterKey": "VpcId",
    "ParameterValue": "$VPC_ID"
  },
  {
    "ParameterKey": "PrivateSubnet1Id",
    "ParameterValue": "$PRIVATE_SUBNET_1_ID"
  },
  {
    "ParameterKey": "PrivateSubnet2Id",
    "ParameterValue": "$PRIVATE_SUBNET_2_ID"
  },
  {
    "ParameterKey": "FargateSecurityGroupId",
    "ParameterValue": "$SG_FARGATE_ID"
  },
  {
    "ParameterKey": "TaskExecutionRoleArn",
    "ParameterValue": "$TASK_EXECUTION_ROLE_ARN"
  },
  {
    "ParameterKey": "TaskRoleArn",
    "ParameterValue": "$TASK_ROLE_ARN"
  },
  {
    "ParameterKey": "DockerImageUri",
    "ParameterValue": "$ECR_URI:latest"
  },
  {
    "ParameterKey": "TaskCpu",
    "ParameterValue": "2048"
  },
  {
    "ParameterKey": "TaskMemory",
    "ParameterValue": "4096"
  }
]
EOF

echo "Deploying CloudFormation stack (Full stack with ECS)..."
echo "This will take approximately 2-3 minutes."
echo ""

aws cloudformation deploy \
    --template-file "$TEMPLATE_FILE" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides file://"$TEMP_PARAMS_FILE" \
    --capabilities CAPABILITY_IAM \
    --region "$AWS_REGION" \
    --tags \
        Environment="$ENVIRONMENT" \
        Project="$PROJECT_NAME" \
        ManagedBy=CloudFormation \
    --no-fail-on-empty-changeset

rm -f "$TEMP_PARAMS_FILE"

DEPLOY_STATUS=$?

if [ $DEPLOY_STATUS -eq 0 ]; then
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}✓ Deployment Successful!${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""

    # Get stack outputs
    echo -e "${YELLOW}Retrieving stack outputs...${NC}"

    OUTPUTS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs' \
        --output json)

    # Update .env file with Phase 2 outputs
    python3 - <<EOF "$OUTPUTS" "$ENV_FILE"
import json
import sys

outputs = json.loads(sys.argv[1])
env_file = sys.argv[2]

# Create dictionary from outputs
output_dict = {o['OutputKey']: o['OutputValue'] for o in outputs}

# Append to .env file
with open(env_file, 'a') as f:
    f.write("\n# Phase 2 Outputs (CloudFormation)\n")
    f.write(f"ECR_REPOSITORY_URI={output_dict.get('ECRRepositoryUri', '')}\n")
    f.write(f"ECR_REPOSITORY_NAME={output_dict.get('ECRRepositoryName', '')}\n")
    f.write(f"ECS_CLUSTER_ARN={output_dict.get('ECSClusterArn', '')}\n")
    f.write(f"ECS_CLUSTER_NAME={output_dict.get('ECSClusterName', '')}\n")
    f.write(f"TASK_DEFINITION_ARN={output_dict.get('TaskDefinitionArn', '')}\n")
    f.write(f"LOG_GROUP_NAME={output_dict.get('LogGroupName', '')}\n")

print(f"\n✓ .env file updated: {env_file}")
EOF

    # Display summary
    echo ""
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}Deployment Summary${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo ""
    echo "Docker Image: $ECR_URI:latest"
    echo "Image Tag: $IMAGE_TAG"
    echo ""
    cat "$ENV_FILE" | grep -A 10 "Phase 2"
    echo ""
    echo -e "${GREEN}Next Steps:${NC}"
    echo "  1. Run verification: ${YELLOW}./scripts/phase2/verify.sh${NC}"
    echo "  2. Proceed to Phase 3: AgentCore Runtime deployment"
    echo ""

else
    echo ""
    echo -e "${RED}============================================${NC}"
    echo -e "${RED}✗ Deployment Failed${NC}"
    echo -e "${RED}============================================${NC}"
    echo ""
    echo "Check CloudFormation console for details:"
    echo "  https://console.aws.amazon.com/cloudformation"
    echo ""
    exit 1
fi
