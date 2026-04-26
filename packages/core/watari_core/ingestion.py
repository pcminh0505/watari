"""Shared ingestion primitives used by every scraper.

Each scraper follows the same skeleton:

    run_id = await start_scrape_run(session, source)
    try:
        for card in batch:
            raw = await fetch(card)
            bronze_key = write_bronze(source, card_id, run_id, observed_at, raw)
            rows = parse(raw, run_id=run_id, ...)
            inserted = await insert_price_points(session, rows)
            await upsert_card_state(session, card_id, source, success=True)
        await finish_scrape_run(session, run_id, "completed", counts)
    except Exception as exc:
        await finish_scrape_run(session, run_id, "failed", counts, str(exc))
        raise
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from watari_core.models import CardScrapeState, PricePoint, ScrapeRun


async def start_scrape_run(
    session: AsyncSession,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert a new scrape_runs row in status='running' and return its id."""
    stmt = (
        pg_insert(ScrapeRun)
        .values(source=source, status="running", metadata_=metadata)
        .returning(ScrapeRun.id)
    )
    result = await session.execute(stmt)
    run_id = int(result.scalar_one())
    await session.commit()
    return run_id


async def finish_scrape_run(
    session: AsyncSession,
    run_id: int,
    status: str,
    cards_attempted: int,
    cards_succeeded: int,
    rows_written: int,
    error_summary: str | None = None,
) -> None:
    """Mark a ScrapeRun as completed/failed and record counters."""
    stmt = (
        update(ScrapeRun)
        .where(ScrapeRun.id == run_id)
        .values(
            status=status,
            finished_at=datetime.now(UTC),
            cards_attempted=cards_attempted,
            cards_succeeded=cards_succeeded,
            rows_written=rows_written,
            error_summary=error_summary,
        )
    )
    await session.execute(stmt)
    await session.commit()


async def insert_price_points(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    chunk_size: int = 1000,
) -> int:
    """Append-only insert of price points with ON CONFLICT DO NOTHING.

    Returns the number of rows that actually landed (duplicates suppressed by
    the `uq_price_points_idem` unique index are counted as 0).

    Rows are inserted in chunks of `chunk_size` to stay under asyncpg's 32767
    query-parameter limit. At 9 columns per row, 1000 rows = 9000 params —
    safely below the limit even for the most popular cards.
    """
    if not rows:
        return 0
    inserted = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        stmt = pg_insert(PricePoint).values(chunk).on_conflict_do_nothing()
        result = await session.execute(stmt)
        await session.commit()
        inserted += int(result.rowcount or 0)  # type: ignore[attr-defined]
    return inserted


async def upsert_card_state(
    session: AsyncSession,
    card_id: str,
    source: str,
    *,
    success: bool,
    error: str | None = None,
) -> None:
    """Update (or create) the per-(card, source) health row."""
    now = datetime.now(UTC)
    base = {
        "card_id": card_id,
        "source": source,
        "last_attempt_at": now,
    }
    if success:
        base["last_success_at"] = now
        base["last_error"] = None
        base["consecutive_failures"] = 0
    else:
        base["last_error"] = error

    stmt = pg_insert(CardScrapeState).values(**base)
    if success:
        update_set = {
            "last_attempt_at": stmt.excluded.last_attempt_at,
            "last_success_at": stmt.excluded.last_success_at,
            "last_error": stmt.excluded.last_error,
            "consecutive_failures": 0,
        }
    else:
        update_set = {
            "last_attempt_at": stmt.excluded.last_attempt_at,
            "last_error": stmt.excluded.last_error,
            "consecutive_failures": CardScrapeState.consecutive_failures + 1,
        }
    stmt = stmt.on_conflict_do_update(
        index_elements=["card_id", "source"], set_=update_set
    )
    await session.execute(stmt)
    await session.commit()


async def fetch_tracked_cards(
    session: AsyncSession,
    set_code: str,
) -> list[dict[str, Any]]:
    """Return per-print metadata for all tracked prints in a set.

    Result keys:
        ``card_id``, ``set_code``, ``local_id``, ``variant``,
        ``artwork_id``, ``rarity_code`` (from artwork), ``name_ja`` (from artwork).

    Matches ``set_code`` case-insensitively.
    """
    from watari_core.models import Artwork, Card

    stmt = (
        select(
            Card.card_id,
            Card.set_code,
            Card.local_id,
            Card.variant,
            Card.artwork_id,
            Artwork.rarity_code,
            Artwork.name_ja,
        )
        .join(Artwork, Card.artwork_id == Artwork.artwork_id)
        .where(
            func.upper(Card.set_code) == set_code.upper(),
            Card.is_tracked.is_(True),
        )
        .order_by(Card.local_id, Card.variant)
    )
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.all()]
