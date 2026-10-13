"""
Admin Router — FastAPI APIRouter for /admin/* routes.

Provides authentication (Cognito) and job monitoring API for the admin dashboard.
All routes are prefixed with /admin. Protected routes use require_admin dependency.
"""

import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from ops.auth import require_admin

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.environ.get("COGNITO_CLIENT_ID", "")
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "")

OPS_STATIC_DIR = Path(__file__).resolve().parent / "static"

admin_router = APIRouter(prefix="/admin")

_ADMIN_STATIC_EXT = {".js", ".css"}


@admin_router.get("/static/{filename}")
def admin_static(filename: str):
    """Serve admin static assets (JS, CSS only)."""
    file_path = OPS_STATIC_DIR / filename
    if file_path.suffix.lower() not in _ADMIN_STATIC_EXT:
        raise HTTPException(status_code=404)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404)
    if not file_path.resolve().is_relative_to(OPS_STATIC_DIR.resolve()):
        raise HTTPException(status_code=404)
    return FileResponse(file_path)


# ---------- Request Models ----------


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    username: str
    session: str
    new_password: str


# ---------- Cookie Helper ----------

_COOKIE_OPTS = {
    "key": "token",
    "httponly": True,
    "samesite": "Lax",
    "path": "/admin",
    "secure": False,  # Phase 2: True when HTTPS added
    "max_age": 3600,  # 1 hour, matches Cognito token expiry
}


def _set_auth_cookie(response, token: str):
    """Set JWT token as HTTP-only cookie."""
    response.set_cookie(value=token, **_COOKIE_OPTS)


# ---------- Public Routes (no auth) ----------


@admin_router.get("/login", response_class=HTMLResponse)
def login_page():
    """Serve the admin login page."""
    html_path = OPS_STATIC_DIR / "login.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Admin login page not deployed yet</h1>", status_code=503)
    return HTMLResponse(html_path.read_text())


@admin_router.post("/login")
def login(request: LoginRequest):
    """Authenticate via Cognito InitiateAuth."""
    if not COGNITO_USER_POOL_ID or not COGNITO_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Cognito not configured")

    try:
        cognito = boto3.client("cognito-idp", region_name=AWS_REGION)
        result = cognito.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": request.username,
                "PASSWORD": request.password,
            },
        )

        # Check for NEW_PASSWORD_REQUIRED challenge (first login)
        if result.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
            return JSONResponse({
                "challenge": "NEW_PASSWORD_REQUIRED",
                "session": result["Session"],
                "username": request.username,
            })

        # Successful authentication
        token = result["AuthenticationResult"]["IdToken"]
        response = JSONResponse({"success": True, "redirect": "/admin/dashboard"})
        _set_auth_cookie(response, token)
        return response

    except cognito.exceptions.NotAuthorizedException:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    except cognito.exceptions.UserNotFoundException:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")


@admin_router.post("/change-password")
def change_password(request: ChangePasswordRequest):
    """Handle NEW_PASSWORD_REQUIRED challenge (first login)."""
    if not COGNITO_USER_POOL_ID or not COGNITO_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Cognito not configured")

    try:
        cognito = boto3.client("cognito-idp", region_name=AWS_REGION)
        result = cognito.respond_to_auth_challenge(
            ClientId=COGNITO_CLIENT_ID,
            ChallengeName="NEW_PASSWORD_REQUIRED",
            Session=request.session,
            ChallengeResponses={
                "USERNAME": request.username,
                "NEW_PASSWORD": request.new_password,
            },
        )

        token = result["AuthenticationResult"]["IdToken"]
        response = JSONResponse({"success": True, "redirect": "/admin/dashboard"})
        _set_auth_cookie(response, token)
        return response

    except cognito.exceptions.InvalidPasswordException:
        raise HTTPException(
            status_code=400,
            detail="Password does not meet requirements: min 12 chars, uppercase, lowercase, number, symbol",
        )
    except Exception as e:
        logger.error(f"Change password failed: {e}")
        raise HTTPException(status_code=500, detail="Password change failed")


@admin_router.post("/logout")
def logout():
    """Clear JWT cookie."""
    response = JSONResponse({"success": True})
    response.delete_cookie(key="token", path="/admin")
    return response


# ---------- Protected Routes (require auth) ----------


@admin_router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(claims: dict = Depends(require_admin)):
    """Serve the admin dashboard page."""
    html_path = OPS_STATIC_DIR / "jobs.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Admin dashboard not deployed yet</h1>", status_code=503)
    return HTMLResponse(html_path.read_text())


@admin_router.get("/dashboard/{job_id}")
def job_detail_page(job_id: str, claims: dict = Depends(require_admin)):
    """Old job page URL: the job list opens the job in its side panel."""
    if not _SAFE_ID.match(job_id):
        raise HTTPException(status_code=404)
    return RedirectResponse(f"/admin/dashboard?job={job_id}")


@admin_router.get("/api/jobs")
def list_jobs(status: str = "", claims: dict = Depends(require_admin)):
    """Query jobs from DynamoDB. Optional status filter."""
    if not DYNAMODB_TABLE_NAME:
        return {"success": False, "error": "DYNAMODB_TABLE_NAME not configured"}

    try:
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)

        if status:
            # Query StatusStartedIndex GSI with status filter
            response = table.query(
                IndexName="StatusStartedIndex",
                KeyConditionExpression="status = :s",
                ExpressionAttributeValues={":s": status},
                ScanIndexForward=False,  # newest first
            )
        else:
            # Scan all jobs, sorted client-side
            response = table.scan()

        items = response.get("Items", [])

        # Sort by started_at descending (scan results are unsorted)
        items.sort(key=lambda x: x.get("started_at", 0), reverse=True)

        return {"success": True, "jobs": [_to_json(item) for item in items]}

    except Exception as e:
        logger.error(f"List jobs failed: {e}")
        return {"success": False, "error": "Failed to retrieve jobs"}


@admin_router.get("/api/jobs/{job_id}")
def get_job(job_id: str, claims: dict = Depends(require_admin)):
    """Get a single job record from DynamoDB."""
    if not DYNAMODB_TABLE_NAME:
        return {"success": False, "error": "DYNAMODB_TABLE_NAME not configured"}

    try:
        return {"success": True, "job": _to_json(_get_job_item(job_id))}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get job failed: {e}")
        return {"success": False, "error": "Failed to retrieve job"}


# ---------- Job trace, artifacts and files ----------
#
#   deep-insight/traces/{job_id}/events.jsonl              agent trace, updated after
#                                                          each agent invocation
#   deep-insight/fargate_sessions/{session_id}/artifacts/  generated files (session_id
#                                                          reaches the record at the end)
#   uploads/{job_id}/                                      input data

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_SESSIONS_PREFIX = "deep-insight/fargate_sessions/"
_TRACES_PREFIX = "deep-insight/traces/"

# Served inline (previews); everything else downloads. Inline responses carry
# CSP sandbox so an SVG or text file can't run script on the admin origin.
_INLINE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
    ".csv": "text/plain; charset=utf-8", ".json": "text/plain; charset=utf-8",
    ".py": "text/plain; charset=utf-8", ".log": "text/plain; charset=utf-8",
    ".html": "text/plain; charset=utf-8",
}


def _to_json(item: dict) -> dict:
    """Convert a DynamoDB item (Decimal numbers) to JSON-serializable values."""
    job = {}
    for k, v in item.items():
        if hasattr(v, "as_integer_ratio"):
            job[k] = int(v) if v == int(v) else float(v)
        elif isinstance(v, list):
            job[k] = [str(i) for i in v]
        else:
            job[k] = str(v) if not isinstance(v, (str, bool)) else v
    return job


def _get_job_item(job_id: str) -> dict:
    """Get the job record, or raise 404."""
    if not _SAFE_ID.match(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(DYNAMODB_TABLE_NAME)
    item = table.get_item(Key={"job_id": job_id}).get("Item")
    if not item:
        raise HTTPException(status_code=404, detail="Job not found")
    return item


def _job_prefix(item: dict, area: str) -> str:
    """S3 prefix of one file area of the job; "" if artifacts have no session yet."""
    if area == "input":
        return f"uploads/{item['job_id']}/"
    if area == "artifacts":
        session_id = str(item.get("session_id", ""))
        return f"{_SESSIONS_PREFIX}{session_id}/artifacts/" if _SAFE_ID.match(session_id) else ""
    raise HTTPException(status_code=404)


def _list_files(s3, prefix: str) -> list:
    files = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            name = obj["Key"].removeprefix(prefix)
            if name:
                files.append({"name": name, "size": obj["Size"]})
    return files


@admin_router.get("/api/jobs/{job_id}/trace")
def get_job_trace(job_id: str, claims: dict = Depends(require_admin)):
    """Agent trace recorded by the runtime (events.jsonl), one record per step.

    A running job's trace covers the agents finished so far. available=False
    for jobs that ran before the runtime recorded traces, or whose first agent
    hasn't finished yet.
    """
    if not S3_BUCKET_NAME:
        return {"success": False, "error": "S3_BUCKET_NAME not configured"}
    try:
        item = _get_job_item(job_id)
        # trace_path is set when the job ends; until then the trace is at its job_id key
        trace_path = str(item.get("trace_path", "")) or f"{_TRACES_PREFIX}{job_id}/events.jsonl"
        if not trace_path.startswith((_TRACES_PREFIX, _SESSIONS_PREFIX)):
            return {"success": True, "available": False, "records": []}

        s3 = boto3.client("s3", region_name=AWS_REGION)
        try:
            body = s3.get_object(Bucket=S3_BUCKET_NAME, Key=trace_path)["Body"].read().decode("utf-8")
        except ClientError as e:
            # Without s3:ListBucket on output/, a missing key is AccessDenied, not NoSuchKey
            if e.response["Error"]["Code"] not in ("NoSuchKey", "AccessDenied"):
                raise
            logger.info(f"No trace for job {job_id} at {trace_path} ({e.response['Error']['Code']})")
            return {"success": True, "available": False, "records": []}

        records = []
        for line in body.splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        return {"success": True, "available": True, "records": records}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get job trace failed: {e}")
        return {"success": False, "error": "Failed to retrieve trace"}


@admin_router.get("/api/jobs/{job_id}/files")
def list_job_files(job_id: str, claims: dict = Depends(require_admin)):
    """List the job's generated artifacts and input data files."""
    if not S3_BUCKET_NAME:
        return {"success": False, "error": "S3_BUCKET_NAME not configured"}
    try:
        item = _get_job_item(job_id)
        s3 = boto3.client("s3", region_name=AWS_REGION)
        result = {"success": True}
        for area in ("artifacts", "input"):
            prefix = _job_prefix(item, area)
            result[area] = _list_files(s3, prefix) if prefix else []
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List job files failed: {e}")
        return {"success": False, "error": "Failed to list files"}


@admin_router.get("/api/jobs/{job_id}/files/{area}/{filename:path}")
def get_job_file(job_id: str, area: str, filename: str, download: bool = False,
                 claims: dict = Depends(require_admin)):
    """Proxy one job file: inline preview for images and text, else a download."""
    if ".." in filename.split("/") or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not S3_BUCKET_NAME:
        raise HTTPException(status_code=503, detail="S3_BUCKET_NAME not configured")
    prefix = _job_prefix(_get_job_item(job_id), area)
    if not prefix:
        raise HTTPException(status_code=404, detail="File not found")
    key = prefix + filename

    try:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
    except Exception as e:
        logger.error(f"Get job file failed: {key}: {e}")
        raise HTTPException(status_code=404, detail="File not found")

    # Streamed in chunks: a large input CSV must not be held in the web task's memory
    body = obj["Body"].iter_chunks(chunk_size=1024 * 1024)
    length = {"Content-Length": str(obj["ContentLength"])} if obj.get("ContentLength") is not None else {}
    name = filename.rsplit("/", 1)[-1]
    inline_type = _INLINE_TYPES.get(Path(name).suffix.lower())
    if inline_type and not download:
        return StreamingResponse(body, media_type=inline_type, headers={
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            **length,
        })

    # RFC 5987: ASCII fallback + UTF-8 encoded filename for non-ASCII characters
    ext = name.rsplit(".", 1)[-1] if "." in name else "bin"
    disposition = f"attachment; filename=\"download.{ext}\"; filename*=UTF-8''{quote(name)}"
    return StreamingResponse(body, media_type="application/octet-stream",
                             headers={"Content-Disposition": disposition, **length})
