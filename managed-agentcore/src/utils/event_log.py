"""
Event log: the full agent trace of one request, for the ops dashboard.

The response stream carries only STREAM_EVENT_TYPES (agentcore_runtime.py);
tool calls and their results never leave the runtime. This log records every
graph event before that filter, in a compact form:
  - consecutive text / reasoning chunks of one agent become one record
  - the streamed updates of one tool call collapse to its final input
  - string fields are capped at MAX_FIELD_CHARS
Records are appended to a local file as they complete, so memory stays flat
however long the run is. TraceUploader puts the log to S3 each time an agent
invocation finishes, every CHECKPOINT_SECONDS while it changes (one agent can
run for many minutes), and once more at teardown. The dashboard can follow a
running job, and a runtime that dies mid-run still leaves its trace behind.

Record kinds (one JSON object per line, in order):
  input        prompt, data_directory, job_id, request_id
  agent_start  an agent invocation begins: input (the message the agent got)
  agent_end    the invocation ended: error (None on success)
  text         agent response text
  reasoning    agent reasoning text
  tool_use     tool, tool_id, input (parsed JSON when possible)
  tool_result  tool, tool_id, output
  usage        model_id and token counts of one agent invocation
  plan_review  plan shown to the user, revision_count
  plan_feedback  how the review ended: decision, feedback, revision_count,
               waited_seconds
"""

import asyncio
import json
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MAX_FIELD_CHARS = 50_000
CHECKPOINT_SECONDS = 30
# Re-upload at least this often, changed or not: the trace's last-modified time
# is the job's heartbeat for the ops stale-job sweep (agents can sit silent for
# minutes: a HITL wait, a long code execution)
HEARTBEAT_SECONDS = 300


def _now() -> str:
    return datetime.now().isoformat()


def _cap(value: Any) -> Any:
    """Cap every string inside value at MAX_FIELD_CHARS."""
    if isinstance(value, str):
        if len(value) <= MAX_FIELD_CHARS:
            return value
        return value[:MAX_FIELD_CHARS] + f"\n... [{len(value) - MAX_FIELD_CHARS:,} more chars]"
    if isinstance(value, dict):
        return {k: _cap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v) for v in value]
    return value


def _parse_tool_input(raw: Any) -> Any:
    """Streamed tool input is the JSON text received so far; parse it when complete."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


class EventLog:
    def __init__(self, request_id: str):
        self.path = os.path.join(tempfile.gettempdir(), f"events_{request_id}.jsonl")
        self._file = open(self.path, "w", encoding="utf-8")
        self._seq = 0
        self._pending: Optional[Dict[str, Any]] = None
        self._last_text = ""

    def record_input(self, **fields) -> None:
        self._write({"kind": "input", "ts": _now(), **fields})

    def add(self, event: Dict[str, Any]) -> None:
        """Record one graph event. Never raises: the trace must not break a run."""
        try:
            self._add(event)
        except Exception as e:
            logger.warning(f"Event log: skipped an event ({e})")

    def _add(self, event: Dict[str, Any]) -> None:
        kind = event.get("event_type") or event.get("type")
        agent = event.get("agent_name", "")
        ts = event.get("timestamp") or _now()
        pending = self._pending

        if kind in ("text_chunk", "reasoning"):
            record_kind = "text" if kind == "text_chunk" else "reasoning"
            text = str((event.get("data") if kind == "text_chunk" else event.get("reasoning_text")) or "")
            if pending and pending["kind"] == record_kind and pending["agent"] == agent:
                pending["text"] += text
                pending["end_ts"] = ts
                return
            self._flush()
            self._pending = {"kind": record_kind, "agent": agent, "ts": ts, "end_ts": ts, "text": text}

        elif kind == "tool_use":
            tool_id = event.get("tool_id")
            if pending and pending["kind"] == "tool_use" and pending["tool_id"] == tool_id:
                pending["input"] = event.get("tool_input")
                return
            self._flush()
            self._pending = {
                "kind": "tool_use", "agent": agent, "ts": ts,
                "tool": event.get("tool_name", ""), "tool_id": tool_id,
                "input": event.get("tool_input"),
            }

        elif kind == "tool_result":
            self._flush()
            self._write({
                "kind": "tool_result", "agent": agent, "ts": ts,
                "tool": event.get("tool_name", ""), "tool_id": event.get("tool_id"),
                "output": event.get("output", ""),
            })

        # Two usage events exist per agent: one per model call from the stream
        # (no model_id) and one per invocation from the agent's metrics. Keep
        # only the latter so tokens aren't counted twice.
        elif kind == "usage_metadata" and "model_id" in event:
            self._flush()
            self._write({
                "kind": "usage", "agent": agent, "ts": ts,
                "model_id": event.get("model_id"),
                "input_tokens": event.get("input_tokens", 0),
                "output_tokens": event.get("output_tokens", 0),
                "cache_read_input_tokens": event.get("cache_read_input_tokens", 0),
                "cache_write_input_tokens": event.get("cache_write_input_tokens", 0),
            })

        elif kind == "plan_review_request":
            self._flush()
            self._write({
                "kind": "plan_review", "agent": "plan_reviewer", "ts": ts,
                "plan": event.get("plan", ""),
                "revision_count": event.get("revision_count", 0),
            })

        elif kind == "agent_start":
            self._flush()
            self._write({"kind": "agent_start", "agent": agent, "ts": ts, "input": event.get("input", "")})

        elif kind == "agent_end":
            self._flush()
            self._write({"kind": "agent_end", "agent": agent, "ts": ts, "error": event.get("error")})

        elif kind == "plan_review_result":
            self._flush()
            self._write({
                "kind": "plan_feedback", "agent": "plan_reviewer", "ts": ts,
                "decision": event.get("decision", ""),
                "feedback": event.get("feedback", ""),
                "revision_count": event.get("revision_count", 0),
                "waited_seconds": event.get("waited_seconds", 0),
            })

    @property
    def last_text(self) -> str:
        """The most recent agent response text: the run's final answer at the end."""
        if self._pending and self._pending["kind"] == "text" and self._pending["text"].strip():
            return self._pending["text"]
        return self._last_text

    def _flush(self) -> None:
        if self._pending is None:
            return
        record, self._pending = self._pending, None
        if record["kind"] == "text" and record["text"].strip():
            self._last_text = record["text"]
        if record["kind"] == "tool_use":
            record["input"] = _parse_tool_input(record["input"])
        self._write(record)

    def _write(self, record: Dict[str, Any]) -> None:
        self._seq += 1
        line = json.dumps({"seq": self._seq, **_cap(record)}, ensure_ascii=False, default=str)
        self._file.write(line + "\n")

    @property
    def version(self):
        """Changes whenever the log does (new record, or the open record grows)."""
        pending = self._pending
        size = len(pending.get("text", "")) if pending else 0
        return (self._seq, pending is not None, size, str(pending.get("input")) if pending else "")

    @staticmethod
    def ends_agent_invocation(event: Dict[str, Any]) -> bool:
        """True for the usage event an agent emits once its invocation finishes."""
        return event.get("event_type") == "usage_metadata" and "model_id" in event

    def snapshot_ref(self):
        """A cheap handle on the log as it is now: (path, size, open record).

        Taken on the event loop; read_snapshot() does the file I/O elsewhere.
        The first `size` bytes are complete lines, so appends made after this
        call don't affect what is read. The open record is serialized without
        closing it, so a snapshot taken mid-response doesn't split it.
        """
        self._file.flush()
        tail = b""
        if self._pending is not None:
            record = dict(self._pending)
            if record["kind"] == "tool_use":
                record["input"] = _parse_tool_input(record["input"])
            tail = (json.dumps({"seq": self._seq + 1, **_cap(record)}, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        return self.path, self._file.tell(), tail

    @staticmethod
    def read_snapshot(ref) -> bytes:
        path, size, tail = ref
        with open(path, "rb") as f:
            return f.read(size) + tail

    def snapshot(self) -> bytes:
        """Everything recorded so far, plus the record still being merged."""
        return self.read_snapshot(self.snapshot_ref())

    def close(self) -> None:
        """Flush the last record and close the file. Safe to call twice."""
        if self._file.closed:
            return
        try:
            self._flush()
        finally:
            self._file.close()

    def discard(self) -> None:
        self.close()
        try:
            os.remove(self.path)
        except OSError:
            pass


class TraceUploader:
    """Puts the event log to one S3 key, during the run and at the end.

    S3 has no append, so each upload replaces the object with the whole log.
    Uploads run on a single worker thread: the stream isn't blocked, and they
    land in order, so an older snapshot never overwrites a newer one.
    """

    def __init__(self, event_log: EventLog, s3_client, bucket: str, key: str):
        self.event_log = event_log
        self.s3_client = s3_client
        self.bucket = bucket
        self.key = key
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trace-upload")
        self._uploaded_version = None
        self._uploaded_at = 0.0
        self._finished = False

    def checkpoint(self) -> None:
        """Queue an upload of the log as it is now, if it changed or the
        heartbeat is due. Never raises."""
        if self._finished:
            return
        try:
            version = self.event_log.version
            heartbeat_due = time.monotonic() - self._uploaded_at >= HEARTBEAT_SECONDS
            if version == self._uploaded_version and not heartbeat_due:
                return
            self._uploaded_version = version
            self._uploaded_at = time.monotonic()
            # File read and upload on the worker thread: the event loop only
            # takes the handle, so the stream isn't held up by large logs
            ref = self.event_log.snapshot_ref()
            self._executor.submit(lambda: self._put(EventLog.read_snapshot(ref)))
        except Exception as e:
            logger.warning(f"Trace checkpoint skipped ({e})")

    async def checkpoint_periodically(self, interval: float = CHECKPOINT_SECONDS) -> None:
        """Checkpoint every interval until cancelled.

        Runs on the event loop that feeds the log, so it never reads the log
        while an event is being added.
        """
        while True:
            await asyncio.sleep(interval)
            self.checkpoint()

    def finish(self) -> bool:
        """Wait for queued uploads, then upload the complete log. True on success."""
        self._finished = True
        self._executor.shutdown(wait=True)
        self.event_log.close()
        with open(self.event_log.path, "rb") as f:
            return self._put(f.read())

    def _put(self, body: bytes) -> bool:
        try:
            self.s3_client.put_object(Bucket=self.bucket, Key=self.key, Body=body,
                                      ContentType="application/x-ndjson")
            return True
        except Exception as e:
            logger.warning(f"Trace upload to s3://{self.bucket}/{self.key} failed ({e})")
            return False
