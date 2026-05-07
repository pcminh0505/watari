"""Parse Cardrush product-list HTML into typed listing rows.

Reuses:
- ``watari_core.conditions.parse_cardrush_condition`` for the
  ``〔状態X〕`` prefix and graded-listing detection.
- ``watari_core.conditions.extract_cardrush_grade`` / ``parse_grade_company_score``
  for capturing PSA/BGS/CGC slab listings into ``GradedListingRow``.
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
from watari_core.conditions import (
    Condition,
    extract_cardrush_grade,
    parse_cardrush_condition,
    parse_grade_company_score,
)
from watari_core.models import SourceEnum, SourceTypeEnum

BASE_URL = "https://www.cardrush-pokemon.jp"


@dataclass(frozen=True)
class ListingRow:
    """Typed, fully-parsed Cardrush listing row (ungraded)."""

    raw_name: str
    set_code: str | None
    local_id_padded: str | None
    variant: str
    rarity_code: str | None
    name_ja: str | None
    condition: Condition
    price_jpy: int
    stock_qty: int
    external_url: str | None


@dataclass(frozen=True)
class GradedListingRow:
    """Typed Cardrush listing row for PSA/BGS/CGC certified slabs."""

    raw_name: str
    set_code: str | None
    local_id_padded: str | None
    variant: str
    name_ja: str | None
    grade_company: str  # GradeCompany.value, e.g. "PSA"
    grade_score: float  # e.g. 10.0, 9.5
    price_jpy: int
    stock_qty: int
    external_url: str | None


def _extract_price(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _extract_stock_qty(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def _extract_url(item: object) -> str | None:
    link_el = item.select_one("a[href]")  # type: ignore[union-attr]
    if link_el is None:
        return None
    href = cast(str, link_el.get("href") or "")
    if href.startswith("http"):
        return href
    if href:
        return f"{BASE_URL}{href}"
    return None


def parse_listing_rows(
    html: str,
) -> tuple[list[ListingRow], list[GradedListingRow]]:
    """Extract listing rows from a Cardrush search-results page.

    Returns ``(ungraded_rows, graded_rows)``.

    Ungraded rows are dropped when:
        - no product-name element,
        - unrecognized condition tag,
        - no price or price <= 0,
        - no parseable local_id.

    Graded rows (PSA/BGS/CGC) are captured when:
        - the grade string parses to a known company + score,
        - the price is valid,
        - the product name yields a local_id.

    SGC listings are detected (not misclassified as ungraded) but not stored
    because ``GradeCompany`` excludes SGC (deferred).
    """
    soup = BeautifulSoup(html, "lxml")
    rows: list[ListingRow] = []
    graded_rows: list[GradedListingRow] = []

    for item in soup.select(".item_data"):
        name_el = item.select_one(".goods_name")
        if not name_el:
            continue
        raw_name = name_el.get_text(strip=True)

        condition, is_graded = parse_cardrush_condition(raw_name)

        # Extract price, stock, URL — shared by both graded and ungraded paths.
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

        external_url = _extract_url(item)

        parsed = parse_cardrush_product_name(raw_name)
        if parsed.local_id is None:
            continue

        if is_graded:
            grade_str = extract_cardrush_grade(raw_name)
            if grade_str:
                grade_parsed = parse_grade_company_score(grade_str)
                if grade_parsed:
                    company, score = grade_parsed
                    graded_rows.append(
                        GradedListingRow(
                            raw_name=raw_name,
                            set_code=parsed.set_code,
                            local_id_padded=pad_local_id(parsed.local_id),
                            variant=parsed.variant,
                            name_ja=parsed.name_ja,
                            grade_company=company.value,
                            grade_score=score,
                            price_jpy=price,
                            stock_qty=stock_qty,
                            external_url=external_url,
                        )
                    )
            continue

        if condition is None:
            continue

        rows.append(
            ListingRow(
                raw_name=raw_name,
                set_code=parsed.set_code,
                local_id_padded=pad_local_id(parsed.local_id),
                variant=parsed.variant,
                rarity_code=parsed.rarity_code,
                name_ja=parsed.name_ja,
                condition=condition,
                price_jpy=price,
                stock_qty=stock_qty,
                external_url=external_url,
            )
        )

    return rows, graded_rows


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


def graded_listing_row_to_graded_price_point(
    row: GradedListingRow,
    *,
    card_id: str,
    scrape_run_id: int,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    """Convert a ``GradedListingRow`` (+ resolved ``card_id``) into a
    graded_price_points dict."""
    ts = observed_at or datetime.now(UTC)
    return {
        "card_id": card_id,
        "source": SourceEnum.cardrush.value,
        "source_type": SourceTypeEnum.listing.value,
        "grade_company": row.grade_company,
        "grade_score": row.grade_score,
        "price_jpy": row.price_jpy,
        "stock_qty": row.stock_qty,
        "observed_at": ts,
        "external_url": row.external_url,
        "scrape_run_id": scrape_run_id,
    }
