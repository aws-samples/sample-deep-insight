# Phase 2: Fargate Runtime 배포 (CloudFormation + Docker)

> **소요 시간**: 10-15분
> **난이도**: 중급
> **사전 요구사항**: Phase 1 완료 + Docker 설치

---

## 📋 목차

1. [개요](#개요)
2. [배포 방법](#배포-방법)
3. [검증](#검증)
4. [트러블슈팅](#트러블슈팅)

---

## 🎯 개요

Phase 2에서는 Python 코드를 실행하는 Fargate Runtime을 Docker 컨테이너로 패키징하고, CloudFormation으로 ECS 인프라를 배포합니다.

### 자동화 특징

**단일 스크립트로 전체 프로세스 자동화**:
- ✅ Docker 이미지 빌드
- ✅ ECR 푸시
- ✅ CloudFormation 배포
- ✅ 환경 변수 자동 설정

### 생성 리소스

**CloudFormation** (`cloudformation/phase2-fargate.yaml`):
- ECR Repository (이미지 스캔, AES256 암호화, lifecycle policy)
- ECS Cluster (Container Insights 활성화)
- ECS Task Definition (Fargate, 2 vCPU, 4GB RAM)
- CloudWatch Log Group (7일 보관)

**Docker 이미지**:
- Base: Python 3.12-slim
- 한글 폰트: fonts-nanum
- 필수 패키지: pandas, matplotlib, boto3, flask 등
- Application: dynamic_executor_v2.py

---

## 🚀 배포 방법

### 사전 요구사항

```bash
# Docker 설치 확인
docker --version

# Phase 1 완료 확인
ls -la .env

# fargate-runtime 디렉토리 확인
ls -la ../fargate-runtime/
```

### 단일 명령어 배포 (Three-Stage 자동화)

```bash
# Phase 2 배포 (Three-Stage 자동 실행)
./scripts/phase2/deploy.sh prod
```

**소요 시간**: 10-15분 (ECR 생성 → Docker 빌드/푸시 → ECS 배포)

### Three-Stage 자동 실행

스크립트가 자동으로 3단계를 실행합니다:

#### 사전 확인 (1분)
- Phase 1 .env 파일 로드
- AWS CLI, Docker 설치 확인
- fargate-runtime 디렉토리 확인
- CloudFormation 템플릿 검증

#### STAGE 1: ECR Repository 생성 (1-2분)

**CloudFormation 배포 (DeployECS=false)**:
```bash
aws cloudformation deploy \
  --parameter-overrides DeployECS=false \
  ...
```

**실행 내용**:
- ECR Repository: `deep-insight-fargate-runtime-prod` 생성
- 이미지 스캔 활성화
- AES256 암호화
- DeletionPolicy: Retain (데이터 보호)
- ECR URI 가져오기

**출력 예시**:
```
============================================
STAGE 1: Creating ECR Repository
============================================
✓ ECR Repository created via CloudFormation

ECR Repository URI: 738490718699.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod
```

#### STAGE 2: Docker 빌드 및 푸시 (5-10분)

**Docker 이미지 빌드**:
- Python 3.12 + 한글 폰트 설치
- 필수 Python 패키지 설치
- dynamic_executor_v2.py 복사
- 두 개 태그 생성: `v20251102-083527`, `latest`

**빌드 로그 예시**:
```
============================================
STAGE 2: Building & Pushing Docker Image
============================================

Building Docker image...
Image: 738490718699.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod:v20251102-083527
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
  - 738490718699.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod:v20251102-083527
  - 738490718699.dkr.ecr.us-east-1.amazonaws.com/deep-insight-fargate-runtime-prod:latest
✓ Docker images pushed successfully
```

#### STAGE 3: Full Stack 배포 (2-3분)

**CloudFormation 배포 (DeployECS=true)**:
```bash
aws cloudformation deploy \
  --parameter-overrides \
    DeployECS=true \
    DockerImageUri=$ECR_URI:latest \
  ...
```

**실행 내용**:
- ECS Cluster 생성 (Container Insights 활성화)
- Task Definition 등록 (2 vCPU, 4GB RAM)
- CloudWatch Log Group 생성 (7일 보관)
- .env 파일에 모든 outputs 저장

**배포 완료 메시지**:
```
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

## ✅ 검증

### 자동 검증

```bash
./scripts/phase2/verify.sh
```

**검증 항목** (총 12개):

1. **ECR Repository**
   - Repository 존재
   - Docker 이미지 개수
   - Latest 태그 존재

2. **ECS Cluster**
   - Cluster 존재
   - Cluster 상태 (ACTIVE)
   - Container Insights 활성화

3. **Task Definition**
   - Task Definition 존재
   - Task Definition 상태 (ACTIVE)
   - Network mode (awsvpc)
   - Requires compatibilities (FARGATE)

4. **CloudWatch Logs**
   - Log Group 존재
   - Log 보관 기간 (7일)

**성공 출력**:
```
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
```

### 수동 검증

```bash
# ECR 이미지 확인
aws ecr list-images \
  --repository-name deep-insight-fargate-runtime-prod \
  --region us-east-1

# ECS Cluster 확인
aws ecs describe-clusters \
  --clusters deep-insight-cluster-prod \
  --region us-east-1

# Task Definition 확인
aws ecs describe-task-definition \
  --task-definition deep-insight-fargate-task-prod \
  --region us-east-1

# .env 파일 확인
cat .env | grep "# Phase 2"
```

---

## 🛠️ 트러블슈팅

### 문제 1: Docker 빌드 실패

**증상**:
```
Error: Docker build failed
```

**해결**:
```bash
# Docker 서비스 확인
sudo systemctl status docker

# Docker 서비스 시작
sudo systemctl start docker

# 권한 확인
sudo usermod -aG docker $USER
newgrp docker
```

### 문제 2: ECR 로그인 실패

**증상**:
```
Error: ECR login failed
```

**해결**:
```bash
# AWS CLI 자격증명 확인
aws sts get-caller-identity

# ECR 권한 확인 (필요 권한)
# - ecr:GetAuthorizationToken
# - ecr:BatchCheckLayerAvailability
# - ecr:PutImage
# - ecr:InitiateLayerUpload
# - ecr:UploadLayerPart
# - ecr:CompleteLayerUpload

# 수동 ECR 로그인 테스트
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789012.dkr.ecr.us-east-1.amazonaws.com
```

### 문제 3: CloudFormation 배포 실패

**증상**:
```
Error: CloudFormation deployment failed
```

**해결**:
```bash
# CloudFormation 스택 이벤트 확인
aws cloudformation describe-stack-events \
  --stack-name deep-insight-fargate-prod \
  --region us-east-1 \
  --max-items 20

# 일반적인 원인:
# 1. Phase 1 .env 파일 없음 → Phase 1 먼저 배포
# 2. IAM 권한 부족 → CloudFormation, ECS 권한 확인
# 3. 리소스 제한 초과 → Service Quota 확인
```

### 문제 4: 이미지 크기가 너무 큼

**증상**:
```
Docker image size: 1.2 GB
```

**해결**:
이미지 크기는 정상입니다 (700-800MB 예상):
- Python 3.12-slim: ~150MB
- 한글 폰트 + texlive: ~400MB
- Python 패키지: ~150MB

필요 시 최적화:
```dockerfile
# 불필요한 패키지 제거
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# Multi-stage build 사용 (고급)
```

### 문제 5: Phase 1 .env 파일을 찾을 수 없음

**증상**:
```
Error: Phase 1 .env file not found
```

**해결**:
```bash
# Phase 1이 완료되었는지 확인
./scripts/phase1/verify.sh

# Phase 1 배포
./scripts/phase1/deploy.sh prod

# .env 파일 확인
cat .env
```

---

## 🗑️ 리소스 정리 (Cleanup)

### Cleanup 스크립트 실행

사용하지 않을 때는 cleanup 스크립트로 Phase 2 리소스를 정리하여 비용을 절감할 수 있습니다.

#### Interactive 모드 (권장)

```bash
./scripts/phase2/cleanup.sh prod
```

**실행 과정**:
1. 'yes' 타이핑 확인
2. 실행 중인 ECS Task 정지 확인
3. CloudFormation 스택 삭제 진행
4. Task Definition 삭제 여부 선택
5. .env Phase 2 섹션 삭제 여부 선택

#### Force 모드 (자동 삭제)

```bash
./scripts/phase2/cleanup.sh prod --force
```

**주의**: 확인 없이 모든 리소스를 자동 삭제합니다 (2초 대기 후 시작)

### Cleanup 단계 (총 6단계, 2-10분)

1. **환경 변수 로드** (1초)
   - .env 파일에서 리소스 이름 가져오기

2. **실행 중인 ECS Task 정지** (30초)
   - 모든 Fargate container 중지
   - 30초 대기

3. **CloudFormation 상태 확인** (5초)
   - 스택 존재 여부 확인

4. **CloudFormation Stack 삭제** (2-5분) ⭐
   - **자동 삭제**: ECS Cluster, Task Definitions (모든 버전), CloudWatch Log Group
   - **보호됨**: ECR Repository (DeletionPolicy: Retain)
   - 실시간 진행 상황 표시
   - Timeout: 10분

5. **ECR Repository 정리** (선택 사항, 10초)
   - **CloudFormation이 보호**: DeletionPolicy: Retain으로 설정됨
   - 사용자가 수동으로 삭제 여부 선택 (Interactive 모드)
   - Force 모드: 자동 삭제
   - 모든 Docker 이미지 포함 삭제 (force delete)

6. **.env 파일 정리** (선택 사항, 1초)
   - Phase 2 섹션만 제거
   - Phase 1 섹션은 유지

### 정리되는 리소스

| 리소스 | 이름 | 삭제 방법 |
|--------|------|-----------|
| **CloudFormation이 관리** | | |
| ECS Cluster | deep-insight-cluster-prod | ✅ 자동 (CloudFormation) |
| Task Definitions | 모든 버전 | ✅ 자동 (CloudFormation) |
| CloudWatch Log Group | /ecs/deep-insight-fargate-prod | ✅ 자동 (CloudFormation) |
| CloudFormation Stack | deep-insight-fargate-prod | ✅ 자동 |
| **DeletionPolicy: Retain** | | |
| ECR Repository | deep-insight-fargate-runtime-prod | ⚠️ 선택 사항 (수동) |
| Docker 이미지 | 모든 태그 | ⚠️ ECR과 함께 삭제 가능 |

### Cleanup 성공 예시

```
============================================
✓ Phase 2 Cleanup Complete!
============================================

Cleaned up:
  ✓ CloudFormation stack: deep-insight-fargate-prod
    - ECS Cluster
    - Task Definitions (all versions)
    - CloudWatch Log Group
  ✓ ECR repository (if you selected 'y')
  ✓ .env Phase 2 section removed (if you selected 'y')

Note: ECR has DeletionPolicy: Retain for data protection
Note: Phase 1 infrastructure (VPC, ALB, etc.) remains intact

You can now redeploy Phase 2:
  ./scripts/phase2/deploy.sh prod
```

### 주의사항

⚠️ **중요 - DeletionPolicy: Retain**:
- **ECR Repository는 CloudFormation이 보호**합니다
- Stack 삭제 시 ECR은 자동 삭제되지 않음
- Docker 이미지 데이터 보호를 위한 안전 장치
- 삭제를 원하면 cleanup 스크립트에서 'y' 선택 또는 수동 삭제

⚠️ **Phase 1 인프라**:
- Phase 1 (VPC, ALB 등)는 그대로 유지됩니다
- Phase 2만 정리하므로 Phase 1 비용 (~$84/월)은 계속 발생
- 전체 정리를 원하면 Phase 1도 cleanup 필요:
  ```bash
  ./scripts/phase1/cleanup.sh prod
  ```

⚠️ **재배포 시**:
- .env 파일의 Phase 1 정보만 있으면 Phase 2 재배포 가능
- ECR 이미지를 유지했다면: 재빌드 불필요 (1-2분)
- ECR 이미지를 삭제했다면: 재빌드 필요 (5-10분)

### 수동 정리 (대안)

cleanup 스크립트를 사용하지 않고 수동으로 정리:

```bash
# 1. CloudFormation 스택 삭제 (ECS Cluster, Task Definitions, Log Group)
aws cloudformation delete-stack \
  --stack-name deep-insight-fargate-prod \
  --region us-east-1

# 삭제 완료 대기 (2-5분)
aws cloudformation wait stack-delete-complete \
  --stack-name deep-insight-fargate-prod \
  --region us-east-1

# 2. ECR Repository 삭제 (선택 사항)
# Note: CloudFormation이 DeletionPolicy: Retain으로 보호함
aws ecr delete-repository \
  --repository-name deep-insight-fargate-runtime-prod \
  --region us-east-1 \
  --force
```

---

## 📊 생성된 리소스 요약

| 리소스 | 이름 | 설명 |
|--------|------|------|
| ECR Repository | deep-insight-fargate-runtime-prod | Docker 이미지 저장소 |
| ECS Cluster | deep-insight-cluster-prod | Fargate Task 실행 환경 |
| Task Definition | deep-insight-fargate-task-prod | 2 vCPU, 4GB RAM |
| Log Group | /ecs/deep-insight-fargate-prod | 7일 보관 |

---

## 🎉 Phase 2 완료!

**✅ 완료 체크리스트**:
- [x] ECR Repository 생성
- [x] Docker 이미지 빌드 및 푸시 (2개 태그)
- [x] ECS Cluster 생성 (Container Insights 활성화)
- [x] Task Definition 등록 (ACTIVE)
- [x] CloudWatch Log Group 생성 (7일 보관)
- [x] `.env` 파일에 Phase 2 outputs 추가

**다음 단계**:
- Phase 3: AgentCore Runtime 배포
- Phase 4: 통합 테스트

---

**작성일**: 2025-11-02
**버전**: 2.0.0 (CloudFormation 자동화)
