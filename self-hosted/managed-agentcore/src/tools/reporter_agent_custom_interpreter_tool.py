#!/usr/bin/env python3

import logging
import os
import asyncio
from typing import Any, Annotated
from strands.types.tools import ToolResult, ToolUse
from strands.types.content import ContentBlock
from dotenv import load_dotenv
from src.utils.strands_sdk_utils import strands_utils
from src.prompts.template import apply_prompt_template
from src.utils.common_utils import get_message_from_string
from src.tools import custom_interpreter_python_tool, custom_interpreter_bash_tool
from src.utils.strands_sdk_utils import TokenTracker

# Observability
from opentelemetry import trace
from src.utils.agentcore_observability import add_span_event

load_dotenv()

# Simple logger setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TOOL_SPEC = {
    "name": "reporter_agent_custom_interpreter_tool",
    "description": "Generate comprehensive reports based on analysis results using a specialized reporter agent with custom code interpreter. This tool provides access to a reporter agent that can read analysis results from artifacts, create structured reports with visualizations, and generate output in multiple formats (HTML, PDF, Markdown) in isolated containers.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The reporting task or instruction for generating the report (e.g., 'Create a comprehensive analysis report', 'Generate PDF report with all findings')."
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
    CYAN = '\033[96m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def handle_reporter_agent_custom_interpreter_tool(task: Annotated[str, "The reporting task or instruction for generating the report."]):
    """
    Generate comprehensive reports based on analysis results using a specialized reporter agent with custom code interpreter.

    This tool provides access to a reporter agent that can:
    - Read analysis results from artifacts directory in isolated containers
    - Create structured reports with executive summaries, key findings, and detailed analysis
    - Generate reports in multiple formats (HTML, PDF, Markdown) with automatic S3 upload
    - Include visualizations and charts in reports using isolated environments
    - Process accumulated analysis results from all_results.txt

    Args:
        task: The reporting task or instruction for generating the report

    Returns:
        The generated report content and confirmation of file creation
    """
    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("reporter_agent_custom_interpreter_tool") as span:
        print()  # Add newline before log
        logger.info(f"\n{Colors.GREEN}Reporter Agent Custom Interpreter Tool starting task{Colors.END}")
        logger.info(f"{Colors.BLUE}🚀 Using custom code interpreter for isolated report generation{Colors.END}")

        # Try to extract shared state from global storage
        from src.graph.nodes import _global_node_states
        shared_state = _global_node_states.get('shared', None)

        if not shared_state:
            logger.warning("No shared state found")
            add_span_event(span, "error", {"message": "No shared state available"})
            return "Error: No shared state available"

        request_prompt, full_plan = shared_state.get("request_prompt", ""), shared_state.get("full_plan", "")
        clues, messages = shared_state.get("clues", ""), shared_state.get("messages", [])

        # Create reporter agent with custom interpreter tools using consistent pattern
        logger.info(f"{Colors.BLUE}📦 Creating reporter agent with custom interpreter tools{Colors.END}")
        reporter_agent = strands_utils.get_agent(
            agent_name="reporter",  # 기존 이름 유지
            system_prompts=apply_prompt_template(
                prompt_name="reporter",
                prompt_context={
                    "USER_REQUEST": request_prompt,
                    "FULL_PLAN": full_plan,
                    "EXECUTION_ENVIRONMENT": "Custom code interpreter (isolated containers with automatic S3 upload for PDFs and charts)"
                }
            ),
            model_id=os.getenv("REPORTER_MODEL_ID", os.getenv("DEFAULT_MODEL_ID")),
            enable_reasoning=False,
            prompt_cache_info=(True, "default"),  # enable prompt caching for reporter agent
            tool_cache=True,
            tools=[custom_interpreter_python_tool, custom_interpreter_bash_tool],  # Custom interpreter tools
            streaming=True  # Enable streaming for consistency
        )

        # Prepare message with context if available
        message = '\n\n'.join([messages[-1]["content"][-1]["text"], clues])

        # Create message with cache point for messages caching
        # This caches the large context (clues) for cost savings
        message_with_cache = [ContentBlock(text=message), ContentBlock(cachePoint={"type": "default"})]  # Cache point for messages caching

        # Process streaming response and collect text in one pass
        async def process_reporter_stream():
            full_text = ""
            logger.info(f"{Colors.BLUE}🔄 Processing reporter agent with custom interpreter backend{Colors.END}")
            async for event in strands_utils.process_streaming_response_yield(
                reporter_agent, message_with_cache, agent_name="reporter", source="reporter_custom_interpreter_tool"
            ):
                if event.get("event_type") == "text_chunk":
                    full_text += event.get("data", "")
                # Accumulate token usage
                TokenTracker.accumulate(event, shared_state)
            return {"text": full_text}

        response = asyncio.run(process_reporter_stream())
        result_text = response['text']

        # Update clues
        clues = '\n\n'.join([clues, CLUES_FORMAT.format("reporter", response["text"])])

        # Update history
        history = shared_state.get("history", [])
        history.append({"agent":"reporter", "message": response["text"]})

        # Update shared state
        shared_state['messages'] = [get_message_from_string(
            role="user",
            string=RESPONSE_FORMAT.format("reporter", response["text"]),
            imgs=[]
        )]
        shared_state['clues'] = clues
        shared_state['history'] = history

        logger.info(f"\n{Colors.GREEN}Reporter Agent Custom Interpreter Tool completed successfully{Colors.END}")
        logger.info(f"{Colors.BLUE}✅ Reports generated in isolated custom interpreter environment{Colors.END}")
        # Print token usage using TokenTracker
        TokenTracker.print_current(shared_state)

        # Add Event
        add_span_event(span, "input_message", {"message": str(message)})
        add_span_event(span, "response", {"response": str(response["text"])})
        add_span_event(span, "execution_environment", {"environment": "Custom code interpreter"})

        return result_text

# Function name must match tool name
def reporter_agent_custom_interpreter_tool(tool: ToolUse, **_kwargs: Any) -> ToolResult:
    tool_use_id = tool["toolUseId"]
    task = tool["input"]["task"]

    # Use the existing handle_reporter_agent_custom_interpreter_tool function
    result = handle_reporter_agent_custom_interpreter_tool(task)

    # Check if execution was successful based on the result string
    if "Error in reporter agent tool" in result or "Error: No shared state available" in result:
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

