"""Auditor grader: reads the Auditor's own verdict on the final report."""
import json
from pathlib import Path


def grade(artifacts_dir):
    p = Path(artifacts_dir) / "audit_findings.json"
    if not p.is_file():
        return {"audit_present": False, "details": ["no audit_findings.json (Auditor not run or not in this version)"]}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"audit_present": False, "details": [f"audit_findings.json unreadable: {e}"]}
    stats = data.get("stats", {}) or {}
    verdict = str(data.get("verdict", "")).lower()
    return {
        "audit_present": True,
        "audit_verdict": verdict,
        "audit_pass": verdict == "pass",
        "audit_block_findings": int(stats.get("type_b", 0)) + int(stats.get("type_c", 0)),
        "audit_warn_findings": int(stats.get("type_a", 0)) + int(stats.get("type_d", 0)),
        "audit_retry_count": (data.get("audit_metadata") or {}).get("retry_count"),
        "details": [],
    }
