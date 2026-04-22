"""CLI entry point: `python -m pokeprice_snkrdunk --era sv2a [--limit N]`."""

from __future__ import annotations

import argparse
import asyncio
import sys

from pokeprice_snkrdunk.run import scrape_era


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape SNKRDUNK sold prices for an era")
    p.add_argument("--era", required=True, help="Era / set id (e.g. sv2a)")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max sales entries per card (default: all pages)",
    )
    p.add_argument(
        "--polite-delay",
        type=float,
        default=0.25,
        help="Seconds to sleep between API pages (default: 0.25)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    asyncio.run(
        scrape_era(
            args.era,
            history_limit=args.limit,
            polite_delay_sec=args.polite_delay,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
