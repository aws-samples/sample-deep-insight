"""Run the four evaluator scripts sequentially in one AgentCore invocation."""
import asyncio
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = {
    "rules": "graders/rules.py",
    "factcheck": "graders/factcheck.py",
    "judge": "graders/judge.py",
    "pairwise": "graders/pairwise.py",
}


async def execute_evaluator(payload, context=None):
    name = payload.get("evaluator")
    if name not in SCRIPTS:
        raise ValueError("Unknown evaluator")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 64:
        raise ValueError("A request_id of 1–64 characters is required")
    script = ROOT / SCRIPTS[name]
    started = datetime.now(timezone.utc).isoformat()
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(script), cwd=str(ROOT),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        timed_out = True
        process.kill()
        stdout, stderr = await process.communicate()
        stderr += b"\nEvaluator exceeded 30 seconds"
    return {
        "type": "evaluation_complete",
        "execution_environment": "agentcore-runtime",
        "evaluator": name,
        "script": SCRIPTS[name],
        "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        "request_id": request_id,
        "runtime_session_id": getattr(context, "session_id", None),
        "code_revision": os.environ.get("EVAL_CODE_REVISION", "unknown"),
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "returncode": 124 if timed_out else process.returncode,
        "stdout": stdout.decode("utf-8"),
        "stderr": stderr.decode("utf-8"),
    }


async def execute_evaluators(payload, context=None):
    if payload.get("evaluators") != list(SCRIPTS):
        raise ValueError("Expected all four evaluators in order: rules, factcheck, judge, pairwise")
    results = []
    for name in SCRIPTS:
        results.append(await execute_evaluator(
            {"evaluator": name, "request_id": payload.get("request_id")}, context,
        ))
    return {
        "type": "evaluation_complete",
        "execution_environment": "agentcore-runtime",
        "request_id": payload["request_id"],
        "runtime_session_id": getattr(context, "session_id", None),
        "results": results,
    }


async def invoke(payload, context):
    if "evaluators" in payload:
        yield await execute_evaluators(payload, context)
        return
    # Keep existing analysis invocations working on the evaluation runtime.
    sys.path.insert(0, str(ROOT.parent))
    from agentcore_runtime import agentcore_streaming_execution
    async for event in agentcore_streaming_execution(payload, context):
        yield event


def main():
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
    app = BedrockAgentCoreApp()
    app.entrypoint(invoke)
    app.run()


if __name__ == "__main__":
    main()
