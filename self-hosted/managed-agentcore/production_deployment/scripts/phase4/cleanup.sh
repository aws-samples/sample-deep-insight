#!/bin/bash

#==============================================================================
# Phase 4: AgentCore Runtime Cleanup Script
#==============================================================================
# Description: Delete AgentCore Runtime created in Phase 4
# Usage: ./cleanup.sh [environment] --region <region> [--force]
#
# Arguments:
#   environment  - Environment name (dev, staging, prod) [default: prod]
#
# Options:
#   --region REGION  - AWS region (e.g., us-west-2, us-east-1) [REQUIRED]
#   --force, -f      - Force delete without confirmation
#
# Examples:
#   ./cleanup.sh prod --region us-east-1
#   ./cleanup.sh prod --region us-west-2 --force
#==============================================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Phase 4: AgentCore Runtime Cleanup${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Region: ${AWS_REGION}${NC}"
if [ "$FORCE_MODE" = true ]; then
    echo -e "${YELLOW}Mode: FORCE (automatic deletion)${NC}"
else
    echo -e "${YELLOW}Mode: INTERACTIVE (confirmation required)${NC}"
fi
echo -e "${BLUE}============================================${NC}"
echo ""

# Check current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROD_DEPLOY_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$PROD_DEPLOY_DIR/.." && pwd)"

# .env file check (must be at project root, not production_deployment)
ENV_FILE="$PROJECT_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}✗ .env file not found${NC}"
    exit 1
fi

# Load .env
source "$ENV_FILE"

# Check RUNTIME_ARN
if [ -z "$RUNTIME_ARN" ]; then
    echo -e "${YELLOW}⚠ RUNTIME_ARN is not set${NC}"
    echo -e "${YELLOW}  Phase 4 not deployed or already cleaned up${NC}"
    exit 0
fi

echo -e "${YELLOW}The following resources will be deleted:${NC}"
echo -e "  - AgentCore Runtime: ${RUNTIME_ARN}"
echo -e "  - ECR Repository: ${RUNTIME_NAME} (if created by bedrock_agentcore)"
echo -e "  - agentcore-runtime/ directory"
echo -e "  - Phase 4 section in .env file"
echo ""

# Confirm (if not Force mode)
if [ "$FORCE_MODE" = false ]; then
    read -p "Do you want to continue? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cleanup cancelled${NC}"
        exit 0
    fi
    echo ""
fi

#------------------------------------------------------------------------------
# Step 1: Delete AgentCore Runtime
#------------------------------------------------------------------------------

echo -e "${YELLOW}[1/4] Deleting AgentCore Runtime...${NC}"

# Check if runtime exists
RUNTIME_INFO=$(aws bedrock-agentcore get-agent-runtime \
    --agent-runtime-arn "$RUNTIME_ARN" \
    --region "$AWS_REGION" \
    --output json 2>/dev/null || echo "")

if [ -n "$RUNTIME_INFO" ]; then
    echo "  - Runtime ARN: $RUNTIME_ARN"

    # Delete runtime
    if aws bedrock-agentcore delete-agent-runtime \
        --agent-runtime-arn "$RUNTIME_ARN" \
        --region "$AWS_REGION" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Runtime deletion request completed${NC}"

        # Wait for deletion (max 5 minutes)
        echo "  - Deletion in progress... (max 5 minutes)"
        MAX_WAIT=300
        ELAPSED=0
        while [ $ELAPSED -lt $MAX_WAIT ]; do
            RUNTIME_STATUS=$(aws bedrock-agentcore get-agent-runtime \
                --agent-runtime-arn "$RUNTIME_ARN" \
                --region "$AWS_REGION" \
                --query 'status' \
                --output text 2>/dev/null || echo "DELETED")

            if [ "$RUNTIME_STATUS" = "DELETED" ] || [ -z "$RUNTIME_STATUS" ]; then
                echo -e "${GREEN}  ✓ Runtime deletion completed${NC}"
                break
            fi

            echo "    Status: $RUNTIME_STATUS (${ELAPSED}s elapsed)"
            sleep 10
            ELAPSED=$((ELAPSED + 10))
        done

        if [ $ELAPSED -ge $MAX_WAIT ]; then
            echo -e "${YELLOW}  ⚠ Runtime deletion timeout (5 minutes)${NC}"
            echo -e "${YELLOW}    Please check manually in AWS Console${NC}"
        fi
    else
        echo -e "${YELLOW}  ⚠ Runtime deletion failed (may have already been deleted)${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠ Runtime not found (already deleted)${NC}"
fi

echo ""

#------------------------------------------------------------------------------
# Step 2: Delete ECR Repository (if created by bedrock_agentcore)
#------------------------------------------------------------------------------

echo -e "${YELLOW}[2/4] Checking ECR Repository...${NC}"

# Search for ECR Repository created by bedrock_agentcore toolkit
ECR_REPOS=$(aws ecr describe-repositories \
    --region "$AWS_REGION" \
    --query "repositories[?contains(repositoryName, '${RUNTIME_NAME}') || contains(repositoryName, 'bedrock') && contains(repositoryName, 'agentcore')].repositoryName" \
    --output text 2>/dev/null || echo "")

if [ -n "$ECR_REPOS" ]; then
    echo -e "${YELLOW}  Found the following ECR Repositories:${NC}"
    for REPO in $ECR_REPOS; do
        echo "    - $REPO"
    done
    echo ""

    # Confirm (if not Force mode)
    DELETE_ECR=false
    if [ "$FORCE_MODE" = true ]; then
        DELETE_ECR=true
    else
        read -p "  Do you want to delete ECR Repository? (y/N): " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            DELETE_ECR=true
        fi
    fi

    if [ "$DELETE_ECR" = true ]; then
        for REPO in $ECR_REPOS; do
            echo "  - Deleting ECR Repository: $REPO"
            if aws ecr delete-repository \
                --repository-name "$REPO" \
                --region "$AWS_REGION" \
                --force 2>/dev/null; then
                echo -e "${GREEN}    ✓ $REPO deletion completed${NC}"
            else
                echo -e "${YELLOW}    ⚠ $REPO deletion failed${NC}"
            fi
        done
    else
        echo -e "${YELLOW}  ECR Repository deletion skipped${NC}"
    fi
else
    echo -e "${GREEN}  ✓ No ECR Repository created by bedrock_agentcore${NC}"
fi

echo ""

#------------------------------------------------------------------------------
# Step 3: Delete agentcore-runtime/ directory
#------------------------------------------------------------------------------

echo -e "${YELLOW}[3/4] Deleting agentcore-runtime/ directory...${NC}"

RUNTIME_DIR="$PROD_DEPLOY_DIR/agentcore-runtime"

if [ -d "$RUNTIME_DIR" ]; then
    echo "  - Directory: $RUNTIME_DIR"

    # Confirm (if not Force mode)
    DELETE_DIR=false
    if [ "$FORCE_MODE" = true ]; then
        DELETE_DIR=true
    else
        read -p "  Do you want to delete agentcore-runtime/ directory? (y/N): " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            DELETE_DIR=true
        fi
    fi

    if [ "$DELETE_DIR" = true ]; then
        rm -rf "$RUNTIME_DIR"
        echo -e "${GREEN}  ✓ Directory deletion completed${NC}"
    else
        echo -e "${YELLOW}  Directory deletion skipped${NC}"
    fi
else
    echo -e "${GREEN}  ✓ Directory not found (already deleted)${NC}"
fi

echo ""

#------------------------------------------------------------------------------
# Step 4: Cleanup .env file
#------------------------------------------------------------------------------

echo -e "${YELLOW}[4/4] Cleaning up .env file...${NC}"

# Delete Phase 4 section
if grep -q "# Phase 4: AgentCore Runtime" "$ENV_FILE" || grep -q "# Phase 3: AgentCore Runtime" "$ENV_FILE"; then
    # Delete from Phase 3/4 section to next Phase section or end of file
    sed -i '/# Phase [34]: AgentCore Runtime/,/# Phase [0-9]/{ /# Phase [34]: AgentCore Runtime/d; /# Phase [0-9]/!d; }' "$ENV_FILE"

    # Delete if Phase 3/4 is at the end of file
    sed -i '/# Phase [34]: AgentCore Runtime/,$d' "$ENV_FILE"

    echo -e "${GREEN}  ✓ Phase 4 section removed from .env file${NC}"
else
    echo -e "${YELLOW}  ⚠ Phase 4 section not found in .env file${NC}"
fi

echo ""

#------------------------------------------------------------------------------
# Cleanup Complete
#------------------------------------------------------------------------------

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}✓ Phase 4 Cleanup Completed!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "${BLUE}Deleted Resources:${NC}"
echo -e "  - AgentCore Runtime"
echo -e "  - ECR Repository (optional)"
echo -e "  - agentcore-runtime/ directory (optional)"
echo -e "  - Phase 4 section in .env file"
echo ""
echo -e "${YELLOW}Note:${NC}"
echo -e "  - ENIs will be automatically deleted when Runtime is deleted (takes several minutes)"
echo -e "  - CloudWatch Logs will NOT be automatically deleted (manual deletion required)"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo -e "  - To redeploy Phase 4: cd ../../.. && uv run 01_create_agentcore_runtime_vpc.py"
echo -e "  - Phase 2 cleanup: ./scripts/phase2/cleanup.sh ${ENVIRONMENT} --region ${AWS_REGION}"
echo -e "  - Phase 1 cleanup: ./scripts/phase1/cleanup.sh ${ENVIRONMENT} --region ${AWS_REGION}"
echo ""
