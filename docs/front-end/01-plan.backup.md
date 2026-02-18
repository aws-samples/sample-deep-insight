
## Project: Deep Insight Front-end 구축

## 배경
- 현재 이 코드 리포는 front-end side (예: Web Page) 가 없고, self-hosted, managed-agentcore 는 모두 서버에 배포가 되어서, 간단하게 cli client 혹은 py file 을 통하여 사용을 하고 있습니다.

## 목적
- 일반 사용자도 web page 를 통하여, 본인의 데이터 파일 (예: csv 파일) 을 업로드 하여, 리포트 생성을 하고, 다운로드 받아서 사용을 하면 좋을 것 같습니다.

---

## Architecture Decisions

### 1. Communication Protocol — Google A2A
- BFF 와 AgentCore 간 통신은 **Google A2A (Agent-to-Agent) protocol** 을 사용합니다.
- Amazon Bedrock AgentCore Runtime 이 A2A protocol 을 네이티브로 지원합니다.
  - JSON-RPC 2.0 over HTTP
  - Agent Card 를 통한 agent discovery (`/.well-known/agent-card.json`)
  - Port 9000 (A2A 전용)
- 기존 `managed-agentcore/` 코드는 변경하지 않습니다.
- **별도 폴더** (`under-development/front-end-implementation/backend-a2a/`) 에 A2A wrapper 를 새로 생성합니다.
  - 기존 Deep Insight agent 를 import 하여 Strands SDK 의 `A2AServer` 로 래핑
  - Port 9000 에서 A2A endpoint 로 노출
  - 기존 HTTP runtime (port 8080) 과 독립적으로 동작

### 2. BFF (Backend-for-Frontend) — Non-LLM Middleware
- BFF 는 **LLM 이 없는 middleware 서비스** 입니다.
- 핵심 역할:
  - 파일 업로드 처리 (CSV → S3)
  - Browser 와 AgentCore 간 A2A 메시지 중계
  - AgentCore 로부터 스트리밍 응답을 받아 브라우저에 전달
  - 리포트 다운로드 제공 (S3 에서 읽기)

### 3. HITL (Human-in-the-Loop) — Frontend 범위에서 제외
- Backend 의 plan review (HITL) 기능은 frontend 에서 구현하지 않습니다.
- Backend 는 기존 로직대로 HITL feedback timeout 시 자동 승인 (auto-approve) 처리합니다.
- 기존 `managed-agentcore/` 코드는 변경하지 않습니다. (A2A wrapper 는 별도 폴더에 신규 생성 — Decision 1 참조)

### 4. Single-Account Architecture — Backend Account
- **모든 리소스를 Backend Account 에 배포합니다** (AgentCore Runtime, BFF, S3, Cognito).
- ALB Security Group 을 허용된 내부 IP 대역으로 제한하여 외부 접근을 차단합니다 (CIDR 은 배포 시 환경 변수로 설정).
- 보안: ALB 가 public internet 에 노출되지 않으므로, 단일 계정으로도 보안 경계를 유지할 수 있습니다.
- 장점: cross-account IAM role, cross-account S3, cross-account OAuth 가 불필요하여 아키텍처가 단순해집니다.

### 5. BFF → A2A 통신 — 동일 계정 내부 통신
- BFF 와 AgentCore A2A endpoint 가 **동일 계정** 에 있으므로, cross-account 인증이 불필요합니다.
- BFF 는 동일 VPC 또는 내부 네트워크를 통해 A2A endpoint 에 직접 통신합니다.
- 필요 시 IAM role 기반 인증 또는 Security Group 으로 접근을 제한합니다.

### 7. S3 — 동일 계정 내 IAM Prefix Scoping

#### Upload (CSV): Browser → BFF → S3
```
Browser → BFF → S3
                       │
                       │ AgentCore reads directly
                       ▼
               AgentCore reads CSV
```
- 사용자가 업로드한 CSV 는 S3 에 저장됩니다.
- S3 경로는 user_id 와 session_id 로 네임스페이싱:
  ```
  s3://{bucket}/uploads/{user_id}/{session_id}/data.csv
  s3://{bucket}/uploads/{user_id}/{session_id}/column_definitions.json
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
- A2A 응답에 **session_id** 가 포함되므로, BFF 는 이를 통해 S3 경로를 구성하여 리포트를 다운로드합니다:
  - `s3://{bucket}/deep-insight/fargate_sessions/{session_id}/artifacts/` → DOCX 파일 위치

#### IAM Role Prefix Scoping
- 보안을 위해 BFF 의 IAM role 은 **특정 S3 prefix** 로 제한합니다:

  | Role | 허용 범위 |
  |------|----------|
  | BFF Upload | `s3://{bucket}/uploads/*` 만 WRITE 허용 |
  | BFF Download | `s3://{bucket}/deep-insight/fargate_sessions/*/artifacts/*` 만 READ 허용 |

- BFF 는 `user_id` 를 검증하여 다른 사용자의 업로드/리포트에 접근 불가하도록 합니다.
- Role 이 침해되더라도 특정 prefix 외의 S3 객체에는 접근 불가합니다.

---

## Tech Stack & Hosting

### 8. Frontend Tech Stack — FastAPI + Plain HTML/JS
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
│   ├── poc1-a2a-wrapper/         ← PoC 1: A2A Server 래핑 테스트
│   ├── poc2-a2a-client/          ← PoC 2: A2A SDK 클라이언트 테스트
│   ├── poc3-a2a-streaming/       ← PoC 2: A2A 스트리밍 클라이언트
│   └── poc5-alb-ecs-webapp/      ← PoC 5: ALB + ECS Fargate 웹 서빙
├── backend-a2a/                  ← A2A wrapper
│   ├── a2a_server.py             ← 기존 agent import, A2AServer 로 래핑
│   ├── requirements.txt
│   └── Dockerfile                ← 빌드 시 상위 src/ 를 포함하여 기존 agent 코드 접근
├── frontend-bff/                 ← BFF service
│   ├── app.py                    ← FastAPI BFF
│   ├── static/                   ← HTML/JS/CSS
│   │   ├── index.html            ← 메인 페이지 (Deep Insight 설명 + 로그인)
│   │   ├── login.html            ← 로그인 / 비밀번호 변경
│   │   └── dashboard.html        ← 파일 업로드 + 진행 상태 + 다운로드
│   ├── requirements.txt
│   └── Dockerfile
```

### BFF 필수 환경 변수
```
# 인증
COGNITO_USER_POOL_ID=       ← 사용자 인증용 Cognito User Pool
COGNITO_APP_CLIENT_ID=      ← 사용자 인증용 App Client

# S3
S3_BUCKET=                  ← 업로드/다운로드용 S3 버킷 (동일 계정)

# A2A
A2A_ENDPOINT_URL=           ← AgentCore A2A endpoint URL (동일 계정)

# 보안
ALLOWED_CIDR=               ← ALB Security Group 에 허용할 내부 IP 대역
```

### 9. Frontend Hosting — ECS Fargate + ALB (Restricted Access)
- FastAPI BFF 서비스를 **ECS Fargate** 에 컨테이너로 배포합니다.
- **ALB** 를 앞에 배치하고, Security Group 을 허용된 내부 IP 대역으로 제한합니다.
  - ALB SG: 허용된 CIDR 에서만 TCP 80/443 허용
  - ECS SG: ALB SG 에서만 TCP 8080 허용 (직접 접근 불가)
- Auto-scaling 지원, backend 패턴과 일관성 유지
- Long-lived connection (streaming) 지원 가능
- PoC 5 에서 검증 완료: VPN 접속 시 접근 가능, VPN 미접속 시 차단 확인

### 10. Report Preview — 미구현 (Download Only)
- 리포트 미리 보기 기능은 현재 범위에서 제외합니다.
- 리포트 생성 완료 시 다운로드 버튼만 제공합니다.

---

## 사용자 시나리오

### 최초 로그인 (첫 번째만)
1. Admin 이 Cognito 에서 사용자 계정을 생성합니다.
2. 사용자가 이메일로 임시 비밀번호를 수신합니다.
3. 사용자가 웹 페이지에 접속하여 임시 비밀번호로 로그인합니다.
4. 본인 비밀번호로 변경 후 로그인 완료됩니다.

### 일반 사용 흐름
1. 사용자가 웹 페이지에 접속하면 Deep Insight 설명 및 로그인 화면이 보입니다.
2. 사용자가 ID (email) / PW 로 로그인합니다 (Cognito 인증).
3. 로그인 성공 → 파일 업로드 페이지로 redirect 됩니다.
4. 데이터 파일을 업로드하고 (CSV 필수, column_definitions.json 선택), 분석 요청 (user query) 을 입력한 후 "시작" 버튼을 클릭합니다.
5. BFF 가 파일을 S3 에 저장합니다:
   - `s3://{bucket}/uploads/{user_id}/{session_id}/data.csv`
   - `s3://{bucket}/uploads/{user_id}/{session_id}/column_definitions.json` (있는 경우)
6. BFF 가 A2A endpoint 를 호출합니다. A2A 메시지에 포함되는 내용:
   - **user query**: 사용자가 입력한 분석 요청 (예: "매출 트렌드 분석해줘")
   - **S3 path**: 업로드된 CSV 의 S3 경로
7. AgentCore Runtime 이 동일 계정 S3 에서 CSV 를 읽고, 분석을 실행하고, 스트리밍으로 진행 상태를 응답합니다.
8. BFF 가 응답을 받아 브라우저에 실행 상태를 표시합니다.
9. 리포트 생성이 완료되면 다운로드 버튼이 활성화됩니다.
10. 사용자가 다운로드 버튼을 클릭하면 DOCX 리포트가 로컬에 저장됩니다.

---

## Deferred Decisions (추후 결정)

### 11. Real-Time Progress Streaming 방식
- Browser 와 BFF 간 실시간 진행 상태 전달 방식은 테스트 코드 완성 후 결정합니다.
- 후보: SSE (Server-Sent Events), WebSocket, Polling

### Report Preview
- 추후 필요 시 구현 검토 (PDF 변환, HTML 변환 등)

### Session Persistence (세션 유지)
- 분석은 10분 이상 소요될 수 있음. 사용자가 브라우저를 닫았다가 다시 접속했을 때 결과를 확인할 수 있는지 결정 필요.
- 후보: BFF 에서 session_id ↔ user_id 매핑을 DB/DynamoDB 에 저장, 재접속 시 상태 복원

### Error Handling (에러 처리)
- Backend 분석 중 실패 시 사용자에게 표시할 에러 화면 및 재시도 흐름 결정 필요.
- 후보: A2A 에러 응답 코드 매핑, 사용자에게 에러 메시지 + 재시도 버튼 제공

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
│    ├─► Cognito User Pool (user login, JWT 검증)          │
│    │                                                     │
│    ├─► A2A JSON-RPC ──► AgentCore Runtime                │
│    │                     (A2A Server, port 9000)         │
│    │                       │                             │
│    │                       │ backend-a2a/ wrapper        │
│    │                       │ (Strands A2AServer)         │
│    │                       ▼                             │
│    │                     Fargate Containers               │
│    │                     (code execution)                 │
│    │                       │                             │
│    │                       │ writes DOCX                 │
│    │                       ▼                             │
│    ├─► S3                                                │
│    │   ├── uploads/{user_id}/{session_id}/    ← CSV 업로드│
│    │   └── deep-insight/fargate_sessions/     ← 리포트    │
│    │        {session_id}/artifacts/                       │
│    ▼                                                     │
│  Browser ◄── DOCX download                               │
│                                                          │
└──────────────────────────────────────────────────────────┘
```
