"""Unit tests for ``watari_catalog.tcgcollector_client`` parsers.

The HTTP client itself is exercised via integration tests / live scrapes
(it depends on Cloudflare-impersonating ``curl_cffi``). What we lock down
here is the pure HTML-parsing surface, which is the part that breaks when
TCGCollector tweaks their markup.

Fixtures are intentionally small, hand-written snippets that mirror the
exact structure observed on TCGCollector during the Phase-2 audit work
(set-index grid items + per-card detail page footer key-value rows).
"""

from __future__ import annotations

import pytest
from watari_catalog.tcgcollector_client import (
    parse_card_detail,
    parse_set_index,
)

# ---------------------------------------------------------------------------
# Set-index grid parser
# ---------------------------------------------------------------------------


SET_INDEX_FRAGMENT = """
<div id="card-image-grid">
  <div class="card-image-grid-item">
    <a class="card-image-grid-item-link"
       href="/cards/43384/oddish-shiny-treasure-ex-001-190"
       title="Oddish (Shiny Treasure ex 001/190)"></a>
  </div>
  <div class="card-image-grid-item">
    <a class="card-image-grid-item-link"
       href="/cards/43385/gloom-shiny-treasure-ex-002-190"
       title="Gloom (Shiny Treasure ex 002/190)"></a>
  </div>
  <div class="card-image-grid-item">
    <!-- Duplicate render of card 43384 (1st-edition + reprint).
         The parser must dedupe by card id. -->
    <a class="card-image-grid-item-link"
       href="/cards/43384/oddish-shiny-treasure-ex-001-190"
       title="Oddish (Shiny Treasure ex 001/190)"></a>
  </div>
  <div class="card-image-grid-item">
    <!-- Bogus link that doesn't match the canonical URL pattern.
         Should be ignored cleanly. -->
    <a class="card-image-grid-item-link"
       href="/some/other/page"
       title="Garbage"></a>
  </div>
</div>
"""


class TestParseSetIndex:
    def test_extracts_basic_fields(self) -> None:
        entries = parse_set_index(SET_INDEX_FRAGMENT)
        assert len(entries) == 2

        first, second = entries
        assert first.card_id == "43384"
        assert first.local_id == "001"
        assert first.set_total == "190"
        assert first.detail_path == "/cards/43384/oddish-shiny-treasure-ex-001-190"
        assert first.title == "Oddish (Shiny Treasure ex 001/190)"

        assert second.card_id == "43385"
        assert second.local_id == "002"
        assert second.set_total == "190"

    def test_dedupes_by_card_id(self) -> None:
        entries = parse_set_index(SET_INDEX_FRAGMENT)
        ids = [e.card_id for e in entries]
        assert ids == sorted(set(ids), key=ids.index)

    def test_skips_links_with_unrecognized_path(self) -> None:
        entries = parse_set_index(SET_INDEX_FRAGMENT)
        assert all(e.detail_path.startswith("/cards/") for e in entries)

    def test_empty_grid_returns_empty_list(self) -> None:
        assert parse_set_index("<html><body></body></html>") == []

    def test_pads_local_id_to_three_digits(self) -> None:
        html = """
        <div id="card-image-grid">
          <div class="card-image-grid-item">
            <a class="card-image-grid-item-link"
               href="/cards/99999/zacian-v-002-070"
               title="Zacian V (Sword 002/070)"></a>
          </div>
        </div>
        """
        entries = parse_set_index(html)
        assert len(entries) == 1
        assert entries[0].local_id == "002"
        assert entries[0].set_total == "070"


# ---------------------------------------------------------------------------
# Card-detail parser
# ---------------------------------------------------------------------------


def _detail_html(
    *,
    name_en: str,
    rarity: str | None,
    illustrator: str | None,
    card_number: str = "001/165",
    expansion: str = "Pokémon Card 151 SV2a",
) -> str:
    """Render a small fragment shaped like a TCGCollector detail page."""

    def _row(title: str, value: str) -> str:
        return f"""
        <div class="card-info-footer-item">
          <div class="card-info-footer-item-title">{title}</div>
          <div class="card-info-footer-item-text-container">{value}</div>
        </div>
        """

    rarity_value = rarity if rarity is not None else "—"
    illustrator_value = illustrator if illustrator is not None else "—"
    return f"""
    <html><body>
      <h1>{name_en}</h1>
      <section>
        {_row("Card number", card_number)}
        {_row("Expansion", expansion)}
        {_row("Rarity", rarity_value)}
        {_row("Illustrators", illustrator_value)}
      </section>
    </body></html>
    """


class TestParseCardDetail:
    def test_extracts_all_fields(self) -> None:
        html = _detail_html(
            name_en="Bulbasaur",
            rarity="Common (C)",
            illustrator="Yuu Nishida",
        )
        d = parse_card_detail(html, card_id="42000")
        assert d.card_id == "42000"
        assert d.name_en == "Bulbasaur"
        assert d.rarity_raw == "Common (C)"
        assert d.illustrator == "Yuu Nishida"
        assert d.card_number_raw == "001/165"
        assert d.expansion_raw == "Pokémon Card 151 SV2a"

    def test_em_dash_rarity_is_none(self) -> None:
        html = _detail_html(
            name_en="Trainer Promo",
            rarity=None,  # renders as the em-dash placeholder
            illustrator="kawayoo",
        )
        d = parse_card_detail(html, card_id="99")
        assert d.rarity_raw is None
        assert d.illustrator == "kawayoo"

    def test_em_dash_illustrator_is_none(self) -> None:
        html = _detail_html(
            name_en="Mystery Card",
            rarity="Special Art Rare (SAR)",
            illustrator=None,
        )
        d = parse_card_detail(html, card_id="100")
        assert d.illustrator is None
        assert d.rarity_raw == "Special Art Rare (SAR)"

    @pytest.mark.parametrize("placeholder", ["—", "-", "–", "  "])
    def test_assorted_placeholders_normalize_to_none(self, placeholder: str) -> None:
        html = _detail_html(
            name_en="Test",
            rarity=placeholder,
            illustrator=placeholder,
        )
        d = parse_card_detail(html, card_id="1")
        assert d.rarity_raw is None
        assert d.illustrator is None

    def test_missing_h1_yields_empty_name(self) -> None:
        html = """
        <html><body>
          <div class="card-info-footer-item">
            <div class="card-info-footer-item-title">Rarity</div>
            <div class="card-info-footer-item-text-container">Common (C)</div>
          </div>
        </body></html>
        """
        d = parse_card_detail(html, card_id="0")
        assert d.name_en == ""
        assert d.rarity_raw == "Common (C)"

    def test_unknown_footer_keys_dont_break_parser(self) -> None:
        html = """
        <html><body>
          <h1>Pikachu</h1>
          <div class="card-info-footer-item">
            <div class="card-info-footer-item-title">Some Future Field</div>
            <div class="card-info-footer-item-text-container">whatever</div>
          </div>
          <div class="card-info-footer-item">
            <div class="card-info-footer-item-title">Rarity</div>
            <div class="card-info-footer-item-text-container">Hyper Rare (HR)</div>
          </div>
        </body></html>
        """
        d = parse_card_detail(html, card_id="42")
        assert d.name_en == "Pikachu"
        assert d.rarity_raw == "Hyper Rare (HR)"
        assert d.illustrator is None
        assert d.card_number_raw == ""
        assert d.expansion_raw == ""
