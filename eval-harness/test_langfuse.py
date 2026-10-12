"""langfuse_sync.py and calibrate.py's Langfuse path against an in-memory fake of the REST API."""
import json
import shutil

import pytest

import calibrate
import langfuse_sync as ls
from fixtures import make_run
from grade import grade_run, load_scenario


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.content = b"x"
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeLangfuse:
    """Just enough of the public API: configs, datasets, items, run items, runs, ingestion, queues, scores."""
    def __init__(self, ingestion_errors=None):
        self.auth = None
        self.configs, self.datasets, self.items, self.run_items, self.events = {}, set(), {}, [], []
        self.queues, self.queue_items, self.annotations = {}, [], []
        self.ingestion_errors = ingestion_errors or []
        self.runs, self.deleted = set(), []

    def request(self, method, url, params=None, json=None, timeout=None):
        path = url.split("://", 1)[1].split("/", 1)[1]
        path = "/" + path
        if method == "GET":
            return self._get(path, params or {})
        if method == "DELETE":
            return self._delete(path)
        return self._post(path, json)

    def _delete(self, path):
        self.deleted.append(path)
        if path.startswith(f"/api/public/datasets/{ls.DATASET}/runs/"):
            self.runs.discard(path.rsplit("/", 1)[1])
            self.run_items = [r for r in self.run_items if r["runName"] != path.rsplit("/", 1)[1]]
        if "/annotation-queues/" in path and "/items/" in path:
            self.queue_items = [o for o in self.queue_items if f"item-{o}" != path.rsplit("/", 1)[1]]
        return Resp(200, {})

    def _page(self, rows):
        return Resp(200, {"data": rows, "meta": {"totalPages": 1}})

    def _get(self, path, params):
        if path == "/api/public/score-configs":
            return self._page([{"id": i, "name": n} for n, i in self.configs.items()])
        if path.startswith("/api/public/v2/datasets/"):
            return Resp(200, {"name": path.rsplit("/", 1)[1]}) if path.rsplit("/", 1)[1] in self.datasets else Resp(404, {"message": "not found"})
        if path.startswith(f"/api/public/datasets/{ls.DATASET}/runs/"):
            name = path.rsplit("/", 1)[1]
            return Resp(200, {"id": "run-" + name}) if name in self.runs else Resp(404, {"message": "not found"})
        if path == "/api/public/dataset-items":
            return self._page(list(self.items.values()))
        if path == "/api/public/annotation-queues":
            return self._page(list(self.queues.values()))
        if path.endswith("/items") and "annotation-queues" in path:
            return self._page([{"id": f"item-{o}", "objectId": o} for o in self.queue_items])
        if path == "/api/public/v2/scores":
            return self._page([a for a in self.annotations if a["traceId"] == params.get("traceId")
                               and params.get("source") in (None, "ANNOTATION")])
        raise AssertionError(f"unexpected GET {path}")

    def _post(self, path, body):
        if path == "/api/public/score-configs":
            self.configs[body["name"]] = f"cfg-{body['name']}"
            return Resp(200, {"id": self.configs[body["name"]]})
        if path == "/api/public/v2/datasets":
            self.datasets.add(body["name"])
            return Resp(200, body)
        if path == "/api/public/dataset-items":
            self.items[body["id"]] = body
            return Resp(200, body)
        if path == "/api/public/dataset-run-items":
            self.runs.add(body["runName"])
            self.run_items = [r for r in self.run_items if (r["runName"], r["datasetItemId"]) != (body["runName"], body["datasetItemId"])]
            self.run_items.append(body)  # Langfuse keeps one run item per (run, dataset item)
            return Resp(200, body)
        if path == "/api/public/ingestion":
            self.events += body["batch"]
            return Resp(207, {"successes": [], "errors": self.ingestion_errors})
        if path == "/api/public/annotation-queues":
            q = {"id": "q1", **body}
            self.queues["q1"] = q
            return Resp(200, q)
        if path.endswith("/items") and "annotation-queues" in path:
            self.queue_items.append(body["objectId"])
            return Resp(200, body)
        raise AssertionError(f"unexpected POST {path}")


@pytest.fixture
def tag_dir(tmp_path, monkeypatch):
    """A tag folder with one graded run (clean fixture + judge.json), inside a fake eval-harness root."""
    monkeypatch.setattr(ls, "HERE", tmp_path)
    monkeypatch.setattr(calibrate, "HERE", tmp_path)
    tag = tmp_path / "eval_results" / "baseline"
    run = make_run.make_clean_run(tag / "jungle_market_simple-20261002-000000-1")
    (run / "run.json").write_text(json.dumps({"scenario": "jungle_market_simple", "status": "completed",
                                              "started_at": "2026-10-02T06:00:00+00:00", "agent_span_s": {"coder": 12.0},
                                              "agent_calls": {"coder": 1}}))
    (run / "config.json").write_text(json.dumps({"git_sha": "abcdef1234567", "runtime_version": "5", "models": {"CODER_MODEL_ID": "global.anthropic.claude-sonnet-5"}}))
    (run / "usage.json").write_text(json.dumps({"by_agent": {"coder": {"model_id": "global.anthropic.claude-sonnet-5", "input": 1000, "output": 100, "cache_read": 0, "cache_write": 0}}}))
    sc = load_scenario("jungle_market_simple")
    verdict = {"requirements": [{"requirement_id": r["id"], "status": "met", "evidence": "quoted"} for r in sc["requirements"]],
               "criteria": [{"criterion": c, "score": 4, "justification": f"why {c}"} for c in ls.CRITERIA], "summary": "ok"}
    (run / "judge.json").write_text(json.dumps({"verdict": verdict, "metrics": {}}))
    result = grade_run(run, sc["csv"], sc["answer_key"], sc)
    (run / "scores.json").write_text(json.dumps(result))
    (tag / "pairwise_vs_baseline.json").write_text(json.dumps({
        "baseline": "baseline", "candidate": "baseline", "judge_model": "m",
        "scenarios": {"jungle_market_simple": {"pairs": 3, "win_rate": 0.5, "wins": 1, "ties": 1, "losses": 1, "both_bad": 0, "position_consistency": 2 / 3}}}))
    return tag, run


def sync(tag, fake, queue=False, manifest=None):
    lf = ls.Langfuse("http://lf", "pk", "sk", session=fake)
    configs = ls.ensure_score_configs(lf, ["total_revenue", "segments"])
    run = next(tag.glob("*/run.json")).parent
    ls.ensure_dataset_items(lf, {"jungle_market_simple": load_scenario("jungle_market_simple")}, {"jungle_market_simple": ls.repeat_of(run)})
    events, trace_id, scenario, _, started = ls.run_events(run, "baseline", configs)
    lf.ingest(events)
    ls.reset_dataset_run(lf, "baseline", ls.pairwise_names(tag))
    ls.link_run_items(lf, "baseline", [(trace_id, scenario, ls.repeat_of(run), started)], "git abcdef1")
    n_pw = ls.pairwise_scores(lf, tag)
    if manifest is not None:
        current = {trace_id: {"run_dir": str(run), "tag": "baseline", "scenario": scenario}}
        ls.retire_traces(lf, manifest, current)
        manifest.update(current)
    if queue:
        ls.queue_traces(lf, [trace_id], configs)
    return lf, trace_id, n_pw


def test_trace_has_report_scores_and_agents(tag_dir):
    tag, run = tag_dir
    fake = FakeLangfuse()
    _, trace_id, _ = sync(tag, fake)
    trace = next(e["body"] for e in fake.events if e["type"] == "trace-create")
    assert trace["id"] == trace_id and "$110,270.26" in trace["output"]       # the report is readable in the UI
    assert trace["tags"] == ["baseline", "jungle_market_simple", "PASS"] and trace["release"] == "abcdef123456"
    gen = next(e["body"] for e in fake.events if e["type"] == "generation-create")
    assert gen["name"] == "coder" and gen["usageDetails"]["input"] == 1000 and gen["costDetails"]["total"] > 0
    scores = {e["body"]["name"]: e["body"] for e in fake.events if e["type"] == "score-create"}
    assert scores["core_pass"]["value"] == 1 and scores["core_pass"]["dataType"] == "BOOLEAN"
    assert scores["recompute_supported"]["value"] == 5.0
    assert scores["insight_depth"]["comment"] == "why insight_depth" and scores["insight_depth"]["configId"] == "cfg-insight_depth"
    assert scores["req.total_revenue"]["value"] == "met" and scores["req.total_revenue"]["dataType"] == "CATEGORICAL"


def test_ids_are_stable_so_resync_updates_in_place(tag_dir):
    tag, _ = tag_dir
    a, b = FakeLangfuse(), FakeLangfuse()
    sync(tag, a)
    sync(tag, b)
    assert [e["body"].get("id") for e in a.events] == [e["body"].get("id") for e in b.events]
    assert len({e["id"] for e in a.events}) == len(a.events)                    # no duplicate events within a sync


def test_dataset_item_run_item_and_pairwise(tag_dir):
    tag, _ = tag_dir
    fake = FakeLangfuse()
    _, trace_id, n_pw = sync(tag, fake)
    item = fake.items[ls.item_id("jungle_market_simple", 1)]
    assert item["input"]["repeat"] == 1
    assert item["expectedOutput"]["pass"]["required_facts"] == ["total_revenue", "order_count", "avg_order_value"]
    answers = {a["id"]: a for a in item["expectedOutput"]["answer_key"]}
    assert answers["total_revenue"]["value"] == 110270.26
    ranking = next(a for a in answers.values() if a["kind"] == "ranking")   # rankings carry their order, not a value
    assert ranking["order"] and "value" not in ranking
    assert fake.run_items == [{"runName": "baseline", "runDescription": "git abcdef1", "datasetItemId": item["id"], "traceId": trace_id,
                               "createdAt": "2026-10-02T06:00:00Z"}]   # the run's own time, not the upload time
    pw = [e["body"] for e in fake.events if e["body"].get("datasetRunId")]
    assert n_pw == 1 and pw[0]["datasetRunId"] == "run-baseline" and pw[0]["value"] == 0.5


def test_every_timestamp_is_the_runs_own_time(tag_dir):
    """The UI looks a trace up by the clicked score's / run item's time; upload-time stamps hid traces."""
    tag, _ = tag_dir
    fake = FakeLangfuse()
    sync(tag, fake)
    by_type = {}
    for e in fake.events:
        if e["body"].get("datasetRunId"):
            continue  # run-level pairwise scores aren't used to look up traces
        by_type.setdefault(e["type"], set()).add(e["timestamp"][:10])
    assert by_type["trace-create"] == {"2026-10-02"} and by_type["score-create"] == {"2026-10-02"}


def test_changed_results_replace_the_trace(tag_dir):
    tag, run = tag_dir
    fake, manifest = FakeLangfuse(), {}
    _, first, _ = sync(tag, fake, queue=True, manifest=manifest)
    _, same, _ = sync(tag, fake, manifest=manifest)
    assert same == first and not any("/traces/" in d for d in fake.deleted)     # unchanged → same trace
    (run / "judge.json").write_text((run / "judge.json").read_text().replace("why insight_depth", "rewritten"))
    _, second, _ = sync(tag, fake, manifest=manifest)
    assert second != first and f"/api/public/traces/{first}" in fake.deleted
    assert set(manifest) == {second} and first not in fake.queue_items


def test_labeled_trace_is_kept(tag_dir):
    tag, run = tag_dir
    fake, manifest = FakeLangfuse(), {}
    _, first, _ = sync(tag, fake, manifest=manifest)
    fake.annotations = [{"traceId": first, "name": "insight_depth", "value": 3}]
    (run / "judge.json").write_text((run / "judge.json").read_text().replace("why insight_depth", "rewritten"))
    _, second, _ = sync(tag, fake, manifest=manifest)
    assert f"/api/public/traces/{first}" not in fake.deleted
    assert manifest[first]["superseded_by"] == second


def test_configs_created_once(tag_dir):
    tag, _ = tag_dir
    fake = FakeLangfuse()
    sync(tag, fake)
    n = len(fake.configs)
    sync(tag, fake)
    assert len(fake.configs) == n and "req.segments" in fake.configs and "reasoning_soundness" in fake.configs


def test_ingestion_errors_raise(tag_dir):
    tag, _ = tag_dir
    with pytest.raises(RuntimeError, match="ingestion rejected"):
        sync(tag, FakeLangfuse(ingestion_errors=[{"id": "x", "status": 400, "message": "bad"}]))


def test_queue_adds_each_trace_once(tag_dir):
    tag, _ = tag_dir
    fake = FakeLangfuse()
    lf, trace_id, _ = sync(tag, fake, queue=True)
    ls.queue_traces(lf, [trace_id], {c: f"cfg-{c}" for c in fake.configs})
    assert fake.queue_items == [trace_id]
    assert "cfg-insight_depth" in fake.queues["q1"]["scoreConfigIds"]


def test_calibrate_reads_langfuse_annotations(tag_dir, capsys):
    tag, run = tag_dir
    fake = FakeLangfuse()
    lf, trace_id, _ = sync(tag, fake)
    (tag.parent / "langfuse_sync.json").write_text(json.dumps({trace_id: {"run_dir": str(run.relative_to(tag.parent.parent))}}))
    fake.annotations = [
        {"traceId": trace_id, "name": "insight_depth", "value": 3},
        {"traceId": trace_id, "name": "req.total_revenue", "value": 1, "stringValue": "met"},
    ]
    calibrate.score_langfuse(lf)
    out = capsys.readouterr().out
    assert "requirement status agreement: 1/1" in out
    assert "| insight_depth | 1 | 0% | 100% |" in out                          # judge 4 vs human 3


def test_dry_run_needs_no_credentials(tag_dir, monkeypatch, capsys):
    tag, _ = tag_dir
    for k in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("sys.argv", ["langfuse_sync.py", str(tag), "--dry-run"])
    assert ls.main() == 0
    assert "1 runs" in capsys.readouterr().out


def test_cloud_host_refused_unless_allowed(monkeypatch):
    for host in ("https://cloud.langfuse.com", "https://us.cloud.langfuse.com", "eu.cloud.langfuse.com"):
        assert ls.is_cloud_host(host)
    for host in ("https://langfuse.internal.example.com", "http://localhost:3000", "https://notcloud.langfuse.com.evil"):
        assert not ls.is_cloud_host(host)
    monkeypatch.setattr(ls, "dotenv_values", lambda p: {})
    monkeypatch.setenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    with pytest.raises(SystemExit, match="Langfuse Cloud"):
        ls.credentials()
    assert ls.credentials(allow_cloud=True)[0] == "https://us.cloud.langfuse.com"
