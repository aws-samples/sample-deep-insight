# Changelog

## [3.0.0] - 2025-11-04 - Phase 3 완료

### Added
- **Phase 3 배포 스크립트**: `create_agentcore_runtime_vpc.py`
  - Native `Runtime.launch()` 메서드 사용
  - VPC 설정 자동화
  - CodeBuild Role 자동 생성/재사용

- **coordinator.md 자동 포함**: `setup/patch_dockerignore_template.sh`
  - toolkit의 dockerignore.template 자동 패치
  - `src/prompts/*.md` 파일들이 Docker 이미지에 포함됨

- **의존성 업데이트**:
  - boto3: 1.40.10 → 1.40.65 (VPC 지원)
  - bedrock-agentcore-starter-toolkit: 0.1.8 → 0.1.28 (VPC 지원)
  - requirements.txt, setup/pyproject.toml 모두 업데이트

- **문서**:
  - `production_deployment/PHASE3_QUICKSTART.md` - Phase 3 빠른 시작 가이드
  - `production_deployment/docs/archive/UPDATE_PHASE1_IAM.md` - IAM 업데이트 가이드 (선택 사항)
  - README.md Phase 3 섹션 업데이트

- **자동화 스크립트**:
  - `scripts/phase1/update-iam.sh` - IAM Stack 업데이트 자동화

### Changed
- **create_agentcore_runtime_vpc.py**: 7단계 → 5단계로 간소화
  - AWS CLI 우회 방식 제거
  - Native configure() + launch() 사용
  - Agent name 고정: `deep_insight_runtime_vpc` (timestamp 제거)

- **CloudFormation 템플릿**:
  - `cloudformation/nested/iam.yaml`: CodeBuildExecutionRole 추가 (선택 사항)

### Fixed
- **coordinator.md FileNotFoundError 해결**:
  - 근본 원인: toolkit의 dockerignore.template이 *.md 제외
  - 해결: patch script로 `!src/prompts/*.md` 추가

- **langchain import 경로 수정**:
  - `src/utils/strands_sdk_utils.py`: langchain 0.3.x 호환

### Removed
- `01_test_launch_with_latest_boto3.py` - 테스트 파일 삭제 (production 코드로 통합)

---

## [2.0.0] - 2025-11-02 - Phase 2 완료

### Added
- **Phase 2 CloudFormation**: Three-Stage 배포
  - ECR Repository (DeletionPolicy: Retain)
  - ECS Cluster (Container Insights)
  - Task Definition (2 vCPU, 4GB RAM)
  - CloudWatch Log Group

- **Three-Stage 배포 프로세스**:
  1. ECR 생성 (DeployECS=false)
  2. Docker 빌드 + 푸시
  3. Full Stack 배포 (DeployECS=true)

- **스크립트**:
  - `scripts/phase2/deploy.sh` - Three-Stage 자동 배포
  - `scripts/phase2/verify.sh` - 12개 항목 검증
  - `scripts/phase2/cleanup.sh` - CloudFormation-centric cleanup

### Fixed
- ECR Repository 충돌 문제 완전 해결 (Infrastructure as Code)

---

## [1.0.0] - 2025-10-20 - Phase 1 완료

### Added
- **Phase 1 CloudFormation**: Nested Stacks 아키텍처
  - VPC (10.0.0.0/16)
  - Private/Public Subnets (Multi-AZ)
  - NAT Gateway, Internet Gateway
  - Security Groups (4개)
  - VPC Endpoints (6개)
  - Internal ALB
  - IAM Roles

- **스크립트**:
  - `scripts/phase1/deploy.sh` - Phase 1 자동 배포
  - `scripts/phase1/verify.sh` - 23개 항목 검증
  - `scripts/phase1/cleanup.sh` - 리소스 정리
  - `scripts/phase1/monitor.sh` - 실시간 모니터링

- **문서**:
  - `README.md` - 메인 가이드
  - `DEPLOYMENT_WORKFLOW.md` - 두 계정 워크플로우
  - `docs/STEP_BY_STEP_GUIDE.md` - 단계별 가이드
  - `docs/CLOUDFORMATION_GUIDE.md` - CloudFormation 상세
  - `docs/00_OVERVIEW.md` - 아키텍처 개요

---

## 주요 마일스톤

- **2025-11-04**: Phase 3 완료 - AgentCore Runtime 배포 자동화
- **2025-11-02**: Phase 2 완료 - Fargate Runtime Three-Stage 배포
- **2025-10-20**: Phase 1 완료 - VPC Infrastructure Nested Stacks
- **2025-10-12**: coordinator.md 문제 해결
- **2025-10-11**: Fargate Runtime v19 배포 (Exception handling)
- **2025-10-07**: Keep-Alive 제거로 GeneratorExit 해결

---

## 업그레이드 가이드

### 1.x → 2.x
Phase 2 배포:
```bash
cd production_deployment
./scripts/phase2/deploy.sh prod
```

### 2.x → 3.x
Phase 3 배포:
```bash
cd setup
uv sync
./patch_dockerignore_template.sh

cd ..
python3 create_agentcore_runtime_vpc.py
```

---

**참고**: 상세한 변경 내용은 각 버전의 문서를 참조하세요.
