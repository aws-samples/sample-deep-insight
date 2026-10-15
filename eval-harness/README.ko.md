# Deep Insight Eval Harness

**→ [메인 README](../README.md)로 돌아가기** · [English](README.md) | **한국어**

Deep Insight의 자동 채점표입니다. 코드, 프롬프트, 모델을 바꿨을 때 "보고서가
더 나아 보인다" 대신 숫자로 두 가지에 답합니다.

1. **핵심 기능이 여전히 동작하는가?** → 실행마다 PASS / FAIL
2. **무엇이 얼마나 좋아지거나 나빠졌는가?** → 변경 전후 비교표

## 구성

| 구성 요소 | 하는 일 |
|---|---|
| **Runner** `run_eval.py` | 배포된 런타임에 정해진 분석 요청을 보내고, 계획 검토를 사람 없이 자동 승인하고, 보고서·인용·코드 실행 로그·토큰 사용량을 저장합니다 |
| **Grader** `grade.py` | 실행 하나를 채점합니다: 산출물, 숫자 정확도, 비용, 시간 → PASS / FAIL이 담긴 `scores.json` |
| **Comparer** `compare.py` | 두 버전을 나란히 놓고 지표별 평균 ± 표준편차와 차이를 보여줍니다 |
| **Fact checker** `graders/factcheck.py` | 모델이 보고서를 정답 키와 대조해 어떤 사실이 맞고 틀렸는지, 어떤 진술이 다른 기간이나 부분집합에 대한 것인지 판정합니다 (유료, 기본으로 켜짐) |
| **LLM judge** `graders/judge.py`, `pairwise.py` | 숫자로 잴 수 없는 것을 채점합니다: 보고서가 요청에 답했는지, 베이스라인 보고서보다 나은지 (유료, 선택) |
| **정적 검사** `pytest` | AWS 없이 몇 초: 프롬프트 템플릿 렌더링, 모델 요청 필드 유효성, 채점기가 심어둔 결함을 실제로 잡는지 |

`compare.py` 출력 예시:

```
                       baseline        opus55          Δ
printed value = citation  100.0%        100.0%          +0.0%p
core facts correct        100.0%        100.0%          +0.0%p
cost                      $10.20        $8.50           -17% ▲ better
duration                  1920s         1680s           -12% ▲ better
```

## 폴더 구조

```
eval-harness/
├── run_eval.py, grade.py, compare.py, pairwise.py    평소에 쓰는 명령
├── eval_runtime.py, langfuse_sync.py, calibrate.py   평가 런타임 설정, 게시, 보정
├── graders/       채점 모듈: 규칙 기반 채점기, factcheck.py, judge.py, cost.py
├── sanity/        유료 평가기 검사: factcheck_sanity.py, judge_sanity.py, factcheck_cases/
├── config/        scenarios.yaml, judge.yaml, pricing.yaml, runtime_configs.yaml,
│                  eval.env, langfuse.env (git 제외, 로컬 전용)
├── answer_keys/   fact check용 데이터셋별 정답과 이를 만드는 스크립트
├── ground_truth/  사람용 데이터셋별 답안지 (데이터 디렉토리에는 두지 않음)
├── docs/          jungle-market.md, yummy-food.md: 개발용 데이터셋, 심어둔 패턴, 정답
├── tests/         pytest 테스트와 fixture
└── eval_results/  모든 실행, 채점, 비교 결과 (git 제외)
```

모든 명령은 `eval-harness/`에서 실행합니다. `config/scenarios.yaml`의 경로는
`eval-harness/` 기준입니다.

## 동작 방식: 단계와 파일

```
config/scenarios.yaml + jungle-market CSV
        │
        ▼  1. run_eval.py            평가 런타임 호출, 계획 검토 자동 승인
eval_results/<tag>/<run>/            events.jsonl, run.json, usage.json, config.json, artifacts/
        │
        ▼  2. grade.py               (run_eval.py가 실행마다 자동으로 호출)
        │     graders/*.py           산출물, 인용, 재계산, 보고서, 비용          → scores.json
        │     graders/factcheck.py   보고서 숫자 vs answer_keys/                 → factcheck.json
        │     graders/judge.py       요구사항 충족과 품질 점수 (--judge)         → judge.json
        ▼
scores.json  (core_pass: PASS / FAIL)
        │
        ├─▶ 3. pairwise.py           후보 vs 베이스라인 보고서  → pairwise_vs_<baseline>.json
        ├─▶ 4. compare.py            태그 간 비교표             → 화면 출력 또는 compare.md
        └─▶ 5. langfuse_sync.py      Langfuse에 trace, dataset run, annotation queue 게시
                  │
                  ▼  6. calibrate.py 사람 레이블 vs judge 점수
```

| 단계 | 명령 | 읽는 것 | 쓰는 것 | 유료 |
|---|---|---|---|---|
| 1. 실행 | `run_eval.py --scenario <s> --tag <t>` | `config/scenarios.yaml`, 시나리오의 `upload` 파일(S3로 전송), `config/eval.env` | `eval_results/<t>/<s>-<time>-<n>/`: `events.jsonl`, `run.json`, `usage.json`, `config.json`, `s3/`, `artifacts/` | 예: 런타임(에이전트, Fargate) |
| 2. 채점 | `grade.py <run_dir> --scenario <s>` (1단계 후 자동) | `artifacts/`, CSV, `config/pricing.yaml`, 시나리오의 `pass:` | `scores.json` | 아니요 |
| 2a. Fact check | 2단계의 일부, 기본으로 켜짐 (`--no-factcheck`로 생략) | 보고서, `answer_keys/<dataset>.json`, `config/judge.yaml` | `factcheck.json` | 예: 보고서당 약 $1 |
| 2b. Judge | `--judge`일 때 2단계의 일부 | 보고서, 시나리오의 `requirements`, `config/judge.yaml` | `judge.json` | 예: 보고서당 약 $0.1-0.3 |
| 3. Pairwise | `pairwise.py <baseline_tag> <candidate_tag>` | 두 태그의 보고서 | `<candidate_tag>/pairwise/`, `<candidate_tag>/pairwise_vs_<baseline>.json` | 예 |
| 4. 비교 | `compare.py <tag> <tag> [--out compare.md]` | `*/scores.json`, `run.json`, `config.json`, `pairwise_vs_*.json` | 비교표 | 아니요 |
| 5. 게시 | `langfuse_sync.py <tag>... [--queue]` | `run.json`, `scores.json`, `judge.json`, `factcheck.json`, `config.json`, `config/langfuse.env` | Langfuse, `eval_results/langfuse_sync.json` | 모델 호출 없음 |
| 6. 보정 | `calibrate.py export` / `score` / `langfuse` | `judge.json`, 사람 레이블(CSV 또는 Langfuse queue) | 레이블 시트, 일치도 표 | 아니요 |

**채점기를 검사하는 도구.** 유료 평가기를 믿기 전에, 정답을 이미 아는 입력으로
먼저 돌려봅니다.

| 명령 | 검사 내용 | 읽는 것 | 쓰는 것 | 유료 |
|---|---|---|---|---|
| `sanity/factcheck_sanity.py` | fact checker가 알려진 오류를 잡고, 그 밖의 것은 틀렸다고 하지 않는지 | `sanity/factcheck_cases/*.yaml` (gold case) | `eval_results/factcheck_sanity/<time>.json` | 예: 반복당 약 $5 |
| `sanity/judge_sanity.py <run>` | judge가 떨어뜨려야 할 것을 떨어뜨리는지 | 실행 하나의 보고서와 그로부터 만든 변형 | `eval_results/judge_sanity/<time>.json` | 예 |
| `pytest` | 프롬프트 렌더링, 요청 필드 유효성, 채점기가 심어둔 결함을 잡는지, 프롬프트가 Auditor·Validator에게 주는 코드가 막아야 할 것을 막는지(`tests/test_prompt_code.py`) | 코드와 fixture | 없음 | 아니요 |
| `planner_eval.py runs <tag>` / `generate --scenario <s>` | Planner의 계획이 요청을 다루는지(아래) | `events.jsonl` 또는 Planner 호출 | `plan_eval.json` | 예: 계획당 judge, `generate`는 계획당 약 $0.10 추가 |

5단계를 실행하기 전에는 Langfuse에 아무것도 올라가지 않습니다. 실행과 채점
결과는 `eval_results/`에만 남습니다.

## 데이터셋: 개발용 둘, 따로 떼어둔 하나

`config/scenarios.yaml`의 시나리오마다 `split`이 있습니다.

| Split | 데이터셋 | 용도 |
|---|---|---|
| `dev` | jungle_market, yummy_food | 프롬프트, judge, 루브릭, 통과 기준을 이 데이터에 맞춰 조정합니다. gold case와 보정용 레이블도 여기서 나옵니다 |
| `test` | moon_market | 릴리스 전에만 확인합니다. 이 데이터에 맞춰 조정하는 것이 없으므로, 개발셋에만 맞춘 변경은 여기서 드러납니다 |

- **jungle_market** (`deep-insight-web/sample_data/jungle-market/`): 8개 도시의
  2주치 식료품 주문 데이터로, 얕은 분석이 틀리게 되는 패턴을 일부러 심어뒀습니다
  (매출 1위 도시를 바꾸는 중복 행, 쿠폰의 심슨의 역설, 품절, 할인 문턱 몰림,
  프로모션 후광 효과). [docs/jungle-market.md](docs/jungle-market.md)에 데이터,
  패턴, 정답, 보고서 채점 방법을 정리해 뒀습니다.
- **yummy_food** (`managed-agentcore/data/yummy_food/<lang>/`): 4개 매체 × 6개
  상품의 한 달치 일별 광고 성과입니다. 정제할 것은 없고, 함정은 광고 지표를 집계하는
  방식에 있습니다 (ROAS 컬럼을 평균하면 1위 매체가 바뀌고, CTR이 가장 높은 매체가
  ROAS는 가장 낮고, 두 배로 늘린 예산의 한계 수익은 훨씬 낮음).
  [docs/yummy-food.md](docs/yummy-food.md)를 보세요.
- **moon_market** (`managed-agentcore/data/moon_market/<lang>/`): 서울 10개 구의
  2주치 단일 상품 주문 데이터입니다. 시나리오의 통과 기준은 개발셋 값을 그대로 쓰고,
  다시 정할 때도 개발셋 결과로만 정합니다. gold case와 보정 queue는 두지 않습니다.
  둘 다 평가기를 이 데이터에 맞추게 되기 때문입니다.

데이터셋마다 사람용 답안지(`ground_truth/<dataset>/`, 국문(kr)·영문(en)판이 있고
숫자가 같은 yummy_food와 moon_market은 그 아래 `<lang>/`)와 fact checker용 정답
키(`answer_keys/`, 판마다 하나)가 있습니다. 답안지는 CSV 옆이 아니라 여기에 둡니다.
데이터 디렉토리는 에이전트에 닿고, 웹 앱은 `deep-insight-web/sample_data/`의 모든
파일을 사용자에게 목록으로 보여주고 내려주기 때문입니다. 다시 그쪽에 두면
`tests/test_l0_static.py`가 실패합니다.

테스트 시나리오는 `run_eval.py`에서 `--allow-test`가 있어야 돌고, `compare.py`는
dev와 test를 다른 섹션으로 보고하고, `langfuse_sync.py`는 test 실행을 별도 dataset에
올리고 보정 queue에는 넣지 않습니다. 테스트 결과는 릴리스 여부를 정할 때 보고, 다음
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

채점에도 유료 모델 호출이 있습니다. **fact check는 시나리오에 정답 키가 있으면
기본으로 실행**되고(보고서당 약 $1, `--no-factcheck`로 생략), LLM judge는
`--judge`일 때 실행됩니다(보고서당 약 $0.1~0.3). Runner는 첫 실행 전에 어떤 유료
검사가 켜져 있는지 모델, 리전과 함께 출력합니다.

## Fact check: 보고서 숫자를 정답 키와 대조

정답 키(`answer_keys/`)에는 데이터셋에서 pandas로 계산한 사실이 들어 있습니다:
합계, 도시 순위, 동시구매 건수, 프로모션 효과. 보고서를 여기에 대조하려면 패턴
매칭이 아니라 읽기가 필요합니다. "Paris가 매출 1위"는 전체 기간 기준으로는
틀렸지만(Paris는 4위, Singapore가 1위) 2026-03-10 하루만 보면 맞고, 어느 쪽인지는
주변 문장만 알려줍니다. `graders/factcheck.py`는 모델이 읽고 코드가 계산하도록 일을
나눕니다.

1. **추출** (모델, 정답 숨김). 모델은 각 사실의 정의와 범위를 값 없이 받고,
   보고서가 그 사실에 대해 말한 모든 진술을 나열합니다: 정확한 인용, 진술된 값,
   단위, 보고서가 밝힌 기간이나 필터. 정답을 숨겨서 모델이 기대하는 값을 보지
   않게 합니다.
2. **비교** (코드). 인용이 보고서에 있어야 하고, 숫자가 인용 안에 있어야 하고,
   값이 출력된 정밀도에서 정답과 같아야 합니다. 12,481,923은 12,431,923이 아니지만
   12,430,000과 1,243만은 맞습니다. 순위는 위치를, 관계는 방향을 비교합니다.
3. **판정** (모델, 정답 공개). 불일치와 코드가 결정하지 못한 경우(범위 불명확,
   단위 의심)는 정답과 인용 주변 문단과 함께 다시 모델에 보냅니다.

각 진술은 다음 중 하나로 끝납니다: `correct`, `wrong_confirmed`(코드와 판정 모델
모두 틀렸다고 하고 범위도 같음), `out_of_scope`(다른 기간이나 부분집합),
`needs_review`(둘의 의견이 다르거나 모델만 틀렸다고 함), `unverified_quote`(인용이
보고서에 없음, 버림). **`wrong_confirmed`는 `core_pass`를 실패시키고
`needs_review`는 실패시키지 않습니다.** `needs_review`는 사람이 읽을 수 있도록
`scores.json` details에 남습니다. 성장률을 `71.73%p`로 쓴 경우는 틀린 값이 아니라
`factcheck_unit_issues`로 셉니다.

```bash
.venv/bin/python sanity/factcheck_sanity.py --repeat 3      # fact checker가 맞게 판정하는가? (유료, 반복당 약 $5)
.venv/bin/python grade.py <run_dir> --scenario jungle_market   # fact check는 기본으로 실행
.venv/bin/python grade.py <run_dir> --scenario jungle_market --no-factcheck   # 모델 호출 없음
```

- **먼저 검증하고 쓴다.** `sanity/factcheck_sanity.py`는 `sanity/factcheck_cases/`의 gold case로
  채점기를 돌립니다. gold case는 사람이 오류를 직접 찾은 실제 보고서, 그 오류를
  고친 같은 보고서, 작은 오류를 심은 버전, 다른 기간이나 부분집합에 대한 진술,
  평가자를 겨냥한 지시문으로 구성됩니다. wrong recall, false wrong, 반복 간
  안정성을 보고하고, recall이 100% 미만이거나 false wrong이 1건 이상이면 실패합니다.
  프롬프트(`factcheck.PROMPT_VERSION`), `config/judge.yaml`의 모델, 정답 키가 바뀔 때마다
  다시 돌리세요. gold case는 개발셋에만 둡니다. jungle_market gold case
  (`sanity/factcheck_cases/jungle_market.yaml`)는 중복 행을 지우지 않은 베이스라인
  보고서로 만들었습니다. 레이블은 pandas로 CSV와 대조했고, 사람의 최종 검토가 아직
  필요합니다(#133). yummy_food gold case(`sanity/factcheck_cases/yummy_food.yaml`)는
  답안지를 보고 손으로 쓴 보고서로, 이 데이터의 얕은 분석 실수(ROAS 컬럼 평균, 늘린
  예산도 한 달 ROAS만큼 번다는 가정)를 그대로 담았습니다. 작성할 때 지금 데이터로 만든
  Deep Insight 보고서가 없었기 때문이며, `real` 케이스는 첫 yummy_food_kr 베이스라인
  실행에서 만듭니다.
  `sanity/factcheck_sanity.py --repeat 3`로 측정한 결과(2026-10-13,
  `global.openai.gpt-6-astra`, effort high, 15회 $9.23):

  | | factcheck-v3 | factcheck-v4 |
  |---|---|---|
  | wrong recall | 58% (21/36) | **100% (36/36)** |
  | correct recall | 100% (60/60) | 100% (60/60) |
  | not_wrong (범위 함정) | 92% (22/24) | 100% (24/24) |
  | false wrong | 2 | **0** |
  | 3회 반복에서 같은 레이블 | 38/40 | 40/40 |

  v3는 인용 번호가 숫자를 가른 경우(`111,065 [2].13달러`)를 모두 놓쳤습니다. 판정
  모델은 틀렸다고 봤지만 코드가 숫자를 읽지 못해 `needs_review`로 끝났고, v4는
  숫자를 읽기 전에 인용 번호를 지웁니다. v3의 false wrong 2건은 원본 파일과 중복
  제거 결과를 대비한 문장이었는데, 정답 키의 범위에 그 예외가 없었기 때문입니다.
  지금은 예외가 들어 있습니다. 리포터는 첫 jungle_market 보고서 14개 중 10개에
  이렇게 갈라진 숫자를 씁니다(`managed-agentcore/src/prompts/reporter.md`의
  `resolve_body_citations`: 천 단위 쉼표 패턴에 소수부가 없음).
- **양쪽을 같은 평가기로.** 결과는 보고서 해시와 `factcheck_version`(프롬프트 버전,
  모델, effort, 정답 키 해시) 기준으로 `factcheck.json`에 캐시됩니다. 태그끼리
  다른 버전으로 검사됐으면 `compare.py`가 경고합니다. 저장된 실행을 `grade.py`로
  둘 다 다시 채점하세요.
- effort high의 `global.openai.gpt-6-astra` 기준 보고서당 약 $1입니다.
- 프롬프트의 예시는 지어낸 이름과 숫자를 써서, 어떤 데이터셋의 정답도 예시를
  통해 평가기에 들어가지 않습니다.

## LLM judge: 분석 품질

위 채점기들은 숫자가 맞는지 확인합니다. 보고서가 요청에 답했는지는 보지 못해서,
총매출만 정확히 적은 보고서도 전부 통과합니다. judge가 이 빈틈을 메웁니다.
judge는 **Amazon Bedrock의 OpenAI 모델**(Converse API, `config/judge.yaml`)로 돌아갑니다.
Claude 에이전트와 다른 계열이라 자기 계열이 쓴 글을 채점하지 않습니다. fact check도
같은 모델을 씁니다.

**리전과 모델.** `config/judge.yaml`의 `region: null`은 `JUDGE_REGION`, 그다음
`EVAL_REGION`(`config/eval.env`), 그다음 AWS 기본 리전을 씁니다. 첫 호출 전에 하네스가 그
리전에서 모델을 호출할 수 있는지 확인하고(무료 Bedrock control-plane 호출), 안 되면
메시지와 함께 멈춥니다. 기본값 `global.openai.gpt-6-astra`는 us-west-2에서
테스트했습니다. 다른 리전에서는 계정에 있는 모델을 확인해 `model:`에 넣으세요.

```bash
aws bedrock list-inference-profiles --region <region> --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'openai')].[inferenceProfileId,status]"
```

모델을 바꾸면 `judge_version`이 바뀌어 예전 판정을 재사용하지 않고 다시 채점합니다.
그 점수를 믿기 전에 새 모델로 `sanity/judge_sanity.py`와 `sanity/factcheck_sanity.py`를 돌리세요.

**Pointwise** (`grade.py --judge`, `run_eval.py --judge`)는 요청, 시나리오의
`requirements`(`config/scenarios.yaml`), 보고서를 읽고 다음을 돌려줍니다.

- 요구사항별 met / partial / missing → `judge_requirement_coverage`,
  `judge_requirements_missing` (**missing 요구사항이 하나라도 있으면 `core_pass` 실패**)
- 기준이 정의된 1~5점: `evidence_linkage`(주장이 분석 결과와 연결됨),
  `strategy_specificity`(대상, 단계, 정량화된 효과, 우선순위), `insight_depth`(기술
  통계를 넘어섬), `reasoning_soundness`(과장 없음, 데이터 한계 명시)

일부러 뺀 것: 숫자 정확도(채점기와 fact check가 담당), 차트 품질(judge는 텍스트만
읽음), 길이와 서식.

**Pairwise** (`pairwise.py`)는 주된 A/B 신호입니다. judge는 절대 점수보다 "둘 중
어느 쪽"을 더 잘 판단합니다. 후보 보고서를 고정된 베이스라인 보고서와 순서를 바꿔
두 번 비교하고, 순서에 따라 뒤집히는 판정은 무승부로 셉니다. 결과는 `compare.py`에
나옵니다.

```bash
.venv/bin/python sanity/judge_sanity.py eval_results/baseline/<run> --scenario jungle_market  # judge가 떨어뜨려야 할 것을 떨어뜨리는가?
.venv/bin/python grade.py eval_results/baseline/<run> --scenario jungle_market --judge
.venv/bin/python pairwise.py eval_results/baseline eval_results/baseline   # 노이즈 기준, 약 50%가 정상
.venv/bin/python pairwise.py eval_results/baseline eval_results/my-change
```

- **쌍을 충분히 쓴다.** 쌍이 3개면 한 쌍이 승률을 ±33%p 움직입니다. 판단하기 전에
  `--pairs all`(3 × 3 = 9쌍) 이상으로 비교하고, 먼저 baseline 대 baseline으로
  노이즈를 확인하세요.
- **먼저 검증하고 쓴다.** `sanity/judge_sanity.py`는 judge에 실제 보고서와 정답을 아는
  변형(숫자만 있음, 전략 삭제, 다른 질문, 빈 보고서, 프롬프트 인젝션)을 주고, 잘못
  채점하면 실패합니다. baseline 대 baseline pairwise 실행은 노이즈만으로 승률이
  50%에서 얼마나 움직이는지 보여줍니다.
- **사람과 한 번 보정한다.** `calibrate.py export`는 judge 점수가 없는 블라인드 레이블
  시트를 씁니다. 보고서 10~20개에 레이블을 단 뒤 `calibrate.py score`가 기준별 일치도
  (정확 일치, ±1, Spearman, 편향)를 출력합니다. 루브릭이나 judge 모델이 바뀔 때마다
  다시 확인하세요.
- judge 결과는 보고서 해시와 `judge_version` 기준으로 캐시됩니다(`judge.json`,
  `pairwise/`). `judge_version`은 `judge.PROMPT_VERSION`, 시스템 프롬프트·루브릭·
  프롬프트 템플릿의 지문, judge 모델과 effort, 시나리오의 요청과 요구사항으로
  만들어집니다. 이 중 하나라도 바뀌면 예전 판정을 재사용하지 않고 다시 채점하고,
  바뀐 게 없으면 다시 채점해도 비용이 두 번 들지 않습니다. 스키마를 깬 응답은 점수가
  아니라 `judge_error`로 기록됩니다.

## Langfuse: UI에서 보고, 비교하고, 레이블 달기

`langfuse_sync.py`는 공개 REST API로 결과를 Langfuse 프로젝트에 게시합니다.
**보내는 것:** 요청, 보고서 전문, judge의 판단 근거, 에이전트별 사용량. 이 데이터가
계정 밖으로 나가지 않도록 Langfuse를 자신의 AWS 계정에서 운영하세요.
[deploy-langfuse-on-ecs-with-fargate](https://github.com/aws-samples/deploy-langfuse-on-ecs-with-fargate)로
ECS Fargate에 self-hosted Langfuse를 배포할 수 있습니다. Langfuse Cloud
호스트(`*.cloud.langfuse.com`)는 `--allow-cloud` 없이는 거부합니다.

하네스 전용 **Langfuse 프로젝트를 따로** 두세요. 다시 sync하면 같은 실행에 대해 이
도구가 예전에 만든 것을 지웁니다: 대체된 trace(사람 레이블이 없는 경우)와
`deep-insight-eval`과 `deep-insight-eval-test`에서 sync한 각 태그의 dataset run(새로 만듦). 공유 프로젝트에서는
같은 이름의 dataset이나 run이 바뀔 수 있습니다.

| Eval harness | Langfuse |
|---|---|
| 시나리오 (요청, 요구사항, 정답 키, 통과 기준) | dataset `deep-insight-eval`(dev) 또는 `deep-insight-eval-test`(test)의 item |
| 태그 (`baseline`, `my-change`) | 같은 이름의 dataset run. 태그에 실행이 있는 dataset마다 하나 |
| 실행 하나 | trace: input = 요청, output = 보고서 텍스트, metadata = git SHA, 런타임 버전, 모델 ID |
| 에이전트별 토큰, 비용, 시간 | 에이전트마다 generation 하나 |
| `scores.json`, `judge.json` | trace score. judge 점수에는 판단 근거가 comment로 붙음 |
| pairwise 승률 | 후보 dataset run의 score |
| 사람 레이블 | dev 시나리오별 annotation queue `deep-insight-calibration-<scenario>`. 그 시나리오의 요구사항과 루브릭 기준만 보여줌 (judge와 같은 score config). test 시나리오에는 queue를 만들지 않음: 그 레이블로 judge나 루브릭을 고치게 되기 때문 |

```bash
# eval-harness/config/langfuse.env (git 제외): LANGFUSE_HOST (또는 LANGFUSE_BASE_URL), LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
.venv/bin/python langfuse_sync.py eval_results/baseline eval_results/my-change --dry-run   # 개수만 확인
.venv/bin/python langfuse_sync.py eval_results/baseline eval_results/my-change --queue
.venv/bin/python calibrate.py langfuse     # annotation queue에 입력된 레이블 vs judge
```

Langfuse는 실행마다 dataset item 하나에 trace 하나를 두므로, 반복 실행은 각각 별도
item이 됩니다(`jungle_market #1`, `#2`, …). 모든 타임스탬프는 실행 자체의 시각이라,
UI에서 클릭한 score나 run item의 시각으로 trace를 찾습니다. trace와 score ID에는
실행 내용의 해시가 들어 있어, 바뀌지 않은 결과를 다시 sync하면 아무 일도 일어나지
않고 바뀐 결과는 예전 trace를 대체합니다(이미 사람 레이블이 있으면 경고와 함께
유지). queue에서 레이블을 달 때는 API(judge) 점수를 숨겨서 블라인드로 다세요.

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

## Planner: 실행 전에 계획이 맞는지

Planner는 데이터를 보지 않고 요청만 보며, 이후 모든 에이전트가 그 계획대로
일합니다. 그래서 계획에서 빠진 요구사항은 대개 보고서에서도 빠집니다.
`planner_eval.py`는 Planner가 알 수 있는 것만으로 계획을 채점합니다.

| 검사 | 방법 |
|---|---|
| `plan_requirements_met`, `plan_requirements_missing`, `_partial` | judge가 시나리오 요구사항마다 계획 단계로 met / partial / missing을 판정 |
| `plan_data_quality` | judge: 분석 전에 데이터를 점검하는 단계(결측치, 중복, 타입, 범위)가 있는지 |
| `plan_workflow_ok`, `plan_auditor_planned` | 규칙: Coder → Validator → Reporter, Reporter 뒤에 Auditor |
| `plan_format_ok`, `plan_language_ok` | 규칙: 요청이 지정한 형식(DOCX, PDF)이 계획에 있는지, 계획이 요청과 같은 언어인지 |

```bash
.venv/bin/python planner_eval.py runs eval_results/baseline              # 저장된 실행의 계획
.venv/bin/python planner_eval.py generate --scenario yummy_food_kr --repeat 5 --tag planner-my-change
```

`generate`는 배포된 프롬프트, eval 런타임의 `PLANNER_MODEL_ID`, 런타임이 만드는
요청 필드로 Planner만 호출합니다. 그래서 `planner.md` 변경을 전체 실행 대신 계획당
약 $0.10로 여러 번 확인할 수 있습니다. 전체 실행과 다른 점은 하나입니다. 사용자
메시지가 실행에서는 Coordinator의 인계 문장이고, 여기서는 요청 자체입니다. 테스트
시나리오는 `--allow-test`가 필요하고, `--no-judge`는 규칙 검사만 합니다.

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
넘깁니다. 그래서 데이터셋이 런타임 이미지에 들어 있을 필요가 없습니다. 답안지는 업로드
목록에 넣지 않으므로(`tests/test_l0_static.py`가 검사) 에이전트에 닿지 않습니다.

시나리오마다 `pass:` 블록이 core_pass 기준을 정합니다.

| 키 | 의미 |
|---|---|
| `required_facts` | 정확히 진술돼야 하는 정답 키 항목 (fact check) |
| `min_other_facts` | 나머지 정답 키 항목 중 정확히 진술돼야 하는 개수 |
| `min_recompute` | CSV에서 다시 계산돼야 하는 계산 개수 |
| `min_cited_checked` | 비교돼야 하는 "숫자 [n]" 쌍의 개수 |

느슨한 기본값에서 시작해 실제 실행으로 정합니다: 정상적인 베이스라인 실행에서 나온
가장 낮은 개수의 절반. 세그먼트 숫자는 보고서마다 무엇을 분석했는지에 따라 달라서,
특정 숫자를 요구하면 좋은 보고서도 떨어집니다. "나머지 중 최소 N개"는 보고서가 고르게
두면서도, 숫자를 적게 쓰거나 대부분 틀린 보고서는 떨어뜨립니다.

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
.venv/bin/python run_eval.py --scenario jungle_market --repeat 5 --tag baseline-<date> --judge

# 사용자에게 영향 없이 모델 구성 시험
.venv/bin/python eval_runtime.py set-models sonnet45-workers
.venv/bin/python run_eval.py --scenario jungle_market --repeat 5 --tag sonnet45 --judge
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
- 한 태그 안에 git SHA, 런타임 버전, 모델 구성이 섞였거나, 태그끼리 다른 fact check나
  judge 버전으로 채점됐으면 ⚠ 줄이 나옵니다. 비교 전에 나누거나 다시 채점하세요.

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
| `required_facts_missing`, `other_facts_found` | 정확히 진술된 정답 키 항목: 시나리오의 필수 항목, 나머지 중 몇 개 | `graders/factcheck.py` + `answer_keys/` |
| `factcheck_wrong_confirmed`, `factcheck_wrong_ids` | 같은 범위에서 정답 키와 어긋나는 진술. 코드와 판정 모델이 모두 확인 | `graders/factcheck.py` |
| `factcheck_needs_review`, `factcheck_out_of_scope`, `factcheck_unit_issues`, `factcheck_unverified_quotes` | 사람이 볼 진술, 다른 기간이나 부분집합에 대한 진술, %p로 쓴 진술, 모델이 잘못 인용한 진술 | `graders/factcheck.py` |
| `audit_pass`, `audit_block_findings` | 버전에 Auditor가 있으면 그 판정 | `graders/audit.py` |
| `audit_missed`, `audit_missed_kinds` | Auditor가 pass라 했는데 위 채점기가 Auditor가 막아야 할 결함(인용값 불일치, 깨진 `[n]`, 숫자 안 `[n]`)을 찾은 경우 | `grade.py` |
| `code_exec_failed`, `code_exec_fail_causes` | Fargate 샌드박스에서 실패한 에이전트 코드, 원인별 분류(파일 없음, AttributeError 등) | `graders/executions.py` |
| `cost_usd`, `cache_hit_rate` | 토큰 사용량 × `config/pricing.yaml` | `graders/cost.py` |

`core_pass`는 `grade.py`의 `fail_reasons()` 한 곳에서 정의합니다. 결과를 내지 못한
검사는 통과가 아니라 실패입니다: 채점기 오류, `judge_error`나 `factcheck_error`,
다시 계산한 개수 부족, 비교한 인용 개수 부족. 일부러 실행하지 않은 검사(`--judge` 없는
LLM judge, `--no-factcheck`의 fact check)만 건너뜁니다.

### 정답 키

`answer_keys/build_answer_key.py`가 데이터셋에서 pandas로 사실을 계산합니다. 데이터셋이
바뀌면 다시 만들고 값을 직접 검토하세요. 각 정답 키는 `ground_truth/`의 답안지와
일치합니다(jungle_market 2026-10-12, yummy_food와 moon_market 2026-10-14 확인). 각 사실에는 `kind`(value, ranking,
relation), fact checker가 정답 없이 읽는 `description`과 `scope`, `unit`, 정답 자체,
판정할 때만 보여주는 `note`가 있습니다. jungle_market 값은 `scope`에 따로 적지 않았으면
파일의 완전 중복 행 111개를 뺀 기준입니다. 보고서 자체 수식에 달린 숫자(기회 점수, 시나리오 상승폭)는
데이터셋 정답이 없어서 넣지 않았습니다.

### 가격

`config/pricing.yaml`에는 모델 계열별 Bedrock 온디맨드 가격이 있습니다. `verified: true`
항목은 us-west-2 글로벌 추론 기준으로 AWS Pricing API에서 읽었고, `verified: false`
항목은 아직 확인하지 않은 정가입니다. 가격이 `null`이면 추측하지 않고
`unpriced_tokens`로 보고합니다.
