"""graders/plan.py and planner_eval.py: rule checks, judge parsing, cache. No network."""
import json

import planner_eval
from fixtures.fake_bedrock import CFG, FakeConverse
from grade import load_scenario
from graders import plan

PLAN = """# Plan
## thought
매체별 광고 성과를 분석하고 DOCX로 보고합니다.
## steps
### 1. Coder: 광고 성과 분석
- [ ] 데이터 프로파일링 (결측치, 중복, 타입)
### 2. Validator: 계산 검증
### 3. Reporter: DOCX 보고서
### 4. Auditor: 인용 감사
"""
QUERY = load_scenario("yummy_food_kr")["query"]


def test_rule_checks():
    s = plan.rule_checks(QUERY, PLAN)
    assert s["plan_steps"] == ["Coder", "Validator", "Reporter", "Auditor"]
    assert s["plan_workflow_ok"] and s["plan_auditor_planned"] and s["plan_format_ok"] and s["plan_language_ok"]
    swapped = PLAN.replace("### 2. Validator", "### 2. Reporter").replace("### 3. Reporter", "### 3. Validator")
    assert not plan.rule_checks(QUERY, swapped)["plan_workflow_ok"]                 # Reporter before Validator
    no_validator = PLAN.replace("### 2. Validator: 계산 검증\n", "")
    assert not plan.rule_checks(QUERY, no_validator)["plan_workflow_ok"]            # numbers with no Validator
    assert not plan.rule_checks(QUERY, PLAN.replace("DOCX", "보고서"))["plan_format_ok"]
    assert not plan.rule_checks(QUERY, "# Plan\n### 1. Coder: analyze the data")["plan_language_ok"]


def _verdict(reqs, missing=(), partial=(), dq=True):
    return {"requirements": [{"requirement_id": r["id"], "evidence": "x",
                              "status": "missing" if r["id"] in missing else "partial" if r["id"] in partial else "met"} for r in reqs],
            "data_quality": {"present": dq, "evidence": "데이터 프로파일링"}}


def test_judge_scores_and_unanswered_requirements(tmp_path):
    sc = load_scenario("yummy_food_kr")
    reqs = sc["requirements"]
    reply = _verdict(reqs[1:], partial=("priority",))            # the judge skipped the first requirement
    scores, record, usage = plan.grade(FakeConverse([reply]), CFG, sc["query"], reqs, PLAN)
    assert scores["plan_requirements_missing"] == [reqs[0]["id"]]      # unanswered counts as missing
    assert scores["plan_requirements_partial"] == ["priority"]
    assert scores["plan_requirements_met"] == (len(reqs) - 2) / len(reqs)
    assert scores["plan_data_quality"] is True and usage["input"] == 10_000


def test_cache_is_reused_until_the_plan_changes(tmp_path):
    sc = load_scenario("yummy_food_kr")
    fake = FakeConverse([_verdict(sc["requirements"]), _verdict(sc["requirements"], missing=("priority",))])
    first = planner_eval.grade_plan(tmp_path, PLAN, sc, (fake, CFG))
    again = planner_eval.grade_plan(tmp_path, PLAN, sc, (fake, CFG))
    assert again == first and len(fake.requests) == 1
    changed = planner_eval.grade_plan(tmp_path, PLAN + "\n### 5. Tracker", sc, (fake, CFG))
    assert changed["plan_requirements_missing"] == ["priority"] and len(fake.requests) == 2
    assert planner_eval.grade_plan(tmp_path / "x", PLAN, sc, (None, CFG))["plan_workflow_ok"]   # rules only, no cache
    assert not (tmp_path / "x").exists()


def test_plans_from_events_takes_each_invocation(tmp_path):
    events = [{"type": "agent_text_stream", "agent_name": "planner", "data": "첫 계획"},
              {"type": "agent_usage_stream", "agent_name": "planner"},
              {"type": "agent_text_stream", "agent_name": "coordinator", "data": "x"},
              {"type": "agent_text_stream", "agent_name": "planner", "data": "수정 "},
              {"type": "agent_text_stream", "agent_name": "planner", "data": "계획"}]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    assert plan.plans_from_events(tmp_path) == ["첫 계획", "수정 계획"]


def test_generate_sends_the_runtime_request(monkeypatch):
    fake = FakeConverse(["# Plan\n### 1. Coder: x"])
    text, usd = planner_eval.generate_plan(fake, "global.anthropic.claude-opus-5", QUERY)
    req = fake.requests[0]
    assert text.startswith("# Plan") and QUERY.strip() in req["system"][0]["text"]
    assert req["additionalModelRequestFields"]["thinking"] == {"type": "adaptive"}
    assert "<user_request>" in req["messages"][0]["content"][0]["text"]
