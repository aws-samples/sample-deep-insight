"""Admin trace / files APIs, against moto's DynamoDB and S3.

Run from deep-insight-web/: python -m pytest ops/tests/   (needs fastapi, httpx, PyJWT, boto3, moto, pytest)
"""
import importlib
import json
import sys
from pathlib import Path

import boto3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

BUCKET = "bucket"
TABLE = "deep-insight-jobs"
SESSION = "sess-1"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", TABLE)
    monkeypatch.setenv("S3_BUCKET_NAME", BUCKET)
    with mock_aws():
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
        boto3.client("dynamodb").create_table(
            TableName=TABLE, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        )
        table = boto3.resource("dynamodb").Table(TABLE)
        table.put_item(Item={"job_id": "job-1", "status": "Success", "session_id": SESSION, "started_at": 1,
                             "trace_path": "deep-insight/traces/job-1/events.jsonl"})
        table.put_item(Item={"job_id": "job-3", "status": "Start", "started_at": 3})
        table.put_item(Item={"job_id": "job-2", "status": "Start", "started_at": 2})

        trace = [{"seq": 1, "kind": "input", "prompt": "q"}, {"seq": 2, "kind": "text", "agent": "planner", "text": "plan"}]
        body = "\n".join(json.dumps(r) for r in trace) + "\n"
        # job-1 finished (trace_path recorded); job-3 is running (trace at its job_id key)
        s3.put_object(Bucket=BUCKET, Key="deep-insight/traces/job-1/events.jsonl", Body=body)
        s3.put_object(Bucket=BUCKET, Key="deep-insight/traces/job-3/events.jsonl", Body=body)
        s3.put_object(Bucket=BUCKET, Key=f"deep-insight/fargate_sessions/{SESSION}/artifacts/chart.png", Body=b"PNG")
        s3.put_object(Bucket=BUCKET, Key=f"deep-insight/fargate_sessions/{SESSION}/artifacts/보고서.docx", Body=b"DOCX")
        s3.put_object(Bucket=BUCKET, Key=f"deep-insight/fargate_sessions/{SESSION}/artifacts/chart.svg", Body=b"<svg/>")
        s3.put_object(Bucket=BUCKET, Key="uploads/job-1/sales.csv", Body=b"a,b\n1,2\n")

        from ops import admin_router as module
        module = importlib.reload(module)
        app = FastAPI()
        app.include_router(module.admin_router)
        app.dependency_overrides[module.require_admin] = lambda: {"email": "admin@example.com"}
        yield TestClient(app)


def test_trace_returns_records(client):
    data = client.get("/admin/api/jobs/job-1/trace").json()
    assert data["available"] is True
    assert [r["kind"] for r in data["records"]] == ["input", "text"]


def test_running_job_trace_read_from_job_id_key(client):
    data = client.get("/admin/api/jobs/job-3/trace").json()
    assert data["available"] is True and len(data["records"]) == 2


def test_trace_unavailable_before_first_upload(client):
    assert client.get("/admin/api/jobs/job-2/trace").json() == {"success": True, "available": False, "records": []}


def test_unknown_or_unsafe_job_is_404(client):
    assert client.get("/admin/api/jobs/nope/trace").status_code == 404
    assert client.get("/admin/api/jobs/a.b/files").status_code == 404


def test_lists_artifacts_and_input(client):
    data = client.get("/admin/api/jobs/job-1/files").json()
    assert sorted(f["name"] for f in data["artifacts"]) == ["chart.png", "chart.svg", "보고서.docx"]
    assert data["input"] == [{"name": "sales.csv", "size": 8}]
    no_session = client.get("/admin/api/jobs/job-2/files").json()
    assert no_session["artifacts"] == []


def test_images_inline_and_sandboxed(client):
    r = client.get("/admin/api/jobs/job-1/files/artifacts/chart.svg")
    assert r.headers["content-type"] == "image/svg+xml"
    assert r.headers["content-security-policy"] == "sandbox"
    assert "content-disposition" not in r.headers


def test_download_as_attachment_with_utf8_name(client):
    r = client.get("/admin/api/jobs/job-1/files/artifacts/보고서.docx")
    assert r.content == b"DOCX"
    assert "attachment" in r.headers["content-disposition"]
    assert "%EB%B3%B4" in r.headers["content-disposition"]
    forced = client.get("/admin/api/jobs/job-1/files/input/sales.csv?download=true")
    assert "attachment" in forced.headers["content-disposition"]


def test_rejects_traversal_and_unknown_area(client):
    assert client.get("/admin/api/jobs/job-1/files/artifacts/../output/events.jsonl").status_code in (400, 404)
    assert client.get("/admin/api/jobs/job-1/files/artifacts/a/%2E%2E/b").status_code in (400, 404)
    assert client.get("/admin/api/jobs/job-1/files/debug/x.json").status_code == 404
    assert client.get("/admin/api/jobs/job-2/files/artifacts/chart.png").status_code == 404


def test_old_job_page_url_opens_the_side_panel(client):
    r = client.get("/admin/dashboard/job-1", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/admin/dashboard?job=job-1"
    assert client.get("/admin/dashboard/a.b", follow_redirects=False).status_code == 404
