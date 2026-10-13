"""
Job Tracker — DynamoDB write functions for job lifecycle tracking.

Entry points called from app.py:
  - track_job_start()  : called at /analyze (writes Start record)
  - track_job_link()   : called at workflow_complete (links session_id)
  - track_job_failure() : called on SSE error (writes Failed + SNS notification)
  - get_job_status()   : called at /jobs/{upload_id}/status (browser lost the stream)

All functions are non-breaking: they skip silently if DYNAMODB_TABLE_NAME is not set,
and catch all exceptions to never affect the analysis workflow.
"""

import logging
import os
import time

import boto3

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")


def _get_table():
    """Return DynamoDB Table resource. Returns None if table name is not configured."""
    if not DYNAMODB_TABLE_NAME:
        return None
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return dynamodb.Table(DYNAMODB_TABLE_NAME)


def track_job_start(upload_id: str, query: str, data_filename: str = "", column_def_filename: str = ""):
    """Write Start record to DynamoDB when /analyze is called.

    Args:
        upload_id: UUID from the upload step, used as job_id (DynamoDB PK).
        query: User's analysis query (truncated to 500 chars).
        data_filename: Original data file name (optional, empty for Phase 1).
        column_def_filename: Column definitions file name (optional, empty for Phase 1).
    """
    table = _get_table()
    if not table:
        return

    try:
        table.put_item(Item={
            "job_id": upload_id,
            "status": "Start",
            "user_query": query[:500],
            "data_filename": data_filename,
            "column_def_filename": column_def_filename,
            "started_at": int(time.time()),
        })
        logger.info(f"Job tracking: Start recorded for job_id={upload_id}")
    except Exception as e:
        logger.warning(f"Job tracking: Start write failed (non-breaking): {e}")


def track_job_link(upload_id: str, session_id: str):
    """Link AgentCore session_id to the job record at workflow_complete.

    This enables the Lambda function (triggered by S3 event) to find the
    DynamoDB record via the SessionIdIndex GSI.

    Args:
        upload_id: The job_id (DynamoDB PK).
        session_id: AgentCore session ID from the workflow_complete SSE event.
    """
    table = _get_table()
    if not table or not session_id:
        return

    try:
        table.update_item(
            Key={"job_id": upload_id},
            UpdateExpression="SET session_id = :sid",
            ExpressionAttributeValues={":sid": session_id},
        )
        logger.info(f"Job tracking: session_id={session_id} linked to job_id={upload_id}")
    except Exception as e:
        logger.warning(f"Job tracking: Link write failed (non-breaking): {e}")


def track_job_failure(upload_id: str, error_message: str):
    """Mark job as Failed and send SNS failure notification.

    Called when the SSE stream from AgentCore errors out or disconnects.
    The runtime and the ops Lambda may already have recorded Success by then
    (the stream can break after the run reported its result). Success is
    final: the write is conditional, and no failure mail goes out for it.

    Args:
        upload_id: The job_id (DynamoDB PK).
        error_message: Error description (truncated to 1000 chars).
    """
    table = _get_table()
    if not table:
        return

    try:
        table.update_item(
            Key={"job_id": upload_id},
            UpdateExpression="SET #s = :status, ended_at = :ended, error_message = :err",
            ConditionExpression="attribute_not_exists(#s) OR #s <> :success",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "Failed",
                ":success": "Success",
                ":ended": int(time.time()),
                ":err": error_message[:1000],
            },
        )
        logger.info(f"Job tracking: Failed recorded for job_id={upload_id}")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        logger.info(f"Job tracking: job_id={upload_id} already Success — stream error not recorded")
        return
    except Exception as e:
        logger.warning(f"Job tracking: Failure write failed (non-breaking): {e}")

    # Send SNS failure notification (Step 3)
    _notify_failure(upload_id, error_message)


def get_job_status(upload_id: str):
    """Status of a job for a browser that lost its analysis stream.

    The runtime keeps running when the browser's connection drops and reports
    the final status itself, so the page can follow the job here instead of
    treating the disconnect as a failure.

    The error message is left out: it can hold raw boto3/IAM text (ARNs,
    account ID) that stays admin-only, like everywhere else in app.py.

    Returns:
        {"status", "session_id"}, or None if tracking is not configured or
        the job is unknown.
    """
    table = _get_table()
    if not table:
        return None

    try:
        item = table.get_item(Key={"job_id": upload_id}).get("Item")
    except Exception as e:
        logger.warning(f"Job tracking: status read failed: {e}")
        return None
    if not item:
        return None
    return {
        "status": item.get("status", ""),
        "session_id": item.get("session_id", ""),
    }


def _notify_failure(upload_id: str, error_message: str):
    """Publish failure notification to SNS topic.

    Provides immediate failure alert without waiting for Lambda.
    Skips silently if SNS_TOPIC_ARN is not configured.
    """
    if not SNS_TOPIC_ARN:
        return

    try:
        sns = boto3.client("sns", region_name=AWS_REGION)
        message = (
            "Deep Insight Job Failed\n"
            "\n"
            f"Job ID: {upload_id}\n"
            f"Status: Failed\n"
            f"Error: {error_message[:500]}\n"
        )
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="Deep Insight Job Failed",
            Message=message,
        )
        logger.info(f"Job tracking: Failure notification sent for job_id={upload_id}")
    except Exception as e:
        logger.warning(f"Job tracking: SNS publish failed (non-breaking): {e}")
