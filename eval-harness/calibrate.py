"""Calibrate the LLM judge against human labels.

A judge is only worth trusting once it agrees with people on a sample. Label
10-20 reports by hand once, then re-check agreement whenever the rubric, the
judge model or its settings change.

    # 1. write a blank label sheet (no judge scores in it, so labels stay blind)
    python calibrate.py export eval_results/baseline [more tags] --out calibration/pointwise.csv
    python calibrate.py export-pairs eval_results/baseline eval_results/opus55 --out calibration/pairwise.csv
    # 2. open each report_docx, fill the blank columns
    # 3. compare with the judge (runs grade.py --judge / pairwise.py results already on disk)
    python calibrate.py score calibration/pointwise.csv
    python calibrate.py score-pairs calibration/pairwise.csv
    # or label in the Langfuse UI (langfuse_sync.py --queue), then
    python calibrate.py langfuse

Pointwise columns: req:<id> = met / partial / missing, score:<criterion> = 1-5.
Pairwise column: human_overall = candidate / baseline / tie / both_bad.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from graders import judge  # noqa: E402
from grade import artifacts_dir, load_scenario  # noqa: E402
from pairwise import make_pairs, runs_by_scenario  # noqa: E402


def export(tags, out):
    rows, req_ids = [], []
    for tag in tags:
        for name, runs in sorted(runs_by_scenario(tag).items()):
            for r in load_scenario(name)["requirements"]:
                if r["id"] not in req_ids:
                    req_ids.append(r["id"])
            for run in runs:
                rows.append({"run_dir": str(run), "scenario": name, "report_docx": str(artifacts_dir(run) / "final_report_with_citations.docx")})
    cols = ["run_dir", "scenario", "report_docx"] + [f"req:{i}" for i in req_ids] + [f"score:{k}" for k in judge.CRITERIA] + ["labeler", "notes"]
    _write(out, cols, rows)
    print(f"{len(rows)} reports → {out}. Leave req:<id> blank where the scenario doesn't have that requirement.")


def export_pairs(base, cand, out):
    rows = []
    bases, cands = runs_by_scenario(base), runs_by_scenario(cand)
    same = Path(base).resolve() == Path(cand).resolve()
    for name in sorted(set(bases) & set(cands)):
        for c, b in make_pairs(cands[name], bases[name], "matched", same):
            rows.append({"scenario": name, "candidate_run": str(c), "baseline_run": str(b),
                         "candidate_docx": str(artifacts_dir(c) / "final_report_with_citations.docx"),
                         "baseline_docx": str(artifacts_dir(b) / "final_report_with_citations.docx")})
    _write(out, ["scenario", "candidate_run", "baseline_run", "candidate_docx", "baseline_docx", "human_overall", "labeler", "notes"], rows)
    print(f"{len(rows)} pairs → {out}")


def _write(out, cols, rows):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _spearman(xs, ys):
    """Rank correlation with average ranks for ties; None when undefined."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def _judge_verdict(run_dir):
    jpath = Path(run_dir) / "judge.json"
    if not jpath.is_file():
        return None
    v = json.loads(jpath.read_text(encoding="utf-8"))["verdict"]
    return {r["requirement_id"]: r["status"] for r in v["requirements"]}, {c["criterion"]: c["score"] for c in v["criteria"]}


def report_agreement(human, n_rows, missing_judge):
    """human: list of (judge_req, judge_crit, human_req, human_crit) per labeled report."""
    req_agree = req_total = 0
    crit = {k: ([], []) for k in judge.CRITERIA}
    for j_req, j_crit, h_req, h_crit in human:
        for rid, status in h_req.items():
            req_total += 1
            req_agree += j_req.get(rid, "missing") == status
        for k, v in h_crit.items():
            if k in j_crit:
                crit[k][0].append(float(v))
                crit[k][1].append(float(j_crit[k]))
    print(f"labels: {n_rows} reports ({missing_judge} without a judge verdict; run grade.py --judge on them)")
    print(f"requirement status agreement: {req_agree}/{req_total}" + (f" = {req_agree / req_total:.0%}" if req_total else ""))
    print("| criterion | n | exact | within ±1 | spearman | judge − human |\n|---|---|---|---|---|---|")
    for k, (h, j) in crit.items():
        if not h:
            print(f"| {k} | 0 | – | – | – | – |")
            continue
        n = len(h)
        exact = sum(a == b for a, b in zip(h, j)) / n
        near = sum(abs(a - b) <= 1 for a, b in zip(h, j)) / n
        rho = _spearman(h, j)
        bias = sum(b - a for a, b in zip(h, j)) / n
        print(f"| {k} | {n} | {exact:.0%} | {near:.0%} | {'–' if rho is None else f'{rho:.2f}'} | {bias:+.2f} |")


def score(labels):
    rows = list(csv.DictReader(open(labels, encoding="utf-8")))
    human, missing = [], 0
    for row in rows:
        verdict = _judge_verdict(row["run_dir"])
        if verdict is None:
            missing += 1
            continue
        h_req = {c[4:]: v.strip().lower() for c, v in row.items() if c.startswith("req:") and v.strip()}
        h_crit = {c[6:]: v for c, v in row.items() if c.startswith("score:") and v.strip()}
        human.append((*verdict, h_req, h_crit))
    report_agreement(human, len(rows), missing)


def score_langfuse(lf=None):
    """Compare labels people entered in the Langfuse annotation queue with the judge."""
    import langfuse_sync
    lf = lf or langfuse_sync.Langfuse(*langfuse_sync.credentials())
    manifest = json.loads((HERE / "eval_results" / "langfuse_sync.json").read_text(encoding="utf-8"))
    human, missing, labeled = [], 0, 0
    for trace_id, entry in manifest.items():
        rows = list(lf.pages("/api/public/v2/scores", traceId=trace_id, source="ANNOTATION"))
        if not rows:
            continue
        labeled += 1
        verdict = _judge_verdict(HERE / entry["run_dir"])
        if verdict is None:
            missing += 1
            continue
        h_req = {r["name"][4:]: str(r.get("stringValue") or r.get("value")).lower() for r in rows if r["name"].startswith("req.")}
        h_crit = {r["name"]: r["value"] for r in rows if r["name"] in judge.CRITERIA}
        human.append((*verdict, h_req, h_crit))
    report_agreement(human, labeled, missing)


def score_pairs(labels):
    rows = [r for r in csv.DictReader(open(labels, encoding="utf-8")) if r.get("human_overall", "").strip()]
    agree = n = 0
    for row in rows:
        b = Path(row["baseline_run"])
        f = Path(row["candidate_run"]) / "pairwise" / f"{b.parent.name}__{b.name}.json"
        if not f.is_file():
            continue
        n += 1
        agree += json.loads(f.read_text(encoding="utf-8"))["result"]["overall"] == row["human_overall"].strip().lower()
    print(f"pairwise agreement with humans: {agree}/{n}" + (f" = {agree / n:.0%}" if n else " (no judged pairs; run pairwise.py first)"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export"); e.add_argument("tags", nargs="+"); e.add_argument("--out", required=True)
    ep = sub.add_parser("export-pairs"); ep.add_argument("baseline"); ep.add_argument("candidate"); ep.add_argument("--out", required=True)
    s = sub.add_parser("score"); s.add_argument("labels")
    sp = sub.add_parser("score-pairs"); sp.add_argument("labels")
    sub.add_parser("langfuse", help="compare human labels from the Langfuse annotation queue with the judge")
    a = ap.parse_args()
    if a.cmd == "export":
        export(a.tags, a.out)
    elif a.cmd == "export-pairs":
        export_pairs(a.baseline, a.candidate, a.out)
    elif a.cmd == "score":
        score(a.labels)
    elif a.cmd == "langfuse":
        score_langfuse()
    else:
        score_pairs(a.labels)


if __name__ == "__main__":
    main()
