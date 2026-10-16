"""Measure one agent on its own: a saved run's artifacts as the fixed input, errors planted as the known answer.

A full run grades only the final report, so it can't say which agent a worse
score came from, and each agent's input differs from run to run. Here the
agent runs alone (nothing before it is re-run) on an input whose right answer
is known, so two versions of it are compared on the same input.

    python component_eval.py validator --from eval_results/baseline/<run> [--from ...] \\
        --plant 6 --repeat 2 --tag comp-validator
    python component_eval.py reporter --from eval_results/baseline/<run> --plant 4 --tag comp-reporter

For each source run and repeat: the component module (components/<name>.py)
plants its case and stages the artifacts as they were when the agent started;
this file uploads them with the scenario's data, invokes the eval runtime with
`component: <name>` (managed-agentcore/src/graph/component.py), downloads the
session and has the module score it. What is planted and how it is scored is
described in each module.

    eval_results/<tag>/component/<component>/<scenario>-<time>-<n>/
      planted.json   what was changed
      events.jsonl, run.json, s3/, artifacts/   as run_eval.py writes them
      result.json    the module's counts, and the run's cost

Needs the eval runtime with EVAL_COMPONENT_MODE=1 (eval_runtime.py
enable-components) and an image that has component runs. Paid: one agent run
per repeat.
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from components import COMPONENTS  # noqa: E402
from components.common import NothingToPlant  # noqa: E402
from grade import artifacts_dir, load_scenario  # noqa: E402


def plans_from_events(run_dir):
    """Every plan the Planner wrote in a run, in order (more than one after a revision); the Validator works from the last."""
    path = Path(run_dir) / "events.jsonl"
    plans, current = [], ""
    if not path.is_file():
        return plans
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("agent_name") != "planner":
                continue
            if ev.get("type") == "agent_text_stream":
                current += ev.get("data", "")
            elif ev.get("type") == "agent_usage_stream" and current:
                plans.append(current)
                current = ""
    if current:
        plans.append(current)
    return plans


def upload(s3, bucket, prefix, files_or_dir):
    """Upload a list of files, or a directory tree, under prefix; returns the s3:// URL."""
    if isinstance(files_or_dir, Path) and files_or_dir.is_dir():
        for p in sorted(files_or_dir.rglob("*")):
            if p.is_file():
                s3.upload_file(str(p), bucket, prefix + str(p.relative_to(files_or_dir)))
    else:
        for f in files_or_dir:
            path = (HERE / f).resolve()
            s3.upload_file(str(path), bucket, prefix + path.name)
    return f"s3://{bucket}/{prefix}"


def invoke(args, payload, run_dir, clients):
    """Stream one component run into run_dir, like run_eval.run_once without plan reviews."""
    from run_eval import download_session, parse_sse
    agentcore, s3 = clients
    meta = {"status": "incomplete", "component": payload["component"]}
    start = time.monotonic()
    meta["started_at"] = datetime.now(timezone.utc).isoformat()
    usage = {}
    try:
        resp = agentcore.invoke_agent_runtime(agentRuntimeArn=args.runtime_arn, qualifier="DEFAULT", payload=json.dumps(payload))
        with open(run_dir / "events.jsonl", "w", encoding="utf-8") as events:
            for line in resp["response"].iter_lines(chunk_size=1):
                ev = parse_sse(line)
                if ev is None:
                    continue
                events.write(json.dumps({"client_ts": round(time.monotonic() - start, 3), **ev}, ensure_ascii=False) + "\n")
                if ev.get("event_type") == "usage_metadata" and ev.get("agent_name"):
                    u = usage.setdefault(ev["agent_name"], {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "model_id": None})
                    u["input"] += ev.get("input_tokens", 0) or 0
                    u["output"] += ev.get("output_tokens", 0) or 0
                    u["cache_read"] += ev.get("cache_read_input_tokens", 0) or 0
                    u["cache_write"] += ev.get("cache_write_input_tokens", 0) or 0
                    u["model_id"] = ev.get("model_id") or u["model_id"]
                if (ev.get("type") or ev.get("event_type")) == "workflow_complete":
                    meta["status"], meta["session_id"] = "completed", ev.get("session_id") or None
                    break
    except Exception as e:
        meta["status"], meta["error"] = "error", f"{type(e).__name__}: {e}"
    meta["duration_s"] = round(time.monotonic() - start, 1)
    if meta.get("session_id"):
        meta["artifact_files"] = download_session(s3, args.bucket, meta["session_id"], run_dir)
    (run_dir / "usage.json").write_text(json.dumps({"by_agent": usage}, indent=2), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta, usage


def main():
    import boto3
    from botocore.config import Config
    from dotenv import dotenv_values
    from graders import cost
    from run_eval import _runtime_bucket
    env = {**dotenv_values(HERE.parent / "managed-agentcore" / ".env"), **dotenv_values(HERE / "config" / "eval.env"), **os.environ}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("component", choices=list(COMPONENTS))
    ap.add_argument("--from", dest="sources", action="append", required=True, help="saved run folder (repeatable)")
    ap.add_argument("--plant", type=int, default=6, help="errors to plant (validator) or citations to mark needs_review (reporter) per run")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--allow-test", action="store_true", help="allow source runs of test-split scenarios")
    ap.add_argument("--runtime-arn", default=env.get("EVAL_RUNTIME_ARN"))
    ap.add_argument("--region", default=env.get("EVAL_REGION") or env.get("AWS_REGION") or "us-west-2")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()
    if not args.runtime_arn:
        ap.error("--runtime-arn is required (or EVAL_RUNTIME_ARN from eval_runtime.py create)")
    if args.runtime_arn == env.get("RUNTIME_ARN"):
        ap.error("that is the users' runtime; component runs exist on the eval runtime only")
    args.bucket = args.bucket or _runtime_bucket(args.region, args.runtime_arn)
    agentcore = boto3.client("bedrock-agentcore", region_name=args.region,
                             config=Config(connect_timeout=60, read_timeout=args.timeout, retries={"max_attempts": 0}))
    s3 = boto3.client("s3", region_name=args.region)
    rng = random.Random(args.seed)
    results, failures = [], 0
    mod = COMPONENTS[args.component]
    for src in map(Path, args.sources):
        name = json.loads((src / "run.json").read_text(encoding="utf-8"))["scenario"]
        sc = load_scenario(name)
        if sc["split"] == "test" and not args.allow_test:
            ap.error(f"{src.name} is a run of test scenario {name}; pass --allow-test")
        adir = artifacts_dir(src)
        ctx = mod.prepare(adir, sc)
        plans = plans_from_events(src)
        if not plans:
            ap.error(f"{src}: no plan in events.jsonl")
        for i in range(1, args.repeat + 1):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_dir = HERE / "eval_results" / args.tag / "component" / args.component / f"{name}-{stamp}-{i}"
            run_dir.mkdir(parents=True)
            staged = run_dir / "staged_artifacts"
            try:
                record, state, summary = mod.plant(ctx, adir, staged, args.plant, rng)
            except NothingToPlant as e:
                ap.error(f"{src}: {e}")
            (run_dir / "planted.json").write_text(json.dumps({"source_run": str(src), **record}, indent=2, ensure_ascii=False),
                                                  encoding="utf-8")
            prefix = f"uploads/eval-component-{args.component}-{name.replace('_', '-')}-{stamp}-{i}/"
            payload = {"prompt": sc["query"].strip(), "component": args.component, "full_plan": plans[-1],
                       "data_directory": upload(s3, args.bucket, prefix + "data/", sc["upload"]),
                       "artifacts_directory": upload(s3, args.bucket, prefix + "artifacts/", staged)}
            print(f"{name} ← {src.name} run {i}: {summary} → {run_dir.relative_to(HERE)}", flush=True)
            meta, usage = invoke(args, payload, run_dir, (agentcore, s3))
            if meta["status"] != "completed":
                failures += 1
                print(f"  {meta['status']} {meta.get('error', '')}", flush=True)
                continue
            r = mod.evaluate(artifacts_dir(run_dir), ctx, state)
            c = cost.compute({"by_agent": usage})
            r["cost_usd"] = c["cost_usd"] if c["cost_complete"] else None
            (run_dir / "result.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append((f"{src.name} #{i}", r))
            print(f"  {mod.summary(r)} · {meta['duration_s']:.0f}s" + (f" · ${r['cost_usd']:.2f}" if r.get("cost_usd") is not None else ""),
                  flush=True)
    if results:
        print(mod.table(results))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
