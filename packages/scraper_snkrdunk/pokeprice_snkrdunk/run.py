"""SNKRDUNK scrape orchestrator.

Workflow per card:
    1. resolve apparel_id via product number
    2. page through sales-history
    3. write each API page to MinIO bronze
    4. parse -> insert into price_points (ON CONFLICT DO NOTHING)
    5. upsert card_scrape_state

The ScrapeRun row is finalized with aggregate counts once all cards are done.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from pokeprice_core.bronze import ensure_bucket, write_bronze
from pokeprice_core.db import async_session_factory
from pokeprice_core.ingestion import (
    fetch_tracked_cards,
    finish_scrape_run,
    insert_price_points,
    start_scrape_run,
    upsert_card_state,
)
from pokeprice_core.models import SourceEnum

from pokeprice_snkrdunk.client import SnkrdunkClient
from pokeprice_snkrdunk.parser import parse_sales_history

SOURCE = SourceEnum.snkrdunk.value


async def scrape_era(
    era: str,
    *,
    history_limit: int | None = None,
    polite_delay_sec: float = 0.25,
) -> dict[str, int]:
    """Scrape every tracked card in `era` from SNKRDUNK.

    Returns a counters dict: cards_attempted, cards_succeeded, rows_written,
    cards_not_found.
    """
    ensure_bucket()

    async with async_session_factory() as session:
        cards = await fetch_tracked_cards(session, era)
        if not cards:
            print(f"[snkrdunk] no tracked cards in era={era!r}")
            return {"cards_attempted": 0, "cards_succeeded": 0, "rows_written": 0,
                    "cards_not_found": 0}

        run_id = await start_scrape_run(
            session,
            source=SOURCE,
            metadata={"era": era, "history_limit": history_limit},
        )
        print(f"[snkrdunk] run_id={run_id} era={era} cards={len(cards)}")

        attempted = succeeded = rows_written = not_found = 0
        status = "completed"
        error_summary: str | None = None

        try:
            async with SnkrdunkClient(polite_delay_sec=polite_delay_sec) as client:
                for card in cards:
                    attempted += 1
                    card_id = card["card_id"]
                    local_id = card["local_id"]
                    try:
                        apparel = await client.resolve_apparel(era, local_id)
                        if apparel is None:
                            not_found += 1
                            await upsert_card_state(
                                session, card_id, SOURCE,
                                success=False, error="not found on SNKRDUNK",
                            )
                            print(f"  [{attempted:3}/{len(cards)}] {card_id}: not found")
                            continue

                        entries, raw_pages = await client.fetch_sales_history(
                            apparel["apparel_id"], limit=history_limit,
                        )
                        observed_at = datetime.now(timezone.utc)
                        for i, raw in enumerate(raw_pages, start=1):
                            write_bronze(
                                source=SOURCE,
                                card_id=card_id,
                                run_id=run_id,
                                observed_at=observed_at,
                                payload=raw,
                                key_suffix=f"sales-p{i}.json",
                            )

                        rows = parse_sales_history(
                            entries,
                            card_id=card_id,
                            apparel_id=apparel["apparel_id"],
                            scrape_run_id=run_id,
                            reference_now=observed_at,
                        )
                        inserted = await insert_price_points(session, rows)
                        rows_written += inserted
                        succeeded += 1

                        await upsert_card_state(session, card_id, SOURCE, success=True)
                        print(
                            f"  [{attempted:3}/{len(cards)}] {card_id}: "
                            f"{len(entries)} sales -> {inserted} new rows"
                        )
                    except Exception as exc:  # noqa: BLE001 - log & keep going
                        await session.rollback()
                        try:
                            await upsert_card_state(
                                session, card_id, SOURCE,
                                success=False, error=str(exc),
                            )
                        except Exception:  # noqa: BLE001
                            await session.rollback()
                        print(f"  [{attempted:3}/{len(cards)}] {card_id}: ERROR {exc!r}")
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error_summary = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            await finish_scrape_run(
                session,
                run_id=run_id,
                status=status,
                cards_attempted=attempted,
                cards_succeeded=succeeded,
                rows_written=rows_written,
                error_summary=error_summary,
            )

        print(
            f"[snkrdunk] done. attempted={attempted} succeeded={succeeded} "
            f"not_found={not_found} rows_written={rows_written}"
        )
        return {
            "cards_attempted": attempted,
            "cards_succeeded": succeeded,
            "rows_written": rows_written,
            "cards_not_found": not_found,
        }


def _run(era: str, history_limit: int | None) -> dict[str, int]:
    return asyncio.run(scrape_era(era, history_limit=history_limit))
