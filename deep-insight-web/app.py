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
from urllib.parse import quote

from ops.job_tracker import track_job_start, track_job_link, track_job_failure
from ops.admin_router import admin_router

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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


# ---------- Feature 2: Static page serving ----------


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the single-page UI."""
    return (STATIC_DIR / "index.html").read_text()


# ---------- Request Models ----------


class AnalyzeRequest(BaseModel):
    upload_id: str
    query: str


class FeedbackRequest(BaseModel):
    request_id: str
    approved: bool
    feedback: str = ""


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
    """Upload data file (required) and column_definitions.json (optional) to S3."""
    if not S3_BUCKET_NAME:
        return {"success": False, "error": "S3_BUCKET_NAME not configured"}

    upload_id = str(uuid.uuid4())
    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3_paths = []

    # Upload data file (keep original filename)
    data_key = f"uploads/{upload_id}/{data_file.filename}"
    s3.put_object(Bucket=S3_BUCKET_NAME, Key=data_key, Body=await data_file.read())
    s3_paths.append(f"s3://{S3_BUCKET_NAME}/{data_key}")
    logger.info(f"Uploaded: s3://{S3_BUCKET_NAME}/{data_key}")

    # Upload column definitions (optional)
    if column_definitions:
        coldef_key = f"uploads/{upload_id}/column_definitions.json"
        s3.put_object(
            Bucket=S3_BUCKET_NAME, Key=coldef_key, Body=await column_definitions.read()
        )
        s3_paths.append(f"s3://{S3_BUCKET_NAME}/{coldef_key}")
        logger.info(f"Uploaded: s3://{S3_BUCKET_NAME}/{coldef_key}")

    return {"success": True, "upload_id": upload_id, "s3_paths": s3_paths}


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
        event_queue.put({"type": "error", "text": str(e)})
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
        logger.error(f"AgentCore invocation error: {e}")
        yield format_sse({"type": "error", "text": str(e)})
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
        logger.error(f"Feedback upload failed: {e}")
        return {"success": False, "error": str(e)}


# ---------- Feature 6: Report download ----------

# Allowed pattern: UUID or UUID-like session IDs (alphanumeric, hyphens, underscores)
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
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
        logger.error(f"List artifacts failed: {e}")
        return {"success": False, "error": str(e)}


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
        logger.error(f"Download failed: {e}")
        return {"success": False, "error": str(e)}


# ---------- Main ----------

if __name__ == "__main__":
    logger.info(f"Starting Deep Insight Web on {HOST}:{PORT}")
    logger.info(f"Runtime ARN: {RUNTIME_ARN}")
    logger.info(f"Region: {AWS_REGION}")
    logger.info(f"S3 Bucket: {S3_BUCKET_NAME}")
    uvicorn.run(app, host=HOST, port=PORT)
