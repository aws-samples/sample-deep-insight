import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import ci
from fixtures import make_run


class Body(io.BytesIO):
    def iter_chunks(self, chunk_size):
        while data := self.read(chunk_size):
            yield data


class S3:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.get_calls = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        def paginate(Bucket, Prefix):
            return [{"Contents": [{"Key": k, "Size": len(v)} for (b, k), v in self.objects.items()
                                  if b == Bucket and k.startswith(Prefix)]}]
        return SimpleNamespace(paginate=paginate)

    def download_file(self, bucket, key, dest):
        Path(dest).write_bytes(self.objects[bucket, key])

    def upload_file(self, path, bucket, key):
        self.objects[bucket, key] = Path(path).read_bytes()

    def head_object(self, Bucket, Key):
        data = self.objects[Bucket, Key]
        return {"ContentLength": len(data), "ETag": '"' + hashlib.sha256(data).hexdigest() + '"'}

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)
        return {"Body": Body(self.objects[kwargs["Bucket"], kwargs["Key"]])}


def answer_key(run):
    calc = json.loads((run / "artifacts/calculation_metadata.json").read_text())["calculations"][0]
    return {"version": 1, "scenario": "jungle_market_simple", "facts": [
        {"id": "sales", "statement": "Total deduplicated revenue in USD", "expected": calc["value"]},
    ]}


def source_objects(run):
    objects = {}
    for name in ("candidate", "baseline"):
        for path in run.rglob("*"):
            if path.is_file():
                objects["bucket", name + "/" + path.relative_to(run).as_posix()] = path.read_bytes()
    objects["bucket", "facts.json"] = json.dumps(answer_key(run)).encode()
    objects["bucket", "candidate/artifacts/evil.py"] = b"raise RuntimeError('never run this')"
    return objects


def prepare(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    s3 = S3(source_objects(run))
    args = SimpleNamespace(candidate_s3_uri="s3://bucket/candidate/", baseline_s3_uri="s3://bucket/baseline/",
                           facts_s3_uri="s3://bucket/facts.json", results_s3_uri="s3://bucket/results/",
                           execution_id="123-1", scenario="jungle_market_simple", manifest_out=tmp_path / "manifest.json")
    manifest = ci.prepare(args, s3)
    return run, s3, manifest


def test_snapshot_is_shared_checksum_verified_and_contains_no_executable_attachments(tmp_path):
    run, s3, manifest = prepare(tmp_path)
    dest = tmp_path / "download"
    ci.unpack_snapshot(s3, manifest, dest)
    assert ci.digest(dest / "candidate/artifacts/final_report_with_citations.docx") == ci.digest(run / "artifacts/final_report_with_citations.docx")
    assert not (dest / "candidate/artifacts/evil.py").exists()
    assert s3.get_calls[0]["IfMatch"] == manifest["snapshot_etag"]
    assert "facts" not in manifest and "report" not in manifest


def test_modified_snapshot_is_rejected(tmp_path):
    _, s3, manifest = prepare(tmp_path)
    bucket, key = ci.s3_location(manifest["snapshot_uri"])
    s3.objects[bucket, key] += b"changed"
    with pytest.raises(ValueError, match="checksum"):
        ci.unpack_snapshot(s3, manifest, tmp_path / "download")


@pytest.mark.parametrize("path", ["../outside", "/absolute", "a/../../outside", "a/./b", "a\\..\\b"])
def test_snapshot_paths_cannot_escape_or_alias_staging_directory(tmp_path, path):
    with pytest.raises(ValueError):
        ci.safe_path(tmp_path, path)


@pytest.mark.parametrize("uri", ["https://example.org/run", "s3://bucket/", "s3://bucket/../key", "s3://bucket/key?token=x"])
def test_s3_uris_require_explicit_safe_prefix(uri):
    with pytest.raises(ValueError):
        ci.s3_location(uri)


def test_snapshot_expansion_rejects_zip_slip(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("../escape", "bad")
    s3 = S3({("bucket", "inputs.zip"): data.getvalue()})
    manifest = {"version": 1, "snapshot_uri": "s3://bucket/inputs.zip", "snapshot_etag": '"x"',
                "snapshot_sha256": hashlib.sha256(data.getvalue()).hexdigest()}
    with pytest.raises(ValueError):
        ci.unpack_snapshot(s3, manifest, tmp_path / "download")
    assert not (tmp_path / "escape").exists()


def test_public_summary_does_not_leak_report_evidence_errors_or_metadata():
    result = {"evaluator": "rules", "passed": False, "status": "error", "scores": {
        "core_pass": False, "warning": "private report text", "agent_calls": {"sensitive": 1}, "checked": 2},
        "error": "private prompt", "findings": [{"quote": "private report text"}], "snapshot_uri": "s3://private/key"}
    public = ci.public_summary(result)
    assert public["scores"] == {"core_pass": False, "checked": 2}
    assert "private" not in json.dumps(public)


def test_missing_evaluator_cannot_make_overall_run_pass(tmp_path):
    ci.write_json(tmp_path / "rules/summary.json", {"evaluator": "rules", "status": "passed", "passed": True, "scores": {}})
    code = ci.summarize(tmp_path, tmp_path / "all.json", tmp_path / "summary.md")
    assert code == 1
    data = json.loads((tmp_path / "all.json").read_text())
    assert len(data["evaluators"]) == 4 and data["evaluators"][1]["status"] == "missing"


def test_all_four_evaluators_run_independently_in_parallel(tmp_path, monkeypatch):
    run = make_run.make_clean_run(tmp_path / "candidate")
    facts = tmp_path / "facts.json"
    ci.write_json(facts, answer_key(run))
    quote = ci.read_report(run).splitlines()[1]
    expected = answer_key(run)["facts"][0]["expected"]

    class Model:
        def __init__(self, *args):
            self.calls = []
        def assess(self, task, data):
            self.calls.append({"usage": {"inputTokens": 10}})
            if "facts" in data:
                return {"claims": [{"id": "sales", "status": "found", "value": expected, "quote": quote}]}
            if "report_A" in data:
                return {"winner": "tie", "reason": "Equal", "quote_a": quote, "quote_b": quote}
            return {"dimensions": [{"id": d["id"], "score": 4, "reason": "Supported", "quote": quote} for d in data["rubric"]]}

    monkeypatch.setattr(ci, "BedrockEvaluator", Model)
    def run_kind(kind):
        return ci.main(["evaluate", "--kind", kind, "--candidate-dir", str(run), "--baseline-dir", str(run),
                        "--facts", str(facts), "--scenario", "jungle_market_simple", "--out", str(tmp_path / kind / "detail.json"),
                        "--summary-out", str(tmp_path / kind / "summary.json")])
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(run_kind, ci.KINDS)) == [0, 0, 0, 0]
    assert ci.summarize(tmp_path, tmp_path / "all.json", tmp_path / "summary.md") == 0
    assert "model_calls" not in json.loads((tmp_path / "rules/detail.json").read_text())
    assert len(json.loads((tmp_path / "pairwise/detail.json").read_text())["model_calls"]) == 2


def test_model_failure_still_writes_failing_public_summary(tmp_path, monkeypatch):
    run = make_run.make_clean_run(tmp_path / "candidate")
    class Unavailable:
        def __init__(self, *args):
            self.calls = []
        def assess(self, *args):
            raise RuntimeError("private model error and report details")
    monkeypatch.setattr(ci, "BedrockEvaluator", Unavailable)
    code = ci.main(["evaluate", "--kind", "judge", "--candidate-dir", str(run), "--scenario", "jungle_market_simple",
                    "--out", str(tmp_path / "detail.json"), "--summary-out", str(tmp_path / "summary.json")])
    assert code == 2
    assert json.loads((tmp_path / "summary.json").read_text())["status"] == "error"
    assert "private" not in (tmp_path / "summary.json").read_text()


def test_workflow_runs_four_evaluators_without_invoking_runtime():
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/eval-harness.yml"
    doc = yaml.safe_load(workflow.read_text())
    matrix = doc["jobs"]["evaluate"]
    assert matrix["needs"] == "prepare"
    assert matrix["strategy"]["matrix"]["evaluator"] == list(ci.KINDS)
    assert matrix["strategy"]["fail-fast"] is False
    assert matrix["strategy"]["max-parallel"] == 4
    assert doc["jobs"]["summary"]["if"] == "always()"
    assert all("run_eval.py" not in step.get("run", "") for job in doc["jobs"].values() for step in job["steps"])
    artifact_steps = [s for s in matrix["steps"] if "actions/upload-artifact" in s.get("uses", "")]
    assert artifact_steps[0]["with"]["path"] == "public-results/summary.json"

