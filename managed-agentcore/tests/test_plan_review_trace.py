"""The plan reviewer records how each review ended, and the event log keeps it.

Run from managed-agentcore/ with the project venv: .venv/bin/python -m pytest tests/
"""
import asyncio

import pytest

from src.graph import nodes
from src.utils import event_queue
from src.utils.event_log import EventLog


@pytest.fixture
def review(monkeypatch):
    event_queue.clear_queue()
    monkeypatch.setattr(nodes, "PLAN_FEEDBACK_POLL_INTERVAL", 0)
    monkeypatch.setattr(nodes, "delete_s3_feedback", lambda request_id: None)
    nodes._global_node_states["shared"] = {
        "full_plan": "1. load data", "plan_revision_count": 1, "request_id": "r1", "history": [],
    }

    def run(feedback=None, timeout=5):
        monkeypatch.setattr(nodes, "PLAN_FEEDBACK_TIMEOUT", timeout)
        monkeypatch.setattr(nodes, "check_s3_feedback", lambda request_id: feedback)
        asyncio.run(nodes.plan_reviewer_node())
        events = []
        while event_queue.has_events():
            events.append(event_queue.get_event())
        return [e for e in events if e["type"] == "plan_review_result"]

    yield run
    nodes._global_node_states.pop("shared", None)


def test_revision_request_records_feedback(review):
    [result] = review({"approved": False, "feedback": "지역별로도 나눠줘"})
    assert result["decision"] == "revision_requested"
    assert result["feedback"] == "지역별로도 나눠줘" and result["revision_count"] == 1


def test_approval(review):
    [result] = review({"approved": True})
    assert result["decision"] == "approved"


def test_timeout_auto_approves(review):
    [result] = review(None, timeout=0)
    assert result["decision"] == "auto_approved_timeout"


def test_event_log_records_plan_feedback(review, tmp_path, monkeypatch):
    [result] = review({"approved": False, "feedback": "more detail"})
    monkeypatch.setattr("src.utils.event_log.tempfile.gettempdir", lambda: str(tmp_path))
    log = EventLog("r1")
    log.add(result)
    record = __import__("json").loads(log.snapshot().decode().splitlines()[0])
    assert record["kind"] == "plan_feedback" and record["agent"] == "plan_reviewer"
    assert record["decision"] == "revision_requested" and record["feedback"] == "more detail"
