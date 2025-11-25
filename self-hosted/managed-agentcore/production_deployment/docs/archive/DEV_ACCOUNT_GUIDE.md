# 개발 계정 실행 가이드

## 📋 현재 상태

✅ **완료된 준비 작업**:
- Test VPC 구축 완료
- VPC Endpoints 생성 완료
- Internal ALB 구축 완료
- Security Groups 설정 완료
- IAM Role 생성 완료

✅ **생성된 설정 파일**:
- `.env.development` - 개발 계정 설정
- `production_deployment/.env` - 01, 03 스크립트가 읽는 파일

---

## 🚀 실행 순서

### 실제로 실행하는 파일은 **2개**입니다:

```bash
1️⃣ python3 create_agentcore_runtime_vpc.py  # Runtime 생성
   ↓
   (02_agentcore_runtime.py는 Container에서 자동 실행됨 - 직접 실행 안 함!)
   ↓
2️⃣ python3 invoke_agentcore_runtime_vpc.py  # Runtime 테스트
```

**중요**: `02_agentcore_runtime.py`는 **직접 실행하지 않습니다**!
- 이 파일은 AgentCore Runtime의 진입점입니다
- Fargate Container에서 자동으로 실행됩니다
- 번호를 02로 한 이유: 실행 흐름을 이해하기 위함

---

## 📝 Step 1: 환경 확인

### 1.1 설정 파일 확인

```bash
# .env 파일 확인
cat production_deployment/.env
```

**예상 출력**:
```bash
# Development Account Configuration
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=057716757052
VPC_ID=vpc-05975448296a22c21
PRIVATE_SUBNET_ID=subnet-0b2fb367d6e823a79
SG_AGENTCORE_ID=sg-0affaea9ac4dc26b1
TASK_EXECUTION_ROLE_ARN=arn:aws:iam::057716757052:role/agentcore-bedrock_manus_runtime-role
...
```

### 1.2 필수 패키지 확인

```bash
# bedrock_agentcore toolkit 확인
python3 -m pip show bedrock_agentcore_starter_toolkit

# 설치 안 되어 있으면:
pip install bedrock_agentcore_starter_toolkit
pip install python-dotenv boto3 pyyaml
```

---

## 🎯 Step 2: Runtime 생성

### 2.1 create_agentcore_runtime_vpc.py 실행

```bash
python3 create_agentcore_runtime_vpc.py
```

**예상 소요 시간**: 5-10분

**작업 내용**:
1. `production_deployment/.env` 로드
2. VPC 정보 검증
3. `.bedrock_agentcore.yaml` 생성 (VPC 설정 포함)
4. AWS CLI로 Runtime 생성
5. Runtime ARN을 `.env`에 저장

**예상 출력**:
```
============================================================
AgentCore Runtime 생성 (VPC Private 모드)
============================================================

[1/7] 환경 설정 로드...
✅ 환경 설정 로드 완료
  - Region: us-east-1
  - VPC: vpc-05975448296a22c21
  - Subnet: subnet-0b2fb367d6e823a79
  - Security Group: sg-0affaea9ac4dc26b1

[2/7] IAM Role 설정...
✅ 기존 IAM Role 재사용: arn:aws:iam::057716757052:role/...

[3/7] AgentCore Runtime 설정...
✅ Configuration 완료

[4/7] VPC 설정 추가...
✅ VPC 설정 추가 완료
  - Network Mode: VPC
  - Observability: ENABLED (CloudWatch Logs)

[5/7] AgentCore Runtime 생성...
🚀 Runtime 생성 중...
✅ Runtime 생성 요청 완료
  - ARN: arn:aws:bedrock-agentcore:us-east-1:057716757052:runtime/...
  - Status: CREATING

[6/7] Runtime 상태 확인...
⏳ Runtime이 READY 상태가 될 때까지 대기 중...
  Status: CREATING
  Status: READY

✅ Runtime이 READY 상태입니다!

[7/7] .env 파일 업데이트...
✅ .env 파일 업데이트 완료

============================================================
✅ AgentCore Runtime 생성 완료!
============================================================
```

### 2.2 생성 확인

```bash
# .env 파일에 Runtime ARN이 추가되었는지 확인
grep RUNTIME_ARN production_deployment/.env
```

**예상 출력**:
```bash
RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:057716757052:runtime/bedrock_manus_runtime_vpc_1730518400-PtBWr17D4z
```

---

## 🧪 Step 3: Runtime 테스트

### 3.1 프롬프트 선택

**간단한 테스트** (2-5분, 권장):
```python
# invoke_agentcore_runtime_vpc.py 편집
PROMPT = "./data/Dat-fresh-food-claude.csv 파일의 총 매출액 계산해줘. PDF 보고서는 만들지 마."
```

**복잡한 테스트** (20-25분):
```python
# 기본값 (이미 설정됨)
PROMPT = "./data/Dat-fresh-food-claude.csv 파일을 분석해서 총 매출액을 계산하고, 카테고리별 매출 비중도 함께 보여줘. 그리고 pdf 로 보고서 생성해줘"
```

### 3.2 invoke_agentcore_runtime_vpc.py 실행

```bash
python3 invoke_agentcore_runtime_vpc.py
```

**예상 출력**:
```
============================================================
🚀 AgentCore Runtime Job 시작
📅 시작 시간: 2025-11-03 16:00:00
🎯 Agent ARN: arn:aws:bedrock-agentcore:us-east-1:057716757052:runtime/...
🌐 Region: us-east-1
============================================================

📤 요청 전송 중...
💬 프롬프트: ./data/Dat-fresh-food-claude.csv 파일의 총 매출액 계산해줘...

📥 스트리밍 응답 수신 시작...

[Supervisor] Planning the task...
[Coder] Executing calculations...
[Validator] Validating results...
[Reporter] Generating report...

============================================================
✅ AgentCore Runtime Job 완료
📅 종료 시간: 2025-11-03 16:03:30
⏱️  총 소요 시간: 210.00초 (3.50분)
============================================================
```

---

## ✅ 성공 확인

### 개발 계정 테스트 완료 체크리스트

- [ ] create_agentcore_runtime_vpc.py 실행 성공
- [ ] Runtime 상태: READY
- [ ] `.env`에 RUNTIME_ARN 추가됨
- [ ] invoke_agentcore_runtime_vpc.py 실행 성공
- [ ] 스트리밍 응답 수신 완료
- [ ] 총 매출액 계산 결과 출력

**모두 완료되면** → Production 계정 배포 준비 완료! 🎉

---

## 🔧 트러블슈팅

### 문제 1: .env 파일이 없음

**증상**:
```
❌ .env 파일이 없습니다: production_deployment/.env
```

**해결**:
```bash
# .env 파일 다시 생성
cp .env.development production_deployment/.env
```

### 문제 2: bedrock_agentcore toolkit 없음

**증상**:
```
ModuleNotFoundError: No module named 'bedrock_agentcore_starter_toolkit'
```

**해결**:
```bash
pip install bedrock_agentcore_starter_toolkit
```

### 문제 3: Runtime 생성 실패 (CREATE_FAILED)

**원인**: Subnet AZ 문제 (use1-az6는 지원 안 됨)

**해결**:
```bash
# .env 파일에서 PRIVATE_SUBNET_ID 확인
# subnet-0b2fb367d6e823a79 (use1-az2) 사용해야 함
```

### 문제 4: AWS CLI v2 없음

**증상**:
```
aws: command not found
```

**해결**:
```bash
# AWS CLI v2 설치 또는 활성화
```

---

## 📊 생성되는 파일

### create_agentcore_runtime_vpc.py 실행 후

```
05_insight_extractor_strands_sdk_workshop_phase_2/
├── .bedrock_agentcore.yaml         # ✅ Runtime 설정 (VPC 포함)
├── Dockerfile                       # ✅ Docker 이미지 빌드용
├── .dockerignore                    # ✅ Docker 빌드 제외 파일
└── production_deployment/
    └── .env                         # ✅ RUNTIME_ARN 추가됨
```

---

## 🎯 다음 단계

### 개발 계정 테스트 성공 후:

1. **Git에 커밋** (설정 파일 제외)
   ```bash
   # .env 파일은 git에 포함하지 않음 (.gitignore에 추가)
   echo ".env" >> .gitignore
   echo ".env.development" >> .gitignore

   git add create_agentcore_runtime_vpc.py
   git add 02_agentcore_runtime.py
   git add invoke_agentcore_runtime_vpc.py
   git add PHASE3_EXECUTION_GUIDE.md
   git add DEV_ACCOUNT_GUIDE.md

   git commit -m "Add Phase 3 Python scripts (refactored from notebook)"
   git push origin master
   ```

2. **Production 계정에서 실행**
   - Git clone/pull
   - Production 계정의 VPC 정보로 `.env` 생성
   - 동일한 순서로 실행 (01 → 03)

---

## 📚 참고

### 파일 역할

| 파일 | 역할 | 실행 여부 |
|------|------|-----------|
| `create_agentcore_runtime_vpc.py` | Runtime 생성 | ✅ **직접 실행** |
| `02_agentcore_runtime.py` | Runtime 진입점 | ❌ Container에서 자동 실행 |
| `invoke_agentcore_runtime_vpc.py` | Runtime 테스트 | ✅ **직접 실행** |

### 설정 파일

| 파일 | 용도 |
|------|------|
| `.env.development` | 개발 계정 원본 설정 |
| `production_deployment/.env` | 스크립트가 읽는 설정 파일 |
| `.bedrock_agentcore.yaml` | Runtime 설정 (01 실행 시 생성) |

---

**작성일**: 2025-11-03
**개발 계정**: 057716757052
**Region**: us-east-1
