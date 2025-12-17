#!/usr/bin/env python3

import os
import logging
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
    "name": "custom_interpreter_python_tool",
    "description": "Use this to execute python code and do data analysis or calculation using custom code interpreter. If you want to see the output of a value, you should print it out with `print(...)`. This is visible to the user.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The python code to execute to do further analysis or calculation."
                }
            },
            "required": ["code"]
        }
    }
}

class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

@log_io
def _handle_custom_interpreter_python_tool(code: Annotated[str, "The python code to execute to do further analysis or calculation."]):
    """
    Use this to execute python code and do data analysis or calculation using custom code interpreter.
    If you want to see the output of a value, you should print it out with `print(...)`. This is visible to the user.
    """
    tracer = trace.get_tracer(
        instrumenting_module_name=os.getenv("TRACER_MODULE_NAME", "insight_extractor_agent"),
        instrumenting_library_version=os.getenv("TRACER_LIBRARY_VERSION", "1.0.0")
    )
    with tracer.start_as_current_span("custom_interpreter_python_tool") as span:
        print()  # Add newline before log
        logger.info(f"{Colors.GREEN}===== Executing Python code in custom interpreter ====={Colors.END}")

        try:
            # 글로벌 세션 매니저를 통해 Fargate에서 실행
            session_manager = get_global_session()

            # 코드 실행
            result = session_manager.execute_code(code, "Python execution")

            # 에러 처리
            if result.get('error'):
                error_msg = f"Failed to execute. Error: {result['error']}"
                logger.error(f"{Colors.RED}Failed to execute. Error: {result['error']}{Colors.END}")

                # Add Event
                add_span_event(span, "code", {"code": str(code)})
                add_span_event(span, "error", {"response": str(result['error'])})

                return error_msg

            # 성공적으로 실행된 경우
            stdout = result.get('stdout', '')

            # Truncate code to first 7 lines for context efficiency
            code_lines = code.split('\n')
            if len(code_lines) > 7:
                code_preview = '\n'.join(code_lines[:7])
                code_summary = f"{code_preview}\n... ({len(code_lines) - 7} more lines omitted)"
            else:
                code_summary = code

            # # 파일 처리 (Method 1 구현) - 주석 처리됨 (필요 없음)
            # files = result.get('files', {})
            # if files:
            #     logger.info(f"{Colors.BLUE}📁 Processing {len(files)} file(s) from Fargate{Colors.END}")
            #
            #     # 로컬 artifacts 디렉토리 확인
            #     os.makedirs('./artifacts', exist_ok=True)
            #     os.makedirs('./data', exist_ok=True)
            #
            #     saved_files = []
            #     for relative_path, file_data in files.items():
            #         # 텍스트 파일은 content 필드가 있고, 이진 파일은 error 필드가 있음
            #         # Binary files can have different error messages: "Binary file" or UTF-8 decode errors
            #         is_binary_file = ('error' in file_data and
            #                         (file_data.get('error') == 'Binary file' or
            #                          'codec can\'t decode' in str(file_data.get('error', ''))))
            #         if 'content' in file_data or is_binary_file:
            #             # 로컬 경로 결정
            #             if relative_path.startswith('artifacts/'):
            #                 local_path = f"./{relative_path}"
            #             elif relative_path.startswith('data/'):
            #                 local_path = f"./{relative_path}"
            #             else:
            #                 local_path = f"./artifacts/{relative_path}"
            #
            #             # 디렉토리 생성
            #             os.makedirs(os.path.dirname(local_path), exist_ok=True)
            #
            #             # 파일 저장 (이진 파일과 텍스트 파일 구분)
            #             try:
            #                 if 'content' in file_data:
            #                     # 텍스트 파일 처리 (content가 있는 경우)
            #                     with open(local_path, 'w', encoding='utf-8') as f:
            #                         f.write(file_data['content'])
            #                     saved_files.append(local_path)
            #                     logger.info(f"{Colors.GREEN}✅ Saved: {local_path}{Colors.END}")
            #                 elif is_binary_file:
            #                     # 이진 파일 처리 (S3에서 다운로드)
            #                     try:
            #                         import boto3
            #                         # Get session from current session manager
            #                         session_info = session_manager.get_session_info()
            #                         session_id = session_info.get('session_id')
            #
            #                         if session_id:
            #                             # S3 경로 구성: manus/fargate_sessions/{session_id}/artifacts/{filename}
            #                             s3_key = f"manus/fargate_sessions/{session_id}/{relative_path}"
            #                             s3_client = boto3.client('s3')
            #
            #                             # S3에서 파일 다운로드
            #                             s3_client.download_file('bedrock-logs-gonsoomoon', s3_key, local_path)
            #                             saved_files.append(local_path)
            #                             logger.info(f"{Colors.GREEN}✅ Downloaded from S3: {local_path}{Colors.END}")
            #                         else:
            #                             logger.error(f"{Colors.RED}❌ No session ID available for S3 download{Colors.END}")
            #                     except Exception as s3_error:
            #                         logger.error(f"{Colors.RED}❌ Failed to download {relative_path} from S3: {s3_error}{Colors.END}")
            #                         # 세션이 끝났을 가능성이 있으므로 로그만 남기고 계속 진행
            #                 else:
            #                     logger.warning(f"{Colors.YELLOW}⚠️ Skipping file (no content or binary): {relative_path}{Colors.END}")
            #
            #             except Exception as e:
            #                 logger.error(f"{Colors.RED}❌ Failed to save {local_path}: {e}{Colors.END}")
            #
            #     # all_results.txt 내용 추가로 stdout에 포함
            #     if 'artifacts/all_results.txt' in files and 'content' in files['artifacts/all_results.txt']:
            #         all_results_content = files['artifacts/all_results.txt']['content']
            #         stdout += f"\n\n=== all_results.txt content ===\n{all_results_content}"

            # 기존 인터페이스와 동일한 형식으로 반환
            result_str = f"Successfully executed:\n||{code_summary}||{stdout}"

            logger.info(f"{Colors.GREEN}===== Code execution successful in custom interpreter ====={Colors.END}")

            # Add Event
            add_span_event(span, "code", {"code": str(code_summary)})
            add_span_event(span, "result", {"response": str(stdout)})

            return result_str

        except Exception as e:
            error_msg = f"Failed to execute. Error: {repr(e)}"
            logger.error(f"{Colors.RED}Failed to execute. Error: {repr(e)}{Colors.END}")

            # Add Event
            add_span_event(span, "code", {"code": str(code)})
            add_span_event(span, "error", {"response": repr(e)})

            return error_msg

# Function name must match tool name
def _custom_interpreter_python_tool(tool: ToolUse, **_kwargs: Any) -> ToolResult:
    tool_use_id = tool["toolUseId"]
    code = tool["input"]["code"]

    # Use the existing handle_custom_interpreter_python_tool function
    result = _handle_custom_interpreter_python_tool(code)

    # Check if execution was successful based on the result string
    if "Failed to execute" in result:
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
custom_interpreter_python_tool = PythonAgentTool("custom_interpreter_python_tool", TOOL_SPEC, _custom_interpreter_python_tool)
