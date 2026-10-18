"""Graders must pass a clean run and catch each injected defect."""
import json

import pytest

from fixtures import make_run
from grade import grade_run, load_scenario
from graders import recompute
from graders.numbers import matches, parse_numbers


@pytest.fixture
def scenario():
    # The fixture run is small (5 calculations), so grade it under the simple
    # scenario's thresholds.
    return load_scenario("jungle_market_simple")


@pytest.fixture
def clean(tmp_path):
    return make_run.make_clean_run(tmp_path / "run")


def grade(run_dir, scenario):
    return grade_run(run_dir, scenario["csv"], scenario)["scores"]


def test_clean_run_passes(clean, scenario):
    s = grade(clean, scenario)
    assert s["core_pass"], s["core_fail_reasons"]
    assert s["citation_value_match_rate"] == 1.0
    assert s["cited_value_match_rate"] == 1.0 and s["cited_value_checked"] == 5
    assert s["recompute_supported"] == 5 and s["recompute_lenient"] == 0  # GROUP BY checked against the named group
    assert s["recompute_match_rate"] == 1.0 and s["recompute_dedup"] == 2  # revenue and AOV only match after dedup
    assert s["audit_pass"] is True
    assert s["citation_inside_number"] == 0
    assert s["validator_verified_checked"] == 5 and s["validator_false_verified"] == 0
    assert s["validator_false_alarm"] == 0 and s["audit_missed"] is False


@pytest.mark.parametrize("corrupt, metric, expected", [
    (make_run.corrupt_citation_value, "citations_ok", False),
    (make_run.corrupt_metadata_value, "recompute_match_rate", 0.8),
    (make_run.corrupt_report_number, "cited_value_match_rate", 0.8),
    (make_run.corrupt_broken_ref, "broken_citation_refs", 1),
    (make_run.corrupt_missing_file, "all_required_ok", False),
    (make_run.corrupt_marker_inside_number, "citation_inside_number", 1),
])
def test_each_defect_is_caught(clean, scenario, corrupt, metric, expected):
    corrupt(clean)
    s = grade(clean, scenario)
    assert s[metric] == pytest.approx(expected) if isinstance(expected, float) else s[metric] == expected
    assert not s["core_pass"]
    assert metric in s["core_fail_reasons"]


# --- a check that produced nothing must fail, not pass ------------------------

def test_grader_crash_fails(clean, scenario, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(recompute, "grade", boom)
    s = grade(clean, scenario)
    assert s["recompute_grader_error"] is True
    assert "recompute_grader_error" in s["core_fail_reasons"]


def test_unrecognised_formulas_fail(clean, scenario):
    """Agent writes formulas the grader can't parse → nothing recomputed → FAIL (used to pass)."""
    path = clean / "artifacts" / "calculation_metadata.json"
    data = json.loads(path.read_text())
    for c in data["calculations"]:
        c["formula"] = "합계(매출)"
    path.write_text(json.dumps(data, ensure_ascii=False))
    s = grade(clean, scenario)
    assert s["recompute_supported"] == 0 and s["recompute_match_rate"] is None
    assert "recompute_supported" in s["core_fail_reasons"]


def test_no_numbers_before_markers_fails(clean, scenario):
    """Citations the grader can't pair with a number → 0 compared → FAIL (used to pass)."""
    make_run.write_docx(clean / "artifacts" / "final_report_with_citations.docx",
                        ["총 매출은 $110,270.26이며 주문은 2,987건, 평균 주문 금액은 $36.92입니다.", "출처는 [1] [2] [3] [4] [5]입니다."], [])
    s = grade(clean, scenario)
    assert s["cited_value_checked"] == 0
    assert "cited_value_checked" in s["core_fail_reasons"]


def test_missing_artifacts_still_produce_scores(tmp_path, scenario):
    (tmp_path / "artifacts").mkdir()
    s = grade(tmp_path, scenario)
    assert s["required_present"] == 0
    assert not s["core_pass"]


def test_failed_status_fails_core(clean, scenario):
    (clean / "run.json").write_text(json.dumps({"status": "session_unresolved"}))
    s = grade(clean, scenario)
    assert s["core_fail_reasons"][0] == "status"


# --- recompute: grouped formulas ---------------------------------------------

@pytest.fixture(scope="module")
def df():
    return recompute.load_csv(load_scenario("jungle_market")["csv"])


@pytest.mark.parametrize("formula, description, expected", [
    ("SUM(line_total) GROUP BY category", "Bakery 매출", lambda d: d[d.category == "Bakery"].line_total.sum()),
    ("SUM(line_total) grouped by city", "Paris 도시 매출", lambda d: d[d.city == "Paris"].line_total.sum()),
    ("SUM(line_total)/TOTAL(line_total)*100 GROUP BY category", "Ready Meals 카테고리 매출 비중",
     lambda d: d[d.category == "Ready Meals"].line_total.sum() / d.line_total.sum() * 100),
    ("MAX(SUM(line_total) GROUP BY order_date)", "일별 매출 최고점", lambda d: d.groupby("order_date").line_total.sum().max()),
    ("SUM(line_total) GROUP BY order_date", "2026-03-07 일별 매출", lambda d: d[d.order_date == "2026-03-07"].line_total.sum()),
    ("SUM(line_total) GROUP BY order_date", "3월 9일 매출", lambda d: d[d.order_date == "2026-03-09"].line_total.sum()),
    ("SUM(line_total) GROUP BY gender", "여성 고객 매출", lambda d: d[d.gender == "F"].line_total.sum()),
    ("SUM(line_total) WHERE gender=F", "", lambda d: d[d.gender == "F"].line_total.sum()),
])
def test_grouped_formulas(df, formula, description, expected):
    r = recompute.recompute(formula, df, description)
    assert r["lenient"] is False
    assert r["value"] == pytest.approx(float(expected(df)), rel=1e-9)


def test_group_not_named_is_lenient(df):
    r = recompute.recompute("SUM(line_total) GROUP BY category", df, "어떤 카테고리 매출")
    assert r["lenient"] is True and len(r["candidates"]) == df.category.nunique()


def test_weekday_group(df):
    """The weekday comes from the file's date column, whatever it is called (order_date here)."""
    import pandas as pd
    r = recompute.recompute("SUM(line_total) GROUP BY weekday", df, "토요일 총매출")
    saturday = df[pd.to_datetime(df.order_date).dt.dayofweek == 5].line_total.sum()
    assert r["lenient"] is False and r["value"] == pytest.approx(saturday)


def test_wrong_group_value_is_caught(clean, scenario):
    """A segment number that doesn't match its group fails (segments weren't checked before)."""
    path = clean / "artifacts" / "calculation_metadata.json"
    data = json.loads(path.read_text())
    data["calculations"][3]["value"] = 17053.67  # the top city's revenue with the duplicate rows counted
    path.write_text(json.dumps(data, ensure_ascii=False))
    s = grade(clean, scenario)
    assert s["recompute_match_rate"] < 1.0


def test_duplicate_rows_recomputed_with_and_without(tmp_path):
    """A file with exact duplicate rows: the deduplicated value is right, the raw one too; anything else is wrong."""
    csv = tmp_path / "sales.csv"
    csv.write_text("order_id,line_total\nA,10\nB,20\nB,20\nC,5\n")
    (tmp_path / "artifacts").mkdir()
    calcs = [{"id": "dedup", "value": 35.0}, {"id": "raw", "value": 55.0}, {"id": "wrong", "value": 40.0}]
    for c in calcs:
        c.update(formula="SUM(line_total)", source_file="./data/sales.csv", description="total revenue")
    (tmp_path / "artifacts" / "calculation_metadata.json").write_text(json.dumps({"calculations": calcs}))
    s = recompute.grade(tmp_path / "artifacts", csv)
    assert s["recompute_supported"] == 3 and s["recompute_dedup"] == 1
    assert s["recompute_match_rate"] == pytest.approx(2 / 3)
    assert any(d.startswith("wrong:") for d in s["details"])


def test_overall_formula_with_the_group_in_the_description(tmp_path):
    """'SUM(discount)/SUM(line_total)' described as 'PASTA30 할인율' is checked on the PASTA30 rows; a wrong value still fails."""
    csv = tmp_path / "sales.csv"
    csv.write_text("promo_code,line_total,discount\nPASTA30,7,3\nSAVE10,9,1\n,10,0\n")
    (tmp_path / "artifacts").mkdir()
    f = "SUM(discount)/(SUM(line_total)+SUM(discount))*100"
    calcs = [{"id": "pasta", "value": 30.0, "description": "PASTA30 할인율"},
             {"id": "none", "value": 0.0, "description": "No Promo 할인율"},
             {"id": "wrong", "value": 12.0, "description": "SAVE10 할인율"}]
    for c in calcs:
        c.update(formula=f, source_file="./data/sales.csv")
    (tmp_path / "artifacts" / "calculation_metadata.json").write_text(json.dumps({"calculations": calcs}))
    s = recompute.grade(tmp_path / "artifacts", csv)
    assert s["recompute_supported"] == 3 and s["recompute_lenient"] == 2
    assert [d.split(":")[0] for d in s["details"]] == ["wrong"]


def test_derived_file_counts_only_when_it_matches(tmp_path):
    """df_clean.pkl calculations: a match is recomputed support, a mismatch (rows filtered?) is not called wrong."""
    csv = tmp_path / "sales.csv"
    csv.write_text("order_id,line_total\nA,10\nB,20\nB,20\nC,5\n")
    (tmp_path / "artifacts").mkdir()
    calcs = [{"id": "raw", "value": 35.0, "source_file": "./data/sales.csv"},
             {"id": "clean_ok", "value": 35.0, "source_file": "./artifacts/cache/df_clean.pkl"},
             {"id": "clean_filtered", "value": 30.0, "source_file": "./artifacts/cache/df_clean.pkl"},
             {"id": "clean_named", "value": 35.0, "source_file": "./artifacts/cache/df_clean.pkl", "formula": "total_sales / order_count"}]
    for c in calcs:
        c.setdefault("formula", "SUM(line_total)")
        c["description"] = "total revenue"
    (tmp_path / "artifacts" / "calculation_metadata.json").write_text(json.dumps({"calculations": calcs}))
    s = recompute.grade(tmp_path / "artifacts", csv)
    assert s["recompute_supported"] == 2 and s["recompute_match_rate"] == 1.0
    assert s["recompute_derived"] == 1 and s["recompute_derived_unmatched"] == 1


@pytest.mark.parametrize("stored, expected, ok", [
    (19655.0, 19655.41, True),           # stored as a whole number
    (18.6, 18.551663, True),             # stored to one decimal
    (18.55166312549055, 18.55166312549055, True),
    (16432923.0, 16431923.0, False),     # off by 1,000
    (18.7, 18.551663, False),
    # rounded to 4, 6, 7 or 8 decimals: all the same value (6 and 7 used to fail)
    (round(18.55166312549055, 4), 18.55166312549055, True),
    (round(18.55166312549055, 6), 18.55166312549055, True),
    (round(18.55166312549055, 7), 18.55166312549055, True),
    (round(18.55166312549055, 8), 18.55166312549055, True),
    (18.551664, 18.55166312549055, False),  # 6 decimals, last digit wrong
    (18.551663125490547, 18.55166312549055, True),  # same value from another computation
    # a tie is right whichever way it was rounded: Python's round() vs pandas/numpy and half-up
    (6.56, 393300 / 60000, True),        # 6.555: Python 6.55, numpy 6.56
    (6.55, 393300 / 60000, True),
    (2.34, 2.345, True), (2.35, 2.345, True),
    (0.13, 0.125, True), (0.12, 0.125, True),   # 0.13 - 0.125 is 0.005000000000000004 in floats
    (6.57, 6.555, False), (6.54, 6.555, False),  # one step past the tie
])
def test_same_value_respects_stored_precision(stored, expected, ok):
    assert recompute.same_value(stored, expected) is ok


# --- number parsing and matching ---------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("16,431,923원", 16431923), ("₩2,958,765", 2958765), ("19,655.41", 19655.41),
    ("87.8%", 87.8), ("1,643만", 16430000), ("3.5M", 3.5e6),
])
def test_parse_numbers(text, value):
    assert parse_numbers(text)[0][0] == pytest.approx(value)


@pytest.mark.parametrize("printed, decimals, stored, ok", [
    (19655, 0, 19655.41, True),      # display rounding
    (19655.4, 1, 19655.41, True),
    (87.8, 1, 0.878, True),          # ratio shown as percent
    (1643, None, 1643.2, True),
    (2686000, 0, 3048395, False),
    (15.0, 1, 15.006, True),
    (16.0, 1, 15.006, False),
    (1500, 0, 15.0, False),          # ×100 only for ratios between 0 and 1
])
def test_matches(printed, decimals, stored, ok):
    assert matches(printed, decimals, stored) is ok


# --- general expressions: shapes agents wrote in real runs -------------------------

@pytest.mark.parametrize("formula, description, expected", [
    ("SUM(line_total WHERE promo_code IS NULL)", "", lambda d: d[d.promo_code.isna()].line_total.sum()),
    ("MEAN(line_total WHERE promo_code NOT NULL)", "", lambda d: d[d.promo_code.notna()].line_total.mean()),
    ("SUM(line_total) WHERE category=='Bakery'", "", lambda d: d[d.category == "Bakery"].line_total.sum()),
    ("SUM(line_total WHERE category=='Bakery') / SUM(line_total) * 100", "", lambda d: d[d.category == "Bakery"].line_total.sum() / d.line_total.sum() * 100),
    ("SUM(line_total|category)/SUM(line_total)*100", "Bakery 매출 비중", lambda d: d[d.category == "Bakery"].line_total.sum() / d.line_total.sum() * 100),
    ("SUM(line_total|cat) / SUM(line_total|all)", "Bakery 비중", lambda d: d[d.category == "Bakery"].line_total.sum() / d.line_total.sum()),
    ("SUM(line_total WHERE category==X) / SUM(line_total) * 100", "Bakery 비중", lambda d: d[d.category == "Bakery"].line_total.sum() / d.line_total.sum() * 100),
    ("SUM(line_total WHERE category=='Bakery') / COUNT(rows WHERE category=='Bakery')", "", lambda d: d[d.category == "Bakery"].line_total.mean()),
    ("STD(line_total)/MEAN(line_total)*100", "", lambda d: d.line_total.std() / d.line_total.mean() * 100),
    ("SUM(line_total WHERE product_name='{}')", "Oat Milk 매출", lambda d: d[d.product_name == "Oat Milk"].line_total.sum()),
    ("MAX(SUM(line_total) grouped by age_group, category)", "55+ 최선호 카테고리(Ready Meals) 매출",
     lambda d: d[(d.age_group == "55+") & (d.category == "Ready Meals")].line_total.sum()),
])
def test_general_expressions(df, formula, description, expected):
    r = recompute.recompute(formula, df, description)
    assert r is not None and r["lenient"] is False
    assert r["value"] == pytest.approx(float(expected(df)), rel=1e-9)


@pytest.mark.parametrize("formula", ["cat_sales/total_sales*100", "STD(daily_sum)/MEAN(daily_sum)*100", "SUM(line_total WHERE seg)/SUM(line_total)",
                                     "__import__('os').system('x')", "SUM(line_total) + foo",
                                     "SUM(line_total) ** 2", "SUM(line_total) / 9**9**9**9"])  # ** could hang eval()
def test_names_the_agent_made_up_stay_unsupported(df, formula):
    assert recompute.recompute(formula, df, "") is None


def test_unnamed_group_that_matches_nothing_is_unverified_not_wrong(clean, scenario):
    """'MEAN(line_total|weekday)' for 'weekdays' (Mon-Fri) matches no single weekday: unverified, not a mismatch."""
    path = clean / "artifacts" / "calculation_metadata.json"
    data = json.loads(path.read_text())
    data["calculations"].append({"id": "calc_weekdays", "value": 7.0123, "description": "Average line value on weekdays",
                                 "formula": "MEAN(line_total|weekday)", "source_file": data["calculations"][0]["source_file"]})
    path.write_text(json.dumps(data, ensure_ascii=False))
    s = grade(clean, scenario)
    assert s["recompute_match_rate"] == 1.0 and s["recompute_unverified"] == 1


def test_marker_inside_a_number_passes_the_value_check_but_fails_core(clean, scenario):
    """The value check reads "110,270" before [1] and accepts it; only the inside-number check sees the split."""
    make_run.corrupt_marker_inside_number(clean)
    s = grade(clean, scenario)
    assert s["cited_value_match_rate"] == 1.0
    assert s["citation_inside_number"] == 1 and "citation_inside_number" in s["core_fail_reasons"]


def test_validator_false_verified(clean, scenario):
    """The Coder's total is wrong, the Validator still says verified: recompute disagrees."""
    make_run.corrupt_metadata_value(clean)
    s = grade(clean, scenario)
    assert s["validator_verified_checked"] == 5 and s["validator_false_verified"] == 1


def test_subset_named_by_two_columns():
    """"아마존×건강식품 조합 ROAS" with the overall formula: the cell is two named values, from two columns."""
    from pathlib import Path
    df = recompute.load_csv(Path(__file__).resolve().parents[2] / "managed-agentcore/data/yummy_food/kr/yummy-food-market.csv")
    f = "SUM(매출액)/SUM(광고비용)"
    assert recompute._named_subset(f, df, "아마존×건강식품 조합 ROAS", 8.41) == pytest.approx(8.41, abs=0.005)
    assert recompute._named_subset(f, df, "아마존×건강식품 조합 ROAS", 3.39) is None   # the whole-file value is not this cell
    assert recompute._named_subset(f, df, "아마존 ROAS", 3.17) == pytest.approx(3.17, abs=0.005)  # one column still works


def test_bare_by_groups():
    """Coders write "SUM(매출액)/SUM(광고비용) by 매체" as often as GROUP BY."""
    from pathlib import Path
    df = recompute.load_csv(Path(__file__).resolve().parents[2] / "managed-agentcore/data/yummy_food/kr/yummy-food-market.csv")
    r = recompute.recompute("SUM(매출액)/SUM(광고비용) by 매체", df, "쿠빵 ROAS")
    assert r["value"] == pytest.approx(4.143265, rel=1e-5)
    assert recompute.recompute("SUM(매출액) by 없는컬럼", df, "") is None



def test_audit_missed(clean, scenario):
    """The fixture's Auditor says pass; a wrong number next to [4] is exactly what it should have blocked."""
    make_run.corrupt_report_number(clean)
    s = grade(clean, scenario)
    assert s["audit_pass"] is True and s["audit_missed"] is True and s["audit_missed_kinds"] == ["cited_value"]


def test_audit_missed_when_every_cited_value_is_wrong(clean, scenario):
    """A match rate of 0.0 is the worst case, not a missing one (it used to read as 1 through `or 1`)."""
    calcs, top_name = make_run._calcs()
    body = [f"수치 {c['value'] * 2:,.2f} [{i}]입니다." for i, c in enumerate(calcs, 1)]
    make_run.write_docx(clean / "artifacts" / "final_report_with_citations.docx", body, [])
    s = grade(clean, scenario)
    assert s["cited_value_match_rate"] == 0.0 and s["audit_pass"] is True
    assert s["audit_missed"] is True and s["audit_missed_kinds"] == ["cited_value"]


def test_validator_false_alarm(clean, scenario):
    """A right value marked needs_review: the Reporter would leave it out for nothing."""
    make_run._edit_json(clean / "artifacts" / "citations.json", lambda d: d["citations"][1].update(verification_status="needs_review"))
    s = grade(clean, scenario)
    assert s["validator_needs_review_checked"] == 1 and s["validator_false_alarm"] == 1
