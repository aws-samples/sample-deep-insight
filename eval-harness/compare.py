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

Component runs under a tag (eval_results/<tag>/component/, from
component_eval.py or run_eval.py --components) get a table per agent under
their scenario. They compare two versions of one agent only when both ran on
the same input: a tag whose source run or planted errors differ from the
first tag's is flagged.

With about 3 runs per side no delta is flagged: a bootstrap over 3 values is
too coarse (a constant series resamples to itself and gives a zero-width
interval), so 2/3 → 3/3 or even 0/3 → 3/3 is shown, not called a change. Runs under one tag that mix git SHAs, runtime versions
or model sets are flagged too, since averaging across them compares nothing.
"""
import argparse
import hashlib
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
    ("audit_pass", "auditor pass", +1, "binary"),
    ("audit_block_findings", "auditor block findings", -1, "num"),
    ("audit_missed", "auditor passed a defect the graders found", -1, "binary"),
    ("citation_count", "citations", +1, "num"),
    ("chart_count", "charts", 0, "num"),
    ("cost_usd", "cost", -1, "usd"),
    ("cache_hit_rate", "cache hit rate", +1, "rate"),
    ("tokens_input_total", "input tokens", -1, "num"),
    ("tokens_output", "output tokens", 0, "num"),
    ("duration_s", "duration", -1, "s"),
    ("time_to_first_plan_s", "time to first plan", -1, "s"),
    ("code_exec_failed", "failed code executions", -1, "num"),
    ("code_executions", "code executions", -1, "num"),
]


# Component runs (component_eval.py): per agent, metrics from result.json.
COMPONENT_METRICS = {
    "validator": [
        ("recall", "recall (caught / checked)", +1, "rate"),
        ("caught", "planted errors caught", +1, "num"),
        ("missed", "planted errors verified", -1, "num"),
        ("not_checked", "planted errors not checked", -1, "num"),
        ("false_alarm", "false alarms on right values", -1, "num"),
        ("value_changed", "planted values changed (must mark, not correct)", -1, "num"),
        ("cost_usd", "cost", -1, "usd"),
    ],
    "reporter": [
        ("report_ok", "report written", +1, "binary"),
        ("leak_rate", "needs_review values in the report", -1, "rate"),
        ("left_out", "needs_review values left out", +1, "num"),
        ("cited", "needs_review values cited", -1, "num"),
        ("quoted", "needs_review values quoted", -1, "num"),
        ("cited_value_match_rate", "printed value = citation", +1, "rate"),
        ("citation_inside_number", "[n] inside a number", -1, "num"),
        ("cost_usd", "cost", -1, "usd"),
    ],
}


def input_fingerprint(planted):
    """What a component run was given: source run, plant settings and the planted errors (not the repeat number)."""
    record = {k: v for k, v in planted.items() if k != "repeat"}
    record["source_run"] = Path(str(record.get("source_run", ""))).name
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def load_component_runs(tag_dir):
    """[(component, scenario, result)] with the result's grader counts flattened and _source/_repeat/_input added."""
    runs = []
    for result_path in sorted(Path(tag_dir).glob("component/*/*/result.json")):
        run_dir = result_path.parent
        r = json.loads(result_path.read_text(encoding="utf-8"))
        planted_path = run_dir / "planted.json"
        planted = json.loads(planted_path.read_text(encoding="utf-8")) if planted_path.is_file() else {}
        scenario = planted.get("scenario") or run_dir.name.rsplit("-", 3)[0]
        r = {**r.get("graders", {}), **r, "_source": Path(str(planted.get("source_run", "?"))).name,
             "_repeat": planted.get("repeat"), "_input": input_fingerprint(planted) if planted else None}
        runs.append((run_dir.parent.name, scenario, r))
    return runs


def input_warnings(comp, tags, runs_by_tag):
    """A component's A/B holds only on the same input: same source run, and the same errors for the same repeat number."""
    out = []
    base = {r["_repeat"]: (r["_source"], r["_input"]) for r in runs_by_tag[tags[0]]}
    for t in tags[1:]:
        cand = {r["_repeat"]: (r["_source"], r["_input"]) for r in runs_by_tag[t]}
        sources = {s for s, _ in base.values()}, {s for s, _ in cand.values()}
        if sources[0] and sources[1] and sources[0] != sources[1]:
            out.append(f"> ⚠ {comp}: `{Path(t).name}` ran on {', '.join(sorted(sources[1]))}, `{Path(tags[0]).name}` on "
                       f"{', '.join(sorted(sources[0]))}: not the same input, so the difference isn't the agent's alone.")
            continue
        differ = sorted(i for i in base.keys() & cand.keys() if base[i] != cand[i])
        if differ:
            out.append(f"> ⚠ {comp}: repeat(s) {', '.join(map(str, differ))} planted different errors in `{Path(t).name}` than in "
                       f"`{Path(tags[0]).name}` (another plant or seed setting?): not the same input.")
    return out


def component_table(comp, tags, runs_by_tag):
    header = [f"{comp} on its own (component runs)"] + [Path(t).name for t in tags] + [f"Δ {Path(t).name}" for t in tags[1:]]
    warnings = input_warnings(comp, tags, runs_by_tag)
    lines = warnings + ([""] if warnings else []) + ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for metric, label, direction, kind in COMPONENT_METRICS.get(comp, []):
        stats = [summarize(values(runs_by_tag[t], metric)) for t in tags]
        if all(s is None for s in stats):
            continue
        row = [label] + [fmt_stat(s, kind) for s in stats]
        for s in stats[1:]:
            text, flag = delta(stats[0], s, kind, direction)
            row.append(f"{text} {flag}".strip())
        lines.append("| " + " | ".join(row) + " |")
    models = [", ".join(sorted({str(r.get("model_id")).split("anthropic.")[-1].split("-v1")[0] for r in runs_by_tag[t] if r.get("model_id")}))
              or "–" for t in tags]
    if any(m != "–" for m in models):
        lines.append("| model | " + " | ".join(models) + " |" + " |" * (len(tags) - 1))
    return lines


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


def table(scenario, tags, runs_by_tag, components=None):
    # Each agent on its own, on the scenario's fixed input.
    component_lines = [line for comp in sorted(components or {}) for line in [""] + component_table(comp, tags, components[comp])]
    ns = [len(runs_by_tag[t]) for t in tags]
    if not any(ns):
        return "\n".join([f"### {scenario}", "", "> Component runs only, no full runs under these tags."] + component_lines)
    lines = [f"### {scenario}", ""]
    lines += config_warnings(tags, runs_by_tag)
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

    return "\n".join(lines + component_lines)


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
    comps = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # scenario -> component -> tag -> results
    split = {}
    listed = load_scenarios()
    for t in args.tags:
        if not Path(t).is_dir():
            ap.error(f"no such tag folder: {t}")
        for scenario, s in load_runs(t):
            by_scenario[scenario][t].append(s)
            split.setdefault(scenario, s["_split"])
        for comp, scenario, r in load_component_runs(t):
            comps[scenario][comp][t].append(r)
            by_scenario[scenario][t]   # a scenario with component runs only still gets a section
            split.setdefault(scenario, (listed.get(scenario) or {}).get("split"))

    scenarios = args.scenario or sorted(by_scenario)
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
            parts += [table(sc, args.tags, by_scenario[sc], comps.get(sc)), ""]
    text = "\n".join(parts)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
