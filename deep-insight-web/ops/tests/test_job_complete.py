"""Job status transitions in the ops Lambda, against moto's DynamoDB, S3 and SNS.

Run from deep-insight-web/: python -m pytest ops/tests/   (needs boto3, moto, pytest)
"""
import importlib
import json
import sys
import time
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))

BUCKET = "bucket"
TABLE = "deep-insight-jobs"
SESSION = "sess-1"
OUTPUT = f"deep-insight/fargate_sessions/{SESSION}/output/"


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "us-west-2"})
        boto3.client("dynamodb").create_table(
            TableName=TABLE,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "job_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "started_at", "AttributeType": "N"},
                {"AttributeName": "session_id", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {"IndexName": "StatusStartedIndex",
                 "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"},
                               {"AttributeName": "started_at", "KeyType": "RANGE"}],
                 "Projection": {"ProjectionType": "ALL"}},
                {"IndexName": "SessionIdIndex",
                 "KeySchema": [{"AttributeName": "session_id", "KeyType": "HASH"}],
                 "Projection": {"ProjectionType": "KEYS_ONLY"}},
            ],
        )
        topic = boto3.client("sns").create_topic(Name="jobs")["TopicArn"]
        monkeypatch.setenv("DYNAMODB_TABLE_NAME", TABLE)
        monkeypatch.setenv("SNS_TOPIC_ARN", topic)
        monkeypatch.setenv("STALE_JOB_MINUTES", "120")
        monkeypatch.setenv("STALE_HEARTBEAT_MINUTES", "30")
        monkeypatch.setenv("S3_BUCKET_NAME", BUCKET)
        import job_complete
        module = importlib.reload(job_complete)
        sent = []
        monkeypatch.setattr(module, "_publish", lambda subject, message, job_id: sent.append(subject))
        module.sent = sent
        yield module


def _table():
    return boto3.resource("dynamodb").Table(TABLE)


def _start_job(job_id="job-1", started_at=None, **extra):
    _table().put_item(Item={"job_id": job_id, "status": "Start", "user_query": "q",
                            "started_at": started_at or int(time.time()) - 60, **extra})


def _put(key, body):
    boto3.client("s3").put_object(Bucket=BUCKET, Key=key, Body=json.dumps(body))


def _s3_event(key):
    return {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": key}}}]}


def _report(lam, status, job_id="job-1", error="", **extra):
    _put(OUTPUT + "job_status.json", {"job_id": job_id, "session_id": SESSION, "status": status,
                                      "error": error, "ended_at": int(time.time()),
                                      "trace_path": OUTPUT + "events.jsonl", "output_preview": "Top segment: 30s women",
                                      **extra})
    lam.handler(_s3_event(OUTPUT + "job_status.json"), None)


TOKENS = {"job_id": "job-1", "summary": {"total_tokens": 1500, "total_input_tokens": 1000,
                                         "total_output_tokens": 500, "cache_read_input_tokens": 400,
                                         "cache_write_input_tokens": 0}}


def test_success_without_session_link(aws):
    # The browser stream broke before workflow_complete: session_id was never linked
    _start_job()
    _put(OUTPUT + "token_usage.json", TOKENS)
    _put(f"deep-insight/fargate_sessions/{SESSION}/artifacts/report.docx", {})
    _report(aws, "Success")
    job = _table().get_item(Key={"job_id": "job-1"})["Item"]
    assert job["status"] == "Success"
    assert job["session_id"] == SESSION
    assert job["trace_path"] == OUTPUT + "events.jsonl"
    assert job["total_tokens"] == 1500 and job["cache_hit_rate"] == 40
    assert job["report_filename"] == "report.docx"
    assert job["output_preview"] == "Top segment: 30s women"
    assert aws.sent == ["Deep Insight Job Completed"]


def test_failure_records_error_and_notifies_once(aws):
    _start_job()
    _report(aws, "Failed", error="client disconnected")
    job = _table().get_item(Key={"job_id": "job-1"})["Item"]
    assert job["status"] == "Failed" and job["error_message"] == "client disconnected"
    assert job["total_tokens"] == 0  # no token_usage.json
    assert aws.sent == ["Deep Insight Job Failed"]


def test_failure_already_reported_by_web_is_not_mailed_again(aws):
    _start_job()
    _table().update_item(Key={"job_id": "job-1"}, UpdateExpression="SET #s = :f",
                         ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":f": "Failed"})
    _report(aws, "Failed", error="stream interrupted")
    job = _table().get_item(Key={"job_id": "job-1"})["Item"]
    assert job["session_id"] == SESSION  # trace still linked
    assert aws.sent == []


def test_duplicate_success_event_is_skipped(aws):
    _start_job()
    _report(aws, "Success")
    _report(aws, "Success")
    assert aws.sent == ["Deep Insight Job Completed"]


def test_job_status_without_job_id_and_no_job_record_is_ignored(aws):
    _report(aws, "Success", job_id=None)  # e.g. an eval harness run
    assert aws.sent == []


def test_job_status_without_job_id_settles_the_linked_job(aws):
    # job_id null, token_usage.json carries the key (null): the legacy trigger
    # skips it, so job_status.json must settle the job via the session link
    _start_job(session_id=SESSION)
    _put(OUTPUT + "token_usage.json", {**TOKENS, "job_id": None})
    aws.handler(_s3_event(OUTPUT + "token_usage.json"), None)
    assert _table().get_item(Key={"job_id": "job-1"})["Item"]["status"] == "Start"
    _report(aws, "Success", job_id=None)
    job = _table().get_item(Key={"job_id": "job-1"})["Item"]
    assert job["status"] == "Success" and job["total_tokens"] == 1500
    assert aws.sent == ["Deep Insight Job Completed"]


def test_failed_run_takes_token_totals_from_job_status(aws):
    # Failed runs write no token_usage.json (older Lambdas would read it as Success)
    _start_job()
    _report(aws, "Failed", error="boom", token_usage=TOKENS["summary"])
    job = _table().get_item(Key={"job_id": "job-1"})["Item"]
    assert job["status"] == "Failed" and job["total_tokens"] == 1500


def test_failed_never_replaces_success(aws):
    _start_job()
    _report(aws, "Success")
    _report(aws, "Failed", error="late failure report")
    # also when Success lands between the Lambda's read and its write
    assert aws._update_job(_table(), "job-1", {"status": "Failed"}, keep_success=True) is False
    job = _table().get_item(Key={"job_id": "job-1"})["Item"]
    assert job["status"] == "Success"
    assert aws.sent == ["Deep Insight Job Completed"]


def test_legacy_token_usage_trigger_skips_new_runtime(aws):
    _start_job(session_id=SESSION)
    _put(OUTPUT + "token_usage.json", TOKENS)
    aws.handler(_s3_event(OUTPUT + "token_usage.json"), None)
    assert _table().get_item(Key={"job_id": "job-1"})["Item"]["status"] == "Start"


def test_legacy_token_usage_trigger_still_works_for_old_runtime(aws):
    _start_job(session_id=SESSION)
    _put(OUTPUT + "token_usage.json", {k: v for k, v in TOKENS.items() if k != "job_id"})
    aws.handler(_s3_event(OUTPUT + "token_usage.json"), None)
    job = _table().get_item(Key={"job_id": "job-1"})["Item"]
    assert job["status"] == "Success" and job["total_tokens"] == 1500


def test_sweep_marks_only_stale_start_jobs(aws):
    now = int(time.time())
    _start_job("stale", started_at=now - 3 * 3600)
    _start_job("fresh", started_at=now - 600)
    _table().put_item(Item={"job_id": "done", "status": "Success", "started_at": now - 5 * 3600})
    aws.handler({"source": "aws.events", "detail-type": "Scheduled Event"}, None)
    status = {j: _table().get_item(Key={"job_id": j})["Item"]["status"] for j in ["stale", "fresh", "done"]}
    assert status == {"stale": "Failed", "fresh": "Start", "done": "Success"}
    assert "No completion signal" in _table().get_item(Key={"job_id": "stale"})["Item"]["error_message"]
    assert aws.sent == ["Deep Insight Job Failed"]


def test_sweep_keeps_a_long_job_with_a_fresh_heartbeat(aws):
    # 3 hours in (plan revisions, HITL waits, long Coder/Reporter), trace just uploaded
    _start_job("long", started_at=int(time.time()) - 3 * 3600)
    _put("deep-insight/traces/long/events.jsonl", {})
    aws.handler({"source": "aws.events"}, None)
    assert _table().get_item(Key={"job_id": "long"})["Item"]["status"] == "Start"
    assert aws.sent == []


def test_sweep_marks_a_job_whose_heartbeat_stopped(aws, monkeypatch):
    now = int(time.time())
    _start_job("dead", started_at=now - 50 * 60)
    _start_job("quiet", started_at=now - 50 * 60)
    beats = {"dead": now - 40 * 60, "quiet": now - 10 * 60}
    monkeypatch.setattr(aws, "_trace_heartbeat", lambda s3, job_id: beats[job_id])
    aws.handler({"source": "aws.events"}, None)
    dead = _table().get_item(Key={"job_id": "dead"})["Item"]
    assert dead["status"] == "Failed" and "No sign of life" in dead["error_message"]
    assert _table().get_item(Key={"job_id": "quiet"})["Item"]["status"] == "Start"


def test_late_success_overrides_sweep(aws):
    _start_job(started_at=int(time.time()) - 3 * 3600)
    aws.handler({"source": "aws.events"}, None)
    _report(aws, "Success")
    job = _table().get_item(Key={"job_id": "job-1"})["Item"]
    assert job["status"] == "Success" and "error_message" not in job
