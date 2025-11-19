#!/bin/bash
#
# Cleanup Orphaned Resources
# Run this after AWS has released the orphaned ENI
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REGION=us-west-2
ENI_ID=eni-00acff7c1d7a3d40b
SUBNET_ID=subnet-067f7c256784b454d
SG_ID=sg-0c0476f3543003739
VPC_ID=vpc-08b063bd039214742

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Orphaned Resources Cleanup${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# Check ENI status
echo "Checking ENI status..."
ENI_STATUS=$(aws ec2 describe-network-interfaces \
    --region "$REGION" \
    --network-interface-ids "$ENI_ID" \
    --query 'NetworkInterfaces[0].Status' \
    --output text 2>&1 || echo "DELETED")

if [[ "$ENI_STATUS" == "DELETED" ]] || [[ "$ENI_STATUS" == *"InvalidNetworkInterfaceID"* ]] || [[ "$ENI_STATUS" == *"does not exist"* ]]; then
    echo -e "${GREEN}✓ ENI has been cleaned up by AWS${NC}"
    echo ""

    # Now we can delete the other resources
    echo "Step 1: Deleting Security Group..."
    aws ec2 delete-security-group \
        --region "$REGION" \
        --group-id "$SG_ID" 2>&1 && \
        echo -e "${GREEN}✓ Security Group deleted${NC}" || \
        echo -e "${YELLOW}⚠️  Security Group may already be deleted${NC}"

    echo ""
    echo "Step 2: Deleting Subnet..."
    aws ec2 delete-subnet \
        --region "$REGION" \
        --subnet-id "$SUBNET_ID" 2>&1 && \
        echo -e "${GREEN}✓ Subnet deleted${NC}" || \
        echo -e "${YELLOW}⚠️  Subnet may already be deleted${NC}"

    echo ""
    echo "Step 3: Deleting VPC..."
    aws ec2 delete-vpc \
        --region "$REGION" \
        --vpc-id "$VPC_ID" 2>&1 && \
        echo -e "${GREEN}✓ VPC deleted${NC}" || \
        echo -e "${YELLOW}⚠️  VPC may already be deleted${NC}"

    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}✓ Cleanup Complete!${NC}"
    echo -e "${GREEN}============================================${NC}"
else
    echo -e "${YELLOW}============================================${NC}"
    echo -e "${YELLOW}⚠️  ENI Still Present${NC}"
    echo -e "${YELLOW}============================================${NC}"
    echo ""
    echo "ENI Status: $ENI_STATUS"
    echo ""
    echo "The ENI is still present. AWS typically cleans up"
    echo "orphaned Bedrock AgentCore ENIs within a few hours"
    echo "after runtime deletion."
    echo ""
    echo "Current orphaned resources:"
    echo "  - ENI:            $ENI_ID"
    echo "  - Security Group: $SG_ID"
    echo "  - Subnet:         $SUBNET_ID"
    echo "  - VPC:            $VPC_ID"
    echo ""
    echo "These resources do NOT incur costs."
    echo ""
    echo "Run this script again later to clean them up,"
    echo "or wait for AWS to automatically remove them."
    echo ""
    echo "To force check current status:"
    echo "  aws ec2 describe-network-interfaces \\"
    echo "    --region $REGION \\"
    echo "    --network-interface-ids $ENI_ID"
fi
