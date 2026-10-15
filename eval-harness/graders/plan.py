"""Planner grader: does the plan set up the work the request asks for?

The Planner sees only the request, not the data, so a plan is graded on what
it can know:

  rules (no model call)
    workflow_ok      Coder → Validator → Reporter, and the Auditor after the
                     Reporter when there is one (planner.md's mandatory order)
    auditor_planned  an Auditor step after a Reporter step
    format_ok        the output format the request names (DOCX, PDF) is in the plan
    language_ok      the plan is in the request's language (Korean or not)
  judge (judge.yaml model)
    requirements     each scenario requirement: met (a step will produce it),
                     partial, missing
    data_quality     a step checks the data before analysing it (missing
                     values, duplicates, types, ranges)

A requirement missing from the plan is missing from the report unless an
agent adds it on its own, so plan coverage is an early, cheap signal for the
report's coverage. The plan text comes from a run's events.jsonl or from
planner_eval.py generate, which calls the Planner alone.
"""
import json
import re
from pathlib import Path
from typing import List, Literal

from pydantic import BaseModel, Field

from . import judge

PROMPT_VERSION = "plan-v1"
AGENTS = ("Coder", "Validator", "Reporter", "Auditor", "Tracker")
STEP_RE = re.compile(r"^#{2,4}\s*\d+\.\s*(" + "|".join(AGENTS) + r")\b", re.I | re.M)

SYSTEM = """You grade analysis plans written by a planning agent before any data is read. You see the user's request, a list of requirements taken from it, and the plan. Judge only what the plan says it will do; do not reward wording that restates the request without a step that produces it. Quote the plan for every judgment."""


class RequirementCheck(BaseModel):
    requirement_id: str
    status: Literal["met", "partial", "missing"]
    evidence: str = Field(description="the plan step that covers it, quoted; empty if missing")


class DataQualityCheck(BaseModel):
    present: bool
    evidence: str = Field(description="the plan step that checks the data, quoted; empty if none")


class PlanVerdict(BaseModel):
    requirements: List[RequirementCheck]
    data_quality: DataQualityCheck


def plans_from_events(run_dir):
    """Every plan the Planner wrote in a run, in order (more than one after a revision)."""
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


def _korean(text):
    letters = re.findall(r"[A-Za-z가-힣]", text)
    return bool(letters) and sum("가" <= c <= "힣" for c in letters) / len(letters) > 0.3


def rule_checks(query, plan):
    steps = [m.group(1).capitalize() for m in STEP_RE.finditer(plan)]

    def first(agent):
        return steps.index(agent) if agent in steps else None

    c, v, r, a = (first(x) for x in ("Coder", "Validator", "Reporter", "Auditor"))
    order = [i for i in (c, v, r) if i is not None]
    workflow_ok = (c is None or (v is not None and r is not None)) and order == sorted(order) \
        and (a is None or (r is not None and a > r))
    formats = [f for f in ("DOCX", "PDF") if f.lower() in query.lower()]
    return {
        "plan_steps": steps,
        "plan_workflow_ok": workflow_ok,
        "plan_auditor_planned": a is not None and r is not None and a > r,
        "plan_format_ok": all(f.lower() in plan.lower() for f in formats),
        "plan_language_ok": _korean(query) == _korean(plan),
    }


def version(cfg):
    import hashlib
    import inspect
    src = SYSTEM + inspect.getsource(judge_plan) + json.dumps(PlanVerdict.model_json_schema(), sort_keys=True)
    return "|".join([PROMPT_VERSION, hashlib.sha256(src.encode()).hexdigest()[:10], cfg["model"], f"effort={cfg.get('effort')}"])


def judge_plan(client, cfg, query, requirements, plan):
    prompt = f"""<request>
{query.strip()}
</request>

<requirements>
{judge._requirements_block(requirements)}
</requirements>

<plan>
{plan}
</plan>

For each requirement, decide whether the plan has a step that will produce it: met (a step clearly produces it), partial (a step touches it but leaves part out, e.g. strategies without priorities), missing (no step produces it).
Then decide whether some step checks the data before the analysis (missing values, duplicate rows, data types or value ranges)."""
    verdict, usage = judge._call(client, cfg, prompt, PlanVerdict, system=SYSTEM)
    return verdict, usage


def grade(client, cfg, query, requirements, plan):
    """Scores for one plan: rule checks always, judge checks when a client is given."""
    scores = rule_checks(query, plan)
    record, usage = None, None
    if client is not None:
        verdict, usage = judge_plan(client, cfg, query, requirements, plan)
        expected = {r["id"] for r in requirements}
        status = {x.requirement_id: x.status for x in verdict.requirements if x.requirement_id in expected}
        status.update({rid: "missing" for rid in expected - set(status)})   # an unanswered requirement is not met
        n = len(expected) or 1
        scores.update({
            "plan_requirements_met": sum(s == "met" for s in status.values()) / n,
            "plan_requirements_missing": sorted(k for k, s in status.items() if s == "missing"),
            "plan_requirements_partial": sorted(k for k, s in status.items() if s == "partial"),
            "plan_data_quality": verdict.data_quality.present,
        })
        record = verdict.model_dump()
    return scores, record, usage
