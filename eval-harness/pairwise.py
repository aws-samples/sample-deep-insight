"""Blind comparison in both report orders, with explicit order disagreement."""
from graders.llm import require_quote, validate_rubric


def grade(candidate, baseline, query, rubric, evaluator):
    dimensions = validate_rubric(rubric)
    comparisons = []
    for a, b, labels in ((candidate, baseline, {"A": "candidate", "B": "baseline"}),
                          (baseline, candidate, {"A": "baseline", "B": "candidate"})):
        response = evaluator.assess(
            "Compare the two anonymous reports on the SAME request and rubric. Choose the better "
            "report overall or tie when neither is materially better. Do not infer which is newer. "
            "Do not reward length or formatting over correctness. You cannot inspect images or the "
            'source CSV. Return {"winner":"A|B|tie","reason":"specific comparative reasoning",'
            '"quote_a":"exact excerpt from A","quote_b":"exact excerpt from B"}.',
            {"request": query, "rubric": dimensions, "report_A": a, "report_B": b},
        )
        if response.get("winner") not in ("A", "B", "tie"):
            raise ValueError("Invalid pairwise winner")
        if not isinstance(response.get("reason"), str) or not response["reason"].strip():
            raise ValueError("Pairwise comparison needs a reason")
        require_quote(response.get("quote_a"), a)
        require_quote(response.get("quote_b"), b)
        comparisons.append({**response, "order": labels,
                            "normalized_winner": labels.get(response["winner"], "tie")})
    winners = [r["normalized_winner"] for r in comparisons]
    consistent = winners[0] == winners[1]
    winner = winners[0] if consistent else "inconclusive"
    passed = winner in ("candidate", "tie")
    return {"passed": passed, "scores": {"pairwise_pass": passed, "pairwise_winner": winner,
             "pairwise_order_consistent": consistent}, "comparisons": comparisons}
