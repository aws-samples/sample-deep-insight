"""Grade one run folder and write scores.json next to it.

A run folder is what run_eval.py writes (or a manual download from S3):

    <run_dir>/
      artifacts/          final_report_with_citations.docx, citations.json, ...
      usage.json          optional, token usage by agent
      run.json            optional, runner metadata (status, timings)

Usage:
    python grade.py <run_dir> --scenario jungle_market
    python grade.py <run_dir> --scenario jungle_market --judge   # + LLM judge (paid)
    python grade.py <run_dir> --csv path/to.csv --answer-key answer_keys/x.json
    python grade.py <run_dir> --scenario jungle_market --no-factcheck   # no model calls

The answer-key fact check (factcheck.py) calls a model on Bedrock and runs by
default; its result is cached in <run_dir>/factcheck.json.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from graders import artifacts, audit, citations, executions, recompute, report  # noqa: E402
from graders import cost  # noqa: E402

# Thresholds a scenario can override in scenarios.yaml under `pass:`.
DEFAULT_PASS = {
    "min_cited_checked": 5,      # "number [n]" pairs actually compared
    "min_recompute": 10,         # calculations actually re-derived from the CSV
    "required_facts": ["total_revenue"],
    "min_other_facts": 0,        # answer-key numbers besides the required ones
}


def pass_rules(scenario=None):
    return {**DEFAULT_PASS, **((scenario or {}).get("pass") or {})}


def fail_reasons(scores, rules):
    """The single definition of "core functionality works" for a run.

    A check that produced no result is a failure, not a pass: a grader that
    crashed, or found nothing it could check, proves nothing. Only checks that
    were deliberately not run (the LLM judge without --judge, the fact check
    with --no-factcheck) are skipped.
    """
    out = []
    if scores.get("status") not in (None, "completed"):
        out.append("status")
    out += sorted(k for k in scores if k.endswith("_grader_error") or k in ("judge_error", "factcheck_error"))

    def need(name, ok):
        if not ok:
            out.append(name)

    need("all_required_ok", scores.get("all_required_ok") is True)
    need("citations_ok", scores.get("citations_ok") is True)
    need("broken_citation_refs", scores.get("broken_citation_refs") == 0)
    need("cited_value_checked", (scores.get("cited_value_checked") or 0) >= rules["min_cited_checked"])
    need("cited_value_match_rate", (scores.get("cited_value_match_rate") or 0) >= 0.95)
    need("recompute_supported", (scores.get("recompute_supported") or 0) >= rules["min_recompute"])
    need("recompute_match_rate", scores.get("recompute_match_rate") == 1.0)
    if not scores.get("factcheck_skipped"):
        need("required_facts", "facts_found_ids" in scores and not scores.get("required_facts_missing"))
        need("other_facts_found", (scores.get("other_facts_found") or 0) >= rules["min_other_facts"])
        # only statements both code and the adjudicating model call wrong; disagreements are needs_review
        need("factcheck_wrong_confirmed", scores.get("factcheck_wrong_confirmed", 0) == 0)
    if "judge_requirements_missing" in scores:  # only when --judge ran
        need("judge_requirements_missing", scores["judge_requirements_missing"] == 0)
    return out


def load_scenario(name):
    data = yaml.safe_load((HERE / "config" / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]
    if name not in data:
        raise SystemExit(f"unknown scenario {name!r}; known: {', '.join(data)}")
    s = dict(data[name])
    s["csv"] = str((HERE / s["csv"]).resolve())
    s["answer_key"] = str((HERE / s["answer_key"]).resolve())
    return s


def artifacts_dir(run_dir):
    run_dir = Path(run_dir)
    return run_dir / "artifacts" if (run_dir / "artifacts").is_dir() else run_dir


def run_judge(run_dir, adir, scenario, judge_ctx):
    """Pointwise LLM judge, cached in judge.json by report hash and judge version."""
    from graders import judge
    client, cfg = judge_ctx
    text = judge.report_text(adir, cfg["max_report_chars"])
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ver = judge.version(cfg, scenario["query"], scenario["requirements"])
    cache = Path(run_dir) / "judge.json"
    if cache.is_file():
        prev = json.loads(cache.read_text(encoding="utf-8"))
        if prev.get("report_sha256") == digest and prev.get("judge_version") == ver:
            return prev["metrics"]
    metrics, verdict, usage = judge.pointwise(client, cfg, scenario["query"], scenario["requirements"], text)
    metrics["judge_cost_usd"] = judge.judge_cost([usage])
    metrics["judge_version"] = ver
    cache.write_text(json.dumps({"model": cfg["model"], "effort": cfg.get("effort"), "judge_version": ver, "report_sha256": digest,
                                 "metrics": metrics, "verdict": verdict, "usage": usage}, indent=2, ensure_ascii=False), encoding="utf-8")
    return metrics


def run_factcheck(run_dir, adir, answer_key_path, factcheck_ctx):
    """Answer-key fact check, cached in factcheck.json by report hash and evaluator version."""
    from graders import factcheck
    from graders import judge
    from graders.report import read_docx
    client, cfg = factcheck_ctx
    paragraphs = read_docx(Path(adir) / "final_report_with_citations.docx")
    key_bytes = Path(answer_key_path).read_bytes()
    digest = hashlib.sha256("\n".join(paragraphs).encode("utf-8")).hexdigest()
    ver = factcheck.version(cfg, hashlib.sha256(key_bytes).hexdigest())
    cache = Path(run_dir) / "factcheck.json"
    if cache.is_file():
        prev = json.loads(cache.read_text(encoding="utf-8"))
        if prev.get("report_sha256") == digest and prev.get("version") == ver:
            return prev["metrics"], factcheck.describe(prev["records"])
    metrics, records, usages = factcheck.check(client, cfg, json.loads(key_bytes), paragraphs)
    metrics["factcheck_cost_usd"] = judge.judge_cost(usages)
    metrics["factcheck_version"] = ver
    cache.write_text(json.dumps({"version": ver, "report_sha256": digest, "metrics": metrics, "records": records, "usage": usages},
                                indent=2, ensure_ascii=False), encoding="utf-8")
    return metrics, factcheck.describe(records)


def grade_run(run_dir, csv_path=None, answer_key_path=None, scenario=None, judge_ctx=None, factcheck_ctx=None):
    run_dir = Path(run_dir)
    adir = artifacts_dir(run_dir)

    scores, details = {}, {}
    sections = [
        ("artifacts", lambda: artifacts.grade(adir)),
        ("citations", lambda: citations.grade(adir)),
        ("report", lambda: report.grade(adir)),
        ("audit", lambda: audit.grade(adir)),
        ("executions", lambda: executions.grade(run_dir)),
    ]
    if csv_path:
        sections.append(("recompute", lambda: recompute.grade(adir, csv_path)))
    for name, fn in sections:
        try:
            result = fn()
        except Exception as e:  # a grader bug must not hide the other scores
            result = {"details": [f"grader error: {type(e).__name__}: {e}"], f"{name}_grader_error": True}
        details[name] = result.pop("details", [])
        scores.update(result)

    if answer_key_path and factcheck_ctx is None:
        scores["factcheck_skipped"] = True
    elif answer_key_path:
        try:
            metrics, details["factcheck"] = run_factcheck(run_dir, adir, answer_key_path, factcheck_ctx)
            scores.update(metrics)
        except Exception as e:  # a failed check is reported, never silently passed
            scores["factcheck_error"] = f"{type(e).__name__}: {e}"[:300]
            details["factcheck"] = [scores["factcheck_error"]]

    if judge_ctx is not None:
        try:
            scores.update(run_judge(run_dir, adir, scenario, judge_ctx))
        except Exception as e:  # judge failure is reported, never silently scored
            scores["judge_error"] = f"{type(e).__name__}: {e}"[:300]
            details["judge"] = [scores["judge_error"]]

    usage_path = run_dir / "usage.json"
    if usage_path.is_file():
        c = cost.compute(json.loads(usage_path.read_text(encoding="utf-8")))
        scores.update({k: v for k, v in c.items() if k != "by_agent"})
        details["cost_by_agent"] = c["by_agent"]

    run_meta_path = run_dir / "run.json"
    if run_meta_path.is_file():
        meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        for k in ("status", "duration_s", "time_to_first_plan_s", "plan_revisions", "agent_calls", "agent_span_s", "warning", "session_id_source"):
            if k in meta:
                scores[k] = meta[k]

    rules = pass_rules(scenario)
    found = scores.get("facts_found_ids")
    if found is not None:
        scores["required_facts_missing"] = [f for f in rules["required_facts"] if f not in found]
        scores["other_facts_found"] = sum(f not in rules["required_facts"] for f in found)
    failed = fail_reasons(scores, rules)
    scores["core_pass"] = not failed
    scores["core_fail_reasons"] = failed
    return {"scores": scores, "details": details}


def model_ctx():
    """(Bedrock client, judge.yaml settings), shared by the judge and the fact check."""
    from graders import judge
    cfg = judge.load_config()
    judge.check_available(cfg)
    return judge.make_client(cfg), cfg


def announce(factcheck_ctx, judge_ctx):
    """Say up front which paid model calls a run will make."""
    cfg = (factcheck_ctx or judge_ctx or (None, None))[1]
    if not cfg:
        return
    on = [name for name, ctx in (("fact check ~$1/report", factcheck_ctx), ("LLM judge ~$0.1-0.3/report", judge_ctx)) if ctx]
    print(f"paid checks: {', '.join(on)} · {cfg['model']} in {cfg['region']}"
          + ("" if not factcheck_ctx else " · --no-factcheck to skip the fact check"), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--scenario")
    ap.add_argument("--csv")
    ap.add_argument("--answer-key")
    ap.add_argument("--judge", action="store_true", help="also run the LLM judge (paid; needs --scenario)")
    ap.add_argument("--no-factcheck", action="store_true", help="skip the answer-key fact check (no model calls; fact rules are skipped)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    csv_path, key_path, scenario, judge_ctx, factcheck_ctx = args.csv, args.answer_key, None, None, None
    if args.scenario:
        scenario = load_scenario(args.scenario)
        csv_path, key_path = csv_path or scenario["csv"], key_path or scenario["answer_key"]
    if args.judge:
        if scenario is None:
            ap.error("--judge needs --scenario (the request and its requirements)")
        judge_ctx = model_ctx()
    if key_path and not args.no_factcheck:
        factcheck_ctx = judge_ctx or model_ctx()

    announce(factcheck_ctx, judge_ctx)
    result = grade_run(args.run_dir, csv_path, key_path, scenario, judge_ctx, factcheck_ctx)
    out = Path(args.run_dir) / "scores.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.quiet:
        s = result["scores"]
        print(json.dumps(s, indent=2, ensure_ascii=False))
        print(f"\n{'PASS' if s['core_pass'] else 'FAIL'}  → {out}")
    return 0 if result["scores"]["core_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
