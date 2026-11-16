"""Invoke one evaluator inside AgentCore; do not execute its script locally."""
import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

SCRIPTS = {
    "rules": "graders/rules.py",
    "factcheck": "graders/factcheck.py",
    "judge": "graders/judge.py",
    "pairwise": "graders/pairwise.py",
}
ROOT = Path(__file__).resolve().parent


def invoke_evaluator(client, runtime_arn, evaluator):
    request_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn, qualifier="DEFAULT", runtimeSessionId=session_id,
        payload=json.dumps({"evaluator": evaluator, "request_id": request_id}),
    )
    if response["ResponseMetadata"]["HTTPStatusCode"] != 200:
        raise RuntimeError("AgentCore did not return HTTP 200")
    body = response["response"]
    try:
        content_type = response.get("contentType", "")
        if "text/event-stream" in content_type:
            results = []
            for line in body.iter_lines(chunk_size=1):
                if line.startswith(b"data:"):
                    event = json.loads(line[5:].strip())
                    if event.get("type") == "evaluation_complete":
                        results.append(event)
                    elif event.get("type") == "error":
                        raise RuntimeError("Runtime reported an error")
            if len(results) != 1:
                raise RuntimeError("Expected exactly one evaluator result")
            result = results[0]
        elif "application/json" in content_type:
            result = json.loads(body.read())
        else:
            raise RuntimeError("Unexpected AgentCore response content type")
    finally:
        body.close()
    expected_hash = hashlib.sha256((ROOT / SCRIPTS[evaluator]).read_bytes()).hexdigest()
    if (result.get("execution_environment") != "agentcore-runtime"
            or result.get("evaluator") != evaluator
            or result.get("request_id") != request_id
            or result.get("script") != SCRIPTS[evaluator]
            or result.get("script_sha256") != expected_hash):
        raise RuntimeError("Runtime result does not match the requested evaluator and checked-out script")
    if result.get("returncode") != 0:
        raise RuntimeError("Evaluator script failed inside the runtime")
    if "Hello World" not in result.get("stdout", ""):
        raise RuntimeError("Runtime evaluator did not print Hello World")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator", choices=SCRIPTS, required=True)
    parser.add_argument("--runtime-arn", default=os.environ.get("EVAL_RUNTIME_ARN"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    parser.add_argument("--out")
    args = parser.parse_args()
    if not args.runtime_arn:
        parser.error("--runtime-arn or EVAL_RUNTIME_ARN is required")
    import boto3
    from botocore.config import Config
    client = boto3.client("bedrock-agentcore", region_name=args.region,
                          config=Config(connect_timeout=30, read_timeout=300,
                                        retries={"total_max_attempts": 1}))
    result = invoke_evaluator(client, args.runtime_arn, args.evaluator)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
