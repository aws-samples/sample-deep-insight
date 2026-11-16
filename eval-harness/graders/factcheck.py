"""Extract claims with a reader, then compare them deterministically to an answer key."""
import math

from .llm import finite_number, normalize, require_quote
from .numbers import parse_numbers


def validate_facts(answer_key, scenario):
    if answer_key.get("example"):
        raise ValueError("The schema example is not a verified answer key")
    if answer_key.get("version") != 1 or answer_key.get("scenario") != scenario:
        raise ValueError("Answer key version/scenario does not match this evaluation")
    facts = answer_key.get("facts", [])
    ids = [f.get("id") for f in facts]
    if not ids or len(ids) > 64 or any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Answer key must contain unique, nonempty fact IDs")
    for fact in facts:
        if not isinstance(fact.get("statement"), str) or not fact["statement"].strip():
            raise ValueError("Each fact needs a statement describing its scope and unit")
        value = fact.get("expected")
        if not finite_number(value) and not (isinstance(value, str) and value.strip()):
            raise ValueError("Expected facts must be finite numbers or nonempty strings")
        for key in ("absolute_tolerance", "relative_tolerance"):
            if not finite_number(fact.get(key, 0)) or fact.get(key, 0) < 0:
                raise ValueError("Fact tolerances must be finite and nonnegative")
        if not isinstance(fact.get("required", True), bool):
            raise ValueError("required must be a boolean")
    return facts


def grade(report, answer_key, scenario, evaluator):
    facts = validate_facts(answer_key, scenario)
    findings = []
    # Bounded batches keep a large answer key from silently exhausting output tokens.
    for start in range(0, len(facts), 8):
        batch = facts[start:start + 8]
        response = evaluator.assess(
            "Extract the report's claim for EACH requested fact. Respect its exact scope, period, "
            "population and unit; a value for another scope is not an answer. Return "
            '{"claims":[{"id":"...","status":"found|not_found","value":number|string|null,'
            '"quote":"exact report excerpt, or empty when not_found"}]}. '
            "Do not calculate or correct the report's value. Numeric values must use the unit "
            "in the requested statement, with magnitude suffixes expanded. Return each ID exactly once.",
            {"facts": [{"id": f["id"], "statement": f["statement"]} for f in batch], "report": report},
        )
        claims = response.get("claims")
        if not isinstance(claims, list) or len(claims) != len(batch):
            raise ValueError("Fact extraction omitted or added facts")
        by_id = {c.get("id"): c for c in claims}
        if len(by_id) != len(claims) or set(by_id) != {f["id"] for f in batch}:
            raise ValueError("Fact extraction has duplicate or unknown IDs")
        for fact in batch:
            claim = by_id[fact["id"]]
            status = claim.get("status")
            if status == "not_found":
                if claim.get("value") is not None or claim.get("quote") not in ("", None):
                    raise ValueError("Missing claims cannot contain a value or quote")
                correct = False
            elif status == "found":
                require_quote(claim.get("quote"), report)
                value = claim.get("value")
                expected = fact["expected"]
                if finite_number(expected):
                    if not finite_number(value):
                        raise ValueError("Numeric fact extraction must return a finite number")
                    evidence = [v for v, *_ in parse_numbers(claim["quote"])]
                    if not any(math.isclose(v, value, rel_tol=1e-9, abs_tol=1e-9) for v in evidence):
                        raise ValueError("Extracted numeric value does not occur in its evidence quote")
                    correct = math.isclose(value, expected, rel_tol=fact.get("relative_tolerance", 0),
                                           abs_tol=fact.get("absolute_tolerance", 0))
                else:
                    if not isinstance(value, str) or not normalize(value) or normalize(value).casefold() not in normalize(claim["quote"]).casefold():
                        raise ValueError("Extracted text does not occur in its evidence quote")
                    correct = normalize(value).casefold() == normalize(expected).casefold()
            else:
                raise ValueError("Unknown fact extraction status")
            findings.append({**claim, "correct": correct, "expected": fact["expected"],
                             "required": fact.get("required", True)})
    found = [f for f in findings if f["status"] == "found"]
    wrong = [f for f in found if not f["correct"]]
    missing = [f for f in findings if f["status"] == "not_found" and f["required"]]
    passed = bool(found) and not wrong and not missing
    return {"passed": passed, "scores": {"factcheck_pass": passed, "facts_total": len(facts),
             "facts_checked": len(found), "facts_correct": sum(f["correct"] for f in found),
             "facts_wrong": len(wrong), "required_facts_missing": len(missing),
             "fact_coverage": len(found) / len(facts)}, "findings": findings}
