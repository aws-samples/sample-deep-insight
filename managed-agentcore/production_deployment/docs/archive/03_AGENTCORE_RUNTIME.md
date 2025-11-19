# Phase 3: AgentCore Runtime 배포

> **소요 시간**: 10-15분
> **난이도**: 중급
> **사전 요구사항**: Phase 1, 2 완료

---

## 📋 목차

1. [개요](#개요)
2. [빠른 시작 (자동 배포)](#빠른-시작-자동-배포)
3. [수동 배포 (단계별)](#수동-배포-단계별)
4. [트러블슈팅](#트러블슈팅)

---

## 🎯 개요

이 단계에서는 Bedrock AgentCore Runtime을 VPC Private 모드로 배포합니다.

### 주요 작업

- ✅ AgentCore Runtime 소스 코드 준비
- ✅ `.bedrock_agentcore.yaml` 설정 파일 생성 (VPC 모드)
- ✅ bedrock_agentcore toolkit으로 Runtime 배포
- ✅ Runtime 상태 및 ENI 확인
- ✅ Runtime ARN 저장

### 배포 방법

**자동 배포** (권장):
- 🚀 단일 스크립트로 전체 프로세스 자동화
- ⏱️ 소요 시간: 10-15분
- 📝 명령어: `./scripts/phase3/deploy.sh prod`

**수동 배포** (학습 목적):
- 📖 단계별 실행으로 이해도 향상
- ⏱️ 소요 시간: 20-25분
- 📝 각 단계를 수동으로 실행

---

## 🚀 빠른 시작 (자동 배포)

### 1단계: 스크립트 실행 권한 부여

```bash
cd production_deployment
chmod +x scripts/phase3/*.sh
```

### 2단계: Phase 3 배포 실행

```bash
./scripts/phase3/deploy.sh prod
```

**예상 출력**:
```
============================================
Phase 3: AgentCore Runtime 배포
Environment: prod
============================================

[1/7] 사전 체크...
  ✓ .env 파일 확인
  ✓ 필수 환경 변수 확인 (9개)
  ✓ AWS CLI 확인
  ✓ Python3 확인
  ✓ bedrock_agentcore toolkit 확인

[2/7] AgentCore Runtime 소스 파일 준비...
  ✓ agentcore_runtime.py
  ✓ src/ (graph, tools, utils, prompts)
  ✓ requirements.txt

[3/7] .bedrock_agentcore.yaml 생성...
  ✓ .bedrock_agentcore.yaml 생성 완료

[4/7] 환경 변수 파일 생성...
  ✓ .env 파일 생성 완료

[5/7] AgentCore Runtime 배포 시작...
  📦 Docker 이미지 빌드 및 ECR 푸시 중...
  ⏱️  예상 소요 시간: 5-10분

  [1/2] Configuration...
  ✓ Configuration 완료

  [2/2] Runtime 배포 (launch)...
  ✓ Runtime 배포 완료

[6/7] Runtime ARN 가져오기...
  ✓ Runtime ARN: arn:aws:bedrock-agentcore:us-east-1:xxx:runtime/...

[7/7] .env 파일 업데이트...
  ✓ .env 파일 업데이트 완료

============================================
✓ Phase 3 배포 완료!
============================================

Deployment Summary:
  Runtime Name: bedrock_manus_runtime_prod_1730518400
  Runtime ARN: arn:aws:bedrock-agentcore:us-east-1:xxx:runtime/...
  Network Mode: VPC
  VPC ID: vpc-xxx
  Subnet: subnet-xxx
  Security Group: sg-xxx

Next Steps:
  1. 검증 실행: ./scripts/phase3/verify.sh
  2. ENI 상태 확인: aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=vpc-xxx"
  3. Phase 4 진행: 테스트 및 검증
```

### 3단계: Runtime 검증

```bash
./scripts/phase3/verify.sh
```

**검증 항목** (총 8개):
```
============================================
Phase 3: AgentCore Runtime Verification
============================================

1. Checking AgentCore Runtime...
  Runtime exists                              ✓ OK
  Runtime status                              ✓ READY
  Network mode                                ✓ VPC
  Security group                              ✓ OK
  Subnet                                      ✓ OK

2. Checking Network Interface (ENI)...
  ✓ ENI found (count: 1)

3. Checking CloudWatch Logs (optional)...
  ✓ CloudWatch Log Group found

4. Checking Runtime Metadata...
  Runtime ARN saved in .env                   ✓ OK
  Runtime name saved in .env                  ✓ OK

============================================
Verification Summary
============================================

Total Checks:  8
Passed:        8

✓ All checks passed!
```

### ✅ 자동 배포 완료!

Phase 3 자동 배포가 완료되었습니다. [Phase 4](./04_TESTING.md)로 진행하세요.

---

## 📖 수동 배포 (단계별)

자동 배포 스크립트의 내부 동작을 이해하고 싶거나, 특정 단계만 수정하고 싶은 경우 아래 단계별 가이드를 참고하세요.

---

## Step 1: AgentCore 파일 준비

### 1.1 필수 파일 복사

```bash
# 프로젝트 루트로 이동
cd production_deployment

# AgentCore Runtime 디렉토리 생성
mkdir -p agentcore-runtime
cd agentcore-runtime

# 필수 파일 복사
cp ../../agentcore_runtime.py .
cp -r ../../src .
cp ../../requirements.txt .
cp ../../.env.example .env

echo "✅ AgentCore Runtime 파일 복사 완료"
```

### 1.2 필수 파일 확인

```bash
# 파일 구조 확인
tree -L 2 .

# 예상 출력:
# .
# ├── agentcore_runtime.py
# ├── src/
# │   ├── graph/
# │   ├── prompts/
# │   ├── tools/
# │   └── utils/
# ├── requirements.txt
# └── .env
```

**필수 파일**:
- `agentcore_runtime.py` - EntryPoint
- `src/graph/builder.py` - Workflow graph
- `src/tools/` - Fargate tools (global_fargate_coordinator.py 등)
- `src/utils/` - Utilities (strands_sdk_utils.py 등)
- `src/prompts/` - Agent prompts (coder.md, validator.md, reporter.md)

---

## Step 2: Runtime 설정 파일 생성

### 2.1 환경 변수 로드

```bash
# Phase 1, 2에서 생성한 환경 변수 로드
cd ..
source deployment.env

# 확인
echo "VPC ID: $VPC_ID"
echo "Subnets: $PRIVATE_SUBNET_IDS"
echo "Security Group: $AGENTCORE_SECURITY_GROUP"
echo "AWS Account: $AWS_ACCOUNT_ID"
```

### 2.2 `.bedrock_agentcore.yaml` 생성

```bash
# Subnets를 배열 형식으로 변환
SUBNET_ARRAY=$(echo $PRIVATE_SUBNET_IDS | sed 's/,/\n          - /g')

# .bedrock_agentcore.yaml 생성
cat > agentcore-runtime/.bedrock_agentcore.yaml <<EOF
default_agent: bedrock_manus_runtime_${ENVIRONMENT}
agents:
  bedrock_manus_runtime_${ENVIRONMENT}:
    name: bedrock_manus_runtime_${ENVIRONMENT}
    entrypoint: ./agentcore_runtime.py
    platform: linux/arm64
    container_runtime: docker
    aws:
      execution_role_auto_create: false
      account: '${AWS_ACCOUNT_ID}'
      region: ${AWS_REGION}
      ecr_repository: null
      ecr_auto_create: true
      network_configuration:
        network_mode: VPC
        network_mode_config:
          security_groups:
          - ${AGENTCORE_SECURITY_GROUP}
          subnets:
          - ${SUBNET_ARRAY}
      protocol_configuration:
        server_protocol: HTTP
      observability:
        enabled: true
    bedrock_agentcore:
      agent_id: null
      agent_arn: null
      agent_session_id: null
    codebuild:
      project_name: null
      execution_role: null
      source_bucket: null
    authorizer_configuration: null
    oauth_configuration: null
EOF

echo "✅ .bedrock_agentcore.yaml 생성 완료"
cat agentcore-runtime/.bedrock_agentcore.yaml
```

### 2.3 환경 변수 파일 설정

```bash
# .env 파일 업데이트
cat > agentcore-runtime/.env <<EOF
# AWS Configuration
AWS_REGION=${AWS_REGION}
AWS_DEFAULT_REGION=${AWS_REGION}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID}

# S3 Bucket
S3_BUCKET_NAME=${S3_BUCKET_NAME}

# Fargate Configuration
FARGATE_CLUSTER_NAME=${ECS_CLUSTER_NAME}
INTERNAL_ALB_DNS=${INTERNAL_ALB_DNS}
ALB_TARGET_GROUP_ARN=${ALB_TARGET_GROUP_ARN}

# Observability
AGENT_OBSERVABILITY_ENABLED=true
OTEL_PYTHON_DISTRO=aws_distro
OTEL_PYTHON_CONFIGURATOR=aws_configurator
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_RESOURCE_ATTRIBUTES=service.name=deep-insight-${ENVIRONMENT}
EOF

echo "✅ .env 파일 설정 완료"
cat agentcore-runtime/.env
```

---

## Step 3: Runtime 배포

### 3.1 bedrock_agentcore toolkit 확인

```bash
# bedrock_agentcore toolkit 설치 확인
python3 -m pip show bedrock_agentcore_starter_toolkit

# 설치되지 않은 경우:
# pip install bedrock_agentcore_starter_toolkit
```

### 3.2 Runtime 배포

```bash
# agentcore-runtime 디렉토리로 이동
cd agentcore-runtime

# Runtime 배포 (configure + launch)
bedrock_agentcore configure --config .bedrock_agentcore.yaml
bedrock_agentcore launch

echo "✅ AgentCore Runtime 배포 시작"
```

**예상 소요 시간**: 5-10분

**배포 과정**:
1. Docker 이미지 빌드 (AgentCore Runtime 컨테이너)
2. ECR에 이미지 푸시
3. Bedrock AgentCore 서비스에 등록
4. VPC ENI 생성 및 연결
5. Runtime 상태 `READY` 전환

### 3.3 배포 진행 상황 모니터링

**방법 1: Toolkit 로그 확인**
```bash
# 터미널에서 bedrock_agentcore launch 출력 확인
# 예상 로그:
# [INFO] Building Docker image...
# [INFO] Pushing to ECR...
# [INFO] Creating Runtime...
# [INFO] Runtime Status: CREATING...
# [INFO] Runtime Status: READY
```

**방법 2: AWS CLI로 확인**
```bash
# Runtime 목록 확인
aws bedrock-agentcore list-agent-runtimes \
  --region $AWS_REGION \
  --query 'agentRuntimes[?contains(agentRuntimeName, `bedrock_manus_runtime_${ENVIRONMENT}`)]' \
  --output table
```

---

## Step 4: Runtime 검증

### 4.1 Runtime ARN 가져오기

```bash
# Runtime ARN 추출
RUNTIME_ARN=$(bedrock_agentcore get-runtime-arn)

# 또는 AWS CLI로:
RUNTIME_ARN=$(aws bedrock-agentcore list-agent-runtimes \
  --region $AWS_REGION \
  --query 'agentRuntimes[?contains(agentRuntimeName, `bedrock_manus_runtime_'${ENVIRONMENT}'`)].agentRuntimeArn' \
  --output text | head -1)

echo "Runtime ARN: $RUNTIME_ARN"

# 환경 변수에 저장
cd ..
echo "RUNTIME_ARN=$RUNTIME_ARN" >> deployment.env
```

### 4.2 Runtime 상태 확인

```bash
# Runtime 상세 정보
aws bedrock-agentcore get-agent-runtime \
  --agent-runtime-arn $RUNTIME_ARN \
  --region $AWS_REGION \
  --output table
```

**확인 사항**:
- [ ] Status: `READY` (또는 `ACTIVE`)
- [ ] Network Mode: `VPC`
- [ ] Subnets: Phase 1에서 생성한 Private Subnets
- [ ] Security Groups: AgentCore Security Group

### 4.3 ENI 확인

```bash
# VPC에 생성된 ENI 확인 (Bedrock AgentCore용)
aws ec2 describe-network-interfaces \
  --filters \
    "Name=vpc-id,Values=$VPC_ID" \
    "Name=description,Values=*bedrock*" \
  --query 'NetworkInterfaces[*].[NetworkInterfaceId,Status,PrivateIpAddress,Description]' \
  --output table
```

**예상 출력**:
```
----------------------------------------------------------------------
|                  DescribeNetworkInterfaces                          |
+-------------------+-----------+---------------+---------------------+
|  eni-0abc123def  |  in-use   |  10.0.1.45    |  bedrock-agentcore  |
+-------------------+-----------+---------------+---------------------+
```

**중요**: ENI가 생성되고 `in-use` 상태여야 Runtime이 정상 작동합니다.

### 4.4 Observability 확인 (선택 사항)

```bash
# CloudWatch Log Group 확인
aws logs describe-log-groups \
  --log-group-name-prefix "/aws/bedrock-agentcore" \
  --region $AWS_REGION \
  --query 'logGroups[*].[logGroupName,creationTime]' \
  --output table
```

**참고**: Observability가 활성화되면 Runtime 실행 로그가 CloudWatch에 기록됩니다.

---

## Step 5: 최종 설정 파일 생성

### 5.1 invoke_agentcore_job.py 생성

```bash
# invoke 스크립트 생성
cat > agentcore-runtime/invoke_agentcore_job.py <<'EOF'
#!/usr/bin/env python3
"""
AgentCore Runtime Job Invoker - Production
"""
import json
import sys
import os
from datetime import datetime
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

import boto3
from boto3.session import Session
from botocore.config import Config

# 설정
AGENT_ARN = os.getenv("RUNTIME_ARN")
if not AGENT_ARN:
    print("❌ RUNTIME_ARN 환경 변수가 설정되지 않았습니다.")
    sys.exit(1)

REGION = os.getenv("AWS_REGION", "us-east-1")

# 프롬프트 (인자로 받거나 기본값 사용)
PROMPT = sys.argv[1] if len(sys.argv) > 1 else \
    "./data/Dat-fresh-food-claude.csv 파일의 총 매출액 계산해줘."

def parse_sse_data(sse_bytes):
    """SSE 데이터 파싱"""
    if not sse_bytes or len(sse_bytes) == 0:
        return None

    try:
        text = sse_bytes.decode('utf-8').strip()
        if not text or text == '':
            return None

        if text.startswith('data: '):
            json_text = text[6:].strip()
            if json_text:
                return json.loads(json_text)
        else:
            return json.loads(text)
    except Exception:
        pass

    return None

def main():
    """AgentCore Runtime 호출"""
    start_time = datetime.now()
    print(f"\n{'='*60}")
    print(f"🚀 AgentCore Runtime Job 시작")
    print(f"📅 시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 Agent ARN: {AGENT_ARN}")
    print(f"{'='*60}\n")

    # boto3 클라이언트 생성
    my_config = Config(
        connect_timeout=60*100,
        read_timeout=3600,
        retries={'max_attempts': 0}
    )

    agentcore_client = boto3.client(
        'bedrock-agentcore',
        region_name=REGION,
        config=my_config,
    )

    print(f"📤 요청 전송 중...")
    print(f"💬 프롬프트: {PROMPT}\n")

    try:
        boto3_response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_ARN,
            qualifier="DEFAULT",
            payload=json.dumps({"prompt": PROMPT})
        )

        # 응답 처리
        if "text/event-stream" in boto3_response.get("contentType", ""):
            print(f"📥 스트리밍 응답 수신 시작...\n")

            for event in boto3_response["response"].iter_lines(chunk_size=1):
                event_data = parse_sse_data(event)
                if event_data:
                    print(f"Event: {json.dumps(event_data, indent=2)}")

        end_time = datetime.now()
        elapsed_time = (end_time - start_time).total_seconds()

        print(f"\n{'='*60}")
        print(f"✅ AgentCore Runtime Job 완료")
        print(f"📅 종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱️  총 소요 시간: {elapsed_time:.2f}초 ({elapsed_time/60:.2f}분)")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
EOF

chmod +x agentcore-runtime/invoke_agentcore_job.py
echo "✅ invoke_agentcore_job.py 생성 완료"
```

### 5.2 .env 파일에 RUNTIME_ARN 추가

```bash
# RUNTIME_ARN을 .env에 추가
echo "RUNTIME_ARN=$RUNTIME_ARN" >> agentcore-runtime/.env

echo "✅ .env 파일 업데이트 완료"
```

---

## Step 6: 간단한 테스트 (선택 사항)

### 6.1 빠른 테스트 실행

```bash
cd agentcore-runtime

# 간단한 프롬프트 테스트
python3 invoke_agentcore_job.py "Hello, AgentCore!"
```

**예상 출력**:
```
🚀 AgentCore Runtime Job 시작
📅 시작 시간: 2025-10-20 16:00:00
🎯 Agent ARN: arn:aws:bedrock-agentcore:us-east-1:xxx:runtime/bedrock_manus_runtime_prod-xxx
...
📥 스트리밍 응답 수신 시작...
Event: {...}
...
✅ AgentCore Runtime Job 완료
⏱️  총 소요 시간: 45.23초
```

---

## ✅ 완료 확인

다음이 모두 완료되었으면 Phase 3가 성공적으로 완료되었습니다:

- [x] AgentCore Runtime 파일 준비 완료
- [x] `.bedrock_agentcore.yaml` 생성 완료
- [x] Runtime 배포 성공
- [x] Runtime 상태: `READY`
- [x] Network Mode: `VPC`
- [x] ENI 생성 및 `in-use` 상태 확인
- [x] RUNTIME_ARN 저장 완료
- [x] `invoke_agentcore_job.py` 생성 완료

**다음 단계**:
- ✅ Phase 3 완료
- ⏳ Phase 4로 진행: [04_TESTING.md](./04_TESTING.md)

---

## 🧹 Cleanup (리소스 정리)

Phase 3 리소스를 정리하려면 cleanup 스크립트를 사용하세요.

### Cleanup 방법

**Interactive 모드** (권장):
```bash
./scripts/phase3/cleanup.sh prod
```
- 각 리소스 삭제 전 확인 요청
- 실수로 삭제하는 것을 방지

**Force 모드** (자동 삭제):
```bash
./scripts/phase3/cleanup.sh prod --force
```
- 모든 확인을 건너뛰고 자동 삭제
- CI/CD 파이프라인에서 사용

### 삭제되는 리소스

1. **AgentCore Runtime**: `bedrock_manus_runtime_prod_xxx`
2. **ECR Repository**: bedrock_agentcore toolkit이 생성한 ECR (선택적)
3. **agentcore-runtime/**: 로컬 디렉토리 (선택적)
4. **.env**: Phase 3 섹션만 삭제

**참고**:
- ENI는 Runtime 삭제 시 자동으로 삭제됩니다
- CloudWatch Logs는 수동 삭제 필요 (선택 사항)

---

## 🔧 트러블슈팅

### 문제 1: Runtime 생성 실패 (CREATE_FAILED)

**증상**:
```
Runtime Status: CREATE_FAILED
```

**해결 방법**:
```bash
# Runtime 상세 에러 확인
aws bedrock-agentcore get-agent-runtime \
  --agent-runtime-arn $RUNTIME_ARN \
  --query 'failureReasons' \
  --output text

# 일반적인 원인:
# - Subnet이 지원되지 않는 AZ에 있음
# - Security Group 규칙 오류
# - VPC Endpoint 미생성
# - Service-Linked Role 부족
```

**해결**:
1. AZ ID 확인: us-east-1a는 `use1-az2`여야 함
2. VPC Endpoints 상태 확인: 모두 `available`
3. Service-Linked Role 확인:
   ```bash
   aws iam get-role \
     --role-name AWSServiceRoleForBedrockAgentCoreNetwork
   ```

### 문제 2: ENI가 생성되지 않음

**증상**:
```
Runtime Status: READY
하지만 ENI 없음
```

**참고**: 이는 정상일 수 있습니다. ENI는 첫 Job 실행 시 생성됩니다.

**확인 방법**:
```bash
# 간단한 Job 실행 후 ENI 재확인
python3 invoke_agentcore_job.py "test"

# ENI 재확인
aws ec2 describe-network-interfaces \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'NetworkInterfaces[*].[NetworkInterfaceId,Status,Description]' \
  --output table
```

### 문제 3: bedrock_agentcore toolkit 에러

**증상**:
```
bedrock_agentcore: command not found
```

**해결 방법**:
```bash
# Toolkit 재설치
pip install --upgrade bedrock_agentcore_starter_toolkit

# 또는 Python 모듈로 실행
python3 -m bedrock_agentcore_starter_toolkit configure --config .bedrock_agentcore.yaml
python3 -m bedrock_agentcore_starter_toolkit launch
```

### 문제 4: VPC 모드 업데이트 실패

**증상**:
```
UPDATE_FAILED: Cannot update network mode from PUBLIC to VPC
```

**해결 방법**:
새로운 Runtime을 VPC 모드로 생성하고, 기존 PUBLIC Runtime을 삭제합니다.

```bash
# 기존 Runtime 삭제 (주의: 프로덕션에서는 신중하게)
aws bedrock-agentcore delete-agent-runtime \
  --agent-runtime-arn $OLD_RUNTIME_ARN

# 새 Runtime 생성
bedrock_agentcore launch
```

---

## 📚 다음 단계

Phase 3 완료를 축하합니다! 🎉

다음 단계로 진행하세요:

→ **[04_TESTING.md](./04_TESTING.md)** - 테스트 및 검증

---

**작성일**: 2025-10-20
**마지막 업데이트**: 2025-10-20
