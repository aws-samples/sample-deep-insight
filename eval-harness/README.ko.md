# Deep Insight Eval Harness

**→ [메인 README](../README.md)로 돌아가기** · [English](README.md) | **한국어**

Deep Insight의 자동 채점표입니다. 코드, 프롬프트, 모델을 바꿨을 때 "보고서가
더 나아 보인다" 대신 숫자로 두 가지에 답합니다.

1. **핵심 기능이 여전히 동작하는가?** → 실행마다 PASS / FAIL
2. **무엇이 얼마나 좋아지거나 나빠졌는가?** → 변경 전후 비교표

이 버전은 규칙으로만 채점합니다. 모델 호출이 없으므로 채점 비용도 없습니다.
읽는 주체가 필요한 검사(정답 키 fact check, LLM judge, pairwise judge)는 이어지는
PR에서 추가합니다.

## 구성

| 구성 요소 | 하는 일 |
|---|---|
| **Runner** `run_eval.py` | 배포된 런타임에 정해진 분석 요청을 보내고, 계획 검토를 사람 없이 자동 승인하고, 보고서·인용·코드 실행 로그·토큰 사용량을 저장합니다 |
| **Grader** `grade.py` | 실행 하나를 채점합니다: 산출물, 숫자 정확도, 비용, 시간 → PASS / FAIL이 담긴 `scores.json` |
| **Comparer** `compare.py` | 두 버전을 나란히 놓고 지표별 평균 ± 표준편차와 차이를 보여줍니다 |
| **정적 검사** `pytest` | AWS 없이 몇 초: 프롬프트 템플릿 렌더링, 모델 요청 필드 유효성, 채점기가 심어둔 결함을 실제로 잡는지 |

`compare.py` 출력 예시:

```
                          baseline        opus55          Δ
printed value = citation  100.0%          100.0%          +0.0%p
recompute matches CSV     100.0%          100.0%          +0.0%p
cost                      $10.20          $8.50           -17% ▲ better
duration                  1920s           1680s           -12% ▲ better
```

## 폴더 구조

```
eval-harness/
├── run_eval.py, grade.py, compare.py    평소에 쓰는 명령
├── eval_runtime.py                      평가 런타임 설정
├── component_eval.py                    컴포넌트 실행: 오류를 심고 Validator만 실행
├── graders/       규칙 기반 채점 모듈과 cost.py
├── config/        scenarios.yaml, pricing.yaml, runtime_configs.yaml,
│                  eval.env (git 제외, 로컬 전용)
├── tests/         pytest 테스트와 fixture
└── eval_results/  모든 실행, 채점, 비교 결과 (git 제외)
```

모든 명령은 `eval-harness/`에서 실행합니다. `config/scenarios.yaml`의 경로는
`eval-harness/` 기준입니다.

## 동작 방식: 단계와 파일

실행은 두 종류입니다. 둘 다 eval 런타임과 같은 시나리오를 쓰고, 무엇을 호출하고 무엇을
채점하는지가 다릅니다.

| 실행 | 명령 | 무엇이 도는가 | 채점 | 비용 |
|---|---|---|---|---|
| **전체 실행** | `run_eval.py` | 시나리오 요청에 대한 전체 워크플로(Coordinator → Planner → Coder → Validator → Reporter → Auditor) | `grade.py` 규칙 채점기. 이어서 `compare.py` | 실행당 $4~6 |
| **컴포넌트 실행** | `component_eval.py validator` | 저장된 전체 실행의 결과물에 오류를 심고 Validator만 실행([아래](#컴포넌트-실행-에이전트-하나-심어둔-오류)) | 규칙 검사: 심은 오류마다 잡음/놓침/검사 안 함, 오경보, 값 변경 | 실행당 약 $1.3~2 |

이 절의 나머지는 전체 실행에 대한 설명입니다.

```
config/scenarios.yaml + jungle-market CSV
        │
        ▼  1. run_eval.py            평가 런타임 호출, 계획 검토 자동 승인
eval_results/<tag>/<run>/            events.jsonl, run.json, usage.json, config.json, artifacts/
        │
        ▼  2. grade.py               (run_eval.py가 실행마다 자동으로 호출)
        │     graders/*.py           산출물, 인용, 재계산, 보고서, 비용          → scores.json
        ▼
scores.json  (core_pass: PASS / FAIL)
        │
        └─▶ 3. compare.py            태그 간 비교표             → 화면 출력 또는 compare.md
```

| 단계 | 명령 | 읽는 것 | 쓰는 것 | 유료 |
|---|---|---|---|---|
| 1. 실행 | `run_eval.py --scenario <s> --tag <t>` | `config/scenarios.yaml`, 시나리오의 `upload` 파일(S3로 전송), `config/eval.env` | `eval_results/<t>/<s>-<time>-<n>/`: `events.jsonl`, `run.json`, `usage.json`, `config.json`, `s3/`, `artifacts/` | 예: 런타임(에이전트, Fargate) |
| 2. 채점 | `grade.py <run_dir> --scenario <s>` (1단계 후 자동) | `artifacts/`, CSV, `config/pricing.yaml`, 시나리오의 `pass:` | `scores.json` | 아니요 |
| 3. 비교 | `compare.py <tag> <tag> [--out compare.md]` | `*/scores.json`, `run.json`, `config.json` | 비교표 | 아니요 |

## 데이터셋: 개발용 둘, 따로 떼어둔 하나

`config/scenarios.yaml`의 시나리오마다 `split`이 있습니다.

| Split | 데이터셋 | 용도 |
|---|---|---|
| `dev` | jungle_market, yummy_food | 프롬프트와 통과 기준을 이 데이터에 맞춰 조정합니다 |
| `test` | moon_market | 릴리스 전에만 확인합니다. 이 데이터에 맞춰 조정하는 것이 없으므로, 개발셋에만 맞춘 변경은 여기서 드러납니다 |

- **jungle_market** (`deep-insight-web/sample_data/jungle-market/`): 8개 도시의
  2주치 식료품 주문 데이터로, 얕은 분석이 틀리게 되는 패턴을 일부러 심어뒀습니다
  (매출 1위 도시를 바꾸는 중복 행, 쿠폰의 심슨의 역설, 품절, 할인 문턱 몰림,
  프로모션 후광 효과).
- **yummy_food** (`managed-agentcore/data/yummy_food/<lang>/`): 4개 매체 × 6개
  상품의 한 달치 일별 광고 성과입니다. 정제할 것은 없고, 함정은 광고 지표를 집계하는
  방식에 있습니다 (ROAS 컬럼을 평균하면 1위 매체가 바뀌고, CTR이 가장 높은 매체가
  ROAS는 가장 낮고, 두 배로 늘린 예산의 한계 수익은 훨씬 낮음).
- **moon_market** (`managed-agentcore/data/moon_market/<lang>/`): 서울 10개 구의
  2주치 단일 상품 주문 데이터입니다. 시나리오의 통과 기준은 개발셋 값을 그대로 쓰고,
  다시 정할 때도 개발셋 결과로만 정합니다.

테스트 시나리오는 `run_eval.py`에서 `--allow-test`가 있어야 돌고, `compare.py`는
dev와 test를 다른 섹션으로 보고합니다. 테스트 결과는 릴리스 여부를 정할 때 보고, 다음
변경을 고를 때는 보지 마세요. 그 결과에 맞춰 조정하기 시작하면 세 번째 개발셋이 될
뿐입니다.

## 작업 흐름

```bash
# 0. 최초 1회: 설정 (아래 참고)
# 1. 현재 버전 측정 → 기준점
.venv/bin/python run_eval.py --scenario jungle_market --repeat 3 --tag baseline
# 2. 코드 / 프롬프트 / 모델 변경, 런타임 재배포, 다시 측정
.venv/bin/python run_eval.py --scenario jungle_market --repeat 3 --tag my-change
# 3. 비교
.venv/bin/python compare.py eval_results/baseline eval_results/my-change
```

릴리스 전에는 같은 버전을 테스트셋으로도 돌립니다.

```bash
.venv/bin/python run_eval.py --scenario moon_market_kr --repeat 3 --tag my-change-test --allow-test
.venv/bin/python compare.py eval_results/baseline-test eval_results/my-change-test --split test
```

실행마다 실제 비용이 들고(`jungle_market_simple`은 몇 달러, 전체 요청은 그 이상)
15~40분이 걸립니다. 스모크 테스트만 필요하면 `jungle_market_simple`부터 돌리세요.

## 설정

```bash
cd eval-harness
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python -r requirements.txt
```

Runner는 `managed-agentcore/.env`(배포 스크립트가 작성)에서 `RUNTIME_ARN`,
`AWS_REGION`, `S3_BUCKET_NAME`을 읽거나, `--runtime-arn`, `--region`, `--bucket`을
받습니다.

## 정적 검사 (AWS 불필요)

```bash
.venv/bin/python -m pytest -q
```

`test_no_legacy_human_stop_sequence`는 알려진 버그를 기록하는 예상된 실패(`xfail`,
strict)입니다. 버그가 고쳐지면 오류로 바뀌므로, 고칠 때 마커도 함께 지웁니다.

## 컴포넌트 실행: 에이전트 하나, 심어둔 오류

전체 실행은 에이전트를 한꺼번에 채점합니다. Validator가 틀린 계산을 잡는지 보려면
틀린 계산이 있어야 하는데, 보통 실행에서는 Coder의 숫자가 맞습니다.
`component_eval.py`는 저장된 실행의 결과물에 오류를 심고 Validator만 돌립니다.

```bash
.venv/bin/python eval_runtime.py enable-components        # 최초 1회, eval 런타임에만
.venv/bin/python component_eval.py validator --from eval_results/baseline/<run> --plant 6 --tag comp-validator
```

중요도 high인 계산 최대 `--plant`개의 값을 10% 바꿉니다. 절반은 원본 CSV 기반이면서
재계산으로 맞다고 확인된 것, 절반은 Coder가 만든 파생 파일 기반입니다. 결과물을
Validator 시작 시점 상태로 올리고 eval 런타임을 `component: validator`로
호출합니다(`managed-agentcore/src/graph/component.py`). Validator가 쓴
`citations.json`에서 심은 오류마다 잡음(needs_review), 놓침(verified), 검사 안 함을
세고, 맞는 값을 needs_review로 표시한 오경보와 심은 값을 바꾼 경우(표시만 해야 하고
고치면 안 됨)도 셉니다.

런타임은 환경변수에 `EVAL_COMPONENT_MODE=1`이 없으면 컴포넌트 실행을 거부합니다.
두 런타임은 같은 이미지를 쓰고, 이 변수는 `eval_runtime.py`가 eval 런타임에만
넣습니다. 런타임은 `component: reporter`도 받지만, 그 하네스는 아직 없습니다.

## 시나리오

`config/scenarios.yaml`은 데이터셋 × 요청 쌍을 정의합니다.

| 시나리오 | Split | 용도 |
|---|---|---|
| `jungle_market` | dev | 메인 벤치마크: 열린 성장 기회 요청 (한국어) |
| `jungle_market_en` | dev | 같은 요청을 영어로 |
| `jungle_market_simple` | dev | 저렴한 스모크 테스트: 합계, 객단가, 카테고리 비중 |
| `jungle_market_revision` | dev | simple과 같지만 먼저 계획 수정을 한 번 요청 (`planner_revise` 검사) |
| `yummy_food_kr` | dev | 매체·카테고리·상품별 광고 성과와 광고비를 더 잘 쓰는 전략 3가지 |
| `yummy_food_en` | dev | 같은 요청을 영문판 데이터로 |
| `moon_market_kr` | test | moon_market에 대한 열린 성장 기회 요청 (`--allow-test` 필요) |
| `moon_market_en` | test | 같은 요청을 영어로 (`--allow-test` 필요) |

Runner는 시나리오의 `upload` 파일(CSV와 `column_definitions.json`)을 웹 앱이 업로드를
두는 `s3://<bucket>/uploads/eval-<scenario>/`에 올리고, 그 경로를 데이터 디렉터리로
넘깁니다. 그래서 데이터셋이 런타임 이미지에 들어 있을 필요가 없습니다.

시나리오마다 `pass:` 블록이 core_pass 기준을 정합니다.

| 키 | 의미 |
|---|---|
| `min_recompute` | CSV에서 다시 계산돼야 하는 계산 개수 |
| `min_cited_checked` | 비교돼야 하는 "숫자 [n]" 쌍의 개수 |

느슨한 기본값에서 시작해 실제 실행으로 정합니다: 정상적인 베이스라인 실행에서 나온
가장 낮은 개수의 절반.

## 평가 런타임: 사용자 런타임에서 평가하지 않기

웹 앱은 AgentCore 런타임 `deep_insight_runtime_vpc`에서 돌아갑니다. 평가는 별도의
`deep_insight_eval_runtime`에서 돌려서, 실험으로 모델을 바꾸거나 이미지를 시험해도
사용자가 받는 결과가 바뀌지 않고, 평가 부하가 사용자 런타임에 걸리지 않게 합니다.

| | 사용자 런타임 | 평가 런타임 |
|---|---|---|
| 호출하는 쪽 | 웹 앱 (그리고 `02_invoke_agentcore_runtime_vpc.py`) | `run_eval.py`만 |
| 모델 | `managed-agentcore/.env`, 배포 시 설정 | `eval_runtime.py set-models <preset>` (`config/runtime_configs.yaml`) |
| 이미지 | `…deep_insight_runtime_vpc:latest`, 배포할 때마다 바뀜 | digest로 고정, `set-image`로만 바뀜 |
| 공유 | role, VPC, ECS 클러스터, ALB, Fargate task definition, S3 버킷 | 같음 |

두 런타임 사이에 세션이 넘어가지 않습니다. Fargate 컨테이너로 가는 모든 요청에 세션
ID가 붙고, 코드 실행기는 불일치하면 403으로 거부합니다(`docs/incidents/`의
2026-02-22 런타임 교차 사고에 대한 수정). 여전히 공유되는 건 용량(Fargate task, ALB,
Bedrock 할당량)이므로, 긴 평가 배치는 사용이 많은 시간을 피하세요.

**최초 1회 설정** (사용자 런타임이 배포돼 있어야 함, `managed-agentcore/` 1~3단계):

```bash
.venv/bin/python eval_runtime.py create    # 사용자 런타임을 복사, ARN → config/eval.env (git 제외)
.venv/bin/python eval_runtime.py status    # 두 런타임의 버전, 이미지, 모델
```

**평소 사용**

```bash
# 사용자가 지금 쓰는 버전 측정
.venv/bin/python eval_runtime.py set-image          # 사용자 런타임의 현재 이미지를 따라감
.venv/bin/python eval_runtime.py set-models users
.venv/bin/python run_eval.py --scenario jungle_market --repeat 5 --tag baseline-<date>

# 사용자에게 영향 없이 모델 구성 시험
.venv/bin/python eval_runtime.py set-models sonnet45-workers
.venv/bin/python run_eval.py --scenario jungle_market --repeat 5 --tag sonnet45
.venv/bin/python eval_runtime.py set-models users

# 사용자에게 가기 전에 후보 이미지 시험: 별도 태그로 빌드·푸시한 뒤
.venv/bin/python eval_runtime.py set-image <account>.dkr.ecr.<region>.amazonaws.com/<repo>:<candidate-tag>
```

`run_eval.py`는 `config/eval.env`의 `EVAL_RUNTIME_ARN`을 쓰고, `--allow-users-runtime` 없이는
사용자 런타임(`managed-agentcore/.env`의 `RUNTIME_ARN`)을 거부합니다. 2026-06-11 이후
만든 런타임은 `requireServiceS3Endpoint`를 설정할 수 없어서, 사용자 런타임은 이 값이
켜져 있지만 평가 런타임은 AgentCore 기본값을 씁니다. 어느 쪽이든 S3 접근은 같은 VPC를
거칩니다. `eval_runtime.py delete`로 지울 수 있습니다.

## 평가 런타임에서 실행

```bash
.venv/bin/python run_eval.py --scenario jungle_market --repeat 3 --tag baseline
# 한 태그로 병렬 배치: 배치마다 반복 번호를 따로 지정
.venv/bin/python run_eval.py --scenario jungle_market --repeat 2 --first-repeat 4 --tag baseline
```

실행마다 `eval_results/<tag>/<scenario>-<timestamp>-<n>/`에 저장됩니다:
`events.jsonl`(스트리밍된 모든 이벤트), `run.json`(상태, 시간), `usage.json`,
`config.json`(git SHA + 런타임의 모델 ID), `s3/` 아래 내려받은 세션(`artifacts/`가
산출물을 가리킴), `scores.json`.

- 계획 검토는 런타임이 폴링하는 S3 피드백 파일을 써서 답합니다
  (`02_invoke_agentcore_runtime_vpc.py`와 같은 방식). 그래서 사람을 기다리지 않고 300초
  타임아웃도 없습니다. 시나리오의 `hitl` 목록이 있으면 정해진 수정 요청을 먼저 보냅니다.
- 토큰 사용량은 스트림의 `usage_metadata` 이벤트를 합산합니다. 런타임 자체의
  `token_usage.json`과 일치합니다.
- 모델 ID는 로컬 체크아웃이 아니라 **런타임의** 환경에서 가져옵니다. 그래서 모델 구성을
  비교하려면 재배포가 필요합니다(또는 구성마다 런타임 하나).
- 런타임은 도구 호출을 스트리밍하지 않습니다. `agent_calls`는 `usage_metadata` 이벤트
  수(에이전트 호출당 하나)를 세고, 코드 실패는 실행기의 `debug/execution_*.json`에서
  가져옵니다.
- 런타임이 session_id를 알려주지 않으면, 버킷의 "가장 최근 세션"(다른 사람 것일 수 있음)을
  채점하지 않고 `session_unresolved`로 실패합니다. 아무도 쓰지 않는 버킷에서는
  `--allow-session-fallback`으로 추측을 되살릴 수 있고, 경고가 기록됩니다.

## 태그 비교

```bash
.venv/bin/python compare.py eval_results/baseline eval_results/candidate --out compare.md
```

시나리오마다 표 하나:

- **통과/실패 지표**(core_pass, 필수 산출물, Auditor 통과)는 95% Wilson 구간과 함께
  비율로 보여줍니다: `67% [21–94%] (2/3)`.
- **그 밖의 지표**는 평균 ± 표준편차(n)로 보여줍니다.
- 첫 태그 대비 **Δ**에는 95% bootstrap 구간이 붙고, ▲/▼는 **양쪽 각 5회 이상**이고
  구간이 0을 포함하지 않을 때만 붙습니다. 3회로는 bootstrap이 너무 거칠어 의미가
  없습니다: 상수 시퀀스는 자기 자신으로만 재표집되므로 (0, 0, 0) 대 (1, 1, 1)도 폭이 0인
  구간이 나옵니다. 5회 미만이면 Δ와 구간을 표시 없이 출력하니 참고로만 보고, 변화를
  판단하기 전에 `--repeat 5`를 쓰세요.
- **pass^k**: k번 연속 모두 통과할 확률. 평균 통과율보다 신뢰성을 더 잘 보여줍니다.
- 한 태그 안에 git SHA, 런타임 버전, 모델 구성이 섞였으면 ⚠ 줄이 나옵니다. 비교 전에
  태그를 나누세요.

에이전트별 비용도 각 에이전트가 쓴 모델과 함께 출력합니다.

## 실행 채점

```bash
.venv/bin/python grade.py <run_dir> --scenario jungle_market
```

`<run_dir>`에는 `artifacts/` 폴더가 있어야 합니다
(`s3://<bucket>/deep-insight/fargate_sessions/<session_id>/`에서 내려받은 것).
`<run_dir>/scores.json`을 씁니다. 종료 코드 0 = core pass.

### 채점 항목

| 지표 | 의미 | 출처 |
|---|---|---|
| `all_required_ok` | 보고서 docx, citations.json, calculation_metadata.json, validation_report.txt가 있고 파싱됨 | `graders/artifacts.py` |
| `citation_value_match_rate` | citations.json 값 == calculation_metadata 값 | `graders/citations.py` |
| `recompute_match_rate`, `recompute_supported`, `recompute_unverified` | metadata 값을 원본 CSV에서 pandas로 다시 계산. 수식은 집계(SUM/AVG/MEAN/MEDIAN/MIN/MAX/COUNT/STD/TOTAL) 위의 산술로 읽고, 필터(`=`, `==`, `!=`, `IS NULL`, `NOT NULL`, 집계 안이나 뒤), 그룹(`GROUP BY`, `grouped by`, `by`, `col\|key`, 요일), 자리표시자(`cat`, `X`, `'{}'`)는 계산 설명에서 풉니다. 에이전트가 지어낸 이름(`cat_sales`, `daily_sum`)은 지원하지 않습니다. 설명에만 적힌 부분집합(열 값 1~3개, "아마존×건강식품 조합 ROAS")도 시도합니다. 설명에 그룹이 없으면 어떤 그룹과 맞기만 하면 되고(`recompute_lenient`), 하나도 안 맞으면 틀림이 아니라 `recompute_unverified`입니다. 완전 중복 행이 있는 파일은 중복을 뺀 상태로도 다시 계산합니다. 중복 제거가 올바른 분석이기 때문입니다(`recompute_dedup`) | `graders/recompute.py` |
| `cited_value_match_rate`, `cited_value_checked` | 보고서에서 `[n]` 바로 앞에 쓴 숫자가 인용 n과 같은지, 비교한 쌍의 개수 | `graders/report.py` |
| `broken_citation_refs` | 본문의 `[n]` 중 인용 n이 없는 것 | `graders/report.py` |
| `citation_inside_number` | 숫자, 범위, 시각 안에 들어간 `[n]`(`$111,065 [2].13`, `10 [1]~15%`). 값 검사는 마커 앞부분만 읽기 때문에 따로 셉니다. core_pass 실패 사유(#141) | `graders/report.py` |
| `validator_false_verified`, `validator_false_alarm` | Validator가 verified라 했는데 재계산이 틀렸다고 보는 인용, needs_review라 했는데 재계산이 맞다고 보는 인용(Reporter는 needs_review 숫자를 보고서에서 뺌). 분모는 `validator_verified_checked` / `validator_needs_review_checked` | `graders/recompute.py` |
| `citation_coverage` | 본문의 유의미한 숫자(금액, %, 소수) 중 인용이 붙은 비율. 근사치 | `graders/report.py` |
| `audit_pass`, `audit_block_findings` | 버전에 Auditor가 있으면 그 판정 | `graders/audit.py` |
| `audit_missed`, `audit_missed_kinds` | Auditor가 pass라 했는데 위 채점기가 Auditor가 막아야 할 결함(인용값 불일치, 깨진 `[n]`, 숫자 안 `[n]`)을 찾은 경우 | `grade.py` |
| `code_exec_failed`, `code_exec_fail_causes` | Fargate 샌드박스에서 실패한 에이전트 코드, 원인별 분류(파일 없음, AttributeError 등) | `graders/executions.py` |
| `cost_usd`, `cache_hit_rate` | 토큰 사용량 × `config/pricing.yaml` | `graders/cost.py` |

`core_pass`는 `grade.py`의 `fail_reasons()` 한 곳에서 정의합니다. 결과를 내지 못한
검사는 통과가 아니라 실패입니다: 채점기 오류, 다시 계산한 개수 부족, 비교한 인용 개수
부족.

### 가격

`config/pricing.yaml`에는 모델 계열별 Bedrock 온디맨드 가격이 있습니다. `verified: true`
항목은 us-west-2 글로벌 추론 기준으로 AWS Pricing API에서 읽었고, `verified: false`
항목은 아직 확인하지 않은 정가입니다. 가격이 `null`이면 추측하지 않고
`unpriced_tokens`로 보고합니다.
