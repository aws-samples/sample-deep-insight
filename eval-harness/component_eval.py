"""Measure one agent on its own: a saved run's artifacts as the fixed input, errors planted as the known answer.

A full run grades only the final report, so it can't say which agent a worse
score came from, and each agent's input differs from run to run. Here the
agent runs alone (nothing before it is re-run) on an input whose right answer
is known, so two versions of it are compared on the same input. The counts
are for that A/B: the agent gets the saved artifacts but not what earlier
agents said in a full run (see managed-agentcore/src/graph/component.py), so
they aren't the numbers a full run would give.

    python component_eval.py validator --scenario jungle_market [--repeat 2] --tag comp-validator
    python component_eval.py reporter --from eval_results/baseline/<run> [--from ...] --plant 4 --tag comp-reporter
    python component_eval.py pin --from eval_results/baseline/<run>     # make it the scenario's fixed input

`--scenario` takes the scenario's pinned input (component_inputs/<scenario>/,
in git) and its `components:` settings in scenarios.yaml (plant, seed), so
every version is measured on the same artifacts with the same planted errors.
`pin` copies a saved run there: its artifacts up to the Reporter (without
cached DataFrames no calculation reads) and its report (the Reporter
component picks values it cited), the plan and where it came from.
Re-pin when the artifact format changes.

For each source and repeat: the component module (components/<name>.py)
plants its case and stages the artifacts as they were when the agent started;
this file uploads them with the scenario's data, invokes the eval runtime with
`component: <name>`, downloads the session and has the module score it. What
is planted and how it is scored is described in each module. Repeat i plants
from seed "<seed>:i", so repeat i of two versions gets the same errors.

    eval_results/<tag>/component/<component>/<scenario>-<time>-<n>/
      planted.json   what was changed, and the source
      events.jsonl, run.json, s3/, artifacts/   as run_eval.py writes them
      result.json    the module's counts, and the run's cost

run_eval.py --components runs these next to the full runs. Needs the eval
runtime with EVAL_COMPONENT_MODE=1 (eval_runtime.py enable-components) and an
image that has component runs. Paid: one agent run per repeat.
"""
import argparse
import json
import os
import random
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from components import COMPONENTS  # noqa: E402
from components.common import REPORTER_AND_AUDITOR, NothingToPlant, copy_before  # noqa: E402
from grade import artifacts_dir, load_scenario  # noqa: E402

INPUTS = HERE / "component_inputs"
DEFAULT_PLANT = 6
# Kept in a pinned input though the Reporter writes it: the Reporter component picks the values it cited
# (staging removes it again, so no agent sees it).
PINNED_REPORT = "final_report_with_citations.docx"


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


def source_plan(src):
    """The plan a source's agent works from: plan.md in a pinned input, else the last one in events.jsonl."""
    if (Path(src) / "plan.md").is_file():
        return (Path(src) / "plan.md").read_text(encoding="utf-8")
    plans = plans_from_events(src)
    return plans[-1] if plans else None


def pinned_input(scenario_name):
    """component_inputs/<scenario>/ if a run was pinned for it, else None."""
    d = INPUTS / scenario_name
    return d if (d / "run.json").is_file() else None


def pin(src, force=False):
    """Copy a saved run to component_inputs/<scenario>/: artifacts up to the Reporter, plan.md, run.json."""
    src = Path(src)
    meta = json.loads((src / "run.json").read_text(encoding="utf-8"))
    plan = source_plan(src)
    if not plan:
        raise ValueError(f"{src}: no plan in events.jsonl")
    for f in ("citations.json", PINNED_REPORT):
        if not (artifacts_dir(src) / f).is_file():
            raise ValueError(f"{src}: no {f}; pin a run that got past the Reporter")
    dest = INPUTS / meta["scenario"]
    if dest.exists():
        if not force:
            raise ValueError(f"{dest.relative_to(HERE)} exists; pass --force to replace it")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copy_before(artifacts_dir(src), dest / "artifacts", REPORTER_AND_AUDITOR)
    shutil.copy2(artifacts_dir(src) / PINNED_REPORT, dest / "artifacts" / PINNED_REPORT)
    drop_unread_pickles(dest / "artifacts")
    (dest / "plan.md").write_text(plan, encoding="utf-8")
    cfg_path = src / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    record = {"scenario": meta["scenario"], "pinned_from": src.name, "pinned_at": datetime.now(timezone.utc).date().isoformat(),
              **{k: cfg[k] for k in ("git_sha", "runtime_version", "image", "models") if k in cfg}}
    (dest / "run.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def drop_unread_pickles(adir):
    """Remove cached DataFrames no calculation names as its source_file (the Validator loads a calculation's
    source_file, the Reporter no pickle, so they only add megabytes to git), and __pycache__."""
    meta = json.loads((adir / "calculation_metadata.json").read_text(encoding="utf-8"))
    rows = meta["calculations"] if isinstance(meta, dict) else meta
    read = {Path(str(r.get("source_file", ""))).name for r in rows}
    for p in adir.rglob("*.pkl"):
        if p.name not in read:
            p.unlink()
    for d in list(adir.rglob("__pycache__")):   # git-ignored: a clone wouldn't have them
        shutil.rmtree(d)


def scenario_settings(scenario, component):
    """(plant, seed) from the scenario's `components:` block; None when the scenario doesn't list the component."""
    c = (scenario.get("components") or {}).get(component)
    if c is None:
        return None
    return c.get("plant", DEFAULT_PLANT), c.get("seed", 0)


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


def invoke(runtime_arn, bucket, payload, run_dir, clients):
    """Stream one component run into run_dir, like run_eval.run_once without plan reviews."""
    from run_eval import download_session, parse_sse
    agentcore, s3 = clients
    meta = {"status": "incomplete", "component": payload["component"]}
    start = time.monotonic()
    meta["started_at"] = datetime.now(timezone.utc).isoformat()
    usage = {}
    try:
        resp = agentcore.invoke_agent_runtime(agentRuntimeArn=runtime_arn, qualifier="DEFAULT", payload=json.dumps(payload))
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
        meta["artifact_files"] = download_session(s3, bucket, meta["session_id"], run_dir)
    (run_dir / "usage.json").write_text(json.dumps({"by_agent": usage}, indent=2), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta, usage


def run_components(component, sources, *, plant, seed, repeats, tag, runtime_arn, bucket, clients,
                   allow_test=False, config=None, log=print):
    """Plant, stage, invoke and score `component` on each source for each repeat number; (results, failures).

    config (git SHA, runtime version, models; run_eval.py's snapshot) goes in each run's config.json."""
    from graders import cost
    agentcore, s3 = clients
    results, failures = [], 0
    mod = COMPONENTS[component]
    for src in map(Path, sources):
        name = json.loads((src / "run.json").read_text(encoding="utf-8"))["scenario"]
        sc = load_scenario(name)
        if sc["split"] == "test" and not allow_test:
            raise ValueError(f"{src.name} is a run of test scenario {name}; pass --allow-test")
        adir = artifacts_dir(src)
        ctx = mod.prepare(adir, sc)
        plan = source_plan(src)
        if not plan:
            raise ValueError(f"{src}: no plan in events.jsonl")
        for i in repeats:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_dir = HERE / "eval_results" / tag / "component" / component / f"{name}-{stamp}-{i}"
            run_dir.mkdir(parents=True)
            staged = run_dir / "staged_artifacts"
            try:
                record, state, summary = mod.plant(ctx, adir, staged, plant, random.Random(f"{seed}:{i}"))
            except NothingToPlant as e:
                raise ValueError(f"{src}: {e}") from e
            (run_dir / "planted.json").write_text(json.dumps({"scenario": name, "source_run": src.name, "plant": plant, "seed": seed, "repeat": i, **record},
                                                             indent=2, ensure_ascii=False), encoding="utf-8")
            prefix = f"uploads/eval-component-{component}-{name.replace('_', '-')}-{stamp}-{i}/"
            payload = {"prompt": sc["query"].strip(), "component": component, "full_plan": plan,
                       "data_directory": upload(s3, bucket, prefix + "data/", sc["upload"]),
                       "artifacts_directory": upload(s3, bucket, prefix + "artifacts/", staged)}
            log(f"{component} · {name} ← {src.name} run {i}: {summary} → {run_dir.relative_to(HERE)}")
            meta, usage = invoke(runtime_arn, bucket, payload, run_dir, clients)
            if config is not None:
                (run_dir / "config.json").write_text(json.dumps({**config, "bucket": bucket, "scenario": name}, indent=2,
                                                                ensure_ascii=False), encoding="utf-8")
            if meta["status"] != "completed":
                failures += 1
                log(f"  {component} · {name} run {i}: {meta['status']} {meta.get('error', '')}")
                continue
            r = mod.evaluate(artifacts_dir(run_dir), ctx, state)
            c = cost.compute({"by_agent": usage})
            r["cost_usd"] = c["cost_usd"] if c["cost_complete"] else None
            r["model_id"] = (usage.get(component) or {}).get("model_id")
            (run_dir / "result.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append((f"{name} ← {src.name} #{i}", r))
            log(f"  {component} · {name} run {i}: {mod.summary(r)} · {meta['duration_s']:.0f}s"
                + (f" · ${r['cost_usd']:.2f}" if r.get("cost_usd") is not None else ""))
    return results, failures


def make_clients(region, timeout):
    import boto3
    from botocore.config import Config
    return (boto3.client("bedrock-agentcore", region_name=region,
                         config=Config(connect_timeout=60, read_timeout=timeout, retries={"max_attempts": 0})),
            boto3.client("s3", region_name=region))


def main():
    from dotenv import dotenv_values
    from run_eval import _runtime_bucket, git_info, runtime_config
    env = {**dotenv_values(HERE.parent / "managed-agentcore" / ".env"), **dotenv_values(HERE / "config" / "eval.env"), **os.environ}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("component", choices=list(COMPONENTS) + ["pin"])
    ap.add_argument("--from", dest="sources", action="append", default=[], help="saved run folder (repeatable)")
    ap.add_argument("--scenario", dest="scenarios", action="append", default=[],
                    help="the scenario's pinned input and scenarios.yaml settings (repeatable)")
    ap.add_argument("--plant", type=int, default=None,
                    help=f"errors to plant (validator) or citations to mark needs_review (reporter) per run; "
                         f"default: the scenario's setting with --scenario, else {DEFAULT_PLANT}")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--first-repeat", type=int, default=1, help="number of the first repeat (and of its seed)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--tag")
    ap.add_argument("--force", action="store_true", help="pin: replace the scenario's pinned input")
    ap.add_argument("--allow-test", action="store_true", help="allow source runs of test-split scenarios")
    ap.add_argument("--runtime-arn", default=env.get("EVAL_RUNTIME_ARN"))
    ap.add_argument("--region", default=env.get("EVAL_REGION") or env.get("AWS_REGION") or "us-west-2")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    if args.component == "pin":
        if len(args.sources) != 1 or args.scenarios:
            ap.error("pin takes exactly one --from")
        try:
            dest = pin(args.sources[0], args.force)
        except ValueError as e:
            ap.error(str(e))
        files = sum(1 for p in dest.rglob("*") if p.is_file())
        print(f"pinned {args.sources[0]} → {dest.relative_to(HERE)} ({files} files)")
        return 0

    if not args.tag:
        ap.error("--tag is required")
    if bool(args.sources) == bool(args.scenarios):
        ap.error("give --from or --scenario")
    jobs = [(args.sources, args.plant or DEFAULT_PLANT, args.seed or 0)] if args.sources else []
    for name in args.scenarios:
        src = pinned_input(name)
        settings = scenario_settings(load_scenario(name), args.component)
        if src is None or settings is None:
            ap.error(f"{name}: no pinned input (component_eval.py pin) or no `components: {args.component}` in scenarios.yaml")
        jobs.append(([src], args.plant or settings[0], settings[1] if args.seed is None else args.seed))
    if not args.runtime_arn:
        ap.error("--runtime-arn is required (or EVAL_RUNTIME_ARN from eval_runtime.py create)")
    if args.runtime_arn == env.get("RUNTIME_ARN"):
        ap.error("that is the users' runtime; component runs exist on the eval runtime only")
    args.bucket = args.bucket or _runtime_bucket(args.region, args.runtime_arn)
    clients = make_clients(args.region, args.timeout)
    config = {**git_info(), "runtime_arn": args.runtime_arn, "region": args.region, **runtime_config(args.region, args.runtime_arn)}
    repeats = range(args.first_repeat, args.first_repeat + args.repeat)
    results, failures = [], 0
    for sources, plant, seed in jobs:
        try:
            r, f = run_components(args.component, sources, plant=plant, seed=seed, repeats=repeats, tag=args.tag,
                                  runtime_arn=args.runtime_arn, bucket=args.bucket, clients=clients, allow_test=args.allow_test,
                                  config=config, log=lambda m: print(m, flush=True))
        except ValueError as e:
            ap.error(str(e))
        results += r
        failures += f
    if results:
        print(COMPONENTS[args.component].table(results))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
