"""Parse Cardrush product-list HTML into typed listing rows.

Reuses:
- ``watari_core.conditions.parse_cardrush_condition`` for the
  ``〔状態X〕`` prefix and graded-listing rejection.
- ``watari_catalog.parser.parse_cardrush_product_name`` for the
  (set_code / local_id / variant / rarity) grammar, so the scraper and
  catalog speak the same language.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from bs4 import BeautifulSoup
from watari_catalog.parser import parse_cardrush_product_name
from watari_core.catalog import pad_local_id
from watari_core.conditions import Condition, parse_cardrush_condition
from watari_core.models import SourceEnum, SourceTypeEnum

BASE_URL = "https://www.cardrush-pokemon.jp"


@dataclass(frozen=True)
class ListingRow:
    """Typed, fully-parsed Cardrush listing row."""

    raw_name: str
    set_code: str | None
    local_id_padded: str | None
    variant: str
    rarity_code: str | None
    condition: Condition
    price_jpy: int
    stock_qty: int
    external_url: str | None


def _extract_price(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _extract_stock_qty(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def parse_listing_rows(html: str) -> list[ListingRow]:
    """Extract ``ListingRow`` objects from a Cardrush search-results page.

    Listings are dropped (not raised) when:
        - no product-name element,
        - graded (PSA/BGS/CGC/SGC) — not supported by ``price_points`` enums,
        - unrecognized condition tag,
        - no price or price <= 0,
        - no parseable local_id (can't match back to catalog).
    """
    soup = BeautifulSoup(html, "lxml")
    rows: list[ListingRow] = []

    for item in soup.select(".item_data"):
        name_el = item.select_one(".goods_name")
        if not name_el:
            continue
        raw_name = name_el.get_text(strip=True)

        condition, is_graded = parse_cardrush_condition(raw_name)
        if is_graded or condition is None:
            continue

        price_el = item.select_one(".figure") or item.select_one(".selling_price")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = _extract_price(price_text)
        if price is None or price <= 0:
            continue

        stock_el = item.select_one(".stock")
        if stock_el is None:
            stock_qty = 0
        else:
            classes: list[str] = stock_el.get_attribute_list("class")
            if "soldout" in classes:
                stock_qty = 0
            else:
                stock_qty = _extract_stock_qty(stock_el.get_text(strip=True))

        external_url: str | None = None
        link_el = item.select_one("a[href]")
        if link_el is not None:
            href = cast(str, link_el.get("href") or "")
            if href.startswith("http"):
                external_url = href
            elif href:
                external_url = f"{BASE_URL}{href}"

        parsed = parse_cardrush_product_name(raw_name)
        if parsed.local_id is None:
            continue

        rows.append(
            ListingRow(
                raw_name=raw_name,
                set_code=parsed.set_code,
                local_id_padded=pad_local_id(parsed.local_id),
                variant=parsed.variant,
                rarity_code=parsed.rarity_code,
                condition=condition,
                price_jpy=price,
                stock_qty=stock_qty,
                external_url=external_url,
            )
        )

    return rows


def listing_row_to_price_point(
    row: ListingRow,
    *,
    card_id: str,
    scrape_run_id: int,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    """Convert a ``ListingRow`` (+ resolved ``card_id``) into a PricePoint dict."""
    ts = observed_at or datetime.now(UTC)
    return {
        "card_id": card_id,
        "source": SourceEnum.cardrush,
        "source_type": SourceTypeEnum.listing,
        "condition": row.condition,
        "price_jpy": row.price_jpy,
        "stock_qty": row.stock_qty,
        "observed_at": ts,
        "external_url": row.external_url,
        "scrape_run_id": scrape_run_id,
    }
