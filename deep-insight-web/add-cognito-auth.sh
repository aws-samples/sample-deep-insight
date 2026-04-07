#!/bin/bash
set -euo pipefail

# ============================================================
# add-cognito-auth.sh — Attach Cognito Lambda@Edge to CloudFront
#
# Associates a pre-deployed Cognito Lambda@Edge function with a
# CloudFront distribution for authentication. Also registers the
# CloudFront domain as a callback URL in the Cognito app client.
#
# Prerequisites:
#   - Cognito User Pool with Lambda@Edge function deployed
#     (e.g., via CDK stack in a separate Cognito project)
#   - Lambda@Edge must be in us-east-1 (CloudFront requirement)
#   - Lambda must have a published version (not $LATEST)
#
# Usage:
#   bash add-cognito-auth.sh <distribution-id> [lambda-arn] [user-pool-id] [client-id]
#
# Examples:
#   bash add-cognito-auth.sh E1234567890ABC
#   bash add-cognito-auth.sh E1234567890ABC arn:aws:lambda:us-east-1:123:function:auth:1
#
# Environment variables (override defaults):
#   COGNITO_LAMBDA_ARN    - Lambda@Edge version ARN
#   COGNITO_USER_POOL_ID  - Cognito User Pool ID
#   COGNITO_CLIENT_ID     - Cognito App Client ID
#   COGNITO_REGION        - Cognito region (default: us-east-1)
# ============================================================

if [ $# -lt 1 ]; then
    echo "Usage: $0 <distribution-id> [lambda-arn] [user-pool-id] [client-id]"
    echo ""
    echo "Examples:"
    echo "  $0 E1234567890ABC"
    echo "  $0 E1234567890ABC arn:aws:lambda:us-east-1:123:function:auth:1"
    echo ""
    echo "Override defaults with environment variables:"
    echo "  COGNITO_LAMBDA_ARN=... COGNITO_USER_POOL_ID=... $0 E1234567890ABC"
    exit 1
fi

DIST_ID="$1"
LAMBDA_VERSION_ARN="${2:-${COGNITO_LAMBDA_ARN:-}}"
USER_POOL_ID="${3:-${COGNITO_USER_POOL_ID:-}}"
CLIENT_ID="${4:-${COGNITO_CLIENT_ID:-}}"
COGNITO_REGION="${COGNITO_REGION:-us-east-1}"

# Auto-discover Lambda@Edge if not provided
if [ -z "$LAMBDA_VERSION_ARN" ]; then
    echo "Auto-discovering Lambda@Edge function..."
    # Look for common naming patterns
    for FUNC_NAME in "poc-cognito-auth-edge" "deep-insight-cognito-auth" "cognito-auth-edge"; do
        ARN=$(aws lambda list-versions-by-function \
            --function-name "$FUNC_NAME" \
            --region "$COGNITO_REGION" \
            --query 'Versions[-1].FunctionArn' \
            --output text 2>/dev/null || true)
        if [ -n "$ARN" ] && [ "$ARN" != "None" ]; then
            LAMBDA_VERSION_ARN="$ARN"
            echo "  Found: ${FUNC_NAME} -> ${LAMBDA_VERSION_ARN}"
            break
        fi
    done

    if [ -z "$LAMBDA_VERSION_ARN" ]; then
        echo "ERROR: No Lambda@Edge function found. Provide ARN as argument or COGNITO_LAMBDA_ARN env var."
        exit 1
    fi
fi

# Auto-discover Cognito User Pool if not provided
if [ -z "$USER_POOL_ID" ] || [ -z "$CLIENT_ID" ]; then
    echo "Auto-discovering Cognito User Pool..."
    POOLS=$(aws cognito-idp list-user-pools --max-results 10 --region "$COGNITO_REGION" \
        --query "UserPools[?contains(Name, 'deep-insight') || contains(Name, 'poc-demo')].{Id:Id,Name:Name}" \
        --output json 2>/dev/null || echo "[]")

    POOL_ID=$(echo "$POOLS" | python3 -c "
import json, sys
pools = json.load(sys.stdin)
if pools: print(pools[0]['Id'])
else: print('')
" 2>/dev/null || true)

    if [ -n "$POOL_ID" ]; then
        USER_POOL_ID="$POOL_ID"
        CLIENT_ID=$(aws cognito-idp list-user-pool-clients \
            --user-pool-id "$USER_POOL_ID" \
            --region "$COGNITO_REGION" \
            --query "UserPoolClients[0].ClientId" \
            --output text 2>/dev/null || true)
        echo "  User Pool: ${USER_POOL_ID}"
        echo "  Client ID: ${CLIENT_ID}"
    fi
fi

if [ -z "$USER_POOL_ID" ] || [ -z "$CLIENT_ID" ]; then
    echo "ERROR: Cognito User Pool not found. Provide user-pool-id and client-id as arguments."
    exit 1
fi

echo ""
echo "============================================"
echo "Attach Cognito Auth to CloudFront"
echo "============================================"
echo "Distribution:  ${DIST_ID}"
echo "Lambda@Edge:   ${LAMBDA_VERSION_ARN}"
echo "User Pool:     ${USER_POOL_ID}"
echo "Client ID:     ${CLIENT_ID}"
echo ""

# Step 1: Get current distribution config
echo "=== Step 1: Get current CloudFront config ==="
ETAG=$(aws cloudfront get-distribution-config --id "${DIST_ID}" --query 'ETag' --output text)
aws cloudfront get-distribution-config --id "${DIST_ID}" --query 'DistributionConfig' > /tmp/cf-config.json
echo "  ETag: ${ETAG}"

# Step 2: Add Lambda@Edge to default cache behavior
echo "=== Step 2: Update config with Lambda@Edge ==="
LAMBDA_ASSOC="{\"LambdaFunctionAssociations\":{\"Quantity\":1,\"Items\":[{\"LambdaFunctionARN\":\"${LAMBDA_VERSION_ARN}\",\"EventType\":\"viewer-request\",\"IncludeBody\":false}]}}"

jq --argjson assoc "${LAMBDA_ASSOC}" \
    '.DefaultCacheBehavior += $assoc' \
    /tmp/cf-config.json > /tmp/cf-config-updated.json

# Step 3: Update distribution
echo "=== Step 3: Update CloudFront distribution ==="
aws cloudfront update-distribution \
    --id "${DIST_ID}" \
    --if-match "${ETAG}" \
    --distribution-config file:///tmp/cf-config-updated.json \
    --no-cli-pager > /dev/null

echo ""
echo "  Done! Distribution ${DIST_ID} is being updated."
echo "  CloudFront deployment takes 2-5 minutes."

# Step 4: Add callback URL to Cognito
echo "=== Step 4: Register CloudFront callback URL ==="

CF_DOMAIN=$(aws cloudfront get-distribution --id "${DIST_ID}" \
    --query 'Distribution.DomainName' --output text)

CALLBACK="https://${CF_DOMAIN}/callback"
LOGOUT="https://${CF_DOMAIN}"

CURRENT=$(aws cognito-idp describe-user-pool-client \
    --user-pool-id "${USER_POOL_ID}" \
    --client-id "${CLIENT_ID}" \
    --region "${COGNITO_REGION}")

CURRENT_CALLBACKS=$(echo "${CURRENT}" | jq -r '.UserPoolClient.CallbackURLs // [] | .[]')

if echo "${CURRENT_CALLBACKS}" | grep -q "${CALLBACK}"; then
    echo "  Callback URL already registered: ${CALLBACK}"
else
    echo "  Adding callback URL: ${CALLBACK}"

    # Build updated URL lists
    NEW_CALLBACKS=$(echo "${CURRENT}" | jq -r '[.UserPoolClient.CallbackURLs // [] | .[]] + ["'"${CALLBACK}"'"] | join(" ")')
    NEW_LOGOUTS=$(echo "${CURRENT}" | jq -r '[.UserPoolClient.LogoutURLs // [] | .[]] + ["'"${LOGOUT}"'"] | join(" ")')

    # Ensure SupportedIdentityProviders includes COGNITO (required for Hosted UI)
    aws cognito-idp update-user-pool-client \
        --user-pool-id "${USER_POOL_ID}" \
        --client-id "${CLIENT_ID}" \
        --supported-identity-providers COGNITO \
        --callback-urls ${NEW_CALLBACKS} \
        --logout-urls ${NEW_LOGOUTS} \
        --allowed-o-auth-flows code \
        --allowed-o-auth-scopes openid email profile \
        --allowed-o-auth-flows-user-pool-client \
        --region "${COGNITO_REGION}" \
        --no-cli-pager > /dev/null

    echo "  Cognito callback URLs updated"
fi

# Cleanup
rm -f /tmp/cf-config.json /tmp/cf-config-updated.json

echo ""
echo "============================================"
echo "Cognito auth attached successfully!"
echo "============================================"
echo ""
echo "URL:      https://${CF_DOMAIN}"
echo "Sign-out: https://${CF_DOMAIN}/signout"
echo ""
echo "Wait 2-5 minutes for CloudFront to deploy, then test access."
