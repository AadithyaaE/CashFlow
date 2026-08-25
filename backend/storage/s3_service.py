"""AWS S3 storage for uploaded invoice files.

Centralizes all S3 interaction behind a few small functions so main.py never
imports boto3 directly. The bucket is expected to be private — nothing here
ever sets an object ACL to public; the only way to read a file back out is a
short-lived presigned URL, generated per-request by the caller after it has
already verified the requesting user owns the invoice.

Credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) are never read by
this module — boto3's default credential chain picks them up from the
environment on its own. Only AWS_REGION and AWS_S3_BUCKET are read here,
and neither is ever logged.
"""

import os
import re
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError

AWS_REGION = os.getenv("AWS_REGION")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET")

_client = None


class S3StorageError(Exception):
    """Raised on any S3 operation failure, so callers can handle storage
    errors without depending on botocore's exception types directly."""


def is_configured() -> bool:
    return bool(AWS_S3_BUCKET)


def _get_client():
    global _client
    if _client is None:
        # boto3 can otherwise build presigned URLs against the global
        # s3.amazonaws.com host while signing them for the regional host,
        # which S3 rejects as SignatureDoesNotMatch. Pinning endpoint_url
        # keeps both consistent.
        endpoint_url = f"https://s3.{AWS_REGION}.amazonaws.com" if AWS_REGION else None
        _client = boto3.client("s3", region_name=AWS_REGION, endpoint_url=endpoint_url)
    return _client


def _sanitize_filename(filename: str) -> str:
    # Mirrors the exact sanitization the old local-upload path already used.
    name = os.path.basename(filename or "file")
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def build_object_key(user_id: int, original_filename: str) -> str:
    """invoices/<user_id>/<uuid>_<sanitized-filename>"""
    safe_name = _sanitize_filename(original_filename)
    return f"invoices/{user_id}/{uuid.uuid4().hex}_{safe_name}"


def upload_file(file_bytes: bytes, key: str, content_type: str | None = None) -> None:
    if not is_configured():
        raise S3StorageError("AWS_S3_BUCKET is not configured on the server.")

    extra_args = {"ContentType": content_type} if content_type else {}

    try:
        _get_client().put_object(Bucket=AWS_S3_BUCKET, Key=key, Body=file_bytes, **extra_args)
    except (ClientError, BotoCoreError) as exc:
        raise S3StorageError("Could not upload the file to S3.") from exc


def delete_file(key: str | None) -> None:
    """No-ops on a falsy key (e.g. an invoice that was never uploaded, or
    already has no associated file) instead of making callers guard first."""
    if not key or not is_configured():
        return

    try:
        _get_client().delete_object(Bucket=AWS_S3_BUCKET, Key=key)
    except (ClientError, BotoCoreError) as exc:
        raise S3StorageError("Could not delete the file from S3.") from exc


def generate_presigned_url(key: str, expires_in: int = 300) -> str:
    if not is_configured():
        raise S3StorageError("AWS_S3_BUCKET is not configured on the server.")

    try:
        return _get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": AWS_S3_BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )
    except (ClientError, BotoCoreError) as exc:
        raise S3StorageError("Could not generate a download link.") from exc
