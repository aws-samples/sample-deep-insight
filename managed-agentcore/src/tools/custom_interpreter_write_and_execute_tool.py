#!/usr/bin/env python3

import os
import logging
import base64
from typing import Any, Annotated
from strands.types.tools import ToolResult, ToolUse
from strands.tools.tools import PythonAgentTool
from src.tools.decorators import log_io
from src.tools.global_fargate_coordinator import get_global_session

# Observability
from opentelemetry import trace
from src.utils.agentcore_observability import add_span_event

# Simple logger setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TOOL_SPEC = {
    "name": "custom_interpreter_write_and_execute_tool",
    "description": "Write a Python script to a file and immediately execute it in a single operation. This is the most efficient way to run Python code - it combines file writing and execution into one network request. Use this instead of separate write_file + bash calls.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path where the script should be written (e.g., './artifacts/code/analysis.py')"
                },
                "content": {
                    "type": "string",
                    "description": "The Python script content to write and execute"
                },
                "execute_cmd": {
                    "type": "string",
                    "description": "Optional: The bash command to execute the script. If not provided, defaults to 'python {file_path}'"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds for script execution (default: 300)",
                    "default": 300
                }
            },
            "required": ["file_path", "content"]
        }
    }
}

class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

@log_io
def _handle_custom_interpreter_write_and_execute_tool(
    file_path: Annotated[str, "The path where the script should be written"],
    content: Annotated[str, "The Python script content to write and execute"],
    execute_cmd: Annotated[str, "The bash command to execute the script"] = None,
    timeout: Annotated[int, "Timeout in seconds for script execution"] = 300
):
    """Write a Python script to a file and immediately execute it.

    Two-phase execution to avoid GIL blocking issues:
    - Phase 1: Write file using simple exec() (fast, no subprocess)
    - Phase 2: Execute command using BASH: prefix (subprocess with timeout)
    """

    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("custom_interpreter_write_and_execute_tool") as span:
        print()  # Add newline before log
        logger.info(f"\n{Colors.GREEN}[Write & Execute] Writing to: {file_path}{Colors.END}")

        results = []

        # Default execute_cmd if not provided
        if not execute_cmd:
            execute_cmd = f"python {file_path}"

        try:
            # Get global session manager
            session_manager = get_global_session()

            # Base64 encode content for safe transmission (handles all special characters)
            content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')

            # ===== PHASE 1: Write file (simple exec, no subprocess) =====
            write_code = f'''import os
import base64

file_path = "{file_path}"
dir_path = os.path.dirname(file_path)
if dir_path:
    os.makedirs(dir_path, exist_ok=True)

# Decode base64 content
content_b64 = "{content_b64}"
content = base64.b64decode(content_b64).decode('utf-8')

# Write content to file
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

file_size = os.path.getsize(file_path)
num_lines = len(content.split('\\n'))
print(f"{{num_lines}}|{{file_size}}")
'''

            logger.info(f"{Colors.BLUE}[PHASE 1] Writing file: {file_path}{Colors.END}")
            write_result = session_manager.execute_code(write_code, f"Write: {file_path}")

            # Check write result
            if write_result.get('error'):
                error_msg = f"✗ Error writing file: {write_result['error']}"
                logger.error(f"{Colors.RED}{error_msg}{Colors.END}")
                add_span_event(span, "file_path", {"path": str(file_path)})
                add_span_event(span, "error", {"response": str(write_result['error'])})
                return error_msg

            # Parse write output to get num_lines and file_size
            write_stdout = write_result.get('stdout', '').strip()
            try:
                num_lines, file_size = write_stdout.split('|')
                num_lines = int(num_lines)
                file_size = int(file_size)
            except:
                num_lines = len(content.split('\n'))
                file_size = len(content.encode('utf-8'))

            write_msg = f"✓ Written {num_lines} lines ({file_size} bytes) to {file_path}"
            logger.info(f"{Colors.GREEN}{write_msg}{Colors.END}")
            results.append(write_msg)

            # ===== PHASE 2: Execute command using BASH: prefix =====
            # BASH: prefix uses subprocess.run with timeout, avoiding GIL issues
            # Add timeout to the command using 'timeout' utility
            if timeout and timeout > 30:
                bash_code = f"BASH: timeout {timeout} {execute_cmd}"
            else:
                bash_code = f"BASH: {execute_cmd}"

            logger.info(f"\n{Colors.GREEN}[Write & Execute] Executing: {execute_cmd}{Colors.END}")
            exec_result = session_manager.execute_code(bash_code, f"Execute: {execute_cmd}")

            # Get outputs
            exec_stdout = exec_result.get('stdout', '').strip()
            exec_stderr = exec_result.get('stderr', '').strip()

            # Handle execution errors
            if exec_result.get('error'):
                error_msg = f"✗ Execution failed: {exec_result['error']}"
                logger.error(f"{Colors.RED}{error_msg}{Colors.END}")
                results.append(error_msg)
                if exec_stdout:
                    results.append(f"Stdout: {exec_stdout}")
                if exec_stderr:
                    results.append(f"Stderr: {exec_stderr}")

                add_span_event(span, "file_path", {"path": str(file_path)})
                add_span_event(span, "execute_cmd", {"cmd": str(execute_cmd)})
                add_span_event(span, "error", {"response": str(exec_result['error'])})

                return "\n".join(results)

            # Success case
            exec_msg = "✓ Execution successful"
            logger.info(f"{Colors.GREEN}{exec_msg}{Colors.END}")
            results.append(exec_msg)

            # Include stdout if present
            if exec_stdout:
                results.append(f"Output:\n{exec_stdout}")
                # Log full output for CloudWatch
                logger.info(f"[TOOL OUTPUT] {file_path}\n{exec_stdout}")

            # Include stderr if present (warnings, etc.)
            if exec_stderr:
                results.append(f"Stderr:\n{exec_stderr}")

            logger.info(f"{Colors.GREEN}[Write & Execute] Success: {file_path}{Colors.END}")

            # Truncate content for telemetry
            content_lines = content.split('\n')
            if len(content_lines) > 7:
                content_preview = '\n'.join(content_lines[:7])
                content_summary = f"{content_preview}\n... ({len(content_lines) - 7} more lines omitted)"
            else:
                content_summary = content

            # Add Event
            add_span_event(span, "file_path", {"path": str(file_path)})
            add_span_event(span, "execute_cmd", {"cmd": str(execute_cmd)})
            add_span_event(span, "content_preview", {"content": str(content_summary)})
            add_span_event(span, "result", {"response": str(exec_stdout)})

            return "\n".join(results)

        except Exception as e:
            error_msg = f"✗ Error executing script: {repr(e)}"
            logger.error(f"{Colors.RED}{error_msg}{Colors.END}")
            results.append(error_msg)

            # Add Event
            add_span_event(span, "file_path", {"path": str(file_path)})
            add_span_event(span, "execute_cmd", {"cmd": str(execute_cmd) if execute_cmd else 'N/A'})
            add_span_event(span, "error", {"response": repr(e)})

            return "\n".join(results)

# Function name must match tool name
def _custom_interpreter_write_and_execute_tool(tool: ToolUse, **_kwargs: Any) -> ToolResult:
    tool_use_id = tool["toolUseId"]
    file_path = tool["input"]["file_path"]
    content = tool["input"]["content"]
    execute_cmd = tool["input"].get("execute_cmd")  # Optional, defaults to None
    timeout = tool["input"].get("timeout", 300)

    # Use the existing handle function
    result = _handle_custom_interpreter_write_and_execute_tool(file_path, content, execute_cmd, timeout)

    # Check if execution had errors (same as write_and_execute_tool.py)
    if "✗ Error" in result or "✗ Execution failed" in result or "✗ Execution timed out" in result:
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
custom_interpreter_write_and_execute_tool = PythonAgentTool("custom_interpreter_write_and_execute_tool", TOOL_SPEC, _custom_interpreter_write_and_execute_tool)

if __name__ == "__main__":
    # Test example
    test_code = '''
print("Hello from write_and_execute!")
import sys
print(f"Python version: {sys.version}")
'''
    print(_handle_custom_interpreter_write_and_execute_tool(
        "./artifacts/test_script.py",
        test_code
    ))
