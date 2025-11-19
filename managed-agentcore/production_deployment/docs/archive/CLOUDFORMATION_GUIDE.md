# 🏗️ CloudFormation 기반 배포 가이드 (Nested Stacks)

> **목표**: CloudFormation Nested Stacks로 모듈화된 인프라를 코드로 관리하고, 각 Phase를 Shell 스크립트로 실행

---

## 🎯 Nested Stacks 아키텍처

이 프로젝트는 **CloudFormation Nested Stacks**를 사용하여 인프라를 모듈화합니다.

### 장점
- ✅ **모듈화**: 각 컴포넌트를 독립적으로 관리
- ✅ **재사용성**: network.yaml을 다른 프로젝트에서 재사용 가능
- ✅ **명확한 의존성**: Parent stack이 dependency 자동 관리
- ✅ **업데이트 격리**: Security Group만 변경 시 해당 nested stack만 업데이트
- ✅ **팀 협업**: 네트워크 팀, 보안 팀이 각자 스택 관리 가능

### 구조
```
phase1-main.yaml (Parent Stack)
├── NetworkStack           # VPC, 4 Subnets, NAT Gateway, Routes
├── SecurityGroupsStack    # 4 Security Groups + 15 Ingress/Egress Rules
├── VPCEndpointsStack      # Bedrock, ECR, Logs, S3 VPC Endpoints
├── ALBStack               # Internal ALB + Target Group + Listener
└── IAMStack               # Task Execution Role + Task Role
```

---

## 📋 전체 구조

```
production_deployment/
│
├── cloudformation/                    # CloudFormation 템플릿
│   ├── phase1-main.yaml               # Parent Stack (Orchestrator)
│   ├── nested/                        # Nested Stacks
│   │   ├── network.yaml               # VPC, Subnets, NAT, Routes
│   │   ├── security-groups.yaml       # Security Groups + Rules
│   │   ├── vpc-endpoints.yaml         # VPC Endpoints
│   │   ├── alb.yaml                   # ALB + Target Group
│   │   └── iam.yaml                   # IAM Roles
│   ├── phase2-fargate.yaml            # ECR Repository, ECS Cluster
│   └── parameters/                    # 환경별 파라미터
│       ├── phase1-prod-params.json
│       └── phase2-prod-params.json
│
├── scripts/                           # 배포 실행 스크립트
│   ├── phase1/
│   │   ├── deploy.sh                  # Phase 1 배포 (S3 업로드 + CloudFormation)
│   │   ├── verify.sh                  # Phase 1 검증 (23개 체크)
│   │   ├── monitor.sh                 # 실시간 배포 모니터링
│   │   └── cleanup.sh                 # Phase 1 리소스 정리
│   │
│   ├── phase2/
│   │   ├── deploy.sh                  # Phase 2 배포 (Docker 빌드 + ECR 푸시 + CloudFormation)
│   │   └── verify.sh                  # Phase 2 검증 (12개 체크)
│   │
│   ├── phase3/
│   │   ├── 1-prepare-source.sh        # Runtime 소스 준비
│   │   ├── 2-create-yaml.sh           # .bedrock_agentcore.yaml 생성
│   │   ├── 3-deploy-runtime.sh        # AgentCore Runtime 배포
│   │   └── 4-verify.sh                # Phase 3 검증
│   │
│   ├── phase4/
│   │   ├── 1-test-simple.sh           # 간단한 Job 테스트
│   │   ├── 2-test-complex.sh          # 복잡한 Job 테스트
│   │   └── 3-download-artifacts.sh    # Artifacts 다운로드
│   │
│   └── cleanup/
│       ├── cleanup-phase-4.sh
│       ├── cleanup-phase-3.sh
│       ├── cleanup-phase-2.sh         # CloudFormation 스택 삭제
│       └── cleanup-phase-1.sh         # CloudFormation 스택 삭제
│
├── fargate-runtime/                   # Fargate Docker 이미지
│   ├── Dockerfile
│   ├── dynamic_executor_v2.py
│   ├── session_fargate_manager.py
│   └── requirements.txt
│
└── .env.template                      # 환경 변수 템플릿
```

---

## 🎯 Phase별 상세 설명

### Phase 1: Infrastructure (Nested CloudFormation Stacks)

**Parent Stack**: `deep-insight-infrastructure-prod`
**Nested Stacks**: 5개 (Network, SecurityGroups, VPCEndpoints, ALB, IAM)
**S3 Bucket**: `deep-insight-cfn-templates-{ACCOUNT_ID}` (자동 생성)

#### 배포 프로세스

1. **S3 Bucket 생성/확인** (자동)
   - Bucket: `deep-insight-cfn-templates-{ACCOUNT_ID}`
   - Versioning 활성화

2. **Nested Templates 업로드** (자동)
   - network.yaml → s3://.../nested/network.yaml
   - security-groups.yaml → s3://.../nested/security-groups.yaml
   - vpc-endpoints.yaml → s3://.../nested/vpc-endpoints.yaml
   - alb.yaml → s3://.../nested/alb.yaml
   - iam.yaml → s3://.../nested/iam.yaml

3. **Parent Stack 배포**
   - Parent stack이 5개 nested stacks를 순차적으로 생성

#### Nested Stacks 상세

**1. NetworkStack** (`nested/network.yaml`):
- VPC (10.0.0.0/16)
- Private Subnet 1 (10.0.1.0/24, us-east-1a)
- Private Subnet 2 (10.0.2.0/24, us-east-1b)
- Public Subnet 1 (10.0.11.0/24, us-east-1a)
- Public Subnet 2 (10.0.12.0/24, us-east-1b)
- Internet Gateway
- NAT Gateway (in Public Subnet 1)
- Route Tables (Private, Public)

**2. SecurityGroupsStack** (`nested/security-groups.yaml`):
- 4 Security Groups (AgentCore, ALB, Fargate, VPC Endpoint)
- 15 Ingress/Egress Rules

**3. VPCEndpointsStack** (`nested/vpc-endpoints.yaml`):
- Bedrock AgentCore Data Plane (Interface)
- Bedrock AgentCore Gateway (Interface)
- ECR API (Interface)
- ECR Docker (Interface)
- CloudWatch Logs (Interface)
- S3 (Gateway)

**4. ALBStack** (`nested/alb.yaml`):
- Internal Application Load Balancer (Multi-AZ)
- Target Group (IP type, port 8080)
- Listener (HTTP, port 80)

**5. IAMStack** (`nested/iam.yaml`):
- Task Execution Role (ECR, CloudWatch Logs 접근)
- Task Role (S3, Bedrock 접근)

**배포 명령**:
```bash
chmod +x scripts/phase1/deploy.sh
./scripts/phase1/deploy.sh prod
```

**소요 시간**: 30-40분 (VPC Endpoints 생성 때문)

**CloudFormation Console 뷰**:
```
Stacks:
├── deep-insight-infrastructure-prod (Parent)
    ├── NetworkStack
    ├── SecurityGroupsStack
    ├── VPCEndpointsStack
    ├── ALBStack
    └── IAMStack
```

**Outputs** (다음 Phase에서 사용):
- VpcId
- PrivateSubnet1Id, PrivateSubnet2Id
- PublicSubnet1Id, PublicSubnet2Id
- AgentCoreSecurityGroupId
- ALBSecurityGroupId
- FargateSecurityGroupId
- VPCEndpointSecurityGroupId
- ApplicationLoadBalancerArn
- ApplicationLoadBalancerDNS
- TargetGroupArn
- TaskExecutionRoleArn
- TaskRoleArn

---

### Phase 2: Fargate Runtime (Three-Stage CloudFormation)

**특징**: CloudFormation이 모든 리소스를 관리하는 완전한 IaC 구현

#### 2.1 CloudFormation 템플릿

**파일**: `cloudformation/phase2-fargate.yaml` (270줄)

**포함 리소스**:
- ✅ ECR Repository (이미지 스캔, AES256 암호화, **DeletionPolicy: Retain**)
- ✅ ECS Cluster (Container Insights 활성화, Conditional)
- ✅ ECS Task Definition (Fargate, 2 vCPU, 4GB RAM, Conditional)
- ✅ CloudWatch Log Group (7일 보관, Conditional)

**핵심 설계**:
```yaml
Parameters:
  DeployECS: 'false' | 'true'  # Stage 제어

Conditions:
  ShouldDeployECS: !Equals [!Ref DeployECS, 'true']

Resources:
  ECRRepository:     # 항상 생성 (DeletionPolicy: Retain)
  ECSCluster:        # Condition: ShouldDeployECS
  TaskDefinition:    # Condition: ShouldDeployECS
  LogGroup:          # Condition: ShouldDeployECS
```

**파라미터**:
- `DeployECS`: false (Stage 1), true (Stage 3)
- Phase 1 outputs (VPC ID, Subnets, Security Groups, IAM Roles)
- Docker Image URI (Stage 3에서 주입)
- Task CPU/Memory 설정

**Outputs**:
- ECRRepositoryUri (항상)
- ECRRepositoryName (항상)
- ECSClusterArn (Conditional)
- ECSClusterName (Conditional)
- TaskDefinitionArn (Conditional)
- LogGroupName (Conditional)

#### 2.2 Three-Stage 배포 스크립트

**파일**: `scripts/phase2/deploy.sh` (450줄)

**실행 워크플로우**:
```bash
./scripts/phase2/deploy.sh prod
```

**Three-Stage 자동 배포**:

**STAGE 1: ECR Repository 생성** (1-2분)
```bash
# CloudFormation으로 ECR만 생성
aws cloudformation deploy \
  --parameter-overrides DeployECS=false
```
- ECR Repository 생성 (CloudFormation)
- DeletionPolicy: Retain 적용
- ECR URI 가져오기

**STAGE 2: Docker 빌드 및 푸시** (5-10분)
```bash
# fargate-runtime 디렉토리에서 Docker 빌드
docker build -t $ECR_URI:$TAG -t $ECR_URI:latest .
docker push (versioned + latest)
```
- Python 3.12 + 한글 폰트 설치
- dynamic_executor_v2.py 포함
- 두 개 태그 생성 및 푸시 (약 700MB)

**STAGE 3: Full Stack 배포** (2-3분)
```bash
# CloudFormation 업데이트로 ECS 생성
aws cloudformation deploy \
  --parameter-overrides DeployECS=true DockerImageUri=$ECR_URI:latest
```
- ECS Cluster, Task Definition, Log Group 생성
- .env 파일에 모든 outputs 저장

**전체 소요 시간**: 10-15분

**장점**:
- ✅ **완전한 IaC**: CloudFormation이 모든 리소스 관리
- ✅ **어느 계정에서나 동일**: ECR 충돌 없음
- ✅ **데이터 보호**: ECR은 DeletionPolicy: Retain
- ✅ **재현 가능**: Git으로 전체 인프라 버전 관리

#### 2.3 검증 스크립트

**파일**: `scripts/phase2/verify.sh` (250줄)

**실행**:
```bash
./scripts/phase2/verify.sh
```

**검증 항목** (총 12개):
1. ECR Repository 존재
2. Docker 이미지 존재 (개수 확인)
3. Latest 태그 존재
4. ECS Cluster 존재
5. ECS Cluster 상태 (ACTIVE)
6. Container Insights 활성화
7. Task Definition 존재
8. Task Definition 상태 (ACTIVE)
9. Network mode (awsvpc)
10. Requires compatibilities (FARGATE)
11. CloudWatch Log Group 존재
12. Log 보관 기간

**성공 출력**:
```
Total Checks:  12
Passed:        12

✓ All checks passed!
```

#### 2.4 Phase 1과의 통합

**Phase 1 의존성**:
- VPC ID
- Private Subnets (2개)
- Fargate Security Group
- Task Execution Role ARN
- Task Role ARN

모든 값은 Phase 1의 `.env` 파일에서 자동으로 로드됩니다.

**전체 Phase 2 소요 시간**: 10-15분

#### 2.5 Cleanup 스크립트 (CloudFormation 중심)

**파일**: `scripts/phase2/cleanup.sh` (340줄)

**실행**:
```bash
# Interactive 모드 (단계별 확인)
./scripts/phase2/cleanup.sh prod

# Force 모드 (자동 삭제, 확인 없음)
./scripts/phase2/cleanup.sh prod --force
```

**자동 정리 단계** (총 6단계, 2-5분):

1. **환경 변수 로드** (.env 파일에서 리소스 이름 가져오기)
2. **실행 중인 ECS Task 정지** (모든 Fargate container 중지, 30초 대기)
3. **CloudFormation 상태 확인** (스택 존재 여부)
4. **CloudFormation Stack 삭제** (2-5분)
   - ECS Cluster 자동 삭제
   - Task Definitions 모든 버전 자동 삭제
   - CloudWatch Log Group 자동 삭제
5. **ECR Repository 삭제** (선택 사항, **DeletionPolicy: Retain으로 보호됨**)
6. **.env 파일 정리** (Phase 2 섹션만 제거, 선택 사항)

**CloudFormation이 자동 삭제**:
- ✅ ECS Cluster (`deep-insight-cluster-prod`)
- ✅ Task Definitions (모든 버전)
- ✅ CloudWatch Log Group (`/ecs/deep-insight-fargate-prod`)

**수동 확인 필요** (보호됨):
- ⚠️ ECR Repository (DeletionPolicy: Retain)
  - Interactive 모드: 삭제 여부 확인
  - Force 모드: 자동 삭제
  - 데이터 보호를 위해 CloudFormation은 자동 삭제하지 않음

**참고**: Phase 1 인프라 (VPC, ALB 등)는 그대로 유지됩니다.

**안전 장치**:
- Interactive 모드: 'yes' 타이핑 필수
- Force 모드: 2초 대기 (Ctrl+C로 취소 가능)
- ECR은 DeletionPolicy: Retain으로 데이터 보호
- 10분 timeout (무한 대기 방지)

**핵심 개선사항**:
- ✅ CloudFormation이 대부분 리소스 자동 삭제
- ✅ ECR은 DeletionPolicy로 데이터 보호
- ✅ 더 간단하고 안전한 cleanup 프로세스

---

### Phase 3: AgentCore Runtime (Scripts Only)

**이유**: Bedrock AgentCore는 CloudFormation 미지원, CLI 사용 필요

**스크립트**:

1. **소스 준비**:
   ```bash
   ./scripts/phase3/1-prepare-source.sh
   ```
   - `agentcore-runtime/` 디렉토리 생성
   - 필수 파일 복사
   - 소요 시간: 1분

2. **YAML 생성**:
   ```bash
   ./scripts/phase3/2-create-yaml.sh
   ```
   - `.bedrock_agentcore.yaml` 생성 (VPC 모드)
   - Phase 1의 Subnet, Security Group 사용
   - 소요 시간: 1분

3. **Runtime 배포**:
   ```bash
   ./scripts/phase3/3-deploy-runtime.sh
   ```
   - `bedrock_agentcore launch` 실행
   - ENI 생성 대기
   - 소요 시간: 10분

4. **검증**:
   ```bash
   ./scripts/phase3/4-verify.sh
   ```
   - Runtime Status 확인
   - ENI 확인
   - 소요 시간: 1분

**전체 Phase 3 소요 시간**: 10-15분

---

### Phase 4: Testing (Scripts Only)

1. **간단한 Job**:
   ```bash
   ./scripts/phase4/1-test-simple.sh
   ```
   - CSV 분석, 총 매출액 계산
   - 소요 시간: 5분

2. **복잡한 Job**:
   ```bash
   ./scripts/phase4/2-test-complex.sh
   ```
   - 카테고리별 분석, PDF 보고서 생성
   - 소요 시간: 15-20분

3. **Artifacts 다운로드**:
   ```bash
   ./scripts/phase4/3-download-artifacts.sh
   ```
   - S3에서 생성된 파일 다운로드
   - 소요 시간: 2분

**전체 Phase 4 소요 시간**: 20-30분

---

## 🚀 Production 계정 배포 순서

### 1. Git Clone 및 환경 설정

```bash
# Repository Clone
git clone https://github.com/hyeonsangjeon/aws-ai-ml-workshop-kr.git
cd aws-ai-ml-workshop-kr/genai/aws-gen-ai-kr/20_applications/08_bedrock_manus/use_cases/05_insight_extractor_strands_sdk_workshop_phase_2/production_deployment

# AWS 설정
aws configure
aws sts get-caller-identity

# 환경 변수 설정
cp .env.template .env
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed -i "s/AWS_ACCOUNT_ID=/AWS_ACCOUNT_ID=$AWS_ACCOUNT_ID/g" .env

# 스크립트 실행 권한
chmod +x scripts/phase*/*.sh scripts/cleanup/*.sh
```

### 2. Phase 1: Infrastructure (30-40분)

```bash
# CloudFormation 스택 배포
./scripts/phase1/deploy.sh

# 배포 진행 상황 모니터링 (별도 터미널)
watch -n 10 aws cloudformation describe-stacks \
  --stack-name deep-insight-infrastructure-prod \
  --query 'Stacks[0].StackStatus'

# 배포 완료 후 검증
./scripts/phase1/verify.sh
```

**완료 시 .env 파일에 자동으로 추가**:
- VPC_ID
- PRIVATE_SUBNET_ID
- PUBLIC_SUBNET_ID
- SG_AGENTCORE_ID, SG_ALB_ID, SG_FARGATE_ID, SG_VPCE_ID
- ALB_ARN, ALB_DNS, ALB_TARGET_GROUP_ARN
- TASK_EXECUTION_ROLE_ARN, TASK_ROLE_ARN

### 3. Phase 2: Fargate Runtime (15-20분)

```bash
# 2.1 CloudFormation 배포 (ECR, ECS Cluster)
./scripts/phase2/1-deploy-infrastructure.sh

# 2.2 Docker 빌드
./scripts/phase2/2-build-docker.sh

# 2.3 ECR 푸시
./scripts/phase2/3-push-to-ecr.sh

# 2.4 Task Definition 등록
./scripts/phase2/4-register-task.sh

# 2.5 테스트 Task 실행
./scripts/phase2/5-run-test-task.sh

# 2.6 검증
./scripts/phase2/6-verify.sh
```

**완료 시 .env 파일에 추가**:
- ECR_REPOSITORY_URI
- ECS_CLUSTER_ARN
- TASK_DEFINITION_ARN

### 4. Phase 3: AgentCore Runtime (10-15분)

```bash
# 3.1 소스 준비
./scripts/phase3/1-prepare-source.sh

# 3.2 YAML 생성
./scripts/phase3/2-create-yaml.sh

# 3.3 Runtime 배포
./scripts/phase3/3-deploy-runtime.sh

# 3.4 검증
./scripts/phase3/4-verify.sh
```

**완료 시 .env 파일에 추가**:
- RUNTIME_ID
- RUNTIME_ARN

### 5. Phase 4: Testing (20-30분)

```bash
# 4.1 간단한 Job
./scripts/phase4/1-test-simple.sh

# 4.2 복잡한 Job
./scripts/phase4/2-test-complex.sh

# 4.3 Artifacts 다운로드
./scripts/phase4/3-download-artifacts.sh
```

**✅ 전체 배포 완료!**

**총 소요 시간**: 75-105분 (약 1.5-2시간)

---

## 🧹 리소스 정리

**⚠️ 역순으로 실행해야 합니다!**

```bash
# Phase 4 정리 (Artifacts)
./scripts/cleanup/cleanup-phase-4.sh

# Phase 3 정리 (AgentCore Runtime)
./scripts/cleanup/cleanup-phase-3.sh

# Phase 2 정리 (CloudFormation Stack 삭제)
./scripts/cleanup/cleanup-phase-2.sh

# Phase 1 정리 (CloudFormation Stack 삭제)
./scripts/cleanup/cleanup-phase-1.sh
```

**Phase 1 정리 소요 시간**: 15-20분 (VPC Endpoints 삭제 대기)

---

## 📊 CloudFormation의 장점

### 1. **재사용 가능**
```bash
# Dev 환경
./scripts/phase1/deploy.sh dev

# Staging 환경
./scripts/phase1/deploy.sh staging

# Production 환경
./scripts/phase1/deploy.sh prod
```

### 2. **롤백 용이**
```bash
# 문제 발생 시 자동 롤백
aws cloudformation delete-stack --stack-name deep-insight-infrastructure-prod
```

### 3. **변경 관리**
```bash
# Change Set으로 변경 사항 미리 확인
aws cloudformation create-change-set \
  --stack-name deep-insight-infrastructure-prod \
  --template-body file://cloudformation/phase1-infrastructure.yaml \
  --change-set-name update-vpc-cidr
```

### 4. **의존성 관리**
- CloudFormation이 자동으로 리소스 생성 순서 결정
- DependsOn으로 명시적 의존성 설정 가능

### 5. **Infrastructure as Code**
- Git으로 버전 관리
- 코드 리뷰 가능
- 히스토리 추적

---

## 🔍 트러블슈팅

### CloudFormation 스택 생성 실패

```bash
# 실패 이유 확인
aws cloudformation describe-stack-events \
  --stack-name deep-insight-infrastructure-prod \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`]' \
  --output table

# 스택 삭제 후 재시도
aws cloudformation delete-stack --stack-name deep-insight-infrastructure-prod
./scripts/phase1/deploy.sh
```

### VPC Endpoints 생성 시간 초과

**원인**: VPC Endpoints는 생성에 10-15분 소요

**해결**:
- 스크립트가 자동으로 대기하도록 설계됨
- `WaitCondition`을 사용하여 모든 Endpoints가 `available`이 될 때까지 대기

### Docker 빌드 실패

```bash
# Docker 데몬 확인
sudo systemctl status docker

# 수동으로 빌드
cd fargate-runtime
docker build -t deep-insight-fargate-runtime:latest .
```

---

## 📝 파일 구조 요약

```
production_deployment/
├── cloudformation/
│   ├── phase1-infrastructure.yaml (약 800-1000줄)
│   ├── phase2-fargate.yaml (약 100줄)
│   └── parameters/
│       ├── phase1-prod-params.json
│       └── phase2-prod-params.json
│
├── scripts/ (총 18개 스크립트)
│   ├── phase1/ (2개)
│   ├── phase2/ (6개)
│   ├── phase3/ (4개)
│   ├── phase4/ (3개)
│   └── cleanup/ (4개)
│
├── fargate-runtime/ (Docker 이미지)
├── .env.template
├── CLOUDFORMATION_GUIDE.md (이 파일)
└── STATUS.md (자동 업데이트)
```

---

**작성일**: 2025-11-01
**버전**: 1.0.0
**다음 단계**: Phase 1 CloudFormation YAML 파일 생성
