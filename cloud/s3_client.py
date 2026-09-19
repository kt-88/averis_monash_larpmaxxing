"""S3 upload/download stubs for the generated report. Not wired into the pipeline yet."""
import os

import boto3

BUCKET = os.environ.get("AWS_S3_BUCKET", "shipping-doc-checker")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    return _client


def upload_report(local_path: str, key: str = "submission.json") -> str:
    """Upload a local report file to S3. Returns the S3 key.

    STUB: no retry/error handling yet.
    """
    _get_client().upload_file(local_path, BUCKET, key)
    return key


def download_report(key: str, local_path: str) -> str:
    """Download a report file from S3 to a local path. Returns the local path.

    STUB: no retry/error handling yet.
    """
    _get_client().download_file(BUCKET, key, local_path)
    return local_path
