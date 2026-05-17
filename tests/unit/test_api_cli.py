"""Unit tests for the API CLI parser + subcommand wiring — online mode.

In online mode the CLI only exposes the ``serve`` subcommand (key-management
and MV-refresh commands have been removed). We verify:

    1. Legacy ``--host/--port/--reload`` top-level flags still parse.
    2. The ``serve`` subcommand registers its own flags.
    3. ``main(argv)`` dispatches to uvicorn without actually binding a port
       (uvicorn.run is stubbed).
"""

from __future__ import annotations

from typing import Any

from watari_api import cli


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

    assert captured["app"] == "watari_api.main:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9100
    assert captured["reload"] is False
