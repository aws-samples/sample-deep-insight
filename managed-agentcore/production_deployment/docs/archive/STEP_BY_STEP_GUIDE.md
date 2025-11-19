# 🚀 Phase 1-2 단계별 배포 가이드 (CloudFormation)

> **목표**: Production 계정에서 Phase 1 인프라와 Phase 2 Fargate Runtime을 CloudFormation으로 배포

---

## 📋 목차

1. [사전 준비](#1-사전-준비)
2. [Git Repository Clone](#2-git-repository-clone)
3. [Phase 1 배포 (인프라)](#3-phase-1-배포-인프라)
4. [Phase 1 검증](#4-phase-1-검증)
5. [Phase 2 배포 (Fargate Runtime)](#5-phase-2-배포-fargate-runtime)
6. [Phase 2 검증](#6-phase-2-검증)
7. [다음 단계](#7-다음-단계)

---

## 1. 사전 준비

### 1.1 AWS CLI 설치 및 설정

```bash
# AWS CLI 버전 확인 (v2.0 이상 필요)
aws --version

# Production 계정 자격증명 설정
aws configure
```

**입력 정보**:
- AWS Access Key ID: `<Production 계정 Access Key>`
- AWS Secret Access Key: `<Production 계정 Secret Key>`
- Default region name: `us-east-1`
- Default output format: `json`

**확인**:
```bash
aws sts get-caller-identity
```

### 1.2 필수 IAM 권한 확인

다음 권한이 필요합니다:
- ✅ `EC2FullAccess`
- ✅ `ElasticLoadBalancingFullAccess`
- ✅ `IAMFullAccess`
- ✅ `CloudFormationFullAccess`

**권한 확인**:
```bash
# 현재 사용자의 정책 확인
aws iam list-attached-user-policies \
  --user-name $(aws sts get-caller-identity --query 'Arn' --output text | cut -d'/' -f2)
```

---

## 2. Git Repository Clone

### 2.1 Repository Clone

```bash
# GitHub에서 Clone
git clone https://github.com/hyeonsangjeon/aws-ai-ml-workshop-kr.git

# 프로젝트 디렉토리로 이동
cd aws-ai-ml-workshop-kr/genai/aws-gen-ai-kr/20_applications/08_bedrock_manus/use_cases/05_insight_extractor_strands_sdk_workshop_phase_2/production_deployment
```

### 2.2 파일 확인

```bash
# Phase 1 관련 파일 확인
ls -l cloudformation/phase1-infrastructure.yaml
ls -l cloudformation/parameters/phase1-prod-params.json
ls -l scripts/phase1/deploy.sh
ls -l scripts/phase1/verify.sh
```

**예상 출력**:
```
-rw-r--r-- 1 user group 22K cloudformation/phase1-infrastructure.yaml
-rw-r--r-- 1 user group 588 cloudformation/parameters/phase1-prod-params.json
-rwxr-xr-x 1 user group 12K scripts/phase1/deploy.sh
-rwxr-xr-x 1 user group 8K  scripts/phase1/verify.sh
```

---

## 3. Phase 1 배포 (인프라)

### 3.1 배포 스크립트 실행 권한 부여

```bash
chmod +x scripts/phase1/*.sh
```

### 3.2 Phase 1 배포 시작

```bash
# Production 환경으로 배포
./scripts/phase1/deploy.sh prod
```

### 3.3 배포 과정

**자동 실행되는 단계**:

1. ✅ **사전 체크** (1분)
   - AWS CLI 설치 확인
   - AWS 자격증명 확인
   - CloudFormation 템플릿 검증

2. ✅ **Account ID 주입** (1분)
   - `phase1-prod-params.json`의 `ACCOUNT_ID` 플레이스홀더를 실제 Account ID로 치환

3. ✅ **CloudFormation 스택 배포** (30-40분)
   - Stack 이름: `deep-insight-infrastructure-prod`
   - 리소스 생성 시작

4. ✅ **스택 출력값 추출** (1분)
   - 생성된 리소스 ID를 `.env` 파일에 저장

### 3.4 배포 모니터링 (별도 터미널)

배포 중 별도 터미널에서 진행 상황을 모니터링할 수 있습니다:

```bash
# 스택 상태 확인 (10초마다 갱신)
watch -n 10 "aws cloudformation describe-stacks \
  --stack-name deep-insight-infrastructure-prod \
  --region us-east-1 \
  --query 'Stacks[0].StackStatus' \
  --output text"
```

**스택 상태 변화**:
```
CREATE_IN_PROGRESS → CREATE_COMPLETE (성공)
CREATE_IN_PROGRESS → ROLLBACK_IN_PROGRESS → ROLLBACK_COMPLETE (실패)
```

### 3.5 예상 배포 시간

| 리소스 | 예상 시간 |
|--------|-----------|
| VPC, Subnets | 2-3분 |
| Internet Gateway | 1분 |
| NAT Gateway | 5-7분 |
| Security Groups | 1-2분 |
| VPC Endpoints (6개) | 15-20분 |
| ALB + Target Group | 3-5분 |
| IAM Roles | 1-2분 |
| **총 예상 시간** | **30-40분** |

### 3.6 배포 완료 확인

배포가 성공하면 다음과 같은 메시지가 표시됩니다:

```bash
============================================
✓ Stack deployment successful!
============================================

Created Resources:

Network:
  VPC ID:            vpc-xxxxxxxxxxxxx
  Private Subnet:    subnet-xxxxxxxxxxxxx (us-east-1a)
  Public Subnet:     subnet-xxxxxxxxxxxxx (us-east-1a)

Security Groups:
  AgentCore SG:      sg-xxxxxxxxxxxxx
  ALB SG:            sg-xxxxxxxxxxxxx
  Fargate SG:        sg-xxxxxxxxxxxxx
  VPC Endpoint SG:   sg-xxxxxxxxxxxxx

Load Balancer:
  ALB ARN:           arn:aws:elasticloadbalancing:us-east-1:...
  ALB DNS:           deep-insight-alb-prod-xxxxx.us-east-1.elb.amazonaws.com
  Target Group:      arn:aws:elasticloadbalancing:us-east-1:...

IAM Roles:
  Task Execution:    arn:aws:iam::123456789012:role/deep-insight-task-execution-role-prod
  Task Role:         arn:aws:iam::123456789012:role/deep-insight-task-role-prod

Next Steps:
  1. Run verification: ./scripts/phase1/verify.sh
  2. Proceed to Phase 2: (Phase 1 완료 후 진행)
```

---

## 4. Phase 1 검증

### 4.1 자동 검증 스크립트 실행

```bash
./scripts/phase1/verify.sh
```

### 4.2 검증 항목 (총 15개 체크)

**1. VPC 및 네트워크 리소스** (5개):
- VPC 존재 확인
- Private Subnet 존재 확인
- Public Subnet 존재 확인
- NAT Gateway available 확인
- Internet Gateway attached 확인

**2. Security Groups** (4개):
- AgentCore Security Group
- ALB Security Group
- Fargate Security Group
- VPC Endpoint Security Group

**3. VPC Endpoints** (7개):
- 총 6개 엔드포인트 확인
- 각 엔드포인트 available 상태 확인
  - bedrock-agentcore-control
  - bedrock-agentcore
  - ecr.api
  - ecr.dkr
  - logs
  - s3 (Gateway)

**4. Application Load Balancer** (3개):
- ALB State: active
- Target Group Health Check 활성화
- Sticky Sessions 활성화

**5. IAM Roles** (2개):
- Task Execution Role 존재 확인
- Task Role 존재 확인

### 4.3 검증 성공 출력

모든 검증이 통과하면:

```bash
============================================
Verification Summary
============================================

Total Checks:  15
Passed:        15

============================================
✓ All checks passed!
============================================

Next Steps:
  1. Proceed to Phase 2: (Phase 1 완료 후 진행)
```

### 4.4 .env 파일 확인

생성된 리소스 ID 확인:

```bash
cat .env
```

**예상 내용**:
```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012

# VPC Configuration
VPC_ID=vpc-xxxxxxxxxxxxx
PRIVATE_SUBNET_ID=subnet-xxxxxxxxxxxxx
PUBLIC_SUBNET_ID=subnet-xxxxxxxxxxxxx
SG_AGENTCORE_ID=sg-xxxxxxxxxxxxx
SG_ALB_ID=sg-xxxxxxxxxxxxx
SG_FARGATE_ID=sg-xxxxxxxxxxxxx
SG_VPCE_ID=sg-xxxxxxxxxxxxx
AVAILABILITY_ZONE=us-east-1a

# ALB Configuration
ALB_ARN=arn:aws:elasticloadbalancing:...
ALB_DNS=deep-insight-alb-prod-xxxxx.us-east-1.elb.amazonaws.com
ALB_TARGET_GROUP_ARN=arn:aws:elasticloadbalancing:...

# IAM Roles
TASK_EXECUTION_ROLE_ARN=arn:aws:iam::123456789012:role/...
TASK_ROLE_ARN=arn:aws:iam::123456789012:role/...
```

---

## 5. Phase 2 배포 (Fargate Runtime)

### 5.1 Docker 설치 확인

Phase 2는 Docker를 사용하여 Fargate 이미지를 빌드합니다.

```bash
# Docker 설치 확인
docker --version
```

**예상 출력**:
```
Docker version 24.0.0, build ...
```

**Docker가 설치되지 않은 경우**:

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install docker.io -y
sudo systemctl start docker
sudo systemctl enable docker

# 현재 사용자를 docker 그룹에 추가
sudo usermod -aG docker $USER
newgrp docker

# 설치 확인
docker --version
```

### 5.2 fargate-runtime 디렉토리 확인

```bash
# 프로젝트 루트에서 fargate-runtime 디렉토리 확인
ls -la ../fargate-runtime/

# 필수 파일 확인
ls -la ../fargate-runtime/Dockerfile
ls -la ../fargate-runtime/dynamic_executor_v2.py
```

**예상 출력**:
```
-rw-r--r-- 1 user group 1.5K Dockerfile
-rw-r--r-- 1 user group  31K dynamic_executor_v2.py
-rw-r--r-- 1 user group 872  requirements.txt
```

### 5.3 Phase 2 배포 스크립트 실행

**단일 스크립트로 전체 자동화**:

```bash
# Phase 2 배포 (10-15분)
./scripts/phase2/deploy.sh prod
```

### 5.4 배포 과정 설명 (Three-Stage 자동화)

스크립트가 자동으로 3단계를 실행합니다:

**사전 확인** (1분)
```
Checking prerequisites...
✓ Phase 1 .env file loaded
✓ AWS CLI configured
✓ Docker installed
✓ CloudFormation template validated
✓ fargate-runtime directory found
```

**STAGE 1: ECR Repository 생성** (1-2분)
```
============================================
STAGE 1: Creating ECR Repository
============================================

Deploying CloudFormation stack (DeployECS=false)...
✓ ECR Repository created via CloudFormation
✓ DeletionPolicy: Retain (데이터 보호)

ECR Repository URI: 123456789012.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod
```

**STAGE 2: Docker 빌드 및 푸시** (5-10분)
```
============================================
STAGE 2: Building & Pushing Docker Image
============================================

Building Docker image...
Image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod:v20251102-083527
This may take 5-10 minutes...

Step 1/11 : FROM python:3.12-slim
Step 2/11 : WORKDIR /app
Step 3/11 : RUN apt-get update && apt-get install -y fonts-nanum...
Step 4/11 : RUN fc-cache -f -v
Step 5/11 : COPY requirements.txt .
Step 6/11 : RUN pip install --no-cache-dir -r requirements.txt
Step 7/11 : COPY dynamic_executor_v2.py .
Step 8/11 : CMD ["python", "-u", "dynamic_executor_v2.py"]
Successfully built 1234567890ab
✓ Docker image built successfully

Logging in to ECR...
✓ Logged in to ECR

Pushing Docker images to ECR...
  - v20251102-083527
  - latest
✓ Docker images pushed successfully
```

**STAGE 3: Full Stack 배포** (2-3분)
```
============================================
STAGE 3: Deploying Full Stack (ECS)
============================================

Updating CloudFormation stack (DeployECS=true)...
This will take approximately 2-3 minutes.

Creating resources:
  - ECS Cluster (Container Insights enabled)
  - Task Definition (2 vCPU, 4GB RAM)
  - CloudWatch Log Group (7 days retention)

Waiting for changeset to be created...
Waiting for stack update to complete...
✓ Stack updated successfully
```

### 5.5 배포 완료 메시지

배포가 성공하면:

```bash
============================================
✓ Deployment Successful!
============================================

✓ .env file updated: /path/to/.env

============================================
Deployment Summary
============================================

Docker Image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod:latest
Image Tag: v20251102-083527

# Phase 2 Outputs
ECR_REPOSITORY_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod
ECR_REPOSITORY_NAME=deep-insight-fargate-runtime-prod
ECS_CLUSTER_ARN=arn:aws:ecs:us-east-1:123456789012:cluster/deep-insight-cluster-prod
ECS_CLUSTER_NAME=deep-insight-cluster-prod
TASK_DEFINITION_ARN=arn:aws:ecs:us-east-1:123456789012:task-definition/deep-insight-fargate-task-prod:1
LOG_GROUP_NAME=/ecs/deep-insight-fargate-prod

Next Steps:
  1. Run verification: ./scripts/phase2/verify.sh
  2. Test Fargate task: ./scripts/phase2/test-task.sh
  3. Proceed to Phase 3: AgentCore Runtime deployment
```

---

## 6. Phase 2 검증

### 6.1 자동 검증 스크립트 실행

```bash
./scripts/phase2/verify.sh
```

### 6.2 검증 항목 (총 12개 체크)

**1. ECR Repository** (3개):
- ECR Repository 존재
- Docker 이미지 개수 확인
- Latest 태그 존재

**2. ECS Cluster** (3개):
- ECS Cluster 존재
- Cluster 상태 (ACTIVE)
- Container Insights 활성화

**3. Task Definition** (4개):
- Task Definition 존재
- Task Definition 상태 (ACTIVE)
- Network mode (awsvpc)
- Requires compatibilities (FARGATE)

**4. CloudWatch Logs** (2개):
- Log Group 존재
- Log 보관 기간 (7일)

### 6.3 검증 성공 출력

모든 검증이 통과하면:

```bash
============================================
Phase 2: Fargate Runtime Verification
============================================

1. Checking ECR Repository...
  ECR Repository exists                              ✓ OK
  Docker images in repository                        ✓ OK (2)
  Latest tag exists                                  ✓ OK

2. Checking ECS Cluster...
  ECS Cluster exists                                 ✓ OK
  ECS Cluster status                                 ✓ ACTIVE
  Container Insights                                 ✓ Enabled

3. Checking Task Definition...
  Task Definition exists                             ✓ OK
  Task Definition status                             ✓ ACTIVE
  Network mode                                       ✓ awsvpc
  Requires compatibilities                           ✓ FARGATE

4. Checking CloudWatch Logs...
  CloudWatch Log Group exists                        ✓ OK
  Log retention                                      ✓ 7 days

============================================
Verification Summary
============================================

Total Checks:  12
Passed:        12

✓ All checks passed!

Next Steps:
  1. Test Fargate task: ./scripts/phase2/test-task.sh
  2. Proceed to Phase 3: AgentCore Runtime deployment
```

### 6.4 수동 확인

```bash
# ECR 이미지 확인
aws ecr list-images \
  --repository-name deep-insight-fargate-runtime-prod \
  --region us-east-1

# ECS Cluster 확인
aws ecs describe-clusters \
  --clusters deep-insight-cluster-prod \
  --region us-east-1

# .env 파일에서 Phase 2 outputs 확인
cat .env | grep "# Phase 2"
```

**예상 출력** (.env 파일):
```bash
# Phase 2 Outputs
ECR_REPOSITORY_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod
ECR_REPOSITORY_NAME=deep-insight-fargate-runtime-prod
ECS_CLUSTER_ARN=arn:aws:ecs:us-east-1:123456789012:cluster/deep-insight-cluster-prod
ECS_CLUSTER_NAME=deep-insight-cluster-prod
TASK_DEFINITION_ARN=arn:aws:ecs:us-east-1:123456789012:task-definition/deep-insight-fargate-task-prod:1
LOG_GROUP_NAME=/ecs/deep-insight-fargate-prod
```

---

## 7. 다음 단계

### 7.1 Phase 1-2 완료 체크리스트

**Phase 1**:
- [x] AWS CLI 설정 완료
- [x] Git Repository Clone 완료
- [x] Phase 1 CloudFormation 배포 성공
- [x] Phase 1 검증 통과 (23/23)
- [x] `.env` 파일에 Phase 1 outputs 저장 완료

**Phase 2**:
- [x] Docker 설치 완료
- [x] fargate-runtime 디렉토리 확인
- [x] Phase 2 CloudFormation 배포 성공 (Docker 빌드 + ECR 푸시 포함)
- [x] Phase 2 검증 통과 (12/12)
- [x] `.env` 파일에 Phase 2 outputs 저장 완료

### 7.2 다음 작업

**✅ Phase 1-2 완료!**

**⏳ Phase 3-4는 향후 진행 예정**:

1. **Phase 3: AgentCore Runtime** (예정)
   - `.bedrock_agentcore.yaml` 생성 (VPC 모드)
   - Runtime 배포
   - ENI 생성 확인

2. **Phase 4: Testing** (예정)
   - 네트워크 연결 테스트
   - AgentCore Job 실행
   - PDF 보고서 생성 테스트

**현재 배포 완료 상태**:
- ✅ **Phase 1**: VPC, ALB, Security Groups, VPC Endpoints, IAM Roles
- ✅ **Phase 2**: ECR, Docker Image, ECS Cluster, Task Definition, CloudWatch Logs
  - CloudFormation Three-Stage deployment
  - DeletionPolicy: Retain for ECR (데이터 보호)
- ⏳ **Phase 3-4**: 향후 진행

### 7.3 리소스 정리 (테스트 환경)

테스트 환경에서 비용 절감을 위해 리소스를 정리하려면:

#### 방법 1: Cleanup 스크립트 사용 (권장)

```bash
# Phase 2 정리 (Interactive 모드, 2-5분)
./scripts/phase2/cleanup.sh prod

# Phase 2 정리 (Force 모드, 확인 없이 자동 삭제)
./scripts/phase2/cleanup.sh prod --force

# Phase 1 정리 (Interactive 모드, 10-20분)
./scripts/phase1/cleanup.sh prod

# Phase 1 정리 (Force 모드)
./scripts/phase1/cleanup.sh prod --force
```

**Cleanup 스크립트 특징**:
- ✅ 안전한 Interactive 모드 (단계별 확인)
- ✅ Fast Force 모드 (자동 삭제)
- ✅ 실행 중인 Task 자동 정지
- ✅ CloudFormation-centric 정리 (자동)
- ✅ ECR Repository 선택적 삭제 (DeletionPolicy: Retain)
- ✅ .env 파일 선택적 정리

**Phase 2 정리 (2-10분)**:
- 실행 중인 ECS Task 자동 정지 (30초)
- **CloudFormation Stack 자동 삭제** (2-5분):
  - ECS Cluster
  - Task Definitions (모든 버전)
  - CloudWatch Log Group
- **ECR Repository 선택적 삭제** (10초):
  - DeletionPolicy: Retain으로 보호됨
  - Interactive 모드: 사용자가 y/N 선택
  - Force 모드: 자동 삭제
  - Docker 이미지 포함 삭제
- .env Phase 2 섹션 (선택 사항)

**Phase 1 정리 (10-20분)**:
- VPC Endpoints (5-10분)
- NAT Gateway (2-3분)
- ALB, Security Groups, Subnets
- IAM Roles
- S3 Bucket (선택 사항)
- .env 파일 (선택 사항)

#### 방법 2: 수동 CloudFormation 삭제

```bash
# Phase 2 스택 삭제 (ECS Cluster, Task Definitions, Log Group만 삭제됨)
aws cloudformation delete-stack \
  --stack-name deep-insight-fargate-prod \
  --region us-east-1

# 삭제 완료 대기 (2-5분)
aws cloudformation wait stack-delete-complete \
  --stack-name deep-insight-fargate-prod \
  --region us-east-1

# ECR Repository 삭제 (선택 사항, DeletionPolicy: Retain으로 보호됨)
aws ecr delete-repository \
  --repository-name deep-insight-fargate-runtime-prod \
  --region us-east-1 \
  --force

# Phase 1 스택 삭제
aws cloudformation delete-stack \
  --stack-name deep-insight-infrastructure-prod \
  --region us-east-1

# 삭제 완료 대기 (10-20분)
aws cloudformation wait stack-delete-complete \
  --stack-name deep-insight-infrastructure-prod \
  --region us-east-1

# .env 파일 삭제
rm .env
```

**⚠️ 주의사항**:
- **Phase 2 먼저 삭제**: Phase 1은 Phase 2의 의존성이므로 순서 중요
- **ECR Repository는 DeletionPolicy: Retain으로 보호됨**:
  - CloudFormation 스택 삭제 시 ECR은 자동 삭제되지 않음
  - Docker 이미지 데이터 보호를 위한 안전 장치
  - 삭제를 원하면 수동 삭제 필요
- 수동 삭제 시 실행 중인 ECS Task가 있으면 삭제 실패 가능
- cleanup 스크립트는 모든 의존성을 자동으로 처리

---

## 📊 요약

### 전체 프로세스

```
1. 사전 준비 (5분)
   └─ AWS CLI 설정 + IAM 권한 확인

2. Git Clone (2분)
   └─ Repository 다운로드 + 파일 확인

3. Phase 1 배포 (30-40분)
   └─ CloudFormation 스택 배포

4. Phase 1 검증 (2-3분)
   └─ 23개 항목 자동 검증

5. Phase 2 배포 (10-15분) - Three-Stage
   ├─ STAGE 1: ECR Repository 생성 (CloudFormation, 1-2분)
   ├─ STAGE 2: Docker 빌드 + ECR 푸시 (5-10분)
   └─ STAGE 3: Full Stack 배포 (CloudFormation, 2-3분)

6. Phase 2 검증 (2-3분)
   └─ 12개 항목 자동 검증

총 소요 시간: 50-70분
(CloudFormation Three-Stage 자동화)
```

### 주요 명령어

| 작업 | 명령어 |
|------|--------|
| **Phase 1 배포** | `./scripts/phase1/deploy.sh prod` |
| **Phase 1 검증** | `./scripts/phase1/verify.sh` |
| **Phase 2 배포** | `./scripts/phase2/deploy.sh prod` |
| **Phase 2 검증** | `./scripts/phase2/verify.sh` |
| **리소스 확인** | `cat .env` |
| **Phase 2 정리** | `./scripts/phase2/cleanup.sh prod` |
| **Phase 1 정리** | `./scripts/phase1/cleanup.sh prod` |

---

**작성일**: 2025-11-02
**버전**: 2.0.0 (CloudFormation 기반)
**작성자**: Claude Code
