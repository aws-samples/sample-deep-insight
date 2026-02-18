#!/bin/bash
set -e

# ============================================================
# Add VPN CIDR inbound rule to ALB Security Group
#
# The existing ALB SG only allows inbound from the AgentCore SG.
# This script adds an inbound rule so that users on the VPN
# can reach the BFF via the ALB on port 80.
#
# Usage:
#   bash add_alb_sg_rule.sh <ALB_SG_ID> <ALLOWED_CIDR> [REGION]
#
# Examples:
#   bash add_alb_sg_rule.sh sg-0da8890bd65a94906 "10.0.0.0/8"
#   bash add_alb_sg_rule.sh sg-0da8890bd65a94906 "54.239.0.0/16" us-west-2
# ============================================================

ALB_SG_ID=$1
ALLOWED_CIDR=$2
REGION=${3:-us-west-2}

if [ -z "$ALB_SG_ID" ] || [ -z "$ALLOWED_CIDR" ]; then
  echo "Usage: bash add_alb_sg_rule.sh <ALB_SG_ID> <ALLOWED_CIDR> [REGION]"
  echo ""
  echo "Arguments:"
  echo "  ALB_SG_ID     ALB Security Group ID (e.g. sg-0abc1234)"
  echo "  ALLOWED_CIDR  VPN or internal IP CIDR to allow (e.g. 10.0.0.0/8)"
  echo "  REGION        AWS region (default: us-west-2)"
  exit 1
fi

echo "=== Add ALB SG Inbound Rule ==="
echo "ALB SG:       ${ALB_SG_ID}"
echo "Allowed CIDR: ${ALLOWED_CIDR}"
echo "Region:       ${REGION}"
echo ""

# Check if the rule already exists
EXISTING=$(aws ec2 describe-security-group-rules \
  --filters "Name=group-id,Values=${ALB_SG_ID}" \
  --region "${REGION}" \
  --query "SecurityGroupRules[?IsEgress==\`false\` && IpProtocol==\`tcp\` && FromPort==\`80\` && ToPort==\`80\` && CidrIpv4==\`${ALLOWED_CIDR}\`]" \
  --output text 2>/dev/null || true)

if [ -n "$EXISTING" ]; then
  echo "Rule already exists: TCP 80 from ${ALLOWED_CIDR} — skipping."
  exit 0
fi

# Add inbound rule for TCP 80
aws ec2 authorize-security-group-ingress \
  --group-id "${ALB_SG_ID}" \
  --protocol tcp \
  --port 80 \
  --cidr "${ALLOWED_CIDR}" \
  --region "${REGION}" > /dev/null

echo "Added: TCP 80 from ${ALLOWED_CIDR} to ${ALB_SG_ID}"
