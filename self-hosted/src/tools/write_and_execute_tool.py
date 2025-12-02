import os
import logging
import subprocess
from typing import Any, Annotated
from strands.types.tools import ToolResult, ToolUse
from strands.tools.tools import PythonAgentTool
from src.tools.decorators import log_io

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

TOOL_SPEC = {
    "name": "write_and_execute_tool",
    "description": "Write a Python script to a file and immediately execute it. This is more efficient than calling write_file_tool and bash_tool separately. Use this when you need to create and run a Python script in one step.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path where the Python script should be written (e.g., './artifacts/code/analysis.py')"
                },
                "content": {
                    "type": "string",
                    "description": "The Python code content to write to the file"
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
    BOLD = '\033[1m'
    END = '\033[0m'


@log_io
def _handle_write_and_execute_tool(
    file_path: Annotated[str, "The path where the Python script should be written"],
    content: Annotated[str, "The Python code content to write to the file"],
    timeout: Annotated[int, "Timeout in seconds for script execution"] = 300
):
    """Write a Python script to a file and immediately execute it."""

    print()  # Add newline before log
    logger.info(f"\n{Colors.GREEN}[Write & Execute] Writing to: {file_path}{Colors.END}")

    results = []

    # Step 1: Write the file
    try:
        # Create directory if it doesn't exist
        dir_path = os.path.dirname(file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        # Write content to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Get file info
        file_size = os.path.getsize(file_path)
        num_lines = len(content.split('\n'))

        write_result = f"✓ Written {num_lines} lines ({file_size} bytes) to {file_path}"
        logger.info(f"{Colors.GREEN}{write_result}{Colors.END}")
        results.append(write_result)

    except Exception as e:
        error_msg = f"✗ Error writing file: {str(e)}"
        logger.error(f"{Colors.RED}{error_msg}{Colors.END}")
        return error_msg

    # Step 2: Execute the Python script
    cmd = f"python {file_path}"
    logger.info(f"\n{Colors.GREEN}[Write & Execute] Executing: {cmd}{Colors.END}")

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout
        )

        exec_result = f"✓ Execution successful"
        logger.info(f"{Colors.GREEN}{exec_result}{Colors.END}")
        results.append(exec_result)

        # Include stdout if present
        if result.stdout.strip():
            results.append(f"Output:\n{result.stdout}")

        # Include stderr if present (warnings, etc.)
        if result.stderr.strip():
            results.append(f"Stderr:\n{result.stderr}")

    except subprocess.TimeoutExpired:
        error_msg = f"✗ Execution timed out after {timeout} seconds"
        logger.error(f"{Colors.RED}{error_msg}{Colors.END}")
        results.append(error_msg)
        return "\n".join(results)

    except subprocess.CalledProcessError as e:
        error_msg = f"✗ Execution failed with exit code {e.returncode}"
        logger.error(f"{Colors.RED}{error_msg}{Colors.END}")
        results.append(error_msg)
        if e.stdout:
            results.append(f"Stdout: {e.stdout}")
        if e.stderr:
            results.append(f"Stderr: {e.stderr}")
        return "\n".join(results)

    except Exception as e:
        error_msg = f"✗ Error executing script: {str(e)}"
        logger.error(f"{Colors.RED}{error_msg}{Colors.END}")
        results.append(error_msg)
        return "\n".join(results)

    return "\n".join(results)


def _write_and_execute_tool(tool: ToolUse, **_kwargs: Any) -> ToolResult:
    tool_use_id = tool["toolUseId"]
    file_path = tool["input"]["file_path"]
    content = tool["input"]["content"]
    timeout = tool["input"].get("timeout", 300)

    result = _handle_write_and_execute_tool(file_path, content, timeout)

    # Check if execution had errors
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
write_and_execute_tool = PythonAgentTool("write_and_execute_tool", TOOL_SPEC, _write_and_execute_tool)
