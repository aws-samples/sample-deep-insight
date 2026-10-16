"""Grade one run folder and write scores.json next to it.

A run folder is what run_eval.py writes (or a manual download from S3):

    <run_dir>/
      artifacts/          final_report_with_citations.docx, citations.json, ...
      usage.json          optional, token usage by agent
      run.json            optional, runner metadata (status, timings)

Usage:
    python grade.py <run_dir> --scenario jungle_market
    python grade.py <run_dir> --csv path/to.csv

Rule graders only: no model calls.
"""
import argparse
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
}


def pass_rules(scenario=None):
    return {**DEFAULT_PASS, **((scenario or {}).get("pass") or {})}


def fail_reasons(scores, rules):
    """The single definition of "core functionality works" for a run.

    A check that produced no result is a failure, not a pass: a grader that
    crashed, or found nothing it could check, proves nothing.
    """
    out = []
    if scores.get("status") not in (None, "completed"):
        out.append("status")
    out += sorted(k for k in scores if k.endswith("_grader_error"))

    def need(name, ok):
        if not ok:
            out.append(name)

    need("all_required_ok", scores.get("all_required_ok") is True)
    need("citations_ok", scores.get("citations_ok") is True)
    need("broken_citation_refs", scores.get("broken_citation_refs") == 0)
    need("cited_value_checked", (scores.get("cited_value_checked") or 0) >= rules["min_cited_checked"])
    need("cited_value_match_rate", (scores.get("cited_value_match_rate") or 0) >= 0.95)
    need("citation_inside_number", scores.get("citation_inside_number", 0) == 0)
    need("recompute_supported", (scores.get("recompute_supported") or 0) >= rules["min_recompute"])
    need("recompute_match_rate", scores.get("recompute_match_rate") == 1.0)
    return out


# dev: tuned against (prompts, thresholds). test: checked before a release only.
SPLITS = ("dev", "test")


def load_scenarios():
    return yaml.safe_load((HERE / "config" / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]


def load_scenario(name):
    data = load_scenarios()
    if name not in data:
        raise SystemExit(f"unknown scenario {name!r}; known: {', '.join(data)}")
    s = dict(data[name])
    if s.get("split") not in SPLITS:
        raise SystemExit(f"scenario {name!r}: split must be one of {', '.join(SPLITS)}, not {s.get('split')!r}")
    s["csv"] = str((HERE / s["csv"]).resolve())
    return s


def artifacts_dir(run_dir):
    run_dir = Path(run_dir)
    return run_dir / "artifacts" if (run_dir / "artifacts").is_dir() else run_dir


def grade_run(run_dir, csv_path=None, scenario=None):
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

    failed = fail_reasons(scores, pass_rules(scenario))
    # The Auditor passed a report the rule graders find a defect in: the defects
    # its engine exists to block (wrong cited value, broken [n], [n] inside a number).
    if scores.get("audit_present"):
        missed = [k for k, bad in (("cited_value", (scores.get("cited_value_match_rate") or 1) < 1),
                                   ("broken_ref", (scores.get("broken_citation_refs") or 0) > 0),
                                   ("inside_number", (scores.get("citation_inside_number") or 0) > 0)) if bad]
        scores["audit_missed"] = scores.get("audit_verdict") == "pass" and bool(missed)
        scores["audit_missed_kinds"] = missed if scores.get("audit_verdict") == "pass" else []
    scores["core_pass"] = not failed
    scores["core_fail_reasons"] = failed
    return {"scores": scores, "details": details}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--scenario")
    ap.add_argument("--csv")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    csv_path, scenario = args.csv, None
    if args.scenario:
        scenario = load_scenario(args.scenario)
        csv_path = csv_path or scenario["csv"]

    result = grade_run(args.run_dir, csv_path, scenario)
    out = Path(args.run_dir) / "scores.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.quiet:
        s = result["scores"]
        print(json.dumps(s, indent=2, ensure_ascii=False))
        print(f"\n{'PASS' if s['core_pass'] else 'FAIL'}  → {out}")
    return 0 if result["scores"]["core_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
