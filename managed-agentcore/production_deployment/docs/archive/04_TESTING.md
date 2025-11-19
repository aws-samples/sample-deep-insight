# Phase 4: 테스트 및 검증

> **소요 시간**: 10-15분 (간단한 테스트), 20-30분 (전체 테스트)
> **난이도**: 초급
> **사전 요구사항**: Phase 1, 2, 3 완료

---

## 📋 목차

1. [개요](#개요)
2. [Step 1: 기본 연결 테스트](#step-1-기본-연결-테스트)
3. [Step 2: 간단한 Job 실행](#step-2-간단한-job-실행)
4. [Step 3: 복잡한 Job 실행](#step-3-복잡한-job-실행)
5. [Step 4: 성능 검증](#step-4-성능-검증)
6. [Step 5: 프로덕션 체크리스트](#step-5-프로덕션-체크리스트)

---

## 🎯 개요

이 단계에서는 배포한 시스템을 테스트하고 프로덕션 준비 상태를 검증합니다.

### 테스트 종류

1. **기본 연결 테스트**: Runtime Health Check
2. **간단한 Job**: 총 매출액 계산 (2-5분)
3. **복잡한 Job**: PDF 보고서 생성 (15-20분)
4. **성능 검증**: 로그, 리소스, 비용 확인

---

## Step 1: 기본 연결 테스트

### 1.1 환경 준비

```bash
# 프로젝트 루트로 이동
cd production_deployment

# 환경 변수 로드
source deployment.env

# AgentCore Runtime 디렉토리로 이동
cd agentcore-runtime

# 필요한 Python 패키지 설치
pip install boto3 python-dotenv

echo "✅ 환경 준비 완료"
```

### 1.2 Runtime 상태 확인

```bash
# Runtime ARN 확인
echo "Runtime ARN: $RUNTIME_ARN"

# Runtime 상태 확인
aws bedrock-agentcore get-agent-runtime \
  --agent-runtime-arn $RUNTIME_ARN \
  --region $AWS_REGION \
  --query '[status,networkConfiguration.networkMode]' \
  --output table
```

**예상 출력**:
```
------------------
|  READY         |
|  VPC           |
------------------
```

### 1.3 VPC 연결 확인

```bash
# ENI 상태 확인
aws ec2 describe-network-interfaces \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkInterfaces[?contains(Description, `bedrock`)].{ID:NetworkInterfaceId,Status:Status,IP:PrivateIpAddress}' \
  --output table
```

**예상 출력**:
```
----------------------------------------------------
|          DescribeNetworkInterfaces               |
+-------------------+-----------+------------------+
|       ID          |  Status   |       IP         |
+-------------------+-----------+------------------+
|  eni-0abc123def  |  in-use   |  10.0.1.45       |
+-------------------+-----------+------------------+
```

### 1.4 체크리스트

- [ ] Runtime 상태: `READY`
- [ ] Network Mode: `VPC`
- [ ] ENI 상태: `in-use` (또는 첫 Job 실행 후 생성됨)
- [ ] VPC, Subnets, Security Groups 올바르게 설정됨

---

## Step 2: 간단한 Job 실행

### 2.1 테스트 데이터 준비

```bash
# CSV 파일 복사 (기존 프로젝트에서)
cp ../../data/Dat-fresh-food-claude.csv ./data/

# 또는 S3에 업로드
aws s3 cp ../../data/Dat-fresh-food-claude.csv \
  s3://$S3_BUCKET_NAME/data/Dat-fresh-food-claude.csv
```

### 2.2 간단한 프롬프트 실행

```bash
# 총 매출액 계산 (가장 빠른 테스트)
python3 invoke_agentcore_job.py \
  "./data/Dat-fresh-food-claude.csv 파일의 총 매출액을 계산해줘. PDF 보고서는 만들지 마."
```

**예상 소요 시간**: 2-5분

### 2.3 실행 모니터링

**새 터미널 1 - Fargate Task 모니터링**:
```bash
# Fargate Task 상태 모니터링
watch -n 10 "aws ecs list-tasks \
  --cluster $ECS_CLUSTER_NAME \
  --desired-status RUNNING \
  --region $AWS_REGION \
  --query 'taskArns[*]' \
  --output table"
```

**새 터미널 2 - CloudWatch Logs**:
```bash
# Fargate Runtime 로그
aws logs tail /ecs/fargate-runtime-$ENVIRONMENT \
  --follow \
  --format short \
  --region $AWS_REGION
```

**새 터미널 3 - AgentCore Runtime 로그 (Observability 활성화 시)**:
```bash
# AgentCore Runtime 로그
aws logs tail /aws/bedrock-agentcore/runtimes/bedrock_manus_runtime_$ENVIRONMENT \
  --follow \
  --format short \
  --region $AWS_REGION
```

### 2.4 실행 결과 확인

**예상 출력**:
```
🚀 AgentCore Runtime Job 시작
📅 시작 시간: 2025-10-20 16:30:00
🎯 Agent ARN: arn:aws:bedrock-agentcore:us-east-1:xxx:runtime/bedrock_manus_runtime_prod-xxx
=========================================================

📤 요청 전송 중...
💬 프롬프트: ./data/Dat-fresh-food-claude.csv 파일의 총 매출액을 계산해줘...

📥 스트리밍 응답 수신 시작...

Event: {
  "type": "agent_execution",
  "agent": "coder",
  "status": "running"
}
...
Event: {
  "type": "agent_execution",
  "agent": "validator",
  "status": "completed"
}
...
Event: {
  "type": "final_result",
  "result": {
    "total_sales": 157685452,
    "calculations_verified": true
  }
}

✅ AgentCore Runtime Job 완료
⏱️  총 소요 시간: 183.45초 (3.06분)
```

### 2.5 S3 Artifacts 확인

```bash
# S3에 업로드된 결과 확인
aws s3 ls s3://$S3_BUCKET_NAME/ --recursive | tail -20

# 최신 세션 디렉토리 확인
LATEST_SESSION=$(aws s3 ls s3://$S3_BUCKET_NAME/ | tail -1 | awk '{print $2}')
echo "Latest Session: $LATEST_SESSION"

aws s3 ls s3://$S3_BUCKET_NAME/$LATEST_SESSION
```

**예상 파일**:
- `calculation_metadata.json`
- `citations.json`
- 실행 로그 (execution_*.txt)

### 2.6 체크리스트

- [ ] Job 실행 성공
- [ ] 총 매출액: 157,685,452원 (정확한 값)
- [ ] Fargate Task 생성 및 정상 종료
- [ ] S3에 Artifacts 업로드됨
- [ ] CloudWatch Logs 수집됨

---

## Step 3: 복잡한 Job 실행 (선택 사항)

### 3.1 전체 기능 테스트

```bash
# PDF 보고서 생성 포함 (가장 복잡한 테스트)
python3 invoke_agentcore_job.py \
  "./data/Dat-fresh-food-claude.csv 파일을 분석해서 총 매출액을 계산하고, 카테고리별 매출 비중도 함께 보여줘. 그리고 PDF로 보고서 생성해줘."
```

**예상 소요 시간**: 15-20분

### 3.2 Multi-Agent Workflow 확인

이 테스트는 다음 Agent들을 순차적으로 실행합니다:

1. **Coder Agent** (5-8분):
   - CSV 파일 분석
   - 총 매출액 계산
   - 카테고리별 분석
   - 차트 생성

2. **Validator Agent** (2-3분):
   - 계산 검증
   - Citations 생성
   - 검증 결과 저장

3. **Reporter Agent** (5-8분):
   - PDF 보고서 생성
   - 차트 포함
   - Citations 포함
   - 최종 보고서 업로드

### 3.3 생성된 Artifacts 다운로드

```bash
# 최신 세션 ID 가져오기
LATEST_SESSION=$(aws s3 ls s3://$S3_BUCKET_NAME/ | tail -1 | awk '{print $2}' | tr -d '/')

# 모든 Artifacts 다운로드
mkdir -p test_results/$LATEST_SESSION
aws s3 sync s3://$S3_BUCKET_NAME/$LATEST_SESSION/ \
  ./test_results/$LATEST_SESSION/

echo "✅ Artifacts 다운로드 완료: ./test_results/$LATEST_SESSION/"

# 다운로드된 파일 확인
ls -lh ./test_results/$LATEST_SESSION/
```

**예상 파일**:
- `final_report.pdf` - 최종 PDF 보고서
- `final_report_with_citations.pdf` - Citations 포함 PDF
- `citations.json` - 인용 데이터
- `calculation_metadata.json` - 계산 메타데이터
- `*.png` - 생성된 차트들
- `execution_*.txt` - 실행 로그

### 3.4 PDF 보고서 확인

```bash
# PDF 파일 열기 (Mac)
open ./test_results/$LATEST_SESSION/final_report_with_citations.pdf

# 또는 Linux
xdg-open ./test_results/$LATEST_SESSION/final_report_with_citations.pdf
```

**확인 사항**:
- [ ] 한글 폰트 정상 렌더링
- [ ] 차트 5-7개 포함
- [ ] Citations 섹션 존재
- [ ] 총 매출액: 157,685,452원
- [ ] 카테고리별 매출 비중 차트

---

## Step 4: 성능 검증

### 4.1 실행 시간 분석

```bash
# CloudWatch Logs Insights 쿼리 (AgentCore Runtime)
aws logs start-query \
  --log-group-name "/aws/bedrock-agentcore/runtimes/bedrock_manus_runtime_$ENVIRONMENT" \
  --start-time $(date -u -d '1 hour ago' +%s) \
  --end-time $(date -u +%s) \
  --query-string '
    fields @timestamp, @message
    | filter @message like /Agent execution/
    | sort @timestamp asc
    | limit 100
  '
```

**확인 사항**:
- Coder → Validator → Reporter 순서 확인
- 각 Agent 실행 시간 확인
- 에러 없이 완료되었는지 확인

### 4.2 리소스 사용량 확인

```bash
# Fargate Task CPU/Memory 사용량
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=fargate-runtime-$ENVIRONMENT \
    Name=ClusterName,Value=$ECS_CLUSTER_NAME \
  --start-time $(date -u -d '1 hour ago' --iso-8601=seconds) \
  --end-time $(date -u --iso-8601=seconds) \
  --period 300 \
  --statistics Average,Maximum \
  --output table

# Memory 사용량
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name MemoryUtilization \
  --dimensions Name=ServiceName,Value=fargate-runtime-$ENVIRONMENT \
    Name=ClusterName,Value=$ECS_CLUSTER_NAME \
  --start-time $(date -u -d '1 hour ago' --iso-8601=seconds) \
  --end-time $(date -u --iso-8601=seconds) \
  --period 300 \
  --statistics Average,Maximum \
  --output table
```

**확인 사항**:
- CPU 사용률: 50-80% (적정)
- Memory 사용률: 60-80% (적정)
- 리소스 부족 시 Task Definition 업데이트 필요

### 4.3 비용 추정

```bash
# 이번 달 비용 확인
aws ce get-cost-and-usage \
  --time-period Start=$(date -u -d 'this month' +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --filter file://<(cat <<EOF
{
  "Tags": {
    "Key": "Project",
    "Values": ["deep-insight"]
  }
}
EOF
) \
  --query 'ResultsByTime[0].Total.BlendedCost' \
  --output table
```

**예상 월간 비용** (us-east-1):
- NAT Gateway: ~$32.40
- VPC Endpoints (5개): ~$36.00
- ALB: ~$16.00
- Fargate (10시간/월): ~$4.00
- S3: ~$0.50
- CloudWatch Logs: ~$2.50
- **합계**: ~$91.40/월

---

## Step 5: 프로덕션 체크리스트

### 5.1 기능 검증

- [ ] **기본 연결**: Runtime Health Check 통과
- [ ] **간단한 Job**: 총 매출액 계산 성공
- [ ] **복잡한 Job**: PDF 보고서 생성 성공
- [ ] **Multi-Agent Workflow**: Coder → Validator → Reporter 순차 실행
- [ ] **S3 Integration**: Artifacts 업로드 성공
- [ ] **한글 지원**: PDF 한글 폰트 정상 렌더링

### 5.2 인프라 검증

- [ ] **VPC**: VPC 및 Subnets 생성 확인
- [ ] **VPC Endpoints**: 모두 `available` 상태
- [ ] **Security Groups**: 올바른 Inbound/Outbound 규칙
- [ ] **NAT Gateway**: `available` 상태
- [ ] **ALB**: `active` 상태, Health Check 통과
- [ ] **ECS Cluster**: 생성 확인
- [ ] **Fargate Task**: 실행 및 종료 정상
- [ ] **IAM Roles**: Task Role, Execution Role 생성 확인

### 5.3 Runtime 검증

- [ ] **Runtime 상태**: `READY`
- [ ] **Network Mode**: `VPC`
- [ ] **ENI**: 생성 및 `in-use` 상태
- [ ] **Observability**: CloudWatch Logs 수집 (활성화 시)
- [ ] **ECR Image**: 최신 이미지 푸시됨

### 5.4 성능 검증

- [ ] **실행 시간**: 간단한 Job 2-5분, 복잡한 Job 15-20분
- [ ] **CPU 사용률**: 50-80% (적정 범위)
- [ ] **Memory 사용률**: 60-80% (적정 범위)
- [ ] **에러율**: 0% (에러 없이 완료)
- [ ] **S3 업로드**: 모든 Artifacts 업로드 성공

### 5.5 보안 검증

- [ ] **Private Subnets**: Fargate는 Private Subnet에서 실행
- [ ] **Internal ALB**: 외부 인터넷에서 직접 접근 불가
- [ ] **VPC Endpoints**: 인터넷 경유 없이 AWS 서비스 접근
- [ ] **Security Groups**: 최소 권한 원칙 적용
- [ ] **IAM Policies**: 필요한 권한만 부여

---

## ✅ 프로덕션 배포 완료!

모든 체크리스트가 완료되었다면 프로덕션 배포가 성공적으로 완료되었습니다! 🎉

### 최종 상태 요약

```bash
# 전체 리소스 요약 출력
cat << EOF

╔═══════════════════════════════════════════════════════════╗
║       Bedrock Manus Production Deployment Summary         ║
╚═══════════════════════════════════════════════════════════╝

환경 정보:
  Environment:        $ENVIRONMENT
  AWS Region:         $AWS_REGION
  AWS Account:        $AWS_ACCOUNT_ID

네트워크:
  VPC ID:             $VPC_ID
  Private Subnets:    $PRIVATE_SUBNET_IDS
  Security Groups:    $AGENTCORE_SECURITY_GROUP (AgentCore)
                      $ALB_SECURITY_GROUP (ALB)
                      $FARGATE_SECURITY_GROUP (Fargate)

컴퓨팅:
  ECS Cluster:        $ECS_CLUSTER_NAME
  ECR Repository:     $ECR_URI
  Task Definition:    $TASK_DEF_ARN

AgentCore Runtime:
  Runtime ARN:        $RUNTIME_ARN
  Network Mode:       VPC
  Status:             READY ✅

Storage:
  S3 Bucket:          $S3_BUCKET_NAME

Monitoring:
  Fargate Logs:       /ecs/fargate-runtime-$ENVIRONMENT
  AgentCore Logs:     /aws/bedrock-agentcore/runtimes/...

═══════════════════════════════════════════════════════════

다음 단계:
  1. Git에 코드 푸시
  2. 프로덕션 계정에서 동일한 과정 반복
  3. CI/CD 파이프라인 구축 (선택 사항)
  4. 모니터링 대시보드 설정 (선택 사항)

═══════════════════════════════════════════════════════════
EOF
```

### STATUS.md 최종 업데이트

```bash
# production_deployment/STATUS.md 파일을 편집하여:
# - Phase 4 체크박스를 완료로 표시
# - 전체 진행률을 100%로 업데이트
# - 생성된 리소스 정보 기록
```

---

## 🔄 다음 단계 (선택 사항)

### 1. Git에 코드 푸시

```bash
# 프로젝트 루트로 이동
cd ../..

# Git add
git add production_deployment/
git add CLAUDE.md

# Commit
git commit -m "Add production deployment guide and infrastructure

- CloudFormation templates for VPC, ALB, Fargate, VPC Endpoints
- Step-by-step deployment guide (Phase 1-4)
- AgentCore Runtime configuration for VPC mode
- Testing and validation scripts
- Production-ready infrastructure (VPC Private mode)
"

# Push
git push origin master
```

### 2. 프로덕션 계정 배포

프로덕션 AWS 계정에서 동일한 가이드를 따라 배포:

```bash
# 1. 프로덕션 계정으로 AWS CLI 프로파일 전환
export AWS_PROFILE=production

# 2. Phase 1부터 순차적으로 진행
cd production_deployment
# ... (STEP_BY_STEP_GUIDE.md부터 시작)
```

### 3. CI/CD 파이프라인 (고급)

GitHub Actions 또는 AWS CodePipeline으로 자동 배포:

- Docker 이미지 자동 빌드
- CloudFormation 스택 자동 업데이트
- 자동 테스트 실행
- Blue/Green 배포

### 4. 모니터링 대시보드

CloudWatch Dashboard로 운영 메트릭 시각화:

- Fargate CPU/Memory 사용률
- ALB 요청 수, 에러율
- AgentCore Job 실행 시간
- 비용 추적

---

## 🆘 지원 및 문서

- **가이드 문서**: `production_deployment/docs/`
- **CloudFormation 템플릿**: `production_deployment/cloudformation/`
- **배포 스크립트**: `production_deployment/scripts/`
- **진행 상황**: `production_deployment/STATUS.md`

**문제 발생 시**:
1. 각 Phase의 트러블슈팅 섹션 참조
2. CloudWatch Logs 확인
3. AWS Support 케이스 생성

---

**축하합니다! 프로덕션 배포가 완료되었습니다!** 🎉🚀

---

**작성일**: 2025-10-20
**마지막 업데이트**: 2025-10-20
