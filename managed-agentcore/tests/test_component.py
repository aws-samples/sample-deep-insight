"""Component runs (src/graph/component.py): refused outside the eval runtime, and
one agent runs on staged artifacts with the same event stream as a full run.

Run from managed-agentcore/: .venv/bin/python -m unittest tests.test_component
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.graph import component  # noqa: E402
from src.utils.event_queue import clear_queue, put_event  # noqa: E402

PAYLOAD = {"component": "validator", "data_directory": "s3://b/uploads/eval-x/", "full_plan": "# Plan",
           "artifacts_directory": "s3://b/uploads/eval-x-artifacts/", "prompt": "분석해줘"}


class FakeSession:
    def __init__(self):
        self.calls = []

    def ensure_session_with_directory(self, d):
        self.calls.append(("data", d))
        return True

    def stage_artifacts(self, d):
        self.calls.append(("artifacts", d))
        return True


async def _collect(runner, task):
    return [e async for e in runner.stream_async(task)]


class Refusal(unittest.TestCase):
    def test_refused_without_eval_mode(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EVAL_COMPONENT_MODE", None)
            self.assertIn("eval runtime", component.check_component_payload(PAYLOAD))

    def test_payload_checks(self):
        with mock.patch.dict(os.environ, {"EVAL_COMPONENT_MODE": "1"}):
            self.assertIsNone(component.check_component_payload(PAYLOAD))
            self.assertIn("one of", component.check_component_payload({**PAYLOAD, "component": "coder"}))
            self.assertIn("full_plan", component.check_component_payload({**PAYLOAD, "full_plan": ""}))
            self.assertIn("s3://", component.check_component_payload({**PAYLOAD, "artifacts_directory": "./a"}))
        self.assertFalse(component.component_requested({"prompt": "x"}))


class Run(unittest.TestCase):
    def setUp(self):
        clear_queue()

    def _run(self, result="done", events=()):
        session = FakeSession()
        seen = {}

        def handler(text):
            from src.graph.nodes import _global_node_states
            seen["shared"] = dict(_global_node_states["shared"])
            seen["text"] = text
            for e in events:
                put_event(e)
            return result

        with mock.patch("src.tools.global_fargate_coordinator.get_global_session", return_value=session), \
                mock.patch.object(component, "_handler", return_value=handler):
            task = {"request": "분석해줘", "request_prompt": "AgentCore Request: 분석해줘", "data_directory": PAYLOAD["data_directory"],
                    "request_id": "r1"}
            out = asyncio.run(_collect(component.ComponentRunner(PAYLOAD), task))
        return out, session, seen

    def test_stages_then_runs_the_agent_and_streams_its_events(self):
        usage = {"type": "agent_usage_stream", "agent_name": "validator", "event_type": "usage_metadata"}
        out, session, seen = self._run(events=[usage])
        self.assertEqual(session.calls, [("data", PAYLOAD["data_directory"]), ("artifacts", PAYLOAD["artifacts_directory"])])
        self.assertEqual(out[0], usage)
        self.assertEqual(out[-1]["type"], "workflow_complete")
        self.assertEqual(seen["shared"]["full_plan"], "# Plan")
        self.assertEqual(seen["text"], component.DEFAULT_TASK["validator"])
        self.assertEqual(seen["shared"]["messages"][0]["content"][0]["text"], seen["text"])

    def test_agent_error_raises_and_does_not_complete(self):
        with self.assertRaises(RuntimeError):
            self._run(result="Error: No shared state available")


if __name__ == "__main__":
    unittest.main()
