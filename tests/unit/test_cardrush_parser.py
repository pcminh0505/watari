"""Unit tests for the curl_cffi-era Cardrush listing parser."""

from __future__ import annotations

from datetime import datetime, timezone

from pokeprice_cardrush.parser import (
    ListingRow,
    listing_row_to_price_point,
    parse_listing_rows,
)
from pokeprice_core.conditions import Condition
from pokeprice_core.models import SourceEnum, SourceTypeEnum

SAMPLE_HTML = """
<div class="item_data">
  <a href="/products/abc"><span class="goods_name">ポケモンカード sv2a 183/165 ミュウツー ex SAR</span></a>
  <span class="figure">￥12,800</span>
  <span class="stock">在庫3点</span>
</div>
<div class="item_data">
  <a href="https://www.cardrush-pokemon.jp/products/def"><span class="goods_name">ポケモンカード sv2a 183/165 〔状態A-〕 SAR</span></a>
  <span class="figure">¥10,000</span>
  <span class="stock">在庫1点</span>
</div>
<div class="item_data">
  <a href="/products/ghi"><span class="goods_name">ポケモンカード sv2a 183/165 〔状態B〕 SAR</span></a>
  <span class="figure">7,500円</span>
  <span class="stock soldout">売り切れ</span>
</div>
<div class="item_data">
  <a href="/products/jkl"><span class="goods_name">ポケモンカード sv2a 183/165 【PSA10】 SAR</span></a>
  <span class="figure">¥95,000</span>
  <span class="stock">在庫1点</span>
</div>
<div class="item_data">
  <a href="/products/mno"><span class="goods_name">ポケモンカード sv2a 183/165 〔状態Z〕 SAR</span></a>
  <span class="figure">¥5,000</span>
  <span class="stock">在庫1点</span>
</div>
<div class="item_data">
  <span class="goods_name">sealed SV2A special box</span>
  <span class="figure">¥0</span>
  <span class="stock">在庫1点</span>
</div>
<div class="item_data">
  <a href="/products/pqr"><span class="goods_name">ポケモンカード sv2a 025/165 ピカチュウ マスターボール柄 C</span></a>
  <span class="figure">¥3,000</span>
  <span class="stock">在庫5点</span>
</div>
"""


class TestParseListingRows:
    def test_produces_four_rows(self):
        # 3 valid SAR listings (A/A-/B) + 1 master-ball Pikachu.
        # Graded, unknown-condition, and no-price-no-local rows are dropped.
        rows = parse_listing_rows(SAMPLE_HTML)
        assert len(rows) == 4

    def test_set_and_local_id(self):
        rows = parse_listing_rows(SAMPLE_HTML)
        for r in rows[:3]:
            assert r.set_code == "sv2a"
            assert r.local_id_padded == "183"
        assert rows[3].local_id_padded == "025"

    def test_conditions(self):
        rows = parse_listing_rows(SAMPLE_HTML)
        assert [r.condition for r in rows[:3]] == [
            Condition.A,
            Condition.A_MINUS,
            Condition.B,
        ]

    def test_prices(self):
        rows = parse_listing_rows(SAMPLE_HTML)
        assert [r.price_jpy for r in rows[:3]] == [12800, 10000, 7500]

    def test_stock(self):
        rows = parse_listing_rows(SAMPLE_HTML)
        assert [r.stock_qty for r in rows[:3]] == [3, 1, 0]

    def test_rarity(self):
        rows = parse_listing_rows(SAMPLE_HTML)
        assert all(r.rarity_code == "SAR" for r in rows[:3])
        assert rows[3].rarity_code == "C"

    def test_variant_default_is_normal(self):
        rows = parse_listing_rows(SAMPLE_HTML)
        assert all(r.variant == "normal" for r in rows[:3])

    def test_variant_master_ball_mirror(self):
        rows = parse_listing_rows(SAMPLE_HTML)
        assert rows[3].variant == "master_ball_mirror"

    def test_external_url_absolute_or_prefixed(self):
        rows = parse_listing_rows(SAMPLE_HTML)
        assert rows[0].external_url == "https://www.cardrush-pokemon.jp/products/abc"
        assert rows[1].external_url == "https://www.cardrush-pokemon.jp/products/def"

    def test_empty_html(self):
        assert parse_listing_rows("") == []


class TestListingRowToPricePoint:
    def test_basic_mapping(self):
        row = ListingRow(
            raw_name="sv2a 183 SAR",
            set_code="sv2a",
            local_id_padded="183",
            variant="normal",
            rarity_code="SAR",
            condition=Condition.A,
            price_jpy=12800,
            stock_qty=3,
            external_url="https://example.test/x",
        )
        ts = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
        out = listing_row_to_price_point(
            row, card_id="jp-sv2a-183-normal", scrape_run_id=42, observed_at=ts
        )
        assert out["card_id"] == "jp-sv2a-183-normal"
        assert out["source"] == SourceEnum.cardrush
        assert out["source_type"] == SourceTypeEnum.listing
        assert out["condition"] == Condition.A
        assert out["price_jpy"] == 12800
        assert out["stock_qty"] == 3
        assert out["observed_at"] == ts
        assert out["external_url"] == "https://example.test/x"
        assert out["scrape_run_id"] == 42
