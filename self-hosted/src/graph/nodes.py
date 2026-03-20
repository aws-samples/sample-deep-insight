import logging
import os
from dotenv import load_dotenv
from strands.types.content import ContentBlock
from src.utils.strands_sdk_utils import strands_utils, TokenTracker
from src.prompts.template import apply_prompt_template
from src.utils.common_utils import get_message_from_string

# Load environment variables
load_dotenv()

# Tools - import PythonAgentTool instances directly
from src.tools.coder_agent_tool import coder_agent_tool
from src.tools.reporter_agent_tool import reporter_agent_tool
from src.tools.tracker_agent_tool import tracker_agent_tool
from src.tools.validator_agent_tool import validator_agent_tool

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

# Maximum characters for clues passed to Supervisor.
# Each agent appends its full response to clues, causing unbounded growth.
# Truncating to the most recent entries prevents Bedrock token limit issues.
MAX_CLUES_CHARS = int(os.getenv("MAX_CLUES_CHARS", "8000"))

def _truncate_clues(clues: str) -> str:
    """Keep only the most recent clues within MAX_CLUES_CHARS.

    Preserves complete <clues>...</clues> blocks from the end.
    This prevents Supervisor's context from growing unboundedly
    while retaining the latest status from each agent.
    """
    if len(clues) <= MAX_CLUES_CHARS:
        return clues

    # Find clues blocks and keep the most recent ones that fit
    import re
    blocks = re.findall(r'Here is (?:clues from \w+|updated tracking status):\n\n<(?:clues|tracking_clues)>.*?</(?:clues|tracking_clues)>', clues, re.DOTALL)

    if not blocks:
        # No structured blocks found, just keep the tail
        return "...(truncated)\n\n" + clues[-MAX_CLUES_CHARS:]

    # Build from the most recent blocks
    result_blocks = []
    total_len = 0
    for block in reversed(blocks):
        if total_len + len(block) > MAX_CLUES_CHARS and result_blocks:
            break
        result_blocks.insert(0, block)
        total_len += len(block)

    return "...(earlier clues truncated)\n\n" + "\n\n".join(result_blocks)

def should_handoff_to_planner(_):
    """Check if coordinator requested handoff to planner."""

    # Check coordinator's response for handoff request
    global _global_node_states
    shared_state = _global_node_states.get('shared', {})
    history = shared_state.get('history', [])

    # Look for coordinator's last message
    for entry in reversed(history):
        if entry.get('agent') == 'coordinator':
            message = entry.get('message', '')
            return 'handoff_to_planner' in message

    return False


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
    result = _check_plan_revision_state()
    logger.info(f"should_revise_plan: {result}")
    return result


def should_proceed_to_supervisor(_):
    """Check if plan was approved and should proceed to supervisor.

    Note: This is the logical negation of should_revise_plan. Both conditions are needed
    because Strands SDK evaluates all edges and marks destination nodes as "ready"
    if their incoming edge conditions are satisfied.
    """
    result = not _check_plan_revision_state()
    logger.info(f"should_proceed_to_supervisor: {result}")
    return result

async def coordinator_node(task=None, **kwargs):
    
    """Coordinator node that communicate with customers."""
    global _global_node_states

    log_node_start("Coordinator")

    # Extract user request from task (now passed as dictionary)
    if isinstance(task, dict):
        request = task.get("request", "")
        request_prompt = task.get("request_prompt", request)
    else:
        request = str(task) if task else ""
        request_prompt = request

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

    # Build and update history
    if 'history' not in shared_state: 
        shared_state['history'] = []
    shared_state['history'].append({"agent":"coordinator", "message": response["text"]})

    log_node_complete("Coordinator")
    # Return response only
    return response

async def planner_node(task=None, **kwargs):

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

    # Check if this is a revision request
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

    log_node_complete("Planner")
    # Return response only
    return response


# Plan feedback configuration
MAX_PLAN_REVISIONS = int(os.getenv("MAX_PLAN_REVISIONS", "10"))

# Plugin callback for web mode — set by web/app.py, None in CLI mode
_plan_review_callback = None

async def plan_reviewer_node(task=None, **kwargs):
    """
    Plan reviewer node that allows user to review and provide feedback on the generated plan.

    This node:
    1. Displays the generated plan to the user
    2. Asks for approval or feedback
    3. If feedback provided and revisions remaining, triggers re-planning
    4. If approved or max revisions reached, proceeds to supervisor
    """
    log_node_start("PlanReviewer")
    global _global_node_states

    shared_state = _global_node_states.get('shared', {})

    if not shared_state:
        logger.warning("No shared state found in global storage")
        return {"text": "No shared state available"}

    # Get current plan and revision count
    full_plan = shared_state.get('full_plan', '')
    revision_count = shared_state.get('plan_revision_count', 0)

    # Reset revision flag at start
    shared_state['plan_revision_requested'] = False

    # Check if we've exceeded max revisions - auto-approve
    if revision_count >= MAX_PLAN_REVISIONS:
        logger.info(f"{Colors.YELLOW}Max revisions ({MAX_PLAN_REVISIONS}) reached. Auto-approving plan.{Colors.END}")
        shared_state['history'].append({
            "agent": "plan_reviewer",
            "message": f"Plan auto-approved (max {MAX_PLAN_REVISIONS} revisions reached)"
        })
        log_node_complete("PlanReviewer")
        return {"text": "Plan auto-approved after max revisions", "approved": True}

    # Web mode: delegate to async callback if registered
    if _plan_review_callback is not None:
        approved, user_input = await _plan_review_callback(
            full_plan=full_plan,
            revision_count=revision_count,
            max_revisions=MAX_PLAN_REVISIONS,
        )
        if approved:
            user_input = "yes"
    else:
        # CLI mode: display plan and ask for user input
        print(f"\n{Colors.CYAN}{'='*60}{Colors.END}")
        print(f"{Colors.CYAN}📋 PLAN REVIEW (Revision {revision_count}/{MAX_PLAN_REVISIONS}){Colors.END}")
        print(f"{Colors.CYAN}{'='*60}{Colors.END}")
        print(f"\n{full_plan}\n")
        print(f"{Colors.CYAN}{'='*60}{Colors.END}")

        print(f"\n{Colors.YELLOW}Please review the plan above.{Colors.END}")
        print(f"  - Press {Colors.GREEN}Enter{Colors.END} or type '{Colors.GREEN}yes{Colors.END}' to approve and proceed")
        print(f"  - Type your {Colors.YELLOW}feedback{Colors.END} to request revisions ({MAX_PLAN_REVISIONS - revision_count} revision(s) remaining)")
        print()

        try:
            import readline  # noqa: F401
            user_input = input("Your response: ").strip()
        except EOFError:
            user_input = "yes"

    # Process user response
    if user_input.lower() in ['', 'yes', 'y', 'approve', 'ok', 'proceed']:
        # User approved the plan - plan_revision_requested stays False (set above)
        shared_state['history'].append({
            "agent": "plan_reviewer",
            "message": "Plan approved by user"
        })
        logger.info(f"{Colors.GREEN}Plan approved by user{Colors.END}")
        log_node_complete("PlanReviewer")
        return {"text": "Plan approved", "approved": True}
    else:
        # User provided feedback - request revision
        shared_state['plan_revision_requested'] = True
        shared_state['plan_feedback'] = user_input
        shared_state['plan_revision_count'] = revision_count + 1
        shared_state['history'].append({
            "agent": "plan_reviewer",
            "message": f"User feedback: {user_input}"
        })
        logger.info(f"{Colors.YELLOW}Plan revision requested. Feedback: {user_input}{Colors.END}")
        log_node_complete("PlanReviewer")
        return {"text": f"Revision requested: {user_input}", "approved": False, "feedback": user_input}


async def supervisor_node(task=None, **kwargs):
    """Supervisor node that decides which agent should act next."""
    log_node_start("Supervisor")
    global _global_node_states

    # task and kwargs parameters are unused - supervisor relies on global state
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
        tools=[coder_agent_tool, reporter_agent_tool, tracker_agent_tool, validator_agent_tool],  # Add coder, reporter, tracker and validator agents as tools
        streaming=True,
    )

    clues, full_plan, messages = shared_state.get("clues", ""), shared_state.get("full_plan", ""), shared_state["messages"]
    truncated_clues = _truncate_clues(clues)
    if len(clues) != len(truncated_clues):
        logger.info(f"Clues truncated: {len(clues)} -> {len(truncated_clues)} chars")
    message_text = '\n\n'.join([messages[-1]["content"][-1]["text"], FULL_PLAN_FORMAT.format(full_plan), truncated_clues])

    # Create message with cache point for messages caching
    # This caches the large context (full_plan, clues) for cost savings
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

    log_node_complete("Supervisor")
    logger.info("Workflow completed")
    # Return response only
    return response
