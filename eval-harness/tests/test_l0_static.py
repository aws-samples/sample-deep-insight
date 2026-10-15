"""L0: static checks on the runtime code. No LLM calls, no AWS calls.

Imports managed-agentcore/src directly (see conftest.py), so these run in
seconds on every commit.
"""
import os
import re
import string
from pathlib import Path

import pytest
import yaml

from graders import cost

AGENTCORE = Path(__file__).resolve().parents[2] / "managed-agentcore"
PROMPTS = AGENTCORE / "src" / "prompts"

# Context keys each prompt receives at its call site (src/graph/nodes.py,
# src/tools/*_tool.py). A placeholder outside this set raises KeyError at
# runtime, mid-workflow.
CALL_SITE_KEYS = {
    "coordinator": set(),
    "planner": {"USER_REQUEST"},
    "planner_revise": {"USER_REQUEST", "PREVIOUS_PLAN", "USER_FEEDBACK", "REVISION_COUNT", "MAX_REVISIONS"},
    "supervisor": {"FULL_PLAN"},
    "coder": {"USER_REQUEST", "FULL_PLAN"},
    "validator": {"USER_REQUEST", "FULL_PLAN", "EXECUTION_ENVIRONMENT"},
    "reporter": {"USER_REQUEST", "FULL_PLAN", "EXECUTION_ENVIRONMENT"},
    "auditor": {"USER_REQUEST", "FULL_PLAN", "EXECUTION_ENVIRONMENT"},
    "tracker": {"USER_REQUEST", "FULL_PLAN"},
    "summarization": set(),
}


@pytest.mark.parametrize("name", sorted(CALL_SITE_KEYS))
def test_prompt_placeholders_match_call_site(name):
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    fields = {f for _, f, _, _ in string.Formatter().parse(text) if f}
    unknown = fields - CALL_SITE_KEYS[name] - {"CURRENT_TIME"}
    assert not unknown, f"{name}.md uses placeholders its call site does not pass: {sorted(unknown)}"


@pytest.mark.parametrize("name", sorted(CALL_SITE_KEYS))
def test_prompt_renders(name):
    from src.prompts.template import apply_prompt_template
    ctx = {k: f"<{k}>" for k in CALL_SITE_KEYS[name]}
    rendered = apply_prompt_template(prompt_name=name, prompt_context=ctx)
    assert len(rendered) > 100


# --- model request fields ----------------------------------------------------

MODELS = [
    "global.anthropic.claude-opus-5-5",
    "global.anthropic.claude-sonnet-5-5",
    "global.anthropic.claude-opus-5",
    "global.anthropic.claude-sonnet-5",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
]
# Families that reject temperature/top_p/top_k with a 400.
NO_SAMPLING = ("claude-opus-5", "claude-sonnet-5", "claude-opus-4-7", "claude-opus-4-8", "claude-fable")

# Which thinking configs each family accepts (Claude API model docs). First
# match wins, so specific families come first.
#   disabled: {"type": "disabled"} accepted
#   adaptive: {"type": "adaptive"} accepted (older families need budget_tokens instead)
THINKING_RULES = [
    ("claude-opus-5-5", {"disabled": False, "adaptive": True}),    # thinking can't be turned off; lower effort instead
    ("claude-sonnet-5-5", {"disabled": False, "adaptive": True}),  # off is {"type": "between_tools"}
    ("claude-fable", {"disabled": False, "adaptive": True}),       # thinking always on
    ("claude-opus-5", {"disabled": True, "adaptive": True}),       # disabled only at effort <= high
    ("claude-sonnet-5", {"disabled": True, "adaptive": True}),
    ("claude-sonnet-4-5", {"disabled": True, "adaptive": False}),
    ("claude-haiku-4-5", {"disabled": True, "adaptive": False}),
]

# Combinations the runtime gets wrong today, with why it matters. The test is
# an expected failure for these until get_model() handles them, and turns into
# an error (strict) once it does, so the marker gets removed with the fix.
KNOWN_BROKEN = {
    ("claude-opus-5-5", False): "non-reasoning agents send thinking disabled → 400 on Opus 5.5 (blocks the Opus 5.5 migration, #129)",
    ("claude-sonnet-5-5", False): "non-reasoning agents send thinking disabled → 400 on Sonnet 5.5; needs between_tools",
    ("claude-sonnet-4-5", True): "reasoning sends adaptive, which Sonnet 4.5 doesn't take (no agent uses this combo today)",
    ("claude-haiku-4-5", True): "reasoning sends adaptive, which Haiku 4.5 doesn't take (no agent uses this combo today)",
}


def _rules(model_id):
    return next((fam, r) for fam, r in THINKING_RULES if fam in model_id)


def _model(model_id, reasoning):
    os.environ.setdefault("AWS_REGION", "us-west-2")
    from src.utils.strands_sdk_utils import strands_utils
    return strands_utils.get_model(llm_type=model_id, enable_reasoning=reasoning, tool_cache=False).config


def _cases():
    for model_id in MODELS:
        for reasoning in (True, False):
            fam, _ = _rules(model_id)
            reason = KNOWN_BROKEN.get((fam, reasoning))
            marks = [pytest.mark.xfail(strict=True, reason=f"known issue: {reason}")] if reason else []
            yield pytest.param(model_id, reasoning, marks=marks, id=f"{fam}-{'reasoning' if reasoning else 'plain'}")


@pytest.mark.parametrize("model_id, reasoning", list(_cases()))
def test_request_fields_accepted_by_model(model_id, reasoning):
    """The request get_model() builds must be one the model accepts (no 400)."""
    cfg = _model(model_id, reasoning)
    extra = cfg.get("additional_request_fields", {})
    thinking = extra.get("thinking")
    effort = (extra.get("output_config") or {}).get("effort")
    _, rules = _rules(model_id)
    assert "budget_tokens" not in str(extra) or not rules["adaptive"], "fixed thinking budget on a model that only takes adaptive"
    if thinking == {"type": "disabled"}:
        assert rules["disabled"], f"{model_id} rejects thinking disabled"
        assert effort in (None, "low", "medium", "high"), "thinking off + effort above high is a 400"
    if thinking == {"type": "adaptive"}:
        assert rules["adaptive"], f"{model_id} doesn't take adaptive thinking"
    if any(f in model_id for f in NO_SAMPLING):
        assert "temperature" not in cfg and "top_p" not in cfg


@pytest.mark.xfail(strict=True, reason="known issue: legacy '\\n\\nHuman' stop sequence truncates reports "
                   "that contain e.g. '\\n\\nHuman Resources'; see #129")
def test_no_legacy_human_stop_sequence():
    cfg = _model(MODELS[0], False)
    assert not any("Human" in s for s in cfg.get("stop_sequences") or [])


# --- config consistency ------------------------------------------------------

def _env_example_model_ids():
    text = (AGENTCORE / ".env.example").read_text(encoding="utf-8")
    return dict(re.findall(r"^([A-Z_]+_MODEL_ID)=(\S+)", text, re.M))


def test_every_configured_model_has_a_pricing_entry():
    pricing = cost.load_pricing()
    missing = {k: v for k, v in _env_example_model_ids().items() if cost.price_for(v, pricing) is None}
    assert not missing, f"add these model families to pricing.yaml: {missing}"


def test_scenarios_point_to_existing_files():
    here = Path(__file__).resolve().parents[1]   # paths in scenarios.yaml are relative to eval-harness/
    scenarios = yaml.safe_load((here / "config" / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]
    for name, s in scenarios.items():
        assert (here / s["csv"]).is_file(), name
        assert (here / s["answer_key"]).is_file(), name
        assert s["upload"] and all((here / f).is_file() for f in s["upload"]), name
        assert not any("ground_truth" in f for f in s["upload"]), f"{name}: the answer sheet must not reach the agents"


def test_every_scenario_has_a_split():
    """dev or test decides what run_eval.py runs by default, how compare.py groups it and whether Langfuse queues it."""
    from grade import SPLITS, load_scenario, load_scenarios
    scenarios = load_scenarios()
    for name, s in scenarios.items():
        assert s.get("split") in SPLITS, f"{name}: split must be one of {SPLITS}"
        assert load_scenario(name)["split"] == s["split"]
    # moon_market is the held-out test set; the dev sets are tuned on
    assert {n for n, s in scenarios.items() if s["split"] == "test"} == {n for n in scenarios if n.startswith("moon_market")}


def test_test_sets_have_no_gold_case():
    """Gold cases tune the fact checker; one on a test set would tune it to that set."""
    from grade import load_scenarios
    test_keys = {Path(s["answer_key"]).name for s in load_scenarios().values() if s["split"] == "test"}
    gold = Path(__file__).resolve().parents[1] / "sanity" / "factcheck_cases"
    for path in gold.glob("*.yaml"):
        key = Path(yaml.safe_load(path.read_text(encoding="utf-8"))["answer_key"]).name
        assert key not in test_keys, f"{path.name} is a gold case on a test set"


def test_no_answer_sheet_in_a_data_directory():
    """These directories reach the agents or, through the web app's /sample-data, the users."""
    repo = Path(__file__).resolve().parents[2]
    shipped = [repo / "deep-insight-web" / "sample_data", repo / "managed-agentcore" / "data", repo / "self-hosted" / "data"]
    leaked = [str(p.relative_to(repo)) for d in shipped for p in d.rglob("*ground_truth*")]
    assert not leaked, f"answer sheets belong in eval-harness/ground_truth/: {leaked}"
