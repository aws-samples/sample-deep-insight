
## Project: Deep Insight Front-end 구축

## 배경
- 현재 이 코드 리포는 front-end side (예: Web Page) 가 없고, self-hosted, managed-agentcore 는 모두 서버에 배포가 되어서, 간단하게 cli client 혹은 py file 을 통하여 사용을 하고 있습니다.

## 목적
- 일반 사용자도 web page 를 통하여, 본인의 데이터 파일 (예: csv 파일) 을 업로드 하여, 리포트 생성을 하고, 다운로드 받아서 사용을 하면 좋을 것 같습니다.

---

## Architecture Decisions

### 1. Communication Protocol — AgentCore Native Protocol + S3
- BFF 와 AgentCore 간 통신은 **AgentCore Native Protocol** (`boto3.invoke_agent_runtime()`) 을 사용합니다.
  - Native SSE: 분석 요청 전송 + 실시간 스트리밍 진행 상태 수신 (20분+ 세션 지원)
  - S3: HITL (plan review feedback) + 파일 업로드/다운로드
- BFF 가 기존 CLI client (`02_invoke_agentcore_runtime_vpc.py`) 의 역할을 대체합니다.
- 기존 `managed-agentcore/` 코드는 변경하지 않습니다.
- **A2A wrapper 불필요** — AgentCore 네이티브 프로토콜이 커스텀 이벤트 (`plan_review_request`, `agent_text_stream` 등) 를 모두 지원하므로, A2A 래핑 시 발생하는 이벤트 손실 문제가 없습니다.

### 2. BFF (Backend-for-Frontend) — Non-LLM Middleware
- BFF 는 **LLM 이 없는 middleware 서비스** 입니다.
- 핵심 역할:
  - 파일 업로드 처리 (CSV → S3)
  - `boto3.invoke_agent_runtime()` 으로 AgentCore 에 분석 요청 전송 + SSE 스트리밍 응답 수신
  - 스트리밍 응답을 브라우저에 실시간 전달 (FastAPI `StreamingResponse`)
  - HITL: `plan_review_request` 이벤트 감지 → 브라우저에 표시, 사용자 feedback 을 S3 에 업로드
  - 리포트 다운로드 제공 (S3 에서 읽기)

### 3. HITL (Human-in-the-Loop) — S3 Polling (기존 메커니즘 활용)
- AgentCore 스트리밍 응답에 `plan_review_request` 이벤트가 포함됩니다.
- BFF 가 기존 CLI client (`02_invoke`) 의 역할을 대체하여 S3 를 통해 feedback 을 교환합니다.
- 흐름:
  1. Planner 가 plan 생성 → `plan_review_request` 이벤트 발행 (request_id, plan 포함)
  2. BFF 가 SSE 스트림에서 `plan_review_request` 이벤트 감지 → 브라우저에 plan 표시
  3. Backend 가 S3 폴링 시작: `s3://{bucket}/deep-insight/feedback/{request_id}.json` (매 3초)
  4. 사용자가 Approve/Reject → BFF 가 feedback JSON 을 S3 에 업로드
  5. Backend 가 S3 에서 feedback 을 읽고 실행 계속 (또는 plan 수정)
  6. Timeout 300초 시 자동 승인
- 기존 `managed-agentcore/` 코드는 변경하지 않습니다.

### 4. Single-Account Architecture — Backend Account
- **모든 리소스를 Backend Account 에 배포합니다** (AgentCore Runtime, BFF, S3).
- ALB Security Group 을 허용된 내부 IP 대역으로 제한하여 외부 접근을 차단합니다 (CIDR 은 배포 시 환경 변수로 설정).
- 보안: ALB 가 public internet 에 노출되지 않으므로, 단일 계정으로도 보안 경계를 유지할 수 있습니다.
- 장점: cross-account IAM role, cross-account S3, cross-account OAuth 가 불필요하여 아키텍처가 단순해집니다.

### 5. BFF → AgentCore 통신 — boto3 (동일 계정)
- BFF 는 `boto3.client('bedrock-agentcore')` 로 AgentCore Runtime 을 호출합니다.
- `invoke_agent_runtime(agentRuntimeArn=..., payload=...)` → SSE 스트리밍 응답
- 동일 계정이므로 BFF 의 IAM role 에 `bedrock-agentcore:InvokeAgentRuntime` 권한만 필요합니다.
- OAuth, SigV4 서명 등 별도 인증 불필요 — boto3 가 IAM role 기반 인증을 자동 처리합니다.

### 6. S3 — IAM Prefix Scoping

#### Upload (CSV): Browser → BFF → S3
```
Browser → BFF → S3
                       │
                       │ AgentCore reads directly
                       ▼
               AgentCore reads CSV
```
- 사용자가 업로드한 CSV 는 S3 에 저장됩니다.
- S3 경로는 session_id 로 네임스페이싱:
  ```
  s3://{bucket}/uploads/{session_id}/data.csv
  s3://{bucket}/uploads/{session_id}/column_definitions.json
  ```
- IAM policy 로 접근을 제어합니다.

#### Download (DOCX): S3 → BFF → Browser
```
AgentCore writes DOCX → S3
                              │
                              │ BFF reads directly
                              ▼
                       BFF → Browser
```
- AgentCore 가 생성한 리포트 (DOCX) 는 S3 에 저장됩니다.
- BFF 는 IAM role 로 S3 에서 리포트를 읽어 브라우저에 전달합니다.

#### Backend S3 세션 구조 (기존 시스템)
- Backend 은 세션별로 S3 에 다음 구조로 결과를 저장합니다:
  ```
  s3://{bucket}/deep-insight/fargate_sessions/{session_id}/
  ├── debug/                    ← 실행 로그
  │   ├── session_status.json
  │   └── execution_*.json
  ├── artifacts/                ← 생성된 리포트 (DOCX, 차트 등)
  ├── data/                     ← 입력 데이터
  └── output/                   ← 토큰 사용량 등
  ```
- 스트리밍 응답에 **session_id** 가 포함되므로, BFF 는 이를 통해 S3 경로를 구성하여 리포트를 다운로드합니다:
  - `s3://{bucket}/deep-insight/fargate_sessions/{session_id}/artifacts/` → DOCX 파일 위치

#### IAM Role Prefix Scoping
- 보안을 위해 BFF 의 IAM role 은 **특정 S3 prefix** 로 제한합니다:

  | Role | 허용 범위 |
  |------|----------|
  | BFF Upload | `s3://{bucket}/uploads/*` 만 WRITE 허용 |
  | BFF HITL | `s3://{bucket}/deep-insight/feedback/*` READ/WRITE 허용 |
  | BFF Download | `s3://{bucket}/deep-insight/fargate_sessions/*/artifacts/*` 만 READ 허용 |

- Role 이 침해되더라도 특정 prefix 외의 S3 객체에는 접근 불가합니다.

---

## Tech Stack & Hosting

### 7. Frontend Tech Stack — FastAPI + Plain HTML/JS
- **BFF:** Python FastAPI — backend 코드베이스와 일관성 유지, 경량
- **Web UI:** Plain HTML + vanilla JavaScript (또는 Alpine.js/htmx)
- npm, build step, node_modules 없이 심플하게 구성
- UI 디자인에 대한 완전한 제어 가능

### 프로젝트 폴더 구조
```
under-development/front-end-implementation/
├── doc/
│   ├── 01-plan.md                ← 아키텍처 및 설계 문서 (이 파일)
│   └── 02-technical-proof-points.md  ← PoC 검증 목록 및 결과
├── poc/                          ← PoC 코드 (기술 검증용)
│   ├── setup/                    ← UV 환경 설정
│   ├── poc1-a2a-wrapper/         ← PoC 1: A2A Server 래핑 테스트 (참고용)
│   ├── poc2-a2a-client/          ← PoC 2: A2A SDK 클라이언트 테스트 (참고용)
│   ├── poc3-a2a-streaming/       ← PoC 2: A2A 스트리밍 클라이언트 (참고용)
│   ├── poc3-bff-sse-relay/       ← PoC 3: BFF SSE relay 테스트 (참고용)
│   └── poc5-alb-ecs-webapp/      ← PoC 5: ALB + ECS Fargate 웹 서빙
├── frontend-bff/                 ← BFF service
│   ├── app.py                    ← FastAPI BFF
│   ├── static/                   ← HTML/JS/CSS
│   │   ├── index.html            ← 메인 페이지 (Deep Insight 설명)
│   │   └── dashboard.html        ← 파일 업로드 + 진행 상태 + 다운로드
│   ├── requirements.txt
│   └── Dockerfile
```

### BFF 필수 환경 변수
```
# AgentCore
RUNTIME_ARN=                ← AgentCore Runtime ARN (동일 계정)
AWS_REGION=                 ← AWS 리전

# S3
S3_BUCKET=                  ← 업로드/다운로드용 S3 버킷 (동일 계정)

# 보안
ALLOWED_CIDR=               ← ALB Security Group 에 허용할 내부 IP 대역
```

### 8. Frontend Hosting — ECS Fargate + ALB (Restricted Access)
- FastAPI BFF 서비스를 **ECS Fargate** 에 컨테이너로 배포합니다.
- **ALB** 를 앞에 배치하고, Security Group 을 허용된 내부 IP 대역으로 제한합니다.
  - ALB SG: 허용된 CIDR 에서만 TCP 80/443 허용
  - ECS SG: ALB SG 에서만 TCP 8080 허용 (직접 접근 불가)
- Auto-scaling 지원, backend 패턴과 일관성 유지
- Long-lived connection (streaming) 지원 가능
- PoC 5 에서 검증 완료: VPN 접속 시 접근 가능, VPN 미접속 시 차단 확인

### 9. Real-Time Progress — SSE (Server-Sent Events)
- AgentCore → BFF: `boto3.invoke_agent_runtime()` SSE 스트리밍으로 진행 상태 수신
- BFF → Browser: FastAPI `StreamingResponse` 로 SSE 중계
- End-to-end SSE relay: AgentCore → boto3 SSE → BFF → SSE → Browser
- 20분+ 장시간 세션 동안 실시간 이벤트 전달 (agent_text_stream, plan_review_request 등)

### 10. Report Preview — 미구현 (Download Only)
- 리포트 미리 보기 기능은 현재 범위에서 제외합니다.
- 리포트 생성 완료 시 다운로드 버튼만 제공합니다.

---

## 사용자 시나리오

### 일반 사용 흐름
1. 사용자가 VPN 접속 후 웹 페이지에 접속하면 Deep Insight 설명 및 파일 업로드 화면이 보입니다.
2. 데이터 파일을 업로드하고 (CSV 필수, column_definitions.json 선택), 분석 요청 (user query) 을 입력한 후 "시작" 버튼을 클릭합니다.
3. BFF 가 파일을 S3 에 저장합니다:
   - `s3://{bucket}/uploads/{session_id}/data.csv`
   - `s3://{bucket}/uploads/{session_id}/column_definitions.json` (있는 경우)
4. BFF 가 `boto3.invoke_agent_runtime()` 을 호출합니다. 요청에 포함되는 내용:
   - **prompt**: 사용자가 입력한 분석 요청 (예: "매출 트렌드 분석해줘")
   - **data_directory**: 업로드된 CSV 의 S3 경로
5. AgentCore Runtime 이 동일 계정 S3 에서 CSV 를 읽고, 분석을 실행하고, SSE 스트리밍으로 진행 상태를 응답합니다.
6. BFF 가 SSE 스트리밍 응답을 파싱하여 브라우저에 실시간 표시합니다.
7. HITL: `plan_review_request` 이벤트 감지 → 사용자에게 plan 표시 → 승인/거절 feedback 을 S3 에 업로드.
8. 리포트 생성이 완료되면 다운로드 버튼이 활성화됩니다.
9. 사용자가 다운로드 버튼을 클릭하면 DOCX 리포트가 로컬에 저장됩니다.

---

## Deferred Decisions (추후 결정)

### A2A Protocol
- 현재는 AgentCore Native Protocol (boto3) 으로 직접 통신.
- A2A 래핑 시 커스텀 이벤트 (plan_review_request 등) 손실 문제로 보류.
- 추후 multi-agent 라우팅이 필요할 때 도입 검토.
- A2A 기술 검증은 완료: PoC 1 (서버/클라이언트), PoC 2 (스트리밍), PoC 3 (BFF SSE relay).

### Report Preview
- 추후 필요 시 구현 검토 (PDF 변환, HTML 변환 등)

### User Authentication (사용자 인증)
- 현재는 ALB Security Group 으로 VPN 접속자만 허용하여 접근 제한.
- 추후 필요 시 Cognito 등을 통한 사용자 인증 구현 검토.

### Session Persistence (세션 유지)
- 분석은 10분 이상 소요될 수 있음. 사용자가 브라우저를 닫았다가 다시 접속했을 때 결과를 확인할 수 있는지 결정 필요.
- 후보: BFF 에서 session_id 매핑을 DB/DynamoDB 에 저장, 재접속 시 상태 복원

### Error Handling (에러 처리)
- Backend 분석 중 실패 시 사용자에게 표시할 에러 화면 및 재시도 흐름 결정 필요.
- 후보: 에러 응답 코드 매핑, 사용자에게 에러 메시지 + 재시도 버튼 제공

---

## Architecture Diagram

```
[Backend Account — Single Account]
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  Browser (HTML/JS)                                       │
│    │                                                     │
│    │ HTTPS (VPN/internal IP only)                        │
│    ▼                                                     │
│  ALB (Security Group: 허용된 내부 IP 대역만 허용)            │
│    │                                                     │
│    ▼                                                     │
│  FastAPI BFF (ECS Fargate)                               │
│    │                                                     │
│    ├─► boto3.invoke_agent_runtime() ──► AgentCore Runtime│
│    │   (SSE streaming, 20min+ sessions)   │              │
│    │                                      │              │
│    │   events: agent_text_stream,         ▼              │
│    │           plan_review_request,  Fargate Containers  │
│    │           workflow_complete      (code execution)    │
│    │                                      │              │
│    │                                      │ writes DOCX  │
│    │                                      ▼              │
│    ├─► S3                                                │
│    │   ├── uploads/{session_id}/              ← CSV 업로드│
│    │   ├── deep-insight/feedback/{req_id}.json ← HITL    │
│    │   └── deep-insight/fargate_sessions/     ← 리포트    │
│    │        {session_id}/artifacts/                       │
│    ▼                                                     │
│  Browser ◄── DOCX download                               │
│                                                          │
└──────────────────────────────────────────────────────────┘
```
