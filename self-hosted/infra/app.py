#!/usr/bin/env python3
"""CDK app entry point for Deep Insight self-hosted infrastructure."""

import json
import secrets
from pathlib import Path

import aws_cdk as cdk

from stacks.deep_insight_stack import DeepInsightStack

# Auto-generate origin_verify_secret if empty, and save to cdk.json for reuse
cdk_json_path = Path(__file__).parent / "cdk.json"
cdk_json = json.loads(cdk_json_path.read_text())
if not cdk_json.get("context", {}).get("origin_verify_secret"):
    cdk_json.setdefault("context", {})["origin_verify_secret"] = secrets.token_urlsafe(32)
    cdk_json_path.write_text(json.dumps(cdk_json, indent=2) + "\n")
    print(f"🔑 Generated origin_verify_secret and saved to cdk.json")

app = cdk.App()

DeepInsightStack(
    app,
    "DeepInsightStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account") or None,
        region=app.node.try_get_context("region") or "us-west-2",
    ),
)

app.synth()
