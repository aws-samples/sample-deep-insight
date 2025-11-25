#!/usr/bin/env python3
"""
Session-Based Fargate Container Manager

This module provides session-based lifecycle management for AWS Fargate containers
in a multi-agent data analysis environment.

Architecture:
    - Session-Based Lifecycle: Each session gets its own dedicated Fargate container
    - Container Creation: ECS Task → Private IP → ALB Registration → Health Check
    - Container Cleanup: Session Complete → S3 Upload → ALB Deregister → Task Stop
    - Sticky Session Support: ALB cookie-based routing to specific containers
    - VPC Private Mode: All traffic routed through private subnets and VPC endpoints

Key Features:
    1. Session Management
       - Auto-generate session IDs (UUID-based)
       - Container reuse for existing sessions
       - Health check before reusing containers
       - Graceful session completion and cleanup

    2. Container Lifecycle
       - Start Fargate task with environment variables
       - Wait for private IP assignment (with timeout)
       - Register container to ALB target group
       - Monitor container health status
       - Stop task and cleanup on session end

    3. Code Execution
       - Fixed container per session (no container switching)
       - HTTP-based code execution via ALB
       - Timeout handling (180s default for large operations)
       - Error handling with workflow termination

    4. Network Configuration
       - VPC private subnets (comma-separated from env)
       - Security groups (comma-separated from env)
       - Public IP assignment control (DISABLED by default)
       - ALB internal routing

Usage Example:
    ```python
    # Initialize manager with environment variables
    manager = SessionBasedFargateManager()

    # Set HTTP session (injected by coordinator)
    manager.set_http_session(requests.Session())

    # Create new session
    session = manager.create_session(session_id="task-001", max_executions=50)
    # Returns: {"session_id": "task-001", "private_ip": "10.0.1.23", ...}

    # Execute code on container
    result = manager.execute_code(
        code="import pandas as pd\ndf = pd.read_csv('data.csv')",
        description="Load data"
    )

    # Complete session (triggers cleanup)
    manager.complete_session(wait_for_s3=True)
    ```

Environment Variables:
    Required:
        ECS_CLUSTER_NAME: ECS cluster for Fargate tasks
        ALB_DNS: Application Load Balancer DNS name
        ALB_TARGET_GROUP_ARN: ALB target group ARN
        FARGATE_SUBNET_IDS: Comma-separated subnet IDs
        FARGATE_SECURITY_GROUP_IDS: Comma-separated security group IDs

    Optional:
        TASK_DEFINITION_ARN: Task definition (ARN or family name)
        CONTAINER_NAME: Container name in task definition
        FARGATE_ASSIGN_PUBLIC_IP: ENABLED or DISABLED (default)
        AWS_REGION: AWS region for boto3 clients (passed to container)
        S3_BUCKET_NAME: S3 bucket for results (passed to container)

Notes:
    - This manager is typically used by GlobalFargateSessionManager
    - HTTP session is injected for per-request cookie isolation
    - Container reuse is only safe if health check passes
    - All container failures terminate the entire workflow
"""

import os
import boto3
import time
import uuid
import requests
from typing import Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables (don't override Runtime env vars)
load_dotenv(override=False)

# ECS and ALB configuration from environment
# These must be provided via environment variables (no hardcoded defaults)
ECS_CLUSTER_NAME = os.getenv("ECS_CLUSTER_NAME")
TASK_DEFINITION_ARN = os.getenv("TASK_DEFINITION_ARN")
CONTAINER_NAME = os.getenv("CONTAINER_NAME")
ALB_DNS = os.getenv("ALB_DNS")
ALB_TARGET_GROUP_ARN = os.getenv("ALB_TARGET_GROUP_ARN")

# Fargate Task Network Configuration (VPC)
# These must be provided via environment variables (no hardcoded defaults)
FARGATE_SUBNET_IDS = os.getenv("FARGATE_SUBNET_IDS")
FARGATE_SECURITY_GROUP_IDS = os.getenv("FARGATE_SECURITY_GROUP_IDS")
FARGATE_ASSIGN_PUBLIC_IP = os.getenv("FARGATE_ASSIGN_PUBLIC_IP", "DISABLED")  # Default to DISABLED for security

class SessionBasedFargateManager:
    # ========================================================================
    # CLASS CONSTANTS - Timeouts and Intervals
    # ========================================================================
    TASK_IP_WAIT_TIMEOUT = 60          # Timeout for waiting for task IP address (seconds)
    TASK_IP_POLL_INTERVAL = 3          # Polling interval for task IP check (seconds)
    HEALTH_CHECK_TIMEOUT = 5           # Timeout for container health check (seconds)
    CODE_EXECUTION_TIMEOUT = 600       # Timeout for code execution (seconds) - Increased for long-running tasks like DOCX generation
    SESSION_COMPLETE_TIMEOUT = 10      # Timeout for session completion signal (seconds)
    STATUS_CHECK_TIMEOUT = 5           # Timeout for session status check (seconds)
    S3_UPLOAD_WAIT = 15                # Wait time for S3 upload completion (seconds)
    CONTAINER_PORT = 8080              # Container HTTP port

    # ========================================================================
    # HELPER METHODS (DRY - Don't Repeat Yourself)
    # ========================================================================

    def _build_session_response(self, session_id: str, private_ip: str,
                                max_executions: int, container_reused: bool) -> Dict[str, Any]:
        """Build standardized session response dictionary"""
        return {
            "session_id": session_id,
            "alb_url": self.alb_dns,
            "private_ip": private_ip,
            "max_executions": max_executions,
            "status": "ready",
            "container_reused": container_reused
        }

    def _raise_container_error(self, error_type: str, exception: Exception):
        """Raise container error with standardized message format"""
        error_msg = f"FIXED CONTAINER {error_type.upper()} FAILED: {str(exception)} - TERMINATING ENTIRE WORKFLOW"
        print(f"❌ {error_msg}", flush=True)
        raise Exception(error_msg)

    def _add_optional_env_var(self, container_env: list, env_var_name: str):
        """Add environment variable to container config if it exists"""
        env_value = os.getenv(env_var_name)
        if env_value:
            container_env.append({
                'name': env_var_name,
                'value': env_value
            })

    def _ensure_http_session(self):
        """Validate HTTP session is initialized"""
        if not self.http_session:
            raise Exception("No HTTP session. Call set_http_session() first.")

    def _ensure_active_session(self):
        """Validate active session exists"""
        if not self.current_session:
            raise Exception("No active session. Call create_session() first.")

    # ========================================================================
    # INITIALIZATION HELPERS
    # ========================================================================

    def _parse_task_definition(self, task_definition: str) -> str:
        """Parse task definition ARN and extract family name"""
        task_def = task_definition or TASK_DEFINITION_ARN or "fargate-dynamic-task"

        if task_def and task_def.startswith("arn:"):
            # Extract family name from ARN: arn:aws:ecs:region:account:task-definition/family:revision
            # Example: arn:aws:ecs:us-east-1:123456:task-definition/deep-insight-fargate-task-prod:1
            # Result: deep-insight-fargate-task-prod
            return task_def.split("/")[-1].split(":")[0]
        else:
            return task_def

    def _parse_network_config(self, subnets: list, security_groups: list):
        """Parse and validate network configuration from parameters or environment"""
        # Parse subnets
        if subnets:
            self.subnets = subnets
        elif FARGATE_SUBNET_IDS:
            self.subnets = [s.strip() for s in FARGATE_SUBNET_IDS.split(",")]
        else:
            raise ValueError("FARGATE_SUBNET_IDS environment variable is required")

        # Parse security groups
        if security_groups:
            self.security_groups = security_groups
        elif FARGATE_SECURITY_GROUP_IDS:
            self.security_groups = [sg.strip() for sg in FARGATE_SECURITY_GROUP_IDS.split(",")]
        else:
            raise ValueError("FARGATE_SECURITY_GROUP_IDS environment variable is required")

        # Assign public IP setting
        self.assign_public_ip = FARGATE_ASSIGN_PUBLIC_IP

    def _validate_required_config(self):
        """Validate that all required configuration is present"""
        if not self.cluster_name:
            raise ValueError("ECS_CLUSTER_NAME environment variable is required")
        if not self.alb_dns:
            raise ValueError("ALB_DNS environment variable is required")
        if not self.alb_target_group_arn:
            raise ValueError("ALB_TARGET_GROUP_ARN environment variable is required")

    def _initialize_aws_clients(self, region: str):
        """Initialize AWS service clients"""
        self.ecs_client = boto3.client('ecs', region_name=region)
        self.ec2_client = boto3.client('ec2', region_name=region)
        self.elbv2_client = boto3.client('elbv2', region_name=region)

    def __init__(self,
                 cluster_name: str = None,
                 task_definition: str = None,
                 container_name: str = None,
                 alb_target_group_arn: str = None,
                 alb_dns: str = None,
                 subnets: list = None,
                 security_groups: list = None,
                 region: str = None):
        """
        Initialize session-based Fargate manager
        """
        # Basic configuration
        self.cluster_name = cluster_name or ECS_CLUSTER_NAME
        self.task_definition = self._parse_task_definition(task_definition)
        self.container_name = container_name or CONTAINER_NAME or "dynamic-executor"
        self.alb_target_group_arn = alb_target_group_arn or ALB_TARGET_GROUP_ARN
        self.alb_dns = alb_dns or ALB_DNS
        # Get region from parameter, environment variable, or default to us-east-1
        self.region = region or os.getenv('AWS_REGION') or 'us-east-1'

        # Validate required configuration
        self._validate_required_config()

        # Parse network configuration
        self._parse_network_config(subnets, security_groups)

        # Initialize AWS clients
        self._initialize_aws_clients(self.region)

        # HTTP session is injected by global_fargate_coordinator (per-request isolation)
        self.http_session = None

        # Current session information
        self.current_session = None

    def set_http_session(self, http_session):
        """Set HTTP session (injected by global_fargate_coordinator)"""
        self.http_session = http_session
        print(f"🔗 HTTP session injected for request-specific cookie isolation", flush=True)

    # ========================================================================
    # SESSION CREATION HELPERS
    # ========================================================================

    def _reuse_existing_session(self, session_id: str, max_executions: int) -> Dict[str, Any]:
        """Reuse existing healthy container"""
        print(f"🔍 [Session {session_id}] Checking existing container health...", flush=True)

        if self._check_existing_container_health():
            print(f"✅ [Session {session_id}] Reusing existing container: {self.current_session['session_id']}", flush=True)
            print(f"   Task ARN: {self.current_session['task_arn']}", flush=True)
            print(f"   Private IP: {self.current_session['private_ip']}", flush=True)
            print(f"   ALB DNS: {self.alb_dns}", flush=True)

            # Update existing session information
            self.current_session['session_id'] = session_id
            self.current_session['max_executions'] = max_executions
            self.current_session['status'] = 'active'

            return self._build_session_response(
                session_id,
                self.current_session['private_ip'],
                max_executions,
                container_reused=True
            )
        else:
            print(f"❌ [Session {session_id}] Existing container unhealthy - TERMINATING WITH ERROR", flush=True)
            raise Exception("Existing container is unhealthy and cannot be reused. Session terminated.")

    def _create_new_session_internal(self, session_id: str, max_executions: int) -> Dict[str, Any]:
        """Create new Fargate container and session"""
        print(f"🆕 [Session {session_id}] Creating new container (first time)...", flush=True)

        # Start Fargate Task
        task_arn = self._start_fargate_task(session_id)

        # Wait for Task IP
        private_ip = self._wait_for_task_ip(task_arn)

        # Register to ALB
        self._register_to_alb(private_ip)

        # Save session info (health check handled by global_fargate_coordinator)
        self.current_session = {
            "session_id": session_id,
            "task_arn": task_arn,
            "private_ip": private_ip,
            "max_executions": max_executions,
            "start_time": datetime.now(),
            "status": "active"
        }

        print(f"✅ [Session {session_id}] New container created successfully!", flush=True)
        print(f"   Task ARN: {task_arn}", flush=True)
        print(f"   Private IP: {private_ip}", flush=True)
        print(f"   ALB DNS: {self.alb_dns}", flush=True)

        return self._build_session_response(
            session_id,
            private_ip,
            max_executions,
            container_reused=False
        )

    def create_session(self, session_id: Optional[str] = None, max_executions: int = 300) -> Dict[str, Any]:
        """
        Create new session or reuse existing container
        - First request: Create new container
        - Subsequent requests: Check existing container health and reuse

        Args:
            session_id: Session ID (auto-generated if None)
            max_executions: Maximum number of executions

        Returns:
            Session information dictionary
        """
        if session_id is None:
            session_id = str(uuid.uuid4())[:8]

        print(f"🚀 [Session {session_id}] Creating or reusing session...", flush=True)

        try:
            # Check if we can reuse existing session
            if self.current_session:
                return self._reuse_existing_session(session_id, max_executions)

            # Create new session
            return self._create_new_session_internal(session_id, max_executions)

        except Exception as e:
            print(f"❌ [Session {session_id}] Failed to create/reuse session: {e}", flush=True)
            raise

    def _start_fargate_task(self, session_id: str) -> str:
        """Start Fargate Task with required environment variables"""
        print(f"🏗️ [Session {session_id}] Starting Fargate task...", flush=True)

        # Prepare environment variables to pass to Fargate container
        container_env = [
            {
                'name': 'SESSION_ID',
                'value': session_id
            }
        ]

        # Pass optional environment variables from AgentCore runtime to Fargate container
        self._add_optional_env_var(container_env, 'AWS_REGION')
        self._add_optional_env_var(container_env, 'S3_BUCKET_NAME')

        response = self.ecs_client.run_task(
            cluster=self.cluster_name,
            taskDefinition=self.task_definition,
            launchType='FARGATE',
            networkConfiguration={
                'awsvpcConfiguration': {
                    'subnets': self.subnets,
                    'securityGroups': self.security_groups,
                    'assignPublicIp': self.assign_public_ip
                }
            },
            overrides={
                'containerOverrides': [
                    {
                        'name': self.container_name,
                        'environment': container_env
                    }
                ]
            }
        )

        if response['failures']:
            raise Exception(f"Task execution failed: {response['failures']}")

        task_arn = response['tasks'][0]['taskArn']
        print(f"📋 [Session {session_id}] Task started: {task_arn}", flush=True)
        return task_arn

    def _extract_eni_id_from_task(self, task: Dict[str, Any]) -> Optional[str]:
        """Extract ENI ID from ECS task attachments"""
        for attachment in task.get('attachments', []):
            if attachment.get('type') == 'ElasticNetworkInterface':
                for detail in attachment.get('details', []):
                    if detail.get('name') == 'networkInterfaceId':
                        return detail.get('value')
        return None

    def _get_private_ip_from_eni(self, eni_id: str) -> Optional[str]:
        """Get private IP address from ENI"""
        eni_response = self.ec2_client.describe_network_interfaces(
            NetworkInterfaceIds=[eni_id]
        )
        if eni_response['NetworkInterfaces']:
            return eni_response['NetworkInterfaces'][0].get('PrivateIpAddress')
        return None

    def _wait_for_task_ip(self, task_arn: str, timeout: int = None) -> str:
        """Wait for task's private IP address"""
        if timeout is None:
            timeout = self.TASK_IP_WAIT_TIMEOUT

        print(f"⏳ Waiting for task IP...", flush=True)

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = self.ecs_client.describe_tasks(
                    cluster=self.cluster_name,
                    tasks=[task_arn]
                )

                if not response['tasks']:
                    raise Exception("Task not found")

                task = response['tasks'][0]

                # Extract ENI ID from task
                eni_id = self._extract_eni_id_from_task(task)

                if eni_id:
                    # Get private IP from ENI
                    private_ip = self._get_private_ip_from_eni(eni_id)
                    if private_ip:
                        print(f"🌐 Task Private IP: {private_ip}", flush=True)
                        return private_ip

                time.sleep(self.TASK_IP_POLL_INTERVAL)

            except Exception as e:
                print(f"⏳ Still waiting for IP... ({e})", flush=True)
                time.sleep(self.TASK_IP_POLL_INTERVAL)

        raise TimeoutError("Failed to get task IP within timeout")

    def _register_to_alb(self, private_ip: str):
        """Register IP to ALB Target Group"""
        print(f"🔗 Registering {private_ip} to ALB Target Group...", flush=True)

        # Check existing targets
        current_targets = self._get_current_targets()
        print(f"📋 Current targets in ALB: {[t['Id'] for t in current_targets]}", flush=True)

        # Register new target
        self.elbv2_client.register_targets(
            TargetGroupArn=self.alb_target_group_arn,
            Targets=[{
                'Id': private_ip,
                'Port': self.CONTAINER_PORT
            }]
        )

        print(f"✅ Registered {private_ip} to ALB (keeping {len(current_targets)} existing targets)", flush=True)

    def _get_current_targets(self) -> list:
        """Query current targets in ALB Target Group"""
        response = self.elbv2_client.describe_target_health(
            TargetGroupArn=self.alb_target_group_arn
        )

        return [
            {
                'Id': target['Target']['Id'],
                'Port': self.CONTAINER_PORT
            }
            for target in response['TargetHealthDescriptions']
            if target['TargetHealth']['State'] in ['healthy', 'unhealthy', 'initial']
        ]

    def _check_existing_container_health(self) -> bool:
        """Check health status of existing container"""
        try:
            if not self.http_session:
                print(f"⚠️ HTTP session not initialized")
                return False

            response = self.http_session.get(f"http://{self.alb_dns}/health", timeout=self.HEALTH_CHECK_TIMEOUT)
            if response.status_code == 200:
                health_data = response.json()
                status = health_data.get('status', '')
                if status == 'healthy':
                    print(f"✅ Existing container healthy - reusable")
                    return True
                else:
                    print(f"❌ Existing container unhealthy status: {status}")
                    return False
            else:
                print(f"❌ Container health check failed - Status: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Container connection failed: {e}")
            return False

    def execute_code(self, code: str, description: str = "") -> Dict[str, Any]:
        """
        Execute code on fixed container
        - Terminate entire workflow if container is unresponsive
        - No new container creation allowed

        Args:
            code: Code to execute
            description: Execution description

        Returns:
            Execution result
        """
        self._ensure_active_session()
        self._ensure_http_session()

        print(f"🔄 [Session {self.current_session['session_id']}] Executing on FIXED container: {description}", flush=True)

        try:
            # 🍪 Use http_session (includes Sticky Session cookie - per-request isolation)
            response = self.http_session.post(
                f"http://{self.alb_dns}/execute",
                json={"code": code},
                timeout=self.CODE_EXECUTION_TIMEOUT  # Increased for large PDF generation and complex data processing
            )

            if response.status_code == 200:
                result = response.json()
                print(f"✅ Execution completed on fixed container: {result['execution_num']}/{result['total_executions']}", flush=True)
                return result
            else:
                self._raise_container_error("NOT RESPONDING", Exception(f"HTTP {response.status_code}"))

        except requests.exceptions.RequestException as e:
            self._raise_container_error("CONNECTION", e)

        except Exception as e:
            self._raise_container_error("EXECUTION", e)

    def complete_session(self, wait_for_s3: bool = True) -> Dict[str, Any]:
        """
        Complete current session and cleanup

        Args:
            wait_for_s3: Whether to wait for S3 upload completion

        Returns:
            Completion information
        """
        try:
            self._ensure_active_session()
        except Exception:
            return {"error": "No active session"}

        session_id = self.current_session['session_id']
        print(f"🏁 [Session {session_id}] Completing session...", flush=True)

        try:
            try:
                self._ensure_http_session()
            except Exception:
                print(f"⚠️ HTTP session not available for completion", flush=True)
                return {"error": "No HTTP session"}

            # 1. Send session completion signal (🍪 use http_session - per-request isolation)
            response = self.http_session.post(f"http://{self.alb_dns}/session/complete", timeout=self.SESSION_COMPLETE_TIMEOUT)
            result = response.json() if response.status_code == 200 else {}

            # 2. Wait for S3 upload
            if wait_for_s3:
                print(f"⏳ Waiting for S3 upload...", flush=True)
                time.sleep(self.S3_UPLOAD_WAIT)

            # 3. Session cleanup
            self._cleanup_session(self.current_session)

            # 4. Reset current session information
            self.current_session = None

            print(f"✅ [Session {session_id}] Session completed successfully!", flush=True)

            return {
                "session_id": session_id,
                "status": "completed",
                "total_executions": result.get('total_executions', 0)
            }

        except Exception as e:
            print(f"❌ [Session {session_id}] Error completing session: {e}", flush=True)
            return {"error": str(e)}

    def _cleanup_session(self, session_info: Dict[str, Any]):
        """Session cleanup (ALB deregister + Task stop)"""
        session_id = session_info['session_id']
        private_ip = session_info['private_ip']
        task_arn = session_info['task_arn']

        try:
            # 1. Remove from ALB
            print(f"🔗 [Session {session_id}] Removing from ALB...", flush=True)
            self.elbv2_client.deregister_targets(
                TargetGroupArn=self.alb_target_group_arn,
                Targets=[{
                    'Id': private_ip,
                    'Port': self.CONTAINER_PORT
                }]
            )

            # 2. Stop task (delete container)
            print(f"🛑 [Session {session_id}] Stopping task and deleting container...", flush=True)
            self.ecs_client.stop_task(
                cluster=self.cluster_name,
                task=task_arn,
                reason=f'Session {session_id} completed - Container deletion'
            )

            print(f"🧹 [Session {session_id}] Cleanup completed - Container deleted", flush=True)

        except Exception as e:
            print(f"⚠️ [Session {session_id}] Cleanup error: {e}", flush=True)

    def get_session_status(self) -> Dict[str, Any]:
        """Query current session status"""
        try:
            self._ensure_active_session()
        except Exception:
            return {"status": "no_session"}

        try:
            self._ensure_http_session()
        except Exception:
            return {"error": "No HTTP session"}

        try:
            response = self.http_session.get(f"http://{self.alb_dns}/session/status", timeout=self.STATUS_CHECK_TIMEOUT)
            if response.status_code == 200:
                status = response.json()
                status['session_info'] = self.current_session
                return status
            else:
                return {"error": f"Status check failed: HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}