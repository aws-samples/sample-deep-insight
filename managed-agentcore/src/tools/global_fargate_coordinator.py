#!/usr/bin/env python3
"""
Global Fargate Session Manager for Multi-Agent Workflows

This module provides a singleton session manager that coordinates Fargate container
sessions across multiple tools and concurrent requests in a multi-agent data analysis
environment.

Architecture:
    - Singleton Pattern: Single global instance manages all sessions
    - Session Isolation: Each request gets its own HTTP client, cookies, and container
    - Container Lifecycle: Automated creation, health checks, and cleanup
    - ALB Integration: Sticky session management with subprocess-based cookie acquisition
    - S3 Integration: Automatic data synchronization for CSV files
    - Error Handling: Exponential backoff retry with fail-fast for configuration errors

Key Features:
    1. Multi-Request Session Isolation
       - Separate HTTP clients per request (cookie isolation)
       - IP-based container ownership tracking
       - Prevents session conflicts in concurrent workflows

    2. Container Lifecycle Management
       - Fargate task creation with ECS
       - ALB target registration and health checks
       - Automatic cleanup on workflow completion
       - Orphaned container detection and cleanup

    3. ALB Sticky Session Management
       - Subprocess-based cookie acquisition (process isolation)
       - Round-robin retry logic for target IP matching
       - Session ID validation for multi-job support

    4. Robust Error Handling
       - Exponential backoff for transient errors (3^attempt)
       - Fail-fast for configuration errors (IAM, VPC, etc.)
       - Per-request failure tracking with limits

    5. S3 Data Synchronization
       - Local directory upload with session ID prefixes (CLI flow)
       - S3-to-S3 server-side copy for pre-uploaded data (web app flow)
       - Container file sync via HTTP API
       - Automatic cleanup on session completion

Usage Example:
    ```python
    # Get singleton instance
    session_mgr = get_global_session()

    # Set request context (required)
    session_mgr.set_request_context("request-123")

    # Create session with local directory data (CLI flow)
    success = session_mgr.ensure_session_with_directory("./data")

    # Or with S3 URL (web app flow)
    success = session_mgr.ensure_session_with_directory("s3://bucket/uploads/uuid/")

    # Execute code in container
    result = session_mgr.execute_code("import pandas as pd\\ndf = pd.read_csv('data/file.csv')")

    # Cleanup when done
    session_mgr.cleanup_session()
    ```

Environment Variables Required:
    - AWS_REGION: AWS region for service calls
    - ECS_CLUSTER_NAME: ECS cluster for Fargate tasks
    - ALB_TARGET_GROUP_ARN: ALB target group ARN
    - S3_BUCKET_NAME: S3 bucket for data/results
    - TASK_DEFINITION_ARN: ECS task definition ARN
    - CONTAINER_NAME: Container name in task definition

Thread Safety:
    This module is NOT thread-safe by design. It uses a singleton pattern with
    request context switching (`set_request_context()`). Each request should run
    sequentially or use separate process instances.

Notes:
    - Automatic cleanup registered via atexit
    - Cookies are session-specific (AWSALB sticky sessions)
    - Health checks wait up to 150 seconds for container readiness
    - Cookie acquisition timeout: 240 seconds (4 minutes)
"""

# ============================================================================
# IMPORTS
# ============================================================================

import logging
import os
import time
import json
import subprocess
import atexit
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables (don't override Runtime env vars)
load_dotenv(override=False)

# ECS and ALB configuration from environment
# These must be provided via environment variables (no hardcoded defaults)
ECS_CLUSTER_NAME = os.getenv("ECS_CLUSTER_NAME")
ALB_TARGET_GROUP_ARN = os.getenv("ALB_TARGET_GROUP_ARN")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# Third-party imports
import boto3
import requests
from botocore.exceptions import ClientError

# Local imports
from src.tools.fargate_container_controller import SessionBasedFargateManager

# ============================================================================
# LOGGER SETUP
# ============================================================================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================================
# GLOBAL FARGATE SESSION MANAGER (SINGLETON)
# ============================================================================

class GlobalFargateSessionManager:
    """
    Singleton session manager for coordinating Fargate container sessions.

    Features:
    - Per-request session isolation (cookies, HTTP clients, containers)
    - Exponential backoff retry for session creation
    - ALB health checks and sticky session management
    - S3 data synchronization
    - Automatic cleanup on exit
    """

    # ========================================================================
    # CLASS VARIABLES (SINGLETON STATE)
    # ========================================================================

    _instance = None
    _session_manager = None
    _sessions = {}  # {request_id: session_info} - Per-request session management
    _http_clients = {}  # {request_id: http_session} - Per-request HTTP client (cookie isolation)
    _used_container_ips = {}  # {container_ip: request_id} - IP-based container ownership tracking
    _current_request_id = None  # Current context request ID
    _session_creation_failures = {}  # {request_id: failure_count} - Session creation failure tracking
    _cleaned_up_requests = set()  # Cleaned-up request IDs (prevents recreation)

    # ========================================================================
    # CONSTANTS (TIMEOUTS AND RETRY LIMITS)
    # ========================================================================

    # Session Creation
    SESSION_CREATION_MAX_RETRIES = 5  # Maximum session creation retry attempts
    EXPONENTIAL_BACKOFF_BASE = 3      # Base for exponential backoff (3^attempt)

    # Code Execution
    CODE_EXECUTION_MAX_RETRIES = 3    # Maximum code execution retry attempts
    CODE_EXECUTION_RETRY_DELAY = 2    # Delay between retries (seconds)

    # ALB Health Check Wait Times (seconds)
    ALB_INITIAL_WAIT_DURATION = 60    # Total wait before health checks start
    ALB_WAIT_ITERATIONS = 6           # Number of keep-alive log iterations
    ALB_WAIT_INTERVAL = 10            # Interval for each iteration (60s / 6 = 10s)

    # Container Health Check (seconds)
    HEALTH_CHECK_MAX_ATTEMPTS = 30    # Maximum health check attempts
    HEALTH_CHECK_INTERVAL = 5         # Interval between health checks

    # Timeouts (seconds)
    COOKIE_ACQUISITION_TIMEOUT = 240  # Cookie acquisition subprocess timeout (4 minutes)
    FILE_SYNC_TIMEOUT = 30            # File sync HTTP request timeout
    FILE_SYNC_WAIT = 10               # Wait after file sync for completion

    # ========================================================================
    # 📦 INITIALIZATION (SINGLETON PATTERN)
    # ========================================================================

    def __new__(cls):
        """Singleton pattern implementation"""
        if cls._instance is None:
            cls._instance = super(GlobalFargateSessionManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the session manager (only once due to singleton)"""
        if self._session_manager is None:
            logger.info("🚀 Initializing Global Fargate Session Manager")
            self._session_manager = SessionBasedFargateManager()
            atexit.register(self._auto_cleanup)

    # ========================================================================
    # 🌐 PUBLIC API METHODS
    # ========================================================================

    def set_request_context(self, request_id: str):
        """Set current request context"""
        self._current_request_id = request_id
        logger.info(f"📋 Request context set: {request_id}")

    def ensure_session(self):
        """
        Ensure session exists or create new one (with exponential backoff retry)

        Returns:
            bool: True if session exists or was created successfully, False otherwise
        """
        try:
            if not self._current_request_id:
                raise Exception("Request context not set. Call set_request_context() first.")

            # Prevent new session creation for already cleaned-up requests
            if self._current_request_id in self._cleaned_up_requests:
                error_msg = f"❌ FATAL: Request {self._current_request_id} already cleaned up - cannot create new session. This prevents duplicate container creation after workflow completion."
                logger.error(error_msg)
                raise Exception(error_msg)

            # Check if session exists for current request
            if self._current_request_id in self._sessions:
                return self._reuse_existing_session()

            # Create new session with exponential backoff
            return self._create_new_session()

        except Exception as e:
            logger.error(f"❌ Failed to ensure session: {e}")

            # Re-raise fatal errors (stop workflow)
            if "FATAL" in str(e):
                raise

            return False

    def ensure_session_with_directory(self, data_directory: str):
        """
        Create session with directory data (recursive upload of all files).

        Supports two input types:
        - Local path (e.g., "./data"): Used by CLI invocation. Files are uploaded
          from the runtime container's local filesystem to S3.
        - S3 URL (e.g., "s3://bucket/uploads/uuid/"): Used by web app. Files are
          copied directly within S3 (server-side copy, no download needed).

        Both paths produce the same S3 prefix format, so the Fargate container
        sync step (step 3) is identical regardless of input type.

        Workflow:
        1. Create Fargate session (generates session ID)
        2. Upload local directory to S3 OR copy S3 directory to session prefix
        3. Sync S3 directory to Fargate container (recursive)

        Args:
            data_directory: Local path (e.g., "./data") or S3 URL (e.g., "s3://bucket/prefix/")

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"🚀 Creating session with directory data: {data_directory}")

            # Detect whether input is an S3 URL or a local filesystem path
            is_s3_path = data_directory.startswith("s3://")

            # Validate local path exists (S3 paths are validated during the copy step)
            if not is_s3_path:
                if not os.path.exists(data_directory):
                    raise Exception(f"Directory not found: {data_directory}")
                if not os.path.isdir(data_directory):
                    raise Exception(f"Path is not a directory: {data_directory}")

            # 1. Create session first (generates session ID)
            if not self.ensure_session():
                raise Exception("Failed to create Fargate session")

            # 2. Upload/copy data to session S3 prefix
            #    - S3 path: S3-to-S3 server-side copy (web upload flow)
            #    - Local path: local-to-S3 upload (CLI flow)
            session_id = self._sessions[self._current_request_id]['session_id']
            if is_s3_path:
                s3_prefix = self._copy_s3_directory_to_session(data_directory, session_id)
            else:
                s3_prefix = self._upload_directory_to_s3_with_session_id(data_directory, session_id)
            logger.info(f"📤 Directory ready in S3: {s3_prefix}")

            # 3. Sync S3 directory → container local storage (recursive)
            self._sync_directory_from_s3_to_container(s3_prefix)
            logger.info("✅ Directory synced to container")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to create session with directory data: {e}")
            return False

    def execute_code(self, code: str, description: str = ""):
        """
        Execute code with automatic session management and connection retry

        Args:
            code: Python code to execute
            description: Description of the code execution

        Returns:
            dict: Execution result or error
        """
        for attempt in range(1, self.CODE_EXECUTION_MAX_RETRIES + 1):
            try:
                # Ensure session exists
                if not self.ensure_session():
                    return {"error": "Failed to create or maintain session"}

                # Execute code
                result = self._session_manager.execute_code(code, description)

                # Return immediately on success
                return result

            except Exception as e:
                error_msg = str(e)

                # Check if it's a connection error
                is_connection_error = any(keyword in error_msg.upper() for keyword in [
                    "CONNECTION FAILED",
                    "NOT RESPONDING",
                    "TIMEOUT",
                    "CONNECTIONERROR",
                    "HTTPERROR"
                ])

                if is_connection_error:
                    # Connection error - retry
                    logger.warning(f"⚠️ Connection error (attempt {attempt}/{self.CODE_EXECUTION_MAX_RETRIES}): {error_msg}")

                    if attempt < self.CODE_EXECUTION_MAX_RETRIES:
                        logger.info(f"🔄 Retrying in {self.CODE_EXECUTION_RETRY_DELAY} seconds...")
                        time.sleep(self.CODE_EXECUTION_RETRY_DELAY)
                    else:
                        logger.error(f"❌ Connection failed after {self.CODE_EXECUTION_MAX_RETRIES} attempts. Giving up.")
                        return {
                            "error": f"Connection failed after {self.CODE_EXECUTION_MAX_RETRIES} attempts: {error_msg}"
                        }
                else:
                    # Code execution error - don't retry
                    logger.error(f"❌ Code execution failed: {e}")
                    # NOTE: Don't reset session to None!
                    # Keep session alive so next agent can retry
                    # Multiple agents share the same container, so don't reset session
                    return {"error": str(e)}

    def cleanup_session(self, request_id: str = None):
        """
        Clean up session for specific request

        Args:
            request_id: Request ID to cleanup (defaults to current request)
        """
        try:
            # Use current context if request_id not provided
            cleanup_request_id = request_id or self._current_request_id

            if not cleanup_request_id:
                logger.warning("⚠️ No request ID for cleanup")
                return

            if cleanup_request_id in self._sessions:
                session_info = self._sessions[cleanup_request_id]
                logger.info(f"🧹 Cleaning up session for request {cleanup_request_id}: {session_info['session_id']}")

                container_ip = session_info.get('container_ip')

                # FIX: Call complete_session() first (before ALB removal)
                # 1. Allow container to upload to S3 first
                logger.info(f"🏁 Completing session (S3 upload)...")
                self._session_manager.current_session = session_info['fargate_session']
                self._session_manager.complete_session()

                # 2. Then release container IP and remove from ALB (safe now)
                if container_ip and container_ip in self._used_container_ips:
                    del self._used_container_ips[container_ip]
                    logger.info(f"🧹 Released container IP: {container_ip}")
                    logger.info(f"   Remaining IPs: {list(self._used_container_ips.keys())}")

                    # Remove container from ALB Target Group (prevents zombie targets)
                    # Execute after complete_session() to prevent HTTP 502 errors
                    self._deregister_from_alb(container_ip)

                # Remove from session dictionary
                del self._sessions[cleanup_request_id]
                logger.info(f"✅ Session cleanup completed. Remaining sessions: {len(self._sessions)}")
            else:
                logger.warning(f"⚠️ No session found for request {cleanup_request_id}")

            # Clean up HTTP client (remove cookies)
            if cleanup_request_id in self._http_clients:
                del self._http_clients[cleanup_request_id]
                logger.info(f"🍪 Removed HTTP client for request {cleanup_request_id}")

            # Clean up failure counter
            if cleanup_request_id in self._session_creation_failures:
                del self._session_creation_failures[cleanup_request_id]
                logger.info(f"🧹 Cleared failure counter for request {cleanup_request_id}")

            # Track cleaned-up request ID (prevent recreation)
            self._cleaned_up_requests.add(cleanup_request_id)
            logger.info(f"🔒 Request {cleanup_request_id} marked as cleaned up - new session creation blocked")

        except Exception as e:
            logger.error(f"❌ Session cleanup failed: {e}")

    # ========================================================================
    # 🔧 SESSION MANAGEMENT (PRIVATE HELPERS)
    # ========================================================================

    def _get_aws_region(self) -> str:
        """
        Get AWS region from environment with validation

        Returns:
            str: AWS region name

        Raises:
            ValueError: If AWS_REGION environment variable is not set
        """
        aws_region = os.getenv('AWS_REGION')
        if not aws_region:
            raise ValueError("AWS_REGION environment variable is required but not set")
        return aws_region

    def _cleanup_failed_session(self):
        """Clean up session state after creation failure"""
        if self._current_request_id in self._sessions:
            del self._sessions[self._current_request_id]
        self._cleanup_orphaned_containers()

    def _increment_failure_counter(self):
        """Increment session creation failure counter for current request"""
        failure_count = self._session_creation_failures.get(self._current_request_id, 0)
        self._session_creation_failures[self._current_request_id] = failure_count + 1

    def _log_active_sessions(self, attempt: int):
        """Log information about currently active sessions"""
        active_sessions = [req_id for req_id in self._sessions.keys() if req_id not in self._cleaned_up_requests]
        logger.info(f"📦 Creating new Fargate session for request {self._current_request_id} (attempt {attempt}/{self.SESSION_CREATION_MAX_RETRIES})...")
        logger.info(f"   Current active sessions: {len(active_sessions)}")
        if active_sessions:
            logger.info(f"   Active request IDs: {active_sessions}")
            logger.info(f"   Active container IPs: {[self._sessions[req_id]['container_ip'] for req_id in active_sessions if req_id in self._sessions]}")

    def _create_fargate_container(self):
        """Create and configure Fargate container with HTTP session"""
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        # Append short request ID to prevent collisions in concurrent requests
        request_id_short = self._current_request_id[:8] if self._current_request_id else "unknown"
        session_id = f"{timestamp}-{request_id_short}"

        fargate_session_info = self._session_manager.create_session(
            session_id=session_id,
            max_executions=300
        )

        # Inject HTTP session (per-request cookie isolation)
        http_client = self._get_http_client(self._current_request_id)
        self._session_manager.set_http_session(http_client)
        logger.info(f"🔗 HTTP session injected for request {self._current_request_id}")

        return fargate_session_info

    def _register_container_ip(self, private_ip: str):
        """Register container IP for current request"""
        self._used_container_ips[private_ip] = self._current_request_id
        logger.info(f"📝 Registered container IP: {private_ip}")
        logger.info(f"   Request ID: {self._current_request_id}")
        logger.info(f"   All registered IPs: {list(self._used_container_ips.keys())}")

    def _save_session(self, fargate_session_info: dict, container_ip: str):
        """Save session information after successful creation"""
        self._sessions[self._current_request_id] = {
            'session_id': fargate_session_info['session_id'],
            'request_id': self._current_request_id,
            'container_ip': container_ip,
            'fargate_session': self._session_manager.current_session,
            'created_at': datetime.now()
        }
        logger.info(f"✅ Session created and saved for request {self._current_request_id}: {fargate_session_info['session_id']}")
        logger.info(f"   Total active sessions: {len(self._sessions)}")

        # Session creation success - reset failure counter
        if self._current_request_id in self._session_creation_failures:
            del self._session_creation_failures[self._current_request_id]

    def _handle_aws_session_error(self, error_code: str, error_message: str, attempt: int) -> bool:
        """
        Handle AWS ClientError during session creation

        Returns:
            True to continue retry loop, False to stop (error was raised)
        """
        # Configuration errors - FAIL FAST (don't retry)
        NON_RETRYABLE_ERRORS = [
            'ValidationException',
            'InvalidParameterException',
            'AccessDeniedException',
            'ResourceNotFoundException',
            'UnauthorizedException',
        ]

        if error_code in NON_RETRYABLE_ERRORS:
            logger.error(f"❌ FATAL: Non-retryable configuration error detected: {error_code}")
            logger.error(f"   Error: {error_message}")
            logger.error(f"   Fix the configuration and try again. Not retrying.")
            self._increment_failure_counter()
            raise

        # Transient errors - retry with exponential backoff
        if attempt < self.SESSION_CREATION_MAX_RETRIES:
            wait_time = self.EXPONENTIAL_BACKOFF_BASE ** attempt
            logger.warning(f"⏳ Transient error - waiting {wait_time}s before retry (exponential backoff: {self.EXPONENTIAL_BACKOFF_BASE}^{attempt})...")
            time.sleep(wait_time)
            return True
        else:
            # Last attempt failed
            self._increment_failure_counter()
            logger.error(f"❌ FATAL: Session creation failed {self.SESSION_CREATION_MAX_RETRIES} times for request {self._current_request_id}")
            logger.error(f"   Total backoff time: {sum(self.EXPONENTIAL_BACKOFF_BASE ** i for i in range(1, self.SESSION_CREATION_MAX_RETRIES + 1))} seconds")
            raise

    def _handle_generic_session_error(self, attempt: int) -> bool:
        """
        Handle generic exceptions during session creation

        Returns:
            True to continue retry loop, False to stop (error was raised)
        """
        if attempt < self.SESSION_CREATION_MAX_RETRIES:
            wait_time = self.EXPONENTIAL_BACKOFF_BASE ** attempt
            logger.warning(f"⏳ Waiting {wait_time}s before retry (exponential backoff: {self.EXPONENTIAL_BACKOFF_BASE}^{attempt})...")
            time.sleep(wait_time)
            return True
        else:
            # Last attempt failed
            self._increment_failure_counter()
            logger.error(f"❌ FATAL: Session creation failed {self.SESSION_CREATION_MAX_RETRIES} times for request {self._current_request_id}")
            logger.error(f"   Total backoff time: {sum(self.EXPONENTIAL_BACKOFF_BASE ** i for i in range(1, self.SESSION_CREATION_MAX_RETRIES + 1))} seconds")
            raise

    def _reuse_existing_session(self):
        """Reuse existing session (with health check)"""
        session_info = self._sessions[self._current_request_id]
        container_ip = session_info.get('container_ip', 'unknown')

        logger.info(f"♻️ Reusing existing session for request {self._current_request_id}: {session_info['session_id']}")

        # 🔍 Container Health Check (ALB Target Health)
        if container_ip != 'unknown':
            target_health = self._check_alb_target_health(container_ip)
            logger.info(f"   🏥 Container ALB Health: {target_health}")

            if target_health not in ['healthy', 'initial']:
                logger.warning(f"⚠️ WARNING: Reusing session with container in '{target_health}' state!")
                logger.warning(f"   This may cause connection failures!")
                logger.warning(f"   Container IP: {container_ip}")
                logger.warning(f"   Session ID: {session_info['session_id']}")
                logger.warning(f"   Consider implementing automatic cleanup for stopped containers")

        # Update SessionBasedFargateManager's current_session
        self._session_manager.current_session = session_info['fargate_session']

        # Re-inject HTTP session (required even when reusing session)
        http_client = self._get_http_client(self._current_request_id)
        self._session_manager.set_http_session(http_client)

        return True

    def _create_new_session(self):
        """Create new session (with exponential backoff retry)"""
        for attempt in range(1, self.SESSION_CREATION_MAX_RETRIES + 1):
            try:
                # Log concurrent execution detection
                self._log_active_sessions(attempt)

                # Create Fargate container and inject HTTP session
                fargate_session_info = self._create_fargate_container()

                # Register container IP
                expected_private_ip = self._session_manager.current_session['private_ip']
                self._register_container_ip(expected_private_ip)

                # Wait for ALB health check and acquire cookie
                if not self._wait_for_container_ready(expected_private_ip, fargate_session_info['session_id']):
                    # Release IP registration on failure
                    if expected_private_ip in self._used_container_ips:
                        del self._used_container_ips[expected_private_ip]
                    return False

                # Save session after health check + cookie acquisition
                self._save_session(fargate_session_info, expected_private_ip)

                return True

            except ClientError as create_error:
                error_code = create_error.response['Error']['Code']
                error_message = create_error.response['Error']['Message']
                logger.error(f"❌ Session creation failed (attempt {attempt}/{self.SESSION_CREATION_MAX_RETRIES}): [{error_code}] {error_message}")

                # Cleanup only if session creation itself failed
                self._cleanup_failed_session()

                # Handle AWS error (may raise exception)
                self._handle_aws_session_error(error_code, error_message, attempt)

            except Exception as create_error:
                # Handle non-AWS exceptions (e.g., network errors, Python exceptions)
                logger.error(f"❌ Session creation failed (attempt {attempt}/{self.SESSION_CREATION_MAX_RETRIES}): {create_error}")

                # Cleanup only if session creation itself failed
                self._cleanup_failed_session()

                # Handle generic error (may raise exception)
                self._handle_generic_session_error(attempt)

    def _wait_for_container_ready(self, expected_ip: str, session_id: str) -> bool:
        """Wait for container readiness (ALB Health Check + Cookie acquisition)"""
        # Wait for ALB to begin health checks (with keep-alive logging)
        logger.info(f"⏳ Waiting {self.ALB_INITIAL_WAIT_DURATION} seconds for ALB to begin health checks...")
        logger.info(f"   This prevents 'ALB never sent health checks' issue")

        # Keep-alive: Split 60s into 6 iterations of 10s with logging
        for wait_i in range(self.ALB_WAIT_ITERATIONS):
            time.sleep(self.ALB_WAIT_INTERVAL)
            logger.info(f"   ⏱️  Waiting for ALB... ({(wait_i+1)*self.ALB_WAIT_INTERVAL}/{self.ALB_INITIAL_WAIT_DURATION}s)")

        # Wait for ALB Health Check (until container becomes healthy)
        logger.info(f"⏰ Waiting for container {expected_ip} to be healthy in ALB...")
        alb_healthy = False
        max_wait_time = self.HEALTH_CHECK_MAX_ATTEMPTS * self.HEALTH_CHECK_INTERVAL
        for wait_attempt in range(1, self.HEALTH_CHECK_MAX_ATTEMPTS + 1):
            target_health = self._check_alb_target_health(expected_ip)
            logger.info(f"   Attempt {wait_attempt}/{self.HEALTH_CHECK_MAX_ATTEMPTS}: ALB health = {target_health}")

            if target_health == 'healthy':
                logger.info(f"✅ Container is healthy in ALB after {wait_attempt * self.HEALTH_CHECK_INTERVAL}s")
                alb_healthy = True
                break
            elif target_health in ['unhealthy', 'draining']:
                logger.warning(f"⚠️ Container is {target_health} - continuing to wait...")
            elif target_health == 'not_registered':
                logger.info(f"   Container not yet registered to ALB - waiting...")

            if wait_attempt < self.HEALTH_CHECK_MAX_ATTEMPTS:
                time.sleep(self.HEALTH_CHECK_INTERVAL)

        if not alb_healthy:
            logger.warning(f"⚠️ Container not healthy after {max_wait_time}s, but will try cookie acquisition anyway")

        # Acquire IP-based cookie (with session ID validation)
        cookie_acquired = self._acquire_cookie_for_ip(expected_ip, session_id)

        if not cookie_acquired:
            logger.warning(f"⚠️ Failed to acquire Sticky Session cookie")
            logger.warning(f"   Releasing IP registration: {expected_ip}")
            logger.warning(f"   Cookie acquisition failed - session NOT saved")
            return False

        return True

    def _get_http_client(self, request_id: str):
        """Return HTTP client for request (cookie isolation)"""
        if request_id not in self._http_clients:
            self._http_clients[request_id] = requests.Session()
            logger.info(f"🍪 Created new HTTP client for request {request_id}")
        return self._http_clients[request_id]

    def _check_alb_target_health(self, target_ip: str) -> str:
        """
        Check if the specified IP is registered and healthy in the ALB target group

        Returns:
            'healthy', 'unhealthy', 'initial', 'draining', 'unused', 'not_registered', 'unknown'
        """
        try:
            if not ALB_TARGET_GROUP_ARN:
                raise ValueError("ALB_TARGET_GROUP_ARN environment variable is required")

            elbv2_client = boto3.client('elbv2', region_name=self._get_aws_region())
            response = elbv2_client.describe_target_health(TargetGroupArn=ALB_TARGET_GROUP_ARN)

            for target_health in response.get('TargetHealthDescriptions', []):
                if target_health['Target']['Id'] == target_ip:
                    state = target_health['TargetHealth']['State']
                    return state

            return 'not_registered'
        except Exception as e:
            logger.warning(f"⚠️ Failed to check ALB target health: {e}")
            return 'unknown'

    # ========================================================================
    # 🍪 COOKIE ACQUISITION (SUBPROCESS-BASED)
    # ========================================================================

    def _run_cookie_subprocess(self, script_path: Path, expected_ip: str, session_id: str) -> subprocess.CompletedProcess:
        """Run cookie acquisition subprocess and return result"""
        logger.info(f"🔧 Launching subprocess for cookie acquisition...")
        logger.info(f"   Script: {script_path}")

        result = subprocess.run(
            ["python3", str(script_path), self._session_manager.alb_dns, expected_ip, session_id],
            capture_output=True,
            text=True,
            timeout=self.COOKIE_ACQUISITION_TIMEOUT
        )

        # Log subprocess stderr
        if result.stderr:
            for line in result.stderr.strip().split('\n'):
                if line.strip():
                    logger.info(f"   {line}")

        return result

    def _parse_cookie_result(self, result: subprocess.CompletedProcess) -> dict:
        """Parse cookie acquisition subprocess result"""
        output = result.stdout.strip()
        if not output:
            logger.error(f"❌ Subprocess produced no output")
            if result.stderr:
                logger.error(f"   Full stderr: {result.stderr}")
            return None

        try:
            data = json.loads(output)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse subprocess output: {e}")
            logger.error(f"   Output: {result.stdout}")
            if result.stderr:
                logger.error(f"   Full stderr: {result.stderr}")
            return None

    def _store_acquired_cookie(self, cookie_value: str, attempt: int, actual_ip: str) -> bool:
        """Store acquired cookie in HTTP client"""
        logger.info(f"✅ Cookie acquired! (attempt {attempt})")
        logger.info(f"   My container IP: {actual_ip}")
        logger.info(f"   Cookie value: {cookie_value[:20]}...")

        # Set cookie in HTTP client (reuse existing session)
        http_client = self._get_http_client(self._current_request_id)
        http_client.cookies.set('AWSALB', cookie_value)

        return True

    def _acquire_cookie_for_ip(self, expected_ip: str, session_id: str) -> bool:
        """
        Acquire sticky session cookie from container with specific IP using subprocess

        Why use subprocess:
        - Complete process isolation → Independent TCP Connection Pool
        - ALB Round Robin works correctly (no Connection: close/Pool Control needed)
        - Multi-job environment: Each job can acquire cookies independently

        How it works:
        1. Run inline script in isolated Python process
        2. Try 40 times inside subprocess (each with new TCP connection)
        3. Reach target container via ALB Round Robin and acquire cookie
        4. Validate session ID to confirm correct container (multi-job support)
        5. Return result as JSON (stdout)
        6. Parent process sets cookie in HTTP client
        """
        logger.info(f"🍪 Acquiring cookie for container: {expected_ip}")
        logger.info(f"   Session ID: {session_id}")
        other_ips = [ip for ip in self._used_container_ips.keys() if ip != expected_ip]
        if other_ips:
            logger.info(f"   Other active containers: {other_ips}")
        else:
            logger.info(f"   No other active containers")

        try:
            # Get path to cookie acquisition subprocess script
            current_file = Path(__file__)
            script_path = current_file.parent / "cookie_acquisition_subprocess.py"

            if not script_path.exists():
                raise FileNotFoundError(f"Cookie acquisition script not found: {script_path}")

            # Run subprocess
            result = self._run_cookie_subprocess(script_path, expected_ip, session_id)

            # Parse result
            data = self._parse_cookie_result(result)
            if not data:
                return False

            # Check success
            if data.get("success"):
                cookie_value = data.get("cookie")
                attempt = data.get("attempt")
                actual_ip = data.get("ip")
                return self._store_acquired_cookie(cookie_value, attempt, actual_ip)
            else:
                error_msg = data.get("error", "Unknown error")
                logger.error(f"❌ Cookie acquisition failed: {error_msg}")
                logger.error(f"   Expected IP: {expected_ip}")
                logger.error(f"   Registered IPs: {list(self._used_container_ips.keys())}")
                return False

        except subprocess.TimeoutExpired as e:
            logger.error(f"❌ Cookie acquisition timeout ({self.COOKIE_ACQUISITION_TIMEOUT} seconds)")
            logger.error(f"   Expected IP: {expected_ip}")
            if e.stderr:
                # Also log timeout stderr (safe bytes → string conversion)
                stderr_text = str(e.stderr, 'utf-8') if isinstance(e.stderr, bytes) else e.stderr
                for line in stderr_text.strip().split('\n'):
                    if line.strip():
                        logger.error(f"   {line}")
            return False
        except Exception as e:
            logger.error(f"❌ Cookie acquisition subprocess failed: {e}")
            logger.error(f"   Expected IP: {expected_ip}")
            return False

    # ========================================================================
    # 📤 DATA SYNC METHODS (S3 UPLOAD/DOWNLOAD)
    # ========================================================================

    def _copy_s3_directory_to_session(self, s3_url: str, session_id: str) -> str:
        """
        Copy files from an S3 URL to the session's input prefix (S3-to-S3 copy).

        This method handles the web upload flow where user data is already stored
        in S3 (uploaded via the web app's /upload endpoint). Instead of downloading
        to local disk and re-uploading, it performs a server-side S3 copy which is
        faster and avoids unnecessary data transfer.

        The destination prefix matches the format used by _upload_directory_to_s3_with_session_id(),
        so the subsequent Fargate container sync step works identically.

        Example:
            Source: s3://deep-insight-logs-us-west-2-057716757052/uploads/abc-123/
                ├── sales.csv
                └── column_definitions.json

            Destination: deep-insight/fargate_sessions/{session_id}/input/
                ├── sales.csv
                └── column_definitions.json

        Args:
            s3_url: Full S3 URL pointing to the uploaded data directory
                    (e.g., "s3://bucket-name/uploads/uuid/")
            session_id: Fargate session ID used to construct the destination prefix

        Returns:
            str: S3 prefix where files were copied
                 (e.g., "deep-insight/fargate_sessions/{session_id}/input/")

        Raises:
            Exception: If no files are found at the source S3 path,
                       or if S3 copy operations fail
        """
        try:
            # Parse S3 URL into bucket name and key prefix
            # Example: "s3://my-bucket/uploads/abc-123/"
            #   -> source_bucket = "my-bucket"
            #   -> source_prefix = "uploads/abc-123/"
            url_body = s3_url[5:]  # Remove "s3://" scheme
            parts = url_body.split("/", 1)
            source_bucket = parts[0]
            source_prefix = parts[1].rstrip("/") + "/" if len(parts) > 1 and parts[1] else ""

            # Destination prefix: same format as _upload_directory_to_s3_with_session_id()
            dest_prefix = f"deep-insight/fargate_sessions/{session_id}/input/"
            s3_client = boto3.client('s3', region_name=self._get_aws_region())

            logger.info(f"📤 Copying S3 directory to session...")
            logger.info(f"   Source: s3://{source_bucket}/{source_prefix}")
            logger.info(f"   Dest:   s3://{S3_BUCKET_NAME}/{dest_prefix}")

            # List all objects under the source prefix and copy each to destination.
            # Uses paginator to handle any number of files (>1000).
            copied_count = 0
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=source_bucket, Prefix=source_prefix):
                for obj in page.get('Contents', []):
                    source_key = obj['Key']

                    # Strip source prefix to get the relative file path
                    # e.g., "uploads/abc-123/sales.csv" -> "sales.csv"
                    relative_path = source_key[len(source_prefix):]
                    if not relative_path:
                        continue  # Skip the prefix itself (directory marker)

                    dest_key = f"{dest_prefix}{relative_path}"

                    # Server-side copy within the same AWS account (no data download)
                    s3_client.copy_object(
                        CopySource={'Bucket': source_bucket, 'Key': source_key},
                        Bucket=S3_BUCKET_NAME,
                        Key=dest_key,
                    )
                    copied_count += 1
                    logger.info(f"   📤 {relative_path} → s3://{S3_BUCKET_NAME}/{dest_key}")

            # Fail early if no files were found (likely wrong upload_id or empty upload)
            if copied_count == 0:
                raise Exception(f"No files found at source: s3://{source_bucket}/{source_prefix}")

            logger.info(f"✅ Copied {copied_count} files within S3")
            return dest_prefix

        except Exception as e:
            logger.error(f"❌ S3 directory copy failed: {e}")
            raise

    def _upload_directory_to_s3_with_session_id(self, data_directory: str, session_id: str) -> str:
        """
        Upload entire directory to S3 recursively (maintains subdirectory structure)

        S3 Structure:
            deep-insight/fargate_sessions/{session_id}/input/
                ├── file1.csv
                ├── file2.json
                ├── subdir1/
                │   ├── file3.txt
                │   └── file4.xlsx
                └── subdir2/
                    └── file5.csv

        Args:
            data_directory: Local directory path (e.g., "./data")
            session_id: Fargate session ID

        Returns:
            str: S3 prefix (e.g., "deep-insight/fargate_sessions/{session_id}/input/")
        """
        try:
            from pathlib import Path

            s3_prefix = f"deep-insight/fargate_sessions/{session_id}/input/"
            s3_client = boto3.client('s3', region_name=self._get_aws_region())

            uploaded_count = 0
            data_path = Path(data_directory).resolve()  # Absolute path

            logger.info(f"📤 Starting directory upload to S3...")
            logger.info(f"   Local directory: {data_directory}")
            logger.info(f"   Resolved path: {data_path}")
            logger.info(f"   S3 prefix: s3://{S3_BUCKET_NAME}/{s3_prefix}")

            # Walk directory tree and upload all files (use absolute path)
            for root, dirs, files in os.walk(data_path):
                for filename in files:
                    local_file_path = Path(root) / filename

                    # Calculate relative path from base directory
                    relative_path = local_file_path.relative_to(data_path)
                    s3_key = f"{s3_prefix}{relative_path}".replace('\\', '/')

                    # Upload file to S3
                    s3_client.upload_file(
                        str(local_file_path),
                        S3_BUCKET_NAME,
                        s3_key
                    )

                    uploaded_count += 1
                    logger.info(f"   📤 {relative_path} → s3://{S3_BUCKET_NAME}/{s3_key}")

            logger.info(f"✅ Uploaded {uploaded_count} files to S3")
            return s3_prefix

        except Exception as e:
            logger.error(f"❌ Directory upload to S3 failed: {e}")
            raise

    def _sync_directory_from_s3_to_container(self, s3_prefix: str):
        """
        Synchronize entire directory from S3 to container (recursive)

        Args:
            s3_prefix: S3 prefix (e.g., "deep-insight/fargate_sessions/{session_id}/input/")
        """
        try:
            alb_dns = self._session_manager.alb_dns

            logger.info(f"🔄 Starting directory sync from S3 to container...")
            logger.info(f"   S3 Prefix: {s3_prefix}")
            logger.info(f"   Target: /app/data/ (recursive)")

            # Directory sync request (container handles recursive download)
            sync_request = {
                "action": "sync_data_from_s3",
                "bucket_name": S3_BUCKET_NAME,
                "s3_key_prefix": s3_prefix,
                "local_path": "/app/data/"
            }

            logger.info(f"📤 Sending directory sync request:")
            logger.info(f"   URL: http://{alb_dns}/file-sync")
            logger.info(f"   Request: {sync_request}")

            # Use per-request HTTP client (cookie isolation)
            http_client = self._get_http_client(self._current_request_id)
            response = http_client.post(
                f"http://{alb_dns}/file-sync",
                json=sync_request,
                timeout=self.FILE_SYNC_TIMEOUT
            )

            logger.info(f"📥 Directory sync response:")
            logger.info(f"   Status: {response.status_code}")
            logger.info(f"   Body: {response.text[:500]}")

            if response.status_code != 200:
                logger.error(f"❌ Directory sync failed with status {response.status_code}")
                raise Exception(f"Directory sync failed: {response.text}")

            result = response.json()
            files_count = result.get('files_count', 0)
            downloaded_files = result.get('downloaded_files', [])

            logger.info(f"✅ Directory sync completed:")
            logger.info(f"   Files synced: {files_count}")
            if files_count <= 10:
                logger.info(f"   Downloaded: {downloaded_files}")
            else:
                logger.info(f"   Downloaded (first 10): {downloaded_files[:10]}")
                logger.info(f"   ... and {files_count - 10} more files")

            logger.info(f"⏳ Waiting {self.FILE_SYNC_WAIT} seconds for directory sync to complete...")
            time.sleep(self.FILE_SYNC_WAIT)

            logger.info("✅ Directory sync wait complete")

        except Exception as e:
            logger.error(f"❌ Directory sync failed: {e}")
            logger.error(f"   Exception type: {type(e).__name__}")
            logger.error(f"   Exception details: {str(e)[:1000]}")
            raise

    # ========================================================================
    # 🧹 CLEANUP METHODS
    # ========================================================================

    def _cleanup_orphaned_containers(self):
        """Clean up only current request's container on session creation failure (protect other requests' containers)"""
        try:
            ecs_client = boto3.client('ecs', region_name=self._get_aws_region())

            # Check current request's Task ARN
            current_task_arn = None
            if self._current_request_id and self._current_request_id in self._sessions:
                session_info = self._sessions[self._current_request_id]
                fargate_session = session_info.get('fargate_session', {})
                current_task_arn = fargate_session.get('task_arn')

            if not current_task_arn:
                logger.warning(f"⚠️ No task ARN found for current request {self._current_request_id} - skipping cleanup")
                return

            # ✅ Stop only current request's container (don't touch other requests' containers)
            try:
                logger.info(f"🧹 Cleaning up orphaned container for request {self._current_request_id}: {current_task_arn.split('/')[-1][:12]}...")
                ecs_client.stop_task(
                    cluster=ECS_CLUSTER_NAME,
                    task=current_task_arn,
                    reason=f'Session creation failed - cleanup (request: {self._current_request_id})'
                )
                logger.info(f"   ✅ Stopped container: {current_task_arn.split('/')[-1][:12]}")
            except Exception as stop_error:
                logger.warning(f"   ⚠️ Failed to stop container {current_task_arn.split('/')[-1][:12]}: {stop_error}")

        except Exception as e:
            logger.warning(f"⚠️ Orphaned container cleanup failed: {e}")

    def _deregister_from_alb(self, container_ip: str):
        """Remove container from ALB Target Group"""
        try:
            elbv2_client = boto3.client('elbv2', region_name=self._get_aws_region())
            elbv2_client.deregister_targets(
                TargetGroupArn=self._session_manager.alb_target_group_arn,
                Targets=[{
                    'Id': container_ip,
                    'Port': 8080
                }]
            )
            logger.info(f"🔗 Deregistered target from ALB: {container_ip}:8080")
        except Exception as alb_error:
            # Continue session cleanup even if ALB deregistration fails
            logger.warning(f"⚠️ Failed to deregister ALB target {container_ip}: {alb_error}")

    def _auto_cleanup(self):
        """Automatically clean up all sessions on program exit"""
        try:
            if self._sessions:
                logger.info(f"🧹 Auto-cleanup: Closing {len(self._sessions)} Fargate sessions on exit...")
                # Clean up all sessions
                for request_id in list(self._sessions.keys()):
                    self.cleanup_session(request_id)

            # ✅ Clear all HTTP clients
            if self._http_clients:
                logger.info(f"🧹 Auto-cleanup: Clearing {len(self._http_clients)} HTTP clients...")
                self._http_clients.clear()

            # ✅ Clear all failure counters
            if self._session_creation_failures:
                logger.info(f"🧹 Auto-cleanup: Clearing {len(self._session_creation_failures)} failure counters...")
                self._session_creation_failures.clear()

            # ✅ Clear all cleanup trackers
            if self._cleaned_up_requests:
                logger.info(f"🧹 Auto-cleanup: Clearing {len(self._cleaned_up_requests)} cleaned-up request trackers...")
                self._cleaned_up_requests.clear()
        except Exception as e:
            logger.warning(f"⚠️ Auto-cleanup failed: {e}")


# ============================================================================
# GLOBAL INSTANCE (SINGLETON)
# ============================================================================

# Global instance (Singleton)
global_fargate_session = GlobalFargateSessionManager()


def get_global_session():
    """Return global session manager instance"""
    return global_fargate_session
