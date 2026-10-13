"""Build synthetic run folders for grader tests.

`make_clean_run` writes a run whose artifacts are all mutually consistent and
correct for the jungle_market dataset. Each `corrupt_*` helper then breaks
exactly one thing, so a test can assert that the matching grader notices.
Built at test time so no binary .docx fixtures live in git.
"""
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
CSV = REPO / "deep-insight-web" / "sample_data" / "jungle-market" / "jungle-market-sales.csv"


def _calcs():
    # Values after removing the file's exact duplicate rows, as a correct analysis does;
    # the recompute grader accepts them through its deduplicated pass.
    df = pd.read_csv(CSV).drop_duplicates()
    src = "./data/jungle-market-sales.csv"
    top = df.groupby("city")["line_total"].sum().sort_values(ascending=False)
    return [
        {"id": "calc_001", "value": round(float(df["line_total"].sum()), 2), "description": "총 매출", "formula": "SUM(line_total)", "source_file": src},
        {"id": "calc_002", "value": float(df["order_id"].nunique()), "description": "주문 건수", "formula": "COUNT(DISTINCT order_id)", "source_file": src},
        {"id": "calc_003", "value": float(df["line_total"].sum() / df["order_id"].nunique()), "description": "평균 주문 금액",
         "formula": "SUM(line_total) / COUNT(DISTINCT order_id)", "source_file": src},
        {"id": "calc_004", "value": round(float(top.iloc[0]), 2), "description": f"{top.index[0]} 매출", "formula": "SUM(line_total) GROUP BY city", "source_file": src},
        {"id": "calc_005", "value": float(df["customer_id"].nunique()), "description": "고객 수", "formula": "COUNT(DISTINCT customer_id)", "source_file": src},
    ], top.index[0]


def _body(calcs, top_name):
    v = {c["id"]: c["value"] for c in calcs}
    return [
        "Executive Summary",
        f"분석 기간 동안 총 {v['calc_002']:,.0f}건 [2]의 주문이 발생했고 총 매출은 ${v['calc_001']:,.2f} [1]입니다.",
        f"평균 주문 금액(AOV)은 ${v['calc_003']:,.2f} [3]이며, 2026년 3월 2일부터 15일까지의 데이터입니다.",
        f"{top_name}의 매출이 ${v['calc_004']:,.2f} [4]로 도시 중 1위입니다.",
        f"구매 고객 수는 {v['calc_005']:,.0f}명 [5]입니다.",
    ]


def statement(fact_id, quote, stated, number, unit, subject="", relation="none", scope="same", stated_scope="unstated"):
    """One fact-check extraction entry, as the model would return it."""
    return {"fact_id": fact_id, "quote": quote, "stated": stated, "number": number, "unit": unit, "subject": subject,
            "relation": relation, "stated_scope": stated_scope, "scope": scope, "scope_reason": ""}


def clean_extraction(drop=()):
    """The fact-check extraction a correct model returns for make_clean_run's report."""
    calcs, top = _calcs()
    v = {c["id"]: c["value"] for c in calcs}
    out = [
        statement("order_count", f"총 {v['calc_002']:,.0f}건", f"{v['calc_002']:,.0f}건", v["calc_002"], "count"),
        statement("total_revenue", f"총 매출은 ${v['calc_001']:,.2f}", f"${v['calc_001']:,.2f}", v["calc_001"], "USD"),
        statement("avg_order_value", f"평균 주문 금액(AOV)은 ${v['calc_003']:,.2f}", f"${v['calc_003']:,.2f}", round(v["calc_003"], 2), "USD"),
        statement("top_city_revenue", f"{top}의 매출이 ${v['calc_004']:,.2f}", f"${v['calc_004']:,.2f}", v["calc_004"], "USD", subject=top),
        statement("customer_count", f"구매 고객 수는 {v['calc_005']:,.0f}명", f"{v['calc_005']:,.0f}명", v["calc_005"], "count"),
    ]
    return {"statements": [s for s in out if s["fact_id"] not in drop]}


def write_docx(path, body, refs):
    import docx
    doc = docx.Document()
    for line in body:
        doc.add_paragraph(line)
    doc.add_paragraph("참고문헌 및 데이터 출처")
    for line in refs:
        doc.add_paragraph(line)
    doc.save(str(path))


def make_clean_run(run_dir):
    run_dir = Path(run_dir)
    a = run_dir / "artifacts"
    a.mkdir(parents=True, exist_ok=True)
    calcs, top_name = _calcs()
    cites = [
        {"citation_id": f"[{i}]", "calculation_id": c["id"], "value": c["value"], "description": c["description"], "verification_status": "verified"}
        for i, c in enumerate(calcs, 1)
    ]
    (a / "calculation_metadata.json").write_text(json.dumps({"calculations": calcs}, ensure_ascii=False), encoding="utf-8")
    (a / "citations.json").write_text(json.dumps({"metadata": {}, "citations": cites}, ensure_ascii=False), encoding="utf-8")
    (a / "validation_report.txt").write_text("Total: 5, Verified: 5, Needs review: 0\n", encoding="utf-8")
    (a / "audit_findings.json").write_text(json.dumps({"verdict": "pass", "stats": {"type_a": 0, "type_b": 0, "type_c": 0, "type_d": 0}, "findings": [], "audit_metadata": {"retry_count": 0}}), encoding="utf-8")
    refs = [f"[{i}] {c['description']}: {c['value']} | Formula: {c['formula']}" for i, c in enumerate(calcs, 1)]
    write_docx(a / "final_report_with_citations.docx", _body(calcs, top_name), refs)
    debug = run_dir / "debug"
    debug.mkdir(exist_ok=True)
    (debug / "execution_1.json").write_text(json.dumps({"execution_num": 1, "status": "failed", "stderr": "cat: ./data/x.csv: No such file or directory\n", "execution_time_ms": 3}))
    (debug / "execution_2.json").write_text(json.dumps({"execution_num": 2, "status": "completed", "stdout": "ok", "execution_time_ms": 1200}))
    return run_dir


def _edit_json(path, fn):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fn(data)
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def corrupt_citation_value(run_dir):
    """citations.json [1] no longer equals the computed value."""
    _edit_json(Path(run_dir) / "artifacts" / "citations.json", lambda d: d["citations"][0].update(value=12345678.0))


def corrupt_metadata_value(run_dir):
    """The Coder's total revenue is wrong (and the citation faithfully copies it)."""
    def bump(d):
        d["calculations"][0]["value"] += 1000
    _edit_json(Path(run_dir) / "artifacts" / "calculation_metadata.json", bump)
    _edit_json(Path(run_dir) / "artifacts" / "citations.json", lambda d: d["citations"][0].update(value=d["citations"][0]["value"] + 1000))


def corrupt_report_number(run_dir):
    """The report prints a number next to [4] that is not the cited value."""
    calcs, top_name = _calcs()
    body = _body(calcs, top_name)
    body[4] = f"{top_name}의 매출이 $15,000.00 [4]로 도시 중 1위입니다."
    write_docx(Path(run_dir) / "artifacts" / "final_report_with_citations.docx", body, [])


def corrupt_broken_ref(run_dir):
    """The report cites [9], which does not exist."""
    calcs, top_name = _calcs()
    body = _body(calcs, top_name) + ["추가로 재구매율은 87.8% [9]입니다."]
    write_docx(Path(run_dir) / "artifacts" / "final_report_with_citations.docx", body, [])


def corrupt_missing_file(run_dir):
    (Path(run_dir) / "artifacts" / "validation_report.txt").unlink()
