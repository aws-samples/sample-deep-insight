"""Run eval scenarios against the deployed AgentCore Runtime, then grade them.

For each repeat: invoke the runtime, answer plan reviews automatically through
the S3 feedback file (no human, no 300 s timeout), record every event with a
client timestamp, download the session's artifacts from S3, snapshot the
runtime's model configuration, and run grade.py.

    eval_results/<tag>/<scenario>-<timestamp>-<n>/
      events.jsonl   every streamed event + client_ts
      run.json       status, timings, plan revisions, agent calls (from usage events)
      usage.json     token usage by agent, summed from the event stream
      config.json    git SHA, runtime ARN/version, model IDs from the runtime env
      artifacts/     downloaded from s3://<bucket>/deep-insight/fargate_sessions/<session_id>/
      scores.json    from grade.py

Usage:
    python run_eval.py --scenario jungle_market --repeat 5 --tag baseline \\
        --runtime-arn arn:aws:bedrock-agentcore:... [--region us-west-2]

Test-split scenarios (moon_market, see scenarios.yaml) run only with
--allow-test: they are for a release check, and looking at their results
while tuning makes them a second dev set.

The invoke and feedback logic mirrors managed-agentcore/02_invoke_agentcore_runtime_vpc.py,
which can't be imported (it parses CLI args and loads .env at import time).
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from grade import announce, grade_run, load_scenario, model_ctx  # noqa: E402

SESSIONS_PREFIX = "deep-insight/fargate_sessions/"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_sse(line):
    if not line:
        return None
    text = line.decode("utf-8", errors="replace").strip()
    if text.startswith("data: "):
        text = text[6:].strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def upload_feedback(s3, event, approved, feedback, fallback_bucket):
    path = event.get("feedback_s3_path", "")
    if path.startswith("s3://") and path[5:].split("/", 1)[0]:
        bucket, key = path[5:].split("/", 1)
    else:
        bucket, key = fallback_bucket, f"deep-insight/feedback/{event.get('request_id', '')}.json"
    body = {"approved": approved, "feedback": feedback, "timestamp": datetime.now().isoformat()}
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(body, ensure_ascii=False), ContentType="application/json")
    return f"s3://{bucket}/{key}"


def runtime_config(region, runtime_arn):
    """The deployed runtime's version and model env, which decide what is being measured."""
    runtime_id = runtime_arn.rsplit("/", 1)[-1]
    try:
        ctl = boto3.client("bedrock-agentcore-control", region_name=region)
        r = ctl.get_agent_runtime(agentRuntimeId=runtime_id)
    except Exception as e:
        return {"error": f"get_agent_runtime failed: {e}"}
    env = r.get("environmentVariables", {}) or {}
    return {
        "runtime_version": r.get("agentRuntimeVersion"),
        "runtime_updated_at": str(r.get("lastUpdatedAt")),
        "models": {k: v for k, v in sorted(env.items()) if k.endswith("_MODEL_ID")},
    }


def git_info():
    def git(*args):
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return {"git_sha": git("rev-parse", "HEAD"), "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"), "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def find_session(s3, bucket, since):
    """Newest session folder created after `since`, for runtimes that don't report session_id."""
    newest = None
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=SESSIONS_PREFIX):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < since:
                continue
            sid = obj["Key"][len(SESSIONS_PREFIX):].split("/", 1)[0]
            if newest is None or obj["LastModified"] > newest[1]:
                newest = (sid, obj["LastModified"])
    return newest[0] if newest else None


def download_session(s3, bucket, session_id, dest):
    """Mirror the session folder; files under its artifacts/ land in dest/artifacts/."""
    prefix = f"{SESSIONS_PREFIX}{session_id}/"
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix):]
            if not rel or rel.endswith("/"):
                continue
            target = dest / "s3" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, obj["Key"], str(target))
            n += 1
    src = dest / "s3" / "artifacts"
    if src.is_dir():
        (dest / "artifacts").symlink_to(Path("s3") / "artifacts", target_is_directory=True)
    return n


def upload_data(s3, bucket, scenario_name, files):
    """Put a scenario's data files where the web app puts uploads; the S3 data_directory for the payload.

    For datasets that aren't baked into the runtime image. Only the listed
    files go up, so an answer sheet next to the CSV never reaches the agents.
    """
    prefix = f"uploads/eval-{scenario_name.replace('_', '-')}/"
    for f in files:
        path = (HERE / f).resolve()
        s3.upload_file(str(path), bucket, prefix + path.name)
    return f"s3://{bucket}/{prefix}"


def run_once(args, scenario_name, scenario, run_dir, clients):
    agentcore, s3 = clients
    run_dir.mkdir(parents=True)
    feedback_queue = list(scenario.get("hitl") or [])
    usage = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "model_id": None})
    agent_first, agent_last = {}, {}
    calls = Counter()
    meta = {"scenario": scenario_name, "split": scenario["split"], "tag": args.tag, "status": "incomplete", "plan_revisions": 0}

    start = time.monotonic()
    started_at = datetime.now(timezone.utc)
    meta["started_at"] = started_at.isoformat()
    payload = {"prompt": scenario["query"].strip(), "data_directory": scenario["data_directory"]}

    try:
        resp = agentcore.invoke_agent_runtime(agentRuntimeArn=args.runtime_arn, qualifier="DEFAULT", payload=json.dumps(payload))
        with open(run_dir / "events.jsonl", "w", encoding="utf-8") as events:
            for line in resp["response"].iter_lines(chunk_size=1):
                ev = parse_sse(line)
                if ev is None:
                    continue
                t = time.monotonic() - start
                events.write(json.dumps({"client_ts": round(t, 3), **ev}, ensure_ascii=False) + "\n")
                kind = ev.get("type") or ev.get("event_type")
                agent = ev.get("agent_name")
                if agent:
                    agent_first.setdefault(agent, t)
                    agent_last[agent] = t

                if kind == "plan_review_request":
                    meta.setdefault("time_to_first_plan_s", round(t, 1))
                    if feedback_queue:
                        fb = feedback_queue.pop(0)
                        where = upload_feedback(s3, ev, False, fb, args.bucket)
                        meta["plan_revisions"] += 1
                        log(f"  plan review → revision requested ({where})")
                    else:
                        where = upload_feedback(s3, ev, True, "", args.bucket)
                        log(f"  plan review → approved at {t:.0f}s")
                elif ev.get("event_type") == "usage_metadata" and agent:
                    # one usage event per agent invocation (tool calls are not streamed)
                    calls[agent] += 1
                    u = usage[agent]
                    u["input"] += ev.get("input_tokens", 0) or 0
                    u["output"] += ev.get("output_tokens", 0) or 0
                    u["cache_read"] += ev.get("cache_read_input_tokens", 0) or 0
                    u["cache_write"] += ev.get("cache_write_input_tokens", 0) or 0
                    u["model_id"] = ev.get("model_id") or u["model_id"]
                elif kind == "workflow_complete":
                    meta["status"] = "completed"
                    meta["session_id"] = ev.get("session_id") or None
                    break
                if t > args.timeout:
                    meta["status"] = "timeout"
                    break
    except Exception as e:
        meta["status"] = "error"
        meta["error"] = f"{type(e).__name__}: {e}"

    meta["duration_s"] = round(time.monotonic() - start, 1)
    meta["agent_calls"] = dict(sorted(calls.items()))
    # first-to-last event per agent; an agent called several times spans the gaps too
    meta["agent_span_s"] = {a: round(agent_last[a] - agent_first[a], 1) for a in sorted(agent_first)}

    # Artifacts
    sid = meta.get("session_id")
    try:
        if not sid and getattr(args, "allow_session_fallback", False):
            # Guessing "the newest session" can pick up someone else's run in a
            # shared bucket, so it is opt-in and flagged.
            sid = find_session(s3, args.bucket, started_at)
            meta["session_id"] = sid
            meta["session_id_source"] = "s3_newest_after_start" if sid else None
            meta["warning"] = "session_id guessed from the newest S3 session; results may belong to another run"
        elif not sid and meta["status"] == "completed":
            meta["status"] = "session_unresolved"  # don't grade a session we can't identify
        meta["artifact_files"] = download_session(s3, args.bucket, sid, run_dir) if sid else 0
    except Exception as e:
        meta["artifact_error"] = f"{type(e).__name__}: {e}"

    (run_dir / "usage.json").write_text(json.dumps({"by_agent": dict(usage)}, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    result = grade_run(run_dir, scenario["csv"], scenario["answer_key"], scenario, args.judge_ctx, getattr(args, "factcheck_ctx", None))
    (run_dir / "scores.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta, result["scores"]


def refuse_test_split(scenarios, allow_test):
    """Why the run is refused, or None: test scenarios need --allow-test."""
    test = [n for n, s in scenarios.items() if s["split"] == "test"]
    if test and not allow_test:
        return (f"{', '.join(test)} {'is a test scenario' if len(test) == 1 else 'are test scenarios'}: "
                "tune on the dev scenarios and run these before a release. Pass --allow-test to run them.")
    return None


def main():
    # eval.env (written by eval_runtime.py create) points at the eval runtime;
    # managed-agentcore/.env only has the users' runtime.
    env = {**dotenv_values(REPO / "managed-agentcore" / ".env"), **dotenv_values(HERE / "config" / "eval.env"), **os.environ}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True, action="append", help="repeatable")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--first-repeat", type=int, default=1,
                    help="number of the first repeat, so parallel batches under one tag don't share numbers (Langfuse keys items on it)")
    ap.add_argument("--tag", required=True, help="results go to eval_results/<tag>/")
    ap.add_argument("--runtime-arn", default=env.get("EVAL_RUNTIME_ARN") or env.get("RUNTIME_ARN"))
    ap.add_argument("--region", default=env.get("EVAL_REGION") or env.get("AWS_REGION") or "us-west-2")
    ap.add_argument("--allow-test", action="store_true",
                    help="allow test-split scenarios (moon_market); run them before a release, not while tuning")
    ap.add_argument("--allow-users-runtime", action="store_true",
                    help="run against the runtime the web app uses (model or image changes there reach users)")
    ap.add_argument("--bucket", default=env.get("S3_BUCKET_NAME"), help="defaults to the runtime's S3_BUCKET_NAME")
    ap.add_argument("--timeout", type=int, default=3600, help="seconds per run")
    ap.add_argument("--allow-session-fallback", action="store_true",
                    help="if the runtime reports no session_id, grade the newest S3 session (only for a bucket nobody else uses)")
    ap.add_argument("--judge", action="store_true", help="also run the LLM judge on each run (paid, see judge.yaml)")
    ap.add_argument("--no-factcheck", action="store_true", help="skip the answer-key fact check (it calls a model; on by default)")
    args = ap.parse_args()
    scenarios = {name: load_scenario(name) for name in args.scenario}
    if (refused := refuse_test_split(scenarios, args.allow_test)):
        ap.error(refused)
    args.judge_ctx = model_ctx() if args.judge else None
    args.factcheck_ctx = None if args.no_factcheck else (args.judge_ctx or model_ctx())
    announce(args.factcheck_ctx, args.judge_ctx)
    if not args.runtime_arn:
        ap.error("--runtime-arn is required (or run `eval_runtime.py create`, which writes eval.env)")
    if args.runtime_arn == env.get("RUNTIME_ARN") and not args.allow_users_runtime:
        ap.error("this is the users' runtime (managed-agentcore/.env RUNTIME_ARN); evals belong on the eval runtime "
                 "(`eval_runtime.py create`). Pass --allow-users-runtime to run here anyway.")

    cfg = {**git_info(), "runtime_arn": args.runtime_arn, "region": args.region, **runtime_config(args.region, args.runtime_arn)}
    if not args.bucket:
        args.bucket = _runtime_bucket(args.region, args.runtime_arn)
    if not args.bucket:
        ap.error("--bucket could not be determined; pass it explicitly")
    log(f"runtime v{cfg.get('runtime_version')} · git {cfg['git_sha'][:7]}{' (dirty)' if cfg['git_dirty'] else ''} · bucket {args.bucket}")
    for k, v in cfg.get("models", {}).items():
        log(f"  {k} = {v}")

    agentcore = boto3.client("bedrock-agentcore", region_name=args.region,
                             config=Config(connect_timeout=60, read_timeout=args.timeout, retries={"max_attempts": 0}))
    s3 = boto3.client("s3", region_name=args.region)
    out_root = HERE / "eval_results" / args.tag

    failures = 0
    for name, scenario in scenarios.items():
        if scenario.get("upload"):
            scenario["data_directory"] = upload_data(s3, args.bucket, name, scenario["upload"])
            log(f"{name}: data uploaded to {scenario['data_directory']}")
        for i in range(args.first_repeat, args.first_repeat + args.repeat):
            run_dir = out_root / f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{i}"
            log(f"{name} run {i} ({i - args.first_repeat + 1}/{args.repeat}) → {run_dir.relative_to(HERE)}")
            meta, s = run_once(args, name, scenario, run_dir, (agentcore, s3))
            (run_dir / "config.json").write_text(json.dumps({**cfg, "bucket": args.bucket, "scenario": name}, indent=2, ensure_ascii=False), encoding="utf-8")
            failures += not s["core_pass"]
            cost = f"${s['cost_usd']:.2f}" + ("" if s.get("cost_complete") else "+?") if "cost_usd" in s else "n/a"
            log(f"  {meta['status']} in {meta['duration_s']:.0f}s · {cost} · core_pass={s['core_pass']}"
                + (f" ({', '.join(s['core_fail_reasons'])})" if s["core_fail_reasons"] else "")
                + (f" · {meta['error']}" if meta.get("error") else "")
                + (f" · ⚠ {meta['warning']}" if meta.get("warning") else ""))
    return 1 if failures else 0


def _runtime_bucket(region, runtime_arn):
    try:
        ctl = boto3.client("bedrock-agentcore-control", region_name=region)
        env = ctl.get_agent_runtime(agentRuntimeId=runtime_arn.rsplit("/", 1)[-1]).get("environmentVariables", {})
        return env.get("S3_BUCKET_NAME")
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
