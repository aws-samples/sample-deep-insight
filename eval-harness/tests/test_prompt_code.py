"""Code the agent prompts give the agents to write, run as written. No LLM calls.

Auditor: does it fail what must fail? Its verdict comes from audit_engine.py,
code the auditor prompt tells the agent to write verbatim. Each case plants one
defect in a clean run's artifacts and runs that code on them.

What the engine is built to block (Type B: a cited number differs from its
citation; Type C: a marker with no citation) must give `retry`, and
`needs_review` once retries are used up. What it is not built to see (an
uncited number, a wrong value carried consistently through metadata, citation
and report) passes here and is left to the other graders; those cases pin
that boundary so a change to it shows up.

Validator: the step 2 example must not mark a calculation verified unless it
actually re-derived it.
"""
import json
import re

import pytest

from fixtures import make_run


def _engine():
    from src.prompts.template import apply_prompt_template
    md = apply_prompt_template(prompt_name="auditor", prompt_context={"USER_REQUEST": "", "FULL_PLAN": "", "EXECUTION_ENVIRONMENT": ""})
    start = md.index('file_path="./artifacts/code/audit_engine.py"')
    code = re.compile(r'content=("""|\'\'\')(.*?)\1', re.DOTALL).search(md, start).group(2)
    ns = {}
    exec(code, ns)
    return ns


@pytest.fixture(scope="module")
def engine():
    return _engine()


def audit(engine, run_dir, retry_count=0):
    adir = run_dir / "artifacts"
    claims = engine["extract_claims"](str(adir / "final_report_with_citations.docx"))
    cites = json.loads((adir / "citations.json").read_text(encoding="utf-8"))
    meta = json.loads((adir / "calculation_metadata.json").read_text(encoding="utf-8"))
    findings = engine["classify"](claims, cites, meta)
    return engine["decide_verdict"](findings, retry_count), sorted({f["type"] for f in findings})


@pytest.fixture
def clean(tmp_path):
    return make_run.make_clean_run(tmp_path / "run")


def test_clean_report_passes(engine, clean):
    verdict, types = audit(engine, clean)
    assert verdict == "pass" and not {"B", "C"} & set(types)


@pytest.mark.parametrize("corrupt, kind", [
    (make_run.corrupt_report_number, "B"),    # $15,000.00 [4], citation says otherwise
    (make_run.corrupt_metadata_value, "B"),   # metadata and citation moved, the report kept the computed value
    (make_run.corrupt_broken_ref, "C"),       # [9] has no citation
])
def test_blocking_defects_are_caught(engine, clean, corrupt, kind):
    corrupt(clean)
    verdict, types = audit(engine, clean)
    assert kind in types and verdict == "retry"
    assert audit(engine, clean, retry_count=2)[0] == "needs_review"   # retries used up


@pytest.mark.xfail(strict=True, reason="known gap: the engine reads '110,270' before [1] and accepts it; "
                   "graders/report.py citation_inside_number catches it (#141)")
def test_marker_inside_a_number_is_caught(engine, clean):
    make_run.corrupt_marker_inside_number(clean)
    assert audit(engine, clean)[0] != "pass"


def test_uncited_number_warns_but_passes(engine, clean):
    """Type A (a number without a marker) is a warning by design."""
    calcs, top = make_run._calcs()
    body = make_run._body(calcs, top) + ["재구매 고객의 평균 지출은 $1,234.56로 신규 고객보다 높다."]
    make_run.write_docx(clean / "artifacts" / "final_report_with_citations.docx", body, [])
    verdict, types = audit(engine, clean)
    assert "A" in types and verdict == "pass"


def test_consistently_wrong_value_passes(engine, clean):
    """A wrong Coder value that metadata, citation and report all carry is invisible to the Auditor:
    it compares the report with the citations, not with the data. recompute.py catches it."""
    make_run.corrupt_metadata_value(clean)
    calcs, top = make_run._calcs()
    calcs[0]["value"] += 1000
    make_run.write_docx(clean / "artifacts" / "final_report_with_citations.docx", make_run._body(calcs, top), [])
    assert audit(engine, clean)[0] == "pass"


# --- Validator step 2 example: what it marks verified ----------------------------

def _validator_step2():
    from src.prompts.template import apply_prompt_template
    md = apply_prompt_template(prompt_name="validator", prompt_context={"USER_REQUEST": "", "FULL_PLAN": "", "EXECUTION_ENVIRONMENT": ""})
    start = md.index('file_path="./artifacts/code/validator_step2_validate.py"')
    return re.compile(r'content=("""|\'\'\')(.*?)\1', re.DOTALL).search(md, start).group(2)


def test_validator_example_never_verifies_what_it_did_not_recompute(tmp_path, monkeypatch):
    """The example once compared every SUM-free formula with itself, so they all came out verified."""
    import pickle
    import pandas as pd
    monkeypatch.chdir(tmp_path)
    (tmp_path / "artifacts" / "cache").mkdir(parents=True)
    pd.DataFrame({"매출액": [100.0, 300.0], "광고비용": [50.0, 50.0], "매체": ["a", "b"]}).to_csv("data.csv", index=False)
    calcs = [
        {"id": "rev", "value": 400.0, "formula": "SUM(매출액)", "source_file": "data.csv"},
        {"id": "rev_wrong", "value": 410.0, "formula": "SUM(매출액)", "source_file": "data.csv"},
        {"id": "roas", "value": 4.0, "formula": "SUM(매출액) / SUM(광고비용)", "source_file": "data.csv"},
        {"id": "avg", "value": 200.0, "formula": "AVG(매출액)", "source_file": "data.csv"},
        {"id": "roas_10pct_off", "value": 4.4, "formula": "SUM(매출액)/SUM(광고비용)", "source_file": "data.csv"},   # a fixed 0.5 would pass it
        {"id": "roas_rounded", "value": 4.0004, "formula": "SUM(매출액)/SUM(광고비용)", "source_file": "data.csv"},  # 4 decimals: 4.0004 ≠ 4.0
        {"id": "by_media", "value": 999.0, "formula": "SUM(매출액)/SUM(광고비용) GROUP BY 매체", "source_file": "data.csv"},
    ]
    with open("artifacts/cache/priority_calcs.pkl", "wb") as f:
        pickle.dump(calcs, f)
    exec(_validator_step2(), {})
    with open("artifacts/cache/verified.pkl", "rb") as f:
        v = pickle.load(f)
    assert {k: r["match"] for k, r in v.items()} == {"rev": True, "rev_wrong": False, "roas": True, "avg": True, "by_media": None,
                                                          "roas_10pct_off": False, "roas_rounded": False}
