"""The runtime reports the trace and final job status on every exit path.

Run from managed-agentcore/ with the project venv: .venv/bin/python -m pytest tests/
"""
import asyncio
import json

import pytest

import agentcore_runtime as runtime


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.history = []

    def put_object(self, Bucket, Key, Body, ContentType=None):
        body = Body.decode("utf-8") if isinstance(Body, bytes) else Body
        self.objects[Key] = body
        self.history.append((Key, body))


class FakeGraph:
    def __init__(self, events, error=None):
        self.events, self.error = events, error

    async def stream_async(self, graph_input):
        for event in self.events:
            yield event
            await asyncio.sleep(0)
        if self.error:
            raise self.error
        yield {"type": "workflow_complete"}


TEXT = {"type": "agent_text_stream", "event_type": "text_chunk", "agent_name": "planner", "data": "plan"}
USAGE = {"type": "agent_usage_stream", "event_type": "usage_metadata", "agent_name": "planner",
         "model_id": "m", "input_tokens": 10, "output_tokens": 5}
TOOL = {"type": "agent_tool_stream", "event_type": "tool_use", "agent_name": "coder",
        "tool_name": "custom_interpreter_python_tool", "tool_id": "t1", "tool_input": '{"code": "1+1"}'}


@pytest.fixture
def s3(monkeypatch, tmp_path):
    fake = FakeS3()
    monkeypatch.setenv("S3_BUCKET_NAME", "bucket")
    monkeypatch.setattr("boto3.client", lambda *a, **k: fake)
    monkeypatch.setattr(runtime, "_setup_execution", lambda: None)
    # cleanup is when the container uploads artifacts; mark it in the S3 history
    monkeypatch.setattr(runtime, "_cleanup_request_session",
                        lambda request_id: fake.history.append(("<cleanup>", "")))
    monkeypatch.setattr(runtime, "_get_output_session_id", lambda request_id: "sess-1")
    monkeypatch.setattr(runtime, "_print_conversation_history", lambda: None)
    monkeypatch.setattr(runtime, "_print_token_usage_summary", lambda: None)
    monkeypatch.setattr("src.utils.event_log.tempfile.gettempdir", lambda: str(tmp_path))
    return fake


def _run(monkeypatch, graph, consume=None):
    monkeypatch.setattr(runtime, "build_graph", lambda: graph)
    payload = {"prompt": "analyze sales", "data_directory": "s3://bucket/uploads/job-1/", "job_id": "job-1"}

    async def main():
        gen = runtime.agentcore_streaming_execution(payload, None)
        if consume:
            await consume(gen)
        else:
            return [e async for e in gen]

    return asyncio.run(main())


def _status(s3):
    return json.loads(s3.objects["deep-insight/fargate_sessions/sess-1/output/job_status.json"])


TRACE_KEY = "deep-insight/traces/job-1/events.jsonl"


def _trace(s3):
    return [json.loads(line) for line in s3.objects[TRACE_KEY].splitlines()]


def test_success_reports_trace_with_tool_events_and_success(s3, monkeypatch):
    streamed = _run(monkeypatch, FakeGraph([TEXT, TOOL]))
    # tool events stay out of the response stream but are in the trace
    assert [e["type"] for e in streamed] == ["agent_text_stream", "workflow_complete"]
    assert [r["kind"] for r in _trace(s3)] == ["input", "text", "tool_use"]
    assert _trace(s3)[0]["job_id"] == "job-1"
    status = _status(s3)
    assert status["status"] == "Success" and status["job_id"] == "job-1" and status["session_id"] == "sess-1"
    assert status["trace_path"] == TRACE_KEY


def test_trace_uploaded_after_each_agent_invocation(s3, monkeypatch):
    _run(monkeypatch, FakeGraph([TEXT, USAGE, TOOL]))
    uploads = [body for key, body in s3.history if key == TRACE_KEY]
    assert len(uploads) == 2  # after the planner finished, then the final one
    assert [json.loads(l)["kind"] for l in uploads[0].splitlines()] == ["input", "text", "usage"]
    assert [r["kind"] for r in _trace(s3)] == ["input", "text", "usage", "tool_use"]
    # the final upload lands after the checkpoint, and before job_status.json
    keys = [key for key, _ in s3.history]
    assert keys[-1].endswith("job_status.json") and keys[-2] == TRACE_KEY


def test_run_without_job_id_keys_trace_by_request_id(s3, monkeypatch):
    monkeypatch.setattr(runtime, "build_graph", lambda: FakeGraph([TEXT]))
    monkeypatch.setattr(runtime, "_generate_request_id", lambda: "req-9")

    async def main():
        return [e async for e in runtime.agentcore_streaming_execution({"prompt": "q"}, None)]

    asyncio.run(main())
    assert "deep-insight/traces/req-9/events.jsonl" in s3.objects
    assert _status(s3)["job_id"] is None


def test_exception_mid_run_reports_failed(s3, monkeypatch):
    with pytest.raises(RuntimeError):
        _run(monkeypatch, FakeGraph([TEXT], error=RuntimeError("bedrock throttled")))
    status = _status(s3)
    assert status["status"] == "Failed" and "bedrock throttled" in status["error"]
    assert [r["kind"] for r in _trace(s3)] == ["input", "text"]


def test_client_disconnect_reports_failed(s3, monkeypatch):
    async def read_one_then_disconnect(gen):
        await gen.__anext__()
        await gen.aclose()

    _run(monkeypatch, FakeGraph([TEXT, TEXT, TEXT]), consume=read_one_then_disconnect)
    status = _status(s3)
    assert status["status"] == "Failed" and "client disconnected" in status["error"]


def test_disconnect_after_success_keeps_success(s3, monkeypatch):
    async def read_until_final_then_disconnect(gen):
        async for event in gen:
            if event["type"] == "workflow_complete":
                await gen.aclose()
                return

    _run(monkeypatch, FakeGraph([TEXT]), consume=read_until_final_then_disconnect)
    assert _status(s3)["status"] == "Success"


@pytest.mark.parametrize("error", [None, RuntimeError("boom")])
def test_job_status_written_after_cleanup(s3, monkeypatch, error):
    # The Lambda lists artifacts when job_status.json lands; they are uploaded at cleanup
    try:
        _run(monkeypatch, FakeGraph([TEXT], error=error))
    except RuntimeError:
        pass
    keys = [key for key, _ in s3.history]
    assert keys.index("<cleanup>") < keys.index("deep-insight/fargate_sessions/sess-1/output/job_status.json")
    assert keys.count("<cleanup>") == 1


@pytest.fixture
def tokens(monkeypatch):
    from src.graph import nodes
    monkeypatch.setitem(nodes._global_node_states, "shared", {"token_usage": {
        "total_tokens": 150, "total_input_tokens": 100, "total_output_tokens": 50,
        "cache_read_input_tokens": 0, "cache_write_input_tokens": 0, "by_agent": {}}})


def test_failed_run_writes_no_token_usage_file(s3, monkeypatch, tokens):
    # Ops Lambdas that predate job_status.json read token_usage.json as "succeeded"
    with pytest.raises(RuntimeError):
        _run(monkeypatch, FakeGraph([TEXT], error=RuntimeError("boom")))
    assert not any(k.endswith("token_usage.json") for k in s3.objects)
    status = _status(s3)
    assert status["status"] == "Failed" and status["token_usage"]["total_tokens"] == 150


def test_successful_run_writes_token_usage_file(s3, monkeypatch, tokens):
    _run(monkeypatch, FakeGraph([TEXT]))
    assert "deep-insight/fargate_sessions/sess-1/output/token_usage.json" in s3.objects
    assert _status(s3)["token_usage"] is None


def test_failure_while_setting_up_the_trace_still_reports(s3, monkeypatch):
    # EventLog/uploader setup is inside the try: the finally still reports and cleans up
    def broken(request_id):
        raise OSError("disk full")
    monkeypatch.setattr(runtime, "EventLog", broken)
    with pytest.raises(OSError):
        _run(monkeypatch, FakeGraph([TEXT]))
    status = _status(s3)
    assert status["status"] == "Failed" and "disk full" in status["error"] and status["trace_path"] == ""
    assert "<cleanup>" in [k for k, _ in s3.history]
