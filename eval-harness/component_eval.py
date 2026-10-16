"""Measure one agent on its own: a saved run's artifacts as the fixed input, errors planted as the known answer.

A full run grades only the final report, so it can't say which agent a worse
score came from, and each agent's input differs from run to run. Here the
agent runs alone (nothing before it is re-run) on an input whose right answer
is known, so two versions of it are compared on the same input.

    python component_eval.py validator --from eval_results/baseline/<run> [--from ...] \\
        --plant 6 --repeat 2 --tag comp-validator
    python component_eval.py reporter --from eval_results/baseline/<run> --plant 4 --tag comp-reporter

Validator. For each source run: pick calculations the recomputation (graders/recompute.py)
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

Reporter. needs_review values must not reach the report: no value, marker or
reference (reporter.md, value_status_resolution). Pick verified
values the saved report cites, mark them needs_review in citations.json, stage
the artifacts as they were when the Reporter started, and invoke the eval
runtime with `component: reporter`. Each marked value is then, in the new report:

  cited     a body [n] points to it
  quoted    printed without its marker (body, table or references)
  left out  not in the report: what the prompt asks for

Only values far (>1%) from every other citation's value are marked, so a
number in the report can't be another citation's. The new report is also
graded by the rule graders of a full run (graders/report.py, citations.py).

    eval_results/<tag>/component/<component>/<scenario>-<time>-<n>/
      planted.json   what was changed: calculations and values, or citations marked
      events.jsonl, run.json, s3/, artifacts/   as run_eval.py writes them
      result.json    the counts above

Needs the eval runtime with EVAL_COMPONENT_MODE=1 (eval_runtime.py
enable-components) and an image that has component runs. Paid: one agent run
per repeat.
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
from graders import citations, recompute, report  # noqa: E402
from graders.citations import load_citations  # noqa: E402
from graders.numbers import NUMBER_RE  # noqa: E402
from graders.report import MARKER_RE, read_docx, split_body  # noqa: E402

# What each component and every agent after it write: removed before staging,
# so the component starts where it would in a full run.
_REPORTER_ON = ["final_report*", "report*.docx", "audit_*", "code/reporter_*", "code/svg_docx.py", "code/audit_*", "cache/audit_*"]
LATER_OUTPUTS = {
    "validator": ["citations.json", "validation_report.txt", "code/validator_*", "cache/priority_calcs.pkl", "cache/verified.pkl"]
                 + _REPORTER_ON,
    "reporter": _REPORTER_ON,
}
REPORT = "final_report_with_citations.docx"


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


def _copy_before(src, dest, component):
    shutil.copytree(src, dest, symlinks=False)
    for pattern in LATER_OUTPUTS[component]:
        for p in dest.glob(pattern):
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def stage(src, dest, plants):
    """Copy the saved artifacts as they were before the Validator, with the planted values."""
    _copy_before(src, dest, "validator")
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


def _forms(x):
    """How a stored value may be printed: as is, and a ratio as a percentage."""
    return (x, x * 100) if 0 < abs(x) <= 1 else (x,)


def cited_in_report(adir):
    """calculation id -> citation, for every citation the saved report's body cites with a marker."""
    cites = load_citations(adir) or {}
    if not (Path(adir) / REPORT).is_file():
        return {}
    body, _ = split_body(read_docx(Path(adir) / REPORT))
    used = {int(n) for n in MARKER_RE.findall("\n".join(body))}
    return {cites[n].get("calculation_id"): cites[n] for n in sorted(used) if n in cites}


def pick_reporter_plants(adir, k, rng):
    """Up to k verified values the saved report cites, each >1% from every other citation's value.

    Integers under 100 are left alone: they show up in a report for other
    reasons, so finding one says nothing about the citation.
    """
    others = [(c.get("calculation_id"), _number(c.get("value"))) for c in (load_citations(adir) or {}).values()]
    cited, pool = cited_in_report(adir), []
    for cid, c in cited.items():
        v = _number(c.get("value"))
        if v is None or v == 0 or (float(v).is_integer() and abs(v) < 100):
            continue
        if str(c.get("verification_status", "verified")).lower() != "verified":
            continue
        if any(o != cid and w is not None and any(abs(a - b) <= 0.01 * abs(a) for a in _forms(v) for b in _forms(w))
               for o, w in others):
            continue
        pool.append(cid)
    rng.shuffle(pool)
    return {cid: _number(cited[cid]["value"]) for cid in pool[:k]}


def stage_reporter(src, dest, plants):
    """Copy the saved artifacts as they were before the Reporter, with the chosen citations marked needs_review."""
    _copy_before(src, dest, "reporter")
    path = dest / "citations.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for c in data["citations"]:
        if c.get("calculation_id") in plants:
            c["verification_status"] = "needs_review"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# Rule-grader metrics kept for a Reporter component run (the rest belong to a full run).
REPORTER_GRADES = ["cited_value_checked", "cited_value_match_rate", "broken_citation_refs", "citation_inside_number",
                   "citation_coverage", "body_citations_used", "citation_value_match_rate", "citations_ok"]


_SCALE = {"천": 1e3, "만": 1e4, "억": 1e8, "K": 1e3, "M": 1e6, "B": 1e9}


def printed_values(paragraphs):
    """(value, half a unit of its last digit) of every number printed with at least 3 significant digits.

    A stored value is in the report only if it rounds to a printed number at
    the precision it was printed with: 6,879.45 is not "$6,891", though the
    full-run graders' 0.5% tolerance would take it. Fewer than 3 significant
    digits identify nothing (3.69 rounds to a printed "3.7" or "4"). Markers
    are blanked first so "[12]" is not read as 12.
    """
    text = MARKER_RE.sub(lambda m: " " * len(m.group(0)), "\n".join(paragraphs))
    out = []
    for m in NUMBER_RE.finditer(text):
        sign, whole, frac, suffix = m.groups()
        digits = (whole.replace(",", "") + (frac or "")[1:]).lstrip("0")
        if len(digits) < 3:
            continue
        scale = _SCALE.get(suffix, 1)
        value = float(whole.replace(",", "") + (frac or "")) * scale * (-1 if sign in ("-", "−") else 1)
        out.append((value, 0.5 * 10 ** -(len(frac) - 1 if frac else 0) * scale))
    return out


def score_reporter(adir, plants):
    """Counts from the Reporter's report; plants: calculation id -> the value marked needs_review."""
    adir = Path(adir)
    out = {"planted": len(plants), "cited": 0, "quoted": 0, "left_out": 0, "per_calc": {}}
    if not (adir / REPORT).is_file():
        return {**out, "report_ok": False}
    paragraphs = read_docx(adir / REPORT)
    body, _ = split_body(paragraphs)
    cites = load_citations(adir) or {}
    marked = {cites[int(n)].get("calculation_id") for n in MARKER_RE.findall("\n".join(body)) if int(n) in cites}
    nums = printed_values(paragraphs)   # body, tables and references
    for cid, v in plants.items():
        outcome = ("cited" if cid in marked
                   else "quoted" if any(abs(f - p) <= half + 1e-9 for p, half in nums for f in _forms(v))
                   else "left_out")
        out[outcome] += 1
        out["per_calc"][cid] = {"value": v, "outcome": outcome}
    out["report_ok"] = True
    out["leaked"] = out["cited"] + out["quoted"]
    out["leak_rate"] = out["leaked"] / len(plants) if plants else None
    graded = {}
    for fn in (report.grade, citations.grade):
        r = fn(adir)
        graded.update({k: r[k] for k in REPORTER_GRADES if k in r})
    out["graders"] = graded
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


def table_reporter(results):
    lines = ["| source run | marked needs_review | cited | quoted | left out | printed value = citation | broken [n] | [n] inside a number | values cited |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, r in results:
        g = r.get("graders", {})
        rate = "–" if g.get("cited_value_match_rate") is None else f"{g['cited_value_match_rate']:.0%} ({g['cited_value_checked']})"
        lines.append(f"| {name} | {r['planted']} | {r['cited']} | {r['quoted']} | {r['left_out']} | {rate} | "
                     f"{g.get('broken_citation_refs', '–')} | {g.get('citation_inside_number', '–')} | {g.get('body_citations_used', '–')} |")
    return "\n".join(lines)


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
    ap.add_argument("component", choices=list(LATER_OUTPUTS))
    ap.add_argument("--from", dest="sources", action="append", required=True, help="saved run folder (repeatable)")
    ap.add_argument("--plant", type=int, default=6, help="errors to plant (validator) or citations to mark needs_review (reporter) per run")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--allow-test", action="store_true", help="allow source runs of test-split scenarios")
    ap.add_argument("--runtime-arn", default=env.get("EVAL_RUNTIME_ARN"))
    ap.add_argument("--region", default=env.get("EVAL_REGION") or env.get("AWS_REGION") or "us-west-2")
    ap.add_argument("--bucket", default=None)
    ap.add_argument("--timeout", type=int, default=3600)
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
        strict = recompute.grade(adir, sc["csv"], with_strict=True)[1] if args.component == "validator" else {}
        plans = plans_from_events(src)
        if not plans:
            ap.error(f"{src}: no plan in events.jsonl")
        for i in range(1, args.repeat + 1):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_dir = HERE / "eval_results" / args.tag / "component" / args.component / f"{name}-{stamp}-{i}"
            run_dir.mkdir(parents=True)
            staged = run_dir / "staged_artifacts"
            if args.component == "validator":
                ids, kinds = pick_plants(calcs, strict, Path(sc["csv"]).name, args.plant, rng)
                plants = {c: {"original": calcs[c]["value"], "planted": planted_value(calcs[c]["value"]),
                              "formula": calcs[c].get("formula"), "source_file": calcs[c].get("source_file")} for c in ids}
                planted = {"source_run": str(src), "kinds": kinds, "plants": plants}
                stage(adir, staged, plants)
                summary = f"planted {len(plants)} ({sum(k == 'raw' for k in kinds.values())} raw, {sum(k == 'derived' for k in kinds.values())} derived)"
            else:
                plants = pick_reporter_plants(adir, args.plant, rng)
                if not plants:
                    ap.error(f"{src}: no cited verified value far enough from the others to mark")
                planted = {"source_run": str(src), "marked_needs_review": plants}
                stage_reporter(adir, staged, plants)
                summary = f"marked {len(plants)} cited values needs_review"
            (run_dir / "planted.json").write_text(json.dumps(planted, indent=2, ensure_ascii=False), encoding="utf-8")
            prefix = f"uploads/eval-component-{args.component}-{name.replace('_', '-')}-{stamp}-{i}/"
            payload = {"prompt": sc["query"].strip(), "component": args.component, "full_plan": plans[-1],
                       "data_directory": upload(s3, args.bucket, prefix + "data/", sc["upload"]),
                       "artifacts_directory": upload(s3, args.bucket, prefix + "artifacts/", staged)}
            print(f"{name} ← {src.name} run {i}: {summary} → {run_dir.relative_to(HERE)}", flush=True)
            meta, usage = invoke(args, payload, run_dir, (agentcore, s3))
            if meta["status"] != "completed":
                failures += 1
                print(f"  {meta['status']} {meta.get('error', '')}", flush=True)
                continue
            if args.component == "validator":
                r = score(artifacts_dir(run_dir), plants, kinds, [c for c, ok in strict.items() if ok])
                line = (f"caught {r['caught']}/{r['planted']} · missed {r['missed']} · not checked {r['not_checked']} · "
                        f"false alarms {r['false_alarm']}/{r['right_checked']}")
            else:
                r = score_reporter(artifacts_dir(run_dir), plants)
                line = (f"left out {r['left_out']}/{r['planted']} · cited {r['cited']} · quoted {r['quoted']}"
                        if r["report_ok"] else "no report written")
            c = cost.compute({"by_agent": usage})
            r["cost_usd"] = c["cost_usd"] if c["cost_complete"] else None
            (run_dir / "result.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append((f"{src.name} #{i}", r))
            print(f"  {line} · {meta['duration_s']:.0f}s" + (f" · ${r['cost_usd']:.2f}" if r.get("cost_usd") is not None else ""), flush=True)
    if results:
        print(table(results) if args.component == "validator" else table_reporter(results))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
