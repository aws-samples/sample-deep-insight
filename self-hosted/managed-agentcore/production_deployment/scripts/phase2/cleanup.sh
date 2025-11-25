#!/bin/bash
#
# Cleanup Phase 2 Fargate Runtime
# Safely delete CloudFormation stack and related resources
#
# Usage:
#   ./scripts/phase2/cleanup.sh [environment] [options]
#
# Arguments:
#   environment  - Environment name (dev, staging, prod) [default: prod]
#
# Options:
#   --region REGION  - AWS region (e.g., us-west-2, us-east-1)
#   --force, -f      - Force delete without confirmation
#
# Examples:
#   ./scripts/phase2/cleanup.sh prod --region us-east-1
#   ./scripts/phase2/cleanup.sh prod --region us-west-2 --force
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Parse arguments
ENVIRONMENT="prod"
FORCE_MODE=false
REGION=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --force|-f)
            FORCE_MODE=true
            shift
            ;;
        --region)
            REGION="$2"
            shift 2
            ;;
        dev|staging|prod)
            ENVIRONMENT=$1
            shift
            ;;
        *)
            shift
            ;;
    esac
done

PROJECT_NAME="deep-insight"
STACK_NAME="${PROJECT_NAME}-fargate-${ENVIRONMENT}"

# Region is REQUIRED for cleanup to prevent accidental deletions
if [ -z "$REGION" ]; then
    echo -e "${RED}Error: Region parameter is required for cleanup${NC}"
    echo ""
    echo "Usage: $0 [environment] --region <region> [--force]"
    echo ""
    echo "Examples:"
    echo "  $0 prod --region us-east-1"
    echo "  $0 prod --region us-west-2"
    echo ""
    echo "This is a safety measure to prevent accidental deletion in the wrong region."
    exit 1
fi

AWS_REGION="$REGION"

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo -e "${RED}============================================${NC}"
echo -e "${RED}Phase 2 Fargate Runtime Cleanup${NC}"
if [ "$FORCE_MODE" = true ]; then
    echo -e "${RED}⚡ FORCE MODE - No confirmation required${NC}"
fi
echo -e "${RED}============================================${NC}"
echo ""
echo "Stack Name: $STACK_NAME"
echo "Region: $AWS_REGION"
echo ""

# Warning
echo -e "${YELLOW}⚠️  WARNING: This will delete Phase 2 CloudFormation resources!${NC}"
echo ""
echo "Resources to be deleted:"
echo "  - CloudFormation Stack: $STACK_NAME"
echo "    • ECS Cluster (after stopping all tasks)"
echo "    • Task Definitions (all versions)"
echo "    • CloudWatch Log Group"
echo "  - ECR Repository (optional, will prompt)"
echo ""
echo "Note: CloudFormation manages all resources except ECR (DeletionPolicy: Retain)"
echo ""

# Confirmation (skip if --force)
if [ "$FORCE_MODE" = false ]; then
    read -p "Are you sure? (type 'yes' to confirm): " CONFIRM

    if [ "$CONFIRM" != "yes" ]; then
        echo "Cleanup cancelled."
        exit 0
    fi
else
    echo -e "${YELLOW}⚡ Force mode: Skipping confirmation${NC}"
    sleep 2  # Give user 2 seconds to cancel with Ctrl+C
fi

echo ""
echo -e "${YELLOW}Starting cleanup...${NC}"

# ============================================
# Step 1: Load .env to get resource names
# ============================================
echo ""
echo -e "${BLUE}Step 1: Loading environment variables...${NC}"

ENV_FILE="$(dirname "$0")/../../.env"
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
    echo -e "${GREEN}✓ Loaded .env file${NC}"
else
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo "Will attempt cleanup using default naming conventions"
fi

# Set resource names (use from .env or construct from defaults)
ECR_REPOSITORY_NAME="${ECR_REPOSITORY_NAME:-${PROJECT_NAME}-fargate-runtime-${ENVIRONMENT}}"
ECS_CLUSTER_NAME="${ECS_CLUSTER_NAME:-${PROJECT_NAME}-cluster-${ENVIRONMENT}}"
TASK_DEFINITION_FAMILY="${PROJECT_NAME}-fargate-task-${ENVIRONMENT}"
LOG_GROUP_NAME="${LOG_GROUP_NAME:-/ecs/${PROJECT_NAME}-fargate-${ENVIRONMENT}}"

echo "ECR Repository: $ECR_REPOSITORY_NAME"
echo "ECS Cluster: $ECS_CLUSTER_NAME"
echo "Task Definition: $TASK_DEFINITION_FAMILY"
echo "Log Group: $LOG_GROUP_NAME"

# ============================================
# Step 2: Stop all running ECS tasks
# ============================================
echo ""
echo -e "${BLUE}Step 2: Stopping all running ECS tasks...${NC}"

CLUSTER_EXISTS=$(aws ecs describe-clusters \
    --clusters "$ECS_CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --query 'clusters[0].clusterName' \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$CLUSTER_EXISTS" != "NOT_FOUND" ] && [ "$CLUSTER_EXISTS" != "None" ]; then
    RUNNING_TASKS=$(aws ecs list-tasks \
        --cluster "$ECS_CLUSTER_NAME" \
        --region "$AWS_REGION" \
        --desired-status RUNNING \
        --query 'taskArns[*]' \
        --output text)

    if [ -n "$RUNNING_TASKS" ]; then
        echo "Found running tasks. Stopping..."
        for TASK_ARN in $RUNNING_TASKS; do
            echo "  Stopping: $TASK_ARN"
            aws ecs stop-task \
                --cluster "$ECS_CLUSTER_NAME" \
                --task "$TASK_ARN" \
                --region "$AWS_REGION" \
                --output text > /dev/null
        done
        echo "Waiting for tasks to stop (30 seconds)..."
        sleep 30
        echo -e "${GREEN}✓ All tasks stopped${NC}"
    else
        echo "No running tasks found"
    fi
else
    echo "ECS Cluster not found (may have been deleted already)"
fi

# ============================================
# Step 3: Check if CloudFormation stack exists
# ============================================
echo ""
echo -e "${BLUE}Step 3: Checking CloudFormation stack status...${NC}"

STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "STACK_NOT_FOUND")

if [ "$STACK_STATUS" == "STACK_NOT_FOUND" ]; then
    echo -e "${YELLOW}Stack not found: $STACK_NAME${NC}"
    echo "Skipping stack deletion."
else
    echo "Current status: $STACK_STATUS"

    # ============================================
    # Step 4: Delete CloudFormation Stack
    # ============================================
    echo ""
    echo -e "${BLUE}Step 4: Deleting CloudFormation stack...${NC}"
    echo "This will delete: ECS Cluster, Task Definition, Log Group"
    echo "Note: ECR Repository is retained (DeletionPolicy: Retain)"
    echo "This will take 2-5 minutes."
    echo ""

    aws cloudformation delete-stack \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION"

    echo "Delete initiated. Waiting for completion..."

    # Monitor deletion with timeout
    START_TIME=$(date +%s)
    TIMEOUT_SECONDS=$((10 * 60))  # 10 minutes timeout

    while true; do
        CURRENT_TIME=$(date +%s)
        ELAPSED=$((CURRENT_TIME - START_TIME))

        if [ $ELAPSED -gt $TIMEOUT_SECONDS ]; then
            echo ""
            echo -e "${RED}⏰ Timeout reached (10 minutes)${NC}"
            echo ""
            echo "Stack deletion is still in progress."
            echo "Check status manually:"
            echo "  aws cloudformation describe-stacks --stack-name $STACK_NAME"
            echo ""
            exit 1
        fi

        CURRENT_STATUS=$(aws cloudformation describe-stacks \
            --stack-name "$STACK_NAME" \
            --region "$AWS_REGION" \
            --query 'Stacks[0].StackStatus' \
            --output text 2>/dev/null || echo "DELETED")

        if [ "$CURRENT_STATUS" == "DELETED" ]; then
            echo -e "${GREEN}✓ Stack deleted successfully${NC}"
            break
        elif [[ "$CURRENT_STATUS" == *"FAILED"* ]]; then
            echo ""
            echo -e "${RED}✗ Stack deletion failed: $CURRENT_STATUS${NC}"
            echo ""
            echo "Fetching failed events..."
            aws cloudformation describe-stack-events \
                --stack-name "$STACK_NAME" \
                --region "$AWS_REGION" \
                --query 'StackEvents[?ResourceStatus==`DELETE_FAILED`] | [0:5].[Timestamp,LogicalResourceId,ResourceStatusReason]' \
                --output table
            echo ""
            echo "Manual cleanup may be required."
            echo "Check CloudFormation console for details."
            exit 1
        else
            echo -ne "\r  Status: $CURRENT_STATUS (${ELAPSED}s elapsed)"
            sleep 10
        fi
    done
fi

# ============================================
# Step 5: Clean up ECR Repository (Optional)
# ============================================
echo ""
echo -e "${BLUE}Step 5: ECR Repository cleanup (optional)...${NC}"

REPO_EXISTS=$(aws ecr describe-repositories \
    --repository-names "$ECR_REPOSITORY_NAME" \
    --region "$AWS_REGION" \
    --query 'repositories[0].repositoryName' \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$REPO_EXISTS" != "NOT_FOUND" ]; then
    IMAGE_COUNT=$(aws ecr list-images \
        --repository-name "$ECR_REPOSITORY_NAME" \
        --region "$AWS_REGION" \
        --query 'length(imageIds)' \
        --output text 2>/dev/null || echo "0")

    echo "Found ECR repository: $ECR_REPOSITORY_NAME ($IMAGE_COUNT images)"
    echo "Note: ECR is managed by CloudFormation with DeletionPolicy: Retain"

    if [ "$FORCE_MODE" = false ]; then
        read -p "Delete ECR repository and all images? (y/N): " DELETE_ECR
        if [ "$DELETE_ECR" == "y" ] || [ "$DELETE_ECR" == "Y" ]; then
            aws ecr delete-repository \
                --repository-name "$ECR_REPOSITORY_NAME" \
                --region "$AWS_REGION" \
                --force > /dev/null
            echo -e "${GREEN}✓ ECR repository and $IMAGE_COUNT images deleted${NC}"
        else
            echo -e "${YELLOW}ECR repository kept: $ECR_REPOSITORY_NAME${NC}"
        fi
    else
        echo -e "${YELLOW}⚡ Force mode: Auto-deleting ECR repository${NC}"
        aws ecr delete-repository \
            --repository-name "$ECR_REPOSITORY_NAME" \
            --region "$AWS_REGION" \
            --force > /dev/null
        echo -e "${GREEN}✓ ECR repository and $IMAGE_COUNT images deleted${NC}"
    fi
else
    echo "ECR repository not found (may have been deleted already)"
fi

# ============================================
# Step 6: Clean up .env file Phase 2 section
# ============================================
echo ""
echo -e "${BLUE}Step 6: Cleaning up .env file...${NC}"

if [ -f "$ENV_FILE" ]; then
    if [ "$FORCE_MODE" = false ]; then
        read -p "Remove Phase 2 variables from .env file? (y/N): " DELETE_ENV_SECTION
        if [ "$DELETE_ENV_SECTION" == "y" ] || [ "$DELETE_ENV_SECTION" == "Y" ]; then
            # Remove Phase 2 section from .env (lines between "# Phase 2" and next "# Phase" or EOF)
            sed -i '/^# Phase 2 Outputs/,/^# Phase [3-9]/d' "$ENV_FILE" 2>/dev/null || true
            echo -e "${GREEN}✓ Phase 2 section removed from .env${NC}"
        else
            echo -e "${YELLOW}.env file kept unchanged${NC}"
        fi
    else
        echo -e "${YELLOW}⚡ Force mode: Auto-removing Phase 2 section from .env${NC}"
        sed -i '/^# Phase 2 Outputs/,/^# Phase [3-9]/d' "$ENV_FILE" 2>/dev/null || true
        echo -e "${GREEN}✓ Phase 2 section removed from .env${NC}"
    fi
else
    echo ".env file not found"
fi

# ============================================
# Note: Task Definitions are managed by CloudFormation
# They will be deleted automatically when the stack is deleted
# ============================================

# ============================================
# Summary
# ============================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}✓ Phase 2 Cleanup Complete!${NC}"
if [ "$FORCE_MODE" = true ]; then
    echo -e "${GREEN}⚡ Force Mode - All resources deleted${NC}"
fi
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Cleaned up:"
echo "  ✓ CloudFormation stack: $STACK_NAME"
echo "    - ECS Cluster"
echo "    - Task Definitions (all versions)"
echo "    - CloudWatch Log Group"
if [ "$FORCE_MODE" = true ]; then
    echo "  ✓ ECR repository and Docker images (auto-deleted)"
    echo "  ✓ .env Phase 2 section removed (auto)"
else
    echo "  ✓ ECR repository (if you selected 'y')"
    echo "  ✓ .env Phase 2 section (if you selected 'y')"
fi
echo ""
echo "Note: ECR has DeletionPolicy: Retain for data protection"
echo "Note: Phase 1 infrastructure (VPC, ALB, etc.) remains intact"
echo ""
echo "You can now redeploy Phase 2:"
echo "  ./scripts/phase2/deploy.sh $ENVIRONMENT"
echo ""
