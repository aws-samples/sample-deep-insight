"""Rubric-based, evidence-backed report quality assessment."""
from .llm import require_quote, validate_rubric


def grade(report, query, rubric, evaluator):
    dimensions = validate_rubric(rubric)
    response = evaluator.assess(
        "Assess how well the report answers the original request using EVERY rubric dimension. "
        "Score each from 1 (unusable), 2 (major deficiencies), 3 (adequate), 4 (good), to 5 (excellent). "
        "A score is an ordinal rubric assessment, not a verified fact check. Do not claim access to "
        "the source CSV or images. Return "
        '{"dimensions":[{"id":"...","score":1,"reason":"specific justification",'
        '"quote":"exact supporting report excerpt, or null for a missing criterion scored 1 or 2"}]}. '
        "Quotes must come ONLY from the report body, never the original request or rubric. "
        "For a missing criterion, use score 1 or 2 and quote null; explain the absence in reason. "
        "Scores 3 through 5 require an exact report excerpt. Return each dimension exactly once.",
        {"request": query, "rubric": dimensions, "report": report},
    )
    rows = response.get("dimensions")
    if not isinstance(rows, list) or len(rows) != len(dimensions):
        raise ValueError("Judge did not score every rubric dimension")
    by_id = {r.get("id"): r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != {d["id"] for d in dimensions}:
        raise ValueError("Judge returned duplicate or unknown rubric dimensions")
    for row in rows:
        if type(row.get("score")) is not int or not 1 <= row["score"] <= 5:
            raise ValueError("Judge scores must be integers from 1 to 5")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("Judge must justify each score")
        if row.get("quote") in (None, "") and row["score"] <= 2:
            continue  # absence supports a low score, never a positive unsupported assessment
        require_quote(row.get("quote"), report)
    score = sum(by_id[d["id"]]["score"] * d["weight"] for d in dimensions) / sum(d["weight"] for d in dimensions)
    passed = score >= rubric.get("minimum_score", 3.5) and all(r["score"] >= rubric.get("minimum_dimension_score", 2) for r in rows)
    return {"passed": passed, "scores": {"judge_pass": passed, "judge_score": round(score, 4),
             **{f"judge_{r['id']}": r["score"] for r in rows}}, "dimensions": rows}
