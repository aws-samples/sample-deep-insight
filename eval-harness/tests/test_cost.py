import pytest

from graders import cost

PRICING = [
    {"match": "claude-opus-5-5", "input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write": 5.0, "verified": True},
    {"match": "claude-sonnet-5", "input": None, "output": None, "cache_read": None, "cache_write": None, "verified": False},
]


def test_cost_and_cache_rate():
    usage = {"by_agent": {"planner": {"model_id": "global.anthropic.claude-opus-5-5", "input": 1_000_000, "output": 100_000, "cache_read": 3_000_000, "cache_write": 0}}}
    c = cost.compute(usage, PRICING)
    assert c["cost_usd"] == pytest.approx(4.0 + 2.0 + 0.6)
    assert c["cache_hit_rate"] == pytest.approx(0.75)
    assert c["cost_complete"]


def test_unknown_price_is_reported_not_guessed():
    usage = {"by_agent": {"coder": {"model_id": "global.anthropic.claude-sonnet-5", "input": 10, "output": 10, "cache_read": 0, "cache_write": 0}}}
    c = cost.compute(usage, PRICING)
    assert c["cost_complete"] is False
    assert c["unpriced_tokens"] == 20
    assert c["by_agent"]["coder"]["cost_usd"] is None


def test_specific_family_matches_before_generic():
    assert cost.price_for("claude-opus-5-5", cost.load_pricing())["match"] == "claude-opus-5-5"
    assert cost.price_for("global.anthropic.claude-sonnet-4-5-20250929-v1:0", cost.load_pricing())["match"] == "claude-sonnet-4-5"
    assert cost.price_for("global.anthropic.claude-sonnet-4-20250514-v1:0", cost.load_pricing())["match"] == "claude-sonnet-4-2"
