"""CLI: ``python -m watari_cardrush [--set X] [--era Y] [--all] ...``.

Examples:
    # Single set
    uv run python -m watari_cardrush --set SV2A

    # All SV-era sets
    uv run python -m watari_cardrush --era SV

    # Everything in the catalog
    uv run python -m watari_cardrush --all

    # Diagnostic / smoke
    uv run python -m watari_cardrush --set SV2A --rarity AR --dry-run --limit-pages 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from watari_cardrush.run import (
    list_all_sets,
    list_sets_for_era,
    scrape_sets,
)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="watari_cardrush",
        description="Crawl Cardrush listings by rarity bucket.",
    )
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--set",
        dest="sets",
        action="append",
        help="Scrape a single set. Repeatable. (e.g. --set SV2A --set M2A)",
    )
    scope.add_argument(
        "--era",
        dest="era",
        help="Scrape every set in an era block (e.g. SV, M, ME).",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Scrape every set in the catalog.",
    )
    p.add_argument(
        "--rarity",
        dest="rarities",
        action="append",
        help="Restrict to one or more rarity codes (repeatable, e.g. --rarity AR).",
    )
    p.add_argument(
        "--max-pages",
        dest="max_pages",
        type=int,
        default=30,
        help="Safety cap on pages per (set, rarity). Default: 30.",
    )
    p.add_argument(
        "--limit-pages",
        dest="limit_pages",
        type=int,
        default=None,
        help="Alias for --max-pages, for smoke tests.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and parse, but don't write to DB or MinIO.",
    )
    p.add_argument(
        "--impersonate",
        default="chrome124",
        help="curl_cffi TLS fingerprint to use. Default: chrome124.",
    )
    p.add_argument("--log-level", default="INFO")
    return p


async def _resolve_sets(args: argparse.Namespace) -> list[str]:
    if args.sets:
        return [s.upper() for s in args.sets]
    if args.era:
        return await list_sets_for_era(args.era)
    if args.all:
        return await list_all_sets()
    return []


async def _dispatch(args: argparse.Namespace) -> int:
    set_codes = await _resolve_sets(args)
    if not set_codes:
        print("no sets resolved from arguments; nothing to do", file=sys.stderr)
        return 2

    max_pages = args.limit_pages or args.max_pages
    summaries = await scrape_sets(
        set_codes,
        rarities_filter=args.rarities,
        max_pages=max_pages,
        dry_run=args.dry_run,
        impersonate=args.impersonate,
    )
    print(json.dumps(summaries, indent=2, ensure_ascii=False, default=str))
    return 0


def main() -> None:
    args = _build_parser().parse_args()
    _configure_logging(args.log_level)
    sys.exit(asyncio.run(_dispatch(args)))


if __name__ == "__main__":
    main()
