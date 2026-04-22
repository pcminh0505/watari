"""Unit tests for the API CLI parser + subcommand wiring.

We don't exercise the DB-touching branches (``create-key`` / ``revoke-key``
/ ``list-keys``) here — those need a live Postgres and belong in the
integration suite. Instead we verify:

    1. Legacy ``--host/--port/--reload`` still parses without a subcommand.
    2. Each subcommand is registered with its own required/optional args.
    3. ``serve`` is the implicit default when no subcommand is supplied.
    4. ``main(argv)`` dispatches to uvicorn for ``serve`` without actually
       binding a port (we stub uvicorn.run).
"""

from __future__ import annotations

from typing import Any

import pytest
from pokeprice_api import cli


def test_parser_accepts_legacy_top_level_flags() -> None:
    args = cli.build_parser().parse_args(
        ["--host", "127.0.0.1", "--port", "9000", "--reload"],
    )
    assert args.cmd is None  # no subcommand → treated as serve
    assert args.host == "127.0.0.1"
    assert args.port == 9000
    assert args.reload is True


def test_parser_serve_subcommand_has_flags() -> None:
    args = cli.build_parser().parse_args(["serve", "--port", "8080"])
    assert args.cmd == "serve"
    assert args.port == 8080


def test_parser_create_key_requires_owner() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["create-key"])


def test_parser_create_key_accepts_tier() -> None:
    args = cli.build_parser().parse_args(
        ["create-key", "--owner", "dev@example.com", "--tier", "paid"],
    )
    assert args.cmd == "create-key"
    assert args.owner == "dev@example.com"
    assert args.tier == "paid"


def test_parser_revoke_key_requires_prefix() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["revoke-key"])
    args = cli.build_parser().parse_args(["revoke-key", "pk_abc123"])
    assert args.cmd == "revoke-key"
    assert args.prefix == "pk_abc123"


def test_parser_list_keys_include_revoked_flag() -> None:
    args = cli.build_parser().parse_args(["list-keys"])
    assert args.cmd == "list-keys"
    assert args.include_revoked is False

    args2 = cli.build_parser().parse_args(["list-keys", "--include-revoked"])
    assert args2.include_revoked is True


def test_main_defaults_to_serve_and_calls_uvicorn(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, Any] = {}

    class _FakeUvicorn:
        @staticmethod
        def run(app: str, **kwargs: Any) -> None:
            captured["app"] = app
            captured.update(kwargs)

    # cli.main imports uvicorn lazily; intercept it via sys.modules.
    import sys

    monkeypatch.setitem(sys.modules, "uvicorn", _FakeUvicorn)

    cli.main(["--host", "127.0.0.1", "--port", "9100"])

    assert captured["app"] == "pokeprice_api.main:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9100
    assert captured["reload"] is False
