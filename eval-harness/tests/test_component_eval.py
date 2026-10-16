"""component_eval.py: what is planted, what is staged, how the Validator's answer is scored. No AWS."""
import json
import random

import component_eval as ce
from fixtures import make_run


def _calcs():
    return {
        "r1": {"id": "r1", "value": 100.0, "importance": "high", "source_file": "./data/x.csv"},
        "r2": {"id": "r2", "value": 2987, "importance": "high", "source_file": "./data/x.csv"},
        "r3": {"id": "r3", "value": 5.0, "importance": "medium", "source_file": "./data/x.csv"},
        "d1": {"id": "d1", "value": 3.39, "importance": "high", "source_file": "./artifacts/media_agg.csv"},
        "d2": {"id": "d2", "value": "n/a", "importance": "high", "source_file": "./artifacts/media_agg.csv"},
    }


def test_pick_plants_splits_raw_and_derived():
    ids, kinds = ce.pick_plants(_calcs(), {"r1": True, "r2": True, "r3": True}, "x.csv", 4, random.Random(0))
    assert sorted(ids) == ["d1", "r1", "r2"]                    # r3 is medium, d2 is not a number
    assert kinds == {"r1": "raw", "r2": "raw", "d1": "derived"}
    ids, _ = ce.pick_plants(_calcs(), {"r1": True, "r2": False}, "x.csv", 2, random.Random(0))
    assert sorted(ids) == ["d1", "r1"]                          # r2 was not confirmed right


def test_planted_value_keeps_the_type_and_differs():
    assert ce.planted_value(2987) == 3286 and isinstance(ce.planted_value(2987), int)
    assert ce.planted_value(3.39) == 3.729 and ce.planted_value(0) == 1 and ce.planted_value(5) == 6


def test_stage_removes_later_outputs_and_plants(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    src = run / "artifacts"
    (src / "code").mkdir(exist_ok=True)
    (src / "code" / "validator_step1.py").write_text("x")
    (src / "code" / "coder_step1.py").write_text("x")
    meta = json.loads((src / "calculation_metadata.json").read_text(encoding="utf-8"))
    cid = meta["calculations"][0]["id"]
    ce.stage(src, tmp_path / "staged", {cid: {"planted": 1.0}})
    staged = tmp_path / "staged"
    assert not (staged / "citations.json").exists() and not (staged / "final_report_with_citations.docx").exists()
    assert not (staged / "code" / "validator_step1.py").exists() and (staged / "code" / "coder_step1.py").exists()
    assert json.loads((staged / "calculation_metadata.json").read_text(encoding="utf-8"))["calculations"][0]["value"] == 1.0


def test_score(tmp_path):
    cites = {"citations": [
        {"citation_id": "[1]", "calculation_id": "r1", "value": 110.0, "verification_status": "needs_review"},
        {"citation_id": "[2]", "calculation_id": "d1", "value": 3.39, "verification_status": "verified"},   # missed, and "corrected"
        {"citation_id": "[3]", "calculation_id": "ok", "value": 7, "verification_status": "needs_review"},   # right value flagged
        {"citation_id": "[4]", "calculation_id": "ok2", "value": 8, "verification_status": "verified"},
    ]}
    (tmp_path / "citations.json").write_text(json.dumps(cites))
    plants = {"r1": {"planted": 110.0}, "d1": {"planted": 3.729}, "r2": {"planted": 3286}}
    r = ce.score(tmp_path, plants, {"r1": "raw", "d1": "derived", "r2": "raw"}, ["ok", "ok2", "r1"])
    assert (r["caught"], r["missed"], r["not_checked"], r["value_changed"]) == (1, 1, 1, 1)
    assert r["recall"] == 0.5 and r["by_kind"]["derived"]["missed"] == 1
    assert (r["false_alarm"], r["right_checked"]) == (1, 2)


def test_plans_from_events_takes_each_invocation(tmp_path):
    events = [{"type": "agent_text_stream", "agent_name": "planner", "data": "첫 계획"},
              {"type": "agent_usage_stream", "agent_name": "planner"},
              {"type": "agent_text_stream", "agent_name": "coordinator", "data": "x"},
              {"type": "agent_text_stream", "agent_name": "planner", "data": "수정 "},
              {"type": "agent_text_stream", "agent_name": "planner", "data": "계획"}]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    assert ce.plans_from_events(tmp_path) == ["첫 계획", "수정 계획"]


# --- Reporter: needs_review values must stay out of the report -----------------

def _mark(run, edit):
    path = run / "artifacts" / "citations.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data["citations"])
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_pick_reporter_plants_takes_cited_verified_distinct_values(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    def edit(cites):
        cites[2]["verification_status"] = "needs_review"                     # AOV: not verified
        cites.append({"citation_id": "[6]", "calculation_id": "twin", "value": cites[3]["value"] * 1.005,
                      "verification_status": "verified"})                     # within 1% of the top city's revenue
        cites[4]["value"] = 42                                                 # a small integer
    _mark(run, edit)
    plants = ce.pick_reporter_plants(run / "artifacts", 10, random.Random(0))
    meta = {c["id"]: c["value"] for c in json.loads((run / "artifacts" / "calculation_metadata.json").read_text())["calculations"]}
    assert sorted(plants) == ["calc_001", "calc_002"]                          # total revenue, order count
    assert plants["calc_002"] == meta["calc_002"]
    assert len(ce.pick_reporter_plants(run / "artifacts", 1, random.Random(0))) == 1


def test_stage_reporter_keeps_the_validators_files_and_marks(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    src = run / "artifacts"
    (src / "code").mkdir(exist_ok=True)
    for f in ("validator_step1.py", "reporter_step1.py", "svg_docx.py", "audit_engine.py", "coder_step1.py"):
        (src / "code" / f).write_text("x")
    (src / "report_draft.docx").write_text("x")
    ce.stage_reporter(src, tmp_path / "staged", {"calc_001": 1.0})
    staged = tmp_path / "staged"
    assert not (staged / "final_report_with_citations.docx").exists() and not (staged / "report_draft.docx").exists()
    assert not (staged / "audit_findings.json").exists()
    assert sorted(p.name for p in (staged / "code").iterdir()) == ["coder_step1.py", "validator_step1.py"]
    assert (staged / "validation_report.txt").exists()
    status = {c["calculation_id"]: c["verification_status"] for c in json.loads((staged / "citations.json").read_text())["citations"]}
    assert status["calc_001"] == "needs_review" and status["calc_002"] == "verified"


def test_score_reporter(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    a = run / "artifacts"
    body = ["총 매출은 $110,270.26 [1]입니다.",                      # cited: the marker points to it
            "도시 | 매출 | 비고", "Berlin | 6,879.45 | -",             # quoted in a table, no marker
            "최저 매출일은 $6,891입니다.",                            # 6,891 is not 6,879.45 at that precision
            "고객 1인당 3.7회 구매했습니다."]                          # 2 significant digits identify nothing
    make_run.write_docx(a / "final_report_with_citations.docx", body, [])
    r = ce.score_reporter(a, {"calc_001": 110270.26, "x_berlin": 6879.45, "x_daily": 6880.2, "x_freq": 3.69, "x_gone": 4321.0})
    outcome = {k: v["outcome"] for k, v in r["per_calc"].items()}
    assert outcome == {"calc_001": "cited", "x_berlin": "quoted", "x_daily": "left_out", "x_freq": "left_out", "x_gone": "left_out"}
    assert (r["cited"], r["quoted"], r["left_out"], r["leaked"]) == (1, 1, 3, 2) and r["leak_rate"] == 0.4
    assert r["graders"]["broken_citation_refs"] == 0 and r["graders"]["cited_value_match_rate"] == 1.0


def test_score_reporter_without_a_report(tmp_path):
    r = ce.score_reporter(tmp_path, {"c": 123.4})
    assert r["report_ok"] is False and r["left_out"] == 0


def test_printed_values_reads_ratios_and_scales():
    vals = ce.printed_values(["재구매율 37.7%[3], 매출 1.23만 원, 3.7배"])
    assert (37.7, 0.05) in [(v, round(h, 6)) for v, h in vals]
    assert (12300.0, 50.0) in [(v, h) for v, h in vals]
    assert all(v != 3.7 for v, _ in vals) and all(v != 3.0 for v, _ in vals)   # [3] is a marker, not a number


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
