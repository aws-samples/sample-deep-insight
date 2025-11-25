#!/usr/bin/env python3
"""
invoke_agentcore_runtime_vpc.py

Purpose:
    Client script to test and invoke AgentCore Runtime deployed in VPC mode.

Usage:
    # Use environment variables or defaults
    python3 02_invoke_agentcore_runtime_vpc.py

    # Override with command-line arguments
    python3 02_invoke_agentcore_runtime_vpc.py --user_query "Analyze sales data" --data_directory "./my_data"

    # Mix CLI args and environment variables
    python3 02_invoke_agentcore_runtime_vpc.py --user_query "Custom query"

Configuration Priority:
    1. Command-line arguments (--user_query, --data_directory)
    2. Environment variables (USER_QUERY, DATA_DIRECTORY)
    3. Default values (hardcoded Korean prompt, "./data")

Features:
    - Invokes AgentCore Runtime
    - Processes streaming responses
    - Displays results in real-time
    - Flexible input via CLI arguments or environment variables

Execution Order:
    create_agentcore_runtime_vpc.py → agentcore_runtime.py (entrypoint) → invoke_agentcore_runtime_vpc.py (test)
"""

import json
import sys
import os
import argparse
from datetime import datetime
import traceback
from dotenv import load_dotenv

# Terminal color codes
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color

# Path configuration
current_dir = os.path.dirname(os.path.abspath(__file__))
utils_dir = os.path.abspath(os.path.join(current_dir, '.'))
sys.path.insert(0, utils_dir)

import boto3
from botocore.config import Config
from src.utils.strands_sdk_utils import strands_utils

# ============================================================
# Command-Line Argument Parsing
# ============================================================

def parse_arguments():
    """Parse command-line arguments for user query and data directory"""
    parser = argparse.ArgumentParser(
        description="Invoke AgentCore Runtime with custom query and data directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use environment variables or defaults
  python3 02_invoke_agentcore_runtime_vpc.py

  # Override user query
  python3 02_invoke_agentcore_runtime_vpc.py --user_query "Analyze sales data"

  # Override both query and directory
  python3 02_invoke_agentcore_runtime_vpc.py --user_query "Calculate revenue" --data_directory "./my_data"
        """
    )

    parser.add_argument(
        '--user_query',
        type=str,
        default=None,
        help='User query to send to AgentCore Runtime (overrides USER_QUERY env var)'
    )

    parser.add_argument(
        '--data_directory',
        type=str,
        default=None,
        help='Data directory path to upload (overrides DATA_DIRECTORY env var, default: ./data)'
    )

    return parser.parse_args()

# ============================================================
# Configuration Loading
# ============================================================

# Load .env file
env_file = os.path.join(current_dir, ".env")
if not os.path.exists(env_file):
    print(f"{RED}❌ .env file not found: {env_file}{NC}")
    print(f"{YELLOW}⚠️  Deploy Phase 1, 2, 3 first{NC}")
    print(f"{YELLOW}⚠️  Or run ./production_deployment/scripts/setup_env.sh{NC}")
    sys.exit(1)

load_dotenv(env_file, override=True)

# Parse command-line arguments
args = parse_arguments()

# Read configuration from environment variables
AGENT_ARN = os.getenv("RUNTIME_ARN")
REGION = os.getenv("AWS_REGION", "us-east-1")

# Validation
if not AGENT_ARN:
    print(f"{RED}❌ RUNTIME_ARN is not set{NC}")
    print(f"{YELLOW}⚠️  Run create_agentcore_runtime_vpc.py first{NC}")
    sys.exit(1)

# simple version for debugging
#DEFAULT_PROMPT = "데이터 디렉토리의 모든 CSV 파일을 분석하고 총 매출액을 계산해줘. 보고서는 만들지 마."
# simple version - bill expectation :$2.137 
# DEFAULT_PROMPT = "데이터 디렉토리의 모든 CSV 파일을 분석하고,이 Moon Market 데이터의 핵심 지표를 요약해줘" # Simple Version
# complex version
DEFAULT_PROMPT = "데이터 디렉토리의 모든 CSV 파일을 분석하고 이 Moon Market 데이터에서 비즈니스 성장 기회를 발굴해줘: 숨겨진 고객 패턴과 세그먼트를 발견하고, 수익 최적화 방안을 제시하며, 마케팅과 운영 효율성을 높일 수 있는 개선점을 찾고, 다음 달 매출을 크게 늘릴 수 있는 실행 가능한 전략 3가지를 우선순위와 기대 효과를 포함해서 제안해줘." 
# User prompt with priority: CLI args > env var > default
#DEFAULT_PROMPT = "데이터 디렉토리의 모든 CSV 파일을 분석하고 총 매출액을 계산해줘. PDF 보고서는 만들지 마."
#DEFAULT_PROMPT = "데이터 디렉토리의 모든 CSV 파일을 분석하고 총 매출액을 계산해줘, 아주 자세히 분석해줘." 
DEFAULT_PROMPT = "데이터 디렉토리의 모든 CSV 파일을 분석하고 이 Moon Market 데이터에서 비즈니스 성장 기회를 발굴해줘: 숨겨진 고객 패턴과 세그먼트를 발견하고, 수익 최적화 방안을 제시하며, 마케팅과 운영 효율성을 높일 수 있는 개선점을 찾고, 다음 달 매출을 크게 늘릴 수 있는 실행 가능한 전략 3가지를 우선순위와 기대 효과를 포함해서 제안해줘." 

#DEFAULT_PROMPT = "데이터 디렉토리의 모든 CSV 파일을 분석하고 총 매출액을 계산해줘, 카테고리별 매출 비중도 함께 보여줘. 결과물을 docx로 만들어줘" 
PROMPT = args.user_query or os.getenv("USER_QUERY", DEFAULT_PROMPT)

# Data directory with priority: CLI args > env var > default
DATA_DIRECTORY = args.data_directory or os.getenv("DATA_DIRECTORY", "./data")


def parse_sse_data(sse_bytes):
    """Parse Server-Sent Events (SSE) data from streaming response"""
    if not sse_bytes or len(sse_bytes) == 0:
        return None

    try:
        text = sse_bytes.decode('utf-8').strip()
        if not text or text == '':
            return None

        if text.startswith('data: '):
            json_text = text[6:].strip()
            if json_text:
                return json.loads(json_text)
        else:
            return json.loads(text)

    except Exception as e:
        pass

    return None

def build_payload():
    """Build request payload with directory support"""
    return {
        "prompt": PROMPT,
        "data_directory": DATA_DIRECTORY  # Required for data upload
    }

def main():
    """Invoke AgentCore Runtime and process streaming response"""
    start_time = datetime.now()
    print(f"\n{BLUE}{'='*60}{NC}")
    print(f"{BLUE}🚀 AgentCore Runtime Job Started{NC}")
    print(f"{BLUE}📅 Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}{NC}")
    print(f"{BLUE}🎯 Agent ARN: {AGENT_ARN}{NC}")
    print(f"{BLUE}🌐 Region: {REGION}{NC}")
    print(f"{BLUE}{'='*60}{NC}\n")

    # Display input sources
    print(f"📝 Input Configuration:")
    if args.user_query:
        print(f"   💬 User Query: [CLI argument] {PROMPT}")
    elif os.getenv("USER_QUERY"):
        print(f"   💬 User Query: [Environment variable] {PROMPT}")
    else:
        print(f"   💬 User Query: [Default] {PROMPT}")

    if args.data_directory:
        print(f"   📂 Data Directory: [CLI argument] {DATA_DIRECTORY}")
    elif os.getenv("DATA_DIRECTORY"):
        print(f"   📂 Data Directory: [Environment variable] {DATA_DIRECTORY}")
    else:
        print(f"   📂 Data Directory: [Default] {DATA_DIRECTORY}")
    print()

    # Create boto3 client with extended timeouts
    my_config = Config(
        connect_timeout=6000,
        read_timeout=3600,  # 1 hour for long-running jobs
        retries={'max_attempts': 0}  # Disable retries to avoid duplicate requests
    )

    agentcore_client = boto3.client(
        'bedrock-agentcore',
        region_name=REGION,
        config=my_config,
    )

    # Invoke AgentCore Runtime
    print(f"📤 Sending request...")

    try:
        payload = build_payload()
        print(f"📦 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}\n")

        boto3_response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_ARN,
            qualifier="DEFAULT",
            payload=json.dumps(payload)
        )

        # Process streaming response
        if "text/event-stream" in boto3_response.get("contentType", ""):
            print(f"📥 Receiving streaming response...\n")

            for event in boto3_response["response"].iter_lines(chunk_size=1):
                event_data = parse_sse_data(event)
                if event_data is None:
                    continue
                else:
                    strands_utils.process_event_for_display(event_data)

        end_time = datetime.now()
        elapsed_time = (end_time - start_time).total_seconds()

        print(f"\n{GREEN}{'='*60}{NC}")
        print(f"{GREEN}✅ AgentCore Runtime Job Completed{NC}")
        print(f"{GREEN}📅 End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}{NC}")
        print(f"{GREEN}⏱️  Total Duration: {elapsed_time:.2f}s ({elapsed_time/60:.2f}min){NC}")
        print(f"{GREEN}{'='*60}{NC}\n")

    except Exception as e:
        error_message = str(e)
        error_type = type(e).__name__

        # Get full traceback
        full_traceback = traceback.format_exc()

        # Print to terminal
        print(f"\n{RED}❌ Error occurred: {error_message}{NC}")
        print(f"{RED}📛 Error type: {error_type}{NC}")
        print(f"\nTraceback:")
        print(full_traceback)

        sys.exit(1)

if __name__ == "__main__":
    main()
