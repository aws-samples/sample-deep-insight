"""
agentcore_runtime.py

Purpose:
    Main entry point for AgentCore Runtime execution with streaming workflow support.
    Orchestrates multi-agent task execution with Fargate container management and
    comprehensive observability.

Runtime Architecture:
    This runtime manages a complete agent execution workflow:

    1. AgentCore Runtime Container (runs this script):
       - Receives user queries via AgentCore entrypoint
       - Orchestrates agent graph execution
       - Manages streaming event delivery
       - Handles observability and tracing

    2. ECS Fargate Containers (spawned on-demand):
       - Execute agent tasks (code, tools, data analysis)
       - Communicate with runtime via ALB
       - Managed by global_fargate_coordinator
       - Auto-cleanup after request completion

Execution Flow:
    1. Initialize execution environment (artifacts, event queue)
    2. Generate unique request ID for tracking
    3. Setup Fargate session context
    4. Extract user query with fallbacks
    5. Build graph and prepare input configuration
    6. Stream events from graph execution with enrichment
    7. Record observability metrics
    8. Clean up Fargate sessions and resources

Usage:
    # Development (local testing)
    uv run python3 agentcore_runtime.py

    # Production (AgentCore deployment)
    Deploy via create_agentcore_runtime_vpc.py
    Invoke via invoke_agentcore_runtime_vpc.py

Main Features:
    - Async streaming workflow with event enrichment
    - Fargate container lifecycle management
    - OpenTelemetry observability integration
    - Multi-level error handling (specific exceptions)
    - Per-request cleanup with fail-safe termination
    - VPC-mode support with private networking

Environment Variables Required:
    - AWS_REGION: AWS region for resources
    - AWS_ACCOUNT_ID: AWS account identifier
    - ECS_CLUSTER_NAME: ECS cluster for Fargate tasks
    - TASK_DEFINITION_ARN: Fargate task definition
    - ALB_DNS: Application Load Balancer endpoint
    - BEDROCK_MODEL_ID: Claude model identifier
    - OTEL_*: Observability configuration (6 variables)

Important Notes:
    - app.add_async_task() not used (causes 94s timeout with 60-90s health checks)
    - Fargate cleanup happens at both request-level and process-level
    - All helper functions prefixed with _ for internal use
    - Type hints required for all function signatures
    - Flush output for real-time CloudWatch visibility

Related Files:
    - create_agentcore_runtime_vpc.py: Runtime deployment script
    - invoke_agentcore_runtime_vpc.py: Runtime testing script
    - src/tools/global_fargate_coordinator.py: Fargate session manager
    - src/graph/builder.py: Agent graph construction
"""
import os
import shutil
import asyncio
import atexit
import subprocess
from typing import Dict, Any, AsyncGenerator
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from src.utils.strands_sdk_utils import strands_utils
from src.graph.builder import build_graph

# ECS Cluster configuration from environment
# Note: Environment variables are provided by AWS via create_agentcore_runtime_vpc.py
# (passed to runtime container via Runtime.launch(env_vars=...))
ECS_CLUSTER_NAME = os.getenv("ECS_CLUSTER_NAME", "my-fargate-cluster")

# Configuration constants
ARTIFACTS_FOLDER = "./artifacts/"
RUNTIME_SOURCE = "bedrock_manus_agentcore"
RUNTIME_VERSION = "2.0"
AGENTCORE_SESSION_NAME = "agentcore-session"
TRACER_MODULE_NAME_DEFAULT = "agentcore_insight_extractor"
TRACER_LIBRARY_VERSION_DEFAULT = "2.0.0"
SEPARATOR_LINE = "=" * 60

# Timeout configurations (in seconds)
AWS_CLI_LIST_TIMEOUT = 30
AWS_CLI_STOP_TIMEOUT = 20

# Observability
from opentelemetry import trace
from opentelemetry import context as otel_context
from src.utils.agentcore_observability import set_session_context, add_span_event

# Import event queue for unified event processing
from src.utils.event_queue import clear_queue

# Import Fargate session manager for cleanup
from src.tools.global_fargate_coordinator import get_global_session

# Initialize AgentCore app
app = BedrockAgentCoreApp()

def remove_artifact_folder(folder_path: str = ARTIFACTS_FOLDER) -> None:
    """
    Remove the artifacts folder if it exists.

    Safely removes the specified folder and all its contents. Handles permission
    errors and missing folders gracefully.

    Args:
        folder_path (str): Path to the folder to be removed. Defaults to ./artifacts/
    """
    if os.path.exists(folder_path):
        print(f"Removing '{folder_path}' folder...")
        try:
            shutil.rmtree(folder_path)
            print(f"'{folder_path}' folder successfully removed.")
        except OSError as e:
            print(f"Error removing folder '{folder_path}': {e}", flush=True)
        except PermissionError as e:
            print(f"Permission denied when removing '{folder_path}': {e}", flush=True)
    else:
        print(f"'{folder_path}' folder does not exist.")

def cleanup_fargate_session() -> None:
    """
    Clean up Fargate session with guaranteed task termination.

    Performs two-stage cleanup:
    1. Graceful session completion with S3 upload wait
    2. Forced termination of any remaining ECS tasks (fail-safe)

    This function should only be called at process termination via atexit.
    """
    try:
        # 1. Attempt graceful session cleanup
        fargate_manager = get_global_session()
        if fargate_manager and fargate_manager._session_manager and fargate_manager._session_manager.current_session:
            print("\n🧹 Starting final Fargate session cleanup...", flush=True)

            # Send session completion signal and wait for S3 upload
            print("📤 Initiating final S3 upload and waiting for completion...", flush=True)
            completion_result = fargate_manager._session_manager.complete_session(wait_for_s3=True)

            if completion_result and completion_result.get("status") == "success":
                print("✅ S3 upload confirmed - all Fargate artifacts uploaded", flush=True)
            else:
                print("⚠️ S3 upload status unclear, but proceeding with cleanup", flush=True)

        # 2. Force cleanup of all Fargate tasks (fail-safe)
        print("🔍 Checking for any remaining Fargate tasks...", flush=True)
        try:
            result = subprocess.run([
                'aws', 'ecs', 'list-tasks',
                '--cluster', ECS_CLUSTER_NAME,
                '--query', 'taskArns[*]',
                '--output', 'text'
            ], capture_output=True, text=True, timeout=AWS_CLI_LIST_TIMEOUT)

            if result.returncode == 0 and result.stdout.strip():
                task_arns = result.stdout.strip().split('\t')
                task_ids = [arn.split('/')[-1] for arn in task_arns if arn.strip()]

                if task_ids:
                    print(f"🛑 Found {len(task_ids)} running tasks, terminating...", flush=True)
                    for task_id in task_ids:
                        subprocess.run([
                            'aws', 'ecs', 'stop-task',
                            '--cluster', ECS_CLUSTER_NAME,
                            '--task', task_id
                        ], capture_output=True, timeout=AWS_CLI_STOP_TIMEOUT)
                        print(f"   • Stopped task: {task_id[:12]}...", flush=True)
                    print("✅ All orphaned Fargate tasks terminated", flush=True)
                else:
                    print("✅ No running Fargate tasks found", flush=True)
            else:
                print("ℹ️ Could not list Fargate tasks (cluster may not exist)", flush=True)

        except subprocess.TimeoutExpired:
            print("⚠️ Timeout while checking Fargate tasks", flush=True)
        except subprocess.CalledProcessError as e:
            print(f"⚠️ AWS CLI error during task cleanup: {e}", flush=True)
        except FileNotFoundError:
            print("⚠️ AWS CLI not found - cannot list/stop tasks", flush=True)
        except Exception as cleanup_error:
            print(f"⚠️ Unexpected error during task cleanup: {cleanup_error}", flush=True)

        print("✅ Fargate session cleanup completed", flush=True)
    except (AttributeError, KeyError) as e:
        print(f"⚠️ Fargate session manager not properly initialized: {e}", flush=True)
    except Exception as e:
        print(f"⚠️ Unexpected error during Fargate session cleanup: {e}", flush=True)

def _setup_execution() -> None:
    """
    Initialize execution environment for AgentCore Runtime.

    Clears artifacts folder and event queue before starting new execution.
    Per-request cleanup is handled separately in finally blocks.
    """
    remove_artifact_folder()
    clear_queue()

    # ⚠️ cleanup_fargate_session should only run at process termination
    # Per-request cleanup is handled in finally block via cleanup_session(request_id)
    # atexit is registered only once to prevent duplicates

    print("\n=== Starting AgentCore Runtime Event Stream ===")

def _print_conversation_history() -> None:
    """
    Print final conversation history from agent execution.

    Displays all agent messages from the shared state, or a message
    if no history is available.
    """
    print("\n=== Conversation History ===")
    from src.graph.nodes import _global_node_states
    shared_state = _global_node_states.get('shared', {})
    history = shared_state.get('history', [])

    if history:
        for hist_item in history:
            print(f"[{hist_item['agent']}] {hist_item['message']}")
    else:
        print("No conversation history found")

def _generate_request_id() -> str:
    """
    Generate and print unique request ID for tracking.

    Returns:
        str: UUID-based unique request identifier
    """
    import uuid
    request_id = str(uuid.uuid4())
    print(f"\n{SEPARATOR_LINE}")
    print(f"🆔 Request ID: {request_id}")
    print(f"{SEPARATOR_LINE}\n", flush=True)
    return request_id

def _setup_fargate_context(request_id: str) -> None:
    """
    Set up Fargate session context for request.

    Initializes the Fargate session manager with the request ID for tracking
    and managing container lifecycle during execution.

    Args:
        request_id (str): Unique identifier for the current request
    """
    try:
        fargate_manager = get_global_session()
        fargate_manager.set_request_context(request_id)
        print(f"✅ Fargate session context set for request: {request_id}", flush=True)
    except AttributeError as e:
        print(f"⚠️ Fargate manager not available or method missing: {e}", flush=True)
    except Exception as e:
        print(f"⚠️ Unexpected error setting Fargate session context: {e}", flush=True)

def _extract_user_query(payload: Dict[str, Any]) -> str:
    """
    Extract user query from payload.

    Attempts to extract query in order:
    1. 'prompt' key (AgentCore standard)
    2. 'user_query' key (compatibility)
    3. Raises error if neither is provided

    Args:
        payload (dict): Request payload from AgentCore

    Returns:
        str: User query string from client

    Raises:
        ValueError: If no prompt is provided in payload
    """
    # AgentCore uses 'prompt' key
    user_query = payload.get("prompt", "")

    # Fall back to 'user_query' for compatibility
    if not user_query:
        user_query = payload.get("user_query", "")

    # Error if no query provided (runtime is a server, not a standalone app)
    if not user_query:
        raise ValueError("No prompt provided in payload. Runtime requires 'prompt' or 'user_query' from client.")

    return user_query

def _extract_csv_path_from_prompt(prompt: str) -> str:
    """
    Extract CSV file path from user prompt using regex.

    Searches for file paths ending with .csv in the prompt text.
    Supports both relative and absolute paths.

    Args:
        prompt (str): User's prompt text

    Returns:
        str: Extracted CSV file path, or None if not found

    Examples:
        "./data/file.csv 파일 분석해줘" → "./data/file.csv"
        "Read /home/user/data.csv and analyze" → "/home/user/data.csv"
    """
    import re
    # Match file paths ending with .csv
    # Supports: ./path/file.csv, /absolute/path/file.csv, relative/file.csv
    match = re.search(r'([./\w\-]+\.csv)', prompt)
    return match.group(1) if match else None

def _build_graph_input(user_query: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build graph input configuration from user query and payload.

    Constructs complete input dictionary for graph execution including:
    - User query and formatted prompt (for LLM understanding)
    - Extracted CSV file path (for system S3 upload to Fargate)
    - AgentCore metadata (runtime info, version, features)

    The CSV file path is extracted from the user prompt automatically.
    This allows natural language queries while enabling system-level file handling.

    Args:
        user_query (str): User's query string
        payload (dict): Original request payload for additional parameters

    Returns:
        dict: Complete graph input configuration
    """
    # Prepare input for AgentCore-enhanced graph execution
    graph_input = {
        "request": user_query,
        "request_prompt": f"AgentCore Request: <user_request>{user_query}</user_request>",
        "agentcore_enabled": True,
        "runtime_source": RUNTIME_SOURCE
    }

    # Extract CSV file path from prompt (if mentioned)
    # Priority: 1. Explicit payload parameter, 2. Extracted from prompt
    csv_file_path = payload.get("csv_file_path") or _extract_csv_path_from_prompt(user_query)
    graph_input["csv_file_path"] = csv_file_path
    if csv_file_path:
        print(f"📂 Extracted CSV file path: {csv_file_path}", flush=True)

    # Add AgentCore metadata
    agentcore_metadata = payload.get("agentcore_metadata", {
        "runtime": "agentcore",
        "version": RUNTIME_VERSION,
        "fargate_enabled": True
    })
    graph_input["agentcore_metadata"] = agentcore_metadata

    return graph_input

def _enrich_event(event: Dict[str, Any], event_count: int) -> Dict[str, Any]:
    """
    Add AgentCore runtime metadata to streaming event.

    Enriches each event with event ID, runtime source, and marks the final
    event with total count and completion message.

    Args:
        event (dict): Event dictionary from graph execution
        event_count (int): Sequential event number

    Returns:
        dict: Enriched event with added metadata
    """
    event["event_id"] = event_count
    event["runtime_source"] = RUNTIME_SOURCE

    # Mark final event
    if event.get("type") == "workflow_complete":
        event["total_events"] = event_count
        event["message"] = "All events processed through AgentCore Runtime"

    return event

def _cleanup_request_session(request_id: str) -> None:
    """
    Clean up Fargate session for completed request.

    Performs cleanup of Fargate containers and resources associated with
    the specific request. Handles cases where session manager is unavailable
    or request ID is not found.

    Args:
        request_id (str): Request identifier to clean up
    """
    try:
        fargate_manager = get_global_session()
        print(f"\n🧹 Request {request_id} completed - cleaning up Fargate session...", flush=True)
        fargate_manager.cleanup_session(request_id)
        print(f"✅ Fargate session cleaned up for request {request_id}", flush=True)
    except AttributeError as e:
        print(f"⚠️ Fargate manager unavailable during cleanup for {request_id}: {e}", flush=True)
    except KeyError as e:
        print(f"⚠️ Request ID {request_id} not found in Fargate sessions: {e}", flush=True)
    except Exception as cleanup_error:
        print(f"⚠️ Unexpected error cleaning up Fargate session for {request_id}: {cleanup_error}", flush=True)

@app.entrypoint
async def agentcore_streaming_execution(
    payload: Dict[str, Any],
    context: Any
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Execute full graph streaming workflow through AgentCore Runtime.

    Orchestrates the complete agent execution workflow:
    1. Initialize request (ID generation, Fargate context, query extraction)
    2. Build and configure graph with user query
    3. Stream events from graph execution with metadata enrichment
    4. Clean up resources on completion

    Enhanced with Fargate session management, observability tracing, and
    comprehensive error handling.

    Args:
        payload (dict): Request payload containing user query and configuration
        context: AgentCore runtime context for ping/health management

    Yields:
        dict: Enriched streaming events from graph execution
    """

    # Step 1: Initialize execution environment
    _setup_execution()

    # Step 2: Initialize request context
    request_id = _generate_request_id()
    _setup_fargate_context(request_id)
    user_query = _extract_user_query(payload)

    context_token = set_session_context(AGENTCORE_SESSION_NAME)

    try:
        # Step 3: Setup observability tracing
        tracer = trace.get_tracer(
            instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", TRACER_MODULE_NAME_DEFAULT),
            instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", TRACER_LIBRARY_VERSION_DEFAULT)
        )

        with tracer.start_as_current_span("agentcore_session") as span:
            # Step 4: Build and configure graph
            graph = build_graph()
            graph_input = _build_graph_input(user_query, payload)

            print(f"🚀 Launching AgentCore Runtime with query: {user_query[:100]}...")

            # Step 5: Stream events from graph execution
            event_count = 0
            async for event in graph.stream_async(graph_input):
                event_count += 1
                yield _enrich_event(event, event_count)

            # Step 6: Print conversation history and completion
            _print_conversation_history()
            print("=== AgentCore Runtime Event Stream Complete ===")

            # Step 7: Record observability metrics
            add_span_event(span, "agentcore_query", {
                "user-query": str(user_query),
                "agentcore-enabled": True,
                "total-events": event_count
            })

    finally:
        # Step 8: Clean up resources
        _cleanup_request_session(request_id)
        otel_context.detach(context_token)

if __name__ == "__main__":
    # Register cleanup to run only at process termination (once)
    atexit.register(cleanup_fargate_session)

    # Run with AgentCore app.run()
    print(SEPARATOR_LINE)
    print("🤖 AgentCore Runtime v2.0 with async task management")
    print(SEPARATOR_LINE)
    app.run()