"""Validator component: plant wrong values, see which the Validator catches.

For each source run: pick calculations the recomputation (graders/recompute.py)
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
"""
import json
from pathlib import Path

from graders import recompute
from graders.citations import load_citations

from .common import REPORTER_AND_AUDITOR, copy_before, number as _number

# What the Validator and every agent after it write.
LATER_OUTPUTS = ["citations.json", "validation_report.txt", "code/validator_*", "cache/priority_calcs.pkl",
                 "cache/verified.pkl"] + REPORTER_AND_AUDITOR


def prepare(adir, scenario):
    """Once per source run: its calculations and which ones the raw file confirms."""
    calcs = {c["id"]: c for c in json.loads((Path(adir) / "calculation_metadata.json").read_text(encoding="utf-8"))["calculations"]}
    return {"calcs": calcs, "strict": recompute.grade(adir, scenario["csv"], with_strict=True)[1],
            "csv_name": Path(scenario["csv"]).name}


def plant(ctx, adir, staged, k, rng):
    """Plant up to k errors and stage the artifacts; (record for planted.json, state for evaluate, summary)."""
    calcs = ctx["calcs"]
    ids, kinds = pick_plants(calcs, ctx["strict"], ctx["csv_name"], k, rng)
    plants = {c: {"original": calcs[c]["value"], "planted": planted_value(calcs[c]["value"]),
                  "formula": calcs[c].get("formula"), "source_file": calcs[c].get("source_file")} for c in ids}
    stage(adir, staged, plants)
    n_raw = sum(k == "raw" for k in kinds.values())
    return {"kinds": kinds, "plants": plants}, (plants, kinds), f"planted {len(plants)} ({n_raw} raw, {len(plants) - n_raw} derived)"


def evaluate(adir, ctx, state):
    plants, kinds = state
    return score(adir, plants, kinds, [c for c, ok in ctx["strict"].items() if ok])


def summary(r):
    return (f"caught {r['caught']}/{r['planted']} · missed {r['missed']} · not checked {r['not_checked']} · "
            f"false alarms {r['false_alarm']}/{r['right_checked']}")


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


def planted_value(v):
    """10% off, same type: an integer stays an integer, a decimal keeps 4 places."""
    x = _number(v)
    if x == 0:
        return 1
    if float(x).is_integer() and not isinstance(v, float):
        return int(round(x * 1.1)) if round(x * 1.1) != x else int(x) + 1
    return round(x * 1.1, 4)


def stage(src, dest, plants):
    """Copy the saved artifacts as they were before the Validator, with the planted values."""
    copy_before(src, dest, LATER_OUTPUTS)
    meta_path = dest / "calculation_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    rows = meta["calculations"] if isinstance(meta, dict) else meta
    for row in rows:
        if row.get("id") in plants:
            row["value"] = plants[row["id"]]["planted"]
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


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
