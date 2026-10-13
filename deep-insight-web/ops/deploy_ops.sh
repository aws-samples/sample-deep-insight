#!/bin/bash
set -e

# ============================================================
# deploy_ops.sh — Deploy Deep Insight Ops infrastructure
#
# Creates DynamoDB table, SNS topic, Lambda function, S3 event
# notification, and IAM policies for job tracking and notifications.
#
# Prerequisites:
#   - AWS CLI configured with appropriate permissions
#   - managed-agentcore/.env populated (from Phase 1+2 deployment)
#   - deep-insight-web deployed (deploy.sh already run)
#
# Usage:
#   bash ops/deploy_ops.sh admin1@x.com admin2@x.com   # First deploy
#   bash ops/deploy_ops.sh                              # Redeploy (updates Lambda code)
#   bash ops/deploy_ops.sh cleanup                      # Remove all Ops resources
#
# Adding subscribers later:
#   aws sns subscribe --topic-arn <ARN> --protocol email --endpoint new@x.com
#   aws cognito-idp admin-create-user --user-pool-id <ID> --username new@x.com --desired-delivery-mediums EMAIL
# ============================================================

export AWS_PAGER=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$(cd "$WEB_DIR/../managed-agentcore" && pwd)/.env"

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
S3_BUCKET="${S3_BUCKET_NAME}"

# Existing resources (from deep-insight-web deployment)
CLUSTER_NAME="${ECS_CLUSTER_NAME}"
WEB_TASK_ROLE_NAME="deep-insight-web-task-role"
WEB_TASK_FAMILY="deep-insight-web-task"
WEB_SERVICE_NAME="deep-insight-web-service"
EXECUTION_ROLE_ARN="${TASK_EXECUTION_ROLE_ARN}"

# New Ops resources
DYNAMODB_TABLE="deep-insight-jobs"
SNS_TOPIC_NAME="deep-insight-job-notifications"
LAMBDA_FUNC_NAME="deep-insight-job-complete"
LAMBDA_ROLE_NAME="deep-insight-ops-lambda-role"
SWEEP_RULE_NAME="deep-insight-stale-job-sweep"
OPS_POLICY_NAME="deep-insight-ops-dynamodb-sns-policy"
COGNITO_POOL_NAME="deep-insight-ops-admins"

# Collect email args (skip "cleanup")
ADMIN_EMAILS=()
if [ "${1}" != "cleanup" ]; then
    for arg in "$@"; do
        ADMIN_EMAILS+=("$arg")
    done
fi

echo "============================================"
echo "Deploy Deep Insight Ops Infrastructure"
echo "============================================"
echo "Region:       ${REGION}"
echo "Account:      ${ACCOUNT_ID}"
echo "S3 Bucket:    ${S3_BUCKET}"
echo "Admin emails: ${ADMIN_EMAILS[*]:-"(none — redeploy mode)"}"
echo ""

# ---------- Cleanup mode ----------

if [ "${1}" = "cleanup" ]; then
    echo "=== Cleanup: Removing Ops resources ==="

    echo "Deleting Cognito User Pool..."
    COGNITO_POOL_ID=$(aws cognito-idp list-user-pools --max-results 50 --region "$REGION" \
        --query "UserPools[?Name=='${COGNITO_POOL_NAME}'].Id" --output text 2>/dev/null || true)
    if [ -n "$COGNITO_POOL_ID" ] && [ "$COGNITO_POOL_ID" != "None" ]; then
        aws cognito-idp delete-user-pool --user-pool-id "$COGNITO_POOL_ID" \
            --region "$REGION" 2>/dev/null || true
    fi

    echo "Removing S3 event notification for Lambda..."
    EXISTING_CONFIG=$(aws s3api get-bucket-notification-configuration \
        --bucket "$S3_BUCKET" --region "$REGION" 2>/dev/null || true)
    [ -z "$EXISTING_CONFIG" ] && EXISTING_CONFIG="{}"
    # Remove our Lambda configuration, keep others
    CLEANED_CONFIG=$(echo "$EXISTING_CONFIG" | python3 -c "
import sys, json
config = json.load(sys.stdin)
lc = config.get('LambdaFunctionConfigurations', [])
config['LambdaFunctionConfigurations'] = [c for c in lc if '${LAMBDA_FUNC_NAME}' not in c.get('LambdaFunctionArn', '')]
# Remove empty keys
for key in ['TopicConfigurations', 'QueueConfigurations', 'LambdaFunctionConfigurations', 'EventBridgeConfiguration']:
    if key in config and not config[key]:
        del config[key]
json.dump(config, sys.stdout)
")
    aws s3api put-bucket-notification-configuration \
        --bucket "$S3_BUCKET" \
        --notification-configuration "$CLEANED_CONFIG" \
        --region "$REGION" 2>/dev/null || true

    echo "Deleting stale job sweep schedule..."
    aws events remove-targets --rule "$SWEEP_RULE_NAME" --ids "$LAMBDA_FUNC_NAME" \
        --region "$REGION" 2>/dev/null || true
    aws events delete-rule --name "$SWEEP_RULE_NAME" --region "$REGION" 2>/dev/null || true

    echo "Deleting Lambda function..."
    aws lambda delete-function --function-name "$LAMBDA_FUNC_NAME" \
        --region "$REGION" 2>/dev/null || true

    echo "Deleting Lambda IAM role..."
    aws iam delete-role-policy --role-name "$LAMBDA_ROLE_NAME" \
        --policy-name "${LAMBDA_ROLE_NAME}-policy" 2>/dev/null || true
    aws iam delete-role --role-name "$LAMBDA_ROLE_NAME" 2>/dev/null || true

    echo "Deleting SNS subscriptions..."
    SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:${SNS_TOPIC_NAME}"
    SUBS=$(aws sns list-subscriptions-by-topic --topic-arn "$SNS_TOPIC_ARN" \
        --region "$REGION" --query "Subscriptions[].SubscriptionArn" --output text 2>/dev/null || true)
    for sub in $SUBS; do
        if [ "$sub" != "PendingConfirmation" ]; then
            aws sns unsubscribe --subscription-arn "$sub" --region "$REGION" 2>/dev/null || true
        fi
    done

    echo "Deleting SNS topic..."
    aws sns delete-topic --topic-arn "$SNS_TOPIC_ARN" --region "$REGION" 2>/dev/null || true

    echo "Deleting DynamoDB table..."
    aws dynamodb delete-table --table-name "$DYNAMODB_TABLE" \
        --region "$REGION" 2>/dev/null || true

    echo "Removing Ops policy from web task role..."
    aws iam delete-role-policy --role-name "$WEB_TASK_ROLE_NAME" \
        --policy-name "$OPS_POLICY_NAME" 2>/dev/null || true

    echo ""
    echo "=== Cleanup complete ==="
    echo "NOTE: ECS task definition env vars (DYNAMODB_TABLE_NAME, SNS_TOPIC_ARN) remain"
    echo "      but are harmless — job_tracker.py skips writes when table does not exist."
    exit 0
fi

# ---------- Step 1: DynamoDB Table ----------

echo "=== Step 1: DynamoDB Table ==="
EXISTING_TABLE=$(aws dynamodb describe-table --table-name "$DYNAMODB_TABLE" \
    --region "$REGION" --query "Table.TableStatus" --output text 2>/dev/null || true)

if [ -z "$EXISTING_TABLE" ] || [ "$EXISTING_TABLE" = "None" ]; then
    aws dynamodb create-table \
        --table-name "$DYNAMODB_TABLE" \
        --attribute-definitions \
            AttributeName=job_id,AttributeType=S \
            AttributeName=status,AttributeType=S \
            AttributeName=started_at,AttributeType=N \
            AttributeName=session_id,AttributeType=S \
        --key-schema \
            AttributeName=job_id,KeyType=HASH \
        --global-secondary-indexes \
            "IndexName=StatusStartedIndex,KeySchema=[{AttributeName=status,KeyType=HASH},{AttributeName=started_at,KeyType=RANGE}],Projection={ProjectionType=ALL}" \
            "IndexName=SessionIdIndex,KeySchema=[{AttributeName=session_id,KeyType=HASH}],Projection={ProjectionType=KEYS_ONLY}" \
        --billing-mode PAY_PER_REQUEST \
        --region "$REGION" > /dev/null

    echo "Waiting for table to become active..."
    aws dynamodb wait table-exists --table-name "$DYNAMODB_TABLE" --region "$REGION"
    echo "DynamoDB: ${DYNAMODB_TABLE} (created)"
else
    echo "DynamoDB: ${DYNAMODB_TABLE} (already exists — ${EXISTING_TABLE})"
fi

# ---------- Step 2: SNS Topic ----------

echo "=== Step 2: SNS Topic ==="
SNS_TOPIC_ARN=$(aws sns create-topic --name "$SNS_TOPIC_NAME" \
    --region "$REGION" --query "TopicArn" --output text)
echo "SNS Topic: ${SNS_TOPIC_ARN}"

# ---------- Step 3: SNS Subscriptions ----------

echo "=== Step 3: SNS Subscriptions ==="
if [ ${#ADMIN_EMAILS[@]} -eq 0 ]; then
    echo "No email args — skipping subscription creation"
else
    for email in "${ADMIN_EMAILS[@]}"; do
        # Check if subscription already exists
        EXISTING_SUB=$(aws sns list-subscriptions-by-topic --topic-arn "$SNS_TOPIC_ARN" \
            --region "$REGION" \
            --query "Subscriptions[?Endpoint=='${email}'].SubscriptionArn" \
            --output text 2>/dev/null || true)

        if [ -z "$EXISTING_SUB" ] || [ "$EXISTING_SUB" = "None" ]; then
            aws sns subscribe --cli-input-json "{
                \"TopicArn\": \"${SNS_TOPIC_ARN}\",
                \"Protocol\": \"email\",
                \"Endpoint\": \"${email}\"
            }" --region "$REGION" > /dev/null
            echo "SNS Subscription: ${email} (confirmation email sent)"
        else
            echo "SNS Subscription: ${email} (already subscribed)"
        fi
    done
fi

# ---------- Step 4: Lambda IAM Role ----------

echo "=== Step 4: Lambda IAM Role ==="
LAMBDA_ROLE_ARN=$(aws iam get-role --role-name "$LAMBDA_ROLE_NAME" \
    --query "Role.Arn" --output text 2>/dev/null || true)

if [ -z "$LAMBDA_ROLE_ARN" ] || [ "$LAMBDA_ROLE_ARN" = "None" ]; then
    TRUST_POLICY='{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'

    LAMBDA_ROLE_ARN=$(aws iam create-role \
        --role-name "$LAMBDA_ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --query "Role.Arn" --output text)

    # Wait for IAM role propagation
    echo "Waiting for IAM role propagation..."
    sleep 10


    echo "Lambda Role: ${LAMBDA_ROLE_ARN} (created)"
else
    echo "Lambda Role: ${LAMBDA_ROLE_ARN} (already exists)"
fi

# Policy on every run, so existing deployments pick up new permissions
# (traces/* read: the stale-job sweep uses the trace as a heartbeat)
LAMBDA_POLICY=$(cat <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/lambda/${LAMBDA_FUNC_NAME}:*"
        },
        {
            "Sid": "DynamoDBAccess",
            "Effect": "Allow",
            "Action": [
                "dynamodb:Query",
                "dynamodb:UpdateItem",
                "dynamodb:GetItem"
            ],
            "Resource": [
                "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${DYNAMODB_TABLE}",
                "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${DYNAMODB_TABLE}/index/*"
            ]
        },
        {
            "Sid": "S3ReadAccess",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::${S3_BUCKET}",
                "arn:aws:s3:::${S3_BUCKET}/deep-insight/fargate_sessions/*",
                "arn:aws:s3:::${S3_BUCKET}/deep-insight/traces/*"
            ]
        },
        {
            "Sid": "SNSPublish",
            "Effect": "Allow",
            "Action": "sns:Publish",
            "Resource": "${SNS_TOPIC_ARN}"
        }
    ]
}
POLICY
)

aws iam put-role-policy \
    --role-name "$LAMBDA_ROLE_NAME" \
    --policy-name "${LAMBDA_ROLE_NAME}-policy" \
    --policy-document "$LAMBDA_POLICY"
echo "Lambda Role policy: ${LAMBDA_ROLE_NAME}-policy applied"


# ---------- Step 5: Lambda Function ----------

echo "=== Step 5: Lambda Function ==="

# S3_BUCKET_NAME: the stale-job sweep reads trace timestamps (heartbeat)
LAMBDA_ENV="DYNAMODB_TABLE_NAME=${DYNAMODB_TABLE},SNS_TOPIC_ARN=${SNS_TOPIC_ARN},S3_BUCKET_NAME=${S3_BUCKET}"

# Zip the Lambda code
LAMBDA_ZIP="/tmp/deep-insight-job-complete.zip"
(cd "$SCRIPT_DIR/lambda" && zip -q "$LAMBDA_ZIP" job_complete.py)

EXISTING_LAMBDA=$(aws lambda get-function --function-name "$LAMBDA_FUNC_NAME" \
    --region "$REGION" --query "Configuration.FunctionArn" --output text 2>/dev/null || true)

if [ -z "$EXISTING_LAMBDA" ] || [ "$EXISTING_LAMBDA" = "None" ]; then
    LAMBDA_ARN=$(aws lambda create-function \
        --function-name "$LAMBDA_FUNC_NAME" \
        --runtime python3.12 \
        --handler job_complete.handler \
        --role "$LAMBDA_ROLE_ARN" \
        --zip-file "fileb://${LAMBDA_ZIP}" \
        --timeout 60 \
        --memory-size 256 \
        --environment "Variables={${LAMBDA_ENV}}" \
        --region "$REGION" \
        --query "FunctionArn" --output text)

    echo "Waiting for Lambda to become active..."
    aws lambda wait function-active-v2 --function-name "$LAMBDA_FUNC_NAME" --region "$REGION"
    echo "Lambda: ${LAMBDA_ARN} (created)"
else
    aws lambda update-function-code \
        --function-name "$LAMBDA_FUNC_NAME" \
        --zip-file "fileb://${LAMBDA_ZIP}" \
        --region "$REGION" > /dev/null
    aws lambda wait function-updated-v2 --function-name "$LAMBDA_FUNC_NAME" --region "$REGION"
    aws lambda update-function-configuration \
        --function-name "$LAMBDA_FUNC_NAME" \
        --environment "Variables={${LAMBDA_ENV}}" \
        --region "$REGION" > /dev/null
    echo "Lambda: ${EXISTING_LAMBDA} (code and environment updated)"
fi

rm -f "$LAMBDA_ZIP"

# ---------- Step 6: S3 Event Notification ----------

echo "=== Step 6: S3 Event Notification ==="

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LAMBDA_FUNC_NAME}"

# Two triggers on one Lambda:
#   job_status.json  — written by the runtime on every exit path (success,
#                      failure, client disconnect); updates the job by job_id
#   token_usage.json — runtimes that predate job_status.json
EXISTING_CONFIG=$(aws s3api get-bucket-notification-configuration \
    --bucket "$S3_BUCKET" --region "$REGION" 2>/dev/null || true)
[ -z "$EXISTING_CONFIG" ] && EXISTING_CONFIG="{}"

# Grant S3 permission to invoke Lambda
aws lambda add-permission \
    --function-name "$LAMBDA_FUNC_NAME" \
    --statement-id "s3-invoke-${LAMBDA_FUNC_NAME}" \
    --action lambda:InvokeFunction \
    --principal s3.amazonaws.com \
    --source-arn "arn:aws:s3:::${S3_BUCKET}" \
    --source-account "$ACCOUNT_ID" \
    --region "$REGION" > /dev/null 2>&1 || true

# Add whichever of our notifications is missing; prints nothing if none is
MERGED_CONFIG=$(echo "$EXISTING_CONFIG" | python3 -c "
import sys, json
config = json.load(sys.stdin)
lc = config.get('LambdaFunctionConfigurations', [])
existing = {c.get('Id') for c in lc}
added = []
for notification_id, suffix in [('deep-insight-job-complete', 'token_usage.json'),
                                ('deep-insight-job-status', 'job_status.json')]:
    if notification_id in existing:
        continue
    lc.append({
        'Id': notification_id,
        'LambdaFunctionArn': '${LAMBDA_ARN}',
        'Events': ['s3:ObjectCreated:*'],
        'Filter': {
            'Key': {
                'FilterRules': [
                    {'Name': 'prefix', 'Value': 'deep-insight/fargate_sessions/'},
                    {'Name': 'suffix', 'Value': suffix}
                ]
            }
        }
    })
    added.append(suffix)
if added:
    config['LambdaFunctionConfigurations'] = lc
    print(json.dumps(config))
    print('S3 Event: notification added for ' + ', '.join(added), file=sys.stderr)
")

if [ -n "$MERGED_CONFIG" ]; then
    aws s3api put-bucket-notification-configuration \
        --bucket "$S3_BUCKET" \
        --notification-configuration "$MERGED_CONFIG" \
        --region "$REGION"
else
    echo "S3 Event: notifications already configured (token_usage.json, job_status.json)"
fi

# ---------- Step 6b: Stale Job Sweep Schedule ----------

# Marks jobs still in Start after STALE_JOB_MINUTES (Lambda env, default 120)
# as Failed: a runtime that dies without writing job_status.json.
echo "=== Step 6b: Stale Job Sweep Schedule ==="

SWEEP_RULE_ARN=$(aws events put-rule \
    --name "$SWEEP_RULE_NAME" \
    --schedule-expression "rate(15 minutes)" \
    --description "Mark Deep Insight jobs that never reported a final status as Failed" \
    --region "$REGION" \
    --query "RuleArn" --output text)

aws lambda add-permission \
    --function-name "$LAMBDA_FUNC_NAME" \
    --statement-id "events-invoke-${LAMBDA_FUNC_NAME}" \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "$SWEEP_RULE_ARN" \
    --region "$REGION" > /dev/null 2>&1 || true

aws events put-targets \
    --rule "$SWEEP_RULE_NAME" \
    --targets "Id=${LAMBDA_FUNC_NAME},Arn=${LAMBDA_ARN}" \
    --region "$REGION" > /dev/null

echo "Schedule: ${SWEEP_RULE_NAME} (rate 15 minutes)"

# ---------- Step 7: DynamoDB + SNS Policy on Web Task Role ----------

echo "=== Step 7: Web Task Role Policy ==="

OPS_TASK_POLICY=$(cat <<POLICY
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "DynamoDBJobTracking",
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:GetItem",
                "dynamodb:Query",
                "dynamodb:Scan"
            ],
            "Resource": [
                "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${DYNAMODB_TABLE}",
                "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${DYNAMODB_TABLE}/index/*"
            ]
        },
        {
            "Sid": "SNSFailureNotification",
            "Effect": "Allow",
            "Action": "sns:Publish",
            "Resource": "${SNS_TOPIC_ARN}"
        },
        {
            "Sid": "S3JobTraceRead",
            "Effect": "Allow",
            "Action": "s3:GetObject",
            "Resource": [
                "arn:aws:s3:::${S3_BUCKET}/deep-insight/traces/*",
                "arn:aws:s3:::${S3_BUCKET}/deep-insight/fargate_sessions/*/output/*"
            ]
        }
    ]
}
POLICY
)

aws iam put-role-policy \
    --role-name "$WEB_TASK_ROLE_NAME" \
    --policy-name "$OPS_POLICY_NAME" \
    --policy-document "$OPS_TASK_POLICY"
echo "Policy: ${OPS_POLICY_NAME} attached to ${WEB_TASK_ROLE_NAME}"

# ---------- Step 8: ECS Task Definition (add env vars) ----------

echo "=== Step 8: ECS Task Definition ==="

# Read current task definition env vars
CURRENT_ENV=$(aws ecs describe-task-definition --task-definition "$WEB_TASK_FAMILY" \
    --region "$REGION" \
    --query "taskDefinition.containerDefinitions[0].environment" --output json 2>/dev/null || echo "[]")

# Check if DYNAMODB_TABLE_NAME already exists in env vars
HAS_DYNAMODB_ENV=$(echo "$CURRENT_ENV" | python3 -c "
import sys, json
env = json.load(sys.stdin)
for e in env:
    if e['name'] == 'DYNAMODB_TABLE_NAME':
        print('yes')
        sys.exit(0)
print('no')
")

if [ "$HAS_DYNAMODB_ENV" = "yes" ]; then
    echo "ECS Task Def: env vars already present — skipping"
else
    # Read full current task definition
    CURRENT_TASK_DEF=$(aws ecs describe-task-definition --task-definition "$WEB_TASK_FAMILY" \
        --region "$REGION" --query "taskDefinition" --output json)

    # Add new env vars while preserving existing ones
    TASK_DEF_FILE="/tmp/deep-insight-ops-task-def.json"
    echo "$CURRENT_TASK_DEF" | python3 -c "
import sys, json
td = json.load(sys.stdin)
env = td['containerDefinitions'][0].get('environment', [])
env.append({'name': 'DYNAMODB_TABLE_NAME', 'value': '${DYNAMODB_TABLE}'})
env.append({'name': 'SNS_TOPIC_ARN', 'value': '${SNS_TOPIC_ARN}'})
td['containerDefinitions'][0]['environment'] = env

# Build register-task-definition input (remove read-only fields)
output = {
    'family': td['family'],
    'networkMode': td.get('networkMode', 'awsvpc'),
    'requiresCompatibilities': td.get('requiresCompatibilities', ['FARGATE']),
    'cpu': td['cpu'],
    'memory': td['memory'],
    'executionRoleArn': td.get('executionRoleArn', ''),
    'taskRoleArn': td.get('taskRoleArn', ''),
    'containerDefinitions': td['containerDefinitions'],
}
if 'runtimePlatform' in td:
    output['runtimePlatform'] = td['runtimePlatform']

json.dump(output, sys.stdout)
" > "$TASK_DEF_FILE"

    TASK_DEF_ARN=$(aws ecs register-task-definition \
        --cli-input-json "file://${TASK_DEF_FILE}" \
        --region "$REGION" \
        --query "taskDefinition.taskDefinitionArn" --output text)
    rm -f "$TASK_DEF_FILE"

    # Update service to use new task definition
    aws ecs update-service \
        --cluster "$CLUSTER_NAME" \
        --service "$WEB_SERVICE_NAME" \
        --task-definition "$TASK_DEF_ARN" \
        --force-new-deployment \
        --region "$REGION" > /dev/null

    echo "ECS Task Def: ${TASK_DEF_ARN} (env vars added, service updated)"
fi

# ============================================================
# Phase 1B: Admin Dashboard Infrastructure
# ============================================================

# ---------- Step 9: Cognito User Pool ----------

echo "=== Step 9: Cognito User Pool ==="
EXISTING_POOL_ID=$(aws cognito-idp list-user-pools --max-results 50 --region "$REGION" \
    --query "UserPools[?Name=='${COGNITO_POOL_NAME}'].Id" --output text 2>/dev/null || true)

if [ -z "$EXISTING_POOL_ID" ] || [ "$EXISTING_POOL_ID" = "None" ]; then
    COGNITO_POOL_ID=$(aws cognito-idp create-user-pool \
        --pool-name "$COGNITO_POOL_NAME" \
        --admin-create-user-config '{"AllowAdminCreateUserOnly": true}' \
        --policies '{
            "PasswordPolicy": {
                "MinimumLength": 12,
                "RequireUppercase": true,
                "RequireLowercase": true,
                "RequireNumbers": true,
                "RequireSymbols": true
            }
        }' \
        --auto-verified-attributes email \
        --schema '[{"Name":"email","Required":true,"Mutable":true}]' \
        --region "$REGION" \
        --query "UserPool.Id" --output text)
    echo "Cognito User Pool: ${COGNITO_POOL_ID} (created)"
else
    COGNITO_POOL_ID="$EXISTING_POOL_ID"
    echo "Cognito User Pool: ${COGNITO_POOL_ID} (already exists)"
fi

# ---------- Step 10: Cognito App Client ----------

echo "=== Step 10: Cognito App Client ==="
COGNITO_CLIENT_NAME="deep-insight-ops-web"
EXISTING_CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id "$COGNITO_POOL_ID" \
    --region "$REGION" \
    --query "UserPoolClients[?ClientName=='${COGNITO_CLIENT_NAME}'].ClientId" --output text 2>/dev/null || true)

if [ -z "$EXISTING_CLIENT_ID" ] || [ "$EXISTING_CLIENT_ID" = "None" ]; then
    COGNITO_CLIENT_ID=$(aws cognito-idp create-user-pool-client \
        --user-pool-id "$COGNITO_POOL_ID" \
        --client-name "$COGNITO_CLIENT_NAME" \
        --no-generate-secret \
        --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH \
        --region "$REGION" \
        --query "UserPoolClient.ClientId" --output text)
    echo "Cognito App Client: ${COGNITO_CLIENT_ID} (created)"
else
    COGNITO_CLIENT_ID="$EXISTING_CLIENT_ID"
    echo "Cognito App Client: ${COGNITO_CLIENT_ID} (already exists)"
fi

# ---------- Step 11: Cognito Admin User ----------

echo "=== Step 11: Cognito Admin User ==="
if [ ${#ADMIN_EMAILS[@]} -eq 0 ]; then
    echo "No email args — skipping admin user creation"
else
    for email in "${ADMIN_EMAILS[@]}"; do
        EXISTING_USER=$(aws cognito-idp admin-get-user --user-pool-id "$COGNITO_POOL_ID" \
            --username "$email" --region "$REGION" \
            --query "Username" --output text 2>/dev/null || true)

        if [ -z "$EXISTING_USER" ] || [ "$EXISTING_USER" = "None" ]; then
            aws cognito-idp admin-create-user \
                --user-pool-id "$COGNITO_POOL_ID" \
                --username "$email" \
                --user-attributes Name=email,Value="$email" Name=email_verified,Value=true \
                --desired-delivery-mediums EMAIL \
                --region "$REGION" > /dev/null
            echo "Cognito Admin: ${email} (created — temporary password sent via email)"
        else
            echo "Cognito Admin: ${email} (already exists)"
        fi
    done
fi

# ---------- Step 12: ECS Task Definition (Cognito env vars) ----------

echo "=== Step 12: ECS Task Definition (Cognito) ==="

# Read current task definition env vars
CURRENT_ENV=$(aws ecs describe-task-definition --task-definition "$WEB_TASK_FAMILY" \
    --region "$REGION" \
    --query "taskDefinition.containerDefinitions[0].environment" --output json 2>/dev/null || echo "[]")

# Check if COGNITO_USER_POOL_ID already exists in env vars
HAS_COGNITO_ENV=$(echo "$CURRENT_ENV" | python3 -c "
import sys, json
env = json.load(sys.stdin)
for e in env:
    if e['name'] == 'COGNITO_USER_POOL_ID':
        print('yes')
        sys.exit(0)
print('no')
")

if [ "$HAS_COGNITO_ENV" = "yes" ]; then
    echo "ECS Task Def: Cognito env vars already present — skipping"
else
    # Read full current task definition
    CURRENT_TASK_DEF=$(aws ecs describe-task-definition --task-definition "$WEB_TASK_FAMILY" \
        --region "$REGION" --query "taskDefinition" --output json)

    # Add Cognito env vars while preserving existing ones
    TASK_DEF_FILE="/tmp/deep-insight-ops-task-def.json"
    echo "$CURRENT_TASK_DEF" | python3 -c "
import sys, json
td = json.load(sys.stdin)
env = td['containerDefinitions'][0].get('environment', [])
env.append({'name': 'COGNITO_USER_POOL_ID', 'value': '${COGNITO_POOL_ID}'})
env.append({'name': 'COGNITO_CLIENT_ID', 'value': '${COGNITO_CLIENT_ID}'})
td['containerDefinitions'][0]['environment'] = env

output = {
    'family': td['family'],
    'networkMode': td.get('networkMode', 'awsvpc'),
    'requiresCompatibilities': td.get('requiresCompatibilities', ['FARGATE']),
    'cpu': td['cpu'],
    'memory': td['memory'],
    'executionRoleArn': td.get('executionRoleArn', ''),
    'taskRoleArn': td.get('taskRoleArn', ''),
    'containerDefinitions': td['containerDefinitions'],
}
if 'runtimePlatform' in td:
    output['runtimePlatform'] = td['runtimePlatform']

json.dump(output, sys.stdout)
" > "$TASK_DEF_FILE"

    TASK_DEF_ARN=$(aws ecs register-task-definition \
        --cli-input-json "file://${TASK_DEF_FILE}" \
        --region "$REGION" \
        --query "taskDefinition.taskDefinitionArn" --output text)
    rm -f "$TASK_DEF_FILE"

    # Update service to use new task definition
    aws ecs update-service \
        --cluster "$CLUSTER_NAME" \
        --service "$WEB_SERVICE_NAME" \
        --task-definition "$TASK_DEF_ARN" \
        --force-new-deployment \
        --region "$REGION" > /dev/null

    echo "ECS Task Def: ${TASK_DEF_ARN} (Cognito env vars added, service updated)"
fi

# ---------- Done ----------

echo ""
echo "============================================"
echo "Ops Infrastructure Deployment Complete!"
echo "============================================"
echo ""
echo "Resources:"
echo "  DynamoDB Table:     ${DYNAMODB_TABLE}"
echo "  SNS Topic ARN:      ${SNS_TOPIC_ARN}"
echo "  Lambda Function:    ${LAMBDA_FUNC_NAME}"
echo "  Sweep Schedule:     ${SWEEP_RULE_NAME}"
echo "  Cognito User Pool:  ${COGNITO_POOL_ID}"
echo "  Cognito Client ID:  ${COGNITO_CLIENT_ID}"
echo ""
if [ ${#ADMIN_EMAILS[@]} -gt 0 ]; then
    echo "ACTION REQUIRED:"
    echo "  1. Each admin must confirm their SNS subscription via the email they received."
    echo "  2. Each admin must log in to /admin/login with the temporary password from Cognito email."
    echo ""
fi
echo "Adding subscribers later:"
echo "  # Add email notifications:"
echo "  aws sns subscribe --cli-input-json '{\"TopicArn\": \"${SNS_TOPIC_ARN}\", \"Protocol\": \"email\", \"Endpoint\": \"NEW_EMAIL\"}' --region ${REGION}"
echo ""
echo "  # Add dashboard admin:"
echo "  aws cognito-idp admin-create-user --user-pool-id ${COGNITO_POOL_ID} --username NEW_EMAIL --user-attributes Name=email,Value=NEW_EMAIL Name=email_verified,Value=true --desired-delivery-mediums EMAIL --region ${REGION}"
echo ""
