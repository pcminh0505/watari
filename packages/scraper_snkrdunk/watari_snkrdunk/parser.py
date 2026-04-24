"""Translate SNKRDUNK sales-history JSON into `price_points` rows.

Produces dicts ready to pass to `insert_price_points()`. Any entries whose
condition string maps to `None` (unknown grade) are silently dropped —
strict mapping is S/A → A, B → B, C → C per §D of the plan.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from watari_core.conditions import parse_snkrdunk_condition
from watari_core.models import SourceEnum, SourceTypeEnum

from watari_snkrdunk.dates import parse_snkrdunk_date


def parse_sales_history(
    entries: list[dict[str, Any]],
    *,
    card_id: str,
    apparel_id: int,
    scrape_run_id: int | None,
    reference_now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Map a list of history entries to PricePoint kwargs dicts."""
    rows: list[dict[str, Any]] = []
    external_url = f"https://snkrdunk.com/apparels/{apparel_id}"

    for entry in entries:
        raw_cond = entry.get("condition")
        if not isinstance(raw_cond, str):
            continue
        condition = parse_snkrdunk_condition(raw_cond)
        if condition is None:
            continue

        price = entry.get("price")
        if not isinstance(price, int) or price <= 0:
            continue

        date_str = entry.get("date")
        if not isinstance(date_str, str):
            continue
        observed_at = parse_snkrdunk_date(date_str, now=reference_now)

        rows.append(
            {
                "card_id": card_id,
                "source": SourceEnum.snkrdunk,
                "source_type": SourceTypeEnum.sold,
                "condition": condition,
                "price_jpy": int(price),
                "stock_qty": None,
                "observed_at": observed_at,
                "external_url": external_url,
                "scrape_run_id": scrape_run_id,
            }
        )

    return rows
