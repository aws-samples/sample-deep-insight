"""Pairwise LLM judge: candidate tag vs a frozen baseline tag.

    python pairwise.py eval_results/baseline eval_results/opus55 [--scenario jungle_market] [--pairs matched|all]
    python pairwise.py eval_results/baseline eval_results/baseline     # noise check, expect ~50%

Each candidate run's report is compared with a baseline run's report from the
same scenario, twice with the order swapped (judge.py). Baseline reports are
read from disk as they are: never regenerated, so "win rate vs baseline" keeps
its meaning across rounds.

  matched  candidate run i vs baseline run i (mod n)  — one pair per candidate run
  all      every candidate run vs every baseline run  — more pairs, more cost

Comparing a tag with itself pairs run i with run i+1, so the result shows the
judge's noise floor: anything far from 50% means the judge, not the code, is
moving the number.

Each pair is cached under <candidate run>/pairwise/<baseline run>.json (keyed by
both report hashes and the judge model), and the summary is written to
<candidate tag>/pairwise_vs_<baseline tag>.json, which compare.py picks up.
"""
import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import judge  # noqa: E402
from grade import artifacts_dir, load_scenario  # noqa: E402


def runs_by_scenario(tag_dir):
    out = defaultdict(list)
    for run in sorted(Path(tag_dir).glob("*/run.json")):
        meta = json.loads(run.read_text(encoding="utf-8"))
        out[meta["scenario"]].append(run.parent)
    return out


def _text(run_dir, cfg):
    adir = artifacts_dir(run_dir)
    if not (adir / "final_report_with_citations.docx").is_file():
        return None
    return judge.report_text(adir, cfg["max_report_chars"])


def make_pairs(cands, bases, mode, same_tag):
    if same_tag:
        return [(r, cands[(i + 1) % len(cands)]) for i, r in enumerate(cands)] if len(cands) > 1 else []
    if mode == "all":
        return [(c, b) for c in cands for b in bases]
    return [(c, bases[i % len(bases)]) for i, c in enumerate(cands)]


def judge_pair(client, cfg, scenario, cand_dir, base_dir, rng):
    cand_text, base_text = _text(cand_dir, cfg), _text(base_dir, cfg)
    if base_text is None:
        return None  # nothing to compare against; not the candidate's fault
    if cand_text is None:
        return {"overall": "baseline", "position_consistent": True, "criteria": {k: "baseline" for k in judge.CRITERIA},
                "note": "candidate produced no report", "cost_usd": 0.0}
    ver = judge.version(cfg, scenario["query"], scenario["requirements"])
    key = hashlib.sha256((cand_text + "\0" + base_text + "\0" + ver).encode()).hexdigest()
    cache = cand_dir / "pairwise" / f"{base_dir.parent.name}__{base_dir.name}.json"
    if cache.is_file():
        prev = json.loads(cache.read_text(encoding="utf-8"))
        if prev.get("key") == key:
            return prev["result"]
    result, rounds, usages = judge.pairwise(client, cfg, scenario["query"], scenario["requirements"], cand_text, base_text, rng)
    result["cost_usd"] = judge.judge_cost(usages)
    cache.parent.mkdir(exist_ok=True)
    result["judge_version"] = ver
    cache.write_text(json.dumps({"key": key, "model": cfg["model"], "judge_version": ver, "baseline_run": str(base_dir), "result": result,
                                 "rounds": rounds, "usage": usages}, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def summarize(results):
    results = [r for r in results if r is not None]
    n = len(results)
    if not n:
        return {"pairs": 0}
    count = lambda side: sum(r["overall"] == side for r in results)
    costs = [r.get("cost_usd") for r in results]
    return {
        "pairs": n,
        "win_rate": sum(judge.win_score(r["overall"]) for r in results) / n,
        "wins": count("candidate"), "ties": count("tie"), "losses": count("baseline"), "both_bad": count("both_bad"),
        "position_consistency": sum(r["position_consistent"] for r in results) / n,
        "criteria_win_rate": {k: sum(judge.win_score(r["criteria"][k]) for r in results) / n for k in judge.CRITERIA},
        "judge_cost_usd": round(sum(c for c in costs if c), 4) if all(c is not None for c in costs) else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--scenario", action="append")
    ap.add_argument("--pairs", choices=["matched", "all"], default="matched")
    ap.add_argument("--seed", type=int, default=0, help="seeds which order each pair is judged in first")
    args = ap.parse_args()

    cfg = judge.load_config()
    judge.check_available(cfg)
    client = judge.make_client(cfg)
    rng = random.Random(args.seed)
    base_dir, cand_dir = Path(args.baseline).resolve(), Path(args.candidate).resolve()
    same_tag = base_dir == cand_dir
    bases, cands = runs_by_scenario(base_dir), runs_by_scenario(cand_dir)

    summary = {"baseline": base_dir.name, "candidate": cand_dir.name, "judge_model": cfg["model"], "pairs_mode": args.pairs, "scenarios": {}}
    for name in args.scenario or sorted(set(bases) & set(cands)):
        scenario = load_scenario(name)
        pairs = make_pairs(cands.get(name, []), bases.get(name, []), args.pairs, same_tag)
        results = []
        for c, b in pairs:
            print(f"[{name}] {c.name} vs {b.name}", flush=True)
            results.append(judge_pair(client, cfg, scenario, c, b, rng))
        summary["scenarios"][name] = summarize(results)

    out = cand_dir / f"pairwise_vs_{base_dir.name}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(table(summary))
    print(f"\n→ {out}")


def table(summary):
    lines = [f"### Pairwise: {summary['candidate']} vs {summary['baseline']} (judge {summary['judge_model']})", "",
             "| scenario | pairs | win rate | W / T / L / both bad | position-consistent | judge cost |", "|---|---|---|---|---|---|"]
    for name, s in summary["scenarios"].items():
        if not s.get("pairs"):
            lines.append(f"| {name} | 0 | – | – | – | – |")
            continue
        cost = f"${s['judge_cost_usd']:.2f}" if s["judge_cost_usd"] is not None else "unpriced"
        lines.append(f"| {name} | {s['pairs']} | {s['win_rate'] * 100:.0f}% | {s['wins']} / {s['ties']} / {s['losses']} / {s['both_bad']} "
                     f"| {s['position_consistency'] * 100:.0f}% | {cost} |")
    crit = [(n, s) for n, s in summary["scenarios"].items() if s.get("pairs")]
    if crit:
        lines += ["", "| scenario | " + " | ".join(judge.CRITERIA) + " |", "|" + "---|" * (len(judge.CRITERIA) + 1)]
        for n, s in crit:
            lines.append(f"| {n} | " + " | ".join(f"{s['criteria_win_rate'][k] * 100:.0f}%" for k in judge.CRITERIA) + " |")
    lines += ["", "win rate = (wins + 0.5 × ties and both-bad) / pairs, candidate's view. 50% = no difference."]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
