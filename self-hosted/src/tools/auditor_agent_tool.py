import logging
import os
import asyncio
from typing import Any, Annotated
from strands.types.tools import ToolResult, ToolUse
from strands.tools.tools import PythonAgentTool
from strands.types.content import ContentBlock
from dotenv import load_dotenv
from src.utils.strands_sdk_utils import strands_utils
from src.prompts.template import apply_prompt_template, filter_plan_for_agent
from src.utils.common_utils import get_message_from_string
from src.utils.strands_sdk_utils import TokenTracker

from src.tools.bash_tool import bash_tool
from src.tools.write_and_execute_tool import write_and_execute_tool
from strands_tools import file_read

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Colors:
    GREEN = '\033[92m'
    CYAN = '\033[96m'
    END = '\033[0m'


TOOL_SPEC = {
    "name": "auditor_agent_tool",
    "description": (
        "Audit a finalized DOCX report for citation defects (DeepTRACE Type A/B/C/D) "
        "and emit a verdict (PASS / RETRY / NEEDS_REVIEW). This tool runs AFTER the "
        "Reporter agent produces final_report_with_citations.docx. It performs "
        "independent, read-only verification — it never modifies the DOCX, "
        "citations.json, or calculation_metadata.json. Use it to catch marker-value "
        "mismatches, unsupported claims, undefined markers, and incomplete citation "
        "chains before publication."
    ),
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "The audit task description (e.g., 'Audit the final report "
                        "for citation defects and emit a verdict')."
                    )
                }
            },
            "required": ["task"]
        }
    }
}

RESPONSE_FORMAT = "Response from {}:\n\n<response>\n{}\n</response>\n\n*Please execute the next step.*"
CLUES_FORMAT = "Here is clues from {}:\n\n<clues>\n{}\n</clues>\n\n"


def _handle_auditor_agent_tool(_task: Annotated[str, "The audit task description."]):
    """
    Run independent audit of the finalized report and emit a verdict.

    This tool provides access to an Auditor agent that:
    - Reads final_report_with_citations.docx (READ-ONLY)
    - Cross-checks body numeric claims against citations.json and
      calculation_metadata.json using the DeepTRACE 4-type taxonomy
    - Produces audit_findings.json + audit_report.txt
    - Emits verdict: PASS | RETRY | NEEDS_REVIEW

    Args:
        task: The audit task description.

    Returns:
        The audit summary (verdict + stats + top findings).
    """
    print()  # newline before log
    logger.info(f"\n{Colors.GREEN}Auditor Agent Tool starting{Colors.END}")

    from src.graph.nodes import _global_node_states
    shared_state = _global_node_states.get('shared', None)

    if not shared_state:
        logger.warning("No shared state found")
        return "Error: No shared state available"

    request_prompt = shared_state.get("request_prompt", "")
    full_plan = shared_state.get("full_plan", "")
    clues = shared_state.get("clues", "")
    messages = shared_state.get("messages", [])

    # Filter plan to only show Auditor tasks (keep prompt focused)
    auditor_plan = filter_plan_for_agent(full_plan, "auditor")

    # Create auditor agent — Sonnet by default (semantic verdict judgment needed
    # on top of deterministic audit_engine checks).
    auditor_agent = strands_utils.get_agent(
        agent_name="auditor",
        system_prompts=apply_prompt_template(
            prompt_name="auditor",
            prompt_context={"USER_REQUEST": request_prompt, "FULL_PLAN": auditor_plan}
        ),
        model_id=os.getenv("AUDITOR_MODEL_ID", os.getenv("DEFAULT_MODEL_ID")),
        enable_reasoning=False,
        # auditor is re-invoked across retry passes (verdict=RETRY) — cache the
        # system prompt + tool specs like reporter, not validator (single-shot)
        prompt_cache_info=(True, "default"),
        tool_cache=True,
        tools=[write_and_execute_tool, bash_tool, file_read],
        streaming=True
    )

    # Prepare message with accumulated clues (Coder + Validator + Reporter outputs)
    message = '\n\n'.join([messages[-1]["content"][-1]["text"], clues])
    message = [
        ContentBlock(text=message),
        ContentBlock(cachePoint={"type": "default"})  # cache the long clues context
    ]

    async def process_auditor_stream():
        full_text = ""
        async for event in strands_utils.process_streaming_response_yield(
            auditor_agent, message, agent_name="auditor", source="auditor_tool"
        ):
            if event.get("event_type") == "text_chunk":
                full_text += event.get("data", "")
            TokenTracker.accumulate(event, shared_state)

        return auditor_agent, {"text": full_text}

    auditor_agent, response = asyncio.run(process_auditor_stream())
    result_text = response['text']

    # Update clues
    clues = '\n\n'.join([clues, CLUES_FORMAT.format("auditor", response["text"])])

    # Update history
    history = shared_state.get("history", [])
    history.append({"agent": "auditor", "message": response["text"]})

    # Update shared state
    shared_state['messages'] = [
        get_message_from_string(
            role="user",
            string=RESPONSE_FORMAT.format("auditor", response["text"]),
            imgs=[]
        )
    ]
    shared_state['clues'] = clues
    shared_state['history'] = history

    logger.info(f"\n{Colors.GREEN}Auditor Agent Tool completed{Colors.END}")
    TokenTracker.print_current(shared_state)
    return result_text


def _auditor_agent_tool(tool: ToolUse, **_kwargs: Any) -> ToolResult:
    tool_use_id = tool["toolUseId"]
    task = tool["input"]["task"]

    result = _handle_auditor_agent_tool(task)

    if "Error: " in result:
        return {
            "toolUseId": tool_use_id,
            "status": "error",
            "content": [{"text": result}]
        }
    return {
        "toolUseId": tool_use_id,
        "status": "success",
        "content": [{"text": result}]
    }


# Wrap with PythonAgentTool for proper Strands SDK registration
auditor_agent_tool = PythonAgentTool("auditor_agent_tool", TOOL_SPEC, _auditor_agent_tool)
