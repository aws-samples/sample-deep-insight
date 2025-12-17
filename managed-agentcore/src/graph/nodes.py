
import os
import time
import json
import logging
import asyncio
import boto3
from dotenv import load_dotenv
from strands.types.content import ContentBlock
from src.utils.strands_sdk_utils import strands_utils, TokenTracker
from src.prompts.template import apply_prompt_template
from src.utils.common_utils import get_message_from_string
from src.utils.event_queue import put_event
from src.utils.s3_utils import get_s3_feedback_key, check_s3_feedback, delete_s3_feedback

# Load environment variables
load_dotenv()

# Plan feedback configuration (Human-in-the-Loop)
MAX_PLAN_REVISIONS = int(os.getenv("MAX_PLAN_REVISIONS", "10"))
PLAN_FEEDBACK_TIMEOUT = int(os.getenv("PLAN_FEEDBACK_TIMEOUT", "300"))  # 5 minutes default
PLAN_FEEDBACK_POLL_INTERVAL = int(os.getenv("PLAN_FEEDBACK_POLL_INTERVAL", "3"))  # 3 seconds

# Tools
from src.tools.coder_agent_custom_interpreter_tool import coder_agent_custom_interpreter_tool
from src.tools.reporter_agent_custom_interpreter_tool import reporter_agent_custom_interpreter_tool
from src.tools.tracker_agent_tool import tracker_agent_tool
from src.tools.validator_agent_custom_interpreter_tool import validator_agent_custom_interpreter_tool

# Observability
from opentelemetry import trace
from src.utils.agentcore_observability import add_span_event

# Simple logger setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    END = '\033[0m'

def log_node_start(node_name: str):
    """Log the start of a node execution."""
    print()  # Add newline before log
    logger.info(f"{Colors.GREEN}===== {node_name} started ====={Colors.END}")

def log_node_complete(node_name: str):
    """Log the completion of a node."""
    print()  # Add newline before log
    logger.info(f"{Colors.GREEN}===== {node_name} completed ====={Colors.END}")

    # Print token usage using TokenTracker
    global _global_node_states
    shared_state = _global_node_states.get('shared', {})
    TokenTracker.print_current(shared_state)

# Global state storage for sharing between nodes
_global_node_states = {}

RESPONSE_FORMAT = "Response from {}:\n\n<response>\n{}\n</response>\n\n*Please execute the next step.*"
FULL_PLAN_FORMAT = "Here is full plan :\n\n<full_plan>\n{}\n</full_plan>\n\n*Please consider this to select the next step.*"
CLUES_FORMAT = "Here is clues from {}:\n\n<clues>\n{}\n</clues>\n\n"


def should_handoff_to_planner(_):
    """Check if coordinator requested handoff to planner."""

    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("should_handoff_to_planner") as span:
        # Check coordinator's response for handoff request
        global _global_node_states
        shared_state = _global_node_states.get('shared', {})
        history = shared_state.get('history', [])

        # Look for coordinator's last message
        for entry in reversed(history):
            if entry.get('agent') == 'coordinator':
                message = entry.get('message', '')

                # Add Event
                add_span_event(span, "input_message", {"message": str(message)})
                add_span_event(span, "response", {"handoff_to_planner": bool("handoff_to_planner" in message)})

                return 'handoff_to_planner' in message

        return False


# ============================================================
# Plan Revision Conditional Functions (Human-in-the-Loop)
# ============================================================

def _check_plan_revision_state():
    """Helper to get plan revision state from global storage."""
    global _global_node_states
    shared_state = _global_node_states.get('shared', {})
    return shared_state.get('plan_revision_requested', False)


def should_revise_plan(_):
    """Check if user requested plan revision in plan_reviewer.

    Note: Strands SDK requires explicit conditions on both outgoing edges from a node
    to ensure only one destination becomes "ready". This is why we have two opposite
    condition functions (should_revise_plan and should_proceed_to_supervisor).
    """
    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("should_revise_plan") as span:
        result = _check_plan_revision_state()
        logger.info(f"should_revise_plan: {result}")
        add_span_event(span, "condition_check", {"should_revise_plan": result})
        return result


def should_proceed_to_supervisor(_):
    """Check if plan was approved and should proceed to supervisor.

    Note: This is the logical negation of should_revise_plan. Both conditions are needed
    because Strands SDK evaluates all edges and marks destination nodes as "ready"
    if their incoming edge conditions are satisfied.
    """
    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("should_proceed_to_supervisor") as span:
        result = not _check_plan_revision_state()
        logger.info(f"should_proceed_to_supervisor: {result}")
        add_span_event(span, "condition_check", {"should_proceed_to_supervisor": result})
        return result

async def coordinator_node(task=None, **kwargs):

    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("coordinator") as span:
        """Coordinator node that communicate with customers."""
        global _global_node_states

        log_node_start("Coordinator")

        # Extract user request from task (now passed as dictionary)
        if isinstance(task, dict):
            request = task.get("request", "")
            request_prompt = task.get("request_prompt", request)
            data_directory = task.get("data_directory")  # Directory upload
            request_id = task.get("request_id", "")  # For human-in-the-loop feedback
        else:
            request = str(task) if task else ""
            request_prompt = request
            data_directory = None
            request_id = ""

        agent = strands_utils.get_agent(
            agent_name="coordinator",
            system_prompts=apply_prompt_template(prompt_name="coordinator", prompt_context={}), # apply_prompt_template(prompt_name="task_agent", prompt_context={"TEST": "sdsd"})
            model_id=os.getenv("COORDINATOR_MODEL_ID", os.getenv("DEFAULT_MODEL_ID")),
            enable_reasoning=False,
            prompt_cache_info=(False, None), #(False, None), (True, "default")
            tool_cache=False,
            streaming=True,
        )

        # Store data directly in shared global storage
        if 'shared' not in _global_node_states: _global_node_states['shared'] = {}
        shared_state = _global_node_states['shared']

        # Process streaming response and collect text in one pass
        full_text = ""
        async for event in strands_utils.process_streaming_response_yield(
            agent, request_prompt, agent_name="coordinator", source="coordinator_node"
        ):
            if event.get("event_type") == "text_chunk":
                full_text += event.get("data", "")
            # Accumulate token usage
            TokenTracker.accumulate(event, shared_state)
        response = {"text": full_text}

        # Update shared global state
        shared_state['messages'] = agent.messages
        shared_state['request'] = request
        shared_state['request_prompt'] = request_prompt

        # Store data directory
        if data_directory:
            shared_state['data_directory'] = data_directory
            logger.info(f"📂 Shared state: data_directory = {data_directory}")
        else:
            shared_state['data_directory'] = None

        # Store request_id for human-in-the-loop feedback
        shared_state['request_id'] = request_id
        if request_id:
            logger.info(f"🆔 Shared state: request_id = {request_id}")

        # Build and update history
        if 'history' not in shared_state:
            shared_state['history'] = []
        shared_state['history'].append({"agent":"coordinator", "message": response["text"]})

        # Add Event
        add_span_event(span, "input_message", {"message": str(request_prompt)})
        add_span_event(span, "response", {"response": str(response["text"])})

        log_node_complete("Coordinator")
        # Return response only
        return response

async def planner_node(task=None, **kwargs):

    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("planner") as span:   
        """Planner node that generates detailed plans for task execution."""
        log_node_start("Planner")
        global _global_node_states

        # Extract shared state from global storage
        shared_state = _global_node_states.get('shared', None)

        # Get request from shared state (task parameter not used in planner)
        request = shared_state.get("request", "") if shared_state else ""

        if not shared_state:
            logger.warning("No shared state found in global storage")
            return None, {"text": "No shared state available"}

        # Check if this is a revision request (Human-in-the-Loop)
        is_revision = shared_state.get('plan_revision_requested', False)
        plan_feedback = shared_state.get('plan_feedback', '')
        previous_plan = shared_state.get('full_plan', '')
        revision_count = shared_state.get('plan_revision_count', 0)

        # Select appropriate prompt based on whether this is initial planning or revision
        if is_revision and plan_feedback:
            # Use revision prompt with feedback context
            prompt_context = {
                "USER_REQUEST": request,
                "PREVIOUS_PLAN": previous_plan,
                "USER_FEEDBACK": plan_feedback,
                "REVISION_COUNT": revision_count,
                "MAX_REVISIONS": MAX_PLAN_REVISIONS
            }
            prompt_name = "planner_revise"
            logger.info(f"{Colors.YELLOW}Revising plan based on user feedback (revision {revision_count}){Colors.END}")
        else:
            prompt_context = {"USER_REQUEST": request}
            prompt_name = "planner"

        agent = strands_utils.get_agent(
            agent_name="planner",
            system_prompts=apply_prompt_template(prompt_name=prompt_name, prompt_context=prompt_context),
            model_id=os.getenv("PLANNER_MODEL_ID", os.getenv("DEFAULT_MODEL_ID")),
            enable_reasoning=True,
            prompt_cache_info=(False, None),  # enable prompt caching for reasoning agent, (False, None), (True, "default")
            tool_cache=False,
            streaming=True,
        )

        messages = shared_state["messages"]
        message = messages[-1]["content"][-1]["text"]

        # If revision, append feedback to the message
        if is_revision and plan_feedback:
            message = f"{message}\n\n<user_feedback>\nUser requested the following changes to the plan:\n{plan_feedback}\n</user_feedback>"
            # Reset the revision flag after using it
            shared_state['plan_revision_requested'] = False

        # Process streaming response and collect text in one pass
        full_text = ""
        async for event in strands_utils.process_streaming_response_yield(
            agent, message, agent_name="planner", source="planner_node"
        ):
            if event.get("event_type") == "text_chunk":
                full_text += event.get("data", "")
            # Accumulate token usage
            TokenTracker.accumulate(event, shared_state)
        response = {"text": full_text}

        # Update shared global state
        shared_state['messages'] = [get_message_from_string(role="user", string=response["text"], imgs=[])]
        shared_state['full_plan'] = response["text"]
        shared_state['history'].append({"agent":"planner", "message": response["text"]})

        # Add Event
        add_span_event(span, "input_message", {"message": str(message)})
        add_span_event(span, "response", {"response": str(response["text"])})
        add_span_event(span, "revision_info", {"is_revision": is_revision, "revision_count": revision_count})

        log_node_complete("Planner")
        # Return response only
        return response


async def plan_reviewer_node(task=None, **kwargs):
    """
    Plan reviewer node that allows user to review and provide feedback on the generated plan.

    This node implements human-in-the-loop for managed AgentCore by:
    1. Emitting a 'plan_review_request' event with the plan via the event queue
    2. Polling S3 for a feedback file uploaded by the client
    3. Processing the feedback to either approve or request revision

    The feedback file format (JSON):
    {
        "approved": true/false,
        "feedback": "optional revision notes"
    }
    """
    log_node_start("PlanReviewer")
    global _global_node_states

    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("plan_reviewer") as span:
        shared_state = _global_node_states.get('shared', {})

        if not shared_state:
            logger.warning("No shared state found in global storage")
            return {"text": "No shared state available"}

        # Get current plan and revision count
        full_plan = shared_state.get('full_plan', '')
        revision_count = shared_state.get('plan_revision_count', 0)
        request_id = shared_state.get('request_id', '')

        # Reset revision flag at start
        shared_state['plan_revision_requested'] = False

        # Check if we've exceeded max revisions - auto-approve
        if revision_count >= MAX_PLAN_REVISIONS:
            logger.info(f"{Colors.YELLOW}Max revisions ({MAX_PLAN_REVISIONS}) reached. Auto-approving plan.{Colors.END}")
            shared_state['history'].append({
                "agent": "plan_reviewer",
                "message": f"Plan auto-approved (max {MAX_PLAN_REVISIONS} revisions reached)"
            })
            add_span_event(span, "auto_approve", {"reason": "max_revisions_reached", "revision_count": revision_count})
            log_node_complete("PlanReviewer")
            return {"text": "Plan auto-approved after max revisions", "approved": True}

        # Step 1: Emit plan_review_request event to client via event queue
        s3_bucket = os.getenv('S3_BUCKET_NAME', '')
        plan_review_event = {
            "type": "plan_review_request",
            "event_type": "plan_review_request",
            "plan": full_plan,
            "revision_count": revision_count,
            "max_revisions": MAX_PLAN_REVISIONS,
            "request_id": request_id,
            "feedback_s3_path": f"s3://{s3_bucket}/{get_s3_feedback_key(request_id)}",
            "timeout_seconds": PLAN_FEEDBACK_TIMEOUT,
            "message": "Please review the plan and provide feedback"
        }
        put_event(plan_review_event)
        logger.info(f"{Colors.CYAN}📋 Plan review request sent to client (revision {revision_count}/{MAX_PLAN_REVISIONS}){Colors.END}")
        add_span_event(span, "plan_review_request_sent", {"request_id": request_id, "revision_count": revision_count})

        # Step 2: Poll S3 for feedback with timeout
        start_time = time.time()
        feedback_data = None
        poll_count = 0

        while (time.time() - start_time) < PLAN_FEEDBACK_TIMEOUT:
            poll_count += 1

            # Check for feedback file in S3
            feedback_data = check_s3_feedback(request_id)
            if feedback_data:
                logger.info(f"{Colors.GREEN}✅ Feedback received after {poll_count} polls{Colors.END}")
                # Delete the feedback file after reading
                delete_s3_feedback(request_id)
                break

            # Emit keepalive event to prevent connection timeout
            if poll_count % 2 == 0:  # Every ~6 seconds (2 polls × 3 seconds)
                keepalive_event = {
                    "type": "plan_review_keepalive",
                    "event_type": "plan_review_keepalive",
                    "message": f"Waiting for plan feedback... ({int(time.time() - start_time)}s elapsed)",
                    "elapsed_seconds": int(time.time() - start_time),
                    "timeout_seconds": PLAN_FEEDBACK_TIMEOUT
                }
                put_event(keepalive_event)

            # Wait before next poll
            await asyncio.sleep(PLAN_FEEDBACK_POLL_INTERVAL)

        # Step 3: Process feedback or timeout
        if feedback_data is None:
            # Timeout - auto-approve
            logger.info(f"{Colors.YELLOW}⏰ Feedback timeout ({PLAN_FEEDBACK_TIMEOUT}s). Auto-approving plan.{Colors.END}")
            shared_state['history'].append({
                "agent": "plan_reviewer",
                "message": f"Plan auto-approved (timeout after {PLAN_FEEDBACK_TIMEOUT}s)"
            })
            add_span_event(span, "timeout_auto_approve", {"timeout_seconds": PLAN_FEEDBACK_TIMEOUT})
            log_node_complete("PlanReviewer")
            return {"text": "Plan auto-approved after timeout", "approved": True}

        # Process feedback
        is_approved = feedback_data.get('approved', True)
        user_feedback = feedback_data.get('feedback', '')

        if is_approved:
            # User approved the plan
            shared_state['history'].append({
                "agent": "plan_reviewer",
                "message": "Plan approved by user"
            })
            logger.info(f"{Colors.GREEN}✅ Plan approved by user{Colors.END}")
            add_span_event(span, "plan_approved", {"approved": True})
            log_node_complete("PlanReviewer")
            return {"text": "Plan approved", "approved": True}
        else:
            # User requested revision
            shared_state['plan_revision_requested'] = True
            shared_state['plan_feedback'] = user_feedback
            shared_state['plan_revision_count'] = revision_count + 1
            shared_state['history'].append({
                "agent": "plan_reviewer",
                "message": f"User feedback: {user_feedback}"
            })
            logger.info(f"{Colors.YELLOW}📝 Plan revision requested. Feedback: {user_feedback}{Colors.END}")
            add_span_event(span, "revision_requested", {"feedback": user_feedback, "new_revision_count": revision_count + 1})
            log_node_complete("PlanReviewer")
            return {"text": f"Revision requested: {user_feedback}", "approved": False, "feedback": user_feedback}


async def supervisor_node(task=None, **kwargs):
    """Supervisor node that decides which agent should act next."""
    log_node_start("Supervisor")
    global _global_node_states

    # task and kwargs parameters are unused - supervisor relies on global state
    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("supervisor") as span:  

        # Extract shared state from global storage
        shared_state = _global_node_states.get('shared', None)

        if not shared_state:
            logger.warning("No shared state found in global storage")
            return None, {"text": "No shared state available"}

        agent = strands_utils.get_agent(
            agent_name="supervisor",
            system_prompts=apply_prompt_template(prompt_name="supervisor", prompt_context={}),
            model_id=os.getenv("SUPERVISOR_MODEL_ID", os.getenv("DEFAULT_MODEL_ID")),
            enable_reasoning=False,
            prompt_cache_info=(True, "default"),  # enable prompt caching for reasoning agent
            tool_cache=True,
            tools=[coder_agent_custom_interpreter_tool, reporter_agent_custom_interpreter_tool, tracker_agent_tool, validator_agent_custom_interpreter_tool],  # Add coder, reporter, tracker and validator agents as tools
            streaming=True,
        )

        clues, full_plan, messages = shared_state.get("clues", ""), shared_state.get("full_plan", ""), shared_state["messages"]
        message_text = '\n\n'.join([messages[-1]["content"][-1]["text"], FULL_PLAN_FORMAT.format(full_plan), clues])

        # Create message with cache point for messages caching
        # This caches the large context (full_plan, clues) for cost savings
        # NOTE: Message cache disabled to avoid "maximum 4 cache_control blocks" error in multi-turn tool calls
        # message = [ContentBlock(text=message_text), ContentBlock(cachePoint={"type": "default"})]  # Cache point for messages caching
        message = [ContentBlock(text=message_text)]  # No cache point - system prompt cache only

        # Process streaming response and collect text in one pass
        full_text = ""
        async for event in strands_utils.process_streaming_response_yield(
            agent, message, agent_name="supervisor", source="supervisor_node"
        ):
            if event.get("event_type") == "text_chunk":
                full_text += event.get("data", "")
            # Accumulate token usage
            TokenTracker.accumulate(event, shared_state)
        response = {"text": full_text}

        # Update shared global state
        shared_state['history'].append({"agent":"supervisor", "message": response["text"]})

        # Add Event
        add_span_event(span, "input_message", {"message": str(message)})
        add_span_event(span, "response", {"response": str(response["text"])})

        log_node_complete("Supervisor")
        logger.info("Workflow completed")
        # Return response only
        return response
