# Deep Insight A2A 하이브리드 아키텍처

> **Status**: Conceptual Design
> **Created**: 2025-12-14
> **Last Updated**: 2025-12-14

---

## 1. WHY: 왜 A2A 아키텍처인가?

### 1.1 배경

Deep Insight는 데이터 분석 및 리포트 생성에 특화된 멀티에이전트 시스템입니다. 하지만 새로운 기능(Text2SQL, DataPipeline, RAG 등)을 추가할 때마다 기존 시스템을 수정해야 하는 한계가 있습니다.

### 1.2 A2A 도입의 필요성

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      진화적 접근 (Evolution, Not Revolution)              │
│                                                                         │
│   "작동하는 것은 유지하고, 새로운 패턴으로 확장하고, 두 세계를 연결한다"      │
│                                                                         │
│   현재 시스템                │    신규 기능                              │
│   ─────────────────          │    ────────────────────                  │
│   • 계층적 구조               │    • A2A 프로토콜                         │
│   • Supervisor 중심           │    • Peer-to-Peer 가능                   │
│   • 검증됨, 안정적             │    • DataPipeline, Text2SQL, RAG...     │
│   • 그대로 유지               │    • A2A 확장으로 추가                    │
│                              │                                          │
│                       ┌──────┴──────┐                                   │
│                       │   GATEWAY   │                                   │
│                       │   (브릿지)   │                                   │
│                       └─────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 주요 이점

| 이점 | 설명 |
|------|------|
| **최소 변경** | 기존 시스템 변경 없이 확장 (~5% 코드 영향) |
| **표준 프로토콜** | AWS AgentCore A2A 공식 지원 |
| **양방향 통신** | 에이전트 간 자유로운 호출 |
| **독립적 확장** | 각 A2A 에이전트 별도 스케일링 |
| **프레임워크 무관** | Strands, LangGraph, OpenAI SDK 등 호환 |

### 1.4 기존 코드 영향도

| 컴포넌트 | 변경 필요 | 작업량 |
|----------|----------|--------|
| Coordinator | 없음 | - |
| Planner | A2A 기능 인식 (프롬프트) | 낮음 |
| Supervisor | `a2a_gateway_tool` 추가 | 낮음 |
| Coder/Validator/Reporter | 없음 | - |
| 그래프 구조 | 없음 | - |
| 스트리밍/이벤트 | 없음 | - |
| **신규: A2A Gateway** | 새 컴포넌트 | 중간 |
| **신규: Agent Card** | JSON 파일 | 낮음 |

---

## 2. WHAT: 사용 시나리오

### 2.1 시나리오 개요

A2A 아키텍처는 두 가지 통신 패턴을 지원합니다:

| 패턴 | 방향 | 사용 사례 |
|------|------|----------|
| **Forward Flow** | Deep Insight → A2A Agent | Deep Insight가 Text2SQL, DataPipeline 등 호출 |
| **Reverse Flow** | A2A Agent → Deep Insight | 외부 에이전트가 Deep Insight의 분석/리포트 기능 사용 |

### 2.2 Forward Flow: Deep Insight → A2A Agent

**시나리오**: 사용자가 데이터 웨어하우스에서 매출 데이터 분석을 요청

```
┌─────────────────────────────────────────────────────────────────────────┐
│  순방향 흐름: Deep Insight가 Text2SQL 에이전트 호출                        │
│                                                                         │
│  사용자: "데이터 웨어하우스에서 매출 데이터 분석해줘"                       │
│                                                                         │
│  Deep Insight (Supervisor)                                              │
│      │                                                                  │
│      │  A2A Gateway 호출 (a2a_gateway_tool)                             │
│      ↓                                                                  │
│  A2A Gateway (Outbound Handler)                                        │
│      │                                                                  │
│      │  POST text2sql-agent:9000/                                      │
│      │  JSON-RPC: method="message/send"                                │
│      ↓                                                                  │
│  Text2SQL Agent                                                        │
│      │                                                                  │
│      │  SQL 생성 및 실행                                                │
│      │  결과 반환 (artifacts)                                           │
│      ↓                                                                  │
│  A2A Gateway                                                           │
│      │                                                                  │
│      │  결과를 Supervisor에게 반환                                      │
│      ↓                                                                  │
│  Deep Insight (Coder → Reporter)                                       │
│      │                                                                  │
│      │  분석 및 리포트 생성                                             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Reverse Flow: A2A Agent → Deep Insight

**시나리오**: Text2SQL이 쿼리 결과를 받아 Deep Insight에 분석 및 리포트 생성 요청

```
┌─────────────────────────────────────────────────────────────────────────┐
│  역방향 흐름: Text2SQL이 Deep Insight 호출                               │
│                                                                         │
│  Text2SQL Agent                                                        │
│      │                                                                  │
│      │  "쿼리 결과 분석하고 리포트 만들어줘"                             │
│      │                                                                  │
│      │  POST deep-insight-agent:9000/                                  │
│      │  JSON-RPC: method="message/send"                                │
│      │  {                                                              │
│      │    "params": {                                                  │
│      │      "message": {                                               │
│      │        "parts": [{                                              │
│      │          "kind": "text",                                        │
│      │          "text": "skill:analyze_data\n분석 요청..."             │
│      │        }]                                                       │
│      │      }                                                          │
│      │    }                                                            │
│      │  }                                                              │
│      ↓                                                                  │
│  A2A Gateway (Inbound Handler)                                         │
│      │                                                                  │
│      │  요청 파싱, 스킬 라우팅                                          │
│      ↓                                                                  │
│  Deep Insight Core                                                     │
│      │                                                                  │
│      │  Supervisor → Coder (분석 수행)                                  │
│      ↓                                                                  │
│  A2A Gateway                                                           │
│      │                                                                  │
│      │  JSON-RPC 응답 반환                                              │
│      ↓                                                                  │
│  Text2SQL Agent                                                        │
│      │                                                                  │
│      │  분석 결과 수신                                                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.4 Deep Insight가 제공하는 스킬

외부 에이전트가 Deep Insight를 호출할 때 사용할 수 있는 스킬:

| 스킬 ID | 이름 | 설명 | 라우팅 |
|---------|------|------|--------|
| `full_workflow` | 전체 워크플로우 | 데이터 분석 + 리포트 생성 전체 파이프라인 | Coordinator → 전체 |
| `analyze_data` | 데이터 분석 | 통계 분석 및 시각화 | Supervisor → Coder |
| `generate_report` | 리포트 생성 | DOCX 리포트 생성 | Supervisor → Reporter |
| `validate_results` | 결과 검증 | 분석 결과 검증 | Supervisor → Validator |

---

## 3. HOW: 아키텍처

### 3.1 전체 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                    DEEP INSIGHT 양방향 A2A 아키텍처                           │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         A2A 에이전트 네트워크                            │ │
│  │                                                                         │ │
│  │    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │ │
│  │    │ DataPipeline│    │  Text2SQL   │    │ RAG Search  │              │ │
│  │    │   Agent     │    │   Agent     │    │   Agent     │              │ │
│  │    │  (Port 9000)│    │  (Port 9000)│    │  (Port 9000)│              │ │
│  │    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘              │ │
│  │           │                  │                  │                      │ │
│  │           │      ┌───────────┴───────────┐      │                      │ │
│  │           │      │   A2A Peer-to-Peer    │      │                      │ │
│  │           │      │   (JSON-RPC 2.0)      │      │                      │ │
│  │           │      └───────────────────────┘      │                      │ │
│  │           │                  │                  │                      │ │
│  └───────────┼──────────────────┼──────────────────┼──────────────────────┘ │
│              │                  │                  │                        │
│              └──────────────────┼──────────────────┘                        │
│                                 │                                           │
│                        ┌────────┴────────┐                                  │
│                        │                 │                                  │
│                        ↓                 ↓                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │                    A2A GATEWAY (양방향)                                │  │
│  │                    Port 9000 | JSON-RPC 2.0                          │  │
│  │                                                                       │  │
│  │         ┌─────────────────┐       ┌─────────────────┐                │  │
│  │         │ OUTBOUND        │       │ INBOUND         │                │  │
│  │         │ Handler         │       │ Handler         │                │  │
│  │         │                 │       │                 │                │  │
│  │         │ Supervisor      │       │ A2A 요청        │                │  │
│  │         │ → A2A Agents    │       │ → Coordinator   │                │  │
│  │         └────────┬────────┘       └────────┬────────┘                │  │
│  │                  │                         │                          │  │
│  └──────────────────┼─────────────────────────┼──────────────────────────┘  │
│                     │                         │                             │
│                     └────────────┬────────────┘                             │
│                                  │                                          │
│                                  ↓                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                                                                       │  │
│  │                    DEEP INSIGHT CORE (변경 없음)                       │  │
│  │                                                                       │  │
│  │      User Query ───→ Coordinator ───→ Planner ───→ Supervisor        │  │
│  │                                                          │            │  │
│  │                                            ┌─────────────┼─────────┐  │  │
│  │                                            ↓             ↓         ↓  │  │
│  │                                         Coder      Validator  Reporter│  │
│  │                                                                       │  │
│  │      A2A Agent로 등록: "deep-insight-agent"                           │  │
│  │      • 외부 에이전트가 분석/리포트 요청 가능                            │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 구현 로드맵

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         구현 로드맵                                       │
│                                                                         │
│  Phase 1: 기반 구축                                                      │
│  ├── A2A Gateway 컨테이너 생성 (Port 9000)                              │
│  ├── Agent Card JSON 정의                                               │
│  └── Supervisor에 a2a_gateway_tool 등록                                 │
│                                                                         │
│  Phase 2: 첫 번째 A2A 에이전트                                           │
│  ├── DataPipeline Agent를 A2A 서버로 구현                               │
│  ├── Gateway 라우팅 로직 구현                                            │
│  └── 엔드투엔드 테스트                                                   │
│                                                                         │
│  Phase 3: 역방향 흐름                                                    │
│  ├── Gateway Inbound Handler 구현                                       │
│  ├── Deep Insight를 A2A Agent로 등록                                    │
│  └── 양방향 통신 테스트                                                  │
│                                                                         │
│  Phase 4: 추가 에이전트                                                  │
│  ├── Text2SQL Agent 구현                                                │
│  ├── RAG Search Agent 구현                                              │
│  └── 멀티에이전트 협업 테스트                                            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. HOW: A2A 프로토콜 사양

### 4.1 프로토콜 핵심 사양

| 항목 | 사양 |
|------|------|
| **전송 프로토콜** | JSON-RPC 2.0 over HTTP |
| **포트** | 9000 (HTTP: 8080, MCP: 8000과 구분) |
| **마운트 경로** | `/` (루트 경로) |
| **Agent Card 경로** | `/.well-known/agent-card.json` |
| **아키텍처** | Stateless HTTP 서버 필수 |
| **플랫폼** | ARM64 컨테이너 |

### 4.2 필수 엔드포인트

| 엔드포인트 | 메서드 | 용도 |
|-----------|--------|------|
| `/` | POST | JSON-RPC 2.0 에이전트 통신 |
| `/.well-known/agent-card.json` | GET | 에이전트 검색 및 기능 광고 |
| `/ping` | GET | 헬스 체크 |

### 4.3 인증 방식

| 방식 | 설명 |
|------|------|
| **SigV4** | AWS 표준 서명 인증 |
| **OAuth 2.0** | Bearer 토큰 기반 인증 (Cognito 사용) |

**세션 관리 헤더:**
```
Authorization: Bearer <oauth-token>
X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <session-id>
```

### 4.4 에러 처리

A2A 프로토콜은 JSON-RPC 2.0 에러 형식을 사용합니다. HTTP 상태 코드는 항상 200이며, 에러는 JSON-RPC error 객체로 반환됩니다.

> **참고**: 구체적인 에러 코드 매핑은 [AWS 공식 문서](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html)를 참조하세요.

---

## 5. HOW: Agent Card 정의

### 5.1 Agent Card 개요

Agent Card는 에이전트의 identity, capabilities, endpoints, authentication 정보를 포함하는 JSON 메타데이터입니다. `/.well-known/agent-card.json` 경로에서 제공되며, 다른 에이전트가 이를 조회하여 기능을 파악합니다.

> **참고**: 정확한 스키마는 [AWS 공식 문서](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html)를 참조하세요.

### 5.2 일반 Agent Card 예시 (참고용)

```json
{
  "name": "에이전트 이름",
  "description": "에이전트 설명",
  "version": "1.0.0",
  "url": "https://bedrock-agentcore.region.amazonaws.com/runtimes/agent-arn/invocations/",
  "capabilities": {
    "streaming": true
  },
  "skills": [
    {
      "id": "skill-id",
      "name": "스킬 이름",
      "description": "스킬 설명"
    }
  ]
}
```

### 5.3 Deep Insight Agent Card

```json
{
  "name": "deep-insight-agent",
  "description": "멀티에이전트 데이터 분석 및 리포트 생성 시스템",
  "version": "1.0.0",
  "url": "https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/deep-insight-arn/invocations/",
  "protocolVersion": "0.3.0",
  "preferredTransport": "JSONRPC",
  "capabilities": {
    "streaming": true
  },
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "skills": [
    {
      "id": "full_workflow",
      "name": "전체 워크플로우",
      "description": "데이터 분석 + 리포트 생성 전체 파이프라인",
      "tags": ["analysis", "report", "visualization"]
    },
    {
      "id": "analyze_data",
      "name": "데이터 분석",
      "description": "통계 분석 및 시각화 (Coder Agent)",
      "tags": ["analysis", "statistics", "charts"]
    },
    {
      "id": "generate_report",
      "name": "리포트 생성",
      "description": "DOCX 리포트 생성 (Reporter Agent)",
      "tags": ["report", "docx"]
    },
    {
      "id": "validate_results",
      "name": "결과 검증",
      "description": "분석 결과 검증 (Validator Agent)",
      "tags": ["validation", "quality"]
    }
  ]
}
```

---

## 6. HOW: JSON-RPC 메시지 형식

### 6.1 개요

A2A 프로토콜은 JSON-RPC 2.0을 사용하여 에이전트 간 통신합니다.

> **참고**: 정확한 메시지 형식은 [AWS 공식 문서](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html)를 참조하세요.

### 6.2 요청 예시 (참고용)

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {
          "kind": "text",
          "text": "메시지 내용"
        }
      ],
      "messageId": "unique-message-id"
    }
  }
}
```

### 6.3 응답 예시 (참고용)

```json
{
  "jsonrpc": "2.0",
  "id": "req-001",
  "result": {
    "artifacts": [...]
  }
}
```

---

## 7. HOW: 구현 코드

### 7.1 A2A 서버 구현 예제 (Strands SDK)

> **참고**: 최신 구현 방법은 [AWS 공식 문서](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a.html)를 참조하세요.

```python
import logging
import os
from strands import Agent
from strands.multiagent.a2a import A2AServer
import uvicorn
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)

# 환경변수에서 런타임 URL 가져오기
runtime_url = os.environ.get('AGENTCORE_RUNTIME_URL', 'http://127.0.0.1:9000/')

# 에이전트 생성
strands_agent = Agent(
    name="My A2A Agent",
    description="A2A 프로토콜을 지원하는 에이전트",
    tools=[],  # 도구 목록
    callback_handler=None
)

host, port = "0.0.0.0", 9000

# A2A 서버로 래핑
a2a_server = A2AServer(
    agent=strands_agent,
    http_url=runtime_url,
    serve_at_root=True
)

app = FastAPI()

@app.get("/ping")
def ping():
    return {"status": "healthy"}

app.mount("/", a2a_server.to_fastapi_app())

if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
```

### 7.2 배포 명령어

```bash
# 1. 필수 패키지 설치
pip install strands-agents[a2a]
pip install bedrock-agentcore
pip install bedrock-agentcore-starter-toolkit

# 2. A2A 프로토콜로 구성
agentcore configure -e my_a2a_server.py --protocol A2A

# 3. AWS에 배포
agentcore launch
```

---

## 참고 자료

- [AWS 블로그: AgentCore Runtime A2A 프로토콜 소개](https://aws.amazon.com/blogs/machine-learning/introducing-agent-to-agent-protocol-support-in-amazon-bedrock-agentcore-runtime/)
- [AWS 문서: A2A 서버 배포 가이드](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a.html)
- [AWS 문서: A2A 프로토콜 계약](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html)
- [Large File Processing Architecture](./large_file_processing_architecture.md)

---

## 관련 문서

- `large_file_processing_architecture.md` - DataPipeline Agent 상세 설계
- (예정) `text2sql_agent_design.md` - Text2SQL Agent 상세 설계
- (예정) `a2a_gateway_implementation.md` - Gateway 구현 상세
