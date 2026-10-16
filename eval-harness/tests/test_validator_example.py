"""The Validator's step 2 example, run as the agent writes it. No LLM calls.

It must not mark a calculation verified unless it re-derived it, and it must
compare at the stored value's own precision: a fixed tolerance let planted
10% errors in small values (ROAS 3.17 → 3.487) through as verified.
"""
import pickle
import re

import pandas as pd


def _validator_step2():
    from src.prompts.template import apply_prompt_template
    md = apply_prompt_template(prompt_name="validator", prompt_context={"USER_REQUEST": "", "FULL_PLAN": "", "EXECUTION_ENVIRONMENT": ""})
    start = md.index('file_path="./artifacts/code/validator_step2_validate.py"')
    return re.compile(r'content=("""|\'\'\')(.*?)\1', re.DOTALL).search(md, start).group(2)


def test_verifies_only_what_it_recomputed_at_the_stored_precision(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "artifacts" / "cache").mkdir(parents=True)
    pd.DataFrame({"매출액": [100.0, 300.0], "광고비용": [50.0, 50.0], "매체": ["a", "b"]}).to_csv("data.csv", index=False)
    calcs = [
        {"id": "rev", "value": 400.0, "formula": "SUM(매출액)", "source_file": "data.csv"},
        {"id": "rev_wrong", "value": 410.0, "formula": "SUM(매출액)", "source_file": "data.csv"},
        {"id": "roas", "value": 4.0, "formula": "SUM(매출액) / SUM(광고비용)", "source_file": "data.csv"},
        {"id": "avg", "value": 200.0, "formula": "AVG(매출액)", "source_file": "data.csv"},
        {"id": "by_media", "value": 999.0, "formula": "SUM(매출액)/SUM(광고비용) GROUP BY 매체", "source_file": "data.csv"},
        {"id": "roas_10pct_off", "value": 4.4, "formula": "SUM(매출액)/SUM(광고비용)", "source_file": "data.csv"},
        {"id": "roas_rounded", "value": 4.0004, "formula": "SUM(매출액)/SUM(광고비용)", "source_file": "data.csv"},
    ]
    with open("artifacts/cache/priority_calcs.pkl", "wb") as f:
        pickle.dump(calcs, f)
    exec(_validator_step2(), {})
    with open("artifacts/cache/verified.pkl", "rb") as f:
        v = pickle.load(f)
    assert {k: r["match"] for k, r in v.items()} == {"rev": True, "rev_wrong": False, "roas": True, "avg": True, "by_media": None,
                                                      "roas_10pct_off": False, "roas_rounded": False}


def test_same_value_reads_the_stored_precision():
    """A float with a trailing .0 was rounded to an integer: 20850.0 vs 20850.08 is a match (a false alarm once)."""
    code = _validator_step2()
    ns = {}
    exec(code[:code.index("with open('./artifacts/cache/priority_calcs.pkl'")], ns)
    same = ns["same_value"]
    assert same(20850.0, 20850.0822) and same(2987, 2987.4) and same(3.17, 3.1695)
    assert not same(3.487, 3.17) and not same(2.343, 2.132) and not same(4.0004, 4.0)
