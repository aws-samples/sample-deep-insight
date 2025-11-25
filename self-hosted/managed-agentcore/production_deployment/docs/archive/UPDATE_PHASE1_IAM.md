# Phase 1 IAM Stack 업데이트 가이드

## 📋 개요

이미 배포된 Phase 1 스택에 **CodeBuild Execution Role**을 추가하는 가이드입니다.

**변경 내용**:
- ✅ 기존 리소스 유지 (삭제 없음)
- ✅ CodeBuild Role 1개 추가
- ✅ Output 1개 추가 (CodeBuildExecutionRoleArn)

**소요 시간**: 2-3분

**리스크**: 거의 없음 (새 리소스 추가만)

---

## 🚀 업데이트 절차

### 방법 1: 자동 스크립트 사용 (권장)

```bash
cd production_deployment
./scripts/phase1/update-iam.sh prod
```

### 방법 2: 수동 업데이트

#### Step 1: 템플릿 S3 업로드

```bash
# 프로덕션 계정 자격증명 설정
aws configure

# 계정 확인
aws sts get-caller-identity

# S3 버킷 확인 (Phase 1 배포 시 사용한 버킷)
TEMPLATE_BUCKET="deep-insight-templates-prod-<YOUR_ACCOUNT_ID>"

# 업데이트된 iam.yaml 업로드
aws s3 cp cloudformation/nested/iam.yaml \
  s3://${TEMPLATE_BUCKET}/nested/iam.yaml

# 확인
aws s3 ls s3://${TEMPLATE_BUCKET}/nested/
```

#### Step 2: IAM Nested Stack 이름 확인

```bash
# Parent Stack에서 IAM Stack 이름 찾기
aws cloudformation describe-stack-resources \
  --stack-name deep-insight-infrastructure-prod \
  --query "StackResources[?LogicalResourceId=='IAMStack'].PhysicalResourceId" \
  --output text

# 예시 출력: deep-insight-infrastructure-prod-IAMStack-ABC123XYZ
```

#### Step 3: IAM Stack 업데이트

```bash
# IAM Stack 이름 (Step 2에서 확인)
IAM_STACK_NAME="deep-insight-infrastructure-prod-IAMStack-ABC123XYZ"

# Stack 업데이트
aws cloudformation update-stack \
  --stack-name ${IAM_STACK_NAME} \
  --template-url https://s3.amazonaws.com/${TEMPLATE_BUCKET}/nested/iam.yaml \
  --parameters \
    ParameterKey=Environment,UsePreviousValue=true \
    ParameterKey=ProjectName,UsePreviousValue=true \
    ParameterKey=S3BucketName,UsePreviousValue=true \
  --capabilities CAPABILITY_NAMED_IAM

# 완료 대기 (2-3분)
aws cloudformation wait stack-update-complete \
  --stack-name ${IAM_STACK_NAME}
```

#### Step 4: 결과 확인

```bash
# Stack 상태 확인
aws cloudformation describe-stacks \
  --stack-name ${IAM_STACK_NAME} \
  --query 'Stacks[0].StackStatus' \
  --output text

# 출력: UPDATE_COMPLETE ✅

# 새로 생성된 Role 확인
aws cloudformation describe-stack-resources \
  --stack-name ${IAM_STACK_NAME} \
  --query "StackResources[?ResourceType=='AWS::IAM::Role'].[LogicalResourceId,PhysicalResourceId]" \
  --output table

# 출력:
# --------------------------------------------------
# | DescribeStackResources                         |
# +-------------------------+----------------------+
# | TaskExecutionRole       | deep-insight-task... |
# | TaskRole                | deep-insight-task... |
# | CodeBuildExecutionRole  | deep-insight-code... | ← 새로 추가됨 ✅
# +-------------------------+----------------------+

# CodeBuild Role ARN 확인
aws cloudformation describe-stacks \
  --stack-name ${IAM_STACK_NAME} \
  --query 'Stacks[0].Outputs[?OutputKey==`CodeBuildExecutionRoleArn`].OutputValue' \
  --output text

# 출력: arn:aws:iam::ACCOUNT:role/deep-insight-codebuild-role-prod
```

---

## 📝 .env 파일 업데이트 (선택 사항)

CodeBuild Role을 Phase 3에서 사용하려면 `.env`에 추가:

```bash
# CodeBuild Role ARN 가져오기
CODEBUILD_ROLE_ARN=$(aws cloudformation describe-stacks \
  --stack-name ${IAM_STACK_NAME} \
  --query 'Stacks[0].Outputs[?OutputKey==`CodeBuildExecutionRoleArn`].OutputValue' \
  --output text)

# .env에 추가
echo "" >> .env
echo "# CodeBuild Execution Role (Phase 1에서 생성)" >> .env
echo "CODEBUILD_EXECUTION_ROLE_ARN=${CODEBUILD_ROLE_ARN}" >> .env

# 확인
cat .env | grep CODEBUILD
```

그런 다음 `create_agentcore_runtime_vpc.py`에서 주석 해제:

```python
# 주석 해제
CODEBUILD_EXECUTION_ROLE_ARN = os.getenv("CODEBUILD_EXECUTION_ROLE_ARN")
if CODEBUILD_EXECUTION_ROLE_ARN:
    print_info(f"Phase 1 CodeBuild Role 사용: {CODEBUILD_EXECUTION_ROLE_ARN}")

response = agentcore_runtime.configure(
    ...
    code_build_execution_role=CODEBUILD_EXECUTION_ROLE_ARN,  # 주석 해제
    ...
)
```

---

## ⚠️ 중요 참고사항

### 현재 방식 (자동 생성)도 완전히 정상입니다!

**CodeBuild Role을 명시적으로 설정하지 않아도**:
- ✅ Toolkit이 자동으로 Role 생성 (첫 실행)
- ✅ 이후 실행 시 자동으로 재사용
- ✅ 모든 권한 자동 설정
- ✅ 추가 작업 불필요

**CloudFormation으로 관리하는 장점**:
- ✅ 완전한 Infrastructure as Code
- ✅ 중앙화된 권한 관리
- ✅ 재현 가능한 배포

**권장사항**:
1. **현재**: 자동 생성 방식 사용 (간편함)
2. **향후**: 두 번째 프로덕션 계정 배포 시 이 업데이트 적용 (완전한 IaC)

---

## 🔄 롤백 방법

만약 문제가 발생하면 이전 버전으로 롤백 가능:

```bash
# 이전 템플릿 버전 확인
aws s3api list-object-versions \
  --bucket ${TEMPLATE_BUCKET} \
  --prefix nested/iam.yaml

# 이전 버전으로 롤백
aws cloudformation update-stack \
  --stack-name ${IAM_STACK_NAME} \
  --template-url https://s3.amazonaws.com/${TEMPLATE_BUCKET}/nested/iam.yaml?versionId=<PREVIOUS_VERSION_ID> \
  --parameters \
    ParameterKey=Environment,UsePreviousValue=true \
    ParameterKey=ProjectName,UsePreviousValue=true \
    ParameterKey=S3BucketName,UsePreviousValue=true \
  --capabilities CAPABILITY_NAMED_IAM
```

---

## 📊 변경 사항 요약

| 항목 | 기존 | 업데이트 후 |
|------|------|-----------|
| **IAM Roles** | 2개 (Task, Execution) | 3개 (+ CodeBuild) ✅ |
| **Outputs** | 2개 | 3개 (+ CodeBuildExecutionRoleArn) ✅ |
| **기존 리소스** | 모두 유지 ✅ | 모두 유지 ✅ |
| **추가 비용** | $0 | $0 (IAM Role은 무료) |

---

**작성일**: 2025-11-04
**버전**: 1.0.0
**상태**: Ready for Production
