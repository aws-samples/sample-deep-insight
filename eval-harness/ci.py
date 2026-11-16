"""Evaluate existing S3/local results. Never invoke or deploy an analysis runtime.

prepare: snapshot S3 inputs privately; publish only a checksum/URI manifest.
evaluate: one independent evaluator, with detailed results kept in S3.
summarize: combine only public scores, even when an evaluator failed or is missing.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from grade import grade_run, load_scenario
from graders import factcheck, judge
from graders.llm import BedrockEvaluator, finite_number, read_report
import pairwise

KINDS = ("rules", "factcheck", "judge", "pairwise")
MAX_BYTES = 200 * 1024 * 1024
MAX_FILES = 2000
HERE = Path(__file__).resolve().parent


def s3_location(uri):
    u = urlsplit(uri)
    if u.scheme != "s3" or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", u.netloc) or u.query or u.fragment:
        raise ValueError("Use an s3://bucket/key URI without query parameters")
    key = u.path.lstrip("/")
    if not key or any(p in ("", ".", "..") for p in key.rstrip("/").split("/")):
        raise ValueError("S3 inputs and outputs must specify a non-root key/prefix")
    return u.netloc, key


def safe_path(root, name):
    parts = PurePosixPath(name).parts
    if not parts or name.startswith("/") or "\\" in name or any(p in ("", ".", "..") for p in name.split("/")):
        raise ValueError("Unsafe path in evaluation input")
    target = Path(root).joinpath(*parts)
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Evaluation input escapes the staging directory")
    return target


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def download_prefix(s3, uri, dest):
    bucket, prefix = s3_location(uri)
    prefix = prefix.rstrip("/") + "/"
    files, total = 0, 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.startswith(prefix):
                raise ValueError("S3 returned an object outside the requested prefix")
            rel = key[len(prefix):]
            # Rules read execution JSON, citations and validation text; LLMs read only DOCX.
            # Generated Python/shell files are neither downloaded nor executed.
            if not rel or Path(rel).suffix.lower() not in (".json", ".txt", ".docx"):
                continue
            files += 1
            total += obj["Size"]
            if files > MAX_FILES or total > MAX_BYTES:
                raise ValueError("Input exceeds the evaluation download limit")
            target = safe_path(dest, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(target))
            if target.stat().st_size > obj["Size"]:
                raise ValueError("S3 input changed during download")
    if not files:
        raise ValueError("No evaluation files found under the supplied S3 prefix")


def prepare(args, s3):
    load_scenario(args.scenario)  # reject typos before transferring files
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.execution_id):
        raise ValueError("Invalid execution ID")
    out_bucket, out_prefix = s3_location(args.results_s3_uri)
    result_prefix = out_prefix.rstrip("/") + "/actions/" + args.execution_id + "/"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        download_prefix(s3, args.candidate_s3_uri, root / "candidate")
        download_prefix(s3, args.baseline_s3_uri, root / "baseline")
        fb, fk = s3_location(args.facts_s3_uri)
        if s3.head_object(Bucket=fb, Key=fk)["ContentLength"] > 1024 * 1024:
            raise ValueError("Answer key exceeds 1 MB")
        s3.download_file(fb, fk, str(root / "facts.json"))
        bundle = root / "inputs.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(root.rglob("*")):
                if path.is_file() and path != bundle:
                    z.write(path, path.relative_to(root).as_posix())
        if bundle.stat().st_size > MAX_BYTES:
            raise ValueError("Input bundle exceeds the size limit")
        key = result_prefix + "inputs.zip"
        s3.upload_file(str(bundle), out_bucket, key)
        head = s3.head_object(Bucket=out_bucket, Key=key)
        manifest = {"version": 1, "scenario": args.scenario, "snapshot_uri": f"s3://{out_bucket}/{key}",
                    "snapshot_sha256": digest(bundle), "snapshot_etag": head["ETag"],
                    "snapshot_version_id": head.get("VersionId"),
                    "results_s3_uri": f"s3://{out_bucket}/{result_prefix}results/"}
        write_json(args.manifest_out, manifest)
    return manifest


def unpack_snapshot(s3, manifest, dest):
    if manifest.get("version") != 1:
        raise ValueError("Unsupported input manifest version")
    bucket, key = s3_location(manifest["snapshot_uri"])
    params = {"Bucket": bucket, "Key": key}
    if manifest.get("snapshot_version_id"):
        params["VersionId"] = manifest["snapshot_version_id"]
    else:
        params["IfMatch"] = manifest["snapshot_etag"]
    response = s3.get_object(**params)
    bundle = Path(dest) / "inputs.zip"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    body = response["Body"]
    size = 0
    try:
        with bundle.open("wb") as out:
            for block in body.iter_chunks(chunk_size=1024 * 1024):
                size += len(block)
                if size > MAX_BYTES:
                    raise ValueError("Snapshot exceeds download limit")
                out.write(block)
    finally:
        body.close()
    if digest(bundle) != manifest["snapshot_sha256"]:
        raise ValueError("Input snapshot checksum mismatch")
    with zipfile.ZipFile(bundle) as z:
        entries = z.infolist()
        if len(entries) > MAX_FILES * 2 + 1 or sum(i.file_size for i in entries) > MAX_BYTES * 2 + 1024 * 1024:
            raise ValueError("Expanded snapshot exceeds size limit")
        seen = set()
        for item in entries:
            target = safe_path(dest, item.filename)
            if item.filename in seen or stat.S_ISLNK(item.external_attr >> 16) or item.is_dir():
                raise ValueError("Snapshot contains duplicate, symlink or unexpected directory entries")
            seen.add(item.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as source, target.open("wb") as out:
                while block := source.read(1024 * 1024):
                    out.write(block)


def check_scenario(run_dir, scenario):
    # The caller explicitly chooses a scenario for legacy S3 sessions without metadata.
    # When metadata exists, do not silently compare a different request/dataset.
    for name in ("run.json", "config.json"):
        path = Path(run_dir) / name
        if path.is_file():
            meta = json.loads(path.read_text(encoding="utf-8"))
            if meta.get("scenario") and meta["scenario"] != scenario:
                raise ValueError("Run metadata does not match the selected scenario")


def evaluate(kind, candidate, baseline, facts_path, scenario_name, evaluator=None, rubric_path=None):
    scenario = load_scenario(scenario_name)
    check_scenario(candidate, scenario_name)
    if kind == "rules":
        result = grade_run(candidate, scenario["csv"], scenario)
        return {"passed": result["scores"]["core_pass"], **result}
    report = read_report(candidate)
    if kind == "factcheck":
        answer_key = json.loads(Path(facts_path).read_text(encoding="utf-8"))
        return factcheck.grade(report, answer_key, scenario_name, evaluator)
    rubric = json.loads(Path(rubric_path or HERE / "config/judge_rubric.json").read_text(encoding="utf-8"))
    if kind == "judge":
        return judge.grade(report, scenario["query"], rubric, evaluator)
    if kind == "pairwise":
        check_scenario(baseline, scenario_name)
        return pairwise.grade(report, read_report(baseline), scenario["query"], rubric, evaluator)
    raise ValueError("Unknown evaluator")


def public_summary(result):
    # No report excerpts, facts, prompts, input manifests, resource IDs or exception messages.
    summary = {k: result[k] for k in ("evaluator", "scenario", "status", "passed") if k in result}
    scores = result.get("scores", {})
    summary["scores"] = {k: v for k, v in scores.items() if type(v) is bool or finite_number(v)
                         or (k == "pairwise_winner" and v in ("candidate", "baseline", "tie", "inconclusive"))
                         or (k == "audit_verdict" and v in ("pass", "retry", "needs_review"))}
    return summary


def evaluate_command(args):
    s3 = None
    manifest = None
    evaluator = None
    result = {"version": 1, "evaluator": args.kind, "scenario": args.scenario,
              "status": "error", "passed": False, "scores": {},
              "code_revision": os.environ.get("GITHUB_SHA"),
              "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
    try:
        if args.manifest:
            import boto3
            s3 = boto3.client("s3", region_name=args.region)
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            if args.scenario and args.scenario != manifest["scenario"]:
                raise ValueError("CLI scenario differs from the input manifest")
            args.scenario = manifest["scenario"]
            unpack_snapshot(s3, manifest, args.work_dir)
            args.candidate_dir = str(Path(args.work_dir) / "candidate")
            args.baseline_dir = str(Path(args.work_dir) / "baseline")
            args.facts = str(Path(args.work_dir) / "facts.json")
            result["snapshot_sha256"] = manifest["snapshot_sha256"]
        if not args.candidate_dir or not args.scenario:
            raise ValueError("Specify an input manifest, or a candidate directory and scenario")
        result["scenario"] = args.scenario
        if args.kind != "rules":
            evaluator = BedrockEvaluator(args.model_id, args.region)
        result.update(evaluate(args.kind, args.candidate_dir, args.baseline_dir, args.facts,
                               args.scenario, evaluator, args.rubric))
        result["status"] = "passed" if result["passed"] else "failed"
    except Exception as error:
        result.update(status="error", passed=False, error={"type": type(error).__name__, "message": str(error)})
    if evaluator is not None:
        result["model_calls"] = evaluator.calls
    write_json(args.out, result)
    if manifest is not None:
        try:
            bucket, prefix = s3_location(manifest["results_s3_uri"])
            s3.upload_file(args.out, bucket, prefix.rstrip("/") + "/" + args.kind + ".json")
        except Exception as error:
            result.update(status="error", passed=False, result_upload_error=type(error).__name__)
            write_json(args.out, result)
    write_json(args.summary_out, public_summary(result))
    print(f"{args.kind}: {result['status']}")
    return 0 if result["passed"] else (2 if result["status"] == "error" else 1)


def summarize(results_dir, out, markdown):
    by_kind = {}
    for path in sorted(Path(results_dir).rglob("summary.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        kind = value.get("evaluator")
        if kind in KINDS:
            if kind in by_kind:
                raise ValueError("Duplicate evaluator summaries")
            by_kind[kind] = public_summary(value)
    results = [by_kind.get(k, {"evaluator": k, "status": "missing", "passed": False, "scores": {}}) for k in KINDS]
    passed = all(r.get("passed") is True and r.get("status") == "passed" for r in results)
    write_json(out, {"passed": passed, "evaluators": results})
    headlines = {"rules": "core_pass", "factcheck": "fact_coverage", "judge": "judge_score", "pairwise": "pairwise_winner"}
    lines = ["## Eval harness", "", "| Evaluator | Status | Result |", "|---|---|---|"]
    lines += [f"| {r['evaluator']} | {r['status']} | {r['scores'].get(headlines[r['evaluator']], '—')} |" for r in results]
    lines += ["", "Detailed evidence stays in the configured private S3 results prefix.", ""]
    Path(markdown).write_text("\n".join(lines), encoding="utf-8")
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    for name in ("candidate-s3-uri", "baseline-s3-uri", "facts-s3-uri", "results-s3-uri", "execution-id", "scenario", "manifest-out"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    e = sub.add_parser("evaluate")
    e.add_argument("--kind", required=True, choices=KINDS)
    for name in ("manifest", "candidate-dir", "baseline-dir", "facts", "scenario", "rubric"):
        e.add_argument("--" + name)
    e.add_argument("--work-dir", default=".eval-inputs")
    e.add_argument("--out", required=True)
    e.add_argument("--summary-out", required=True)
    e.add_argument("--model-id", default=os.environ.get("EVAL_JUDGE_MODEL_ID", "global.anthropic.claude-sonnet-5"))
    e.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    s = sub.add_parser("summarize")
    s.add_argument("--results-dir", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--markdown", required=True)
    args = parser.parse_args(argv)
    if args.command == "evaluate":
        return evaluate_command(args)
    if args.command == "summarize":
        return summarize(args.results_dir, args.out, args.markdown)
    import boto3
    prepare(args, boto3.client("s3", region_name=args.region))
    print("Private input snapshot prepared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
