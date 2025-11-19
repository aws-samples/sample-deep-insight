#!/bin/bash
#
# Cleanup Phase 1 Infrastructure
# Safely delete CloudFormation stack and related resources
#
# Usage:
#   ./scripts/phase1/cleanup.sh [environment] [options]
#
# Arguments:
#   environment  - Environment name (dev, staging, prod) [default: prod]
#
# Options:
#   --region REGION  - AWS region (e.g., us-west-2, us-east-1)
#   --force, -f      - Force delete without confirmation
#
# Examples:
#   ./scripts/phase1/cleanup.sh prod --region us-east-1
#   ./scripts/phase1/cleanup.sh prod --region us-west-2 --force
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

STACK_NAME="deep-insight-infrastructure-${ENVIRONMENT}"

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
S3_BUCKET_NAME="deep-insight-templates-${ENVIRONMENT}-${AWS_REGION}-${AWS_ACCOUNT_ID}"

echo -e "${RED}============================================${NC}"
echo -e "${RED}Phase 1 Infrastructure Cleanup${NC}"
if [ "$FORCE_MODE" = true ]; then
    echo -e "${RED}⚡ FORCE MODE - No confirmation required${NC}"
fi
echo -e "${RED}============================================${NC}"
echo ""
echo "Stack Name: $STACK_NAME"
echo "Region: $AWS_REGION"
echo "S3 Bucket: $S3_BUCKET_NAME"
echo ""

# Warning
echo -e "${YELLOW}⚠️  WARNING: This will delete all Phase 1 resources!${NC}"
echo ""
echo "Resources to be deleted:"
echo "  - VPC and all subnets"
echo "  - NAT Gateway and Elastic IP"
echo "  - 4 Security Groups"
echo "  - 6 VPC Endpoints"
echo "  - Internal ALB and Target Group"
echo "  - 2 IAM Roles"
echo "  - All 5 nested stacks"
echo "  - S3 bucket and nested templates"
echo "  - .env file"
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
# Step 1: Check if stack exists
# ============================================
echo ""
echo -e "${BLUE}Step 1: Checking stack status...${NC}"

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
    # Step 2: Delete CloudFormation Stack
    # ============================================
    echo ""
    echo -e "${BLUE}Step 2: Deleting CloudFormation stack...${NC}"
    echo "This will take 10-20 minutes."
    echo ""

    aws cloudformation delete-stack \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION"

    echo "Delete initiated. Waiting for completion..."

    # Monitor deletion with timeout
    START_TIME=$(date +%s)
    TIMEOUT_SECONDS=$((30 * 60))  # 30 minutes timeout

    while true; do
        CURRENT_TIME=$(date +%s)
        ELAPSED=$((CURRENT_TIME - START_TIME))

        if [ $ELAPSED -gt $TIMEOUT_SECONDS ]; then
            echo ""
            echo -e "${RED}⏰ Timeout reached (30 minutes)${NC}"
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
# Step 3: Clean up S3 Bucket (Nested Templates)
# ============================================
echo ""
echo -e "${BLUE}Step 3: Cleaning up S3 bucket...${NC}"

if aws s3 ls "s3://${S3_BUCKET_NAME}" 2>/dev/null; then
    echo "Found S3 bucket: $S3_BUCKET_NAME"

    # Check if bucket has nested templates
    OBJECT_COUNT=$(aws s3 ls "s3://${S3_BUCKET_NAME}/nested/" 2>/dev/null | wc -l)

    if [ "$OBJECT_COUNT" -gt 0 ]; then
        echo "Deleting nested templates..."
        aws s3 rm "s3://${S3_BUCKET_NAME}/nested/" --recursive
        echo -e "${GREEN}✓ Nested templates deleted${NC}"
    fi

    # Ask if user wants to delete the bucket (or auto-delete in force mode)
    echo ""
    if [ "$FORCE_MODE" = false ]; then
        read -p "Delete S3 bucket '$S3_BUCKET_NAME'? (y/N): " DELETE_BUCKET
        if [ "$DELETE_BUCKET" == "y" ] || [ "$DELETE_BUCKET" == "Y" ]; then
            # Delete all object versions and delete markers (handles versioned buckets)
            echo "Deleting all object versions and delete markers..."
            aws s3api delete-objects \
                --bucket "${S3_BUCKET_NAME}" \
                --delete "$(aws s3api list-object-versions \
                    --bucket "${S3_BUCKET_NAME}" \
                    --output json \
                    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}, Quiet: `true`}')" \
                2>/dev/null || true

            aws s3api delete-objects \
                --bucket "${S3_BUCKET_NAME}" \
                --delete "$(aws s3api list-object-versions \
                    --bucket "${S3_BUCKET_NAME}" \
                    --output json \
                    --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}, Quiet: `true`}')" \
                2>/dev/null || true

            # Now delete the empty bucket
            aws s3 rb "s3://${S3_BUCKET_NAME}"
            echo -e "${GREEN}✓ S3 bucket deleted${NC}"
        else
            echo -e "${YELLOW}S3 bucket kept: $S3_BUCKET_NAME${NC}"
            echo "  (Contains versioned nested templates)"
        fi
    else
        echo -e "${YELLOW}⚡ Force mode: Auto-deleting S3 bucket${NC}"
        # Delete all object versions and delete markers (handles versioned buckets)
        echo "Deleting all object versions and delete markers..."
        aws s3api delete-objects \
            --bucket "${S3_BUCKET_NAME}" \
            --delete "$(aws s3api list-object-versions \
                --bucket "${S3_BUCKET_NAME}" \
                --output json \
                --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}, Quiet: `true`}')" \
            2>/dev/null || true

        aws s3api delete-objects \
            --bucket "${S3_BUCKET_NAME}" \
            --delete "$(aws s3api list-object-versions \
                --bucket "${S3_BUCKET_NAME}" \
                --output json \
                --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}, Quiet: `true`}')" \
            2>/dev/null || true

        # Now delete the empty bucket
        aws s3 rb "s3://${S3_BUCKET_NAME}"
        echo -e "${GREEN}✓ S3 bucket deleted${NC}"
    fi
else
    echo -e "${YELLOW}S3 bucket not found (may have been deleted already)${NC}"
fi

# ============================================
# Step 4: Clean up .env file
# ============================================
echo ""
echo -e "${BLUE}Step 4: Cleaning up .env file...${NC}"

ENV_FILE="$(dirname "$0")/../../.env"
if [ -f "$ENV_FILE" ]; then
    if [ "$FORCE_MODE" = false ]; then
        read -p "Delete .env file? (y/N): " DELETE_ENV
        if [ "$DELETE_ENV" == "y" ] || [ "$DELETE_ENV" == "Y" ]; then
            rm "$ENV_FILE"
            echo -e "${GREEN}✓ .env file deleted${NC}"
        else
            echo -e "${YELLOW}.env file kept${NC}"
        fi
    else
        echo -e "${YELLOW}⚡ Force mode: Auto-deleting .env file${NC}"
        rm "$ENV_FILE"
        echo -e "${GREEN}✓ .env file deleted${NC}"
    fi
else
    echo ".env file not found"
fi

# ============================================
# Summary
# ============================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}✓ Cleanup Complete!${NC}"
if [ "$FORCE_MODE" = true ]; then
    echo -e "${GREEN}⚡ Force Mode - All resources deleted${NC}"
fi
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Cleaned up:"
echo "  ✓ CloudFormation stack (parent + 5 nested stacks)"
echo "  ✓ All AWS resources (VPC, Subnets, NAT, ALB, etc.)"
if [ "$FORCE_MODE" = true ]; then
    echo "  ✓ S3 bucket and nested templates (auto-deleted)"
    echo "  ✓ .env file (auto-deleted)"
else
    echo "  ✓ S3 bucket (if you selected 'y')"
    echo "  ✓ .env file (if you selected 'y')"
fi
echo ""
echo "You can now redeploy Phase 1:"
echo "  ./scripts/phase1/deploy.sh $ENVIRONMENT"
echo ""
