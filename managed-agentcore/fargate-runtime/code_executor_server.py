#!/usr/bin/env python3
"""
Dynamic Code Executor for Fargate V2 - HTTP Server Version

Purpose:
    Flask-based HTTP server running in ECS Fargate containers that executes
    Python and Bash code dynamically. Each container manages a session of up to
    300 code executions and uploads all results to S3 upon completion.

Architecture:
    This executor runs in Fargate containers spawned by the AgentCore Runtime:

    1. AgentCore Runtime Container:
       - Manages agent workflow execution
       - Spawns Fargate containers on-demand via fargate_container_controller.py
       - Passes environment variables (SESSION_ID, AWS_REGION, S3_BUCKET_NAME)

    2. Fargate Executor Container (this file):
       - Receives code execution requests via HTTP POST /execute
       - Executes Python or Bash code in isolated environment
       - Stores results locally during session
       - Uploads all results to S3 at session completion
       - Auto-terminates after 1 hour

Execution Flow:
    1. Container starts with SESSION_ID from environment
    2. Flask server listens on port 8080
    3. ALB routes requests to container via sticky session cookies
    4. Execute endpoint receives and runs code (Python/Bash)
    5. Results stored locally: /tmp/session_{id}/execution_{n}.json
    6. Session completes when:
       - 300 executions reached, OR
       - POST /session/complete called
    7. All results uploaded to S3:
       - s3://{bucket}/deep-insight/fargate_sessions/{session_id}/debug/
       - s3://{bucket}/deep-insight/fargate_sessions/{session_id}/artifacts/
       - s3://{bucket}/deep-insight/fargate_sessions/{session_id}/data/

HTTP Endpoints:
    GET  /health              - ALB health check (returns session status)
    GET  /container-info      - Container metadata (IP, session_id, sticky session)
    POST /execute             - Execute Python or Bash code
    POST /session/complete    - Force session completion and S3 upload
    POST /file-sync           - S3 file synchronization (upload/download)

Environment Variables:
    Required (all passed from AgentCore Runtime):
    - SESSION_ID: Unique session identifier
    - AWS_REGION: AWS region for S3 operations
    - S3_BUCKET_NAME: S3 bucket for result uploads

Code Execution:
    Python Code:
        - Executed via exec() in isolated namespace
        - stdout/stderr captured and returned
        - Auto-imports: datetime, json, os
        - Working directory: /app/

    Bash Commands:
        - Prefix with "BASH:" to execute shell commands
        - Executed via subprocess.run() with shell=True
        - Working directory: /app/
        - 30-second timeout per command

File Management:
    - /app/data/: Data files (CSV, input files)
    - /app/artifacts/: Generated files (charts, PDFs, reports)
    - All files uploaded to S3 at session completion

Session Lifecycle:
    1. Initialize: SessionManager creates workspace /tmp/session_{id}/
    2. Execute: Up to 300 code executions, results saved locally
    3. Complete: Upload all results to S3 (debug/, artifacts/, data/)
    4. Terminate: Container exits after 1 hour (auto-shutdown)

Error Handling:
    - Execution errors: Captured with compact traceback
    - Large outputs: Truncated to 8192 chars for streaming stability
    - Container crashes: Prevented with explicit exception handling
    - S3 upload failures: Logged but don't block completion

Performance:
    - Mid-session S3 uploads: DISABLED (caused HTTP 502 errors)
    - S3 uploads: Only at session completion (one batch upload)
    - Output streaming: Compact format to prevent network issues
    - Auto-shutdown: 1 hour timeout to prevent resource leaks

Related Files:
    - src/tools/fargate_container_controller.py: Spawns Fargate containers
    - src/tools/global_fargate_coordinator.py: Session management
    - agentcore_runtime.py: AgentCore runtime entry point

Usage:
    # In Fargate container (auto-started by ECS)
    python3 code_executor_server.py

    # Execute Python code via HTTP
    curl -X POST http://container:8080/execute \
      -H "Content-Type: application/json" \
      -d '{"code": "print(\"Hello from Fargate\")"}'

    # Execute Bash command
    curl -X POST http://container:8080/execute \
      -H "Content-Type: application/json" \
      -d '{"code": "BASH: ls -la /app/data"}'
"""

import sys
import os
import json
import uuid
import traceback
import threading
import time
import subprocess
import re
from datetime import datetime
from io import StringIO
import contextlib
import boto3
from flask import Flask, request, jsonify
from pathlib import Path
import shutil

app = Flask(__name__)

# Global session state management
class SessionManager:
    def __init__(self):
        self.session_id = os.environ.get('SESSION_ID', str(uuid.uuid4())[:8])
        self.executions = []
        self.max_executions = 300
        self.start_time = datetime.now()
        self.is_complete = False
        self.workspace = f"/tmp/session_{self.session_id}"
        os.makedirs(self.workspace, exist_ok=True)

        # Create data and artifacts directories for file I/O
        self.data_dir = "/app/data"
        self.artifacts_dir = "/app/artifacts"
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.artifacts_dir, exist_ok=True)

    def add_execution(self, result):
        self.executions.append(result)
        execution_num = len(self.executions)

        # Save each execution result locally
        output_file = f"{self.workspace}/execution_{execution_num}.json"

        # Convert execution_time_ms to duration_ms for saving
        save_result = result.copy()
        if 'execution_time_ms' in save_result:
            save_result['duration_ms'] = save_result.pop('execution_time_ms')

        with open(output_file, 'w') as f:
            json.dump(save_result, f, indent=2)

        print(f"💾 Saved execution {execution_num} to {output_file}", flush=True)

        # Complete session after max executions reached
        if execution_num >= self.max_executions:
            self.complete_session()

    def complete_session(self):
        """Complete session - Upload all results to S3"""
        if self.is_complete:
            return

        self.is_complete = True
        print(f"🏁 Session {self.session_id} complete. Uploading to S3...", flush=True)

        try:
            # Generate complete session result
            session_result = {
                "session_id": self.session_id,
                "total_executions": len(self.executions),
                "start_time": str(self.start_time),
                "end_time": str(datetime.now()),
                "executions": self.executions
            }

            # Upload to S3
            self.upload_to_s3(session_result)

            print(f"✅ Session {self.session_id} uploaded to S3", flush=True)
        except Exception as e:
            print(f"❌ Failed to upload session to S3: {e}", flush=True)

    def upload_to_s3(self, session_result):
        """Upload session results and generated files to S3"""
        # Note: AWS_REGION and S3_BUCKET_NAME are ALWAYS passed from AgentCore Runtime
        aws_region = os.environ.get('AWS_REGION')
        bucket = os.environ.get('S3_BUCKET_NAME')

        if not aws_region:
            raise ValueError("AWS_REGION environment variable is required but not set")
        if not bucket:
            raise ValueError("S3_BUCKET_NAME environment variable is required but not set")

        s3_client = boto3.client('s3', region_name=aws_region)

        print(f"☁️ Starting S3 upload to s3://{bucket}/deep-insight/fargate_sessions/{self.session_id}/", flush=True)

        # Save complete session result to debug folder
        s3_key = f"deep-insight/fargate_sessions/{self.session_id}/debug/session_status.json"
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=json.dumps(session_result, indent=2),
            ContentType='application/json'
        )
        print(f"  📄 Uploaded debug/session_status.json", flush=True)

        # Save individual execution results to debug folder
        for i, execution in enumerate(self.executions, 1):
            s3_key = f"deep-insight/fargate_sessions/{self.session_id}/debug/execution_{i}.json"
            s3_client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=json.dumps(execution, indent=2),
                ContentType='application/json'
            )
        print(f"  📄 Uploaded {len(self.executions)} execution result files to debug/", flush=True)

        # Upload artifacts folder (generated files)
        artifacts_path = "/app/artifacts"
        if os.path.exists(artifacts_path):
            artifacts_uploaded = self._upload_directory_to_s3(
                s3_client, bucket, artifacts_path,
                f"deep-insight/fargate_sessions/{self.session_id}/artifacts"
            )
            print(f"  📁 Uploaded {artifacts_uploaded} files from artifacts/", flush=True)

        # Upload data folder (CSV and input data files)
        data_path = "/app/data"
        if os.path.exists(data_path):
            data_uploaded = self._upload_directory_to_s3(
                s3_client, bucket, data_path,
                f"deep-insight/fargate_sessions/{self.session_id}/data"
            )
            print(f"  📁 Uploaded {data_uploaded} files from data/", flush=True)

        print(f"✅ S3 upload completed for session {self.session_id}", flush=True)

    def _upload_directory_to_s3(self, s3_client, bucket, local_dir, s3_prefix):
        """Upload all files in directory to S3"""
        uploaded_count = 0

        for root, dirs, files in os.walk(local_dir):
            for file in files:
                local_file_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_file_path, local_dir)
                s3_key = f"{s3_prefix}/{relative_path}".replace('\\', '/')

                try:
                    # Set ContentType based on file extension
                    content_type = 'application/octet-stream'
                    if file.endswith('.json'):
                        content_type = 'application/json'
                    elif file.endswith('.txt'):
                        content_type = 'text/plain'
                    elif file.endswith('.csv'):
                        content_type = 'text/csv'
                    elif file.endswith('.png'):
                        content_type = 'image/png'
                    elif file.endswith('.jpg') or file.endswith('.jpeg'):
                        content_type = 'image/jpeg'
                    elif file.endswith('.pdf'):
                        content_type = 'application/pdf'
                    elif file.endswith('.py'):
                        content_type = 'text/x-python'

                    s3_client.upload_file(
                        local_file_path, bucket, s3_key,
                        ExtraArgs={'ContentType': content_type}
                    )
                    uploaded_count += 1
                    print(f"    📤 {relative_path} → s3://{bucket}/{s3_key}", flush=True)
                except Exception as e:
                    print(f"    ❌ Upload failed for {relative_path}: {e}", flush=True)

        return uploaded_count

# Initialize session manager
session_manager = SessionManager()

def create_compact_error_response(exception, traceback_text=None):
    """
    Create compact error response suitable for streaming

    Args:
        exception: Exception object that occurred
        traceback_text: Result from traceback.format_exc()

    Returns:
        dict: Compact error information
    """
    error_type = type(exception).__name__
    error_message = str(exception)

    # Limit message length (8192 chars)
    if len(error_message) > 4096*2:
        error_message = error_message[:4096*2] + "..."

    # Extract line number
    line_number = None
    if traceback_text:
        # Extract line number from patterns like "line 205"
        line_match = re.search(r'line (\d+)', traceback_text)
        if line_match:
            line_number = int(line_match.group(1))

    # Extract key information by error type
    key_info = extract_error_key_info(error_type, error_message, traceback_text)

    compact_error = {
        "type": error_type,
        "message": error_message,
        "line": line_number,
        "key_info": key_info
    }

    # Include full traceback (8192 char limit)
    if traceback_text:
        if len(traceback_text) > 4096*2:
            compact_error["traceback"] = traceback_text[:4096*2] + "..."
        else:
            compact_error["traceback"] = traceback_text

    return compact_error

def extract_error_key_info(error_type, error_message, traceback_text):
    """Extract key information by error type"""
    key_info = {}

    if error_type == "SyntaxError":
        # Extract specific issues for syntax errors
        if "invalid decimal literal" in error_message:
            key_info["issue"] = "Invalid number format (possibly CSS in Python code)"
        elif "format code" in error_message:
            key_info["issue"] = "f-string formatting error"
        elif "unexpected EOF" in error_message:
            key_info["issue"] = "Missing closing bracket or quote"

    elif error_type == "ValueError":
        if "Unknown format code" in error_message:
            key_info["issue"] = "f-string format specifier error"
        elif "Cannot specify" in error_message:
            key_info["issue"] = "Invalid format combination"

    elif error_type == "NameError":
        # Extract variable name
        if "is not defined" in error_message:
            var_match = re.search(r"'(\w+)' is not defined", error_message)
            if var_match:
                key_info["undefined_variable"] = var_match.group(1)

    elif error_type == "ImportError" or error_type == "ModuleNotFoundError":
        # Extract module name
        module_match = re.search(r"No module named '(\w+)'", error_message)
        if module_match:
            key_info["missing_module"] = module_match.group(1)

    return key_info

def create_compact_output(output_text, output_type="stdout", max_length=500):
    """
    Create compact output suitable for streaming

    Args:
        output_text: Original output text
        output_type: Output type ("stdout" or "stderr")
        max_length: Maximum length (default: 500 chars)

    Returns:
        str or dict: Compact output information
    """
    if not output_text or not output_text.strip():
        return output_text

    # Original length
    original_length = len(output_text)

    # Return as-is if within limit
    if original_length <= max_length:
        return output_text

    # Generate summary if exceeds limit
    lines = output_text.strip().split('\n')
    total_lines = len(lines)

    # Keep first 3 and last 3 lines only
    if total_lines > 6:
        first_lines = '\n'.join(lines[:3])
        last_lines = '\n'.join(lines[-3:])
        compact_text = f"{first_lines}\n\n... ({total_lines - 6} lines omitted) ...\n\n{last_lines}\n\n[Output truncated: {original_length} chars, {total_lines} lines total]"
    else:
        # Simple truncation if few lines
        compact_text = output_text[:max_length] + f"...\n\n[Output truncated: {original_length} chars total]"

    return compact_text

def execute_code(code_string, execution_num):
    """Execute dynamic code and return results (Python code or Bash commands)"""

    print(f"🚀 Execution {execution_num} starting...", flush=True)

    # Detect code type
    code_type = "bash" if code_string.strip().startswith("BASH:") else "python"

    if code_type == "bash":
        # Remove BASH: prefix
        bash_command = code_string.strip()[5:].strip()
        print(f"🐧 Executing bash command: {bash_command}", flush=True)
    else:
        print(f"🐍 Executing python code", flush=True)

    # Get container IP
    import socket
    try:
        hostname = socket.gethostname()
        container_ip = socket.gethostbyname(hostname)
    except Exception:
        container_ip = "unknown"

    result = {
        "execution_num": execution_num,
        "timestamp": str(datetime.now()),
        "code": code_string[:200] + "..." if len(code_string) > 200 else code_string,
        "code_type": code_type,
        "status": "running",
        "stdout": "",
        "stderr": "",
        "error": None,
        "execution_time_ms": 0,
        "container_ip": container_ip
    }

    start_time = datetime.now()

    try:
        if code_type == "bash":
            # Execute bash command (set working directory to /app/)
            process = subprocess.run(
                bash_command,
                shell=True,
                capture_output=True,
                text=True,
                cwd="/app",
                timeout=30
            )

            result["status"] = "completed" if process.returncode == 0 else "failed"
            result["stdout"] = process.stdout
            result["stderr"] = process.stderr

            if process.returncode != 0:
                result["error"] = {
                    "type": "BashError",
                    "message": f"Command failed with return code {process.returncode}",
                    "return_code": process.returncode
                }
                print(f"❌ Bash execution {execution_num} failed with code {process.returncode}", flush=True)
            else:
                print(f"✅ Bash execution {execution_num} completed successfully", flush=True)

        else:
            # Execute Python code
            stdout_capture = StringIO()
            stderr_capture = StringIO()

            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                # Add necessary imports automatically
                exec_globals = {
                    '__builtins__': __builtins__,
                    'datetime': datetime,
                    'json': json,
                    'os': os,
                    'workspace': session_manager.workspace
                }

                # Execute code - Explicit exception handling to prevent container instability
                try:
                    exec(code_string, exec_globals)
                    result["status"] = "completed"
                except Exception as exec_error:
                    # Catch exec() errors immediately to prevent container crash
                    result["status"] = "failed"
                    traceback_text = traceback.format_exc()
                    result["error"] = create_compact_error_response(exec_error, traceback_text)
                    print(f"❌ Python execution {execution_num} failed during exec(): {exec_error}", flush=True)

            # Capture stdout/stderr regardless of success or failure
            result["stdout"] = stdout_capture.getvalue()
            result["stderr"] = stderr_capture.getvalue()

            if result["status"] == "completed":
                print(f"✅ Python execution {execution_num} completed successfully", flush=True)

    except subprocess.TimeoutExpired:
        result["status"] = "failed"
        result["error"] = {
            "type": "TimeoutError",
            "message": "Command timed out after 30 seconds"
        }
        print(f"⏰ Execution {execution_num} timed out", flush=True)

    except Exception as e:
        result["status"] = "failed"
        if code_type == "python":
            result["stdout"] = stdout_capture.getvalue()
            result["stderr"] = stderr_capture.getvalue()

        # Create compact error response suitable for streaming
        traceback_text = traceback.format_exc()
        result["error"] = create_compact_error_response(e, traceback_text)

        print(f"❌ Execution {execution_num} failed: {e}", flush=True)

    finally:
        end_time = datetime.now()
        result["execution_time_ms"] = int((end_time - start_time).total_seconds() * 1000)

    return result

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint (for ALB Health Check)"""
    return jsonify({
        "status": "healthy",
        "session_id": session_manager.session_id,
        "executions_completed": len(session_manager.executions),
        "max_executions": session_manager.max_executions,
        "is_complete": session_manager.is_complete
    })


@app.route('/container-info', methods=['GET'])
def container_info():
    """Return container information (for Sticky Session cookie validation)

    Multi-Job support:
    - Can validate specific session with session_id parameter
    - Returns known_sessions list of all session IDs this container knows
    """
    import socket
    try:
        hostname = socket.gethostname()
        private_ip = socket.gethostbyname(hostname)
    except Exception as e:
        hostname = "unknown"
        private_ip = "unknown"

    # List of session IDs this container knows
    # session_manager.session_id is the session this container was started with
    known_sessions = [session_manager.session_id] if session_manager.session_id else []

    return jsonify({
        "private_ip": private_ip,
        "hostname": hostname,
        "session_id": session_manager.session_id,  # Main session for this container
        "known_sessions": known_sessions,  # For multi-job validation
        "executions_completed": len(session_manager.executions)
    })

@app.route('/execute', methods=['POST'])
def execute():
    """Code execution endpoint"""

    if session_manager.is_complete:
        return jsonify({
            "error": "Session is already complete",
            "session_id": session_manager.session_id
        }), 400

    # Get code from request
    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({"error": "No code provided"}), 400

    code = data['code']
    execution_num = len(session_manager.executions) + 1

    # Execute code
    result = execute_code(code, execution_num)

    # Save execution result
    session_manager.add_execution(result)

    # Limit stdout/stderr output size for streaming stability
    compact_stdout = create_compact_output(result["stdout"], "stdout", max_length=4096*2)
    compact_stderr = create_compact_output(result["stderr"], "stderr", max_length=4096*2)

    # Return response
    response_data = {
        "session_id": session_manager.session_id,
        "execution_num": execution_num,
        "status": result["status"],
        "stdout": compact_stdout,
        "stderr": compact_stderr,
        "error": result["error"],
        "execution_time_ms": result["execution_time_ms"],
        "total_executions": len(session_manager.executions),
        "is_session_complete": session_manager.is_complete,
        "s3_backup": "skipped_until_session_end"  # S3 upload only at session completion
    }

    return jsonify(response_data)

@app.route('/session/complete', methods=['POST'])
def complete_session():
    """Force session completion (can terminate before 300 executions)"""
    session_manager.complete_session()
    return jsonify({
        "message": "Session completed",
        "session_id": session_manager.session_id,
        "total_executions": len(session_manager.executions)
    })

@app.route('/file-sync', methods=['POST'])
def file_sync():
    """Handle file synchronization via S3"""

    try:
        data = request.get_json()
        if not data or 'action' not in data:
            return jsonify({"error": "No action specified"}), 400

        action = data['action']
        bucket_name = data.get('bucket_name')
        s3_key_prefix = data.get('s3_key_prefix')
        local_path = data.get('local_path')

        if not all([bucket_name, s3_key_prefix, local_path]):
            return jsonify({"error": "Missing required parameters"}), 400

        # Note: AWS_REGION is ALWAYS passed from AgentCore Runtime
        aws_region = os.environ.get('AWS_REGION')
        if not aws_region:
            return jsonify({"error": "AWS_REGION environment variable is required but not set"}), 500

        s3_client = boto3.client('s3', region_name=aws_region)

        if action == "sync_data_from_s3":
            # Download data from S3
            result = sync_from_s3(s3_client, bucket_name, s3_key_prefix, local_path)
            return jsonify(result)

        elif action == "sync_artifacts_to_s3":
            # Upload artifacts to S3
            result = sync_to_s3(s3_client, bucket_name, s3_key_prefix, local_path)
            return jsonify(result)

        else:
            return jsonify({"error": f"Unknown action: {action}"}), 400

    except Exception as e:
        print(f"❌ File sync error: {e}", flush=True)
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

def sync_from_s3(s3_client, bucket_name, s3_key_prefix, local_path):
    """Download files from S3 to local"""
    downloaded_files = []

    try:
        # Create local directory
        Path(local_path).mkdir(parents=True, exist_ok=True)

        # List S3 objects
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=s3_key_prefix
        )

        if 'Contents' not in response:
            print(f"⚠️ No files found in S3 with prefix: {s3_key_prefix}", flush=True)
            return {
                "status": "success",
                "message": "No files to download",
                "files_count": 0,
                "downloaded_files": []
            }

        for obj in response['Contents']:
            s3_key = obj['Key']

            # Extract relative path from S3 key
            relative_path = s3_key[len(s3_key_prefix):].lstrip('/')
            if not relative_path:  # Skip empty keys
                continue

            local_file_path = os.path.join(local_path, relative_path)

            # Create local directory
            local_file_dir = os.path.dirname(local_file_path)
            Path(local_file_dir).mkdir(parents=True, exist_ok=True)

            try:
                s3_client.download_file(bucket_name, s3_key, local_file_path)
                downloaded_files.append(local_file_path)
                print(f"  ⬇️ Downloaded: s3://{bucket_name}/{s3_key} → {local_file_path}", flush=True)
            except Exception as e:
                print(f"  ❌ Download failed for {s3_key}: {e}", flush=True)

        return {
            "status": "success",
            "message": f"Downloaded {len(downloaded_files)} files from S3",
            "files_count": len(downloaded_files),
            "downloaded_files": downloaded_files
        }

    except Exception as e:
        print(f"❌ S3 download error: {e}", flush=True)
        return {
            "status": "error",
            "message": str(e),
            "files_count": 0
        }

def sync_to_s3(s3_client, bucket_name, s3_key_prefix, local_path):
    """Upload files from local to S3"""
    uploaded_files = []

    try:
        if not os.path.exists(local_path):
            return {
                "status": "success",
                "message": "Local path does not exist",
                "files_count": 0,
                "uploaded_files": []
            }

        for root, dirs, files in os.walk(local_path):
            for file in files:
                local_file_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_file_path, local_path)
                s3_key = f"{s3_key_prefix}/{relative_path}".replace('\\', '/')

                try:
                    s3_client.upload_file(local_file_path, bucket_name, s3_key)
                    uploaded_files.append(s3_key)
                    print(f"  📤 Uploaded: {local_file_path} → s3://{bucket_name}/{s3_key}", flush=True)
                except Exception as e:
                    print(f"  ❌ Upload failed for {local_file_path}: {e}", flush=True)

        return {
            "status": "success",
            "message": f"Uploaded {len(uploaded_files)} files to S3",
            "files_count": len(uploaded_files),
            "uploaded_files": uploaded_files
        }

    except Exception as e:
        print(f"❌ S3 upload error: {e}", flush=True)
        return {
            "status": "error",
            "message": str(e),
            "files_count": 0
        }

def auto_shutdown():
    """Auto-shutdown after 1 hour"""
    time.sleep(3600)  # 1 hour

    print("⏰ Auto-shutdown timeout reached", flush=True)

    if not session_manager.is_complete:
        session_manager.complete_session()

    time.sleep(10)  # Wait for S3 upload completion
    sys.exit(0)

if __name__ == "__main__":
    print("=" * 60, flush=True)
    print("🔥 FARGATE DYNAMIC CODE EXECUTOR V2 - HTTP Server", flush=True)
    print(f"📍 Session ID: {session_manager.session_id}", flush=True)
    print(f"📊 Max Executions: {session_manager.max_executions}", flush=True)
    print("=" * 60, flush=True)

    # Start auto-shutdown thread
    shutdown_thread = threading.Thread(target=auto_shutdown)
    shutdown_thread.daemon = True
    shutdown_thread.start()

    # Start Flask server
    app.run(host='0.0.0.0', port=8080, debug=False)