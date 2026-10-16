"""Run one agent on a saved run's artifacts, with errors planted, and see if it catches them.

    python component_eval.py validator --from eval_results/baseline/<run> [--from ...] \\
        --plant 6 --repeat 2 --tag comp-validator

For each source run: pick calculations the recomputation (graders/recompute.py)
confirms are right, change their value in calculation_metadata.json by 10%,
stage the artifacts as they were when the Validator started (the files the
Validator and later agents wrote removed), and invoke the eval runtime with
`component: validator` (managed-agentcore/src/graph/component.py). The
Validator's citations.json then says, for each planted error:

  caught       needs_review
  missed       verified
  not checked  not in citations.json (the Validator only checks what it selects)

Planted errors are split between calculations on the raw CSV and on files the
Coder derived (media_agg.csv, ...), since the Validator is told to verify a
derived calculation against that same file: an error the Coder made while
building the file can't be caught that way, but a metadata value that differs
from the file can. Also reported: false alarms (right values marked
needs_review; the Reporter leaves those out) and whether the planted values
were kept as they are (the Validator must not correct them).

    eval_results/<tag>/component/validator/<scenario>-<time>-<n>/
      planted.json   which calculations were changed, from what to what
      events.jsonl, run.json, s3/, artifacts/   as run_eval.py writes them
      result.json    the counts above

Needs the eval runtime with EVAL_COMPONENT_MODE=1 (eval_runtime.py
enable-components) and an image that has component runs. Paid: one Validator
run per repeat.
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

from grade import artifacts_dir, load_scenario  # noqa: E402
from graders import recompute  # noqa: E402
from graders.citations import load_citations  # noqa: E402

# What the Validator and every agent after it write: removed before staging, so
# the Validator starts where it would in a full run.
LATER_OUTPUTS = ["citations.json", "validation_report.txt", "final_report*", "audit_*", "report*.docx",
                 "code/validator_*", "code/reporter_*", "code/audit_*", "cache/priority_calcs.pkl", "cache/verified.pkl"]


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


def pick_plants(calcs, strict, csv_name, k, rng):
    """Up to k high-importance calculations, half on the raw CSV (recomputation-confirmed) and half on derived files."""
    high = {c for c, x in calcs.items() if str(x.get("importance", "high")).lower() == "high" and _number(x.get("value")) is not None}
    raw = sorted(c for c in high if strict.get(c))   # strict only holds checks on the raw file
    derived = sorted(c for c in high if Path(str(calcs[c].get("source_file", ""))).name not in ("", csv_name))
    rng.shuffle(raw)
    rng.shuffle(derived)
    n_raw = min(len(raw), max(k // 2, k - len(derived)))
    take = raw[:n_raw] + derived[:k - n_raw]
    return take, {c: ("raw" if c in raw else "derived") for c in take}


def _number(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def planted_value(v):
    """10% off, same type: an integer stays an integer, a decimal keeps 4 places."""
    x = _number(v)
    if x == 0:
        return 1
    if float(x).is_integer() and not isinstance(v, float):
        return int(round(x * 1.1)) if round(x * 1.1) != x else int(x) + 1
    return round(x * 1.1, 4)


def stage(src, dest, plants):
    """Copy the saved artifacts as they were before the Validator, with the planted values."""
    shutil.copytree(src, dest, symlinks=False)
    for pattern in LATER_OUTPUTS:
        for p in dest.glob(pattern):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    meta_path = dest / "calculation_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    rows = meta["calculations"] if isinstance(meta, dict) else meta
    for row in rows:
        if row.get("id") in plants:
            row["value"] = plants[row["id"]]["planted"]
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


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


def score(adir, plants, kinds, strict_ok):
    """Counts from the Validator's citations.json; strict_ok: calculations known right before planting."""
    cites = load_citations(adir) or {}
    by_calc = {c.get("calculation_id"): c for c in cites.values()}
    out = {"planted": len(plants), "caught": 0, "missed": 0, "not_checked": 0, "value_changed": 0,
           "by_kind": {k: {"caught": 0, "missed": 0, "not_checked": 0} for k in ("raw", "derived")}, "per_calc": {}}
    for cid, p in plants.items():
        c = by_calc.get(cid)
        status = str((c or {}).get("verification_status", "")).lower()
        outcome = "not_checked" if c is None else "caught" if status == "needs_review" else "missed"
        out[outcome] += 1
        out["by_kind"][kinds[cid]][outcome] += 1
        if c is not None and _number(c.get("value")) != _number(p["planted"]):
            out["value_changed"] += 1   # the Validator must mark, not correct
        out["per_calc"][cid] = {"kind": kinds[cid], "outcome": outcome, "status": status or None, **p}
    right = [cid for cid in strict_ok if cid not in plants and cid in by_calc]
    out["false_alarm"] = sum(str(by_calc[c].get("verification_status", "")).lower() == "needs_review" for c in right)
    out["right_checked"] = len(right)
    checked = out["caught"] + out["missed"]
    out["recall"] = out["caught"] / checked if checked else None
    return out


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


def table(results):
    lines = ["| source run | planted | caught | missed | not checked | recall | raw caught/checked | derived caught/checked | false alarms | values changed |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in results:
        def kind(k):
            b = r["by_kind"][k]
            return f"{b['caught']}/{b['caught'] + b['missed']}"
        rec = "–" if r["recall"] is None else f"{r['recall']:.0%}"
        lines.append(f"| {name} | {r['planted']} | {r['caught']} | {r['missed']} | {r['not_checked']} | {rec} | {kind('raw')} | "
                     f"{kind('derived')} | {r['false_alarm']}/{r['right_checked']} | {r['value_changed']} |")
    return "\n".join(lines)


def main():
    import boto3
    from botocore.config import Config
    from dotenv import dotenv_values
    from graders import cost
    from run_eval import _runtime_bucket
    env = {**dotenv_values(HERE.parent / "managed-agentcore" / ".env"), **dotenv_values(HERE / "config" / "eval.env"), **os.environ}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("component", choices=["validator"])
    ap.add_argument("--from", dest="sources", action="append", required=True, help="saved run folder (repeatable)")
    ap.add_argument("--plant", type=int, default=6, help="errors to plant per run")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--allow-test", action="store_true", help="allow source runs of test-split scenarios")
    ap.add_argument("--runtime-arn", default=env.get("EVAL_RUNTIME_ARN"))
    ap.add_argument("--region", default=env.get("EVAL_REGION") or env.get("AWS_REGION") or "us-west-2")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--timeout", type=int, default=1800)
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
    for src in map(Path, args.sources):
        name = json.loads((src / "run.json").read_text(encoding="utf-8"))["scenario"]
        sc = load_scenario(name)
        if sc["split"] == "test" and not args.allow_test:
            ap.error(f"{src.name} is a run of test scenario {name}; pass --allow-test")
        adir = artifacts_dir(src)
        calcs = {c["id"]: c for c in json.loads((adir / "calculation_metadata.json").read_text(encoding="utf-8"))["calculations"]}
        _, strict = recompute.grade(adir, sc["csv"], with_strict=True)
        plans = plans_from_events(src)
        if not plans:
            ap.error(f"{src}: no plan in events.jsonl")
        for i in range(1, args.repeat + 1):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_dir = HERE / "eval_results" / args.tag / "component" / args.component / f"{name}-{stamp}-{i}"
            run_dir.mkdir(parents=True)
            ids, kinds = pick_plants(calcs, strict, Path(sc["csv"]).name, args.plant, rng)
            plants = {c: {"original": calcs[c]["value"], "planted": planted_value(calcs[c]["value"]),
                          "formula": calcs[c].get("formula"), "source_file": calcs[c].get("source_file")} for c in ids}
            (run_dir / "planted.json").write_text(json.dumps({"source_run": str(src), "kinds": kinds, "plants": plants},
                                                             indent=2, ensure_ascii=False), encoding="utf-8")
            staged = run_dir / "staged_artifacts"
            stage(adir, staged, plants)
            prefix = f"uploads/eval-component-{args.component}-{name.replace('_', '-')}-{stamp}-{i}/"
            payload = {"prompt": sc["query"].strip(), "component": args.component, "full_plan": plans[-1],
                       "data_directory": upload(s3, args.bucket, prefix + "data/", sc["upload"]),
                       "artifacts_directory": upload(s3, args.bucket, prefix + "artifacts/", staged)}
            print(f"{name} ← {src.name} run {i}: planted {len(plants)} ({sum(k == 'raw' for k in kinds.values())} raw, "
                  f"{sum(k == 'derived' for k in kinds.values())} derived) → {run_dir.relative_to(HERE)}", flush=True)
            meta, usage = invoke(args, payload, run_dir, (agentcore, s3))
            if meta["status"] != "completed":
                failures += 1
                print(f"  {meta['status']} {meta.get('error', '')}", flush=True)
                continue
            r = score(artifacts_dir(run_dir), plants, kinds, [c for c, ok in strict.items() if ok])
            c = cost.compute({"by_agent": usage})
            r["cost_usd"] = c["cost_usd"] if c["cost_complete"] else None
            (run_dir / "result.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append((f"{src.name} #{i}", r))
            print(f"  caught {r['caught']}/{r['planted']} · missed {r['missed']} · not checked {r['not_checked']} · "
                  f"false alarms {r['false_alarm']}/{r['right_checked']} · {meta['duration_s']:.0f}s"
                  + (f" · ${r['cost_usd']:.2f}" if r.get("cost_usd") is not None else ""), flush=True)
    if results:
        print(table(results))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
