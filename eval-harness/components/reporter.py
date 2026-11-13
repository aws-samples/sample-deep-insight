"""Reporter component: mark cited values needs_review, see whether the Reporter keeps them out.

needs_review values must not reach the report: no value, marker or
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
"""
import json
from pathlib import Path

from graders import citations, report
from graders.citations import load_citations
from graders.numbers import NUMBER_RE
from graders.report import MARKER_RE, read_docx, split_body

from .common import REPORTER_AND_AUDITOR, NothingToPlant, copy_before, number as _number

# What the Reporter and every agent after it write.
LATER_OUTPUTS = REPORTER_AND_AUDITOR
REPORT = "final_report_with_citations.docx"


def prepare(adir, scenario):
    return {}


def plant(ctx, adir, staged, k, rng):
    """Mark up to k cited values needs_review and stage the artifacts; (record for planted.json, state for evaluate, summary)."""
    plants = pick_reporter_plants(adir, k, rng)
    if not plants:
        raise NothingToPlant("no cited verified value far enough from the others to mark")
    stage_reporter(adir, staged, plants)
    return {"marked_needs_review": plants}, plants, f"marked {len(plants)} cited values needs_review"


def evaluate(adir, ctx, plants):
    return score_reporter(adir, plants)


def summary(r):
    if not r["report_ok"]:
        return "no report written"
    return f"left out {r['left_out']}/{r['planted']} · cited {r['cited']} · quoted {r['quoted']}"


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
    copy_before(src, dest, LATER_OUTPUTS)
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


def table(results):
    lines = ["| source run | marked needs_review | cited | quoted | left out | printed value = citation | broken [n] | [n] inside a number | values cited |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, r in results:
        g = r.get("graders", {})
        rate = "–" if g.get("cited_value_match_rate") is None else f"{g['cited_value_match_rate']:.0%} ({g['cited_value_checked']})"
        lines.append(f"| {name} | {r['planted']} | {r['cited']} | {r['quoted']} | {r['left_out']} | {rate} | "
                     f"{g.get('broken_citation_refs', '–')} | {g.get('citation_inside_number', '–')} | {g.get('body_citations_used', '–')} |")
    return "\n".join(lines)
