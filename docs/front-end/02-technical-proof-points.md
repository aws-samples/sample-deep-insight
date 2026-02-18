
## Technical Proof Points — Deep Insight Front-end

이 문서는 01-plan.md 의 핵심 기술 요소가 실제로 구현 가능한지 검증하기 위한 PoC 목록입니다.

---

## Phase 1: A2A Protocol (local, toy agent) — 참고용

> A2A 는 Deferred 로 변경됨 (01-plan.md 참조). 기술 검증은 완료되어 추후 도입 시 재활용 가능.

### PoC 1. A2A Server & Client ✅

**상태:** 검증 완료 (2026-02-14)

- `strands-agents[a2a]` v1.26.0, `a2a-sdk` v0.3.22
- `A2AServer` 래핑, Agent Card, SDK 통신, Tool invocation 모두 정상
- 테스트: `poc/poc1-a2a-wrapper/test_a2a_server.py` (4/4), `poc/poc2-a2a-client/test_a2a_client.py` (4/4)

---

### PoC 2. A2A Streaming ✅

**상태:** 검증 완료 (2026-02-14)

- SSE 실시간 이벤트 수신 확인 (49개 이벤트, 2.098초)
- 테스트: `poc/poc3-a2a-streaming/test_a2a_streaming.py` (4/4)
- 재사용 클라이언트: `poc/poc3-a2a-streaming/a2a_stream_client.py`

---

### PoC 3. BFF SSE Relay ✅

**상태:** 검증 완료 (2026-02-15)

- FastAPI `StreamingResponse` 로 A2A SSE 를 브라우저에 중계 성공
- End-to-end: 브라우저 → BFF (8080) → A2A `message/stream` (9000) → BFF → 브라우저 (SSE)
- SSE 형식: `data: {"type":"artifact_update","text":"..."}\n\n`
- 43개 이벤트, 1.963초 — 실시간 incremental delivery 확인
- 테스트: `poc/poc3-bff-sse-relay/test_bff_sse_relay.py` (4/4)

---

## Phase 2: BFF → AgentCore Native Protocol

### PoC 4. BFF → AgentCore 연동 + HITL ✅

**상태:** 검증 완료 (2026-02-15)

- `boto3.invoke_agent_runtime()` → FastAPI `StreamingResponse` → 브라우저 SSE 중계 성공
- End-to-end: 브라우저 → BFF (8080) → boto3 → AgentCore Runtime → BFF → 브라우저 (SSE)
- 수신 확인된 이벤트 타입: `agent_text_stream`, `agent_reasoning_stream`, `agent_usage_stream`, `plan_review_request`, `plan_review_keepalive`
- HITL: `plan_review_request` 이벤트 감지 → 브라우저에 plan 표시 확인, `/feedback` 엔드포인트로 S3 업로드
- Cold start ~2초, SSE 실시간 incremental delivery 확인
- 테스트: `poc/poc4-bff-agentcore/test_bff_agentcore.py` (3/4 — feedback endpoint 미실행, 핵심 streaming 검증 완료)

---

## Phase 3: Single-Account Infrastructure (Backend Account)

### PoC 5. ALB Restricted Access + Web Page ✅

**상태:** 검증 완료 (2026-02-15)

- FastAPI 컨테이너 → ECS Fargate → ALB 웹 페이지 서빙 성공
- ALB SG: VPN NAT IP 대역 제한 → VPN 접속 시 접근 성공, 미접속 시 차단 확인
- 테스트: `poc/poc5-alb-ecs-webapp/` (app.py, deploy.sh, cleanup.sh)

**트러블슈팅:**

1. **Docker 아키텍처 불일치** — ARM 빌드 → x86_64 Fargate 에서 `exec format error`. 해결: `docker buildx --platform linux/amd64` + QEMU
2. **CloudWatch Log Group 권한** — `AmazonECSTaskExecutionRolePolicy` 에 `logs:CreateLogGroup` 미포함. 해결: 인라인 정책 추가
3. **VPN IP ≠ NAT IP** — VPN 인터페이스 IP 와 실제 NAT IP 가 다름. 해결: VPC Flow Logs 로 실제 source IP 확인

---

## 검증 순서

```
Phase 1: A2A Protocol — 참고용 (Deferred)
  PoC 1 (A2A server & client) ✅
    └─► PoC 2 (A2A streaming) ✅
          └─► PoC 3 (BFF SSE relay) ✅

Phase 2: BFF → AgentCore Native Protocol
  PoC 4 (BFF → AgentCore + HITL) ✅

Phase 3: Single-Account Infrastructure (Backend Account)
  PoC 5 (ALB restricted access + web page) ✅
```
