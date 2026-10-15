"""Grade the Planner on its own: does the plan set up what the request asks for?

    python planner_eval.py runs eval_results/baseline [eval_results/other ...]
    python planner_eval.py generate --scenario yummy_food_kr --repeat 5 --tag planner-baseline

`runs` grades the plan each saved run's Planner wrote (from events.jsonl; the
last one when the plan was revised). `generate` calls the Planner alone, with
the deployed planner prompt, the eval runtime's PLANNER_MODEL_ID and the
request fields the runtime builds for it, so a planner.md change can be
measured over many samples for cents instead of full runs. Its input differs
from a full run in one place: the user message is the request itself, where a
run passes the Coordinator's hand-off text.

Each plan gets graders/plan.py's rule checks (step order, Auditor, output
format, language) and the judge's requirement coverage and data-quality
check, cached in plan_eval.json next to the plan by plan hash and grader
version. Prints one table per scenario. Paid: the judge (judge.yaml) per plan,
and with `generate` the Planner call (an Opus call with thinking).
"""
import argparse
import hashlib
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from grade import load_scenario  # noqa: E402
from graders import cost, judge, plan  # noqa: E402


def grade_plan(run_dir, plan_text, scenario, ctx):
    """plan_eval.json for one plan, reused while the plan and grader version are unchanged."""
    client, cfg = ctx
    if client is None:  # rule checks only: free, and never cached as if the judge had run
        return plan.grade(None, cfg, scenario["query"], scenario.get("requirements", []), plan_text)[0]
    digest = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
    ver = plan.version(cfg)
    cache = Path(run_dir) / "plan_eval.json"
    if cache.is_file():
        prev = json.loads(cache.read_text(encoding="utf-8"))
        if prev.get("plan_sha256") == digest and prev.get("version") == ver:
            return prev["scores"]
    scores, record, usage = plan.grade(client, cfg, scenario["query"], scenario.get("requirements", []), plan_text)
    scores["plan_judge_cost_usd"] = judge.judge_cost([usage]) if usage else None
    cache.write_text(json.dumps({"version": ver, "plan_sha256": digest, "scores": scores, "verdict": record, "usage": usage},
                                indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return scores


# --- generate: the Planner alone -------------------------------------------------------

def planner_request(model_id):
    """Model and request fields as the runtime builds them for the Planner (enable_reasoning=True)."""
    os.environ.setdefault("AWS_REGION", "us-west-2")
    sys.path.insert(0, str(REPO / "managed-agentcore"))
    from src.utils.strands_sdk_utils import strands_utils
    c = strands_utils.get_model(llm_type=model_id, enable_reasoning=True, tool_cache=False).config
    return {"maxTokens": c.get("max_tokens")}, c.get("additional_request_fields") or {}, c.get("stop_sequences") or []


def generate_plan(bedrock, model_id, query):
    sys.path.insert(0, str(REPO / "managed-agentcore"))
    from src.prompts.template import apply_prompt_template
    system = apply_prompt_template(prompt_name="planner", prompt_context={"USER_REQUEST": query})
    inference, extra, stops = planner_request(model_id)
    if stops:
        inference["stopSequences"] = stops
    resp = bedrock.converse(modelId=model_id, system=[{"text": system}],
                            messages=[{"role": "user", "content": [{"text": f"AgentCore Request: <user_request>{query}</user_request>"}]}],
                            inferenceConfig=inference, additionalModelRequestFields=extra)
    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    u = resp.get("usage", {})
    usage = {"model_id": model_id, "input": u.get("inputTokens", 0), "output": u.get("outputTokens", 0),
             "cache_read": u.get("cacheReadInputTokens", 0), "cache_write": u.get("cacheWriteInputTokens", 0)}
    c = cost.compute({"by_agent": {"planner": usage}})
    return text, (c["cost_usd"] if c["cost_complete"] else None)


def _eval_env():
    return {**dotenv_values(REPO / "managed-agentcore" / ".env"), **dotenv_values(HERE / "config" / "eval.env"), **os.environ}


def planner_model(region, arn):
    from run_eval import runtime_config
    return (runtime_config(region, arn).get("models") or {}).get("PLANNER_MODEL_ID")


# --- table ---------------------------------------------------------------------------

def table(rows):
    """rows: (scenario, scores). One line per scenario."""
    by = defaultdict(list)
    for sc, s in rows:
        by[sc].append(s)
    out = ["| scenario | plans | requirements met | missing (count) | data-quality step | step order ok | Auditor planned | format | language |",
           "|---|---|---|---|---|---|---|---|---|"]

    def rate(xs, k):
        v = [bool(x[k]) for x in xs if x.get(k) is not None]
        return f"{sum(v)}/{len(v)}" if v else "–"

    for sc, xs in sorted(by.items()):
        met = [x["plan_requirements_met"] for x in xs if x.get("plan_requirements_met") is not None]
        missing = defaultdict(int)
        for x in xs:
            for r in x.get("plan_requirements_missing") or []:
                missing[r] += 1
        out.append(f"| {sc} | {len(xs)} | {f'{statistics.fmean(met):.0%}' if met else '–'} | "
                   f"{', '.join(f'{k} ({n})' for k, n in sorted(missing.items())) or '–'} | {rate(xs, 'plan_data_quality')} | "
                   f"{rate(xs, 'plan_workflow_ok')} | {rate(xs, 'plan_auditor_planned')} | {rate(xs, 'plan_format_ok')} | {rate(xs, 'plan_language_ok')} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("runs", help="grade the plans in saved runs")
    r.add_argument("tags", nargs="+")
    g = sub.add_parser("generate", help="call the Planner alone, then grade")
    g.add_argument("--scenario", required=True, action="append")
    g.add_argument("--repeat", type=int, default=3)
    g.add_argument("--tag", required=True, help="plans go to eval_results/<tag>/planner/")
    g.add_argument("--model", help="default: the eval runtime's PLANNER_MODEL_ID")
    g.add_argument("--allow-test", action="store_true", help="allow test-split scenarios")
    for p in (r, g):
        p.add_argument("--no-judge", action="store_true", help="rule checks only (no model calls for grading)")
    args = ap.parse_args()

    cfg = judge.load_config()
    if not args.no_judge:
        judge.check_available(cfg)
    ctx = (None if args.no_judge else judge.make_client(cfg), cfg)
    rows = []

    if args.cmd == "runs":
        for tag in args.tags:
            for run_json in sorted(Path(tag).glob("*/run.json")):
                run_dir = run_json.parent
                name = json.loads(run_json.read_text(encoding="utf-8"))["scenario"]
                plans = plan.plans_from_events(run_dir)
                if not plans:
                    print(f"  {run_dir.name}: no plan in events.jsonl", file=sys.stderr)
                    continue
                rows.append((name, grade_plan(run_dir, plans[-1], load_scenario(name), ctx)))
    else:
        import boto3
        scenarios = {n: load_scenario(n) for n in args.scenario}
        test = [n for n, s in scenarios.items() if s["split"] == "test"]
        if test and not args.allow_test:
            ap.error(f"{', '.join(test)}: test scenario(s); pass --allow-test")
        env = _eval_env()
        region = env.get("EVAL_REGION") or env.get("AWS_REGION") or "us-west-2"
        model = args.model or planner_model(region, env.get("EVAL_RUNTIME_ARN"))
        if not model:
            ap.error("no PLANNER_MODEL_ID: pass --model or set EVAL_RUNTIME_ARN (eval_runtime.py create writes it)")
        bedrock = judge.make_client({**cfg, "region": region})
        print(f"planner {model} · judge {'off' if args.no_judge else cfg['model']}", flush=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for name, sc in scenarios.items():
            for i in range(1, args.repeat + 1):
                run_dir = HERE / "eval_results" / args.tag / "planner" / f"{name}-{stamp}-{i}"
                run_dir.mkdir(parents=True)
                text, usd = generate_plan(bedrock, model, sc["query"].strip())
                (run_dir / "plan.md").write_text(text, encoding="utf-8")
                (run_dir / "run.json").write_text(json.dumps({"scenario": name, "split": sc["split"], "planner_model": model,
                                                              "planner_cost_usd": usd}, indent=2), encoding="utf-8")
                s = grade_plan(run_dir, text, sc, ctx)
                rows.append((name, s))
                print(f"  {run_dir.relative_to(HERE)} · planner ${usd or 0:.2f} · met {s.get('plan_requirements_met', '–')}"
                      f" · missing {s.get('plan_requirements_missing', '–')}", flush=True)
    print(table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
