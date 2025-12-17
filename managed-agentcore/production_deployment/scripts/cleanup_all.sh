#!/bin/bash
#
# Complete Cleanup Script - Deep Insight
# Cleans up ALL resources in Phase 4 -> 3 -> 2 -> 1 order
#
# Usage: ./cleanup_all.sh <environment> <region>
# Example: ./cleanup_all.sh prod us-west-2

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ENVIRONMENT=${1:-prod}
REGION=$2

# Region is REQUIRED for cleanup to prevent accidental deletions
if [ -z "$REGION" ]; then
    echo -e "${RED}Error: Region parameter is required for cleanup${NC}"
    echo ""
    echo "Usage: $0 <environment> <region>"
    echo ""
    echo "Examples:"
    echo "  $0 prod us-east-1"
    echo "  $0 prod us-west-2"
    echo ""
    echo "This is a safety measure to prevent accidental deletion in the wrong region."
    exit 1
fi

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Deep Insight - Complete Cleanup${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo -e "${YELLOW}Environment:${NC} $ENVIRONMENT"
echo -e "${YELLOW}Region:${NC} $REGION"
echo ""
echo -e "${RED}⚠️  WARNING: This will delete ALL resources!${NC}"
echo -e "${RED}   - AgentCore Runtime${NC}"
echo -e "${RED}   - ECS Cluster, Tasks, Task Definitions${NC}"
echo -e "${RED}   - ECR Repository and Docker Images${NC}"
echo -e "${RED}   - VPC, Subnets, Security Groups${NC}"
echo -e "${RED}   - ALB, Target Groups${NC}"
echo -e "${RED}   - VPC Endpoints${NC}"
echo -e "${RED}   - S3 Buckets (templates and logs)${NC}"
echo -e "${RED}   - IAM Roles${NC}"
echo ""
read -p "Are you absolutely sure? Type 'DELETE' to confirm: " CONFIRM

if [ "$CONFIRM" != "DELETE" ]; then
    echo -e "${YELLOW}Cleanup cancelled${NC}"
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Phase 4: Cleanup AgentCore Runtime${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Check if .env exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
    
    if [ -n "$RUNTIME_ARN" ] && [ "$RUNTIME_ARN" != "" ]; then
        echo "Found Runtime ARN: $RUNTIME_ARN"
        RUNTIME_ID=$(basename "$RUNTIME_ARN")
        
        echo "Deleting runtime: $RUNTIME_ID"
        aws bedrock-agentcore-control delete-agent-runtime \
            --runtime-identifier "$RUNTIME_ID" \
            --region "$REGION" 2>/dev/null || echo "Runtime already deleted or not found"
        
        # Delete CloudWatch logs
        LOG_GROUP="/aws/bedrock-agentcore/runtimes/${RUNTIME_ID}"
        echo "Deleting CloudWatch logs: $LOG_GROUP"
        aws logs delete-log-group --log-group-name "$LOG_GROUP" --region "$REGION" 2>/dev/null || echo "Log group not found"
        
        echo -e "${GREEN}✓${NC} Runtime cleanup complete"
    else
        echo "No runtime found in .env"
    fi
else
    echo "No .env file found"
fi

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Phase 3: Cleanup Environment${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Remove UV environment
if [ -d "$SCRIPT_DIR/phase3/.venv" ]; then
    echo "Removing UV virtual environment..."
    rm -rf "$SCRIPT_DIR/phase3/.venv"
    echo -e "${GREEN}✓${NC} UV environment removed"
fi

# Remove symlinks
cd "$PROJECT_ROOT"
for file in .venv pyproject.toml uv.lock; do
    if [ -L "$file" ]; then
        echo "Removing symlink: $file"
        rm -f "$file"
    fi
done

# Remove .env file
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Removing .env file..."
    rm -f "$PROJECT_ROOT/.env"
    echo -e "${GREEN}✓${NC} .env removed"
fi

echo -e "${GREEN}✓${NC} Phase 3 cleanup complete"

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Phase 2: Cleanup Fargate Resources${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

PHASE2_STACK="deep-insight-fargate-${ENVIRONMENT}"
ECR_REPO="deep-insight-fargate-runtime-${ENVIRONMENT}"
ECS_CLUSTER="deep-insight-cluster-${ENVIRONMENT}"

# Stop all running tasks
echo "Checking for running ECS tasks..."
RUNNING_TASKS=$(aws ecs list-tasks --cluster "$ECS_CLUSTER" --region "$REGION" --query 'taskArns[]' --output text 2>/dev/null || echo "")

if [ -n "$RUNNING_TASKS" ]; then
    echo "Stopping running tasks..."
    for TASK in $RUNNING_TASKS; do
        echo "  Stopping: $TASK"
        aws ecs stop-task --cluster "$ECS_CLUSTER" --task "$TASK" --region "$REGION" 2>/dev/null || true
    done
    echo "Waiting 30 seconds for tasks to stop..."
    sleep 30
fi

# Delete CloudFormation stack
PHASE2_STATUS=$(aws cloudformation describe-stacks --stack-name "$PHASE2_STACK" --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$PHASE2_STATUS" != "NOT_FOUND" ]; then
    echo "Deleting Phase 2 CloudFormation stack: $PHASE2_STACK"
    aws cloudformation delete-stack --stack-name "$PHASE2_STACK" --region "$REGION"

    echo "Waiting for stack deletion..."
    aws cloudformation wait stack-delete-complete --stack-name "$PHASE2_STACK" --region "$REGION" 2>&1
    WAIT_EXIT_CODE=$?

    # Verify actual deletion status
    FINAL_STATUS=$(aws cloudformation describe-stacks --stack-name "$PHASE2_STACK" --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "DELETED")

    if [ "$FINAL_STATUS" == "DELETED" ] || [[ "$FINAL_STATUS" == *"does not exist"* ]]; then
        echo -e "${GREEN}✓${NC} Phase 2 stack deleted"
    elif [ "$FINAL_STATUS" == "DELETE_FAILED" ]; then
        echo -e "${RED}✗${NC} Phase 2 stack deletion FAILED!"
        echo ""
        echo "Failed resources:"
        aws cloudformation describe-stack-events --stack-name "$PHASE2_STACK" --region "$REGION" --max-items 10 --query 'StackEvents[?ResourceStatus==`DELETE_FAILED`].[LogicalResourceId,ResourceType,ResourceStatusReason]' --output table
        echo ""
        echo -e "${YELLOW}Manual intervention required. Check the AWS Console or run:${NC}"
        echo "  aws cloudformation describe-stack-events --stack-name $PHASE2_STACK --region $REGION"
        exit 1
    else
        echo -e "${GREEN}✓${NC} Phase 2 stack status: $FINAL_STATUS"
    fi
else
    echo "Phase 2 stack not found"
fi

# Clean up orphaned ECR repository (if exists outside CloudFormation)
echo "Checking for orphaned ECR repository..."
ECR_EXISTS=$(aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" 2>/dev/null || echo "")

if [ -n "$ECR_EXISTS" ]; then
    echo "Found orphaned ECR repository: $ECR_REPO"
    echo "Deleting all images..."
    aws ecr batch-delete-image \
        --repository-name "$ECR_REPO" \
        --region "$REGION" \
        --image-ids "$(aws ecr list-images --repository-name "$ECR_REPO" --region "$REGION" --query 'imageIds[*]' --output json)" 2>/dev/null || true
    
    echo "Deleting repository..."
    aws ecr delete-repository --repository-name "$ECR_REPO" --region "$REGION" --force 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Orphaned ECR repository deleted"
fi

# Clean up orphaned ECS cluster (if exists outside CloudFormation)
echo "Checking for orphaned ECS cluster..."
CLUSTER_EXISTS=$(aws ecs describe-clusters --clusters "$ECS_CLUSTER" --region "$REGION" --query 'clusters[0].status' --output text 2>/dev/null || echo "")

if [ "$CLUSTER_EXISTS" == "ACTIVE" ]; then
    echo "Found orphaned ECS cluster: $ECS_CLUSTER"
    aws ecs delete-cluster --cluster "$ECS_CLUSTER" --region "$REGION" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Orphaned ECS cluster deleted"
fi

echo -e "${GREEN}✓${NC} Phase 2 cleanup complete"

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Phase 1: Cleanup VPC Infrastructure${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

PHASE1_STACK="deep-insight-infrastructure-${ENVIRONMENT}"

# Get VPC ID before attempting deletion
VPC_ID=$(aws cloudformation describe-stacks --stack-name "$PHASE1_STACK" --region "$REGION" --query 'Stacks[0].Outputs[?OutputKey==`VPCId`].OutputValue' --output text 2>/dev/null || echo "")

if [ -n "$VPC_ID" ]; then
    echo "Checking for orphaned resources in VPC: $VPC_ID"

    # Check for GuardDuty VPC Endpoints
    GUARDDUTY_ENDPOINTS=$(aws ec2 describe-vpc-endpoints --region "$REGION" --filters "Name=vpc-id,Values=$VPC_ID" "Name=service-name,Values=*guardduty*" --query 'VpcEndpoints[].VpcEndpointId' --output text 2>/dev/null || echo "")

    if [ -n "$GUARDDUTY_ENDPOINTS" ]; then
        echo "Found GuardDuty VPC endpoints - deleting..."
        for ENDPOINT in $GUARDDUTY_ENDPOINTS; do
            echo "  Deleting VPC endpoint: $ENDPOINT"
            aws ec2 delete-vpc-endpoints --region "$REGION" --vpc-endpoint-ids "$ENDPOINT" 2>/dev/null || true
        done
        echo "Waiting 30 seconds for VPC endpoints to delete..."
        sleep 30
    fi

    # Check for GuardDuty Security Groups
    GUARDDUTY_SGS=$(aws ec2 describe-security-groups --region "$REGION" --filters "Name=vpc-id,Values=$VPC_ID" "Name=group-name,Values=*GuardDuty*" --query 'SecurityGroups[].GroupId' --output text 2>/dev/null || echo "")

    if [ -n "$GUARDDUTY_SGS" ]; then
        echo "Found GuardDuty security groups - deleting..."
        for SG in $GUARDDUTY_SGS; do
            echo "  Deleting security group: $SG"
            aws ec2 delete-security-group --region "$REGION" --group-id "$SG" 2>/dev/null || true
        done
    fi

    echo -e "${GREEN}✓${NC} Orphaned resources cleanup complete"
    echo ""
fi

PHASE1_STATUS=$(aws cloudformation describe-stacks --stack-name "$PHASE1_STACK" --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$PHASE1_STATUS" != "NOT_FOUND" ]; then
    echo "Deleting Phase 1 CloudFormation stack: $PHASE1_STACK"
    aws cloudformation delete-stack --stack-name "$PHASE1_STACK" --region "$REGION"

    echo "Waiting for stack deletion (this may take 10-15 minutes)..."
    aws cloudformation wait stack-delete-complete --stack-name "$PHASE1_STACK" --region "$REGION" 2>&1
    WAIT_EXIT_CODE=$?

    # Verify actual deletion status
    FINAL_STATUS=$(aws cloudformation describe-stacks --stack-name "$PHASE1_STACK" --region "$REGION" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "DELETED")

    if [ "$FINAL_STATUS" == "DELETED" ] || [[ "$FINAL_STATUS" == *"does not exist"* ]]; then
        echo -e "${GREEN}✓${NC} Phase 1 stack deleted"
    elif [ "$FINAL_STATUS" == "DELETE_FAILED" ]; then
        echo -e "${RED}✗${NC} Phase 1 stack deletion FAILED!"
        echo ""
        echo "Failed resources:"
        aws cloudformation describe-stack-events --stack-name "$PHASE1_STACK" --region "$REGION" --max-items 10 --query 'StackEvents[?ResourceStatus==`DELETE_FAILED`].[LogicalResourceId,ResourceType,ResourceStatusReason]' --output table
        echo ""
        echo -e "${YELLOW}Manual intervention required.${NC}"
        echo -e "${YELLOW}Common issues:${NC}"
        echo "  1. VPC Endpoints created outside CloudFormation (e.g., GuardDuty)"
        echo "  2. Security Groups with dependencies"
        echo "  3. Network Interfaces still attached"
        echo ""
        echo "To investigate, run:"
        echo "  aws cloudformation describe-stack-events --stack-name $PHASE1_STACK --region $REGION"
        echo ""
        echo "Check for orphaned VPC resources in VPC ID from stack outputs"
        exit 1
    else
        echo -e "${GREEN}✓${NC} Phase 1 stack status: $FINAL_STATUS"
    fi
else
    echo "Phase 1 stack not found"
fi

echo ""
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Cleanup S3 Buckets${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Delete nested templates bucket
TEMPLATE_BUCKET="deep-insight-templates-${ENVIRONMENT}-${REGION}-${AWS_ACCOUNT_ID}"
echo "Checking for template bucket: $TEMPLATE_BUCKET"
if aws s3 ls "s3://$TEMPLATE_BUCKET" --region "$REGION" 2>/dev/null; then
    echo "Deleting template bucket..."
    aws s3 rb "s3://$TEMPLATE_BUCKET" --force --region "$REGION" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Template bucket deleted"
else
    echo "Template bucket not found"
fi

# Delete session data bucket
SESSION_BUCKET="deep-insight-logs-${REGION}-${AWS_ACCOUNT_ID}"
echo "Checking for session data bucket: $SESSION_BUCKET"
if aws s3 ls "s3://$SESSION_BUCKET" --region "$REGION" 2>/dev/null; then
    echo "Deleting session data bucket..."
    aws s3 rb "s3://$SESSION_BUCKET" --force --region "$REGION" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Session data bucket deleted"
else
    echo "Session data bucket not found"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}✓ Complete Cleanup Finished!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "All resources have been deleted from region: $REGION"
echo ""
echo "To redeploy:"
echo "  cd production_deployment/scripts"
echo "  ./deploy_phase1_phase2.sh $ENVIRONMENT $REGION"
echo ""
