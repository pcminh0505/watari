"""Unit tests for bronze layer — compression, content-type, and lifecycle."""

import gzip
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from watari_core.bronze import (
    _MIN_COMPRESS_BYTES,
    _compress_opts,
    setup_lifecycle,
    write_bronze,
    write_bronze_set,
)


# ── _compress_opts ───────────────────────────────────────────────────────────


class TestCompressOpts:
    def test_large_html_compressed(self):
        body = b"x" * _MIN_COMPRESS_BYTES
        out_body, extra = _compress_opts(body, "page.html")
        assert extra["ContentType"] == "text/html; charset=utf-8"
        assert extra["ContentEncoding"] == "gzip"
        assert gzip.decompress(out_body) == body

    def test_large_json_compressed(self):
        body = b"y" * _MIN_COMPRESS_BYTES
        out_body, extra = _compress_opts(body, "data.json")
        assert extra["ContentType"] == "application/json"
        assert extra["ContentEncoding"] == "gzip"
        assert gzip.decompress(out_body) == body

    def test_small_payload_not_compressed(self):
        body = b"z" * (_MIN_COMPRESS_BYTES - 1)
        out_body, extra = _compress_opts(body, "data.json")
        assert extra["ContentType"] == "application/json"
        assert "ContentEncoding" not in extra
        assert out_body == body

    def test_unknown_suffix_octet_stream(self):
        body = b"a" * _MIN_COMPRESS_BYTES
        _, extra = _compress_opts(body, "raw")
        assert extra["ContentType"] == "application/octet-stream"

    def test_exact_threshold_compressed(self):
        body = b"b" * _MIN_COMPRESS_BYTES
        _, extra = _compress_opts(body, "page.html")
        assert "ContentEncoding" in extra

    def test_one_below_threshold_not_compressed(self):
        body = b"c" * (_MIN_COMPRESS_BYTES - 1)
        _, extra = _compress_opts(body, "page.html")
        assert "ContentEncoding" not in extra


# ── write_bronze ─────────────────────────────────────────────────────────────


class TestWriteBronze:
    @patch("watari_core.bronze._get_s3_client")
    def test_returns_correct_key(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        dt = datetime(2026, 5, 7, 12, 0, 0)

        key = write_bronze(
            source="snkrdunk",
            card_id="jp-sv2a-089-normal",
            run_id=42,
            observed_at=dt,
            payload=b"{}",
            key_suffix="sales-p1.json",
            bucket="test-bucket",
        )

        assert key == "bronze/snkrdunk/dt=2026-05-07/card=jp-sv2a-089-normal/run=42/sales-p1.json"

    @patch("watari_core.bronze._get_s3_client")
    def test_large_html_written_with_gzip(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        dt = datetime(2026, 5, 7)
        large_payload = "A" * _MIN_COMPRESS_BYTES

        write_bronze(
            source="cardrush",
            card_id="jp-sv2a-089-normal",
            run_id=1,
            observed_at=dt,
            payload=large_payload,
            key_suffix="listing.html",
            bucket="test-bucket",
        )

        _, kwargs = mock_s3.put_object.call_args
        assert kwargs["ContentEncoding"] == "gzip"
        assert kwargs["ContentType"] == "text/html; charset=utf-8"
        assert gzip.decompress(kwargs["Body"]) == large_payload.encode("utf-8")

    @patch("watari_core.bronze._get_s3_client")
    def test_small_json_not_compressed(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        dt = datetime(2026, 5, 7)
        small_payload = b'{"a":1}'

        write_bronze(
            source="snkrdunk",
            card_id="jp-sv2a-089-normal",
            run_id=1,
            observed_at=dt,
            payload=small_payload,
            key_suffix="sales.json",
            bucket="test-bucket",
        )

        _, kwargs = mock_s3.put_object.call_args
        assert "ContentEncoding" not in kwargs
        assert kwargs["ContentType"] == "application/json"
        assert kwargs["Body"] == small_payload

    @patch("watari_core.bronze._get_s3_client")
    def test_string_payload_utf8_encoded(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        dt = datetime(2026, 5, 7)
        payload_str = "テスト" * 500  # large enough to trigger compression

        write_bronze(
            source="cardrush",
            card_id="jp-sv2a-001-normal",
            run_id=1,
            observed_at=dt,
            payload=payload_str,
            key_suffix="page.html",
            bucket="test-bucket",
        )

        _, kwargs = mock_s3.put_object.call_args
        assert kwargs["ContentEncoding"] == "gzip"
        decompressed = gzip.decompress(kwargs["Body"])
        assert decompressed == payload_str.encode("utf-8")


# ── write_bronze_set ─────────────────────────────────────────────────────────


class TestWriteBronzeSet:
    @patch("watari_core.bronze._get_s3_client")
    def test_returns_correct_key(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        dt = datetime(2026, 5, 7)

        key = write_bronze_set(
            source="cardrush",
            set_code="SV2A",
            run_id=7,
            observed_at=dt,
            payload=b"data",
            key_suffix="rarity-SAR-p1.html",
            bucket="test-bucket",
        )

        assert key == "bronze/cardrush/dt=2026-05-07/set=SV2A/run=7/rarity-SAR-p1.html"

    @patch("watari_core.bronze._get_s3_client")
    def test_large_html_written_with_gzip(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3
        dt = datetime(2026, 5, 7)
        large_payload = b"Z" * _MIN_COMPRESS_BYTES

        write_bronze_set(
            source="cardrush",
            set_code="SV2A",
            run_id=1,
            observed_at=dt,
            payload=large_payload,
            key_suffix="page.html",
            bucket="test-bucket",
        )

        _, kwargs = mock_s3.put_object.call_args
        assert kwargs["ContentEncoding"] == "gzip"
        assert kwargs["ContentType"] == "text/html; charset=utf-8"


# ── setup_lifecycle ───────────────────────────────────────────────────────────


class TestSetupLifecycle:
    @patch("watari_core.bronze._get_s3_client")
    def test_calls_put_lifecycle_with_correct_days(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        setup_lifecycle(bucket="test-bucket", days=90)

        mock_s3.put_bucket_lifecycle_configuration.assert_called_once()
        _, kwargs = mock_s3.put_bucket_lifecycle_configuration.call_args
        rules = kwargs["LifecycleConfiguration"]["Rules"]
        assert len(rules) == 1
        assert rules[0]["Expiration"]["Days"] == 90
        assert rules[0]["Status"] == "Enabled"
        assert rules[0]["Prefix"] == "bronze/"

    @patch("watari_core.bronze._get_s3_client")
    def test_custom_days(self, mock_get_client):
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        setup_lifecycle(bucket="test-bucket", days=180)

        _, kwargs = mock_s3.put_bucket_lifecycle_configuration.call_args
        rules = kwargs["LifecycleConfiguration"]["Rules"]
        assert rules[0]["Expiration"]["Days"] == 180
        assert rules[0]["ID"] == "expire-bronze-180d"
