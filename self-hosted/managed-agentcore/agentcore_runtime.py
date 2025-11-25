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

def _print_token_usage_summary() -> None:
    """
    Print final token usage statistics across all agents.

    Displays comprehensive token usage breakdown including:
    - Total tokens by agent
    - Model usage per agent
    - Cache hit/write statistics
    - Cost optimization insights
    """
    from src.graph.nodes import _global_node_states
    from src.utils.strands_sdk_utils import TokenTracker

    shared_state = _global_node_states.get('shared', {})
    TokenTracker.print_summary(shared_state)

def _save_token_usage_to_s3(request_id: str) -> None:
    """
    Save token usage statistics directly to S3.

    Uploads token usage files to S3:
    - s3://{bucket}/deep-insight/fargate_sessions/{session_id}/output/token_usage.json
    - s3://{bucket}/deep-insight/fargate_sessions/{session_id}/output/token_usage.txt

    Args:
        request_id (str): Request identifier to retrieve session ID
    """
    import json
    from datetime import datetime
    from src.graph.nodes import _global_node_states
    from src.tools.global_fargate_coordinator import get_global_session
    import boto3

    shared_state = _global_node_states.get('shared', {})
    token_usage = shared_state.get('token_usage', {})

    if not token_usage or token_usage.get('total_tokens', 0) == 0:
        print(f"⚠️ No token usage data to save for request {request_id}", flush=True)
        return

    # Get session ID from Fargate session manager
    fargate_manager = get_global_session()
    session_id = None

    if request_id in fargate_manager._sessions:
        session_id = fargate_manager._sessions[request_id]['session_id']

    if not session_id:
        print(f"⚠️ No session ID found for request {request_id}, using request_id as fallback", flush=True)
        session_id = request_id

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Prepare token usage data
    json_data = {
        "session_id": session_id,
        "request_id": request_id,
        "timestamp": timestamp,
        "summary": {
            "total_tokens": token_usage.get('total_tokens', 0),
            "total_input_tokens": token_usage.get('total_input_tokens', 0),
            "total_output_tokens": token_usage.get('total_output_tokens', 0),
            "cache_read_input_tokens": token_usage.get('cache_read_input_tokens', 0),
            "cache_write_input_tokens": token_usage.get('cache_write_input_tokens', 0)
        },
        "by_agent": token_usage.get('by_agent', {})
    }

    # Build text content
    text_lines = []
    text_lines.append("=" * 60)
    text_lines.append("Token Usage Summary")
    text_lines.append("=" * 60)
    text_lines.append(f"\nSession ID: {session_id}")
    text_lines.append(f"Request ID: {request_id}")
    text_lines.append(f"Timestamp: {timestamp}")
    text_lines.append("\n" + "-" * 60)
    text_lines.append("Overall Statistics")
    text_lines.append("-" * 60)

    total_input = token_usage.get('total_input_tokens', 0)
    total_output = token_usage.get('total_output_tokens', 0)
    total = token_usage.get('total_tokens', 0)
    cache_read = token_usage.get('cache_read_input_tokens', 0)
    cache_write = token_usage.get('cache_write_input_tokens', 0)

    # Get unique models used
    by_agent = token_usage.get('by_agent', {})
    models_used = set()
    for agent_data in by_agent.values():
        if 'model_id' in agent_data:
            models_used.add(agent_data['model_id'])

    text_lines.append(f"\nTotal Tokens: {total:,}")
    if models_used:
        text_lines.append(f"Model(s) Used: {', '.join(sorted(models_used))}")
    text_lines.append(f"  - Regular Input:  {total_input:>10,} (100% cost)")
    text_lines.append(f"  - Cache Read:     {cache_read:>10,} (10% cost - 90% discount)")
    text_lines.append(f"  - Cache Write:    {cache_write:>10,} (125% cost - 25% extra)")
    text_lines.append(f"  - Output:         {total_output:>10,}")

    # Model Usage Summary - aggregate by model
    if by_agent:
        text_lines.append("\n" + "-" * 60)
        text_lines.append("Model Usage Summary (for cost calculation)")
        text_lines.append("-" * 60)

        # Aggregate tokens by model
        model_usage = {}
        for agent_name, usage in by_agent.items():
            model_id = usage.get('model_id', 'unknown')
            if model_id not in model_usage:
                model_usage[model_id] = {
                    'input': 0,
                    'output': 0,
                    'cache_read': 0,
                    'cache_write': 0,
                    'agents': []
                }
            model_usage[model_id]['input'] += usage.get('input', 0)
            model_usage[model_id]['output'] += usage.get('output', 0)
            model_usage[model_id]['cache_read'] += usage.get('cache_read', 0)
            model_usage[model_id]['cache_write'] += usage.get('cache_write', 0)
            model_usage[model_id]['agents'].append(agent_name)

        # Display model usage
        for model_id in sorted(model_usage.keys()):
            usage = model_usage[model_id]
            model_total = usage['input'] + usage['output'] + usage['cache_read'] + usage['cache_write']
            agents_str = ', '.join(usage['agents'])

            text_lines.append(f"\n  [{model_id}]")
            text_lines.append(f"    Total: {model_total:,}")
            text_lines.append(f"    - Regular Input:  {usage['input']:>10,} (100% cost)")
            text_lines.append(f"    - Cache Read:     {usage['cache_read']:>10,} (10% cost - 90% discount)")
            text_lines.append(f"    - Cache Write:    {usage['cache_write']:>10,} (125% cost - 25% extra)")
            text_lines.append(f"    - Output:         {usage['output']:>10,}")
            text_lines.append(f"    Used by: {agents_str}")

        text_lines.append("\n" + "-" * 60)
        text_lines.append("Token Usage by Agent")
        text_lines.append("-" * 60)

        for agent_name in sorted(by_agent.keys()):
            usage = by_agent[agent_name]
            input_tokens = usage.get('input', 0)
            output_tokens = usage.get('output', 0)
            agent_cache_read = usage.get('cache_read', 0)
            agent_cache_write = usage.get('cache_write', 0)
            agent_total = input_tokens + output_tokens + agent_cache_read + agent_cache_write
            model_id = usage.get('model_id', 'unknown')

            text_lines.append(f"\n[{agent_name}] Total: {agent_total:,}")
            text_lines.append(f"  Model: {model_id}")
            text_lines.append(f"  - Regular Input:  {input_tokens:>10,} (100% cost)")
            text_lines.append(f"  - Cache Read:     {agent_cache_read:>10,} (10% cost - 90% discount)")
            text_lines.append(f"  - Cache Write:    {agent_cache_write:>10,} (125% cost - 25% extra)")
            text_lines.append(f"  - Output:         {output_tokens:>10,}")

    text_lines.append("\n" + "=" * 60)
    text_content = "\n".join(text_lines)

    # Upload directly to S3 (no local files)
    try:
        s3_bucket = os.getenv('S3_BUCKET_NAME')
        aws_region = os.getenv('AWS_REGION', 'us-east-1')

        if not s3_bucket:
            print(f"⚠️ S3_BUCKET_NAME not set, skipping S3 upload", flush=True)
            return

        s3_client = boto3.client('s3', region_name=aws_region)
        s3_prefix = f"deep-insight/fargate_sessions/{session_id}/output/"

        # Upload JSON directly to S3
        s3_json_key = f"{s3_prefix}token_usage.json"
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=s3_json_key,
            Body=json.dumps(json_data, indent=2, ensure_ascii=False),
            ContentType='application/json'
        )
        print(f"✅ Token usage uploaded to S3: s3://{s3_bucket}/{s3_json_key}", flush=True)

        # Upload TXT directly to S3
        s3_txt_key = f"{s3_prefix}token_usage.txt"
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=s3_txt_key,
            Body=text_content,
            ContentType='text/plain'
        )
        print(f"✅ Token usage uploaded to S3: s3://{s3_bucket}/{s3_txt_key}", flush=True)

    except Exception as e:
        print(f"⚠️ Failed to upload token usage to S3: {e}", flush=True)

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

def _extract_data_directory_from_payload(payload: Dict[str, Any]) -> str:
    """
    Extract data directory from payload parameter.

    Args:
        payload (dict): Request payload from AgentCore

    Returns:
        str: Data directory path, or None if not provided
    """
    return payload.get("data_directory")

def _build_graph_input(user_query: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build graph input configuration from user query and payload.

    Constructs complete input dictionary for graph execution including:
    - User query and formatted prompt (for LLM understanding)
    - Data directory for S3 upload to Fargate
    - AgentCore metadata (runtime info, version, features)

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

    # Extract data directory from payload parameter
    data_directory = payload.get("data_directory")
    if data_directory:
        graph_input["data_directory"] = data_directory
        print(f"📂 Using data directory: {data_directory}", flush=True)

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
            # Filter out high-volume events to prevent client connection overload
            # See: https://github.com/aws/... - socket.send() errors from event volume
            SKIP_EVENT_TYPES = {"agent_usage_stream"}  # usage_metadata events are very frequent
            event_count = 0
            async for event in graph.stream_async(graph_input):
                # Skip high-frequency metadata events to reduce streaming volume
                if event.get("type") in SKIP_EVENT_TYPES:
                    continue
                event_count += 1
                yield _enrich_event(event, event_count)

            # Step 6: Print conversation history and completion
            _print_conversation_history()
            _print_token_usage_summary()

            # Step 6.5: Save token usage directly to S3
            _save_token_usage_to_s3(request_id)

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