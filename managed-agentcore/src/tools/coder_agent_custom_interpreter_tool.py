#!/usr/bin/env python3

import logging
import os
import asyncio
from typing import Any, Annotated
from strands.types.tools import ToolResult, ToolUse
from strands.tools.tools import PythonAgentTool
from strands.types.content import ContentBlock
from dotenv import load_dotenv
from src.utils.strands_sdk_utils import strands_utils
from src.prompts.template import apply_prompt_template
from src.utils.common_utils import get_message_from_string
from src.tools.custom_interpreter_write_and_execute_tool import custom_interpreter_write_and_execute_tool
from src.tools.custom_interpreter_bash_tool import custom_interpreter_bash_tool
from src.utils.strands_sdk_utils import TokenTracker

# Observability
from opentelemetry import trace
from src.utils.agentcore_observability import add_span_event

load_dotenv()

# Simple logger setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TOOL_SPEC = {
    "name": "coder_agent_custom_interpreter_tool",
    "description": "Execute Python code and bash commands using a specialized coder agent with custom code interpreter. This tool provides access to a coder agent that can execute Python code for data analysis and calculations, run bash commands for system operations, and handle complex programming tasks in isolated containers.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The coding task or question that needs to be executed by the coder agent."
                }
            },
            "required": ["task"]
        }
    }
}

RESPONSE_FORMAT = "Response from {}:\n\n<response>\n{}\n</response>\n\n*Please execute the next step.*"
FULL_PLAN_FORMAT = "Here is full plan :\n\n<full_plan>\n{}\n</full_plan>\n\n*Please consider this to select the next step.*"
CLUES_FORMAT = "Here is clues from {}:\n\n<clues>\n{}\n</clues>\n\n"

class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    END = '\033[0m'

def _handle_coder_agent_custom_interpreter_tool(task: Annotated[str, "The coding task or question that needs to be executed by the coder agent."]):
    """
    Execute Python code and bash commands using a specialized coder agent with custom code interpreter.

    This tool provides access to a coder agent that can:
    - Execute Python code for data analysis and calculations in isolated containers
    - Run bash commands for system operations in isolated environments
    - Handle complex programming tasks with automatic container lifecycle management

    Args:
        task: The coding task or question that needs to be executed

    Returns:
        The result of the code execution or analysis
    """
    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("coder_agent_custom_interpreter_tool") as span:
        print()  # Add newline before log
        logger.info(f"\n{Colors.GREEN}Coder Agent Custom Interpreter Tool starting task{Colors.END}")

        # Try to extract shared state from global storage
        from src.graph.nodes import _global_node_states
        shared_state = _global_node_states.get('shared', None)

        if not shared_state:
            logger.warning("No shared state found")
            add_span_event(span, "error", {"message": "No shared state available"})
            return "Error: No shared state available"

        request_prompt, full_plan = shared_state.get("request_prompt", ""), shared_state.get("full_plan", "")
        clues, messages = shared_state.get("clues", ""), shared_state.get("messages", [])

        # Check for data directory
        data_directory = shared_state.get("data_directory")

        # Fargate session creation with data
        from src.tools.global_fargate_coordinator import get_global_session
        fargate_manager = get_global_session()

        if data_directory:
            # Directory upload (recursive)
            logger.info(f"{Colors.GREEN}📂 Creating custom interpreter session with directory data: {data_directory}{Colors.END}")
            if not fargate_manager.ensure_session_with_directory(data_directory):
                return "Error: Failed to create custom interpreter session with directory data"
        else:
            # No data to upload
            logger.info(f"{Colors.GREEN}📦 Creating standard custom interpreter session (no data){Colors.END}")
            if not fargate_manager.ensure_session():
                return "Error: Failed to create custom interpreter session"

        # Create coder agent with custom interpreter tools using consistent pattern
        coder_agent = strands_utils.get_agent(
            agent_name="coder",
            system_prompts=apply_prompt_template(prompt_name="coder", prompt_context={"USER_REQUEST": request_prompt, "FULL_PLAN": full_plan}),
            model_id=os.getenv("CODER_MODEL_ID", os.getenv("DEFAULT_MODEL_ID")),
            enable_reasoning=False,
            prompt_cache_info=(True, "default"),  # reasoning agent uses prompt caching
            tool_cache=True,
            tools=[custom_interpreter_write_and_execute_tool, custom_interpreter_bash_tool],
            streaming=True  # Enable streaming for consistency
        )

        # Prepare message with context if available
        message = '\n\n'.join([messages[-1]["content"][-1]["text"], clues])

        # Create message with cache point for messages caching
        # This caches the large context (clues) for cost savings
        message = [ContentBlock(text=message), ContentBlock(cachePoint={"type": "default"})]  # Cache point for messages caching

        # Process streaming response and collect text in one pass
        async def process_coder_stream():
            full_text = ""
            async for event in strands_utils.process_streaming_response_yield(
                coder_agent, message, agent_name="coder", source="coder_tool"
            ):
                if event.get("event_type") == "text_chunk":
                    full_text += event.get("data", "")
                # Accumulate token usage
                TokenTracker.accumulate(event, shared_state)
            return {"text": full_text}

        response = asyncio.run(process_coder_stream())
        result_text = response['text']

        # Update clues
        clues = '\n\n'.join([clues, CLUES_FORMAT.format("coder", response["text"])])

        # Update history
        history = shared_state.get("history", [])
        history.append({"agent":"coder", "message": response["text"]})

        # Update shared state
        shared_state['messages'] = [get_message_from_string(role="user", string=RESPONSE_FORMAT.format("coder", response["text"]), imgs=[])]
        shared_state['clues'] = clues
        shared_state['history'] = history

        logger.info(f"\n{Colors.GREEN}Coder Agent Custom Interpreter Tool completed successfully{Colors.END}")
        # Print token usage using TokenTracker
        TokenTracker.print_current(shared_state)

        # Add Event
        add_span_event(span, "input_message", {"message": str(message)})
        add_span_event(span, "response", {"response": str(response["text"])})

        return result_text

# Function name must match tool name
def _coder_agent_custom_interpreter_tool(tool: ToolUse, **_kwargs: Any) -> ToolResult:
    tool_use_id = tool["toolUseId"]
    task = tool["input"]["task"]

    # Use the existing handle_coder_agent_custom_interpreter_tool function
    result = _handle_coder_agent_custom_interpreter_tool(task)

    # Check if execution was successful based on the result string
    if "Error in coder agent tool" in result or "Error: " in result:
        return {
            "toolUseId": tool_use_id,
            "status": "error",
            "content": [{"text": result}]
        }
    else:
        return {
            "toolUseId": tool_use_id,
            "status": "success",
            "content": [{"text": result}]
        }

# Wrap with PythonAgentTool for proper Strands SDK registration
coder_agent_custom_interpreter_tool = PythonAgentTool("coder_agent_custom_interpreter_tool", TOOL_SPEC, _coder_agent_custom_interpreter_tool)
