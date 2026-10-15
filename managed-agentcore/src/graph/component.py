"""Component runs: one agent on a saved run's artifacts, for the eval harness.

A full run reaches the Validator only after the Coder, and the Reporter only
after the Validator, so measuring one of them means paying for the agents
before it and accepting whatever they produced. A component run starts the
agent where a full run would have reached it: the data files arrive as usual,
the artifacts the earlier agents wrote are staged into ./artifacts/, the
shared state carries the request and plan, and the agent's tool handler runs
exactly as the Supervisor would call it. eval-harness/component_eval.py builds
these runs from saved ones, with errors planted where it wants to see whether
they are caught.

Payload (besides prompt and data_directory, as for a full run):
    component            "validator" or "reporter"
    artifacts_directory  s3:// folder with the saved run's artifacts
    full_plan            the plan the agent works from
    task                 the message the agent gets (a full run passes the
                         previous agent's response; optional)

Both runtimes run the same image, so this is refused unless the runtime's
environment has EVAL_COMPONENT_MODE=1, which only the eval runtime has
(eval-harness/eval_runtime.py sets it).
"""
import asyncio
import os

from src.utils.common_utils import get_message_from_string
from src.utils.event_queue import get_event, has_events

COMPONENTS = ("validator", "reporter")
DEFAULT_TASK = {
    "validator": "Validate the calculations in ./artifacts/calculation_metadata.json against the data, then write "
                 "./artifacts/citations.json and ./artifacts/validation_report.txt.",
    "reporter": "Write the final report from ./artifacts/ (calculation_metadata.json, citations.json, charts) "
                "as the plan asks.",
}


def component_requested(payload):
    return bool(payload.get("component"))


def check_component_payload(payload):
    """Why a component payload is refused, or None."""
    if os.getenv("EVAL_COMPONENT_MODE") != "1":
        return "component runs are only allowed on the eval runtime (EVAL_COMPONENT_MODE=1)"
    if payload.get("component") not in COMPONENTS:
        return f"component must be one of {', '.join(COMPONENTS)}, not {payload.get('component')!r}"
    for key in ("artifacts_directory", "data_directory", "full_plan"):
        if not payload.get(key):
            return f"component run needs {key}"
    if not str(payload["artifacts_directory"]).startswith("s3://"):
        return "artifacts_directory must be an s3:// URL"
    return None


def _handler(name):
    if name == "validator":
        from src.tools.validator_agent_custom_interpreter_tool import _handle_validator_agent_custom_interpreter_tool
        return _handle_validator_agent_custom_interpreter_tool
    from src.tools.reporter_agent_custom_interpreter_tool import _handle_reporter_agent_custom_interpreter_tool
    return _handle_reporter_agent_custom_interpreter_tool


class ComponentRunner:
    """Same stream_async contract as the workflow graph, for one agent."""

    def __init__(self, payload):
        self.payload = payload
        self.name = payload["component"]

    def _run(self, task):
        from src.graph.nodes import _global_node_states
        from src.tools.global_fargate_coordinator import get_global_session

        request = task.get("request", "")
        text = self.payload.get("task") or DEFAULT_TASK[self.name]
        _global_node_states["shared"] = {
            "request": request,
            "request_prompt": task.get("request_prompt", request),
            "full_plan": self.payload["full_plan"],
            "data_directory": task.get("data_directory"),
            "request_id": task.get("request_id", ""),
            "messages": [get_message_from_string(role="user", string=text, imgs=[])],
            "clues": "",
            "history": [],
        }
        session = get_global_session()
        if not session.ensure_session_with_directory(task["data_directory"]):
            raise RuntimeError("component run: data upload failed")
        if not session.stage_artifacts(self.payload["artifacts_directory"]):
            raise RuntimeError("component run: staging artifacts failed")
        result = _handler(self.name)(text)
        if isinstance(result, str) and result.startswith("Error"):
            raise RuntimeError(f"component run: {self.name} failed: {result[:300]}")
        return result

    async def stream_async(self, task):
        work = asyncio.create_task(asyncio.to_thread(self._run, task))  # the handler calls asyncio.run itself
        try:
            while not work.done():
                while has_events():
                    yield get_event()
                await asyncio.sleep(0.005)
            work.result()  # raise the agent's error here, after its events
        finally:
            while has_events():
                yield get_event()
        yield {"type": "workflow_complete", "message": f"component run: {self.name}"}
