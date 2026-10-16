"""run_eval.py and compare.py against a fake runtime stream and a fake S3."""
import json
import shutil
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

import compare
import run_eval
from fixtures import make_run
from grade import load_scenario


def sse(ev):
    return f"data: {json.dumps(ev, ensure_ascii=False)}".encode()


class FakeAgentCore:
    def __init__(self, events):
        self.events = events
        self.payload = None

    def invoke_agent_runtime(self, **kw):
        self.payload = json.loads(kw["payload"])
        lines = [sse(e) for e in self.events] + [b""]
        return {"response": types.SimpleNamespace(iter_lines=lambda chunk_size=1: iter(lines))}


class FakeS3:
    """Serves one session folder built by make_run, records feedback uploads."""
    def __init__(self, session_dir, session_id):
        self.session_dir, self.session_id = Path(session_dir), session_id
        self.feedback, self.uploads = [], []

    def upload_file(self, path, bucket, key):
        self.uploads.append((Path(path).name, bucket, key))

    def put_object(self, Bucket, Key, Body, **_):
        self.feedback.append((Bucket, Key, json.loads(Body)))

    def get_paginator(self, _):
        files = [p for p in self.session_dir.rglob("*") if p.is_file()]
        prefix = f"{run_eval.SESSIONS_PREFIX}{self.session_id}/"
        contents = [{"Key": prefix + str(p.relative_to(self.session_dir)), "LastModified": datetime.now(timezone.utc)} for p in files]
        return types.SimpleNamespace(paginate=lambda **kw: [{"Contents": [c for c in contents if c["Key"].startswith(kw["Prefix"])]}])

    def download_file(self, bucket, key, dest):
        rel = key.split(f"{self.session_id}/", 1)[1]
        shutil.copy(self.session_dir / rel, dest)


def events(n_reviews, session_id="sess-1"):
    out = []
    for i in range(n_reviews):
        out.append({"type": "plan_review_request", "request_id": "req-1", "revision_count": i,
                    "feedback_s3_path": "s3://bucket-x/deep-insight/feedback/req-1.json"})
    out += [
        {"event_type": "usage_metadata", "agent_name": "planner", "model_id": "global.anthropic.claude-opus-5-5",
         "input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 3000, "cache_write_input_tokens": 0},
        {"event_type": "usage_metadata", "agent_name": "planner", "model_id": "global.anthropic.claude-opus-5-5",
         "input_tokens": 500, "output_tokens": 100},
        {"type": "workflow_complete", "session_id": session_id},
        {"type": "should_not_be_read"},
    ]
    return out


def run(tmp_path, scenario_name, n_reviews, reported_session="sess-1", fallback=False):
    session = make_run.make_clean_run(tmp_path / "session")
    s3 = FakeS3(session, "sess-1")
    agentcore = FakeAgentCore(events(n_reviews, reported_session))
    args = types.SimpleNamespace(tag="t", runtime_arn="arn:x", bucket="bucket-x", timeout=60, allow_session_fallback=fallback)
    run_dir = tmp_path / "eval_results" / "t" / "r1"
    scenario = load_scenario(scenario_name)
    scenario["data_directory"] = run_eval.upload_data(s3, args.bucket, scenario_name, scenario["upload"])
    meta, scores = run_eval.run_once(args, scenario_name, scenario, run_dir, (agentcore, s3))
    return meta, scores, s3, agentcore, run_dir


def test_auto_approve_and_scoring(tmp_path):
    meta, scores, s3, agentcore, run_dir = run(tmp_path, "jungle_market_simple", n_reviews=1)
    assert agentcore.payload["data_directory"] == "s3://bucket-x/uploads/eval-jungle-market-simple/"
    # only the listed files go up, nothing else next to the CSV
    assert sorted(name for name, *_ in s3.uploads) == ["column_definitions.json", "jungle-market-sales.csv"]
    assert s3.feedback == [("bucket-x", "deep-insight/feedback/req-1.json", s3.feedback[0][2])]
    assert s3.feedback[0][2]["approved"] is True
    assert meta["status"] == "completed" and meta["session_id"] == "sess-1"
    assert meta["agent_calls"] == {"planner": 2}  # one usage event per invocation
    usage = json.loads((run_dir / "usage.json").read_text())["by_agent"]["planner"]
    assert usage["input"] == 1500 and usage["cache_read"] == 3000
    assert scores["core_pass"], scores["core_fail_reasons"]
    assert scores["cache_hit_rate"] == 3000 / 4500
    assert "should_not_be_read" not in (run_dir / "events.jsonl").read_text()
    # debug/ came down with the session and was graded
    assert scores["code_executions"] == 2 and scores["code_exec_failed"] == 1
    assert scores["code_exec_fail_causes"] == {"missing_file": 1}


def test_scripted_revision_then_approve(tmp_path):
    meta, _, s3, _, _ = run(tmp_path, "jungle_market_revision", n_reviews=2)
    first, second = (f[2] for f in s3.feedback)
    assert first["approved"] is False and "도시별" in first["feedback"]
    assert second["approved"] is True
    assert meta["plan_revisions"] == 1


def test_unreported_session_is_not_guessed(tmp_path):
    """No session_id from the runtime → fail as session_unresolved (used to grade the newest S3 session)."""
    meta, scores, *_ = run(tmp_path, "jungle_market_simple", n_reviews=1, reported_session="")
    assert meta["status"] == "session_unresolved" and meta["artifact_files"] == 0
    assert not scores["core_pass"] and scores["core_fail_reasons"][0] == "status"


def test_session_fallback_is_opt_in_and_flagged(tmp_path):
    meta, scores, *_ = run(tmp_path, "jungle_market_simple", n_reviews=1, reported_session="", fallback=True)
    assert meta["session_id"] == "sess-1" and meta["session_id_source"] == "s3_newest_after_start"
    assert "another run" in scores["warning"]


def _tag(tmp_path, tag, rows, configs=None):
    for i, scores in enumerate(rows):
        d = tmp_path / tag / f"jungle_market-x-{i}"
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({"scenario": "jungle_market"}))
        (d / "scores.json").write_text(json.dumps({"scores": scores}))
        if configs:
            (d / "config.json").write_text(json.dumps(configs[i]))
    return str(tmp_path / tag)


def _table(tmp_path, tags):
    return compare.table("jungle_market", tags, {t: [s for _, s in compare.load_runs(t)] for t in tags})


def _row(text, label):
    return next(l for l in text.splitlines() if l.startswith(f"| {label}"))


def test_compare_flags_clear_regression_only(tmp_path):
    base = _tag(tmp_path, "base", [{"recompute_supported": 12, "cost_usd": 4.0 + i * 0.1, "core_pass": True} for i in range(5)])
    cand = _tag(tmp_path, "cand", [{"recompute_supported": 3, "cost_usd": 4.0 + i * 0.1, "core_pass": True} for i in range(5)])
    text = _table(tmp_path, [base, cand])
    assert "▼ worse" in _row(text, "calculations recomputed")   # 12 → 3 on every run
    cost = _row(text, "cost")
    assert "▼" not in cost and "▲" not in cost                   # same costs


def test_two_of_three_to_three_of_three_is_not_flagged(tmp_path):
    """The old rule called 67% → 100% better; with n=3 that can be luck."""
    base = _tag(tmp_path, "base", [{"core_pass": v} for v in (True, True, False)])
    cand = _tag(tmp_path, "cand", [{"core_pass": True} for _ in range(3)])
    text = _table(tmp_path, [base, cand])
    row = _row(text, "core pass rate")
    assert "67% [21–94%] (2/3)" in row and "100% [44–100%] (3/3)" in row
    assert "▲" not in row
    assert "Fewer than 5 runs" in text
    assert "k=2 33%" in _row(text, "pass^k")                     # C(2,2)/C(3,2)


def test_pass_k_and_wilson():
    assert compare.pass_k([1, 1, 0]) == pytest.approx([2 / 3, 1 / 3, 0.0])
    lo, hi = compare.wilson(3, 3)
    assert round(lo, 2) == 0.44 and hi == 1.0


def test_mixed_configs_within_a_tag_are_flagged(tmp_path):
    cfg = lambda sha: {"git_sha": sha, "runtime_version": "5", "models": {"CODER_MODEL_ID": "global.anthropic.claude-sonnet-5"}}
    base = _tag(tmp_path, "base", [{"core_pass": True}] * 2, configs=[cfg("aaaaaaa1"), cfg("bbbbbbb2")])
    text = _table(tmp_path, [base])
    assert "mixes 2 configurations" in text


def test_constant_series_with_three_runs_are_not_flagged(tmp_path):
    """With n=3, (0,0,0) vs (1,1,1) bootstraps to a zero-width interval; that isn't evidence of a change."""
    base = _tag(tmp_path, "base", [{"core_pass": False, "recompute_supported": 0} for _ in range(3)])
    cand = _tag(tmp_path, "cand", [{"core_pass": True, "recompute_supported": 1} for _ in range(3)])
    text = _table(tmp_path, [base, cand])
    assert "▲" not in _row(text, "core pass rate") and "▲" not in _row(text, "calculations recomputed")
    assert "shown without ▲/▼" in text


def test_constant_series_with_five_runs_are_flagged(tmp_path):
    base = _tag(tmp_path, "base5", [{"recompute_supported": 0} for _ in range(5)])
    cand = _tag(tmp_path, "cand5", [{"recompute_supported": 1} for _ in range(5)])
    assert "▲ better" in _row(_table(tmp_path, [base, cand]), "calculations recomputed")


def test_test_scenarios_need_allow_test():
    scenarios = {n: load_scenario(n) for n in ("jungle_market_simple", "moon_market_kr")}
    assert "moon_market_kr is a test scenario" in run_eval.refuse_test_split(scenarios, allow_test=False)
    assert run_eval.refuse_test_split(scenarios, allow_test=True) is None
    assert run_eval.refuse_test_split({"yummy_food_kr": load_scenario("yummy_food_kr")}, allow_test=False) is None


def test_compare_reports_dev_and_test_apart(tmp_path, monkeypatch, capsys):
    tag = tmp_path / "t"
    for i, (sc, ok) in enumerate([("jungle_market", True), ("yummy_food_kr", False), ("moon_market_kr", True)]):
        d = tag / f"{sc}-x-{i}"
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({"scenario": sc}))       # no split recorded: taken from scenarios.yaml
        (d / "scores.json").write_text(json.dumps({"scores": {"core_pass": ok}}))
    monkeypatch.setattr("sys.argv", ["compare.py", str(tag)])
    compare.main()
    out = capsys.readouterr().out
    dev, test = out.split("## Test scenarios")
    assert "pooled over jungle_market, yummy_food_kr" in dev and "50% [" in dev and "moon_market_kr" not in dev
    assert "### moon_market_kr" in test and "100% [" in test and "jungle_market" not in test
    monkeypatch.setattr("sys.argv", ["compare.py", str(tag), "--split", "dev"])
    compare.main()
    assert "Test scenarios" not in capsys.readouterr().out
