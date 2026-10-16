"""Code-execution grader: how often the agents' code failed in the Fargate sandbox.

The runtime doesn't stream tool calls to the client, but the code executor
writes one debug/execution_<n>.json per run of agent code (status, error,
stderr). Failures the agents recovered from still cost tokens and time, so
they are counted even when the run ends well.
"""
import json
import re
from collections import Counter
from pathlib import Path

# Coarse buckets for failure causes, matched against stderr/stdout tail.
CAUSES = [
    ("missing_file", re.compile(r"No such file or directory|FileNotFoundError|cannot access|cannot open")),
    ("attribute_error", re.compile(r"AttributeError")),
    ("import_error", re.compile(r"ModuleNotFoundError|ImportError")),
    ("key_error", re.compile(r"KeyError")),
    ("type_value_error", re.compile(r"TypeError|ValueError")),
    ("timeout", re.compile(r"[Tt]imed? ?out")),
]


def debug_dir(run_dir):
    for d in (Path(run_dir) / "s3" / "debug", Path(run_dir) / "debug"):
        if d.is_dir():
            return d
    return None


def grade(run_dir):
    d = debug_dir(run_dir)
    if d is None:
        return {"details": ["no debug/ folder (code execution logs not downloaded)"]}
    runs = []
    for p in d.glob("execution_*.json"):
        try:
            runs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    if not runs:
        return {"code_executions": 0, "details": ["debug/ has no execution_*.json"]}
    failed = [r for r in runs if r.get("status") != "completed"]
    causes = Counter()
    details = []
    for r in sorted(failed, key=lambda r: r.get("execution_num", 0)):
        text = f"{r.get('stderr') or ''}\n{r.get('stdout') or ''}"
        cause = next((name for name, rx in CAUSES if rx.search(text)), "other")
        causes[cause] += 1
        tail = text.strip().splitlines()[-1][:160] if text.strip() else (r.get("error") or {}).get("message", "")
        details.append(f"#{r.get('execution_num')} {cause}: {tail}")
    return {
        "code_executions": len(runs),
        "code_exec_failed": len(failed),
        "code_exec_fail_rate": len(failed) / len(runs),
        "code_exec_time_s": round(sum(r.get("execution_time_ms", 0) or 0 for r in runs) / 1000, 1),
        "code_exec_fail_causes": dict(causes),
        "details": details,
    }
