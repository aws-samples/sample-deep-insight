#!/bin/bash
#
# Phase 1: Infrastructure Deployment (Nested Stacks)
# Deploy VPC, Subnets, Security Groups, VPC Endpoints, ALB, IAM Roles
#
# Usage: ./scripts/phase1/deploy.sh <environment> --region <region> [options]
#   environment: dev, staging, prod (default: prod)
#   --region: AWS region (REQUIRED, e.g., us-east-1, us-west-2)
#   --parameter-overrides: CloudFormation parameter overrides (optional)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENVIRONMENT="${1:-prod}"

# Parse command-line arguments
REGION=""
PARAMETER_OVERRIDES=()
shift || true  # Remove first positional argument (ENVIRONMENT)

while [[ $# -gt 0 ]]; do
    case $1 in
        --region)
            REGION="$2"
            shift 2
            ;;
        --parameter-overrides)
            shift
            # Collect all remaining arguments as parameter overrides
            while [[ $# -gt 0 ]] && [[ ! "$1" =~ ^-- ]]; do
                PARAMETER_OVERRIDES+=("$1")
                shift
            done
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
    echo "  $0 dev --region us-east-1"
    echo ""
    echo "This is a safety measure to ensure deployment to the correct region."
    exit 1
fi

STACK_NAME="deep-insight-infrastructure-${ENVIRONMENT}"
TEMPLATE_FILE="$PROJECT_ROOT/cloudformation/phase1-main.yaml"
PARAMS_FILE="$PROJECT_ROOT/cloudformation/parameters/phase1-${ENVIRONMENT}-params.json"
ENV_FILE="$PROJECT_ROOT/.env"
NESTED_DIR="$PROJECT_ROOT/cloudformation/nested"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}Phase 1: Infrastructure Deployment (Nested)${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo "Environment: $ENVIRONMENT"
echo "Region: $REGION"
echo "Stack Name: $STACK_NAME"
echo ""

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI not found. Please install AWS CLI.${NC}"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS credentials not configured. Run 'aws configure'.${NC}"
    exit 1
fi

# Get AWS Account ID and set Region
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="$REGION"

echo -e "${GREEN}✓${NC} AWS CLI configured"
echo "  Account ID: $AWS_ACCOUNT_ID"
echo "  Region: $AWS_REGION"

# Check template file
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo -e "${RED}Error: Template file not found: $TEMPLATE_FILE${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} CloudFormation template found"

# Check nested templates
if [ ! -d "$NESTED_DIR" ]; then
    echo -e "${RED}Error: Nested templates directory not found: $NESTED_DIR${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Nested templates directory found"

# Check parameter file
if [ ! -f "$PARAMS_FILE" ]; then
    echo -e "${RED}Error: Parameter file not found: $PARAMS_FILE${NC}"
    echo "Please create: $PARAMS_FILE"
    exit 1
fi
echo -e "${GREEN}✓${NC} Parameter file found"

# ============================================
# S3 Bucket for Nested Templates
# ============================================
# Use environment and region-specific bucket name for multi-region support
S3_BUCKET_NAME="deep-insight-templates-${ENVIRONMENT}-${AWS_REGION}-${AWS_ACCOUNT_ID}"

echo ""
echo -e "${YELLOW}Setting up S3 bucket for nested templates...${NC}"
echo "Bucket name: ${S3_BUCKET_NAME}"
echo "Target region: ${AWS_REGION}"

# Check if bucket exists and verify region
BUCKET_EXISTS=false
BUCKET_REGION=""

if aws s3api head-bucket --bucket "${S3_BUCKET_NAME}" 2>/dev/null; then
    BUCKET_EXISTS=true
    # Get bucket region
    BUCKET_REGION=$(aws s3api get-bucket-location --bucket "${S3_BUCKET_NAME}" --query 'LocationConstraint' --output text 2>/dev/null || echo "us-east-1")
    # AWS returns "None" for us-east-1, normalize it
    if [ "$BUCKET_REGION" == "None" ] || [ "$BUCKET_REGION" == "null" ]; then
        BUCKET_REGION="us-east-1"
    fi

    if [ "$BUCKET_REGION" != "$AWS_REGION" ]; then
        echo -e "${RED}✗${NC} Bucket exists but in different region!"
        echo "   Bucket region: ${BUCKET_REGION}"
        echo "   Target region: ${AWS_REGION}"
        echo ""
        echo -e "${RED}Error: Cannot use bucket from different region for CloudFormation templates${NC}"
        echo "Please use a different environment name or delete the bucket in ${BUCKET_REGION}"
        exit 1
    fi
    echo -e "${GREEN}✓${NC} S3 bucket already exists in correct region (${BUCKET_REGION})"
fi

# Create bucket if it doesn't exist
if [ "$BUCKET_EXISTS" = false ]; then
    echo "Creating S3 bucket: ${S3_BUCKET_NAME} in ${AWS_REGION}"

    if [ "$AWS_REGION" == "us-east-1" ]; then
        # us-east-1 doesn't need LocationConstraint
        aws s3api create-bucket \
            --bucket "${S3_BUCKET_NAME}" \
            --region "$AWS_REGION"
    else
        # All other regions need LocationConstraint
        aws s3api create-bucket \
            --bucket "${S3_BUCKET_NAME}" \
            --region "$AWS_REGION" \
            --create-bucket-configuration LocationConstraint="$AWS_REGION"
    fi

    # Enable versioning (best practice)
    aws s3api put-bucket-versioning \
        --bucket "${S3_BUCKET_NAME}" \
        --region "$AWS_REGION" \
        --versioning-configuration Status=Enabled

    echo -e "${GREEN}✓${NC} S3 bucket created in ${AWS_REGION}"
fi

# ============================================
# Upload Nested Templates to S3
# ============================================
echo ""
echo -e "${YELLOW}Uploading nested templates to S3...${NC}"

for template in "$NESTED_DIR"/*.yaml; do
    template_name=$(basename "$template")
    echo "  Uploading: $template_name"
    aws s3 cp "$template" "s3://${S3_BUCKET_NAME}/nested/$template_name" \
        --region "$AWS_REGION"
done

echo -e "${GREEN}✓${NC} Nested templates uploaded"

# ============================================
# Update Parameter File with Account ID
# ============================================
echo ""
echo -e "${YELLOW}Updating Account ID in parameter file...${NC}"

# Create a temporary parameter file
TEMP_PARAMS_FILE="${PARAMS_FILE}.temp"
cp "$PARAMS_FILE" "$TEMP_PARAMS_FILE"

# Replace ACCOUNT_ID placeholder
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sed -i '' "s/ACCOUNT_ID/${AWS_ACCOUNT_ID}/g" "$TEMP_PARAMS_FILE"
else
    # Linux
    sed -i "s/ACCOUNT_ID/${AWS_ACCOUNT_ID}/g" "$TEMP_PARAMS_FILE"
fi

echo -e "${GREEN}✓${NC} Parameter file updated with Account ID: $AWS_ACCOUNT_ID"

# ============================================
# Add NestedTemplatesBucketName and CLI Parameters
# ============================================
# Create updated params with nested bucket parameter and CLI overrides
FINAL_PARAMS_FILE="${PARAMS_FILE}.final"

# Convert bash array to Python list for parameter overrides
PARAM_OVERRIDES_JSON="[]"
if [ ${#PARAMETER_OVERRIDES[@]} -gt 0 ]; then
    PARAM_OVERRIDES_JSON=$(printf '%s\n' "${PARAMETER_OVERRIDES[@]}" | python3 -c "import sys, json; items = [line.strip() for line in sys.stdin if line.strip()]; params = [];
for item in items:
    if '=' in item:
        key, value = item.split('=', 1)
        params.append({'ParameterKey': key, 'ParameterValue': value})
print(json.dumps(params))")
fi

# Read existing params and add new ones
python3 - <<EOF
import json
import sys

# Read existing params
with open('${TEMP_PARAMS_FILE}', 'r') as f:
    params = json.load(f)

# Add nested bucket param
params.append({
    "ParameterKey": "NestedTemplatesBucketName",
    "ParameterValue": "${S3_BUCKET_NAME}"
})

# Add CLI parameter overrides (from wrapper script)
cli_overrides = json.loads('${PARAM_OVERRIDES_JSON}')
for override in cli_overrides:
    # Check if parameter already exists
    existing = [p for p in params if p['ParameterKey'] == override['ParameterKey']]
    if existing:
        # Update existing parameter
        existing[0]['ParameterValue'] = override['ParameterValue']
    else:
        # Add new parameter
        params.append(override)

# Write final params
with open('${FINAL_PARAMS_FILE}', 'w') as f:
    json.dump(params, f, indent=2)
EOF

echo -e "${GREEN}✓${NC} Added NestedTemplatesBucketName parameter and CLI overrides"

# ============================================
# Validate CloudFormation Template
# ============================================
echo ""
echo -e "${YELLOW}Validating CloudFormation template...${NC}"

if aws cloudformation validate-template \
    --template-body file://"$TEMPLATE_FILE" \
    --region "$AWS_REGION" > /dev/null; then
    echo -e "${GREEN}✓${NC} Template validation successful"
else
    echo -e "${RED}Error: Template validation failed${NC}"
    rm -f "$TEMP_PARAMS_FILE" "$FINAL_PARAMS_FILE"
    exit 1
fi

# ============================================
# Deploy CloudFormation Stack
# ============================================
echo ""
echo -e "${YELLOW}Deploying CloudFormation stack...${NC}"
echo "This will take approximately 30-40 minutes."
echo ""

aws cloudformation deploy \
    --template-file "$TEMPLATE_FILE" \
    --stack-name "$STACK_NAME" \
    --parameter-overrides file://"$FINAL_PARAMS_FILE" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$AWS_REGION" \
    --tags \
        Environment="$ENVIRONMENT" \
        Project=deep-insight \
        ManagedBy=CloudFormation \
    --no-fail-on-empty-changeset \
    --disable-rollback

# Clean up temp files
rm -f "$TEMP_PARAMS_FILE" "$FINAL_PARAMS_FILE"

DEPLOY_STATUS=$?

if [ $DEPLOY_STATUS -eq 0 ]; then
    echo ""
    echo -e "${GREEN}============================================${NC}"
    echo -e "${GREEN}✓ Deployment Successful!${NC}"
    echo -e "${GREEN}============================================${NC}"
    echo ""

    # ============================================
    # Create CloudWatch Logs Resource Policy
    # ============================================
    echo -e "${YELLOW}Creating CloudWatch Logs resource policy for Bedrock AgentCore...${NC}"

    # Check if policy already exists
    EXISTING_POLICY=$(aws logs describe-resource-policies \
        --region "$AWS_REGION" \
        --query "resourcePolicies[?policyName=='BedrockAgentCoreLogsAccess'].policyName" \
        --output text 2>/dev/null || echo "")

    if [ -z "$EXISTING_POLICY" ]; then
        # Create the policy
        aws logs put-resource-policy \
            --policy-name BedrockAgentCoreLogsAccess \
            --region "$AWS_REGION" \
            --policy-document '{
              "Version": "2012-10-17",
              "Statement": [
                {
                  "Sid": "BedrockAgentCoreRuntimeLogsAccess",
                  "Effect": "Allow",
                  "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                  },
                  "Action": [
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                  ],
                  "Resource": "arn:aws:logs:'"$AWS_REGION"':'"$AWS_ACCOUNT_ID"':log-group:/aws/bedrock-agentcore/runtimes/*"
                },
                {
                  "Sid": "BedrockAgentCoreObservabilityAccess",
                  "Effect": "Allow",
                  "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                  },
                  "Action": [
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                  ],
                  "Resource": "arn:aws:logs:'"$AWS_REGION"':'"$AWS_ACCOUNT_ID"':log-group:bedrock-agentcore-observability:*"
                }
              ]
            }' > /dev/null 2>&1
        echo -e "${GREEN}✓${NC} CloudWatch Logs resource policy created"
    else
        echo -e "${GREEN}✓${NC} CloudWatch Logs resource policy already exists"
    fi

    # Get stack outputs
    echo -e "${YELLOW}Retrieving stack outputs...${NC}"

    OUTPUTS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs' \
        --output json)

    # Parse outputs using Python
    python3 - <<EOF "$OUTPUTS" "$ENV_FILE" "$AWS_REGION" "$AWS_ACCOUNT_ID" "$ENVIRONMENT"
import json
import sys

outputs = json.loads(sys.argv[1])
env_file = sys.argv[2]
aws_region = sys.argv[3]
aws_account_id = sys.argv[4]
environment = sys.argv[5]

# Create dictionary from outputs
output_dict = {o['OutputKey']: o['OutputValue'] for o in outputs}

# Write to .env file
with open(env_file, 'w') as f:
    f.write("# AWS Configuration\n")
    f.write(f"AWS_REGION={aws_region}\n")
    f.write(f"AWS_ACCOUNT_ID={aws_account_id}\n")
    f.write("\n# Project Configuration\n")
    f.write("PROJECT_NAME=deep-insight\n")
    f.write(f"ENVIRONMENT={environment}\n")
    f.write("\n# Phase 1 Outputs\n")
    f.write(f"VPC_ID={output_dict.get('VpcId', '')}\n")
    f.write(f"PRIVATE_SUBNET_1_ID={output_dict.get('PrivateSubnet1Id', '')}\n")
    f.write(f"PRIVATE_SUBNET_2_ID={output_dict.get('PrivateSubnet2Id', '')}\n")
    f.write(f"PUBLIC_SUBNET_1_ID={output_dict.get('PublicSubnet1Id', '')}\n")
    f.write(f"PUBLIC_SUBNET_2_ID={output_dict.get('PublicSubnet2Id', '')}\n")
    f.write(f"SG_AGENTCORE_ID={output_dict.get('AgentCoreSecurityGroupId', '')}\n")
    f.write(f"SG_ALB_ID={output_dict.get('ALBSecurityGroupId', '')}\n")
    f.write(f"SG_FARGATE_ID={output_dict.get('FargateSecurityGroupId', '')}\n")
    f.write(f"SG_VPCE_ID={output_dict.get('VPCEndpointSecurityGroupId', '')}\n")
    f.write(f"ALB_ARN={output_dict.get('ApplicationLoadBalancerArn', '')}\n")
    f.write(f"ALB_DNS={output_dict.get('ApplicationLoadBalancerDNS', '')}\n")
    f.write(f"ALB_TARGET_GROUP_ARN={output_dict.get('TargetGroupArn', '')}\n")
    f.write(f"TASK_EXECUTION_ROLE_ARN={output_dict.get('TaskExecutionRoleArn', '')}\n")
    f.write(f"TASK_ROLE_ARN={output_dict.get('TaskRoleArn', '')}\n")

print(f"\n✓ .env file created: {env_file}")
EOF

    # Display summary
    echo ""
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}Deployment Summary${NC}"
    echo -e "${BLUE}============================================${NC}"
    cat "$ENV_FILE"
    echo ""
    echo -e "${GREEN}Next Steps:${NC}"
    echo "  1. Run verification: ${YELLOW}./scripts/phase1/verify.sh${NC}"
    echo "  2. Proceed to Phase 2: Fargate Runtime deployment"
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
