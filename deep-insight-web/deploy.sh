#!/bin/bash
set -e

# ============================================================
# deploy.sh — Deploy deep-insight-web to ECS Fargate
#
# Creates a new internet-facing ALB in the Deep Insight VPC's
# public subnets, restricted to VPN CIDR. ECS tasks run in
# private subnets (same VPC).
#
# Prerequisites:
#   - AWS CLI configured with appropriate permissions
#   - Docker installed
#   - managed-agentcore/.env populated (from Phase 1+2 deployment)
#
# Usage:
#   bash deploy.sh <VPN_CIDR>
#
# Examples:
#   bash deploy.sh "10.0.0.0/8"
#   bash deploy.sh "54.239.0.0/16"
#
# To clean up all resources created by this script:
#   bash deploy.sh cleanup
# ============================================================

export AWS_PAGER=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$(cd "$SCRIPT_DIR/../managed-agentcore" && pwd)/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Deploy managed-agentcore first."
    exit 1
fi

# Load env vars from managed-agentcore/.env
set -a
source "$ENV_FILE"
set +a

# ---------- Configuration ----------

REGION="${AWS_REGION:-us-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID}"

# Existing resources (from managed-agentcore deployment)
CLUSTER_NAME="${ECS_CLUSTER_NAME}"
VPC_ID="${VPC_ID}"
SUBNET_1="${PRIVATE_SUBNET_1_ID}"
SUBNET_2="${PRIVATE_SUBNET_2_ID}"
PUBLIC_SUBNET_1="${PUBLIC_SUBNET_1_ID}"
PUBLIC_SUBNET_2="${PUBLIC_SUBNET_2_ID}"
SG_VPCE="${SG_VPCE_ID}"
EXECUTION_ROLE_ARN="${TASK_EXECUTION_ROLE_ARN}"
S3_BUCKET="${S3_BUCKET_NAME}"
RUNTIME_ARN_VALUE="${RUNTIME_ARN}"

# VPN CIDR for ALB access restriction (required argument)
if [ "${1}" != "cleanup" ]; then
    if [ -z "$1" ]; then
        echo "ERROR: VPN CIDR is required."
        echo "Usage: bash deploy.sh <VPN_CIDR>"
        echo "Example: bash deploy.sh \"10.0.0.0/8\""
        exit 1
    fi
    VPN_CIDR="$1"
fi

# New resources
ECR_REPO_NAME="deep-insight-web"
IMAGE_TAG="latest"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO_NAME}"
ALB_WEB_NAME="deep-insight-web-alb"
SG_ALB_WEB_NAME="deep-insight-web-alb-sg"
TG_NAME="deep-insight-web-tg"
SG_WEB_NAME="deep-insight-web-ecs-sg"
TASK_FAMILY="deep-insight-web-task"
SERVICE_NAME="deep-insight-web-service"
LOG_GROUP="/ecs/deep-insight-web"
TASK_ROLE_NAME="deep-insight-web-task-role"
TASK_ROLE_POLICY_NAME="deep-insight-web-task-policy"

echo "============================================"
echo "Deploy deep-insight-web"
echo "============================================"
echo "Region:      ${REGION}"
echo "Account:     ${ACCOUNT_ID}"
echo "Cluster:     ${CLUSTER_NAME}"
echo "VPC:         ${VPC_ID}"
echo "S3 Bucket:   ${S3_BUCKET}"
echo "Runtime ARN: ${RUNTIME_ARN_VALUE:0:60}..."
echo "VPN CIDR:    ${VPN_CIDR}"
echo ""

# ---------- Cleanup mode ----------

if [ "${1}" = "cleanup" ]; then
    echo "=== Cleanup: Removing deep-insight-web resources ==="

    echo "Deleting ECS service..."
    aws ecs update-service --cluster "$CLUSTER_NAME" --service "$SERVICE_NAME" \
        --desired-count 0 --region "$REGION" 2>/dev/null || true
    aws ecs delete-service --cluster "$CLUSTER_NAME" --service "$SERVICE_NAME" \
        --force --region "$REGION" 2>/dev/null || true

    echo "Deregistering task definitions..."
    TASK_DEFS=$(aws ecs list-task-definitions --family-prefix "$TASK_FAMILY" \
        --region "$REGION" --query "taskDefinitionArns[]" --output text 2>/dev/null || true)
    for td in $TASK_DEFS; do
        aws ecs deregister-task-definition --task-definition "$td" --region "$REGION" 2>/dev/null || true
    done

    echo "Deleting web ALB..."
    ALB_WEB_ARN=$(aws elbv2 describe-load-balancers --names "$ALB_WEB_NAME" \
        --region "$REGION" --query "LoadBalancers[0].LoadBalancerArn" --output text 2>/dev/null || true)
    if [ -n "$ALB_WEB_ARN" ] && [ "$ALB_WEB_ARN" != "None" ]; then
        # Delete listeners first
        LISTENER_ARNS=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB_WEB_ARN" \
            --region "$REGION" --query "Listeners[*].ListenerArn" --output text 2>/dev/null || true)
        for la in $LISTENER_ARNS; do
            aws elbv2 delete-listener --listener-arn "$la" --region "$REGION" 2>/dev/null || true
        done
        aws elbv2 delete-load-balancer --load-balancer-arn "$ALB_WEB_ARN" --region "$REGION" 2>/dev/null || true
        echo "Waiting for ALB deletion..."
        sleep 10
    fi

    echo "Deleting ALB target group..."
    TG_ARN=$(aws elbv2 describe-target-groups --names "$TG_NAME" \
        --region "$REGION" --query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null || true)
    if [ -n "$TG_ARN" ] && [ "$TG_ARN" != "None" ]; then
        aws elbv2 delete-target-group --target-group-arn "$TG_ARN" --region "$REGION" 2>/dev/null || true
    fi

    echo "Deleting ECS security group..."
    SG_WEB_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=${SG_WEB_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
        --region "$REGION" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || true)
    if [ -n "$SG_WEB_ID" ] && [ "$SG_WEB_ID" != "None" ]; then
        # Remove VPC endpoint SG rule
        aws ec2 revoke-security-group-ingress \
            --group-id "$SG_VPCE" \
            --protocol tcp --port 443 \
            --source-group "$SG_WEB_ID" \
            --region "$REGION" 2>/dev/null || true
        aws ec2 delete-security-group --group-id "$SG_WEB_ID" --region "$REGION" 2>/dev/null || true
    fi

    echo "Deleting ALB security group..."
    SG_ALB_WEB_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=${SG_ALB_WEB_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
        --region "$REGION" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || true)
    if [ -n "$SG_ALB_WEB_ID" ] && [ "$SG_ALB_WEB_ID" != "None" ]; then
        aws ec2 delete-security-group --group-id "$SG_ALB_WEB_ID" --region "$REGION" 2>/dev/null || true
    fi

    echo "Deleting IAM role and policy..."
    aws iam delete-role-policy --role-name "$TASK_ROLE_NAME" --policy-name "$TASK_ROLE_POLICY_NAME" 2>/dev/null || true
    aws iam delete-role --role-name "$TASK_ROLE_NAME" 2>/dev/null || true

    echo "Deleting CloudWatch log group..."
    aws logs delete-log-group --log-group-name "$LOG_GROUP" --region "$REGION" 2>/dev/null || true

    echo "Deleting ECR repository..."
    aws ecr delete-repository --repository-name "$ECR_REPO_NAME" --force --region "$REGION" 2>/dev/null || true

    echo ""
    echo "=== Cleanup complete ==="
    exit 0
fi

# ---------- Step 1: ECR Repository ----------

echo "=== Step 1: ECR Repository ==="
aws ecr describe-repositories --repository-names "$ECR_REPO_NAME" --region "$REGION" 2>/dev/null \
    || aws ecr create-repository --repository-name "$ECR_REPO_NAME" --region "$REGION" > /dev/null
echo "ECR: ${ECR_URI}"

# ---------- Step 2: Docker Build + Push ----------

echo "=== Step 2: Docker Build + Push ==="
# On arm64 hosts (e.g., Mac M1/M2), install Docker buildx and use:
#   docker buildx build --platform linux/amd64 -t "${ECR_REPO_NAME}:${IMAGE_TAG}" "$SCRIPT_DIR"
docker build -t "${ECR_REPO_NAME}:${IMAGE_TAG}" "$SCRIPT_DIR"

aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

docker tag "${ECR_REPO_NAME}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"
echo "Pushed: ${ECR_URI}:${IMAGE_TAG}"

# ---------- Step 3: Security Groups ----------

echo "=== Step 3: Security Groups ==="

# 3a: ALB Security Group (internet-facing, VPN CIDR only)
SG_ALB_WEB_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${SG_ALB_WEB_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
    --region "$REGION" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || true)

if [ -z "$SG_ALB_WEB_ID" ] || [ "$SG_ALB_WEB_ID" = "None" ]; then
    SG_ALB_WEB_ID=$(aws ec2 create-security-group \
        --group-name "$SG_ALB_WEB_NAME" \
        --description "Allow HTTP from VPN to deep-insight-web ALB" \
        --vpc-id "$VPC_ID" \
        --region "$REGION" \
        --query "GroupId" --output text)

    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_ALB_WEB_ID" \
        --protocol tcp --port 80 \
        --cidr "$VPN_CIDR" \
        --region "$REGION" > /dev/null

    # Remove default egress-all rule (least privilege)
    aws ec2 revoke-security-group-egress \
        --group-id "$SG_ALB_WEB_ID" \
        --protocol all --cidr 0.0.0.0/0 \
        --region "$REGION" > /dev/null
fi
echo "ALB SG: ${SG_ALB_WEB_ID} (inbound: ${VPN_CIDR}:80)"

# 3b: ECS Security Group (allow traffic from web ALB SG)
SG_WEB_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${SG_WEB_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
    --region "$REGION" --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || true)

if [ -z "$SG_WEB_ID" ] || [ "$SG_WEB_ID" = "None" ]; then
    SG_WEB_ID=$(aws ec2 create-security-group \
        --group-name "$SG_WEB_NAME" \
        --description "Allow TCP 8080 from web ALB to deep-insight-web" \
        --vpc-id "$VPC_ID" \
        --region "$REGION" \
        --query "GroupId" --output text)

    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_WEB_ID" \
        --protocol tcp --port 8080 \
        --source-group "$SG_ALB_WEB_ID" \
        --region "$REGION" > /dev/null
fi

# Ensure inbound rule from web ALB SG exists (handles reused SG)
EXISTING_ECS_INGRESS=$(aws ec2 describe-security-group-rules \
    --filters "Name=group-id,Values=${SG_WEB_ID}" \
    --region "$REGION" \
    --query "SecurityGroupRules[?IsEgress==\`false\` && IpProtocol==\`tcp\` && FromPort==\`8080\` && ToPort==\`8080\` && ReferencedGroupInfo.GroupId==\`${SG_ALB_WEB_ID}\`]" \
    --output text 2>/dev/null || true)

if [ -z "$EXISTING_ECS_INGRESS" ]; then
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_WEB_ID" \
        --protocol tcp --port 8080 \
        --source-group "$SG_ALB_WEB_ID" \
        --region "$REGION" > /dev/null
    echo "ECS SG: added inbound from ${SG_ALB_WEB_ID} on port 8080"
else
    echo "ECS SG: inbound rule already exists"
fi
echo "ECS SG: ${SG_WEB_ID}"

# 3c: ALB egress to ECS containers on port 8080
EXISTING_ALB_EGRESS=$(aws ec2 describe-security-group-rules \
    --filters "Name=group-id,Values=${SG_ALB_WEB_ID}" \
    --region "$REGION" \
    --query "SecurityGroupRules[?IsEgress==\`true\` && IpProtocol==\`tcp\` && FromPort==\`8080\` && ToPort==\`8080\` && ReferencedGroupInfo.GroupId==\`${SG_WEB_ID}\`]" \
    --output text 2>/dev/null || true)

if [ -z "$EXISTING_ALB_EGRESS" ]; then
    aws ec2 authorize-security-group-egress \
        --group-id "$SG_ALB_WEB_ID" \
        --protocol tcp --port 8080 \
        --source-group "$SG_WEB_ID" \
        --region "$REGION" > /dev/null
    echo "ALB SG: added egress to ${SG_WEB_ID} on port 8080"
else
    echo "ALB SG: egress rule already exists"
fi

# 3d: Allow web SG to reach VPC endpoints (ECR, S3, CloudWatch Logs)
EXISTING_VPCE_RULE=$(aws ec2 describe-security-group-rules \
    --filters "Name=group-id,Values=${SG_VPCE}" \
    --region "$REGION" \
    --query "SecurityGroupRules[?IsEgress==\`false\` && IpProtocol==\`tcp\` && FromPort==\`443\` && ToPort==\`443\` && ReferencedGroupInfo.GroupId==\`${SG_WEB_ID}\`]" \
    --output text 2>/dev/null || true)

if [ -z "$EXISTING_VPCE_RULE" ]; then
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_VPCE" \
        --protocol tcp --port 443 \
        --source-group "$SG_WEB_ID" \
        --region "$REGION" > /dev/null
    echo "VPC Endpoint SG: added inbound from ${SG_WEB_ID}"
else
    echo "VPC Endpoint SG: rule already exists"
fi

# ---------- Step 4: Internet-facing ALB + Target Group + Listener ----------

echo "=== Step 4: Internet-facing ALB + Target Group + Listener ==="

# 4a: Target Group
TG_ARN=$(aws elbv2 describe-target-groups --names "$TG_NAME" \
    --region "$REGION" --query "TargetGroups[0].TargetGroupArn" --output text 2>/dev/null || true)

if [ -z "$TG_ARN" ] || [ "$TG_ARN" = "None" ]; then
    TG_ARN=$(aws elbv2 create-target-group \
        --name "$TG_NAME" \
        --protocol HTTP --port 8080 \
        --vpc-id "$VPC_ID" \
        --target-type ip \
        --health-check-path "/health" \
        --health-check-interval-seconds 30 \
        --healthy-threshold-count 2 \
        --unhealthy-threshold-count 3 \
        --region "$REGION" \
        --query "TargetGroups[0].TargetGroupArn" --output text)
fi
echo "Target Group: ${TG_ARN}"

# 4b: Internet-facing ALB
ALB_WEB_ARN=$(aws elbv2 describe-load-balancers --names "$ALB_WEB_NAME" \
    --region "$REGION" --query "LoadBalancers[0].LoadBalancerArn" --output text 2>/dev/null || true)

if [ -z "$ALB_WEB_ARN" ] || [ "$ALB_WEB_ARN" = "None" ]; then
    ALB_WEB_ARN=$(aws elbv2 create-load-balancer \
        --name "$ALB_WEB_NAME" \
        --scheme internet-facing \
        --type application \
        --subnets "$PUBLIC_SUBNET_1" "$PUBLIC_SUBNET_2" \
        --security-groups "$SG_ALB_WEB_ID" \
        --region "$REGION" \
        --query "LoadBalancers[0].LoadBalancerArn" --output text)

    echo "Waiting for ALB to become active..."
    aws elbv2 wait load-balancer-available --load-balancer-arns "$ALB_WEB_ARN" --region "$REGION"
fi

ALB_WEB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns "$ALB_WEB_ARN" \
    --region "$REGION" --query "LoadBalancers[0].DNSName" --output text)
echo "ALB: ${ALB_WEB_ARN}"
echo "ALB DNS: ${ALB_WEB_DNS}"

# Set ALB idle timeout to 3600s (1 hour).
# AgentCore analysis sessions run 15-20+ minutes. During Fargate container setup
# (task creation, health check, S3 data sync), no SSE events flow for ~2 minutes.
# The default 60s timeout would drop the browser's SSE connection.
aws elbv2 modify-load-balancer-attributes \
    --load-balancer-arn "$ALB_WEB_ARN" \
    --attributes Key=idle_timeout.timeout_seconds,Value=3600 \
    --region "$REGION" > /dev/null
echo "ALB idle timeout: 3600s"

# 4c: Listener (port 80 → target group)
LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn "$ALB_WEB_ARN" \
    --region "$REGION" --query "Listeners[?Port==\`80\`].ListenerArn" --output text 2>/dev/null || true)

if [ -z "$LISTENER_ARN" ] || [ "$LISTENER_ARN" = "None" ]; then
    LISTENER_ARN=$(aws elbv2 create-listener \
        --load-balancer-arn "$ALB_WEB_ARN" \
        --protocol HTTP --port 80 \
        --default-actions "[{\"Type\":\"forward\",\"TargetGroupArn\":\"${TG_ARN}\"}]" \
        --region "$REGION" \
        --query "Listeners[0].ListenerArn" --output text)
fi
echo "Listener: ${LISTENER_ARN}"

# ---------- Step 5: IAM Task Role ----------

echo "=== Step 5: IAM Task Role ==="
TASK_ROLE_ARN_VALUE=$(aws iam get-role --role-name "$TASK_ROLE_NAME" \
    --query "Role.Arn" --output text 2>/dev/null || true)

if [ -z "$TASK_ROLE_ARN_VALUE" ] || [ "$TASK_ROLE_ARN_VALUE" = "None" ]; then
    TRUST_POLICY='{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'

    TASK_ROLE_ARN_VALUE=$(aws iam create-role \
        --role-name "$TASK_ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --query "Role.Arn" --output text)

    TASK_POLICY=$(cat <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "S3Upload",
            "Effect": "Allow",
            "Action": ["s3:PutObject"],
            "Resource": "arn:aws:s3:::${S3_BUCKET}/uploads/*"
        },
        {
            "Sid": "S3Feedback",
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject"],
            "Resource": "arn:aws:s3:::${S3_BUCKET}/deep-insight/feedback/*"
        },
        {
            "Sid": "S3ArtifactsList",
            "Effect": "Allow",
            "Action": ["s3:ListBucket"],
            "Resource": "arn:aws:s3:::${S3_BUCKET}",
            "Condition": {
                "StringLike": {
                    "s3:prefix": "deep-insight/fargate_sessions/*/artifacts/*"
                }
            }
        },
        {
            "Sid": "S3ArtifactsGet",
            "Effect": "Allow",
            "Action": ["s3:GetObject"],
            "Resource": "arn:aws:s3:::${S3_BUCKET}/deep-insight/fargate_sessions/*/artifacts/*"
        },
        {
            "Sid": "AgentCoreInvoke",
            "Effect": "Allow",
            "Action": ["bedrock-agentcore:InvokeAgentRuntime"],
            "Resource": "*"
        }
    ]
}
POLICY
)

    aws iam put-role-policy \
        --role-name "$TASK_ROLE_NAME" \
        --policy-name "$TASK_ROLE_POLICY_NAME" \
        --policy-document "$TASK_POLICY"
fi
echo "Task Role: ${TASK_ROLE_ARN_VALUE}"

# ---------- Step 6: CloudWatch Log Group ----------

echo "=== Step 6: CloudWatch Log Group ==="
aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$REGION" 2>/dev/null || true
echo "Log Group: ${LOG_GROUP}"

# ---------- Step 7: ECS Task Definition ----------

echo "=== Step 7: ECS Task Definition ==="
TASK_DEF=$(cat <<TASKDEF
{
    "family": "${TASK_FAMILY}",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "256",
    "memory": "512",
    "executionRoleArn": "${EXECUTION_ROLE_ARN}",
    "taskRoleArn": "${TASK_ROLE_ARN_VALUE}",
    "containerDefinitions": [
        {
            "name": "deep-insight-web",
            "image": "${ECR_URI}:${IMAGE_TAG}",
            "portMappings": [{"containerPort": 8080, "protocol": "tcp"}],
            "environment": [
                {"name": "RUNTIME_ARN", "value": "${RUNTIME_ARN_VALUE}"},
                {"name": "AWS_REGION", "value": "${REGION}"},
                {"name": "S3_BUCKET_NAME", "value": "${S3_BUCKET}"}
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "${LOG_GROUP}",
                    "awslogs-region": "${REGION}",
                    "awslogs-stream-prefix": "web"
                }
            },
            "essential": true
        }
    ]
}
TASKDEF
)

TASK_DEF_ARN=$(aws ecs register-task-definition \
    --cli-input-json "$TASK_DEF" \
    --region "$REGION" \
    --query "taskDefinition.taskDefinitionArn" --output text)
echo "Task Definition: ${TASK_DEF_ARN}"

# ---------- Step 8: ECS Service ----------

echo "=== Step 8: ECS Service ==="
EXISTING_SERVICE=$(aws ecs describe-services --cluster "$CLUSTER_NAME" --services "$SERVICE_NAME" \
    --region "$REGION" --query "services[?status=='ACTIVE'].serviceName" --output text 2>/dev/null || true)

if [ -z "$EXISTING_SERVICE" ]; then
    aws ecs create-service \
        --cluster "$CLUSTER_NAME" \
        --service-name "$SERVICE_NAME" \
        --task-definition "$TASK_DEF_ARN" \
        --desired-count 1 \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[${SUBNET_1},${SUBNET_2}],securityGroups=[${SG_WEB_ID}],assignPublicIp=DISABLED}" \
        --load-balancers "targetGroupArn=${TG_ARN},containerName=deep-insight-web,containerPort=8080" \
        --region "$REGION" > /dev/null
    echo "Service created: ${SERVICE_NAME}"
else
    aws ecs update-service \
        --cluster "$CLUSTER_NAME" \
        --service "$SERVICE_NAME" \
        --task-definition "$TASK_DEF_ARN" \
        --force-new-deployment \
        --region "$REGION" > /dev/null
    echo "Service updated: ${SERVICE_NAME}"
fi

# ---------- Done ----------

echo ""
echo "============================================"
echo "Deployment complete!"
echo "============================================"
echo ""
echo "ALB DNS: http://${ALB_WEB_DNS}"
echo ""
echo "Wait for the ECS task to reach RUNNING state:"
echo "  aws ecs list-tasks --cluster ${CLUSTER_NAME} --service-name ${SERVICE_NAME} --region ${REGION}"
echo ""
echo "Check target health:"
echo "  aws elbv2 describe-target-health --target-group-arn ${TG_ARN} --region ${REGION}"
echo ""
echo "Check service events:"
echo "  aws ecs describe-services --cluster ${CLUSTER_NAME} --services ${SERVICE_NAME} --region ${REGION} --query 'services[0].events[:5]'"
