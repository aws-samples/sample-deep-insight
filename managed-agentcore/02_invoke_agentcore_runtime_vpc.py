#!/usr/bin/env python3
"""
invoke_agentcore_runtime_vpc.py

Purpose:
    Client script to test and invoke AgentCore Runtime deployed in VPC mode.

Usage:
    python3 invoke_agentcore_runtime_vpc.py

Configuration:
    - AgentCore Runtime ARN (loaded from .env)
    - AWS Region (loaded from .env)
    - User Prompt

Features:
    - Invokes AgentCore Runtime
    - Processes streaming responses
    - Displays results in real-time

Execution Order:
    create_agentcore_runtime_vpc.py → agentcore_runtime.py (entrypoint) → invoke_agentcore_runtime_vpc.py (test)
"""

import json
import sys
import os
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

# Read configuration from environment variables
AGENT_ARN = os.getenv("RUNTIME_ARN")
REGION = os.getenv("AWS_REGION", "us-east-1")

# Validation
if not AGENT_ARN:
    print(f"{RED}❌ RUNTIME_ARN is not set{NC}")
    print(f"{YELLOW}⚠️  Run create_agentcore_runtime_vpc.py first{NC}")
    sys.exit(1)

# User prompt (expected runtime: 2-5 minutes for quick VPC test)
PROMPT = "./data/Dat-fresh-food-claude.csv 파일의 총 매출액 계산해줘. PDF 보고서는 만들지 마."
# Alternative prompts:
# PROMPT = "./data/Dat-fresh-food-claude.csv 파일의 총 매출액을 계산하고 차트 1개와 PDF 보고서를 생성해줘"  # 15-20 min
# PROMPT = "./data/Dat-fresh-food-claude.csv 파일을 분석해서 총 매출액을 계산하고, 카테고리별 매출 비중도 함께 보여줘. 그리고 pdf 로 보고서 생성해줘"  # 20-25 min


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

def main():
    """Invoke AgentCore Runtime and process streaming response"""
    start_time = datetime.now()
    print(f"\n{BLUE}{'='*60}{NC}")
    print(f"{BLUE}🚀 AgentCore Runtime Job Started{NC}")
    print(f"{BLUE}📅 Start Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}{NC}")
    print(f"{BLUE}🎯 Agent ARN: {AGENT_ARN}{NC}")
    print(f"{BLUE}🌐 Region: {REGION}{NC}")
    print(f"{BLUE}{'='*60}{NC}\n")

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
    print(f"💬 Prompt: {PROMPT}\n")

    try:
        boto3_response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_ARN,
            qualifier="DEFAULT",
            payload=json.dumps({"prompt": PROMPT})
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
