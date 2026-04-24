"""CLI: ``python -m watari_catalog <command> [options]``.

Commands (v3 pipeline):

    seed-sets
        Upsert ``Set`` rows from ``data/sets/*.yml``.

    bootstrap-set --set SV2A [--set M2A] [--no-fetch]
        Build / refresh the per-card YML tree for a set from Pokellector
        (primary), TCGdex (fallback), and Cardrush (variant hints).
        Writes ``data/cards/{set_code}/{local_id}.yml`` preserving the
        ``# manual: true`` opt-out on existing files.

    seed-cards [--set SV2A]
        Load the YML tree into ``artworks`` and ``cards`` tables.

    verify
        Print a catalog health snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("watari_catalog")
    p.add_argument("--log-level", default="INFO")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("seed-sets", help="Upsert Set rows from data/sets/*.yml")

    b = sub.add_parser(
        "bootstrap-set",
        help="Build data/cards/{set_code}/*.yml from Pokellector + TCGdex + Cardrush",
    )
    b.add_argument("--set", dest="sets", action="append", required=True)
    b.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip network calls; rebuild from MinIO bronze cache only",
    )

    s = sub.add_parser(
        "seed-cards",
        help="Load data/cards/*/*.yml into artworks/cards tables",
    )
    s.add_argument("--set", dest="sets", action="append", default=None)

    sub.add_parser("verify", help="Print catalog health snapshot")

    return p


async def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "seed-sets":
        from watari_catalog import seed_sets

        await seed_sets.run()
        return 0
    if args.command == "bootstrap-set":
        from watari_catalog import bootstrap

        await bootstrap.run(args.sets, no_fetch=args.no_fetch)
        return 0
    if args.command == "seed-cards":
        from watari_catalog import seed_cards

        await seed_cards.run(args.sets)
        return 0
    if args.command == "verify":
        from watari_catalog import verify

        await verify.run()
        return 0
    return 1


def main() -> None:
    args = _build_parser().parse_args()
    _configure_logging(args.log_level)
    sys.exit(asyncio.run(_dispatch(args)))


if __name__ == "__main__":
    main()
