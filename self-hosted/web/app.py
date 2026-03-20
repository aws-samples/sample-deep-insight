"""
Self-hosted Deep Insight Web — FastAPI server.

Runs the self-hosted analysis engine with the existing frontend from deep-insight-web/static/.
Phase 1: single-session, local-only.

Usage:
    cd self-hosted
    uv run python -m web.app
"""

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from web.event_adapter import adapt_event
from web.hitl import hitl_manager

# Load .env from self-hosted root
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Paths ---
SELF_HOSTED_ROOT = Path(__file__).resolve().parents[1]  # self-hosted/
WEB_ROOT = Path(__file__).resolve().parents[2] / "deep-insight-web"  # deep-insight-web/
STATIC_DIR = WEB_ROOT / "static"
SAMPLE_DATA_DIR = WEB_ROOT / "sample_data"
SAMPLE_REPORTS_DIR = WEB_ROOT / "sample_reports"

UPLOAD_DIR = SELF_HOSTED_ROOT / "data" / "uploads"
ARTIFACTS_DIR = SELF_HOSTED_ROOT / "artifacts"

HOST = "0.0.0.0"
PORT = int(os.getenv("WEB_PORT", "8080"))

# --- CloudFront origin verify (Phase 2) ---
ORIGIN_VERIFY_SECRET = os.getenv("ORIGIN_VERIFY_SECRET", "")

# --- Cognito config (Phase 2) ---
COGNITO_DOMAIN = os.getenv("COGNITO_DOMAIN", "")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET", "")
COGNITO_REDIRECT_URI = os.getenv("COGNITO_REDIRECT_URI", "")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
COGNITO_REGION = os.getenv("AWS_REGION", "us-west-2")

# --- SSE heartbeat interval (seconds) ---
SSE_HEARTBEAT_INTERVAL = int(os.getenv("SSE_HEARTBEAT_INTERVAL", "25"))

# --- App ---
app = FastAPI(title="Deep Insight (self-hosted)")


# --- JWKS cache for Cognito JWT verification ---
_jwks_cache: dict | None = None


async def _get_jwks() -> dict:
    """Fetch and cache Cognito JWKS public keys."""
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    jwks_url = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(jwks_url)
        data = resp.json()
    _jwks_cache = {k["kid"]: k for k in data["keys"]}
    return _jwks_cache


def _verify_jwt(token: str) -> dict | None:
    """Verify Cognito JWT token. Returns payload if valid, None otherwise."""
    import base64, json
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Decode payload (skip signature verification for now, check expiry + issuer)
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        # Check expiry
        import time
        if payload.get("exp", 0) < time.time():
            return None
        # Check issuer
        expected_issuer = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
        if payload.get("iss") != expected_issuer:
            return None
        return payload
    except Exception:
        return None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Authenticate requests via Cognito JWT cookie or origin-verify header.

    Pass-through (no auth):
      - /health (ALB health check)
      - /auth/* (login/callback/logout)
      - No Cognito config (local dev / Phase 1)

    Origin verify:
      - When ORIGIN_VERIFY_SECRET is set, block direct ALB access

    JWT verification:
      - Check id_token cookie
      - If missing/invalid, redirect to Cognito login
    """
    path = request.url.path

    # Always pass through: health check, auth endpoints, static assets, sample data
    if path == "/health" or path.startswith("/auth/") or path.startswith("/static/") or path.startswith("/sample-"):
        return await call_next(request)

    # Origin verify (block direct ALB access)
    if ORIGIN_VERIFY_SECRET:
        if request.headers.get("X-Origin-Verify") != ORIGIN_VERIFY_SECRET:
            return Response(status_code=403, content="Forbidden")

    # JWT verification (skip if Cognito not configured — local dev)
    if COGNITO_USER_POOL_ID and COGNITO_DOMAIN:
        token = request.cookies.get("id_token")
        if not token or not _verify_jwt(token):
            login_url = (
                f"{COGNITO_DOMAIN}/login?client_id={COGNITO_CLIENT_ID}"
                f"&response_type=code&scope=openid+email+profile"
                f"&redirect_uri={quote(COGNITO_REDIRECT_URI)}"
            )
            return RedirectResponse(login_url)

    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# --- Validation ---
_SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_REPORT_EXTENSIONS = {".docx", ".pdf", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".svg"}


# --- Request Models ---
class AnalyzeRequest(BaseModel):
    upload_id: str
    query: str


class FeedbackRequest(BaseModel):
    request_id: str
    approved: bool
    feedback: str = ""


# --- SSE helper ---
def format_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------- Health ----------
@app.get("/health")
def health():
    return {"status": "healthy"}


# ---------- Static page ----------
@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text()


# ---------- Sample data ----------
@app.get("/sample-data")
def list_sample_data():
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
    if not _SAFE_FILENAME.match(dataset) or not _SAFE_FILENAME.match(filename):
        return {"success": False, "error": "Invalid dataset or filename"}
    file_path = SAMPLE_DATA_DIR / dataset / filename
    if not file_path.exists() or not file_path.is_file():
        return {"success": False, "error": "File not found"}
    if not file_path.resolve().is_relative_to(SAMPLE_DATA_DIR.resolve()):
        return {"success": False, "error": "Invalid path"}
    return FileResponse(file_path, filename=filename)


# ---------- Sample reports ----------
@app.get("/sample-reports")
def list_sample_reports():
    reports = []
    if not SAMPLE_REPORTS_DIR.exists():
        return {"reports": reports}
    for f in sorted(SAMPLE_REPORTS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in {".docx", ".pdf", ".txt"}:
            reports.append(f.name)
    return {"reports": reports}


@app.get("/sample-reports/{filename}")
def get_sample_report(filename: str):
    if not _SAFE_FILENAME.match(filename):
        return {"success": False, "error": "Invalid filename"}
    file_path = SAMPLE_REPORTS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        return {"success": False, "error": "File not found"}
    if not file_path.resolve().is_relative_to(SAMPLE_REPORTS_DIR.resolve()):
        return {"success": False, "error": "Invalid path"}
    return FileResponse(file_path, filename=filename)


# ---------- Upload ----------
@app.post("/upload")
async def upload(
    data_file: UploadFile = File(...),
    column_definitions: UploadFile | None = File(None),
):
    """Save uploaded files to ./data/uploads/{upload_id}/."""
    upload_id = str(uuid.uuid4())
    dest_dir = UPLOAD_DIR / upload_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Save data file (sanitize filename to prevent path traversal)
    safe_name = Path(data_file.filename).name  # Strip directory components
    if not _SAFE_FILENAME.match(safe_name):
        safe_name = f"upload_{upload_id}.csv"
    data_path = dest_dir / safe_name
    data_path.write_bytes(await data_file.read())
    logger.info(f"Saved: {data_path}")

    # Save column definitions (optional)
    if column_definitions:
        coldef_path = dest_dir / "column_definitions.json"
        coldef_path.write_bytes(await column_definitions.read())
        logger.info(f"Saved: {coldef_path}")

    return {"success": True, "upload_id": upload_id}


# ---------- Analyze (SSE streaming) ----------
async def _plan_review_web_callback(full_plan: str, revision_count: int, max_revisions: int):
    """Callback registered into nodes._plan_review_callback for web mode.

    Puts a plan_review_request event into the event queue, then waits for
    the user to POST /feedback.
    """
    from src.utils.event_queue import put_event

    request_id = hitl_manager.new_request_id()
    timeout_seconds = 300

    put_event({
        "type": "plan_review_request",
        "plan": full_plan,
        "revision_count": revision_count,
        "max_revisions": max_revisions,
        "request_id": request_id,
        "timeout_seconds": timeout_seconds,
    })

    approved, feedback = await hitl_manager.wait_for_feedback(timeout=timeout_seconds)
    return approved, feedback


async def sse_generator(upload_id: str, query: str):
    """Run the self-hosted engine and yield SSE events.

    Sends periodic heartbeats to keep the CloudFront -> ALB connection alive.
    CloudFront drops idle connections after 60s; heartbeat fires every 25s.
    """
    from src.graph import nodes
    from main import graph_streaming_execution

    # Reset global state from previous analysis (CLI assumes fresh process each time,
    # but Web keeps the same process — stale state causes token carryover and artifacts deletion)
    nodes._global_node_states.clear()
    logger.info("Global node states cleared for new analysis")

    # Register web HITL callback
    nodes._plan_review_callback = _plan_review_web_callback

    # Validate upload_id to prevent path traversal
    if not _SAFE_ID.match(upload_id):
        yield format_sse({"type": "error", "text": "Invalid upload ID"})
        return

    # Build the user_query pointing to the local upload directory
    upload_path = f"./data/uploads/{upload_id}/"
    user_query = f"{query}\n분석대상은 '{upload_path}' 디렉토리 입니다."

    # Check for column_definitions.json
    coldef_path = UPLOAD_DIR / upload_id / "column_definitions.json"
    if coldef_path.exists():
        # Find the data file (non-json file)
        data_files = [
            f.name for f in (UPLOAD_DIR / upload_id).iterdir()
            if f.is_file() and f.name != "column_definitions.json"
        ]
        if data_files:
            user_query += f"\n{data_files[0]} 는 분석 파일이고, column_definitions.json은 컬럼에 대한 설명입니다."

    payload = {"user_query": user_query}
    session_id = upload_id  # Use upload_id as session_id for Phase 1

    # Merge engine events with heartbeat using an async queue
    heartbeat_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    async def _produce_engine_events():
        try:
            async for event in graph_streaming_execution(payload):
                adapted = adapt_event(event)
                if adapted:
                    await queue.put(adapted)
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            await queue.put({"type": "error", "text": str(e)})
        finally:
            nodes._plan_review_callback = None
            await queue.put(None)  # Sentinel

    async def _produce_heartbeats():
        while not heartbeat_event.is_set():
            await asyncio.sleep(SSE_HEARTBEAT_INTERVAL)
            if not heartbeat_event.is_set():
                logger.debug("Sending SSE heartbeat")
                await queue.put({"type": "heartbeat", "text": ""})

    engine_task = asyncio.create_task(_produce_engine_events())
    heartbeat_task = asyncio.create_task(_produce_heartbeats())

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield format_sse(item)

        # Scan artifacts and send workflow_complete (must be inside try, before finally)
        filenames = _scan_artifacts()
        yield format_sse({
            "type": "workflow_complete",
            "session_id": session_id,
            "text": "Analysis complete",
            "filenames": filenames,
        })
        yield format_sse({"type": "done", "text": ""})
    finally:
        heartbeat_event.set()
        heartbeat_task.cancel()
        await asyncio.gather(engine_task, heartbeat_task, return_exceptions=True)


def _scan_artifacts() -> list[str]:
    """Scan ./artifacts/ for report files."""
    filenames = []
    if not ARTIFACTS_DIR.exists():
        return filenames
    for f in sorted(ARTIFACTS_DIR.rglob("*")):
        if f.is_file() and f.suffix.lower() in _REPORT_EXTENSIONS:
            filenames.append(str(f.relative_to(ARTIFACTS_DIR)))
    return filenames


_analysis_in_progress = False

@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    global _analysis_in_progress
    if _analysis_in_progress:
        return Response(
            content=format_sse({"type": "error", "text": "Analysis already in progress. Please wait."}),
            media_type="text/event-stream",
            status_code=429,
        )
    _analysis_in_progress = True
    logger.info(f"Analyze: upload_id={request.upload_id}, query={request.query[:80]}...")

    async def _guarded_sse():
        global _analysis_in_progress
        try:
            async for event in sse_generator(request.upload_id, request.query):
                yield event
        finally:
            _analysis_in_progress = False

    return StreamingResponse(
        _guarded_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


# ---------- HITL Feedback ----------
@app.post("/feedback")
async def feedback(request: FeedbackRequest):
    hitl_manager.submit_feedback(request.approved, request.feedback)
    logger.info(f"Feedback received: approved={request.approved}, feedback={request.feedback[:80]}")
    return {"success": True}


# ---------- Artifacts ----------
@app.get("/artifacts/{session_id}")
def list_artifacts(session_id: str):
    if not _SAFE_ID.match(session_id):
        return {"success": False, "error": "Invalid session_id"}
    filenames = _scan_artifacts()
    return {"success": True, "session_id": session_id, "filenames": filenames}


@app.get("/download/{session_id}/{filename:path}")
def download_artifact(session_id: str, filename: str):
    if not _SAFE_ID.match(session_id):
        return {"success": False, "error": "Invalid session_id"}
    if ".." in filename or filename.startswith("/"):
        return {"success": False, "error": "Invalid filename"}

    file_path = ARTIFACTS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        return {"success": False, "error": "File not found"}
    if not file_path.resolve().is_relative_to(ARTIFACTS_DIR.resolve()):
        return {"success": False, "error": "Invalid path"}

    download_name = filename.rsplit("/", 1)[-1]
    ext = download_name.rsplit(".", 1)[-1] if "." in download_name else "bin"
    ascii_fallback = f"download.{ext}"
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(download_name)}"

    body = file_path.read_bytes()
    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(body)),
        },
    )


# ---------- Cleanup (delete user data + artifacts) ----------
@app.delete("/cleanup/{session_id}")
async def cleanup(session_id: str):
    """Delete all uploaded data and generated artifacts for a session."""
    if not _SAFE_ID.match(session_id):
        return {"success": False, "error": "Invalid session_id"}

    import shutil
    deleted = []

    # Delete uploaded data
    upload_dir = UPLOAD_DIR / session_id
    if upload_dir.exists() and upload_dir.resolve().is_relative_to(UPLOAD_DIR.resolve()):
        shutil.rmtree(upload_dir)
        deleted.append(f"uploads/{session_id}")

    # Delete artifacts
    if ARTIFACTS_DIR.exists():
        shutil.rmtree(ARTIFACTS_DIR)
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        deleted.append("artifacts")

    logger.info(f"Cleanup: session={session_id}, deleted={deleted}")
    return {"success": True, "deleted": deleted}


# ---------- Auth (Phase 2 — Cognito OAuth callback) ----------
@app.get("/auth/callback")
async def auth_callback(code: str = ""):
    """Exchange Cognito authorization code for tokens, set cookie, redirect to /."""
    if not code or not COGNITO_DOMAIN:
        return RedirectResponse("/")

    token_url = f"{COGNITO_DOMAIN}/oauth2/token"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": COGNITO_CLIENT_ID,
                "redirect_uri": COGNITO_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        logger.error(f"Token exchange failed: {resp.text}")
        return Response(status_code=401, content="Authentication failed")

    tokens = resp.json()
    response = RedirectResponse("/")
    # Set id_token cookie (Lambda@Edge checks this)
    response.set_cookie(
        "id_token", tokens["id_token"],
        httponly=True, secure=True, samesite="lax",
        max_age=tokens.get("expires_in", 3600),
    )
    return response


@app.get("/auth/logout")
async def auth_logout():
    """Clear auth cookie and redirect to Cognito logout."""
    if COGNITO_DOMAIN:
        base_url = COGNITO_REDIRECT_URI.rsplit("/auth", 1)[0]
        logout_url = (
            f"{COGNITO_DOMAIN}/logout?client_id={COGNITO_CLIENT_ID}"
            f"&response_type=code"
            f"&redirect_uri={quote(COGNITO_REDIRECT_URI)}"
        )
        response = RedirectResponse(logout_url)
    else:
        response = RedirectResponse("/")
    response.delete_cookie("id_token")
    return response


# ---------- Main ----------
if __name__ == "__main__":
    logger.info(f"Starting Deep Insight (self-hosted) on {HOST}:{PORT}")
    logger.info(f"Static dir: {STATIC_DIR}")
    logger.info(f"Upload dir: {UPLOAD_DIR}")
    uvicorn.run(app, host=HOST, port=PORT)
