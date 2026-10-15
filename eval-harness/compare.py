"""Compare eval results between tags (e.g. baseline vs a candidate change).

    python compare.py eval_results/baseline eval_results/opus55 [--scenario jungle_market] [--split dev] [--out compare.md]

Each tag folder holds run folders with scores.json (from run_eval.py or
grade.py). Dev and test scenarios (`split` in scenarios.yaml) are reported in
separate sections, each opening with the core pass rate pooled over its
scenarios, so a test result never blends into the dev numbers being tuned.
Then one markdown table per scenario:

  pass/fail metrics  rate with a 95% Wilson interval, e.g. 67% [21–94%] (2/3)
  other metrics      mean ± std (n)
  Δ                  difference vs the first tag with a 95% bootstrap interval;
                     ▲/▼ only with at least 5 runs a side and an interval that
                     excludes 0
  pass^k             chance that k runs in a row all pass

With about 3 runs per side no delta is flagged: a bootstrap over 3 values is
too coarse (a constant series resamples to itself and gives a zero-width
interval), so 2/3 → 3/3 or even 0/3 → 3/3 is shown, not called a change. Runs under one tag that mix git SHAs, runtime versions
or model sets are flagged too, since averaging across them compares nothing.
"""
import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from grade import load_scenarios

# (metric, label, direction, kind) — direction +1 = higher is better, -1 = lower is better.
# kind: "binary" pass/fail per run (Wilson interval), "rate" prints as %, "num"
# as a plain number, "usd", "s".
METRICS = [
    ("core_pass", "core pass rate", +1, "binary"),
    ("all_required_ok", "required artifacts ok", +1, "binary"),
    ("citation_value_match_rate", "citation = metadata", +1, "rate"),
    ("recompute_match_rate", "recompute matches CSV", +1, "rate"),
    ("cited_value_match_rate", "printed value = citation", +1, "rate"),
    ("broken_citation_refs", "broken [n] refs", -1, "num"),
    ("citation_inside_number", "[n] inside a number", -1, "num"),
    ("citation_coverage", "citation coverage", +1, "rate"),
    ("cited_value_checked", "citations compared", +1, "num"),
    ("recompute_supported", "calculations recomputed", +1, "num"),
    ("validator_false_verified", "Validator verified, recompute disagrees", -1, "num"),
    ("validator_false_alarm", "Validator needs_review, recompute agrees", -1, "num"),
    ("facts_found", "answer-key facts correct", +1, "num"),
    ("factcheck_wrong_confirmed", "answer-key facts stated wrong", -1, "num"),
    ("factcheck_needs_review", "fact check: needs review", -1, "num"),
    ("factcheck_unit_issues", "fact check: unit issues (%p for %)", -1, "num"),
    ("judge_requirement_coverage", "judge: requirements met", +1, "rate"),
    ("judge_requirements_missing", "judge: requirements missing", -1, "num"),
    ("judge_score_mean", "judge: mean score (1-5)", +1, "num"),
    ("judge_evidence_linkage", "judge: evidence linkage", +1, "num"),
    ("judge_strategy_specificity", "judge: strategy specificity", +1, "num"),
    ("judge_insight_depth", "judge: insight depth", +1, "num"),
    ("judge_reasoning_soundness", "judge: reasoning soundness", +1, "num"),
    ("audit_pass", "auditor pass", +1, "binary"),
    ("audit_block_findings", "auditor block findings", -1, "num"),
    ("audit_missed", "auditor passed a defect the graders found", -1, "binary"),
    ("citation_count", "citations", +1, "num"),
    ("chart_count", "charts", 0, "num"),
    ("cost_usd", "cost", -1, "usd"),
    ("judge_cost_usd", "judge cost (pointwise)", 0, "usd"),
    ("factcheck_cost_usd", "fact check cost", 0, "usd"),
    ("cache_hit_rate", "cache hit rate", +1, "rate"),
    ("tokens_input_total", "input tokens", -1, "num"),
    ("tokens_output", "output tokens", 0, "num"),
    ("duration_s", "duration", -1, "s"),
    ("time_to_first_plan_s", "time to first plan", -1, "s"),
    ("code_exec_failed", "failed code executions", -1, "num"),
    ("code_executions", "code executions", -1, "num"),
]


def split_of(scenario, run_meta, listed):
    """The split recorded at run time, else the one in scenarios.yaml; None for a scenario no longer listed."""
    return run_meta.get("split") or (listed.get(scenario) or {}).get("split")


def load_runs(tag_dir):
    listed = load_scenarios()
    runs = []
    for scores_path in sorted(Path(tag_dir).glob("*/scores.json")):
        data = json.loads(scores_path.read_text(encoding="utf-8"))
        s = data["scores"]
        run_meta = scores_path.parent / "run.json"
        scenario = json.loads(run_meta.read_text())["scenario"] if run_meta.is_file() else scores_path.parent.name.rsplit("-", 3)[0]
        meta = json.loads(run_meta.read_text()) if run_meta.is_file() else {}
        s["_agent_calls"] = meta.get("agent_calls", {})
        s["_split"] = split_of(scenario, meta, listed)
        s["_cost_by_agent"] = data.get("details", {}).get("cost_by_agent", {})
        cfg_path = scores_path.parent / "config.json"
        s["_config"] = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
        runs.append((scenario, s))
    return runs


def values(runs, metric):
    out = []
    for s in runs:
        v = s.get(metric)
        if isinstance(v, bool):
            v = float(v)
        if isinstance(v, (int, float)):
            out.append(float(v))
    return out


def summarize(vals):
    if not vals:
        return None
    return {"mean": statistics.fmean(vals), "std": statistics.stdev(vals) if len(vals) > 1 else 0.0, "n": len(vals), "vals": vals}


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def bootstrap_diff(a, b, iters=4000, seed=0):
    """95% percentile interval of mean(b) - mean(a), resampling each side."""
    rng = random.Random(seed)
    diffs = sorted(statistics.fmean(rng.choices(b, k=len(b))) - statistics.fmean(rng.choices(a, k=len(a))) for _ in range(iters))
    return diffs[int(0.025 * iters)], diffs[int(0.975 * iters) - 1]


def pass_k(vals):
    """Unbiased pass^k for k = 1..n: C(successes, k) / C(n, k)."""
    n, c = len(vals), int(sum(vals))
    return [math.comb(c, k) / math.comb(n, k) for k in range(1, n + 1)]


def fmt(v, kind):
    if v is None:
        return "–"
    if kind in ("rate", "binary"):
        return f"{v * 100:.0f}%" if kind == "binary" else f"{v * 100:.1f}%"
    if kind == "usd":
        return f"${v:.2f}"
    if kind == "s":
        return f"{v:.0f}s"
    return f"{v:.1f}" if abs(v) < 100 else f"{v:,.0f}"


def fmt_stat(st, kind):
    if st is None:
        return "–"
    if kind == "binary":
        k, n = int(sum(st["vals"])), st["n"]
        lo, hi = wilson(k, n)
        return f"{fmt(k / n, kind)} [{lo * 100:.0f}–{hi * 100:.0f}%] ({k}/{n})"
    spread = f" ± {fmt(st['std'], kind)}" if st["n"] > 1 else ""
    return f"{fmt(st['mean'], kind)}{spread} (n={st['n']})"


def _fmt_d(d, kind, base_mean):
    if kind in ("rate", "binary"):
        return f"{d * 100:+.0f}%p"
    if kind == "usd":
        return f"{'+' if d >= 0 else '−'}${abs(d):.2f}"
    if kind == "s":
        return f"{d:+.0f}s"
    return f"{d:+.1f}" if abs(d) < 100 else f"{d:+,.0f}"


# Below this many runs a side, a bootstrap interval says little: with n = 3 a
# constant series resamples to itself, so (0, 0, 0) vs (1, 1, 1) gets a
# zero-width interval that "excludes 0". Deltas are still printed, unflagged.
MIN_N_FOR_FLAGS = 5


def delta(base, cand, kind, direction):
    """Difference with its bootstrap interval; flagged only with enough runs and an interval excluding 0."""
    if base is None or cand is None:
        return "–", ""
    d = cand["mean"] - base["mean"]
    lo, hi = bootstrap_diff(base["vals"], cand["vals"])
    text = f"{_fmt_d(d, kind, base['mean'])} [{_fmt_d(lo, kind, base['mean'])}, {_fmt_d(hi, kind, base['mean'])}]"
    clear = (lo > 1e-12 or hi < -1e-12) and min(base["n"], cand["n"]) >= MIN_N_FOR_FLAGS
    if direction == 0 or not clear:
        return text, ""
    return text, "▲ better" if d * direction > 0 else "▼ worse"


def config_warnings(tags, runs_by_tag):
    """Runs under one tag must come from the same code, runtime and models."""
    out = []
    for t in tags:
        seen = defaultdict(int)
        for s in runs_by_tag[t]:
            c = s.get("_config") or {}
            models = ", ".join(f"{k.replace('_MODEL_ID', '').lower()}={v.split('.')[-1]}" for k, v in sorted((c.get("models") or {}).items()))
            seen[(str(c.get("git_sha", "?"))[:7], str(c.get("runtime_version", "?")), models)] += 1
        if len(seen) > 1:
            parts = "; ".join(f"{n}× git {g} / runtime v{r}" for (g, r, m), n in seen.items())
            out.append(f"> ⚠ `{Path(t).name}` mixes {len(seen)} configurations ({parts}). Split them into separate tags before comparing.")
    return out


# (version key, a metric the evaluator always writes, name, rows it affects)
EVALUATORS = [("factcheck_version", "factcheck_statements", "Fact check", "fact rows"),
              ("judge_version", "judge_score_mean", "The LLM judge", "judge rows")]


def evaluator_warnings(tags, runs_by_tag):
    """Every run must be graded by the same evaluators, or a delta may be the evaluator's."""
    out = []
    runs = [s for t in tags for s in runs_by_tag[t]]
    for key, marker, what, rows in EVALUATORS:
        versions = {s[key] for s in runs if s.get(key)}
        # graded before versions were recorded: can't be shown to match the others
        unversioned = any(s.get(marker) is not None and not s.get(key) for s in runs)
        if len(versions) + unversioned > 1:
            listed = "; ".join(sorted(versions)) + ("; unversioned (older cache)" if unversioned else "")
            out.append(f"> ⚠ {what} ran with {len(versions) + unversioned} evaluator versions ({listed}). "
                       f"Re-grade every tag with the current one (grade.py on the saved runs) before reading the {rows}.")
    return out


def table(scenario, tags, runs_by_tag):
    lines = [f"### {scenario}", ""]
    lines += config_warnings(tags, runs_by_tag) + evaluator_warnings(tags, runs_by_tag)
    ns = [len(runs_by_tag[t]) for t in tags]
    if min(ns) < 5:
        lines.append(f"> Fewer than {MIN_N_FOR_FLAGS} runs on a side (n = {', '.join(map(str, ns))}): deltas are shown without ▲/▼. "
                     "With this few runs a bootstrap interval can be zero-width and isn't evidence of a change.")
    if lines[-1] != "":
        lines.append("")
    header = ["metric"] + [Path(t).name for t in tags] + [f"Δ {Path(t).name}" for t in tags[1:]]
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for metric, label, direction, kind in METRICS:
        stats = [summarize(values(runs_by_tag[t], metric)) for t in tags]
        if all(s is None for s in stats):
            continue
        row = [label] + [fmt_stat(s, kind) for s in stats]
        for s in stats[1:]:
            text, flag = delta(stats[0], s, kind, direction)
            row.append(f"{text} {flag}".strip())
        lines.append("| " + " | ".join(row) + " |")
        if metric == "core_pass":
            cells = []
            for st in stats:
                cells.append("–" if st is None else " · ".join(f"k={k} {v * 100:.0f}%" for k, v in enumerate(pass_k(st["vals"]), 1)))
            lines.append("| pass^k (k runs in a row all pass) | " + " | ".join(cells) + " |" + " |" * (len(tags) - 1))

    # Per-agent cost: where the money goes and what a model change moved.
    agents = sorted({a for t in tags for s in runs_by_tag[t] for a in s["_cost_by_agent"]})
    if agents:
        lines += ["", "| agent cost (mean) | " + " | ".join(Path(t).name for t in tags) + " |", "|" + "---|" * (len(tags) + 1)]
        for a in agents:
            cells = []
            for t in tags:
                v = [s["_cost_by_agent"][a]["cost_usd"] for s in runs_by_tag[t] if a in s["_cost_by_agent"] and s["_cost_by_agent"][a]["cost_usd"] is not None]
                models = {s["_cost_by_agent"][a]["model_id"] for s in runs_by_tag[t] if a in s["_cost_by_agent"]}
                short = ", ".join(sorted(m.split("anthropic.")[-1].split("-v1")[0] for m in models if m))
                cells.append(f"{fmt(statistics.fmean(v), 'usd')} ({short})" if v else "–")
            lines.append(f"| {a} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# Section order and headings; None = a scenario no longer in scenarios.yaml.
SECTIONS = [("dev", "Dev scenarios"), ("test", "Test scenarios (release check: don't tune on these)"),
            (None, "Scenarios not in scenarios.yaml")]


def pooled(scenarios, tags, by_scenario):
    """Core pass rate per tag over all runs of these scenarios, so dev and test each get one headline number."""
    lines = ["| pooled over " + ", ".join(scenarios) + " | " + " | ".join(Path(t).name for t in tags) + " |",
             "|" + "---|" * (len(tags) + 1)]
    cells = [fmt_stat(summarize(values([s for sc in scenarios for s in by_scenario[sc][t]], "core_pass")), "binary") for t in tags]
    return lines + ["| core pass rate | " + " | ".join(cells) + " |"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tags", nargs="+", help="tag folders; the first is the baseline")
    ap.add_argument("--scenario", action="append")
    ap.add_argument("--split", choices=["dev", "test"], help="only this split")
    ap.add_argument("--out")
    args = ap.parse_args()

    by_scenario = defaultdict(lambda: defaultdict(list))
    split = {}
    for t in args.tags:
        if not Path(t).is_dir():
            ap.error(f"no such tag folder: {t}")
        for scenario, s in load_runs(t):
            by_scenario[scenario][t].append(s)
            split.setdefault(scenario, s["_split"])

    scenarios = args.scenario or sorted(by_scenario)
    listed = load_scenarios()
    for sc in scenarios:  # a --scenario with no runs yet
        split.setdefault(sc, (listed.get(sc) or {}).get("split"))
    parts = [f"## Eval comparison: {' vs '.join(Path(t).name for t in args.tags)}", "",
             "Δ is vs the first tag, with a 95% bootstrap interval in brackets. ▲/▼ only when that interval excludes 0.", ""]
    for key, heading in SECTIONS:
        group = [sc for sc in scenarios if split.get(sc) == key and (args.split is None or key == args.split)]
        if not group:
            continue
        parts += [f"## {heading}", ""] + pooled(group, args.tags, by_scenario) + [""]
        for sc in group:
            parts += [table(sc, args.tags, by_scenario[sc]), ""]
    # Pairwise LLM judge results written by pairwise.py, if any.
    import pairwise
    for t in args.tags[1:]:
        f = Path(t) / f"pairwise_vs_{Path(args.tags[0]).name}.json"
        if f.is_file():
            parts += [pairwise.table(json.loads(f.read_text(encoding="utf-8"))), ""]
    text = "\n".join(parts)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
