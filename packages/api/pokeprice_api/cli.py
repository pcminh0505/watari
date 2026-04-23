"""CLI for the read API.

Subcommands:
    ``serve``       Run the uvicorn HTTP server.
    ``create-key``  Mint a new API key; prints the plaintext exactly once.
    ``revoke-key``  Revoke an API key by its ``key_prefix``.
    ``list-keys``   List stored keys (hashes and plaintexts are never shown).
    ``refresh-mvs`` Manually refresh the three price materialized views.

The ``serve`` subcommand is also the implicit default so the legacy
invocation ``pokeprice-api --host ... --port ... --reload`` keeps working.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from pokeprice_core.db import async_session_factory
from pokeprice_core.models import ApiKey
from pokeprice_core.mvs import refresh_price_mvs
from sqlalchemy import select

from pokeprice_api.auth import mint_api_key

SERVE_SUBCOMMANDS = {"serve"}
KEY_SUBCOMMANDS = {"create-key", "revoke-key", "list-keys"}
OPS_SUBCOMMANDS = {"refresh-mvs"}


async def _create_key(owner: str, tier: str) -> None:
    plaintext, key_prefix, key_hash = mint_api_key()
    async with async_session_factory() as session:
        row = ApiKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            owner_email=owner,
            tier=tier,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    print(f"id        : {row.id}")
    print(f"owner     : {owner}")
    print(f"tier      : {tier}")
    print(f"prefix    : {key_prefix}")
    print(f"plaintext : {plaintext}")
    print()
    print("This is the only time the plaintext key will be shown. Store it now.")


async def _revoke_key(prefix: str) -> None:
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(ApiKey).where(ApiKey.key_prefix == prefix),
            )
        ).scalar_one_or_none()
        if row is None:
            raise SystemExit(f"no api key with prefix {prefix!r}")
        if row.revoked_at is not None:
            print(f"already revoked at {row.revoked_at.isoformat()}")
            return
        row.revoked_at = datetime.now(UTC)
        await session.commit()
        print(f"revoked {row.key_prefix} (id={row.id}, owner={row.owner_email})")


async def _refresh_mvs(concurrently: bool) -> None:
    async with async_session_factory() as session:
        refreshed = await refresh_price_mvs(session, concurrently=concurrently)
    mode = "CONCURRENTLY" if concurrently else "non-concurrently"
    print(f"refreshed {len(refreshed)} MV(s) {mode}:")
    for name in refreshed:
        print(f"  - {name}")


async def _list_keys(include_revoked: bool) -> None:
    async with async_session_factory() as session:
        rows = list(
            (await session.execute(select(ApiKey).order_by(ApiKey.id))).scalars().all(),
        )
    if not rows:
        print("(no api keys)")
        return
    for row in rows:
        if row.revoked_at is not None and not include_revoked:
            continue
        state = "revoked" if row.revoked_at is not None else "active"
        last = row.last_used_at.isoformat() if row.last_used_at is not None else "never"
        print(
            f"{row.key_prefix:14}  {row.tier:8}  {state:8}  {row.owner_email:32}  last_used={last}",
        )


def _add_serve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Hot-reload on code changes (dev only).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pokeprice-api")
    # Top-level serve flags so legacy `pokeprice-api --host ... --port ...`
    # invocations keep working without requiring the explicit `serve`.
    _add_serve_args(parser)

    sub = parser.add_subparsers(dest="cmd")
    _add_serve_args(sub.add_parser("serve", help="Run the HTTP server (default)."))

    ck = sub.add_parser("create-key", help="Mint a new API key and print it once.")
    ck.add_argument("--owner", required=True, help="Owner email, stored as-is.")
    ck.add_argument(
        "--tier",
        default="free",
        help="Rate-limit tier (must be known to api_rate_limits).",
    )

    rk = sub.add_parser("revoke-key", help="Revoke a key by its prefix (e.g. pk_ab12cd).")
    rk.add_argument("prefix")

    lk = sub.add_parser("list-keys", help="List all API keys (metadata only).")
    lk.add_argument(
        "--include-revoked",
        action="store_true",
        help="Include revoked keys in the output.",
    )

    rm = sub.add_parser(
        "refresh-mvs",
        help="Refresh the three price materialized views.",
    )
    rm.add_argument(
        "--no-concurrently",
        action="store_true",
        help=(
            "Use plain REFRESH (takes an AccessExclusive lock). "
            "Default is CONCURRENTLY; useful as a fallback if a unique index is missing."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    cmd = args.cmd or "serve"
    if cmd in SERVE_SUBCOMMANDS:
        # Imported lazily so key management commands don't need uvicorn.
        import uvicorn

        uvicorn.run(
            "pokeprice_api.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    elif cmd == "create-key":
        asyncio.run(_create_key(args.owner, args.tier))
    elif cmd == "revoke-key":
        asyncio.run(_revoke_key(args.prefix))
    elif cmd == "list-keys":
        asyncio.run(_list_keys(args.include_revoked))
    elif cmd == "refresh-mvs":
        asyncio.run(_refresh_mvs(concurrently=not args.no_concurrently))
    else:  # pragma: no cover — argparse rejects unknown subcommands first
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
