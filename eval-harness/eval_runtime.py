"""A separate AgentCore runtime for evals, so evals never touch the users' runtime.

    python eval_runtime.py create                       # copy the users' runtime, image pinned by digest
    python eval_runtime.py status                       # both runtimes: version, image, models
    python eval_runtime.py set-models sonnet45-workers  # a preset from runtime_configs.yaml
    python eval_runtime.py set-models users             # back to the users' runtime's models
    python eval_runtime.py set-image                    # follow the users' runtime's current image
    python eval_runtime.py set-image <uri>[:tag|@sha256:…]  # a candidate image, before it goes to users
    python eval_runtime.py delete

Why: the web app and the harness used to share one runtime. Switching models
for an experiment changed what users got, and redeploying for an eval
redeployed the product. The eval runtime is its own AgentCore runtime (own
models, own image, own version) that reuses everything else from the users'
runtime: role, VPC, ECS cluster, ALB, Fargate task definition, S3 bucket.
Sessions on the two runtimes can't cross: every container request carries its
session id and the code executor rejects a mismatch (403), the fix for the
2026-02-22 cross-runtime incident (docs/incidents/). What stays shared is
capacity (Fargate tasks, ALB, Bedrock quotas), so avoid long eval batches when
users are busy.

The runtime ARN is written to eval-harness/config/eval.env (git-ignored), which
run_eval.py reads as EVAL_RUNTIME_ARN.
"""
import argparse
import copy
import sys
import time
from pathlib import Path

import yaml
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / "config" / "eval.env"
CONFIGS = HERE / "config" / "runtime_configs.yaml"
EVAL_NAME = "deep_insight_eval_runtime"
USERS_NAME = "deep_insight_runtime_vpc"
# Settings copied from the users' runtime as they are.
COPY = ["roleArn", "networkConfiguration", "protocolConfiguration", "lifecycleConfiguration",
        "requestHeaderConfiguration", "authorizerConfiguration"]


def client(region):
    import boto3
    return boto3.client("bedrock-agentcore-control", region_name=region)


def find(ctl, name):
    token = None
    while True:
        page = ctl.list_agent_runtimes(**({"nextToken": token} if token else {}))
        for r in page.get("agentRuntimes", []):
            if r["agentRuntimeName"] == name:
                return ctl.get_agent_runtime(agentRuntimeId=r["agentRuntimeId"])
        token = page.get("nextToken")
        if not token:
            return None


def wait_ready(ctl, runtime_id, timeout=900):
    t0 = time.time()
    while True:
        r = ctl.get_agent_runtime(agentRuntimeId=runtime_id)
        if r["status"] == "READY":
            return r
        if r["status"].endswith("FAILED") or time.time() - t0 > timeout:
            raise SystemExit(f"runtime {runtime_id} is {r['status']}: {r.get('failureReason', '')}")
        time.sleep(10)


def pinned(image_uri, region):
    """repo:tag → repo@sha256:digest, so the eval runtime doesn't move when a tag is re-pushed."""
    if "@sha256:" in image_uri:
        return image_uri
    import boto3
    repo_part, _, tag = image_uri.rpartition(":") if ":" in image_uri.split("/")[-1] else (image_uri, "", "latest")
    registry, repo = repo_part.split("/", 1)
    ecr = boto3.client("ecr", region_name=region)
    detail = ecr.describe_images(repositoryName=repo, imageIds=[{"imageTag": tag}])["imageDetails"][0]
    return f"{registry}/{repo}@{detail['imageDigest']}"


def _update(ctl, current, **changes):
    """UpdateAgentRuntime replaces the configuration: pass everything back, change only what's asked."""
    args = {k: copy.deepcopy(current[k]) for k in ["agentRuntimeArtifact", "description", "environmentVariables", *COPY] if current.get(k)}
    # GetAgentRuntime returns requireServiceS3Endpoint, but a runtime created after
    # 2026-06-11 rejects any update that carries it, even unchanged; left out, it stays as is.
    ((args.get("networkConfiguration") or {}).get("networkModeConfig") or {}).pop("requireServiceS3Endpoint", None)
    args.update(changes)
    ctl.update_agent_runtime(agentRuntimeId=current["agentRuntimeId"], metadataConfiguration={"requireMMDSV2": True}, **args)
    return wait_ready(ctl, current["agentRuntimeId"])


def save_arn(arn, region):
    lines = [l for l in (ENV_FILE.read_text().splitlines() if ENV_FILE.is_file() else []) if not l.startswith(("EVAL_RUNTIME_ARN=", "EVAL_REGION="))]
    ENV_FILE.write_text("\n".join(lines + [f"EVAL_RUNTIME_ARN={arn}", f"EVAL_REGION={region}"]) + "\n")


def models(r):
    return {k: v.split(".")[-1] for k, v in sorted((r.get("environmentVariables") or {}).items()) if k.endswith("_MODEL_ID")}


def image(r):
    return r["agentRuntimeArtifact"]["containerConfiguration"]["containerUri"]


def load_preset(name, users_env):
    if name == "users":
        return {k: v for k, v in users_env.items() if k.endswith("_MODEL_ID")}
    presets = yaml.safe_load(CONFIGS.read_text(encoding="utf-8"))["presets"]
    if name not in presets:
        raise SystemExit(f"unknown preset {name!r}; known: users, {', '.join(presets)}")
    return {**{k: v for k, v in users_env.items() if k.endswith("_MODEL_ID")}, **(presets[name].get("models") or {})}


def cmd_create(ctl, args):
    users = find(ctl, USERS_NAME)
    if users is None:
        raise SystemExit(f"users' runtime {USERS_NAME} not found in {args.region}")
    existing = find(ctl, EVAL_NAME)
    if existing:
        print(f"{EVAL_NAME} already exists ({existing['agentRuntimeArn']}); use set-image / set-models")
        save_arn(existing["agentRuntimeArn"], args.region)
        return
    uri = pinned(image(users), args.region)
    copied = {k: users[k] for k in COPY if users.get(k)}
    # Runtimes created after 2026-06-11 can neither set nor later change
    # requireServiceS3Endpoint, so the eval runtime gets AgentCore's default for it.
    create_net = copy.deepcopy(copied["networkConfiguration"])
    (create_net.get("networkModeConfig") or {}).pop("requireServiceS3Endpoint", None)
    created = ctl.create_agent_runtime(
        agentRuntimeName=EVAL_NAME,
        description="Deep Insight eval runtime (eval-harness/eval_runtime.py); no user traffic",
        agentRuntimeArtifact={"containerConfiguration": {"containerUri": uri}},
        environmentVariables=users["environmentVariables"],
        tags={"purpose": "eval", "copied-from": USERS_NAME},
        **{**copied, "networkConfiguration": create_net},
    )
    r = wait_ready(ctl, created["agentRuntimeId"])
    if not (r.get("metadataConfiguration") or {}).get("requireMMDSV2"):
        r = _update(ctl, r)  # AgentCore only invokes runtimes with MMDSv2 on
    save_arn(r["agentRuntimeArn"], args.region)
    print(f"created {r['agentRuntimeArn']} v{r['agentRuntimeVersion']}\n  image {uri}\n  ARN saved to {ENV_FILE.name}")


def cmd_status(ctl, args):
    for name in (USERS_NAME, EVAL_NAME):
        r = find(ctl, name)
        if r is None:
            print(f"{name}: not found")
            continue
        print(f"{name}: v{r['agentRuntimeVersion']} {r['status']} · MMDSv2 {(r.get('metadataConfiguration') or {}).get('requireMMDSV2')}")
        print(f"  image  {image(r)}")
        print(f"  models {models(r)}")


def _eval(ctl):
    r = find(ctl, EVAL_NAME)
    if r is None:
        raise SystemExit(f"{EVAL_NAME} doesn't exist yet: run `eval_runtime.py create` first")
    return r


def cmd_set_models(ctl, args):
    r, users = _eval(ctl), find(ctl, USERS_NAME)
    # Model IDs come only from the preset (on top of the users' models), so switching back to
    # `users` leaves no model from an earlier preset behind.
    keep = {k: v for k, v in r["environmentVariables"].items() if not k.endswith("_MODEL_ID")}
    env = {**keep, **load_preset(args.preset, users["environmentVariables"])}
    r = _update(ctl, r, environmentVariables=env)
    print(f"{EVAL_NAME} v{r['agentRuntimeVersion']} models → {models(r)}")


def cmd_set_image(ctl, args):
    r = _eval(ctl)
    uri = pinned(args.image or image(find(ctl, USERS_NAME)), args.region)
    r = _update(ctl, r, agentRuntimeArtifact={"containerConfiguration": {"containerUri": uri}})
    print(f"{EVAL_NAME} v{r['agentRuntimeVersion']} image → {uri}")


def cmd_delete(ctl, args):
    r = _eval(ctl)
    ctl.delete_agent_runtime(agentRuntimeId=r["agentRuntimeId"])
    if ENV_FILE.is_file():
        ENV_FILE.write_text("".join(l + "\n" for l in ENV_FILE.read_text().splitlines() if not l.startswith(("EVAL_RUNTIME_ARN=", "EVAL_REGION="))))
    print(f"deleted {r['agentRuntimeArn']}")


def main():
    env = {**dotenv_values(ENV_FILE)} if ENV_FILE.is_file() else {}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default=env.get("EVAL_REGION") or "us-west-2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create")
    sub.add_parser("status")
    sm = sub.add_parser("set-models"); sm.add_argument("preset")
    si = sub.add_parser("set-image"); si.add_argument("image", nargs="?")
    sub.add_parser("delete")
    args = ap.parse_args()
    ctl = client(args.region)
    {"create": cmd_create, "status": cmd_status, "set-models": cmd_set_models,
     "set-image": cmd_set_image, "delete": cmd_delete}[args.cmd](ctl, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
