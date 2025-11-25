#!/usr/bin/env python3

import os
import logging
from typing import Any, Annotated
from strands.types.tools import ToolResult, ToolUse
from src.tools.decorators import log_io
from src.tools.global_fargate_coordinator import get_global_session

# Observability
from opentelemetry import trace
from src.utils.agentcore_observability import add_span_event

# Simple logger setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TOOL_SPEC = {
    "name": "custom_interpreter_bash_tool",
    "description": "Use this to execute bash command and do necessary operations using custom code interpreter.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "The bash command to be executed."
                }
            },
            "required": ["cmd"]
        }
    }
}

class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'

@log_io
def handle_custom_interpreter_bash_tool(cmd: Annotated[str, "The bash command to be executed."]):
    """Use this to execute bash command and do necessary operations using custom code interpreter."""

    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("custom_interpreter_bash_tool") as span:
        print()  # Add newline before log
        logger.info(f"\n{Colors.GREEN}Executing Bash in custom interpreter: {cmd}{Colors.END}")

        try:
            # 글로벌 세션 매니저를 통해 Fargate에서 실행
            session_manager = get_global_session()

            # BASH: 접두사를 추가하여 Bash 명령어로 인식시킴
            bash_code = f"BASH: {cmd}"

            # 코드 실행
            result = session_manager.execute_code(bash_code, f"Bash: {cmd}")

            # 에러 처리
            if result.get('error'):
                error_message = f"Command failed with error: {result['error']}"
                logger.error(f"{Colors.RED}Command failed: {result['error']}{Colors.END}")

                # Add Event
                add_span_event(span, "command", {"cmd": str(cmd)})
                add_span_event(span, "error", {"response": str(result['error'])})

                return error_message

            # 성공적으로 실행된 경우
            stdout = result.get('stdout', '')

            # 기존 인터페이스와 동일한 형식으로 반환
            results = "||".join([cmd, stdout])

            logger.info(f"{Colors.GREEN}===== Bash command execution successful in custom interpreter ====={Colors.END}")
            logger.info(f"{Colors.GREEN}===== Command in custom interpreter ====={Colors.END}{str(cmd)}")
            logger.info(f"{Colors.YELLOW}===== Result in custom interpreter ====={Colors.END}{str(stdout)}")

            # Add Event
            add_span_event(span, "command", {"cmd": str(cmd)})
            add_span_event(span, "result", {"response": str(stdout)})

            return results + "\n"

        except Exception as e:
            # Catch any other exceptions
            error_message = f"Error executing command: {str(e)}"
            logger.error(f"{Colors.RED}Error: {str(e)}{Colors.END}")

            # Add Event
            add_span_event(span, "command", {"cmd": str(cmd)})
            add_span_event(span, "error", {"response": repr(e)})

            return error_message

# Function name must match tool name
def custom_interpreter_bash_tool(tool: ToolUse, **_kwargs: Any) -> ToolResult:
    tool_use_id = tool["toolUseId"]
    cmd = tool["input"]["cmd"]

    # Use the existing handle_custom_interpreter_bash_tool function
    result = handle_custom_interpreter_bash_tool(cmd)

    # Check if execution was successful based on the result string
    if "Command failed" in result or "Error executing command" in result:
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

if __name__ == "__main__":
    # Test example using the handle_custom_interpreter_bash_tool function directly
    print(handle_custom_interpreter_bash_tool("ls -la"))