"""Completion grader: did the run produce the files a finished run must have."""
import json
from pathlib import Path

# Files every finished run must produce. The Auditor artifacts only exist on
# versions that ship the Auditor agent, so they are reported but not required.
REQUIRED = [
    "final_report_with_citations.docx",
    "citations.json",
    "calculation_metadata.json",
    "validation_report.txt",
]
OPTIONAL = ["audit_findings.json", "audit_report.txt", "final_report.docx"]


def _docx_opens(path):
    try:
        import docx
        docx.Document(str(path))
        return True
    except Exception:
        return False


def _json_loads(path):
    try:
        json.loads(Path(path).read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def grade(artifacts_dir):
    d = Path(artifacts_dir)
    details = []
    present = {name: (d / name).is_file() and (d / name).stat().st_size > 0 for name in REQUIRED + OPTIONAL}
    for name in REQUIRED:
        if not present[name]:
            details.append(f"missing required artifact: {name}")

    readable = True
    for name in REQUIRED:
        p = d / name
        if not present[name]:
            continue
        ok = _docx_opens(p) if name.endswith(".docx") else _json_loads(p) if name.endswith(".json") else True
        if not ok:
            readable = False
            details.append(f"unreadable artifact: {name}")

    charts = len(list(d.glob("*.png")))
    n_required = sum(present[n] for n in REQUIRED)
    return {
        "required_present": n_required,
        "required_total": len(REQUIRED),
        "required_rate": n_required / len(REQUIRED),
        "all_required_ok": n_required == len(REQUIRED) and readable,
        "has_audit": present["audit_findings.json"],
        "chart_count": charts,
        "details": details,
    }
