"""Cardrush scrape orchestrator (rarity-bucket crawl, curl_cffi-backed)."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from watari_core.bronze import ensure_bucket, write_bronze_set
from watari_core.db import async_session_factory
from watari_core.ingestion import (
    finish_scrape_run,
    insert_price_points,
    start_scrape_run,
    upsert_card_state,
)
from watari_core.models import Card, Set, SourceEnum
from watari_core.mvs import refresh_price_mvs_if_needed
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watari_cardrush.client import CardrushClient
from watari_cardrush.parser import (
    ListingRow,
    listing_row_to_price_point,
    parse_listing_rows,
)

logger = logging.getLogger(__name__)

SOURCE = SourceEnum.cardrush.value


@dataclass
class ScrapeSetResult:
    set_code: str
    run_id: int | None = None
    pages_fetched: int = 0
    listings_seen: int = 0
    listings_dropped_wrong_set: int = 0
    listings_dropped_unknown_card: int = 0
    listings_in_stock: int = 0
    listings_sold_out: int = 0
    rows_written: int = 0
    cards_touched: set[str] = field(default_factory=set)
    cards_all_sold_out: set[str] = field(default_factory=set)
    _cards_ever_in_stock: set[str] = field(default_factory=set, repr=False)
    per_rarity_pages: Counter[str] = field(default_factory=Counter)
    per_rarity_rows: Counter[str] = field(default_factory=Counter)

    def summary(self) -> dict[str, object]:
        return {
            "set_code": self.set_code,
            "run_id": self.run_id,
            "pages_fetched": self.pages_fetched,
            "listings_seen": self.listings_seen,
            "listings_dropped_wrong_set": self.listings_dropped_wrong_set,
            "listings_dropped_unknown_card": self.listings_dropped_unknown_card,
            "listings_in_stock": self.listings_in_stock,
            "listings_sold_out": self.listings_sold_out,
            "rows_written": self.rows_written,
            "cards_touched": len(self.cards_touched),
            "cards_all_sold_out": len(self.cards_all_sold_out),
            "per_rarity_pages": dict(self.per_rarity_pages),
            "per_rarity_rows": dict(self.per_rarity_rows),
        }


# --- Catalog snapshot ---------------------------------------------------


async def _load_set(session: AsyncSession, set_code: str) -> Set | None:
    result = await session.execute(select(Set).where(Set.set_code == set_code.upper()))
    return result.scalar_one_or_none()


async def _load_card_index(session: AsyncSession, set_code: str) -> dict[tuple[str, str], str]:
    """Return ``{(local_id, variant): card_id}`` for tracked cards in a set."""
    stmt = (
        select(Card.card_id, Card.local_id, Card.variant)
        .where(Card.set_code == set_code.upper(), Card.is_tracked.is_(True))
        .order_by(Card.local_id, Card.variant)
    )
    result = await session.execute(stmt)
    return {(row.local_id, row.variant): row.card_id for row in result.all()}


async def _load_rarities(session: AsyncSession, set_code: str) -> list[str]:
    """Distinct non-null rarity codes present in the catalog for a set.

    Rarity lives on ``artworks`` now; join through tracked prints so we
    only crawl rarities that actually have a tracked variant.
    """
    from watari_core.models import Artwork

    stmt = (
        select(Artwork.rarity_code)
        .join(Card, Card.artwork_id == Artwork.artwork_id)
        .where(
            Card.set_code == set_code.upper(),
            Card.is_tracked.is_(True),
            Artwork.rarity_code.is_not(None),
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return sorted(r for (r,) in result.all() if r)


# --- Per-rarity crawl ---------------------------------------------------


async def _crawl_rarity(
    *,
    set_code: str,
    rarity_code: str,
    client: CardrushClient,
    card_index: dict[tuple[str, str], str],
    run_id: int,
    observed_at: datetime,
    max_pages: int,
    dry_run: bool,
    result: ScrapeSetResult,
) -> list[dict[str, object]]:
    keyword = f"{set_code} {rarity_code}"
    pages = await client.paginate(keyword, max_pages=max_pages)
    result.per_rarity_pages[rarity_code] = len(pages)
    result.pages_fetched += len(pages)

    price_rows: list[dict[str, object]] = []

    for page_num, _url, html in pages:
        if not dry_run:
            write_bronze_set(
                source=SOURCE,
                set_code=set_code,
                run_id=run_id,
                observed_at=observed_at,
                payload=html,
                key_suffix=f"{rarity_code}-p{page_num}.html",
            )

        listings = parse_listing_rows(html)
        result.listings_seen += len(listings)

        for listing in listings:
            card_id = _match_listing_to_card(
                listing,
                expected_set_code=set_code,
                card_index=card_index,
                result=result,
            )
            if card_id is None:
                continue
            price_rows.append(
                listing_row_to_price_point(
                    listing,
                    card_id=card_id,
                    scrape_run_id=run_id,
                    observed_at=observed_at,
                )
            )
            result.cards_touched.add(card_id)
            if listing.stock_qty > 0:
                result.listings_in_stock += 1
                result.cards_all_sold_out.discard(card_id)
                result._cards_ever_in_stock.add(card_id)
            else:
                result.listings_sold_out += 1
                if card_id not in result._cards_ever_in_stock:
                    result.cards_all_sold_out.add(card_id)

    result.per_rarity_rows[rarity_code] = len(price_rows)
    return price_rows


def _match_listing_to_card(
    listing: ListingRow,
    *,
    expected_set_code: str,
    card_index: dict[tuple[str, str], str],
    result: ScrapeSetResult,
) -> str | None:
    # Set disambiguation: drop listings whose name encodes a different set.
    if listing.set_code and listing.set_code.upper() != expected_set_code.upper():
        result.listings_dropped_wrong_set += 1
        return None
    if listing.local_id_padded is None:
        result.listings_dropped_unknown_card += 1
        return None

    key = (listing.local_id_padded, listing.variant)
    card_id = card_index.get(key)
    if card_id is None:
        # Fall back to variant='normal' if the exact variant isn't cataloged.
        card_id = card_index.get((listing.local_id_padded, "normal"))
    if card_id is None:
        result.listings_dropped_unknown_card += 1
        logger.debug(
            "unknown card: set=%s local=%s variant=%s name=%r",
            expected_set_code,
            listing.local_id_padded,
            listing.variant,
            listing.raw_name,
        )
    return card_id


# --- Top-level entrypoints ----------------------------------------------


async def scrape_set(
    set_code: str,
    *,
    rarities_filter: list[str] | None = None,
    max_pages: int = 30,
    dry_run: bool = False,
    impersonate: str = "chrome124",
) -> dict[str, object]:
    """Scrape a single set. Returns a summary dict."""
    set_code = set_code.upper()
    result = ScrapeSetResult(set_code=set_code)

    if not dry_run:
        ensure_bucket()

    async with async_session_factory() as session:
        set_row = await _load_set(session, set_code)
        if set_row is None:
            logger.error("set %s not found in catalog; run seed-sets first", set_code)
            return result.summary()

        card_index = await _load_card_index(session, set_code)
        if not card_index:
            logger.warning(
                "set %s has no tracked cards in catalog; run discover-cardrush first",
                set_code,
            )
            return result.summary()

        rarities = await _load_rarities(session, set_code)
        if rarities_filter:
            wanted = {r.upper() for r in rarities_filter}
            rarities = [r for r in rarities if r.upper() in wanted]
        if not rarities:
            logger.warning(
                "set %s has no rarities to crawl (catalog empty or filtered out)",
                set_code,
            )
            return result.summary()

        run_id: int | None = None
        if not dry_run:
            run_id = await start_scrape_run(
                session,
                source=SOURCE,
                metadata={
                    "set_code": set_code,
                    "rarities": rarities,
                    "max_pages": max_pages,
                },
            )
            result.run_id = run_id

        observed_at = datetime.now(UTC)
        status = "completed"
        error_summary: str | None = None

        try:
            async with CardrushClient(impersonate=impersonate) as client:
                for rarity in rarities:
                    logger.info("set=%s rarity=%s", set_code, rarity)
                    try:
                        price_rows = await _crawl_rarity(
                            set_code=set_code,
                            rarity_code=rarity,
                            client=client,
                            card_index=card_index,
                            run_id=run_id or 0,
                            observed_at=observed_at,
                            max_pages=max_pages,
                            dry_run=dry_run,
                            result=result,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.exception(
                            "crawl failed set=%s rarity=%s: %s",
                            set_code,
                            rarity,
                            exc,
                        )
                        await session.rollback()
                        continue

                    if dry_run or not price_rows:
                        continue

                    try:
                        inserted = await insert_price_points(session, price_rows)
                        result.rows_written += inserted
                    except Exception as exc:  # noqa: BLE001
                        await session.rollback()
                        logger.exception(
                            "insert_price_points failed set=%s rarity=%s: %s",
                            set_code,
                            rarity,
                            exc,
                        )
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error_summary = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if run_id is not None:
                try:
                    for card_id in result.cards_touched:
                        await upsert_card_state(session, card_id, SOURCE, success=True)
                except Exception:  # noqa: BLE001
                    await session.rollback()
                await finish_scrape_run(
                    session,
                    run_id=run_id,
                    status=status,
                    cards_attempted=len(card_index),
                    cards_succeeded=len(result.cards_touched),
                    rows_written=result.rows_written,
                    error_summary=error_summary,
                )

    # Writes are committed; refresh the read-side MVs in a fresh session.
    await refresh_price_mvs_if_needed(
        rows_written=result.rows_written,
        dry_run=dry_run,
    )

    return result.summary()


async def scrape_sets(
    set_codes: list[str],
    *,
    rarities_filter: list[str] | None = None,
    max_pages: int = 30,
    dry_run: bool = False,
    impersonate: str = "chrome124",
) -> list[dict[str, object]]:
    """Scrape many sets sequentially.

    Each set is isolated: an unhandled exception in one set is logged and
    counted but does not abort the remaining sets.
    """
    summaries: list[dict[str, object]] = []
    for code in set_codes:
        try:
            summary = await scrape_set(
                code,
                rarities_filter=rarities_filter,
                max_pages=max_pages,
                dry_run=dry_run,
                impersonate=impersonate,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("scrape_set failed for %s, continuing: %s", code, exc)
            summary = {"set_code": code.upper(), "error": f"{type(exc).__name__}: {exc}"}
        summaries.append(summary)
    return summaries


async def list_sets_for_era(era_block: str) -> list[str]:
    """Return set_codes belonging to an era block (e.g. 'sv', 'me')."""
    async with async_session_factory() as session:
        stmt = (
            select(Set.set_code)
            .where(func.lower(Set.era_block) == era_block.lower())
            .order_by(Set.set_code)
        )
        result = await session.execute(stmt)
        return [code for (code,) in result.all()]


async def list_all_sets() -> list[str]:
    async with async_session_factory() as session:
        stmt = select(Set.set_code).order_by(Set.set_code)
        result = await session.execute(stmt)
        return [code for (code,) in result.all()]
