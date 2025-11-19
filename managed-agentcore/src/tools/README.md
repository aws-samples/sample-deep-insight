# Tools Directory

이 디렉토리는 멀티에이전트 워크플로우에서 사용되는 도구(Tool) 모듈들을 포함합니다.

## 📂 파일 구조 및 용도

### 🛠️ 기본 실행 도구 (Local Execution Tools)

#### `python_repl_tool.py`
- **용도**: Python 코드를 로컬 환경에서 실행하는 REPL 도구
- **기능**:
  - Python 코드 실행 및 결과 반환
  - 변수 상태 유지 (세션 기반)
  - 에러 처리 및 로깅
- **사용처**: coder_agent_tool, reporter_agent_tool, validator_agent_tool

#### `bash_tool.py`
- **용도**: Bash 명령어를 로컬 환경에서 실행하는 도구
- **기능**:
  - Shell 명령어 실행
  - 표준 출력/에러 캡처
  - 타임아웃 처리
- **사용처**: coder_agent_tool, reporter_agent_tool, validator_agent_tool

### 🚀 Fargate 실행 도구 (Remote Execution Tools)

#### `fargate_python_tool.py`
- **용도**: Python 코드를 Fargate 컨테이너에서 실행
- **기능**:
  - 원격 Python 코드 실행
  - S3 파일 동기화
  - 세션 기반 상태 관리
- **사용처**: coder_agent_fargate_tool, reporter_agent_fargate_tool, validator_agent_fargate_tool

#### `fargate_bash_tool.py`
- **용도**: Bash 명령어를 Fargate 컨테이너에서 실행
- **기능**:
  - 원격 Shell 명령어 실행
  - 작업 디렉토리 관리
  - 실행 결과 스트리밍
- **사용처**: coder_agent_fargate_tool, reporter_agent_fargate_tool, validator_agent_fargate_tool

#### `fargate_session_manager.py`
- **용도**: Fargate 태스크 세션 관리
- **기능**:
  - ECS 태스크 생성/종료
  - 세션별 고유 ID 관리
  - 헬스체크 (5분 타임아웃)
  - 리소스 정리
- **사용처**: main.py, fargate_python_tool, fargate_bash_tool

### 🤖 에이전트 도구 - 로컬 버전

#### `coder_agent_tool.py`
- **용도**: 코드 작성 및 데이터 분석을 수행하는 코더 에이전트
- **기능**:
  - 데이터 분석 코드 생성
  - Python/Bash 명령 실행
  - 결과 해석 및 보고
- **도구**: python_repl_tool, bash_tool

#### `validator_agent_tool.py`
- **용도**: 계산 결과를 검증하는 검증 에이전트
- **기능**:
  - 계산 정확도 검증
  - 데이터 무결성 확인
  - 검증 보고서 생성
- **도구**: python_repl_tool, bash_tool

#### `reporter_agent_tool.py`
- **용도**: 분석 결과를 보고서로 작성하는 리포터 에이전트
- **기능**:
  - PDF 보고서 생성
  - 시각화 차트 생성
  - 한글 지원 보고서 작성
- **도구**: python_repl_tool, bash_tool

#### `tracker_agent_tool.py`
- **용도**: 작업 진행 상황을 추적하는 트래커 에이전트
- **기능**:
  - 워크플로우 상태 추적
  - 진행 상황 모니터링
  - 메타데이터 관리
- **사용처**: src/graph/nodes.py

### 🤖 에이전트 도구 - Fargate 버전

#### `coder_agent_fargate_tool.py`
- **용도**: Fargate에서 실행되는 코더 에이전트
- **기능**:
  - 원격 데이터 분석
  - 대용량 데이터 처리
  - S3 결과 저장
- **도구**: fargate_python_tool, fargate_bash_tool

#### `validator_agent_fargate_tool.py`
- **용도**: Fargate에서 실행되는 검증 에이전트
- **기능**:
  - 원격 계산 검증
  - 분산 검증 작업
  - 검증 결과 S3 저장
- **도구**: fargate_python_tool, fargate_bash_tool

#### `reporter_agent_fargate_tool.py`
- **용도**: Fargate에서 실행되는 리포터 에이전트
- **기능**:
  - 원격 PDF 생성
  - 대용량 보고서 처리
  - 결과물 S3 업로드
- **도구**: fargate_python_tool, fargate_bash_tool

### 🔧 유틸리티

#### `decorators.py`
- **용도**: 공통 데코레이터 함수들
- **기능**:
  - `@log_io`: 입출력 로깅
  - 성능 측정
  - 에러 처리 래퍼
- **사용처**: bash_tool, python_repl_tool, fargate_bash_tool, fargate_python_tool


## 🔄 실행 모드

### Local Mode (로컬 실행)
```
coder_agent_tool → python_repl_tool, bash_tool
validator_agent_tool → python_repl_tool, bash_tool
reporter_agent_tool → python_repl_tool, bash_tool
```

### Fargate Mode (원격 실행)
```
coder_agent_fargate_tool → fargate_python_tool, fargate_bash_tool → fargate_session_manager → ECS/Fargate
validator_agent_fargate_tool → fargate_python_tool, fargate_bash_tool → fargate_session_manager → ECS/Fargate
reporter_agent_fargate_tool → fargate_python_tool, fargate_bash_tool → fargate_session_manager → ECS/Fargate
```

## 📝 사용 예시

### 로컬 에이전트 사용
```python
from src.tools import coder_agent_tool

result = await coder_agent_tool.handle_coder_agent_tool(
    task="데이터 분석 수행"
)
```

### Fargate 에이전트 사용
```python
from src.tools import coder_agent_fargate_tool

result = await coder_agent_fargate_tool.handle_coder_agent_fargate_tool(
    task="대용량 데이터 분석 수행"
)
```

## ⚠️ 주의사항

- Fargate 도구들은 AWS 자격 증명이 필요합니다
- 로컬 도구는 시스템 리소스를 직접 사용합니다
- Fargate 도구는 네트워크 지연이 있을 수 있습니다
- 모든 에이전트 도구는 비동기(async) 함수입니다