"""Unit tests for the curl_cffi-era Cardrush listing parser."""

from __future__ import annotations

from datetime import UTC, datetime

from watari_cardrush.parser import (
    GradedListingRow,
    ListingRow,
    graded_listing_row_to_graded_price_point,
    listing_row_to_price_point,
    parse_listing_rows,
)
from watari_core.conditions import Condition
from watari_core.models import SourceEnum, SourceTypeEnum

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
    def test_produces_four_ungraded_rows(self):
        # 3 valid SAR listings (A/A-/B) + 1 master-ball Pikachu = 4 ungraded.
        # Unknown-condition and no-price-no-local rows are dropped.
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        assert len(rows) == 4

    def test_produces_one_graded_row(self):
        # PSA10 listing captured as graded, not dropped.
        _, graded_rows = parse_listing_rows(SAMPLE_HTML)
        assert len(graded_rows) == 1

    def test_set_and_local_id(self):
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        for r in rows[:3]:
            assert r.set_code == "sv2a"
            assert r.local_id_padded == "183"
        assert rows[3].local_id_padded == "025"

    def test_conditions(self):
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        assert [r.condition for r in rows[:3]] == [
            Condition.A,
            Condition.A_MINUS,
            Condition.B,
        ]

    def test_prices(self):
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        assert [r.price_jpy for r in rows[:3]] == [12800, 10000, 7500]

    def test_stock(self):
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        assert [r.stock_qty for r in rows[:3]] == [3, 1, 0]

    def test_rarity(self):
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        assert all(r.rarity_code == "SAR" for r in rows[:3])
        assert rows[3].rarity_code == "C"

    def test_variant_default_is_normal(self):
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        assert all(r.variant == "normal" for r in rows[:3])

    def test_variant_master_ball_mirror(self):
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        assert rows[3].variant == "master_ball_mirror"

    def test_external_url_absolute_or_prefixed(self):
        rows, _ = parse_listing_rows(SAMPLE_HTML)
        assert rows[0].external_url == "https://www.cardrush-pokemon.jp/products/abc"
        assert rows[1].external_url == "https://www.cardrush-pokemon.jp/products/def"

    def test_empty_html(self):
        rows, graded_rows = parse_listing_rows("")
        assert rows == []
        assert graded_rows == []

    def test_graded_row_fields(self):
        _, graded_rows = parse_listing_rows(SAMPLE_HTML)
        g = graded_rows[0]
        assert g.grade_company == "PSA"
        assert g.grade_score == 10.0
        assert g.price_jpy == 95000
        assert g.stock_qty == 1
        assert g.local_id_padded == "183"
        assert g.external_url == "https://www.cardrush-pokemon.jp/products/jkl"


class TestGradedListingRowToPricePoint:
    def test_basic_mapping(self):
        row = GradedListingRow(
            raw_name="sv2a 183 【PSA10】 SAR",
            set_code="sv2a",
            local_id_padded="183",
            variant="normal",
            name_ja=None,
            grade_company="PSA",
            grade_score=10.0,
            price_jpy=95000,
            stock_qty=1,
            external_url="https://example.test/psa",
        )
        ts = datetime(2026, 5, 7, 12, 0, tzinfo=UTC)
        out = graded_listing_row_to_graded_price_point(
            row, card_id="jp-sv2a-183-normal", scrape_run_id=99, observed_at=ts
        )
        assert out["card_id"] == "jp-sv2a-183-normal"
        assert out["source"] == SourceEnum.cardrush.value
        assert out["source_type"] == SourceTypeEnum.listing.value
        assert out["grade_company"] == "PSA"
        assert out["grade_score"] == 10.0
        assert out["price_jpy"] == 95000
        assert out["stock_qty"] == 1
        assert out["observed_at"] == ts
        assert out["external_url"] == "https://example.test/psa"
        assert out["scrape_run_id"] == 99


class TestListingRowToPricePoint:
    def test_basic_mapping(self):
        row = ListingRow(
            raw_name="sv2a 183 SAR",
            set_code="sv2a",
            local_id_padded="183",
            variant="normal",
            rarity_code="SAR",
            name_ja=None,
            condition=Condition.A,
            price_jpy=12800,
            stock_qty=3,
            external_url="https://example.test/x",
        )
        ts = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
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


# -- Disambiguation tests ----------------------------------------------------

from watari_cardrush.run import (
    ScrapeSetResult,
    _CARDRUSH_BASE_ALIAS,
    _match_listing_to_card,
    _name_matches,
    _normalize_name,
)


class TestNameMatching:
    """Test the name normalization and matching helpers."""

    def test_exact_match(self):
        assert _name_matches("ロゼリア", "ロゼリア")

    def test_substring_listing_longer(self):
        assert _name_matches("フシギダネ(ミラー/ハイクラスパック仕様)", "フシギダネ")

    def test_substring_catalog_longer(self):
        assert _name_matches("ロゼリア", "ロゼリアGX")

    def test_fullwidth_normalization(self):
        assert _name_matches("ザシアンＶ", "ザシアンV")

    def test_no_match(self):
        assert not _name_matches("ロゼリア", "ウッウ")

    def test_none_listing(self):
        assert not _name_matches(None, "ロゼリア")

    def test_none_catalog(self):
        assert not _name_matches("ロゼリア", None)

    def test_normalize_strips_parens(self):
        assert _normalize_name("フシギダネ(ミラー)") == "フシギダネ"
        assert _normalize_name("ピカチュウ（特別仕様）") == "ピカチュウ"


class TestMatchListingAlias:
    """Test _match_listing_to_card with alias disambiguation."""

    def _listing(self, *, set_code="s1", local_id="001", name_ja="ロゼリア"):
        return ListingRow(
            raw_name=f"s1 001/060 C {name_ja or ''}",
            set_code=set_code,
            local_id_padded=local_id,
            variant="normal",
            rarity_code="C",
            name_ja=name_ja,
            condition=Condition.A,
            price_jpy=100,
            stock_qty=1,
            external_url=None,
        )

    def _card_index(self):
        return {("001", "normal"): "jp-s1w-001-normal"}

    def _name_index(self):
        return {"001": "ロゼリア"}

    def test_exact_match_no_alias(self):
        """Listing set_code matches expected exactly → accept."""
        listing = self._listing(set_code="s1w")
        result = ScrapeSetResult(set_code="S1W")
        card_id = _match_listing_to_card(
            listing,
            expected_set_code="S1W",
            card_index=self._card_index(),
            name_index={},
            result=result,
        )
        assert card_id == "jp-s1w-001-normal"

    def test_alias_match_name_matches(self):
        """Listing has base code 's1', name matches S1W card → accept."""
        listing = self._listing(set_code="s1", name_ja="ロゼリア")
        result = ScrapeSetResult(set_code="S1W")
        card_id = _match_listing_to_card(
            listing,
            expected_set_code="S1W",
            card_index=self._card_index(),
            name_index=self._name_index(),
            result=result,
        )
        assert card_id == "jp-s1w-001-normal"
        assert result.listings_dropped_wrong_set == 0

    def test_alias_match_name_mismatch_drops(self):
        """Listing has base code 's1', name doesn't match → drop (wrong sibling set)."""
        listing = self._listing(set_code="s1", name_ja="ウッウ")
        result = ScrapeSetResult(set_code="S1W")
        card_id = _match_listing_to_card(
            listing,
            expected_set_code="S1W",
            card_index=self._card_index(),
            name_index=self._name_index(),
            result=result,
        )
        assert card_id is None
        assert result.listings_dropped_wrong_set == 1

    def test_alias_match_no_name_accepts(self):
        """Listing has base code but no name_ja → accept (fallback)."""
        listing = self._listing(set_code="s1", name_ja=None)
        result = ScrapeSetResult(set_code="S1W")
        card_id = _match_listing_to_card(
            listing,
            expected_set_code="S1W",
            card_index=self._card_index(),
            name_index=self._name_index(),
            result=result,
        )
        assert card_id == "jp-s1w-001-normal"

    def test_unrelated_set_drops(self):
        """Listing from a totally different set → drop."""
        listing = self._listing(set_code="sv2a")
        result = ScrapeSetResult(set_code="S1W")
        card_id = _match_listing_to_card(
            listing,
            expected_set_code="S1W",
            card_index=self._card_index(),
            name_index=self._name_index(),
            result=result,
        )
        assert card_id is None
        assert result.listings_dropped_wrong_set == 1

    def test_no_alias_for_sv_set(self):
        """SV-era sets have no alias entries → different set code drops."""
        listing = self._listing(set_code="sv2")
        result = ScrapeSetResult(set_code="SV2A")
        card_id = _match_listing_to_card(
            listing,
            expected_set_code="SV2A",
            card_index={("001", "normal"): "jp-sv2a-001-normal"},
            name_index={},
            result=result,
        )
        assert card_id is None

    def test_alias_map_has_expected_entries(self):
        """Verify the alias map covers the known problematic sets."""
        assert _CARDRUSH_BASE_ALIAS["S1W"] == "S1"
        assert _CARDRUSH_BASE_ALIAS["S1H"] == "S1"
        assert _CARDRUSH_BASE_ALIAS["SM1S"] == "SM1"
        assert _CARDRUSH_BASE_ALIAS["SM1M"] == "SM1"
        assert _CARDRUSH_BASE_ALIAS["SM3P"] == "SM3"
