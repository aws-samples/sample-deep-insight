"""
Deep Insight Web — FastAPI server for the Deep Insight data analysis system.

Provides a web interface for uploading data, invoking AgentCore Runtime,
handling HITL plan review, and downloading generated reports.
"""

import json
import logging
import os
import queue
import threading
import uuid
from datetime import datetime
from pathlib import Path

import boto3
import uvicorn
from botocore.config import Config
from dotenv import load_dotenv
import re
import unicodedata
from urllib.parse import quote

from ops.job_tracker import track_job_start, track_job_link, track_job_failure
from ops.admin_router import admin_router
from chat_agent import (
    session_manager as chat_session_manager,
    LOCAL_UPLOAD_DIR,
    generate_suggestions,
    execute_sql_for_session,
)

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

try:
    _env_path = Path(__file__).resolve().parents[1] / "managed-agentcore" / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except (IndexError, OSError):
    pass  # Running in container — env vars injected by ECS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RUNTIME_ARN = os.environ.get("RUNTIME_ARN", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "")
WEB_UTILITY_MODEL_ID = os.environ.get("WEB_UTILITY_MODEL_ID") or "global.anthropic.claude-sonnet-4-6"

STATIC_DIR = Path(__file__).resolve().parent / "static"
SAMPLE_DATA_DIR = Path(__file__).resolve().parent / "sample_data"
SAMPLE_REPORTS_DIR = Path(__file__).resolve().parent / "sample_reports"

HOST = "0.0.0.0"
PORT = 8080

app = FastAPI()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(admin_router)


# ---------- Feature 1: Health check ----------


@app.get("/health")
def health():
    """ALB health check endpoint."""
    return {"status": "healthy"}


# ---------- Sample data endpoints ----------

_SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
# Allowed pattern for upload/session/request IDs: UUID-like (alphanumeric +
# hyphen/underscore). Defined here at module scope so all request models can
# share it. Anchored in the validators (Pydantic uses `re.search` by default).
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_MAX_ID_LEN = 64


def _validate_id(value: str, field: str = "id") -> str:
    """Reject IDs that don't match _SAFE_ID. Used by both Pydantic validators
    and FastAPI query parameters. Returns the value unchanged if valid.

    Without this, callers could submit `upload_id="../foo"` (local-mode path
    traversal) or another user's UUID (S3-mode IDOR via /chat/meta /
    /sql/execute / /chat). UUIDs are unguessable but leak via browser
    history, ALB logs, and admin DynamoDB rows, so structural validation
    is the durable defense.
    """
    if not isinstance(value, str) or not value or len(value) > _MAX_ID_LEN \
            or not _SAFE_ID.match(value):
        raise ValueError(f"Invalid {field}")
    return value


_MAX_FILENAME_LEN = 255


def _sanitize_filename(name: str) -> str:
    """Reduce a user-supplied filename to a safe basename.

    The browser-supplied `data_file.filename` flows into both S3 keys and the
    local on-disk path (`LOCAL_UPLOAD_DIR / upload_id / name`), and from there
    into `chat_agent.py:_load_data_locked` which constructs
    `tmp_path = LOCAL_UPLOAD_DIR / self.upload_id / f"_chat_{name}"`. Without
    sanitization a filename like `../../etc/passwd` or `foo/../../bar.csv`
    escapes the upload directory.

    Strategy: NFC-normalize, strip all directory separators by taking the
    basename, reject empty / dot-only names, cap length, reject control chars
    and NUL bytes. Returns the cleaned name or raises ValueError.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("Empty filename")
    normalized = unicodedata.normalize("NFC", name)
    # Take the basename — drops any directory components a hostile client put
    # in the multipart filename. PurePosixPath handles forward slashes; we
    # also explicitly strip backslashes for Windows-style payloads.
    basename = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    # Reject "..", ".", empty after stripping, or NUL/control bytes.
    if not basename or basename in (".", "..") \
            or any(ord(c) < 32 for c in basename) \
            or "\x00" in basename:
        raise ValueError("Invalid filename")
    if len(basename) > _MAX_FILENAME_LEN:
        raise ValueError("Filename too long")
    return basename


@app.get("/sample-data")
def list_sample_data():
    """List available sample datasets from the sample_data/ directory."""
    datasets = []
    if not SAMPLE_DATA_DIR.exists():
        return {"datasets": datasets}

    for dataset_dir in sorted(SAMPLE_DATA_DIR.iterdir()):
        if not dataset_dir.is_dir():
            continue
        files = [f.name for f in sorted(dataset_dir.iterdir()) if f.is_file()]
        if files:
            datasets.append({"name": dataset_dir.name, "files": files})
    return {"datasets": datasets}


@app.get("/sample-data/{dataset}/{filename}")
def get_sample_file(dataset: str, filename: str):
    """Serve a sample data file. Path-traversal safe."""
    if not _SAFE_FILENAME.match(dataset) or not _SAFE_FILENAME.match(filename):
        return {"success": False, "error": "Invalid dataset or filename"}

    file_path = SAMPLE_DATA_DIR / dataset / filename
    if not file_path.exists() or not file_path.is_file():
        return {"success": False, "error": "File not found"}

    # Ensure resolved path is within SAMPLE_DATA_DIR
    if not file_path.resolve().is_relative_to(SAMPLE_DATA_DIR.resolve()):
        return {"success": False, "error": "Invalid path"}

    return FileResponse(file_path, filename=filename)


# ---------- Sample report endpoints ----------


@app.get("/sample-reports")
def list_sample_reports():
    """List available sample report files from the sample_reports/ directory."""
    reports = []
    if not SAMPLE_REPORTS_DIR.exists():
        return {"reports": reports}

    for f in sorted(SAMPLE_REPORTS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in {".docx", ".pdf", ".txt"}:
            reports.append(f.name)
    return {"reports": reports}


@app.get("/sample-reports/{filename}")
def get_sample_report(filename: str):
    """Serve a sample report file. Path-traversal safe."""
    if not _SAFE_FILENAME.match(filename):
        return {"success": False, "error": "Invalid filename"}

    file_path = SAMPLE_REPORTS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        return {"success": False, "error": "File not found"}

    if not file_path.resolve().is_relative_to(SAMPLE_REPORTS_DIR.resolve()):
        return {"success": False, "error": "Invalid path"}

    return FileResponse(file_path, filename=filename)


# ---------- Feature 1.5: Auto-generate column definitions ----------


def _parse_csv_preview(raw_bytes: bytes, max_rows: int = 5) -> tuple[list[str], list[list[str]]]:
    """Read CSV header and up to max_rows sample rows from raw bytes."""
    import csv
    import io

    text = raw_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, [])
    rows = []
    for row in reader:
        rows.append(row)
        if len(rows) >= max_rows:
            break
    return headers, rows


@app.post("/generate-column-definitions")
async def generate_column_definitions(
    data_file: UploadFile = File(...),
    lang: str = Form("ko"),
):
    """Read CSV header + sample rows and call Bedrock Claude to generate column_definitions.json."""
    try:
        raw = await data_file.read()
        headers, sample_rows = _parse_csv_preview(raw)

        if not headers:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Could not parse CSV headers"},
            )

        # Build a preview table for the LLM
        preview_lines = [",".join(headers)]
        for row in sample_rows:
            preview_lines.append(",".join(row))
        preview_text = "\n".join(preview_lines)

        lang_instruction = (
            "Write column_desc in Korean." if lang == "ko"
            else "Write column_desc in English."
        )

        prompt = f"""Analyze the following CSV data (header + sample rows) and generate a column_definitions JSON array.

For each column, produce an object with:
- "column_name": the exact column header from the CSV
- "column_desc": a clear, concise description of what the column represents, including data type, unit, or format if apparent from the sample data.

{lang_instruction}

Return ONLY a valid JSON array, no markdown fences, no explanation.

CSV data:
{preview_text}"""

        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        })

        response = bedrock.invoke_model(
            modelId=WEB_UTILITY_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )

        result = json.loads(response["body"].read())
        text_content = result["content"][0]["text"].strip()

        # Strip markdown code fences if present (```json ... ```)
        if text_content.startswith("```"):
            lines = text_content.split("\n")
            # Remove first line (```json) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text_content = "\n".join(lines).strip()

        # Parse the JSON to validate it
        column_definitions = json.loads(text_content)

        return {"success": True, "column_definitions": column_definitions}

    except json.JSONDecodeError:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "LLM returned invalid JSON. Please try again."},
        )
    except Exception as e:
        # Same rationale as S2/S7 / C2 — Bedrock errors disclose model ARN,
        # IAM principal, and region. Keep details server-side only.
        logger.error(f"Column definition generation failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Column definition generation failed"},
        )


@app.post("/generate-prompts")
async def generate_prompts(
    column_definitions: UploadFile = File(...),
    lang: str = Form("ko"),
):
    """Generate 3 sample analysis prompts (simple/medium/complex) from a
    column-definitions JSON, using Bedrock Claude.

    Mirrors /generate-column-definitions in shape: one file input + lang.
    Used by the Web UI to populate dynamic prompt chips in the analyze card.
    """
    try:
        raw = await column_definitions.read()
        try:
            coldef_data = json.loads(raw)
        except json.JSONDecodeError as e:
            # Surface only the offset/line so the user can fix their file —
            # don't include the raw exception text (which echoes the bad
            # bytes verbatim and trips CodeQL's stack-trace-exposure rule).
            logger.warning(f"column_definitions JSON parse failed: {e}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"Invalid JSON at line {e.lineno}, column {e.colno}",
                },
            )

        if not isinstance(coldef_data, list) or not coldef_data:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "column_definitions must be a non-empty JSON array"},
            )

        lang_instruction = (
            "Write all prompt text in Korean."
            if lang == "ko"
            else "Write all prompt text in English."
        )
        tag_simple = "간단" if lang == "ko" else "Simple"
        tag_medium = "중간" if lang == "ko" else "Medium"
        tag_complex = "복잡" if lang == "ko" else "Complex"

        prompt = f"""You generate sample business-analysis prompts for a data analysis tool, given a column-definitions JSON describing the dataset.

Generate exactly 3 sample prompts at distinct complexity levels:

- "simple":  one metric or one operation (e.g., summarize key metrics, calculate a total). 1 sentence, under 40 characters.
- "medium":  a focused trend, segmentation, or comparison spanning 2-3 columns. 1-2 sentences.
- "complex": a strategic, multi-dimensional question requiring synthesis across many columns - e.g., growth-opportunity discovery, multi-factor optimization. 2-4 sentences. Should ask for prioritized actionable strategies with expected impact.

Use a business perspective, not a technical one. Reference actual column names from the JSON where natural.

{lang_instruction}

Return ONLY a valid JSON array with this exact shape, no markdown fences, no explanation:

[
  {{"level": "simple",  "tag": "{tag_simple}",  "text": "..."}},
  {{"level": "medium",  "tag": "{tag_medium}",  "text": "..."}},
  {{"level": "complex", "tag": "{tag_complex}", "text": "..."}}
]

Column definitions:
{json.dumps(coldef_data, ensure_ascii=False)}"""

        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        })

        response = bedrock.invoke_model(
            modelId=WEB_UTILITY_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )

        result = json.loads(response["body"].read())
        text_content = result["content"][0]["text"].strip()

        # Strip markdown code fences if present (mirrors /generate-column-definitions)
        if text_content.startswith("```"):
            lines = text_content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text_content = "\n".join(lines).strip()

        prompts = json.loads(text_content)

        if not isinstance(prompts, list) or len(prompts) != 3:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": f"LLM returned {len(prompts) if isinstance(prompts, list) else 'non-array'} prompts; expected 3"},
            )
        for p in prompts:
            if not isinstance(p, dict) or set(p.keys()) < {"level", "tag", "text"}:
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "error": "LLM response missing required keys (level, tag, text)"},
                )

        return {"success": True, "prompts": prompts}

    except json.JSONDecodeError:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "LLM returned invalid JSON. Please try again."},
        )
    except Exception as e:
        logger.error(f"Prompt generation failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Prompt generation failed"},
        )


# ---------- Feature 2: Static page serving ----------


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the single-page UI."""
    return (STATIC_DIR / "index.html").read_text()


# ---------- Request Models ----------


class AnalyzeRequest(BaseModel):
    upload_id: str
    query: str

    @field_validator("upload_id")
    @classmethod
    def _check_upload_id(cls, v: str) -> str:
        return _validate_id(v, "upload_id")


class FeedbackRequest(BaseModel):
    request_id: str
    approved: bool
    feedback: str = ""

    @field_validator("request_id")
    @classmethod
    def _check_request_id(cls, v: str) -> str:
        return _validate_id(v, "request_id")


# ---------- AgentCore Client & SSE Helpers ----------


def get_agentcore_client():
    """Create boto3 bedrock-agentcore client with extended timeouts."""
    config = Config(
        connect_timeout=6000,
        read_timeout=3600,
        retries={"max_attempts": 0},
    )
    return boto3.client("bedrock-agentcore", region_name=AWS_REGION, config=config)


def parse_sse_data(sse_bytes):
    """Parse SSE bytes from boto3 streaming response into a dict."""
    if not sse_bytes or len(sse_bytes) == 0:
        return None
    try:
        text = sse_bytes.decode("utf-8").strip()
        if not text:
            return None
        if text.startswith("data: "):
            json_text = text[6:].strip()
            if json_text:
                return json.loads(json_text)
        else:
            return json.loads(text)
    except Exception:
        pass
    return None


def format_sse(data: dict) -> str:
    """Format a dict as an SSE line for the browser."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------- Feature 3: File upload ----------


@app.post("/upload")
async def upload(
    data_file: UploadFile = File(...),
    column_definitions: UploadFile | None = File(None),
):
    """Upload data file (required) and column_definitions.json (optional) to S3 or local."""
    upload_id = str(uuid.uuid4())
    try:
        normalized_filename = _sanitize_filename(data_file.filename or "")
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Invalid filename"},
        )

    if S3_BUCKET_NAME:
        # S3 mode (production)
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3_paths = []

        data_key = f"uploads/{upload_id}/{normalized_filename}"
        s3.put_object(Bucket=S3_BUCKET_NAME, Key=data_key, Body=await data_file.read())
        s3_paths.append(f"s3://{S3_BUCKET_NAME}/{data_key}")
        logger.info(f"Uploaded: s3://{S3_BUCKET_NAME}/{data_key}")

        if column_definitions:
            coldef_key = f"uploads/{upload_id}/column_definitions.json"
            s3.put_object(
                Bucket=S3_BUCKET_NAME, Key=coldef_key, Body=await column_definitions.read()
            )
            s3_paths.append(f"s3://{S3_BUCKET_NAME}/{coldef_key}")
            logger.info(f"Uploaded: s3://{S3_BUCKET_NAME}/{coldef_key}")

        return {"success": True, "upload_id": upload_id, "s3_paths": s3_paths}
    else:
        # Local mode (development/testing)
        dest = LOCAL_UPLOAD_DIR / upload_id
        dest.mkdir(parents=True, exist_ok=True)

        data_bytes = await data_file.read()
        (dest / normalized_filename).write_bytes(data_bytes)
        logger.info(f"Local upload: {dest / normalized_filename}")

        if column_definitions:
            coldef_bytes = await column_definitions.read()
            (dest / "column_definitions.json").write_bytes(coldef_bytes)
            logger.info(f"Local upload: {dest / 'column_definitions.json'}")

        return {"success": True, "upload_id": upload_id, "s3_paths": [str(dest)]}


# ---------- Feature 4: Analysis + SSE streaming ----------


# SSE keepalive interval in seconds. Must be shorter than CloudFront's default
# Origin Read Timeout (60s) to prevent proxy idle disconnections.
SSE_KEEPALIVE_INTERVAL = 30


def _read_agentcore_events(response, event_queue):
    """Read AgentCore SSE stream in a background thread and enqueue parsed events.

    iter_lines() is a blocking call, so it must run in a separate thread
    to allow the main generator to yield keepalive comments.
    """
    try:
        for event_bytes in response["response"].iter_lines(chunk_size=1):
            event_data = parse_sse_data(event_bytes)
            if event_data is not None:
                event_queue.put(event_data)
    except Exception as e:
        # Don't echo exception details (boto3/IAM messages disclose bucket
        # name, IAM principal, region). Log server-side instead.
        logger.error(f"SSE iter_lines failed: {e}", exc_info=True)
        event_queue.put({"type": "error", "text": "Stream interrupted"})
    finally:
        event_queue.put(None)  # End-of-stream sentinel


def agentcore_sse_generator(query: str, data_directory: str, upload_id: str = ""):
    """Call AgentCore Runtime and yield SSE events for the browser.

    To prevent proxy idle timeout disconnections (e.g., CloudFront Origin Read
    Timeout of 60s), this generator sends an SSE comment (": keepalive") every
    SSE_KEEPALIVE_INTERVAL seconds when no real events are available.
    Browsers ignore SSE comments per the W3C spec, so this has no side effects.
    """
    if not RUNTIME_ARN:
        yield format_sse({"type": "error", "text": "RUNTIME_ARN not configured"})
        return

    client = get_agentcore_client()
    payload = json.dumps({"prompt": query, "data_directory": data_directory})

    logger.info(f"Invoking AgentCore: query={query[:80]}...")

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            qualifier="DEFAULT",
            payload=payload,
        )

        content_type = response.get("contentType", "")
        if "text/event-stream" not in content_type:
            yield format_sse({"type": "error", "text": f"Unexpected content type: {content_type}"})
            return

        # Read events in a background thread so the main generator can
        # yield keepalive comments during long idle periods.
        event_queue = queue.Queue()
        reader_thread = threading.Thread(
            target=_read_agentcore_events, args=(response, event_queue), daemon=True
        )
        reader_thread.start()

        while True:
            try:
                event_data = event_queue.get(timeout=SSE_KEEPALIVE_INTERVAL)
            except queue.Empty:
                # No event within the interval — send SSE comment to keep
                # the connection alive through proxies.
                yield ": keepalive\n\n"
                continue

            if event_data is None:
                break  # End-of-stream sentinel from reader thread

            event_type = event_data.get("type") or event_data.get("event_type") or "unknown"

            # Track failures from the reader thread so the ops dashboard
            # (DynamoDB job tracking) records them correctly.
            if event_type == "error":
                track_job_failure(upload_id, event_data.get("text", "unknown error"))

            if event_type == "plan_review_request":
                yield format_sse({
                    "type": "plan_review_request",
                    "plan": event_data.get("plan", ""),
                    "revision_count": event_data.get("revision_count", 0),
                    "max_revisions": event_data.get("max_revisions", 10),
                    "request_id": event_data.get("request_id", ""),
                    "timeout_seconds": event_data.get("timeout_seconds", 300),
                })
            elif event_type == "plan_review_keepalive":
                yield format_sse({
                    "type": "plan_review_keepalive",
                    "elapsed_seconds": event_data.get("elapsed_seconds", 0),
                    "timeout_seconds": event_data.get("timeout_seconds", 300),
                })
            elif event_type == "workflow_complete":
                session_id = event_data.get("session_id", "")
                yield format_sse({
                    "type": "workflow_complete",
                    "text": event_data.get("text", ""),
                    "session_id": session_id,
                    "filenames": event_data.get("filenames", []),
                })
                track_job_link(upload_id, session_id)
            else:
                text = event_data.get("text") or event_data.get("data") or ""
                yield format_sse({"type": event_type, "text": text})

        yield format_sse({"type": "done", "text": ""})

    except Exception as e:
        # Don't echo `str(e)` to the browser — boto3/IAM messages can leak
        # the runtime ARN, IAM principal, region, and account ID. Keep the
        # raw message in server logs and DynamoDB (admin-only) only.
        logger.error(f"AgentCore invocation error: {e}", exc_info=True)
        yield format_sse({"type": "error", "text": "Analysis failed"})
        track_job_failure(upload_id, str(e))


@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    """Invoke AgentCore Runtime and relay SSE events to the browser."""
    data_directory = f"s3://{S3_BUCKET_NAME}/uploads/{request.upload_id}/"
    logger.info(f"Analyze request: upload_id={request.upload_id}, query={request.query[:80]}...")
    track_job_start(request.upload_id, request.query)
    return StreamingResponse(
        agentcore_sse_generator(request.query, data_directory, request.upload_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------- Feature 5: HITL plan review ----------


@app.post("/feedback")
def feedback(request: FeedbackRequest):
    """Upload HITL feedback to S3 for the runtime to read."""
    if not S3_BUCKET_NAME:
        return {"success": False, "error": "S3_BUCKET_NAME not configured"}

    feedback_data = {
        "approved": request.approved,
        "feedback": request.feedback,
        "timestamp": datetime.now().isoformat(),
    }

    s3_key = f"deep-insight/feedback/{request.request_id}.json"

    try:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=json.dumps(feedback_data, ensure_ascii=False),
            ContentType="application/json",
        )
        logger.info(f"Feedback uploaded: s3://{S3_BUCKET_NAME}/{s3_key}")
        return {"success": True, "s3_path": f"s3://{S3_BUCKET_NAME}/{s3_key}"}
    except Exception as e:
        logger.error(f"Feedback upload failed: {e}", exc_info=True)
        return {"success": False, "error": "Feedback upload failed"}


# ---------- Feature 6: Report download ----------

# _SAFE_ID is defined at module top alongside _SAFE_FILENAME (used here for
# session_id and elsewhere for upload_id / request_id validation).
_REPORT_EXTENSIONS = {".docx", ".pdf", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".svg"}


@app.get("/artifacts/{session_id}")
def list_artifacts(session_id: str):
    """List artifact files for a completed analysis session."""
    if not S3_BUCKET_NAME:
        return {"success": False, "error": "S3_BUCKET_NAME not configured"}
    if not _SAFE_ID.match(session_id):
        return {"success": False, "error": "Invalid session_id"}

    prefix = f"deep-insight/fargate_sessions/{session_id}/artifacts/"

    try:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=prefix)
        filenames = []
        for obj in response.get("Contents", []):
            name = obj["Key"].removeprefix(prefix)
            if name:
                ext = Path(name).suffix.lower()
                if ext in _REPORT_EXTENSIONS:
                    filenames.append(name)
        logger.info(f"Artifacts for {session_id}: {filenames}")
        return {"success": True, "session_id": session_id, "filenames": filenames}
    except Exception as e:
        logger.error(f"List artifacts failed: {e}", exc_info=True)
        return {"success": False, "error": "Failed to list artifacts"}


@app.get("/download/{session_id}/{filename:path}")
def download_artifact(session_id: str, filename: str):
    """Generate a pre-signed S3 URL and redirect the browser to download directly.

    Instead of proxying the file through the BFF, this generates a time-limited
    pre-signed URL (15 minutes) and returns an HTTP 302 redirect. The browser
    then downloads the file directly from S3 over HTTPS, which ensures correct
    Content-Type and Content-Length headers from S3 itself.
    """
    if not S3_BUCKET_NAME:
        return {"success": False, "error": "S3_BUCKET_NAME not configured"}
    if not _SAFE_ID.match(session_id):
        return {"success": False, "error": "Invalid session_id"}
    if ".." in filename or filename.startswith("/"):
        return {"success": False, "error": "Invalid filename"}

    s3_key = f"deep-insight/fargate_sessions/{session_id}/artifacts/{filename}"
    download_name = filename.rsplit("/", 1)[-1]

    try:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
        body = obj["Body"].read()

        # RFC 5987: ASCII fallback + UTF-8 encoded filename for non-ASCII characters
        ext = download_name.rsplit(".", 1)[-1] if "." in download_name else "bin"
        ascii_fallback = f"download.{ext}"
        disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(download_name)}"

        logger.info(f"Download proxy: {s3_key} ({len(body)} bytes)")
        return Response(
            content=body,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": disposition,
                "Content-Length": str(len(body)),
            },
        )
    except Exception as e:
        # Do NOT echo the exception to the client — it can leak the S3 key,
        # bucket name, IAM error codes, or stacktrace. Keep details server-side.
        logger.error(f"Download failed: {e}", exc_info=True)
        return {"success": False, "error": "Download failed"}


# ---------- Feature 7: Data Q&A Chat ----------

SSE_CHAT_KEEPALIVE = 30


class ChatRequest(BaseModel):
    upload_id: str
    message: str

    @field_validator("upload_id")
    @classmethod
    def _check_upload_id(cls, v: str) -> str:
        return _validate_id(v, "upload_id")


class ChatResetRequest(BaseModel):
    upload_id: str

    @field_validator("upload_id")
    @classmethod
    def _check_upload_id(cls, v: str) -> str:
        return _validate_id(v, "upload_id")


def chat_sse_generator(upload_id: str, message: str):
    """Run Strands Agent chat and yield SSE events for the browser.

    The agent loop (tool calling, retries) is handled by Strands SDK.
    This generator reads events from a background thread and relays them as SSE,
    sending keepalive comments every SSE_CHAT_KEEPALIVE seconds.
    """
    event_queue = queue.Queue()

    def _run_agent():
        """Run the agent in a background thread using asyncio for stream_async."""
        import asyncio

        def _flush_side_channel(session):
            """Push any pending rich outputs (SQL, charts, tables) from tools to the event queue."""
            while session.side_channel:
                output_type, data = session.side_channel.pop(0)
                if output_type == "sql":
                    event_queue.put({"type": "sql", "sql": data})
                elif output_type == "chart":
                    event_queue.put({"type": "chart", "image": data})
                elif output_type == "table":
                    event_queue.put({"type": "table", "html": data})

        def _process_event(event, session):
            # After every event, check if tools pushed rich outputs
            _flush_side_channel(session)

            # Extract text deltas
            if "data" in event and "delta" in event:
                delta = event["delta"]
                if "text" in delta:
                    event_queue.put({"type": "text", "text": delta["text"]})
            # Extract tool use from complete messages
            elif "message" in event and event["message"].get("role") == "assistant":
                content = event["message"].get("content", [])
                for item in content:
                    if isinstance(item, dict) and "toolUse" in item:
                        tool_name = item["toolUse"].get("name", "")
                        event_queue.put({"type": "tool_call", "tool": tool_name})

        def _log_usage(session):
            """Log per-turn token usage from the Strands EventLoopMetrics.

            `stream_async` calls reset_usage_metrics() at the start of each turn,
            so accumulated_usage after the iterator drains = this turn's usage.
            """
            try:
                usage = session.agent.event_loop_metrics.accumulated_usage
                # Usage is a TypedDict-like mapping
                logger.info(
                    "chat usage upload_id=%s input=%s output=%s total=%s "
                    "cache_read=%s cache_write=%s",
                    upload_id,
                    usage.get("inputTokens"),
                    usage.get("outputTokens"),
                    usage.get("totalTokens"),
                    usage.get("cacheReadInputTokens"),
                    usage.get("cacheWriteInputTokens"),
                )
            except Exception as e:
                logger.warning(f"Could not log usage: {e}")

        async def _stream():
            session = chat_session_manager.get_or_create(upload_id)
            session.ensure_agent_created()
            async for event in session.agent.stream_async(message):
                _process_event(event, session)
            # Final flush in case tool output arrived after last event
            _flush_side_channel(session)
            # Log token usage for this turn (prompt caching observability)
            _log_usage(session)

        try:
            asyncio.run(_stream())
        except Exception as e:
            # Same rationale as the /analyze SSE generator: keep boto3/IAM
            # / Bedrock error details server-side.
            logger.error(f"Chat agent error: {e}", exc_info=True)
            event_queue.put({"type": "error", "text": "Chat agent error"})
        finally:
            event_queue.put(None)  # End-of-stream sentinel

    thread = threading.Thread(target=_run_agent, daemon=True)
    thread.start()

    while True:
        try:
            event_data = event_queue.get(timeout=SSE_CHAT_KEEPALIVE)
        except queue.Empty:
            yield ": keepalive\n\n"
            continue

        if event_data is None:
            break

        yield format_sse(event_data)

    yield format_sse({"type": "done"})


@app.post("/chat")
def chat(request: ChatRequest):
    """Data Q&A chat endpoint with SSE streaming."""
    logger.info(f"Chat request: upload_id={request.upload_id}, message={request.message[:80]}...")
    return StreamingResponse(
        chat_sse_generator(request.upload_id, request.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/chat/reset")
def chat_reset(request: ChatResetRequest):
    """Clear chat history for a session."""
    chat_session_manager.remove(request.upload_id)
    logger.info(f"Chat reset: upload_id={request.upload_id}")
    return {"success": True}


class SuggestionsRequest(BaseModel):
    upload_id: str

    @field_validator("upload_id")
    @classmethod
    def _check_upload_id(cls, v: str) -> str:
        return _validate_id(v, "upload_id")


@app.post("/chat/suggestions")
def chat_suggestions(request: SuggestionsRequest):
    """Generate dynamic example questions based on the uploaded data's schema."""
    try:
        suggestions = generate_suggestions(request.upload_id)
        return {"success": True, "suggestions": suggestions}
    except Exception as e:
        logger.error(f"Suggestions error: {e}")
        return {"success": True, "suggestions": [
            "데이터의 기본 통계를 보여줘",
            "가장 많이 팔린 상품 TOP 5는?",
            "매출 추이 차트를 그려줘",
        ]}


class SqlExecuteRequest(BaseModel):
    upload_id: str
    sql: str

    @field_validator("upload_id")
    @classmethod
    def _check_upload_id(cls, v: str) -> str:
        return _validate_id(v, "upload_id")


@app.post("/sql/execute")
def sql_execute(request: SqlExecuteRequest):
    """Run user-edited SQL directly against the session's DuckDB (read-only, no LLM).

    Used by the in-chat SQL editor so users can tweak queries and re-run
    without another agent turn. Results are returned as pre-formatted HTML.
    """
    logger.info(
        f"SQL execute: upload_id={request.upload_id}, "
        f"sql={request.sql[:120]}..."
    )
    return execute_sql_for_session(request.upload_id, request.sql)


# ---------- Meta (dataset summary for Q&A welcome) ----------


@app.get("/chat/meta")
def chat_meta(upload_id: str):
    """Return dataset summary for the Q&A welcome card: row count, columns (with
    types + user-supplied descriptions from column_definitions.json when available).
    """
    try:
        _validate_id(upload_id, "upload_id")
    except ValueError:
        return {"success": False, "error": "Invalid upload_id"}
    try:
        session = chat_session_manager.get_or_create(upload_id)
        session.ensure_data_loaded()
        cols = session.run_query(
            f"DESCRIBE {session.table_name}"
        ).fetchall()

        # Build description lookup from column_definitions.json (optional)
        desc_by_name: dict[str, str] = {}
        coldef = session.column_definitions
        if isinstance(coldef, list):
            for item in coldef:
                if not isinstance(item, dict):
                    continue
                name = item.get("column_name") or item.get("name")
                desc = item.get("column_desc") or item.get("description") or ""
                if name:
                    desc_by_name[str(name)] = str(desc)

        return {
            "success": True,
            "table": session.table_name,
            "rows": session.row_count,
            "filename": session.csv_filename,
            "columns": [
                {"name": c[0], "type": c[1], "desc": desc_by_name.get(c[0], "")}
                for c in cols
            ],
            "has_descriptions": bool(desc_by_name),
        }
    except Exception as e:
        logger.error(f"chat_meta failed: {e}", exc_info=True)
        return {"success": False, "error": "Failed to load dataset metadata"}


# ---------- Main ----------

if __name__ == "__main__":
    logger.info(f"Starting Deep Insight Web on {HOST}:{PORT}")
    logger.info(f"Runtime ARN: {RUNTIME_ARN}")
    logger.info(f"Region: {AWS_REGION}")
    logger.info(f"S3 Bucket: {S3_BUCKET_NAME}")
    uvicorn.run(app, host=HOST, port=PORT)
