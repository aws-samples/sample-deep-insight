"""components/reporter.py: which values are marked, what is staged, how the Reporter's report is scored. No AWS."""
import json
import random

from components import reporter as cr
from fixtures import make_run


def _mark(run, edit):
    path = run / "artifacts" / "citations.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data["citations"])
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_pick_reporter_plants_takes_cited_verified_distinct_values(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    def edit(cites):
        cites[2]["verification_status"] = "needs_review"                     # AOV: not verified
        cites.append({"citation_id": "[6]", "calculation_id": "twin", "value": cites[3]["value"] * 1.005,
                      "verification_status": "verified"})                     # within 1% of the top city's revenue
        cites[4]["value"] = 42                                                 # a small integer
    _mark(run, edit)
    plants = cr.pick_reporter_plants(run / "artifacts", 10, random.Random(0))
    meta = {c["id"]: c["value"] for c in json.loads((run / "artifacts" / "calculation_metadata.json").read_text())["calculations"]}
    assert sorted(plants) == ["calc_001", "calc_002"]                          # total revenue, order count
    assert plants["calc_002"] == meta["calc_002"]
    assert len(cr.pick_reporter_plants(run / "artifacts", 1, random.Random(0))) == 1


def test_stage_reporter_keeps_the_validators_files_and_marks(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    src = run / "artifacts"
    (src / "code").mkdir(exist_ok=True)
    for f in ("validator_step1.py", "reporter_step1.py", "svg_docx.py", "audit_engine.py", "coder_step1.py"):
        (src / "code" / f).write_text("x")
    (src / "report_draft.docx").write_text("x")
    cr.stage_reporter(src, tmp_path / "staged", {"calc_001": 1.0})
    staged = tmp_path / "staged"
    assert not (staged / "final_report_with_citations.docx").exists() and not (staged / "report_draft.docx").exists()
    assert not (staged / "audit_findings.json").exists()
    assert sorted(p.name for p in (staged / "code").iterdir()) == ["coder_step1.py", "validator_step1.py"]
    assert (staged / "validation_report.txt").exists()
    status = {c["calculation_id"]: c["verification_status"] for c in json.loads((staged / "citations.json").read_text())["citations"]}
    assert status["calc_001"] == "needs_review" and status["calc_002"] == "verified"


def test_score_reporter(tmp_path):
    run = make_run.make_clean_run(tmp_path / "run")
    a = run / "artifacts"
    body = ["총 매출은 $110,270.26 [1]입니다.",                      # cited: the marker points to it
            "도시 | 매출 | 비고", "Berlin | 6,879.45 | -",             # quoted in a table, no marker
            "최저 매출일은 $6,891입니다.",                            # 6,891 is not 6,879.45 at that precision
            "고객 1인당 3.7회 구매했습니다."]                          # 2 significant digits identify nothing
    make_run.write_docx(a / "final_report_with_citations.docx", body, [])
    r = cr.score_reporter(a, {"calc_001": 110270.26, "x_berlin": 6879.45, "x_daily": 6880.2, "x_freq": 3.69, "x_gone": 4321.0})
    outcome = {k: v["outcome"] for k, v in r["per_calc"].items()}
    assert outcome == {"calc_001": "cited", "x_berlin": "quoted", "x_daily": "left_out", "x_freq": "left_out", "x_gone": "left_out"}
    assert (r["cited"], r["quoted"], r["left_out"], r["leaked"]) == (1, 1, 3, 2) and r["leak_rate"] == 0.4
    assert r["graders"]["broken_citation_refs"] == 0 and r["graders"]["cited_value_match_rate"] == 1.0


def test_score_reporter_without_a_report(tmp_path):
    r = cr.score_reporter(tmp_path, {"c": 123.4})
    assert r["report_ok"] is False and r["left_out"] == 0


def test_printed_values_reads_ratios_and_scales():
    vals = cr.printed_values(["재구매율 37.7%[3], 매출 1.23만 원, 3.7배"])
    assert (37.7, 0.05) in [(v, round(h, 6)) for v, h in vals]
    assert (12300.0, 50.0) in [(v, h) for v, h in vals]
    assert all(v != 3.7 for v, _ in vals) and all(v != 3.0 for v, _ in vals)   # [3] is a marker, not a number
