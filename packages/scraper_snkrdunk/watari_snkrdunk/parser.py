"""Translate SNKRDUNK sales-history JSON into price_points / graded_price_points rows.

SNKRDUNK embeds graded (PSA/BGS/CGC) sold comps directly in the same
sales-history feed as ungraded entries — the ``condition`` field carries
the grade string (e.g. ``"PSA10"``, ``"BGS9.5"``) instead of the usual
``"S"``/``"A"``/``"B"``/``"C"`` codes.

``parse_sales_history`` now returns ``(ungraded_rows, graded_rows)``:
- ``ungraded_rows``: dicts for ``insert_price_points`` (unchanged shape)
- ``graded_rows``:  dicts for ``upsert_graded_price_points``

Entries whose condition string is neither a known raw condition nor a
parseable grade string (e.g. ``"PSA8以下"``, ``"BGS10 BL"``, ``"D"``) are
silently dropped — the same policy as before.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from watari_core.conditions import parse_grade_company_score, parse_snkrdunk_condition
from watari_core.models import SourceEnum, SourceTypeEnum

from watari_snkrdunk.dates import parse_snkrdunk_date


def parse_sales_history(
    entries: list[dict[str, Any]],
    *,
    card_id: str,
    apparel_id: int,
    scrape_run_id: int | None,
    reference_now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map sales-history entries to ``(ungraded_rows, graded_rows)``.

    Graded entries (``"PSA10"``, ``"BGS9.5"``, etc.) are routed to
    ``graded_rows``; standard condition codes (``"S"``/``"A"``/``"B"``/``"C"``)
    go to ``ungraded_rows``.  Ambiguous strings (``"PSA8以下"``,
    ``"BGS10 BL"``) are dropped.
    """
    rows: list[dict[str, Any]] = []
    graded_rows: list[dict[str, Any]] = []
    external_url = f"https://snkrdunk.com/apparels/{apparel_id}"

    for entry in entries:
        raw_cond = entry.get("condition")
        if not isinstance(raw_cond, str):
            continue

        price = entry.get("price")
        if not isinstance(price, int) or price <= 0:
            continue

        date_str = entry.get("date")
        if not isinstance(date_str, str):
            continue
        observed_at = parse_snkrdunk_date(date_str, now=reference_now)

        condition = parse_snkrdunk_condition(raw_cond)
        if condition is not None:
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
            continue

        # Not a raw condition — try as a graded entry.
        grade_parsed = parse_grade_company_score(raw_cond.strip())
        if grade_parsed is None:
            # Ambiguous (e.g. "PSA8以下", "BGS10 BL", "D") — drop.
            continue
        company, score = grade_parsed
        graded_rows.append(
            {
                "card_id": card_id,
                "source": SourceEnum.snkrdunk.value,
                "source_type": SourceTypeEnum.sold.value,
                "grade_company": company.value,
                "grade_score": score,
                "price_jpy": int(price),
                "stock_qty": None,
                "observed_at": observed_at,
                "external_url": external_url,
                "scrape_run_id": scrape_run_id,
            }
        )

    return rows, graded_rows
