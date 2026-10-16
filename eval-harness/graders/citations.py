"""Citation-chain grader: citations.json must faithfully mirror calculation_metadata.json.

The Validator copies each verified calculation into citations.json; the
Reporter then cites those numbers. A mismatch here means a number in the
report can differ from the number that was actually computed.
"""
import json
import re
from pathlib import Path

from .numbers import matches


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def load_citations(artifacts_dir):
    """citation number (int) -> citation dict, or None if citations.json is unusable."""
    data = _load(Path(artifacts_dir) / "citations.json")
    if not isinstance(data, dict) or not isinstance(data.get("citations"), list):
        return None
    out = {}
    for c in data["citations"]:
        m = re.fullmatch(r"\[?(\d+)\]?", str(c.get("citation_id", "")).strip())
        if m:
            out[int(m.group(1))] = c
    return out


def load_calculations(artifacts_dir):
    data = _load(Path(artifacts_dir) / "calculation_metadata.json")
    if not isinstance(data, dict) or not isinstance(data.get("calculations"), list):
        return None
    return {c.get("id"): c for c in data["calculations"] if c.get("id")}


def grade(artifacts_dir):
    details = []
    cites = load_citations(artifacts_dir)
    calcs = load_calculations(artifacts_dir)
    if cites is None or calcs is None:
        return {"citations_ok": False, "citation_count": 0, "details": ["citations.json or calculation_metadata.json unusable"]}

    numbers = sorted(cites)
    sequential = numbers == list(range(1, len(numbers) + 1))
    if not sequential:
        details.append(f"citation numbers not contiguous from 1: {numbers}")

    linked = value_ok = 0
    for n, c in cites.items():
        calc = calcs.get(c.get("calculation_id"))
        if calc is None:
            details.append(f"[{n}] points to unknown calculation_id {c.get('calculation_id')!r}")
            continue
        linked += 1
        stored = calc.get("value")
        if _same_value(c.get("value"), stored):
            value_ok += 1
        else:
            details.append(f"[{n}] value {c.get('value')!r} != metadata {stored!r}")

    calc_ids = [c.get("calculation_id") for c in cites.values()]
    duplicates = len(calc_ids) - len(set(calc_ids))
    if duplicates:
        details.append(f"{duplicates} calculation(s) cited under more than one number")

    statuses = [str(c.get("verification_status", "")).lower() for c in cites.values()]
    total = len(cites)
    return {
        "citations_ok": sequential and linked == total and value_ok == total,
        "citation_count": total,
        "calculation_count": len(calcs),
        "citation_link_rate": linked / total if total else 0.0,
        "citation_value_match_rate": value_ok / total if total else 0.0,
        "citation_sequential": sequential,
        "citation_duplicates": duplicates,
        "verified_rate": statuses.count("verified") / total if total else 0.0,
        "details": details,
    }


def _same_value(a, b):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    return matches(a, None, b, rel_tol=1e-9) or a == b
