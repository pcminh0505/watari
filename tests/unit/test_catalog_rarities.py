"""Unit tests for canonical rarity mapping."""

import pytest
from watari_catalog.rarities import (
    canonicalize_cardrush,
    canonicalize_pokellector,
    canonicalize_tcgdex,
)


class TestCardrush:
    def test_common(self):
        assert canonicalize_cardrush("C") == "C"

    def test_sar(self):
        assert canonicalize_cardrush("SAR") == "SAR"

    def test_ma(self):
        assert canonicalize_cardrush("MA") == "MA"

    def test_mur(self):
        assert canonicalize_cardrush("MUR") == "MUR"

    def test_shiny(self):
        assert canonicalize_cardrush("S") == "S"

    def test_lowercase_ok(self):
        assert canonicalize_cardrush("sar") == "SAR"

    def test_unknown_returns_none(self):
        assert canonicalize_cardrush("ZZZ") is None

    def test_empty_returns_none(self):
        assert canonicalize_cardrush("") is None
        assert canonicalize_cardrush(None) is None


class TestTcgdex:
    def test_common(self):
        assert canonicalize_tcgdex("Common") == "C"

    def test_double_rare(self):
        assert canonicalize_tcgdex("Double rare") == "RR"

    def test_sar(self):
        assert canonicalize_tcgdex("Special illustration rare") == "SAR"

    def test_unknown_returns_none(self):
        assert canonicalize_tcgdex("Future Rarity 9000") is None
        assert canonicalize_tcgdex(None) is None


class TestPokellector:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Common", "C"),
            ("Uncommon", "U"),
            ("Rare", "R"),
            ("Ultra Rare", "UR"),
            ("Super Rare", "SR"),
            ("Art Rare", "AR"),
            ("Special Art Rare", "SAR"),
            ("Hyper Rare", "HR"),
            # SM-era labels added in Pillar 1
            ("Secret Rare", "UR"),
            ("Prism Star", "SR"),
            # Shiny tier (baby shinies — SV4A, S4A)
            ("Shiny", "S"),
            ("Shiny Rare", "S"),
            # ME-era
            ("Master Ball Rare", "MA"),
            ("Masterball Rare", "MA"),
            # SV-era jp.pokellector.com labels
            ("Ace Spec", "R"),
            ("Super Secret Rare", "SAR"),
            ("B Double Rare", "RR"),
        ],
    )
    def test_known_labels(self, raw: str, expected: str) -> None:
        assert canonicalize_pokellector(raw) == expected

    def test_unknown_returns_none(self) -> None:
        assert canonicalize_pokellector("GoldenRareXX") is None

    def test_none_returns_none(self) -> None:
        assert canonicalize_pokellector(None) is None

    def test_strips_whitespace(self) -> None:
        assert canonicalize_pokellector("  Secret Rare  ") == "UR"
