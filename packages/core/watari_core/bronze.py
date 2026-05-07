"""Bronze layer — raw HTML/JSON storage in MinIO (S3-compatible)."""

import gzip
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from watari_core.config import settings

_MIN_COMPRESS_BYTES = 1024  # skip gzip for tiny payloads (overhead > savings)


def _compress_opts(body: bytes, key_suffix: str) -> tuple[bytes, dict[str, str]]:
    """Return (body, extra_put_kwargs) with gzip compression and ContentType."""
    if key_suffix.endswith(".html"):
        content_type = "text/html; charset=utf-8"
    elif key_suffix.endswith(".json"):
        content_type = "application/json"
    else:
        content_type = "application/octet-stream"

    extra: dict[str, str] = {"ContentType": content_type}
    if len(body) >= _MIN_COMPRESS_BYTES:
        body = gzip.compress(body, compresslevel=6)
        extra["ContentEncoding"] = "gzip"
    return body, extra


# Reuse a single client for the process lifetime. boto3 clients hold circular
# references (event system, credential chain, connection pools) that prevent
# immediate GC — creating one per write call leaks memory across a long scrape run.
_s3_client: Any = None


def _get_s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
    return _s3_client


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
    body, extra = _compress_opts(body, key_suffix)
    s3.put_object(Bucket=bucket, Key=key, Body=body, **extra)
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
    body, extra = _compress_opts(body, key_suffix)
    s3.put_object(Bucket=bucket, Key=key, Body=body, **extra)
    return key


def setup_lifecycle(bucket: str | None = None, *, days: int = 90) -> None:
    """Install an expiration lifecycle rule on the bronze bucket.

    Idempotent — safe to run multiple times (overwrites the existing rule).
    Call once after provisioning a new bucket or changing the retention period.
    """
    bucket = bucket or settings.s3_bucket_bronze
    s3 = _get_s3_client()
    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": f"expire-bronze-{days}d",
                    "Status": "Enabled",
                    "Prefix": "bronze/",
                    "Expiration": {"Days": days},
                }
            ]
        },
    )
