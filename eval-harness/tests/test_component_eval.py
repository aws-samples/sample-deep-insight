"""component_eval.py: the plan a component works from, and main() end to end against fake AgentCore and S3. No AWS."""
import json

import component_eval as ce
from fixtures import make_run


def test_plans_from_events_takes_each_invocation(tmp_path):
    events = [{"type": "agent_text_stream", "agent_name": "planner", "data": "첫 계획"},
              {"type": "agent_usage_stream", "agent_name": "planner"},
              {"type": "agent_text_stream", "agent_name": "coordinator", "data": "x"},
              {"type": "agent_text_stream", "agent_name": "planner", "data": "수정 "},
              {"type": "agent_text_stream", "agent_name": "planner", "data": "계획"}]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    assert ce.plans_from_events(tmp_path) == ["첫 계획", "수정 계획"]


# --- main(): stage, upload, invoke, download, score, against fakes -------------

def _main(tmp_path, monkeypatch, component, report_body):
    """Run component_eval.main() on a clean saved run; the fake runtime returns report_body as the new report."""
    import sys
    import boto3
    from test_runner import FakeAgentCore, FakeS3
    src = make_run.make_clean_run(tmp_path / "src")
    (src / "run.json").write_text(json.dumps({"scenario": "jungle_market_simple"}))
    (src / "events.jsonl").write_text(json.dumps({"type": "agent_text_stream", "agent_name": "planner", "data": "# Plan"}) + "\n")
    session = make_run.make_clean_run(tmp_path / "session")       # what the agent left in the session
    if report_body is not None:
        make_run.write_docx(session / "artifacts" / "final_report_with_citations.docx", report_body, [])
    s3 = FakeS3(session, "sess-c")
    agentcore = FakeAgentCore([{"event_type": "usage_metadata", "agent_name": component, "model_id": "global.anthropic.claude-sonnet-5",
                                "input_tokens": 1000, "output_tokens": 100},
                               {"type": "workflow_complete", "session_id": "sess-c"}])
    monkeypatch.setattr(boto3, "client", lambda name, **kw: agentcore if name == "bedrock-agentcore" else s3)
    monkeypatch.setattr(ce, "HERE", tmp_path)
    monkeypatch.setattr(sys, "argv", ["component_eval.py", component, "--from", str(src), "--plant", "5", "--tag", "t",
                                      "--runtime-arn", "arn:eval", "--bucket", "b"])
    assert ce.main() == 0
    run_dir = next((tmp_path / "eval_results" / "t" / "component" / component).iterdir())
    return run_dir, agentcore, s3


def test_main_reporter(tmp_path, monkeypatch):
    calcs, _ = make_run._calcs()
    v = {c["id"]: c["value"] for c in calcs}
    body = [f"총 매출은 ${v['calc_001']:,.2f} [1]입니다.", f"주문은 {v['calc_002']:,.0f}건이었습니다.", "나머지는 생략합니다."]
    run_dir, agentcore, s3 = _main(tmp_path, monkeypatch, "reporter", body)
    assert agentcore.payload["component"] == "reporter" and agentcore.payload["full_plan"] == "# Plan"
    assert agentcore.payload["artifacts_directory"].startswith("s3://b/uploads/eval-component-reporter-")
    staged = json.loads((run_dir / "staged_artifacts" / "citations.json").read_text())["citations"]
    planted = json.loads((run_dir / "planted.json").read_text())["marked_needs_review"]
    assert {c["calculation_id"] for c in staged if c["verification_status"] == "needs_review"} == set(planted)
    assert not (run_dir / "staged_artifacts" / "final_report_with_citations.docx").exists()
    r = json.loads((run_dir / "result.json").read_text())
    outcome = {k: x["outcome"] for k, x in r["per_calc"].items()}
    assert outcome["calc_001"] == "cited" and outcome["calc_002"] == "quoted"
    assert r["left_out"] == r["planted"] - 2 and r["cost_usd"] is not None


def test_main_validator(tmp_path, monkeypatch):
    run_dir, agentcore, _ = _main(tmp_path, monkeypatch, "validator", None)   # the clean run's citations: all verified
    assert agentcore.payload["component"] == "validator"
    assert not (run_dir / "staged_artifacts" / "citations.json").exists()
    r = json.loads((run_dir / "result.json").read_text())
    assert r["planted"] > 0 and r["missed"] == r["planted"] and r["caught"] == 0
