"""S3 utility functions for feedback handling."""

import os
import json
import logging
import boto3

logger = logging.getLogger(__name__)


def get_s3_feedback_key(request_id: str) -> str:
    """Generate S3 key for feedback file."""
    return f"deep-insight/feedback/{request_id}.json"


def check_s3_feedback(request_id: str) -> dict:
    """
    Check S3 for feedback file from client.

    Returns:
        dict: Feedback data if found, None otherwise
    """
    s3_bucket = os.getenv('S3_BUCKET_NAME')
    if not s3_bucket:
        logger.warning("S3_BUCKET_NAME not set, cannot check for feedback")
        return None

    s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    feedback_key = get_s3_feedback_key(request_id)

    try:
        response = s3_client.get_object(Bucket=s3_bucket, Key=feedback_key)
        feedback_data = json.loads(response['Body'].read().decode('utf-8'))
        logger.info(f"Feedback received from S3: {feedback_key}")
        return feedback_data
    except s3_client.exceptions.NoSuchKey:
        return None
    except Exception as e:
        logger.warning(f"Error checking S3 feedback: {e}")
        return None


def delete_s3_feedback(request_id: str) -> bool:
    """
    Delete feedback file from S3 after processing.

    Returns:
        bool: True if deleted successfully, False otherwise
    """
    s3_bucket = os.getenv('S3_BUCKET_NAME')
    if not s3_bucket:
        return False

    s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    feedback_key = get_s3_feedback_key(request_id)

    try:
        s3_client.delete_object(Bucket=s3_bucket, Key=feedback_key)
        logger.info(f"Feedback file deleted: {feedback_key}")
        return True
    except Exception as e:
        logger.warning(f"Error deleting S3 feedback: {e}")
        return False
