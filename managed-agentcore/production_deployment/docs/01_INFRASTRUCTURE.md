# Phase 1: 인프라 배포

> **소요 시간**: 30-40분
> **난이도**: 중급
> **사전 요구사항**: [00_OVERVIEW.md](./00_OVERVIEW.md) 확인 완료

---

## 📋 목차

1. [개요](#개요)
2. [Step 1: 환경 설정](#step-1-환경-설정)
3. [Step 2: CloudFormation 템플릿 준비](#step-2-cloudformation-템플릿-준비)
4. [Step 3: 인프라 배포](#step-3-인프라-배포)
5. [Step 4: 검증](#step-4-검증)
6. [트러블슈팅](#트러블슈팅)

---

## 🎯 개요

이 단계에서는 다음 리소스를 CloudFormation으로 배포합니다:

### 생성될 리소스

- ✅ VPC (10.0.0.0/16)
- ✅ Subnets 2개 (Private 1개, Public 1개, Single-AZ: us-east-1a)
- ✅ Internet Gateway
- ✅ NAT Gateway
- ✅ Route Tables
- ✅ Security Groups 4개 (AgentCore, ALB, Fargate, VPC Endpoint)
- ✅ Internal ALB + Target Group
- ✅ ECS Cluster
- ✅ VPC Endpoints 6개 (Bedrock AgentCore x2, ECR API, ECR Docker, CloudWatch Logs, S3 Gateway)
- ✅ IAM Roles 3개 (Fargate Task Role, Execution Role, Service-Linked Role)

---

## Step 1: 환경 설정

### 1.1 환경 변수 설정

```bash
# 프로젝트 루트로 이동
cd production_deployment

# 환경 파라미터 파일 생성
cat > parameters/prod-params.json <<EOF
{
  "Parameters": [
    {"ParameterKey": "Environment", "ParameterValue": "prod"},
    {"ParameterKey": "ProjectName", "ParameterValue": "bedrock-manus"},
    {"ParameterKey": "VpcCidr", "ParameterValue": "10.0.0.0/16"},
    {"ParameterKey": "PrivateSubnetCidr", "ParameterValue": "10.0.1.0/24"},
    {"ParameterKey": "PublicSubnetCidr", "ParameterValue": "10.0.11.0/24"},
    {"ParameterKey": "AvailabilityZone", "ParameterValue": "us-east-1a"},
    {"ParameterKey": "S3BucketName", "ParameterValue": "bedrock-logs-prod-REPLACE_WITH_ACCOUNT_ID"}
  ]
}
EOF
```

**⚠️ 중요**: `REPLACE_WITH_ACCOUNT_ID`를 실제 AWS 계정 ID로 변경하세요.

```bash
# AWS 계정 ID 확인
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Your AWS Account ID: $AWS_ACCOUNT_ID"

# 자동으로 파라미터 파일 업데이트
sed -i "s/REPLACE_WITH_ACCOUNT_ID/$AWS_ACCOUNT_ID/g" parameters/prod-params.json

# 확인
cat parameters/prod-params.json
```

### 1.2 체크리스트

- [ ] AWS CLI 로그인 확인: `aws sts get-caller-identity`
- [ ] 리전 확인: `us-east-1` (또는 원하는 리전)
- [ ] `parameters/prod-params.json` 파일 생성 및 확인
- [ ] S3 버킷 이름 고유성 확인 (S3는 전역 고유 이름 필요)

---

## Step 2: CloudFormation 템플릿 준비

### 2.1 통합 템플릿 구조

단순화를 위해 하나의 CloudFormation 템플릿으로 모든 인프라를 배포합니다.

**템플릿 위치**: `cloudformation/infrastructure.yaml`

템플릿은 다음 섹션으로 구성됩니다:

1. **Parameters**: 환경별 설정 (VPC CIDR, 환경 이름 등)
2. **VPC & Networking**: VPC, Subnets, IGW, NAT, Route Tables
3. **Security Groups**: 4개 (AgentCore, ALB, Fargate, VPC Endpoint)
4. **VPC Endpoints**: Bedrock AgentCore, ECR, S3, Logs
5. **ALB**: Internal Application Load Balancer + Target Group
6. **ECS**: Fargate Cluster
7. **IAM**: Task Role, Execution Role
8. **Outputs**: 다음 단계에서 사용할 값들

### 2.2 템플릿 복사 확인

```bash
# 템플릿 파일 존재 확인
ls -lh cloudformation/infrastructure.yaml

# 템플릿 검증
aws cloudformation validate-template \
  --template-body file://cloudformation/infrastructure.yaml \
  --query 'Description' \
  --output text
```

**예상 출력**:
```
Bedrock Manus Production Infrastructure - VPC, ALB, Fargate, VPC Endpoints
```

---

## Step 3: 인프라 배포

### 3.1 CloudFormation 스택 생성

```bash
# 스택 이름 설정
STACK_NAME="bedrock-manus-infrastructure-prod"
REGION="us-east-1"

# CloudFormation 스택 배포
aws cloudformation deploy \
  --template-file cloudformation/infrastructure.yaml \
  --stack-name $STACK_NAME \
  --parameter-overrides file://parameters/prod-params.json \
  --capabilities CAPABILITY_NAMED_IAM \
  --region $REGION \
  --tags \
    Environment=prod \
    Project=bedrock-manus \
    ManagedBy=CloudFormation

echo "✅ CloudFormation 스택 배포 시작: $STACK_NAME"
```

### 3.2 배포 진행 상황 모니터링

**방법 1: CLI로 모니터링**
```bash
# 실시간 이벤트 모니터링 (새 터미널에서 실행)
watch -n 5 "aws cloudformation describe-stack-events \
  --stack-name $STACK_NAME \
  --max-items 10 \
  --query 'StackEvents[*].[Timestamp,ResourceStatus,ResourceType,LogicalResourceId]' \
  --output table"
```

**방법 2: AWS 콘솔로 모니터링**
1. AWS 콘솔 접속: https://console.aws.amazon.com/cloudformation
2. 리전 선택: us-east-1
3. 스택 이름 클릭: `bedrock-manus-infrastructure-prod`
4. "Events" 탭에서 진행 상황 확인

### 3.3 예상 시간

- VPC 및 Subnets: ~2분
- Internet Gateway & NAT Gateway: ~3분
- Security Groups: ~1분
- VPC Endpoints: ~5-10분 (가장 오래 걸림)
- ALB & Target Group: ~3분
- ECS Cluster: ~1분
- IAM Roles: ~1분

**총 예상 시간**: 15-20분

### 3.4 배포 완료 확인

```bash
# 스택 상태 확인
aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].StackStatus' \
  --output text
```

**예상 출력**: `CREATE_COMPLETE` 또는 `UPDATE_COMPLETE`

---

## Step 4: 검증

### 4.1 CloudFormation Outputs 확인

```bash
# 모든 출력 값 확인
aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs' \
  --output table
```

**예상 출력**:
```
-----------------------------------------------------------------
|                        DescribeStacks                          |
+------------------------+---------------------------------------+
|      OutputKey         |           OutputValue                 |
+------------------------+---------------------------------------+
|  VpcId                 |  vpc-0xxxxxxxxxxxxx                   |
|  PrivateSubnetIds      |  subnet-0xxx,subnet-0yyy              |
|  SecurityGroupIds      |  sg-0xxx,sg-0yyy,sg-0zzz,sg-0www      |
|  ALBTargetGroupArn     |  arn:aws:elasticloadbalancing:...     |
|  InternalALBDNS        |  internal-bedrock-xxx.elb.amazonaws...|
|  ECSClusterName        |  bedrock-manus-cluster-prod           |
|  FargateTaskRoleArn    |  arn:aws:iam::xxx:role/...            |
|  FargateExecutionRole  |  arn:aws:iam::xxx:role/...            |
+------------------------+---------------------------------------+
```

### 4.2 리소스 개별 확인

#### VPC 확인
```bash
VPC_ID=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`VpcId`].OutputValue' \
  --output text)

echo "VPC ID: $VPC_ID"

# VPC 상세 정보
aws ec2 describe-vpcs --vpc-ids $VPC_ID --output table
```

#### Subnets 확인
```bash
# Private Subnets
aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Type,Values=private" \
  --query 'Subnets[*].[SubnetId,AvailabilityZone,CidrBlock,AvailableIpAddressCount]' \
  --output table
```

#### VPC Endpoints 확인
```bash
# VPC Endpoints 상태 확인
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'VpcEndpoints[*].[VpcEndpointId,ServiceName,State]' \
  --output table
```

**모든 Endpoint가 `available` 상태여야 합니다.**

#### ALB 확인
```bash
# ALB DNS 이름
ALB_DNS=$(aws cloudformation describe-stacks \
  --stack-name $STACK_NAME \
  --query 'Stacks[0].Outputs[?OutputKey==`InternalALBDNS`].OutputValue' \
  --output text)

echo "Internal ALB DNS: $ALB_DNS"

# ALB 상태 확인
aws elbv2 describe-load-balancers \
  --names "internal-bedrock-manus-alb-prod" \
  --query 'LoadBalancers[0].State' \
  --output table
```

**예상 출력**: `active`

#### Security Groups 확인
```bash
# Security Group IDs
aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[*].[GroupId,GroupName,Description]' \
  --output table
```

### 4.3 환경 변수 파일 생성 (다음 단계용)

```bash
# .env.prod 파일 생성
cat > ../deployment.env <<EOF
# Auto-generated from CloudFormation Stack: $STACK_NAME
# Generated at: $(date)

ENVIRONMENT=prod
AWS_REGION=$REGION
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# CloudFormation Stack
STACK_NAME=$STACK_NAME

# VPC
VPC_ID=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`VpcId`].OutputValue' --output text)
PRIVATE_SUBNET_IDS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`PrivateSubnetIds`].OutputValue' --output text)

# Security Groups
AGENTCORE_SECURITY_GROUP=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`AgentCoreSecurityGroupId`].OutputValue' --output text)
ALB_SECURITY_GROUP=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`ALBSecurityGroupId`].OutputValue' --output text)
FARGATE_SECURITY_GROUP=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`FargateSecurityGroupId`].OutputValue' --output text)

# ALB
INTERNAL_ALB_DNS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`InternalALBDNS`].OutputValue' --output text)
ALB_TARGET_GROUP_ARN=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`ALBTargetGroupArn`].OutputValue' --output text)

# ECS
ECS_CLUSTER_NAME=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' --output text)

# IAM
FARGATE_TASK_ROLE_ARN=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`FargateTaskRoleArn`].OutputValue' --output text)
FARGATE_EXECUTION_ROLE_ARN=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`FargateExecutionRoleArn`].OutputValue' --output text)

# S3
S3_BUCKET_NAME=bedrock-logs-prod-$(aws sts get-caller-identity --query Account --output text)
EOF

echo "✅ 환경 변수 파일 생성 완료: deployment.env"
cat ../deployment.env
```

### 4.4 체크리스트

배포 완료 전 다음을 확인하세요:

- [ ] CloudFormation 스택 상태: `CREATE_COMPLETE`
- [ ] VPC ID 확인됨
- [ ] Private Subnet 생성됨 (us-east-1a)
- [ ] Public Subnet 생성됨 (us-east-1a)
- [ ] NAT Gateway 상태: `available`
- [ ] VPC Endpoints 6개 모두 상태: `available`
- [ ] Security Groups 4개 생성됨
- [ ] Internal ALB 상태: `active`
- [ ] ECS Cluster 생성됨
- [ ] IAM Roles 생성됨
- [ ] `deployment.env` 파일 생성됨

---

## 🔧 트러블슈팅

### 문제 1: CloudFormation 스택 생성 실패

**증상**:
```
Stack creation failed: CREATE_FAILED
```

**해결 방법**:
```bash
# 실패 이유 확인
aws cloudformation describe-stack-events \
  --stack-name $STACK_NAME \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`].[LogicalResourceId,ResourceStatusReason]' \
  --output table

# 스택 삭제 (재시도 전)
aws cloudformation delete-stack --stack-name $STACK_NAME

# 삭제 완료 대기
aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME
```

**일반적인 원인**:
1. **VPC CIDR 충돌**: 기존 VPC와 CIDR 블록이 겹침
   - 해결: `parameters/prod-params.json`에서 `VpcCidr` 변경 (예: `10.1.0.0/16`)

2. **S3 버킷 이름 중복**: 전역적으로 고유해야 함
   - 해결: S3 버킷 이름에 랜덤 suffix 추가

3. **IAM 권한 부족**: CAPABILITY_NAMED_IAM 필요
   - 해결: `--capabilities CAPABILITY_NAMED_IAM` 플래그 확인

4. **Availability Zone 미지원**: 특정 AZ에서 리소스 생성 불가
   - 해결: 템플릿에서 다른 AZ 선택 (예: us-east-1b, us-east-1d)

### 문제 2: VPC Endpoint가 `pending` 상태로 멈춤

**증상**:
```
VPC Endpoint State: pending (10분 이상)
```

**해결 방법**:
```bash
# VPC Endpoint 상세 확인
aws ec2 describe-vpc-endpoints \
  --vpc-endpoint-ids vpce-xxxxxxxxx \
  --query 'VpcEndpoints[0]' \
  --output json

# DNS 설정 확인
aws ec2 describe-vpcs \
  --vpc-ids $VPC_ID \
  --query 'Vpcs[0].[EnableDnsHostnames,EnableDnsSupport]' \
  --output table
```

**일반적인 원인**:
- DNS Hostnames/Support가 비활성화됨
- Security Group 규칙 누락
- Subnet 라우팅 테이블 문제

### 문제 3: NAT Gateway 생성 실패

**증상**:
```
NAT Gateway State: failed
```

**해결 방법**:
```bash
# NAT Gateway 상태 확인
aws ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=$VPC_ID" \
  --query 'NatGateways[*].[NatGatewayId,State,FailureMessage]' \
  --output table
```

**일반적인 원인**:
- Elastic IP 할당량 초과
- Public Subnet 없음
- Internet Gateway 미연결

### 문제 4: ALB Target Group Unhealthy

**증상**:
```
Target Group Health: unhealthy
```

**참고**: 이 단계에서는 아직 Fargate Task를 등록하지 않았으므로 Target이 없는 것이 정상입니다.

다음 단계 (Phase 2)에서 Fargate Task 등록 후 Health Check를 확인합니다.

---

## ✅ 완료 확인

다음이 모두 완료되었으면 Phase 1이 성공적으로 완료되었습니다:

- [x] CloudFormation 스택 `CREATE_COMPLETE` 상태
- [x] VPC 및 Subnets 생성 확인
- [x] VPC Endpoints 모두 `available` 상태
- [x] Security Groups 생성 확인
- [x] ALB 및 Target Group 생성 확인
- [x] ECS Cluster 생성 확인
- [x] IAM Roles 생성 확인
- [x] `deployment.env` 파일 생성 완료

**STATUS.md 업데이트**:
```bash
# production_deployment/STATUS.md 파일을 편집하여 Phase 1 체크박스를 완료로 표시하세요
```

---

## 📚 다음 단계

Phase 1 완료를 축하합니다! 🎉

다음 단계로 진행하세요:

→ **[02_FARGATE_RUNTIME.md](./02_FARGATE_RUNTIME.md)** - Fargate Runtime 배포

---

**작성일**: 2025-10-20
**마지막 업데이트**: 2025-10-20
