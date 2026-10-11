"""Tests for src/utils/event_log.py. Run from managed-agentcore/: python -m pytest tests/"""
import json

import pytest

from src.utils import event_log as event_log_module
from src.utils.event_log import EventLog


def _text(agent, data):
    return {"type": "agent_text_stream", "event_type": "text_chunk", "agent_name": agent, "data": data}


def _tool_use(agent, tool_id, tool_input, name="custom_interpreter_python_tool"):
    return {"type": "agent_tool_stream", "event_type": "tool_use", "agent_name": agent,
            "tool_name": name, "tool_id": tool_id, "tool_input": tool_input}


def _records(log):
    log.close()
    with open(log.path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(event_log_module.tempfile, "gettempdir", lambda: str(tmp_path))
    return EventLog("req-1")


def test_merges_consecutive_text_of_one_agent(log):
    for chunk in ["Hel", "lo", " world"]:
        log.add(_text("planner", chunk))
    log.add(_text("supervisor", "next"))
    records = _records(log)
    assert [(r["agent"], r["text"]) for r in records] == [("planner", "Hello world"), ("supervisor", "next")]
    assert [r["seq"] for r in records] == [1, 2]


def test_tool_use_keeps_final_parsed_input(log):
    log.add(_tool_use("coder", "t1", '{"code": "print('))
    log.add(_tool_use("coder", "t1", '{"code": "print(1)"}'))
    log.add({"type": "agent_tool_stream", "event_type": "tool_result", "agent_name": "coder",
             "tool_name": "custom_interpreter_python_tool", "tool_id": "t1", "output": "1"})
    records = _records(log)
    assert [r["kind"] for r in records] == ["tool_use", "tool_result"]
    assert records[0]["input"] == {"code": "print(1)"}
    assert records[1]["output"] == "1"


def test_unfinished_tool_input_stays_raw(log):
    log.add(_tool_use("coder", "t1", '{"code": "pri'))
    assert _records(log)[0]["input"] == '{"code": "pri'


def test_keeps_only_per_invocation_usage(log):
    base = {"type": "agent_usage_stream", "event_type": "usage_metadata", "agent_name": "coder",
            "input_tokens": 10, "output_tokens": 5}
    log.add(base)  # per model call, no model_id
    log.add({**base, "model_id": "m", "input_tokens": 30})
    records = _records(log)
    assert len(records) == 1
    assert records[0]["kind"] == "usage" and records[0]["input_tokens"] == 30


def test_records_input_and_plan_review_and_skips_keepalives(log):
    log.record_input(prompt="analyze", job_id="job-1")
    log.add({"type": "plan_review_request", "event_type": "plan_review_request", "plan": "1. load", "revision_count": 0})
    log.add({"type": "plan_review_keepalive", "event_type": "plan_review_keepalive", "elapsed_seconds": 6})
    log.add({"type": "workflow_complete"})
    records = _records(log)
    assert [r["kind"] for r in records] == ["input", "plan_review"]
    assert records[0]["job_id"] == "job-1" and records[1]["plan"] == "1. load"


def test_caps_long_fields(log, monkeypatch):
    monkeypatch.setattr(event_log_module, "MAX_FIELD_CHARS", 10)
    log.add(_tool_use("coder", "t1", {"code": "x" * 25}))
    code = _records(log)[0]["input"]["code"]
    assert code.startswith("x" * 10) and "15 more chars" in code


def test_bad_event_does_not_raise(log):
    log.add({"event_type": "text_chunk", "agent_name": "a", "data": None})
    log.add(_text("a", "ok"))
    assert [r["text"] for r in _records(log)] == ["ok"]


def test_discard_removes_file_and_close_is_idempotent(log):
    log.add(_text("a", "x"))
    log.close()
    log.close()
    log.discard()
    import os
    assert not os.path.exists(log.path)


def test_snapshot_keeps_open_record_whole(log):
    log.add(_text("reporter", "Hello"))
    first = [json.loads(l) for l in log.snapshot().decode().splitlines()]
    log.add(_text("reporter", " world"))
    records = _records(log)
    assert first[-1]["text"] == "Hello"
    assert [r["text"] for r in records] == ["Hello world"]  # not split by the snapshot


class _S3:
    def __init__(self):
        self.puts = []

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.puts.append(Body.decode())


def test_checkpoint_uploads_only_changes_and_stops_after_finish(log):
    from src.utils.event_log import TraceUploader
    s3 = _S3()
    up = TraceUploader(log, s3, "b", "k")
    log.add(_text("reporter", "a"))
    up.checkpoint()
    up.checkpoint()  # unchanged: skipped
    log.add(_text("reporter", "b"))  # open record grew
    up.checkpoint()
    assert up.finish()
    up.checkpoint()  # after finish: ignored
    assert [json.loads(p.splitlines()[-1])["text"] for p in s3.puts] == ["a", "ab", "ab"]


def test_periodic_checkpoints(log):
    import asyncio
    from src.utils.event_log import TraceUploader
    s3 = _S3()
    up = TraceUploader(log, s3, "b", "k")

    async def run():
        task = asyncio.create_task(up.checkpoint_periodically(0.01))
        log.add(_text("reporter", "long running"))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())
    up.finish()
    assert len(s3.puts) == 2  # one periodic (then unchanged), one final


def test_agent_start_end_and_last_text(log):
    log.add({"type": "agent_start", "event_type": "agent_start", "agent_name": "coder", "input": "Load the data"})
    log.add(_text("coder", "Done: 836 rows"))
    log.add({"type": "agent_end", "event_type": "agent_end", "agent_name": "coder", "error": None})
    log.add(_text("supervisor", "  "))  # blank text doesn't replace the answer
    assert log.last_text == "Done: 836 rows"
    records = _records(log)
    assert [r["kind"] for r in records] == ["agent_start", "text", "agent_end", "text"]
    assert records[0]["input"] == "Load the data" and records[2]["error"] is None
    assert log.last_text == "Done: 836 rows"


def test_heartbeat_uploads_an_unchanged_log(log, monkeypatch):
    # the trace's last-modified time is the job's heartbeat for the stale-job sweep
    from src.utils import event_log as module
    s3 = _S3()
    up = module.TraceUploader(log, s3, "b", "k")
    clock = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    log.add(_text("coder", "waiting"))
    up.checkpoint()
    clock[0] += 60
    up.checkpoint()  # unchanged, heartbeat not due
    clock[0] += module.HEARTBEAT_SECONDS
    up.checkpoint()  # unchanged, heartbeat due
    up.finish()
    assert len(s3.puts) == 3
