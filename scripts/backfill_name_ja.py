#!/usr/bin/env python3
"""Backfill missing ``name_ja`` from Pokellector card detail pages.

Pokellector card detail pages contain a "JPN:" field with the Japanese card name:
    <div><strong>JPN:</strong> <a href="...">ロゼリア</a></div>

This script:
1. Scans all card YMLs for null ``name_ja``.
2. Groups them by set, loads the set's ``pokellector_slug``.
3. Fetches each card's Pokellector detail page using the card-level slug
   from ``sources.pokellector.slug``.
4. Extracts the JPN name and updates the YML file in-place.

Usage:
    # Dry run — show what would be updated
    python scripts/backfill_name_ja.py --dry-run

    # Run for a specific set
    python scripts/backfill_name_ja.py --set SM1S

    # Run for all sets with missing name_ja
    python scripts/backfill_name_ja.py

    # Adjust concurrency and delay
    python scripts/backfill_name_ja.py --concurrency 2 --delay 0.5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import re
import sys
import time
from dataclasses import dataclass, field

import httpx
import yaml
from ruamel.yaml import YAML

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "packages" / "catalog" / "data"
SETS_DIR = DATA_DIR / "sets"
CARDS_DIR = DATA_DIR / "cards"

POKELLECTOR_BASE = "https://jp.pokellector.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# Regex to extract JPN name from card detail page.
# Matches: <strong>JPN:</strong> <a href="...">ロゼリア</a>
_JPN_RE = re.compile(r"JPN:</strong>\s*<a[^>]*>([^<]+)</a>", re.I)

# Also try a plain-text fallback (some older pages may not have the link):
#   <strong>JPN:</strong> ロゼリア
_JPN_PLAIN_RE = re.compile(r"JPN:</strong>\s*([^<\n]+)", re.I)

# Japanese script ranges: Hiragana, Katakana, CJK Unified Ideographs
_HAS_JP_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class CardToBackfill:
    set_code: str
    local_id: str  # zero-padded
    yml_path: pathlib.Path
    pokellector_slug: str  # e.g. "Roselia-Card-1"
    set_pokellector_slug: str  # e.g. "Sword-Expansion"


@dataclass
class BackfillStats:
    scanned: int = 0
    no_pokellector: int = 0
    fetched: int = 0
    updated: int = 0
    not_found: int = 0
    errors: int = 0
    skipped_manual: int = 0
    per_set: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def load_set_pokellector_slug(set_code: str) -> str | None:
    """Load pokellector_slug from the set YML."""
    path = SETS_DIR / f"{set_code.upper()}.yml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # Top-level field in SM/SW/SV era set YMLs; older format had source_refs.
    slug = data.get("pokellector_slug")
    if slug:
        return slug
    refs = data.get("source_refs") or {}
    return refs.get("pokellector_slug")


def find_cards_to_backfill(
    *, target_set: str | None = None,
) -> list[CardToBackfill]:
    """Find all card YMLs with null name_ja that have Pokellector source data."""
    cards: list[CardToBackfill] = []
    set_slugs: dict[str, str | None] = {}

    set_dirs = sorted(CARDS_DIR.iterdir()) if CARDS_DIR.is_dir() else []
    for set_dir in set_dirs:
        if not set_dir.is_dir():
            continue
        set_code = set_dir.name
        if target_set and set_code.upper() != target_set.upper():
            continue

        # Load set pokellector slug (cached)
        if set_code not in set_slugs:
            set_slugs[set_code] = load_set_pokellector_slug(set_code)
        set_poke_slug = set_slugs[set_code]
        if not set_poke_slug:
            continue

        for yml_path in sorted(set_dir.glob("*.yml")):
            data = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
            if not data:
                continue

            # Skip if name_ja already populated
            name_ja = data.get("name_ja")
            if name_ja:
                continue

            # Need pokellector source with a slug
            sources = data.get("sources") or {}
            poke_src = sources.get("pokellector") or {}
            card_slug = poke_src.get("slug")
            if not card_slug:
                continue

            cards.append(
                CardToBackfill(
                    set_code=set_code,
                    local_id=data.get("local_id", yml_path.stem),
                    yml_path=yml_path,
                    pokellector_slug=card_slug,
                    set_pokellector_slug=set_poke_slug,
                )
            )

    return cards


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


def extract_jpn_name(html: str) -> str | None:
    """Extract the Japanese name from a Pokellector card detail page.

    Returns None if the JPN field is missing or contains only ASCII/Latin
    text (some promo cards have the English name in the JPN slot).
    """
    name: str | None = None
    m = _JPN_RE.search(html)
    if m:
        name = m.group(1).strip()
    else:
        m = _JPN_PLAIN_RE.search(html)
        if m:
            name = m.group(1).strip()

    if not name:
        return None

    # Reject if it's just the English name repeated (no Japanese chars)
    if not _HAS_JP_RE.search(name):
        return None

    return name


async def fetch_jpn_names(
    cards: list[CardToBackfill],
    *,
    concurrency: int = 3,
    delay: float = 0.3,
    stats: BackfillStats,
) -> dict[str, str]:
    """Fetch JPN names from Pokellector. Returns {yml_path_str: name_ja}."""
    results: dict[str, str] = {}
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    last_request = [0.0]

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"},
        timeout=30.0,
        follow_redirects=True,
    ) as client:

        async def fetch_one(card: CardToBackfill) -> None:
            async with sem:
                # Rate limit
                async with lock:
                    now = time.monotonic()
                    wait = delay - (now - last_request[0])
                    if wait > 0:
                        await asyncio.sleep(wait)
                    last_request[0] = time.monotonic()

                url = f"{POKELLECTOR_BASE}/{card.set_pokellector_slug}/{card.pokellector_slug}"
                try:
                    resp = await client.get(url)
                    stats.fetched += 1
                    if resp.status_code == 404:
                        logger.warning(
                            "  404: %s/%s → %s",
                            card.set_code, card.local_id, url,
                        )
                        stats.not_found += 1
                        return
                    resp.raise_for_status()

                    name_ja = extract_jpn_name(resp.text)
                    if name_ja:
                        results[str(card.yml_path)] = name_ja
                    else:
                        logger.warning(
                            "  no JPN field: %s/%s → %s",
                            card.set_code, card.local_id, url,
                        )
                        stats.not_found += 1
                except Exception as exc:
                    logger.error(
                        "  error: %s/%s → %s: %s",
                        card.set_code, card.local_id, url, exc,
                    )
                    stats.errors += 1

        # Process in order to keep logs readable
        for card in cards:
            await fetch_one(card)

    return results


# ---------------------------------------------------------------------------
# YML updater
# ---------------------------------------------------------------------------


def update_yml_name_ja(path: pathlib.Path, name_ja: str) -> bool:
    """Update name_ja in a card YML file using ruamel.yaml for round-trip."""
    text = path.read_text(encoding="utf-8")

    # Respect manual marker
    if text.lstrip().startswith("# manual: true"):
        return False

    # Simple text replacement: find `name_ja:` or `name_ja: null` and replace.
    # This avoids ruamel.yaml reformatting the entire file.
    new_text = re.sub(
        r"^(name_ja:)\s*(?:null)?$",
        rf"\1 {name_ja}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if new_text == text:
        return False

    path.write_text(new_text, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill name_ja from Pokellector")
    parser.add_argument("--set", help="Only process this set code")
    parser.add_argument("--dry-run", action="store_true", help="Don't write files")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between requests")
    parser.add_argument("--limit", type=int, default=0, help="Max cards to process (0=all)")
    args = parser.parse_args()

    stats = BackfillStats()

    logger.info("Scanning for cards with missing name_ja...")
    cards = find_cards_to_backfill(target_set=args.set)
    stats.scanned = len(cards)

    if args.limit > 0:
        cards = cards[: args.limit]

    if not cards:
        logger.info("No cards with missing name_ja found.")
        return

    # Group by set for reporting
    by_set: dict[str, int] = {}
    for c in cards:
        by_set[c.set_code] = by_set.get(c.set_code, 0) + 1
    logger.info(
        "Found %d cards to backfill across %d sets:", len(cards), len(by_set)
    )
    for sc, count in sorted(by_set.items()):
        logger.info("  %s: %d cards", sc, count)

    if args.dry_run:
        logger.info("Dry run — would fetch %d Pokellector pages. Exiting.", len(cards))
        return

    logger.info(
        "Fetching from Pokellector (concurrency=%d, delay=%.1fs)...",
        args.concurrency, args.delay,
    )

    # Process set by set for cleaner logging
    total_updated = 0
    for set_code in sorted(by_set.keys()):
        set_cards = [c for c in cards if c.set_code == set_code]
        logger.info("--- %s (%d cards) ---", set_code, len(set_cards))

        name_map = await fetch_jpn_names(
            set_cards,
            concurrency=args.concurrency,
            delay=args.delay,
            stats=stats,
        )

        set_updated = 0
        for card in set_cards:
            key = str(card.yml_path)
            if key not in name_map:
                continue
            name_ja = name_map[key]
            if update_yml_name_ja(card.yml_path, name_ja):
                set_updated += 1
                logger.debug("  ✓ %s/%s → %s", card.set_code, card.local_id, name_ja)
            else:
                stats.skipped_manual += 1

        total_updated += set_updated
        stats.per_set[set_code] = set_updated
        logger.info("  Updated %d / %d YMLs for %s", set_updated, len(set_cards), set_code)

    stats.updated = total_updated
    logger.info("=== Backfill complete ===")
    logger.info("  Scanned:      %d", stats.scanned)
    logger.info("  Fetched:      %d", stats.fetched)
    logger.info("  Updated:      %d", stats.updated)
    logger.info("  Not found:    %d", stats.not_found)
    logger.info("  Errors:       %d", stats.errors)
    logger.info("  Manual skip:  %d", stats.skipped_manual)


if __name__ == "__main__":
    asyncio.run(main())
