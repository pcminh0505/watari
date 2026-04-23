"""Bronze layer — raw HTML/JSON storage in MinIO (S3-compatible)."""

from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from pokeprice_core.config import settings


def _get_s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )


def ensure_bucket(bucket: str | None = None) -> None:
    """Create the bronze bucket if it doesn't exist."""
    bucket = bucket or settings.s3_bucket_bronze
    s3 = _get_s3_client()
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)


def write_bronze(
    source: str,
    card_id: str,
    run_id: int,
    observed_at: datetime,
    payload: str | bytes,
    *,
    key_suffix: str = "raw",
    bucket: str | None = None,
) -> str:
    """Write raw scrape data to MinIO (card-scoped). Returns the S3 key.

    ``key_suffix`` lets callers disambiguate multiple objects written for the
    same (card, run) — e.g. paginated API pages (``sales-p1.json``, ``sales-p2.json``).
    """
    bucket = bucket or settings.s3_bucket_bronze
    dt_str = observed_at.strftime("%Y-%m-%d")
    key = f"bronze/{source}/dt={dt_str}/card={card_id}/run={run_id}/{key_suffix}"

    s3 = _get_s3_client()
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    s3.put_object(Bucket=bucket, Key=key, Body=body)
    return key


def write_bronze_set(
    source: str,
    set_code: str,
    run_id: int,
    observed_at: datetime,
    payload: str | bytes,
    *,
    key_suffix: str,
    bucket: str | None = None,
) -> str:
    """Write raw scrape data to MinIO (set-scoped). Returns the S3 key.

    Use this when a single HTTP response covers many cards at once (e.g. a
    Cardrush search-results page listing dozens of cards under one rarity).
    """
    bucket = bucket or settings.s3_bucket_bronze
    dt_str = observed_at.strftime("%Y-%m-%d")
    key = f"bronze/{source}/dt={dt_str}/set={set_code}/run={run_id}/{key_suffix}"

    s3 = _get_s3_client()
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    s3.put_object(Bucket=bucket, Key=key, Body=body)
    return key
