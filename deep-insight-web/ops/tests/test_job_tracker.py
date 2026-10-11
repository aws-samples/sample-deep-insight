"""get_job_status: what a browser that lost its stream may see, against moto's DynamoDB.

Run from deep-insight-web/: python -m pytest ops/tests/
"""
import importlib

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def tracker(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("DYNAMODB_TABLE_NAME", "jobs")
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="jobs", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
        )
        from ops import job_tracker
        yield importlib.reload(job_tracker)


def test_status_without_error_text(tracker):
    boto3.resource("dynamodb").Table("jobs").put_item(Item={
        "job_id": "j1", "status": "Failed", "session_id": "s1",
        "error_message": "AccessDenied: arn:aws:iam::123456789012:role/x",
    })
    assert tracker.get_job_status("j1") == {"status": "Failed", "session_id": "s1"}


def test_unknown_job(tracker):
    assert tracker.get_job_status("nope") is None


def test_not_configured(tracker, monkeypatch):
    monkeypatch.setattr(tracker, "DYNAMODB_TABLE_NAME", "")
    assert tracker.get_job_status("j1") is None


def test_stream_error_never_replaces_success(tracker, monkeypatch):
    # the runtime and Lambda recorded Success; then the web server's stream broke
    table = boto3.resource("dynamodb").Table("jobs")
    table.put_item(Item={"job_id": "j2", "status": "Success", "session_id": "s2"})
    mails = []
    monkeypatch.setattr(tracker, "_notify_failure", lambda job_id, err: mails.append(job_id))
    tracker.track_job_failure("j2", "Read timed out")
    assert table.get_item(Key={"job_id": "j2"})["Item"]["status"] == "Success"
    assert mails == []


def test_stream_error_records_failed_while_running(tracker, monkeypatch):
    table = boto3.resource("dynamodb").Table("jobs")
    table.put_item(Item={"job_id": "j3", "status": "Start"})
    mails = []
    monkeypatch.setattr(tracker, "_notify_failure", lambda job_id, err: mails.append(job_id))
    tracker.track_job_failure("j3", "Stream interrupted")
    assert table.get_item(Key={"job_id": "j3"})["Item"]["status"] == "Failed"
    assert mails == ["j3"]
