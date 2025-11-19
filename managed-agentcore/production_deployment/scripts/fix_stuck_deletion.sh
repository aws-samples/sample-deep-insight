#!/bin/bash
#
# Fix Stuck CloudFormation Deletion
# Monitors ENI cleanup and retries stack deletion
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REGION=us-west-2
ENI_ID=eni-00acff7c1d7a3d40b
RUNTIME_ID=deep_insight_runtime_vpc-xFtM9I8wUL
SG_STACK=deep-insight-infrastructure-prod-SecurityGroupsStack-1VHB3GPP2WK2J
PARENT_STACK=deep-insight-infrastructure-prod

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Monitoring ENI Cleanup${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Monitor runtime deletion
echo "Checking runtime status..."
RUNTIME_STATUS=$(aws bedrock-agentcore-control get-agent-runtime \
    --agent-runtime-id "$RUNTIME_ID" \
    --region "$REGION" \
    --query 'status' \
    --output text 2>&1 || echo "DELETED")

echo "Runtime status: $RUNTIME_STATUS"

if [ "$RUNTIME_STATUS" == "DELETING" ]; then
    echo -e "${YELLOW}Waiting for runtime deletion (checking every 15 seconds)...${NC}"

    for i in {1..20}; do
        sleep 15
        RUNTIME_STATUS=$(aws bedrock-agentcore-control get-agent-runtime \
            --agent-runtime-id "$RUNTIME_ID" \
            --region "$REGION" \
            --query 'status' \
            --output text 2>&1 || echo "DELETED")

        echo "  [$i/20] Runtime status: $RUNTIME_STATUS"

        if [[ "$RUNTIME_STATUS" == "DELETED" ]] || [[ "$RUNTIME_STATUS" == *"Could not find"* ]]; then
            echo -e "${GREEN}✓ Runtime deleted${NC}"
            break
        fi
    done
fi

echo ""
echo -e "${BLUE}Checking ENI status...${NC}"

# Monitor ENI deletion
for i in {1..20}; do
    ENI_STATUS=$(aws ec2 describe-network-interfaces \
        --region "$REGION" \
        --network-interface-ids "$ENI_ID" \
        --query 'NetworkInterfaces[0].Status' \
        --output text 2>&1 || echo "DELETED")

    echo "  [$i/20] ENI status: $ENI_STATUS"

    if [[ "$ENI_STATUS" == "DELETED" ]] || [[ "$ENI_STATUS" == *"InvalidNetworkInterfaceID"* ]] || [[ "$ENI_STATUS" == *"does not exist"* ]]; then
        echo -e "${GREEN}✓ ENI deleted${NC}"
        echo ""
        break
    fi

    if [ $i -lt 20 ]; then
        echo "  Waiting 15 seconds..."
        sleep 15
    fi
done

# Check final ENI status
FINAL_ENI=$(aws ec2 describe-network-interfaces \
    --region "$REGION" \
    --network-interface-ids "$ENI_ID" 2>&1 || echo "DELETED")

if [[ "$FINAL_ENI" == *"InvalidNetworkInterfaceID"* ]] || [[ "$FINAL_ENI" == "DELETED" ]]; then
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}✓ ENI Cleanup Complete!${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""
    echo "Now retrying CloudFormation stack deletion..."
    echo ""

    # Retry nested stack deletion
    echo "Step 1: Deleting nested SecurityGroups stack..."
    aws cloudformation delete-stack \
        --stack-name "$SG_STACK" \
        --region "$REGION" 2>/dev/null || echo "Stack already deleted or not found"

    echo "Waiting for nested stack deletion..."
    aws cloudformation wait stack-delete-complete \
        --stack-name "$SG_STACK" \
        --region "$REGION" 2>/dev/null || echo "Done"

    echo ""
    echo "Step 2: Continuing parent stack deletion..."
    aws cloudformation continue-update-rollback \
        --stack-name "$PARENT_STACK" \
        --region "$REGION" 2>/dev/null || \
    aws cloudformation delete-stack \
        --stack-name "$PARENT_STACK" \
        --region "$REGION" 2>/dev/null || echo "Initiated deletion"

    echo ""
    echo -e "${GREEN}✓ Stack deletion initiated${NC}"
    echo ""
    echo "Monitor progress with:"
    echo "  aws cloudformation describe-stacks --stack-name $PARENT_STACK --region $REGION"

else
    echo -e "${RED}============================================${NC}"
    echo -e "${RED}⚠️  ENI Still Exists${NC}"
    echo -e "${RED}============================================${NC}"
    echo ""
    echo "The ENI is still present. This might require manual intervention."
    echo ""
    echo "Options:"
    echo "1. Wait longer (runtime deletion can take up to 10 minutes)"
    echo "2. Contact AWS Support if the ENI persists after 15 minutes"
    echo ""
    echo "ENI Details:"
    aws ec2 describe-network-interfaces \
        --region "$REGION" \
        --network-interface-ids "$ENI_ID" \
        --output table
fi
