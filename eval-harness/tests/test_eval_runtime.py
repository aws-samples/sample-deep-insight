"""eval_runtime.py against fake AgentCore control-plane and ECR clients (no AWS)."""
import copy
import sys
import types

import pytest

import eval_runtime as er

USERS_ID = "deep_insight_runtime_vpc-abc"
IMAGE = "123.dkr.ecr.us-west-2.amazonaws.com/bedrock-agentcore-deep_insight_runtime_vpc:latest"
DIGEST = "sha256:" + "d" * 64
USERS_ENV = {"CODER_MODEL_ID": "global.anthropic.claude-sonnet-5", "PLANNER_MODEL_ID": "global.anthropic.claude-opus-5",
             "ALB_DNS": "internal-alb", "S3_BUCKET_NAME": "bucket"}


class FakeControl:
    def __init__(self):
        self.runtimes = {USERS_ID: {
            "agentRuntimeId": USERS_ID, "agentRuntimeName": er.USERS_NAME, "agentRuntimeArn": f"arn:runtime/{USERS_ID}",
            "agentRuntimeVersion": "12", "status": "READY", "roleArn": "arn:role", "environmentVariables": dict(USERS_ENV),
            "networkConfiguration": {"networkMode": "VPC", "networkModeConfig": {"subnets": ["s"], "requireServiceS3Endpoint": True}},
            "protocolConfiguration": {"serverProtocol": "HTTP"},
            "lifecycleConfiguration": {"maxLifetime": 28800}, "metadataConfiguration": {"requireMMDSV2": True},
            "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": IMAGE}}}}
        self.updates = []

    def list_agent_runtimes(self, **_):
        return {"agentRuntimes": [{"agentRuntimeId": i, "agentRuntimeName": r["agentRuntimeName"]} for i, r in self.runtimes.items()]}

    def get_agent_runtime(self, agentRuntimeId):
        r = copy.deepcopy(self.runtimes[agentRuntimeId])
        net = (r.get("networkConfiguration") or {}).get("networkModeConfig")
        if net is not None:
            net.setdefault("requireServiceS3Endpoint", False)  # AWS reports the default too
        return r

    def create_agent_runtime(self, agentRuntimeName, **kw):
        if "requireServiceS3Endpoint" in str(kw.get("networkConfiguration")):  # as the real API does
            raise ValueError("requireServiceS3Endpoint cannot be set during agent creation.")
        rid = agentRuntimeName + "-new"
        self.runtimes[rid] = {"agentRuntimeId": rid, "agentRuntimeName": agentRuntimeName, "agentRuntimeArn": f"arn:runtime/{rid}",
                              "agentRuntimeVersion": "1", "status": "READY", "metadataConfiguration": {"requireMMDSV2": False}, **kw}
        return {"agentRuntimeId": rid}

    def update_agent_runtime(self, agentRuntimeId, **kw):
        net = (kw.get("networkConfiguration") or {}).get("networkModeConfig") or {}
        cur = (self.runtimes[agentRuntimeId].get("networkConfiguration") or {}).get("networkModeConfig") or {}
        if agentRuntimeId != USERS_ID and "requireServiceS3Endpoint" in net:  # rejected even when unchanged, as the real API does
            raise ValueError("Agents created after 2026-06-11 cannot modify requireServiceS3Endpoint.")
        self.updates.append(kw)
        r = self.runtimes[agentRuntimeId]
        r.update(kw)
        r["agentRuntimeVersion"] = str(int(r["agentRuntimeVersion"]) + 1)

    def delete_agent_runtime(self, agentRuntimeId):
        del self.runtimes[agentRuntimeId]


@pytest.fixture
def env(tmp_path, monkeypatch):
    ctl = FakeControl()
    ecr = types.SimpleNamespace(describe_images=lambda repositoryName, imageIds: {"imageDetails": [{"imageDigest": DIGEST}]})
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda svc, region_name=None: ecr))
    monkeypatch.setattr(er, "ENV_FILE", tmp_path / "eval.env")
    return ctl, types.SimpleNamespace(region="us-west-2", preset=None, image=None)


def eval_rt(ctl):
    return next(r for r in ctl.runtimes.values() if r["agentRuntimeName"] == er.EVAL_NAME)


def test_create_copies_users_runtime_with_pinned_image(env):
    ctl, args = env
    er.cmd_create(ctl, args)
    r = eval_rt(ctl)
    assert r["environmentVariables"] == USERS_ENV and r["roleArn"] == "arn:role"
    assert r["networkConfiguration"]["networkModeConfig"]["subnets"] == ["s"]           # same VPC placement
    assert "requireServiceS3Endpoint" not in r["networkConfiguration"]["networkModeConfig"]   # new runtimes can't set it
    assert er.image(r) == IMAGE.rsplit(":", 1)[0] + "@" + DIGEST       # pinned: a re-pushed :latest doesn't move it
    assert r["metadataConfiguration"] == {"requireMMDSV2": True}         # turned on after create
    assert f"EVAL_RUNTIME_ARN={r['agentRuntimeArn']}" in er.ENV_FILE.read_text()
    er.cmd_create(ctl, args)                                             # second create is a no-op
    assert sum(x["agentRuntimeName"] == er.EVAL_NAME for x in ctl.runtimes.values()) == 1


def test_set_models_preset_keeps_image_and_other_env(env):
    ctl, args = env
    er.cmd_create(ctl, args)
    pinned_image = er.image(eval_rt(ctl))
    args.preset = "sonnet45-workers"
    er.cmd_set_models(ctl, args)
    r = eval_rt(ctl)
    assert r["environmentVariables"]["CODER_MODEL_ID"].startswith("global.anthropic.claude-sonnet-4-5")
    assert r["environmentVariables"]["PLANNER_MODEL_ID"] == USERS_ENV["PLANNER_MODEL_ID"]   # not in the preset
    assert r["environmentVariables"]["ALB_DNS"] == "internal-alb" and er.image(r) == pinned_image
    assert ctl.runtimes[USERS_ID]["environmentVariables"] == USERS_ENV                    # users' runtime untouched
    args.preset = "users"
    er.cmd_set_models(ctl, args)
    assert eval_rt(ctl)["environmentVariables"] == USERS_ENV


def test_set_image_candidate_and_follow_users(env):
    ctl, args = env
    er.cmd_create(ctl, args)
    args.image = "123.dkr.ecr.us-west-2.amazonaws.com/repo@sha256:" + "c" * 64
    er.cmd_set_image(ctl, args)
    assert er.image(eval_rt(ctl)) == args.image
    args.image = None
    er.cmd_set_image(ctl, args)
    assert er.image(eval_rt(ctl)).endswith("@" + DIGEST)
    assert all(u["metadataConfiguration"] == {"requireMMDSV2": True} for u in ctl.updates)


def test_unknown_preset(env):
    with pytest.raises(SystemExit, match="unknown preset"):
        er.load_preset("nope", USERS_ENV)


def test_run_eval_refuses_the_users_runtime(monkeypatch, tmp_path):
    import run_eval
    monkeypatch.setattr(run_eval, "dotenv_values", lambda p: {"RUNTIME_ARN": "arn:users"} if "managed-agentcore" in str(p) else {})
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--scenario", "jungle_market", "--tag", "t", "--runtime-arn", "arn:users"])
    with pytest.raises(SystemExit):
        run_eval.main()
