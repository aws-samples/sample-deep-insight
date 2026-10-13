"""Measure the fact checker on reports whose right answers are known.

factcheck.py decides whether a report states the answer-key facts correctly.
Before trusting its numbers in a release decision, run it on the gold cases in
factcheck_cases/: a real report with errors found by hand, the same report
with the errors fixed, small planted errors, statements about another period
or subset (true there, so never wrong), and an instruction to the evaluator.

    python sanity/factcheck_sanity.py                         # all gold files, once
    python sanity/factcheck_sanity.py --repeat 3              # + how stable the verdicts are

Reports per case which labels held, then:
  wrong recall    errors caught / errors expected            (want 100%)
  false wrongs    wrong_confirmed nobody expected             (want 0)
  correct recall  right statements recognised / expected
  stability       labels with the same outcome in every repeat
Exit 1 when wrong recall < --min-wrong-recall, false wrongs > --max-false-wrongs,
or a run errored (it is recorded and the other cases still run).

Paid: about 2 model calls per case and repeat (see judge.yaml). Re-run when the
prompts (factcheck.PROMPT_VERSION), the judge model or an answer key change.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from graders import factcheck  # noqa: E402
from graders import judge  # noqa: E402

CASES = HERE / "factcheck_cases"


def build_cases(spec_path):
    """{case name: (paragraphs, expect labels)} from a gold file; every edit must apply."""
    spec_path = Path(spec_path)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    report = (spec_path.parent / spec["report"]).read_text(encoding="utf-8").splitlines()
    built = {}

    def build(name):
        if name in built:
            return built[name]
        case = spec["cases"][name]
        paragraphs = list(build(case["base"])[0]) if case.get("base") else list(report)
        text = "\n".join(paragraphs)
        for old, new in case.get("replace", []):
            if old not in text:
                raise ValueError(f"{spec_path.name}/{name}: replace text not in the report: {old!r}")
            text = text.replace(old, new)
        paragraphs = text.split("\n")
        for heading, extra in (case.get("insert_after") or {}).items():
            if heading not in paragraphs:
                raise ValueError(f"{spec_path.name}/{name}: no paragraph {heading!r} to insert after")
            paragraphs.insert(paragraphs.index(heading) + 1, extra)
        paragraphs += case.get("append", [])
        expect = case["expect"]
        if isinstance(expect, str):  # same labels as another case
            expect = spec["cases"][expect]["expect"]
        built[name] = (paragraphs, expect)
        return built[name]

    for name in spec["cases"]:
        build(name)
    key = json.loads((spec_path.parent / spec["answer_key"]).read_text(encoding="utf-8"))
    return key, built


def _matches(record, label):
    if record["fact_id"] != label["fact"]:
        return False
    subject = label.get("subject")
    return subject is None or (record["statement"]["subject"] or "").strip().lower() == subject.lower()


def score_case(records, expect):
    """[(label, held, what happened)] and the wrong_confirmed records no label expects."""
    out = []
    for label in expect:
        mine = [r for r in records if _matches(r, label)]
        wrong = [r for r in mine if r["status"] == "wrong_confirmed"]
        correct = [r for r in mine if r["status"] == "correct"]
        if label["is"] == "wrong":
            held = bool(wrong)
        elif label["is"] == "correct":
            held = bool(correct) and not wrong
        else:  # not_wrong
            held = not wrong
        if label.get("unit_issue"):
            held = held and any(r["unit_issue"] for r in mine)
        seen = sorted({r["status"] for r in mine}) or ["not found"]
        out.append((label, held, ", ".join(seen)))
    expected_wrong = [l for l in expect if l["is"] == "wrong"]
    false_wrongs = [r for r in records if r["status"] == "wrong_confirmed" and not any(_matches(r, l) for l in expected_wrong)]
    return out, false_wrongs


def _label(label):
    return f"{label['fact']}{' ' + label['subject'] if label.get('subject') else ''} is {label['is']}{' (+%p)' if label.get('unit_issue') else ''}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gold", nargs="*", help="gold files (default: factcheck_cases/*.yaml)")
    ap.add_argument("--case", action="append", help="only these cases")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--min-wrong-recall", type=float, default=1.0)
    ap.add_argument("--max-false-wrongs", type=int, default=0)
    args = ap.parse_args()

    cfg = judge.load_config()
    judge.check_available(cfg)
    client = judge.make_client(cfg)
    files = [Path(g) for g in args.gold] or sorted(CASES.glob("*.yaml"))
    outcomes = defaultdict(list)  # (file, case, label index) -> [held, ...]
    totals = defaultdict(int)
    usages, saved = [], []
    for path in files:
        key, cases = build_cases(path)
        for name, (paragraphs, expect) in cases.items():
            if args.case and name not in args.case:
                continue
            for i in range(args.repeat):
                print(f"{path.stem}/{name} run {i + 1}/{args.repeat}", flush=True)
                try:
                    metrics, records, u = factcheck.check(client, cfg, key, paragraphs)
                except Exception as e:  # recorded and counted; the other cases still run
                    totals["errors"] += 1
                    saved.append({"file": path.name, "case": name, "repeat": i, "error": f"{type(e).__name__}: {e}"[:500]})
                    print(f"  ERROR  {type(e).__name__}: {str(e)[:200]}")
                    continue
                usages += u
                results, false_wrongs = score_case(records, expect)
                saved.append({"file": path.name, "case": name, "repeat": i, "metrics": metrics, "records": records,
                              "labels": [{"label": l, "held": h, "seen": s} for l, h, s in results]})
                for j, (label, held, seen) in enumerate(results):
                    outcomes[(path.stem, name, j)].append(held)
                    kind = label["is"]
                    totals[f"{kind}_total"] += 1
                    totals[f"{kind}_held"] += held
                    if not held:
                        print(f"  MISS  {_label(label)}  (saw: {seen})")
                totals["false_wrongs"] += len(false_wrongs)
                for r in false_wrongs:
                    st = r["statement"]
                    print(f"  FALSE WRONG  {r['fact_id']} {st['subject']} stated {st['stated']!r}: \"{st['quote'][:100]}\" "
                          f"({(r['adjudication'] or {}).get('reason', '')[:160]})")
                print(f"  {sum(h for _, h, _ in results)}/{len(results)} labels held · {len(false_wrongs)} false wrongs · "
                      f"{metrics['factcheck_needs_review']} needs review · {metrics['factcheck_unverified_quotes']} unverified quotes")

    def rate(kind):
        n = totals[f"{kind}_total"]
        return totals[f"{kind}_held"] / n if n else None

    stable = sum(len(set(v)) == 1 and len(v) == args.repeat for v in outcomes.values())
    cost = judge.judge_cost(usages)
    print(f"\nfact checker {factcheck.PROMPT_VERSION} · {cfg['model']} (effort {cfg.get('effort')})")
    for kind in ("wrong", "correct", "not_wrong"):
        r = rate(kind)
        print(f"  {kind:10s} recall  {'–' if r is None else f'{r:.0%}'}  ({totals[f'{kind}_held']}/{totals[f'{kind}_total']})")
    print(f"  false wrongs      {totals['false_wrongs']}")
    print(f"  errors            {totals['errors']}")
    if args.repeat > 1:
        print(f"  stability         {stable}/{len(outcomes)} labels same in all {args.repeat} repeats")
    print(f"  cost              {'$%.2f' % cost if cost is not None else 'unpriced'}")

    out = ROOT / "eval_results" / "factcheck_sanity" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"version": factcheck.PROMPT_VERSION, "model": cfg["model"], "effort": cfg.get("effort"),
                               "totals": dict(totals), "stable_labels": stable, "labels": len(outcomes), "cost_usd": cost,
                               "runs": saved}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"→ {out}")
    ok = (rate("wrong") or 0) >= args.min_wrong_recall and totals["false_wrongs"] <= args.max_false_wrongs and not totals["errors"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
