"""CLI for the read API — online mode.

Subcommands:
    ``serve``  Run the uvicorn HTTP server (default).

Key-management and MV-refresh commands removed in online mode
(no PostgreSQL required).
"""

from __future__ import annotations

import argparse


def _add_serve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Hot-reload on code changes (dev only).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="watari-api")
    _add_serve_args(parser)
    sub = parser.add_subparsers(dest="cmd")
    _add_serve_args(sub.add_parser("serve", help="Run the HTTP server (default)."))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    import uvicorn

    uvicorn.run(
        "watari_api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
