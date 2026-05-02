"""Materialized-view refresh helpers.

The read API's ``/prices``, ``/spread``, and ``/market-price`` endpoints
serve from four materialized views over ``price_points``:

- ``mv_latest_price``          — latest obs per ``(card_id, source, condition)``
- ``mv_median_7d``             — 7-day median per ``(card_id, condition)``
- ``mv_cross_source_spread``   — cardrush floor vs SNKRDUNK 7-day median
- ``mv_market_price``          — unified best price per card (condition='A')

Each has a unique index, so ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` is
safe and preferable — it takes a ``SHARE UPDATE EXCLUSIVE`` lock only
(readers stay online). Migration 005 added the indexes on the first two;
migration 006 added it for ``mv_cross_source_spread``; migration 007 added
it for ``mv_market_price``.

Scrape orchestrators (cardrush/snkrdunk) call :func:`refresh_price_mvs`
after ``finish_scrape_run`` commits. ``mv_cross_source_spread`` depends on
both ``mv_latest_price`` and ``mv_median_7d`` so we refresh in that order.

``CONCURRENTLY`` cannot run inside a transaction block, so callers pass an
already-committed session (or a fresh one). The helper does not open a
transaction of its own beyond what SQLAlchemy's ``AUTOCOMMIT`` isolation
level gives us via :meth:`execution_options`.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

PRICE_MVS: tuple[str, ...] = (
    "mv_latest_price",
    "mv_median_7d",
    "mv_cross_source_spread",
    "mv_market_price",
)


async def refresh_price_mvs(
    session: AsyncSession,
    *,
    concurrently: bool = True,
) -> list[str]:
    """Refresh the four price MVs and return the list of names refreshed.

    Uses ``CONCURRENTLY`` by default so ongoing reads aren't blocked
    (each MV has a unique index per migrations 005, 006, and 007). We issue
    one ``REFRESH`` + ``COMMIT`` per view so locks are released between MVs
    and each downstream view reads the already-refreshed upstream views.

    Callers pass any open :class:`AsyncSession`; if the session has
    pending writes, they MUST be committed first — this helper does not
    inherit their uncommitted state.
    """
    suffix = "CONCURRENTLY " if concurrently else ""
    refreshed: list[str] = []
    for mv in PRICE_MVS:
        logger.info(
            "refreshing %s%s",
            "concurrently " if concurrently else "",
            mv,
        )
        await session.execute(text(f"REFRESH MATERIALIZED VIEW {suffix}{mv}"))
        await session.commit()
        refreshed.append(mv)
    return refreshed


async def refresh_price_mvs_if_needed(
    *,
    rows_written: int,
    dry_run: bool = False,
) -> list[str]:
    """Scraper-side post-commit hook: refresh the price MVs once a run ends.

    Opens its **own** short-lived session (CONCURRENTLY can't piggyback on
    an open transaction) so the caller doesn't have to juggle AUTOCOMMIT.
    Skips the refresh entirely when ``dry_run=True`` or ``rows_written==0``
    so that cheap repeat runs / empty sets don't lock-spin the MVs.

    Returns the list of MV names actually refreshed (empty if skipped).
    Errors are logged and swallowed — a failed refresh must never mask a
    successful scrape or abort the outer pipeline.
    """
    if dry_run or rows_written <= 0:
        return []

    # Local import to avoid circular imports (ingestion.py imports this
    # indirectly from scrapers, which import both in the same graph).
    from watari_core.db import async_session_factory

    try:
        async with async_session_factory() as session:
            return await refresh_price_mvs(session)
    except Exception:  # noqa: BLE001 — don't let refresh failures propagate
        logger.exception("refresh_price_mvs failed; continuing")
        return []
