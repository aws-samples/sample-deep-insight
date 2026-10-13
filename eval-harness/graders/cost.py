"""Cost and cache metrics from token usage.

Accepts either the runtime's token_usage.json (`{"by_agent": {...}}`) or the
usage the eval runner collects from the event stream (same shape).

Bedrock reports `inputTokens` without cache reads/writes, so total input is
input + cache_read + cache_write, and the cache hit rate is cache_read over
that total.
"""
import json
import sys
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[1] / "config"


def load_pricing(path=CONFIG / "pricing.yaml"):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["models"]


def price_for(model_id, pricing):
    for p in pricing:
        if p["match"] in (model_id or ""):
            return p
    return None


def compute(usage, pricing=None):
    pricing = pricing if pricing is not None else load_pricing()
    by_agent = usage.get("by_agent", {}) or {}
    agents = {}
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    cost_total = 0.0
    unpriced = 0
    unverified = set()
    for name, a in by_agent.items():
        tok = {k: int(a.get(k, 0) or 0) for k in total}
        for k in total:
            total[k] += tok[k]
        p = price_for(a.get("model_id"), pricing)
        cost = 0.0
        priced = True
        for k, n in tok.items():
            rate = p.get(k) if p else None
            if rate is None:
                if n:
                    priced = False
                continue
            cost += n * rate / 1e6
        if not priced:
            unpriced += sum(tok.values())
        if p and not p.get("verified"):
            unverified.add(p["match"])
        all_in = tok["input"] + tok["cache_read"] + tok["cache_write"]
        agents[name] = {
            "model_id": a.get("model_id"),
            **tok,
            "cost_usd": round(cost, 4) if priced else None,
            "cache_hit_rate": tok["cache_read"] / all_in if all_in else None,
        }
        if priced:
            cost_total += cost
    all_in = total["input"] + total["cache_read"] + total["cache_write"]
    return {
        "cost_usd": round(cost_total, 4),
        "cost_complete": unpriced == 0,
        "unpriced_tokens": unpriced,
        "prices_unverified": sorted(unverified),
        "tokens_input_total": all_in,
        "tokens_output": total["output"],
        "cache_hit_rate": total["cache_read"] / all_in if all_in else None,
        "by_agent": agents,
    }


if __name__ == "__main__":
    print(json.dumps(compute(json.loads(Path(sys.argv[1]).read_text())), indent=2, ensure_ascii=False))
