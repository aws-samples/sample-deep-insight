"""Component runs on a fixed input: pinning, per-repeat seeds, run_eval --components, compare.py. No AWS."""
import json
import sys

import pytest

import compare
import component_eval as ce
import run_eval
from fixtures import make_run
from grade import load_scenario


def _saved_run(path, scenario="jungle_market"):
    """A saved run as run_eval.py writes it: artifacts through the Auditor, run.json, events.jsonl, config.json."""
    src = make_run.make_clean_run(path)
    a = src / "artifacts"
    (a / "cache").mkdir()
    (a / "cache" / "unread.pkl").write_bytes(b"x")
    (a / "code").mkdir()
    (a / "code" / "reporter_step1.py").write_text("")
    (a / "code" / "__pycache__").mkdir()
    (a / "code" / "__pycache__" / "x.pyc").write_bytes(b"x")
    (src / "run.json").write_text(json.dumps({"scenario": scenario}))
    (src / "events.jsonl").write_text(json.dumps({"type": "agent_text_stream", "agent_name": "planner", "data": "# Plan"}) + "\n")
    (src / "config.json").write_text(json.dumps({"git_sha": "abc1234", "runtime_version": "12", "models": {"CODER_MODEL_ID": "m"}}))
    return src


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "INPUTS", tmp_path / "component_inputs")
    monkeypatch.setattr(ce, "HERE", tmp_path)
    return tmp_path / "component_inputs"


def test_pin_keeps_the_input_and_drops_later_outputs(tmp_path, inputs):
    dest = ce.pin(_saved_run(tmp_path / "src"))
    a = dest / "artifacts"
    assert dest == inputs / "jungle_market"
    assert (a / "citations.json").is_file() and (a / "calculation_metadata.json").is_file()
    assert (a / ce.PINNED_REPORT).is_file()                       # kept: the Reporter component picks from it
    assert not (a / "audit_findings.json").exists() and not (a / "code" / "reporter_step1.py").exists()
    assert not (a / "cache" / "unread.pkl").exists() and not (a / "code" / "__pycache__").exists()
    assert (dest / "plan.md").read_text() == "# Plan" and ce.source_plan(dest) == "# Plan"
    meta = json.loads((dest / "run.json").read_text())
    assert meta["scenario"] == "jungle_market" and meta["pinned_from"] == "src" and meta["git_sha"] == "abc1234"
    assert ce.pinned_input("jungle_market") == dest and ce.pinned_input("yummy_food_kr") is None
    with pytest.raises(ValueError, match="--force"):
        ce.pin(tmp_path / "src")
    ce.pin(tmp_path / "src", force=True)


def test_pin_refuses_a_run_without_a_report(tmp_path, inputs):
    src = _saved_run(tmp_path / "src")
    (src / "artifacts" / ce.PINNED_REPORT).unlink()
    with pytest.raises(ValueError, match="past the Reporter"):
        ce.pin(src)


def test_scenario_settings_from_scenarios_yaml():
    assert ce.scenario_settings(load_scenario("jungle_market"), "validator") == (6, 0)
    assert ce.scenario_settings(load_scenario("yummy_food_kr"), "reporter") == (4, 0)
    assert ce.scenario_settings(load_scenario("jungle_market_simple"), "validator") is None


def _fakes(tmp_path, component):
    from test_runner import FakeAgentCore, FakeS3
    session = make_run.make_clean_run(tmp_path / "session")
    return (FakeAgentCore([{"event_type": "usage_metadata", "agent_name": component, "model_id": "global.anthropic.claude-sonnet-5",
                            "input_tokens": 1000, "output_tokens": 100},
                           {"type": "workflow_complete", "session_id": "sess-c"}]),
            FakeS3(session, "sess-c"))


def _planted(tmp_path, tag, component):
    return {json.loads(p.read_text())["repeat"]: json.loads(p.read_text())
            for p in (tmp_path / "eval_results" / tag / "component" / component).glob("*/planted.json")}


def test_repeat_i_plants_the_same_errors_in_any_batch(tmp_path, inputs):
    """Repeat 2 of one --repeat 2 batch and of a --first-repeat 2 batch get the same input."""
    src = ce.pin(_saved_run(tmp_path / "src"))
    kw = dict(plant=3, seed=0, runtime_arn="arn:eval", bucket="b", log=lambda m: None)
    ce.run_components("validator", [src], repeats=range(1, 3), tag="a", clients=_fakes(tmp_path, "validator"), **kw)
    ce.run_components("validator", [src], repeats=range(2, 3), tag="b", clients=_fakes(tmp_path, "validator"), **kw)
    a, b = _planted(tmp_path, "a", "validator"), _planted(tmp_path, "b", "validator")
    assert a[2]["plants"] == b[2]["plants"] and a[2]["scenario"] == "jungle_market" and a[2]["source_run"] == "jungle_market"
    assert compare.input_fingerprint(a[2]) == compare.input_fingerprint(b[2])


def test_main_scenario_uses_the_pinned_input_and_its_settings(tmp_path, inputs, monkeypatch):
    import boto3
    ce.pin(_saved_run(tmp_path / "src"))
    agentcore, s3 = _fakes(tmp_path, "reporter")
    monkeypatch.setattr(boto3, "client", lambda name, **kw: agentcore if name == "bedrock-agentcore" else s3)
    monkeypatch.setattr(sys, "argv", ["component_eval.py", "reporter", "--scenario", "jungle_market", "--tag", "t",
                                      "--runtime-arn", "arn:eval", "--bucket", "b"])
    assert ce.main() == 0
    p = _planted(tmp_path, "t", "reporter")[1]
    assert (p["plant"], p["seed"], p["source_run"]) == (4, 0, "jungle_market")    # scenarios.yaml: reporter plant 4
    assert agentcore.payload["full_plan"] == "# Plan"
    run_dir = next((tmp_path / "eval_results" / "t" / "component" / "reporter").iterdir())
    assert json.loads((run_dir / "result.json").read_text())["model_id"] == "global.anthropic.claude-sonnet-5"
    assert "git_sha" in json.loads((run_dir / "config.json").read_text())
    monkeypatch.setattr(sys, "argv", ["component_eval.py", "reporter", "--scenario", "jungle_market_simple", "--tag", "t",
                                      "--runtime-arn", "arn:eval", "--bucket", "b"])
    with pytest.raises(SystemExit):
        ce.main()                                                            # no pinned input, no settings


def test_run_eval_component_jobs(tmp_path, inputs):
    ce.pin(_saved_run(tmp_path / "src"))
    jobs = run_eval.component_jobs(["jungle_market", "jungle_market_simple", "yummy_food_kr"], ["validator", "reporter"])
    assert [(c, n, p, s) for c, n, _, p, s in jobs] == [("validator", "jungle_market", 6, 0), ("reporter", "jungle_market", 4, 0)]
    assert run_eval.component_jobs(["jungle_market"], []) == []


# --- compare.py ---------------------------------------------------------------

def _component_run(tag, i, result, planted, scenario="jungle_market", component="validator"):
    d = tag / "component" / component / f"{scenario}-20261018-120000-{i}"
    d.mkdir(parents=True)
    (d / "result.json").write_text(json.dumps(result))
    (d / "planted.json").write_text(json.dumps({"scenario": scenario, "source_run": "jungle_market", "plant": 6, "seed": 0,
                                                "repeat": i, **planted}))


def _validator(caught, missed=0, model="global.anthropic.claude-sonnet-5"):
    return {"planted": caught + missed, "caught": caught, "missed": missed, "not_checked": 0, "false_alarm": 0,
            "value_changed": 0, "recall": caught / (caught + missed), "cost_usd": 1.5, "model_id": model}


def test_compare_shows_component_runs_next_to_the_full_runs(tmp_path, capsys, monkeypatch):
    base, cand = tmp_path / "base", tmp_path / "cand"
    for i in (1, 2):
        _component_run(base, i, _validator(3, 3), {"plants": {f"calc_{i}": 1}})
        _component_run(cand, i, _validator(6, model="global.anthropic.claude-sonnet-4-5-20250929-v1:0"), {"plants": {f"calc_{i}": 1}})
    monkeypatch.setattr("sys.argv", ["compare.py", str(base), str(cand)])
    compare.main()
    out = capsys.readouterr().out
    assert "| model | claude-sonnet-5 | claude-sonnet-4-5-20250929 |" in out
    assert "Component runs only" in out
    assert "### jungle_market" in out and "| validator on its own (component runs) | base | cand | Δ cand |" in out
    row = next(l for l in out.splitlines() if l.startswith("| recall"))
    assert "50.0%" in row and "100.0%" in row and "+50%p" in row
    assert "not the same input" not in out


def test_compare_flags_component_runs_on_different_inputs(tmp_path, capsys, monkeypatch):
    base, cand = tmp_path / "base", tmp_path / "cand"
    _component_run(base, 1, _validator(3, 3), {"plants": {"calc_1": 1}})
    _component_run(cand, 1, _validator(6), {"plants": {"calc_9": 1}})      # same repeat, other errors
    monkeypatch.setattr("sys.argv", ["compare.py", str(base), str(cand)])
    compare.main()
    assert "repeat(s) 1 planted different errors" in capsys.readouterr().out
